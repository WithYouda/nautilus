"""Synthetic delayed follow-up erasure and restoration boundaries."""

from contextlib import closing
import shutil
import sqlite3

import pytest

from app.config import Settings
from app.core.commands import SaveTextArtifact
from app.db import Database
from app.learning_production import (
    ProductionLearningDatabaseError, create_learning_backup, restore_learning_backup,
)
from app.learning_service import LearningService
from app.managed_purge import ManagedPurge
from app.purge_content import erase
from app.purge_storage import receipt_path
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY, OWNER, create_context


STAMP = '2026-09-26T00:00:00Z'
OWNER_ID = IDENTITY['id']


def seed(db):
    context = create_context(db, 'delayed')
    outcome = db.fetchone('SELECT outcome_id FROM learning_delegation WHERE id=?',
                          (context['delegation_id'],))[0]
    for suffix in ('one', 'other'):
        artifact = LearningService(db).core.execute(
            OWNER, SaveTextArtifact(session_id=context['session_id'],
                                    content=f'private-source-{suffix}',
                                    expected_version=3 if suffix == 'one' else 4),
            f'delayed-artifact-{suffix}',
        )
        with db.transaction() as c:
            c.execute('''INSERT INTO learning_delayed_follow_up
                (id,owner_id,outcome_id,delegation_id,source_artifact_id,source_content_version,
                 standard_id,standard_snapshot_json,request_key,request_fingerprint,status,due_at,timezone,
                 arranged_at,started_at,history_json,created_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (suffix, OWNER_ID, outcome, context['delegation_id'], artifact['id'], 1,
                 f'synthetic-standard-{suffix}', '{"private":"standard"}', f'key-{suffix}', 'private-fingerprint',
                 'started', STAMP, 'Asia/Shanghai', STAMP, STAMP, '{"private":"history"}', STAMP))
            c.execute('''INSERT INTO learning_delayed_attempt
                (id,owner_id,follow_up_id,phase,answers_json,user_report,condition_json,submitted_at,
                 submit_key,submit_fingerprint,check_status,result_json,checked_at,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (f'attempt-{suffix}', OWNER_ID, suffix, 'initial', '{"private":"answer"}',
                 'used', '{"private":"condition"}', STAMP, f'submit-{suffix}',
                 'private-fingerprint', 'succeeded', '{"private":"result"}', STAMP, STAMP))
            c.execute('''INSERT INTO learning_delayed_view
                (id,owner_id,follow_up_id,attempt_id,provided_at,displayed_at,after_arranging)
                VALUES (?,?,?,?,?,?,?)''',
                (f'view-{suffix}', OWNER_ID, suffix, f'attempt-{suffix}', STAMP, STAMP, 1))
        if suffix == 'one':
            source_id = artifact['id']
    return source_id


def assert_erased(db, suffix):
    row = db.fetchone('SELECT * FROM learning_delayed_follow_up WHERE id=?', (suffix,))
    assert row['purged_at'] and row['status'] == 'purged'
    assert all(row[key] is None for key in ('standard_snapshot_json', 'request_fingerprint',
        'history_json', 'due_at', 'timezone', 'arranged_at', 'started_at'))
    attempt = db.fetchone('SELECT * FROM learning_delayed_attempt WHERE follow_up_id=?', (suffix,))
    assert attempt['purged_at'] and attempt['check_status'] == 'not_checked'
    assert all(attempt[key] is None for key in ('answers_json', 'user_report', 'condition_json',
        'submit_fingerprint', 'result_json'))
    view = db.fetchone('SELECT * FROM learning_delayed_view WHERE follow_up_id=?', (suffix,))
    assert view['purged_at'] and all(view[key] is None for key in
        ('provided_at', 'displayed_at', 'after_arranging'))


def test_direct_and_source_erasure_keep_unrelated_follow_up(learning_database):
    source_id = seed(learning_database)
    with learning_database.transaction() as c:
        erase(c, OWNER_ID, 'delayed', 'one', STAMP)
    assert_erased(learning_database, 'one')
    assert learning_database.fetchone('SELECT answers_json FROM learning_delayed_attempt WHERE follow_up_id=?',
                                      ('other',))[0]
    with learning_database.transaction() as c:
        erase(c, OWNER_ID, 'artifact', source_id, STAMP)
    assert_erased(learning_database, 'one')
    assert learning_database.fetchone('SELECT answers_json FROM learning_delayed_attempt WHERE follow_up_id=?',
                                      ('other',))[0]


def test_source_erasure_propagates_to_selected_follow_up(learning_database):
    source_id = seed(learning_database)
    with learning_database.transaction() as c:
        erase(c, OWNER_ID, 'artifact', source_id, STAMP)
    assert_erased(learning_database, 'one')
    assert learning_database.fetchone('SELECT answers_json FROM learning_delayed_attempt WHERE follow_up_id=?',
                                      ('other',))[0]


def test_verification_source_artifact_erasure_propagates(learning_database):
    source_id = seed(learning_database)
    delegation = learning_database.fetchone('''SELECT d.id,d.action_id,s.id AS session_id
        FROM learning_delayed_follow_up f JOIN learning_delegation d ON d.id=f.delegation_id
        JOIN learning_session s ON s.delegation_id=d.id WHERE f.id='one' ''')
    with learning_database.transaction() as c:
        c.execute('''INSERT INTO learning_verification
            (id,owner_id,action_id,delegation_id,session_id,mode,request_key,request_fingerprint,
             status,challenge_json,answer_key_json,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            ('verification', OWNER_ID, delegation['action_id'], delegation['id'],
             delegation['session_id'], 'user_material', 'verification-key', 'fingerprint',
             'submitted', '{}', '{}', STAMP))
        c.execute('''INSERT INTO learning_verification_submission
            (id,owner_id,verification_id,request_key,request_fingerprint,content_json,created_at,artifact_id)
            VALUES (?,?,?,?,?,?,?,?)''',
            ('submission', OWNER_ID, 'verification', 'submission-key', 'fingerprint', '{}', STAMP, source_id))
        erase(c, OWNER_ID, 'verification', 'verification', STAMP)
    assert_erased(learning_database, 'one')
    assert learning_database.fetchone('SELECT answers_json FROM learning_delayed_attempt WHERE follow_up_id=?',
                                      ('other',))[0]


def test_managed_delayed_purge_scrubs_backup_and_blocks_old_restore(learning_database, tmp_path):
    seed(learning_database)
    old, _, _ = create_learning_backup(learning_database.database_path, tmp_path / 'backups', label='delayed')
    unmanaged = tmp_path / 'unmanaged.sqlite3'
    with closing(sqlite3.connect(old)) as source, closing(sqlite3.connect(unmanaged)) as target:
        source.backup(target)

    def online_purge():
        with learning_database.transaction(immediate=True) as c:
            erase(c, OWNER_ID, 'delayed', 'one', STAMP)
        return {'id': 'one'}

    report = ManagedPurge(LearningService(learning_database)).run(IDENTITY, 'delayed', 'one', online_purge)
    assert report['purge']['status'] == 'complete'
    assert_erased(learning_database, 'one')
    with closing(sqlite3.connect(old)) as backup:
        backup.row_factory = sqlite3.Row
        assert backup.execute('SELECT answers_json FROM learning_delayed_attempt WHERE follow_up_id=?', ('one',)).fetchone()[0] is None
        assert backup.execute('SELECT answers_json FROM learning_delayed_attempt WHERE follow_up_id=?', ('other',)).fetchone()[0]
        backup.execute("UPDATE learning_delayed_attempt SET answers_json='{}' WHERE follow_up_id='one'")
        backup.commit()
    with pytest.raises(ProductionLearningDatabaseError, match='restore'):
        restore_learning_backup(old, learning_database.database_path)
    with pytest.raises(ProductionLearningDatabaseError, match='purged'):
        restore_learning_backup(unmanaged, learning_database.database_path)


def test_receipt_blocks_missing_current_and_missing_delayed_barriers(learning_database, tmp_path):
    seed(learning_database)
    old, _, _ = create_learning_backup(learning_database.database_path, tmp_path / 'backups', label='old')
    unmanaged = tmp_path / 'unmanaged-old.sqlite3'
    with closing(sqlite3.connect(old)) as source, closing(sqlite3.connect(unmanaged)) as target:
        source.backup(target)

    def online_purge():
        with learning_database.transaction(immediate=True) as c:
            erase(c, OWNER_ID, 'delayed', 'one', STAMP)
        return {'id': 'one'}

    assert ManagedPurge(LearningService(learning_database)).run(IDENTITY, 'delayed', 'one', online_purge)['purge']['status'] == 'complete'
    missing = tmp_path / 'missing.sqlite3'
    receipt = receipt_path(missing, OWNER_ID, 'delayed', 'one')
    receipt.parent.mkdir(parents=True)
    shutil.copyfile(receipt_path(learning_database.database_path, OWNER_ID, 'delayed', 'one'), receipt)
    with pytest.raises(ProductionLearningDatabaseError, match='barriers'):
        restore_learning_backup(unmanaged, missing, allow_missing_current=True)
    with closing(sqlite3.connect(old)) as candidate:
        candidate.execute("UPDATE learning_delayed_follow_up SET purged_at=NULL WHERE id='one'")
        candidate.commit()
    with pytest.raises(ProductionLearningDatabaseError, match='barriers'):
        restore_learning_backup(old, missing, allow_missing_current=True)
    no_row = tmp_path / 'no-row.sqlite3'
    shutil.copyfile(old, no_row)
    with closing(sqlite3.connect(no_row)) as candidate:
        candidate.execute("DELETE FROM learning_delayed_view WHERE follow_up_id='one'")
        candidate.execute("DELETE FROM learning_delayed_attempt WHERE follow_up_id='one'")
        candidate.execute("DELETE FROM learning_delayed_follow_up WHERE id='one'")
        candidate.commit()
    with pytest.raises(ProductionLearningDatabaseError, match='barriers'):
        restore_learning_backup(no_row, missing, allow_missing_current=True)
    no_table = tmp_path / 'no-table.sqlite3'
    shutil.copyfile(old, no_table)
    with closing(sqlite3.connect(no_table)) as candidate:
        candidate.execute("UPDATE learning_delayed_follow_up SET purged_at=? WHERE id='one'", (STAMP,))
        candidate.execute('DROP TABLE learning_delayed_view')
        candidate.commit()
    with pytest.raises(ProductionLearningDatabaseError, match='barriers'):
        restore_learning_backup(no_table, missing, allow_missing_current=True)


def test_031_to_032_preserves_existing_rows_and_adds_empty_tables(tmp_path):
    path = tmp_path / 'old.sqlite3'
    db = Database(path, Settings.from_env().migrations_dir, migration_floor=11, migration_ceiling=31)
    with db.transaction() as c:
        c.execute("INSERT INTO local_identity VALUES ('owner-a','device','Learner','UTC',?,?)", (STAMP, STAMP))
    create_context(db, 'upgrade-delayed')
    tables = [row[0] for row in db.fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'learning_%'")]
    before = {table: [tuple(row) for row in db.fetchall(f'SELECT * FROM {table} ORDER BY rowid')]
              for table in tables}
    db.close()
    upgraded_db = Database(path, Settings.from_env().migrations_dir, migration_floor=11, migration_ceiling=None)
    assert upgraded_db.fetchone('SELECT version FROM schema_migrations ORDER BY rowid DESC LIMIT 1')[0] == '032_delayed_follow_up'
    upgraded_db.close()
    with closing(sqlite3.connect(path)) as upgraded:
        assert all(upgraded.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() == rows
                   for table, rows in before.items())
        for table in ('learning_delayed_follow_up', 'learning_delayed_attempt', 'learning_delayed_view'):
            assert upgraded.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0
        assert upgraded.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert upgraded.execute('PRAGMA foreign_key_check').fetchall() == []
