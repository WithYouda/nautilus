"""Real file contents, retries, replay and restore; all data is synthetic."""
import json
import sqlite3
from contextlib import closing

import pytest

from app.completion import CompletionService
from app.config import Settings
from app.db import Database
from app.evidence import EvidenceClaimDraft
from app.evidence_events import _canonical, _event_hash
from app.learning_domain import DomainError
from app.learning_production import create_learning_backup, restore_learning_backup, ProductionLearningDatabaseError
from app.managed_purge import ManagedPurge
from app.purge_content import columns
from app.purge_storage import receipt_path, write_json
from test_completion import request as completion_request
from test_evidence_claims import authorize, create_standard_chain
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY, OWNER, create_context, verification_service
from test_verification_review import attempt


def snapshot(db, path):
    path.parent.mkdir(exist_ok=True)
    with closing(sqlite3.connect(path)) as target:
        db.connection.backup(target)
    return path


def absent(path, *texts):
    for suffix in ('', '-wal', '-journal'):
        file = path.with_name(path.name + suffix)
        if file.exists():
            data = file.read_bytes()
            for text in texts:
                assert text.encode() not in data
                assert json.dumps(text, ensure_ascii=True)[1:-1].encode() not in data


def test_completion_clears_backup_bytes_preserves_other_records_and_reports_retry(learning_database, tmp_path, monkeypatch):
    db = learning_database
    ctx = create_context(db)
    service = CompletionService(verification_service(db, []))
    saved = service.create(IDENTITY, ctx['delegation_id'], completion_request('external_material'))
    other = create_context(db, key='keep')
    keep = service.create(IDENTITY, other['delegation_id'], completion_request('external_report', 'keep'))
    backup, manifest, _ = create_learning_backup(db.database_path, tmp_path / 'elsewhere', label='synthetic')
    with closing(sqlite3.connect(backup)) as conn:
        conn.execute('PRAGMA journal_mode=PERSIST')
        conn.execute("UPDATE learning_completion SET content_json=json_set(content_json,'$.note','synthetic note') WHERE id=?", (saved['id'],))
        conn.commit()
    # An unmanaged copy is deliberately outside the registered locations.
    unmanaged = snapshot(db, tmp_path / 'external.sqlite3')
    manager = ManagedPurge(service.learning)
    import app.managed_purge as module
    scrub = module.scrub_snapshot
    monkeypatch.setattr(module, 'scrub_snapshot', lambda *args: (_ for _ in ()).throw(OSError('synthetic failure')))
    result = manager.run(IDENTITY, 'completion', saved['id'], lambda: service.purge(IDENTITY, saved['id']))
    assert result['purge']['status'] == 'partial'
    assert service.get(IDENTITY, other['delegation_id']) == keep
    assert ManagedPurge(service.learning).status(IDENTITY, 'completion', saved['id'])['status'] == 'partial'
    with pytest.raises(ProductionLearningDatabaseError, match='incomplete'):
        restore_learning_backup(unmanaged, db.database_path)
    monkeypatch.setattr(module, 'scrub_snapshot', scrub)
    result = manager.run(IDENTITY, 'completion', saved['id'], lambda: service.purge(IDENTITY, saved['id']))
    assert result['purge']['status'] == 'complete'
    assert result['purge']['external_limits']
    absent(db.database_path, '合成成绩：60分；评分表未提供。')
    absent(backup, '合成成绩：60分；评分表未提供。')
    with closing(sqlite3.connect(backup)) as conn:
        assert json.loads(conn.execute('SELECT content_json FROM learning_completion WHERE id=?', (keep['id'],)).fetchone()[0]) == keep['content']
    assert json.loads(manifest.read_text())['content_erased_at']
    with pytest.raises(ProductionLearningDatabaseError, match='purged'):
        restore_learning_backup(unmanaged, db.database_path)
    service.learning.core.replay(OWNER)
    with pytest.raises(DomainError, match='not_found'):
        manager.status({**IDENTITY, 'id': 'other-owner'}, 'completion', saved['id'])


async def test_verification_versions_discussions_and_old_snapshot_are_scrubbed(learning_database, tmp_path):
    db = learning_database
    service, current = await attempt(db)
    first = current['latest_submission_id']
    from app.verification_help import record_solution_display
    evaluation_id = db.fetchone('SELECT id FROM learning_verification_evaluation WHERE submission_id=?', (first,))[0]
    record_solution_display(service, IDENTITY, current['id'], evaluation_id, 'q1')
    await service.submit(IDENTITY, current['id'], dict(responses={'q1': 'SECOND_PRIVATE_SENTINEL'}, request_key='second', evidence_condition='independent'))
    with db.transaction() as conn:
        conn.execute('''INSERT INTO learning_question_discussion
            (id,owner_id,verification_id,submission_id,question_id,request_key,created_at)
            VALUES ('discussion','owner-a',?,?,'q1','d','now')''', (current['id'], first))
        conn.execute('''INSERT INTO learning_discussion_turn
            (id,discussion_id,request_key,user_content,assistant_content,reasoning_content,status,sources_json,provider_snapshot_json,created_at)
            VALUES ('turn','discussion','turn','DISCUSSION_PRIVATE','ANSWER_PRIVATE','THINKING_PRIVATE','succeeded','[]','{"model_turn":"TOOL_PRIVATE"}','now')''')
    backup, _, _ = create_learning_backup(db.database_path, tmp_path / 'backups', label='synthetic')
    before_events = [tuple(row) for row in db.fetchall('SELECT * FROM learning_event')]
    result = ManagedPurge(service.learning).run(IDENTITY, 'verification', current['id'], lambda: service.purge(IDENTITY, current['id']))
    assert result['purge']['status'] == 'complete', result['purge']
    for path in (db.database_path, backup):
        absent(path, '合成原始作答', 'SECOND_PRIVATE_SENTINEL', 'DISCUSSION_PRIVATE', 'ANSWER_PRIVATE', 'THINKING_PRIVATE', 'TOOL_PRIVATE')
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute('SELECT provider_snapshot_json FROM learning_verification_evaluation WHERE id=?', (evaluation_id,)).fetchone()[0] is None
    # Existing facts are retained; purge appends its own factual events.
    assert [tuple(row) for row in db.fetchall('SELECT * FROM learning_event')][:len(before_events)] == before_events
    service.learning.core.replay(OWNER)
    assert db.fetchone("SELECT user_content FROM learning_discussion_turn WHERE id='turn'")[0] is None


def test_artifact_legacy_evidence_text_erased_and_hash_chain_still_replays(client, tmp_path):
    identity = authorize(client)
    created = create_standard_chain(client, content='regex: ^Nautilus\\d+$\nsample: Nautilus42\nRAW_PRIVATE_SENTINEL')
    client.app.state.evidence.semantic_analyzer = lambda _: [EvidenceClaimDraft(
        dimension_id='syntax_semantics', stance='supports', source='ai_analysis', statement='LEGACY_PRIVATE_SENTINEL',
        verification_method='semantic_analysis', evidence_condition='independent', scope='artifact')]
    assert client.post(f"/api/learning/artifacts/{created['artifact']['id']}/analysis", json={'request_key': 'analysis'}).status_code == 200
    db = client.app.state.learning.database
    # Recreate the supported pre-024 event format, with text in the ledger.
    with db.transaction() as conn:
        event = dict(conn.execute("SELECT e.* FROM learning_evidence_event e JOIN learning_evidence_private_content p ON e.id=p.event_id WHERE p.content_json LIKE '%LEGACY_PRIVATE_SENTINEL%' LIMIT 1").fetchone())
        private = conn.execute('SELECT content_json FROM learning_evidence_private_content WHERE event_id=?', (event['id'],)).fetchone()[0]
        payload = json.loads(event['payload_json']); payload.update(json.loads(private)); payload.pop('private_content_hash')
        event.update(payload_json=_canonical(payload), schema_version=1)
        trigger = conn.execute("SELECT sql FROM sqlite_master WHERE name='learning_evidence_event_no_update'").fetchone()[0]
        conn.execute('DROP TRIGGER learning_evidence_event_no_update')
        conn.execute('UPDATE learning_evidence_event SET payload_json=?,schema_version=1,event_hash=? WHERE id=?', (event['payload_json'], _event_hash(event), event['id']))
        conn.execute(trigger)
    backup, _, _ = create_learning_backup(db.database_path, tmp_path / 'backups', label='legacy')
    result = client.post(f"/api/learning/artifacts/{created['artifact']['id']}/purge", json={
        'expected_version': created['artifact']['version'], 'idempotency_key': 'purge', 'confirmation': 'PURGE'})
    assert result.status_code == 200
    assert result.json()['purge']['status'] == 'complete', result.json()
    for path in (db.database_path, backup):
        absent(path, 'RAW_PRIVATE_SENTINEL', 'LEGACY_PRIVATE_SENTINEL')
    assert client.app.state.evidence_events.replay(identity['id'])['status'] == 'succeeded'
    status = client.get(f"/api/learning/purges/artifact/{created['artifact']['id']}")
    assert status.json()['status'] == 'complete'
    assert status.headers['cache-control'] == 'no-store'
    with pytest.raises(sqlite3.DatabaseError, match='append-only'):
        with db.transaction() as conn:
            conn.execute("UPDATE learning_evidence_event SET payload_json='{}'")


def test_interrupted_intent_survives_and_missing_current_restore_cannot_erase_it(learning_database, tmp_path):
    ctx = create_context(learning_database)
    service = CompletionService(verification_service(learning_database, []))
    saved = service.create(IDENTITY, ctx['delegation_id'], completion_request())
    original = snapshot(learning_database, tmp_path / 'original.sqlite3')
    receipt = receipt_path(learning_database.database_path, IDENTITY['id'], 'completion', saved['id'])
    write_json(receipt, dict(owner=IDENTITY['id'], kind='completion', object_id=saved['id'], status='pending', updated_at='now', files=[], external_limits=[]))
    assert ManagedPurge(service.learning).status(IDENTITY, 'completion', saved['id'])['status'] == 'pending'
    with pytest.raises(ProductionLearningDatabaseError, match='incomplete'):
        restore_learning_backup(original, learning_database.database_path, allow_missing_current=True)
    missing = tmp_path / 'missing-current.sqlite3'
    write_json(receipt_path(missing, IDENTITY['id'], 'completion', saved['id']), json.loads(receipt.read_text()))
    with pytest.raises(ProductionLearningDatabaseError, match='incomplete'):
        restore_learning_backup(original, missing, allow_missing_current=True)
    assert not missing.exists()


@pytest.mark.parametrize('kind', ['artifact', 'verification'])
async def test_pre_linkage_backup_uses_submission_identity_and_keeps_other_content(learning_database, tmp_path, kind):
    db = learning_database
    service, current = await attempt(db)
    backup = tmp_path / 'backups' / 'old-023.sqlite3'
    Database(backup, Settings.from_env().migrations_dir, migration_floor=11, migration_ceiling=23).close()
    with closing(sqlite3.connect(backup)) as conn:
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name <> 'schema_migrations'").fetchall():
            fields = [r[1] for r in conn.execute(f'PRAGMA table_info({table})') if r[1] in columns(db.connection, table)]
            rows = db.fetchall(f"SELECT {','.join(fields)} FROM {table}")
            conn.executemany(f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", [tuple(r) for r in rows])
        conn.execute("UPDATE learning_verification_submission SET content_json=?", (json.dumps({'learner_work': 'LEGACY_SUBMISSION_PRIVATE'}),))
        conn.execute("UPDATE learning_verification SET submission_json=?", (json.dumps({'learner_work': 'LEGACY_SUBMISSION_PRIVATE'}),))
        conn.commit()
    submission = db.fetchone('SELECT * FROM learning_verification_submission WHERE id=?', (current['latest_submission_id'],))
    if kind == 'verification':
        object_id = current['id']
        purge = lambda: service.purge(IDENTITY, object_id)
    else:
        object_id = submission['artifact_id']
        version = db.fetchone('SELECT event_count FROM learning_stream_head WHERE aggregate_id=?', (current['action_id'],))[0]
        purge = lambda: service.learning.purge_artifact(IDENTITY, dict(artifact_id=object_id, expected_version=version, confirmation='PURGE'), 'purge')
    result = ManagedPurge(service.learning).run(IDENTITY, kind, object_id, purge)
    assert result['purge']['status'] == 'complete', result['purge']
    absent(backup, 'LEGACY_SUBMISSION_PRIVATE', '合成原始作答')
    with closing(sqlite3.connect(backup)) as conn:
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        challenge = json.loads(conn.execute('SELECT challenge_json FROM learning_verification').fetchone()[0])
        assert bool(challenge) == (kind == 'artifact')


def test_rejected_purge_does_not_leave_intent_that_blocks_backups(client, tmp_path):
    authorize(client)
    chain = create_standard_chain(client)
    result = client.post(f"/api/learning/artifacts/{chain['artifact']['id']}/purge", json={
        'expected_version': 1, 'idempotency_key': 'stale', 'confirmation': 'PURGE'})
    assert result.status_code == 409
    assert client.get(f"/api/learning/purges/artifact/{chain['artifact']['id']}").json()['status'] == 'not_requested'
    create_learning_backup(client.app.state.learning.database.database_path, tmp_path / 'backups', label='after-rejected-request')
