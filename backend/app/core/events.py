from __future__ import annotations

import hashlib
import json
import sqlite3
from uuid import NAMESPACE_URL, uuid4, uuid5

from ..learning_domain import DomainError, Principal

PROJECTION_VERSION = 1
SUPPORTED_EVENT_VERSIONS = frozenset({1})
SUPPORTED_EVENT_TYPES = frozenset({
    "setup.confirmed",
    "action.created",
    "outcome.created",
    "delegation.created",
    "session.started",
    "session.ended",
    "action.completed",
    "delegation.completed",
    "artifact.created",
    "verification.artifact_recorded",
    "artifact.corrected",
    "artifact.soft_deleted",
    "artifact.restored",
    "artifact.withdrawn",
    "artifact.purged",
})


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def event_digest(event: dict) -> str:
    return digest({
        key: value
        for key, value in event.items()
        if key != "event_hash" and key != "position" and not key.startswith("_")
    })


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _load_payload(event: dict) -> dict:
    try:
        payload = json.loads(event["payload_json"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise DomainError("event_integrity_failed") from exc
    if not isinstance(payload, dict):
        raise DomainError("event_integrity_failed")
    return payload


def _store_or_validate_raw_artifact(connection, event: dict, payload: dict, *, artifact_id: str, content_version: int) -> sqlite3.Row:
    owner = event["owner_id"]
    expected_hash = payload.get("content_hash")
    row = connection.execute(
        """SELECT * FROM learning_raw_artifact
           WHERE owner_id=? AND artifact_id=? AND content_version=? AND fact_event_id=?""",
        (owner, artifact_id, content_version, event["event_id"]),
    ).fetchone()
    session_id = payload.get("session_id")
    if session_id is None:
        session_id = connection.execute(
            """SELECT session_id FROM learning_raw_artifact
               WHERE owner_id=? AND artifact_id=?
               ORDER BY content_version DESC LIMIT 1""",
            (owner, artifact_id),
        ).fetchone()
        session_id = session_id["session_id"] if session_id is not None else None
    if session_id is None:
        raise DomainError("event_scope_invalid")
    if row is not None:
        if row["session_id"] != session_id:
            raise DomainError("event_scope_invalid")
        if row["purged_at"] is None:
            content = row["content"]
            if (
                content is None
                or not expected_hash
                or row["content_hash"] != expected_hash
                or _content_hash(content) != expected_hash
            ):
                raise DomainError("event_integrity_failed")
        return row

    content = event.get("_private_content")
    if not content:
        raise DomainError("artifact_source_missing")
    if expected_hash != _content_hash(content):
        raise DomainError("event_integrity_failed")
    connection.execute(
        "INSERT INTO learning_raw_artifact VALUES (?, ?, ?, ?, ?, ?, ?, 'private', ?, NULL)",
        (
            artifact_id,
            content_version,
            owner,
            session_id,
            event["event_id"],
            content,
            expected_hash,
            event["occurred_at"],
        ),
    )
    return connection.execute(
        "SELECT * FROM learning_raw_artifact WHERE owner_id=? AND artifact_id=? AND content_version=?",
        (owner, artifact_id, content_version),
    ).fetchone()


def apply_event(connection: sqlite3.Connection, event: dict) -> None:
    if event["event_version"] not in SUPPORTED_EVENT_VERSIONS:
        raise DomainError("event_version_unsupported")
    if event["projection_version"] != PROJECTION_VERSION:
        raise DomainError("projection_version_unsupported")
    if event["event_type"] not in SUPPORTED_EVENT_TYPES:
        raise DomainError("event_type_unsupported")

    owner = event["owner_id"]
    aggregate = (owner, event["aggregate_type"], event["aggregate_id"])
    position = connection.execute(
        """SELECT aggregate_version, projection_version FROM learning_projection_position
           WHERE owner_id=? AND aggregate_type=? AND aggregate_id=?""",
        aggregate,
    ).fetchone()
    version = event["aggregate_version"]
    if (position["aggregate_version"] if position else 0) != version - 1:
        raise DomainError("projection_gap")
    if position is not None and position["projection_version"] != PROJECTION_VERSION:
        raise DomainError("projection_version_unsupported")

    payload = _load_payload(event)
    occurred_at = event["occurred_at"]
    event_type = event["event_type"]

    if event_type == "setup.confirmed":
        if event["aggregate_type"] != "setup" or payload.get("id") != event["aggregate_id"]:
            raise DomainError("event_scope_invalid")
        goal = payload.get("goal")
        plan = payload.get("plan")
        setup = payload.get("setup")
        link = payload.get("action_link")
        if not all(isinstance(item, dict) for item in (goal, plan, setup, link)):
            raise DomainError("event_scope_invalid")
        if (
            not isinstance(goal.get("id"), str)
            or not isinstance(plan.get("id"), str)
            or not isinstance(goal.get("original_intent"), str)
            or not goal["original_intent"].strip()
            or not isinstance(goal.get("title"), str)
            or not goal["title"].strip()
            or not isinstance(plan.get("title"), str)
            or not plan["title"].strip()
            or not isinstance(link.get("action_id"), str)
            or not isinstance(link.get("plan_id"), str)
            or link.get("module_id") is not None
            or not isinstance(setup.get("id"), str)
            or not isinstance(setup.get("action_id"), str)
            or not isinstance(setup.get("outcome_id"), str)
            or not isinstance(setup.get("delegation_id"), str)
            or setup["id"] != event["aggregate_id"]
            or link["action_id"] != setup["action_id"]
            or link["plan_id"] != plan["id"]
        ):
            raise DomainError("event_scope_invalid")
        action = connection.execute(
            "SELECT id FROM learning_action WHERE owner_id=? AND id=?",
            (owner, setup["action_id"]),
        ).fetchone()
        delegation = connection.execute(
            "SELECT action_id, outcome_id FROM learning_delegation WHERE owner_id=? AND id=?",
            (owner, setup["delegation_id"]),
        ).fetchone()
        if action is None or delegation is None or (
            delegation["action_id"] != setup["action_id"]
            or delegation["outcome_id"] != setup["outcome_id"]
        ):
            raise DomainError("event_scope_invalid")
        connection.execute(
            """INSERT INTO learning_goal
               (id, owner_id, original_intent, title, description, status, version, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'hypothesis', 1, ?, ?)""",
            (goal["id"], owner, goal["original_intent"], goal["title"], goal["description"], occurred_at, occurred_at),
        )
        connection.execute(
            """INSERT INTO learning_plan
               (id, owner_id, goal_id, title, description, status, version, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'active', 1, ?, ?)""",
            (plan["id"], owner, goal["id"], plan["title"], plan["description"], occurred_at, occurred_at),
        )
        connection.execute(
            """INSERT INTO learning_action_link
               (owner_id, action_id, plan_id, module_id, created_at)
               VALUES (?, ?, ?, NULL, ?)""",
            (owner, link["action_id"], plan["id"], occurred_at),
        )
        connection.execute(
            """INSERT INTO learning_setup
               (id, owner_id, goal_id, plan_id, action_id, outcome_id, delegation_id,
                original_intent, status, version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', 1, ?)""",
            (
                setup["id"], owner, goal["id"], plan["id"], link["action_id"],
                setup["outcome_id"], setup["delegation_id"], goal["original_intent"], occurred_at,
            ),
        )
    elif event_type == "action.created":
        if event["aggregate_type"] != "action" or payload.get("id") != event["aggregate_id"]:
            raise DomainError("event_scope_invalid")
        connection.execute(
            "INSERT INTO learning_action VALUES (?, ?, ?, ?, 'open', ?, ?)",
            (payload["id"], owner, payload["title"], payload["context_key"], version, occurred_at),
        )
    elif event_type == "outcome.created":
        if event["aggregate_type"] != "outcome" or payload.get("id") != event["aggregate_id"]:
            raise DomainError("event_scope_invalid")
        existing = connection.execute(
            "SELECT object_description, behavior, context_key, source FROM learning_outcome WHERE owner_id=? AND id=?",
            (owner, payload["id"]),
        ).fetchone()
        expected = (payload["object_description"], payload["behavior"], payload["context_key"], "user")
        if existing is None:
            connection.execute(
                "INSERT INTO learning_outcome VALUES (?, ?, ?, ?, ?, 'user', ?)",
                (payload["id"], owner, *expected[:3], occurred_at),
            )
        elif tuple(existing) != expected:
            raise DomainError("event_scope_invalid")
    elif event_type == "delegation.created":
        if event["aggregate_type"] != "action" or payload.get("action_id") != event["aggregate_id"]:
            raise DomainError("event_scope_invalid")
        connection.execute(
            "INSERT INTO learning_delegation VALUES (?, ?, ?, ?, ?, 1, 'ready', 1, ?)",
            (
                payload["id"], owner, payload["action_id"], payload["outcome_id"],
                payload["criterion_id"], occurred_at,
            ),
        )
        connection.execute(
            "INSERT INTO learning_contract_version VALUES (?, ?, 1, ?, ?, ?, ?, ?)",
            (
                payload["id"], owner, payload["boundaries"], payload["stop_conditions"],
                payload["time_budget_minutes"], payload["criterion_id"], occurred_at,
            ),
        )
    elif event_type == "session.started":
        if event["aggregate_type"] != "action":
            raise DomainError("event_scope_invalid")
        connection.execute(
            "INSERT INTO learning_session VALUES (?, ?, ?, ?, 'running', ?, NULL, ?)",
            (payload["id"], owner, payload["delegation_id"], payload["contract_version"], occurred_at, version),
        )
        changed = connection.execute(
            "UPDATE learning_delegation SET status='active' WHERE owner_id=? AND id=?",
            (owner, payload["delegation_id"]),
        ).rowcount
        if changed != 1:
            raise DomainError("event_scope_invalid")
    elif event_type in {"artifact.created", "verification.artifact_recorded"}:
        if event["aggregate_type"] != "action":
            raise DomainError("event_scope_invalid")
        content_version = payload.get("content_version", 1)
        if not isinstance(content_version, int) or content_version != 1:
            raise DomainError("event_scope_invalid")
        raw = _store_or_validate_raw_artifact(
            connection, event, payload, artifact_id=payload["id"], content_version=content_version
        )
        if event_type == "verification.artifact_recorded":
            changed = connection.execute(
                """UPDATE learning_verification_submission SET artifact_id=?, content_json='{}'
                   WHERE owner_id=? AND id=? AND (artifact_id IS NULL OR artifact_id=?)""",
                (payload["id"], owner, payload["submission_id"], payload["id"]),
            ).rowcount
            if changed != 1:
                raise DomainError("event_scope_invalid")
            connection.execute(
                """UPDATE learning_verification SET submission_json=NULL WHERE owner_id=?
                   AND latest_submission_id=?""", (owner, payload["submission_id"]),
            )
        purged = raw["purged_at"] is not None
        connection.execute(
            "INSERT INTO learning_artifact VALUES (?, ?, ?, ?, ?, ?)",
            (
                payload["id"], owner, content_version,
                "purged" if purged else "visible",
                "invalidated" if purged else "eligible",
                content_version,
            ),
        )
        delegation = connection.execute(
            """SELECT d.criterion_id
               FROM learning_session AS s
               JOIN learning_delegation AS d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
               WHERE s.owner_id=? AND s.id=?""",
            (owner, payload["session_id"]),
        ).fetchone()
        if delegation is None:
            raise DomainError("event_scope_invalid")
        if delegation["criterion_id"] is None and not purged:
            connection.execute(
                """INSERT OR IGNORE INTO learning_analysis_run
                   (id, owner_id, artifact_id, content_version, fact_event_id, criterion_id,
                    request_key, attempt, status, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, NULL, ?, 1, 'blocked_no_criterion', 'no approved criterion', ?)""",
                (
                    str(uuid5(NAMESPACE_URL, f"nautilus:analysis:{event['event_id']}")),
                    owner, payload["id"], content_version, event["event_id"],
                    f"artifact:{payload['id']}", occurred_at,
                ),
            )
    elif event_type == "session.ended":
        if event["aggregate_type"] != "action":
            raise DomainError("event_scope_invalid")
        changed = connection.execute(
            """UPDATE learning_session SET status=?, ended_at=?, version=?
               WHERE owner_id=? AND id=? AND status='running'""",
            (payload["disposition"], occurred_at, version, owner, payload["session_id"]),
        ).rowcount
        if changed != 1:
            raise DomainError("event_scope_invalid")
    elif event_type in {"action.completed", "delegation.completed"}:
        if event["aggregate_type"] != "action" or payload.get("action_id") != event["aggregate_id"]:
            raise DomainError("event_scope_invalid")
        changed = connection.execute(
            "UPDATE learning_action SET status=?, version=? WHERE owner_id=? AND id=? AND status='open'",
            ("completed" if event_type == "action.completed" else "open", version, owner, payload["action_id"]),
        ).rowcount
        delegation_changed = connection.execute(
            "UPDATE learning_delegation SET status='completed', version=version+1 WHERE owner_id=? AND id=? AND action_id=? AND status IN ('ready', 'active')",
            (owner, payload["delegation_id"], payload["action_id"]),
        ).rowcount
        connection.execute(
            "UPDATE learning_session SET status='ended', ended_at=?, version=version+1 WHERE owner_id=? AND delegation_id=? AND status='running'",
            (occurred_at, owner, payload["delegation_id"]),
        )
        if changed != 1 or delegation_changed != 1:
            raise DomainError("event_scope_invalid")
    elif event_type == "artifact.corrected":
        if event["aggregate_type"] != "action":
            raise DomainError("event_scope_invalid")
        content_version = payload.get("content_version")
        if not isinstance(content_version, int) or content_version < 1:
            raise DomainError("event_scope_invalid")
        existing = connection.execute(
            """SELECT 1 FROM learning_raw_artifact
               WHERE owner_id=? AND artifact_id=? AND content_version=? AND fact_event_id=?""",
            (owner, payload["artifact_id"], content_version, event["event_id"]),
        ).fetchone()
        if existing is None:
            current = connection.execute(
                """SELECT MAX(content_version) AS latest FROM learning_raw_artifact
                   WHERE owner_id=? AND artifact_id=?""",
                (owner, payload["artifact_id"]),
            ).fetchone()
            if current is None or current["latest"] is None or content_version != current["latest"] + 1:
                raise DomainError("event_scope_invalid")
        raw = _store_or_validate_raw_artifact(
            connection, event, payload,
            artifact_id=payload["artifact_id"], content_version=content_version,
        )
        purged = raw["purged_at"] is not None
        changed = connection.execute(
            """UPDATE learning_artifact SET content_version=?, visibility=?, evidence_status=?, version=?
               WHERE owner_id=? AND id=?""",
            (
                content_version,
                "purged" if purged else "visible",
                "invalidated" if purged else "eligible",
                content_version,
                owner,
                payload["artifact_id"],
            ),
        ).rowcount
        if changed != 1:
            raise DomainError("event_scope_invalid")

    elif event_type == "artifact.soft_deleted":
        if event["aggregate_type"] != "action":
            raise DomainError("event_scope_invalid")
        changed = connection.execute(
            """UPDATE learning_artifact
               SET visibility='soft_deleted', evidence_status='withdrawn', version=?
               WHERE owner_id=? AND id=?""",
            (version, owner, payload["artifact_id"]),
        ).rowcount
        if changed != 1:
            raise DomainError("event_scope_invalid")
    elif event_type == "artifact.restored":
        if event["aggregate_type"] != "action":
            raise DomainError("event_scope_invalid")
        changed = connection.execute(
            """UPDATE learning_artifact
               SET visibility='visible', evidence_status='eligible', version=?
               WHERE owner_id=? AND id=?""",
            (version, owner, payload["artifact_id"]),
        ).rowcount
        if changed != 1:
            raise DomainError("event_scope_invalid")
    elif event_type == "artifact.withdrawn":
        if event["aggregate_type"] != "action":
            raise DomainError("event_scope_invalid")
        changed = connection.execute(
            """UPDATE learning_artifact
               SET visibility='visible', evidence_status='withdrawn', version=?
               WHERE owner_id=? AND id=?""",
            (version, owner, payload["artifact_id"]),
        ).rowcount
        if changed != 1:
            raise DomainError("event_scope_invalid")
    elif event_type == "artifact.purged":
        if event["aggregate_type"] != "action":
            raise DomainError("event_scope_invalid")
        raw = connection.execute(
            """SELECT purged_at FROM learning_raw_artifact
               WHERE owner_id=? AND artifact_id=?""",
            (owner, payload["artifact_id"]),
        ).fetchone()
        if raw is None:
            raise DomainError("event_scope_invalid")
        if raw["purged_at"] is None:
            changed = connection.execute(
                """UPDATE learning_raw_artifact
                   SET purged_at=?, content=NULL, content_hash=NULL
                   WHERE owner_id=? AND artifact_id=?""",
                (occurred_at, owner, payload["artifact_id"]),
            ).rowcount
            if changed != 1:
                raise DomainError("event_scope_invalid")
        changed = connection.execute(
            """UPDATE learning_artifact
               SET visibility='purged', evidence_status='invalidated', version=?
               WHERE owner_id=? AND id=?""",
            (version, owner, payload["artifact_id"]),
        ).rowcount
        if changed != 1:
            raise DomainError("event_scope_invalid")
        connection.execute(
            """UPDATE learning_evidence_claim
               SET status='invalidated'
               WHERE owner_id=? AND artifact_id=? AND status <> 'invalidated'""",
            (owner, payload["artifact_id"]),
        )
        from ..verification_content import purge_artifact_copies
        purge_artifact_copies(connection, owner, payload["artifact_id"], occurred_at)

    if event["aggregate_type"] == "action":
        changed = connection.execute(
            "UPDATE learning_action SET version=? WHERE owner_id=? AND id=?",
            (version, owner, event["aggregate_id"]),
        ).rowcount
        if changed != 1:
            raise DomainError("event_scope_invalid")

    connection.execute(
        """INSERT INTO learning_projection_position VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(owner_id, aggregate_type, aggregate_id) DO UPDATE SET
               aggregate_version=excluded.aggregate_version,
               projection_version=excluded.projection_version,
               last_event_id=excluded.last_event_id""",
        (*aggregate, version, PROJECTION_VERSION, event["event_id"]),
    )


def upsert_stream_head(connection: sqlite3.Connection, event: dict) -> None:
    connection.execute(
        """INSERT INTO learning_stream_head VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(owner_id, aggregate_type, aggregate_id) DO UPDATE SET
               event_count=excluded.event_count, last_hash=excluded.last_hash""",
        (
            event["owner_id"], event["aggregate_type"], event["aggregate_id"],
            event["aggregate_version"], event["event_hash"],
        ),
    )


def append_event(
    connection: sqlite3.Connection, principal: Principal, *,
    command_id: str, key: str, aggregate_type: str, aggregate_id: str,
    expected_version: int, event_type: str, payload: dict, now: str,
) -> dict:
    aggregate = (principal.owner_id, aggregate_type, aggregate_id)
    head = connection.execute(
        """SELECT event_count, last_hash FROM learning_stream_head
           WHERE owner_id=? AND aggregate_type=? AND aggregate_id=?""",
        aggregate,
    ).fetchone()
    count = head["event_count"] if head else 0
    if count != expected_version:
        raise DomainError("version_conflict")
    position = connection.execute(
        """SELECT aggregate_version, projection_version FROM learning_projection_position
           WHERE owner_id=? AND aggregate_type=? AND aggregate_id=?""",
        aggregate,
    ).fetchone()
    if (
        (position["aggregate_version"] if position else 0) != count
        or (position is not None and position["projection_version"] != PROJECTION_VERSION)
    ):
        raise DomainError("projection_gap")

    private_content = payload.pop("content", None)
    if private_content is not None:
        payload["content_hash"] = _content_hash(private_content)
    event = {
        "event_id": str(uuid4()),
        "owner_id": principal.owner_id,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "aggregate_version": count + 1,
        "event_type": event_type,
        "event_version": next(iter(SUPPORTED_EVENT_VERSIONS)),
        "command_id": command_id,
        "idempotency_key": key,
        "actor_id": principal.actor_id,
        "actor_kind": principal.kind,
        "occurred_at": now,
        "recorded_at": now,
        "payload_json": canonical(payload),
        "metadata_json": "{}",
        "projection_version": PROJECTION_VERSION,
        "privacy": "private",
        "previous_hash": head["last_hash"] if head else None,
    }
    if private_content is not None:
        event["_private_content"] = private_content
    event["event_hash"] = event_digest(event)

    persisted = {name: value for name, value in event.items() if not name.startswith("_")}
    connection.execute(
        f"INSERT INTO learning_event ({','.join(persisted)}) VALUES ({','.join('?' for _ in persisted)})",
        tuple(persisted.values()),
    )
    apply_event(connection, event)
    upsert_stream_head(connection, event)
    return event
