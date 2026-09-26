"""Synthetic practice erasure across current data, managed backups and restore."""

import json
from contextlib import closing
import sqlite3

import pytest

from app.config import Settings
from app.db import Database
from app.learning_production import (
    ProductionLearningDatabaseError, create_learning_backup,
    restore_learning_backup, upgrade_learning_database,
)
from app.managed_purge import ManagedPurge
from app.purge_content import erase
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY
from test_verification_review import attempt


def seed_practices(db, current):
    submission_id = current['latest_submission_id']
    evaluation_id = current['evaluation']['id']
    other_submission = 'other-submission'
    with db.transaction() as c:
        source = c.execute('SELECT * FROM learning_verification_submission WHERE id=?', (submission_id,)).fetchone()
        c.execute('''INSERT INTO learning_verification_submission
            (id,owner_id,verification_id,request_key,request_fingerprint,content_json,created_at)
            VALUES (?,?,?,?,?,?,?)''',
            (other_submission, IDENTITY['id'], current['id'], 'other-answer', 'other-fingerprint', '{}', source['created_at']))
        for practice_id, source_id, request in (
            ('recheck', submission_id, '{}'),
            ('derived', submission_id, '{"recheck_id":"recheck"}'),
            ('replacement', submission_id, '{"previous_id":"derived"}'),
            ('sibling', other_submission, '{}'),
        ):
            c.execute('''INSERT INTO learning_practice
                (id,owner_id,verification_id,submission_id,evaluation_id,question_id,operation,requested_kind,
                 request_key,request_fingerprint,request_json,contract_snapshot_json,content_json,status,
                 provider_name,model,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (practice_id, IDENTITY['id'], current['id'], source_id, evaluation_id, 'q1',
                 'recheck' if practice_id == 'recheck' else 'exercise', 'redo', practice_id,
                 'private-fingerprint', request, '{}', '{"private":"exercise"}', 'ready',
                 'private-provider', 'private-model', source['created_at']))
            c.execute('''INSERT INTO learning_practice_attempt
                (id,owner_id,practice_id,request_key,request_fingerprint,answer,condition_json,created_at)
                VALUES (?,?,?,?,?,?,?,?)''',
                (practice_id + '-attempt', IDENTITY['id'], practice_id, 'attempt', 'private-fingerprint',
                 'private-answer', '{"private":"condition"}', source['created_at']))
            c.execute('''INSERT INTO learning_practice_run
                (id,owner_id,practice_id,attempt_id,request_key,kind,status,result_json,
                 provider_name,model,created_at,displayed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (practice_id + '-run', IDENTITY['id'], practice_id, practice_id + '-attempt',
                 'evaluation', 'evaluation', 'succeeded', '{"private":"feedback"}',
                 'private-provider', 'private-model', source['created_at'], source['created_at']))
    return submission_id, other_submission


def assert_erased(db, practice_id):
    row = db.fetchone('SELECT * FROM learning_practice WHERE id=?', (practice_id,))
    assert row['purged_at'] and row['status'] == 'purged'
    assert all(row[key] is None for key in ('request_json', 'request_fingerprint', 'contract_snapshot_json',
                                             'content_json', 'provider_name', 'model'))
    attempt = db.fetchone('SELECT * FROM learning_practice_attempt WHERE practice_id=?', (practice_id,))
    assert attempt['purged_at'] and all(attempt[key] is None for key in ('answer', 'condition_json', 'request_fingerprint'))
    run = db.fetchone('SELECT * FROM learning_practice_run WHERE practice_id=?', (practice_id,))
    assert run['purged_at'] and run['status'] == 'failed'
    assert all(run[key] is None for key in ('result_json', 'provider_name', 'model', 'displayed_at'))


@pytest.mark.asyncio
async def test_source_erasure_clears_only_derived_practice(learning_database):
    service, current = await attempt(learning_database)
    source, other = seed_practices(learning_database, current)
    with learning_database.transaction() as c:
        erase(c, IDENTITY['id'], 'artifact', 'synthetic-artifact', '2026-09-26T12:00:00Z', submission_ids=[source])
    assert_erased(learning_database, 'recheck')
    assert_erased(learning_database, 'derived')
    assert_erased(learning_database, 'replacement')
    assert learning_database.fetchone('SELECT content_json,purged_at FROM learning_verification_submission WHERE id=?', (other,))['purged_at'] is None
    assert learning_database.fetchone('SELECT content_json FROM learning_practice WHERE id=?', ('sibling',))[0]


@pytest.mark.asyncio
async def test_managed_practice_purge_scrubs_backup_and_restore_barrier(learning_database, tmp_path):
    service, current = await attempt(learning_database)
    source, _ = seed_practices(learning_database, current)
    old_backup, _, _ = create_learning_backup(learning_database.database_path, tmp_path / 'backups', label='practice')

    def online_purge():
        with learning_database.transaction(immediate=True) as c:
            erase(c, IDENTITY['id'], 'practice', 'recheck', '2026-09-26T12:00:00Z')
        return {'id': 'recheck'}

    result = ManagedPurge(service.learning).run(IDENTITY, 'practice', 'recheck', online_purge)
    assert result['purge']['status'] == 'complete'
    assert_erased(learning_database, 'recheck')
    assert_erased(learning_database, 'derived')
    assert_erased(learning_database, 'replacement')
    assert learning_database.fetchone('SELECT content_json FROM learning_practice WHERE id=?', ('sibling',))[0]
    assert learning_database.fetchone('SELECT purged_at FROM learning_verification_submission WHERE id=?', (source,))[0] is None
    with closing(sqlite3.connect(old_backup)) as backup:
        assert backup.execute('SELECT content_json FROM learning_practice WHERE id=?', ('recheck',)).fetchone()[0] is None
        assert backup.execute('SELECT answer FROM learning_practice_attempt WHERE practice_id=?', ('derived',)).fetchone()[0] is None
        # A modified candidate retaining old private text must fail restore.
        backup.execute("UPDATE learning_practice SET content_json='{}' WHERE id='recheck'")
        backup.commit()
    with pytest.raises(ProductionLearningDatabaseError, match='restore'):
        restore_learning_backup(old_backup, learning_database.database_path)


@pytest.mark.asyncio
async def test_upgrade_from_030_keeps_existing_records_and_adds_practice(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    db = Database(path, Settings.from_env().migrations_dir, migration_floor=11, migration_ceiling=30)
    with db.transaction() as c:
        c.execute("INSERT INTO local_identity VALUES ('owner-a','device','Learner','UTC','2026-09-26T00:00:00Z','2026-09-26T00:00:00Z')")
    await attempt(db)
    tables = ('local_identity', 'learning_event', 'learning_session', 'learning_verification',
              'learning_verification_submission', 'learning_verification_evaluation')
    before = {table: [tuple(row) for row in db.fetchall(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}
    db.close()
    result = upgrade_learning_database(path, tmp_path / 'backups', authorized=True)
    assert result['post_upgrade_backup']['integrity_check'] == 'ok'
    with closing(sqlite3.connect(path)) as upgraded:
        assert {table: upgraded.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() for table in tables} == before
        assert upgraded.execute('SELECT COUNT(*) FROM learning_practice').fetchone()[0] == 0
        assert upgraded.execute('PRAGMA foreign_key_check').fetchall() == []
