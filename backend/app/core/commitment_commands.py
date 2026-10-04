"""Explicit D2 future promises, suggestion runs and optional feedback."""
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .commands import Command


class CommitmentCommand(Command):
    pass


class SourceReference(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind: Literal['feedback','artifact','submission','delayed_attempt','completion','path_version','action','outcome','plan_content']
    id: str = Field(min_length=1,max_length=100)
    revision: int = Field(default=1,ge=1)


def valid_zone(value):
    try:
        ZoneInfo(value)
    except (ValueError,ZoneInfoNotFoundError) as error:
        raise ValueError('unknown timezone') from error


def utc(value):
    if value is None:
        return None
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('a date must include its UTC offset')
    return parsed.astimezone(timezone.utc).isoformat().replace('+00:00','Z')


class ItemFields(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    id: str | None = Field(default=None,min_length=1,max_length=100)
    node_id: str = Field(min_length=1,max_length=100)
    action_id: str = Field(min_length=1,max_length=100)
    delegation_id: str = Field(min_length=1,max_length=100)
    estimate_min_minutes: int | None = Field(default=None,ge=1,le=10080)
    estimate_max_minutes: int | None = Field(default=None,ge=1,le=10080)
    due_at: str | None = None
    timezone: str | None = None
    reason: str = Field(default='',max_length=2000)
    source_refs: list[SourceReference] = Field(default_factory=list,max_length=30)

    @model_validator(mode='after')
    def valid_time(self):
        if (self.estimate_min_minutes is None)!=(self.estimate_max_minutes is None):
            raise ValueError('an estimate is a range or unknown')
        if self.estimate_min_minutes is not None and self.estimate_min_minutes>self.estimate_max_minutes:
            raise ValueError('estimate range is reversed')
        if bool(self.due_at)!=bool(self.timezone):
            raise ValueError('a planned date needs a timezone')
        self.due_at=utc(self.due_at)
        if self.timezone:
            valid_zone(self.timezone)
        return self


class PlanCommand(CommitmentCommand):
    plan_id: str
    expected_revision: int = Field(ge=0)


class SaveCommitmentDraft(PlanCommand):
    route_version_id: str
    items: list[ItemFields] = Field(max_length=100)
    reason: str = Field(default='',max_length=2000)
    draft_id: str | None = None
    expected_draft_revision: int | None = Field(default=None,ge=1)


class ConfirmCommitments(PlanCommand):
    draft_id: str
    expected_draft_revision: int = Field(ge=1)
    review_key: str


class StartCommitmentItem(PlanCommand):
    item_id: str
    expected_action_version: int = Field(ge=1)
    use_checkpoint: bool = True


class ChangeCommitmentItem(PlanCommand):
    item_id: str
    operation: Literal['defer','skip']
    due_at: str | None = None
    timezone: str | None = None
    review_key: str

    @model_validator(mode='after')
    def valid_date(self):
        if self.operation=='skip' and (self.due_at or self.timezone):
            raise ValueError('skip does not set a date')
        if bool(self.due_at)!=bool(self.timezone):
            raise ValueError('a date needs a timezone')
        object.__setattr__(self,'due_at',utc(self.due_at))
        if self.timezone:
            valid_zone(self.timezone)
        return self


class Slot(BaseModel):
    model_config=ConfigDict(extra='forbid')
    start_at: str
    end_at: str

    @model_validator(mode='after')
    def valid_slot(self):
        self.start_at,self.end_at=utc(self.start_at),utc(self.end_at)
        if self.start_at>=self.end_at:
            raise ValueError('a time slot must have positive duration')
        return self


class AvailabilityFields(BaseModel):
    model_config=ConfigDict(extra='forbid')
    timezone: str
    slots: list[Slot] = Field(default_factory=list,max_length=60)
    weekly_budget_minutes: int | None = Field(default=None,ge=1,le=10080)
    block_max_minutes: int | None = Field(default=None,ge=1,le=1440)
    preferred_days: Literal[7,14] = 7

    @model_validator(mode='after')
    def valid_slots(self):
        valid_zone(self.timezone)
        values=sorted(self.slots,key=lambda slot:slot.start_at)
        if any(a.end_at>b.start_at for a,b in zip(values,values[1:])):
            raise ValueError('availability slots cannot overlap')
        return self


class SaveAvailability(PlanCommand,AvailabilityFields):
    pass


class StartCommitmentRun(PlanCommand):
    input_hash: str
    inputs: dict
    provider_snapshot: dict


class FinishCommitmentRun(CommitmentCommand):
    run_id: str
    expected_revision: int = Field(ge=1)
    status: Literal['succeeded','failed']
    reason: str | None = None
    items: list[ItemFields] = Field(default_factory=list,max_length=30)
    explanation: str = Field(default='',max_length=2000)


class CancelCommitmentRun(CommitmentCommand):
    run_id: str
    expected_revision: int = Field(ge=1)


class PurgeCommitmentRun(CancelCommitmentRun):
    confirmation: Literal['PURGE']


class PurgeCommitmentDraft(PlanCommand):
    draft_id: str
    confirmation: Literal['PURGE']


class FeedbackFields(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    actual_min_minutes: int | None = Field(default=None,ge=0,le=10080)
    actual_max_minutes: int | None = Field(default=None,ge=0,le=10080)
    purpose: Literal['real','test','unknown'] = 'unknown'
    grain: Literal['ok','too_large','too_small','unknown'] = 'unknown'
    pace: Literal['ok','too_tight','want_more','unknown'] = 'unknown'
    method_feedback: Literal['ok','unsuitable','unknown'] = 'unknown'
    progress: Literal['progress','difficulty','uncertain'] = 'uncertain'
    activity: Literal['learning','recall','variation','transfer'] = 'learning'
    artifact_id: str | None = None
    artifact_version: int | None = Field(default=None,ge=1)
    submission_id: str | None = None
    delayed_attempt_id: str | None = None
    notes: str = Field(default='',max_length=2000)

    @model_validator(mode='after')
    def valid_range(self):
        if (self.actual_min_minutes is None)!=(self.actual_max_minutes is None):
            raise ValueError('effective effort is a range or unknown')
        if self.actual_min_minutes is not None and self.actual_min_minutes>self.actual_max_minutes:
            raise ValueError('effective effort range is reversed')
        if self.artifact_version and not self.artifact_id:
            raise ValueError('artifact version needs an artifact')
        return self


class RecordSessionFeedback(CommitmentCommand,FeedbackFields):
    session_id: str
    expected_revision: int = Field(ge=0)


class PurgeSessionFeedback(CommitmentCommand):
    session_id: str
    expected_revision: int = Field(ge=1)
    confirmation: Literal['PURGE']
