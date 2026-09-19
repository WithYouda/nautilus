from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.learning_production import (
    ProductionLearningDatabaseError,
    create_learning_backup,
    inspect_learning_database,
    restore_learning_backup,
    upgrade_learning_database,
)
from test_evidence_claims import authorize, create_standard_chain


def test_production_upgrade_initializes_and_backs_up_isolated_learning_database(tmp_path):
    database_path = tmp_path / "learning.sqlite3"
    backup_dir = tmp_path / "backups"

    result = upgrade_learning_database(database_path, backup_dir, authorized=True)
    assert result["status"] == "initialized"
    assert result["preflight"] is None
    assert result["post_upgrade_backup"]["up_to_date"] is True

    inspection = inspect_learning_database(database_path)
    assert inspection["up_to_date"] is True
    assert inspection["integrity_check"] == "ok"
    assert inspection["foreign_key_check"] == "ok"

    backup_path = Path(result["post_upgrade_backup_path"])
    restored_path = tmp_path / "restored.sqlite3"
    restored = restore_learning_backup(
        backup_path,
        restored_path,
        allow_missing_current=True,
    )
    assert restored["applied_migrations"] == inspection["applied_migrations"]
    assert restored["integrity_check"] == "ok"


def test_production_upgrade_requires_authorization_and_rejects_default_database(tmp_path):
    with pytest.raises(ProductionLearningDatabaseError, match="explicit authorization"):
        upgrade_learning_database(tmp_path / "learning.sqlite3", tmp_path / "backups", authorized=False)

    from app.config import PROJECT_ROOT

    with pytest.raises(ProductionLearningDatabaseError, match="default main database"):
        upgrade_learning_database(
            PROJECT_ROOT / "data" / "nautilus.sqlite3",
            tmp_path / "backups",
            authorized=True,
        )


def test_restore_refuses_backup_that_would_resurrect_purged_content(client, tmp_path):
    authorize(client)
    created = create_standard_chain(client, key_prefix="production-purge")
    database_path = Path(client.app.state.learning.database.database_path)
    backup_dir = tmp_path / "backups"
    before_purge, _manifest, _inspection = create_learning_backup(
        database_path,
        backup_dir,
        label="before-purge",
    )

    purged = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/purge",
        json={
            "expected_version": created["artifact"]["version"],
            "idempotency_key": "production-purge",
            "confirmation": "PURGE",
        },
    )
    assert purged.status_code == 200

    current_copy = tmp_path / "current-copy.sqlite3"
    with closing(sqlite3.connect(database_path)) as source, closing(sqlite3.connect(current_copy)) as target:
        source.backup(target)

    with pytest.raises(ProductionLearningDatabaseError, match="purged"):
        restore_learning_backup(before_purge, current_copy)

    after_purge, _after_manifest, _after_inspection = create_learning_backup(
        current_copy,
        backup_dir,
        label="after-purge",
    )
    restored = restore_learning_backup(after_purge, current_copy)
    assert restored["integrity_check"] == "ok"
    with closing(sqlite3.connect(current_copy)) as connection:
        content, content_hash = connection.execute(
            "SELECT content, content_hash FROM learning_raw_artifact WHERE artifact_id=?",
            (created["artifact"]["id"],),
        ).fetchone()
        assert content is None
        assert content_hash is None
