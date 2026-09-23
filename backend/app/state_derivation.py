from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .learning_domain import CriterionRecipe, DomainError, Principal, trusted_claim_method
from .learning_service import LearningService

_SOURCE_TO_METHOD = {
    "ai_analysis": "semantic_analysis",
    "human_review": "independent_review",
    "deterministic_check": "deterministic_check",
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class StateDerivationService:
    """Derive dimension state from currently applicable adopted claims."""

    def __init__(self, learning: LearningService, evidence_events: Any | None = None):
        self.learning = learning
        self.database = learning.database
        self.evidence_events = evidence_events

    def _principal(self, identity: dict[str, Any]) -> Principal:
        return self.learning.principal(identity)

    def _criterion(self, principal: Principal, criterion_id: str) -> tuple[dict[str, Any], CriterionRecipe]:
        row = self.database.fetchone(
            """SELECT id, outcome_id, version, recipe_json, review_status
               FROM learning_criterion_version
               WHERE owner_id=? AND id=?""",
            (principal.owner_id, criterion_id),
        )
        if row is None:
            raise DomainError("not_found", 404)
        criterion = dict(row)
        if criterion["review_status"] != "approved":
            raise DomainError("criterion_not_approved", 409)
        try:
            recipe = CriterionRecipe.model_validate_json(criterion["recipe_json"])
        except Exception as exc:
            raise DomainError("criterion_invalid_recipe", 409) from exc
        return criterion, recipe

    def _claims(self, principal: Principal, criterion_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.database.fetchall(
                """SELECT c.id, c.dimension_id, c.stance, c.status, c.source,
                          c.evidence_condition, c.verification_method, c.provenance_json, c.artifact_id, c.content_version,
                          current_artifact.content_version AS current_content_version,
                          current_artifact.visibility AS artifact_visibility,
                          current_artifact.evidence_status AS artifact_evidence_status
                   FROM learning_evidence_claim AS c
                   LEFT JOIN learning_artifact AS current_artifact
                     ON current_artifact.owner_id=c.owner_id
                    AND current_artifact.id=c.artifact_id
                   WHERE c.owner_id=? AND c.criterion_id=?
                   ORDER BY c.created_at, c.id""",
                (principal.owner_id, criterion_id),
            )
        ]

    def _derive_dimension(
        self,
        dimension: Any,
        claims: list[dict[str, Any]],
    ) -> dict[str, Any]:
        participating: list[str] = []
        excluded: list[str] = []
        excluded_reasons: list[dict[str, str]] = []
        supporting_by_requirement: list[int] = []
        has_refutation = False
        has_insufficient = False
        has_current_candidate = False
        has_current_adopted = False

        for claim in claims:
            current = (
                claim["current_content_version"] is not None
                and claim["current_content_version"] == claim["content_version"]
                and claim["artifact_visibility"] == "visible"
                and claim["artifact_evidence_status"] == "eligible"
            )
            if not current or claim["dimension_id"] != dimension.id:
                reason = "stale_version" if not current else "dimension_mismatch"
                excluded.append(claim["id"])
                excluded_reasons.append({"claim_id": claim["id"], "reason": reason})
                continue

            if claim["status"] == "candidate":
                has_current_candidate = True
                excluded.append(claim["id"])
                excluded_reasons.append({"claim_id": claim["id"], "reason": "candidate_awaiting_review"})
                continue
            if claim["status"] != "adopted":
                excluded.append(claim["id"])
                excluded_reasons.append({"claim_id": claim["id"], "reason": f"claim_{claim['status']}"})
                continue

            has_current_adopted = True
            method = trusted_claim_method(claim)
            matches_requirement = any(
                requirement.method == method
                for requirement in dimension.requirements
            )
            if not matches_requirement:
                excluded.append(claim["id"])
                excluded_reasons.append({"claim_id": claim["id"], "reason": "recipe_mismatch"})
                continue

            participating.append(claim["id"])
            if claim["stance"] == "refutes":
                has_refutation = True
            elif claim["stance"] == "insufficient":
                has_insufficient = True

        for requirement in dimension.requirements:
            count = 0
            for claim in claims:
                current = (
                    claim["current_content_version"] is not None
                    and claim["current_content_version"] == claim["content_version"]
                    and claim["artifact_visibility"] == "visible"
                    and claim["artifact_evidence_status"] == "eligible"
                )
                if (
                    current
                    and claim["status"] == "adopted"
                    and claim["dimension_id"] == dimension.id
                    and claim["stance"] == "supports"
                    and trusted_claim_method(claim) == requirement.method
                    and claim["evidence_condition"] == requirement.condition
                ):
                    count += 1
            supporting_by_requirement.append(count)

        met = [count >= requirement.minimum for count, requirement in zip(supporting_by_requirement, dimension.requirements)]
        if has_refutation:
            status = "contradicted"
            reason = "contradictory_evidence"
        elif all(met):
            semantic_only = all(claim["source"] == "ai_analysis" for claim in claims if claim["id"] in participating)
            status = "partially_supported" if semantic_only else "supported"
            reason = "ai_observation_only" if semantic_only else "requirements_met"
        elif any(met):
            status = "partially_supported"
            reason = "requirements_partially_met"
        elif participating and any(claim["stance"] == "supports" for claim in claims if claim["id"] in participating):
            status = "partially_supported"
            reason = "independence_unverified"
        elif has_insufficient:
            status = "insufficient_evidence"
            reason = "insufficient_adopted_evidence"
        elif has_current_candidate:
            status = "pending_review"
            reason = "candidate_awaiting_review"
        elif has_current_adopted:
            status = "insufficient_evidence"
            reason = "adopted_claim_does_not_match_recipe"
        else:
            status = "awaiting_evidence"
            reason = "no_current_evidence"

        return {
            "dimension_id": dimension.id,
            "status": status,
            "reason_code": reason,
            "participating_claim_ids": participating,
            "excluded_claim_ids": excluded,
            "excluded_claim_reasons": excluded_reasons,
        }

    def _persist(
        self,
        principal: Principal,
        criterion: dict[str, Any],
        derived: dict[str, Any],
        connection=None,
    ) -> dict[str, Any]:
        dimension_id = derived["dimension_id"]
        history_count = self.database.fetchone(
            """SELECT COUNT(*) FROM learning_derived_state_history
               WHERE owner_id=? AND criterion_id=? AND dimension_id=?""",
            (principal.owner_id, criterion["id"], dimension_id),
        )[0]
        calculation_version = history_count + 1
        state_id = str(uuid4())
        now = utc_timestamp()
        participating_json = json.dumps(derived["participating_claim_ids"], separators=(",", ":"))
        excluded_json = json.dumps(derived["excluded_claim_ids"], separators=(",", ":"))
        excluded_reasons_json = json.dumps(derived["excluded_claim_reasons"], separators=(",", ":"))

        with (nullcontext(connection) if connection is not None else self.database.transaction(immediate=True)) as connection:
            connection.execute(
                """INSERT INTO learning_derived_state
                   (id, owner_id, outcome_id, criterion_id, dimension_id, status, reason_code,
                    standard_version, calculation_version, participating_claim_ids_json,
                    excluded_claim_ids_json, excluded_claim_reasons_json, calculated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(owner_id, criterion_id, dimension_id) DO UPDATE SET
                       id=excluded.id,
                       status=excluded.status,
                       reason_code=excluded.reason_code,
                       standard_version=excluded.standard_version,
                       calculation_version=excluded.calculation_version,
                       participating_claim_ids_json=excluded.participating_claim_ids_json,
                       excluded_claim_ids_json=excluded.excluded_claim_ids_json,
                       excluded_claim_reasons_json=excluded.excluded_claim_reasons_json,
                       calculated_at=excluded.calculated_at""",
                (
                    state_id,
                    principal.owner_id,
                    criterion["outcome_id"],
                    criterion["id"],
                    dimension_id,
                    derived["status"],
                    derived["reason_code"],
                    criterion["version"],
                    calculation_version,
                    participating_json,
                    excluded_json,
                    excluded_reasons_json,
                    now,
                ),
            )
            connection.execute(
                """INSERT INTO learning_derived_state_history
                   (id, owner_id, outcome_id, criterion_id, dimension_id, status, reason_code,
                    standard_version, calculation_version, participating_claim_ids_json,
                    excluded_claim_ids_json, excluded_claim_reasons_json, calculated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()),
                    principal.owner_id,
                    criterion["outcome_id"],
                    criterion["id"],
                    dimension_id,
                    derived["status"],
                    derived["reason_code"],
                    criterion["version"],
                    calculation_version,
                    participating_json,
                    excluded_json,
                    excluded_reasons_json,
                    now,
                ),
            )

            if self.evidence_events is not None:
                self.evidence_events.append(
                    principal.owner_id,
                    "state",
                    state_id,
                    "state.derived",
                    {
                        "id": state_id,
                        "outcome_id": criterion["outcome_id"],
                        "criterion_id": criterion["id"],
                        "dimension_id": dimension_id,
                        "status": derived["status"],
                        "reason_code": derived["reason_code"],
                        "standard_version": criterion["version"],
                        "calculation_version": calculation_version,
                        "participating_claim_ids": derived["participating_claim_ids"],
                        "excluded_claim_ids": derived["excluded_claim_ids"],
                        "excluded_claim_reasons": derived["excluded_claim_reasons"],
                        "calculated_at": now,
                    },
                    connection=connection,
                )

        return {
            "id": state_id,
            "owner_id": principal.owner_id,
            "outcome_id": criterion["outcome_id"],
            "criterion_id": criterion["id"],
            "dimension_id": dimension_id,
            "status": derived["status"],
            "reason_code": derived["reason_code"],
            "standard_version": criterion["version"],
            "calculation_version": calculation_version,
            "participating_claim_ids": derived["participating_claim_ids"],
            "excluded_claim_ids": derived["excluded_claim_ids"],
            "excluded_claim_reasons": derived["excluded_claim_reasons"],
            "calculated_at": now,
        }

    def _refresh_revisit_queue(
        self,
        principal: Principal,
        criterion: dict[str, Any],
        states: list[dict[str, Any]],
        connection=None,
    ) -> None:
        now = utc_timestamp()
        expected: list[dict[str, Any]] = []

        questioned_claims = self.database.fetchall(
            """SELECT c.id, c.dimension_id
               FROM learning_evidence_claim AS c
               JOIN learning_artifact AS current_artifact
                 ON current_artifact.owner_id=c.owner_id
                AND current_artifact.id=c.artifact_id
               WHERE c.owner_id=? AND c.criterion_id=? AND c.status='questioned'
                 AND current_artifact.content_version=c.content_version
                 AND current_artifact.visibility='visible'
                 AND current_artifact.evidence_status='eligible'""",
            (principal.owner_id, criterion["id"]),
        )
        for claim in questioned_claims:
            expected.append(
                {
                    "source_kind": "questioned_claim",
                    "source_id": claim["id"],
                    "claim_id": claim["id"],
                    "dimension_id": claim["dimension_id"],
                    "reason": "claim_questioned",
                    "due_at": now,
                }
            )

        for state in states:
            if state["status"] == "insufficient_evidence":
                expected.append(
                    {
                        "source_kind": "insufficient_state",
                        "source_id": state["id"],
                        "claim_id": None,
                        "dimension_id": state["dimension_id"],
                        "reason": state["reason_code"],
                        "due_at": now,
                    }
                )

        follow_ups = self.database.fetchall(
            """SELECT f.id, f.due_at, c.id AS claim_id, c.dimension_id
               FROM learning_evidence_follow_up AS f
               JOIN learning_evidence_claim AS c
                 ON c.owner_id=f.owner_id AND c.id=f.claim_id
               WHERE f.owner_id=? AND c.criterion_id=?
                 AND f.kind='supplemental_verification'
                 AND f.status='pending'
                 AND c.status <> 'invalidated'
                 AND f.due_at IS NOT NULL
                 AND f.due_at <= ?""",
            (principal.owner_id, criterion["id"], now),
        )
        for follow_up in follow_ups:
            expected.append(
                {
                    "source_kind": "supplemental_verification",
                    "source_id": follow_up["id"],
                    "claim_id": follow_up["claim_id"],
                    "dimension_id": follow_up["dimension_id"],
                    "reason": "supplemental_verification_due",
                    "due_at": follow_up["due_at"],
                }
            )

        expected_keys = {
            (item["source_kind"], item["source_id"]) for item in expected
        }
        with (nullcontext(connection) if connection is not None else self.database.transaction(immediate=True)) as connection:
            existing_pending = connection.execute(
                """SELECT source_kind, source_id FROM learning_revisit_item
                   WHERE owner_id=? AND criterion_id=? AND status='pending'""",
                (principal.owner_id, criterion["id"]),
            ).fetchall()
            for row in existing_pending:
                key = (row["source_kind"], row["source_id"])
                if key not in expected_keys:
                    connection.execute(
                        """UPDATE learning_revisit_item
                           SET status='cancelled', updated_at=?
                           WHERE owner_id=? AND source_kind=? AND source_id=?""",
                        (now, principal.owner_id, row["source_kind"], row["source_id"]),
                    )

            for item in expected:
                connection.execute(
                    """INSERT INTO learning_revisit_item
                       (id, owner_id, source_kind, source_id, claim_id, criterion_id,
                        dimension_id, reason, due_at, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                       ON CONFLICT(owner_id, source_kind, source_id) DO UPDATE SET
                           claim_id=excluded.claim_id,
                           dimension_id=excluded.dimension_id,
                           reason=excluded.reason,
                           due_at=excluded.due_at,
                           status='pending',
                           updated_at=excluded.updated_at""",
                    (
                        str(uuid4()),
                        principal.owner_id,
                        item["source_kind"],
                        item["source_id"],
                        item["claim_id"],
                        criterion["id"],
                        item["dimension_id"],
                        item["reason"],
                        item["due_at"],
                        now,
                        now,
                    ),
                )

    def derive(
        self,
        identity: dict[str, Any],
        criterion_id: str | None = None,
        connection=None,
    ) -> list[dict[str, Any]]:
        if connection is None:
            self._principal(identity)
            with self.database.transaction(immediate=True) as transaction:
                return self.derive(identity, criterion_id, connection=transaction)
        principal = Principal.user(identity["id"])
        if criterion_id is not None:
            criterion_ids = [criterion_id]
        else:
            criterion_ids = [
                row["id"]
                for row in self.database.fetchall(
                    "SELECT id FROM learning_criterion_version WHERE owner_id=? ORDER BY created_at, id",
                    (principal.owner_id,),
                )
            ]

        results: list[dict[str, Any]] = []
        for current_criterion_id in criterion_ids:
            criterion, recipe = self._criterion(principal, current_criterion_id)
            claims = self._claims(principal, current_criterion_id)
            criterion_states: list[dict[str, Any]] = []
            for dimension in recipe.dimensions:
                derived = self._derive_dimension(dimension, claims)
                criterion_states.append(self._persist(principal, criterion, derived, connection))
            self._refresh_revisit_queue(principal, criterion, criterion_states, connection)
            results.extend(criterion_states)
        return results

    def recalculate(
        self,
        identity: dict[str, Any],
        criterion_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.derive(identity, criterion_id)

    def states(self, identity: dict[str, Any], *, connection=None) -> list[dict[str, Any]]:
        principal = Principal.user(identity['id']) if connection is not None else self._principal(identity)
        rows = self.database.fetchall(
            """SELECT id, owner_id, outcome_id, criterion_id, dimension_id, status,
                      reason_code, standard_version, calculation_version,
                      participating_claim_ids_json, excluded_claim_ids_json,
                      excluded_claim_reasons_json, calculated_at
               FROM learning_derived_state
               WHERE owner_id=?
               ORDER BY criterion_id, dimension_id""",
            (principal.owner_id,),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["participating_claim_ids"] = json.loads(item.pop("participating_claim_ids_json"))
            item["excluded_claim_ids"] = json.loads(item.pop("excluded_claim_ids_json"))
            item["excluded_claim_reasons"] = json.loads(item.pop("excluded_claim_reasons_json"))
            if item['status'] in {'supported', 'partially_supported', 'contradicted'} or item['reason_code']=='execution_provenance_unverified':
                unverified = []
                for claim_id in item['participating_claim_ids']:
                    claim = self.database.fetchone('SELECT * FROM learning_evidence_claim WHERE owner_id=? AND id=?', (principal.owner_id, claim_id))
                    if claim is None or trusted_claim_method(dict(claim)) is None:
                        unverified.append(claim_id)
                if unverified:
                    item['status'] = 'insufficient_evidence'
                    item['reason_code'] = 'execution_provenance_unverified'
                    item['participating_claim_ids'] = [key for key in item['participating_claim_ids'] if key not in unverified]
                    item['excluded_claim_ids'] = sorted(set(item['excluded_claim_ids']) | set(unverified))
                    item['excluded_claim_reasons'].extend({'claim_id':key, 'reason':'execution_provenance_unverified'} for key in unverified)
            result.append(item)
        return result

    def refresh_revisit_queues(self, identity: dict[str, Any]) -> None:
        principal = self._principal(identity)
        criterion_ids = [
            row["id"]
            for row in self.database.fetchall(
                "SELECT id FROM learning_criterion_version WHERE owner_id=? ORDER BY created_at, id",
                (principal.owner_id,),
            )
        ]
        for criterion_id in criterion_ids:
            criterion, _recipe = self._criterion(principal, criterion_id)
            states = [
                dict(row)
                for row in self.database.fetchall(
                    """SELECT id, dimension_id, status, reason_code
                       FROM learning_derived_state
                       WHERE owner_id=? AND criterion_id=?""",
                    (principal.owner_id, criterion_id),
                )
            ]
            self._refresh_revisit_queue(principal, criterion, states)

    def revisit_queue(self, identity: dict[str, Any]) -> list[dict[str, Any]]:
        principal = self._principal(identity)
        return [
            dict(row)
            for row in self.database.fetchall(
                """SELECT id, owner_id, source_kind, source_id, claim_id, criterion_id,
                          dimension_id, reason, due_at, status, created_at, updated_at
                   FROM learning_revisit_item
                   WHERE owner_id=?
                   ORDER BY due_at, id""",
                (principal.owner_id,),
            )
        ]

    def history(self, identity: dict[str, Any]) -> list[dict[str, Any]]:
        principal = self._principal(identity)
        rows = self.database.fetchall(
            """SELECT id, owner_id, outcome_id, criterion_id, dimension_id, status,
                      reason_code, standard_version, calculation_version,
                      participating_claim_ids_json, excluded_claim_ids_json,
                      excluded_claim_reasons_json, calculated_at
               FROM learning_derived_state_history
               WHERE owner_id=?
               ORDER BY calculated_at, id""",
            (principal.owner_id,),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["participating_claim_ids"] = json.loads(item.pop("participating_claim_ids_json"))
            item["excluded_claim_ids"] = json.loads(item.pop("excluded_claim_ids_json"))
            item["excluded_claim_reasons"] = json.loads(item.pop("excluded_claim_reasons_json"))
            result.append(item)
        return result
