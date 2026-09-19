from __future__ import annotations

import pytest

from app.evidence import EvidenceClaimDraft


def authorize(client):
    challenge = client.get("/api/auth/challenge").json()["code"]
    response = client.post("/api/auth/authorize", json={"access_token": challenge})
    assert response.status_code == 200
    return response.json()["identity"]


def create_standard_chain(
    client,
    content="regex: ^Nautilus\\d+$\nsample: Nautilus42",
    key_prefix="evidence",
):
    state = client.get("/api/learning/state").json()
    assert state["standards"], "已审核标准包应自动种入"
    standard = state["standards"][0]
    assert standard["context_key"] == "python-regex-basics"
    assert standard["review_status"] == "approved"

    action = client.post(
        "/api/learning/actions",
        json={
            "title": "Python 正则表达式基础行动",
            "context_key": "python-regex-basics",
            "idempotency_key": f"{key_prefix}-action",
        },
    )
    assert action.status_code == 201
    delegation = client.post(
        "/api/learning/delegations",
        json={
            "action_id": action.json()["id"],
            "outcome_id": standard["outcome_id"],
            "criterion_id": standard["id"],
            "boundaries": "只验证基础正则表达式",
            "stop_conditions": "完成一次确定性检查",
            "time_budget_minutes": 30,
            "expected_version": 1,
            "idempotency_key": f"{key_prefix}-delegation",
        },
    )
    assert delegation.status_code == 201
    session = client.post(
        "/api/learning/sessions",
        json={
            "delegation_id": delegation.json()["id"],
            "expected_version": 2,
            "idempotency_key": f"{key_prefix}-session",
        },
    )
    assert session.status_code == 201
    artifact = client.post(
        "/api/learning/artifacts",
        json={
            "session_id": session.json()["id"],
            "content": content,
            "expected_version": 3,
            "idempotency_key": f"{key_prefix}-artifact",
        },
    )
    assert artifact.status_code == 201
    return {
        "standard": standard,
        "action": action.json(),
        "delegation": delegation.json(),
        "session": session.json(),
        "artifact": artifact.json(),
    }


def test_analysis_with_approved_standard_creates_referenced_candidate_claim(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = lambda request: [
        EvidenceClaimDraft(
            dimension_id="syntax_semantics",
            stance="supports",
            source="ai_analysis",
            statement="语义分析确认产出说明了正则表达式的匹配语义。",
            verification_method="semantic_analysis",
            evidence_condition="independent",
            scope="artifact",
        )
    ]

    response = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
        json={"request_key": "evidence-analysis"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["created"] is True
    assert result["run"]["status"] == "succeeded"
    assert result["run"]["criterion_id"] == created["standard"]["id"]
    assert len(result["claims"]) == 2

    claim = next(item for item in result["claims"] if item["dimension_id"] == "application")
    assert claim["artifact_id"] == created["artifact"]["id"]
    assert claim["content_version"] == 1
    assert claim["fact_event_id"] == created["artifact"]["event_id"]
    assert claim["criterion_id"] == created["standard"]["id"]
    assert claim["dimension_id"] == "application"
    assert claim["stance"] == "supports"
    assert claim["status"] == "candidate"
    assert claim["source"] == "deterministic_check"
    assert claim["verification_method"] == "python_re_search"
    assert claim["evidence_condition"] == "independent"

    listed = client.get("/api/learning/evidence-claims").json()
    assert len(listed) == 2
    assert listed[0]["id"] == claim["id"]

    duplicate = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
        json={"request_key": "evidence-analysis"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["created"] is False
    assert duplicate.json()["run"]["id"] == result["run"]["id"]
    assert len(duplicate.json()["claims"]) == 2
    assert len(client.get("/api/learning/evidence-claims").json()) == 2

    artifact = client.get(f"/api/learning/artifacts/{created['artifact']['id']}").json()
    assert artifact["content"] == "regex: ^Nautilus\\d+$\nsample: Nautilus42"


def test_human_review_and_supplemental_verification_can_be_arranged(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    analysis = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
        json={"request_key": "follow-up-analysis"},
    )
    assert analysis.status_code == 200
    claim_id = analysis.json()["claims"][0]["id"]

    review = client.post(
        f"/api/learning/evidence-claims/{claim_id}/human-review",
        json={"request_key": "human-review", "note": "请人工复核语义解释"},
    )
    assert review.status_code == 201
    assert review.json()["kind"] == "human_review"
    assert review.json()["status"] == "pending"

    duplicate_review = client.post(
        f"/api/learning/evidence-claims/{claim_id}/human-review",
        json={"request_key": "human-review"},
    )
    assert duplicate_review.status_code == 201
    assert duplicate_review.json()["id"] == review.json()["id"]

    verification = client.post(
        f"/api/learning/evidence-claims/{claim_id}/supplemental-verification",
        json={"request_key": "supplemental-verification", "note": "安排一次变式匹配"},
    )
    assert verification.status_code == 201
    assert verification.json()["kind"] == "supplemental_verification"
    assert verification.json()["status"] == "pending"
    assert verification.json()["due_at"] is not None

    follow_ups = client.get("/api/learning/evidence-follow-ups").json()
    assert {item["kind"] for item in follow_ups} == {
        "human_review",
        "supplemental_verification",
    }
    assert all(item["status"] == "pending" for item in follow_ups)


def test_missing_provider_fails_semantic_analysis_without_claims(client):
    authorize(client)
    created = create_standard_chain(client)
    response = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
        json={"request_key": "missing-provider"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "failed"
    assert result["run"]["reason"] == "provider_unavailable"
    assert result["claims"] == []
    assert client.get("/api/learning/evidence-claims").json() == []
    assert client.get(f"/api/learning/artifacts/{created['artifact']['id']}").json()[
        "content"
    ] == "regex: ^Nautilus\\d+$\nsample: Nautilus42"


def test_no_standard_analysis_returns_blocked_run_without_claims(client):
    authorize(client)
    action = client.post(
        "/api/learning/actions",
        json={
            "title": "无标准证据行动",
            "context_key": "no-standard-context",
            "idempotency_key": "no-standard-action",
        },
    )
    assert action.status_code == 201
    outcome = client.post(
        "/api/learning/outcomes",
        json={
            "object_description": "无标准成果",
            "behavior": "仅保存事实",
            "context_key": "no-standard-context",
            "idempotency_key": "no-standard-outcome",
        },
    )
    assert outcome.status_code == 201
    delegation = client.post(
        "/api/learning/delegations",
        json={
            "action_id": action.json()["id"],
            "outcome_id": outcome.json()["id"],
            "criterion_id": None,
            "boundaries": "",
            "stop_conditions": "保存产出",
            "time_budget_minutes": 30,
            "expected_version": 1,
            "idempotency_key": "no-standard-delegation",
        },
    )
    assert delegation.status_code == 201
    session = client.post(
        "/api/learning/sessions",
        json={
            "delegation_id": delegation.json()["id"],
            "expected_version": 2,
            "idempotency_key": "no-standard-session",
        },
    )
    assert session.status_code == 201
    artifact = client.post(
        "/api/learning/artifacts",
        json={
            "session_id": session.json()["id"],
            "content": "没有标准的产出",
            "expected_version": 3,
            "idempotency_key": "no-standard-artifact",
        },
    )
    assert artifact.status_code == 201

    before = client.app.state.learning.database.fetchone(
        "SELECT COUNT(*) FROM learning_analysis_run"
    )[0]
    response = client.post(
        f"/api/learning/artifacts/{artifact.json()['id']}/analysis",
        json={"request_key": "no-standard-analysis"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["created"] is False
    assert result["run"]["status"] == "blocked_no_criterion"
    assert result["run"]["reason"] == "no approved criterion"
    assert result["claims"] == []
    after = client.app.state.learning.database.fetchone(
        "SELECT COUNT(*) FROM learning_analysis_run"
    )[0]
    assert after == before
    assert client.get("/api/learning/evidence-claims").json() == []
