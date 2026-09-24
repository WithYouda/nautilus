from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TaskType = Literal["study", "practice", "review", "output"]
ScheduleMode = Literal["fixed", "flexible"]
TimerMode = Literal["pomodoro_25_5", "pomodoro_50_10", "custom", "count_up"]
GoalStatus = Literal["draft", "active", "completed", "archived"]
ConversationScope = Literal["independent", "global", "plan", "task"]


class AuthorizationRequest(BaseModel):
    access_token: str = Field(min_length=1, max_length=512)


class ManualPlanRequest(BaseModel):
    goal_title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    start_date: date
    end_date: date
    subject_title: str = Field(min_length=1, max_length=120)
    topic_title: str = Field(min_length=1, max_length=120)
    task_title: str = Field(min_length=1, max_length=200)
    task_type: TaskType = "study"
    schedule_mode: ScheduleMode = "flexible"
    task_start_date: date
    task_due_date: date
    planned_start: datetime | None = None
    planned_end: datetime | None = None
    estimate_minutes: int = Field(default=50, ge=1, le=1440)
    timer_mode: TimerMode = "pomodoro_50_10"
    work_minutes: int = Field(default=50, ge=1, le=240)
    break_minutes: int = Field(default=10, ge=0, le=120)

    @model_validator(mode="after")
    def validate_planned_times(self) -> "ManualPlanRequest":
        if self.planned_start and self.planned_end and self.planned_end <= self.planned_start:
            raise ValueError("任务结束时间必须晚于开始时间")
        return self


class GoalUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    start_date: date | None = None
    end_date: date | None = None
    status: GoalStatus | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        title = value.strip()
        if not title:
            raise ValueError("目标名称不能为空")
        return title


class NodeTitleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("名称不能为空")
        return title


class ReorderRequest(BaseModel):
    ordered_ids: list[str] = Field(min_length=1)

    @field_validator("ordered_ids")
    @classmethod
    def validate_ids(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("排序节点不能为空")
        if len(value) != len(set(value)):
            raise ValueError("排序节点不能重复")
        return value


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    task_type: TaskType = "study"
    schedule_mode: ScheduleMode = "flexible"
    start_date: date
    due_date: date
    planned_start: datetime | None = None
    planned_end: datetime | None = None
    estimate_minutes: int = Field(default=50, ge=1, le=1440)
    timer_mode: TimerMode = "pomodoro_50_10"
    work_minutes: int = Field(default=50, ge=1, le=240)
    break_minutes: int = Field(default=10, ge=0, le=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("任务名称不能为空")
        return title

    @model_validator(mode="after")
    def validate_planned_times(self) -> "TaskCreateRequest":
        if self.planned_start and self.planned_end and self.planned_end <= self.planned_start:
            raise ValueError("任务结束时间必须晚于开始时间")
        return self


class TaskUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    task_type: TaskType | None = None
    schedule_mode: ScheduleMode | None = None
    start_date: date | None = None
    due_date: date | None = None
    planned_start: datetime | None = None
    planned_end: datetime | None = None
    estimate_minutes: int | None = Field(default=None, ge=1, le=1440)
    timer_mode: TimerMode | None = None
    work_minutes: int | None = Field(default=None, ge=1, le=240)
    break_minutes: int | None = Field(default=None, ge=0, le=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        title = value.strip()
        if not title:
            raise ValueError("任务名称不能为空")
        return title


class TaskRescheduleRequest(BaseModel):
    days: int = Field(ge=-365, le=365)

    @model_validator(mode="after")
    def validate_days(self) -> "TaskRescheduleRequest":
        if self.days == 0:
            raise ValueError("延期天数不能为 0")
        return self


class TaskCompletionRequest(BaseModel):
    completed: bool


class TimerActionRequest(BaseModel):
    action: Literal["start", "pause", "resume", "finish"]
    timer_mode: TimerMode | None = None
    work_minutes: int | None = Field(default=None, ge=1, le=240)
    break_minutes: int | None = Field(default=None, ge=0, le=120)


class LayoutModuleRequest(BaseModel):
    id: Literal["summary", "tasks", "timer", "context"]
    visible: bool


class LayoutUpdateRequest(BaseModel):
    modules: list[LayoutModuleRequest] = Field(min_length=4, max_length=4)


class TemplateNameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("模板名称不能为空")
        return name


class ProviderSaveRequest(BaseModel):
    display_name: str = Field(default="OpenAI 兼容提供方", max_length=80)
    base_url: str = Field(min_length=1, max_length=300)
    model: str = Field(min_length=1, max_length=120)
    # api_key 刻意不加长度约束：Pydantic 的 422 会把不合法输入原样回显，
    # 长度检查放在服务层，避免密钥出现在校验错误里。留空表示保留已存密钥。
    api_key: str | None = None
    enabled: bool = True
    request_timeout_seconds: int = Field(default=60, ge=5, le=600)

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class ProviderModelsRequest(BaseModel):
    base_url: str | None = Field(default=None, max_length=300)
    api_key: str | None = None
    request_timeout_seconds: int | None = Field(default=None, ge=5, le=600)
    force_refresh: bool = False

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class ProviderTestRequest(BaseModel):
    base_url: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=120)
    api_key: str | None = None
    request_timeout_seconds: int | None = Field(default=None, ge=5, le=600)

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class ProviderCreateRequest(ProviderSaveRequest):
    provider_kind: Literal["openai_compatible"] = "openai_compatible"
    is_default: bool = False


class ProviderUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    base_url: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=120)
    api_key: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None
    request_timeout_seconds: int | None = Field(default=None, ge=5, le=600)

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class ModelManualRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)

    @field_validator("model_id")
    @classmethod
    def normalize_model_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("模型名称不能为空")
        return value


class ConversationConfigRequest(BaseModel):
    provider_profile_id: str = Field(min_length=1, max_length=64)
    provider_model_id: str = Field(min_length=1, max_length=64)
    timeout_override_seconds: int | None = Field(default=None, ge=5, le=600)


class ConversationCreateRequest(BaseModel):
    task_id: str | None = Field(default=None, max_length=64)
    context_scope: ConversationScope | None = None
    target_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_scope_target(self) -> "ConversationCreateRequest":
        if self.task_id:
            if self.context_scope not in (None, "task"):
                raise ValueError("旧 task_id 只能用于任务级对话")
            if self.target_id and self.target_id != self.task_id:
                raise ValueError("task_id 与 target_id 不一致")
            return self
        scope = self.context_scope or "independent"
        if scope in {"plan", "task"} and not self.target_id:
            raise ValueError("计划级和任务级对话必须指定目标")
        if scope in {"global", "independent"} and self.target_id:
            raise ValueError("全局或独立对话不能指定节点目标")
        return self


class ConversationUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=60)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("对话标题不能为空")
        return title


class MessageSendRequest(BaseModel):
    regenerate_message_id: str | None = Field(default=None, max_length=64)
    parent_message_id: str | None = Field(default=None, max_length=64)
    content: str = Field(min_length=1, max_length=8000)
    client_message_id: str = Field(min_length=1, max_length=64)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        content = value.strip()
        if not content:
            raise ValueError("消息内容不能为空")
        return content


class LearningActionCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    context_key: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=200)


class LearningSetupDraftRequest(BaseModel):
    intent: str = Field(min_length=1, max_length=4000)

    @field_validator("intent")
    @classmethod
    def normalize_intent(cls, value: str) -> str:
        intent = value.strip()
        if not intent:
            raise ValueError("学习意图不能为空")
        return intent


class LearningSetupConfirmRequest(BaseModel):
    plan_id: str | None = Field(default=None, min_length=1, max_length=100)
    review_id: str | None = Field(default=None, max_length=100)
    draft_id: str | None = Field(default=None, pattern=r'^[0-9a-f-]{36}$')
    original_intent: str = Field(min_length=1, max_length=4000)
    goal_title: str = Field(min_length=1, max_length=200)
    goal_description: str = Field(default="", max_length=1000)
    plan_title: str = Field(min_length=1, max_length=200)
    plan_description: str = Field(default="", max_length=1000)
    action_title: str = Field(min_length=1, max_length=300)
    context_key: str = Field(min_length=1, max_length=200)
    outcome_id: str | None = Field(default=None, min_length=1, max_length=100)
    object_description: str = Field(min_length=1, max_length=500)
    behavior: str = Field(min_length=1, max_length=500)
    outcome_context_key: str = Field(min_length=1, max_length=200)
    criterion_id: str | None = Field(default=None, min_length=1, max_length=100)
    boundaries: str = Field(default="", max_length=2000)
    stop_conditions: str = Field(min_length=1, max_length=2000)
    time_budget_minutes: int | None = Field(default=None, ge=1, le=1440)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator(
        "original_intent",
        "goal_title",
        "plan_title",
        "action_title",
        "context_key",
        "object_description",
        "behavior",
        "outcome_context_key",
        "stop_conditions",
    )
    @classmethod
    def strip_nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value


class LearningOutcomeCreateRequest(BaseModel):
    object_description: str = Field(min_length=1, max_length=500)
    behavior: str = Field(min_length=1, max_length=500)
    context_key: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("object_description", "behavior", "context_key")
    @classmethod
    def strip_nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value


class LearningDelegationCreateRequest(BaseModel):
    action_id: str = Field(min_length=1, max_length=100)
    outcome_id: str = Field(min_length=1, max_length=100)
    criterion_id: str | None = Field(default=None, min_length=1, max_length=100)
    boundaries: str = Field(default="", max_length=2000)
    stop_conditions: str = Field(min_length=1, max_length=2000)
    time_budget_minutes: int | None = Field(default=None, ge=1, le=1440)
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("stop_conditions")
    @classmethod
    def strip_stop_conditions(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("停止条件不能为空")
        return value


class LearningSessionStartRequest(BaseModel):
    delegation_id: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class LearningArtifactSaveRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=1_000_000)
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class LearningSessionEndRequest(BaseModel):
    disposition: Literal["ended", "interrupted"]
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class LearningVerificationStartRequest(BaseModel):
    action_id: str = Field(min_length=1, max_length=100)
    delegation_id: str = Field(min_length=1, max_length=100)
    session_id: str | None = Field(default=None, max_length=100)
    mode: Literal["ai_challenge", "user_material"]
    request_key: str = Field(min_length=1, max_length=200)


class LearningRoomConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str = Field(min_length=1, max_length=100)


class LearningVerificationSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    responses: dict[str, str] = Field(default_factory=dict)
    material: str = Field(default="", max_length=1_000_000)
    learner_work: str = Field(default="", max_length=1_000_000)
    evidence_condition: Literal["independent", "with_materials", "with_hints"] = "with_materials"
    request_key: str = Field(min_length=1, max_length=200)


class LearningVerificationEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submission_id: str = Field(min_length=1, max_length=100)
    request_key: str = Field(min_length=1, max_length=200)


class LearningVerificationConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submission_id: str = Field(min_length=1, max_length=100)
    evaluation_id: str = Field(min_length=1, max_length=100)
    stop_condition_confirmed: Literal[True]


class LearningVerificationPurgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal["PURGE"]


class LearningArtifactCorrectRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1_000_000)
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class AgentPermissionRequestCreate(BaseModel):
    purpose: str = Field(min_length=1, max_length=1000)
    target_id: str = Field(min_length=1, max_length=100)
    content_granularity: Literal["metadata", "full_text"] = "metadata"
    ttl_seconds: int = Field(default=300, ge=60, le=3600)
    request_key: str = Field(min_length=1, max_length=200)

    @field_validator("purpose")
    @classmethod
    def strip_purpose(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("权限申请目的不能为空")
        return value


class AgentPermissionDenyRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class AgentPermissionRevokeRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason")
    @classmethod
    def strip_revoke_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class EvidenceAnalysisRequest(BaseModel):
    content_version: int | None = Field(default=None, ge=1)
    request_key: str = Field(min_length=1, max_length=200)


class EvidenceHumanReviewRequest(BaseModel):
    request_key: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def strip_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class EvidenceSupplementalVerificationRequest(BaseModel):
    request_key: str = Field(min_length=1, max_length=200)
    due_at: datetime | None = None
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def strip_supplemental_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class EvidenceClaimReviewRequest(BaseModel):
    action: Literal["adopt", "question", "withdraw", "supersede", "defer"]
    reason: str | None = Field(default=None, max_length=1000)
    request_key: str = Field(min_length=1, max_length=200)
    replacement_claim_id: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("reason")
    @classmethod
    def strip_review_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class DerivedStateRecalculateRequest(BaseModel):
    criterion_id: str | None = Field(default=None, min_length=1, max_length=100)


class EvidenceBatchReviewRequest(BaseModel):
    claim_ids: list[str] = Field(min_length=1, max_length=100)
    action: Literal["adopt", "question", "withdraw", "defer"]
    reason: str | None = Field(default=None, max_length=1000)
    request_key: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def strip_batch_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("claim_ids")
    @classmethod
    def validate_claim_ids(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("批量复核主张不能为空")
        if len(value) != len(set(value)):
            raise ValueError("批量复核主张不能重复")
        return value


class ArtifactLifecycleRequest(BaseModel):
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ArtifactPurgeRequest(BaseModel):
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)
    confirmation: Literal["PURGE"]


class EvidenceProviderSelectionRequest(BaseModel):
    provider_profile_id: str = Field(min_length=1, max_length=100)
    provider_model_id: str = Field(min_length=1, max_length=100)


class QuestionDiscussionCreateRequest(BaseModel):
    evaluation_id: str | None = Field(default=None, max_length=100)
    submission_id: str = Field(min_length=1, max_length=100)
    question_id: str = Field(min_length=1, max_length=100)
    request_key: str = Field(min_length=1, max_length=200)


class QuestionDiscussionMessageRequest(BaseModel):
    regenerate_turn_id: str | None = Field(default=None, max_length=64)
    parent_turn_id: str | None = Field(default=None, max_length=64)
    content: str = Field(min_length=1, max_length=12000)
    request_key: str = Field(min_length=1, max_length=200)
    retry: bool = False
