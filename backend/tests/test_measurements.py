from __future__ import annotations

from app.evidence import AnalysisError, EvidenceClaimDraft
from test_evidence_claims import authorize, create_standard_chain


def analyze(client, artifact_id, key):
    response = client.post(
        f"/api/learning/artifacts/{artifact_id}/analysis",
        json={"request_key": key},
    )
    assert response.status_code == 200
    return response.json()


def test_metrics_report_no_sample_and_traceability(client):
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
    result = analyze(client, created["artifact"]["id"], "metrics-analysis")
    assert len(result["claims"]) == 2

    response = client.get("/api/learning/metrics")
    assert response.status_code == 200
    report = response.json()
    assert report["metric_version"] == "2.0"
    assert report["window"] == "All records through report time; review-to-next-action observation window is 7 days."

    assert report["product_metrics"]["interrupted_delegation_recovery"]["status"] == "no_sample"
    assert report["product_metrics"]["review_to_next_action"]["status"] == "no_sample"
    assert report["product_metrics"]["evidence_traceability"] == {
        "numerator": 2,
        "denominator": 2,
        "value": 1.0,
        "status": "pass",
        "unit": "ratio",
        "notes": ["Claims are counted once by claim ID."],
        "excluded": {"invalidated_by_purge": 0},
    }

    assert report["hard_guards"]["unsupported_claim_rate"] == {
        "numerator": 0,
        "denominator": 2,
        "value": 0.0,
        "status": "pass",
        "unit": "ratio",
        "notes": ["A single unsupported claim fails this hard guard."],
        "excluded": {"invalidated_by_purge": 0},
    }
    assert report["hard_guards"]["ai_failure_save_success"]["status"] == "no_sample"
    assert report["hard_guards"]["event_rebuild_consistency"]["status"] == "no_sample"
    assert report["hard_guards"]["permission_violation_count"]["numerator"] == 0
    assert report["hard_guards"]["privacy_leak_count"]["numerator"] == 0


def test_metrics_ai_failure_save_success_and_replay_consistency(client):
    class FailThenSucceed:
        def __init__(self):
            self.calls = 0

        def __call__(self, request):
            self.calls += 1
            if self.calls == 1:
                raise AnalysisError("timeout", "metrics timeout")
            return [
                EvidenceClaimDraft(
                    dimension_id="application",
                    stance="supports",
                    source="deterministic_check",
                    statement="重试后的确定性检查通过。",
                    verification_method="python_re_search",
                    evidence_condition="independent",
                    scope="artifact",
                )
            ]

    authorize(client)
    created = create_standard_chain(client, content="regex: ^Metric\\d+$\nsample: Metric42")
    original_analyzer = client.app.state.evidence.analyzer
    original_semantic_analyzer = client.app.state.evidence.semantic_analyzer
    client.app.state.evidence.semantic_analyzer = None
    client.app.state.evidence.analyzer = FailThenSucceed()
    try:
        failed = analyze(client, created["artifact"]["id"], "metrics-failure")
        succeeded = analyze(client, created["artifact"]["id"], "metrics-failure")
        assert failed["run"]["status"] == "timeout"
        assert succeeded["run"]["status"] == "succeeded"

        replay = client.post("/api/learning/evidence-replay")
        assert replay.status_code == 200

        report = client.get("/api/learning/metrics").json()
        assert report["hard_guards"]["ai_failure_save_success"] == {
            "numerator": 1,
            "denominator": 1,
            "value": 1.0,
            "status": "pass",
            "unit": "ratio",
            "notes": ["Intentional later purge does not count as a save failure."],
            "excluded": {},
        }
        assert report["hard_guards"]["event_rebuild_consistency"]["numerator"] == 1
        assert report["hard_guards"]["event_rebuild_consistency"]["denominator"] == 1
        assert report["hard_guards"]["event_rebuild_consistency"]["status"] == "pass"
    finally:
        client.app.state.evidence.analyzer = original_analyzer
        client.app.state.evidence.semantic_analyzer = original_semantic_analyzer


def test_metrics_replay_failure_fails_rebuild_guard(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    analyze(client, created["artifact"]["id"], "broken-metrics-analysis")
    event = client.app.state.learning.database.fetchone(
        "SELECT id FROM learning_evidence_event ORDER BY created_at LIMIT 1"
    )
    client.app.state.learning.database.connection.executescript(
        "DROP TRIGGER IF EXISTS learning_evidence_event_no_update; "
        "DROP TRIGGER IF EXISTS learning_evidence_event_no_delete;"
    )
    with client.app.state.learning.database.transaction() as connection:
        connection.execute(
            "UPDATE learning_evidence_event SET previous_hash=? WHERE id=?",
            ("0" * 64, event["id"]),
        )

    replay = client.post("/api/learning/evidence-replay")
    assert replay.status_code == 409
    report = client.get("/api/learning/metrics").json()
    assert report["hard_guards"]["event_rebuild_consistency"]["numerator"] == 0
    assert report["hard_guards"]["event_rebuild_consistency"]["denominator"] == 1
    assert report["hard_guards"]["event_rebuild_consistency"]["status"] == "fail"


def end_session(client, session_id, version, disposition="ended", key="metrics-end"):
    response = client.post(
        f"/api/learning/sessions/{session_id}/end",
        json={
            "disposition": disposition,
            "expected_version": version,
            "idempotency_key": key,
        },
    )
    assert response.status_code == 200
    return response.json()


def start_session(client, delegation_id, version, key="metrics-next-session"):
    response = client.post(
        "/api/learning/sessions",
        json={
            "delegation_id": delegation_id,
            "expected_version": version,
            "idempotency_key": key,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_metrics_measure_interrupted_delegation_recovery(client):
    authorize(client)
    created = create_standard_chain(client, key_prefix="recovery-success")
    end_session(
        client,
        created["session"]["id"],
        4,
        disposition="interrupted",
        key="recovery-interrupt",
    )
    start_session(
        client,
        created["delegation"]["id"],
        5,
        key="recovery-restore",
    )

    report = client.get("/api/learning/metrics").json()
    assert report["product_metrics"]["interrupted_delegation_recovery"] == {
        "numerator": 1,
        "denominator": 1,
        "value": 1.0,
        "status": "pass",
        "unit": "ratio",
        "notes": ["First session started after an interruption is the restore attempt."],
        "excluded": {"awaiting_first_selection": 0},
    }


def test_metrics_count_wrong_first_restore_selection(client):
    authorize(client)
    interrupted = create_standard_chain(client, key_prefix="recovery-wrong")
    end_session(
        client,
        interrupted["session"]["id"],
        4,
        disposition="interrupted",
        key="wrong-recovery-interrupt",
    )

    state = client.get("/api/learning/state").json()
    standard = state["standards"][0]
    action = client.post(
        "/api/learning/actions",
        json={
            "title": "恢复时选择的其他行动",
            "context_key": "python-regex-basics",
            "idempotency_key": "recovery-other-action",
        },
    )
    assert action.status_code == 201
    delegation = client.post(
        "/api/learning/delegations",
        json={
            "action_id": action.json()["id"],
            "outcome_id": standard["outcome_id"],
            "criterion_id": standard["id"],
            "boundaries": "另一条恢复路径",
            "stop_conditions": "开始一次会话",
            "time_budget_minutes": 20,
            "expected_version": 1,
            "idempotency_key": "recovery-other-delegation",
        },
    )
    assert delegation.status_code == 201
    start_session(
        client,
        delegation.json()["id"],
        2,
        key="recovery-other-session",
    )

    report = client.get("/api/learning/metrics").json()
    metric = report["product_metrics"]["interrupted_delegation_recovery"]
    assert metric["numerator"] == 0
    assert metric["denominator"] == 1
    assert metric["value"] == 0.0
    assert metric["status"] == "fail"
    assert metric["excluded"] == {"awaiting_first_selection": 0}


def test_metrics_measure_review_to_completed_next_action(client):
    authorize(client)
    created = create_standard_chain(client, key_prefix="review-next")
    client.app.state.evidence.semantic_analyzer = None
    analysis = analyze(client, created["artifact"]["id"], "review-next-analysis")
    claim_id = analysis["claims"][0]["id"]
    follow_up = client.post(
        f"/api/learning/evidence-claims/{claim_id}/human-review",
        json={"request_key": "review-next-follow-up", "note": "请人工复核"},
    )
    assert follow_up.status_code == 201

    end_session(client, created["session"]["id"], 4, key="review-next-end")
    next_session = start_session(
        client,
        created["delegation"]["id"],
        5,
        key="review-next-second-session",
    )
    end_session(client, next_session["id"], 6, key="review-next-complete")

    report = client.get("/api/learning/metrics").json()
    assert report["product_metrics"]["review_to_next_action"] == {
        "numerator": 1,
        "denominator": 1,
        "value": 1.0,
        "status": "pass",
        "unit": "ratio",
        "notes": ["A completed later session on the same action counts as the next action."],
        "excluded": {"window_pending": 0, "invalidated_by_purge": 0, "cancelled_follow_up": 0},
    }


def test_metrics_single_list_pending_review_window_and_purged_sample(client):
    authorize(client)
    created = create_standard_chain(client, key_prefix="review-pending")
    client.app.state.evidence.semantic_analyzer = None
    analysis = analyze(client, created["artifact"]["id"], "review-pending-analysis")
    claim_id = analysis["claims"][0]["id"]
    assert client.post(
        f"/api/learning/evidence-claims/{claim_id}/human-review",
        json={"request_key": "review-pending-follow-up", "note": "请人工复核"},
    ).status_code == 201

    report = client.get("/api/learning/metrics").json()
    pending = report["product_metrics"]["review_to_next_action"]
    assert pending["status"] == "no_sample"
    assert pending["denominator"] == 0
    assert pending["excluded"]["window_pending"] == 1

    purged = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/purge",
        json={
            "expected_version": created["artifact"]["version"],
            "idempotency_key": "review-pending-purge",
            "confirmation": "PURGE",
        },
    )
    assert purged.status_code == 200
    report = client.get("/api/learning/metrics").json()
    invalidated = report["product_metrics"]["review_to_next_action"]
    assert invalidated["status"] == "no_sample"
    assert invalidated["denominator"] == 0
    assert invalidated["excluded"]["invalidated_by_purge"] == 1


def test_metrics_report_does_not_expose_private_content_or_credentials(client):
    authorize(client)
    private_content = "regex: ^PrivateMetric\\d+$\nsample: PrivateMetric42"
    created = create_standard_chain(client, content=private_content, key_prefix="privacy-metrics")
    client.app.state.evidence.semantic_analyzer = None
    analyze(client, created["artifact"]["id"], "privacy-metrics-analysis")

    response = client.get("/api/learning/metrics")
    assert response.status_code == 200
    assert "PrivateMetric42" not in response.text
    assert "sk-" not in response.text
    assert "Authorization" not in response.text
