"""Bounded D1 decisions. Private payloads are stored outside immutable events."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .commands import Command


class GraphSource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['outcome', 'artifact', 'criterion', 'external']
    id: str | None = Field(default=None, min_length=1, max_length=100)
    version: int | None = Field(default=None, ge=1)
    url: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode='after')
    def reference(self):
        if self.kind == 'external':
            if not self.url or not self.url.startswith(('https://', 'http://')) or self.id:
                raise ValueError('external source needs an HTTP URL')
        elif not self.id or self.url:
            raise ValueError('internal source needs an ID')
        return self


class RelationFields(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    source_outcome_id: str = Field(min_length=1, max_length=100)
    target_outcome_id: str = Field(min_length=1, max_length=100)
    relation_type: Literal['contains', 'prerequisite', 'equivalent', 'overlap']
    context_key: str = Field(min_length=1, max_length=200)
    rationale: str = Field(default='', max_length=2000)
    uncertainty: str = Field(default='', max_length=1000)
    source_refs: list[GraphSource] = Field(default_factory=list, max_length=30)


class GraphCommand(Command):
    pass


class CreateRelation(GraphCommand, RelationFields):
    pass


class ReviseRelation(CreateRelation):
    relation_id: str
    expected_revision: int = Field(ge=1)


class RevokeRelation(GraphCommand):
    relation_id: str
    expected_revision: int = Field(ge=1)


class PurgeRelation(RevokeRelation):
    confirmation: Literal['PURGE']


class StartGraphRun(GraphCommand):
    outcome_ids: list[str] = Field(min_length=2, max_length=30)
    provider_snapshot: dict
    inputs: list[dict]


class FinishGraphRun(GraphCommand):
    run_id: str
    expected_revision: int = Field(ge=1)
    status: Literal['succeeded', 'failed']
    reason: str | None = None
    candidates: list[RelationFields] = Field(default_factory=list, max_length=60)


class CancelGraphRun(GraphCommand):
    run_id: str
    expected_revision: int = Field(ge=1)


class PurgeGraphRun(CancelGraphRun):
    confirmation: Literal['PURGE']


class ReviewGraphCandidate(GraphCommand):
    run_id: str
    candidate_id: str
    expected_revision: int = Field(ge=1)
    decision: Literal['accept', 'reject']
    relation: RelationFields | None = None
