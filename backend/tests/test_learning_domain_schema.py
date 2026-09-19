"""Task 1: INV-001/005/008/009 and CAP-FACT-001."""

import json
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.db import Database
from app.learning_domain import DomainError, LearningRepository, Principal
from app.learning_storage import open_learning_database


@pytest.fixture
def learning_database(tmp_path):
    database = open_learning_database(tmp_path / "learning.sqlite3")
    with database.transaction() as connection:
        for owner in ("owner-a", "owner-b"):
            connection.execute(
                "INSERT INTO local_identity VALUES (?, ?, ?, 'UTC', ?, ?)",
                (owner, owner, "Synthetic learner", "2026-09-05T00:00:00Z", "2026-09-05T00:00:00Z"),
            )
    yield database
    database.close()


@pytest.fixture
def domain_rows(learning_database):
    database = learning_database
    recipe = {"dimensions": [{"id": "synthetic_dimension", "label": "Synthetic dimension",
        "requirements": [{"method": "independent_review", "condition": "independent", "minimum": 1}]}]}
    with database.transaction() as connection:
        for suffix in ("a", "b"):
            owner = f"owner-{suffix}"
            connection.execute(
                "INSERT INTO learning_outcome VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"outcome-{suffix}", owner, "Synthetic object", "Synthetic behavior", "synthetic-context", "user", "2026-09-05T00:00:00Z"),
            )
            connection.execute(
                "INSERT INTO learning_action VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"action-{suffix}", owner, "Synthetic action", "synthetic-context", "open", 1, "2026-09-05T00:00:00Z"),
            )
            connection.execute(
                "INSERT INTO learning_standard_package VALUES (?, ?, ?, ?, ?)",
                (f"package-{suffix}", owner, "Synthetic standard", "test-fixture", "synthetic-context"),
            )
            for status in ("approved", "candidate"):
                connection.execute(
                    """INSERT INTO learning_criterion_version
                    (id, owner_id, package_id, outcome_id, version, source, context_key,
                     recipe_json, review_status, reviewed_by, reviewed_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (f"criterion-{suffix}-{status}", owner, f"package-{suffix}", f"outcome-{suffix}",
                     1 if status == "approved" else 2, "test-fixture", "synthetic-context", json.dumps(recipe),
                     status, "synthetic-reviewer" if status == "approved" else None,
                     "2026-09-05T00:00:00Z" if status == "approved" else None, "2026-09-05T00:00:00Z"),
                )
    return database


def test_independent_schema_and_reopen_are_stable(tmp_path):
    path = tmp_path / "learning.sqlite3"
    for _ in range(2):
        database = open_learning_database(path)
        try:
            assert [r[0] for r in database.fetchall("SELECT version FROM schema_migrations")] == [
                "011_nautilus_learning_domain",
                "012_learning_evidence_claims",
                "013_learning_evidence_follow_ups",
                "014_learning_derived_states",
                "015_learning_review_completion",
                "016_learning_evidence_events",
                "017_learning_evidence_provider",
                "018_learning_analysis_provider_snapshot",
                "019_agent_permission_grants",
                "020_evidence_event_schema_version",
                "021_learning_guided_setup",
                "022_learning_verifications",
                "023_verification_submissions",
                "024_verification_evidence",
            ]
            assert database.fetchone("PRAGMA integrity_check")[0] == "ok"
            assert database.fetchall("PRAGMA foreign_key_check") == []
            assert {
                row[0]
                for row in database.fetchall(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                    "('learning_goal', 'learning_plan', 'learning_module', 'learning_action_link', 'learning_setup')"
                )
            } == {
                "learning_goal", "learning_plan", "learning_module", "learning_action_link", "learning_setup"
            }
        finally:
            database.close()


def test_learning_database_upgrades_from_016_with_existing_rows(tmp_path):
    path = tmp_path / "learning-upgrade.sqlite3"
    migrations_dir = Path(__file__).resolve().parents[1] / "app" / "migrations"
    legacy = Database(path, migrations_dir, migration_floor=11, migration_ceiling=16)
    with legacy.transaction() as connection:
        connection.execute(
            """INSERT INTO local_identity
               (id, device_id, display_name, timezone, created_at, updated_at)
               VALUES ('upgrade-owner', 'upgrade-device', 'Upgrade learner', 'UTC',
                       '2026-09-09T00:00:00Z', '2026-09-09T00:00:00Z')"""
        )
        from app.evidence_events import _event_hash

        legacy_event = {
            "id": "legacy-evidence-event",
            "owner_id": "upgrade-owner",
            "aggregate_type": "claim",
            "aggregate_id": "legacy-claim",
            "event_type": "claim.created",
            "event_version": 1,
            "payload_json": json.dumps({"id": "legacy-claim"}, sort_keys=True, separators=(",", ":")),
            "previous_hash": None,
            "created_at": "2026-09-09T00:00:01Z",
        }
        legacy_event["event_hash"] = _event_hash(legacy_event)
        connection.execute(
            """INSERT INTO learning_evidence_event
               (id, owner_id, aggregate_type, aggregate_id, event_type, event_version,
                payload_json, previous_hash, event_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tuple(legacy_event[key] for key in (
                "id", "owner_id", "aggregate_type", "aggregate_id", "event_type",
                "event_version", "payload_json", "previous_hash", "event_hash", "created_at",
            )),
        )
    legacy.close()

    database = open_learning_database(path)
    try:
        assert [r[0] for r in database.fetchall("SELECT version FROM schema_migrations")] == [
            "011_nautilus_learning_domain",
            "012_learning_evidence_claims",
            "013_learning_evidence_follow_ups",
            "014_learning_derived_states",
            "015_learning_review_completion",
            "016_learning_evidence_events",
            "017_learning_evidence_provider",
            "018_learning_analysis_provider_snapshot",
            "019_agent_permission_grants",
            "020_evidence_event_schema_version",
            "021_learning_guided_setup",
            "022_learning_verifications",
            "023_verification_submissions",
            "024_verification_evidence",
        ]
        assert database.fetchone(
            "SELECT display_name FROM local_identity WHERE id='upgrade-owner'"
        )["display_name"] == "Upgrade learner"
        upgraded_event = dict(
            database.fetchone(
                "SELECT * FROM learning_evidence_event WHERE id='legacy-evidence-event'"
            )
        )
        assert upgraded_event["schema_version"] == 1
        assert upgraded_event["event_hash"] == _event_hash(upgraded_event)
        assert database.fetchone("PRAGMA integrity_check")[0] == "ok"
        assert database.fetchall("PRAGMA foreign_key_check") == []
    finally:
        database.close()


def test_independent_entry_rejects_default_before_open(database_access_guard):
    from app.config import PROJECT_ROOT
    with pytest.raises(ValueError, match="default"):
        open_learning_database(PROJECT_ROOT / "data" / "nautilus.sqlite3")
    assert database_access_guard["isolated_connections"] == 0


def test_independent_entry_rejects_legacy_database_without_migrating(tmp_path):
    path = tmp_path / "legacy-probe.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT)")
        connection.execute("INSERT INTO schema_migrations VALUES ('001_initial', 'synthetic-time')")
        connection.commit()
    with pytest.raises(ValueError, match="independent"):
        open_learning_database(path)
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='learning_action'").fetchone() is None


def test_binding_requires_matching_reviewed_standard(domain_rows):
    repository = LearningRepository(domain_rows, Principal.user("owner-a"))
    assert repository.validate_binding("action-a", "outcome-a", None)["reason"] == "no_criterion"
    binding = repository.validate_binding("action-a", "outcome-a", "criterion-a-approved")
    assert binding["criterion"]["version"] == 1
    with pytest.raises(DomainError, match="criterion_not_approved"):
        repository.validate_binding("action-a", "outcome-a", "criterion-a-candidate")
    with pytest.raises(DomainError, match="not_found"):
        repository.validate_binding("action-a", "outcome-a", "criterion-b-approved")
    with pytest.raises(DomainError, match="not_found"):
        repository.action("action-b")


def test_binding_rejects_context_mismatch(domain_rows):
    with domain_rows.transaction() as connection:
        connection.execute("UPDATE learning_action SET context_key='different-context' WHERE id='action-a'")
    with pytest.raises(DomainError, match="criterion_out_of_scope"):
        LearningRepository(domain_rows, Principal.user("owner-a")).validate_binding(
            "action-a", "outcome-a", "criterion-a-approved"
        )


def test_standard_version_is_immutable_and_owner_foreign_key_is_enforced(domain_rows):
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with domain_rows.transaction() as connection:
            connection.execute("UPDATE learning_criterion_version SET source='changed' WHERE id='criterion-a-approved'")
    with pytest.raises(sqlite3.IntegrityError):
        with domain_rows.transaction() as connection:
            connection.execute("""INSERT INTO learning_delegation
                (id, owner_id, action_id, outcome_id, criterion_id, contract_version, status, version, created_at)
                VALUES ('delegation-a', 'owner-a', 'action-b', 'outcome-a', NULL, 1, 'ready', 1, 'synthetic-time')""")


def test_agent_cannot_read_action_outside_assigned_scope(domain_rows):
    agent = Principal.agent("owner-a", "agent-a", action_ids=frozenset(), tools=frozenset())
    with pytest.raises(DomainError, match="permission_denied"):
        LearningRepository(domain_rows, agent).action("action-a")


def test_failed_domain_migration_is_atomic(tmp_path):
    from app.db import Database
    from app.config import Settings

    staged = tmp_path / "staged"
    staged.mkdir()
    source = Settings.from_env().migrations_dir / "011_nautilus_learning_domain.sql"
    (staged / source.name).write_text(source.read_text() + "\nINSERT INTO nonexistent VALUES (1);\n")
    path = tmp_path / "failure.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        Database(path, staged, migration_floor=11, migration_ceiling=None)
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT version FROM schema_migrations").fetchall() == []
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='learning_action'").fetchall() == []


@pytest.fixture
def stored_artifact(domain_rows):
    database = domain_rows
    with database.transaction() as connection:
        connection.execute("""INSERT INTO learning_delegation VALUES
            ('delegation-a', 'owner-a', 'action-a', 'outcome-a', 'criterion-a-approved', 1, 'active', 1, 'synthetic-time')""")
        connection.execute("""INSERT INTO learning_contract_version VALUES
            ('delegation-a', 'owner-a', 1, 'Synthetic boundary', 'Synthetic stop', 10, 'criterion-a-approved', 'synthetic-time')""")
        connection.execute("""INSERT INTO learning_session VALUES
            ('session-a', 'owner-a', 'delegation-a', 1, 'running', 'synthetic-time', NULL, 1)""")
        connection.execute("""INSERT INTO learning_command VALUES
            ('command-a', 'owner-a', 'owner-a', 'request-a', 'SyntheticCommand', ?, '{}', 'synthetic-time')""", ("0" * 64,))
        connection.execute("""INSERT INTO learning_event
            (event_id, owner_id, aggregate_type, aggregate_id, aggregate_version, event_type, event_version,
             command_id, idempotency_key, actor_id, actor_kind, occurred_at, recorded_at,
             payload_json, metadata_json, projection_version, privacy, event_hash)
            VALUES ('event-a', 'owner-a', 'artifact', 'artifact-a', 1, 'artifact.created', 1,
                    'command-a', 'request-a', 'owner-a', 'user', 'synthetic-time', 'synthetic-time',
                    '{}', '{}', 1, 'metadata', ?)""", ("0" * 64,))
        connection.execute("""INSERT INTO learning_raw_artifact VALUES
            ('artifact-a', 1, 'owner-a', 'session-a', 'event-a', 'synthetic-output', ?, 'private', 'synthetic-time', NULL)""",
            (hashlib.sha256(b"synthetic-output").hexdigest(),))
        connection.execute("""INSERT INTO learning_artifact VALUES
            ('artifact-a', 'owner-a', 1, 'visible', 'eligible', 1)""")
    return database


@pytest.mark.parametrize("statement", [
    "UPDATE learning_raw_artifact SET content='changed'",
    "DELETE FROM learning_raw_artifact",
    "UPDATE learning_event SET payload_json='{}'",
    "DELETE FROM learning_event",
    "INSERT INTO learning_session VALUES ('session-b','owner-a','delegation-a',1,'running','synthetic-time',NULL,1)",
    "INSERT INTO learning_raw_artifact SELECT * FROM learning_raw_artifact",
    "INSERT INTO learning_projection_position VALUES ('owner-b','artifact','artifact-a',1,1,'event-a')",
    "INSERT INTO learning_projection_position VALUES ('owner-a','artifact','artifact-a',0,1,'event-a')",
    "INSERT INTO learning_analysis_run (id, owner_id, artifact_id, content_version, fact_event_id, criterion_id, request_key, attempt, status, reason, created_at, finished_at) VALUES ('run-a','owner-a','artifact-a',2,'event-a',NULL,'request',1,'blocked_no_criterion','missing','synthetic-time',NULL)",
])
def test_storage_invariants_reject_invalid_writes(stored_artifact, statement):
    with pytest.raises(sqlite3.IntegrityError):
        with stored_artifact.transaction() as connection:
            connection.execute(statement)


@pytest.mark.parametrize("overrides", [
    {"event_id": "event-a", "aggregate_version": 2},
    {"event_id": "event-b"},
    {"event_id": "event-b", "aggregate_version": 0},
    {"event_id": "event-b", "aggregate_version": 2, "event_version": 0},
    {"event_id": "event-b", "aggregate_version": 2, "owner_id": "owner-b"},
    {"event_id": "event-b", "aggregate_version": 2, "idempotency_key": "different-key"},
])
def test_event_unique_version_and_command_scope_constraints(stored_artifact, overrides):
    event = dict(stored_artifact.fetchone("SELECT * FROM learning_event"))
    del event["position"]
    event.update(overrides)
    with pytest.raises(sqlite3.IntegrityError):
        with stored_artifact.transaction() as connection:
            connection.execute(
                f"INSERT INTO learning_event ({','.join(event)}) VALUES ({','.join('?' for _ in event)})",
                tuple(event.values()),
            )


def test_real_domain_schema_backup_and_recovery(tmp_path, stored_artifact):
    from app.config import Settings
    from isolated_storage import RecoveryWorkspace

    staged = tmp_path / "domain-migrations"
    staged.mkdir()
    migrations_dir = Settings.from_env().migrations_dir
    for source in sorted(migrations_dir.glob("*.sql")):
        if int(source.name[:3]) >= 11:
            (staged / source.name).write_bytes(source.read_bytes())
    with RecoveryWorkspace(staged) as workspace:
        database = workspace.create_database()
        stored_artifact.connection.backup(database.connection)
        restored = workspace.restore(workspace.backup(database))
        assert workspace.verify(restored) == workspace.verify(database)
        assert restored.fetchone("SELECT COUNT(*) FROM learning_raw_artifact")[0] == 1
        assert restored.fetchone("SELECT COUNT(*) FROM learning_event")[0] == 1
        assert restored.fetchone("SELECT COUNT(*) FROM learning_artifact")[0] == 1


def test_invalid_recipe_and_unavailable_standard_are_rejected(domain_rows):
    with domain_rows.transaction() as connection:
        connection.execute("""INSERT INTO learning_criterion_version
            SELECT 'invalid-criterion', owner_id, package_id, outcome_id, 3, source, context_key,
                   '{"dimensions": []}', review_status, reviewed_by, reviewed_at, created_at
            FROM learning_criterion_version WHERE id='criterion-a-approved'""")
    repository = LearningRepository(domain_rows, Principal.user("owner-a"))
    with pytest.raises(DomainError, match="criterion_invalid_recipe"):
        repository.validate_binding("action-a", "outcome-a", "invalid-criterion")
    with domain_rows.transaction() as connection:
        connection.execute("INSERT INTO learning_criterion_availability VALUES ('owner-a', 'criterion-a-approved', 'retired', 'synthetic-time')")
    with pytest.raises(DomainError, match="criterion_unavailable"):
        repository.validate_binding("action-a", "outcome-a", "criterion-a-approved")
