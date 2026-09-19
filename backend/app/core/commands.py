from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreateLearningAction(Command):
    title: str = Field(min_length=1, max_length=300)
    context_key: str = Field(min_length=1, max_length=200)


class CreateOutcome(Command):
    object_description: str = Field(min_length=1, max_length=500)
    behavior: str = Field(min_length=1, max_length=500)
    context_key: str = Field(min_length=1, max_length=200)


class ConfirmLearningSetup(Command):
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


class CreateDelegation(Command):
    action_id: str = Field(min_length=1, max_length=100)
    outcome_id: str = Field(min_length=1, max_length=100)
    criterion_id: str | None = Field(default=None, min_length=1, max_length=100)
    boundaries: str = Field(max_length=2000)
    stop_conditions: str = Field(min_length=1, max_length=2000)
    time_budget_minutes: int | None = Field(default=None, ge=1, le=1440)
    expected_version: int = Field(ge=1)

class StartSession(Command):
    delegation_id: str
    expected_version: int = Field(ge=1)


class CompleteLearningAction(Command):
    action_id: str
    delegation_id: str
    expected_version: int = Field(ge=1)


class SaveTextArtifact(Command):
    session_id: str
    content: str = Field(min_length=1, max_length=1_000_000)
    expected_version: int = Field(ge=1)


class RecordVerificationArtifact(Command):
    submission_id: str
    expected_version: int = Field(ge=1)

class EndSession(Command):
    session_id: str
    disposition: str = Field(pattern=r"^(ended|interrupted)$")
    expected_version: int = Field(ge=1)
class CorrectArtifact(Command):
    artifact_id: str
    content: str = Field(min_length=1, max_length=1_000_000)
    expected_version: int = Field(ge=1)


class SoftDeleteArtifact(Command):
    artifact_id: str
    expected_version: int = Field(ge=1)


class RestoreArtifact(Command):
    artifact_id: str
    expected_version: int = Field(ge=1)


class WithdrawArtifact(Command):
    artifact_id: str
    expected_version: int = Field(ge=1)


class PurgeArtifact(Command):
    artifact_id: str
    expected_version: int = Field(ge=1)
    confirmation: str = Field(pattern=r"^PURGE$")
