"""Synthetic original uploads across version, access, purge, and restore boundaries."""
import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

from app.learning_domain import DomainError
from app.learning_production import (
    ProductionLearningDatabaseError,
    create_learning_backup,
    restore_learning_backup,
    upgrade_learning_database,
)
from app.config import Settings
from app.db import Database
from app.managed_purge import ManagedPurge
from app.materials import MaterialService
from app.question_discussion import QuestionDiscussionService
from app.purge_storage import receipt_path, write_json
from test_ai_conversations import authorize, create_task, make_client, start_conversation
from test_learning_domain_schema import learning_database  # noqa: F401
from test_task_materials import material_service  # noqa: F401
from test_verification_review import attempt
from test_learning_verifications import IDENTITY


def _business_rows(connection):
    tables = [row[0] for row in connection.execute('''SELECT name FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name <> 'schema_migrations'
        ORDER BY name''')]
    return {table: [tuple(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY rowid')]
            for table in tables}


def test_upgrade_035_to_current_preserves_every_old_business_table(tmp_path):
    path = tmp_path / 'learning.sqlite3'
    database = Database(path, Settings.from_env().migrations_dir,
                        migration_floor=11, migration_ceiling=35)
    with database.transaction() as connection:
        connection.execute('''INSERT INTO learning_task_material
            (id,material_id,owner_id,scope_kind,scope_id,version,title,content,content_kind,
             provenance_json,created_at)
            VALUES ('old-version','old-group','owner','conversation','old-chat',1,
                    'Existing title','EXISTING_PRIVATE_TEXT','text','{}','now')''')
        connection.execute('''INSERT INTO learning_conversation_current_state
            (owner_id,kind,scope_id,revision,paths_json,source_scope_json,updated_at)
            VALUES ('owner','conversation','old-chat',1,'{}','{"version_ids":["old-version"]}','now')''')
    # Match an initialized 035 trial owner before testing the schema change.
    from app.learning_service import LearningService
    LearningService(database).principal({'id': 'owner', 'device_id': 'synthetic-device',
                                         'display_name': 'Synthetic', 'timezone': 'UTC', 'created_at': '2026-09-29T00:00:00Z'})
    before = _business_rows(database.connection)
    database.close()
    result = upgrade_learning_database(path, tmp_path / 'backups', authorized=True)
    assert result['status'] == 'upgraded'
    assert result['preflight']['applied_migrations'][-1] == '035_conversation_current_state'
    with closing(sqlite3.connect(path)) as connection:
        after = _business_rows(connection)
        assert {table: after[table] for table in before} == before
        assert set(after) - set(before) == {'learning_material_original', 'learning_material_library', 'learning_material_link'}
        assert after['learning_material_library'] == []
        assert after['learning_material_link'] == []
        assert after['learning_material_original'] == []
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []


def test_missing_current_restore_honors_material_receipt_and_original_bytes(material_service, tmp_path):
    service = material_service
    version = service.create({'id': 'owner'}, 'conversation', 'chat', title='source', content='text',
                             original=(b'RECEIPT_ORIGINAL_7381', 'source.txt', 'text/plain'))
    assert service.purge({'id': 'owner'}, version['material_id'])['purge']['status'] == 'complete'
    candidate = tmp_path / 'candidate.sqlite3'
    with closing(sqlite3.connect(candidate)) as target:
        service.db.connection.backup(target)
    with closing(sqlite3.connect(candidate)) as connection:
        connection.execute('''UPDATE learning_material_original SET content=?,filename=?
            WHERE version_id=? AND purged_at IS NOT NULL''',
            (b'RESTORED_STALE_ORIGINAL_7381', 'stale.txt', version['id']))
        connection.commit()
    missing = tmp_path / 'missing.sqlite3'
    receipt = receipt_path(service.db.database_path, 'owner', 'material', version['material_id'])
    write_json(receipt_path(missing, 'owner', 'material', version['material_id']),
               json.loads(receipt.read_text()))
    with pytest.raises(ProductionLearningDatabaseError, match='restore purged private content'):
        restore_learning_backup(candidate, missing, allow_missing_current=True)
    assert not missing.exists()


def test_restore_rejects_missing_original_tombstone(material_service, tmp_path):
    service = material_service
    version = service.create({'id': 'owner'}, 'conversation', 'chat', title='source', content='text',
                             original=(b'TOMBSTONE_ORIGINAL_1549', 'source.txt', 'text/plain'))
    assert service.purge({'id': 'owner'}, version['material_id'])['purge']['status'] == 'complete'
    candidate = tmp_path / 'no-original-tombstone.sqlite3'
    with closing(sqlite3.connect(candidate)) as target:
        service.db.connection.backup(target)
    with closing(sqlite3.connect(candidate)) as connection:
        connection.execute('DELETE FROM learning_material_original WHERE version_id=?', (version['id'],))
        connection.commit()
    with pytest.raises(ProductionLearningDatabaseError, match='lose deletion barriers'):
        restore_learning_backup(candidate, service.db.database_path)


def test_original_download_is_exact_scoped_and_absent_for_manual_versions(tmp_path):
    raw = b'EXACT_ORIGINAL_BYTES\r\nsecond line\n'
    with make_client(tmp_path, lambda request: None) as client:
        authorize(client)
        conversation = start_conversation(client, create_task(client))
        other = start_conversation(client, create_task(client))
        base = f'/api/materials/conversation/{conversation}'
        uploaded = client.post(base + '/upload', headers={'X-Filename': 'notes%20one.txt'}, content=raw)
        assert uploaded.status_code == 201, uploaded.text
        version = uploaded.json()
        assert version['original'] == {
            'filename': 'notes one.txt', 'media_type': 'text/plain',
            'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
        }
        assert 'content' not in version['original']
        assert client.get(base).json()['versions'][0]['original'] == version['original']
        download = client.get(base + f"/versions/{version['id']}/original")
        assert download.status_code == 200 and download.content == raw
        assert download.headers['cache-control'] == 'no-store'
        assert download.headers['x-content-type-options'] == 'nosniff'
        assert 'attachment' in download.headers['content-disposition']
        assert client.get(f"/api/materials/conversation/{other}/versions/{version['id']}/original").status_code == 404
        replacement = client.post(base + '/upload', params={'material_id': version['material_id']},
                                  headers={'X-Filename': 'replacement.txt'}, content=b'REPLACEMENT_BYTES')
        assert replacement.status_code == 201
        assert replacement.json()['version'] == 2
        assert replacement.json()['material_id'] == version['material_id']
        assert client.get(base + f"/versions/{version['id']}/original").content == raw
        assert client.get(base + f"/versions/{replacement.json()['id']}/original").content == b'REPLACEMENT_BYTES'
        manual = client.post(base, json={'title': 'Historical text', 'content': 'typed text'})
        assert manual.status_code == 201 and manual.json()['original'] is None
        missing = client.get(base + f"/versions/{manual.json()['id']}/original")
        assert missing.status_code == 404
        assert missing.json()['detail'] == 'material_original_unavailable'
        client.post('/api/auth/logout')
        assert client.get(base + f"/versions/{version['id']}/original").status_code == 401


def test_original_follows_immutable_version_and_sqlite_backup(material_service, tmp_path):
    service = material_service
    identity = {'id': 'owner'}
    first_raw = b'FIRST_VERSION_ORIGINAL\x00'
    second_raw = b'SECOND_VERSION_ORIGINAL\xff'
    first = service.create(identity, 'conversation', 'chat', title='first', content='first text',
                           original=(first_raw, 'first.txt', 'text/plain'))
    second = service.create(identity, 'conversation', 'chat', title='second', content='second text',
                            material_id=first['material_id'], original=(second_raw, 'second.txt', 'text/plain'))
    typed = service.create(identity, 'conversation', 'chat', title='typed', content='typed text',
                           material_id=first['material_id'])
    assert [item['original']['filename'] if item['original'] else None
            for item in service.list(identity, 'conversation', 'chat')['versions']] == [
                'first.txt', 'second.txt', None]
    assert service.original(identity, 'conversation', 'chat', first['id'])['content'] == first_raw
    assert service.original(identity, 'conversation', 'chat', second['id'])['content'] == second_raw
    with pytest.raises(DomainError, match='material_original_unavailable'):
        service.original(identity, 'conversation', 'chat', typed['id'])
    backup, _, _ = create_learning_backup(service.db.database_path, tmp_path / 'backups', label='originals')
    restored = tmp_path / 'restored.sqlite3'
    restore_learning_backup(backup, restored, allow_missing_current=True)
    with closing(sqlite3.connect(restored)) as connection:
        rows = connection.execute('''SELECT m.id,o.content,o.filename FROM learning_task_material m
            LEFT JOIN learning_material_original o ON o.version_id=m.id
            WHERE m.material_id=? ORDER BY m.version''', (first['material_id'],)).fetchall()
    assert rows == [(first['id'], first_raw, 'first.txt'),
                    (second['id'], second_raw, 'second.txt'), (typed['id'], None, None)]


def test_material_group_purge_scrubs_live_and_managed_originals(material_service, tmp_path):
    service = material_service
    identity = {'id': 'owner'}
    marker = b'RAW_ORIGINAL_PURGE_SENTINEL_8724'
    filename = 'PRIVATE_ORIGINAL_FILENAME_8724.txt'
    first = service.create(identity, 'conversation', 'chat', title='first', content='first text',
                           original=(marker, filename, 'text/plain'))
    second = service.create(identity, 'conversation', 'chat', title='second', content='second text',
                            material_id=first['material_id'], original=(marker + b'2', filename, 'text/plain'))
    managed, _, _ = create_learning_backup(service.db.database_path, tmp_path / 'backups', label='before')
    unmanaged = tmp_path / 'unmanaged.sqlite3'
    with closing(sqlite3.connect(unmanaged)) as target:
        service.db.connection.backup(target)
    result = service.purge(identity, first['material_id'])
    assert result['purge']['status'] == 'complete', result
    for path in (service.db.database_path, managed):
        with closing(sqlite3.connect(path)) as connection:
            rows = connection.execute('''SELECT o.content,o.filename,o.media_type,o.sha256,o.purged_at
                FROM learning_material_original o JOIN learning_task_material m ON m.id=o.version_id
                WHERE m.material_id=? ORDER BY m.version''', (first['material_id'],)).fetchall()
        assert len(rows) == 2
        assert all(row[:4] == (None, None, None, None) and row[4] for row in rows)
        assert marker not in path.read_bytes()
        assert filename.encode() not in path.read_bytes()
    with pytest.raises(DomainError, match='not_found'):
        service.original(identity, 'conversation', 'chat', second['id'])
    with pytest.raises(ProductionLearningDatabaseError):
        restore_learning_backup(unmanaged, service.db.database_path)


def test_purged_original_with_stale_bytes_is_erased_on_retry_and_rejected_on_restore(material_service, tmp_path):
    service = material_service
    identity = {'id': 'owner'}
    version = service.create(identity, 'conversation', 'chat', title='original', content='text',
                             original=(b'FIRST_STALE_ORIGINAL', 'first.txt', 'text/plain'))
    assert service.purge(identity, version['material_id'])['purge']['status'] == 'complete'
    candidate = tmp_path / 'tampered.sqlite3'
    with closing(sqlite3.connect(candidate)) as target:
        service.db.connection.backup(target)
    stale = b'REINSERTED_STALE_ORIGINAL_5931'
    for path in (candidate, service.db.database_path):
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('''UPDATE learning_material_original SET content=?,filename=?,media_type=?,sha256=?
                WHERE version_id=? AND purged_at IS NOT NULL''',
                (stale, 'stale-private.txt', 'text/plain', hashlib.sha256(stale).hexdigest(), version['id']))
            connection.commit()
    result = service.purge(identity, version['material_id'])
    assert result['purge']['status'] == 'complete', result
    assert service.db.fetchone('SELECT content FROM learning_material_original WHERE version_id=?',
                               (version['id'],))[0] is None
    assert stale not in service.db.database_path.read_bytes()
    with pytest.raises(ProductionLearningDatabaseError):
        restore_learning_backup(candidate, service.db.database_path)


@pytest.mark.asyncio
async def test_verification_purge_scrubs_discussion_material_original(learning_database, tmp_path):
    verification, original = await attempt(learning_database)
    discussions = QuestionDiscussionService(verification)
    materials = MaterialService(discussions.learning, discussions.chats)
    discussion = discussions.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'source')
    marker = b'DISCUSSION_ORIGINAL_SENTINEL_4628'
    version = materials.create(IDENTITY, 'discussion', discussion['id'], title='source', content='text',
                               original=(marker, 'discussion-private.txt', 'text/plain'))
    backup, _, _ = create_learning_backup(learning_database.database_path, tmp_path / 'backups', label='discussion')
    result = ManagedPurge(discussions.learning).run(
        IDENTITY, 'verification', original['id'], lambda: verification.purge(IDENTITY, original['id']))
    assert result['purge']['status'] == 'complete', result
    for path in (learning_database.database_path, backup):
        with closing(sqlite3.connect(path)) as connection:
            row = connection.execute('''SELECT content,filename,sha256,purged_at FROM learning_material_original
                WHERE version_id=?''', (version['id'],)).fetchone()
        assert row[:3] == (None, None, None) and row[3]
        assert marker not in path.read_bytes()
