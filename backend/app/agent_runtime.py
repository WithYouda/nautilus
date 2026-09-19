from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from .learning_domain import DomainError
from .learning_service import LearningService

GLOBAL_AGENT_ID = "global-agent"


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class AgentRuntime:
    """Minimal unified runtime boundary for global Agent permission requests."""

    def __init__(self, learning: LearningService) -> None:
        self.learning = learning
        self.database = learning.database

    def _audit(
        self,
        connection,
        owner_id: str,
        operation: str,
        result: str,
        reference_id: str | None = None,
        reason_code: str | None = None,
        actor_id: str | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO learning_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                owner_id,
                actor_id or GLOBAL_AGENT_ID,
                operation,
                result,
                reference_id,
                reason_code,
                utc_timestamp(),
            ),
        )

    def create_permission_request(
        self,
        identity: dict[str, Any],
        payload: dict[str, Any],
        request_key: str,
    ) -> dict[str, Any]:
        principal = self.learning.principal(identity)
        owner_id = principal.owner_id

        action = self.database.fetchone(
            "SELECT id FROM learning_action WHERE owner_id=? AND id=?",
            (owner_id, payload["target_id"]),
        )
        if action is None:
            raise DomainError("not_found", 404)

        existing = self.database.fetchone(
            """SELECT * FROM learning_agent_permission_request
               WHERE owner_id=? AND request_key=?""",
            (owner_id, request_key),
        )
        if existing is not None:
            return dict(existing)

        now = datetime.now(timezone.utc)
        request_id = str(uuid4())
        expires_at = now + timedelta(seconds=int(payload["ttl_seconds"]))
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO learning_agent_permission_request
                   (id, owner_id, agent_id, request_key, purpose, scope, target_id,
                    content_granularity, ttl_seconds, expires_at, status, created_at,
                    decided_at, decision_reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL, NULL)""",
                (
                    request_id,
                    owner_id,
                    GLOBAL_AGENT_ID,
                    request_key,
                    payload["purpose"],
                    payload["scope"],
                    payload["target_id"],
                    payload["content_granularity"],
                    payload["ttl_seconds"],
                    expires_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                    utc_timestamp(),
                ),
            )
            self._audit(
                connection,
                owner_id,
                "AgentPermissionRequest",
                "succeeded",
                request_id,
            )

        row = self.database.fetchone(
            "SELECT * FROM learning_agent_permission_request WHERE owner_id=? AND id=?",
            (owner_id, request_id),
        )
        return dict(row)

    def list_permission_requests(self, identity: dict[str, Any]) -> list[dict[str, Any]]:
        principal = self.learning.principal(identity)
        owner_id = principal.owner_id
        self._expire_requests(owner_id)
        self._expire_grants(owner_id)
        return [
            dict(row)
            for row in self.database.fetchall(
                """SELECT r.*,
                          g.status AS grant_status,
                          g.granted_at,
                          g.revoked_at,
                          g.revoke_reason
                   FROM learning_agent_permission_request AS r
                   LEFT JOIN learning_agent_permission_grant AS g
                     ON g.owner_id=r.owner_id AND g.request_id=r.id
                   WHERE r.owner_id=?
                   ORDER BY r.created_at DESC, r.id""",
                (owner_id,),
            )
        ]

    def approve_permission_request(
        self,
        identity: dict[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        principal = self.learning.principal(identity)
        owner_id = principal.owner_id
        self._expire_requests(owner_id)
        self._expire_grants(owner_id)

        row = self.database.fetchone(
            """SELECT r.*, g.id AS grant_id
               FROM learning_agent_permission_request AS r
               LEFT JOIN learning_agent_permission_grant AS g
                 ON g.owner_id=r.owner_id AND g.request_id=r.id
               WHERE r.owner_id=? AND r.id=?""",
            (owner_id, request_id),
        )
        if row is None:
            raise DomainError("not_found", 404)
        if row["grant_id"] is not None:
            grant = self.database.fetchone(
                """SELECT * FROM learning_agent_permission_grant
                   WHERE owner_id=? AND request_id=?""",
                (owner_id, request_id),
            )
            if grant is not None and grant["status"] == "active":
                return self._request_with_grant(row, grant)
            raise DomainError("permission_request_not_pending", 409)
        if row["status"] != "pending":
            raise DomainError("permission_request_not_pending", 409)

        active = self.database.fetchone(
            """SELECT id FROM learning_agent_permission_grant
               WHERE owner_id=? AND agent_id=? AND target_id=? AND status='active'""",
            (owner_id, row["agent_id"], row["target_id"]),
        )
        if active is not None:
            raise DomainError("permission_request_not_pending", 409)

        grant_id = str(uuid4())
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO learning_agent_permission_grant
                   (id, owner_id, request_id, agent_id, scope, target_id,
                    content_granularity, status, granted_at, expires_at,
                    revoked_at, revoke_reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, NULL, NULL)""",
                (
                    grant_id,
                    owner_id,
                    request_id,
                    row["agent_id"],
                    row["scope"],
                    row["target_id"],
                    row["content_granularity"],
                    utc_timestamp(),
                    row["expires_at"],
                ),
            )
            self._audit(
                connection,
                owner_id,
                "AgentPermissionDecision",
                "approved",
                request_id,
                "permission_approved",
                principal.actor_id,
            )

        request = self.database.fetchone(
            """SELECT r.*, g.id AS grant_id
               FROM learning_agent_permission_request AS r
               LEFT JOIN learning_agent_permission_grant AS g
                 ON g.owner_id=r.owner_id AND g.request_id=r.id
               WHERE r.owner_id=? AND r.id=?""",
            (owner_id, request_id),
        )
        grant = self.database.fetchone(
            """SELECT * FROM learning_agent_permission_grant
               WHERE owner_id=? AND request_id=?""",
            (owner_id, request_id),
        )
        return self._request_with_grant(request, grant)

    def revoke_permission_grant(
        self,
        identity: dict[str, Any],
        request_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        principal = self.learning.principal(identity)
        owner_id = principal.owner_id
        self._expire_requests(owner_id)
        self._expire_grants(owner_id)

        row = self.database.fetchone(
            """SELECT r.*, g.id AS grant_id
               FROM learning_agent_permission_request AS r
               LEFT JOIN learning_agent_permission_grant AS g
                 ON g.owner_id=r.owner_id AND g.request_id=r.id
               WHERE r.owner_id=? AND r.id=?""",
            (owner_id, request_id),
        )
        if row is None or row["grant_id"] is None:
            raise DomainError("not_found", 404)

        grant = self.database.fetchone(
            """SELECT * FROM learning_agent_permission_grant
               WHERE owner_id=? AND request_id=?""",
            (owner_id, request_id),
        )
        if grant["status"] == "revoked":
            return self._request_with_grant(row, grant)
        if grant["status"] != "active":
            raise DomainError("permission_request_not_pending", 409)

        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute(
                """UPDATE learning_agent_permission_grant
                   SET status='revoked', revoked_at=?, revoke_reason=?
                   WHERE owner_id=? AND request_id=? AND status='active'""",
                (utc_timestamp(), reason, owner_id, request_id),
            ).rowcount
            if changed != 1:
                raise DomainError("permission_request_not_pending", 409)
            self._audit(
                connection,
                owner_id,
                "AgentPermissionDecision",
                "revoked",
                request_id,
                "permission_revoked",
                principal.actor_id,
            )

        request = self.database.fetchone(
            """SELECT r.*, g.id AS grant_id
               FROM learning_agent_permission_request AS r
               LEFT JOIN learning_agent_permission_grant AS g
                 ON g.owner_id=r.owner_id AND g.request_id=r.id
               WHERE r.owner_id=? AND r.id=?""",
            (owner_id, request_id),
        )
        grant = self.database.fetchone(
            """SELECT * FROM learning_agent_permission_grant
               WHERE owner_id=? AND request_id=?""",
            (owner_id, request_id),
        )
        return self._request_with_grant(request, grant)

    def agent_context(
        self,
        identity: dict[str, Any],
        target_id: str | None = None,
    ) -> dict[str, Any]:
        principal = self.learning.principal(identity)
        owner_id = principal.owner_id
        self._expire_requests(owner_id)
        self._expire_grants(owner_id)

        if target_id is None:
            evidence_references = self._global_evidence_references(owner_id)
            reference_counts = {
                action_id: sum(1 for item in evidence_references if item["action_id"] == action_id)
                for action_id in {item["action_id"] for item in evidence_references}
            }
            actions = [
                self._action_summary(row)
                for row in self.database.fetchall(
                    """SELECT a.id, a.title, a.status, a.created_at,
                              (SELECT COUNT(*) FROM learning_delegation AS d
                                WHERE d.owner_id=a.owner_id AND d.action_id=a.id) AS delegation_count
                       FROM learning_action AS a
                       WHERE a.owner_id=?
                       ORDER BY a.created_at DESC, a.id""",
                    (owner_id,),
                )
            ]
            for action in actions:
                action["evidence_reference_count"] = reference_counts.get(action["id"], 0)
            return {
                "agent_id": GLOBAL_AGENT_ID,
                "scope": "global",
                "authorization": {
                    "status": "default",
                    "content_granularity": "metadata",
                    "request_id": None,
                },
                "analysis": self._analysis_status("default", "metadata"),
                "context": {
                    "actions": actions,
                    "evidence_references": evidence_references,
                },
            }

        action = self.database.fetchone(
            """SELECT id, title, status, created_at
               FROM learning_action WHERE owner_id=? AND id=?""",
            (owner_id, target_id),
        )
        if action is None:
            raise DomainError("not_found", 404)

        grant = self._grant_for_target(owner_id, target_id)
        request = self._latest_request_for_target(owner_id, target_id)
        if grant is not None and grant["status"] == "active":
            authorization = {
                "status": "approved",
                "content_granularity": grant["content_granularity"],
                "request_id": grant["request_id"],
            }
        elif grant is not None:
            authorization = {
                "status": grant["status"],
                "content_granularity": grant["content_granularity"],
                "request_id": grant["request_id"],
            }
        elif request is not None:
            authorization = {
                "status": request["status"],
                "content_granularity": request["content_granularity"],
                "request_id": request["id"],
            }
        else:
            authorization = {
                "status": "default",
                "content_granularity": "metadata",
                "request_id": None,
            }

        evidence_references = self._evidence_references(owner_id, target_id)
        action_summary = self._action_summary(action)
        action_summary["evidence_reference_count"] = len(evidence_references)
        context: dict[str, Any] = {
            "action": action_summary,
            "delegations": [
                dict(row)
                for row in self.database.fetchall(
                    """SELECT id, outcome_id, criterion_id, status,
                              contract_version, created_at
                       FROM learning_delegation
                       WHERE owner_id=? AND action_id=?
                       ORDER BY created_at, id""",
                    (owner_id, target_id),
                )
            ],
            "sessions": [
                dict(row)
                for row in self.database.fetchall(
                    """SELECT s.id, s.delegation_id, s.status,
                              s.started_at, s.ended_at
                       FROM learning_session AS s
                       JOIN learning_delegation AS d
                         ON d.owner_id=s.owner_id AND d.id=s.delegation_id
                       WHERE s.owner_id=? AND d.action_id=?
                       ORDER BY s.started_at, s.id""",
                    (owner_id, target_id),
                )
            ],
            "evidence_references": evidence_references,
            "artifacts": [],
        }

        if grant is not None and grant["status"] == "active":
            if grant["content_granularity"] == "metadata":
                context["artifacts"] = [
                    dict(row)
                    for row in self.database.fetchall(
                        """SELECT ar.id, ar.content_version, ar.visibility,
                                  ar.evidence_status, raw.session_id,
                                  raw.created_at, raw.purged_at
                           FROM learning_artifact AS ar
                           JOIN learning_raw_artifact AS raw
                             ON raw.owner_id=ar.owner_id
                            AND raw.artifact_id=ar.id
                            AND raw.content_version=ar.content_version
                           JOIN learning_session AS s
                             ON s.owner_id=raw.owner_id AND s.id=raw.session_id
                           JOIN learning_delegation AS d
                             ON d.owner_id=s.owner_id AND d.id=s.delegation_id
                           WHERE ar.owner_id=? AND d.action_id=?
                           ORDER BY raw.created_at, ar.id""",
                        (owner_id, target_id),
                    )
                ]
            else:
                context["artifacts"] = [
                    dict(row)
                    for row in self.database.fetchall(
                        """SELECT ar.id, ar.content_version, ar.visibility,
                                  ar.evidence_status, raw.session_id,
                                  raw.content, raw.created_at, raw.purged_at
                           FROM learning_artifact AS ar
                           JOIN learning_raw_artifact AS raw
                             ON raw.owner_id=ar.owner_id
                            AND raw.artifact_id=ar.id
                            AND raw.content_version=ar.content_version
                           JOIN learning_session AS s
                             ON s.owner_id=raw.owner_id AND s.id=raw.session_id
                           JOIN learning_delegation AS d
                             ON d.owner_id=s.owner_id AND d.id=s.delegation_id
                           WHERE ar.owner_id=? AND d.action_id=?
                           ORDER BY raw.created_at, ar.id""",
                        (owner_id, target_id),
                    )
                ]

        return {
            "agent_id": GLOBAL_AGENT_ID,
            "scope": "learning_action",
            "authorization": authorization,
            "analysis": self._analysis_status(
                authorization["status"],
                authorization["content_granularity"],
            ),
            "context": context,
        }

    @staticmethod
    def _analysis_status(authorization_status: str, granularity: str) -> dict[str, Any]:
        available = ["action_summary", "status", "evidence_references"]
        if authorization_status == "approved" and granularity == "full_text":
            unavailable: list[str] = []
        elif authorization_status == "approved":
            unavailable = ["raw_text"]
        else:
            unavailable = ["raw_text", "authorized_artifact_metadata"]
        return {
            "status": "available" if authorization_status == "approved" else "incomplete",
            "reason": (
                "minimum_context_only" if authorization_status == "default"
                else f"permission_{authorization_status}"
            ),
            "available": available,
            "unavailable": unavailable,
        }

    def _global_evidence_references(self, owner_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.database.fetchall(
                """SELECT c.id, c.artifact_id, c.content_version,
                          c.fact_event_id, c.criterion_id, c.dimension_id,
                          c.stance, c.status, c.source, c.created_at, d.action_id
                   FROM learning_evidence_claim AS c
                   JOIN learning_raw_artifact AS raw
                     ON raw.owner_id=c.owner_id
                    AND raw.artifact_id=c.artifact_id
                    AND raw.content_version=c.content_version
                    AND raw.fact_event_id=c.fact_event_id
                   JOIN learning_session AS s
                     ON s.owner_id=raw.owner_id AND s.id=raw.session_id
                   JOIN learning_delegation AS d
                     ON d.owner_id=s.owner_id AND d.id=s.delegation_id
                   WHERE c.owner_id=?
                   ORDER BY c.created_at, c.id""",
                (owner_id,),
            )
        ]

    @staticmethod
    def _request_with_grant(request, grant) -> dict[str, Any]:
        result = dict(request)
        result.pop("grant_id", None)
        if grant is not None:
            result["status"] = "approved" if grant["status"] == "active" else grant["status"]
            result["grant_status"] = grant["status"]
            result["granted_at"] = grant["granted_at"]
            result["revoked_at"] = grant["revoked_at"]
            result["revoke_reason"] = grant["revoke_reason"]
        return result

    @staticmethod
    def _action_summary(row) -> dict[str, Any]:
        result = dict(row)
        result["evidence_reference_count"] = result.pop("artifact_count", 0)
        return result

    def _evidence_references(self, owner_id: str, action_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.database.fetchall(
                """SELECT c.id, c.artifact_id, c.content_version,
                          c.fact_event_id, c.criterion_id, c.dimension_id,
                          c.stance, c.status, c.source, c.created_at
                   FROM learning_evidence_claim AS c
                   JOIN learning_raw_artifact AS raw
                     ON raw.owner_id=c.owner_id
                    AND raw.artifact_id=c.artifact_id
                    AND raw.content_version=c.content_version
                    AND raw.fact_event_id=c.fact_event_id
                   JOIN learning_session AS s
                     ON s.owner_id=raw.owner_id AND s.id=raw.session_id
                   JOIN learning_delegation AS d
                     ON d.owner_id=s.owner_id AND d.id=s.delegation_id
                   WHERE c.owner_id=? AND d.action_id=?
                   ORDER BY c.created_at, c.id""",
                (owner_id, action_id),
            )
        ]

    def _grant_for_target(self, owner_id: str, target_id: str):
        rows = self.database.fetchall(
            """SELECT * FROM learning_agent_permission_grant
               WHERE owner_id=? AND agent_id=? AND target_id=?
               ORDER BY granted_at DESC, id""",
            (owner_id, GLOBAL_AGENT_ID, target_id),
        )
        for row in rows:
            if row["status"] == "active":
                return row
        return rows[0] if rows else None

    def _latest_request_for_target(self, owner_id: str, target_id: str):
        return self.database.fetchone(
            """SELECT * FROM learning_agent_permission_request
               WHERE owner_id=? AND agent_id=? AND target_id=?
               ORDER BY created_at DESC, id LIMIT 1""",
            (owner_id, GLOBAL_AGENT_ID, target_id),
        )

    def deny_permission_request(
        self,
        identity: dict[str, Any],
        request_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        principal = self.learning.principal(identity)
        owner_id = principal.owner_id
        row = self.database.fetchone(
            "SELECT * FROM learning_agent_permission_request WHERE owner_id=? AND id=?",
            (owner_id, request_id),
        )
        if row is None:
            raise DomainError("not_found", 404)
        if row["status"] == "denied":
            return dict(row)
        if row["status"] != "pending":
            raise DomainError("permission_request_not_pending", 409)

        now = utc_timestamp()
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute(
                """UPDATE learning_agent_permission_request
                   SET status='denied', decided_at=?, decision_reason=?
                   WHERE owner_id=? AND id=? AND status='pending'""",
                (now, reason, owner_id, request_id),
            ).rowcount
            if changed != 1:
                raise DomainError("permission_request_not_pending", 409)
            self._audit(
                connection,
                owner_id,
                "AgentPermissionDecision",
                "rejected",
                request_id,
                "permission_denied",
                principal.actor_id,
            )

        updated = self.database.fetchone(
            "SELECT * FROM learning_agent_permission_request WHERE owner_id=? AND id=?",
            (owner_id, request_id),
        )
        return dict(updated)

    def _expire_grants(self, owner_id: str) -> None:
        now = datetime.now(timezone.utc)
        rows = self.database.fetchall(
            """SELECT id, request_id, expires_at FROM learning_agent_permission_grant
               WHERE owner_id=? AND status='active'""",
            (owner_id,),
        )
        expired_grants: list[dict[str, str]] = []
        for row in rows:
            try:
                expires_at = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
            except ValueError:
                continue
            if expires_at <= now:
                expired_grants.append(dict(row))
        if not expired_grants:
            return
        with self.database.transaction(immediate=True) as connection:
            for grant in expired_grants:
                changed = connection.execute(
                    """UPDATE learning_agent_permission_grant
                       SET status='expired'
                       WHERE owner_id=? AND id=? AND status='active'""",
                    (owner_id, grant["id"]),
                ).rowcount
                if changed == 1:
                    self._audit(
                        connection,
                        owner_id,
                        "AgentPermissionDecision",
                        "rejected",
                        grant["request_id"],
                        "permission_expired",
                    )

    def _expire_requests(self, owner_id: str) -> None:
        now = datetime.now(timezone.utc)
        rows = self.database.fetchall(
            """SELECT r.id, r.expires_at, g.id AS grant_id
               FROM learning_agent_permission_request AS r
               LEFT JOIN learning_agent_permission_grant AS g
                 ON g.owner_id=r.owner_id AND g.request_id=r.id
               WHERE r.owner_id=? AND r.status='pending'""",
            (owner_id,),
        )
        expired_requests: list[dict[str, str | None]] = []
        for row in rows:
            try:
                expires_at = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
            except ValueError:
                continue
            if expires_at <= now:
                expired_requests.append(dict(row))
        if not expired_requests:
            return

        timestamp = utc_timestamp()
        with self.database.transaction(immediate=True) as connection:
            for request in expired_requests:
                changed = connection.execute(
                    """UPDATE learning_agent_permission_request
                       SET status='expired', decided_at=?, decision_reason='request expired'
                       WHERE owner_id=? AND id=? AND status='pending'""",
                    (timestamp, owner_id, request["id"]),
                ).rowcount
                if changed == 1 and request["grant_id"] is None:
                    self._audit(
                        connection,
                        owner_id,
                        "AgentPermissionDecision",
                        "rejected",
                        request["id"],
                        "permission_expired",
                    )
