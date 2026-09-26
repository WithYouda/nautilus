import json
from types import SimpleNamespace

import httpx
import pytest

from app.function_tools import ToolSession, ToolTurn
from app.native_providers import AnthropicProvider, GoogleProvider, OpenAIResponsesProvider
from app.providers import OpenAICompatibleProvider, ProviderError


def cfg(kind):
    return SimpleNamespace(base_url="https://api.example.test/v1beta" if kind == "google" else "https://api.example.test/v1",
                           model="test", api_key="sk-private-test-secret", timeout_seconds=5,
                           provider_kind=kind, web_search=True)


def sse(*events):
    return httpx.Response(200, text="".join(f"event: {name}\ndata: {json.dumps(body)}\n\n" for name, body in events))


TOOL = {"name": "search", "description": "Search", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}


async def collect(session, *, allow=True):
    return [item async for item in session.stream_turn([TOOL], allow_tools=allow)]


@pytest.mark.asyncio
async def test_chat_split_calls_and_deepseek_reasoning_roundtrip():
    requests = []
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return sse(("", {"choices": [{"delta": {"reasoning_content": "think", "tool_calls": [{"index": 0, "id": "call_", "function": {"name": "sea", "arguments": '{"q":'}}]}, "finish_reason": None}]}),
                       ("", {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "1", "function": {"name": "rch", "arguments": '"x"}'}}]}, "finish_reason": "tool_calls"}]}))
        return sse(("", {"choices": [{"delta": {"content": "answer"}, "finish_reason": "stop"}]}))
    session = ToolSession(OpenAICompatibleProvider(cfg("openai_compatible"), httpx.MockTransport(handler)), [{"role": "user", "content": "q"}])
    first = await collect(session)
    assert first[0].kind == "reasoning"
    turn = first[-1]
    assert turn.calls[0].id == "call_1"
    assert turn.calls[0].arguments == '{"q":"x"}'
    session.append_results(turn, [{"call_id": "call_1", "content": "found"}])
    second = await collect(session)
    assert second[-1].calls == []
    assert requests[0]["tools"][0]["function"]["name"] == "search"
    assert requests[1]["messages"][-2]["reasoning_content"] == "think"
    assert requests[1]["messages"][-1] == {"role": "tool", "tool_call_id": "call_1", "content": "found"}


@pytest.mark.asyncio
async def test_responses_call_id_and_reasoning_item_roundtrip():
    requests = []
    reasoning = {"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque"}
    function = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "search", "arguments": '{"q":"x"}'}
    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return sse(("response.reasoning_summary_text.delta", {"type": "response.reasoning_summary_text.delta", "delta": "summary"}),
                       ("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": reasoning}),
                       ("response.output_item.done", {"type": "response.output_item.done", "output_index": 1, "item": function}),
                       ("response.completed", {"type": "response.completed", "response": {"output": [reasoning, function]}}))
        return sse(("response.output_text.delta", {"type": "response.output_text.delta", "delta": "answer"}),
                   ("response.completed", {"type": "response.completed", "response": {"output": [{"type": "message", "content": [{"type": "output_text", "text": "answer"}]}]}}))
    session = ToolSession(OpenAIResponsesProvider(cfg("openai_responses"), httpx.MockTransport(handler)), [{"role": "user", "content": "q"}])
    first = await collect(session)
    assert first[0].kind == "reasoning"
    turn = first[-1]
    assert turn.calls[0].id == "call_1"
    session.append_results(turn, [{"call_id": "call_1", "content": "found"}])
    await collect(session)
    assert requests[0]["tools"][0]["strict"] is False
    assert requests[0]["store"] is False
    assert requests[1]["input"][-3] == reasoning
    assert requests[1]["input"][-1] == {"type": "function_call_output", "call_id": "call_1", "output": "found"}


@pytest.mark.asyncio
async def test_google_signature_and_function_response_id():
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return sse(("", {"candidates": [{"content": {"parts": [{"functionCall": {"id": "call_1", "name": "search", "args": {"q": "x"}}, "thoughtSignature": "opaque"}]}, "finishReason": "STOP"}]}))
        return sse(("", {"candidates": [{"content": {"parts": [{"text": "answer"}]}, "finishReason": "STOP"}]}))
    session = ToolSession(GoogleProvider(cfg("google"), httpx.MockTransport(handler)), [{"role": "user", "content": "q"}])
    turn = (await collect(session))[-1]
    session.append_results(turn, [{"call_id": "call_1", "content": "found"}])
    await collect(session)
    assert "functionDeclarations" in requests[0]["tools"][0]
    assert requests[1]["contents"][-2]["parts"][0]["thoughtSignature"] == "opaque"
    assert requests[1]["contents"][-1]["parts"][0]["functionResponse"]["id"] == "call_1"


@pytest.mark.asyncio
async def test_anthropic_thinking_signature_and_tool_result():
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return sse(("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}}),
                       ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "think"}}),
                       ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "opaque"}}),
                       ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tool_1", "name": "search", "input": {}}}),
                       ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"q":"x"}'}}),
                       ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use"}}),
                       ("message_stop", {"type": "message_stop"}))
        return sse(("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                   ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "answer"}}),
                   ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}),
                   ("message_stop", {"type": "message_stop"}))
    session = ToolSession(AnthropicProvider(cfg("anthropic"), httpx.MockTransport(handler)), [{"role": "user", "content": "q"}])
    turn = (await collect(session))[-1]
    session.append_results(turn, [{"call_id": "tool_1", "content": "found"}])
    await collect(session)
    assert requests[0]["tools"][0]["input_schema"] == TOOL["parameters"]
    assert requests[1]["messages"][-2]["content"][0]["signature"] == "opaque"
    assert requests[1]["messages"][-1]["content"][0]["tool_use_id"] == "tool_1"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,cls", [("openai_compatible", OpenAICompatibleProvider), ("openai_responses", OpenAIResponsesProvider), ("google", GoogleProvider), ("anthropic", AnthropicProvider)])
async def test_disable_tools_wire(kind, cls):
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        if kind == "openai_compatible":
            return sse(("", {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}))
        if kind == "openai_responses":
            return sse(("response.completed", {"type": "response.completed", "response": {"output": []}}))
        if kind == "google":
            return sse(("", {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}))
        return sse(("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": "ok"}}),
                   ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}),
                   ("message_stop", {"type": "message_stop"}))
    session = ToolSession(cls(cfg(kind), httpx.MockTransport(handler)), [{"role": "user", "content": "q"}])
    output = await collect(session, allow=False)
    assert isinstance(output[-1], ToolTurn)
    if kind == "google":
        assert seen[0]["toolConfig"]["functionCallingConfig"]["mode"] == "NONE"
    elif kind == "anthropic":
        assert seen[0]["tool_choice"] == {"type": "none"}
    else:
        assert seen[0]["tool_choice"] == "none"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["truncated", "oversize", "http_error"])
async def test_incomplete_or_bad_call_never_yields_turn(mode):
    def handler(request):
        if mode == "http_error":
            return httpx.Response(500, text="sk-private-test-secret")
        args = "x" * 20001 if mode == "oversize" else '{"q":"x"}'
        finish = "tool_calls" if mode == "oversize" else "length"
        return sse(("", {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "search", "arguments": args}}]}, "finish_reason": finish}]}))
    session = ToolSession(OpenAICompatibleProvider(cfg("openai_compatible"), httpx.MockTransport(handler)), [{"role": "user", "content": "q"}])
    emitted = []
    with pytest.raises(ProviderError) as error:
        async for item in session.stream_turn([TOOL]):
            emitted.append(item)
    assert not any(isinstance(item, ToolTurn) for item in emitted)
    assert "sk-private-test-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_chat_export_restores_final_reasoning_and_empty_call_reasoning():
    seen = []
    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if len(seen) == 1:
            return sse(("", {"choices": [{"delta": {"reasoning_content": "", "tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "search", "arguments": '{"q":"x"}'}}]}, "finish_reason": "tool_calls"}]}))
        if len(seen) == 2:
            return sse(("", {"choices": [{"delta": {"reasoning_content": "final thought", "content": "final"}, "finish_reason": "stop"}]}))
        return sse(("", {"choices": [{"delta": {"content": "next"}, "finish_reason": "stop"}]}))
    provider = OpenAICompatibleProvider(cfg("openai_compatible"), httpx.MockTransport(handler))
    session = ToolSession(provider, [{"role": "user", "content": "q"}])
    turn = (await collect(session))[-1]
    session.append_results(turn, [{"call_id": "call_1", "content": "found"}])
    assert (await collect(session))[-1].calls == []
    assert seen[1]["messages"][-2]["reasoning_content"] == ""
    exported = session.export_turn()
    assert exported["messages"][-1]["reasoning_content"] == "final thought"
    restored = ToolSession(provider, [{"role": "user", "content": "q"},
                                      {"role": "assistant", "content": "final", "_model_turn": exported},
                                      {"role": "user", "content": "next?"}])
    await collect(restored)
    assert seen[2]["messages"][-2]["reasoning_content"] == "final thought"
    assert seen[2]["messages"][-4]["tool_calls"][0]["id"] == "call_1"
    assert restored.export_turn()["messages"][-1]["content"] == "next"


@pytest.mark.asyncio
async def test_responses_export_restores_final_encrypted_reasoning():
    seen = []
    reasoning = {"type": "reasoning", "id": "rs_final", "encrypted_content": "opaque-final"}
    final = {"type": "message", "id": "msg_final", "content": [{"type": "output_text", "text": "answer"}]}
    def handler(request):
        seen.append(json.loads(request.content))
        output = [reasoning, final] if len(seen) == 1 else []
        return sse(("response.completed", {"type": "response.completed", "response": {"output": output}}))
    provider = OpenAIResponsesProvider(cfg("openai_responses"), httpx.MockTransport(handler))
    session = ToolSession(provider, [{"role": "user", "content": "q"}])
    assert (await collect(session))[-1].calls == []
    saved = session.export_turn()
    assert saved["messages"][0] == reasoning
    restored = ToolSession(provider, [{"role": "user", "content": "q"},
                                      {"role": "assistant", "content": "answer", "_model_turn": saved},
                                      {"role": "user", "content": "again"}])
    await collect(restored)
    assert seen[1]["input"][1:3] == [reasoning, final]


@pytest.mark.asyncio
async def test_google_export_restores_signed_final_part():
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return sse(("", {"candidates": [{"content": {"parts": [{"text": "answer", "thoughtSignature": "signed"}]}, "finishReason": "STOP"}]}))
    provider = GoogleProvider(cfg("google"), httpx.MockTransport(handler))
    session = ToolSession(provider, [{"role": "user", "content": "q"}])
    await collect(session)
    saved = session.export_turn()
    restored = ToolSession(provider, [{"role": "user", "content": "q"},
                                      {"role": "assistant", "content": "answer", "_model_turn": saved},
                                      {"role": "user", "content": "again"}])
    await collect(restored)
    assert seen[1]["contents"][1]["parts"][0]["thoughtSignature"] == "signed"


@pytest.mark.asyncio
async def test_mismatched_marker_falls_back_to_clean_text():
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return sse(("", {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}))
    marker = {"provider_kind": "google", "model": "test", "base_url": "https://api.example.test/v1",
              "messages": [{"role": "model", "parts": [{"functionCall": {"name": "bad"}}]}]}
    session = ToolSession(OpenAICompatibleProvider(cfg("openai_compatible"), httpx.MockTransport(handler)),
                          [{"role": "assistant", "content": "plain", "_model_turn": marker, "reasoning_content": ""},
                           {"role": "user", "content": "q"}])
    await collect(session)
    assert seen[0]["messages"][0] == {"role": "assistant", "content": "plain", "reasoning_content": ""}


@pytest.mark.asyncio
async def test_anthropic_export_restores_final_thinking_signature():
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return sse(("content_block_start", {"type": "content_block_start", "index": 0,
                                            "content_block": {"type": "thinking", "thinking": "", "signature": ""}}),
                   ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                            "delta": {"type": "thinking_delta", "thinking": "summary"}}),
                   ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                            "delta": {"type": "signature_delta", "signature": "opaque"}}),
                   ("content_block_start", {"type": "content_block_start", "index": 1,
                                            "content_block": {"type": "text", "text": "answer"}}),
                   ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}),
                   ("message_stop", {"type": "message_stop"}))
    provider = AnthropicProvider(cfg("anthropic"), httpx.MockTransport(handler))
    session = ToolSession(provider, [{"role": "user", "content": "q"}])
    await collect(session)
    saved = session.export_turn()
    restored = ToolSession(provider, [{"role": "user", "content": "q"},
                                      {"role": "assistant", "content": "answer", "_model_turn": saved},
                                      {"role": "user", "content": "again"}])
    await collect(restored)
    assert seen[1]["messages"][1]["content"][0] == {"type": "thinking", "thinking": "summary", "signature": "opaque"}


@pytest.mark.asyncio
async def test_replay_budget_keeps_recent_whole_turn_and_falls_back_for_older(monkeypatch):
    import app.function_tools as function_tools

    older_native = [{"role": "assistant", "content": None,
                     "tool_calls": [{"id": "old_call", "type": "function",
                                     "function": {"name": "search", "arguments": '{"q":"old"}'}}]},
                    {"role": "tool", "tool_call_id": "old_call", "content": "old result"},
                    {"role": "assistant", "content": "old final", "reasoning_content": "old thought"}]
    recent_native = [{"role": "assistant", "content": None,
                      "tool_calls": [{"id": "new_call", "type": "function",
                                      "function": {"name": "search", "arguments": '{"q":"new"}'}}]},
                     {"role": "tool", "tool_call_id": "new_call", "content": "new result"},
                     {"role": "assistant", "content": "new final", "reasoning_content": "new thought"}]
    monkeypatch.setattr(function_tools, "MAX_REPLAY_BYTES",
                        len(json.dumps(recent_native, ensure_ascii=False).encode("utf-8")))
    base = {"provider_kind": "openai_compatible", "model": "test",
            "base_url": "https://api.example.test/v1"}
    messages = [{"role": "user", "content": "q1"},
                {"role": "assistant", "content": "old final", "reasoning_content": "old saved",
                 "_model_turn": {**base, "messages": older_native}},
                {"role": "user", "content": "q2"},
                {"role": "assistant", "content": "new final",
                 "_model_turn": {**base, "messages": recent_native}},
                {"role": "user", "content": "q3"}]
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return sse(("", {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}))
    provider = OpenAICompatibleProvider(cfg("openai_compatible"), httpx.MockTransport(handler))
    session = ToolSession(provider, messages)
    await collect(session)
    wire = seen[0]["messages"]
    assert [m["content"] for m in wire if m["role"] == "user"] == ["q1", "q2", "q3"]
    assert wire[1] == {"role": "assistant", "content": "old final", "reasoning_content": "old saved"}
    assert wire[3:6] == recent_native
    assert not any("_model_turn" in m for m in wire)
    assert not any(m.get("tool_call_id") == "old_call" for m in wire)
