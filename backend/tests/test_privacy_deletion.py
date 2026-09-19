from __future__ import annotations

from app.auth import hash_token
from test_evidence_claims import authorize, create_standard_chain


def test_purged_content_is_not_returned_to_owner_or_other_identity(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    analysis = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
        json={"request_key": "privacy-analysis"},
    )
    assert analysis.status_code == 200
    claim_id = analysis.json()["claims"][0]["id"]

    purged = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/purge",
        json={
            "expected_version": 4,
            "idempotency_key": "privacy-purge",
            "confirmation": "PURGE",
        },
    )
    assert purged.status_code == 200

    owner_read = client.get(f"/api/learning/artifacts/{created['artifact']['id']}")
    assert owner_read.status_code == 200
    assert owner_read.json()["content"] is None
    assert owner_read.json()["content_hash"] is None

    database = client.app.state.database
    now = "2026-09-07T00:00:00Z"
    expires = "2099-01-01T00:00:00Z"
    with database.transaction() as connection:
        connection.execute(
            """INSERT INTO local_identity
               (id, device_id, display_name, timezone, created_at, updated_at)
               VALUES ('privacy-other', 'privacy-other-device', '第二身份', 'UTC', ?, ?)""",
            (now, now),
        )
        connection.execute(
            """INSERT INTO sessions
               (id, identity_id, token_hash, created_at, expires_at)
               VALUES ('privacy-session', 'privacy-other', ?, ?, ?)""",
            (hash_token("privacy-session-token"), now, expires),
        )
    client.cookies.set(client.app.state.settings.cookie_name, "privacy-session-token")
    other_read = client.get(f"/api/learning/artifacts/{created['artifact']['id']}")
    assert other_read.status_code == 404
    other_claims = client.get("/api/learning/evidence-claims")
    assert other_claims.status_code == 200
    assert other_claims.json() == []
    assert claim_id


def test_fact_replay_preserves_purged_semantics(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    analysis = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
        json={"request_key": "replay-purge-analysis"},
    )
    assert analysis.status_code == 200
    claim_id = analysis.json()["claims"][0]["id"]

    purged = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/purge",
        json={
            "expected_version": 4,
            "idempotency_key": "replay-purge",
            "confirmation": "PURGE",
        },
    )
    assert purged.status_code == 200

    fact_replay = client.post("/api/learning/replay")
    assert fact_replay.status_code == 200
    assert client.app.state.learning.database.fetchone(
        "SELECT status FROM learning_evidence_claim WHERE id=?",
        (claim_id,),
    )["status"] == "invalidated"
    assert client.app.state.learning.database.fetchone(
        "SELECT content FROM learning_raw_artifact WHERE artifact_id=? AND content_version=1",
        (created["artifact"]["id"],),
    )["content"] is None


def test_agent_permission_requests_do_not_expose_purged_content(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    purged = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/purge",
        json={
            "expected_version": 4,
            "idempotency_key": "agent-privacy-purge",
            "confirmation": "PURGE",
        },
    )
    assert purged.status_code == 200

    request = client.post(
        "/api/learning/agent/permission-requests",
        json={
            "purpose": "读取学习行动摘要",
            "target_id": created["action"]["id"],
            "content_granularity": "metadata",
            "ttl_seconds": 300,
            "request_key": "agent-privacy-request",
        },
    )
    assert request.status_code == 201
    assert "Lifecycle42" not in request.text
    assert "content" not in request.json()
