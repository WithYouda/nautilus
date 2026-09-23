from __future__ import annotations

from test_evidence_claims import authorize, create_standard_chain


def analyze(client, artifact_id, key="lifecycle-analysis"):
    response = client.post(
        f"/api/learning/artifacts/{artifact_id}/analysis",
        json={"request_key": key},
    )
    assert response.status_code == 200
    return response.json()


def artifact_row(client, artifact_id):
    return client.app.state.learning.database.fetchone(
        """SELECT raw.content, raw.content_hash, raw.purged_at,
                  current_artifact.visibility, current_artifact.evidence_status
           FROM learning_raw_artifact AS raw
           JOIN learning_artifact AS current_artifact
             ON current_artifact.owner_id=raw.owner_id
            AND current_artifact.id=raw.artifact_id
           WHERE raw.owner_id=? AND raw.artifact_id=?
           ORDER BY raw.content_version DESC LIMIT 1""",
        (
            client.app.state.auth.identity_for_session(
                client.cookies.get(client.app.state.settings.cookie_name)
            )["id"],
            artifact_id,
        ),
    )


def test_soft_delete_restore_and_withdraw_are_distinct(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    result = analyze(client, created["artifact"]["id"])
    claim_id = result["claims"][0]["id"]
    adopted = client.post(
        f"/api/learning/evidence-claims/{claim_id}/review",
        json={"action": "adopt", "request_key": "lifecycle-adopt"},
    )
    assert adopted.status_code == 201

    soft_deleted = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/soft-delete",
        json={"expected_version": 4, "idempotency_key": "soft-delete"},
    )
    assert soft_deleted.status_code == 200
    row = artifact_row(client, created["artifact"]["id"])
    assert row["visibility"] == "soft_deleted"
    assert row["evidence_status"] == "withdrawn"
    assert row["content"] is not None
    state = {
        item["dimension_id"]: item
        for item in client.get("/api/learning/derived-states").json()
    }["application"]
    assert state["status"] == "awaiting_evidence"

    restored = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/restore",
        json={"expected_version": 5, "idempotency_key": "restore"},
    )
    assert restored.status_code == 200
    row = artifact_row(client, created["artifact"]["id"])
    assert row["visibility"] == "visible"
    assert row["evidence_status"] == "eligible"
    state = {
        item["dimension_id"]: item
        for item in client.get("/api/learning/derived-states").json()
    }["application"]
    assert state["status"] == "partially_supported"

    withdrawn = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/withdraw",
        json={"expected_version": 6, "idempotency_key": "withdraw-artifact"},
    )
    assert withdrawn.status_code == 200
    row = artifact_row(client, created["artifact"]["id"])
    assert row["visibility"] == "visible"
    assert row["evidence_status"] == "withdrawn"
    state = {
        item["dimension_id"]: item
        for item in client.get("/api/learning/derived-states").json()
    }["application"]
    assert state["status"] == "awaiting_evidence"


def test_purge_requires_confirmation_and_invalidates_dependent_claims(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    result = analyze(client, created["artifact"]["id"], "purge-analysis")
    claim_id = result["claims"][0]["id"]
    adopted = client.post(
        f"/api/learning/evidence-claims/{claim_id}/review",
        json={"action": "adopt", "request_key": "purge-adopt"},
    )
    assert adopted.status_code == 201

    rejected = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/purge",
        json={"expected_version": 4, "idempotency_key": "purge-wrong", "confirmation": "wrong"},
    )
    assert rejected.status_code == 422

    purged = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/purge",
        json={"expected_version": 4, "idempotency_key": "purge", "confirmation": "PURGE"},
    )
    assert purged.status_code == 200
    row = artifact_row(client, created["artifact"]["id"])
    assert row["visibility"] == "purged"
    assert row["evidence_status"] == "invalidated"
    assert row["content"] is None
    assert row["content_hash"] is None
    assert row["purged_at"] is not None
    assert client.app.state.learning.database.fetchone(
        "SELECT status FROM learning_evidence_claim WHERE id=?",
        (claim_id,),
    )["status"] == "invalidated"
    state = {
        item["dimension_id"]: item
        for item in client.get("/api/learning/derived-states").json()
    }["application"]
    assert state["status"] == "awaiting_evidence"

    restore = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/restore",
        json={"expected_version": 5, "idempotency_key": "restore-purged"},
    )
    assert restore.status_code == 409
    assert restore.json()["detail"]["kind"] == "artifact_not_soft_deleted"
