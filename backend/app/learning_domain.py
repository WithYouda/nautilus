from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .db import Database


class DomainError(ValueError):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class Principal:
    owner_id: str
    actor_id: str
    kind: Literal["user", "agent"]
    action_ids: frozenset[str] = frozenset()
    tools: frozenset[str] = frozenset()

    @classmethod
    def user(cls, owner_id: str):
        return cls(owner_id, owner_id, "user")

    @classmethod
    def agent(cls, owner_id: str, actor_id: str, *, action_ids: frozenset[str], tools: frozenset[str]):
        return cls(owner_id, actor_id, "agent", action_ids, tools)


class EvidenceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["semantic_analysis", "independent_review", "deterministic_check", "delayed_recall", "transfer"]
    condition: Literal["independent", "with_materials", "with_hints"]
    minimum: int = Field(ge=1, le=100)


class CriterionDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=200)
    requirements: list[EvidenceRequirement] = Field(min_length=1, max_length=20)


class CriterionRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimensions: list[CriterionDimension] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_dimensions(self):
        if len({dimension.id for dimension in self.dimensions}) != len(self.dimensions):
            raise ValueError("duplicate dimensions")
        return self


class LearningRepository:
    """Scoped reads and binding checks. Domain writes belong to Core commands."""

    def __init__(self, database: Database, principal: Principal):
        self.database = database
        self.principal = principal

    def _owned(self, table: str, object_id: str) -> dict:
        row = self.database.fetchone(
            f"SELECT * FROM {table} WHERE owner_id=? AND id=?",
            (self.principal.owner_id, object_id),
        )
        if row is None:
            raise DomainError("not_found", 404)
        return dict(row)

    def require_action_scope(self, action_id: str):
        if self.principal.kind == "agent" and action_id not in self.principal.action_ids:
            raise DomainError("permission_denied", 403)

    def action(self, action_id: str) -> dict:
        self.require_action_scope(action_id)
        return self._owned("learning_action", action_id)

    def delegation(self, delegation_id: str) -> dict:
        delegation = self._owned("learning_delegation", delegation_id)
        self.action(delegation["action_id"])
        return delegation

    def session(self, session_id: str) -> dict:
        session = self._owned("learning_session", session_id)
        self.delegation(session["delegation_id"])
        return session

    def validate_binding(self, action_id: str, outcome_id: str, criterion_id: str | None) -> dict:
        action = self.action(action_id)
        self._owned("learning_outcome", outcome_id)
        if criterion_id is None:
            return {"criterion": None, "reason": "no_criterion"}
        criterion = self._owned("learning_criterion_version", criterion_id)
        package = self._owned("learning_standard_package", criterion["package_id"])
        if criterion["review_status"] != "approved":
            raise DomainError("criterion_not_approved")
        if criterion["outcome_id"] != outcome_id or any(
            item["context_key"] != action["context_key"] for item in (criterion, package)
        ):
            raise DomainError("criterion_out_of_scope")
        if self.database.fetchone(
            "SELECT 1 FROM learning_criterion_availability WHERE owner_id=? AND criterion_id=?",
            (self.principal.owner_id, criterion_id),
        ):
            raise DomainError("criterion_unavailable")
        try:
            CriterionRecipe.model_validate(json.loads(criterion["recipe_json"]))
        except (ValidationError, json.JSONDecodeError) as exc:
            raise DomainError("criterion_invalid_recipe") from exc
        return {"criterion": criterion, "reason": None}
