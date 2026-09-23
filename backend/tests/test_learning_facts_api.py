from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.auth import hash_token
from app.core.commands import CreateLearningAction
from app.learning_domain import DomainError, Principal


def authorize(client):
    challenge = client.get("/api/auth/challenge").json()["code"]
    response = client.post("/api/auth/authorize", json={"access_token": challenge})
    assert response.status_code == 200
    return response.json()["identity"]


def create_fact_chain(client):
    action = client.post(
        "/api/learning/actions",
        json={
            "title": "API 学习行动",
            "context_key": "api-context",
            "idempotency_key": "api-action",
        },
    )
    assert action.status_code == 201
    outcome = client.post(
        "/api/learning/outcomes",
        json={
            "object_description": "一个可验证对象",
            "behavior": "能独立完成说明",
            "context_key": "api-context",
            "idempotency_key": "api-outcome",
        },
    )
    assert outcome.status_code == 201

    action_id = action.json()["id"]
    outcome_id = outcome.json()["id"]
    delegation = client.post(
        "/api/learning/delegations",
        json={
            "action_id": action_id,
            "outcome_id": outcome_id,
            "criterion_id": None,
            "boundaries": "只保存事实",
            "stop_conditions": "完成一次文本产出",
            "time_budget_minutes": 30,
            "expected_version": 1,
            "idempotency_key": "api-delegation",
        },
    )
    assert delegation.status_code == 201

    session = client.post(
        "/api/learning/sessions",
        json={
            "delegation_id": delegation.json()["id"],
            "expected_version": 2,
            "idempotency_key": "api-session",
        },
    )
    assert session.status_code == 201

    artifact = client.post(
        "/api/learning/artifacts",
        json={
            "session_id": session.json()["id"],
            "content": "第一版学习产出",
            "expected_version": 3,
            "idempotency_key": "api-artifact",
        },
    )
    assert artifact.status_code == 201
    return {
        "action": action.json(),
        "outcome": outcome.json(),
        "delegation": delegation.json(),
        "session": session.json(),
        "artifact": artifact.json(),
    }


def test_learning_api_requires_authorization(client):
    response = client.get("/api/learning/state")
    assert response.status_code == 401
    assert response.json()["detail"] == "需要先完成本地授权"


def test_learning_database_is_independent_from_legacy_database(client):
    authorize(client)
    main_database = client.app.state.database
    learning_database = client.app.state.learning.database

    assert main_database.database_path != learning_database.database_path
    assert [row["version"] for row in main_database.fetchall("SELECT version FROM schema_migrations ORDER BY version")] == [
        "001_initial",
        "002_learning_plans",
        "003_dashboard_layouts",
        "004_plan_editor",
        "005_ai_conversations",
        "006_ai_message_reasoning",
        "007_ai_multi_provider_model_selection",
        "008_ai_conversation_titles",
        "009_task_completion_restore",
        "010_ai_conversation_scope",
    ]
    assert [row["version"] for row in learning_database.fetchall("SELECT version FROM schema_migrations ORDER BY version")] == [
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
        "025_evidence_provenance",
        "026_replay_checks",
        "027_learning_continuity",
        "028_verification_discussions",
        "029_discussion_reasoning",
    ]


def test_full_fact_flow_no_standard_correction_and_replay(client):
    identity = authorize(client)
    created = create_fact_chain(client)

    state = client.get("/api/learning/state").json()
    assert len(state["actions"]) == 1
    assert len([outcome for outcome in state["outcomes"] if outcome["source"] == "user"]) == 1
    assert len([outcome for outcome in state["outcomes"] if outcome["source"] == "standard"]) == 1
    assert len(state["delegations"]) == 1
    assert len(state["sessions"]) == 1
    assert len(state["artifacts"]) == 1
    assert state["delegations"][0]["criterion_id"] is None
    assert state["analysis_runs"][0]["status"] == "blocked_no_criterion"
    assert state["analysis_runs"][0]["reason"] == "no approved criterion"

    duplicate = client.post(
        "/api/learning/artifacts",
        json={
            "session_id": created["session"]["id"],
            "content": "第一版学习产出",
            "expected_version": 3,
            "idempotency_key": "api-artifact",
        },
    )
    assert duplicate.status_code == 201
    assert duplicate.json() == created["artifact"]
    assert len(client.get("/api/learning/state").json()["artifacts"]) == 1

    ended = client.post(
        f"/api/learning/sessions/{created['session']['id']}/end",
        json={
            "disposition": "ended",
            "expected_version": 4,
            "idempotency_key": "api-end",
        },
    )
    assert ended.status_code == 200

    corrected = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/corrections",
        json={
            "content": "更正后的学习产出",
            "expected_version": 5,
            "idempotency_key": "api-correction",
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["version"] == 6

    detail = client.get(f"/api/learning/artifacts/{created['artifact']['id']}").json()
    assert detail["content_version"] == 2
    assert detail["content"] == "更正后的学习产出"

    events = client.get(f"/api/learning/actions/{created['action']['id']}/events").json()
    assert [event["event_type"] for event in events] == [
        "action.created",
        "delegation.created",
        "session.started",
        "artifact.created",
        "session.ended",
        "artifact.corrected",
    ]

    replay = client.post("/api/learning/replay")
    assert replay.status_code == 200, replay.json()
    assert replay.json()["status"] == "succeeded"
    assert replay.json()["event_count"] == 7
    assert replay.json()["aggregate_count"] == 2

    state_after_replay = client.get("/api/learning/state").json()
    assert state_after_replay["artifacts"][0]["content"] == "更正后的学习产出"
    assert state_after_replay["sessions"][0]["status"] == "ended"
    assert state_after_replay["actions"][0]["aggregate_version"] == 6

    learning_core = client.app.state.learning.core
    agent = Principal.agent(
        identity["id"],
        "agent-a",
        action_ids=frozenset({created["action"]["id"]}),
        tools=frozenset(),
    )
    with pytest.raises(DomainError, match="permission_denied"):
        learning_core.events(agent, created["action"]["id"])
    with pytest.raises(DomainError, match="permission_denied"):
        learning_core.execute(
            agent,
            CreateLearningAction(title="Agent action", context_key="api-context"),
            "agent-action",
        )


def test_cross_identity_http_access_is_rejected(client):
    authorize(client)
    created = create_fact_chain(client)

    main_database = client.app.state.database
    second_identity_id = "second-local-identity"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    expires_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(timespec="seconds").replace("+00:00", "Z")
    with main_database.transaction() as connection:
        connection.execute(
            """INSERT INTO local_identity
               (id, device_id, display_name, timezone, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (second_identity_id, "second-device", "第二身份", "Asia/Shanghai", now, now),
        )
        connection.execute(
            """INSERT INTO sessions
               (id, identity_id, token_hash, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("second-session", second_identity_id, hash_token("second-session-token"), now, expires_at),
        )

    client.cookies.set(client.app.state.settings.cookie_name, "second-session-token")
    state = client.get("/api/learning/state")
    assert state.status_code == 200
    assert state.json()["actions"] == []
    assert state.json()["artifacts"] == []

    artifact_response = client.get(f"/api/learning/artifacts/{created['artifact']['id']}")
    assert artifact_response.status_code == 404
    assert artifact_response.json()["detail"]["kind"] == "not_found"

    events_response = client.get(f"/api/learning/actions/{created['action']['id']}/events")
    assert events_response.status_code == 404
    assert events_response.json()["detail"]["kind"] == "not_found"
