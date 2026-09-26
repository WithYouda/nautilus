from contextlib import closing
import sqlite3

import pytest

from app.config import Settings
from app.db import Database
from app.learning_production import ProductionLearningDatabaseError, restore_learning_backup
from app.question_discussion import QuestionDiscussionService
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import CHALLENGE, IDENTITY, create_context, verification_service
from test_verification_evidence import chain


def snapshot(database, path):
    with closing(sqlite3.connect(path)) as target:
        database.connection.backup(target)
    return path


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["verification", "submission", "private_evidence", "discussion"])
async def test_restore_preserves_each_erasure_even_when_backup_has_no_body(learning_database, tmp_path, missing):
    service, _, _, saved = await chain(learning_database)
    await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate")
    await service.analyze_evidence(IDENTITY, saved["id"])
    QuestionDiscussionService(service).create(
        IDENTITY, saved["id"], saved["latest_submission_id"], "material", "discussion",
    )
    service.purge(IDENTITY, saved["id"])
    current = snapshot(learning_database, tmp_path / "current.sqlite3")
    candidate = snapshot(learning_database, tmp_path / "candidate.sqlite3")
    # A body-free backup can still be unsafe if it drops an erasure. Keep
    # every other tombstone, so one kind cannot mask a missing check for another.
    with closing(sqlite3.connect(candidate)) as connection:
        if missing == "private_evidence":
            assert connection.execute("SELECT COUNT(*) FROM learning_evidence_private_content").fetchone()[0]
            connection.execute("DROP TRIGGER learning_evidence_private_no_delete")
            connection.execute("DELETE FROM learning_evidence_private_content")
        else:
            table = {
                "verification": "learning_verification",
                "submission": "learning_verification_submission",
                "discussion": "learning_question_discussion",
            }[missing]
            assert connection.execute(f"SELECT COUNT(*) FROM {table} WHERE purged_at IS NOT NULL").fetchone()[0]
            connection.execute(f"UPDATE {table} SET purged_at=NULL")
        connection.commit()
    before = current.read_bytes()
    with pytest.raises(ProductionLearningDatabaseError, match="lose deletion barriers"):
        restore_learning_backup(candidate, current)
    assert current.read_bytes() == before
    assert not list(tmp_path.glob(".*.restore-*"))


@pytest.mark.asyncio
async def test_restore_rejects_older_schema_without_known_verification_purge(learning_database, tmp_path):
    context = create_context(learning_database)
    service = verification_service(learning_database, [CHALLENGE])
    verification = await service.start(IDENTITY, {**context, "mode": "ai_challenge"}, "ready")
    service.purge(IDENTITY, verification["id"])
    # Deleting an unsubmitted question has no raw artifact to act as a barrier.
    assert not learning_database.fetchone("SELECT 1 FROM learning_raw_artifact")
    current = snapshot(learning_database, tmp_path / "current.sqlite3")
    old = tmp_path / "schema-023.sqlite3"
    Database(old, Settings.from_env().migrations_dir, migration_floor=11, migration_ceiling=23).close()
    before = current.read_bytes()
    with pytest.raises(ProductionLearningDatabaseError, match="lose deletion barriers"):
        restore_learning_backup(old, current)
    assert current.read_bytes() == before


@pytest.mark.asyncio
async def test_restore_installs_the_checked_snapshot_if_source_changes(learning_database, tmp_path, monkeypatch):
    import app.learning_production as production

    service, _, _, saved = await chain(learning_database)
    old = snapshot(learning_database, tmp_path / "old.sqlite3")
    service.purge(IDENTITY, saved["id"])
    current = snapshot(learning_database, tmp_path / "current.sqlite3")
    candidate = snapshot(learning_database, tmp_path / "candidate.sqlite3")
    check = production._backup_restores_verification_content

    def replace_source_after_check(current_connection, checked_snapshot):
        result = check(current_connection, checked_snapshot)
        with closing(sqlite3.connect(old)) as source, closing(sqlite3.connect(candidate)) as target:
            source.backup(target)
        return result

    monkeypatch.setattr(production, "_backup_restores_verification_content", replace_source_after_check)
    assert restore_learning_backup(candidate, current)["up_to_date"]
    with closing(sqlite3.connect(current)) as connection:
        assert connection.execute("SELECT purged_at FROM learning_verification").fetchone()[0]
        assert not connection.execute("SELECT 1 FROM learning_raw_artifact WHERE content IS NOT NULL").fetchone()


def test_missing_current_requires_explicit_recovery_override(learning_database, tmp_path):
    candidate = snapshot(learning_database, tmp_path / "candidate.sqlite3")
    target = tmp_path / "missing.sqlite3"
    with pytest.raises(ProductionLearningDatabaseError, match="current learning database is missing"):
        restore_learning_backup(candidate, target)
    assert not target.exists()
