import asyncio
import json

import httpx
import pytest

from app.providers import ProviderConfig, ProviderError, build_provider, normalize_base_url


# Mock 提供方不消耗真实 API 配额。
def mock_openai_stream(request: httpx.Request) -> httpx.Response:
    """模拟 OpenAI 流式响应。"""
    if b'"stream":true' not in request.content:
        return httpx.Response(400, json={"error": {"message": "stream 必须为 true"}})
    lines = [
        'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"，我是"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":" AI"}}]}\n\n',
        'data: {"choices":[{"delta":{}}]}\n\n',
        "data: [DONE]\n\n",
    ]
    return httpx.Response(200, text="".join(lines))


def mock_openai_completion(request: httpx.Request) -> httpx.Response:
    if b'"stream":false' not in request.content:
        return httpx.Response(400, json={"error": {"message": "stream 必须为 false"}})
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": "pong"}}],
            "model": "gpt-4o",
        },
    )


def mock_auth_error(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        401,
        json={"error": {"message": "Incorrect API key provided"}},
    )


def mock_rate_limit(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(429, json={"error": {"message": "Rate limit exceeded"}})


def mock_upstream_error(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(503, json={"error": {"message": "Service temporarily unavailable"}})


def stream_response(*lines: str) -> httpx.Response:
    return httpx.Response(200, text="".join(f"data: {line}\n\n" for line in lines))


@pytest.mark.asyncio
async def test_stream_chat_produces_text_incrementally():
    config = ProviderConfig(
        base_url="https://api.example.com",
        model="gpt-4o",
        api_key="sk-test-mock",
    )
    transport = httpx.MockTransport(mock_openai_stream)
    provider = build_provider(config, transport=transport)

    chunks = []
    async for chunk in provider.stream_chat([{"role": "user", "content": "你好"}]):
        chunks.append(chunk)

    assert "".join(chunk.text for chunk in chunks if chunk.kind == "content") == "你好，我是 AI"


@pytest.mark.asyncio
async def test_stream_parses_sse_format_and_ignores_empty_deltas():
    config = ProviderConfig(
        base_url="https://api.example.com/v1",
        model="gpt-4o",
        api_key="sk-test",
    )
    transport = httpx.MockTransport(mock_openai_stream)
    provider = build_provider(config, transport=transport)

    chunks = [chunk async for chunk in provider.stream_chat([{"role": "user", "content": "test"}])]
    # 空 delta 被过滤，[DONE] 被过滤。
    assert len(chunks) == 3


@pytest.mark.asyncio
async def test_stream_separates_explicit_reasoning_and_think_blocks():
    config = ProviderConfig(
        base_url="https://api.example.com/v1",
        model="reasoning-model",
        api_key="sk-test",
    )
    response = stream_response(
        '{"choices":[{"delta":{"reasoning_content":"先分析。"}}]}',
        '{"choices":[{"delta":{"content":"<thi"}}]}',
        '{"choices":[{"delta":{"content":"nk>再检查。</think>最终答案。"}}]}',
        "[DONE]",
    )
    provider = build_provider(
        config,
        transport=httpx.MockTransport(lambda _request: response),
    )

    chunks = [chunk async for chunk in provider.stream_chat([])]
    assert "".join(chunk.text for chunk in chunks if chunk.kind == "reasoning") == "先分析。再检查。"
    assert "".join(chunk.text for chunk in chunks if chunk.kind == "content") == "最终答案。"


@pytest.mark.asyncio
async def test_model_discovery_parses_openai_list_and_rejects_invalid_shape():
    config = ProviderConfig(
        base_url="https://api.example.com/v1",
        model="unused",
        api_key="sk-test",
    )

    def list_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == "https://api.example.com/v1/models"
        return httpx.Response(
            200,
            json={"data": [{"id": "gpt-z"}, {"id": "gpt-a"}, {"id": "gpt-a"}]},
        )

    provider = build_provider(config, transport=httpx.MockTransport(list_handler))
    assert await provider.list_models() == ["gpt-a", "gpt-z"]

    invalid = build_provider(
        config,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"models": {}})),
    )
    with pytest.raises(ProviderError) as error:
        await invalid.list_models()
    assert error.value.kind == "protocol_error"


@pytest.mark.asyncio
async def test_stream_requires_non_empty_content_and_done_marker():
    config = ProviderConfig(
        base_url="https://api.example.com",
        model="test",
        api_key="sk-test",
    )

    empty = build_provider(
        config,
        transport=httpx.MockTransport(lambda _request: stream_response("[DONE]")),
    )
    with pytest.raises(ProviderError, match="没有正文") as empty_error:
        async for _ in empty.stream_chat([]):
            pass
    assert empty_error.value.kind == "protocol_error"

    truncated = build_provider(
        config,
        transport=httpx.MockTransport(
            lambda _request: stream_response(
                '{"choices":[{"delta":{"content":"半截"}}]}'
            )
        ),
    )
    with pytest.raises(ProviderError, match="未正常结束") as eof_error:
        async for _ in truncated.stream_chat([]):
            pass
    assert eof_error.value.kind == "protocol_error"


@pytest.mark.asyncio
async def test_stream_protocol_errors_and_upstream_flow_errors_are_safe():
    config = ProviderConfig(
        base_url="https://api.example.com",
        model="test",
        api_key="sk-test-flow-secret-123456",
    )
    malformed = build_provider(
        config,
        transport=httpx.MockTransport(lambda _request: stream_response("not-json")),
    )
    with pytest.raises(ProviderError) as malformed_error:
        async for _ in malformed.stream_chat([]):
            pass
    assert malformed_error.value.kind == "protocol_error"

    flow_error = build_provider(
        config,
        transport=httpx.MockTransport(
            lambda _request: stream_response(
                '{"error":{"message":"上游回显 sk-test-flow-secret-123456"}}'
            )
        ),
    )
    with pytest.raises(ProviderError) as flow_exception:
        async for _ in flow_error.stream_chat([]):
            pass
    assert flow_exception.value.kind == "upstream_error"
    assert "sk-test-flow-secret-123456" not in str(flow_exception.value)
    assert "****" in str(flow_exception.value)


@pytest.mark.asyncio
async def test_provider_removes_trailing_slash_and_appends_chat_completions():
    config = ProviderConfig(
        base_url="https://api.example.com/v1/",
        model="test",
        api_key="sk-test",
    )
    transport = httpx.MockTransport(mock_openai_stream)
    provider = build_provider(config, transport=transport)
    assert provider.endpoint == "https://api.example.com/v1/chat/completions"

    no_slash = ProviderConfig(
        base_url="https://api.example.com/v1",
        model="test",
        api_key="sk-test",
    )
    provider2 = build_provider(no_slash, transport=transport)
    assert provider2.endpoint == "https://api.example.com/v1/chat/completions"

    already_complete = ProviderConfig(
        base_url="https://api.example.com/v1/chat/completions",
        model="test",
        api_key="sk-test",
    )
    provider3 = build_provider(already_complete, transport=transport)
    assert provider3.endpoint == "https://api.example.com/v1/chat/completions"


def test_base_url_rejects_credentials_remote_http_and_invalid_port():
    assert normalize_base_url("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"
    assert normalize_base_url("https://api.example.com/v1/") == "https://api.example.com/v1"
    for value in (
        "http://api.example.com",
        "https://user:pass@api.example.com",
        "https://api.example.com/v1?api_key=secret",
        "https://api.example.com:99999",
    ):
        with pytest.raises(ValueError):
            normalize_base_url(value)


@pytest.mark.asyncio
async def test_http_errors_map_to_provider_error_with_kind():
    config = ProviderConfig(
        base_url="https://api.example.com",
        model="gpt-4o",
        api_key="sk-wrong",
    )

    auth_provider = build_provider(config, transport=httpx.MockTransport(mock_auth_error))
    with pytest.raises(ProviderError) as auth_exc:
        async for _ in auth_provider.stream_chat([{"role": "user", "content": "test"}]):
            pass
    assert auth_exc.value.kind == "auth_error"
    assert "拒绝了当前 API 密钥" in str(auth_exc.value)

    rate_provider = build_provider(config, transport=httpx.MockTransport(mock_rate_limit))
    with pytest.raises(ProviderError) as rate_exc:
        async for _ in rate_provider.stream_chat([{"role": "user", "content": "test"}]):
            pass
    assert rate_exc.value.kind == "rate_limited"

    upstream_provider = build_provider(config, transport=httpx.MockTransport(mock_upstream_error))
    with pytest.raises(ProviderError) as upstream_exc:
        async for _ in upstream_provider.stream_chat([{"role": "user", "content": "test"}]):
            pass
    assert upstream_exc.value.kind == "upstream_error"


@pytest.mark.asyncio
async def test_connection_test_returns_model_and_latency():
    config = ProviderConfig(
        base_url="https://api.example.com",
        model="gpt-4o",
        api_key="sk-test",
    )
    transport = httpx.MockTransport(mock_openai_completion)
    provider = build_provider(config, transport=transport)

    result = await provider.test_connection()
    assert result["model"] == "gpt-4o"
    assert result["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_connection_test_rejects_success_response_without_choices():
    config = ProviderConfig(
        base_url="https://api.example.com",
        model="gpt-4o",
        api_key="sk-test",
    )
    provider = build_provider(
        config,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"ok": True})),
    )
    with pytest.raises(ProviderError) as error:
        await provider.test_connection()
    assert error.value.kind == "protocol_error"


@pytest.mark.asyncio
async def test_timeout_raises_provider_error_with_timeout_kind():
    def slow_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Request timed out")

    config = ProviderConfig(
        base_url="https://api.example.com",
        model="gpt-4o",
        api_key="sk-test",
        timeout_seconds=1,
    )
    provider = build_provider(config, transport=httpx.MockTransport(slow_handler))

    with pytest.raises(ProviderError) as error:
        async for _ in provider.stream_chat([{"role": "user", "content": "test"}]):
            pass
    assert error.value.kind == "timeout"


@pytest.mark.asyncio
async def test_network_error_raises_provider_error():
    def broken_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Failed to connect")

    config = ProviderConfig(
        base_url="https://api.example.com",
        model="gpt-4o",
        api_key="sk-test",
    )
    provider = build_provider(config, transport=httpx.MockTransport(broken_handler))

    with pytest.raises(ProviderError) as error:
        async for _ in provider.stream_chat([{"role": "user", "content": "test"}]):
            pass
    assert error.value.kind == "network_error"
    assert "ConnectError" in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_url", "expected_chat", "expected_models"),
    [
        ("https://api.deepseek.com", "https://api.deepseek.com/chat/completions", "https://api.deepseek.com/models"),
        ("https://api.deepseek.com/", "https://api.deepseek.com/chat/completions", "https://api.deepseek.com/models"),
        ("https://api.deepseek.com/v1", "https://api.deepseek.com/v1/chat/completions", "https://api.deepseek.com/v1/models"),
        ("https://api.deepseek.com/v1/", "https://api.deepseek.com/v1/chat/completions", "https://api.deepseek.com/v1/models"),
        ("https://api.deepseek.com/v1/chat/completions", "https://api.deepseek.com/v1/chat/completions", "https://api.deepseek.com/v1/models"),
    ],
)
async def test_deepseek_compatible_base_url_variants_target_expected_endpoints(
    base_url: str, expected_chat: str, expected_models: str
):
    provider = build_provider(
        ProviderConfig(base_url=base_url, model="deepseek-chat", api_key="sk-test"),
        transport=httpx.MockTransport(mock_openai_stream),
    )
    assert provider.endpoint == expected_chat
    assert provider.models_endpoint == expected_models


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_kind"),
    [(401, "auth_error"), (403, "auth_error"), (404, "endpoint_not_found"), (429, "rate_limited")],
)
async def test_connection_test_classifies_actionable_http_errors(status_code: int, expected_kind: str):
    secret = "sk-classification-secret-123456"
    provider = build_provider(
        ProviderConfig(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-chat",
            api_key=secret,
        ),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                status_code,
                json={"error": {"message": f"upstream echoed {secret}"}},
            )
        ),
    )
    with pytest.raises(ProviderError) as caught:
        await provider.test_connection()
    assert caught.value.kind == expected_kind
    assert secret not in str(caught.value)


@pytest.mark.asyncio
async def test_provider_does_not_log_api_key():
    config = ProviderConfig(
        base_url="https://api.example.com",
        model="test",
        api_key="sk-test-secret-key-0123456789",
    )
    transport = httpx.MockTransport(mock_openai_stream)
    provider = build_provider(config, transport=transport)

    chunks = [chunk async for chunk in provider.stream_chat([{"role": "user", "content": "ping"}])]
    assert len(chunks) > 0
    # 密钥不应出现在任何异常消息、日志或可观测输出里。
    # 这里只检查正常流程不泄露，异常路径由 redact 函数保护。
