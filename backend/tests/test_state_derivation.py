from __future__ import annotations

import json

from app.evidence import EvidenceClaimDraft
from test_evidence_claims import authorize, create_standard_chain


def analyze(client, artifact_id, key):
    response = client.post(
        f"/api/learning/artifacts/{artifact_id}/analysis",
        json={"request_key": key},
    )
    assert response.status_code == 200
    return response.json()


def states_by_dimension(client):
    return {
        item["dimension_id"]: item
        for item in client.get("/api/learning/derived-states").json()
    }


def test_state_derivation_separates_candidate_adopted_and_excluded_claims(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    result = analyze(client, created["artifact"]["id"], "derive-state")
    claim_id = result["claims"][0]["id"]

    assert client.get("/api/learning/derived-states").json() == []
    initial = client.post("/api/learning/derived-states/recalculate", json={}).json()
    assert {item["dimension_id"]: item["status"] for item in initial} == {
        "syntax_semantics": "awaiting_evidence",
        "application": "pending_review",
        "independent_explanation": "awaiting_evidence",
    }

    adopted = client.post(
        f"/api/learning/evidence-claims/{claim_id}/review",
        json={"action": "adopt", "reason": "确定性检查符合标准", "request_key": "adopt-state"},
    )
    assert adopted.status_code == 201
    assert adopted.json()["to_status"] == "adopted"

    after_adopt = states_by_dimension(client)
    assert after_adopt["application"]["status"] == "partially_supported"
    assert after_adopt["application"]["reason_code"] == "independence_unverified"
    assert after_adopt["application"]["participating_claim_ids"] == [claim_id]
    assert after_adopt["application"]["excluded_claim_ids"] == []
    assert after_adopt["application"]["standard_version"] == 1
    assert after_adopt["application"]["calculation_version"] == 2
    assert after_adopt["syntax_semantics"]["status"] == "awaiting_evidence"

    questioned = client.post(
        f"/api/learning/evidence-claims/{claim_id}/review",
        json={"action": "question", "reason": "需要复核", "request_key": "question-state"},
    )
    assert questioned.status_code == 201
    after_question = states_by_dimension(client)
    assert after_question["application"]["status"] == "awaiting_evidence"
    assert after_question["application"]["reason_code"] == "no_current_evidence"
    assert after_question["application"]["participating_claim_ids"] == []
    assert after_question["application"]["excluded_claim_ids"] == [claim_id]
    assert after_question["application"]["excluded_claim_reasons"] == [
        {"claim_id": claim_id, "reason": "claim_questioned"}
    ]
    assert after_question["application"]["calculation_version"] == 3

    history = client.get("/api/learning/derived-state-history").json()
    application_history = [item for item in history if item["dimension_id"] == "application"]
    assert [item["calculation_version"] for item in application_history] == [1, 2, 3]
    assert [item["status"] for item in application_history] == [
        "pending_review",
        "partially_supported",
        "awaiting_evidence",
    ]


def test_contradictory_evidence_is_not_cancelled_out(client):
    class AlternatingAnalyzer:
        def __init__(self):
            self.calls = 0

        def __call__(self, request):
            self.calls += 1
            stance = "supports" if self.calls == 1 else "refutes"
            return [
                EvidenceClaimDraft(
                    dimension_id="application",
                    stance=stance,
                    source="deterministic_check",
                    statement=f"合成 {stance} 主张。",
                    verification_method="python_re_search",
                    evidence_condition="independent",
                    scope="artifact",
                )
            ]

    authorize(client)
    created = create_standard_chain(client, content="regex: ^Contradiction\\d+$\nsample: Contradiction42")
    analyzer = AlternatingAnalyzer()
    client.app.state.evidence.semantic_analyzer = None
    client.app.state.evidence.analyzer = analyzer
    first = analyze(client, created["artifact"]["id"], "contradiction-1")
    second = analyze(client, created["artifact"]["id"], "contradiction-2")
    assert len(first["claims"]) == 1
    assert len(second["claims"]) == 1

    for index, claim in enumerate((first["claims"][0], second["claims"][0]), start=1):
        response = client.post(
            f"/api/learning/evidence-claims/{claim['id']}/review",
            json={"action": "adopt", "request_key": f"adopt-contradiction-{index}"},
        )
        assert response.status_code == 201

    client.post("/api/learning/derived-states/recalculate", json={})
    state = states_by_dimension(client)["application"]
    assert state["status"] == "contradicted"
    assert state["reason_code"] == "contradictory_evidence"
    assert sorted(state["participating_claim_ids"]) == sorted(
        [first["claims"][0]["id"], second["claims"][0]["id"]]
    )


def test_fact_correction_supersedes_old_claims_and_recalculates_state(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    result = analyze(client, created["artifact"]["id"], "correction-state")
    claim_id = result["claims"][0]["id"]
    adopted = client.post(
        f"/api/learning/evidence-claims/{claim_id}/review",
        json={"action": "adopt", "request_key": "adopt-before-correction"},
    )
    assert adopted.status_code == 201
    assert states_by_dimension(client)["application"]["status"] == "partially_supported"

    correction = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/corrections",
        json={
            "content": "regex: ^Corrected\\d+$\nsample: Corrected42",
            "expected_version": 4,
            "idempotency_key": "correct-state-claim",
        },
    )
    assert correction.status_code == 200

    claim = client.app.state.learning.database.fetchone(
        "SELECT status FROM learning_evidence_claim WHERE id=?",
        (claim_id,),
    )
    assert claim["status"] == "superseded"
    state = states_by_dimension(client)["application"]
    assert state["status"] == "awaiting_evidence"
    assert state["participating_claim_ids"] == []
    assert state["excluded_claim_ids"] == [claim_id]

    actions = client.app.state.learning.database.fetchall(
        "SELECT action, reason FROM learning_review_action WHERE claim_id=?",
        (claim_id,),
    )
    assert [tuple(row) for row in actions] == [
        ("adopt", None),
        ("supersede", "artifact corrected"),
    ]

    new_analysis = analyze(client, created["artifact"]["id"], "corrected-state-analysis")
    new_claim_id = new_analysis["claims"][0]["id"]
    replacements = client.get("/api/learning/evidence-replacements").json()
    assert len(replacements) == 1
    assert replacements[0]["superseded_claim_id"] == claim_id
    assert replacements[0]["replacement_claim_id"] == new_claim_id
    assert replacements[0]["reason"] == "artifact corrected"


def test_revisit_queue_tracks_questioned_claims_and_due_supplemental_verification(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    result = analyze(client, created["artifact"]["id"], "revisit-state")
    claim_id = result["claims"][0]["id"]

    supplemental = client.post(
        f"/api/learning/evidence-claims/{claim_id}/supplemental-verification",
        json={"request_key": "revisit-supplemental", "note": "到期补充验证"},
    )
    assert supplemental.status_code == 201

    questioned = client.post(
        f"/api/learning/evidence-claims/{claim_id}/review",
        json={"action": "question", "request_key": "revisit-question", "reason": "需要回访"},
    )
    assert questioned.status_code == 201

    queue = client.get("/api/learning/revisit-queue").json()
    assert {
        (item["source_kind"], item["claim_id"], item["reason"])
        for item in queue
    } == {
        ("questioned_claim", claim_id, "claim_questioned"),
        ("supplemental_verification", claim_id, "supplemental_verification_due"),
    }
    assert all(item["status"] == "pending" for item in queue)


def test_new_standard_version_is_recalculated_without_mutating_old_version(client):
    authorize(client)
    create_standard_chain(client)
    old_criterion = client.app.state.learning.database.fetchone(
        "SELECT id, owner_id, package_id, outcome_id, version, source, context_key, recipe_json FROM learning_criterion_version WHERE owner_id=?",
        (client.app.state.auth.identity_for_session(
            client.cookies.get(client.app.state.settings.cookie_name)
        )["id"],),
    )
    with client.app.state.learning.database.transaction() as connection:
        connection.execute(
            """INSERT INTO learning_criterion_version
               (id, owner_id, package_id, outcome_id, version, source, context_key,
                recipe_json, review_status, reviewed_by, reviewed_at, created_at)
               VALUES (?, ?, ?, ?, 2, ?, ?, ?, 'approved', 'product-owner',
                       '2026-09-07T00:00:00Z', '2026-09-07T00:00:00Z')""",
            (
                "python-regex-basics-v2-criterion",
                old_criterion["owner_id"],
                old_criterion["package_id"],
                old_criterion["outcome_id"],
                old_criterion["source"],
                old_criterion["context_key"],
                old_criterion["recipe_json"],
            ),
        )

    states = client.post("/api/learning/derived-states/recalculate", json={}).json()
    criterion_ids = {item["criterion_id"] for item in states}
    assert criterion_ids == {
        old_criterion["id"],
        "python-regex-basics-v2-criterion",
    }
    assert all(item["standard_version"] in {1, 2} for item in states)
    assert client.app.state.learning.database.fetchone(
        "SELECT version FROM learning_criterion_version WHERE id=?",
        (old_criterion["id"],),
    )["version"] == 1
