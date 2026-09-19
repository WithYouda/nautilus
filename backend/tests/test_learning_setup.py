"""Task 15A: minimal guided setup Core coverage."""

import json

import httpx
import pytest

from app.conversations import ConversationError
from app.core.commands import ConfirmLearningSetup
from app.core.learning import LearningCore
from app.learning_domain import DomainError, Principal
from app.learning_setup import LearningSetupService
from app.learning_service import LearningService
from app.providers import ProviderConfig
from test_learning_domain_schema import domain_rows, learning_database  # noqa: F401


OWNER = Principal.user("owner-a")


class FakeConversations:
    def __init__(self, error: Exception | None = None):
        self.error = error

    def provider_runtime(self, _owner_id: str):
        if self.error:
            raise self.error
        return {}, ProviderConfig(
            base_url="http://127.0.0.1/v1",
            model="setup-model",
            api_key="test-key",
        )


def draft_payload(criterion_id: str | None = "not-a-real-criterion") -> dict:
    return {
        "goal_title": "学会处理日志",
        "goal_description": "从一个小例子开始",
        "plan_title": "日志练习第一步",
        "plan_description": "先完成一个最小示例",
        "action_title": "写一个匹配练习",
        "context_key": "guided",
        "outcome_object": "一个可运行的示例",
        "outcome_behavior": "能解释关键匹配结果",
        "outcome_context_key": "guided",
        "boundaries": "只处理一类日志",
        "stop_conditions": "完成并解释一个示例",
        "time_budget_minutes": 30,
        "recommended_criterion_id": criterion_id,
        "rationale": "先做一个低成本练习",
    }


def setup_service(learning_database, response_text: str, conversations=None):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": response_text}}]},
        )

    learning = LearningService(learning_database)
    return LearningSetupService(
        learning,
        conversations or FakeConversations(),
        transport=httpx.MockTransport(handler),
    )


def identity_payload() -> dict:
    return {
        "id": "owner-a",
        "device_id": "owner-a",
        "display_name": "Synthetic learner",
        "timezone": "UTC",
        "created_at": "2026-09-05T00:00:00Z",
    }


async def test_setup_draft_accepts_json_and_clears_unknown_standard(learning_database):
    service = setup_service(learning_database, json.dumps(draft_payload(), ensure_ascii=False))

    result = await service.draft(identity_payload(), "我想学会处理日志")

    assert result["goal_title"] == "学会处理日志"
    assert result["recommended_criterion_id"] is None


async def test_setup_draft_accepts_json_code_fence(learning_database):
    response = "```json\n" + json.dumps(draft_payload(None), ensure_ascii=False) + "\n```"
    service = setup_service(learning_database, response)

    result = await service.draft(identity_payload(), "我想学会处理日志")

    assert result["action_title"] == "写一个匹配练习"


async def test_setup_draft_rejects_invalid_provider_output(learning_database):
    service = setup_service(learning_database, "不是 JSON")

    with pytest.raises(DomainError, match="setup_draft_invalid"):
        await service.draft(identity_payload(), "我想学会处理日志")


async def test_setup_draft_preserves_manual_fallback_when_provider_is_unavailable(learning_database):
    service = setup_service(
        learning_database,
        "{}",
        conversations=FakeConversations(ConversationError("provider unavailable")),
    )

    with pytest.raises(DomainError, match="setup_provider_unavailable"):
        await service.draft(identity_payload(), "我想学会处理日志")


def setup_command(**overrides) -> ConfirmLearningSetup:
    payload = {
        "original_intent": "我想建立一个可验证的学习起点",
        "goal_title": "理解一个真实主题",
        "goal_description": "从低承诺的第一步开始，逐步校准方向。",
        "plan_title": "第一轮学习计划",
        "plan_description": "先完成一次可复盘的学习会话。",
        "action_title": "完成一次最小学习行动",
        "context_key": "synthetic-context",
        "outcome_id": None,
        "object_description": "一个真实学习对象",
        "behavior": "能用自己的话解释关键内容",
        "outcome_context_key": "synthetic-context",
        "criterion_id": None,
        "boundaries": "只覆盖第一轮学习需要的核心范围",
        "stop_conditions": "完成一次真实产出并记录仍然未知的部分",
        "time_budget_minutes": 30,
    }
    payload.update(overrides)
    return ConfirmLearningSetup(**payload)


def test_confirm_setup_without_standard_creates_one_atomic_learning_chain(domain_rows):
    core = LearningCore(domain_rows)

    result = core.execute(OWNER, setup_command(), "setup-no-standard")

    assert result["setup_id"] == result["id"]
    assert domain_rows.fetchone("SELECT status FROM learning_goal")[0] == "hypothesis"
    assert domain_rows.fetchone("SELECT status FROM learning_plan")[0] == "active"
    assert domain_rows.fetchone("SELECT status FROM learning_action")[0] == "open"
    assert domain_rows.fetchone("SELECT status FROM learning_delegation")[0] == "ready"
    assert domain_rows.fetchone("SELECT criterion_id FROM learning_delegation")[0] is None
    assert domain_rows.fetchone("SELECT COUNT(*) FROM learning_setup")[0] == 1
    assert domain_rows.fetchone("SELECT COUNT(*) FROM learning_event")[0] == 4
    assert domain_rows.fetchone("SELECT COUNT(*) FROM learning_command")[0] == 1


def test_confirm_setup_same_idempotency_key_returns_original_result(domain_rows):
    core = LearningCore(domain_rows)
    command = setup_command()

    first = core.execute(OWNER, command, "setup-retry")
    second = core.execute(OWNER, command, "setup-retry")

    assert second == first
    for table in (
        "learning_goal",
        "learning_plan",
        "learning_action_link",
        "learning_delegation",
        "learning_contract_version",
        "learning_setup",
        "learning_command",
    ):
        assert domain_rows.fetchone(f"SELECT COUNT(*) FROM {table}")[0] == 1
    assert domain_rows.fetchone("SELECT COUNT(*) FROM learning_event")[0] == 4
    assert domain_rows.fetchone("SELECT COUNT(*) FROM learning_action")[0] == 3
    assert domain_rows.fetchone("SELECT COUNT(*) FROM learning_outcome WHERE source='user'")[0] == 3


def test_confirm_setup_persists_user_edited_values(domain_rows):
    core = LearningCore(domain_rows)

    result = core.execute(
        OWNER,
        setup_command(
            original_intent="用户修改后的原始意图",
            goal_title="用户确认的目标标题",
            goal_description="用户确认的目标说明",
            plan_title="用户确认的计划标题",
            plan_description="用户确认的计划说明",
            action_title="用户确认的任务标题",
            object_description="用户确认的成果对象",
            behavior="用户确认的成果行为",
            boundaries="用户确认的学习边界",
            stop_conditions="用户确认的停止条件",
            time_budget_minutes=45,
        ),
        "setup-edited-values",
    )

    goal = domain_rows.fetchone("SELECT * FROM learning_goal")
    plan = domain_rows.fetchone("SELECT * FROM learning_plan")
    action = domain_rows.fetchone(
        "SELECT * FROM learning_action WHERE owner_id=? AND id=?",
        (OWNER.owner_id, result["action_id"]),
    )
    outcome = domain_rows.fetchone(
        "SELECT * FROM learning_outcome WHERE owner_id=? AND id=?",
        (OWNER.owner_id, result["outcome_id"]),
    )
    contract = domain_rows.fetchone(
        "SELECT * FROM learning_contract_version WHERE owner_id=? AND delegation_id=?",
        (OWNER.owner_id, result["delegation_id"]),
    )
    setup = domain_rows.fetchone(
        "SELECT * FROM learning_setup WHERE owner_id=? AND id=?",
        (OWNER.owner_id, result["setup_id"]),
    )

    assert goal["original_intent"] == "用户修改后的原始意图"
    assert goal["title"] == "用户确认的目标标题"
    assert goal["description"] == "用户确认的目标说明"
    assert plan["title"] == "用户确认的计划标题"
    assert plan["description"] == "用户确认的计划说明"
    assert action["title"] == "用户确认的任务标题"
    assert outcome["object_description"] == "用户确认的成果对象"
    assert outcome["behavior"] == "用户确认的成果行为"
    assert contract["boundaries"] == "用户确认的学习边界"
    assert contract["stop_conditions"] == "用户确认的停止条件"
    assert contract["time_budget_minutes"] == 45
    assert setup["original_intent"] == "用户修改后的原始意图"


def test_confirm_setup_with_approved_standard_binds_matching_outcome(domain_rows):
    core = LearningCore(domain_rows)

    result = core.execute(
        OWNER,
        setup_command(
            outcome_id="outcome-a",
            object_description="Synthetic object",
            behavior="Synthetic behavior",
            criterion_id="criterion-a-approved",
        ),
        "setup-approved-standard",
    )

    delegation = domain_rows.fetchone("SELECT * FROM learning_delegation")
    contract = domain_rows.fetchone("SELECT * FROM learning_contract_version")
    assert result["outcome_id"] == "outcome-a"
    assert delegation["criterion_id"] == "criterion-a-approved"
    assert contract["criterion_id"] == "criterion-a-approved"


def test_setup_replay_rebuilds_goal_plan_action_link_and_delegation_relation(domain_rows):
    core = LearningCore(domain_rows)
    created = core.execute(OWNER, setup_command(), "setup-replay")

    replay = core.replay(OWNER)

    assert replay["status"] == "succeeded"
    assert replay["event_count"] == 4
    assert replay["aggregate_count"] == 3
    setup = domain_rows.fetchone("SELECT * FROM learning_setup")
    link = domain_rows.fetchone("SELECT * FROM learning_action_link")
    plan = domain_rows.fetchone("SELECT * FROM learning_plan")
    goal = domain_rows.fetchone("SELECT * FROM learning_goal")
    delegation = domain_rows.fetchone("SELECT * FROM learning_delegation")
    contract = domain_rows.fetchone("SELECT * FROM learning_contract_version")

    assert setup["id"] == created["setup_id"]
    assert setup["goal_id"] == goal["id"]
    assert setup["plan_id"] == plan["id"]
    assert setup["action_id"] == link["action_id"]
    assert plan["goal_id"] == goal["id"]
    assert delegation["action_id"] == setup["action_id"]
    assert delegation["outcome_id"] == setup["outcome_id"]
    assert contract["delegation_id"] == delegation["id"]
    assert domain_rows.fetchone("SELECT id FROM learning_action WHERE id='action-b'") is not None
    assert domain_rows.fetchone("SELECT id FROM learning_outcome WHERE id='outcome-b'") is not None


def test_confirm_setup_failure_rolls_back_all_events_and_projections(domain_rows):
    core = LearningCore(domain_rows)
    tables = (
        "learning_goal",
        "learning_plan",
        "learning_action",
        "learning_action_link",
        "learning_delegation",
        "learning_contract_version",
        "learning_outcome",
        "learning_setup",
        "learning_event",
        "learning_command",
        "learning_stream_head",
        "learning_projection_position",
    )
    before = {
        table: domain_rows.fetchone(f"SELECT COUNT(*) FROM {table}")[0]
        for table in tables
    }
    domain_rows.connection.executescript(
        """
        CREATE TRIGGER fail_guided_setup
        BEFORE INSERT ON learning_setup
        BEGIN
            SELECT RAISE(ABORT, 'synthetic guided setup failure');
        END;
        """
    )

    with pytest.raises(DomainError, match="storage_failure"):
        core.execute(OWNER, setup_command(), "setup-rollback")

    for table in tables:
        assert domain_rows.fetchone(f"SELECT COUNT(*) FROM {table}")[0] == before[table]
    assert domain_rows.fetchone(
        "SELECT COUNT(*) FROM learning_audit WHERE operation='ConfirmLearningSetup' AND result='rejected'"
    )[0] == 1
    assert not domain_rows.connection.in_transaction
