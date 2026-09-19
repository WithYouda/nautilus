from __future__ import annotations

import pytest

from app.evidence import EvidenceClaimDraft

from test_evidence_claims import authorize, create_standard_chain


def analyze(client, artifact_id, key="review-workflow"):
    response = client.post(
        f"/api/learning/artifacts/{artifact_id}/analysis",
        json={"request_key": key},
    )
    assert response.status_code == 200
    return response.json()


def test_review_actions_are_idempotent_and_audited(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    result = analyze(client, created["artifact"]["id"])
    claim_id = result["claims"][0]["id"]

    first = client.post(
        f"/api/learning/evidence-claims/{claim_id}/review",
        json={"action": "adopt", "reason": "符合标准", "request_key": "review-once"},
    )
    assert first.status_code == 201
    second = client.post(
        f"/api/learning/evidence-claims/{claim_id}/review",
        json={"action": "adopt", "reason": "符合标准", "request_key": "review-once"},
    )
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]

    conflict = client.post(
        f"/api/learning/evidence-claims/{claim_id}/review",
        json={"action": "question", "request_key": "review-once"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["kind"] == "idempotency_conflict"

    assert client.app.state.learning.database.fetchone(
        "SELECT COUNT(*) FROM learning_review_action WHERE claim_id=?",
        (claim_id,),
    )[0] == 1
    assert client.app.state.learning.database.fetchone(
        "SELECT COUNT(*) FROM learning_audit WHERE operation='ReviewEvidenceClaim' AND reference_id=?",
        (first.json()["id"],),
    )[0] == 1


def test_only_qualifying_candidate_claims_can_be_adopted(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    result = analyze(client, created["artifact"]["id"], "qualifying")
    claim_id = result["claims"][0]["id"]

    with client.app.state.learning.database.transaction() as connection:
        connection.execute(
            "UPDATE learning_evidence_claim SET source='human_review' WHERE id=?",
            (claim_id,),
        )

    response = client.post(
        f"/api/learning/evidence-claims/{claim_id}/review",
        json={"action": "adopt", "request_key": "adopt-invalid"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["kind"] == "claim_not_qualifying"

    deferred = client.post(
        f"/api/learning/evidence-claims/{claim_id}/review",
        json={"action": "defer", "reason": "暂不处理", "request_key": "defer"},
    )
    assert deferred.status_code == 201
    assert deferred.json()["from_status"] == "candidate"
    assert deferred.json()["to_status"] == "candidate"
    assert client.app.state.learning.database.fetchone(
        "SELECT status FROM learning_evidence_claim WHERE id=?",
        (claim_id,),
    )["status"] == "candidate"


@pytest.mark.parametrize(
    ("action", "status"),
    [
        ("question", "questioned"),
        ("withdraw", "withdrawn"),
    ],
)
def test_review_actions_move_claims_out_of_current_calculation(client, action, status):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    result = analyze(client, created["artifact"]["id"], f"review-{action}")
    claim_id = result["claims"][0]["id"]
    adopted = client.post(
        f"/api/learning/evidence-claims/{claim_id}/review",
        json={"action": "adopt", "request_key": f"adopt-{action}"},
    )
    assert adopted.status_code == 201

    reviewed = client.post(
        f"/api/learning/evidence-claims/{claim_id}/review",
        json={"action": action, "reason": "复核处理", "request_key": f"{action}-after-adopt"},
    )
    assert reviewed.status_code == 201
    assert reviewed.json()["to_status"] == status
    state = {
        item["dimension_id"]: item
        for item in client.get("/api/learning/derived-states").json()
    }["application"]
    assert state["status"] == "awaiting_evidence"
    assert state["participating_claim_ids"] == []
    assert state["excluded_claim_ids"] == [claim_id]


def test_batch_review_adopts_each_claim_with_independent_audit(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = lambda request: [
        EvidenceClaimDraft(
            dimension_id="syntax_semantics",
            stance="supports",
            source="ai_analysis",
            statement="语义分析确认产出说明了正则表达式语义。",
            verification_method="semantic_analysis",
            evidence_condition="independent",
            scope="artifact",
        )
    ]
    result = analyze(client, created["artifact"]["id"], "batch-review")
    claim_ids = [claim["id"] for claim in result["claims"]]
    assert len(claim_ids) == 2

    first = client.post(
        "/api/learning/evidence-claims/batch-review",
        json={
            "claim_ids": claim_ids,
            "action": "adopt",
            "reason": "批量采纳",
            "request_key": "batch-adopt",
        },
    )
    assert first.status_code == 201
    persisted_review_ids = {
        row["id"]
        for row in client.app.state.learning.database.fetchall(
            "SELECT id FROM learning_review_action WHERE claim_id IN (?, ?) AND action='adopt'",
            tuple(claim_ids),
        )
    }
    assert set(first.json()["review_ids"]) == persisted_review_ids
    assert len(first.json()["review_ids"]) == 2

    duplicate = client.post(
        "/api/learning/evidence-claims/batch-review",
        json={
            "claim_ids": claim_ids,
            "action": "adopt",
            "reason": "批量采纳",
            "request_key": "batch-adopt",
        },
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == first.json()["id"]

    assert client.app.state.learning.database.fetchone(
        "SELECT COUNT(*) FROM learning_batch_review_action WHERE owner_id=?",
        (client.app.state.auth.identity_for_session(
            client.cookies.get(client.app.state.settings.cookie_name)
        )["id"],),
    )[0] == 1
    assert client.app.state.learning.database.fetchone(
        "SELECT COUNT(*) FROM learning_review_action WHERE action='adopt' AND claim_id IN (?, ?)",
        tuple(claim_ids),
    )[0] == 2


def test_user_supersede_requires_explicit_replacement_relation(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    first = analyze(client, created["artifact"]["id"], "replacement-1")
    second = analyze(client, created["artifact"]["id"], "replacement-2")
    old_claim_id = first["claims"][0]["id"]
    new_claim_id = second["claims"][0]["id"]

    missing = client.post(
        f"/api/learning/evidence-claims/{old_claim_id}/review",
        json={"action": "supersede", "request_key": "missing-replacement"},
    )
    assert missing.status_code == 422
    assert missing.json()["detail"]["kind"] == "replacement_claim_required"

    replaced = client.post(
        f"/api/learning/evidence-claims/{old_claim_id}/review",
        json={
            "action": "supersede",
            "reason": "由新主张替代",
            "request_key": "explicit-replacement",
            "replacement_claim_id": new_claim_id,
        },
    )
    assert replaced.status_code == 201
    assert replaced.json()["replacement_claim_id"] == new_claim_id

    replacements = client.get("/api/learning/evidence-replacements").json()
    assert len(replacements) == 1
    assert replacements[0]["superseded_claim_id"] == old_claim_id
    assert replacements[0]["replacement_claim_id"] == new_claim_id
    assert replacements[0]["reason"] == "由新主张替代"
