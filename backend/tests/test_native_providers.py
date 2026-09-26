"""Protocol fixtures use vendor wire shapes without contacting live services."""
import json
from types import SimpleNamespace

import httpx
import pytest

from app.native_providers import AnthropicProvider, GoogleProvider, OpenAIResponsesProvider
from app.providers import ProviderError


def config(kind, *, search=True):
    return SimpleNamespace(
        base_url="https://api.example.test/v1beta" if kind == "google" else "https://api.example.test/v1",
        model="gemini-test" if kind == "google" else "model-test",
        api_key="sk-private-mock-key",
        timeout_seconds=5,
        provider_kind=kind,
        web_search=search,
    )


def sse(*events):
    return httpx.Response(200, text="".join(
        f"event: {name}\ndata: {json.dumps(body)}\n\n" for name, body in events
    ))


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,kind", [
    (OpenAIResponsesProvider, "openai_responses"),
    (GoogleProvider, "google"),
    (AnthropicProvider, "anthropic"),
])
async def test_search_is_only_in_enabled_chat_request(cls, kind):
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append((str(request.url), payload))
        if kind == "openai_responses":
            return sse(("response.output_text.delta", {"type": "response.output_text.delta", "delta": "reply"}),
                       ("response.completed", {"type": "response.completed", "response": {"output": []}}))
        if kind == "google":
            return sse(("", {"candidates": [{"content": {"parts": [{"text": "reply"}]}, "finishReason": "STOP"}]}))
        return sse(("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "reply"}}),
                   ("message_stop", {"type": "message_stop"}))

    for enabled in (False, True):
        provider = cls(config(kind, search=enabled), transport=httpx.MockTransport(handler))
        chunks = [chunk async for chunk in provider.stream_chat([{"role": "user", "content": "test"}])]
        assert any(chunk.kind == "content" and chunk.text == "reply" for chunk in chunks)
        if enabled:
            assert json.loads(chunks[-1].text)["status"] == "not_used"
        else:
            assert all(chunk.kind not in {"search_status", "search_sources"} for chunk in chunks)
    off, on = (payload for _, payload in seen)
    assert "tools" not in off
    if kind == "openai_responses":
        assert on["tools"] == [{"type": "web_search"}]
    elif kind == "google":
        assert on["tools"] == [{"googleSearch": {}}]
    else:
        assert on["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]


@pytest.mark.asyncio
async def test_openai_search_call_and_url_citation():
    def handler(request):
        assert str(request.url) == "https://api.example.test/v1/responses"
        return sse(
            ("response.output_item.done", {"type": "response.output_item.done", "item": {"type": "web_search_call", "status": "completed"}}),
            ("response.reasoning_summary_text.delta", {"type": "response.reasoning_summary_text.delta", "delta": "provider summary"}),
            ("response.output_text.delta", {"type": "response.output_text.delta", "delta": "answer"}),
            ("response.output_text.annotation.added", {"type": "response.output_text.annotation.added", "annotation": {"type": "url_citation", "url": "https://example.com/1", "title": "One"}}),
            ("response.completed", {"type": "response.completed", "response": {"output": []}}),
        )
    chunks = [c async for c in OpenAIResponsesProvider(config("openai_responses"), httpx.MockTransport(handler)).stream_chat([{"role": "user", "content": "q"}])]
    assert any(c.kind == "reasoning" and c.text == "provider summary" for c in chunks)
    assert json.loads(chunks[-2].text)["items"] == [{"title": "One", "url": "https://example.com/1"}]
    assert json.loads(chunks[-1].text)["status"] == "succeeded"


@pytest.mark.asyncio
async def test_google_grounding_and_sources():
    suggestion = '<div class="search-suggestion">Search suggestion</div>'
    def handler(request):
        assert str(request.url) == "https://api.example.test/v1beta/models/gemini-test:streamGenerateContent?alt=sse"
        return sse(("", {"candidates": [{"content": {"parts": [{"text": "answer"}]}, "finishReason": "STOP", "groundingMetadata": {"webSearchQueries": ["q"], "groundingChunks": [{"web": {"uri": "https://example.com/2", "title": "Two"}}], "searchEntryPoint": {"renderedContent": suggestion}}}]}))
    chunks = [c async for c in GoogleProvider(config("google"), httpx.MockTransport(handler)).stream_chat([{"role": "user", "content": "q"}])]
    assert json.loads(chunks[-2].text)["items"] == [{"title": "Two", "url": "https://example.com/2"}]
    assert json.loads(chunks[-2].text)["search_suggestions_html"] == suggestion
    assert json.loads(chunks[-1].text)["status"] == "succeeded"
    disabled = [c async for c in GoogleProvider(config("google", search=False), httpx.MockTransport(handler)).stream_chat([{"role": "user", "content": "q"}])]
    assert all(c.kind != "search_sources" and suggestion not in c.text for c in disabled)


@pytest.mark.asyncio
async def test_google_oversized_search_suggestion_is_omitted():
    def handler(_request):
        return sse(("", {"candidates": [{"content": {"parts": [{"text": "answer"}]}, "finishReason": "STOP", "groundingMetadata": {"webSearchQueries": ["q"], "searchEntryPoint": {"renderedContent": "x" * (64 * 1024 + 1)}}}]}))
    chunks = [c async for c in GoogleProvider(config("google"), httpx.MockTransport(handler)).stream_chat([{"role": "user", "content": "q"}])]
    assert not any(c.kind == "search_sources" for c in chunks)
    assert json.loads(chunks[-1].text)["status"] == "succeeded"


@pytest.mark.asyncio
async def test_anthropic_result_and_citation():
    def handler(request):
        return sse(
            ("content_block_start", {"type": "content_block_start", "content_block": {"type": "web_search_tool_result", "content": [{"type": "web_search_result", "url": "https://example.com/3", "title": "Three"}]}}),
            ("content_block_start", {"type": "content_block_start", "content_block": {"type": "text", "citations": [{"type": "web_search_result_location", "url": "https://example.com/3", "title": "Three"}]}}),
            ("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "answer"}}),
            ("message_stop", {"type": "message_stop"}),
        )
    chunks = [c async for c in AnthropicProvider(config("anthropic"), httpx.MockTransport(handler)).stream_chat([{"role": "user", "content": "q"}])]
    assert json.loads(chunks[-2].text)["items"] == [{"title": "Three", "url": "https://example.com/3"}]
    assert json.loads(chunks[-1].text)["status"] == "succeeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,kind,body", [
    (OpenAIResponsesProvider, "openai_responses", {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"ok":true}'}]}]}),
    (GoogleProvider, "google", {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '{"ok":true}'}]}}]}),
    (AnthropicProvider, "anthropic", {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"ok":true}'}]}),
])
async def test_generate_json_never_enables_search(cls, kind, body):
    def handler(request):
        payload = json.loads(request.content)
        assert "tools" not in payload
        assert payload["stream"] is False if kind != "google" else "tools" not in payload
        return httpx.Response(200, json=body)
    provider = cls(config(kind), httpx.MockTransport(handler))
    assert json.loads(await provider.generate_text([{"role": "user", "content": "json"}], json_mode=True)) == {"ok": True}


@pytest.mark.asyncio
async def test_truncation_and_secret_redaction():
    provider = OpenAIResponsesProvider(
        config("openai_responses"),
        httpx.MockTransport(lambda _: sse(("response.output_text.delta", {"type": "response.output_text.delta", "delta": "partial"}))),
    )
    with pytest.raises(ProviderError) as error:
        _ = [c async for c in provider.stream_chat([{"role": "user", "content": "q"}])]
    assert error.value.kind == "protocol_error"

    provider = AnthropicProvider(config("anthropic"), httpx.MockTransport(
        lambda _: httpx.Response(400, json={"error": {"message": "sk-private-mock-key is invalid"}})
    ))
    with pytest.raises(ProviderError) as error:
        await provider.generate_text([{"role": "user", "content": "q"}])
    assert "sk-private-mock-key" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,kind,response,expected", [
    (OpenAIResponsesProvider, "openai_responses", {"data": [{"id": "z"}, {"id": "a"}]}, ["a", "z"]),
    (GoogleProvider, "google", {"models": [{"name": "models/gemini-a"}]}, ["gemini-a"]),
    (AnthropicProvider, "anthropic", {"data": [{"id": "claude-a"}]}, ["claude-a"]),
])
async def test_model_discovery_contract(cls, kind, response, expected):
    # Gemini listModels has `name`; the other APIs use `id`.
    provider = cls(config(kind), httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
    assert await provider.list_models() == expected
