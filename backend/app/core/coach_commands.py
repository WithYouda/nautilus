"""Audited coach configuration and proposals, independent of formal learning state."""
from typing import Literal
from pydantic import Field, model_validator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .commands import Command

SIGNAL_KINDS = {'separate_work_requested','repeated_blocker','scope_conflict','cannot_continue','permission_or_cost_change'}

class CoachCommand(Command):
    pass

class SaveCoachSettings(CoachCommand):
    enabled: bool
    timezone: str = Field(min_length=1,max_length=100)
    max_calls_per_session: int = Field(ge=1,le=20)
    max_calls_per_day: int = Field(ge=1,le=100)
    cooldown_minutes: int = Field(ge=30,le=10080)
    expected_revision: int = Field(ge=0)
    @model_validator(mode='after')
    def valid_zone(self):
        try: ZoneInfo(self.timezone)
        except (ValueError,ZoneInfoNotFoundError) as error: raise ValueError('unknown timezone') from error
        return self

class RecordCoachSignal(CoachCommand):
    signal: dict

class CorrectCoachSignal(CoachCommand):
    signal_id: str
    operation: Literal['exclude','restore']
    expected_revision: int = Field(ge=1)

class ClaimCoachRun(CoachCommand):
    run_id: str
    scope: Literal['global','plan']
    plan_id: str | None = None
    trigger: Literal['manual','return','boundary']
    inputs: dict
    provider_snapshot: dict
    retry_run_id: str | None = None
    permission_candidate_id: str | None = None
    permission_request_id: str | None = None

class SendCoachRun(CoachCommand):
    run_id: str
    expected_revision: int = Field(ge=1)

class FinishCoachRun(CoachCommand):
    run_id: str
    expected_revision: int = Field(ge=1)
    status: Literal['succeeded','failed']
    candidates: list[dict] = Field(default_factory=list,max_length=8)
    reason: str | None = None

class CancelCoachRun(CoachCommand):
    run_id: str
    expected_revision: int = Field(ge=1)
    reason: Literal['canceled','disabled','interrupted'] = 'canceled'

class PurgeCoachRun(CoachCommand):
    run_id: str
    expected_revision: int = Field(ge=1)
    confirmation: Literal['PURGE']

class DecideCoachCandidate(CoachCommand):
    candidate_id: str
    expected_revision: int = Field(ge=1)
    operation: Literal['accept','reject','ignore','undo']
