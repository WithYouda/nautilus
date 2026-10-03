"""Completion evidence must come from the provider, even after a valid state tail."""
import json

import httpx
import pytest

from app.providers import ProviderConfig, ProviderError, build_provider
from app.function_tools import ToolSession, ToolTurn


KINDS = ("openai_compatible", "openai_responses", "google", "anthropic")
PARTIAL = '已输出正文\n<state-run-1>{"step":"next"}</state-run-1>'


def event(name, body):
    return f"event: {name}\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"


def content(kind, text=PARTIAL):
    if kind == "openai_compatible":
        return event("", {"choices": [{"delta": {"content": text}}]})
    if kind == "openai_responses":
        return event("response.output_text.delta", {"type": "response.output_text.delta", "delta": text})
    if kind == "google":
        return event("", {"candidates": [{"content": {"parts": [{"text": text}]}}]})
    return event("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}})


def ending(kind, outcome="complete"):
    if kind == "openai_compatible":
        reason = {"complete": "stop", "truncated": "length", "filtered": "content_filter"}[outcome]
        return event("", {"choices": [{"delta": {}, "finish_reason": reason}]}) + "data: [DONE]\n\n"
    if kind == "openai_responses":
        if outcome == "complete":
            return event("response.completed", {"type": "response.completed", "response": {"status": "completed", "output": []}})
        reason = "max_output_tokens" if outcome == "truncated" else "content_filter"
        return event("response.incomplete", {"type": "response.incomplete", "response": {"status": "incomplete", "incomplete_details": {"reason": reason}}})
    if kind == "google":
        reason = {"complete": "STOP", "truncated": "MAX_TOKENS", "filtered": "SAFETY"}[outcome]
        return event("", {"candidates": [{"finishReason": reason}]})
    reason = {"complete": "end_turn", "truncated": "max_tokens", "filtered": "refusal"}[outcome]
    return event("message_delta", {"type": "message_delta", "delta": {"stop_reason": reason}}) + event("message_stop", {"type": "message_stop"})


def provider(kind, response):
    config = ProviderConfig(base_url="https://provider.example.test/v1", model="fixture-model",
                            api_key="fixture-key", provider_kind=kind, web_search=kind != "openai_compatible")
    return build_provider(config, httpx.MockTransport(lambda _: response))


async def failed_chunks(kind, wire, error_kind):
    chunks = []
    with pytest.raises(ProviderError) as error:
        async for chunk in provider(kind, httpx.Response(200, text=wire)).stream_chat([{"role": "user", "content": "继续"}]):
            chunks.append(chunk)
    assert error.value.kind == error_kind
    assert "".join(chunk.text for chunk in chunks if chunk.kind == "content") == PARTIAL
    return chunks


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_real_terminal_completes_after_incremental_text(kind):
    stream = provider(kind, httpx.Response(200, text=content(kind) + ending(kind))).stream_chat([{"role": "user", "content": "继续"}])
    first = await anext(stream)
    if first.kind == "search_status":
        first = await anext(stream)
    assert first.kind == "content" and first.text == PARTIAL
    rest = [chunk async for chunk in stream]
    assert rest[-1].kind == "completion" and rest[-1].text == "complete"
    if kind != "openai_compatible":
        assert json.loads(rest[-2].text)["status"] == "not_used"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("outcome,error_kind", [("truncated", "output_truncated"), ("filtered", "content_filtered")])
async def test_valid_state_tail_does_not_override_truncation_or_filtering(kind, outcome, error_kind):
    chunks = await failed_chunks(kind, content(kind) + ending(kind, outcome), error_kind)
    assert not any(chunk.kind == "search_status" and json.loads(chunk.text)["status"] == "not_used" for chunk in chunks)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_eof_without_provider_terminal_keeps_partial_text(kind):
    await failed_chunks(kind, content(kind), "protocol_error")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["openai_compatible", "anthropic"])
async def test_transport_end_without_model_finish_reason_keeps_answer_but_is_unknown(kind):
    terminal = "data: [DONE]\n\n" if kind == "openai_compatible" else event("message_stop", {"type": "message_stop"})
    chunks = [chunk async for chunk in provider(kind, httpx.Response(200, text=content(kind) + terminal)).stream_chat([])]
    assert "".join(chunk.text for chunk in chunks if chunk.kind == "content") == PARTIAL
    assert chunks[-1].kind == "completion" and chunks[-1].text == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["openai_compatible", "anthropic"])
async def test_model_finish_without_transport_end_is_incomplete(kind):
    terminal = (event("", {"choices": [{"delta": {}, "finish_reason": "stop"}]}) if kind == "openai_compatible"
                else event("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}))
    await failed_chunks(kind, content(kind) + terminal, "protocol_error")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["incomplete", "failed"])
async def test_responses_terminal_snapshot_must_confirm_completed(status):
    response = {"output": []}
    if status is not None:
        response["status"] = status
    await failed_chunks("openai_responses", content("openai_responses") + event("response.completed", {"type": "response.completed", "response": response}), "protocol_error")


@pytest.mark.asyncio
async def test_responses_completed_event_without_status_is_unknown():
    wire = content("openai_responses") + event("response.completed", {"type": "response.completed", "response": {"output": []}})
    chunks = [chunk async for chunk in provider("openai_responses", httpx.Response(200, text=wire)).stream_chat([])]
    assert "".join(chunk.text for chunk in chunks if chunk.kind == "content") == PARTIAL
    assert chunks[-1].kind == "completion" and chunks[-1].text == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,error_kind", [("model_context_window_exceeded", "output_truncated"), ("pause_turn", "upstream_error"), ("tool_use", "protocol_error"), ("stop_sequence", "protocol_error")])
async def test_anthropic_unfinished_turn_is_not_a_complete_answer(reason, error_kind):
    await failed_chunks("anthropic", content("anthropic") + event("message_delta", {"type": "message_delta", "delta": {"stop_reason": reason}}) + event("message_stop", {"type": "message_stop"}), error_kind)


@pytest.mark.asyncio
async def test_google_preserves_text_in_max_tokens_candidate():
    await failed_chunks("google", event("", {"candidates": [{"content": {"parts": [{"text": PARTIAL}]}, "finishReason": "MAX_TOKENS"}]}), "output_truncated")


class BrokenStream(httpx.AsyncByteStream):
    def __init__(self, wire):
        self.wire = wire

    async def __aiter__(self):
        yield self.wire.encode("utf-8")
        raise httpx.ReadError("fixture stream interrupted")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_network_disconnect_keeps_previously_emitted_text(kind):
    chunks = []
    with pytest.raises(ProviderError) as error:
        async for chunk in provider(kind, httpx.Response(200, stream=BrokenStream(content(kind)))).stream_chat([]):
            chunks.append(chunk)
    assert error.value.kind == "network_error"
    assert "".join(chunk.text for chunk in chunks if chunk.kind == "content") == PARTIAL


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_complete_terminal_without_body_is_not_success(kind):
    with pytest.raises(ProviderError) as error:
        _ = [chunk async for chunk in provider(kind, httpx.Response(200, text=ending(kind))).stream_chat([])]
    assert error.value.kind == "protocol_error"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_upstream_error_after_partial_text_cannot_emit_completion(kind):
    failure = (event("", {"error": {"message": "fixture failure"}}) if kind == "openai_compatible"
               else event("error", {"type": "error", "error": {"message": "fixture failure"}}))
    chunks = await failed_chunks(kind, content(kind) + failure, "upstream_error")
    assert not any(chunk.kind == "completion" for chunk in chunks)


@pytest.mark.asyncio
async def test_responses_refusal_in_terminal_output_keeps_partial_text():
    terminal = event("response.completed", {"type": "response.completed", "response": {
        "status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "fixture refusal"}]}]}})
    await failed_chunks("openai_responses", content("openai_responses") + terminal, "content_filtered")


@pytest.mark.asyncio
async def test_chat_refusal_delta_keeps_partial_text():
    await failed_chunks("openai_compatible", content("openai_compatible") + event("", {"choices": [{"delta": {"refusal": "fixture refusal"}}]}), "content_filtered")


@pytest.mark.asyncio
@pytest.mark.parametrize("status,completion", [("completed", "complete"), (None, "unknown")])
async def test_responses_function_turn_carries_terminal_completion(status, completion):
    output = [{"type": "message", "id": "message-fixture", "role": "assistant",
               "content": [{"type": "output_text", "text": PARTIAL}]}]
    response = {"output": output}
    if status is not None:
        response["status"] = status
    wire = content("openai_responses") + event("response.completed", {"type": "response.completed", "response": response})
    session = ToolSession(provider("openai_responses", httpx.Response(200, text=wire)), [{"role": "user", "content": "继续"}])
    chunks = [chunk async for chunk in session.stream_turn([])]
    turn = chunks[-1]
    assert isinstance(turn, ToolTurn) and turn.calls == []
    assert turn.completion == completion
    assert session.export_turn()["messages"] == output


@pytest.mark.asyncio
async def test_responses_function_turn_rejects_conflicting_terminal_status():
    wire = content("openai_responses") + event("response.completed", {"type": "response.completed", "response": {"status": "incomplete", "output": []}})
    session = ToolSession(provider("openai_responses", httpx.Response(200, text=wire)), [{"role": "user", "content": "继续"}])
    chunks = []
    with pytest.raises(ProviderError) as error:
        async for chunk in session.stream_turn([]):
            chunks.append(chunk)
    assert error.value.kind == "protocol_error"
    assert not any(isinstance(chunk, ToolTurn) for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks if chunk.kind == "content") == PARTIAL


@pytest.mark.asyncio
@pytest.mark.parametrize("done,completion", [(True, "complete"), (False, "unknown")])
async def test_chat_function_final_turn_requires_done_for_explicit_completion(done, completion):
    wire = content("openai_compatible") + event("", {"choices": [{"delta": {}, "finish_reason": "stop"}]})
    if done:
        wire += "data: [DONE]\n\n"
    session = ToolSession(provider("openai_compatible", httpx.Response(200, text=wire)), [{"role": "user", "content": "继续"}])
    chunks = [chunk async for chunk in session.stream_turn([])]
    assert isinstance(chunks[-1], ToolTurn) and chunks[-1].calls == []
    assert chunks[-1].completion == completion
    assert "".join(chunk.text for chunk in chunks[:-1] if chunk.kind == "content") == PARTIAL


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,refusal", [
    ("openai_compatible", event("", {"choices": [{"delta": {"refusal": "fixture refusal"}}]})),
    ("openai_responses", event("response.refusal.delta", {"type": "response.refusal.delta", "delta": "fixture refusal"})),
    ("openai_responses", event("response.completed", {"type": "response.completed", "response": {
        "status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "fixture refusal"}]}]}})),
])
async def test_function_turn_refusal_keeps_partial_text_without_completed_turn(kind, refusal):
    session = ToolSession(provider(kind, httpx.Response(200, text=content(kind) + refusal)), [{"role": "user", "content": "继续"}])
    chunks = []
    with pytest.raises(ProviderError) as error:
        async for chunk in session.stream_turn([]):
            chunks.append(chunk)
    assert error.value.kind == "content_filtered"
    assert not any(isinstance(chunk, ToolTurn) for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks if chunk.kind == "content") == PARTIAL
