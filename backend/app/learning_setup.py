from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .conversations import ConversationError, ConversationService
from .core.commands import ConfirmLearningSetup
from .learning_domain import DomainError
from .learning_service import LearningService
from .providers import ProviderError, build_provider


class LearningSetupDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
                "把用户的自然语言学习意图整理成一次低承诺的第一步。",
                "只返回 JSON，不要 Markdown。",
                "goal_title 是用户想达成的结果，action_title 是现在要执行的任务，不能混为一谈。",
                "boundaries 和 stop_conditions 必须具体、短小、适合一次学习会话。",
                "recommended_criterion_id 只能填写 available_standards 中完全匹配的 id，否则填写 null。",
                "不要声称用户已经掌握，也不要生成长期精确排期。",
            ],
            "output_schema": {
                "goal_title": "string",
                "goal_description": "string",
                "plan_title": "string",
                "plan_description": "string",
                "action_title": "string",
                "context_key": "string",
                "outcome_object": "string",
                "outcome_behavior": "string",
                "outcome_context_key": "string",
                "boundaries": "string",
                "stop_conditions": "string",
                "time_budget_minutes": "number",
                "recommended_criterion_id": "string|null",
                "rationale": "string",
            },
        }
        try:
            provider = build_provider(config, transport=self.transport)
            text = await provider.generate_text(
                [
                    {"role": "system", "content": "你是 Nautilus 的学习初始化助手，只返回符合要求的 JSON。"},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                max_tokens=1200,
            )
            draft = LearningSetupDraft.model_validate(json.loads(_clean_json(text)))
        except (ProviderError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            raise DomainError("setup_draft_invalid", 502) from exc

        valid_ids = {item["id"] for item in available_standards}
        if draft.recommended_criterion_id not in valid_ids:
            draft = draft.model_copy(update={"recommended_criterion_id": None})
        return draft.model_dump(mode="json")

    def confirm(self, identity: dict[str, Any], payload: dict[str, Any], key: str) -> dict[str, Any]:
        principal = self.learning.principal(identity)
        return self.learning.core.execute(principal, ConfirmLearningSetup(**payload), key)
