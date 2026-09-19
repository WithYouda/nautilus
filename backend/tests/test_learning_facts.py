"""Task 3: INV-001/002/004/005 and CAP-FACT-001/002."""

import json

import pytest

from app.core.commands import CorrectArtifact, EndSession, SaveTextArtifact, StartSession
from app.learning_domain import DomainError, Principal
from test_learning_domain_commands import core, create_action, create_outcome, delegation_command  # noqa: F401
from test_learning_domain_schema import learning_database  # noqa: F401

USER = Principal.user("owner-a")


@pytest.fixture
def running(core):
    action = create_action(core)
    outcome = create_outcome(core)
    delegation = core.execute(USER, delegation_command(action["id"], outcome["id"]), "delegation")
    session = core.execute(USER, StartSession(delegation_id=delegation["id"], expected_version=2), "session")
    return {"action": action, "outcome": outcome, "delegation": delegation, "session": session}


def save(core, running, content="  Synthetic output\n\n"):
    return core.execute(USER, SaveTextArtifact(session_id=running["session"]["id"], content=content, expected_version=3), "save")


def test_start_unknown_or_conflicting_session_is_rejected(core, running):
    with pytest.raises(DomainError, match="not_found"):
        core.execute(USER, StartSession(delegation_id="missing", expected_version=3), "bad-start")
    with pytest.raises(DomainError, match="session_already_running"):
        core.execute(USER, StartSession(delegation_id=running["delegation"]["id"], expected_version=3), "second-start")
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_session")[0] == 1


def test_artifact_preserves_exact_text_and_separates_event_context(core, running):
    artifact = save(core, running)
    saved = core.artifact(USER, artifact["id"])
    assert saved["content"] == "  Synthetic output\n\n"
    assert saved["session_id"] == running["session"]["id"]
    event = core.database.fetchone("SELECT * FROM learning_event WHERE event_id=?", (artifact["event_id"],))
    payload = json.loads(event["payload_json"])
    assert "content" not in payload
    assert payload["session_id"] == saved["session_id"]
    assert payload["content_version"] == saved["content_version"] == 1
    assert saved["fact_event_id"] == event["event_id"]
    assert core.database.fetchone("SELECT status FROM learning_analysis_run")[0] == "blocked_no_criterion"
    assert save(core, running) == artifact
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_raw_artifact")[0] == 1


def test_save_unknown_or_foreign_session_leaves_no_artifact(core, running):
    with pytest.raises(DomainError, match="not_found"):
        core.execute(USER, SaveTextArtifact(session_id="missing", content="Synthetic", expected_version=3), "unknown")
    with pytest.raises(DomainError, match="not_found"):
        core.execute(Principal.user("owner-b"), SaveTextArtifact(session_id=running["session"]["id"], content="Synthetic", expected_version=3), "foreign")
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_raw_artifact")[0] == 0


def test_original_artifact_and_event_roll_back_on_save_failure(core, running):
    core.database.connection.executescript("""CREATE TRIGGER fail_artifact BEFORE INSERT ON learning_artifact
        BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END;""")
    before = core.database.fetchone("SELECT COUNT(*) FROM learning_event")[0]
    with pytest.raises(DomainError, match="storage_failure"):
        save(core, running)
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_raw_artifact")[0] == 0
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_event")[0] == before


@pytest.mark.parametrize("disposition", ["ended", "interrupted"])
def test_end_or_interrupt_preserves_artifact_and_allows_new_session(core, running, disposition):
    artifact = save(core, running)
    command = EndSession(session_id=running["session"]["id"], disposition=disposition, expected_version=4)
    ended = core.execute(USER, command, "end")
    assert core.execute(USER, command, "end") == ended
    assert core.database.fetchone("SELECT status FROM learning_session")[0] == disposition
    assert core.database.fetchone("SELECT status FROM learning_delegation")[0] == "active"
    assert core.artifact(USER, artifact["id"])["content"] == "  Synthetic output\n\n"
    with pytest.raises(DomainError, match="session_not_running"):
        core.execute(USER, command, "end-again")
    resumed = core.execute(USER, StartSession(delegation_id=running["delegation"]["id"], expected_version=5), "resume")
    assert resumed["id"] != running["session"]["id"]


def test_correction_appends_version_and_preserves_original(core, running):
    artifact = save(core, running)
    with pytest.raises(DomainError, match="not_found"):
        core.execute(USER, CorrectArtifact(artifact_id="missing", content="Synthetic correction", expected_version=4), "bad-correction")
    corrected = core.execute(USER, CorrectArtifact(artifact_id=artifact["id"], content="Synthetic correction", expected_version=4), "correction")
    assert corrected["id"] == artifact["id"]
    assert core.artifact(USER, artifact["id"])["content_version"] == 2
    assert core.artifact(USER, artifact["id"], content_version=1)["content"] == "  Synthetic output\n\n"
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_raw_artifact")[0] == 2


def test_artifact_read_requires_user_scope(core, running):
    artifact = save(core, running)
    with pytest.raises(DomainError, match="not_found"):
        core.artifact(Principal.user("owner-b"), artifact["id"])
    agent = Principal.agent("owner-a", "agent-a", action_ids=frozenset({running["action"]["id"]}), tools=frozenset())
    with pytest.raises(DomainError, match="permission_denied"):
        core.artifact(agent, artifact["id"])


def test_replay_is_consistent_and_recovers_missing_projection(core, running):
    artifact = save(core, running)
    first = core.replay(USER)
    assert first["status"] == "succeeded"
    assert first["event_count"] == 5
    core.database.connection.execute("PRAGMA foreign_keys=OFF")
    core.database.connection.execute("DELETE FROM learning_action")
    core.database.connection.execute("PRAGMA foreign_keys=ON")
    rebuilt = core.replay(USER)
    assert rebuilt["projection_digest"] == first["projection_digest"]
    assert core.artifact(USER, artifact["id"])["content"] == "  Synthetic output\n\n"
    assert core.database.fetchall("PRAGMA foreign_key_check") == []


@pytest.mark.parametrize("damage,reason", [
    ("UPDATE learning_event SET event_version=999 WHERE event_type='artifact.created'", "event_version_unsupported"),
    ("DELETE FROM learning_event WHERE event_type='session.started'", "event_gap"),
    ("UPDATE learning_event SET payload_json='{}' WHERE event_type='artifact.created'", "event_integrity_failed"),
])
def test_failed_replay_preserves_current_projection_and_is_audited(core, running, damage, reason):
    artifact = save(core, running)
    before = [tuple(row) for row in core.database.fetchall("SELECT * FROM learning_action")]
    core.database.connection.executescript("DROP TRIGGER learning_event_no_update; DROP TRIGGER learning_event_no_delete;")
    core.database.connection.execute(damage)
    with pytest.raises(DomainError, match=reason):
        core.replay(USER)
    assert [tuple(row) for row in core.database.fetchall("SELECT * FROM learning_action")] == before
    assert core.artifact(USER, artifact["id"])["content"] == "  Synthetic output\n\n"
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_audit WHERE operation='Replay' AND result='rejected'")[0] == 1
