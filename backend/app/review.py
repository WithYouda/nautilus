from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .learning_domain import CriterionRecipe, DomainError, Principal, trusted_claim_method
from .learning_service import LearningService
from .state_derivation import StateDerivationService

_SOURCE_TO_METHOD = {
    "ai_analysis": "semantic_analysis",
    "human_review": "independent_review",
    "deterministic_check": "deterministic_check",
}

_ACTION_TO_STATUS = {
    "adopt": "adopted",
    "question": "questioned",
    "withdraw": "withdrawn",
    "supersede": "superseded",
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class ReviewService:
    """User review actions, batch review, and evidence replacements."""

    def __init__(
        self,
        learning: LearningService,
        state_derivation: StateDerivationService,
        evidence_events: Any | None = None,
    ):
        self.learning = learning
        self.database = learning.database
        self.state_derivation = state_derivation
        self.evidence_events = evidence_events

    def _principal(self, identity: dict[str, Any]) -> Principal:
        return self.learning.principal(identity)

    def _claim(self, principal: Principal, claim_id: str) -> dict[str, Any]:
        row = self.database.fetchone(
            "SELECT * FROM learning_evidence_claim WHERE owner_id=? AND id=?",
            (principal.owner_id, claim_id),
        )
        if row is None:
            raise DomainError("not_found", 404)
        return dict(row)

    def _recipe(self, principal: Principal, criterion_id: str) -> CriterionRecipe:
        row = self.database.fetchone(
            "SELECT recipe_json, review_status FROM learning_criterion_version WHERE owner_id=? AND id=?",
            (principal.owner_id, criterion_id),
        )
        if row is None:
            raise DomainError("not_found", 404)
        if row["review_status"] != "approved":
            raise DomainError("criterion_not_approved", 409)
        try:
            return CriterionRecipe.model_validate_json(row["recipe_json"])
        except Exception as exc:
            raise DomainError("criterion_invalid_recipe", 409) from exc

    def _qualifies_for_adoption(self, principal: Principal, claim: dict[str, Any]) -> bool:
        recipe = self._recipe(principal, claim["criterion_id"])
        method = trusted_claim_method(claim)
        return any(
            dimension.id == claim["dimension_id"]
            and requirement.method == method
            for dimension in recipe.dimensions
            for requirement in dimension.requirements
        )

    def _audit(
        self,
        connection,
        principal: Principal,
        operation: str,
        result: str,
        reference_id: str | None = None,
        reason_code: str | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO learning_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                principal.owner_id,
                principal.actor_id,
                operation,
                result,
                reference_id,
                reason_code,
                utc_timestamp(),
            ),
        )

    def _validate_transition(
        self,
        principal: Principal,
        claim: dict[str, Any],
        action: str,
        replacement_claim_id: str | None,
    ) -> tuple[str, str, dict[str, Any] | None]:
        from_status = claim["status"]
        if from_status == "invalidated":
            raise DomainError("artifact_not_eligible", 409)
        replacement: dict[str, Any] | None = None
        if action == "defer":
            to_status = from_status
            if from_status != "candidate":
                raise DomainError("claim_not_candidate", 409)
        else:
            to_status = _ACTION_TO_STATUS[action]
            if action == "adopt":
                if from_status != "candidate":
                    raise DomainError("claim_not_candidate", 409)
                if not self._qualifies_for_adoption(principal, claim):
                    raise DomainError("claim_not_qualifying", 409)
            elif action == "supersede":
                if not replacement_claim_id:
                    raise DomainError("replacement_claim_required", 422)
                replacement = self._claim(principal, replacement_claim_id)
                if replacement["id"] == claim["id"]:
                    raise DomainError("replacement_claim_invalid", 409)
                if (
                    replacement["criterion_id"] != claim["criterion_id"]
                    or replacement["dimension_id"] != claim["dimension_id"]
                ):
                    raise DomainError("replacement_claim_invalid", 409)
                if replacement["status"] not in {"candidate", "adopted"}:
                    raise DomainError("replacement_claim_invalid", 409)
            elif from_status not in {"candidate", "adopted"}:
                raise DomainError("claim_review_invalid_transition", 409)
        return from_status, to_status, replacement

    def _insert_review_action(
        self,
        connection,
        principal: Principal,
        claim_id: str,
        action: str,
        from_status: str,
        to_status: str,
        reason: str | None,
        request_key: str,
        replacement_claim_id: str | None,
        now: str,
    ) -> str:
        review_id = str(uuid4())
        connection.execute(
            """INSERT INTO learning_review_action
               (id, owner_id, claim_id, action, from_status, to_status, reason,
                request_key, created_at, replacement_claim_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                review_id,
                principal.owner_id,
                claim_id,
                action,
                from_status,
                to_status,
                reason,
                request_key,
                now,
                replacement_claim_id,
            ),
        )
        return review_id

    def review(
        self,
        identity: dict[str, Any],
        claim_id: str,
        action: str,
        reason: str | None,
        request_key: str,
        replacement_claim_id: str | None = None,
    ) -> dict[str, Any]:
        principal = self._principal(identity)
        claim = self._claim(principal, claim_id)
        existing = self.database.fetchone(
            "SELECT * FROM learning_review_action WHERE owner_id=? AND request_key=?",
            (principal.owner_id, request_key),
        )
        if existing is not None:
            if (
                existing["claim_id"] != claim_id
                or existing["action"] != action
                or existing["reason"] != reason
                or existing["replacement_claim_id"] != replacement_claim_id
            ):
                raise DomainError("idempotency_conflict", 409)
            return dict(existing)

        from_status, to_status, replacement = self._validate_transition(
            principal,
            claim,
            action,
            replacement_claim_id,
        )
        review_id = str(uuid4())
        now = utc_timestamp()
        with self.database.transaction(immediate=True) as connection:
            from_status, to_status, replacement = self._validate_transition(
                principal, self._claim(principal, claim_id), action, replacement_claim_id,
            )
            review_id = self._insert_review_action(
                connection,
                principal,
                claim_id,
                action,
                from_status,
                to_status,
                reason,
                request_key,
                replacement_claim_id,
                now,
            )
            if self.evidence_events is not None:
                self.evidence_events.append(
                    principal.owner_id,
                    "review",
                    review_id,
                    "review.recorded",
                    {
                        "id": review_id,
                        "claim_id": claim_id,
                        "action": action,
                        "from_status": from_status,
                        "to_status": to_status,
                        "reason": reason,
                        "request_key": request_key,
                        "replacement_claim_id": replacement_claim_id,
                        "created_at": now,
                    },
                    connection=connection,
                )
            if to_status != from_status:
                changed = connection.execute(
                    "UPDATE learning_evidence_claim SET status=? WHERE owner_id=? AND id=?",
                    (to_status, principal.owner_id, claim_id),
                ).rowcount
                if changed != 1:
                    raise DomainError("claim_review_conflict", 409)
            if action == "supersede" and replacement is not None:
                connection.execute(
                    """INSERT INTO learning_claim_replacement
                       (id, owner_id, superseded_claim_id, replacement_claim_id, reason, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid4()),
                        principal.owner_id,
                        claim_id,
                        replacement["id"],
                        reason or "user replacement",
                        now,
                    ),
                )
            self._audit(
                connection,
                principal,
                "ReviewEvidenceClaim",
                "succeeded",
                review_id,
                action,
            )

            if action != "defer":
                self.state_derivation.derive(identity, claim["criterion_id"], connection=connection)

        row = self.database.fetchone(
            "SELECT * FROM learning_review_action WHERE owner_id=? AND id=?",
            (principal.owner_id, review_id),
        )
        return dict(row)

    def batch_review(
        self,
        identity: dict[str, Any],
        claim_ids: list[str],
        action: str,
        reason: str | None,
        request_key: str,
    ) -> dict[str, Any]:
        principal = self._principal(identity)
        existing = self.database.fetchone(
            "SELECT * FROM learning_batch_review_action WHERE owner_id=? AND request_key=?",
            (principal.owner_id, request_key),
        )
        if existing is not None:
            if (
                existing["action"] != action
                or existing["reason"] != reason
                or json.loads(existing["claim_ids_json"]) != claim_ids
            ):
                raise DomainError("idempotency_conflict", 409)
            return dict(existing)

        claims = [self._claim(principal, claim_id) for claim_id in claim_ids]
        transitions = [
            self._validate_transition(principal, claim, action, None)
            for claim in claims
        ]
        if action == "adopt":
            criteria = {claim["criterion_id"] for claim in claims}
            if len(criteria) != 1:
                raise DomainError("batch_claims_not_homogeneous", 409)

        batch_id = str(uuid4())
        now = utc_timestamp()
        review_ids: list[str] = []
        with self.database.transaction(immediate=True) as connection:
            transitions = [self._validate_transition(principal, self._claim(principal, claim["id"]), action, None) for claim in claims]
            connection.execute(
                """INSERT INTO learning_batch_review_action
                   (id, owner_id, action, reason, request_key, claim_ids_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    batch_id,
                    principal.owner_id,
                    action,
                    reason,
                    request_key,
                    json.dumps(claim_ids, separators=(",", ":")),
                    now,
                ),
            )
            if self.evidence_events is not None:
                self.evidence_events.append(
                    principal.owner_id,
                    "review",
                    batch_id,
                    "batch.reviewed",
                    {
                        "id": batch_id,
                        "action": action,
                        "reason": reason,
                        "request_key": request_key,
                        "claim_ids": claim_ids,
                        "created_at": now,
                    },
                    connection=connection,
                )
            for claim, (from_status, to_status, _replacement) in zip(claims, transitions):
                review_id = self._insert_review_action(
                    connection,
                    principal,
                    claim["id"],
                    action,
                    from_status,
                    to_status,
                    reason,
                    f"{request_key}:{claim['id']}",
                    None,
                    now,
                )
                review_ids.append(review_id)
                if self.evidence_events is not None:
                    self.evidence_events.append(
                        principal.owner_id,
                        "review",
                        review_id,
                        "review.recorded",
                        {
                            "id": review_id,
                            "claim_id": claim["id"],
                            "action": action,
                            "from_status": from_status,
                            "to_status": to_status,
                            "reason": reason,
                            "request_key": f"{request_key}:{claim['id']}",
                            "replacement_claim_id": None,
                            "created_at": now,
                        },
                        connection=connection,
                        private_claim_ids=claim_ids,
                    )
                if to_status != from_status:
                    changed = connection.execute(
                        "UPDATE learning_evidence_claim SET status=? WHERE owner_id=? AND id=?",
                        (to_status, principal.owner_id, claim["id"]),
                    ).rowcount
                    if changed != 1:
                        raise DomainError("claim_review_conflict", 409)
                self._audit(
                    connection,
                    principal,
                    "ReviewEvidenceClaim",
                    "succeeded",
                    review_id,
                    action,
                )
            self._audit(
                connection,
                principal,
                "BatchReviewEvidenceClaims",
                "succeeded",
                batch_id,
                action,
            )

            if action != "defer":
                criteria = {claim["criterion_id"] for claim in claims}
                for criterion_id in criteria:
                    self.state_derivation.derive(identity, criterion_id, connection=connection)

        row = self.database.fetchone(
            "SELECT * FROM learning_batch_review_action WHERE owner_id=? AND id=?",
            (principal.owner_id, batch_id),
        )
        result = dict(row)
        result["review_ids"] = review_ids
        return result

    def supersede_artifact_versions(
        self,
        identity: dict[str, Any],
        artifact_id: str,
    ) -> dict[str, Any]:
        principal = self._principal(identity)
        with self.database.transaction(immediate=True) as connection:
            latest = self.database.fetchone(
                """SELECT MAX(content_version) AS latest FROM learning_raw_artifact
                   WHERE owner_id=? AND artifact_id=?""",
                (principal.owner_id, artifact_id),
            )
            if latest is None or latest["latest"] is None:
                raise DomainError("not_found", 404)
            latest_version = latest["latest"]
            claims = self.database.fetchall(
                """SELECT id, status, criterion_id FROM learning_evidence_claim
                   WHERE owner_id=? AND artifact_id=? AND content_version<?""",
                (principal.owner_id, artifact_id, latest_version),
            )
            now = utc_timestamp()
            superseded_count = 0
            criterion_ids: set[str] = set()
            for claim in claims:
                if claim["status"] in {"superseded", "invalidated"}:
                    continue
                review_id = self._insert_review_action(
                    connection,
                    principal,
                    claim["id"],
                    "supersede",
                    claim["status"],
                    "superseded",
                    "artifact corrected",
                    f"correction:{artifact_id}:{latest_version}:{claim['id']}",
                    None,
                    now,
                )
                connection.execute(
                    "UPDATE learning_evidence_claim SET status='superseded' WHERE owner_id=? AND id=?",
                    (principal.owner_id, claim["id"]),
                )
                if self.evidence_events is not None:
                    self.evidence_events.append(principal.owner_id, "review", review_id, "review.recorded", {
                        "id": review_id, "claim_id": claim["id"], "action": "supersede",
                        "from_status": claim["status"], "to_status": "superseded", "reason": "artifact corrected",
                        "request_key": f"correction:{artifact_id}:{latest_version}:{claim['id']}", "created_at": now,
                    }, connection=connection)
                superseded_count += 1
                criterion_ids.add(claim["criterion_id"])
                self._audit(
                    connection,
                    principal,
                    "ReviewEvidenceClaim",
                    "succeeded",
                    review_id,
                    "supersede",
                )
            if superseded_count:
                self._audit(
                    connection,
                    principal,
                    "SupersedeArtifactClaims",
                    "succeeded",
                    artifact_id,
                    "artifact_corrected",
                )

            for criterion_id in criterion_ids:
                self.state_derivation.derive(identity, criterion_id, connection=connection)

        return {
            "artifact_id": artifact_id,
            "latest_content_version": latest_version,
            "superseded_claim_count": superseded_count,
        }

    def actions(self, identity: dict[str, Any]) -> list[dict[str, Any]]:
        principal = self._principal(identity)
        return [
            dict(row)
            for row in self.database.fetchall(
                """SELECT * FROM learning_review_action
                   WHERE owner_id=?
                   ORDER BY created_at DESC, id""",
                (principal.owner_id,),
            )
        ]

    def replacements(self, identity: dict[str, Any]) -> list[dict[str, Any]]:
        principal = self._principal(identity)
        return [
            dict(row)
            for row in self.database.fetchall(
                """SELECT * FROM learning_claim_replacement
                   WHERE owner_id=?
                   ORDER BY created_at DESC, id""",
                (principal.owner_id,),
            )
        ]
