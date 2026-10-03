"""Structured teaching keeps native formats, reasoning and replay separate."""
import copy
import json

import httpx
import pytest

from app.function_tools import ToolSession, ToolTurn
from app.provider_messages import encode_message
from app.providers import ProviderConfig, build_provider
from app.teaching_wire import ENVELOPE_SCHEMA, apply_json_output, uses_json

KINDS = ("openai_compatible", "openai_responses", "google", "anthropic")
TOOL = {"name": "search", "description": "Search", "parameters": {"type": "object", "properties": {}}}
NATIVE_REASONING = "native reasoning"


def runtime(*, json_output=True):
    return {"role": "user", "content": 'Current teaching JSON context: {"token":"current-token"}',
            "_teaching_runtime": True, **({"_teaching_output": "json"} if json_output else {})}


def provider(kind, handler):
    return build_provider(ProviderConfig(
        base_url="https://api.example.test/v1beta" if kind == "google" else "https://api.example.test/v1",
        model="selected-model", api_key="fixture-key", provider_kind=kind,
    ), transport=httpx.MockTransport(handler))


def response_for(kind, raw, *, tool=False, chunk_size=7):
    pieces = [raw[index:index + chunk_size] for index in range(0, len(raw), chunk_size)]
    if kind == "openai_compatible":
        events = [("", {"choices": [{"delta": {"reasoning_content": NATIVE_REASONING}}]})]
        events += [("", {"choices": [{"delta": {"content": piece}}]}) for piece in pieces]
        delta = {"tool_calls": [{"index": 0, "id": "call-1", "function": {"name": "search", "arguments": "{}"}}]} if tool else {}
        events.append(("", {"choices": [{"delta": delta, "finish_reason": "tool_calls" if tool else "stop"}]}))
    elif kind == "openai_responses":
        events = [("response.reasoning_summary_text.delta", {"delta": NATIVE_REASONING})]
        events += [("response.output_text.delta", {"delta": piece}) for piece in pieces]
        output = [{"type": "reasoning", "id": "rs-1", "encrypted_content": "opaque-reasoning"},
                  {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": raw}]}]
        if tool:
            output.append({"type": "function_call", "id": "fc-1", "call_id": "call-1", "name": "search", "arguments": "{}"})
        events.append(("response.completed", {"response": {"status": "completed", "output": output}}))
    elif kind == "google":
        parts = [{"text": NATIVE_REASONING, "thought": True, "thoughtSignature": "signed-thinking"}]
        parts += [{"text": piece} for piece in pieces]
        if tool:
            parts.append({"functionCall": {"id": "call-1", "name": "search", "args": {}}, "thoughtSignature": "signed-call"})
        events = [("", {"candidates": [{"content": {"parts": parts}, "finishReason": "STOP"}]})]
    else:
        events = [("content_block_start", {"index": 0, "content_block": {"type": "thinking", "thinking": ""}}),
                  ("content_block_delta", {"index": 0, "delta": {"type": "thinking_delta", "thinking": NATIVE_REASONING}}),
                  ("content_block_delta", {"index": 0, "delta": {"type": "signature_delta", "signature": "signed-thinking"}}),
                  ("content_block_start", {"index": 1, "content_block": {"type": "text", "text": ""}})]
        events += [("content_block_delta", {"index": 1, "delta": {"type": "text_delta", "text": piece}}) for piece in pieces]
        if tool:
            events.append(("content_block_start", {"index": 2, "content_block": {"type": "tool_use", "id": "call-1", "name": "search", "input": {}}}))
        events += [("message_delta", {"delta": {"stop_reason": "tool_use" if tool else "end_turn"}}),
                   ("message_stop", {})]
    wire = "".join(f"event: {event}\ndata: {json.dumps(body, ensure_ascii=False)}\n\n" for event, body in events)
    if kind == "openai_compatible":
        wire += "data: [DONE]\n\n"
    return httpx.Response(200, text=wire)


def wire_history(kind, payload):
    return payload["contents" if kind == "google" else "input" if kind == "openai_responses" else "messages"]


def assert_format(kind, payload, enabled):
    if kind == "openai_compatible":
        value = payload.get("response_format")
        assert value == ({"type": "json_object"} if enabled else None)
    elif kind == "openai_responses":
        value = payload.get("text", {}).get("format")
        assert value == ({"type": "json_object"} if enabled else None)
    elif kind == "google":
        assert payload.get("generationConfig", {}).get("responseMimeType") == ("application/json" if enabled else None)
    else:
        value = payload.get("output_config", {}).get("format")
        assert value == ({"type": "json_schema", "schema": ENVELOPE_SCHEMA} if enabled else None)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("tool_session", (False, True))
@pytest.mark.parametrize("json_output", (False, True))
async def test_native_format_only_for_flagged_request(kind, tool_session, json_output):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return response_for(kind, "ordinary body")
    adapter = provider(kind, handler)
    messages = [{"role": "system", "content": "Teach"}, runtime(json_output=json_output),
                {"role": "user", "content": "question"}]
    original = copy.deepcopy(messages)
    if tool_session:
        output = [item async for item in ToolSession(adapter, messages).stream_turn([TOOL], allow_tools=False)]
        assert isinstance(output[-1], ToolTurn) and output[-1].completion == "complete"
    else:
        output = [item async for item in adapter.stream_chat(messages)]
        assert output[-1].kind == "completion" and output[-1].text == "complete"
    assert "".join(item.text for item in output if getattr(item, "kind", None) == "content") == "ordinary body"
    assert "".join(item.text for item in output if getattr(item, "kind", None) == "reasoning") == NATIVE_REASONING
    assert len(requests) == 1 and messages == original
    assert_format(kind, requests[0], json_output)
    for message in wire_history(kind, requests[0]):
        assert not any(key.startswith("_") for key in message)
    if tool_session:
        if kind == "google":
            assert requests[0]["tools"] == [{"functionDeclarations": [TOOL]}]
            assert requests[0]["toolConfig"] == {"functionCallingConfig": {"mode": "NONE"}}
        elif kind == "anthropic":
            assert requests[0]["tools"] == [{"name": TOOL["name"], "description": TOOL["description"], "input_schema": TOOL["parameters"]}]
            assert requests[0]["tool_choice"] == {"type": "none"}
        else:
            assert requests[0]["tool_choice"] == "none"
            if kind == "openai_responses":
                assert requests[0]["include"] == ["reasoning.encrypted_content"]
                assert requests[0]["tools"] == [{"type": "function", **TOOL, "strict": False}]
            else:
                assert requests[0]["tools"] == [{"type": "function", "function": TOOL}]


def envelope():
    return json.dumps({"reply": '原样 <think>代码</think>、引号 "、反斜杠 \\、\n换行和😀',
                       "teaching": {"step": None, "attempt": {"quote": '用户 <think>标签、"\\', "needs_help": None},
                                    "mode": None, "help": None, "practice": None},
                       "token": "current-token"}, ensure_ascii=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_session", (False, True))
@pytest.mark.parametrize("chunk_size", (1, 7))
async def test_chat_json_literals_are_content_only_and_native_reasoning_survives(tool_session, chunk_size):
    raw = envelope()
    adapter = provider("openai_compatible", lambda _: response_for("openai_compatible", raw, chunk_size=chunk_size))
    messages = [runtime(), {"role": "user", "content": "question"}]
    session = ToolSession(adapter, messages) if tool_session else None
    stream = session.stream_turn([TOOL]) if session else adapter.stream_chat(messages)
    chunks = [item async for item in stream]
    assert "".join(item.text for item in chunks if getattr(item, "kind", None) == "content") == raw
    assert "".join(item.text for item in chunks if getattr(item, "kind", None) == "reasoning") == NATIVE_REASONING
    if session:
        assert session.export_turn()["messages"][-1]["content"] == raw


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize('next_json', [True, False, None])
async def test_json_tool_history_and_signed_envelopes_replay_unchanged(kind, next_json):
    requests = []
    raw = envelope()
    def handler(request):
        requests.append(json.loads(request.content))
        return response_for(kind, raw, tool=len(requests) == 1)
    adapter = provider(kind, handler)
    current_runtime = runtime()
    session = ToolSession(adapter, [current_runtime, {"role": "user", "content": "question"}])
    turn = [item async for item in session.stream_turn([TOOL])][-1]
    assert isinstance(turn, ToolTurn) and turn.calls[0].id == "call-1"
    original_continuation = copy.deepcopy(turn.continuation)
    session.append_results(turn, [{"call_id": "call-1", "content": "found"}])
    final = [item async for item in session.stream_turn([TOOL])]
    assert final[-1].calls == [] and final[-1].completion == "complete"
    assert "".join(item.text for item in final if getattr(item, "kind", None) == "content") == raw
    assert turn.continuation == original_continuation
    continued = wire_history(kind, requests[1])
    if kind == "openai_responses":
        assert continued[-len(original_continuation)-1:-1] == original_continuation
    elif kind == "anthropic":
        assert continued[-2] == {"role": "assistant", "content": original_continuation}
    else:
        assert continued[-2] == original_continuation
    saved = session.export_turn()
    assert saved["teaching_input"] == {"role": "user", "content": current_runtime["content"]}
    assert raw in _native_texts(kind, saved["messages"])
    original_saved = copy.deepcopy(saved)
    restored = ToolSession(adapter, [{"role": "user", "content": "question"},
                                     {"role": "assistant", "content": "visible reply", "_model_turn": saved},
                                     *([runtime(json_output=next_json)] if next_json is not None else []),
                                     {"role": "user", "content": "follow-up"}])
    await _collect(restored)
    replayed = wire_history(kind, requests[2])
    if next_json:
        assert replayed[0] == encode_message(saved["teaching_input"], kind)
        assert replayed[2:2 + len(saved["messages"])] == saved["messages"]
    else:
        assert replayed[1] == encode_message({'role': 'assistant', 'content': 'visible reply'}, kind)
        assert raw not in _native_texts(kind, replayed)
    assert saved == original_saved
    assert_format(kind, requests[0], True)
    assert_format(kind, requests[1], True)
    assert_format(kind, requests[2], bool(next_json))


async def _collect(session):
    return [item async for item in session.stream_turn([TOOL])]


def _native_texts(kind, messages):
    def parts(message):
        content = message.get('content', [])
        return [{'type': 'text', 'text': content}] if isinstance(content, str) else content
    if kind == "openai_compatible":
        return [message.get("content") for message in messages if message.get("role") == "assistant"]
    if kind == "openai_responses":
        return [part["text"] for message in messages for part in parts(message) if part.get("type") in ("output_text", "text")]
    if kind == "google":
        return ["".join(part.get("text", "") for part in message.get("parts", []) if not part.get("thought"))
                for message in messages if message.get("role") == "model"]
    return ["".join(part.get("text", "") for part in parts(message) if part.get("type") == "text")
            for message in messages if message.get("role") == "assistant"]


def test_newest_runtime_exclusively_selects_format_and_preserves_other_payload_settings():
    old = runtime()
    latest = runtime(json_output=False)
    assert uses_json([old]) is True
    assert uses_json([old, latest]) is False
    assert uses_json([{"role": "user", "content": "json", "_teaching_output": "json"}]) is False
    for kind in KINDS:
        payload = {"tools": [{"name": "existing"}], "tool_choice": "auto",
                   "thinking": {"type": "enabled", "budget_tokens": 1000},
                   "reasoning": {"effort": "high"}, "text": {"verbosity": "low"},
                   "generationConfig": {"temperature": 0.7}, "output_config": {"effort": "high"}}
        original = copy.deepcopy(payload)
        apply_json_output(payload, kind, [old, latest])
        assert payload == original
        apply_json_output(payload, kind, [latest, old])
        assert_format(kind, payload, True)
        assert payload["tools"] == original["tools"] and payload["tool_choice"] == original["tool_choice"]
        assert payload["thinking"] == original["thinking"] and payload["reasoning"] == original["reasoning"]
        assert payload["text"]["verbosity"] == "low"
        assert payload["generationConfig"]["temperature"] == 0.7
        assert payload["output_config"]["effort"] == "high"


def test_schema_requires_exact_envelope_and_current_teaching_fields():
    assert ENVELOPE_SCHEMA["required"] == ["reply", "teaching", "token"]
    assert ENVELOPE_SCHEMA["properties"]["reply"] == {"type": "string"}
    assert ENVELOPE_SCHEMA["properties"]["token"] == {"type": "string"}
    teaching = ENVELOPE_SCHEMA["properties"]["teaching"]
    assert teaching["required"] == ["step", "attempt", "mode", "help", "practice", "project", "adaptation"]
    assert teaching["properties"]["step"] == {"type": ["string", "null"]}
    expected = {"attempt": ["quote", "needs_help"], "mode": ["value", "scope", "quote", "persistence_quote"],
                "help": ["kind", "quote"], "practice": ["question", "feedback"], "project": ["goal", "instruction", "feedback", "change_quote"], "adaptation": ["method", "reason", "rule_id", "draft"]}
    for field, required in expected.items():
        options = teaching["properties"][field]["anyOf"]
        assert options[1] == {"type": "null"} and options[0]["required"] == required
    mode = teaching["properties"]["mode"]["anyOf"][0]["properties"]
    assert set(mode["value"]["enum"]) == {"stepwise", "socratic", "feynman", "practice_first", "project", "adaptive", "direct_answer", "full_explanation"}
    assert mode["scope"]["enum"] == ["turn", "conversation"]
    def check_objects(schema):
        if isinstance(schema, dict):
            assert "maxLength" not in schema
            if schema.get("type") == "object":
                assert schema["additionalProperties"] is False
            for value in schema.values():
                check_objects(value)
        elif isinstance(schema, list):
            for value in schema:
                check_objects(value)
    check_objects(ENVELOPE_SCHEMA)


@pytest.mark.parametrize("kind", ("openai_compatible", "openai_responses"))
def test_private_fields_removed_without_changing_protocol_fields(kind):
    message = {"role": "assistant", "content": "literal JSON", "name": "assistant-name",
               "reasoning_content": "native reasoning", "tool_calls": [{"id": "call-1", "type": "function"}],
               "_teaching_runtime": True, "_teaching_output": "json", "_model_turn": {"private": True}}
    original = copy.deepcopy(message)
    encoded = encode_message(message, kind)
    assert encoded == {key: value for key, value in original.items() if not key.startswith("_")}
    assert message == original
