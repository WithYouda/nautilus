from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from .learning_domain import CriterionRecipe, trusted_claim_method
from .learning_service import LearningService

METRIC_VERSION = "3.0"
OBSERVATION_WINDOW_DAYS = 7
_FAILURE_STATUSES = {
    "failed",
    "timeout",
    "cancelled",
    "invalid_output",
    "permission_denied",
}
_SOURCE_TO_METHOD = {
    "ai_analysis": "semantic_analysis",
    "human_review": "independent_review",
    "deterministic_check": "deterministic_check",
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class MetricResult(BaseModel):
    sample_count: int = Field(default=0, ge=0)
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None = None
    status: Literal["pass", "fail", "no_sample", "observed"]
    unit: Literal["ratio", "count"]
    notes: list[str] = Field(default_factory=list)
    excluded: dict[str, int] = Field(default_factory=dict)


class MeasurementReport(BaseModel):
    metric_version: str
    generated_at: str
    window: str
    product_metrics: dict[str, MetricResult]
    hard_guards: dict[str, MetricResult]


class MeasurementService:
    """Fixed-scope metrics for the first vertical slice."""

    def __init__(self, learning: LearningService):
        self.learning = learning
        self.database = learning.database

    def _ratio(
        self,
        numerator: int,
        denominator: int,
        *,
        higher_is_better: bool = True,
        observational: bool = False,
        notes: list[str] | None = None,
        excluded: dict[str, int] | None = None,
    ) -> MetricResult:
        if denominator == 0:
            return MetricResult(
                numerator=0,
                denominator=0,
                status="no_sample",
                unit="ratio",
                notes=notes or ["No sample in current isolated learning database."],
                excluded=excluded or {},
            )
        value = numerator / denominator
        passed = value == 1 if higher_is_better else value == 0
        return MetricResult(
            sample_count=denominator,
            numerator=numerator,
            denominator=denominator,
            value=value,
            status="observed" if observational else "pass" if passed else "fail",
            unit="ratio",
            notes=notes or [],
            excluded=excluded or {},
        )

    def _count(self, count: int, *, violation: bool = False) -> MetricResult:
        return MetricResult(
            numerator=count,
            denominator=0,
            value=float(count),
            status="fail" if violation and count > 0 else "pass",
            unit="count",
            notes=[] if count == 0 else ["Count is the number of confirmed events."],
        )

    def _claim_rows(self, owner_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.database.fetchall(
                """SELECT c.id, c.artifact_id, c.content_version, c.fact_event_id,
                          c.criterion_id, c.dimension_id, c.source, c.evidence_condition, c.verification_method, c.provenance_json,
                          c.status AS claim_status, raw.purged_at,
                          raw.owner_id AS artifact_owner,
                          raw.fact_event_id AS artifact_fact_event_id,
                          criterion.outcome_id, criterion.review_status, criterion.recipe_json,
                          outcome.id AS outcome_id
                   FROM learning_evidence_claim AS c
                   LEFT JOIN learning_raw_artifact AS raw
                     ON raw.owner_id=c.owner_id
                    AND raw.artifact_id=c.artifact_id
                    AND raw.content_version=c.content_version
                   LEFT JOIN learning_criterion_version AS criterion
                     ON criterion.owner_id=c.owner_id
                    AND criterion.id=c.criterion_id
                   LEFT JOIN learning_outcome AS outcome
                     ON outcome.owner_id=c.owner_id
                    AND outcome.id=criterion.outcome_id
                   WHERE c.owner_id=?""",
                (owner_id,),
            )
        ]

    def _claim_is_supported(self, row: dict[str, Any]) -> bool:
        if (
            row["artifact_owner"] is None
            or row["artifact_fact_event_id"] != row["fact_event_id"]
            or row["outcome_id"] is None
            or row["review_status"] != "approved"
        ):
            return False
        try:
            recipe = CriterionRecipe.model_validate_json(row["recipe_json"])
        except Exception:
            return False
        method = trusted_claim_method(row)
        if method is None:
            return False
        return any(
            dimension.id == row["dimension_id"]
            and requirement.method == method
            for dimension in recipe.dimensions
            for requirement in dimension.requirements
        )

    def _evidence_metrics(self, owner_id: str) -> tuple[MetricResult, MetricResult]:
        rows = self._claim_rows(owner_id)
        purged = sum(1 for row in rows if row["purged_at"] is not None or row["claim_status"] == "invalidated")
        active = [row for row in rows if row["purged_at"] is None and row["claim_status"] != "invalidated"]
        if not active:
            no_sample = self._ratio(
                0,
                0,
                notes=["No active claim exists in the current measurement window."],
                excluded={"invalidated_by_purge": purged},
            )
            return no_sample, no_sample

        supported = sum(1 for row in active if self._claim_is_supported(row))
        unsupported = len(active) - supported
        traceability = self._ratio(
            supported,
            len(active),
            notes=["Claims are counted once by claim ID."],
            excluded={"invalidated_by_purge": purged},
        )
        unsupported_rate = self._ratio(
            unsupported,
            len(active),
            higher_is_better=False,
            notes=["A single unsupported claim fails this hard guard."],
            excluded={"invalidated_by_purge": purged},
        )
        return traceability, unsupported_rate

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _review_events(self, owner_id):
        rows = self.database.fetchall("SELECT * FROM learning_return_review WHERE owner_id=?", (owner_id,))
        for row in rows:
            events = self.database.fetchall("SELECT rowid AS sequence, * FROM learning_usage_event WHERE owner_id=? AND review_id=? ORDER BY rowid", (owner_id, row["id"]))
            yield dict(row), [dict(event) for event in events]

    def _interrupted_delegation_recovery(self, owner_id: str) -> MetricResult:
        successes = attempts = 0
        excluded = {"unknown": 0, "switched": 0, "stopped": 0}
        for review, events in self._review_events(owner_id):
            if review["reason_code"] != "interrupted":
                continue
            kinds = {event["kind"] for event in events}
            if "choose_other" in kinds or "switched" in kinds:
                excluded["switched"] += 1
                continue
            if "stop_for_now" in kinds:
                excluded["stopped"] += 1
                continue
            entered = [event for event in events if event["kind"] == "entered"]
            if not {"review_card_shown", "resume_candidate_presented", "continue", "started"}.issubset(kinds) or not entered:
                excluded["unknown"] += 1
                continue
            attempts += 1
            if entered[0]["delegation_id"] == review["delegation_id"] and "corrected" not in kinds:
                successes += 1
        return self._ratio(successes, attempts, observational=True,
            notes=["Observed explicit resume choice and actual room entry; later correction removes success. No unobserved intent is inferred."], excluded=excluded)

    def _review_to_next_action(self, owner_id: str) -> MetricResult:
        successes = attempts = 0
        excluded = {"window_pending": 0, "declined": 0, "no_linked_execution": 0}
        now = datetime.now(timezone.utc)
        for review, events in self._review_events(owner_id):
            kinds = {event["kind"] for event in events}
            if not review["action_id"] or "review_card_shown" not in kinds:
                continue
            if "choose_other" in kinds or "stop_for_now" in kinds or "corrected" in kinds:
                excluded["declined"] += 1
                continue
            started = next((event for event in events if event["kind"] == "started" and event["action_id"] == review["action_id"]), None)
            if "continue" not in kinds or started is None:
                excluded["no_linked_execution"] += 1
                continue
            deadline = self._parse_time(review["created_at"]) + timedelta(days=OBSERVATION_WINDOW_DAYS)
            completed = any(event["kind"] == "completed" and event["action_id"] == review["action_id"]
                and event['sequence'] > started['sequence'] and self._parse_time(event["created_at"]) <= deadline for event in events)
            if completed:
                successes += 1
                attempts += 1
            elif now < deadline:
                excluded["window_pending"] += 1
            else:
                attempts += 1
        return self._ratio(successes, attempts, observational=True,
            notes=["Stable recommendation, accepted execution and formal action completion are linked; session end never counts."], excluded=excluded)

    def _ai_failure_save_success(self, owner_id: str) -> MetricResult:
        rows = self.database.fetchall(
            """SELECT run.id, run.artifact_id, run.content_version,
                      raw.content IS NOT NULL AS has_content,
                      raw.content_hash IS NOT NULL AS has_hash,
                      raw.purged_at
               FROM learning_analysis_run AS run
               LEFT JOIN learning_raw_artifact AS raw
                 ON raw.owner_id=run.owner_id
                AND raw.artifact_id=run.artifact_id
                AND raw.content_version=run.content_version
               WHERE run.owner_id=? AND run.status IN (
                   'failed', 'timeout', 'cancelled', 'invalid_output', 'permission_denied'
               )""",
            (owner_id,),
        )
        if not rows:
            return self._ratio(
                0,
                0,
                notes=["No AI failure run exists in the current measurement window."],
            )
        successes = 0
        for row in rows:
            saved = row["has_content"] and row["has_hash"]
            intentionally_purged = row["purged_at"] is not None
            if saved or intentionally_purged:
                successes += 1
        return self._ratio(
            successes,
            len(rows),
            notes=["Intentional later purge does not count as a save failure."],
        )

    def _event_rebuild_consistency(self, owner_id: str) -> MetricResult:
        rows = self.database.fetchall("SELECT matched, constraints_ok FROM learning_replay_check WHERE owner_id=?", (owner_id,))
        rejected = self.database.fetchone("SELECT COUNT(*) FROM learning_audit WHERE owner_id=? AND operation IN ('Replay','EvidenceReplay') AND result='rejected'", (owner_id,))[0]
        return self._ratio(sum(bool(row["matched"] and row["constraints_ok"]) for row in rows), len(rows),
            notes=["Same-cutoff domain projection digests, counts, states, relations and constraints compared."],
            excluded={"rejected_before_comparison": rejected})

    def _permission_violations(self, owner_id: str) -> MetricResult:
        count = self.database.fetchone(
            """SELECT COUNT(*) FROM learning_audit
               WHERE owner_id=? AND result='succeeded' AND actor_id<>owner_id
                 AND operation IN (
                     'ReadEvents', 'ReadArtifact', 'AnalyzeEvidence',
                     'ReviewEvidenceClaim', 'BatchReviewEvidenceClaims',
                     'SupersedeArtifactClaims'
                 )""",
            (owner_id,),
        )[0]
        return self._count(count, violation=True)

    def _privacy_leaks(self, owner_id: str) -> MetricResult:
        count = self.database.fetchone(
            """SELECT COUNT(*) FROM learning_raw_artifact
               WHERE owner_id=? AND purged_at IS NOT NULL
                 AND (content IS NOT NULL OR content_hash IS NOT NULL)""",
            (owner_id,),
        )[0]
        return self._count(count, violation=True)

    def report(self, identity: dict[str, Any]) -> MeasurementReport:
        principal = self.learning.principal(identity)
        owner_id = principal.owner_id
        traceability, unsupported_rate = self._evidence_metrics(owner_id)

        return MeasurementReport(
            metric_version=METRIC_VERSION,
            generated_at=utc_timestamp(),
            window=f"All records through report time; review-to-next-action observation window is {OBSERVATION_WINDOW_DAYS} days.",
            product_metrics={
                "interrupted_delegation_recovery": self._interrupted_delegation_recovery(owner_id),
                "review_to_next_action": self._review_to_next_action(owner_id),
                "evidence_traceability": traceability,
            },
            hard_guards={
                "unsupported_claim_rate": unsupported_rate,
                "ai_failure_save_success": self._ai_failure_save_success(owner_id),
                "event_rebuild_consistency": self._event_rebuild_consistency(owner_id),
                "permission_violation_count": self._permission_violations(owner_id),
                "privacy_leak_count": self._privacy_leaks(owner_id),
            },
        )
