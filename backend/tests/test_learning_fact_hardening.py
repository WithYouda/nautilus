"""Task 3.1 regression hardening for the fact foundation."""

import json

import pytest

from app.core.commands import CorrectArtifact, CreateDelegation, CreateLearningAction, EndSession, SaveTextArtifact, StartSession
from app.core.events import event_digest
from app.learning_domain import DomainError, Principal
from test_learning_domain_commands import core, create_action, create_outcome, delegation_command  # noqa: F401
from test_learning_domain_schema import learning_database  # noqa: F401

USER = Principal.user("owner-a")
OTHER = Principal.user("owner-b")


@pytest.fixture
def running(core):
    action = create_action(core)
    outcome = create_outcome(core)
    delegation = core.execute(USER, delegation_command(action["id"], outcome["id"]), "delegation")
    session = core.execute(USER, StartSession(delegation_id=delegation["id"], expected_version=2), "session")
    return {"action": action, "outcome": outcome, "delegation": delegation, "session": session}


@pytest.fixture
def approved_running(core):
    recipe = {"dimensions": [{"id": "synthetic_dimension", "label": "Synthetic dimension",
        "requirements": [{"method": "independent_review", "condition": "independent", "minimum": 1}]}]}
    with core.database.transaction() as connection:
        connection.execute(
            "INSERT INTO learning_outcome VALUES ('approved-outcome', 'owner-a', 'Synthetic object', "
            "'Synthetic behavior', 'synthetic-context', 'user', '2026-09-05T00:00:00Z')"
        )
        connection.execute(
            "INSERT INTO learning_standard_package VALUES ('approved-package', 'owner-a', "
            "'Synthetic standard', 'test-fixture', 'synthetic-context')"
        )
        connection.execute(
            """INSERT INTO learning_criterion_version
            (id, owner_id, package_id, outcome_id, version, source, context_key, recipe_json,
             review_status, reviewed_by, reviewed_at, created_at)
            VALUES ('approved-criterion', 'owner-a', 'approved-package', 'approved-outcome', 1,
                    'test-fixture', 'synthetic-context', ?, 'approved', 'synthetic-reviewer',
                    '2026-09-05T00:00:00Z', '2026-09-05T00:00:00Z')""",
            (json.dumps(recipe),),
        )
    action = create_action(core)
    delegation = core.execute(
        USER,
        CreateDelegation(
            action_id=action["id"], outcome_id="approved-outcome", criterion_id="approved-criterion",
            boundaries="Synthetic boundaries", stop_conditions="Synthetic stop", expected_version=1,
        ),
        "approved-delegation",
    )
    session = core.execute(USER, StartSession(delegation_id=delegation["id"], expected_version=2), "approved-session")
    return {"action": action, "delegation": delegation, "session": session}


def save(core, running, content="  Synthetic output\n\n", key="save"):
    return core.execute(
        USER,
        SaveTextArtifact(session_id=running["session"]["id"], content=content, expected_version=3),
        key,
    )


def damage_projections(database):
    database.connection.executescript("PRAGMA foreign_keys=OFF")
    with database.transaction() as connection:
        for table in (
            "learning_analysis_run", "learning_artifact", "learning_session", "learning_contract_version",
            "learning_delegation", "learning_outcome", "learning_action", "learning_stream_head",
            "learning_projection_position",
        ):
            connection.execute(f"DELETE FROM {table}")
    database.connection.executescript("PRAGMA foreign_keys=ON")


def remove_event_guards(database):
    database.connection.executescript("DROP TRIGGER learning_event_no_update; DROP TRIGGER learning_event_no_delete;")


def test_replay_uses_aggregate_versions_not_global_positions(core):
    create_action(core)
    other_action = core.execute(
        OTHER,
        CreateLearningAction(
            title="Synthetic owner-b action", context_key="synthetic-context"
        ),
        "owner-b-action",
    )
    result = core.replay(OTHER)
    assert result["status"] == "succeeded"
    assert result["event_count"] == 1
    row = core.database.fetchone("SELECT version FROM learning_action WHERE owner_id=? AND id=?", ("owner-b", other_action["id"]))
    assert row[0] == 1


def test_replay_rebuilds_all_fact_projections_and_allows_future_writes(core, running):
    artifact = save(core, running)
    before = {
        "action": core.database.fetchone("SELECT COUNT(*) FROM learning_action")[0],
        "outcome": core.database.fetchone("SELECT COUNT(*) FROM learning_outcome")[0],
        "delegation": core.database.fetchone("SELECT COUNT(*) FROM learning_delegation")[0],
        "session": core.database.fetchone("SELECT COUNT(*) FROM learning_session")[0],
        "artifact": core.database.fetchone("SELECT COUNT(*) FROM learning_artifact")[0],
        "raw": core.database.fetchone("SELECT COUNT(*) FROM learning_raw_artifact")[0],
    }
    damage_projections(core.database)
    result = core.replay(USER)
    assert result["status"] == "succeeded"
    assert result["event_count"] == 5
    assert result["aggregate_count"] == 2
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_action")[0] == before["action"]
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_outcome")[0] == before["outcome"]
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_delegation")[0] == before["delegation"]
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_session")[0] == before["session"]
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_artifact")[0] == before["artifact"]
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_raw_artifact")[0] == before["raw"]
    assert core.database.fetchone("SELECT content FROM learning_raw_artifact WHERE artifact_id=?", (artifact["id"],))["content"] == "  Synthetic output\n\n"
    head = core.database.fetchone("SELECT event_count FROM learning_stream_head WHERE aggregate_type='action'")
    assert head[0] == 4
    assert core.database.fetchall("PRAGMA foreign_key_check") == []
    ended = core.execute(USER, EndSession(session_id=running["session"]["id"], disposition="ended", expected_version=4), "after-replay")
    assert ended["version"] == 5


def test_repeated_corrections_append_three_versions(core, running):
    artifact = save(core, running)
    second = core.execute(USER, CorrectArtifact(artifact_id=artifact["id"], content="Synthetic correction 2", expected_version=4), "correction-2")
    third = core.execute(USER, CorrectArtifact(artifact_id=artifact["id"], content="Synthetic correction 3", expected_version=5), "correction-3")
    assert second["version"] == 5
    assert third["version"] == 6
    assert [row[0] for row in core.database.fetchall(
        "SELECT content_version FROM learning_raw_artifact WHERE artifact_id=? ORDER BY content_version", (artifact["id"],)
    )] == [1, 2, 3]
    assert core.artifact(USER, artifact["id"])["content"] == "Synthetic correction 3"
    assert core.artifact(USER, artifact["id"], content_version=1)["content"] == "  Synthetic output\n\n"


def test_approved_criterion_does_not_create_blocked_analysis(core, approved_running):
    save(core, approved_running, key="approved-save")
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_analysis_run")[0] == 0
    assert core.database.fetchone("SELECT criterion_id FROM learning_delegation")[0] == "approved-criterion"


def test_no_criterion_still_creates_blocked_analysis(core, running):
    save(core, running)
    row = core.database.fetchone("SELECT criterion_id, status, reason FROM learning_analysis_run")
    assert tuple(row) == (None, "blocked_no_criterion", "no approved criterion")


def test_replay_and_reads_reject_agent_and_mismatched_user_principal(core, running):
    action_id = running["action"]["id"]
    artifact = save(core, running)
    agent = Principal.agent("owner-a", "agent-a", action_ids=frozenset({action_id}), tools=frozenset())
    mismatched = Principal("owner-a", "not-owner-a", "user")
    with pytest.raises(DomainError, match="permission_denied"):
        core.replay(agent)
    with pytest.raises(DomainError, match="permission_denied"):
        core.replay(mismatched)
    with pytest.raises(DomainError, match="permission_denied"):
        core.events(agent, action_id)
    with pytest.raises(DomainError, match="permission_denied"):
        core.events(mismatched, action_id)
    with pytest.raises(DomainError, match="permission_denied"):
        core.artifact(agent, artifact["id"])
    with pytest.raises(DomainError, match="permission_denied"):
        core.artifact(mismatched, artifact["id"])
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_audit WHERE operation='Replay' AND reason_code='permission_denied'")[0] == 2


def test_replay_after_correction_validates_existing_raw_artifact(core, running):
    artifact = save(core, running)
    correction = core.execute(
        USER,
        CorrectArtifact(
            artifact_id=artifact["id"],
            content="Synthetic correction",
            expected_version=4,
        ),
        "correction-before-replay",
    )
    assert correction["version"] == 5

    result = core.replay(USER)
    assert result["status"] == "succeeded"
    assert result["event_count"] == 6
    assert result["aggregate_count"] == 2
    assert core.artifact(USER, artifact["id"])["content_version"] == 2
    assert core.artifact(USER, artifact["id"])["content"] == "Synthetic correction"
    assert core.database.fetchone(
        "SELECT event_count FROM learning_stream_head WHERE aggregate_type='action'"
    )[0] == 5


def test_replay_rejects_broken_previous_hash_and_preserves_projection(core, running):
    save(core, running)
    before = [tuple(row) for row in core.database.fetchall("SELECT * FROM learning_session")]
    remove_event_guards(core.database)
    with core.database.transaction() as connection:
        connection.execute("UPDATE learning_event SET previous_hash=? WHERE event_type='delegation.created'", ("1" * 64,))
        row = dict(connection.execute("SELECT * FROM learning_event WHERE event_type='delegation.created'").fetchone())
        connection.execute("UPDATE learning_event SET event_hash=? WHERE event_id=?", (event_digest(row), row["event_id"]))
    with pytest.raises(DomainError, match="event_chain_invalid"):
        core.replay(USER)
    assert [tuple(row) for row in core.database.fetchall("SELECT * FROM learning_session")] == before
    assert core.database.fetchall("PRAGMA foreign_key_check") == []


@pytest.mark.parametrize(
    ("column", "value", "reason"),
    [
        ("event_version", 999, "event_version_unsupported"),
        ("projection_version", 999, "projection_version_unsupported"),
    ],
)
def test_replay_rejects_unsupported_versions_after_rehash(core, running, column, value, reason):
    save(core, running)
    before = [tuple(row) for row in core.database.fetchall("SELECT * FROM learning_session")]
    remove_event_guards(core.database)
    with core.database.transaction() as connection:
        connection.execute(f"UPDATE learning_event SET {column}=? WHERE event_type='session.started'", (value,))
        row = dict(connection.execute("SELECT * FROM learning_event WHERE event_type='session.started'").fetchone())
        connection.execute("UPDATE learning_event SET event_hash=? WHERE event_id=?", (event_digest(row), row["event_id"]))
    with pytest.raises(DomainError, match=reason):
        core.replay(USER)
    assert [tuple(row) for row in core.database.fetchall("SELECT * FROM learning_session")] == before


def test_replay_requires_raw_output_for_artifact_events(core, running):
    artifact = save(core, running)
    remove_event_guards(core.database)
    core.database.connection.executescript("DROP TRIGGER learning_raw_artifact_no_delete; PRAGMA foreign_keys=OFF")
    with core.database.transaction() as connection:
        connection.execute("DELETE FROM learning_raw_artifact WHERE artifact_id=?", (artifact["id"],))
    core.database.connection.executescript("PRAGMA foreign_keys=ON")
    with pytest.raises(DomainError, match="artifact_source_missing"):
        core.replay(USER)
