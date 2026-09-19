from __future__ import annotations

import json

from app.learning_domain import CriterionRecipe
from app.learning_storage import open_learning_database
from app.standards import load_approved_standard_package, seed_standard_package


def test_approved_python_regex_standard_package_is_valid_and_seeded_idempotently(tmp_path):
    database = open_learning_database(tmp_path / "learning.sqlite3")
    try:
        with database.transaction() as connection:
            connection.execute(
                """INSERT INTO local_identity
                   (id, device_id, display_name, timezone, created_at, updated_at)
                   VALUES ('owner-a', 'device-a', 'Synthetic learner', 'UTC',
                           '2026-09-07T00:00:00Z', '2026-09-07T00:00:00Z')"""
            )

        package = load_approved_standard_package()
        assert package.package_id == "python-regex-basics-v1"
        assert package.review_status == "approved"
        assert package.reviewed_by == "product-owner"
        assert package.reviewed_at == "2026-09-07T00:00:00Z"
        assert [dimension.id for dimension in package.recipe.dimensions] == [
            "syntax_semantics",
            "application",
            "independent_explanation",
        ]
        CriterionRecipe.model_validate(json.loads(package.recipe_json))

        seed_standard_package(database, "owner-a", package)
        seed_standard_package(database, "owner-a", package)

        assert database.fetchone(
            "SELECT COUNT(*) FROM learning_outcome WHERE owner_id='owner-a' AND source='standard'"
        )[0] == 1
        assert database.fetchone(
            "SELECT COUNT(*) FROM learning_standard_package WHERE owner_id='owner-a'"
        )[0] == 1
        criterion = database.fetchone(
            """SELECT review_status, reviewed_by, reviewed_at
               FROM learning_criterion_version WHERE owner_id='owner-a'"""
        )
        assert tuple(criterion) == ("approved", "product-owner", "2026-09-07T00:00:00Z")
        assert database.fetchall("PRAGMA foreign_key_check") == []
    finally:
        database.close()


def test_standard_package_is_isolated_between_owners(tmp_path):
    database = open_learning_database(tmp_path / "learning.sqlite3")
    try:
        with database.transaction() as connection:
            for owner in ("owner-a", "owner-b"):
                connection.execute(
                    """INSERT INTO local_identity
                       (id, device_id, display_name, timezone, created_at, updated_at)
                       VALUES (?, ?, 'Synthetic learner', 'UTC',
                               '2026-09-07T00:00:00Z', '2026-09-07T00:00:00Z')""",
                    (owner, f"device-{owner}"),
                )

        package = load_approved_standard_package()
        seed_standard_package(database, "owner-a", package)
        seed_standard_package(database, "owner-b", package)

        assert database.fetchone(
            "SELECT COUNT(*) FROM learning_outcome WHERE source='standard'"
        )[0] == 2
        assert database.fetchone(
            "SELECT COUNT(*) FROM learning_standard_package"
        )[0] == 2
        assert database.fetchone(
            "SELECT COUNT(*) FROM learning_criterion_version WHERE review_status='approved'"
        )[0] == 2
        assert database.fetchall("PRAGMA foreign_key_check") == []
    finally:
        database.close()
