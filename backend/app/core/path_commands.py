"""Explicit owner decisions about a plan's route; never teaching progress."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .commands import Command
from .organization_commands import TaskFields


class PathNode(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    action_ids: list[str] = Field(default_factory=list, max_length=30)
    outcome_ids: list[str] = Field(default_factory=list, max_length=30)


class PathEdge(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=100)


class PathFields(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    nodes: list[PathNode] = Field(min_length=1, max_length=60)
    edges: list[PathEdge] = Field(default_factory=list, max_length=100)
    entry_node_id: str = Field(min_length=1, max_length=100)
    current_node_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def graph_shape(self):
        identifiers = [node.id for node in self.nodes]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError('duplicate route node')
        if self.entry_node_id not in identifiers or self.current_node_id not in identifiers:
            raise ValueError('route position must refer to a node')
        pairs = [(edge.source, edge.target) for edge in self.edges]
        if len(pairs) != len(set(pairs)):
            raise ValueError('duplicate route connection')
        if any(a == b or a not in identifiers or b not in identifiers for a, b in pairs):
            raise ValueError('invalid route connection')
        incoming = {identifier: 0 for identifier in identifiers}
        neighbors = {identifier: [] for identifier in identifiers}
        for a, b in pairs:
            incoming[b] += 1
            neighbors[a].append(b)
        pending = [identifier for identifier in identifiers if incoming[identifier] == 0]
        seen = []
        while pending:
            identifier = pending.pop()
            seen.append(identifier)
            for other in neighbors[identifier]:
                incoming[other] -= 1
                if incoming[other] == 0:
                    pending.append(other)
        if len(seen) != len(identifiers):
            raise ValueError('route connection cycle')
        reachable, pending = set(), [self.entry_node_id]
        while pending:
            identifier = pending.pop()
            if identifier in reachable:
                continue
            reachable.add(identifier)
            pending.extend(neighbors[identifier])
        if reachable != set(identifiers):
            raise ValueError('route contains unreachable nodes')
        for node in self.nodes:
            if len(node.action_ids) != len(set(node.action_ids)) or len(node.outcome_ids) != len(set(node.outcome_ids)):
                raise ValueError('duplicate route reference')
        return self


class PathCommand(Command):
    pass


class PathTaskFields(TaskFields):
    node_id: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=1)
    expected_organization_revision: int = Field(ge=0)
    version_id: str | None = None
    draft_id: str | None = None
    expected_draft_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def target(self):
        if bool(self.version_id) == bool(self.draft_id):
            raise ValueError('select one route target')
        if bool(self.draft_id) != (self.expected_draft_revision is not None):
            raise ValueError('draft revision required for draft target')
        return self


class CreatePathTask(PathCommand, PathTaskFields):
    plan_id: str


class SavePathDraft(PathCommand, PathFields):
    plan_id: str
    expected_revision: int = Field(ge=0)
    expected_organization_revision: int = Field(ge=0)
    intent: Literal['create', 'change_entry', 'change_scope', 'change_direction', 'restore', 'undo'] = 'create'
    draft_id: str | None = None
    expected_draft_revision: int | None = Field(default=None, ge=1)
    source_version_id: str | None = None
    restore_version_id: str | None = None


class ConfirmPathDecision(PathCommand):
    plan_id: str
    draft_id: str
    expected_draft_revision: int = Field(ge=1)
    expected_revision: int = Field(ge=0)
    review_key: str = Field(min_length=1, max_length=100)


class TransferFields(PathFields):
    destination_title: str = Field(min_length=1, max_length=200)
    destination_description: str = Field(default='', max_length=1000)
    pause_original: bool = True
    expected_revision: int = Field(ge=0)
    expected_organization_revision: int = Field(ge=0)


class TransferPathToPlan(PathCommand, TransferFields):
    plan_id: str
    review_key: str = Field(min_length=1, max_length=100)


class SetPathPosition(PathCommand):
    plan_id: str
    version_id: str
    node_id: str
    expected_revision: int = Field(ge=1)


class StartPathTask(SetPathPosition):
    delegation_id: str
    expected_action_version: int = Field(ge=1)
    use_checkpoint: bool = True


class PurgePathContent(PathCommand):
    plan_id: str
    version_id: str
    expected_revision: int = Field(ge=1)
    confirmation: Literal['PURGE']
