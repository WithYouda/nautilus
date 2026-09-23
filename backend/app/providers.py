from __future__ import annotations

import ipaddress
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Literal
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("nautilus.providers")

MAX_ERROR_DETAIL = 300
MAX_ERROR_BODY_BYTES = 64 * 1024
MAX_MODELS_BODY_BYTES = 512 * 1024
MAX_DISCOVERED_MODELS = 500
# 常见密钥前缀，用于抹掉提供方在错误正文里回显的密钥片段。
SECRET_PATTERN = re.compile(r"\b(?:sk|api|key|token)[-_][A-Za-z0-9_-]{6,}", re.IGNORECASE)


class ProviderError(RuntimeError):
    """提供方调用失败。消息与 kind 都不包含密钥或完整请求体。"""

    def __init__(self, message: str, kind: str = "provider_error") -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class ProviderConfig:
    """一次出站调用需要的配置。api_key 只在内存中出现，不写库不写日志。"""

    base_url: str
    model: str
    api_key: str
    timeout_seconds: int = 60
    provider_kind: str = "openai_compatible"


@dataclass(frozen=True)
class ProviderChunk:
    kind: Literal["content", "reasoning"]
    text: str


class _ThinkStreamParser:
    """把正文流里的 <think> 块拆成推理增量，并兼容标签跨 chunk。"""

    def __init__(self) -> None:
        self.buffer = ""
        self.in_reasoning = False

    def feed(self, text: str) -> list[ProviderChunk]:
        self.buffer += text
        chunks: list[ProviderChunk] = []
        while self.buffer:
            marker = "</think>" if self.in_reasoning else "<think>"
            index = self.buffer.find(marker)
            if index >= 0:
                self._emit(chunks, self.buffer[:index])
                self.buffer = self.buffer[index + len(marker) :]
                self.in_reasoning = not self.in_reasoning
                continue
            keep = 0
            for size in range(1, len(marker)):
                if self.buffer.endswith(marker[:size]):
                    keep = size
            ready = self.buffer[:-keep] if keep else self.buffer
            self._emit(chunks, ready)
            self.buffer = self.buffer[-keep:] if keep else ""
            break
        return chunks

    def finish(self) -> list[ProviderChunk]:
        chunks: list[ProviderChunk] = []
        self._emit(chunks, self.buffer)
        self.buffer = ""
        return chunks

    def _emit(self, chunks: list[ProviderChunk], text: str) -> None:
        if text:
            chunks.append(
                ProviderChunk(
                    kind="reasoning" if self.in_reasoning else "content",
                    text=text,
                )
            )


def normalize_base_url(value: str) -> str:
    """校验兼容端点，避免凭据落入 URL 或经明文远程 HTTP 发送。"""
    base = value.strip().rstrip("/")
    try:
        parsed = urlsplit(base)
        host = parsed.hostname
        parsed.port
    except ValueError as error:
        raise ValueError("base URL 格式不正确") from error
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not host:
        raise ValueError("base URL 必须是带主机名的 http:// 或 https:// 地址")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base URL 不能包含用户名或密码")
    if parsed.query or parsed.fragment:
        raise ValueError("base URL 不能包含查询参数或 fragment")
    if any(ord(char) < 0x20 or char.isspace() for char in base):
        raise ValueError("base URL 不能包含空白或控制字符")
    if parsed.scheme == "http":
        normalized_host = host.lower().rstrip(".")
        is_loopback = normalized_host in {"localhost", "localhost.localdomain"}
        if not is_loopback:
            try:
                is_loopback = ipaddress.ip_address(normalized_host).is_loopback
            except ValueError:
                is_loopback = False
        if not is_loopback:
            raise ValueError("远程提供方必须使用 HTTPS；HTTP 仅允许回环地址")
    return base


def _truncate(text: str) -> str:
    flat = " ".join(text.split())
    return flat[:MAX_ERROR_DETAIL] if len(flat) > MAX_ERROR_DETAIL else flat


def redact(text: str, secret: str | None = None) -> str:
    """抹掉提供方回显的密钥片段，避免错误信息把密钥带回前端或日志。"""
    cleaned = text
    if secret:
        cleaned = cleaned.replace(secret, "****")
        if len(secret) > 12:
            cleaned = cleaned.replace(secret[:8], "****").replace(secret[-8:], "****")
    return SECRET_PATTERN.sub("****", cleaned)



class OpenAICompatibleProvider:
    """兼容 OpenAI Chat Completions 风格的适配器。

    只依赖已有的 httpx，不引入官方 SDK：该端点协议稳定，少一个依赖，
    并且测试可以直接用 ``httpx.MockTransport`` 而不触碰真实 API。
    """

    kind = "openai_compatible"

    def __init__(
        self,
        config: ProviderConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport

    # ------------------------------------------------------------------
    @property
    def endpoint(self) -> str:
        try:
            base = normalize_base_url(self.config.base_url)
        except ValueError as error:
            raise ProviderError(str(error), kind="config_error") from error
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    @property
    def models_endpoint(self) -> str:
        try:
            base = normalize_base_url(self.config.base_url)
        except ValueError as error:
            raise ProviderError(str(error), kind="config_error") from error
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        if base.endswith("/models"):
            return base
        return f"{base}/models"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(float(self.config.timeout_seconds), connect=10.0),
            transport=self._transport,
        )

    # ------------------------------------------------------------------
    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[ProviderChunk]:
        """逐块产出正文增量。异常统一为 ProviderError，便于写入 ai_run.error_kind。"""
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": True,
        }
        try:
            async with self._client() as client:
                async with client.stream(
                    "POST", self.endpoint, headers=self._headers(), json=payload
                ) as response:
                    if not 200 <= response.status_code < 300:
                        body = await self._read_limited(response)
                        raise self._http_error(response.status_code, body)
                    terminal = False
                    saw_content = False
                    think_parser = _ThinkStreamParser()
                    async for line in response.aiter_lines():
                        chunks, line_terminal = self._parse_stream_event(
                            line, secret=self.config.api_key
                        )
                        for chunk in chunks:
                            normalized = (
                                think_parser.feed(chunk.text)
                                if chunk.kind == "content"
                                else [chunk]
                            )
                            for item in normalized:
                                saw_content = saw_content or item.kind == "content"
                                yield item
                        if line_terminal:
                            terminal = True
                            break
                    for item in think_parser.finish():
                        saw_content = saw_content or item.kind == "content"
                        yield item
                    if not terminal:
                        raise ProviderError(
                            "提供方流式响应未正常结束", kind="protocol_error"
                        )
                    if not saw_content:
                        raise ProviderError(
                            "提供方流式响应没有正文", kind="protocol_error"
                        )
        except httpx.TimeoutException as error:
            raise ProviderError("提供方响应超时", kind="timeout") from error
        except httpx.HTTPError as error:
            # 只记录异常类型，不记录 URL 之外的请求内容，避免带出密钥。
            raise ProviderError(
                f"无法连接提供方：{type(error).__name__}", kind="network_error"
            ) from error

    async def generate_text(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 48,
        json_mode: bool = False,
    ) -> str:
        """执行一次短的非流式文本请求，用于标题等轻量后台任务。"""
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            async with self._client() as client:
                response = await client.post(
                    self.endpoint,
                    headers={**self._headers(), "Accept": "application/json"},
                    json=payload,
                )
        except httpx.TimeoutException as error:
            raise ProviderError("提供方响应超时", kind="timeout") from error
        except httpx.HTTPError as error:
            raise ProviderError(
                f"无法连接提供方：{type(error).__name__}", kind="network_error"
            ) from error
        if not 200 <= response.status_code < 300:
            raise self._http_error(response.status_code, response.content)
        try:
            parsed = response.json()
        except (ValueError, json.JSONDecodeError) as error:
            raise ProviderError("提供方非流式响应无法解析", kind="protocol_error") from error
        if not isinstance(parsed, dict):
            raise ProviderError("提供方非流式响应格式不正确", kind="protocol_error")
        choices = parsed.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderError("提供方非流式响应缺少 choices", kind="protocol_error")
        if choices[0].get("finish_reason") == "length":
            raise ProviderError("提供方输出达到长度上限，结果不完整", kind="output_truncated")
        if choices[0].get("finish_reason") == "content_filter":
            raise ProviderError("提供方未返回可用内容", kind="content_filtered")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise ProviderError("提供方非流式响应缺少 message", kind="protocol_error")
        content = message.get("content")
        if message.get("refusal"):
            raise ProviderError("提供方拒绝生成本次内容", kind="content_filtered")
        if not isinstance(content, str) or not content.strip():
            reasoning_content = message.get("reasoning_content")
            if isinstance(reasoning_content, str) and reasoning_content.strip():
                raise ProviderError(
                    "提供方只返回了推理过程，没有给出最终文本",
                    kind="reasoning_only",
                )
            raise ProviderError("提供方非流式响应没有正文", kind="protocol_error")
        # Only strip an explicit leading reasoning preamble. A literal <think>
        # inside a JSON string or code sample belongs to the final answer.
        final = content
        if content.lstrip().startswith("<think>"):
            _reasoning, separator, final = content.partition("</think>")
            if not separator:
                final = ""
        if not final.strip():
            raise ProviderError("提供方没有返回最终文本", kind="reasoning_only")
        return final

    @staticmethod
    def _parse_stream_event(
        line: str, *, secret: str | None = None
    ) -> tuple[list[ProviderChunk], bool]:
        """解析一行 SSE，返回（规范化增量、是否终止）。"""
        stripped = line.strip()
        if not stripped or not stripped.startswith("data:"):
            return [], False
        data = stripped[len("data:") :].strip()
        if not data:
            return [], False
        if data == "[DONE]":
            return [], True
        try:
            event = json.loads(data)
        except json.JSONDecodeError as error:
            raise ProviderError("提供方返回了无法解析的流数据", kind="protocol_error") from error
        if not isinstance(event, dict):
            raise ProviderError("提供方返回了无效的流数据", kind="protocol_error")
        if "error" in event:
            detail = event.get("error")
            if isinstance(detail, dict):
                detail = detail.get("message", "")
            raise ProviderError(
                _truncate(redact(str(detail), secret)) or "提供方流式请求失败",
                kind="upstream_error",
            )
        choices = event.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError("提供方返回了无效的流数据", kind="protocol_error")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ProviderError("提供方返回了无效的流数据", kind="protocol_error")
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            raise ProviderError("提供方返回了无效的流数据", kind="protocol_error")
        content = delta.get("content")
        if content is not None and not isinstance(content, str):
            raise ProviderError("提供方返回了无效的正文增量", kind="protocol_error")
        reasoning = delta.get("reasoning_content", delta.get("reasoning"))
        if reasoning is not None and not isinstance(reasoning, str):
            raise ProviderError("提供方返回了无效的推理增量", kind="protocol_error")
        # Chat Completions 流通常先发 finish_reason、随后再发 [DONE]。
        # 这里不把 finish_reason 当终止，否则会吞掉缺失 [DONE] 的截断响应。
        chunks: list[ProviderChunk] = []
        if reasoning:
            chunks.append(ProviderChunk(kind="reasoning", text=reasoning))
        if content:
            chunks.append(ProviderChunk(kind="content", text=content))
        return chunks, False

    @staticmethod
    def _parse_stream_line(line: str) -> str | None:
        """兼容旧的内部调用：只返回正文增量。"""
        chunks, _terminal = OpenAICompatibleProvider._parse_stream_event(line)
        return "".join(chunk.text for chunk in chunks if chunk.kind == "content") or None

    async def list_models(self) -> list[str]:
        """读取 OpenAI 兼容模型列表，返回去重排序后的模型 ID。"""
        try:
            async with self._client() as client:
                async with client.stream(
                    "GET",
                    self.models_endpoint,
                    headers={**self._headers(), "Accept": "application/json"},
                ) as response:
                    if not 200 <= response.status_code < 300:
                        body = await self._read_limited(response)
                        raise self._http_error(response.status_code, body)
                    body = await self._read_limited(response, limit=MAX_MODELS_BODY_BYTES)
        except httpx.TimeoutException as error:
            raise ProviderError("获取模型列表超时", kind="timeout") from error
        except httpx.HTTPError as error:
            raise ProviderError(
                f"无法获取模型列表：{type(error).__name__}", kind="network_error"
            ) from error
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderError("提供方模型列表响应无法解析", kind="protocol_error") from error
        source = parsed.get("data") if isinstance(parsed, dict) else parsed
        if not isinstance(source, list):
            raise ProviderError("提供方模型列表格式不正确", kind="protocol_error")
        models: set[str] = set()
        for item in source:
            candidate = item.get("id") if isinstance(item, dict) else item
            if isinstance(candidate, str):
                candidate = candidate.strip()
                if candidate and len(candidate) <= 120:
                    models.add(candidate)
            if len(models) >= MAX_DISCOVERED_MODELS:
                break
        return sorted(models, key=str.casefold)

    @staticmethod
    async def _read_limited(
        response: httpx.Response, *, limit: int = MAX_ERROR_BODY_BYTES
    ) -> bytes:
        parts: list[bytes] = []
        size = 0
        async for part in response.aiter_bytes():
            remaining = limit - size
            if remaining <= 0:
                break
            parts.append(part[:remaining])
            size += min(len(part), remaining)
            if size >= limit:
                break
        return b"".join(parts)

    # ------------------------------------------------------------------
    async def test_connection(self) -> dict[str, Any]:
        """连接测试。自动化测试用 Mock HTTP，不消耗真实 API。"""
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
            "max_tokens": 1,
        }
        started = time.monotonic()
        try:
            async with self._client() as client:
                response = await client.post(
                    self.endpoint,
                    headers={**self._headers(), "Accept": "application/json"},
                    json=payload,
                )
        except httpx.TimeoutException as error:
            raise ProviderError("提供方响应超时", kind="timeout") from error
        except httpx.HTTPError as error:
            raise ProviderError(
                f"无法连接提供方：{type(error).__name__}", kind="network_error"
            ) from error
        if not 200 <= response.status_code < 300:
            raise self._http_error(response.status_code, response.content)
        try:
            parsed = response.json()
        except (ValueError, json.JSONDecodeError) as error:
            raise ProviderError("提供方连接测试返回了无效响应", kind="protocol_error") from error
        if (
            not isinstance(parsed, dict)
            or not isinstance(parsed.get("choices"), list)
            or not parsed["choices"]
            or not isinstance(parsed["choices"][0], dict)
        ):
            raise ProviderError("提供方连接测试返回了无效响应", kind="protocol_error")
        return {
            "model": self.config.model,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }

    # ------------------------------------------------------------------
    def _http_error(self, status_code: int, body: bytes) -> ProviderError:
        detail = ""
        try:
            parsed = json.loads(body.decode("utf-8"))
            if isinstance(parsed, dict):
                error_block = parsed.get("error")
                if isinstance(error_block, dict):
                    detail = str(error_block.get("message", ""))
                elif isinstance(error_block, str):
                    detail = error_block
                if not detail:
                    detail = str(parsed.get("message", ""))
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = ""
        if status_code in (401, 403):
            kind = "auth_error"
            message = "提供方拒绝了当前 API 密钥"
        elif status_code == 429:
            kind = "rate_limited"
            message = "提供方限流，请稍后重试"
        elif status_code == 404:
            kind = "endpoint_not_found"
            message = "提供方接口路径不存在，请核对 Base URL 是否需要 /v1"
        elif status_code >= 500:
            kind = "upstream_error"
            message = f"提供方服务异常（HTTP {status_code}）"
        else:
            kind = "request_error"
            message = f"提供方拒绝了请求（HTTP {status_code}）"
        if detail:
            # 提供方有时会把密钥回显在错误里，写进 ai_run 之前必须抹掉。
            message = f"{message}：{_truncate(redact(detail, self.config.api_key))}"
        return ProviderError(message, kind=kind)


class ProviderAdapterRegistry:
    """按 provider_kind 创建适配器；新增提供方时只扩展注册表。"""

    def __init__(self) -> None:
        self._factories: dict[str, type[OpenAICompatibleProvider]] = {
            OpenAICompatibleProvider.kind: OpenAICompatibleProvider,
        }

    def build(
        self,
        config: ProviderConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> OpenAICompatibleProvider:
        factory = self._factories.get(config.provider_kind)
        if factory is None:
            raise ProviderError(
                f"暂不支持提供方类型：{config.provider_kind}",
                kind="unsupported_provider",
            )
        return factory(config, transport=transport)

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


provider_adapter_registry = ProviderAdapterRegistry()


def build_provider(
    config: ProviderConfig,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OpenAICompatibleProvider:
    return provider_adapter_registry.build(config, transport=transport)
