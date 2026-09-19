from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.auth import hash_token


def authorize(client):
    challenge = client.get("/api/auth/challenge").json()["code"]
    response = client.post("/api/auth/authorize", json={"access_token": challenge})
    assert response.status_code == 200
    return response.json()["identity"]


def create_action(client, title="Agent permission action"):
    response = client.post(
        "/api/learning/actions",
        json={
            "title": title,
            "context_key": "agent-permission-context",
            "idempotency_key": f"agent-action-{title}",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_request(client, action_id, key="agent-permission-key", granularity="metadata"):
    response = client.post(
        "/api/learning/agent/permission-requests",
        json={
            "purpose": "读取当前学习行动的事实摘要，用于恢复学习上下文。",
            "target_id": action_id,
            "content_granularity": granularity,
            "ttl_seconds": 300,
            "request_key": key,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_agent_permission_requires_authorization(client):
    response = client.get("/api/learning/agent/permission-requests")
    assert response.status_code == 401


def test_agent_permission_request_and_deny_are_persistent_and_audited(client):
    identity = authorize(client)
    action = create_action(client)
    request = create_request(client, action["id"])

    assert request["status"] == "pending"
    assert request["agent_id"] == "global-agent"
    assert request["scope"] == "learning_action"
    assert request["content_granularity"] == "metadata"

    duplicate = create_request(client, action["id"])
    assert duplicate == request

    rows = client.app.state.learning.database.fetchall(
        "SELECT operation, result, reason_code FROM learning_audit WHERE reference_id=? ORDER BY rowid",
        (request["id"],),
    )
    assert [tuple(row) for row in rows] == [("AgentPermissionRequest", "succeeded", None)]

    denied = client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/deny",
        json={"reason": "本次不需要 Agent 读取"},
    )
    assert denied.status_code == 200
    assert denied.json()["status"] == "denied"
    assert denied.json()["decision_reason"] == "本次不需要 Agent 读取"

    repeat = client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/deny",
        json={"reason": "再次拒绝"},
    )
    assert repeat.status_code == 200
    assert repeat.json()["decision_reason"] == "本次不需要 Agent 读取"

    rows = client.app.state.learning.database.fetchall(
        "SELECT operation, result, reason_code FROM learning_audit WHERE reference_id=? ORDER BY rowid",
        (request["id"],),
    )
    assert [tuple(row) for row in rows] == [
        ("AgentPermissionRequest", "succeeded", None),
        ("AgentPermissionDecision", "rejected", "permission_denied"),
    ]

    listed = client.get("/api/learning/agent/permission-requests").json()
    assert [item["id"] for item in listed] == [request["id"]]
    assert listed[0]["status"] == "denied"


def test_denied_agent_permission_does_not_block_fact_saving(client):
    authorize(client)
    action = create_action(client, "Permission denial save action")
    outcome = client.post(
        "/api/learning/outcomes",
        json={
            "object_description": "权限拒绝后的成果",
            "behavior": "仍能保存事实",
            "context_key": "agent-permission-context",
            "idempotency_key": "permission-outcome",
        },
    )
    assert outcome.status_code == 201
    delegation = client.post(
        "/api/learning/delegations",
        json={
            "action_id": action["id"],
            "outcome_id": outcome.json()["id"],
            "criterion_id": None,
            "boundaries": "",
            "stop_conditions": "保存一份产出",
            "time_budget_minutes": 30,
            "expected_version": 1,
            "idempotency_key": "permission-delegation",
        },
    )
    assert delegation.status_code == 201
    session = client.post(
        "/api/learning/sessions",
        json={
            "delegation_id": delegation.json()["id"],
            "expected_version": 2,
            "idempotency_key": "permission-session",
        },
    )
    assert session.status_code == 201

    request = create_request(client, action["id"], "permission-deny-save")
    denied = client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/deny",
        json={"reason": "拒绝后继续保存"},
    )
    assert denied.status_code == 200

    artifact = client.post(
        "/api/learning/artifacts",
        json={
            "session_id": session.json()["id"],
            "content": "拒绝 Agent 权限后保存的学习产出",
            "expected_version": 3,
            "idempotency_key": "permission-artifact",
        },
    )
    assert artifact.status_code == 201
    assert client.get(f"/api/learning/artifacts/{artifact.json()['id']}").json()["content"] == "拒绝 Agent 权限后保存的学习产出"


def test_agent_permission_rejects_missing_action_and_expires(client):
    authorize(client)
    missing = client.post(
        "/api/learning/agent/permission-requests",
        json={
            "purpose": "读取不存在的学习行动",
            "target_id": "missing-action",
            "content_granularity": "metadata",
            "ttl_seconds": 300,
            "request_key": "missing-action-key",
        },
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["kind"] == "not_found"

    action = create_action(client, "Expired permission action")
    request = create_request(client, action["id"], "expired-permission-key")
    expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    with client.app.state.learning.database.transaction() as connection:
        connection.execute(
            "UPDATE learning_agent_permission_request SET expires_at=? WHERE id=?",
            (expired_at, request["id"]),
        )

    listed = client.get("/api/learning/agent/permission-requests").json()
    assert listed[0]["status"] == "expired"
    assert listed[0]["decision_reason"] == "request expired"

    denied = client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/deny",
        json={"reason": "过期后拒绝"},
    )
    assert denied.status_code == 409
    assert denied.json()["detail"]["kind"] == "permission_request_not_pending"


def test_agent_permission_is_isolated_by_identity(client):
    authorize(client)
    action = create_action(client, "Cross identity permission action")
    request = create_request(client, action["id"], "cross-identity-key")

    database = client.app.state.database
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    expires_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    with database.transaction() as connection:
        connection.execute(
            """INSERT INTO local_identity
               (id, device_id, display_name, timezone, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("second-agent-identity", "second-agent-device", "第二身份", "Asia/Shanghai", now, now),
        )
        connection.execute(
            """INSERT INTO sessions
               (id, identity_id, token_hash, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("second-agent-session", "second-agent-identity", hash_token("second-agent-token"), now, expires_at),
        )

    client.cookies.set(client.app.state.settings.cookie_name, "second-agent-token")
    listed = client.get("/api/learning/agent/permission-requests")
    assert listed.status_code == 200
    assert listed.json() == []

    denied = client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/deny",
        json={"reason": "跨身份拒绝"},
    )
    assert denied.status_code == 404
    assert denied.json()["detail"]["kind"] == "not_found"


def create_fact_chain(client, prefix="agent-context"):
    action = client.post(
        "/api/learning/actions",
        json={
            "title": "Agent 上下文学习行动",
            "context_key": "agent-context",
            "idempotency_key": f"{prefix}-action",
        },
    )
    assert action.status_code == 201
    outcome = client.post(
        "/api/learning/outcomes",
        json={
            "object_description": "Agent 上下文成果",
            "behavior": "能保存并读取产出",
            "context_key": "agent-context",
            "idempotency_key": f"{prefix}-outcome",
        },
    )
    assert outcome.status_code == 201
    delegation = client.post(
        "/api/learning/delegations",
        json={
            "action_id": action.json()["id"],
            "outcome_id": outcome.json()["id"],
            "criterion_id": None,
            "boundaries": "只验证读取边界",
            "stop_conditions": "保存一份产出",
            "time_budget_minutes": 30,
            "expected_version": 1,
            "idempotency_key": f"{prefix}-delegation",
        },
    )
    assert delegation.status_code == 201
    session = client.post(
        "/api/learning/sessions",
        json={
            "delegation_id": delegation.json()["id"],
            "expected_version": 2,
            "idempotency_key": f"{prefix}-session",
        },
    )
    assert session.status_code == 201
    artifact = client.post(
        "/api/learning/artifacts",
        json={
            "session_id": session.json()["id"],
            "content": "PRIVATE agent context output",
            "expected_version": 3,
            "idempotency_key": f"{prefix}-artifact",
        },
    )
    assert artifact.status_code == 201
    return {
        "action": action.json(),
        "artifact": artifact.json(),
        "delegation": delegation.json(),
        "session": session.json(),
    }


def insert_candidate_claim(client, chain, prefix):
    database = client.app.state.learning.database
    criterion = database.fetchone(
        """SELECT id, recipe_json FROM learning_criterion_version
           WHERE owner_id=(SELECT owner_id FROM learning_action WHERE id=?)
             AND review_status='approved' LIMIT 1""",
        (chain["action"]["id"],),
    )
    assert criterion is not None
    dimension_id = json.loads(criterion["recipe_json"])["dimensions"][0]["id"]
    raw = database.fetchone(
        """SELECT fact_event_id, content_version FROM learning_raw_artifact
           WHERE owner_id=(SELECT owner_id FROM learning_action WHERE id=?) AND artifact_id=?""",
        (chain["action"]["id"], chain["artifact"]["id"]),
    )
    assert raw is not None
    owner_id = database.fetchone(
        "SELECT owner_id FROM learning_action WHERE id=?", (chain["action"]["id"],)
    )["owner_id"]
    with database.transaction() as connection:
        connection.execute(
            """INSERT INTO learning_analysis_run
               (id, owner_id, artifact_id, content_version, fact_event_id, criterion_id,
                request_key, attempt, status, reason, created_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'succeeded', NULL, '2026-09-10T00:00:00Z',
                       '2026-09-10T00:00:01Z')""",
            (
                f"{prefix}-run", owner_id, chain["artifact"]["id"],
                raw["content_version"], raw["fact_event_id"], criterion["id"],
                f"{prefix}-request",
            ),
        )
        connection.execute(
            """INSERT INTO learning_evidence_claim
               (id, owner_id, artifact_id, content_version, fact_event_id, criterion_id,
                dimension_id, stance, status, source, statement, verification_method,
                evidence_condition, scope, analysis_run_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'supports', 'candidate', 'ai_analysis',
                       'PRIVATE candidate claim statement', 'semantic_review', 'independent',
                       'python regex basics', ?, '2026-09-10T00:00:02Z')""",
            (
                f"{prefix}-claim", owner_id, chain["artifact"]["id"],
                raw["content_version"], raw["fact_event_id"], criterion["id"],
                dimension_id, f"{prefix}-run",
            ),
        )


def test_agent_default_context_contains_summary_and_references_without_raw_text(client):
    identity = authorize(client)
    chain = create_fact_chain(client, "default-context")
    insert_candidate_claim(client, chain, "default-context")

    response = client.get("/api/learning/agent/context")
    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == "global"
    assert payload["authorization"]["status"] == "default"
    assert payload["analysis"] == {
        "status": "incomplete",
        "reason": "minimum_context_only",
        "available": ["action_summary", "status", "evidence_references"],
        "unavailable": ["raw_text", "authorized_artifact_metadata"],
    }
    assert payload["context"]["actions"][0]["id"] == chain["action"]["id"]
    assert payload["context"]["actions"][0]["title"] == "Agent 上下文学习行动"
    assert payload["context"]["actions"][0]["evidence_reference_count"] == 1
    assert payload["context"]["evidence_references"][0]["id"] == "default-context-claim"
    assert payload["context"]["evidence_references"][0]["artifact_id"] == chain["artifact"]["id"]
    assert "PRIVATE agent context output" not in response.text
    assert "PRIVATE candidate claim statement" not in response.text

    targeted = client.get(
        "/api/learning/agent/context",
        params={"target_id": chain["action"]["id"]},
    )
    assert targeted.status_code == 200
    assert targeted.json()["scope"] == "learning_action"
    assert targeted.json()["authorization"]["status"] == "default"
    assert targeted.json()["analysis"]["status"] == "incomplete"
    assert targeted.json()["analysis"]["unavailable"] == ["raw_text", "authorized_artifact_metadata"]
    assert targeted.json()["context"]["action"]["id"] == chain["action"]["id"]
    assert targeted.json()["context"]["evidence_references"][0]["id"] == "default-context-claim"
    assert targeted.json()["context"]["artifacts"] == []
    assert "PRIVATE agent context output" not in targeted.text
    assert "PRIVATE candidate claim statement" not in targeted.text


def test_approved_full_text_grant_expands_read_scope_and_is_audited(client):
    identity = authorize(client)
    chain = create_fact_chain(client, "approved-context")
    request = create_request(client, chain["action"]["id"], "approve-full-text", "full_text")

    approved = client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/approve"
    )
    assert approved.status_code == 200
    assert approved.json()["grant_status"] == "active"

    repeat = client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/approve"
    )
    assert repeat.status_code == 200
    assert repeat.json()["grant_status"] == "active"

    context = client.get(
        "/api/learning/agent/context",
        params={"target_id": chain["action"]["id"]},
    )
    assert context.status_code == 200
    assert context.json()["authorization"] == {
        "status": "approved",
        "content_granularity": "full_text",
        "request_id": request["id"],
    }
    assert context.json()["context"]["artifacts"][0]["content"] == "PRIVATE agent context output"

    rows = client.app.state.learning.database.fetchall(
        "SELECT operation, result, reason_code, actor_id FROM learning_audit WHERE reference_id=? ORDER BY rowid",
        (request["id"],),
    )
    approved_row = next(row for row in rows if row["operation"] == "AgentPermissionDecision")
    assert approved_row["result"] == "approved"
    assert approved_row["reason_code"] == "permission_approved"
    assert approved_row["actor_id"] == identity["id"]


def test_approved_metadata_grant_does_not_expose_raw_text(client):
    authorize(client)
    chain = create_fact_chain(client, "metadata-context")
    request = create_request(client, chain["action"]["id"], "approve-metadata")

    approved = client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/approve"
    )
    assert approved.status_code == 200

    context = client.get(
        "/api/learning/agent/context",
        params={"target_id": chain["action"]["id"]},
    )
    assert context.status_code == 200
    assert context.json()["authorization"]["content_granularity"] == "metadata"
    artifact = context.json()["context"]["artifacts"][0]
    assert artifact["id"] == chain["artifact"]["id"]
    assert "content" not in artifact
    assert "PRIVATE agent context output" not in context.text


def test_revoked_grant_stops_raw_text_and_reapplication_creates_new_request(client):
    authorize(client)
    chain = create_fact_chain(client, "revoked-context")
    request = create_request(client, chain["action"]["id"], "revoke-full-text", "full_text")
    assert client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/approve"
    ).status_code == 200

    revoked = client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/revoke",
        json={"reason": "本次协作结束"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["grant_status"] == "revoked"

    context = client.get(
        "/api/learning/agent/context",
        params={"target_id": chain["action"]["id"]},
    )
    assert context.status_code == 200
    assert context.json()["authorization"]["status"] == "revoked"
    assert context.json()["context"]["artifacts"] == []
    assert "PRIVATE agent context output" not in context.text

    reapply = create_request(client, chain["action"]["id"], "reapply-full-text", "full_text")
    reapply["content_granularity"] = "full_text"
    assert client.post(
        f"/api/learning/agent/permission-requests/{reapply['id']}/approve"
    ).status_code == 200
    renewed = client.get(
        "/api/learning/agent/context",
        params={"target_id": chain["action"]["id"]},
    )
    assert renewed.json()["authorization"]["request_id"] == reapply["id"]
    assert renewed.json()["context"]["artifacts"][0]["content"] == "PRIVATE agent context output"


def test_expired_grant_is_rejected_and_audited(client):
    authorize(client)
    chain = create_fact_chain(client, "expired-context")
    request = create_request(client, chain["action"]["id"], "expire-full-text", "full_text")
    assert client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/approve"
    ).status_code == 200

    expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    with client.app.state.learning.database.transaction() as connection:
        connection.execute(
            "UPDATE learning_agent_permission_grant SET expires_at=? WHERE request_id=?",
            (expired_at, request["id"]),
        )

    context = client.get(
        "/api/learning/agent/context",
        params={"target_id": chain["action"]["id"]},
    )
    assert context.status_code == 200
    assert context.json()["authorization"]["status"] == "expired"
    assert context.json()["context"]["artifacts"] == []
    assert "PRIVATE agent context output" not in context.text

    rows = client.app.state.learning.database.fetchall(
        "SELECT operation, result, reason_code FROM learning_audit WHERE reference_id=? ORDER BY rowid",
        (request["id"],),
    )
    assert ("AgentPermissionDecision", "rejected", "permission_expired") in [
        tuple(row) for row in rows
    ]


def test_denied_request_cannot_be_approved_and_missing_context_target_is_rejected(client):
    authorize(client)
    chain = create_fact_chain(client, "deny-approve-context")
    request = create_request(client, chain["action"]["id"], "deny-then-approve")
    assert client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/deny",
        json={"reason": "不批准"},
    ).status_code == 200

    approved = client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/approve"
    )
    assert approved.status_code == 409
    assert approved.json()["detail"]["kind"] == "permission_request_not_pending"

    missing = client.get("/api/learning/agent/context", params={"target_id": "missing"})
    assert missing.status_code == 404
    assert missing.json()["detail"]["kind"] == "not_found"


def test_agent_permission_actions_and_context_require_authorization(client):
    authorize(client)
    chain = create_fact_chain(client, "unauthorized-context")
    request = create_request(client, chain["action"]["id"], "unauthorized-key")
    client.cookies.clear()

    assert client.get("/api/learning/agent/context").status_code == 401
    assert client.get(
        "/api/learning/agent/context", params={"target_id": chain["action"]["id"]}
    ).status_code == 401
    assert client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/approve"
    ).status_code == 401
    assert client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/revoke"
    ).status_code == 401


def test_agent_permission_actions_and_context_are_isolated_by_identity(client):
    authorize(client)
    chain = create_fact_chain(client, "cross-identity-context")
    request = create_request(client, chain["action"]["id"], "cross-identity-context-key")

    database = client.app.state.database
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    expires_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    with database.transaction() as connection:
        connection.execute(
            """INSERT INTO local_identity
               (id, device_id, display_name, timezone, created_at, updated_at)
               VALUES (?, ?, ?, 'UTC', ?, ?)""",
            ("second-context-identity", "second-context-device", "第二身份", now, now),
        )
        connection.execute(
            """INSERT INTO sessions
               (id, identity_id, token_hash, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("second-context-session", "second-context-identity", hash_token("second-context-token"), now, expires_at),
        )
    client.cookies.set(client.app.state.settings.cookie_name, "second-context-token")

    global_context = client.get("/api/learning/agent/context")
    assert global_context.status_code == 200
    assert global_context.json()["context"]["actions"] == []
    assert global_context.json()["context"]["evidence_references"] == []

    targeted = client.get(
        "/api/learning/agent/context", params={"target_id": chain["action"]["id"]}
    )
    assert targeted.status_code == 404
    assert targeted.json()["detail"]["kind"] == "not_found"
    assert client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/approve"
    ).status_code == 404
    assert client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/revoke",
        json={"reason": "跨身份撤销"},
    ).status_code == 404


def test_full_text_grant_only_reads_its_target_action(client):
    authorize(client)
    first = create_fact_chain(client, "full-text-first")
    ended = client.post(
        f"/api/learning/sessions/{first['session']['id']}/end",
        json={
            "disposition": "ended",
            "expected_version": 4,
            "idempotency_key": "full-text-first-end",
        },
    )
    assert ended.status_code == 200
    second = create_fact_chain(client, "full-text-second")
    request = create_request(client, first["action"]["id"], "target-isolation", "full_text")
    assert client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/approve"
    ).status_code == 200

    context = client.get(
        "/api/learning/agent/context", params={"target_id": second["action"]["id"]}
    )
    assert context.status_code == 200
    assert context.json()["authorization"]["status"] == "default"
    assert context.json()["context"]["artifacts"] == []
    assert "PRIVATE agent context output" not in context.text


def test_purged_artifact_does_not_return_text_through_full_text_grant(client):
    authorize(client)
    chain = create_fact_chain(client, "purge-context")
    request = create_request(client, chain["action"]["id"], "purge-full-text", "full_text")
    assert client.post(
        f"/api/learning/agent/permission-requests/{request['id']}/approve"
    ).status_code == 200

    purged = client.post(
        f"/api/learning/artifacts/{chain['artifact']['id']}/purge",
        json={
            "expected_version": chain["artifact"]["version"],
            "idempotency_key": "purge-agent-context",
            "confirmation": "PURGE",
        },
    )
    assert purged.status_code == 200

    context = client.get(
        "/api/learning/agent/context", params={"target_id": chain["action"]["id"]}
    )
    assert context.status_code == 200
    assert context.json()["authorization"]["status"] == "approved"
    artifact = context.json()["context"]["artifacts"][0]
    assert artifact["id"] == chain["artifact"]["id"]
    assert artifact["content"] is None
    assert "PRIVATE agent context output" not in context.text
