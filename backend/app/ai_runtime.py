from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass, field, replace
from typing import Any, AsyncIterator

import httpx

from .conversations import ConversationError, ConversationService
from .providers import ProviderChunk, ProviderConfig, ProviderError, build_provider
from .learning_domain import DomainError
from .search_runtime import external_stream, apply_native_event
from .generation_trace import GenerationRecorder, interrupt_trace
from .outbound import OutboundApprovals, RunOutbound, ProviderLease
from .provider_network import ProviderDiagnostics
from .material_images import attach_material_images, check_image_sources

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
    search_trace: dict = field(default_factory=lambda: {"mode": "off", "status": "off", "items": []})

    generation_trace: dict | None = None
    recorder: GenerationRecorder | None = None
    teaching_stream: Any = None

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
        self.outbound = getattr(conversations, "outbound", None) or OutboundApprovals()

    # ------------------------------------------------------------------
    async def start(
        self,
        identity_id: str,
        conversation_id: str,
        *,
        content: str,
        client_message_id: str,
        regenerate_message_id: str | None = None,
        parent_message_id: str | None = None,
        edit_message_id: str | None = None,
        search: dict | None = None,
        public_search_query: str | None = None,
        help_request: str | None = None,
        source_scope: dict | None = None,
        attachment_version_ids: list[str] | None = None,
        current_state_revision: int | None = None,
    ) -> dict[str, Any]:
        prepared = self.conversations.prepare_run(
            identity_id,
            conversation_id,
            content=content,
            client_message_id=client_message_id,
            search=search,
            public_search_query=public_search_query,
            help_request=help_request,
            **({"source_scope": source_scope} if source_scope is not None else {}),
            attachment_version_ids=attachment_version_ids,
            current_state_revision=current_state_revision,
            **({"regenerate_message_id": regenerate_message_id,
                "parent_message_id": parent_message_id,
                "edit_message_id": edit_message_id}
               if regenerate_message_id or parent_message_id or edit_message_id else {}),
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
            search_trace=json.loads(run.get("config_snapshot_json") or "{}").get("search_trace", {"mode": "off", "status": "off", "items": []}),
        )
        self._runs[state.run_id] = state
        self._evict()
        try:
            messages = self.conversations.build_prompt(
                prepared["history"], prepared["context"],
                search_enabled=bool(prepared.get("search_run") and prepared["search_run"].selection["mode"] != "off"),
            )
            if prepared.get("material_prompt"):
                messages[0]["content"] += "\n" + prepared["material_prompt"]
            from .help_records import HELP_PROMPTS
            help_kind = json.loads(run.get("config_snapshot_json") or "{}").get("help_request", {}).get("kind")
            if help_kind in HELP_PROMPTS:
                messages[0] = {**messages[0], "content": messages[0]["content"] + "\n" + HELP_PROMPTS[help_kind]}
            teaching = json.loads(run.get('config_snapshot_json') or '{}').get('teaching')
            if teaching:
                from .teaching_runtime import add_prompt, TeachingStream
                messages = add_prompt(messages, teaching, prepared.get('teaching_attempt_texts'))
                state.teaching_stream = TeachingStream(teaching)
            state.task = asyncio.create_task(
                self._execute(state, messages, prepared["provider_config"], prepared.get("search_run"), public_search_query,
                              prepared.get('frozen_scope'))
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
        search_run=None,
        public_search_query=None,
        frozen_scope=None,
    ) -> None:
        stream: AsyncIterator[ProviderChunk] | None = None
        diagnostic = ProviderDiagnostics(getattr(self.conversations, 'diagnostics', None),
            state.identity_id, state.run_id, 'conversation', config.provider_kind)
        failure = None
        try:
            search_enabled = search_run is not None and search_run.selection["mode"] == "native"
            provider = build_provider(replace(config, web_search=search_enabled), transport=self.transport)
            provider.diagnostics = diagnostic
            async with ProviderLease(self._provider_slots) as lease:
                if not self.conversations.mark_run_running(state.run_id):
                    run = self.conversations.owned_run(state.identity_id, state.run_id)
                    state.status = run["status"]
                    state.finished = run["status"] in {"succeeded", "failed", "canceled"}
                    self._broadcast(state, None)
                    return
                state.status = "running"
                state.recorder = GenerationRecorder(lambda trace: self._publish_generation(state, trace))
                async with asyncio.timeout(float(config.timeout_seconds)) as deadline:
                    def active():
                        if state.finished or state.cancel_requested:
                            return False
                        row = self.conversations.database.fetchone(
                            "SELECT r.status,c.deleted_at FROM ai_run r JOIN conversation c ON c.id=r.conversation_id WHERE r.id=?",
                            (state.run_id,))
                        return bool(row and row['status'] == 'running' and row['deleted_at'] is None)
                    outbound = RunOutbound(self.outbound, owner=state.identity_id, kind='conversation',
                        scope_id=state.conversation_id, run_id=state.run_id, active=active,
                        public_query=public_search_query, timeout=deadline, lease=lease)
                    knowledge = None
                    if frozen_scope and frozen_scope.get('knowledge_base'):
                        from .knowledge import KnowledgeRun
                        knowledge = KnowledgeRun(self.conversations.materials, {'id': state.identity_id},
                            'conversation', state.conversation_id, frozen_scope, active=active,
                            register=lambda version, reference: self.conversations.register_knowledge_reference(
                                state.run_id, version, reference))
                    def check_request():
                        if not active():
                            raise asyncio.CancelledError()
                        check_image_sources(self.conversations.materials, {'id': state.identity_id},
                            'conversation', state.conversation_id, frozen_scope)
                        if knowledge:
                            knowledge.check()
                    diagnostic.check = check_request
                    messages = await asyncio.to_thread(attach_material_images, self.conversations.materials,
                        {'id': state.identity_id}, 'conversation', state.conversation_id, frozen_scope, messages, check_request)
                    check_request()
                    if knowledge or (search_run is not None and search_run.selection["mode"] == "external"):
                        stream = external_stream(self.conversations.search_service, search_run, messages, provider,
                            lambda trace: self._publish_search(state, trace), outbound=outbound, knowledge=knowledge,
                            strict_only=bool(frozen_scope and frozen_scope['mode'] == 'only' and knowledge))
                    else:
                        stream = provider.stream_chat(messages)
                    chunks = state.teaching_stream.filter(stream) if state.teaching_stream else stream
                    async for chunk in chunks:
                        if state.cancel_requested:
                            break
                        if chunk.kind == 'completion':
                            continue
                        if chunk.kind in {"search_status", "search_sources"}:
                            apply_native_event(state.search_trace, chunk)
                            self._publish_search(state, state.search_trace)
                            state.recorder.native_event(state.search_trace, chunk.kind)
                            continue
                        if chunk.kind == "model_turn":
                            self.conversations.save_model_turn(state.run_id, json.loads(chunk.text))
                            continue
                        if chunk.kind in {"tool_start", "tool_end", "turn_end"}:
                            state.recorder.observe(chunk)
                            continue
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
                            state.recorder.observe(ProviderChunk(chunk.kind, accepted))
                            self._broadcast(
                                state,
                                sse_event(
                                    "delta",
                                    {"kind": chunk.kind, "text": accepted},
                                ),
                            )
                        if len(accepted) != len(chunk.text):
                            raise ProviderError("AI 回复超过长度限制", kind="output_limit")
            if not state.cancel_requested and not state.text.strip():
                raise ProviderError('提供方没有返回回答正文', kind='empty_response')
            self._finish(state, "canceled" if state.cancel_requested else "succeeded")
            if state.status == "succeeded":
                self._schedule_automatic_title(state, config)
        except asyncio.CancelledError as error:
            failure = error
            self._finish(state, "canceled")
            raise
        except TimeoutError as error:
            failure = error
            self._finish(state, "failed", kind="timeout", message="提供方响应超时")
        except ProviderError as error:
            failure = error
            self._finish(state, "failed", kind=error.kind, message=str(error))
        except DomainError as error:
            failure = error
            self._finish(state, 'failed', kind=error.code,
                         message='本轮知识库选择已失效，请读取最新状态并重新选择后重试。')
        except Exception as error:  # noqa: BLE001 - 兜底，错误详情不外泄
            failure = error
            logger.exception("AI 运行失败：%s", state.run_id)
            self._finish(state, "failed", kind="internal_error", message="AI 运行内部错误")
        finally:
            if stream is not None:
                with suppress(Exception, asyncio.CancelledError):
                    await stream.aclose()
            if state.status in {'succeeded', 'failed', 'canceled'}:
                diagnostic.finish(state.status, failure, state.error_kind)

    def _publish_generation(self, state, trace):
        if state.finished or (state.cancel_requested and trace['status'] == 'running'):
            raise asyncio.CancelledError()
        save = getattr(self.conversations, 'save_generation_trace', None)
        if save and not save(state.run_id, trace):
            raise asyncio.CancelledError()
        state.generation_trace = trace
        self._broadcast(state, sse_event('process', {'run_id': state.run_id, 'message_id': state.response_message_id, 'trace': trace}))

    def _publish_search(self, state, trace):
        if state.cancel_requested or state.finished:
            raise asyncio.CancelledError()
        state.search_trace = trace
        if not self.conversations.save_search_trace(state.run_id, trace):
            raise asyncio.CancelledError()
        self._broadcast(state, sse_event("search", {"run_id": state.run_id, "message_id": state.response_message_id, "trace": trace}))

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
        diagnostic = None
        failure = None
        try:
            if not self.conversations.mark_title_run_running(title_run_id):
                return
            row = self.conversations.database.fetchone('SELECT identity_id FROM conversation_title_run WHERE id=?', (title_run_id,))
            diagnostic = ProviderDiagnostics(getattr(self.conversations, 'diagnostics', None),
                row['identity_id'], title_run_id, 'conversation', config.provider_kind, phase='title')
            def check_title():
                active = self.conversations.database.fetchone('''SELECT 1 FROM conversation_title_run r
                    JOIN conversation c ON c.id=r.conversation_id
                    WHERE r.id=? AND r.status='running' AND c.deleted_at IS NULL''', (title_run_id,))
                if not active:
                    raise asyncio.CancelledError()
            diagnostic.check = check_title
            title_config = ProviderConfig(
                base_url=config.base_url,
                model=config.model,
                api_key=config.api_key,
                timeout_seconds=max(5, min(int(config.timeout_seconds), 30)),
                provider_kind=config.provider_kind,
            )
            provider = build_provider(title_config, transport=self.transport)
            provider.diagnostics = diagnostic
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
        except asyncio.CancelledError as error:
            failure = error
            self.conversations.finalize_title_run(
                title_run_id,
                "failed",
                error_kind="interrupted",
                error_message="服务正在关闭，标题生成被中断",
            )
            raise
        except TimeoutError as error:
            failure = error
            self.conversations.finalize_title_run(
                title_run_id,
                "failed",
                error_kind="timeout",
                error_message="标题生成超时",
            )
        except ProviderError as error:
            failure = error
            self.conversations.finalize_title_run(
                title_run_id,
                "failed",
                error_kind=error.kind,
                error_message=str(error),
            )
        except ConversationError as error:
            failure = error
            self.conversations.finalize_title_run(
                title_run_id,
                "failed",
                error_kind="invalid_title",
                error_message=str(error),
            )
        except Exception as error:  # noqa: BLE001 - 独立后台任务不得影响正常对话
            failure = error
            logger.exception("标题运行失败：%s", title_run_id)
            self.conversations.finalize_title_run(
                title_run_id,
                "failed",
                error_kind="internal_error",
                error_message="标题生成内部错误",
            )
        finally:
            if diagnostic:
                row = self.conversations.database.fetchone('SELECT status,error_kind FROM conversation_title_run WHERE id=?', (title_run_id,))
                result = ('canceled' if isinstance(failure, asyncio.CancelledError) or not row or row['status'] == 'superseded' else row['status'])
                if result in {'succeeded', 'failed', 'canceled'}:
                    diagnostic.finish(result, failure, row['error_kind'] if row else None)

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
            if state.recorder:
                state.recorder.finish(status)
            if state.search_trace.get("status") in {"queued", "running"} and status in {"failed", "canceled"}:
                state.search_trace.update(status="failed", message="搜索已取消" if status == "canceled" else (message or "本轮搜索未完成"))
                self.conversations.save_search_trace(state.run_id, state.search_trace)
            persisted_status = self.conversations.finalize_run(
                state.run_id,
                status,
                content=state.text,
                reasoning_content=state.reasoning_text,
                error_kind=kind,
                error_message=message,
                **({'teaching_proposal': state.teaching_stream.proposal()}
                   if state.teaching_stream and status == 'succeeded' else {}),
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
            snapshot = json.loads(run.get("config_snapshot_json") or "{}")
            process = interrupt_trace(snapshot.get("generation_trace"), "canceled")
            content = reasoning = ""
            if process:
                self.conversations.save_generation_trace(run_id, process)
                content = "".join(part.get("text", "") for part in process["parts"] if part["type"] == "text")
                reasoning = "\n\n".join(part.get("text", "") for part in process["parts"] if part["type"] == "reasoning")
            search = snapshot.get("search_trace")
            if search and search.get("status") in {"queued", "running"}:
                search.update(status="failed", message="搜索已取消")
                self.conversations.save_search_trace(run_id, search)
            self.conversations.finalize_run(run_id, "canceled", content=content, reasoning_content=reasoning)
        return self.conversations.owned_run(identity_id, run_id)

    # ------------------------------------------------------------------
    def forget_material_runs(self, run_ids):
        for run_id in run_ids:
            state = self._runs.get(run_id)
            if state is None:
                continue
            state.cancel_requested = True
            state.finished = True
            state.status = 'canceled'
            state.chunks.clear()
            state.reasoning_chunks.clear()
            state.response_chars = 0
            state.search_trace = {'mode': 'off', 'status': 'off', 'items': []}
            state.generation_trace = None
            state.recorder = None
            state.teaching_stream = None
            state.error_kind = state.error_message = None
            if state.task and not state.task.done():
                state.task.cancel()
            for queue in state.subscribers:
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(sse_event('start', {
                    'run_id': run_id, 'conversation_id': state.conversation_id,
                    'message_id': state.response_message_id, 'status': 'canceled',
                    'content': '', 'reasoning_content': '', 'search_trace': state.search_trace,
                    'generation_trace': None,
                }))
            self._broadcast(state, None)

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
                    "search_trace": state.search_trace,
                    "generation_trace": state.generation_trace,
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
                                "search_trace": state.search_trace,
                                "generation_trace": state.generation_trace,
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
                    "search_trace": state.search_trace,
                    "generation_trace": state.generation_trace,
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
                "search_trace": state.search_trace,
                "generation_trace": state.generation_trace,
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
        snapshot = json.loads(run.get("config_snapshot_json") or "{}")
        search_trace = snapshot.get("search_trace")
        generation_trace = snapshot.get("generation_trace")
        if status in {"queued", "running"} and generation_trace:
            generation_trace = interrupt_trace(generation_trace)
            self.conversations.save_generation_trace(run["id"], generation_trace)
            content = "".join(part.get("text", "") for part in generation_trace["parts"] if part["type"] == "text")
            reasoning_content = "\n\n".join(part.get("text", "") for part in generation_trace["parts"] if part["type"] == "reasoning")
        if status in {"queued", "running"} and search_trace and search_trace.get("status") in {"queued", "running"}:
            search_trace.update(status="failed", message="服务已重启，本轮搜索被中断")
            self.conversations.save_search_trace(run["id"], search_trace)
        yield sse_event(
            "start",
            {
                "run_id": run["id"],
                "conversation_id": run["conversation_id"],
                "message_id": run["response_message_id"],
                "status": status,
                "content": content,
                "reasoning_content": reasoning_content,
                "search_trace": search_trace,
                "generation_trace": generation_trace,
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
                    "search_trace": search_trace,
                    "generation_trace": generation_trace,
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
                    "search_trace": search_trace,
                    "generation_trace": generation_trace,
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
                "search_trace": search_trace,
                "generation_trace": generation_trace,
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
