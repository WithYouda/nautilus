from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .db import Database
from .learning_domain import DomainError

_ACTION_TO_STATUS = {
    "adopt": "adopted",
    "question": "questioned",
    "withdraw": "withdrawn",
    "defer": "candidate",
}

EVIDENCE_EVENT_SCHEMA_VERSION = 1
SUPPORTED_EVIDENCE_EVENT_SCHEMA_VERSIONS = frozenset({1, 2})
SUPPORTED_EVIDENCE_EVENT_TYPES = frozenset({
    ("claim", "claim.created"),
    ("claim", "claim.replaced"),
    ("review", "review.recorded"),
    ("review", "batch.reviewed"),
    ("state", "state.derived"),
    ("follow_up", "follow_up.created"),
})
_REQUIRED_PAYLOAD_FIELDS = {
    ("claim", "claim.created"): {
        "id", "artifact_id", "content_version", "fact_event_id", "criterion_id",
        "dimension_id", "stance", "status", "source", "statement",
        "verification_method", "evidence_condition", "scope", "analysis_run_id",
        "created_at",
    },
    ("claim", "claim.replaced"): {
        "id", "superseded_claim_id", "replacement_claim_id", "reason", "created_at",
    },
    ("review", "review.recorded"): {
        "id", "claim_id", "action", "from_status", "to_status", "reason",
        "request_key", "created_at",
    },
    ("review", "batch.reviewed"): {
        "id", "action", "reason", "request_key", "claim_ids", "created_at",
    },
    ("state", "state.derived"): {
        "id", "outcome_id", "criterion_id", "dimension_id", "status", "reason_code",
        "standard_version", "calculation_version", "participating_claim_ids",
        "excluded_claim_ids", "excluded_claim_reasons", "calculated_at",
    },
    ("follow_up", "follow_up.created"): {
        "id", "claim_id", "kind", "status", "request_key", "note", "due_at",
        "created_at",
    },
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _event_hash(event: dict[str, Any]) -> str:
    # schema_version is a replay compatibility marker, not part of the 016 hash
    # contract. It is independently validated against the supported-version set.
    material = {
        key: value
        for key, value in event.items()
        if key not in {"event_hash", "schema_version"}
    }
    return hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest()


class EvidenceEventService:
    """Append-only event ledger for evidence projections."""

    def __init__(self, database: Database):
        self.database = database

    def _audit(
        self,
        owner_id: str,
        result: str,
        reason_code: str | None = None,
        *,
        connection=None,
    ) -> None:
        if connection is not None:
            connection.execute(
                "INSERT INTO learning_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    owner_id,
                    owner_id,
                    "EvidenceReplay",
                    result,
                    owner_id,
                    reason_code,
                    utc_timestamp(),
                ),
            )
            return
        with self.database.transaction() as transaction_connection:
            transaction_connection.execute(
                "INSERT INTO learning_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    owner_id,
                    owner_id,
                    "EvidenceReplay",
                    result,
                    owner_id,
                    reason_code,
                    utc_timestamp(),
                ),
            )

    def append(
        self,
        owner_id: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        connection=None,
        private_claim_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if connection is None:
            with self.database.transaction(immediate=True) as transaction:
                return self.append(owner_id, aggregate_type, aggregate_id, event_type, payload,
                                   connection=transaction, private_claim_ids=private_claim_ids)
        if (aggregate_type, event_type) not in SUPPORTED_EVIDENCE_EVENT_TYPES:
            raise DomainError("evidence_event_type_unsupported", 409)
        query_connection = connection or self.database.connection
        previous = query_connection.execute(
            """SELECT event_version, event_hash FROM learning_evidence_event
               WHERE owner_id=? AND aggregate_type=? AND aggregate_id=?
               ORDER BY event_version DESC LIMIT 1""",
            (owner_id, aggregate_type, aggregate_id),
        ).fetchone()
        version = (previous["event_version"] + 1) if previous is not None else 1
        private = None
        claim_ids = set(payload.get("claim_ids", []))
        claim_ids.update(private_claim_ids or [])
        claim_ids.update(value for value in (payload.get("claim_id"), payload.get("superseded_claim_id"), payload.get("replacement_claim_id")) if value)
        if aggregate_type == "claim":
            claim_ids.add(aggregate_id)
        if claim_ids:
            payload = dict(payload)
            private = {key: payload[key] for key in ("statement", "reason", "note", "scope", "verification_method") if key in payload}
            for key in private:
                payload[key] = "内容已彻底删除" if key in {"statement", "reason"} else "artifact" if key == "scope" else "redacted" if key == "verification_method" else None
            payload["private_content_hash"] = hashlib.sha256(_canonical(private).encode()).hexdigest()
        event = {
            "id": str(uuid4()),
            "owner_id": owner_id,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "event_type": event_type,
            "event_version": version,
            "schema_version": 2 if private is not None else EVIDENCE_EVENT_SCHEMA_VERSION,
            "payload_json": _canonical(payload),
            "previous_hash": previous["event_hash"] if previous is not None else None,
            "created_at": utc_timestamp(),
        }
        event["event_hash"] = _event_hash(event)
        connection.execute(
            """INSERT INTO learning_evidence_event
               (id, owner_id, aggregate_type, aggregate_id, event_type, event_version,
                schema_version, payload_json, previous_hash, event_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event["id"],
                event["owner_id"],
                event["aggregate_type"],
                event["aggregate_id"],
                event["event_type"],
                event["event_version"],
                event["schema_version"],
                event["payload_json"],
                event["previous_hash"],
                event["event_hash"],
                event["created_at"],
            ),
        )
        if private is not None:
            connection.execute("INSERT INTO learning_evidence_private_content VALUES (?, ?, ?, ?, NULL)",
                               (event["id"], owner_id, _canonical(sorted(claim_ids)), _canonical(private)))
        return event

    def events(self, owner_id: str) -> list[dict[str, Any]]:
        rows = self.database.fetchall(
            """SELECT * FROM learning_evidence_event
               WHERE owner_id=?
               ORDER BY created_at, id""",
            (owner_id,),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            if item["schema_version"] == 2:
                private = self.database.fetchone("SELECT content_json, purged_at FROM learning_evidence_private_content WHERE owner_id=? AND event_id=?", (owner_id, item["id"]))
                if private is None:
                    raise DomainError("evidence_event_payload_invalid", 409)
                if private["purged_at"] is None:
                    if hashlib.sha256(private["content_json"].encode()).hexdigest() != item["payload"].get("private_content_hash"):
                        raise DomainError("evidence_event_integrity_failed", 409)
                    item["payload"].update(json.loads(private["content_json"]))
            result.append(item)
        return result

    def _validate_chain(self, owner_id: str) -> None:
        rows = self.database.fetchall(
            """SELECT * FROM learning_evidence_event WHERE owner_id=?
               ORDER BY aggregate_type, aggregate_id, event_version""",
            (owner_id,),
        )
        chains: dict[tuple[str, str], tuple[int, str | None]] = {}
        for row in rows:
            if row["schema_version"] not in SUPPORTED_EVIDENCE_EVENT_SCHEMA_VERSIONS:
                raise DomainError("evidence_event_version_unsupported", 409)
            if row["event_hash"] != _event_hash(dict(row)):
                raise DomainError("evidence_event_integrity_failed", 409)
            event_key = (row["aggregate_type"], row["event_type"])
            if event_key not in SUPPORTED_EVIDENCE_EVENT_TYPES:
                raise DomainError("evidence_event_type_unsupported", 409)
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError) as error:
                raise DomainError("evidence_event_payload_invalid", 409) from error
            if not isinstance(payload, dict):
                raise DomainError("evidence_event_payload_invalid", 409)
            missing = _REQUIRED_PAYLOAD_FIELDS[event_key] - payload.keys()
            if missing:
                raise DomainError("evidence_event_payload_invalid", 409)

            key = (row["aggregate_type"], row["aggregate_id"])
            previous = chains.get(key)
            expected_version = 1 if previous is None else previous[0] + 1
            expected_previous = None if previous is None else previous[1]
            if row["event_version"] != expected_version or row["previous_hash"] != expected_previous:
                raise DomainError("evidence_event_chain_invalid", 409)
            chains[key] = (row["event_version"], row["event_hash"])

    def replay(self, owner_id: str) -> dict[str, Any]:
        try:
            from .replay_check import EVIDENCE_TABLES, projection_snapshot, record_comparison
            with self.database.transaction(immediate=True) as connection:
                cutoff = connection.execute("SELECT COALESCE(MAX(rowid),0) FROM learning_evidence_event WHERE owner_id=?", (owner_id,)).fetchone()[0]
                self._validate_chain(owner_id)
                events = self.events(owner_id)
                before = projection_snapshot(connection, owner_id, EVIDENCE_TABLES)
                connection.execute("PRAGMA defer_foreign_keys=ON")
                connection.execute("DELETE FROM learning_derived_state WHERE owner_id=?", (owner_id,))
                connection.execute("DELETE FROM learning_derived_state_history WHERE owner_id=?", (owner_id,))
                connection.execute("DELETE FROM learning_claim_replacement WHERE owner_id=?", (owner_id,))
                connection.execute("DELETE FROM learning_review_action WHERE owner_id=?", (owner_id,))
                connection.execute("DELETE FROM learning_batch_review_action WHERE owner_id=?", (owner_id,))
                connection.execute("DELETE FROM learning_evidence_follow_up WHERE owner_id=?", (owner_id,))
                connection.execute("DELETE FROM learning_evidence_claim WHERE owner_id=?", (owner_id,))

                for event in events:
                    payload = event["payload"]
                    if event["aggregate_type"] == "claim" and event["event_type"] == "claim.created":
                        connection.execute(
                            """INSERT INTO learning_evidence_claim
                               (id, owner_id, artifact_id, content_version, fact_event_id, criterion_id,
                                dimension_id, stance, status, source, statement, verification_method,
                                evidence_condition, scope, analysis_run_id, created_at, provenance_json)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                payload["id"], owner_id, payload["artifact_id"],
                                payload["content_version"], payload["fact_event_id"],
                                payload["criterion_id"], payload["dimension_id"], payload["stance"],
                                payload["status"], payload["source"], payload["statement"],
                                payload["verification_method"], payload["evidence_condition"],
                                payload["scope"], payload["analysis_run_id"], payload["created_at"], payload.get("provenance_json"),
                            ),
                        )
                    elif event["aggregate_type"] == "claim" and event["event_type"] == "claim.replaced":
                        connection.execute(
                            """INSERT INTO learning_claim_replacement
                               (id, owner_id, superseded_claim_id, replacement_claim_id, reason, created_at)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (
                                payload["id"], owner_id, payload["superseded_claim_id"],
                                payload["replacement_claim_id"], payload["reason"],
                                payload["created_at"],
                            ),
                        )
                    elif event["aggregate_type"] == "review" and event["event_type"] == "review.recorded":
                        connection.execute(
                            """INSERT INTO learning_review_action
                               (id, owner_id, claim_id, action, from_status, to_status, reason,
                                request_key, created_at, replacement_claim_id)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                payload["id"], owner_id, payload["claim_id"], payload["action"],
                                payload["from_status"], payload["to_status"], payload["reason"],
                                payload["request_key"], payload["created_at"],
                                payload.get("replacement_claim_id"),
                            ),
                        )
                        connection.execute(
                            "UPDATE learning_evidence_claim SET status=? WHERE owner_id=? AND id=?",
                            (payload["to_status"], owner_id, payload["claim_id"]),
                        )
                        if payload.get("replacement_claim_id"):
                            connection.execute(
                                """INSERT INTO learning_claim_replacement
                                   (id, owner_id, superseded_claim_id, replacement_claim_id, reason, created_at)
                                   VALUES (?, ?, ?, ?, ?, ?)""",
                                (
                                    str(uuid4()), owner_id, payload["claim_id"],
                                    payload["replacement_claim_id"], payload.get("reason") or "user replacement",
                                    payload["created_at"],
                                ),
                            )
                    elif event["aggregate_type"] == "review" and event["event_type"] == "batch.reviewed":
                        connection.execute(
                            """INSERT INTO learning_batch_review_action
                               (id, owner_id, action, reason, request_key, claim_ids_json, created_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (
                                payload["id"], owner_id, payload["action"], payload["reason"],
                                payload["request_key"], _canonical(payload["claim_ids"]),
                                payload["created_at"],
                            ),
                        )
                        for claim_id in payload["claim_ids"]:
                            connection.execute(
                                "UPDATE learning_evidence_claim SET status=? WHERE owner_id=? AND id=?",
                                (_ACTION_TO_STATUS[payload["action"]], owner_id, claim_id),
                            )
                    elif event["aggregate_type"] == "state" and event["event_type"] == "state.derived":
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
                                payload["id"], owner_id, payload["outcome_id"], payload["criterion_id"],
                                payload["dimension_id"], payload["status"], payload["reason_code"],
                                payload["standard_version"], payload["calculation_version"],
                                _canonical(payload["participating_claim_ids"]),
                                _canonical(payload["excluded_claim_ids"]),
                                _canonical(payload["excluded_claim_reasons"]),
                                payload["calculated_at"],
                            ),
                        )
                        connection.execute(
                            """INSERT INTO learning_derived_state_history
                               (id, owner_id, outcome_id, criterion_id, dimension_id, status, reason_code,
                                standard_version, calculation_version, participating_claim_ids_json,
                                excluded_claim_ids_json, excluded_claim_reasons_json, calculated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                str(uuid4()), owner_id, payload["outcome_id"], payload["criterion_id"],
                                payload["dimension_id"], payload["status"], payload["reason_code"],
                                payload["standard_version"], payload["calculation_version"],
                                _canonical(payload["participating_claim_ids"]),
                                _canonical(payload["excluded_claim_ids"]),
                                _canonical(payload["excluded_claim_reasons"]),
                                payload["calculated_at"],
                            ),
                        )
                    elif event["aggregate_type"] == "follow_up" and event["event_type"] == "follow_up.created":
                        connection.execute(
                            """INSERT INTO learning_evidence_follow_up
                               (id, owner_id, claim_id, kind, status, request_key, note, due_at,
                                created_at, decided_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                payload["id"], owner_id, payload["claim_id"], payload["kind"],
                                payload["status"], payload["request_key"], payload["note"],
                                payload["due_at"], payload["created_at"], payload.get("decided_at"),
                            ),
                        )

                connection.execute(
                    """UPDATE learning_evidence_claim
                       SET status='invalidated'
                       WHERE owner_id=?
                         AND artifact_id IN (
                             SELECT id FROM learning_artifact
                             WHERE owner_id=? AND visibility='purged'
                         )""",
                    (owner_id, owner_id),
                )
                self._audit(owner_id, "succeeded", connection=connection)

                from .verification_content import purge_artifact_copies
                for artifact in connection.execute(
                    "SELECT DISTINCT artifact_id, purged_at FROM learning_raw_artifact WHERE owner_id=? AND purged_at IS NOT NULL",
                    (owner_id,),
                ).fetchall():
                    purge_artifact_copies(connection, owner_id, artifact["artifact_id"], artifact["purged_at"])
                from .state_derivation import StateDerivationService
                from .learning_service import LearningService
                from .learning_domain import Principal
                state = StateDerivationService(LearningService(self.database))
                for guarded in state.states({'id': owner_id}, connection=connection):
                    if guarded['reason_code'] == 'execution_provenance_unverified':
                        connection.execute("UPDATE learning_derived_state SET status=?, reason_code=? WHERE owner_id=? AND id=?",
                            (guarded['status'], guarded['reason_code'], owner_id, guarded['id']))
                for criterion in connection.execute("SELECT DISTINCT criterion_id FROM learning_derived_state WHERE owner_id=?", (owner_id,)).fetchall():
                    state._refresh_revisit_queue(Principal.user(owner_id), state._criterion(Principal.user(owner_id), criterion[0])[0], [dict(row) for row in connection.execute("SELECT * FROM learning_derived_state WHERE owner_id=? AND criterion_id=?", (owner_id, criterion[0]))], connection=connection)
                after = projection_snapshot(connection, owner_id, EVIDENCE_TABLES)
                comparison = record_comparison(connection, owner_id, "evidence", cutoff, before, after)

            return {
                "status": "succeeded",
                "comparison": comparison,
                "event_count": len(events),
                "aggregate_count": len({
                    (event["aggregate_type"], event["aggregate_id"]) for event in events
                }),
            }
        except DomainError as error:
            self._audit(owner_id, "rejected", error.code)
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, sqlite3.Error) as error:
            self._audit(owner_id, "rejected", "evidence_event_payload_invalid")
            raise DomainError("evidence_event_payload_invalid", 409) from error
