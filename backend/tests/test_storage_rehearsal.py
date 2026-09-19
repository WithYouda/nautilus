"""Task 0: INV-008 and CAP-MEASURE-001; synthetic storage probes only."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from isolated_storage import RecoveryError, RecoveryWorkspace


@pytest.fixture
def probe_migrations(tmp_path):
    migrations = tmp_path / "probe-migrations"
    migrations.mkdir()
    (migrations / "011_recovery_probe.sql").write_text(
        """
        CREATE TABLE probe_artifact (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
            content TEXT NOT NULL, content_version INTEGER NOT NULL CHECK(content_version > 0)
        );
        CREATE TABLE probe_event (
            event_id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL REFERENCES probe_artifact(id),
            aggregate_version INTEGER NOT NULL UNIQUE CHECK(aggregate_version > 0)
        );
        CREATE TABLE probe_projection (
            artifact_id TEXT PRIMARY KEY REFERENCES probe_artifact(id),
            last_event_id TEXT NOT NULL REFERENCES probe_event(event_id),
            position INTEGER NOT NULL CHECK(position > 0)
        );
        """,
        encoding="utf-8",
    )
    return migrations


def seed_probe(database):
    with database.transaction() as connection:
        connection.execute("INSERT INTO probe_artifact VALUES ('artifact-a', 'owner-a', 'synthetic-output', 1)")
        connection.execute("INSERT INTO probe_event VALUES ('event-a', 'artifact-a', 1)")
        connection.execute("INSERT INTO probe_projection VALUES ('artifact-a', 'event-a', 1)")


@pytest.mark.parametrize("repetition", range(2))
def test_wal_backup_restores_to_new_database_and_cleans_up(probe_migrations, repetition):
    with RecoveryWorkspace(probe_migrations) as workspace:
        workspace_path = workspace.root
        database = workspace.create_database()
        seed_probe(database)
        assert database.fetchone("PRAGMA journal_mode")[0] == "wal"
        snapshot = workspace.backup(database)
        assert snapshot.name.startswith("snapshot-011_recovery_probe-")

        with database.transaction() as connection:
            connection.execute("UPDATE probe_projection SET position = 2")
        restored = workspace.restore(snapshot)

        assert restored.database_path != database.database_path
        assert restored.fetchone("SELECT position FROM probe_projection")[0] == 1
        assert restored.fetchone("SELECT content FROM probe_artifact")[0] == "synthetic-output"
        assert restored.fetchone("SELECT owner_id FROM probe_artifact")[0] == "owner-a"
        report = workspace.verify(restored)
        assert report["integrity_check"] == "ok"
        assert report["foreign_key_violations"] == 0
        assert report["versions"] == ["011_recovery_probe"]
        assert report["table_counts"]["probe_event"] == 1
        assert "synthetic-output" not in str(report)
        assert "owner-a" not in str(report)
    assert not workspace_path.exists()


def test_backup_rejects_uncommitted_transaction(probe_migrations):
    with RecoveryWorkspace(probe_migrations) as workspace:
        database = workspace.create_database()
        with database.transaction():
            with pytest.raises(RecoveryError, match="active transaction"):
                workspace.backup(database)


def test_corrupt_backup_is_rejected_without_overwriting_live_database(probe_migrations):
    with RecoveryWorkspace(probe_migrations) as workspace:
        database = workspace.create_database()
        seed_probe(database)
        snapshot = workspace.backup(database)
        snapshot.write_bytes(b"invalid synthetic snapshot")
        with pytest.raises(RecoveryError, match="snapshot digest"):
            workspace.restore(snapshot)
        assert database.fetchone("SELECT COUNT(*) FROM probe_artifact")[0] == 1


def test_restore_refuses_schema_drift(probe_migrations):
    with RecoveryWorkspace(probe_migrations) as workspace:
        database = workspace.create_database()
        snapshot = workspace.backup(database)
        migration = probe_migrations / "011_recovery_probe.sql"
        migration.write_text(migration.read_text() + "\nCREATE TABLE drift(id TEXT);\n")
        with pytest.raises(RecoveryError, match="migration manifest"):
            workspace.restore(snapshot)


def test_backup_refuses_unknown_migration_and_foreign_key_damage(probe_migrations):
    with RecoveryWorkspace(probe_migrations) as workspace:
        database = workspace.create_database()
        with database.transaction() as connection:
            connection.execute("INSERT INTO schema_migrations VALUES ('012_unknown', 'synthetic-time')")
        with pytest.raises(RecoveryError, match="migration versions"):
            workspace.backup(database)
        with database.transaction() as connection:
            connection.execute("DELETE FROM schema_migrations WHERE version = '012_unknown'")
        database.connection.execute("PRAGMA foreign_keys = OFF")
        database.connection.execute("INSERT INTO probe_event VALUES ('event-b', 'missing', 1)")
        database.connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(RecoveryError, match="foreign key"):
            workspace.backup(database)


def test_failed_migration_leaves_no_partial_schema(probe_migrations):
    (probe_migrations / "012_broken_probe.sql").write_text(
        "CREATE TABLE partial(id TEXT); INSERT INTO absent VALUES (1);",
        encoding="utf-8",
    )
    with RecoveryWorkspace(probe_migrations) as workspace:
        with pytest.raises(sqlite3.OperationalError):
            workspace.create_database()
        with closing(sqlite3.connect(workspace.root / "source.sqlite3")) as connection:
            assert connection.execute("SELECT name FROM sqlite_master WHERE name='partial'").fetchall() == []
            assert connection.execute("SELECT version FROM schema_migrations").fetchall() == [("011_recovery_probe",)]


def test_workspace_refuses_legacy_migrations_and_gaps(probe_migrations):
    (probe_migrations / "010_forbidden.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(RecoveryError, match="011"):
        with RecoveryWorkspace(probe_migrations):
            pass
    (probe_migrations / "010_forbidden.sql").unlink()
    (probe_migrations / "013_gap.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(RecoveryError, match="contiguous"):
        with RecoveryWorkspace(probe_migrations):
            pass


def test_workspace_rejects_outside_snapshot_without_opening_it(probe_migrations):
    with RecoveryWorkspace(probe_migrations) as workspace:
        with pytest.raises(RecoveryError, match="workspace"):
            workspace.restore(Path("/outside-unowned/snapshot.sqlite3"))


def test_database_guard_rejects_default_and_aliases_before_connect(tmp_path, database_access_guard):
    from app.config import PROJECT_ROOT

    protected = PROJECT_ROOT / "data" / "nautilus.sqlite3"
    with pytest.raises(RuntimeError, match="isolated"):
        sqlite3.connect(protected)
    alias = tmp_path / "alias.sqlite3"
    alias.symlink_to(protected)
    with pytest.raises(RuntimeError, match="isolated"):
        sqlite3.connect(alias)
    with pytest.raises(RuntimeError, match="isolated"):
        sqlite3.connect(protected.as_uri() + "?mode=ro", uri=True)
    assert database_access_guard["protected_connections"] == 0
