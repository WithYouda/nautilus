"""Frozen native reasoning controls reach every real HTTP request path."""
import copy
import json
from dataclasses import FrozenInstanceError, replace

import httpx
import pytest

from app.function_tools import ToolSession, ToolTurn
from app.providers import ProviderConfig, ProviderError, build_provider
from app.reasoning_wire import apply_reasoning_parameters
from test_teaching_json_providers import TOOL, assert_format, response_for, runtime, wire_history

KINDS = ("openai_compatible", "openai_responses", "google", "anthropic")
CASES = [
    ("openai_compatible", {"reasoning_effort": "max"}),
    ("openai_compatible", {"reasoning_effort": "none"}),
    ("openai_compatible", {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}),
    ("openai_compatible", {"thinking": {"type": "disabled"}}),
    ("openai_compatible", {"thinking": {"type": "enabled", "keep": "all"}}),
    ("openai_compatible", {"enable_thinking": True, "thinking_budget": 8192}),
    ("openai_compatible", {"enable_thinking": False}),
    ("openai_responses", {"reasoning": {"effort": "xhigh"}}),
    ("openai_responses", {"reasoning": {"effort": "none"}}),
    ("anthropic", {"thinking": {"type": "adaptive"}, "output_config": {"effort": "xhigh"}}),
    ("anthropic", {"output_config": {"effort": "low"}}),
    ("anthropic", {"thinking": {"type": "enabled", "budget_tokens": 2048}, "output_config": {"effort": "high"}}),
    ("anthropic", {"thinking": {"type": "disabled"}}),
    ("google", {"generationConfig": {"thinkingConfig": {"thinkingLevel": "medium"}}}),
    ("google", {"generationConfig": {"thinkingConfig": {"thinkingBudget": 2048}}}),
    ("google", {"generationConfig": {"thinkingConfig": {"thinkingBudget": -1}}}),
    ("google", {"generationConfig": {"thinkingConfig": {"thinkingBudget": 0}}}),
    *[(kind, default) for kind in KINDS for default in (None, {})],
]


def config(kind, parameters):
    return ProviderConfig(
        base_url="https://api.example.test/v1beta" if kind == "google" else "https://api.example.test/v1",
        model="selected-model", api_key="fixture-key", provider_kind=kind,
        reasoning_parameters_json=None if parameters is None else json.dumps(parameters, sort_keys=True),
    )


def complete_response(kind, text):
    if kind == "openai_compatible":
        body = {"choices": [{"message": {"content": text}, "finish_reason": "stop"}]}
    elif kind == "openai_responses":
        body = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}
    elif kind == "google":
        body = {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}
    else:
        body = {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}
    return httpx.Response(200, json=body)


def assert_controls(kind, body, parameters):
    expected = parameters or {}
    for root in ("reasoning_effort", "thinking", "enable_thinking", "thinking_budget", "reasoning"):
        assert body.get(root) == expected.get(root)
    assert body.get("output_config", {}).get("effort") == expected.get("output_config", {}).get("effort")
    assert body.get("generationConfig", {}).get("thinkingConfig") == expected.get("generationConfig", {}).get("thinkingConfig")


@pytest.mark.parametrize("kind,parameters", CASES)
@pytest.mark.parametrize("json_output", (False, True))
@pytest.mark.asyncio
async def test_controls_reach_complete_stream_and_every_tool_round(kind, parameters, json_output):
    parameters = copy.deepcopy(parameters)
    requests = []
    operation = "complete"
    tool_requests = 0
    raw = '{"answer":"ok"}'

    def handler(request):
        nonlocal tool_requests
        requests.append(json.loads(request.content))
        if operation == "complete":
            return complete_response(kind, raw)
        if operation == "tools":
            tool_requests += 1
        return response_for(kind, raw, tool=operation == "tools" and tool_requests == 1)

    selected = config(kind, parameters)
    frozen = selected.reasoning_parameters_json
    adapter = build_provider(selected, transport=httpx.MockTransport(handler))
    messages = ([runtime()] if json_output else []) + [{"role": "user", "content": "question"}]
    original_messages = copy.deepcopy(messages)
    assert await adapter.generate_text(messages, max_tokens=96, json_mode=json_output) == raw
    operation = "stream"
    stream = [item async for item in adapter.stream_chat(messages)]
    assert stream[-1].kind == "completion" and stream[-1].text == "complete"
    operation = "tools"
    session = ToolSession(adapter, messages)
    turn = [item async for item in session.stream_turn([TOOL])][-1]
    assert isinstance(turn, ToolTurn) and len(turn.calls) == 1
    continuation = copy.deepcopy(turn.continuation)
    session.append_results(turn, [{"call_id": turn.calls[0].id, "content": "found"}])

    # A new selection is a new immutable config; it cannot alter this run.
    next_config = replace(selected, reasoning_parameters_json="{}")
    with pytest.raises(FrozenInstanceError):
        selected.reasoning_parameters_json = next_config.reasoning_parameters_json
    if parameters:
        parameters.clear()  # No mutable selection object is retained by the run.
    final = [item async for item in session.stream_turn([TOOL], allow_tools=False)][-1]
    assert isinstance(final, ToolTurn) and not final.calls and final.completion == "complete"
    assert len(requests) == 4 and selected.reasoning_parameters_json == frozen
    expected = json.loads(frozen) if frozen is not None else None
    for body in requests:
        assert_controls(kind, body, expected)
        assert_format(kind, body, json_output)
    if kind == "anthropic":
        budget = (expected or {}).get("thinking", {}).get("budget_tokens", 0)
        assert [body["max_tokens"] for body in requests] == [96 + budget, 4096 + budget, 4096 + budget, 4096 + budget]
    assert messages == original_messages and turn.continuation == continuation
    continued = wire_history(kind, requests[-1])
    if kind == "openai_responses":
        assert continued[-len(continuation)-1:-1] == continuation
        assert requests[-1]["include"] == ["reasoning.encrypted_content"]
    elif kind == "anthropic":
        assert continued[-2] == {"role": "assistant", "content": continuation}
    else:
        assert continued[-2] == continuation
    if kind == "google":
        assert requests[-1]["toolConfig"] == {"functionCallingConfig": {"mode": "NONE"}}
        assert requests[-1]["tools"] == [{"functionDeclarations": [TOOL]}]
    elif kind == "anthropic":
        assert requests[-1]["tool_choice"] == {"type": "none"}
        assert requests[-1]["tools"] == [{"name": TOOL["name"], "description": TOOL["description"], "input_schema": TOOL["parameters"]}]
    else:
        assert requests[-1]["tool_choice"] == "none"
        assert requests[-1]["tools"] == ([{"type": "function", **TOOL, "strict": False}]
            if kind == "openai_responses" else [{"type": "function", "function": TOOL}])


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("path", ("complete", "stream", "tools"))
@pytest.mark.asyncio
async def test_wrong_protocol_roots_fail_before_http(kind, path):
    requests = []
    wrong = {"reasoning_effort": "high"} if kind != "openai_compatible" else {"reasoning": {"effort": "high"}}
    adapter = build_provider(config(kind, wrong), transport=httpx.MockTransport(lambda request: requests.append(request)))
    with pytest.raises(ProviderError) as caught:
        if path == "complete":
            await adapter.generate_text([])
        else:
            iterator = adapter.stream_chat([]) if path == "stream" else ToolSession(adapter, []).stream_turn([TOOL])
            _ = [item async for item in iterator]
    assert caught.value.kind == "config_error" and requests == []


@pytest.mark.parametrize("kind,raw", [
    ("openai_compatible", "not-json"),
    ("openai_compatible", "null"),
    ("openai_compatible", "[]"),
    ("openai_compatible", {"reasoning_effort": False}),
    ("openai_compatible", {"reasoning_effort": ""}),
    ("openai_compatible", {"enable_thinking": "false"}),
    ("openai_compatible", {"thinking_budget": True}),
    ("openai_compatible", {"thinking_budget": -2}),
    ("openai_compatible", {"thinking": {"type": "adaptive"}}),
    ("openai_compatible", {"thinking": {"type": "disabled", "keep": "all"}}),
    ("openai_compatible", {"model": "unapproved-model"}),
    ("openai_responses", {"reasoning": {}}),
    ("openai_responses", {"reasoning": {"effort": "high", "tools": []}}),
    ("anthropic", {"thinking": {"type": "enabled"}}),
    ("anthropic", {"thinking": {"type": "enabled", "budget_tokens": 0}}),
    ("anthropic", {"thinking": {"type": "enabled", "budget_tokens": 2048.5}}),
    ("anthropic", {"thinking": {"type": "adaptive", "budget_tokens": 2048}}),
    ("anthropic", {"output_config": {"effort": None}}),
    ("anthropic", {"output_config": {"format": {"type": "json_schema"}}}),
    ("google", {"generationConfig": {"thinkingConfig": {"thinkingBudget": 2000, "thinkingLevel": "low"}}}),
    ("google", {"generationConfig": {"thinkingConfig": {"thinkingBudget": False}}}),
    ("google", {"generationConfig": {"thinkingConfig": {"includeThoughts": 1}}}),
    ("google", {"generationConfig": {"thinkingConfig": {"thinkingLevel": " high "}}}),
    ("google", {"generationConfig": {"temperature": 1}}),
])
def test_malformed_controls_raise_without_changing_payload(kind, raw):
    selected = replace(config(kind, None), reasoning_parameters_json=raw if isinstance(raw, str) else json.dumps(raw))
    payload = {"max_tokens": 4096, "tools": [TOOL], "output_config": {"format": {"type": "json_schema"}}}
    original = copy.deepcopy(payload)
    with pytest.raises(ProviderError) as caught:
        apply_reasoning_parameters(payload, selected)
    assert caught.value.kind == "config_error" and payload == original


@pytest.mark.parametrize("parameters", (None, {}))
def test_default_preserves_existing_payload_exactly(parameters):
    payload = {"tools": [TOOL], "generationConfig": {"temperature": 0.7}, "output_config": {"format": {"type": "json_schema"}}}
    original = copy.deepcopy(payload)
    for kind in KINDS:
        apply_reasoning_parameters(payload, config(kind, parameters))
        assert payload == original


def test_merge_preserves_native_format_and_sampling_settings():
    payload = {"generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 96, "temperature": 0.7}}
    apply_reasoning_parameters(payload, config("google", {"generationConfig": {"thinkingConfig": {"thinkingLevel": "low"}}}))
    assert payload["generationConfig"] == {"responseMimeType": "application/json", "maxOutputTokens": 96,
        "temperature": 0.7, "thinkingConfig": {"thinkingLevel": "low"}}
    payload = {"reasoning": {"summary": "auto"}, "text": {"format": {"type": "json_object"}}}
    apply_reasoning_parameters(payload, config("openai_responses", {"reasoning": {"effort": "max"}}))
    assert payload == {"reasoning": {"summary": "auto", "effort": "max"}, "text": {"format": {"type": "json_object"}}}
