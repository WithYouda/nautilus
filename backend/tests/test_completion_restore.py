"""Restore must preserve a completion's private-content erasure."""

from contextlib import closing
import sqlite3

import pytest

from app.config import Settings
from app.db import Database
from app.learning_production import ProductionLearningDatabaseError, restore_learning_backup
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import create_context


def snapshot(database, path):
    with closing(sqlite3.connect(path)) as target:
        database.connection.backup(target)
    return path


def purged_completion(database):
    context = create_context(database)
    with database.transaction() as connection:
        connection.execute(
            """INSERT INTO learning_completion
               (id, owner_id, action_id, delegation_id, verification_kind, request_key,
                created_at, purged_at)
               VALUES ('completion-1', 'owner-a', ?, ?, 'external_material', 'complete-1',
                       '2026-09-26T00:00:00Z', '2026-09-26T00:01:00Z')""",
            (context["action_id"], context["delegation_id"]),
        )
        connection.execute(
            """INSERT INTO learning_completion_review
               (id, owner_id, completion_id, request_key, status, reason, created_at)
               VALUES ('review-1', 'owner-a', 'completion-1', 'review-1', 'failed',
                       'completion_content_deleted', '2026-09-26T00:00:00Z')""",
        )


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ("UPDATE learning_completion SET purged_at=NULL", "lose deletion barriers"),
        ("UPDATE learning_completion SET content_json='{}'", "restore content"),
        ("UPDATE learning_completion SET contract_snapshot_json='{}'", "restore content"),
        ("UPDATE learning_completion SET request_fingerprint='old-private-fingerprint'", "restore content"),
        ("UPDATE learning_completion_review SET result_json='{}'", "restore content"),
        ("UPDATE learning_completion_review SET provider_name='old provider'", "restore content"),
        ("UPDATE learning_completion_review SET model='old model'", "restore content"),
        ("UPDATE learning_completion_review SET user_response='old private reply'", "restore content"),
        ("UPDATE learning_completion_review SET status='running', reason=NULL", "restore content"),
    ],
)
def test_restore_rejects_completion_erasure_loss(learning_database, tmp_path, change, error):
    purged_completion(learning_database)
    current = snapshot(learning_database, tmp_path / "current.sqlite3")
    candidate = snapshot(learning_database, tmp_path / "candidate.sqlite3")
    with closing(sqlite3.connect(candidate)) as connection:
        connection.execute(change)
        connection.commit()
    before = current.read_bytes()
    with pytest.raises(ProductionLearningDatabaseError, match=error):
        restore_learning_backup(candidate, current)
    assert current.read_bytes() == before


def test_restore_accepts_purged_completion_snapshot(learning_database, tmp_path):
    purged_completion(learning_database)
    current = snapshot(learning_database, tmp_path / "current.sqlite3")
    candidate = snapshot(learning_database, tmp_path / "candidate.sqlite3")
    assert restore_learning_backup(candidate, current)["up_to_date"]


def test_restore_accepts_schema_029_without_completion_table(tmp_path):
    migrations = Settings.from_env().migrations_dir
    current = tmp_path / "current.sqlite3"
    candidate = tmp_path / "candidate.sqlite3"
    Database(current, migrations, migration_floor=11, migration_ceiling=29).close()
    Database(candidate, migrations, migration_floor=11, migration_ceiling=29).close()
    with closing(sqlite3.connect(current)) as connection:
        assert not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='learning_completion'"
        ).fetchone()
    assert restore_learning_backup(candidate, current)["applied_migrations"][-1] == "029_discussion_reasoning"
