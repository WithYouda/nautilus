import asyncio
import json

import httpx
import pytest

from app.conversations import ConversationError
from app.learning_domain import DomainError
from app.providers import ProviderConfig, build_provider
from app.routers.learning import _raise_learning_error
from fastapi import HTTPException
from test_learning_verifications import CHALLENGE, IDENTITY, PASS, create_context, verification_service
from test_learning_domain_schema import learning_database  # noqa: F401


@pytest.mark.asyncio
async def test_deepseek_json_request_and_math_answer_isolation(learning_database):
    context = create_context(learning_database)
    service = verification_service(learning_database, [])
    def handler(request):
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["max_tokens"] >= 8192
        prompt = json.loads(payload["messages"][1]["content"])
        assert prompt["schema"]["questions"][0]["type"] == "short_response"
        challenge = json.loads(CHALLENGE)
        challenge["questions"][0]["prompt"] = r"解释 \(x^2\) 与 $x$ 的关系。"
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "reasoning_content": "Synthetic private reasoning", "content": json.dumps(challenge),
        }}]})
    service.transport = httpx.MockTransport(handler)
    result = await service.start(IDENTITY, {**context, "mode": "ai_challenge"}, "json")
    assert r"\(x^2\)" in result["challenge"]["questions"][0]["prompt"]
    assert "answer_key" not in json.dumps(result)
    assert "Synthetic private reasoning" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,choice,code", [
    (401, None, "verification_auth_error"),
    (429, None, "verification_rate_limited"),
    (404, None, "verification_endpoint_not_found"),
    (400, None, "verification_request_error"),
    (503, None, "verification_upstream_error"),
    (200, {"finish_reason": "length", "message": {"content": CHALLENGE}}, "verification_output_truncated"),
    (200, {"message": {"content": None, "reasoning_content": "synthetic"}}, "verification_reasoning_only"),
    (200, {"message": {"content": "not JSON"}}, "verification_invalid"),
])
async def test_generation_errors_are_actionable_private_and_retryable(learning_database, status, choice, code):
    context = create_context(learning_database)
    service = verification_service(learning_database, [])
    service.transport = httpx.MockTransport(lambda _: httpx.Response(status, json=
        {"choices": [choice]} if choice else {"error": {"message": "synthetic-private-body test-key"}}))
    with pytest.raises(DomainError) as failure:
        await service.start(IDENTITY, {**context, "mode": "ai_challenge"}, "retry")
    assert failure.value.code == code
    assert learning_database.fetchone("SELECT COUNT(*) FROM learning_verification")[0] == 0
    with pytest.raises(HTTPException) as public:
        _raise_learning_error(failure.value)
    assert public.value.detail["kind"] == code
    assert "synthetic-private-body" not in str(public.value.detail)
    assert "test-key" not in str(public.value.detail)
    service.transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [{"message": {"content": CHALLENGE}}]}))
    assert (await service.start(IDENTITY, {**context, "mode": "ai_challenge"}, "retry"))["status"] == "ready"


@pytest.mark.asyncio
async def test_overall_timeout_is_classified_without_creating_attempt(learning_database):
    context = create_context(learning_database)
    service = verification_service(learning_database, [])
    service.conversations.provider_runtime = lambda _: ({}, ProviderConfig("https://api.deepseek.com", "synthetic-model", "synthetic-key", timeout_seconds=0.01))
    async def handler(_):
        await asyncio.sleep(0.1)
        return httpx.Response(200)
    service.transport = httpx.MockTransport(handler)
    with pytest.raises(DomainError, match="verification_timeout"):
        await service.start(IDENTITY, {**context, "mode": "ai_challenge"}, "timeout")
    assert learning_database.fetchone("SELECT COUNT(*) FROM learning_verification")[0] == 0


@pytest.mark.asyncio
async def test_room_selection_used_for_generation_and_evaluation_no_silent_fallback(learning_database):
    context = create_context(learning_database)
    service = verification_service(learning_database, [CHALLENGE, PASS])
    learning_database.connection.execute("INSERT INTO learning_room_conversation VALUES (?,?,?,?)", (IDENTITY["id"], context["session_id"], "synthetic-conversation", "2026-09-22T00:00:00Z"))
    calls = []
    def selected(owner, conversation):
        calls.append((owner, conversation))
        return {}, ProviderConfig("https://api.deepseek.com", "synthetic-selected-model", "synthetic-key"), {}
    def default(_):
        raise AssertionError("must not use global default")
    service.conversations.runtime_for_conversation = selected
    service.conversations.provider_runtime = default
    started = await service.start(IDENTITY, {**context, "mode": "ai_challenge"}, "selected")
    saved = await service.submit(IDENTITY, started["id"], {"responses": {"q1": "Synthetic explanation"}, "request_key": "save"})
    result = await service.evaluate(IDENTITY, started["id"], saved["latest_submission_id"], "evaluate")
    assert result["result"]["passed"]
    assert len(calls) == 2
    def missing(*_):
        raise ConversationError("synthetic unavailable selection")
    service.conversations.runtime_for_conversation = missing
    with pytest.raises(DomainError, match="verification_provider_unavailable"):
        await service.start(IDENTITY, {**context, "mode": "ai_challenge"}, "no-fallback")


@pytest.mark.asyncio
async def test_embedded_think_block_is_not_parsed_as_final_json():
    provider = build_provider(ProviderConfig("https://api.deepseek.com", "synthetic-model", "synthetic-key"),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [{"message": {
            "content": '<think>synthetic internal notes</think>```json\n{"ok":true}\n```',
        }}]})))
    text = await provider.generate_text([], json_mode=True)
    assert text == '```json\n{"ok":true}\n```'


@pytest.mark.asyncio
async def test_literal_think_inside_json_is_not_rewritten():
    content = json.dumps({"prompt": "Explain the literal <think> tag."})
    provider = build_provider(ProviderConfig("https://api.deepseek.com", "synthetic-model", "synthetic-key"),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})))
    assert await provider.generate_text([], json_mode=True) == content


@pytest.mark.asyncio
async def test_saved_answers_survive_provider_error_with_safe_message(learning_database):
    context = create_context(learning_database)
    service = verification_service(learning_database, [])
    started = await service.start(IDENTITY, {**context, "mode": "user_material"}, "start")
    saved = await service.submit(IDENTITY, started["id"], {"learner_work": "Synthetic answer", "request_key": "save"})
    service.transport = httpx.MockTransport(lambda _: httpx.Response(429, json={"error": {"message": "private echo"}}))
    result = await service.evaluate(IDENTITY, started["id"], saved["latest_submission_id"], "evaluate")
    assert result["evaluation"]["reason"] == "verification_rate_limited"
    assert "额度" in result["evaluation"]["message"]
    assert result["latest_submission_id"] == saved["latest_submission_id"]
    assert "private echo" not in json.dumps(result)
