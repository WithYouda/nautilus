from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from .conversations import ConversationError, ConversationService
from .providers import ProviderChunk, ProviderConfig, ProviderError, build_provider

logger = logging.getLogger("nautilus.ai")

# 已完成的运行在内存中保留一段时间，供刷新后的重放使用。
MAX_RETAINED_RUNS = 64
HEARTBEAT_SECONDS = 15.0
MAX_RESPONSE_CHARS = 1_000_000
MAX_CONCURRENT_PROVIDER_RUNS = 4
SUBSCRIBER_QUEUE_SIZE = 256
TITLE_MAX_OUTPUT_TOKENS = 512
_SUBSCRIBER_OVERFLOW = object()


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@dataclass
class RunState:
    """一次 AI 运行的内存态。生成在后台 task 上跑，SSE 只是订阅者。"""

    run_id: str
    conversation_id: str
    identity_id: str
    response_message_id: str
    chunks: list[str] = field(default_factory=list)
    reasoning_chunks: list[str] = field(default_factory=list)
    response_chars: int = 0
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    status: str = "queued"
    error_kind: str | None = None
    error_message: str | None = None
    finished: bool = False
    cancel_requested: bool = False
    task: asyncio.Task | None = None

    @property
    def text(self) -> str:
        return "".join(self.chunks)

    @property
    def reasoning_text(self) -> str:
        return "".join(self.reasoning_chunks)


class AiRunManager:
    """把 AI 生成和 SSE 连接解耦。

    浏览器断开或刷新只会移除一个订阅者，不会杀掉生成；重连时先重放
    已经产生的文本，再继续接收增量。重复提交由 message 上
    ``(conversation_id, client_message_id)`` 唯一索引挡住，不会产生第二次运行。
    """

    def __init__(
        self,
        conversations: ConversationService,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.conversations = conversations
        # 测试通过注入 httpx.MockTransport 完成，不调用真实 API。
        self.transport = transport
        self._runs: "OrderedDict[str, RunState]" = OrderedDict()
        self._provider_slots = asyncio.Semaphore(MAX_CONCURRENT_PROVIDER_RUNS)
        self._title_tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    async def start(
        self,
        identity_id: str,
        conversation_id: str,
        *,
        content: str,
        client_message_id: str,
    ) -> dict[str, Any]:
        prepared = self.conversations.prepare_run(
            identity_id,
            conversation_id,
            content=content,
            client_message_id=client_message_id,
        )
        run = prepared["run"]
        if not prepared["created"]:
            # 幂等命中：同一个 client_message_id 只对应一次 AI 运行。
            return {"run": run, "created": False}

        state = RunState(
            run_id=run["id"],
            conversation_id=conversation_id,
            identity_id=identity_id,
            response_message_id=run["response_message_id"],
        )
        self._runs[state.run_id] = state
        self._evict()
        try:
            messages = self.conversations.build_prompt(
                prepared["history"], prepared["context"]
            )
            state.task = asyncio.create_task(
                self._execute(state, messages, prepared["provider_config"])
            )
        except Exception as error:
            self._finish(
                state,
                "failed",
                kind="startup_error",
                message="无法启动 AI 运行",
            )
            raise ConversationError("无法启动 AI 运行") from error
        return {"run": run, "created": True}

    def _evict(self) -> None:
        if len(self._runs) <= MAX_RETAINED_RUNS:
            return
        for run_id in [key for key, value in self._runs.items() if value.finished]:
            if len(self._runs) <= MAX_RETAINED_RUNS:
                break
            self._runs.pop(run_id, None)

    # ------------------------------------------------------------------
    async def _execute(
        self,
        state: RunState,
        messages: list[dict[str, str]],
        config: ProviderConfig,
    ) -> None:
        stream: AsyncIterator[ProviderChunk] | None = None
        try:
            provider = build_provider(config, transport=self.transport)
            async with self._provider_slots:
                if not self.conversations.mark_run_running(state.run_id):
                    run = self.conversations.owned_run(state.identity_id, state.run_id)
                    state.status = run["status"]
                    state.finished = run["status"] in {"succeeded", "failed", "canceled"}
                    self._broadcast(state, None)
                    return
                state.status = "running"
                stream = provider.stream_chat(messages)
                async with asyncio.timeout(float(config.timeout_seconds)):
                    async for chunk in stream:
                        if state.cancel_requested:
                            break
                        remaining = MAX_RESPONSE_CHARS - state.response_chars
                        if remaining <= 0:
                            raise ProviderError("AI 回复超过长度限制", kind="output_limit")
                        accepted = chunk.text[:remaining]
                        if accepted:
                            if chunk.kind == "reasoning":
                                state.reasoning_chunks.append(accepted)
                            else:
                                state.chunks.append(accepted)
                            state.response_chars += len(accepted)
                            self._broadcast(
                                state,
                                sse_event(
                                    "delta",
                                    {"kind": chunk.kind, "text": accepted},
                                ),
                            )
                        if len(accepted) != len(chunk.text):
                            raise ProviderError("AI 回复超过长度限制", kind="output_limit")
            self._finish(state, "canceled" if state.cancel_requested else "succeeded")
            if state.status == "succeeded":
                self._schedule_automatic_title(state, config)
        except asyncio.CancelledError:
            self._finish(state, "canceled")
            raise
        except TimeoutError:
            self._finish(state, "failed", kind="timeout", message="提供方响应超时")
        except ProviderError as error:
            self._finish(state, "failed", kind=error.kind, message=str(error))
        except Exception:  # noqa: BLE001 - 兜底，错误详情不外泄
            logger.exception("AI 运行失败：%s", state.run_id)
            self._finish(state, "failed", kind="internal_error", message="AI 运行内部错误")
        finally:
            if stream is not None:
                with suppress(Exception, asyncio.CancelledError):
                    await stream.aclose()

    def _track_title_task(self, task: asyncio.Task) -> None:
        self._title_tasks.add(task)
        task.add_done_callback(self._title_tasks.discard)

    def _schedule_automatic_title(self, state: RunState, config: ProviderConfig) -> None:
        try:
            prepared = self.conversations.prepare_automatic_title_run(
                state.identity_id,
                state.conversation_id,
                state.run_id,
            )
        except Exception:  # noqa: BLE001 - 标题失败不得影响主回复
            logger.exception("无法创建自动标题运行：%s", state.conversation_id)
            return
        if not prepared:
            return
        task = asyncio.create_task(
            self._execute_title_run(
                prepared["run"]["id"],
                prepared["inputs"],
                config,
            )
        )
        self._track_title_task(task)

    async def start_title_regeneration(
        self,
        identity_id: str,
        conversation_id: str,
    ) -> dict[str, Any]:
        prepared = self.conversations.prepare_manual_title_run(identity_id, conversation_id)
        task = asyncio.create_task(
            self._execute_title_run(
                prepared["run"]["id"],
                prepared["inputs"],
                prepared["provider_config"],
            )
        )
        self._track_title_task(task)
        return prepared["run"]

    async def _execute_title_run(
        self,
        title_run_id: str,
        inputs: list[dict[str, str]],
        config: ProviderConfig,
    ) -> None:
        try:
            if not self.conversations.mark_title_run_running(title_run_id):
                return
            title_config = ProviderConfig(
                base_url=config.base_url,
                model=config.model,
                api_key=config.api_key,
                timeout_seconds=max(5, min(int(config.timeout_seconds), 30)),
                provider_kind=config.provider_kind,
            )
            provider = build_provider(title_config, transport=self.transport)
            prompt = self.conversations.build_title_prompt(inputs)
            async with self._provider_slots:
                async with asyncio.timeout(float(title_config.timeout_seconds)):
                    title = await provider.generate_text(
                        prompt,
                        max_tokens=TITLE_MAX_OUTPUT_TOKENS,
                    )
            self.conversations.finalize_title_run(
                title_run_id,
                "succeeded",
                generated_title=title,
            )
        except asyncio.CancelledError:
            self.conversations.finalize_title_run(
                title_run_id,
                "failed",
                error_kind="interrupted",
                error_message="服务正在关闭，标题生成被中断",
            )
            raise
        except TimeoutError:
            self.conversations.finalize_title_run(
                title_run_id,
                "failed",
                error_kind="timeout",
                error_message="标题生成超时",
            )
        except ProviderError as error:
            self.conversations.finalize_title_run(
                title_run_id,
                "failed",
                error_kind=error.kind,
                error_message=str(error),
            )
        except ConversationError as error:
            self.conversations.finalize_title_run(
                title_run_id,
                "failed",
                error_kind="invalid_title",
                error_message=str(error),
            )
        except Exception:  # noqa: BLE001 - 独立后台任务不得影响正常对话
            logger.exception("标题运行失败：%s", title_run_id)
            self.conversations.finalize_title_run(
                title_run_id,
                "failed",
                error_kind="internal_error",
                error_message="标题生成内部错误",
            )

    def _finish(
        self,
        state: RunState,
        status: str,
        *,
        kind: str | None = None,
        message: str | None = None,
    ) -> None:
        if state.finished:
            return
        try:
            persisted_status = self.conversations.finalize_run(
                state.run_id,
                status,
                content=state.text,
                reasoning_content=state.reasoning_text,
                error_kind=kind,
                error_message=message,
            )
        except Exception:  # noqa: BLE001 - 收敛失败不能再抛进后台 task
            logger.exception("无法收敛 AI 运行记录：%s", state.run_id)
            status = "failed"
            kind = "persistence_error"
            message = "AI 回复保存失败，请重新加载后重试"
            try:
                persisted_status = self.conversations.finalize_run(
                    state.run_id,
                    status,
                    content=state.text,
                    reasoning_content=state.reasoning_text,
                    error_kind=kind,
                    error_message=message,
                )
            except Exception:  # noqa: BLE001 - 数据库持续失败时只能在内存中报错
                logger.exception("无法记录 AI 持久化失败：%s", state.run_id)
                persisted_status = status
        state.status = persisted_status or status
        if state.status == "failed":
            state.error_kind = kind
            state.error_message = message
        else:
            state.error_kind = None
            state.error_message = None
        state.finished = True
        self._broadcast(state, None)

    @staticmethod
    def _broadcast(state: RunState, payload: str | None) -> None:
        for queue in list(state.subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                with suppress(asyncio.QueueEmpty):
                    while True:
                        queue.get_nowait()
                queue.put_nowait(_SUBSCRIBER_OVERFLOW)

    # ------------------------------------------------------------------
    async def cancel(self, identity_id: str, run_id: str) -> dict[str, Any]:
        run = self.conversations.owned_run(identity_id, run_id)
        state = self._runs.get(run_id)
        if state is not None and not state.finished:
            state.cancel_requested = True
            task = state.task
            if task is not None and not task.done():
                task.cancel()
                await asyncio.wait({task}, timeout=2.0)
            if not state.finished:
                self._finish(state, "canceled")
        elif run["status"] in {"queued", "running"}:
            # 进程重启后遗留的运行记录：直接收敛，不让它永远挂着。
            self.conversations.finalize_run(run_id, "canceled")
        return self.conversations.owned_run(identity_id, run_id)

    # ------------------------------------------------------------------
    async def stream(self, identity_id: str, run_id: str) -> AsyncIterator[str]:
        run = self.conversations.owned_run(identity_id, run_id)
        state = self._runs.get(run_id)
        if state is None or state.identity_id != identity_id:
            async for frame in self._replay_from_database(run):
                yield frame
            return

        queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        # add 与快照之间没有 await，因此不会漏掉正在广播的增量。
        state.subscribers.add(queue)
        replay = state.text
        finished = state.finished
        try:
            yield sse_event(
                "start",
                {
                    "run_id": state.run_id,
                    "conversation_id": state.conversation_id,
                    "message_id": state.response_message_id,
                    "status": state.status,
                    "content": replay,
                    "reasoning_content": state.reasoning_text,
                },
            )
            if not finished:
                while True:
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    if payload is None:
                        break
                    if payload is _SUBSCRIBER_OVERFLOW:
                        yield sse_event(
                            "error",
                            {
                                "run_id": state.run_id,
                                "message_id": state.response_message_id,
                                "status": state.status,
                                "kind": "subscriber_lag",
                                "message": "流式连接处理过慢，请重新连接以继续接收",
                                "content": state.text,
                                "reasoning_content": state.reasoning_text,
                            },
                        )
                        return
                    yield payload
            yield self._final_frame(state)
        finally:
            # 浏览器断开只是退订，不影响后台生成继续跑完。
            state.subscribers.discard(queue)

    def _final_frame(self, state: RunState) -> str:
        if state.status == "failed":
            return sse_event(
                "error",
                {
                    "run_id": state.run_id,
                    "message_id": state.response_message_id,
                    "status": "failed",
                    "kind": state.error_kind,
                    "message": state.error_message or "AI 运行失败",
                    "content": state.text,
                    "reasoning_content": state.reasoning_text,
                },
            )
        return sse_event(
            "done",
            {
                "run_id": state.run_id,
                "message_id": state.response_message_id,
                "status": state.status,
                "content": state.text,
                "reasoning_content": state.reasoning_text,
            },
        )

    async def _replay_from_database(self, run: dict[str, Any]) -> AsyncIterator[str]:
        content = ""
        reasoning_content = ""
        if run["response_message_id"]:
            row = self.conversations.database.fetchone(
                "SELECT content, reasoning_content FROM message WHERE id = ?",
                (run["response_message_id"],),
            )
            if row:
                content = row["content"]
                reasoning_content = row["reasoning_content"]
        status = run["status"]
        yield sse_event(
            "start",
            {
                "run_id": run["id"],
                "conversation_id": run["conversation_id"],
                "message_id": run["response_message_id"],
                "status": status,
                "content": content,
                "reasoning_content": reasoning_content,
            },
        )
        if status in {"queued", "running"}:
            # 内存里没有这次运行，说明服务重启过；收敛为失败而不是一直挂着。
            self.conversations.finalize_run(
                run["id"],
                "failed",
                content=content,
                reasoning_content=reasoning_content,
                error_kind="interrupted",
                error_message="服务已重启，本次生成被中断",
            )
            yield sse_event(
                "error",
                {
                    "run_id": run["id"],
                    "message_id": run["response_message_id"],
                    "status": "failed",
                    "kind": "interrupted",
                    "message": "服务已重启，本次生成被中断",
                    "content": content,
                    "reasoning_content": reasoning_content,
                },
            )
            return
        if status == "failed":
            yield sse_event(
                "error",
                {
                    "run_id": run["id"],
                    "message_id": run["response_message_id"],
                    "status": "failed",
                    "kind": run["error_kind"],
                    "message": run["error_message"] or "AI 运行失败",
                    "content": content,
                    "reasoning_content": reasoning_content,
                },
            )
            return
        yield sse_event(
            "done",
            {
                "run_id": run["id"],
                "message_id": run["response_message_id"],
                "status": status,
                "content": content,
                "reasoning_content": reasoning_content,
            },
        )

    # ------------------------------------------------------------------
    async def shutdown(self) -> None:
        tasks = [state.task for state in self._runs.values() if state.task and not state.task.done()]
        tasks.extend(task for task in self._title_tasks if not task.done())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(set(tasks), timeout=2.0)
