"""Original images stay transient across all four Provider wire protocols."""
import base64
import copy
import io
import json

import httpx
import pytest
from PIL import Image

from app.function_tools import ToolSession, ToolTurn
from app.provider_messages import encode_messages
from app.providers import ProviderConfig, ProviderError, build_provider

KINDS = ("openai_compatible", "openai_responses", "google", "anthropic")
TOOL = {"name": "search", "description": "Search knowledge", "parameters": {"type": "object", "properties": {}}}


@pytest.fixture(scope="module")
def images():
    result = []
    for format, media_type in (("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")):
        output = io.BytesIO()
        Image.new("RGB", (3, 2), (10, 20, 30)).save(output, format=format)
        result.append({"media_type": media_type, "data": base64.b64encode(output.getvalue()).decode("ascii")})
    return result


def provider(kind, handler):
    return build_provider(ProviderConfig(
        base_url="https://api.example.test/v1beta" if kind == "google" else "https://api.example.test/v1",
        model="current-user-selected-model", api_key="sk-mock-test", timeout_seconds=5,
        provider_kind=kind, web_search=True,
    ), transport=httpx.MockTransport(handler))


def sse(*events):
    return httpx.Response(200, text="".join(
        f"event: {kind}\ndata: {json.dumps(body)}\n\n" for kind, body in events
    ))


def stream_reply(kind, text="answer"):
    if kind == "openai_compatible":
        return httpx.Response(200, text=f'data: {json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]})}\n\ndata: [DONE]\n\n')
    if kind == "openai_responses":
        return sse(("response.output_text.delta", {"type": "response.output_text.delta", "delta": text}),
                   ("response.completed", {"type": "response.completed", "response": {"output": [
                       {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}
                   ]}}))
    if kind == "google":
        return sse(("", {"candidates": [{"content": {"parts": [{"text": text, "thoughtSignature": "signed-output"}]}, "finishReason": "STOP"}]}))
    return sse(("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
               ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}),
               ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}),
               ("message_stop", {"type": "message_stop"}))


def json_reply(kind):
    if kind == "openai_compatible":
        body = {"choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}]}
    elif kind == "openai_responses":
        body = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "answer"}]}]}
    elif kind == "google":
        body = {"candidates": [{"content": {"parts": [{"text": "answer"}]}, "finishReason": "STOP"}]}
    else:
        body = {"content": [{"type": "text", "text": "answer"}], "stop_reason": "end_turn"}
    return httpx.Response(200, json=body)


def tool_reply(kind):
    if kind == "openai_compatible":
        response = sse(("", {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call-1", "function": {"name": "search", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]}))
        return httpx.Response(200, text=response.text + "data: [DONE]\n\n")
    if kind == "openai_responses":
        return sse(("response.completed", {"type": "response.completed", "response": {"output": [
            {"type": "reasoning", "id": "rs-1", "encrypted_content": "signed-output"},
            {"type": "function_call", "id": "fc-1", "call_id": "call-1", "name": "search", "arguments": "{}"},
        ]}}))
    if kind == "google":
        return sse(("", {"candidates": [{"content": {"parts": [
            {"functionCall": {"id": "call-1", "name": "search", "args": {}}, "thoughtSignature": "signed-output"},
        ]}, "finishReason": "STOP"}]}))
    return sse(("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "call-1", "name": "search", "input": {}}}),
               ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use"}}),
               ("message_stop", {"type": "message_stop"}))


def expected_user(kind, images, text="Compare original pages"):
    if kind == "google":
        return {"role": "user", "parts": ([{"text": text}] if text else []) + [
            {"inlineData": {"mimeType": image["media_type"], "data": image["data"]}} for image in images
        ]}
    if kind == "anthropic":
        return {"role": "user", "content": [
            *[{"type": "image", "source": {"type": "base64", "media_type": image["media_type"], "data": image["data"]}} for image in images],
            *([{"type": "text", "text": text}] if text else []),
        ]}
    if kind == "openai_responses":
        return {"role": "user", "content": ([{"type": "input_text", "text": text}] if text else []) + [
            {"type": "input_image", "image_url": f"data:{image['media_type']};base64,{image['data']}"} for image in images
        ]}
    return {"role": "user", "content": ([{"type": "text", "text": text}] if text else []) + [
        {"type": "image_url", "image_url": {"url": f"data:{image['media_type']};base64,{image['data']}"}} for image in images
    ]}


def wire_messages(kind, payload):
    return payload["contents" if kind == "google" else "input" if kind == "openai_responses" else "messages"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("stream", (False, True))
async def test_original_images_encode_for_selected_model_and_native_search(kind, stream, images):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return stream_reply(kind) if stream else json_reply(kind)

    messages = [{"role": "system", "content": "Teach"},
                {"role": "user", "content": "Compare original pages", "_images": images}]
    before = copy.deepcopy(messages)
    adapter = provider(kind, handler)
    if stream:
        chunks = [chunk async for chunk in adapter.stream_chat(messages)]
        assert "".join(chunk.text for chunk in chunks if chunk.kind == "content") == "answer"
    else:
        assert await adapter.generate_text(messages, max_tokens=500) == "answer"
    payload = seen[0]
    assert wire_messages(kind, payload)[-1] == expected_user(kind, images)
    assert "_images" not in json.dumps(payload)
    assert messages == before
    assert adapter.config.model == "current-user-selected-model"
    if kind != "google":
        assert payload["model"] == "current-user-selected-model"
    if kind != "openai_compatible":
        assert ("tools" in payload) is stream


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_function_history_keeps_images_after_tool_results_but_export_and_replay_do_not_copy_them(kind, images):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return tool_reply(kind) if len(seen) == 1 else stream_reply(kind)

    messages = [{"role": "system", "content": "Teach"},
                {"role": "user", "content": "Compare original pages", "_images": images}]
    adapter = provider(kind, handler)
    session = ToolSession(adapter, messages)
    first = [item async for item in session.stream_turn([TOOL])]
    turn = first[-1]
    assert isinstance(turn, ToolTurn) and turn.calls[0].id == "call-1"
    session.append_results(turn, [{"call_id": "call-1", "content": "Found relevant knowledge"}])
    final = [item async for item in session.stream_turn([TOOL])]
    assert final[-1].calls == []
    for payload in seen:
        assert expected_user(kind, images) in wire_messages(kind, payload)
        assert "_images" not in json.dumps(payload)
    saved = session.export_turn()
    serialized = json.dumps(saved)
    assert all(image["data"] not in serialized for image in images)
    assert "_images" not in serialized
    if kind in {"openai_responses", "google"}:
        assert "signed-output" in serialized
    restored = ToolSession(adapter, [*messages,
        {"role": "assistant", "content": "answer", "_model_turn": saved},
        {"role": "user", "content": "Follow-up"},
    ])
    await drain(restored)
    wire = wire_messages(kind, seen[-1])
    assert wire.count(expected_user(kind, images)) == 1
    assert "Found relevant knowledge" in json.dumps(wire)
    assert all(image["data"] not in json.dumps(restored.export_turn()) for image in images)


async def drain(session):
    return [item async for item in session.stream_turn([TOOL])]


@pytest.mark.parametrize("kind", KINDS)
def test_plain_text_wire_shapes_and_empty_image_field_are_unchanged(kind):
    messages = [{"role": "system", "content": "Teach"},
                {"role": "user", "content": "Question"},
                {"role": "assistant", "content": "Answer", "reasoning_content": "Thinking"}]
    if kind in {"openai_compatible", "openai_responses"}:
        expected = messages
    elif kind == "google":
        expected = [{"role": "user", "parts": [{"text": "Question"}]},
                    {"role": "model", "parts": [{"text": "Answer"}]}]
    else:
        expected = [{"role": "user", "content": "Question"}, {"role": "assistant", "content": "Answer"}]
    assert encode_messages(messages, kind) == expected
    with_empty = copy.deepcopy(messages)
    with_empty[1]["_images"] = []
    assert encode_messages(with_empty, kind) == expected


@pytest.mark.parametrize("kind", KINDS)
def test_images_only_message_omits_empty_text_blocks(kind, images):
    assert encode_messages([{"role": "user", "content": "", "_images": images}], kind) == [expected_user(kind, images, "")]


INVALID_INPUTS = (
    {"_images": None},
    {"_images": {}},
    {"_images": [None]},
    {"_images": [{"media_type": "image/gif", "data": "R0lG"}]},
    {"_images": [{"media_type": [], "data": "eA=="}]},
    {"_images": [{"media_type": "image/png", "data": "private-not-base64!"}]},
    {"_images": [{"media_type": "image/png", "data": ""}]},
    {"_images": [{"media_type": "image/png", "data": "eA=="}]},
    {"_images": [{"media_type": "image/png", "data": "iVBORw0KGgo=\n"}]},
    {"_images": [{"media_type": "image/png", "data": "iVBORw0KGgo=", "filename": "private.png"}]},
    {"role": "assistant", "_images": [{"media_type": "image/png", "data": "iVBORw0KGgo="}]},
    {"role": "system", "_images": [{"media_type": "image/png", "data": "iVBORw0KGgo="}]},
    {"content": [], "_images": [{"media_type": "image/png", "data": "iVBORw0KGgo="}]},
)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("path", ("stream", "nonstream", "tools"))
@pytest.mark.parametrize("invalid", INVALID_INPUTS)
async def test_invalid_images_fail_before_any_http_with_fixed_private_safe_error(kind, path, invalid):
    def handler(_request):
        pytest.fail("Invalid image input must fail before HTTP")

    adapter = provider(kind, handler)
    messages = [{"role": "user", "content": "Question", **invalid}]
    with pytest.raises(ProviderError) as raised:
        if path == "stream":
            _ = [item async for item in adapter.stream_chat(messages)]
        elif path == "nonstream":
            await adapter.generate_text(messages)
        else:
            await drain(ToolSession(adapter, messages))
    assert raised.value.kind == "invalid_image_input"
    assert str(raised.value) == "图片输入格式无效或不受支持"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("path", ("stream", "nonstream", "tools"))
async def test_http_errors_cannot_echo_images_into_ui_or_persisted_errors(kind, path, images, caplog):
    def handler(_request):
        return httpx.Response(400, json={"error": {"message": f"Rejected data:image/png;base64,{images[0]['data']}"}})

    adapter = provider(kind, handler)
    messages = [{"role": "user", "content": "Question", "_images": images}]
    with pytest.raises(ProviderError) as raised:
        if path == "stream":
            _ = [item async for item in adapter.stream_chat(messages)]
        elif path == "nonstream":
            await adapter.generate_text(messages)
        else:
            await drain(ToolSession(adapter, messages))
    assert raised.value.kind == "request_error"
    assert "Rejected" not in str(raised.value)
    assert "data:image" not in str(raised.value)
    assert images[0]["data"] not in str(raised.value) + caplog.text


@pytest.mark.asyncio
async def test_openai_stream_error_does_not_echo_images_and_text_only_keeps_detail(images):
    def handler(_request):
        return sse(("", {"error": {"message": f"Rejected {images[0]['data']}"}}))

    adapter = provider("openai_compatible", handler)
    with pytest.raises(ProviderError) as raised:
        _ = [item async for item in adapter.stream_chat([{"role": "user", "content": "Question", "_images": images}])]
    assert str(raised.value) == "提供方流式请求失败"
    with pytest.raises(ProviderError) as text_only:
        _ = [item async for item in adapter.stream_chat([{"role": "user", "content": "Question"}])]
    assert "Rejected" in str(text_only.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_input_base64_echo_is_refused_at_tool_snapshot_boundary(kind, images):
    session = ToolSession(provider(kind, lambda _: stream_reply(kind, images[0]["data"])),
                          [{"role": "user", "content": "Question", "_images": images}])
    await drain(session)
    with pytest.raises(ProviderError) as raised:
        session.export_turn()
    assert raised.value.kind == "protocol_error"
    assert images[0]["data"] not in str(raised.value)
