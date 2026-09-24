from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .conversations import ConversationError, ConversationService
from .core.commands import ConfirmLearningSetup
from .core.events import digest
from .continuity import record_usage
from .learning_domain import DomainError
from .learning_service import LearningService
from .providers import ProviderError, build_provider


SETUP_MAX_TOKENS = 8192
SETUP_FAILURE_MESSAGES = {
    "setup_provider_unavailable": "当前默认 AI 提供方或模型不可用，请检查提供方设置。",
    "setup_timeout": "生成学习安排超时，请增加提供方超时时间后重试；已完成的学习记录不受影响。",
    "setup_auth_error": "生成学习安排时被提供方拒绝访问，请检查当前默认模型的权限与 API Key。",
    "setup_rate_limited": "生成学习安排时遇到提供方限流或额度不足，请稍后重试或检查账户额度。",
    "setup_network_error": "生成学习安排时无法连接提供方，请检查网络和服务地址。",
    "setup_endpoint_not_found": "学习安排使用的接口或模型不存在，请核对默认提供方的地址和模型名称。",
    "setup_request_error": "提供方不接受学习安排请求，请检查当前模型是否支持 JSON 输出及请求参数。",
    "setup_upstream_error": "提供方在生成学习安排时发生服务错误，请稍后重试。",
    "setup_output_truncated": "AI 输出达到长度上限，学习安排被截断；请缩小这一步的范围或更换模型后重试。",
    "setup_reasoning_only": "AI 只返回了思考过程，没有最终学习安排；请重试或更换模型。",
    "setup_content_filtered": "提供方拒绝生成本次学习安排，请调整描述或改为自己安排。",
    "setup_protocol_error": "提供方响应缺少可用正文或格式不符合接口约定，请重试或检查模型兼容性。",
    "setup_invalid_json": "AI 已响应，但学习安排格式无法解析；请重试或改为自己安排。",
    "setup_draft_invalid": "AI 已响应，但学习安排缺少必要内容或字段不符合要求；请重试或改为自己安排。",
    "setup_provider_error": "学习安排的 AI 请求失败，请重试或检查默认提供方配置。",
}


class LearningSetupDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    goal_title: str = Field(min_length=1, max_length=200)
    goal_description: str = Field(max_length=1000)
    plan_title: str = Field(min_length=1, max_length=200)
    plan_description: str = Field(max_length=1000)
    action_title: str = Field(min_length=1, max_length=300)
    context_key: str = Field(min_length=1, max_length=200)
    outcome_object: str = Field(min_length=1, max_length=500)
    outcome_behavior: str = Field(min_length=1, max_length=500)
    outcome_context_key: str = Field(min_length=1, max_length=200)
    boundaries: str = Field(max_length=2000)
    stop_conditions: str = Field(min_length=1, max_length=2000)
    time_budget_minutes: int = Field(ge=1, le=1440)
    recommended_criterion_id: str | None = Field(default=None, max_length=100)
    rationale: str = Field(min_length=1, max_length=1000)


def _clean_json(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


class LearningSetupService:
    def __init__(
        self,
        learning: LearningService,
        conversations: ConversationService,
        transport=None,
    ) -> None:
        self.learning = learning
        self.conversations = conversations
        self.transport = transport

    def standards(self, owner_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.learning.database.fetchall(
                """SELECT c.id, c.outcome_id, p.title AS package_title,
                          o.object_description, o.behavior, c.context_key
                   FROM learning_criterion_version AS c
                   JOIN learning_standard_package AS p
                     ON p.owner_id=c.owner_id AND p.id=c.package_id
                   JOIN learning_outcome AS o
                     ON o.owner_id=c.owner_id AND o.id=c.outcome_id
                   LEFT JOIN learning_criterion_availability AS unavailable
                     ON unavailable.owner_id=c.owner_id AND unavailable.criterion_id=c.id
                   WHERE c.owner_id=? AND c.review_status='approved'
                     AND unavailable.criterion_id IS NULL
                   ORDER BY c.created_at DESC, c.id""",
                (owner_id,),
            )
        ]

    async def draft(self, identity: dict[str, Any], intent: str) -> dict[str, Any]:
        principal = self.learning.principal(identity)
        try:
            _profile, config = self.conversations.provider_runtime(principal.owner_id)
        except ConversationError as exc:
            raise DomainError("setup_provider_unavailable", 503) from exc

        available_standards = self.standards(principal.owner_id)
        prompt = {
            "intent": intent,
            "available_standards": available_standards,
            "instructions": [
                "把用户的学习意图整理成一次低承诺、可执行的学习步骤。若输入明确是已有目标和计划的下一步，沿用该目标和计划，不重新安排第一步。",
                "只返回符合 output_schema 的 JSON 对象，不要 Markdown。所有 required 字段都要提供，遵守类型、长度与数值范围。",
                "各字段简短表达，不要把完整教程写入草案；time_budget_minutes 必须是整数分钟。",
                "goal_title 是用户想达成的结果，action_title 是现在要执行的任务，不能混为一谈。",
                "boundaries 和 stop_conditions 必须具体、短小、适合一次学习会话。",
                "recommended_criterion_id 只能填写 available_standards 中完全匹配的 id，否则填写 null。",
                "不要声称用户已经掌握，也不要生成长期精确排期。",
            ],
            "output_schema": LearningSetupDraft.model_json_schema(),
        }
        try:
            provider = build_provider(config, transport=self.transport)
            text = await provider.generate_text(
                [
                    {"role": "system", "content": "你是 Nautilus 的学习初始化助手，只返回符合要求的 JSON。"},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                max_tokens=SETUP_MAX_TOKENS,
                json_mode=True,
            )
        except ProviderError as exc:
            code = f"setup_{exc.kind}"
            raise DomainError(code if code in SETUP_FAILURE_MESSAGES else "setup_provider_error", 502) from exc
        except TimeoutError as exc:
            raise DomainError("setup_timeout", 502) from exc
        try:
            parsed = json.loads(_clean_json(text))
        except (json.JSONDecodeError, ValueError) as exc:
            raise DomainError("setup_invalid_json", 502) from exc
        try:
            draft = LearningSetupDraft.model_validate(parsed)
        except ValueError as exc:
            raise DomainError("setup_draft_invalid", 502) from exc

        valid_ids = {item["id"] for item in available_standards}
        if draft.recommended_criterion_id not in valid_ids:
            draft = draft.model_copy(update={"recommended_criterion_id": None})
        result = draft.model_dump(mode="json")
        # Keep only a fingerprint for change measurement, never a second draft body.
        draft_id = str(uuid4())
        comparison = {key: result[key] for key in (
            "goal_title", "goal_description", "plan_title", "plan_description", "action_title",
            "boundaries", "stop_conditions", "time_budget_minutes")}
        comparison.update(object_description=result['outcome_object'], behavior=result['outcome_behavior'],
                          context_key=result['context_key'], outcome_context_key=result['outcome_context_key'],
                          criterion_id=result['recommended_criterion_id'])
        standard = next((s for s in available_standards if s['id']==draft.recommended_criterion_id), None)
        if standard:
            comparison.update(object_description=standard['object_description'], behavior=standard['behavior'],
                              context_key=standard['context_key'], outcome_context_key=standard['context_key'])
        comparison = {key: value.strip() if isinstance(value, str) else value for key, value in comparison.items()}
        with self.learning.database.transaction(immediate=True) as connection:
            record_usage(connection, principal.owner_id, 'setup_ai', f'draft:{draft_id}:{digest(comparison)}')
        return {**result, 'draft_id': draft_id}

    def confirm(self, identity: dict[str, Any], payload: dict[str, Any], key: str) -> dict[str, Any]:
        principal = self.learning.principal(identity)
        payload = dict(payload)
        draft_id = payload.pop('draft_id', None)
        review_id = payload.pop('review_id', None)
        with self.learning.database.transaction(immediate=True) as connection:
            review = None
            if review_id:
                review = connection.execute("SELECT * FROM learning_return_review WHERE owner_id=? AND id=? AND kind='choose_next'", (principal.owner_id, review_id)).fetchone()
                accepted = connection.execute("SELECT 1 FROM learning_usage_event WHERE owner_id=? AND review_id=? AND kind='continue'", (principal.owner_id, review_id)).fetchone()
                if review is None or accepted is None:
                    raise DomainError('not_found', 404)
                position = connection.execute(
                    """SELECT l.plan_id FROM learning_session s
                       JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
                       JOIN learning_action_link l ON l.owner_id=d.owner_id AND l.action_id=d.action_id
                       WHERE s.owner_id=? AND s.id=?""",
                    (principal.owner_id, review['position_session_id']),
                ).fetchone()
                if position:
                    if payload.get('plan_id') not in (None, position['plan_id']):
                        raise DomainError('verification_scope_invalid')
                    payload['plan_id'] = position['plan_id']
            command = ConfirmLearningSetup(**payload)
            draft = connection.execute("SELECT request_key FROM learning_usage_event WHERE owner_id=? AND kind='setup_ai' AND request_key LIKE ?",
                (principal.owner_id, f'draft:{draft_id}:%')).fetchone() if draft_id else None
            if draft_id and not draft:
                raise DomainError('not_found', 404)
            result = self.learning.core.execute_in_transaction(connection, principal, command, key)
            if review:
                if review['action_id'] not in (None, result['action_id']):
                    raise DomainError('version_conflict')
                # choose_next had no action yet; bind the user's confirmed choice.
                connection.execute('UPDATE learning_return_review SET action_id=?, delegation_id=? WHERE owner_id=? AND id=?',
                    (result['action_id'], result['delegation_id'], principal.owner_id, review_id))
            record_usage(connection, principal.owner_id, 'setup_ai' if draft else 'setup_manual', f'setup:{key}',
                         review_id=review_id, action_id=result['action_id'], delegation_id=result['delegation_id'])
            comparison = {name: value.strip() if isinstance(value, str) else value
                          for name, value in command.model_dump(exclude={'original_intent', 'outcome_id', 'plan_id'}).items()}
            if draft and draft['request_key'].rsplit(':',1)[1] != digest(comparison):
                record_usage(connection, principal.owner_id, 'setup_modified', f'modified:{key}',
                             action_id=result['action_id'], delegation_id=result['delegation_id'])
            return result
