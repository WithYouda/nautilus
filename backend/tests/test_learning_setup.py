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

    with pytest.raises(DomainError, match="setup_invalid_json"):
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


def test_add_step_keeps_goal_and_plan_and_replays_idempotently(domain_rows):
    core = LearningCore(domain_rows)
    first = core.execute(OWNER, setup_command(), "initial-plan")
    goal_before = dict(domain_rows.fetchone("SELECT * FROM learning_goal"))
    plan_before = dict(domain_rows.fetchone("SELECT * FROM learning_plan"))
    command = setup_command(plan_id=first["plan_id"], action_title="第二步", goal_title="不应覆盖目标", plan_title="不应重命名计划")
    second = core.execute(OWNER, command, "next-step")
    assert core.execute(OWNER, command, "next-step") == second
    assert second["plan_id"] == first["plan_id"]
    assert second["goal_id"] == first["goal_id"]
    assert second["action_id"] != first["action_id"]
    assert dict(domain_rows.fetchone("SELECT * FROM learning_goal")) == goal_before
    assert dict(domain_rows.fetchone("SELECT * FROM learning_plan")) == plan_before
    assert domain_rows.fetchone("SELECT COUNT(*) FROM learning_setup")[0] == 2
    assert domain_rows.fetchone("SELECT COUNT(*) FROM learning_action_link WHERE plan_id=?", (first["plan_id"],))[0] == 2
    before = [dict(row) for row in domain_rows.fetchall("SELECT * FROM learning_setup ORDER BY id")]
    assert core.replay(OWNER)["status"] == "succeeded"
    assert [dict(row) for row in domain_rows.fetchall("SELECT * FROM learning_setup ORDER BY id")] == before
    assert dict(domain_rows.fetchone("SELECT * FROM learning_goal")) == goal_before
    assert dict(domain_rows.fetchone("SELECT * FROM learning_plan")) == plan_before


@pytest.mark.parametrize("case", ["missing", "foreign", "inactive"])
def test_add_step_rejects_inaccessible_plan_atomically(domain_rows, case):
    core = LearningCore(domain_rows)
    first = core.execute(OWNER, setup_command(), "initial-plan")
    principal = Principal.user("owner-b") if case == "foreign" else OWNER
    plan_id = "missing" if case == "missing" else first["plan_id"]
    if case == "inactive":
        with domain_rows.transaction() as connection:
            connection.execute("UPDATE learning_plan SET status='archived' WHERE id=?", (plan_id,))
    tables = ["learning_goal", "learning_plan", "learning_setup", "learning_event", "learning_action", "learning_outcome", "learning_delegation"]
    before = {name: domain_rows.fetchone(f"SELECT COUNT(*) FROM {name}")[0] for name in tables}
    with pytest.raises(DomainError):
        core.execute(principal, setup_command(plan_id=plan_id), "invalid-step")
    assert {name: domain_rows.fetchone(f"SELECT COUNT(*) FROM {name}")[0] for name in tables} == before


async def test_setup_requests_complete_json_with_enough_room_for_reasoning(learning_database):
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if payload['max_tokens'] < 8192:
            return httpx.Response(200, json={'choices': [{'finish_reason': 'length', 'message': {'content': '{'}}]})
        assert payload['response_format'] == {'type': 'json_object'}
        prompt = json.loads(payload['messages'][-1]['content'])
        schema = prompt['output_schema']
        assert 'stop_conditions' in schema['required']
        assert schema['properties']['time_budget_minutes']['type'] == 'integer'
        assert schema['properties']['goal_title']['maxLength'] == 200
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(draft_payload(None))}}]})

    service = LearningSetupService(LearningService(learning_database), FakeConversations(), transport=httpx.MockTransport(handler))
    result = await service.draft(identity_payload(), '在已有目标和计划中继续下一步')
    assert result['action_title'] == draft_payload(None)['action_title']
    assert len(requests) == 1
    assert learning_database.fetchone('SELECT COUNT(*) FROM learning_setup')[0] == 0


@pytest.mark.parametrize('scenario,expected', [
    ('timeout', 'setup_timeout'), ('network', 'setup_network_error'),
    (401, 'setup_auth_error'), (429, 'setup_rate_limited'), (404, 'setup_endpoint_not_found'),
    (400, 'setup_request_error'), (503, 'setup_upstream_error'),
    ('length', 'setup_output_truncated'), ('reasoning', 'setup_reasoning_only'),
    ('filtered', 'setup_content_filtered'), ('empty', 'setup_protocol_error'),
    ('json', 'setup_invalid_json'), ('fields', 'setup_draft_invalid'), ('blank', 'setup_draft_invalid'),
])
async def test_setup_failures_remain_distinct_without_exposing_responses(learning_database, scenario, expected):
    from fastapi import HTTPException
    from app.routers.learning import _raise_learning_error
    from app.learning_setup import SETUP_FAILURE_MESSAGES
    calls = []
    private_marker = 'SYNTHETIC_PRIVATE_RESPONSE'

    def handler(request):
        calls.append(request)
        if scenario == 'timeout':
            raise httpx.ReadTimeout(private_marker, request=request)
        if scenario == 'network':
            raise httpx.ConnectError(private_marker, request=request)
        if isinstance(scenario, int):
            return httpx.Response(scenario, json={'error': {'message': private_marker}})
        content = json.dumps(draft_payload(None))
        choice = {'finish_reason': 'stop', 'message': {'content': content}}
        if scenario == 'length':
            choice['finish_reason'] = 'length'
        elif scenario == 'reasoning':
            choice['message'] = {'content': None, 'reasoning_content': private_marker}
        elif scenario == 'filtered':
            choice['finish_reason'] = 'content_filter'
        elif scenario == 'empty':
            choice['message']['content'] = None
        elif scenario == 'json':
            choice['message']['content'] = private_marker
        elif scenario == 'fields':
            choice['message']['content'] = json.dumps({'goal_title': private_marker})
        elif scenario == 'blank':
            choice['message']['content'] = json.dumps({**draft_payload(None), 'stop_conditions': '   '})
        return httpx.Response(200, json={'choices': [choice]})

    service = LearningSetupService(LearningService(learning_database), FakeConversations(), transport=httpx.MockTransport(handler))
    with pytest.raises(DomainError) as failure:
        await service.draft(identity_payload(), '合成下一步')
    assert failure.value.code == expected
    with pytest.raises(HTTPException) as response:
        _raise_learning_error(failure.value)
    assert response.value.detail == {'kind': expected, 'message': SETUP_FAILURE_MESSAGES[expected]}
    assert private_marker not in str(response.value.detail)
    assert len(calls) == 1  # Never silently incur repeated model requests.
    assert learning_database.fetchone('SELECT COUNT(*) FROM learning_usage_event')[0] == 0
    assert learning_database.fetchone('SELECT COUNT(*) FROM learning_setup')[0] == 0
