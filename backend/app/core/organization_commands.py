"""D2 owner decisions limited to organization and manual task creation."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .commands import Command


class OrganizationCommand(Command):
    pass


class CreatePlan(OrganizationCommand):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=1000)
    goal_id: str | None = Field(default=None, min_length=1, max_length=100)


class PlanRevision(OrganizationCommand):
    plan_id: str
    expected_revision: int = Field(ge=0)


class ModuleFields(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=1000)
    parent_module_id: str | None = Field(default=None, min_length=1, max_length=100)


class CreateModule(PlanRevision, ModuleFields):
    pass


class ReviseModule(CreateModule):
    module_id: str


class PlaceTask(PlanRevision):
    action_id: str
    module_id: str | None = Field(default=None, min_length=1, max_length=100)


class RemovePlanTask(PlanRevision):
    action_id: str = Field(min_length=1, max_length=100)
    expected_action_version: int = Field(ge=1)


class ChildReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['module', 'task']
    id: str = Field(min_length=1, max_length=100)


class OrderChildren(PlanRevision):
    parent_module_id: str | None = Field(default=None, min_length=1, max_length=100)
    children: list[ChildReference] = Field(max_length=10000)


class TaskFields(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)
    action_title: str = Field(min_length=1, max_length=300)
    context_key: str = Field(min_length=1, max_length=200)
    object_description: str = Field(min_length=1, max_length=500)
    behavior: str = Field(min_length=1, max_length=500)
    outcome_context_key: str = Field(min_length=1, max_length=200)
    outcome_id: str | None = Field(default=None, min_length=1, max_length=100)
    criterion_id: str | None = Field(default=None, min_length=1, max_length=100)
    boundaries: str = Field(default='', max_length=2000)
    stop_conditions: str = Field(min_length=1, max_length=2000)
    time_budget_minutes: int | None = Field(default=None, ge=1, le=1440)


class CreatePlanTask(PlanRevision, TaskFields):
    pass


class PurgePlanContent(PlanRevision):
    confirmation: Literal['PURGE']


class PurgeModuleContent(PurgePlanContent):
    module_id: str
