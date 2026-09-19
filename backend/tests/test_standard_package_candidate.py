from __future__ import annotations

import json
from pathlib import Path

from app.learning_domain import CriterionRecipe

STANDARD_PATH = Path(__file__).parents[1] / "app" / "standards" / "python_regex_basics_v1.candidate.json"


def test_python_regex_candidate_package_is_structurally_valid():
    package = json.loads(STANDARD_PATH.read_text(encoding="utf-8"))

    assert package["package_id"] == "python-regex-basics-v1"
    assert package["title"] == "Python 正则表达式基础 v1"
    assert package["version"] == 1
    assert package["context_key"] == "python-regex-basics"
    assert package["source"] == "https://docs.python.org/3/library/re.html"
    assert package["review_status"] == "candidate"

    outcome = package["outcome"]
    assert outcome["object_description"] == "Python re 模块中的基础正则表达式语法"
    assert outcome["behavior"].startswith("能在不查阅资料的情况下")
    assert outcome["context_key"] == package["context_key"]

    recipe = CriterionRecipe.model_validate(package["recipe"])
    assert [dimension.id for dimension in recipe.dimensions] == [
        "syntax_semantics",
        "application",
        "independent_explanation",
    ]
