from __future__ import annotations

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .db import Database
from .learning_domain import CriterionRecipe, DomainError

STANDARD_PACKAGE_PATH = (
    Path(__file__).with_name("standards") / "python_regex_basics_v1.approved.json"
)


class StandardOutcomeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_description: str = Field(min_length=1, max_length=500)
    behavior: str = Field(min_length=1, max_length=500)
    context_key: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=200)


class StandardPackageDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    version: int = Field(ge=1)
    context_key: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=500)
    review_status: Literal["approved"]
    reviewed_by: str = Field(min_length=1, max_length=200)
    reviewed_at: str = Field(min_length=1, max_length=64)
    outcome_id: str = Field(min_length=1, max_length=100)
    criterion_id: str = Field(min_length=1, max_length=100)
    outcome: StandardOutcomeDefinition
    recipe: CriterionRecipe

    @property
    def recipe_json(self) -> str:
        return json.dumps(
            self.recipe.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def load_approved_standard_package() -> StandardPackageDefinition:
    package = StandardPackageDefinition.model_validate(
        json.loads(STANDARD_PACKAGE_PATH.read_text(encoding="utf-8"))
    )
    if package.outcome.context_key != package.context_key:
        raise DomainError("standard_package_invalid")
    return package


def _scoped_id(owner_id: str, kind: str, logical_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"nautilus:{kind}:{owner_id}:{logical_id}"))


def _require_same(actual: object, expected: object, field: str) -> None:
    if actual != expected:
        raise DomainError("standard_package_conflict", 409)


def seed_standard_package(
    database: Database, owner_id: str, package: StandardPackageDefinition
) -> None:
    """Idempotently install the approved first-slice standard for one owner."""

    outcome_id = _scoped_id(owner_id, "outcome", package.outcome_id)
    package_id = _scoped_id(owner_id, "package", package.package_id)
    criterion_id = _scoped_id(owner_id, "criterion", package.criterion_id)

    with database.transaction() as connection:
        outcome = connection.execute(
            """SELECT object_description, behavior, context_key, source
               FROM learning_outcome WHERE owner_id=? AND id=?""",
            (owner_id, outcome_id),
        ).fetchone()
        if outcome is None:
            connection.execute(
                """INSERT INTO learning_outcome
                   (id, owner_id, object_description, behavior, context_key, source, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    outcome_id,
                    owner_id,
                    package.outcome.object_description,
                    package.outcome.behavior,
                    package.outcome.context_key,
                    package.outcome.source,
                    package.reviewed_at,
                ),
            )
        else:
            _require_same(outcome["object_description"], package.outcome.object_description, "outcome.object_description")
            _require_same(outcome["behavior"], package.outcome.behavior, "outcome.behavior")
            _require_same(outcome["context_key"], package.outcome.context_key, "outcome.context_key")
            _require_same(outcome["source"], package.outcome.source, "outcome.source")

        standard = connection.execute(
            """SELECT title, source, context_key
               FROM learning_standard_package WHERE owner_id=? AND id=?""",
            (owner_id, package_id),
        ).fetchone()
        if standard is None:
            connection.execute(
                """INSERT INTO learning_standard_package
                   (id, owner_id, title, source, context_key)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    package_id,
                    owner_id,
                    package.title,
                    package.source,
                    package.context_key,
                ),
            )
        else:
            _require_same(standard["title"], package.title, "package.title")
            _require_same(standard["source"], package.source, "package.source")
            _require_same(standard["context_key"], package.context_key, "package.context_key")

        criterion = connection.execute(
            """SELECT package_id, outcome_id, version, source, context_key, recipe_json,
                      review_status, reviewed_by, reviewed_at
               FROM learning_criterion_version WHERE owner_id=? AND id=?""",
            (owner_id, criterion_id),
        ).fetchone()
        if criterion is None:
            connection.execute(
                """INSERT INTO learning_criterion_version
                   (id, owner_id, package_id, outcome_id, version, source, context_key,
                    recipe_json, review_status, reviewed_by, reviewed_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    criterion_id,
                    owner_id,
                    package_id,
                    outcome_id,
                    package.version,
                    package.source,
                    package.context_key,
                    package.recipe_json,
                    package.review_status,
                    package.reviewed_by,
                    package.reviewed_at,
                    package.reviewed_at,
                ),
            )
        else:
            _require_same(criterion["package_id"], package_id, "criterion.package_id")
            _require_same(criterion["outcome_id"], outcome_id, "criterion.outcome_id")
            _require_same(criterion["version"], package.version, "criterion.version")
            _require_same(criterion["source"], package.source, "criterion.source")
            _require_same(criterion["context_key"], package.context_key, "criterion.context_key")
            try:
                same_recipe = json.loads(criterion["recipe_json"]) == package.recipe.model_dump(mode="json")
            except (TypeError, json.JSONDecodeError):
                same_recipe = False
            if not same_recipe:
                raise DomainError("standard_package_conflict", 409)
            _require_same(criterion["review_status"], package.review_status, "criterion.review_status")
            _require_same(criterion["reviewed_by"], package.reviewed_by, "criterion.reviewed_by")
            _require_same(criterion["reviewed_at"], package.reviewed_at, "criterion.reviewed_at")
