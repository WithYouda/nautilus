from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from app.core.commands import CreateDelegation, CreateLearningAction, CreateOutcome, StartSession
from app.core.learning import LearningCore
from app.learning_domain import DomainError, Principal
from app.learning_service import LearningService
from app.providers import ProviderConfig
from app.verification import VerificationService
from test_learning_domain_schema import learning_database  # noqa: F401


OWNER = Principal.user("owner-a")
IDENTITY = {
    "id": "owner-a",
    "device_id": "owner-a-device",
    "display_name": "Synthetic learner",
    "timezone": "UTC",
    "created_at": "2026-09-05T00:00:00Z",
}


CHALLENGE = json.dumps(
    {
        "questions": [
            {
                "id": "q1",
                "type": "scenario",
                "prompt": "请说明一个实际场景中如何完成这项任务。",
                "source_urls": ["https://docs.python.org/3/library/re.html"],
                "pass_criteria": "说明关键步骤和依据",
                "answer_key": "服务端评估依据，不应返回给用户",
            }
        ]
    },
    ensure_ascii=False,
)
PASS = json.dumps(
    {
        "passed": True,
        "stop_condition_met": True,
        "question_feedback": [{"question_id": "q1", "feedback": "已说明关键步骤，建议比较不同输入。", "reference_answer": "先说明步骤，再检验边界。", "follow_up_questions": [], "unmet_requirements": []}],
        "feedback": "回答包含关键步骤。",
        "next_step": "可以结束本次任务。",
    },
    ensure_ascii=False,
)
STOP_NOT_MET = json.dumps(
    {
        "passed": True,
        "stop_condition_met": False,
        "question_feedback": json.loads(PASS)["question_feedback"],
        "feedback": "回答基本正确，但还没有完成约定的停止条件。",
        "next_step": "补充一次独立实践。",
    },
    ensure_ascii=False,
)
FAIL = json.dumps(
    {
        "passed": False,
        "stop_condition_met": False,
        "question_feedback": [{"question_id": "q1", "feedback": "请补充关键依据和独立说明。", "reference_answer": "先说明步骤，再检验边界。", "follow_up_questions": [], "unmet_requirements": ["缺少关键依据"]}],
        "feedback": "还缺少关键依据。",
        "next_step": "补充一次独立说明。",
    },
    ensure_ascii=False,
)


def for_material(response):
    result = json.loads(response)
    for item in result['question_feedback']:
        item['question_id'] = 'material'
    return json.dumps(result, ensure_ascii=False)


MATERIAL_PASS = for_material(PASS)
MATERIAL_FAIL = for_material(FAIL)


class FakeConversations:
    def provider_runtime(self, _owner_id: str):
        return {}, ProviderConfig(
            base_url="http://127.0.0.1/v1",
            model="verification-model",
            api_key="test-key",
        )


def response_transport(responses: list[str]):
    remaining = list(responses)

    def handler(_request: httpx.Request) -> httpx.Response:
        response = remaining.pop(0)
        if json.loads(_request.content).get('stream'):
            event = json.dumps({'choices': [{'delta': {'content': response}}]})
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=f'data: {event}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={"choices": [{"message": {"content": response}}]})

    return httpx.MockTransport(handler)


def create_context(database, key: str = "context", *, start: bool = True) -> dict[str, str]:
    core = LearningCore(database)
    action = core.execute(
        OWNER,
        CreateLearningAction(title=f"Verification action {key}", context_key="verification-context"),
        f"action-{key}",
    )
    outcome = core.execute(
        OWNER,
        CreateOutcome(
            object_description="一个可验证对象",
            behavior="能独立解释关键步骤",
            context_key="verification-context",
        ),
        f"outcome-{key}",
    )
    delegation = core.execute(
        OWNER,
        CreateDelegation(
            action_id=action["id"],
            outcome_id=outcome["id"],
            criterion_id=None,
            boundaries="只覆盖本次学习范围",
            stop_conditions="完成一次独立说明",
            time_budget_minutes=30,
            expected_version=1,
        ),
        f"delegation-{key}",
    )
    context = {"action_id": action["id"], "delegation_id": delegation["id"], "session_id": None}
    if start:
        session = core.execute(
            OWNER,
            StartSession(delegation_id=delegation["id"], expected_version=2),
            f"session-{key}",
        )
        context["session_id"] = session["id"]
    return context


def verification_service(database, responses: list[str]) -> VerificationService:
    return VerificationService(
        LearningService(database),
        FakeConversations(),
        transport=response_transport(responses),
    )


async def submit_evaluate(service, identity, verification_id, payload):
    saved = await service.submit(identity, verification_id, {
        **{key: value for key, value in payload.items() if key != "stop_condition_confirmed"},
        "request_key": str(uuid4()),
    })
    assert saved["status"] == "ready"
    evaluated = await service.evaluate(identity, verification_id, saved["latest_submission_id"], str(uuid4()))
    if payload.get("stop_condition_confirmed") and evaluated["result"] and evaluated["result"]["passed"] and evaluated["stop_condition_met"]:
        return service.confirm(identity, verification_id, evaluated["latest_submission_id"], evaluated["evaluation"]["id"])
    return evaluated


@pytest.mark.asyncio
async def test_ai_challenge_hides_answer_and_completion_closes_learning_action(learning_database):
    context = create_context(learning_database, "pass")
    service = verification_service(learning_database, [CHALLENGE, PASS])

    started = await service.start(
        IDENTITY,
        {**context, "mode": "ai_challenge"},
        "verification-pass",
    )
    public_challenge = json.dumps(started["challenge"], ensure_ascii=False)
    assert "answer_key" not in public_challenge
    assert "pass_criteria" not in public_challenge
    assert started["status"] == "ready"

    submitted = await submit_evaluate(
        service, IDENTITY,
        started["id"],
        {"responses": {"q1": "我会先说明步骤，再用一个真实场景验证结果。"}, "stop_condition_confirmed": True},
    )

    assert submitted["status"] == "passed"
    assert submitted["result"]["passed"] is True
    assert "answer_key" not in json.dumps(submitted, ensure_ascii=False)
    assert learning_database.fetchone("SELECT status FROM learning_action")[0] == "completed"
    assert learning_database.fetchone("SELECT status FROM learning_delegation")[0] == "completed"
    assert learning_database.fetchone("SELECT status FROM learning_session")[0] == "ended"
    with pytest.raises(DomainError, match="action_not_open"):
        LearningCore(learning_database).execute(
            OWNER,
            StartSession(delegation_id=context["delegation_id"], expected_version=4),
            "session-after-completion",
        )
    assert learning_database.fetchone("SELECT answer_key_json FROM learning_verification")[0]


@pytest.mark.asyncio
async def test_failed_or_unconfirmed_verification_does_not_complete_action(learning_database):
    context = create_context(learning_database, "unconfirmed")
    service = verification_service(learning_database, [CHALLENGE, PASS])
    started = await service.start(IDENTITY, {**context, "mode": "ai_challenge"}, "verification-unconfirmed")

    submitted = await submit_evaluate(
        service, IDENTITY,
        started["id"],
        {"responses": {"q1": "完成了说明。"}, "stop_condition_confirmed": False},
    )

    assert submitted["status"] == "submitted"
    assert submitted["stop_condition_confirmed"] is False
    assert learning_database.fetchone("SELECT status FROM learning_action")[0] == "open"
    assert learning_database.fetchone("SELECT status FROM learning_delegation")[0] == "active"
    assert learning_database.fetchone("SELECT status FROM learning_session")[0] == "running"


@pytest.mark.asyncio
async def test_passed_answers_without_stop_condition_do_not_complete_action(learning_database):
    context = create_context(learning_database, "stop-not-met")
    service = verification_service(learning_database, [CHALLENGE, STOP_NOT_MET])
    started = await service.start(IDENTITY, {**context, "mode": "ai_challenge"}, "verification-stop-not-met")

    submitted = await submit_evaluate(
        service, IDENTITY,
        started["id"],
        {"responses": {"q1": "回答了题目。"}, "stop_condition_confirmed": True},
    )

    assert submitted["status"] == "submitted"
    assert submitted["stop_condition_met"] is False
    assert learning_database.fetchone("SELECT status FROM learning_action")[0] == "open"


@pytest.mark.asyncio
async def test_failed_verification_can_be_retried_without_completing_until_passed(learning_database):
    context = create_context(learning_database, "retry")
    service = verification_service(learning_database, [CHALLENGE, FAIL, PASS])
    started = await service.start(IDENTITY, {**context, "mode": "ai_challenge"}, "verification-retry")

    failed = await submit_evaluate(
        service, IDENTITY,
        started["id"],
        {"responses": {"q1": "不完整的回答。"}, "stop_condition_confirmed": True},
    )
    assert failed["status"] == "failed"
    assert learning_database.fetchone("SELECT status FROM learning_action")[0] == "open"

    passed = await submit_evaluate(
        service, IDENTITY,
        started["id"],
        {"responses": {"q1": "补充了独立说明和实际依据。"}, "stop_condition_confirmed": True},
    )
    assert passed["status"] == "passed"
    assert learning_database.fetchone("SELECT status FROM learning_action")[0] == "completed"


@pytest.mark.asyncio
async def test_user_material_mode_evaluates_material_without_returning_private_content(learning_database):
    context = create_context(learning_database, "material")
    service = verification_service(learning_database, [MATERIAL_PASS])
    started = await service.start(IDENTITY, {**context, "mode": "user_material"}, "verification-material")
    private_material = "我的题目、标准答案和个人解题过程"

    submitted = await submit_evaluate(
        service, IDENTITY,
        started["id"],
        {"material": private_material, "learner_work": "我独立完成并说明了过程", "stop_condition_confirmed": True},
    )

    assert submitted["status"] == "passed"
    assert private_material not in json.dumps(submitted, ensure_ascii=False)
    assert private_material not in json.dumps(service.list(IDENTITY), ensure_ascii=False)
    assert private_material in learning_database.fetchone("SELECT content FROM learning_raw_artifact")[0]


@pytest.mark.asyncio
async def test_verification_request_key_conflict_and_owner_isolation_are_rejected(learning_database):
    context = create_context(learning_database, "owner")
    service = verification_service(learning_database, [CHALLENGE])
    await service.start(IDENTITY, {**context, "mode": "ai_challenge"}, "shared-request")

    other_context = create_context(learning_database, "other", start=False)
    with pytest.raises(DomainError, match="idempotency_conflict"):
        await service.start(IDENTITY, {**other_context, "mode": "ai_challenge"}, "shared-request")

    with pytest.raises(DomainError, match="not_found"):
        await service.start(
            {**IDENTITY, "id": "owner-b", "device_id": "owner-b-device"},
            {**context, "mode": "user_material"},
            "foreign-request",
        )


@pytest.mark.asyncio
async def test_generation_failure_does_not_consume_request_and_can_retry(learning_database):
    context = create_context(learning_database, "generation")
    service = verification_service(learning_database, ["not json", CHALLENGE])

    with pytest.raises(DomainError, match="verification_invalid"):
        await service.start(IDENTITY, {**context, "mode": "ai_challenge"}, "retry-generation")

    retried = await service.start(IDENTITY, {**context, "mode": "ai_challenge"}, "retry-generation")
    assert retried["status"] == "ready"
