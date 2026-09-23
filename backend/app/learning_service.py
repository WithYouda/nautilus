from __future__ import annotations

import json
import sqlite3
from typing import Any

from .core.commands import (
    CorrectArtifact,
    CompleteLearningAction,
    CreateDelegation,
    CreateLearningAction,
    CreateOutcome,
    EndSession,
    PurgeArtifact,
    RestoreArtifact,
    SoftDeleteArtifact,
    WithdrawArtifact,
    SaveTextArtifact,
    StartSession,
)
from .core.learning import LearningCore
from .db import Database
from .learning_domain import DomainError, Principal
from .standards import load_approved_standard_package, seed_standard_package


class LearningService:
    """Application boundary for the independent first-slice fact database."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.core = LearningCore(database)
        self.standard_package = load_approved_standard_package()

    def close(self) -> None:
        self.database.close()

    def principal(self, identity: dict[str, Any]) -> Principal:
        self._ensure_identity(identity)
        return Principal.user(identity["id"])

    def _ensure_identity(self, identity: dict[str, Any]) -> None:
        existing = self.database.fetchone(
            "SELECT 1 FROM local_identity WHERE id=?",
            (identity["id"],),
        )
        if existing:
            seed_standard_package(self.database, identity["id"], self.standard_package)
            return
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO local_identity
                   (id, device_id, display_name, timezone, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    identity["id"],
                    identity["device_id"],
                    identity["display_name"],
                    identity["timezone"],
                    identity["created_at"],
                    identity["created_at"],
                ),
            )
        seed_standard_package(self.database, identity["id"], self.standard_package)

    def overview(self, identity: dict[str, Any]) -> dict[str, Any]:
        principal = self.principal(identity)
        owner = principal.owner_id

        goals = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT id, original_intent, title, description, status, version, created_at, updated_at
                   FROM learning_goal WHERE owner_id=? ORDER BY created_at DESC, id""",
                (owner,),
            )
        ]
        plans = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT id, goal_id, title, description, status, version, created_at, updated_at
                   FROM learning_plan WHERE owner_id=? ORDER BY created_at DESC, id""",
                (owner,),
            )
        ]
        modules = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT id, plan_id, parent_module_id, title, description, position, status,
                          created_at, updated_at
                   FROM learning_module WHERE owner_id=? ORDER BY plan_id, position, id""",
                (owner,),
            )
        ]
        action_links = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT owner_id, action_id, plan_id, module_id, created_at
                   FROM learning_action_link WHERE owner_id=? ORDER BY created_at, action_id""",
                (owner,),
            )
        ]
        setups = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT id, goal_id, plan_id, action_id, outcome_id, delegation_id,
                          original_intent, status, version, created_at
                   FROM learning_setup WHERE owner_id=? ORDER BY created_at DESC, id""",
                (owner,),
            )
        ]

        actions = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT a.id, a.title, a.context_key, a.status, a.version, a.created_at,
                          COALESCE(sh.event_count, 0) AS aggregate_version
                   FROM learning_action AS a
                   LEFT JOIN learning_stream_head AS sh
                     ON sh.owner_id=a.owner_id
                    AND sh.aggregate_type='action'
                    AND sh.aggregate_id=a.id
                   WHERE a.owner_id=?
                   ORDER BY a.created_at DESC, a.id""",
                (owner,),
            )
        ]
        outcomes = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT id, object_description, behavior, context_key, source, created_at
                   FROM learning_outcome
                   WHERE owner_id=?
                   ORDER BY created_at DESC, id""",
                (owner,),
            )
        ]
        standards = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT c.id, c.outcome_id, c.package_id, c.version, c.context_key, c.review_status,
                          p.title AS package_title,
                          o.object_description, o.behavior
                   FROM learning_criterion_version AS c
                   JOIN learning_standard_package AS p
                     ON p.owner_id=c.owner_id AND p.id=c.package_id
                   JOIN learning_outcome AS o
                     ON o.owner_id=c.owner_id AND o.id=c.outcome_id
                   LEFT JOIN learning_criterion_availability AS unavailable
                     ON unavailable.owner_id=c.owner_id
                    AND unavailable.criterion_id=c.id
                   WHERE c.owner_id=? AND c.review_status='approved'
                     AND unavailable.criterion_id IS NULL
                   ORDER BY c.created_at DESC, c.id""",
                (owner,),
            )
        ]
        delegations = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT d.id, d.action_id, d.outcome_id, d.criterion_id,
                          d.contract_version, d.status, d.version, d.created_at,
                          a.title AS action_title,
                          o.object_description, o.behavior,
                          c.review_status AS criterion_status,
                          p.title AS criterion_package_title
                   FROM learning_delegation AS d
                   JOIN learning_action AS a
                     ON a.owner_id=d.owner_id AND a.id=d.action_id
                   JOIN learning_outcome AS o
                     ON o.owner_id=d.owner_id AND o.id=d.outcome_id
                   LEFT JOIN learning_criterion_version AS c
                     ON c.owner_id=d.owner_id AND c.id=d.criterion_id
                   LEFT JOIN learning_standard_package AS p
                     ON p.owner_id=d.owner_id AND p.id=c.package_id
                   WHERE d.owner_id=?
                   ORDER BY d.created_at DESC, d.id""",
                (owner,),
            )
        ]
        sessions = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT s.id, s.delegation_id, s.contract_version, s.status,
                          s.started_at, s.ended_at, s.version,
                          d.action_id, a.title AS action_title
                   FROM learning_session AS s
                   JOIN learning_delegation AS d
                     ON d.owner_id=s.owner_id AND d.id=s.delegation_id
                   JOIN learning_action AS a
                     ON a.owner_id=d.owner_id AND a.id=d.action_id
                   WHERE s.owner_id=?
                   ORDER BY s.started_at DESC, s.id""",
                (owner,),
            )
        ]
        artifacts = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT ar.id, ar.content_version, ar.visibility, ar.evidence_status,
                          ar.version, raw.session_id, raw.content, raw.content_hash,
                          raw.privacy, raw.purged_at, raw.created_at,
                          s.delegation_id, a.title AS action_title
                   FROM learning_artifact AS ar
                   JOIN learning_raw_artifact AS raw
                     ON raw.owner_id=ar.owner_id
                    AND raw.artifact_id=ar.id
                    AND raw.content_version=ar.content_version
                   JOIN learning_session AS s
                     ON s.owner_id=raw.owner_id AND s.id=raw.session_id
                   JOIN learning_delegation AS d
                     ON d.owner_id=s.owner_id AND d.id=s.delegation_id
                   JOIN learning_action AS a
                     ON a.owner_id=d.owner_id AND a.id=d.action_id
                   WHERE ar.owner_id=?
                   ORDER BY raw.created_at DESC, ar.id""",
                (owner,),
            )
        ]
        analysis_runs = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT id, artifact_id, content_version, fact_event_id, criterion_id,
                          request_key, attempt, status, reason, created_at, finished_at,
                          provider_selection_source, provider_profile_id, provider_model_id,
                          provider_model, provider_kind, provider_config_version,
                          provider_timeout_seconds, analysis_prompt_schema_version
                   FROM learning_analysis_run
                   WHERE owner_id=?
                   ORDER BY created_at DESC, id""",
                (owner,),
            )
        ]
        evidence_claims = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT id, artifact_id, content_version, fact_event_id, criterion_id,
                          dimension_id, stance, status, source, statement,
                          verification_method, evidence_condition, scope,
                          analysis_run_id, created_at, provenance_json
                   FROM learning_evidence_claim
                   WHERE owner_id=?
                   ORDER BY created_at DESC, id""",
                (owner,),
            )
        ]
        from .learning_domain import trusted_claim_method
        for claim in evidence_claims:
            claim['source_trusted'] = bool(trusted_claim_method(claim))
        evidence_follow_ups = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT id, claim_id, kind, status, request_key, note, due_at,
                          created_at, decided_at
                   FROM learning_evidence_follow_up
                   WHERE owner_id=?
                   ORDER BY created_at DESC, id""",
                (owner,),
            )
        ]
        from .state_derivation import StateDerivationService
        derived_states = StateDerivationService(self).states(identity)
        review_actions = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT id, claim_id, action, from_status, to_status, reason,
                          request_key, replacement_claim_id, created_at
                   FROM learning_review_action
                   WHERE owner_id=?
                   ORDER BY created_at DESC, id""",
                (owner,),
            )
        ]
        evidence_replacements = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT id, superseded_claim_id, replacement_claim_id, reason, created_at
                   FROM learning_claim_replacement
                   WHERE owner_id=?
                   ORDER BY created_at DESC, id""",
                (owner,),
            )
        ]
        revisit_queue = [
            dict(row)
            for row in self.database.fetchall(
                """SELECT id, source_kind, source_id, claim_id, criterion_id, dimension_id,
                          reason, due_at, status, created_at, updated_at
                   FROM learning_revisit_item
                   WHERE owner_id=?
                   ORDER BY due_at, id""",
                (owner,),
            )
        ]

        return {
            "goals": goals,
            "plans": plans,
            "modules": modules,
            "action_links": action_links,
            "setups": setups,
            "actions": actions,
            "outcomes": outcomes,
            "standards": standards,
            "delegations": delegations,
            "sessions": sessions,
            "artifacts": artifacts,
            "analysis_runs": analysis_runs,
            "evidence_claims": evidence_claims,
            "evidence_follow_ups": evidence_follow_ups,
            "derived_states": derived_states,
            "review_actions": review_actions,
            "evidence_replacements": evidence_replacements,
            "revisit_queue": revisit_queue,
        }

    def create_action(self, identity: dict[str, Any], payload: dict[str, Any], key: str) -> dict[str, Any]:
        principal = self.principal(identity)
        return self.core.execute(principal, CreateLearningAction(**payload), key)

    def create_outcome(self, identity: dict[str, Any], payload: dict[str, Any], key: str) -> dict[str, Any]:
        principal = self.principal(identity)
        return self.core.execute(principal, CreateOutcome(**payload), key)

    def create_delegation(self, identity: dict[str, Any], payload: dict[str, Any], key: str) -> dict[str, Any]:
        principal = self.principal(identity)
        return self.core.execute(principal, CreateDelegation(**payload), key)

    def start_session(self, identity: dict[str, Any], payload: dict[str, Any], key: str) -> dict[str, Any]:
        principal = self.principal(identity)
        return self.core.execute(principal, StartSession(**payload), key)

    def complete_action(self, identity: dict[str, Any], payload: dict[str, Any], key: str) -> dict[str, Any]:
        principal = self.principal(identity)
        return self.core.execute(principal, CompleteLearningAction(**payload), key)

    def save_artifact(self, identity: dict[str, Any], payload: dict[str, Any], key: str) -> dict[str, Any]:
        principal = self.principal(identity)
        return self.core.execute(principal, SaveTextArtifact(**payload), key)

    def end_session(self, identity: dict[str, Any], payload: dict[str, Any], key: str) -> dict[str, Any]:
        principal = self.principal(identity)
        return self.core.execute(principal, EndSession(**payload), key)

    def soft_delete_artifact(self, identity: dict[str, Any], payload: dict[str, Any], key: str) -> dict[str, Any]:
        principal = self.principal(identity)
        return self.core.execute(principal, SoftDeleteArtifact(**payload), key)

    def restore_artifact(self, identity: dict[str, Any], payload: dict[str, Any], key: str) -> dict[str, Any]:
        principal = self.principal(identity)
        return self.core.execute(principal, RestoreArtifact(**payload), key)

    def withdraw_artifact(self, identity: dict[str, Any], payload: dict[str, Any], key: str) -> dict[str, Any]:
        principal = self.principal(identity)
        return self.core.execute(principal, WithdrawArtifact(**payload), key)

    def purge_artifact(self, identity: dict[str, Any], payload: dict[str, Any], key: str) -> dict[str, Any]:
        principal = self.principal(identity)
        from .evidence_events import EvidenceEventService
        from .state_derivation import StateDerivationService
        state = StateDerivationService(self, EvidenceEventService(self.database))
        try:
            with self.database.transaction(immediate=True) as connection:
                already_purged = connection.execute("SELECT visibility FROM learning_artifact WHERE owner_id=? AND id=?", (principal.owner_id, payload["artifact_id"])).fetchone()
                result = self.core.execute_in_transaction(connection, principal, PurgeArtifact(**payload), key)
                if already_purged and already_purged[0] == "purged":
                    return result
                for criterion in connection.execute(
                    "SELECT DISTINCT criterion_id FROM learning_evidence_claim WHERE owner_id=? AND artifact_id=?",
                    (principal.owner_id, payload["artifact_id"]),
                ).fetchall():
                    state.derive(identity, criterion[0], connection=connection)
                return result
        except sqlite3.Error as exc:
            raise DomainError("storage_failure", 503) from exc

    def correct_artifact(self, identity: dict[str, Any], payload: dict[str, Any], key: str) -> dict[str, Any]:
        principal = self.principal(identity)
        return self.core.execute(principal, CorrectArtifact(**payload), key)

    def artifact(self, identity: dict[str, Any], artifact_id: str, content_version: int | None = None) -> dict[str, Any]:
        principal = self.principal(identity)
        return self.core.artifact(principal, artifact_id, content_version)

    def events(self, identity: dict[str, Any], action_id: str) -> list[dict[str, Any]]:
        principal = self.principal(identity)
        return self.core.events(principal, action_id)

    def replay(self, identity: dict[str, Any]) -> dict[str, Any]:
        principal = self.principal(identity)
        return self.core.replay(principal)
