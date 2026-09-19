from __future__ import annotations

import pytest

from app.evidence import AnalysisError, EvidenceClaimDraft
from test_evidence_claims import authorize, create_standard_chain


class FlakyAnalyzer:
    def __init__(self, failure_kind: str):
        self.failure_kind = failure_kind
        self.calls = 0

    def __call__(self, request):
        self.calls += 1
        if self.calls == 1:
            raise AnalysisError(self.failure_kind, f"合成 {self.failure_kind} 失败")
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


@pytest.mark.parametrize(
    ("kind", "status", "reason"),
    [
        ("provider_unavailable", "failed", "provider_unavailable"),
        ("timeout", "timeout", "analysis_timeout"),
        ("cancelled", "cancelled", "analysis_cancelled"),
        ("invalid_output", "invalid_output", "analysis_output_invalid"),
        ("permission_denied", "permission_denied", "analysis_permission_denied"),
        ("internal_error", "failed", "internal_error"),
    ],
)
def test_four_ai_failure_kinds_keep_artifact_readable_and_create_no_claims(client, kind, status, reason):
    authorize(client)
    created = create_standard_chain(client, content=f"regex: ^Failing{kind}$\nsample: Failing{kind}")
    original_analyzer = client.app.state.evidence.analyzer
    original_semantic_analyzer = client.app.state.evidence.semantic_analyzer
    client.app.state.evidence.semantic_analyzer = None
    client.app.state.evidence.analyzer = FlakyAnalyzer(kind)
    try:
        response = client.post(
            f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
            json={"request_key": f"failure-{kind}"},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["run"]["status"] == status
        assert result["run"]["reason"] == reason
        assert result["claims"] == []
        assert client.get("/api/learning/evidence-claims").json() == []

        artifact = client.get(f"/api/learning/artifacts/{created['artifact']['id']}").json()
        assert artifact["content"] == f"regex: ^Failing{kind}$\nsample: Failing{kind}"

        retry = client.post(
            f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
            json={"request_key": f"failure-{kind}"},
        )
        assert retry.status_code == 200
        assert retry.json()["run"]["status"] == "succeeded"
        assert retry.json()["run"]["attempt"] == 2
        assert len(retry.json()["claims"]) == 1
        assert len(client.get("/api/learning/evidence-claims").json()) == 1

        audit = client.app.state.learning.database.fetchone(
            "SELECT COUNT(*) FROM learning_audit WHERE operation='AnalyzeEvidence' AND reason_code=?",
            (reason,),
        )
        assert audit[0] == 1
    finally:
        client.app.state.evidence.analyzer = original_analyzer
        client.app.state.evidence.semantic_analyzer = original_semantic_analyzer


def test_retry_after_failure_creates_new_attempt_but_only_one_claim(client):
    authorize(client)
    created = create_standard_chain(client, content="regex: ^Retry\\d+$\nsample: Retry42")
    original_analyzer = client.app.state.evidence.analyzer
    original_semantic_analyzer = client.app.state.evidence.semantic_analyzer
    client.app.state.evidence.semantic_analyzer = None
    analyzer = FlakyAnalyzer("timeout")
    client.app.state.evidence.analyzer = analyzer
    try:
        failed = client.post(
            f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
            json={"request_key": "retry-after-timeout"},
        )
        assert failed.status_code == 200
        assert failed.json()["run"]["status"] == "timeout"
        assert failed.json()["claims"] == []

        succeeded = client.post(
            f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
            json={"request_key": "retry-after-timeout"},
        )
        assert succeeded.status_code == 200
        assert succeeded.json()["run"]["status"] == "succeeded"
        assert succeeded.json()["run"]["attempt"] == 2
        assert len(succeeded.json()["claims"]) == 1

        duplicate = client.post(
            f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
            json={"request_key": "retry-after-timeout"},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["run"]["id"] == succeeded.json()["run"]["id"]
        assert duplicate.json()["run"]["attempt"] == 2
        assert len(duplicate.json()["claims"]) == 1

        runs = client.app.state.learning.database.fetchall(
            """SELECT attempt, status FROM learning_analysis_run
               WHERE owner_id=? AND artifact_id=? ORDER BY attempt""",
            (
                client.app.state.auth.identity_for_session(
                    client.cookies.get(client.app.state.settings.cookie_name)
                )["id"],
                created["artifact"]["id"],
            ),
        )
        assert [tuple(row) for row in runs] == [
            (1, "timeout"),
            (2, "succeeded"),
        ]
        assert client.app.state.learning.database.fetchone(
            "SELECT COUNT(*) FROM learning_evidence_claim"
        )[0] == 1
    finally:
        client.app.state.evidence.analyzer = original_analyzer
        client.app.state.evidence.semantic_analyzer = original_semantic_analyzer
