"""The synthetic UI demo must preserve old data and remain replayable."""
import importlib.util
from pathlib import Path

import pytest

from app.core.commands import CreateDelegation, CreateLearningAction, StartSession
from app.learning_service import LearningService
from app.learning_storage import open_learning_database


def load_demo():
    script = Path(__file__).resolve().parents[2] / "scripts/seed-outcome-graph-demo.py"
    spec = importlib.util.spec_from_file_location("outcome_graph_demo", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def demo_database(tmp_path, monkeypatch):
    demo = load_demo()
    # Simulate the exact trial destination inside pytest's protected isolation.
    monkeypatch.setattr(demo, "PROJECT_ROOT", tmp_path)
    directory = tmp_path / "tmp/nautilus-trial-20260919"
    directory.mkdir(parents=True)
    database = open_learning_database(directory / "learning.sqlite3")
    identity = {"id": "demo-test-owner", "device_id": "demo-test-device", "display_name": "合成测试",
                "timezone": "Asia/Shanghai", "created_at": demo.STAMP}
    learning = LearningService(database)
    principal = learning.principal(identity)
    with database.transaction() as connection:
        connection.execute("INSERT INTO learning_model_defaults VALUES (?,?,?,?)",
                           (identity["id"], '{"reasoning_effort":"medium"}', 1, demo.STAMP))
    yield demo, directory, database, learning, principal, identity
    database.close()


def test_demo_is_idempotent_preserves_existing_rows_and_replays(demo_database):
    demo, directory, database, learning, principal, identity = demo_database
    before = demo.snapshot(database)
    first = demo.seed(directory, demo=True)
    second = demo.seed(directory, demo=True)
    assert second["inserted_rows"] == {}
    assert first["database_digest"] == second["database_digest"]
    assert not any(rows - demo.snapshot(database)[table] for table, rows in before.items())
    assert len(first["outcome_ids"]) == 10
    assert len(first["relation_ids"]) == 12
    assert len(first["artifact_ids"]) == 5
    assert first["coverage"] == {
        "strip": "supported", "split": "supported", "normalize": "no_standard",
        "extract": "conflicting", "groups": "unknown", "capture": "provisional", "unicode": "no_standard",
        "root": "unknown", "clean": "unknown", "regex": "unknown",
    }
    assert database.fetchone("SELECT COUNT(*) FROM learning_session WHERE status='running'")[0] == 0
    assert {row[0] for row in database.fetchall("SELECT DISTINCT relation_type FROM learning_outcome_relation")} == {
        "contains", "prerequisite", "equivalent", "overlap"}
    assert not database.fetchone("SELECT 1 FROM learning_outcome_relation WHERE source_outcome_id=? OR target_outcome_id=?",
                                 (first["outcome_ids"]["unicode"], first["outcome_ids"]["unicode"]))
    assert database.fetchone("PRAGMA integrity_check")[0] == "ok"
    assert database.fetchall("PRAGMA foreign_key_check") == []
    assert learning.core.replay(principal)["comparison"]["matched"]
    assert database.fetchall("PRAGMA foreign_key_check") == []


def test_demo_rejects_running_session_before_data_writes(demo_database):
    demo, directory, database, learning, principal, identity = demo_database
    standard = database.fetchone("SELECT * FROM learning_criterion_version LIMIT 1")
    action = learning.core.execute(principal, CreateLearningAction(title="已有合成任务",
        context_key=standard["context_key"]), "existing-action")
    delegation = learning.core.execute(principal, CreateDelegation(action_id=action["id"],
        outcome_id=standard["outcome_id"], criterion_id=standard["id"], boundaries="已有合成测试",
        stop_conditions="保留原会话", expected_version=1), "existing-delegation")
    session = learning.core.execute(principal, StartSession(delegation_id=delegation["id"], expected_version=2), "existing-session")
    before = demo.snapshot_digest(demo.snapshot(database))
    with pytest.raises(ValueError, match="existing running learning session"):
        demo.seed(directory, demo=True)
    assert demo.snapshot_digest(demo.snapshot(database)) == before
    assert database.fetchone("SELECT status FROM learning_session WHERE id=?", (session["id"],))[0] == "running"


def test_demo_requires_confirmation_allowed_direct_path_and_existing_owner(demo_database, tmp_path):
    demo, directory, database, learning, principal, identity = demo_database
    before = demo.snapshot_digest(demo.snapshot(database))
    with pytest.raises(ValueError, match="explicit --demo"):
        demo.seed(directory)
    with pytest.raises(ValueError, match="demo target"):
        demo.seed(tmp_path, demo=True)
    alias = tmp_path / "alias"
    alias.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        demo.seed(alias, demo=True)
    with pytest.raises(ValueError, match="existing unique owner"):
        demo.seed(directory, "missing-owner", demo=True)
    assert demo.snapshot_digest(demo.snapshot(database)) == before
