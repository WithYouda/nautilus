from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
from urllib.parse import urlsplit

from .conversations import ConversationError, ConversationService
from .core.commands import CompleteLearningAction, RecordVerificationArtifact, PurgeArtifact
from .core.events import digest
from .learning_domain import DomainError, LearningRepository, Principal
from .learning_service import LearningService
from .providers import ProviderError, build_provider
from .verification_content import submission_content, learner_content

VERIFICATION_FAILURE_MESSAGES = {
    "verification_provider_unavailable": "验证使用的 AI 配置不可用，请返回学习室检查所选提供方和模型。",
    "verification_timeout": "AI 验证请求超时，可在提供方设置中增加超时时间后重试。已有学习记录和作答仍保留。",
    "verification_auth_error": "AI 提供方拒绝访问，请检查 API Key、账户余额和模型权限。",
    "verification_rate_limited": "AI 提供方限流或额度不足，请检查账户后重试。",
    "verification_network_error": "无法连接 AI 提供方，请检查服务地址和网络。",
    "verification_endpoint_not_found": "AI 接口或模型不存在，请检查提供方地址和模型名称。",
    "verification_request_error": "AI 提供方不接受本次请求，请检查模型是否支持 JSON 输出及当前请求参数。",
    "verification_upstream_error": "AI 提供方服务异常，请稍后重试。",
    "verification_output_truncated": "AI 输出达到长度上限，题目或评估不完整；请缩小本次学习范围或换用适合的模型后重试。",
    "verification_reasoning_only": "AI 只返回了思考过程，没有最终结果；请换用非推理模型或重试。",
    "verification_content_filtered": "AI 提供方未提供本次内容，请调整学习范围或改为提交自己的材料。",
    "verification_invalid": "AI 返回的 JSON 或验证结构不完整，请重试；也可以改为提交自己的材料。",
}


def _failure_code(error: Exception) -> str:
    if isinstance(error, ConversationError):
        return "verification_provider_unavailable"
    if isinstance(error, TimeoutError):
        return "verification_timeout"
    if isinstance(error, ProviderError):
        code = f"verification_{error.kind}"
        return code if code in VERIFICATION_FAILURE_MESSAGES else "verification_invalid"
    return "verification_invalid"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _clean_json(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


class VerificationService:
    """Small, explicit verification boundary kept separate from teaching chat."""

    def __init__(
        self,
        learning: LearningService,
        conversations: ConversationService,
        transport=None,
        evidence=None,
    ) -> None:
        self.learning = learning
        self.conversations = conversations
        self.transport = transport
        self.evidence = evidence

    def _public(self, row: dict[str, Any]) -> dict[str, Any]:
        challenge = json.loads(row["challenge_json"])
        result = json.loads(row["result_json"]) if row.get("result_json") else None
        evaluation = self.learning.database.fetchone(
            "SELECT id, status, reason FROM learning_verification_evaluation WHERE owner_id=? AND submission_id=? ORDER BY rowid DESC LIMIT 1",
            (row["owner_id"], row.get("latest_submission_id")),
        )
        action = self.learning.database.fetchone("SELECT status FROM learning_action WHERE owner_id=? AND id=?", (row["owner_id"], row["action_id"]))
        submission = self.learning.database.fetchone(
            "SELECT artifact_id, purged_at FROM learning_verification_submission WHERE owner_id=? AND id=?",
            (row["owner_id"], row.get("latest_submission_id")),
        )
        return {
            "id": row["id"],
            "action_id": row["action_id"],
            "delegation_id": row["delegation_id"],
            "session_id": row["session_id"],
            "mode": row["mode"],
            "status": row["status"],
            "challenge": challenge,
            "result": {k: v for k, v in result.items() if k != "question_feedback"} if result else None,
            "stop_condition_confirmed": bool(row["stop_condition_confirmed"]),
            "stop_condition_met": None if row["stop_condition_met"] is None else bool(row["stop_condition_met"]),
            "created_at": row["created_at"],
            "submitted_at": row["submitted_at"],
            "latest_submission_id": row.get("latest_submission_id"),
            "evaluation": {**dict(evaluation), "message": VERIFICATION_FAILURE_MESSAGES.get(evaluation["reason"])} if evaluation else None,
            "action_completed": action["status"] == "completed",
            "stop_conditions": json.loads(row["contract_snapshot_json"])["stop_conditions"],
            "artifact_id": submission["artifact_id"] if submission else None,
            "content_purged": bool(row["purged_at"] or (submission and submission["purged_at"])),
            "verification_purged": bool(row["purged_at"]),
            "evidence": self._evidence_summary(row),
        }

    def _owned_context(self, owner_id: str, action_id: str, delegation_id: str, session_id: str | None):
        principal = Principal.user(owner_id)
        repository = LearningRepository(self.learning.database, principal)
        action = repository.action(action_id)
        delegation = repository.delegation(delegation_id)
        if delegation["action_id"] != action_id:
            raise DomainError("verification_scope_invalid")
        if session_id:
            session = repository.session(session_id)
            if session["delegation_id"] != delegation_id:
                raise DomainError("verification_scope_invalid")
        else:
            session = None
        contract = self.learning.database.fetchone(
            "SELECT * FROM learning_contract_version WHERE owner_id=? AND delegation_id=? AND version=?",
            (owner_id, delegation_id, delegation["contract_version"]),
        )
        outcome = self.learning.database.fetchone(
            "SELECT object_description, behavior FROM learning_outcome WHERE owner_id=? AND id=?",
            (owner_id, delegation["outcome_id"]),
        )
        if contract is None or outcome is None:
            raise DomainError("not_found", 404)
        if action["status"] != "open":
            raise DomainError("action_not_open")
        if delegation["status"] not in {"ready", "active"}:
            raise DomainError("delegation_not_startable")
        return action, delegation, dict(contract), dict(outcome), session

    def _runtime(self, owner_id: str, session_id: str | None):
        # Use the teaching room's explicit selection, including a resumed session.
        # A broken explicit choice must not silently send work to the default provider.
        link = self.learning.database.fetchone(
            """SELECT r.conversation_id FROM learning_room_conversation r
               JOIN learning_session linked ON linked.owner_id=r.owner_id AND linked.id=r.session_id
               JOIN learning_session current ON current.owner_id=linked.owner_id AND current.delegation_id=linked.delegation_id
               WHERE current.owner_id=? AND current.id=? ORDER BY r.selected_at DESC, r.conversation_id LIMIT 1""",
            (owner_id, session_id),
        ) if session_id else None
        if link:
            profile, config, _snapshot = self.conversations.runtime_for_conversation(owner_id, link["conversation_id"])
            return profile, config
        return self.conversations.provider_runtime(owner_id)

    async def _generate_challenge(self, owner_id: str, outcome: dict[str, Any], contract: dict[str, Any], session_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            _profile, config = self._runtime(owner_id, session_id)
            provider = build_provider(config, transport=self.transport)
            prompt = {
                "outcome": outcome,
                "boundaries": contract["boundaries"],
                "stop_conditions": contract["stop_conditions"],
                "instructions": [
                    "生成 1 到 3 个真实、有区分度的验证任务，不要生成填空题。",
                    "优先使用真实场景、代码/项目任务、简答解释或判断题；问题必须能观察用户是否真的会做或会解释。",
                    "本次调用没有搜索工具。不得声称已联网、已搜索或已核验网页；source_urls 返回空数组。",
                    "题目中不要放答案、评分细节或隐藏提示。答案只放在 answer_key 字段供服务端评估。",
                    "只返回 JSON，不要 Markdown 围栏。题目文字可含 Markdown 和 LaTeX，但 JSON 字符串中的反斜杠必须正确转义。",
                    "type 只能是 scenario、project、short_response、true_false 中的一个。",
                ],
                "schema": {
                    "questions": [
                        {
                            "id": "q1",
                            "type": "short_response",
                            "prompt": "题目",
                            "source_urls": [],
                            "pass_criteria": "通过条件",
                            "answer_key": "服务端答案或评估依据",
                        }
                    ]
                },
            }
            async with asyncio.timeout(config.timeout_seconds):
                text = await provider.generate_text(
                    [
                        {"role": "system", "content": "你是 Nautilus 的验证设计助手。验证必须与教学分离，且不能向考生泄露答案。只输出 JSON。"},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                    max_tokens=8192,
                    json_mode=True,
                )
            parsed = json.loads(_clean_json(text))
        except (ConversationError, ProviderError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            raise DomainError(_failure_code(exc), 502) from exc

        questions = parsed.get("questions") if isinstance(parsed, dict) else None
        if not isinstance(questions, list) or not 1 <= len(questions) <= 3:
            raise DomainError("verification_invalid", 502)
        public_questions: list[dict[str, Any]] = []
        answer_questions: list[dict[str, Any]] = []
        question_ids: set[str] = set()
        allowed_types = {"scenario", "project", "short_response", "true_false"}
        for index, question in enumerate(questions, start=1):
            if not isinstance(question, dict):
                raise DomainError("verification_invalid", 502)
            question_id = question.get("id") or f"q{index}"
            question_type = question.get("type")
            prompt_text = question.get("prompt")
            answer_key = question.get("answer_key")
            if not isinstance(question_type, str) or question_type not in allowed_types or not isinstance(prompt_text, str) or not prompt_text.strip() or not isinstance(answer_key, str) or not answer_key.strip():
                raise DomainError("verification_invalid", 502)
            question_id = str(question_id)
            if question_id in question_ids:
                raise DomainError("verification_invalid", 502)
            question_ids.add(question_id)
            if re.search(r"填空|补全", prompt_text):
                raise DomainError("verification_invalid", 502)
            urls = question.get("source_urls", [])
            if not isinstance(urls, list) or any(not self._valid_source(url) for url in urls):
                raise DomainError("verification_invalid", 502)
            item = {
                "id": question_id,
                "type": question_type,
                "prompt": prompt_text.strip(),
                "source_urls": urls[:5],
            }
            public_questions.append(item)
            answer_questions.append({
                **item,
                "pass_criteria": str(question.get("pass_criteria") or "能独立完成并说明关键依据").strip(),
                "answer_key": answer_key.strip(),
            })
        return {"questions": public_questions}, {"questions": answer_questions}

    @staticmethod
    def _valid_source(url: Any) -> bool:
        if not isinstance(url, str) or any(char.isspace() for char in url):
            return False
        try:
            parsed = urlsplit(url)
            parsed.port  # Reject malformed port numbers without fetching the URL.
            host = (parsed.hostname or "").lower().rstrip(".")
            return (parsed.scheme in {"https", "http"} and "." in host
                    and not parsed.username and not parsed.password
                    and not any(host == item or host.endswith("." + item) for item in
                                ("example.com", "example.org", "example.net", "invalid", "test", "localhost")))
        except ValueError:
            return False

    async def start(self, identity: dict[str, Any], payload: dict[str, Any], request_key: str) -> dict[str, Any]:
        principal = self.learning.principal(identity)
        fingerprint = digest({
            "action_id": payload["action_id"],
            "delegation_id": payload["delegation_id"],
            "session_id": payload.get("session_id"),
            "mode": payload["mode"],
        })
        existing = self.learning.database.fetchone(
            "SELECT * FROM learning_verification WHERE owner_id=? AND request_key=?",
            (principal.owner_id, request_key),
        )
        if existing:
            if existing["request_fingerprint"] != fingerprint:
                raise DomainError("idempotency_conflict")
            return self._public(dict(existing))
        mode = payload["mode"]
        action, delegation, contract, outcome, session = self._owned_context(
            principal.owner_id, payload["action_id"], payload["delegation_id"], payload.get("session_id")
        )
        if mode == "ai_challenge":
            challenge, answer_key = await self._generate_challenge(principal.owner_id, outcome, contract, payload.get("session_id"))
        else:
            challenge = {
                "instructions": "粘贴题目、标准答案、项目材料或你自己的理解。系统只会评估你提交的材料，不会把材料当作已验证事实。",
                "stop_condition": contract["stop_conditions"],
            }
            answer_key = {"kind": "user_material"}
        now = _now()
        verification_id = str(uuid4())
        try:
            with self.learning.database.transaction(immediate=True) as connection:
                self._owned_context(principal.owner_id, action["id"], delegation["id"], payload.get("session_id"))
                connection.execute(
                    """INSERT INTO learning_verification
                       (id, owner_id, action_id, delegation_id, session_id, mode, request_key,
                        request_fingerprint, status, challenge_json, answer_key_json, created_at, contract_snapshot_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?)""",
                    (
                        verification_id, principal.owner_id, action["id"], delegation["id"],
                        session["id"] if session else None, mode, request_key, fingerprint,
                        json.dumps(challenge, ensure_ascii=False), json.dumps(answer_key, ensure_ascii=False), now,
                        json.dumps({"version": contract["version"], "boundaries": contract["boundaries"],
                                    "stop_conditions": contract["stop_conditions"], "criterion_id": delegation["criterion_id"]}, ensure_ascii=False),
                    ),
                )
                connection.execute(
                    "INSERT INTO learning_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), principal.owner_id, principal.actor_id, "StartVerification", "succeeded", verification_id, mode, now),
                )
        except sqlite3.IntegrityError as exc:
            existing = self.learning.database.fetchone(
                "SELECT * FROM learning_verification WHERE owner_id=? AND request_key=?",
                (principal.owner_id, request_key),
            )
            if existing is not None and existing["request_fingerprint"] == fingerprint:
                return self._public(dict(existing))
            raise DomainError("storage_failure", 503) from exc
        row = self.learning.database.fetchone("SELECT * FROM learning_verification WHERE owner_id=? AND id=?", (principal.owner_id, verification_id))
        return self._public(dict(row))

    def _owned(self, owner_id: str, verification_id: str) -> dict[str, Any]:
        row = self.learning.database.fetchone(
            "SELECT * FROM learning_verification WHERE owner_id=? AND id=?", (owner_id, verification_id),
        )
        if row is None:
            raise DomainError("not_found", 404)
        return dict(row)

    def _evidence_summary(self, row):
        runs = self.learning.database.fetchall(
            """SELECT r.id, r.status, r.reason FROM learning_verification_evaluation e
               JOIN learning_analysis_run r ON r.owner_id=e.owner_id AND r.id=e.evidence_run_id
               WHERE e.owner_id=? AND e.submission_id=? ORDER BY e.rowid DESC LIMIT 1""",
            (row["owner_id"], row.get("latest_submission_id")),
        )
        return dict(runs[0]) if runs else None

    def _link_submission(self, connection, principal, current, submission):
        if submission["artifact_id"] or submission["purged_at"] or not current["session_id"]:
            return
        version = connection.execute(
            "SELECT event_count FROM learning_stream_head WHERE owner_id=? AND aggregate_type='action' AND aggregate_id=?",
            (principal.owner_id, current["action_id"]),
        ).fetchone()[0]
        self.learning.core.execute_in_transaction(connection, principal, RecordVerificationArtifact(
            submission_id=submission["id"], expected_version=version,
        ), f"verification-artifact:{submission['id']}")

    def link_legacy_submissions(self, identity):
        principal = self.learning.principal(identity)
        with self.learning.database.transaction(immediate=True) as connection:
            for submission in connection.execute(
                "SELECT * FROM learning_verification_submission WHERE owner_id=? AND artifact_id IS NULL AND purged_at IS NULL",
                (principal.owner_id,),
            ).fetchall():
                current = self._owned(principal.owner_id, submission["verification_id"])
                self._link_submission(connection, principal, current, submission)

    def _check_contract(self, owner_id: str, current: dict[str, Any]) -> None:
        _, delegation, _, _, _ = self._owned_context(
            owner_id, current["action_id"], current["delegation_id"], current["session_id"],
        )
        if delegation["contract_version"] != json.loads(current["contract_snapshot_json"])["version"]:
            raise DomainError("verification_contract_changed")

    async def submit(self, identity: dict[str, Any], verification_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Save an immutable submission before any model call."""
        try:
            return self._submit(identity, verification_id, payload)
        except sqlite3.Error as exc:
            raise DomainError("storage_failure", 503) from exc

    def _submit(self, identity: dict[str, Any], verification_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        principal = self.learning.principal(identity)
        current = self._owned(principal.owner_id, verification_id)
        responses = payload.get("responses") or {}
        material = (payload.get("material") or "").strip()
        work = (payload.get("learner_work") or "").strip()
        if current["purged_at"]:
            raise DomainError("artifact_not_eligible", 409)
        if current["mode"] == "ai_challenge":
            questions = json.loads(current["answer_key_json"])["questions"]
            if not all(isinstance(responses.get(q["id"]), str) and responses[q["id"]].strip() for q in questions):
                raise DomainError("verification_response_required")
            submitted = {"responses": {q["id"]: responses[q["id"]].strip() for q in questions}}
        else:
            if not material and not work:
                raise DomainError("verification_material_required")
            submitted = {"material": material, **({"learner_work": work} if work else {})}
        submitted["evidence_condition"] = payload.get("evidence_condition", "with_materials")
        request_key = payload["request_key"]
        fingerprint = digest(submitted)
        with self.learning.database.transaction(immediate=True) as connection:
            existing = connection.execute(
                "SELECT * FROM learning_verification_submission WHERE owner_id=? AND verification_id=? AND request_key=?",
                (principal.owner_id, verification_id, request_key),
            ).fetchone()
            if existing:
                if existing["purged_at"]:
                    raise DomainError("artifact_not_eligible", 409)
                if existing["request_fingerprint"] != fingerprint:
                    raise DomainError("idempotency_conflict")
                return self._public(self._owned(principal.owner_id, verification_id))
            current = self._owned(principal.owner_id, verification_id)
            if current["status"] == "passed":
                raise DomainError("verification_already_completed")
            self._check_contract(principal.owner_id, current)
            # Keep the original request fingerprint for retries, but never turn
            # another answer to these questions after feedback into fresh
            # independent evidence merely because the learner checks a box.
            if connection.execute("SELECT 1 FROM learning_verification_evaluation e JOIN learning_verification_submission s ON s.id=e.submission_id WHERE s.owner_id=? AND s.verification_id=? AND e.status='succeeded'", (principal.owner_id, verification_id)).fetchone():
                submitted["evidence_condition"] = "with_materials"
            submission_id, now = str(uuid4()), _now()
            connection.execute(
                """INSERT INTO learning_verification_submission
                   (id, owner_id, verification_id, request_key, request_fingerprint, content_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (submission_id, principal.owner_id, verification_id, request_key, fingerprint,
                 json.dumps(submitted, ensure_ascii=False), now),
            )
            submission = connection.execute("SELECT * FROM learning_verification_submission WHERE id=?", (submission_id,)).fetchone()
            self._link_submission(connection, principal, current, submission)
            connection.execute(
                """UPDATE learning_verification SET latest_submission_id=?, status='ready',
                   result_json=NULL, stop_condition_met=NULL, stop_condition_confirmed=0, submitted_at=?
                   WHERE owner_id=? AND id=?""",
                (submission_id, now, principal.owner_id, verification_id),
            )
            self._audit(connection, principal, "SaveVerificationSubmission", verification_id, "saved")
        return self._public(self._owned(principal.owner_id, verification_id))

    async def analyze_evidence(self, identity, verification_id):
        principal = self.learning.principal(identity)
        current = self._owned(principal.owner_id, verification_id)
        if current["purged_at"]:
            raise DomainError("artifact_not_eligible", 409)
        submission = self.learning.database.fetchone(
            "SELECT * FROM learning_verification_submission WHERE owner_id=? AND id=?",
            (principal.owner_id, current["latest_submission_id"]),
        )
        if submission is None or not submission["artifact_id"]:
            raise DomainError("verification_session_required")
        evaluation = self.learning.database.fetchone(
            "SELECT * FROM learning_verification_evaluation WHERE owner_id=? AND submission_id=? ORDER BY rowid DESC LIMIT 1",
            (principal.owner_id, submission["id"]),
        )
        if evaluation is None or evaluation["status"] != "succeeded":
            raise DomainError("verification_not_ready")
        if self.evidence is None:
            raise DomainError("verification_provider_unavailable", 503)
        result = await self.evidence.analyze(identity, submission["artifact_id"], f"verification:{submission['id']}", 1)
        with self.learning.database.transaction(immediate=True) as connection:
            connection.execute("UPDATE learning_verification_evaluation SET evidence_run_id=? WHERE id=?", (result["run"]["id"], evaluation["id"]))
        return self._public(self._owned(principal.owner_id, verification_id))

    def _audit(self, connection, principal, operation, verification_id, reason):
        connection.execute(
            "INSERT INTO learning_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), principal.owner_id, principal.actor_id, operation,
             "rejected" if reason in {"evaluation_failed", "cancelled"} else "succeeded",
             verification_id, reason, _now()),
        )

    async def evaluate(self, identity: dict[str, Any], verification_id: str, submission_id: str, request_key: str) -> dict[str, Any]:
        principal = self.learning.principal(identity)
        with self.learning.database.transaction(immediate=True) as connection:
            current = self._owned(principal.owner_id, verification_id)
            if current["purged_at"]:
                raise DomainError("artifact_not_eligible", 409)
            if current["latest_submission_id"] != submission_id:
                raise DomainError("verification_state_conflict")
            submission = connection.execute(
                "SELECT * FROM learning_verification_submission WHERE owner_id=? AND id=? AND verification_id=?",
                (principal.owner_id, submission_id, verification_id),
            ).fetchone()
            if submission is None:
                raise DomainError("not_found", 404)
            submitted = submission_content(connection, principal.owner_id, submission)
            repeated = connection.execute(
                "SELECT 1 FROM learning_verification_evaluation WHERE owner_id=? AND submission_id=? AND request_key=?",
                (principal.owner_id, submission_id, request_key),
            ).fetchone()
            if repeated:
                return self._public(current)
            previous = connection.execute(
                "SELECT * FROM learning_verification_evaluation WHERE owner_id=? AND submission_id=? ORDER BY rowid DESC LIMIT 1",
                (principal.owner_id, submission_id),
            ).fetchone()
            # Successful evaluations are immutable. Retrying them never calls a model.
            if previous and (previous["status"] == "succeeded" or previous["request_key"] == request_key):
                return self._public(current)
            if current["status"] == "passed":
                return self._public(current)
            self._check_contract(principal.owner_id, current)
            evaluation_id, now = str(uuid4()), _now()
            # An explicit retry supersedes an interrupted request; its late result is ignored.
            connection.execute(
                """UPDATE learning_verification_evaluation SET status='failed', reason='superseded', finished_at=?
                   WHERE owner_id=? AND submission_id=? AND status='running'""",
                (now, principal.owner_id, submission_id),
            )
            connection.execute(
                """INSERT INTO learning_verification_evaluation
                   (id, owner_id, submission_id, request_key, status, created_at)
                   VALUES (?, ?, ?, ?, 'running', ?)""",
                (evaluation_id, principal.owner_id, submission_id, request_key, now),
            )
        result, reason = None, None
        try:
            profile, config = self._runtime(principal.owner_id, current["session_id"])
            snapshot = {"model": config.model, "provider_kind": config.provider_kind,
                        "provider_profile_id": profile.get("id"), "provider_config_version": profile.get("config_version"),
                        "timeout_seconds": config.timeout_seconds, "verification_prompt_schema_version": 4}
            with self.learning.database.transaction(immediate=True) as connection:
                connection.execute(
                    "UPDATE learning_verification_evaluation SET provider_snapshot_json=? WHERE id=?",
                    (json.dumps(snapshot), evaluation_id),
                )
            provider = build_provider(config, transport=self.transport)
            prompt = {
                "task": "评估本次作答：先针对每道题给出反馈与建议，再总结整个验证。必须返回 question_feedback、passed、stop_condition_met、feedback、next_step。",
                "question_feedback_schema": [{"question_id": "题目原 id；用户材料使用 material", "feedback": "该题反馈",
                    "reference_answer": "面向学习者的参考解法，不是隐藏评分依据", "follow_up_questions": ["可选拓展问题"],
                    "unmet_requirements": ["未达到的本次原有必需条件；满足时为空数组"]}],
                "stop_conditions": json.loads(current["contract_snapshot_json"])["stop_conditions"],
                "questions": json.loads(current["challenge_json"]).get("questions", []) or [{"id": "material", "prompt": "本次材料验证"}],
                "answer_key": json.loads(current["answer_key_json"]),
                "learner_response": submitted,
                "instructions": [
                    "passed 和 stop_condition_met 必须是布尔值；feedback 和 next_step 必须是文本。",
                    "question_feedback 必填，按 questions 中的原 id 逐题返回，完整覆盖所有题目且不重复。每题 feedback 必须具体回应该题作答，说明正确之处、问题和可操作的改进建议，不能留空或用整次总结代替。",
                    "先完成逐题分析，再在顶层 feedback 总结整次验证，在 next_step 给出整体下一步；不得输出隐藏评分依据、内部推理或无关私人资料。",
                    "reference_answer 是供提交后学习使用的解释性参考解法，不直接复制 answer_key 中的评分指令。",
                    "区分原停止条件与可选拓展；若 unmet_requirements 不为空，passed 与 stop_condition_met 必须为 false。不得临时提高通过门槛。",
                    "用户材料中的标准答案本身不是能力证据；只评价用户过程、理解或项目结果。",
                ],
            }
            async with asyncio.timeout(config.timeout_seconds):
                text = await provider.generate_text([
                    {"role": "system", "content": "你是 Nautilus 的独立验证评估器。当前作答已提交，可以提供面向学习者的解释性参考解法；不得复制隐藏评分指令或输出内部推理。只输出 JSON。"},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ], max_tokens=8192, json_mode=True)
            evaluation = json.loads(_clean_json(text))
            if (not isinstance(evaluation, dict)
                or set(evaluation) != {"passed", "stop_condition_met", "feedback", "next_step", "question_feedback"}
                or any(not isinstance(evaluation.get(key), bool) for key in ("passed", "stop_condition_met"))
                or any(not isinstance(evaluation.get(key), str) or not evaluation[key].strip() for key in ("feedback", "next_step"))):
                raise ValueError("invalid verification result")
            result = {**evaluation, "feedback": evaluation["feedback"][:4000], "next_step": evaluation["next_step"][:1000]}
            if "question_feedback" in result:
                expected = {q["id"] for q in json.loads(current["challenge_json"]).get("questions", [])} or {"material"}
                feedback = result["question_feedback"]
                if not isinstance(feedback, list) or len(feedback) != len(expected):
                    raise ValueError("invalid question feedback")
                seen = set()
                for item in feedback:
                    if not isinstance(item, dict) or set(item) != {"question_id", "feedback", "reference_answer", "follow_up_questions", "unmet_requirements"}:
                        raise ValueError("invalid question feedback")
                    qid = item["question_id"]
                    if not isinstance(qid, str) or qid not in expected or qid in seen:
                        raise ValueError("invalid feedback question")
                    seen.add(qid)
                    for key in ("feedback", "reference_answer"):
                        if not isinstance(item[key], str) or len(item[key]) > 6000:
                            raise ValueError("invalid feedback text")
                    if not item["feedback"].strip():
                        raise ValueError("empty question feedback")
                    for key in ("follow_up_questions", "unmet_requirements"):
                        if not isinstance(item[key], list) or len(item[key]) > 5 or any(not isinstance(v, str) or len(v) > 1000 for v in item[key]):
                            raise ValueError("invalid feedback list")
                    if item["unmet_requirements"]:
                        result.update(passed=False, stop_condition_met=False)
            if current["mode"] == "user_material" and not learner_content(submitted):
                result.update(passed=False, stop_condition_met=False,
                              feedback="材料已保存；请另行提供自己的过程、理解或项目结果，参考答案本身不能证明完成验证。")
        except asyncio.CancelledError:
            self._finish_evaluation(principal, current, submission_id, evaluation_id, None, "cancelled")
            raise
        except (ConversationError, ProviderError, TimeoutError, ValueError) as exc:
            result = None
            reason = _failure_code(exc)
        self._finish_evaluation(principal, current, submission_id, evaluation_id, result, reason)
        return self._public(self._owned(principal.owner_id, verification_id))

    def _finish_evaluation(self, principal, current, submission_id, evaluation_id, result, reason):
        with self.learning.database.transaction(immediate=True) as connection:
            changed = connection.execute(
                """UPDATE learning_verification_evaluation SET status=?, result_json=?, reason=?, finished_at=?
                   WHERE owner_id=? AND id=? AND status='running'""",
                ("succeeded" if result else "failed", json.dumps(result, ensure_ascii=False) if result else None,
                 reason, _now(), principal.owner_id, evaluation_id),
            ).rowcount
            if changed:
                connection.execute(
                    """UPDATE learning_verification SET status=?, result_json=?, stop_condition_met=?
                       WHERE owner_id=? AND id=? AND latest_submission_id=? AND status <> 'passed'""",
                    ("submitted" if result and result["passed"] else "failed",
                     json.dumps(result, ensure_ascii=False) if result else None,
                     int(result["stop_condition_met"]) if result else None,
                     principal.owner_id, current["id"], submission_id),
                )
                self._audit(connection, principal, "EvaluateVerification", current["id"], reason or "evaluated")

    def confirm(self, identity: dict[str, Any], verification_id: str, submission_id: str, evaluation_id: str) -> dict[str, Any]:
        try:
            return self._confirm(identity, verification_id, submission_id, evaluation_id)
        except sqlite3.Error as exc:
            raise DomainError("storage_failure", 503) from exc

    def _confirm(self, identity: dict[str, Any], verification_id: str, submission_id: str, evaluation_id: str) -> dict[str, Any]:
        principal = self.learning.principal(identity)
        with self.learning.database.transaction(immediate=True) as connection:
            current = self._owned(principal.owner_id, verification_id)
            if current["purged_at"]:
                raise DomainError("artifact_not_eligible", 409)
            evaluation = connection.execute(
                """SELECT * FROM learning_verification_evaluation
                   WHERE owner_id=? AND submission_id=? ORDER BY rowid DESC LIMIT 1""",
                (principal.owner_id, submission_id),
            ).fetchone()
            if (current["latest_submission_id"] != submission_id or evaluation is None
                or evaluation["id"] != evaluation_id or evaluation["status"] != "succeeded"):
                raise DomainError("verification_state_conflict")
            if not evaluation["result_json"]:
                raise DomainError("artifact_not_eligible", 409)
            result = json.loads(evaluation["result_json"])
            if not result["passed"] or not result["stop_condition_met"]:
                raise DomainError("verification_not_ready")
            if current["status"] == "passed":
                return self._public(current)
            submission = connection.execute(
                "SELECT * FROM learning_verification_submission WHERE owner_id=? AND id=?",
                (principal.owner_id, submission_id),
            ).fetchone()
            submitted = submission_content(connection, principal.owner_id, submission)
            if current["mode"] == "user_material" and not learner_content(submitted):
                raise DomainError("verification_learner_work_required")
            self._check_contract(principal.owner_id, current)
            version = connection.execute(
                "SELECT event_count FROM learning_stream_head WHERE owner_id=? AND aggregate_type='action' AND aggregate_id=?",
                (principal.owner_id, current["action_id"]),
            ).fetchone()["event_count"]
            self.learning.core.execute_in_transaction(connection, principal, CompleteLearningAction(
                action_id=current["action_id"], delegation_id=current["delegation_id"], expected_version=version,
            ), f"verification-complete:{verification_id}")
            connection.execute(
                "UPDATE learning_verification SET status='passed', stop_condition_confirmed=1 WHERE owner_id=? AND id=?",
                (principal.owner_id, verification_id),
            )
            self._audit(connection, principal, "ConfirmVerification", verification_id, "confirmed")
            from .continuity import record_usage
            action_status = connection.execute("SELECT status FROM learning_action WHERE owner_id=? AND id=?", (principal.owner_id, current["action_id"])).fetchone()[0]
            if action_status == "completed":
                for start in connection.execute("SELECT * FROM learning_usage_event WHERE owner_id=? AND kind='started' AND action_id=?", (principal.owner_id, current["action_id"])).fetchall():
                    record_usage(connection, principal.owner_id, "completed", f"completion:{start['review_id']}:{verification_id}", review_id=start["review_id"], action_id=current["action_id"], delegation_id=current["delegation_id"], session_id=current["session_id"])

        return self._public(self._owned(principal.owner_id, verification_id))

    def list(self, identity: dict[str, Any]) -> list[dict[str, Any]]:
        principal = self.learning.principal(identity)
        return [
            self._public(dict(row))
            for row in self.learning.database.fetchall(
                "SELECT * FROM learning_verification WHERE owner_id=? ORDER BY created_at DESC, id",
                (principal.owner_id,),
            )
        ]

    def purge(self, identity, verification_id):
        try:
            return self._purge(identity, verification_id)
        except sqlite3.Error as exc:
            raise DomainError("storage_failure", 503) from exc

    def _purge(self, identity, verification_id):
        principal = self.learning.principal(identity)
        with self.learning.database.transaction(immediate=True) as connection:
            current = self._owned(principal.owner_id, verification_id)
            if current["purged_at"]:
                return self._public(current)
            now = _now()
            for submission in connection.execute(
                "SELECT * FROM learning_verification_submission WHERE owner_id=? AND verification_id=?",
                (principal.owner_id, verification_id),
            ).fetchall():
                if submission["artifact_id"] and not submission["purged_at"]:
                    version = connection.execute(
                        "SELECT event_count FROM learning_stream_head WHERE owner_id=? AND aggregate_type='action' AND aggregate_id=?",
                        (principal.owner_id, current["action_id"]),
                    ).fetchone()[0]
                    self.learning.core.execute_in_transaction(connection, principal, PurgeArtifact(
                        artifact_id=submission["artifact_id"], expected_version=version, confirmation="PURGE",
                    ), f"verification-purge:{submission['id']}")
            connection.execute(
                "UPDATE learning_verification_submission SET purged_at=?, content_json='{}' WHERE owner_id=? AND verification_id=?",
                (now, principal.owner_id, verification_id),
            )
            connection.execute(
                """UPDATE learning_verification_evaluation SET result_json=NULL, status=CASE WHEN status='running' THEN 'failed' ELSE status END,
                   reason='content_purged', finished_at=COALESCE(finished_at, ?) WHERE owner_id=? AND submission_id IN
                   (SELECT id FROM learning_verification_submission WHERE owner_id=? AND verification_id=?)""",
                (now, principal.owner_id, principal.owner_id, verification_id),
            )
            connection.execute(
                """UPDATE learning_verification SET purged_at=?, answer_key_json='{}', challenge_json='{}',
                   submission_json=NULL, result_json=NULL, contract_snapshot_json='{"version":0,"stop_conditions":""}'
                   WHERE owner_id=? AND id=?""", (now, principal.owner_id, verification_id),
            )
            self._audit(connection, principal, "PurgeVerification", verification_id, "content_purged")
            from .state_derivation import StateDerivationService
            from .evidence_events import EvidenceEventService
            state = StateDerivationService(self.learning, EvidenceEventService(self.learning.database))
            for criterion in connection.execute(
                """SELECT DISTINCT c.criterion_id FROM learning_evidence_claim c
                   JOIN learning_verification_submission s ON s.owner_id=c.owner_id AND s.artifact_id=c.artifact_id
                   WHERE s.owner_id=? AND s.verification_id=?""", (principal.owner_id, verification_id),
            ).fetchall():
                state.derive(identity, criterion[0], connection=connection)
        return self._public(self._owned(principal.owner_id, verification_id))
