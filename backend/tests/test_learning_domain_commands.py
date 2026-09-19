"""Task 2: INV-002/003/010 and CAP-FACT-001/002."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest
from pydantic import ValidationError

from app.core.commands import CreateDelegation, CreateLearningAction, CreateOutcome
from app.core.learning import LearningCore
from app.learning_domain import DomainError, Principal
from app.learning_storage import open_learning_database
from test_learning_domain_schema import learning_database  # noqa: F401


@pytest.fixture
def core(learning_database):
    return LearningCore(learning_database)


def create_action(core, key="create-action"):
    return core.execute(Principal.user("owner-a"), CreateLearningAction(
        title="Synthetic action", context_key="synthetic-context"
    ), key)


def create_outcome(core):
    return core.execute(Principal.user("owner-a"), CreateOutcome(
        object_description="Synthetic object", behavior="Synthetic behavior", context_key="synthetic-context"
    ), "create-outcome")


def delegation_command(action_id, outcome_id, expected_version=1):
    return CreateDelegation(action_id=action_id, outcome_id=outcome_id, criterion_id=None,
        boundaries="Synthetic boundaries", stop_conditions="Synthetic stop", expected_version=expected_version)


def test_create_action_retry_returns_original_result(core):
    first = create_action(core)
    assert create_action(core) == first
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_action")[0] == 1
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_command")[0] == 1
    events = core.events(Principal.user("owner-a"), first["id"])
    assert len(events) == 1
    assert events[0]["aggregate_version"] == 1
    assert events[0]["event_type"] == "action.created"
    assert core.database.fetchone("SELECT aggregate_version FROM learning_projection_position")[0] == 1


def test_same_key_different_request_is_audited_conflict(core):
    create_action(core)
    with pytest.raises(DomainError, match="idempotency_conflict"):
        core.execute(Principal.user("owner-a"), CreateLearningAction(
            title="Different synthetic action", context_key="synthetic-context"), "create-action")
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_event")[0] == 1
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_audit WHERE reason_code='idempotency_conflict'")[0] == 1


@pytest.mark.parametrize("statement", [
    "CREATE TRIGGER fail_projection BEFORE INSERT ON learning_action BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END;",
    "CREATE TRIGGER fail_event BEFORE INSERT ON learning_event BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END;",
    "CREATE TRIGGER fail_position BEFORE INSERT ON learning_projection_position BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END;",
    "CREATE TRIGGER fail_success_audit BEFORE INSERT ON learning_audit WHEN NEW.result='succeeded' BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END;",
])
def test_partial_write_rolls_back_command_event_and_projection(core, statement):
    core.database.connection.executescript(statement)
    with pytest.raises(DomainError, match="storage_failure"):
        create_action(core)
    for table in ("learning_action", "learning_event", "learning_command", "learning_stream_head", "learning_projection_position"):
        assert core.database.fetchone(f"SELECT COUNT(*) FROM {table}")[0] == 0


def test_cross_identity_writes_and_agent_writes_are_rejected(core):
    action = create_action(core)
    outcome = create_outcome(core)
    with pytest.raises(DomainError, match="not_found"):
        core.execute(Principal.user("owner-b"), delegation_command(action["id"], outcome["id"]), "foreign-command")
    with pytest.raises(DomainError, match="not_found"):
        core.events(Principal.user("owner-b"), action["id"])
    agent = Principal.agent("owner-a", "agent-a", action_ids=frozenset({action["id"]}), tools=frozenset())
    with pytest.raises(DomainError, match="permission_denied"):
        core.execute(agent, delegation_command(action["id"], outcome["id"]), "agent-command")
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_delegation")[0] == 0


def test_delegation_missing_outcome_leaves_no_partial_state(core):
    action = create_action(core)
    with pytest.raises(DomainError, match="not_found"):
        core.execute(Principal.user("owner-a"), delegation_command(action["id"], "missing"), "bad-delegation")
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_delegation")[0] == 0
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_contract_version")[0] == 0


def test_delegation_without_standard_preserves_contract_and_order(core):
    action = create_action(core)
    outcome = create_outcome(core)
    command = delegation_command(action["id"], outcome["id"])
    result = core.execute(Principal.user("owner-a"), command, "delegation-request")
    assert core.execute(Principal.user("owner-a"), command, "delegation-request") == result
    delegation = core.database.fetchone("SELECT * FROM learning_delegation")
    assert delegation["criterion_id"] is None
    assert delegation["status"] == "ready"
    assert core.database.fetchone("SELECT COUNT(*) FROM learning_contract_version")[0] == 1
    assert [event["aggregate_version"] for event in core.events(Principal.user("owner-a"), action["id"])] == [1, 2]


def test_stale_concurrent_command_has_one_winner(core):
    action = create_action(core)
    outcome = create_outcome(core)
    other_database = open_learning_database(core.database.database_path)
    other = LearningCore(other_database)

    def submit(instance, key):
        try:
            instance.execute(Principal.user("owner-a"), delegation_command(action["id"], outcome["id"]), key)
            return "succeeded"
        except DomainError as exc:
            return exc.code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(submit, instance, f"concurrent-{index}") for index, instance in enumerate((core, other))]
            assert sorted(f.result() for f in futures) == ["succeeded", "version_conflict"]
        assert core.database.fetchone("SELECT COUNT(*) FROM learning_delegation")[0] == 1
    finally:
        other_database.close()


def test_missing_projection_position_blocks_append(core):
    action = create_action(core)
    outcome = create_outcome(core)
    with core.database.transaction() as connection:
        connection.execute("DELETE FROM learning_projection_position WHERE aggregate_type='action'")
    with pytest.raises(DomainError, match="projection_gap"):
        core.execute(Principal.user("owner-a"), delegation_command(action["id"], outcome["id"]), "gap-command")


def test_outcome_and_action_fields_cannot_forge_learning_state():
    with pytest.raises(ValidationError):
        CreateLearningAction(title="Synthetic", context_key="synthetic-context", learning_state="supported")
    with pytest.raises(ValidationError):
        CreateOutcome(object_description="", behavior="Synthetic", context_key="synthetic-context")


def test_commit_failure_releases_transaction_and_rolls_back(core):
    core.database.connection.executescript("""
        CREATE TABLE deferred_probe(owner_id TEXT REFERENCES local_identity(id) DEFERRABLE INITIALLY DEFERRED);
    """)
    with pytest.raises(sqlite3.IntegrityError):
        with core.database.transaction(immediate=True) as connection:
            connection.execute("INSERT INTO deferred_probe VALUES ('missing-owner')")
    assert not core.database.connection.in_transaction
    assert core.database.fetchone("SELECT COUNT(*) FROM deferred_probe")[0] == 0
    assert create_action(core)["version"] == 1


def test_concurrent_identical_retries_create_one_fact(core):
    other_database = open_learning_database(core.database.database_path)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            requests = [executor.submit(create_action, instance) for instance in (core, LearningCore(other_database))]
            assert requests[0].result() == requests[1].result()
        assert core.database.fetchone("SELECT COUNT(*) FROM learning_event")[0] == 1
    finally:
        other_database.close()
