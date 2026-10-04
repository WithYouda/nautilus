#!/usr/bin/env python3
"""Explicitly seed synthetic UI examples, never real learning or provider results.

Run with PYTHONPATH=backend and --demo. Only the existing development trial and
direct /tmp/nautilus-playwright.* directories are permitted; no initialization,
migration, network calls, or edits to existing records. Demo records may become
the latest history shown by the normal continuity view.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections import Counter
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.core.commands import ConfirmLearningSetup, CreateOutcome
from app.core.events import append_event, canonical, digest
from app.core.graph_commands import CreateRelation
from app.evidence import EvidenceService, ModelObservationDraft
from app.evidence_events import EvidenceEventService
from app.learning_service import LearningService
from app.learning_storage import open_learning_database
from app.outcome_graph import OutcomeGraph
from app.outcome_review import OutcomeReview
from app.review import ReviewService
from app.standards import StandardPackageDefinition, seed_standard_package
from app.state_derivation import StateDerivationService
from app.verification import VerificationService

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREFIX = "outcome-graph-demo-v1"
CONTEXT = "演示/合成：Python 3 文本处理；仅供界面试用"
PLAN_TITLE = "演示：Python 文本处理能力图"
NOTICE = "演示/合成数据，仅用于查看成果图和依据回看，不代表真实学习或掌握。"
STAMP = "2026-10-04T00:00:00Z"

# (short readable label, observable capability, standard condition if present)
ATOMIC = {
    "strip": ("去除文本两端空白", "能用 strip 去除两端空白并保留中间内容", "with_materials"),
    "split": ("拆分分隔符文本", "能按指定分隔符拆分文本并解释空字段", "with_materials"),
    "normalize": ("统一连续空白", "能把混合空白整理为单个空格", None),
    "extract": ("提取文本中的数字", "能用正则提取每段数字并说明匹配边界", "with_materials"),
    "groups": ("解释正则捕获分组", "能解释分组编号与匹配结果的对应关系", "with_materials"),
    "capture": ("收集每段数字串", "能用正则提取每段数字并说明匹配边界", "independent"),
    "unicode": ("处理 Unicode 文本", "能辨认文本编码问题并保留中文字符", None),
}
COMPOSITE = {
    "root": ("完成 Python 文本处理", "能组织清理与提取步骤完成文本处理任务"),
    "clean": ("清理与拆分文本", "能组合空白清理、拆分和格式整理"),
    "regex": ("使用正则提取信息", "能组合数字提取与捕获分组处理文本"),
}
CONTENTS = {
    "strip": NOTICE + '\n输入："  Nautilus 42  "\n代码：text.strip()\n输出："Nautilus 42"\n条件：可查资料。',
    "split": NOTICE + '\n输入："alpha,,beta"\n代码：text.split(",")\n输出：["alpha", "", "beta"]\n条件：可查资料。',
    "normalize": NOTICE + '\n输入："  alpha\\t beta\\n "\n代码：" ".join(text.split())\n输出："alpha beta"\n没有设定合格标准，仅展示这份合成记录。',
    "extract": NOTICE + '\n输入："订单12，退货3"\n代码：re.findall(r"\\d+", text)\n输出：["12", "3"]\n另一次合成尝试：使用 r"\\d"，得到 ["1", "2", "3"]，拆开了多位数。\n条件：可查资料。',
    "capture": NOTICE + '\n输入："A12 B3"\n代码：re.findall(r"\\d+", text)\n输出：["12", "3"]\n条件：可查资料；这份记录不能证明独立完成。',
}


def validated_path(data_dir: str | Path, *, demo: bool) -> Path:
    if not demo:
        raise ValueError("synthetic seeding requires explicit --demo")
    original = Path(data_dir).expanduser().absolute()
    if any(part.is_symlink() for part in (original, *original.parents)):
        raise ValueError("demo paths cannot contain symlinks")
    root = original.resolve(strict=True)
    trial = PROJECT_ROOT / "tmp/nautilus-trial-20260919"
    if root != trial and not (root.parent == Path("/tmp") and root.name.startswith("nautilus-playwright.")):
        raise ValueError("demo target must be the existing trial or /tmp/nautilus-playwright.*")
    db_path = root / "learning.sqlite3"
    if not db_path.is_file() or db_path.is_symlink() or db_path.stat().st_nlink != 1:
        raise ValueError("demo database must be an existing direct, unshared file")
    return db_path


def snapshot(database) -> dict[str, Counter]:
    """Hash rows in memory; never emit credentials or existing private content."""
    result = {}
    for row in database.fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        name = row[0]
        quoted = '"' + name.replace('"', '""') + '"'
        result[name] = Counter(digest([value.hex() if isinstance(value, bytes) else value for value in item])
                               for item in database.fetchall(f"SELECT * FROM {quoted}"))
    return result


def snapshot_digest(rows: dict[str, Counter]) -> str:
    return digest({table: sorted(values.items()) for table, values in rows.items()})


def package(key: str) -> StandardPackageDefinition:
    label, behavior, condition = ATOMIC[key]
    return StandardPackageDefinition.model_validate({
        "package_id": PREFIX + ":package:" + key,
        "title": "演示标准：" + label,
        "version": 1,
        "context_key": CONTEXT,
        "source": "演示/合成：本脚本的文本处理示例，不是已审核的真实学习标准",
        "review_status": "approved",
        "reviewed_by": "演示/合成 fixture；仅为呈现示例覆盖状态",
        "reviewed_at": STAMP,
        "outcome_id": PREFIX + ":outcome:" + key,
        "criterion_id": PREFIX + ":criterion:" + key,
        "outcome": {"object_description": label, "behavior": behavior, "context_key": CONTEXT,
                    "source": "演示/合成：成果图界面示例"},
        "recipe": {"dimensions": [{"id": "application", "label": "演示：结果检查",
                                     "requirements": [{"method": "deterministic_check", "condition": condition, "minimum": 1}]}]},
    })


def scoped_id(owner: str, kind: str, logical: str) -> str:
    # This is the established standard installer identity format.
    return str(uuid5(NAMESPACE_URL, f"nautilus:{kind}:{owner}:{logical}"))


def historical_artifact(learning, principal, setup, key, content):
    """Fixture-only import: new demo session is started/saved/closed in one commit.

    Uses the ordinary Core event projector and stream hashes. It does not invoke
    StartSession against the live user's current session or change that guard.
    """
    request_key = PREFIX + ":history:" + key
    request_hash = digest({"setup": setup["id"], "content": content})
    with learning.database.transaction(immediate=True) as connection:
        previous = connection.execute("SELECT request_hash,result_json FROM learning_command WHERE owner_id=? AND actor_id=? AND idempotency_key=?",
                                      (principal.owner_id, principal.actor_id, request_key)).fetchone()
        if previous:
            if previous["request_hash"] != request_hash:
                raise ValueError("demo historical content changed; do not overwrite existing fixtures")
            return json.loads(previous["result_json"])
        action = connection.execute("SELECT context_key,version FROM learning_action WHERE owner_id=? AND id=?",
                                    (principal.owner_id, setup["action_id"])).fetchone()
        if action is None or action["context_key"] != CONTEXT or action["version"] != 2:
            raise ValueError("historical fixtures require a newly allocated demo action")
        command_id, session_id, artifact_id = (str(uuid4()) for _ in range(3))
        connection.execute("INSERT INTO learning_command VALUES (?,?,?,?,?,?,?,?)",
                           (command_id, principal.owner_id, principal.actor_id, request_key,
                            "DemoHistoricalSession", request_hash, "{}", STAMP))
        common = dict(command_id=command_id, key=request_key, aggregate_type="action",
                      aggregate_id=setup["action_id"], now=STAMP)
        append_event(connection, principal, **common, expected_version=2, event_type="session.started",
                     payload={"id": session_id, "delegation_id": setup["delegation_id"], "contract_version": 1})
        event = append_event(connection, principal, **common, expected_version=3, event_type="artifact.created",
                             payload={"id": artifact_id, "session_id": session_id, "content_version": 1, "content": content})
        append_event(connection, principal, **common, expected_version=4, event_type="session.ended",
                     payload={"id": str(uuid4()), "session_id": session_id, "disposition": "ended"})
        result = {"id": artifact_id, "session_id": session_id, "event_id": event["event_id"]}
        connection.execute("UPDATE learning_command SET result_json=? WHERE id=?", (canonical(result), command_id))
        return result


def demo_observations(key, request):
    """Run actual deterministic checks on the explicitly synthetic raw examples."""
    if request["content"] != CONTENTS[key]:
        raise ValueError("fixture analyzer only accepts its exact synthetic example")
    checks = {
        "strip": lambda: "  Nautilus 42  ".strip() == "Nautilus 42",
        "split": lambda: "alpha,,beta".split(",") == ["alpha", "", "beta"],
        "extract": lambda: re.findall(r"\d+", "订单12，退货3") == ["12", "3"],
        "capture": lambda: re.findall(r"\d+", "A12 B3") == ["12", "3"],
    }
    if not checks[key]():
        raise ValueError("synthetic deterministic check failed")
    observations = [ModelObservationDraft(dimension_id="application", stance="supports",
                    statement="演示/合成：脚本实际检查此合成示例的输出与预期相同；不代表用户真实掌握。",
                    scope="演示/合成原始产出")]
    return observations


def demo_counterexample(request):
    if request["content"] != CONTENTS["extract"]:
        raise ValueError("counterexample analyzer only accepts its exact synthetic example")
    assert re.findall(r"\d", "订单12，退货3") == ["1", "2", "3"]
    return [ModelObservationDraft(dimension_id="application", stance="refutes",
        statement="演示/合成：另一写法把多位数字拆开，得到不同表现；请回看原始示例。", scope="演示/合成原始产出")]


def seed(data_dir: str | Path, owner_id: str | None = None, *, demo: bool = False) -> dict:
    db_path = validated_path(data_dir, demo=demo)
    database = open_learning_database(db_path, migrate=False)
    try:
        identities = database.fetchall("SELECT * FROM local_identity" + (" WHERE id=?" if owner_id else ""),
                                       (owner_id,) if owner_id else ())
        if len(identities) != 1:
            raise ValueError("an existing unique owner is required; select --owner-id if needed")
        identity = dict(identities[0])
        owner = identity["id"]
        # Core replay and the database partial unique index both require one
        # running session per owner. A closed fixture must not interrupt it.
        if database.fetchone("SELECT 1 FROM learning_session WHERE owner_id=? AND status='running'", (owner,)):
            raise ValueError("existing running learning session: synthetic history cannot be imported without changing it")
        before = snapshot(database)
        learning = LearningService(database)
        # Prevent LearningService's normal principal hook from installing any
        # non-demo reference data in a target that has not yet installed it.
        learning.standard_package = package("strip")
        principal = learning.principal(identity)
        outcomes, criteria, setups, artifacts = {}, {}, {}, {}
        for key, (label, behavior, condition) in ATOMIC.items():
            if condition is not None:
                definition = package(key)
                seed_standard_package(database, owner, definition)
                outcomes[key] = scoped_id(owner, "outcome", definition.outcome_id)
                criteria[key] = scoped_id(owner, "criterion", definition.criterion_id)
            else:
                outcomes[key] = learning.core.execute(principal, CreateOutcome(object_description=label,
                    behavior=behavior, context_key=CONTEXT), PREFIX + ":outcome:" + key)["id"]
        for key, (label, behavior) in COMPOSITE.items():
            outcomes[key] = learning.core.execute(principal, CreateOutcome(kind="composite",
                object_description=label, behavior=behavior, context_key=CONTEXT), PREFIX + ":outcome:" + key)["id"]
        plan_id = None
        for key, (label, behavior, _) in ATOMIC.items():
            setup = learning.core.execute(principal, ConfirmLearningSetup(plan_id=plan_id,
                original_intent=NOTICE, goal_title="演示：观察文本处理成果与证据", goal_description=NOTICE,
                plan_title=PLAN_TITLE, plan_description=NOTICE, action_title="演示：" + label,
                context_key=CONTEXT, outcome_id=outcomes[key], object_description=label, behavior=behavior,
                outcome_context_key=CONTEXT, criterion_id=criteria.get(key), boundaries=NOTICE,
                stop_conditions="演示：保存一份合成文本处理作答"), PREFIX + ":setup:" + key)
            setups[key] = setup
            plan_id = setup["plan_id"]
        events = EvidenceEventService(database)
        state = StateDerivationService(learning, events)
        review = ReviewService(learning, state, events)
        for key, content in CONTENTS.items():
            artifact = historical_artifact(learning, principal, setups[key], key, content)
            artifacts[key] = artifact["id"]
            if key not in criteria:
                continue
            evidence = EvidenceService(learning, analyzer=lambda request, key=key: demo_observations(key, request), evidence_events=events)
            result = asyncio.run(evidence.analyze(identity, artifact["id"], PREFIX + ":analysis:" + key))
            if result["run"]["status"] != "succeeded":
                raise ValueError("synthetic evidence analysis failed")
            claims = result["claims"]
            if key == "extract":
                # Existing evidence allows one observation per dimension/run;
                # preserve the different check as its own attributable run.
                different = EvidenceService(learning, analyzer=demo_counterexample, evidence_events=events)
                result = asyncio.run(different.analyze(identity, artifact["id"], PREFIX + ":analysis:extract:different"))
                if result["run"]["status"] != "succeeded":
                    raise ValueError("synthetic counterexample analysis failed")
                claims = [*claims, *result["claims"]]
            for claim in claims:
                review.review(identity, claim["id"], "adopt", NOTICE, PREFIX + ":review:" + claim["id"])
        relations = [
            ("root", "clean", "contains"), ("root", "regex", "contains"),
            ("clean", "strip", "contains"), ("clean", "split", "contains"), ("clean", "normalize", "contains"),
            ("regex", "extract", "contains"), ("regex", "groups", "contains"), ("regex", "capture", "contains"),
            ("strip", "split", "prerequisite"), ("groups", "extract", "prerequisite"),
            ("extract", "capture", "equivalent"), ("split", "groups", "overlap"),
        ]
        relation_ids = []
        for left, right, kind in relations:
            rationale = {"contains": "演示：把组成能力放在这个综合成果下。",
                "prerequisite": "演示：个人选择先理解这个成果，再练习后续成果；不阻止任务。",
                "equivalent": "演示：两个声明在此合成情境中描述相同可观察行为，保留各自身份和证据。",
                "overlap": "演示：两者都涉及文本拆分，但分隔符处理与捕获分组的范围不同。"}[kind]
            result = learning.core.execute(principal, CreateRelation(source_outcome_id=outcomes[left],
                target_outcome_id=outcomes[right], relation_type=kind, context_key=CONTEXT, rationale=rationale,
                uncertainty="演示/合成个人组织决定；不能证明客观领域关系或真实掌握。",
                source_refs=[{"kind": "outcome", "id": outcomes[left], "version": 1},
                             {"kind": "outcome", "id": outcomes[right], "version": 1}]),
                PREFIX + ":relation:" + left + ":" + right + ":" + kind)
            relation_ids.append(result["id"])
        graph_service = OutcomeGraph(learning, None)
        graph = graph_service.graph(identity, plan_id)
        if {n["id"] for n in graph["nodes"]} != set(outcomes.values()):
            raise ValueError("demo plan filter did not return exactly the synthetic nodes")
        outcome_review = OutcomeReview(VerificationService(learning, None))
        for key, artifact_id in artifacts.items():
            record = outcome_review.get(identity, outcomes[key])
            if not any(a["artifact_id"] == artifact_id and a["available"] for a in record["artifacts"]):
                raise ValueError("original synthetic artifact is unavailable in OutcomeReview")
            if NOTICE not in learning.artifact(identity, artifact_id, 1)["content"]:
                raise ValueError("synthetic artifact notice is missing")
        if database.fetchone("PRAGMA integrity_check")[0] != "ok" or database.fetchall("PRAGMA foreign_key_check"):
            raise ValueError("demo database integrity check failed")
        after = snapshot(database)
        if any(rows - after[table] for table, rows in before.items()):
            raise ValueError("existing row changed; inspect the target before continuing")
        return {"synthetic_demo": True, "plan_id": plan_id, "plan_title": PLAN_TITLE,
                "outcome_ids": outcomes, "artifact_ids": artifacts, "relation_ids": relation_ids,
                "coverage": {key: next(n["coverage"]["status"] for n in graph["nodes"] if n["id"] == value)
                             for key, value in outcomes.items()},
                "existing_rows_preserved": True, "database_digest": snapshot_digest(after),
                "inserted_rows": {table: sum(rows.values()) - sum(before[table].values())
                                  for table, rows in after.items() if rows != before[table]}}
    finally:
        database.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--owner-id", help="Optional when there is exactly one existing owner")
    parser.add_argument("--demo", action="store_true", help="Explicitly confirm adding synthetic examples")
    args = parser.parse_args()
    print(json.dumps(seed(args.data_dir, args.owner_id, demo=args.demo), ensure_ascii=False, indent=2))
