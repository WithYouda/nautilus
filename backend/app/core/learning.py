from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from ..db import Database
from ..learning_domain import DomainError, LearningRepository, Principal
from ..goal_lifecycle import goal_review, require_goal_active, OPEN_GOAL_STATUSES
from .commands import (
    Command,
    ChangeGoalStatus,
    CorrectArtifact,
    CompleteLearningAction,
    CreateDelegation,
    ConfirmLearningSetup,
    CreateLearningAction,
    CreateOutcome,
    EndSession,
    PurgeArtifact,
    RestoreArtifact,
    SaveTextArtifact,
    RecordVerificationArtifact,
    SoftDeleteArtifact,
    StartSession,
    WithdrawArtifact,
)
from .events import (
    PROJECTION_VERSION,
    SUPPORTED_EVENT_TYPES,
    SUPPORTED_EVENT_VERSIONS,
    append_event,
    apply_event,
    canonical,
    digest,
    event_digest,
    upsert_stream_head,
)

PROJECTION_TABLES = (
    'learning_coach_decision','learning_coach_candidate','learning_coach_run_source',
    'learning_coach_consumed','learning_coach_run','learning_coach_signal','learning_coach_settings',
    'learning_action_removal',
    'learning_session_feedback_history', 'learning_session_feedback', 'learning_commitment_execution',
    'learning_commitment_item', 'learning_commitment_version', 'learning_commitment_draft',
    'learning_commitment_availability', 'learning_commitment_run', 'learning_plan_commitment_state',
    'learning_path_checkpoint',
    'learning_path_decision',
    'learning_path_version',
    'learning_path_draft',
    'learning_plan_path_state',
    "learning_plan_child",
    "learning_plan_organization",
    "learning_graph_candidate",
    "learning_graph_run",
    "learning_outcome_relation_history",
    "learning_outcome_relation",
    "learning_outcome_kind",
    # Analysis runs and evidence claims are retained as historical evidence
    # references; fact replay must not sever their foreign keys.
    "learning_artifact",
    "learning_session",
    "learning_contract_version",
    "learning_delegation",
    "learning_outcome",
    "learning_action",
    "learning_stream_head",
    "learning_projection_position",
    "learning_setup",
    "learning_action_link",
    "learning_module",
    "learning_plan",
    "learning_goal",
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class LearningCore:
    def __init__(self, database: Database):
        self.database = database

    def _audit(self, connection, principal, operation, result, reference_id=None, reason_code=None):
        connection.execute(
            "INSERT INTO learning_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()), principal.owner_id, principal.actor_id, operation, result,
                reference_id, reason_code, utc_timestamp(),
            ),
        )

    def _require_owner_user(self, principal: Principal) -> None:
        if principal.kind != "user" or principal.actor_id != principal.owner_id:
            raise DomainError("permission_denied", 403)

    def _require_owner(self, principal: Principal) -> None:
        if not self.database.fetchone("SELECT id FROM local_identity WHERE id=?", (principal.owner_id,)):
            raise DomainError("not_found", 404)

    def execute(self, principal: Principal, command: Command, idempotency_key: str) -> dict:
        operation = type(command).__name__
        self._require_owner(principal)
        try:
            with self.database.transaction(immediate=True) as connection:
                return self.execute_in_transaction(connection, principal, command, idempotency_key)
        except (DomainError, sqlite3.Error) as exc:
            error = exc if isinstance(exc, DomainError) else DomainError("storage_failure", 503)
            with self.database.transaction(immediate=True) as connection:
                self._audit(connection, principal, operation, "rejected", reason_code=error.code)
            raise error from exc

    def execute_in_transaction(
        self,
        connection: sqlite3.Connection,
        principal: Principal,
        command: Command,
        idempotency_key: str,
    ) -> dict:
        """Execute a command on a transaction owned by the caller."""
        operation = type(command).__name__
        self._require_owner(principal)
        self._require_owner_user(principal)
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise DomainError("invalid_idempotency_key", 422)
        payload = command.model_dump(mode="json")
        if isinstance(command, CreateOutcome) and command.kind == 'atomic':
            payload.pop('kind')
        # Preserve idempotency hashes issued before plan continuation existed.
        if isinstance(command, ConfirmLearningSetup) and command.plan_id is None:
            payload.pop("plan_id")
        if isinstance(command, CompleteLearningAction) and command.completion_id is None:
            payload.pop("completion_id")
        request_hash = digest({"command": operation, "payload": payload})
        previous = connection.execute(
            """SELECT request_hash, result_json FROM learning_command
               WHERE owner_id=? AND actor_id=? AND idempotency_key=?""",
            (principal.owner_id, principal.actor_id, idempotency_key),
        ).fetchone()
        if previous:
            if previous["request_hash"] != request_hash:
                raise DomainError("idempotency_conflict")
            return json.loads(previous["result_json"])
        command_id = str(uuid4())
        now = utc_timestamp()
        connection.execute(
            "INSERT INTO learning_command VALUES (?, ?, ?, ?, ?, ?, '{}', ?)",
            (command_id, principal.owner_id, principal.actor_id, idempotency_key, operation, request_hash, now),
        )
        result = self._dispatch(connection, principal, command, command_id, idempotency_key, now)
        connection.execute(
            "UPDATE learning_command SET result_json=? WHERE id=?",
            (canonical(result), command_id),
        )
        self._audit(connection, principal, operation, "succeeded", command_id)
        return result

    def _dispatch(self, connection, principal, command, command_id, key, now):
        from .coach_commands import CoachCommand
        if isinstance(command,CoachCommand):
            from .background_coach import dispatch
            return dispatch(self,connection,principal,command,command_id,key,now)
        from .commitment_commands import CommitmentCommand
        if isinstance(command, CommitmentCommand):
            from .commitments import dispatch_commitment
            return dispatch_commitment(self, connection, principal, command, command_id, key, now)
        from .path_commands import PathCommand
        if isinstance(command, PathCommand):
            from .learning_paths import dispatch_path
            return dispatch_path(self, connection, principal, command, command_id, key, now)
        from .graph_commands import GraphCommand
        if isinstance(command, GraphCommand):
            from .outcome_graph import dispatch_graph
            return dispatch_graph(connection, principal, command, command_id, key, now)
        from .organization_commands import OrganizationCommand
        if isinstance(command, OrganizationCommand):
            from .plan_organization import dispatch_organization
            return dispatch_organization(self, connection, principal, command, command_id, key, now)
        repository = LearningRepository(self.database, principal)
        object_id = str(uuid4())
        payload = {"id": object_id, **command.model_dump(exclude={"expected_version"})}
        if isinstance(command, CreateLearningAction):
            aggregate_type, aggregate_id, expected = "action", object_id, 0
            event_type = "action.created"
        elif isinstance(command, CreateOutcome):
            aggregate_type, aggregate_id, expected = "outcome", object_id, 0
            event_type = "outcome.created"
        elif isinstance(command, ConfirmLearningSetup):
            return self._dispatch_setup(connection, principal, command, command_id, key, now, repository)
        elif isinstance(command, ChangeGoalStatus):
            return self._dispatch_goal(connection, principal, command, command_id, key, now)
        elif isinstance(command, CreateDelegation):
            require_goal_active(connection, principal.owner_id, command.action_id)
            action = repository.action(command.action_id)
            if action["status"] != "open":
                raise DomainError("action_not_open")
            repository.validate_binding(command.action_id, command.outcome_id, command.criterion_id)
            aggregate_type, aggregate_id, expected = "action", command.action_id, command.expected_version
            event_type = "delegation.created"
        elif isinstance(command, StartSession):
            delegation = repository.delegation(command.delegation_id)
            action = repository.action(delegation["action_id"])
            require_goal_active(connection, principal.owner_id, action['id'])
            if action["status"] != "open":
                raise DomainError("action_not_open")
            if delegation["status"] not in {"ready", "active"}:
                raise DomainError("delegation_not_startable")
            if connection.execute(
                "SELECT 1 FROM learning_session WHERE owner_id=? AND status='running'",
                (principal.owner_id,),
            ).fetchone():
                raise DomainError("session_already_running")
            aggregate_type = "action"
            aggregate_id = action["id"]
            expected = command.expected_version
            payload = {
                "id": object_id,
                "delegation_id": command.delegation_id,
                "contract_version": delegation["contract_version"],
            }
            event_type = "session.started"
        elif isinstance(command, CompleteLearningAction):
            require_goal_active(connection, principal.owner_id, command.action_id)
            action = repository.action(command.action_id)
            if action["status"] != "open":
                raise DomainError("action_not_open")
            delegation = repository.delegation(command.delegation_id)
            if delegation["action_id"] != command.action_id:
                raise DomainError("event_scope_invalid")
            if delegation["status"] not in {"ready", "active"}:
                raise DomainError("delegation_not_startable")
            aggregate_type = "action"
            aggregate_id = command.action_id
            expected = command.expected_version
            payload = {
                "id": object_id,
                "action_id": command.action_id,
                "delegation_id": command.delegation_id,
            }
            if command.completion_id:
                payload["completion_id"] = command.completion_id
            others = connection.execute(
                "SELECT 1 FROM learning_delegation WHERE owner_id=? AND action_id=? AND id<>? AND status IN ('ready', 'active', 'paused')",
                (principal.owner_id, command.action_id, command.delegation_id),
            ).fetchone()
            event_type = "delegation.completed" if others else "action.completed"
        elif isinstance(command, RecordVerificationArtifact):
            submission = connection.execute(
                """SELECT s.*, v.session_id FROM learning_verification_submission s
                   JOIN learning_verification v ON v.owner_id=s.owner_id AND v.id=s.verification_id
                   WHERE s.owner_id=? AND s.id=?""", (principal.owner_id, command.submission_id),
            ).fetchone()
            if submission is None:
                raise DomainError("not_found", 404)
            if submission["purged_at"] or submission["artifact_id"]:
                raise DomainError("artifact_not_eligible")
            if not submission["session_id"]:
                raise DomainError("verification_session_required")
            session = repository.session(submission["session_id"])
            aggregate_type = "action"
            aggregate_id = repository.delegation(session["delegation_id"])["action_id"]
            expected = command.expected_version
            payload = {"id": object_id, "session_id": session["id"], "content_version": 1,
                       "content": submission["content_json"], "submission_id": command.submission_id,
                       "submitted_at": submission["created_at"]}
            event_type = "verification.artifact_recorded"
        elif isinstance(command, SaveTextArtifact):
            session = repository.session(command.session_id)
            if session["status"] != "running":
                raise DomainError("session_not_running")
            aggregate_type = "action"
            aggregate_id = repository.delegation(session["delegation_id"])["action_id"]
            expected = command.expected_version
            payload = {
                "id": object_id,
                "session_id": command.session_id,
                "content_version": 1,
                "content": command.content,
            }
            event_type = "artifact.created"
        elif isinstance(command, EndSession):
            session = repository.session(command.session_id)
            if session["status"] != "running":
                raise DomainError("session_not_running")
            aggregate_type = "action"
            aggregate_id = repository.delegation(session["delegation_id"])["action_id"]
            expected = command.expected_version
            payload = {
                "id": object_id,
                "session_id": command.session_id,
                "disposition": command.disposition,
            }
            event_type = "session.ended"
        elif isinstance(command, CorrectArtifact):
            if connection.execute(
                "SELECT 1 FROM learning_verification_submission WHERE owner_id=? AND artifact_id=?",
                (principal.owner_id, command.artifact_id),
            ).fetchone():
                raise DomainError("verification_submission_immutable")
            artifact = connection.execute(
                """SELECT artifact_id, session_id, purged_at FROM learning_raw_artifact
                   WHERE owner_id=? AND artifact_id=? ORDER BY content_version DESC LIMIT 1""",
                (principal.owner_id, command.artifact_id),
            ).fetchone()
            if artifact is None:
                raise DomainError("not_found", 404)
            if artifact["purged_at"] is not None:
                raise DomainError("artifact_not_eligible")
            session = repository.session(artifact["session_id"])
            aggregate_type = "action"
            aggregate_id = repository.delegation(session["delegation_id"])["action_id"]
            expected = command.expected_version
            latest = connection.execute(
                """SELECT MAX(content_version) AS latest FROM learning_raw_artifact
                   WHERE owner_id=? AND artifact_id=?""",
                (principal.owner_id, command.artifact_id),
            ).fetchone()["latest"]
            if latest is None:
                raise DomainError("not_found", 404)
            payload = {
                "id": object_id,
                "artifact_id": command.artifact_id,
                "content_version": latest + 1,
                "content": command.content,
            }
            event_type = "artifact.corrected"
        elif isinstance(command, (SoftDeleteArtifact, RestoreArtifact, WithdrawArtifact, PurgeArtifact)):
            artifact = connection.execute(
                """SELECT raw.artifact_id, raw.session_id, raw.purged_at,
                          current_artifact.visibility, current_artifact.evidence_status
                   FROM learning_raw_artifact AS raw
                   JOIN learning_artifact AS current_artifact
                     ON current_artifact.owner_id=raw.owner_id
                    AND current_artifact.id=raw.artifact_id
                   WHERE raw.owner_id=? AND raw.artifact_id=?
                   ORDER BY raw.content_version DESC LIMIT 1""",
                (principal.owner_id, command.artifact_id),
            ).fetchone()
            if artifact is None:
                raise DomainError("not_found", 404)
            session = repository.session(artifact["session_id"])
            aggregate_type = "action"
            aggregate_id = repository.delegation(session["delegation_id"])["action_id"]
            expected = command.expected_version
            payload = {
                "id": object_id,
                "artifact_id": command.artifact_id,
            }
            if isinstance(command, SoftDeleteArtifact):
                if artifact["visibility"] != "visible":
                    raise DomainError("artifact_not_visible", 409)
                event_type = "artifact.soft_deleted"
            elif isinstance(command, RestoreArtifact):
                if artifact["visibility"] != "soft_deleted":
                    raise DomainError("artifact_not_soft_deleted", 409)
                event_type = "artifact.restored"
            elif isinstance(command, WithdrawArtifact):
                if artifact["purged_at"] is not None or artifact["evidence_status"] == "withdrawn":
                    raise DomainError("artifact_not_eligible", 409)
                event_type = "artifact.withdrawn"
            else:
                if artifact["purged_at"] is not None:
                    previous = connection.execute(
                        "SELECT event_id, aggregate_version FROM learning_event WHERE owner_id=? AND event_type='artifact.purged' AND json_extract(payload_json, '$.artifact_id')=? ORDER BY position DESC LIMIT 1",
                        (principal.owner_id, command.artifact_id),
                    ).fetchone()
                    if previous is None:
                        raise DomainError("event_integrity_failed")
                    return {"id": command.artifact_id, "aggregate_id": aggregate_id,
                            "version": previous["aggregate_version"], "event_id": previous["event_id"]}
                payload["confirmation"] = command.confirmation
                event_type = "artifact.purged"
        else:
            raise DomainError("command_unsupported", 422)

        event = append_event(
            connection, principal,
            command_id=command_id, key=key,
            aggregate_type=aggregate_type, aggregate_id=aggregate_id,
            expected_version=expected, event_type=event_type,
            payload=payload, now=now,
        )
        return {
            "id": payload.get("artifact_id", payload.get("id")),
            "aggregate_id": aggregate_id,
            "version": event["aggregate_version"],
            "event_id": event["event_id"],
        }

    def _dispatch_goal(self, connection, principal, command, command_id, key, now):
        review = goal_review(connection, principal.owner_id, command.goal_id)
        goal = review['goal']
        if goal['version'] != command.expected_version:
            raise DomainError('version_conflict')
        if review['review_key'] != command.review_key:
            raise DomainError('goal_review_changed')
        closing = goal['status'] in OPEN_GOAL_STATUSES
        if (closing and command.status == 'active') or (not closing and command.status != 'active'):
            raise DomainError('goal_invalid_transition')
        interrupted = []
        for task in review['tasks']:
            for session_id in task['running_session_ids']:
                if command.status == 'active':
                    continue
                version = connection.execute('SELECT version FROM learning_action WHERE owner_id=? AND id=?',
                                             (principal.owner_id, task['id'])).fetchone()[0]
                append_event(connection, principal, command_id=command_id, key=key,
                             aggregate_type='action', aggregate_id=task['id'], expected_version=version,
                             event_type='session.ended', payload=dict(session_id=session_id, disposition='interrupted'), now=now)
                interrupted.append(session_id)
        event = append_event(connection, principal, command_id=command_id, key=key,
                             aggregate_type='goal', aggregate_id=goal['id'], expected_version=goal['version'] - 1,
                             event_type='goal.status_changed',
                             payload=dict(id=goal['id'], previous_status=goal['status'], status=command.status), now=now)
        return dict(id=goal['id'], version=goal['version'] + 1, status=command.status,
                    event_id=event['event_id'], interrupted_session_ids=interrupted)

    def _dispatch_setup(self, connection, principal, command, command_id, key, now, repository):
        existing_plan = existing_goal = None
        if command.plan_id:
            existing_plan = repository._owned("learning_plan", command.plan_id)
            if existing_plan["status"] != "active":
                raise DomainError("plan_not_active")
            existing_goal = repository._owned("learning_goal", existing_plan["goal_id"])
            if existing_goal['status'] not in OPEN_GOAL_STATUSES:
                raise DomainError('goal_not_active')
        if command.criterion_id and not command.outcome_id:
            raise DomainError("criterion_outcome_required")
        if command.outcome_id:
            outcome = repository._owned("learning_outcome", command.outcome_id)
            if (
                command.criterion_id is not None
                and repository._owned("learning_criterion_version", command.criterion_id)["outcome_id"] != command.outcome_id
            ):
                raise DomainError("criterion_outcome_mismatch")
            outcome_id = command.outcome_id
        else:
            outcome_id = str(uuid4())
            append_event(
                connection, principal, command_id=command_id, key=key,
                aggregate_type="outcome", aggregate_id=outcome_id, expected_version=0,
                event_type="outcome.created",
                payload={
                    "id": outcome_id,
                    "object_description": command.object_description,
                    "behavior": command.behavior,
                    "context_key": command.outcome_context_key,
                }, now=now,
            )

        action_id = str(uuid4())
        append_event(
            connection, principal, command_id=command_id, key=key,
            aggregate_type="action", aggregate_id=action_id, expected_version=0,
            event_type="action.created",
            payload={"id": action_id, "title": command.action_title, "context_key": command.context_key}, now=now,
        )
        delegation_id = str(uuid4())
        action = connection.execute(
            "SELECT context_key, status FROM learning_action WHERE owner_id=? AND id=?",
            (principal.owner_id, action_id),
        ).fetchone()
        if action is None or action["status"] != "open":
            raise DomainError("action_not_open")
        outcome = connection.execute(
            "SELECT context_key FROM learning_outcome WHERE owner_id=? AND id=?",
            (principal.owner_id, outcome_id),
        ).fetchone()
        if outcome is None:
            raise DomainError("not_found", 404)
        repository.validate_binding(action_id, outcome_id, command.criterion_id)
        append_event(
            connection, principal, command_id=command_id, key=key,
            aggregate_type="action", aggregate_id=action_id, expected_version=1,
            event_type="delegation.created",
            payload={
                "id": delegation_id,
                "action_id": action_id,
                "outcome_id": outcome_id,
                "criterion_id": command.criterion_id,
                "boundaries": command.boundaries,
                "stop_conditions": command.stop_conditions,
                "time_budget_minutes": command.time_budget_minutes,
            }, now=now,
        )
        from .plan_organization import revision, append_task
        private_plan_header = bool(existing_plan and revision(connection, principal.owner_id, existing_plan["id"])
            and connection.execute("SELECT 1 FROM learning_plan_private WHERE owner_id=? AND kind='plan' AND object_id=?",
                                   (principal.owner_id, existing_plan["id"])).fetchone())
        # Legacy step projection uses plan.id only, while requiring a nonempty
        # header. D2 private names must never be copied into this immutable event.
        plan_header = {"title":"计划", "description":""} if private_plan_header else {
            "title":existing_plan["title"] if existing_plan else command.plan_title,
            "description":existing_plan["description"] if existing_plan else command.plan_description}
        setup_id = str(uuid4())
        goal_id = existing_goal["id"] if existing_goal else str(uuid4())
        plan_id = existing_plan["id"] if existing_plan else str(uuid4())
        event = append_event(
            connection, principal, command_id=command_id, key=key,
            aggregate_type="setup", aggregate_id=setup_id, expected_version=0,
            event_type="plan.step_added" if existing_plan else "setup.confirmed",
            payload={
                "id": setup_id,
                "goal": {
                    "id": goal_id,
                    "original_intent": existing_goal["original_intent"] if existing_goal else command.original_intent,
                    "title": existing_goal["title"] if existing_goal else command.goal_title,
                    "description": existing_goal["description"] if existing_goal else command.goal_description,
                },
                "plan": {"id": plan_id, **plan_header},
                "action_link": {"action_id": action_id, "plan_id": plan_id, "module_id": None},
                "setup": {
                    "original_intent": command.original_intent,
                    "id": setup_id,
                    "action_id": action_id,
                    "outcome_id": outcome_id,
                    "delegation_id": delegation_id,
                },
            }, now=now,
        )
        if revision(connection, principal.owner_id, plan_id):
            append_task(connection, principal, command_id, key, now, plan_id, action_id, delegation_id, outcome_id, existing_link=True)
        return {
            "id": setup_id,
            "setup_id": setup_id,
            "goal_id": goal_id,
            "plan_id": plan_id,
            "action_id": action_id,
            "outcome_id": outcome_id,
            "delegation_id": delegation_id,
            "version": event["aggregate_version"],
            "event_id": event["event_id"],
        }

    def artifact(self, principal, artifact_id, content_version=None):
        self._require_owner_user(principal)
        self._require_owner(principal)
        sql = "SELECT * FROM learning_raw_artifact WHERE owner_id=? AND artifact_id=?"
        args = [principal.owner_id, artifact_id]
        if content_version is not None:
            sql += " AND content_version=?"
            args.append(content_version)
        row = self.database.fetchone(sql + " ORDER BY content_version DESC LIMIT 1", tuple(args))
        if not row:
            raise DomainError("not_found", 404)
        return dict(row)

    def _validate_event_stream(self, rows: list[dict]) -> dict[tuple[str, str, str], tuple[int, str, str]]:
        chains: dict[tuple[str, str, str], tuple[int, str, str]] = {}
        for row in rows:
            if row["event_version"] not in SUPPORTED_EVENT_VERSIONS:
                raise DomainError("event_version_unsupported")
            if row["projection_version"] != PROJECTION_VERSION:
                raise DomainError("projection_version_unsupported")
            if row["event_hash"] != event_digest(row):
                raise DomainError("event_integrity_failed")
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise DomainError("event_integrity_failed") from exc
            if not isinstance(payload, dict):
                raise DomainError("event_integrity_failed")
            if row["event_type"] not in SUPPORTED_EVENT_TYPES:
                raise DomainError("event_type_unsupported")

            key = (row["owner_id"], row["aggregate_type"], row["aggregate_id"])
            previous = chains.get(key)
            if previous is None:
                if row["aggregate_version"] != 1 or row["previous_hash"] is not None:
                    raise DomainError("event_gap" if row["aggregate_version"] != 1 else "event_chain_invalid")
            else:
                if row["aggregate_version"] != previous[0] + 1:
                    raise DomainError("event_gap")
                if row["previous_hash"] != previous[1]:
                    raise DomainError("event_chain_invalid")
            chains[key] = (row["aggregate_version"], row["event_hash"], row["event_id"])
        return chains

    def replay(self, principal: Principal):
        self._require_owner(principal)
        try:
            self._require_owner_user(principal)
            from ..replay_check import projection_snapshot, record_comparison
            with self.database.transaction(immediate=True) as connection:
                before = projection_snapshot(connection, principal.owner_id, PROJECTION_TABLES)
                rows = [
                    dict(row)
                    for row in self.database.fetchall(
                        "SELECT * FROM learning_event WHERE owner_id=? ORDER BY position",
                        (principal.owner_id,),
                    )
                ]
                chains = self._validate_event_stream(rows)
                connection.execute("PRAGMA defer_foreign_keys=ON")
                for table in PROJECTION_TABLES:
                    if table == "learning_outcome":
                        # Approved standard packages are immutable reference data,
                        # not event-derived user projections.
                        connection.execute(
                            """DELETE FROM learning_outcome
                               WHERE owner_id=? AND source <> 'standard'
                                 AND NOT EXISTS (
                                     SELECT 1 FROM learning_criterion_version AS c
                                      WHERE c.owner_id=learning_outcome.owner_id
                                        AND c.outcome_id=learning_outcome.id
                                 )""",
                            (principal.owner_id,),
                        )
                    else:
                        connection.execute(f"DELETE FROM {table} WHERE owner_id=?", (principal.owner_id,))

                for row in rows:
                    apply_event(connection, row)
                    upsert_stream_head(connection, row)

                if connection.execute(
                    "SELECT COUNT(*) FROM learning_projection_position WHERE owner_id=?",
                    (principal.owner_id,),
                ).fetchone()[0] != len(chains):
                    raise DomainError("projection_rebuild_incomplete")
                for (owner_id, aggregate_type, aggregate_id), (version, _, event_id) in chains.items():
                    position = connection.execute(
                        """SELECT aggregate_version, last_event_id FROM learning_projection_position
                           WHERE owner_id=? AND aggregate_type=? AND aggregate_id=?""",
                        (owner_id, aggregate_type, aggregate_id),
                    ).fetchone()
                    if position is None or position["aggregate_version"] != version or position["last_event_id"] != event_id:
                        raise DomainError("projection_rebuild_incomplete")

                after = projection_snapshot(connection, principal.owner_id, PROJECTION_TABLES)
                comparison = record_comparison(connection, principal.owner_id, "fact", max((row["position"] for row in rows), default=0), before, after)
                self._audit(connection, principal, "Replay", "succeeded")
                return {
                    "status": "succeeded",
                    "comparison": comparison,
                    "event_count": len(rows),
                    "aggregate_count": len(chains),
                    "projection_digest": digest(
                        {
                            f"{owner}:{aggregate_type}:{aggregate_id}": [version, event_hash]
                            for (owner, aggregate_type, aggregate_id), (version, event_hash, _) in chains.items()
                        }
                    ),
                }
        except (DomainError, sqlite3.Error) as exc:
            error = exc if isinstance(exc, DomainError) else DomainError("storage_failure", 503)
            with self.database.transaction(immediate=True) as connection:
                self._audit(connection, principal, "Replay", "rejected", reason_code=error.code)
            raise error from exc

    def events(self, principal: Principal, action_id: str) -> list[dict]:
        self._require_owner(principal)
        try:
            self._require_owner_user(principal)
            LearningRepository(self.database, principal).action(action_id)
            return [
                dict(row)
                for row in self.database.fetchall(
                    """SELECT * FROM learning_event
                       WHERE owner_id=? AND aggregate_type='action' AND aggregate_id=?
                       ORDER BY aggregate_version""",
                    (principal.owner_id, action_id),
                )
            ]
        except DomainError as exc:
            with self.database.transaction(immediate=True) as connection:
                self._audit(connection, principal, "ReadEvents", "rejected", reason_code=exc.code)
            raise
