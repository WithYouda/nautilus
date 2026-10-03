"""Explicit native API adapters. Web search is opt-in for chat runs only.

Protocol references:
https://developers.openai.com/api/docs/guides/tools-web-search
https://ai.google.dev/api/generate-content
https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool
"""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator
from urllib.parse import quote, urlsplit

import httpx

from .providers import ProviderChunk, ProviderConfig, ProviderError, normalize_base_url
from .provider_network import ProviderHTTPClient
from .provider_messages import encode_messages

MAX_EVENT_BYTES = 512 * 1024
MAX_EVENTS = 10000
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_SOURCES = 100


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _array(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _status(kind: str, status: str) -> ProviderChunk:
    return ProviderChunk("search_status", json.dumps({"status": status, "provider": kind}))


def _sources(items: list[dict[str, str]], *, search_suggestions_html: str | None = None) -> ProviderChunk:
    payload: dict[str, Any] = {"items": items}
    if search_suggestions_html is not None:
        payload["search_suggestions_html"] = search_suggestions_html
    return ProviderChunk("search_sources", json.dumps(payload, ensure_ascii=False))


def _source(title: Any, url: Any) -> dict[str, str] | None:
    if not isinstance(url, str) or len(url) > 4096:
        return None
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        return None
    return {"title": str(title or parsed.netloc)[:300], "url": url}


class _NativeProvider:
    kind = ""
    endpoint_suffix = ""

    def __init__(self, config: ProviderConfig, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.config = config
        self._transport = transport

    @property
    def base(self) -> str:
        try:
            return normalize_base_url(self.config.base_url)
        except ValueError as error:
            raise ProviderError(str(error), kind="config_error") from error

    def _client(self) -> httpx.AsyncClient:
        return ProviderHTTPClient(
            timeout=httpx.Timeout(float(self.config.timeout_seconds), connect=10.0),
            transport=self._transport,
            diagnostics=getattr(self, 'diagnostics', None),
        )

    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _error(self, response: httpx.Response) -> ProviderError:
        status = response.status_code
        if status in (401, 403):
            return ProviderError("提供方拒绝了当前 API 密钥", kind="auth_error")
        if status == 429:
            return ProviderError("提供方限流，请稍后重试", kind="rate_limited")
        if status == 404:
            return ProviderError("提供方接口路径不存在，请核对 Base URL", kind="endpoint_not_found")
        return ProviderError(
            f"提供方服务异常（HTTP {status}）" if status >= 500 else f"提供方拒绝了请求（HTTP {status}）",
            kind="upstream_error" if status >= 500 else "request_error",
        )

    async def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._client() as client:
                async with client.stream("POST", url, headers=self._headers(), json=payload) as response:
                    if not response.is_success:
                        raise self._error(response)
                    body = await _read_bounded(response)
        except httpx.TimeoutException as error:
            raise ProviderError("提供方响应超时", kind="timeout") from error
        except httpx.HTTPError as error:
            raise ProviderError(f"无法连接提供方：{type(error).__name__}", kind="network_error") from error
        try:
            parsed = json.loads(body)
        except (ValueError, UnicodeDecodeError) as error:
            raise ProviderError("提供方响应无法解析", kind="protocol_error") from error
        if not isinstance(parsed, dict):
            raise ProviderError("提供方响应格式不正确", kind="protocol_error")
        return parsed

    async def _events(self, url: str, payload: dict[str, Any]) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        try:
            async with self._client() as client:
                async with client.stream("POST", url, headers=self._headers(), json=payload) as response:
                    if not response.is_success:
                        raise self._error(response)
                    event_name = ""
                    data_lines: list[str] = []
                    size = 0
                    count = 0
                    async for line in response.aiter_lines():
                        size += len(line.encode("utf-8"))
                        if size > MAX_EVENT_BYTES:
                            raise ProviderError("提供方流式事件过大", kind="protocol_error")
                        if not line:
                            if data_lines:
                                data = "\n".join(data_lines)
                                if data == "[DONE]":
                                    yield "[DONE]", {}
                                else:
                                    try:
                                        parsed = json.loads(data)
                                    except ValueError as error:
                                        raise ProviderError("提供方流式事件无法解析", kind="protocol_error") from error
                                    if not isinstance(parsed, dict):
                                        raise ProviderError("提供方流式事件格式不正确", kind="protocol_error")
                                    yield event_name, parsed
                                count += 1
                                if count > MAX_EVENTS:
                                    raise ProviderError("提供方流式事件过多", kind="protocol_error")
                            event_name, data_lines, size = "", [], 0
                        elif line.startswith("event:"):
                            event_name = line[6:].strip()
                        elif line.startswith("data:"):
                            data_lines.append(line[5:].strip())
                    if data_lines:
                        raise ProviderError("提供方流式响应未正常结束", kind="protocol_error")
        except httpx.TimeoutException as error:
            raise ProviderError("提供方响应超时", kind="timeout") from error
        except httpx.HTTPError as error:
            raise ProviderError(f"无法连接提供方：{type(error).__name__}", kind="network_error") from error

    async def list_models(self) -> list[str]:
        raise NotImplementedError

    async def _model_list(self, url: str, *, key: str = "data") -> list[str]:
        try:
            async with self._client() as client:
                async with client.stream("GET", url, headers=self._headers()) as response:
                    if not response.is_success:
                        raise self._error(response)
                    body = await _read_bounded(response)
        except httpx.TimeoutException as error:
            raise ProviderError("获取模型列表超时", kind="timeout") from error
        except httpx.HTTPError as error:
            raise ProviderError(f"无法获取模型列表：{type(error).__name__}", kind="network_error") from error
        try:
            parsed = json.loads(body)
        except (ValueError, UnicodeDecodeError) as error:
            raise ProviderError("提供方模型列表无法解析", kind="protocol_error") from error
        values = _object(parsed).get(key)
        if not isinstance(values, list):
            raise ProviderError("提供方模型列表格式不正确", kind="protocol_error")
        result = set()
        for value in values[:500]:
            model = (_object(value).get("name") if self.kind == "google" else _object(value).get("id")) if isinstance(value, dict) else value
            if isinstance(model, str) and 0 < len(model.strip()) <= 120:
                result.add(model.strip().removeprefix("models/") if self.kind == "google" else model.strip())
        return sorted(result, key=str.casefold)

    async def test_connection(self) -> dict[str, Any]:
        started = time.monotonic()
        await self.generate_text([{"role": "user", "content": "ping"}], max_tokens=32)
        return {"model": self.config.model, "latency_ms": int((time.monotonic() - started) * 1000)}


async def _read_bounded(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise ProviderError("提供方响应过大", kind="protocol_error")
        chunks.append(chunk)
    return b"".join(chunks)


class OpenAIResponsesProvider(_NativeProvider):
    kind = "openai_responses"

    @property
    def endpoint(self) -> str:
        base = self.base
        return base if base.endswith("/responses") else f"{base}/responses"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}

    def _payload(self, messages: list[dict[str, Any]], *, stream: bool, max_tokens: int | None = None, json_mode: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.config.model, "input": encode_messages(messages, self.kind), "stream": stream, "store": False}
        if max_tokens is not None:
            payload["max_output_tokens"] = max_tokens
        if json_mode:
            payload["text"] = {"format": {"type": "json_object"}}
        if stream and getattr(self.config, "web_search", False):
            payload["tools"] = [{"type": "web_search"}]
        return payload

    async def stream_chat(self, messages: list[dict[str, Any]]) -> AsyncIterator[ProviderChunk]:
        enabled = bool(getattr(self.config, "web_search", False))
        seen = False
        searched = False
        completed = False
        sources: dict[str, dict[str, str]] = {}
        if enabled:
            yield _status(self.kind, "running")
        async for event, body in self._events(self.endpoint, self._payload(messages, stream=True)):
            event = str(body.get("type") or event)
            if event == "response.output_text.delta":
                delta = body.get("delta")
                if isinstance(delta, str) and delta:
                    seen = True
                    yield ProviderChunk("content", delta)
            elif event in {"response.output_text.annotation.added", "response.output_item.done", "response.completed"}:
                annotation = _object(body.get("annotation"))
                item = _object(body.get("item"))
                candidates = [annotation]
                for content in _array(item.get("content")):
                    candidates.extend(_array(_object(content).get("annotations")))
                for output in _array(_object(body.get("response")).get("output")):
                    for content in _array(_object(output).get("content")):
                        candidates.extend(_array(_object(content).get("annotations")))
                for candidate in candidates:
                    candidate = _object(candidate)
                    if candidate.get("type") == "url_citation":
                        citation = _object(candidate.get("url_citation")) or candidate
                        source = _source(citation.get("title"), citation.get("url"))
                        if source:
                            sources[source["url"]] = source
                if item.get("type") == "web_search_call" and item.get("status") == "completed":
                    searched = True
                for output in _array(_object(body.get("response")).get("output")):
                    output = _object(output)
                    if output.get("type") == "web_search_call" and output.get("status") == "completed":
                        searched = True
                if event == "response.completed":
                    completed = True
            elif event in {"response.reasoning_text.delta", "response.reasoning_summary_text.delta"}:
                delta = body.get("delta")
                if isinstance(delta, str) and delta:
                    yield ProviderChunk("reasoning", delta)
            elif event in {"response.failed", "response.incomplete", "error"}:
                raise ProviderError("提供方未完成回复", kind="upstream_error")
            elif event == "[DONE]":
                break
        if not completed:
            raise ProviderError("提供方流式响应未正常结束", kind="protocol_error")
        if not seen:
            raise ProviderError("提供方流式响应没有正文", kind="protocol_error")
        if enabled:
            if sources:
                yield _sources(list(sources.values())[:MAX_SOURCES])
            yield _status(self.kind, "succeeded" if searched else "not_used")

    async def generate_text(self, messages: list[dict[str, Any]], *, max_tokens: int = 48, json_mode: bool = False) -> str:
        # Responses JSON mode requires an explicit JSON instruction in the input.
        inputs = ([{"role": "system", "content": "Return only a valid JSON object."}] + messages) if json_mode else messages
        body = await self._post_json(self.endpoint, self._payload(inputs, stream=False, max_tokens=max_tokens, json_mode=json_mode))
        if body.get("status") == "incomplete":
            raise ProviderError("提供方输出达到长度上限，结果不完整", kind="output_truncated")
        if body.get("status") != "completed":
            raise ProviderError("提供方未完成回复", kind="protocol_error")
        parts = [p.get("text") for item in _array(body.get("output")) if _object(item).get("type") == "message" for p in _array(_object(item).get("content")) if _object(p).get("type") == "output_text"]
        value = "".join(part for part in parts if isinstance(part, str))
        if not value.strip():
            raise ProviderError("提供方没有返回最终文本", kind="protocol_error")
        return value

    async def list_models(self) -> list[str]:
        base = self.base.removesuffix("/responses")
        return await self._model_list(f"{base}/models")


class GoogleProvider(_NativeProvider):
    kind = "google"

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.config.api_key, "Content-Type": "application/json"}

    def _endpoint(self, stream: bool) -> str:
        base = self.base
        model = quote(self.config.model.removeprefix("models/"), safe="")
        action = "streamGenerateContent?alt=sse" if stream else "generateContent"
        return f"{base}/models/{model}:{action}"

    def _payload(self, messages: list[dict[str, Any]], *, stream: bool, max_tokens: int | None = None, json_mode: bool = False) -> dict[str, Any]:
        system = "\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "system")
        contents = encode_messages(messages, self.kind)
        payload: dict[str, Any] = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        generation: dict[str, Any] = {}
        if max_tokens is not None:
            generation["maxOutputTokens"] = max_tokens
        if json_mode:
            generation["responseMimeType"] = "application/json"
        if generation:
            payload["generationConfig"] = generation
        if stream and getattr(self.config, "web_search", False):
            payload["tools"] = [{"googleSearch": {}}]
        return payload

    @staticmethod
    def _candidate(body: dict[str, Any]) -> dict[str, Any]:
        candidates = _array(body.get("candidates"))
        return _object(candidates[0]) if candidates else {}

    async def stream_chat(self, messages: list[dict[str, Any]]) -> AsyncIterator[ProviderChunk]:
        enabled = bool(getattr(self.config, "web_search", False))
        saw = False
        got_event = False
        finished = False
        grounded = False
        sources: dict[str, dict[str, str]] = {}
        search_suggestions_html: str | None = None
        if enabled:
            yield _status(self.kind, "running")
        async for event, body in self._events(self._endpoint(True), self._payload(messages, stream=True)):
            if event == "[DONE]":
                break
            got_event = True
            if "error" in body:
                raise ProviderError("提供方流式请求失败", kind="upstream_error")
            candidate = self._candidate(body)
            if not candidate:
                if body.get("promptFeedback"):
                    raise ProviderError("提供方未返回可用内容", kind="content_filtered")
                continue
            if candidate.get("finishReason") in {"MAX_TOKENS", "SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"}:
                raise ProviderError("提供方未完成回复", kind="output_truncated")
            if candidate.get("finishReason") not in {None, "STOP"}:
                raise ProviderError("提供方未完成回复", kind="protocol_error")
            if candidate.get("finishReason") == "STOP":
                finished = True
            for part in _array(_object(candidate.get("content")).get("parts")):
                part = _object(part)
                value = part.get("text")
                if not isinstance(value, str) or not value:
                    continue
                if part.get("thought") is True:
                    yield ProviderChunk("reasoning", value)
                else:
                    saw = True
                    yield ProviderChunk("content", value)
            grounding = _object(candidate.get("groundingMetadata"))
            suggestion = _object(grounding.get("searchEntryPoint")).get("renderedContent")
            if isinstance(suggestion, str) and len(suggestion.encode("utf-8")) <= 64 * 1024:
                search_suggestions_html = suggestion
            if grounding.get("webSearchQueries") or grounding.get("groundingChunks") or search_suggestions_html:
                grounded = True
            for chunk in _array(grounding.get("groundingChunks")):
                web = _object(_object(chunk).get("web"))
                source = _source(web.get("title"), web.get("uri"))
                if source:
                    sources[source["url"]] = source
        if not got_event or not finished:
            raise ProviderError("提供方流式响应未正常结束", kind="protocol_error")
        if not saw:
            raise ProviderError("提供方流式响应没有正文", kind="protocol_error")
        if enabled:
            if sources or search_suggestions_html is not None:
                yield _sources(list(sources.values())[:MAX_SOURCES], search_suggestions_html=search_suggestions_html)
            yield _status(self.kind, "succeeded" if grounded else "not_used")

    async def generate_text(self, messages: list[dict[str, Any]], *, max_tokens: int = 48, json_mode: bool = False) -> str:
        body = await self._post_json(self._endpoint(False), self._payload(messages, stream=False, max_tokens=max_tokens, json_mode=json_mode))
        candidate = self._candidate(body)
        if candidate.get("finishReason") == "MAX_TOKENS":
            raise ProviderError("提供方输出达到长度上限，结果不完整", kind="output_truncated")
        if candidate.get("finishReason") not in {"STOP", None}:
            raise ProviderError("提供方未完成回复", kind="content_filtered")
        value = "".join(str(part.get("text", "")) for part in _array(_object(candidate.get("content")).get("parts")) if isinstance(part, dict) and not part.get("thought"))
        if not value.strip():
            raise ProviderError("提供方没有返回最终文本", kind="protocol_error")
        return value

    async def list_models(self) -> list[str]:
        return await self._model_list(f"{self.base}/models", key="models")


class AnthropicProvider(_NativeProvider):
    kind = "anthropic"

    @property
    def endpoint(self) -> str:
        base = self.base
        return base if base.endswith("/messages") else f"{base}/messages"

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.config.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}

    def _payload(self, messages: list[dict[str, Any]], *, stream: bool, max_tokens: int = 4096, json_mode: bool = False) -> dict[str, Any]:
        system = "\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "system")
        converted = encode_messages(messages, self.kind)
        payload: dict[str, Any] = {"model": self.config.model, "messages": converted, "max_tokens": max_tokens, "stream": stream}
        if json_mode:
            system += "\nReturn only a valid JSON object." if system else "Return only a valid JSON object."
        if system:
            payload["system"] = system
        if stream and getattr(self.config, "web_search", False):
            payload["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
        return payload

    async def stream_chat(self, messages: list[dict[str, Any]]) -> AsyncIterator[ProviderChunk]:
        enabled = bool(getattr(self.config, "web_search", False))
        saw = False
        completed = False
        searched = False
        sources: dict[str, dict[str, str]] = {}
        if enabled:
            yield _status(self.kind, "running")
        async for event, body in self._events(self.endpoint, self._payload(messages, stream=True)):
            kind = str(body.get("type") or event)
            if kind == "error":
                raise ProviderError("提供方流式请求失败", kind="upstream_error")
            if kind == "content_block_start":
                block = _object(body.get("content_block"))
                if block.get("type") == "web_search_tool_result":
                    result = block.get("content")
                    if isinstance(result, dict) and result.get("type") == "web_search_tool_result_error":
                        raise ProviderError("提供方网络搜索失败", kind="upstream_error")
                    if isinstance(result, list):
                        searched = True
                        for item in result:
                            item = _object(item)
                            if item.get("type") == "web_search_result":
                                source = _source(item.get("title"), item.get("url"))
                                if source:
                                    sources[source["url"]] = source
                for citation in _array(block.get("citations")):
                    citation = _object(citation)
                    if citation.get("type") == "web_search_result_location":
                        source = _source(citation.get("title"), citation.get("url"))
                        if source:
                            sources[source["url"]] = source
            elif kind == "content_block_delta":
                delta = _object(body.get("delta"))
                if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str) and delta["text"]:
                    saw = True
                    yield ProviderChunk("content", delta["text"])
                elif delta.get("type") == "thinking_delta" and isinstance(delta.get("thinking"), str):
                    yield ProviderChunk("reasoning", delta["thinking"])
                elif delta.get("type") == "citations_delta":
                    citation = _object(delta.get("citation"))
                    if citation.get("type") == "web_search_result_location":
                        source = _source(citation.get("title"), citation.get("url"))
                        if source:
                            sources[source["url"]] = source
            elif kind == "message_delta":
                reason = _object(body.get("delta")).get("stop_reason")
                if reason == "max_tokens":
                    raise ProviderError("提供方输出达到长度上限，结果不完整", kind="output_truncated")
            elif kind == "message_stop":
                completed = True
            elif kind == "[DONE]":
                break
        if not completed:
            raise ProviderError("提供方流式响应未正常结束", kind="protocol_error")
        if not saw:
            raise ProviderError("提供方流式响应没有正文", kind="protocol_error")
        if enabled:
            if sources:
                yield _sources(list(sources.values())[:MAX_SOURCES])
            yield _status(self.kind, "succeeded" if searched else "not_used")

    async def generate_text(self, messages: list[dict[str, Any]], *, max_tokens: int = 48, json_mode: bool = False) -> str:
        body = await self._post_json(self.endpoint, self._payload(messages, stream=False, max_tokens=max_tokens, json_mode=json_mode))
        if body.get("stop_reason") == "max_tokens":
            raise ProviderError("提供方输出达到长度上限，结果不完整", kind="output_truncated")
        value = "".join(str(item.get("text", "")) for item in _array(body.get("content")) if isinstance(item, dict) and item.get("type") == "text")
        if not value.strip():
            raise ProviderError("提供方没有返回最终文本", kind="protocol_error")
        if json_mode:
            try:
                parsed = json.loads(value)
            except ValueError as error:
                raise ProviderError("提供方未返回有效 JSON", kind="protocol_error") from error
            if not isinstance(parsed, dict):
                raise ProviderError("提供方未返回 JSON 对象", kind="protocol_error")
        return value

    async def list_models(self) -> list[str]:
        return await self._model_list(f"{self.base.removesuffix('/messages')}/models")
