from __future__ import annotations

import inspect
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .conversations import ConversationError, ConversationService
from .evidence_provider import EvidenceProviderService
from .learning_domain import CriterionRecipe, DomainError, Principal
from .learning_service import LearningService
from .providers import ProviderError, build_provider
from .verification_content import submission_content, learner_content


class AnalysisError(RuntimeError):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


class ModelObservationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimension_id: str = Field(min_length=1, max_length=100)
    stance: str = Field(pattern=r"^(supports|refutes|insufficient)$")
    statement: str = Field(min_length=1, max_length=4000)
    scope: str = Field(min_length=1, max_length=500)


class EvidenceClaimDraft(ModelObservationDraft):
    """Internal execution result; never used as the Provider output schema."""
    source: str
    verification_method: str
    evidence_condition: str
    provenance_json: str | None = None


Analyzer = Callable[[dict[str, Any]], list[ModelObservationDraft]]
SemanticAnalyzer = Callable[[dict[str, Any]], list[ModelObservationDraft] | Any]

_SOURCE_TO_METHOD = {
    "ai_analysis": "semantic_analysis",
    "human_review": "independent_review",
    "deterministic_check": "deterministic_check",
}

_FAILURE_STATUSES = {
    "provider_unavailable": ("failed", "provider_unavailable"),
    "timeout": ("timeout", "analysis_timeout"),
    "cancelled": ("cancelled", "analysis_cancelled"),
    "invalid_output": ("invalid_output", "analysis_output_invalid"),
    "permission_denied": ("permission_denied", "analysis_permission_denied"),
    "internal_error": ("failed", "internal_error"),
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class RegexDeterministicAnalyzer:
    """First-slice deterministic analyzer for the approved regex standard."""

    def __call__(self, request: dict[str, Any]) -> list[ModelObservationDraft]:
        lines = str(request["content"]).splitlines()
        pattern = next(
            (line.removeprefix("regex:").strip() for line in lines if line.startswith("regex:")),
            None,
        )
        sample = next(
            (line.removeprefix("sample:").strip() for line in lines if line.startswith("sample:")),
            None,
        )
        if not pattern or not sample:
            raise AnalysisError(
                "invalid_output",
                "产出必须同时包含 regex: 和 sample: 两行，才能执行确定性检查",
            )
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise AnalysisError("invalid_output", "正则表达式语法无效") from exc
        if compiled.search(sample) is None:
            raise AnalysisError("invalid_output", "正则表达式未匹配示例文本")

        return [
            ModelObservationDraft(
                dimension_id="application",
                stance="supports",
                statement="确定性检查通过：该正则表达式在示例文本中匹配成功。",
                scope="artifact",
            )
        ]


class ProviderSemanticAnalyzer:
    """Provider-backed semantic analysis boundary for evidence claims."""

    def __init__(
        self,
        conversations: ConversationService,
        transport: httpx.AsyncBaseTransport | None = None,
        provider_service: EvidenceProviderService | None = None,
    ) -> None:
        self.conversations = conversations
        self.transport = transport
        self.provider_service = provider_service

    async def __call__(self, request: dict[str, Any]) -> list[ModelObservationDraft]:
        try:
            if self.provider_service is None:
                _profile, config = self.conversations.provider_runtime(request["identity_id"])
            else:
                _profile, config, snapshot = self.provider_service.runtime_details(
                    request["identity_id"]
                )
                request["provider_snapshot"] = snapshot
        except ConversationError as exc:
            raise AnalysisError("provider_unavailable", "尚未配置可用的 AI 提供方") from exc

        prompt = {
            "task": "Evaluate the syntax_semantics dimension of the learner artifact.",
            "standard": request["recipe"],
            "artifact": request["content"],
            "output_schema": {
                "dimension_id": "syntax_semantics",
                "stance": "supports | refutes | insufficient",
                "statement": "A concise evidence statement grounded only in the artifact.",
                "scope": "artifact",
            },
            "constraints": [
                "Return one JSON object only.",
                "Do not invent facts not present in the artifact.",
                "Do not return markdown or commentary.",
            ],
        }
        messages = [
            {
                "role": "system",
                "content": "You are a strict learning-evidence analyzer. Return valid JSON only.",
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
        try:
            provider = build_provider(config, transport=self.transport)
            text = await provider.generate_text(messages, max_tokens=800)
        except TimeoutError as exc:
            raise AnalysisError("timeout", "语义分析请求超时") from exc
        except ProviderError as exc:
            if exc.kind == "timeout":
                raise AnalysisError("timeout", "语义分析请求超时") from exc
            if exc.kind == "auth_error":
                raise AnalysisError("permission_denied", "AI 提供方认证失败") from exc
            if exc.kind in {"protocol_error", "invalid_response", "output_limit"}:
                raise AnalysisError("invalid_output", "语义分析输出不合格") from exc
            raise AnalysisError("provider_unavailable", "AI 提供方当前不可用") from exc

        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise AnalysisError("invalid_output", "语义分析输出不是有效 JSON") from exc
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list) or not parsed:
            raise AnalysisError("invalid_output", "语义分析输出为空")
        try:
            return [ModelObservationDraft.model_validate(item) for item in parsed]
        except Exception as exc:
            raise AnalysisError("invalid_output", "语义分析输出结构不合格") from exc


class EvidenceService:
    """Application boundary for evidence analysis and candidate claims."""

    def __init__(
        self,
        learning: LearningService,
        analyzer: Analyzer | None = None,
        semantic_analyzer: SemanticAnalyzer | None = None,
        evidence_events: Any | None = None,
    ):
        self.learning = learning
        self.database = learning.database
        self.analyzer = analyzer or RegexDeterministicAnalyzer()
        self.semantic_analyzer = semantic_analyzer
        self.evidence_events = evidence_events

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

    def _artifact(self, principal: Principal, artifact_id: str, content_version: int | None) -> dict[str, Any]:
        version_filter = ""
        params: list[object] = [principal.owner_id, artifact_id]
        if content_version is not None:
            version_filter = " AND raw.content_version=?"
            params.append(content_version)

        row = self.database.fetchone(
            f"""
            SELECT raw.artifact_id, raw.content_version, raw.fact_event_id, raw.content,
                   raw.purged_at, s.delegation_id, d.action_id, d.outcome_id, contract.criterion_id
            FROM learning_raw_artifact AS raw
            JOIN learning_session AS s
              ON s.owner_id=raw.owner_id AND s.id=raw.session_id
            JOIN learning_delegation AS d
              ON d.owner_id=s.owner_id AND d.id=s.delegation_id
            JOIN learning_contract_version AS contract
              ON contract.owner_id=s.owner_id AND contract.delegation_id=s.delegation_id AND contract.version=s.contract_version
            WHERE raw.owner_id=? AND raw.artifact_id=?{version_filter}
            ORDER BY raw.content_version DESC
            LIMIT 1
            """,
            tuple(params),
        )
        if row is None:
            raise DomainError("not_found", 404)
        artifact = dict(row)
        submission = self.database.fetchone(
            "SELECT * FROM learning_verification_submission WHERE owner_id=? AND artifact_id=?",
            (principal.owner_id, artifact_id),
        )
        if submission:
            if artifact["content_version"] != 1:
                raise DomainError("artifact_not_eligible", 409)
            content = submission_content(self.database.connection, principal.owner_id, submission)
            artifact["content"] = learner_content(content)
            artifact["evidence_condition"] = content.get("evidence_condition", "with_materials")
            artifact["verification_submission_id"] = submission["id"]
        return artifact

    def _existing_blocked_run(self, principal: Principal, artifact: dict[str, Any]) -> dict[str, Any] | None:
        row = self.database.fetchone(
            """SELECT * FROM learning_analysis_run
               WHERE owner_id=? AND artifact_id=? AND content_version=? AND status='blocked_no_criterion'
               ORDER BY attempt DESC LIMIT 1""",
            (
                principal.owner_id,
                artifact["artifact_id"],
                artifact["content_version"],
            ),
        )
        return dict(row) if row else None

    def _ensure_eligible(self, principal, artifact):
        current = self.database.fetchone(
            "SELECT visibility, evidence_status, content_version FROM learning_artifact WHERE owner_id=? AND id=?",
            (principal.owner_id, artifact["artifact_id"]),
        )
        if current is None or current["visibility"] != "visible" or current["evidence_status"] != "eligible" or current["content_version"] != artifact["content_version"]:
            raise DomainError("artifact_not_eligible", 409)
        if self.database.fetchone(
            "SELECT 1 FROM learning_criterion_availability WHERE owner_id=? AND criterion_id=?",
            (principal.owner_id, artifact["criterion_id"]),
        ):
            raise DomainError("criterion_unavailable", 409)

    def _create_blocked_run(
        self, principal: Principal, artifact: dict[str, Any], request_key: str
    ) -> dict[str, Any]:
        run_id = str(uuid4())
        now = utc_timestamp()
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO learning_analysis_run
                   (id, owner_id, artifact_id, content_version, fact_event_id, criterion_id,
                    request_key, attempt, status, reason, created_at, finished_at)
                   VALUES (?, ?, ?, ?, ?, NULL, ?, 1, 'blocked_no_criterion',
                           'no approved criterion', ?, ?)""",
                (
                    run_id,
                    principal.owner_id,
                    artifact["artifact_id"],
                    artifact["content_version"],
                    artifact["fact_event_id"],
                    request_key,
                    now,
                    now,
                ),
            )
            self._audit(
                connection,
                principal,
                "AnalyzeEvidence",
                "rejected",
                run_id,
                "blocked_no_criterion",
            )
        row = self.database.fetchone(
            "SELECT * FROM learning_analysis_run WHERE owner_id=? AND id=?",
            (principal.owner_id, run_id),
        )
        return dict(row)

    def _validate_claims(
        self, recipe: CriterionRecipe, claims: list[EvidenceClaimDraft]
    ) -> None:
        if not claims:
            raise AnalysisError("invalid_output", "分析结果没有生成任何候选主张")
        dimensions = {dimension.id: dimension for dimension in recipe.dimensions}
        for claim in claims:
            dimension = dimensions.get(claim.dimension_id)
            if dimension is None:
                raise AnalysisError("invalid_output", "候选主张引用了不存在的验收维度")
            method = _SOURCE_TO_METHOD[claim.source]
            if not any(
                requirement.method == method
                for requirement in dimension.requirements
            ):
                raise AnalysisError(
                    "invalid_output",
                    "候选主张的来源或独立条件不符合标准配方",
                )

    async def _collect_drafts(
        self,
        principal: Principal,
        artifact: dict[str, Any],
        recipe: CriterionRecipe,
        context_key: str,
    ) -> tuple[list[EvidenceClaimDraft], dict[str, Any] | None]:
        request = {
            "identity_id": principal.owner_id,
            "content": artifact["content"],
            "criterion_id": artifact["criterion_id"],
            "context_key": context_key,
            "recipe": recipe.model_dump(mode="json"),
        }
        drafts: list[EvidenceClaimDraft] = []
        condition = artifact.get("evidence_condition", "with_materials")
        condition_basis = "user_self_report" if artifact.get("verification_submission_id") else "unobserved"

        def bind(observations, source, method, executor):
            for item in observations:
                # Injected in-process analyzers are also unable to promote their source.
                fields = item.model_dump() if isinstance(item, BaseModel) else item
                observation = ModelObservationDraft.model_validate({key: fields[key] for key in ModelObservationDraft.model_fields})
                provenance = dict(source=source, verification_method=method,
                    evidence_condition=condition, condition_basis=condition_basis,
                    executor_kind=executor, executor_version="1", observed_at=utc_timestamp())
                drafts.append(EvidenceClaimDraft(**observation.model_dump(), source=source,
                    verification_method=method, evidence_condition=condition,
                    provenance_json=json.dumps(provenance, sort_keys=True)))

        if self.semantic_analyzer is not None:
            semantic_result = self.semantic_analyzer(request)
            if inspect.isawaitable(semantic_result):
                semantic_result = await semantic_result
            bind(semantic_result, "ai_analysis", "semantic_analysis", "provider_semantic")
        bind(self.analyzer(request), "deterministic_check", "python_re_search", "regex_deterministic")
        self._validate_claims(recipe, drafts)
        return drafts, request.get("provider_snapshot")

    async def analyze(
        self,
        identity: dict[str, Any],
        artifact_id: str,
        request_key: str,
        content_version: int | None = None,
    ) -> dict[str, Any]:
        principal = self.learning.principal(identity)
        artifact = self._artifact(principal, artifact_id, content_version)
        if artifact["purged_at"] is not None:
            raise DomainError("artifact_not_eligible", 409)

        if artifact["criterion_id"] is None:
            existing = self._existing_blocked_run(principal, artifact)
            run = existing or self._create_blocked_run(
                principal,
                artifact,
                f"{artifact['artifact_id']}:{artifact['content_version']}:{request_key}",
            )
            return {"run": run, "claims": [], "created": existing is None}
        if artifact.get("verification_submission_id") and not artifact["content"]:
            raise DomainError("verification_learner_work_required", 409)
        self._ensure_eligible(principal, artifact)

        criterion = self.database.fetchone(
            """SELECT recipe_json, context_key FROM learning_criterion_version
               WHERE owner_id=? AND id=? AND review_status='approved'""",
            (principal.owner_id, artifact["criterion_id"]),
        )
        if criterion is None:
            raise DomainError("criterion_not_approved", 409)
        try:
            recipe = CriterionRecipe.model_validate_json(criterion["recipe_json"])
        except Exception as exc:
            raise DomainError("criterion_invalid_recipe", 409) from exc
        if artifact.get("verification_submission_id") and artifact["evidence_condition"] != "independent":
            raise DomainError("verification_independent_evidence_required", 409)

        composite_key = f"{artifact['artifact_id']}:{artifact['content_version']}:{request_key}"
        latest = self.database.fetchone(
            """SELECT * FROM learning_analysis_run
               WHERE owner_id=? AND request_key=?
               ORDER BY attempt DESC LIMIT 1""",
            (principal.owner_id, composite_key),
        )
        if latest is not None and latest["status"] == "succeeded":
            claims = self._claims_for_run(principal.owner_id, latest["id"])
            return {"run": dict(latest), "claims": claims, "created": False}
        if latest is not None and latest["status"] in {"queued", "running"}:
            return {"run": dict(latest), "claims": [], "created": False}

        attempt = (latest["attempt"] + 1) if latest is not None else 1
        run_id = str(uuid4())
        now = utc_timestamp()

        try:
            drafts, provider_snapshot = await self._collect_drafts(
                principal,
                artifact,
                recipe,
                criterion["context_key"],
            )
        except AnalysisError as exc:
            status, reason = _FAILURE_STATUSES.get(
                exc.kind, ("failed", "internal_error")
            )
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    """INSERT INTO learning_analysis_run
                       (id, owner_id, artifact_id, content_version, fact_event_id, criterion_id,
                        request_key, attempt, status, reason, created_at, finished_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        principal.owner_id,
                        artifact["artifact_id"],
                        artifact["content_version"],
                        artifact["fact_event_id"],
                        artifact["criterion_id"],
                        composite_key,
                        attempt,
                        status,
                        reason,
                        now,
                        utc_timestamp(),
                    ),
                )
                self._audit(
                    connection,
                    principal,
                    "AnalyzeEvidence",
                    "rejected",
                    run_id,
                    reason,
                )
            row = self.database.fetchone(
                "SELECT * FROM learning_analysis_run WHERE owner_id=? AND id=?",
                (principal.owner_id, run_id),
            )
            return {"run": dict(row), "claims": [], "created": True}

        with self.database.transaction(immediate=True) as connection:
            self._ensure_eligible(principal, artifact)
            connection.execute(
                """INSERT INTO learning_analysis_run
                   (id, owner_id, artifact_id, content_version, fact_event_id, criterion_id,
                    request_key, attempt, status, reason, created_at, finished_at,
                    provider_selection_source, provider_profile_id, provider_model_id,
                    provider_model, provider_kind, provider_config_version,
                    provider_timeout_seconds, analysis_prompt_schema_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'succeeded', NULL, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    principal.owner_id,
                    artifact["artifact_id"],
                    artifact["content_version"],
                    artifact["fact_event_id"],
                    artifact["criterion_id"],
                    composite_key,
                    attempt,
                    now,
                    utc_timestamp(),
                    provider_snapshot.get("selection_source") if provider_snapshot else None,
                    provider_snapshot.get("provider_profile_id") if provider_snapshot else None,
                    provider_snapshot.get("provider_model_id") if provider_snapshot else None,
                    provider_snapshot.get("model") if provider_snapshot else None,
                    provider_snapshot.get("provider_kind") if provider_snapshot else None,
                    provider_snapshot.get("provider_config_version") if provider_snapshot else None,
                    provider_snapshot.get("timeout_seconds") if provider_snapshot else None,
                    provider_snapshot.get("analysis_prompt_schema_version") if provider_snapshot else None,
                ),
            )
            new_claim_ids: list[str] = []
            for draft in drafts:
                claim_id = str(uuid4())
                new_claim_ids.append(claim_id)
                created_at = utc_timestamp()
                connection.execute(
                    """INSERT INTO learning_evidence_claim
                       (id, owner_id, artifact_id, content_version, fact_event_id, criterion_id,
                        dimension_id, stance, status, source, statement, verification_method,
                        evidence_condition, scope, analysis_run_id, created_at, provenance_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        claim_id,
                        principal.owner_id,
                        artifact["artifact_id"],
                        artifact["content_version"],
                        artifact["fact_event_id"],
                        artifact["criterion_id"],
                        draft.dimension_id,
                        draft.stance,
                        draft.source,
                        draft.statement,
                        draft.verification_method,
                        draft.evidence_condition,
                        draft.scope,
                        run_id,
                        created_at,
                        draft.provenance_json,
                    ),
                )
                if self.evidence_events is not None:
                    self.evidence_events.append(
                        principal.owner_id,
                        "claim",
                        claim_id,
                        "claim.created",
                        {
                            "id": claim_id,
                            "artifact_id": artifact["artifact_id"],
                            "content_version": artifact["content_version"],
                            "fact_event_id": artifact["fact_event_id"],
                            "criterion_id": artifact["criterion_id"],
                            "dimension_id": draft.dimension_id,
                            "stance": draft.stance,
                            "status": "candidate",
                            "source": draft.source,
                            "provenance_json": draft.provenance_json,
                            "statement": draft.statement,
                            "verification_method": draft.verification_method,
                            "evidence_condition": draft.evidence_condition,
                            "scope": draft.scope,
                            "analysis_run_id": run_id,
                            "created_at": created_at,
                        },
                        connection=connection,
                    )

            for claim_id in new_claim_ids:
                new_claim = connection.execute(
                    """SELECT dimension_id FROM learning_evidence_claim
                       WHERE owner_id=? AND id=?""",
                    (principal.owner_id, claim_id),
                ).fetchone()
                superseded_claims = connection.execute(
                    """SELECT old_claim.id
                       FROM learning_evidence_claim AS old_claim
                       LEFT JOIN learning_claim_replacement AS existing
                         ON existing.owner_id=old_claim.owner_id
                        AND existing.superseded_claim_id=old_claim.id
                       WHERE old_claim.owner_id=?
                         AND old_claim.artifact_id=?
                         AND old_claim.content_version<?
                         AND old_claim.criterion_id=?
                         AND old_claim.dimension_id=?
                         AND old_claim.status='superseded'
                         AND existing.id IS NULL""",
                    (
                        principal.owner_id,
                        artifact["artifact_id"],
                        artifact["content_version"],
                        artifact["criterion_id"],
                        new_claim["dimension_id"],
                    ),
                ).fetchall()
                for old_claim in superseded_claims:
                    replacement_id = str(uuid4())
                    replaced_at = utc_timestamp()
                    connection.execute(
                        """INSERT INTO learning_claim_replacement
                           (id, owner_id, superseded_claim_id, replacement_claim_id,
                            reason, created_at)
                           VALUES (?, ?, ?, ?, 'artifact corrected', ?)""",
                        (
                            replacement_id,
                            principal.owner_id,
                            old_claim["id"],
                            claim_id,
                            replaced_at,
                        ),
                    )
                    if self.evidence_events is not None:
                        self.evidence_events.append(
                            principal.owner_id,
                            "claim",
                            old_claim["id"],
                            "claim.replaced",
                            {
                                "id": replacement_id,
                                "superseded_claim_id": old_claim["id"],
                                "replacement_claim_id": claim_id,
                                "reason": "artifact corrected",
                                "created_at": replaced_at,
                            },
                            connection=connection,
                        )

            self._audit(
                connection,
                principal,
                "AnalyzeEvidence",
                "succeeded",
                run_id,
            )

        row = self.database.fetchone(
            "SELECT * FROM learning_analysis_run WHERE owner_id=? AND id=?",
            (principal.owner_id, run_id),
        )
        return {
            "run": dict(row),
            "claims": self._claims_for_run(principal.owner_id, run_id),
            "created": True,
        }

    def _claims_for_run(self, owner_id: str, run_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.database.fetchall(
                """SELECT * FROM learning_evidence_claim
                   WHERE owner_id=? AND analysis_run_id=?
                   ORDER BY created_at, id""",
                (owner_id, run_id),
            )
        ]

    def claims(
        self,
        identity: dict[str, Any],
        artifact_id: str | None = None,
    ) -> list[dict[str, Any]]:
        principal = self.learning.principal(identity)
        sql = """SELECT * FROM learning_evidence_claim WHERE owner_id=?"""
        params: list[object] = [principal.owner_id]
        if artifact_id is not None:
            sql += " AND artifact_id=?"
            params.append(artifact_id)
        sql += " ORDER BY created_at DESC, id"
        return [dict(row) for row in self.database.fetchall(sql, tuple(params))]

    def _owned_claim(self, principal: Principal, claim_id: str) -> dict[str, Any]:
        row = self.database.fetchone(
            "SELECT * FROM learning_evidence_claim WHERE owner_id=? AND id=?",
            (principal.owner_id, claim_id),
        )
        if row is None:
            raise DomainError("not_found", 404)
        claim = dict(row)
        if claim["status"] != "candidate":
            raise DomainError("claim_not_candidate", 409)
        return claim

    def _create_follow_up(
        self,
        identity: dict[str, Any],
        claim_id: str,
        kind: str,
        request_key: str,
        note: str | None,
        due_at: str | None,
    ) -> dict[str, Any]:
        principal = self.learning.principal(identity)
        claim = self._owned_claim(principal, claim_id)
        existing = self.database.fetchone(
            """SELECT * FROM learning_evidence_follow_up
               WHERE owner_id=? AND request_key=?""",
            (principal.owner_id, request_key),
        )
        if existing is not None:
            return dict(existing)

        follow_up_id = str(uuid4())
        now = utc_timestamp()
        with self.database.transaction(immediate=True) as connection:
            self._owned_claim(principal, claim_id)
            connection.execute(
                """INSERT INTO learning_evidence_follow_up
                   (id, owner_id, claim_id, kind, status, request_key, note, due_at,
                    created_at, decided_at)
                   VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, NULL)""",
                (
                    follow_up_id,
                    principal.owner_id,
                    claim["id"],
                    kind,
                    request_key,
                    note,
                    due_at,
                    now,
                ),
            )
            if self.evidence_events is not None:
                self.evidence_events.append(
                    principal.owner_id,
                    "follow_up",
                    follow_up_id,
                    "follow_up.created",
                    {
                        "id": follow_up_id,
                        "claim_id": claim["id"],
                        "kind": kind,
                        "status": "pending",
                        "request_key": request_key,
                        "note": note,
                        "due_at": due_at,
                        "created_at": now,
                        "decided_at": None,
                    },
                    connection=connection,
                )
            self._audit(
                connection,
                principal,
                "EvidenceFollowUp",
                "succeeded",
                follow_up_id,
            )
        row = self.database.fetchone(
            "SELECT * FROM learning_evidence_follow_up WHERE owner_id=? AND id=?",
            (principal.owner_id, follow_up_id),
        )
        return dict(row)

    def request_human_review(
        self,
        identity: dict[str, Any],
        claim_id: str,
        request_key: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        return self._create_follow_up(
            identity,
            claim_id,
            "human_review",
            request_key,
            note,
            None,
        )

    def schedule_supplemental_verification(
        self,
        identity: dict[str, Any],
        claim_id: str,
        request_key: str,
        due_at: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        if due_at is None:
            due_at = (
                datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
            )
        return self._create_follow_up(
            identity,
            claim_id,
            "supplemental_verification",
            request_key,
            note,
            due_at,
        )

    def follow_ups(self, identity: dict[str, Any]) -> list[dict[str, Any]]:
        principal = self.learning.principal(identity)
        return [
            dict(row)
            for row in self.database.fetchall(
                """SELECT * FROM learning_evidence_follow_up
                   WHERE owner_id=?
                   ORDER BY created_at DESC, id""",
                (principal.owner_id,),
            )
        ]
