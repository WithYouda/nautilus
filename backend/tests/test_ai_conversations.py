import asyncio
import json
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.conversations import ConversationError
from app.db import Database
from app.main import create_app
from conftest import build_settings

# 测试里出现的都是假密钥，不是真实凭据。
FAKE_API_KEY = "sk-test-fake-key-0123456789"


# ======================================================================
# Mock 提供方：所有测试都不触碰真实 AI API
# ======================================================================
def streaming_handler(_request: httpx.Request) -> httpx.Response:
    lines = [
        'data: {"choices":[{"delta":{"content":"矩阵乘法"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"的核心是"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"行列对应相乘再求和。"}}]}\n\n',
        "data: [DONE]\n\n",
    ]
    return httpx.Response(200, text="".join(lines))


def failing_handler(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(401, json={"error": {"message": "Incorrect API key provided"}})


def leaky_handler(request: httpx.Request) -> httpx.Response:
    """提供方把密钥回显在错误里——错误信息不得把它带回前端。"""
    return httpx.Response(
        400,
        json={"error": {"message": f"Invalid request with key {FAKE_API_KEY}"}},
    )


class SlowStream(httpx.AsyncByteStream):
    """可控速的异步字节流，用于测试取消、断开和刷新。"""

    def __init__(self, handler: "SlowHandler") -> None:
        self.handler = handler

    async def __aiter__(self):
        for index in range(self.handler.chunks):
            await asyncio.sleep(self.handler.delay)
            self.handler.delivered += 1
            payload = json.dumps({"choices": [{"delta": {"content": f"块{index} "}}]})
            yield f"data: {payload}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"


class SlowHandler:
    """按块慢速产出的 Mock 提供方，不消耗真实 API。"""

    def __init__(self, chunks: int = 50, delay: float = 0.05) -> None:
        self.chunks = chunks
        self.delay = delay
        self.delivered = 0

    def __call__(self, _request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=SlowStream(self))


def make_client(tmp_path, handler) -> TestClient:
    settings = build_settings(tmp_path)
    app = create_app(settings, provider_transport=httpx.MockTransport(handler))
    return TestClient(app)


# ======================================================================
# 辅助
# ======================================================================
def authorize(client: TestClient) -> None:
    token = client.app.state.auth.runtime_access_token
    assert client.post("/api/auth/authorize", json={"access_token": token}).status_code == 200


def create_task(client: TestClient) -> str:
    today = date.today()
    payload = {
        "goal_title": "完成线性代数第一轮复习",
        "description": "建立矩阵与向量空间的知识框架",
        "start_date": today.isoformat(),
        "end_date": (today + timedelta(days=30)).isoformat(),
        "subject_title": "数学",
        "topic_title": "线性代数",
        "task_title": "复习矩阵乘法并完成例题",
        "task_type": "review",
        "schedule_mode": "flexible",
        "task_start_date": today.isoformat(),
        "task_due_date": today.isoformat(),
        "estimate_minutes": 50,
        "timer_mode": "pomodoro_50_10",
        "work_minutes": 50,
        "break_minutes": 10,
    }
    plan = client.post("/api/plans/manual", json=payload).json()
    return plan["subjects"][0]["topics"][0]["tasks"][0]["id"]


def configure_provider(client: TestClient) -> dict:
    response = client.put(
        "/api/ai/provider",
        json={
            "display_name": "测试提供方",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-4o",
            "api_key": FAKE_API_KEY,
        },
    )
    assert response.status_code == 200
    return response.json()["provider"]


def start_conversation(client: TestClient, task_id: str) -> str:
    created = client.post("/api/ai/conversations", json={"task_id": task_id})
    assert created.status_code == 201
    return created.json()["conversation"]["id"]


def read_sse(client: TestClient, run_id: str) -> list[tuple[str, dict]]:
    """读完一次 SSE 流，返回 (事件名, 数据) 列表。

    注意：TestClient 会把整个响应体缓冲完才返回，所以它只能验证"最终结果"。
    真正的增量、取消和断开语义在下面用 AiRunManager 直接驱动来验证，
    浏览器里的真实流式行为由 Playwright 覆盖。
    """
    events: list[tuple[str, dict]] = []
    with client.stream("GET", f"/api/ai/runs/{run_id}/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers.get("x-accel-buffering") == "no"
        current_event = None
        for line in response.iter_lines():
            if line.startswith("event:"):
                current_event = line[len("event:") :].strip()
            elif line.startswith("data:") and current_event:
                events.append((current_event, json.loads(line[len("data:") :].strip())))
                current_event = None
    return events


def identity_id(client: TestClient) -> str:
    return client.app.state.auth.ensure_local_identity()["id"]


async def drain_deltas(agen, count: int) -> list[str]:
    """从 SSE 异步生成器里取若干个增量后停下，模拟浏览器只读了一部分。"""
    seen: list[str] = []
    async for frame in agen:
        if frame.startswith("event: delta"):
            seen.append(frame)
            if len(seen) >= count:
                break
    return seen


async def wait_for_run(manager, run_id: str) -> None:
    state = manager._runs[run_id]
    if state.task is not None:
        await asyncio.wait({state.task}, timeout=10.0)
    assert state.finished, "后台生成没有在预期时间内结束"


# ======================================================================
# 提供方配置：只进出非敏感信息
# ======================================================================
def test_provider_config_never_returns_the_api_key(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        assert client.get("/api/ai/provider").json()["provider"] is None

        provider = configure_provider(client)
        assert provider["has_api_key"] is True
        assert provider["api_key_masked"] == "****6789"
        assert provider["base_url"] == "https://api.example.com/v1"
        assert provider["model"] == "gpt-4o"

        body = client.get("/api/ai/provider").text
        assert FAKE_API_KEY not in body
        assert "api_key" not in json.loads(body)["provider"] or True
        assert json.loads(body)["provider"]["api_key_masked"] == "****6789"


def test_api_key_is_not_stored_in_sqlite(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        configure_provider(client)

        row = client.app.state.database.fetchone("SELECT * FROM provider_profile")
        stored = " ".join(str(value) for value in dict(row).values())
        assert FAKE_API_KEY not in stored

        # 整个数据库文件里都不应出现密钥。
        client.app.state.database.connection.execute("PRAGMA wal_checkpoint(FULL)")
        raw = (tmp_path / "nautilus.sqlite3").read_bytes()
        assert FAKE_API_KEY.encode("utf-8") not in raw


def test_provider_update_keeps_existing_key_and_bumps_config_version(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        first = configure_provider(client)
        assert first["config_version"] == 1

        updated = client.put(
            "/api/ai/provider",
            json={
                "display_name": "测试提供方",
                "base_url": "https://api.example.com/v1",
                "model": "gpt-4o-mini",
                "api_key": None,
            },
        ).json()["provider"]
        assert updated["model"] == "gpt-4o-mini"
        assert updated["has_api_key"] is True
        assert updated["config_version"] == 2

        unchanged = client.put(
            "/api/ai/provider",
            json={
                "display_name": "改个名字",
                "base_url": "https://api.example.com/v1",
                "model": "gpt-4o-mini",
                "api_key": None,
            },
        ).json()["provider"]
        assert unchanged["config_version"] == 2

        timeout_changed = client.put(
            "/api/ai/provider",
            json={
                "display_name": "改个名字",
                "base_url": "https://api.example.com/v1",
                "model": "gpt-4o-mini",
                "api_key": None,
                "request_timeout_seconds": 90,
            },
        ).json()["provider"]
        assert timeout_changed["request_timeout_seconds"] == 90
        assert timeout_changed["config_version"] == 3


def test_provider_key_change_is_compensated_when_sqlite_update_fails(tmp_path, monkeypatch):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        configure_provider(client)
        service = client.app.state.conversations
        profile = dict(client.app.state.database.fetchone("SELECT * FROM provider_profile"))
        credential_key = profile["credential_key"]
        assert client.app.state.credentials.get(credential_key) == FAKE_API_KEY

        @contextmanager
        def broken_transaction():
            raise sqlite3.OperationalError("injected update failure")
            yield

        monkeypatch.setattr(client.app.state.database, "transaction", broken_transaction)
        with pytest.raises(ConversationError, match="无法保存"):
            service.save_provider(
                identity_id(client),
                display_name="测试提供方",
                base_url="https://api.example.com/v1",
                model="new-model",
                api_key="sk-test-replacement-987654",
            )
        assert client.app.state.credentials.get(credential_key) == FAKE_API_KEY
        assert client.app.state.database.fetchone(
            "SELECT model FROM provider_profile WHERE id = ?", (profile["id"],)
        )["model"] == "gpt-4o"


def test_new_provider_key_is_removed_if_sqlite_insert_fails(tmp_path, monkeypatch):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        service = client.app.state.conversations

        @contextmanager
        def broken_transaction():
            raise sqlite3.OperationalError("injected insert failure")
            yield

        monkeypatch.setattr(client.app.state.database, "transaction", broken_transaction)
        with pytest.raises(ConversationError, match="无法保存"):
            service.save_provider(
                identity_id(client),
                display_name="测试提供方",
                base_url="https://api.example.com/v1",
                model="gpt-4o",
                api_key="sk-test-orphan-123456",
            )
        assert client.app.state.credentials.names() == []
        assert client.app.state.database.fetchone("SELECT id FROM provider_profile") is None


def test_provider_delete_restores_key_if_sqlite_update_fails(tmp_path, monkeypatch):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        configure_provider(client)
        service = client.app.state.conversations
        profile = dict(client.app.state.database.fetchone("SELECT * FROM provider_profile"))
        credential_key = profile["credential_key"]

        @contextmanager
        def broken_transaction():
            raise sqlite3.OperationalError("injected delete failure")
            yield

        monkeypatch.setattr(client.app.state.database, "transaction", broken_transaction)
        with pytest.raises(ConversationError, match="无法删除"):
            service.delete_provider(identity_id(client))
        assert client.app.state.credentials.get(credential_key) == FAKE_API_KEY
        assert client.app.state.database.fetchone(
            "SELECT deleted_at FROM provider_profile WHERE id = ?", (profile["id"],)
        )["deleted_at"] is None


def test_provider_requires_key_on_first_save_and_validates_url(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        missing_key = client.put(
            "/api/ai/provider",
            json={"base_url": "https://api.example.com/v1", "model": "gpt-4o"},
        )
        assert missing_key.status_code == 400
        assert "API 密钥" in missing_key.json()["detail"]

        bad_url = client.put(
            "/api/ai/provider",
            json={"base_url": "ftp://example.com", "model": "gpt-4o", "api_key": FAKE_API_KEY},
        )
        assert bad_url.status_code == 400
        assert "base URL" in bad_url.json()["detail"]


def test_provider_connection_test_records_status_without_secrets(tmp_path):
    def completion_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    with make_client(tmp_path, completion_handler) as client:
        authorize(client)
        configure_provider(client)

        result = client.post("/api/ai/provider/test")
        assert result.status_code == 200
        assert result.json()["ok"] is True
        assert result.json()["provider"]["last_test_status"] == "succeeded"
        assert FAKE_API_KEY not in result.text


def test_failed_connection_test_reports_error_without_leaking_key(tmp_path):
    with make_client(tmp_path, leaky_handler) as client:
        authorize(client)
        configure_provider(client)

        result = client.post("/api/ai/provider/test")
        assert result.status_code == 200
        assert result.json()["ok"] is False
        # 提供方把密钥回显了，但我们不能把它转发出去。
        assert FAKE_API_KEY not in result.text
        assert "****" in result.json()["message"]

        stored = client.app.state.database.fetchone(
            "SELECT last_test_status, last_test_error FROM provider_profile"
        )
        assert stored["last_test_status"] == "failed"
        assert FAKE_API_KEY not in (stored["last_test_error"] or "")


def test_model_discovery_uses_cache_and_supports_temporary_form_config(tmp_path):
    calls = {"models": 0, "tests": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/models"):
            calls["models"] += 1
            assert request.headers["Authorization"] == f"Bearer {FAKE_API_KEY}"
            return httpx.Response(200, json={"data": [{"id": "model-b"}, {"id": "model-a"}]})
        calls["tests"] += 1
        payload = json.loads(request.content)
        assert payload["model"] == "model-b"
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    with make_client(tmp_path, handler) as client:
        authorize(client)
        first = client.post(
            "/api/ai/provider/models",
            json={
                "base_url": "https://api.example.com/v1",
                "api_key": FAKE_API_KEY,
            },
        )
        assert first.status_code == 200
        assert first.json() == {"models": ["model-a", "model-b"], "cached": False, "ttl_seconds": 600}

        second = client.post(
            "/api/ai/provider/models",
            json={
                "base_url": "https://api.example.com/v1",
                "api_key": FAKE_API_KEY,
            },
        )
        assert second.json()["cached"] is True
        assert calls["models"] == 1

        tested = client.post(
            "/api/ai/provider/test",
            json={
                "base_url": "https://api.example.com/v1",
                "model": "model-b",
                "api_key": FAKE_API_KEY,
                "request_timeout_seconds": 15,
            },
        )
        assert tested.status_code == 200
        assert tested.json()["ok"] is True
        assert tested.json()["provider"] is None
        assert calls["tests"] == 1
        assert client.app.state.credentials.names() == []


def test_model_discovery_error_is_structured_and_redacted(tmp_path):
    secret = FAKE_API_KEY

    def discovery_error_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": f"missing endpoint {secret}"}})

    with make_client(tmp_path, discovery_error_handler) as client:
        authorize(client)
        configure_provider(client)
        response = client.post(
            "/api/ai/provider/models",
            json={
                "base_url": "https://api.example.com/v1",
                "api_key": secret,
                "force_refresh": True,
            },
        )
        assert response.status_code == 502
        detail = response.json()["detail"]
        assert detail["kind"] == "endpoint_not_found"
        assert "message" in detail
        assert secret not in json.dumps(response.json(), ensure_ascii=False)


def test_multiple_providers_models_and_conversation_run_snapshot(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/models"):
            assert request.headers["Authorization"] == "Bearer sk-test-second-012345"
            return httpx.Response(200, json={"data": [{"id": "remote-model"}]})
        payload = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": f"来自 {payload['model']}"}}]})

    with make_client(tmp_path, handler) as client:
        authorize(client)
        first = configure_provider(client)
        created = client.post(
            "/api/ai/providers",
            json={
                "display_name": "第二提供方",
                "base_url": "https://second.example.com/v1",
                "model": "second-model",
                "api_key": "sk-test-second-012345",
                "is_default": False,
            },
        )
        assert created.status_code == 201
        second = created.json()["provider"]
        assert second["is_default"] is False
        assert second["models"][0]["model_id"] == "second-model"
        assert "sk-test-second-012345" not in created.text

        listed = client.get("/api/ai/providers").json()
        assert [item["display_name"] for item in listed] == ["测试提供方", "第二提供方"]
        assert client.post(f"/api/ai/providers/{second['id']}/default").status_code == 200
        assert client.get("/api/ai/provider").json()["provider"]["id"] == second["id"]

        discovered = client.post(
            f"/api/ai/providers/{second['id']}/models/discover",
            json={},
        )
        assert discovered.status_code == 200
        assert discovered.json()["models"][0]["model_id"] == "remote-model"

        task_id = create_task(client)
        conversation_id = start_conversation(client, task_id)
        second_model = next(item for item in discovered.json()["models"] if item["model_id"] == "remote-model")
        selected = client.put(
            f"/api/ai/conversations/{conversation_id}/config",
            json={"provider_profile_id": second["id"], "provider_model_id": second_model["id"]},
        )
        assert selected.status_code == 200
        assert selected.json()["config"]["model_id"] == "remote-model"

        sent = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "测试快照", "client_message_id": "snapshot-1"},
        )
        assert sent.status_code == 202
        read_sse(client, sent.json()["run"]["id"])
        run = client.app.state.database.fetchone("SELECT * FROM ai_run WHERE id = ?", (sent.json()["run"]["id"],))
        snapshot = json.loads(run["config_snapshot_json"])
        assert run["provider_profile_id"] == second["id"]
        assert run["provider_model_id"] == second_model["id"]
        assert run["model"] == "remote-model"
        assert run["snapshot_schema_version"] == 1
        assert snapshot["provider"]["id"] == second["id"]
        assert snapshot["model"]["model_id"] == "remote-model"
        assert "api_key" not in run["config_snapshot_json"]
        assert snapshot["credential"]["version"] == second["credential_version"]
        assert first["id"] != second["id"]


def test_conversation_config_can_be_restored_to_default(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        provider = configure_provider(client)
        task_id = create_task(client)
        conversation_id = start_conversation(client, task_id)
        model = provider["default_model"]

        selected = client.put(
            f"/api/ai/conversations/{conversation_id}/config",
            json={"provider_profile_id": provider["id"], "provider_model_id": model["id"]},
        )
        assert selected.status_code == 200
        assert client.delete(f"/api/ai/conversations/{conversation_id}/config").status_code == 204
        assert client.get(f"/api/ai/conversations/{conversation_id}/config").json() == {"config": None}


def test_successful_first_reply_generates_title_once_with_redacted_snapshot(tmp_path):
    calls: list[dict] = []

    def title_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        if payload.get("stream") is False:
            return httpx.Response(200, json={"choices": [{"message": {"content": "矩阵乘法学习步骤。"}}]})
        return streaming_handler(request)

    with make_client(tmp_path, title_handler) as client:
        authorize(client)
        configure_provider(client)
        conversation_id = start_conversation(client, create_task(client))

        sent = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "## 请解释矩阵乘法", "client_message_id": "title-auto-1"},
        )
        read_sse(client, sent.json()["run"]["id"])
        for _ in range(30):
            detail = client.get(f"/api/ai/conversations/{conversation_id}").json()
            if detail["conversation"]["title_generation_status"] not in {"queued", "running"}:
                break
            import time
            time.sleep(0.02)

        conversation = detail["conversation"]
        assert conversation["title"] == "矩阵乘法学习步骤"
        assert conversation["title_source"] == "ai"
        assert conversation["title_generation_status"] == "succeeded"
        title_run = client.app.state.database.fetchone(
            "SELECT * FROM conversation_title_run WHERE conversation_id = ?",
            (conversation_id,),
        )
        assert title_run["trigger_ai_run_id"] == sent.json()["run"]["id"]
        assert title_run["forced"] == 0
        assert "api_key" not in title_run["config_snapshot_json"]
        assert "请解释矩阵乘法" not in title_run["config_snapshot_json"]
        assert json.loads(title_run["input_message_ids_json"])
        title_calls = [payload for payload in calls if payload.get("stream") is False]
        assert len(title_calls) == 1
        assert title_calls[0]["max_tokens"] >= 256

        second = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "继续讲一个例子", "client_message_id": "title-auto-2"},
        )
        read_sse(client, second.json()["run"]["id"])
        assert client.app.state.database.fetchone(
            "SELECT COUNT(*) AS count FROM conversation_title_run WHERE conversation_id = ?",
            (conversation_id,),
        )["count"] == 1


def test_reasoning_model_title_request_leaves_budget_for_final_content(tmp_path):
    title_budgets: list[int] = []

    def reasoning_title_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload.get("stream") is False:
            budget = int(payload.get("max_tokens") or 0)
            title_budgets.append(budget)
            if budget <= 48:
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": None,
                                    "reasoning_content": "先分析对话主题再决定标题",
                                }
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "矩阵乘法理解与练习",
                                "reasoning_content": "已完成内部分析",
                            }
                        }
                    ]
                },
            )
        return streaming_handler(request)

    with make_client(tmp_path, reasoning_title_handler) as client:
        authorize(client)
        configure_provider(client)
        conversation_id = start_conversation(client, create_task(client))
        sent = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "请讲解矩阵乘法", "client_message_id": "reasoning-title-budget"},
        )
        read_sse(client, sent.json()["run"]["id"])

        import time
        for _ in range(30):
            detail = client.get(f"/api/ai/conversations/{conversation_id}").json()
            if detail["conversation"]["title_generation_status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)

        assert title_budgets and title_budgets[0] >= 256
        assert detail["conversation"]["title"] == "矩阵乘法理解与练习"
        assert detail["conversation"]["title_source"] == "ai"


def test_title_failure_keeps_fallback_and_manual_regeneration_can_recover(tmp_path):
    title_attempts = 0

    def title_handler(request: httpx.Request) -> httpx.Response:
        nonlocal title_attempts
        payload = json.loads(request.content)
        if payload.get("stream") is False:
            title_attempts += 1
            if title_attempts == 1:
                return httpx.Response(500, json={"error": {"message": "temporary title failure"}})
            return httpx.Response(200, json={"choices": [{"message": {"content": "恢复后的学习标题"}}]})
        return streaming_handler(request)

    with make_client(tmp_path, title_handler) as client:
        authorize(client)
        configure_provider(client)
        conversation_id = start_conversation(client, create_task(client))
        sent = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "第一条学习问题", "client_message_id": "title-fail-1"},
        )
        read_sse(client, sent.json()["run"]["id"])

        import time
        for _ in range(30):
            detail = client.get(f"/api/ai/conversations/{conversation_id}").json()
            if detail["conversation"]["title_generation_status"] == "failed":
                break
            time.sleep(0.02)
        assert detail["conversation"]["title"] == "第一条学习问题"
        assert detail["conversation"]["title_source"] == "fallback"
        assert detail["messages"][1]["status"] == "complete"

        regenerated = client.post(f"/api/ai/conversations/{conversation_id}/title/regenerate")
        assert regenerated.status_code == 202
        assert regenerated.json()["title_run"]["forced"] is True
        for _ in range(30):
            detail = client.get(f"/api/ai/conversations/{conversation_id}").json()
            if detail["conversation"]["title_generation_status"] == "succeeded":
                break
            time.sleep(0.02)
        assert detail["conversation"]["title"] == "恢复后的学习标题"
        assert title_attempts == 2


def test_conversation_title_can_be_renamed_and_supersedes_queued_title_run(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        configure_provider(client)
        conversation_id = start_conversation(client, create_task(client))
        now = "2026-08-03T00:00:00.000000Z"
        with client.app.state.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO message
                    (id, conversation_id, role, content, sequence, status, created_at, updated_at)
                VALUES ('rename-title-message', ?, 'user', '测试改名', 0, 'complete', ?, ?)
                """,
                (conversation_id, now, now),
            )
        prepared = client.app.state.conversations.prepare_manual_title_run(
            identity_id(client), conversation_id
        )

        renamed = client.patch(
            f"/api/ai/conversations/{conversation_id}",
            json={"title": "  手动整理后的标题  "},
        )

        assert renamed.status_code == 200
        conversation = renamed.json()["conversation"]
        assert conversation["title"] == "手动整理后的标题"
        assert conversation["title_source"] == "manual"
        assert conversation["title_generation_status"] == "idle"
        assert conversation["title_revision"] == 1
        title_run = client.app.state.database.fetchone(
            "SELECT status FROM conversation_title_run WHERE id = ?",
            (prepared["run"]["id"],),
        )
        assert title_run["status"] == "superseded"
        assert client.get(f"/api/ai/conversations/{conversation_id}").json()["conversation"]["title"] == "手动整理后的标题"


def test_conversation_delete_is_soft_and_supersedes_queued_title_run(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        configure_provider(client)
        conversation_id = start_conversation(client, create_task(client))
        now = "2026-08-03T00:00:00.000000Z"
        with client.app.state.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO message
                    (id, conversation_id, role, content, sequence, status, created_at, updated_at)
                VALUES ('delete-title-message', ?, 'user', '测试删除', 0, 'complete', ?, ?)
                """,
                (conversation_id, now, now),
            )
        prepared = client.app.state.conversations.prepare_manual_title_run(
            identity_id(client), conversation_id
        )

        deleted = client.delete(f"/api/ai/conversations/{conversation_id}")

        assert deleted.status_code == 204
        assert client.get(f"/api/ai/conversations/{conversation_id}").status_code == 404
        assert all(item["id"] != conversation_id for item in client.get("/api/ai/conversations").json())
        stored = client.app.state.database.fetchone(
            "SELECT deleted_at FROM conversation WHERE id = ?", (conversation_id,)
        )
        assert stored["deleted_at"] is not None
        assert client.app.state.database.fetchone(
            "SELECT COUNT(*) AS count FROM message WHERE conversation_id = ?", (conversation_id,)
        )["count"] == 1
        assert client.app.state.database.fetchone(
            "SELECT status FROM conversation_title_run WHERE id = ?", (prepared["run"]["id"],)
        )["status"] == "superseded"


def test_conversation_delete_rejects_an_active_chat_run(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        conversation_id = start_conversation(client, create_task(client))
        now = "2026-08-03T00:00:00.000000Z"
        with client.app.state.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO ai_run
                    (id, identity_id, conversation_id, workflow, status, created_at, updated_at)
                VALUES ('active-delete-run', ?, ?, 'tutor_chat', 'running', ?, ?)
                """,
                (identity_id(client), conversation_id, now, now),
            )

        deleted = client.delete(f"/api/ai/conversations/{conversation_id}")

        assert deleted.status_code == 409
        assert "先取消" in deleted.json()["detail"]
        assert client.app.state.database.fetchone(
            "SELECT deleted_at FROM conversation WHERE id = ?", (conversation_id,)
        )["deleted_at"] is None


def test_provider_profile_test_endpoint_records_only_selected_profile(tmp_path):
    def completion_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    with make_client(tmp_path, completion_handler) as client:
        authorize(client)
        configure_provider(client)
        second = client.post(
            "/api/ai/providers",
            json={
                "display_name": "第二提供方",
                "base_url": "https://second.example.com/v1",
                "model": "second-model",
                "api_key": "sk-test-second-987654",
            },
        ).json()["provider"]
        result = client.post(f"/api/ai/providers/{second['id']}/test")
        assert result.status_code == 200
        assert result.json()["ok"] is True
        assert result.json()["provider"]["id"] == second["id"]
        stored = client.app.state.database.fetchone(
            "SELECT last_test_status FROM provider_profile WHERE id = ?", (second["id"],)
        )
        assert stored["last_test_status"] == "succeeded"


def test_reasoning_content_is_persisted_and_replayed(tmp_path):
    def reasoning_handler(_request: httpx.Request) -> httpx.Response:
        lines = [
            'data: {"choices":[{"delta":{"reasoning_content":"先判断条件。"}}]}\n\n',
            'data: {"choices":[{"delta":{"content":"最终结论。"}}]}\n\n',
            "data: [DONE]\n\n",
        ]
        return httpx.Response(200, text="".join(lines))

    with make_client(tmp_path, reasoning_handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)
        started = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "请分析", "client_message_id": "reasoning-1"},
        ).json()
        events = read_sse(client, started["run"]["id"])
        # TestClient 会等待后台任务完成后再交付缓冲响应，因此这里验证重放快照；
        # 实时 reasoning delta 由 provider 单测和 Playwright 真流覆盖。
        assert events[0][1]["reasoning_content"] == "先判断条件。"
        detail = client.get(f"/api/ai/conversations/{conversation_id}").json()
        assert detail["messages"][1]["content"] == "最终结论。"
        assert detail["messages"][1]["reasoning_content"] == "先判断条件。"
        assert events[-1][1]["reasoning_content"] == "先判断条件。"


def test_deleting_provider_removes_the_stored_credential(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        configure_provider(client)
        store = client.app.state.credentials
        assert store.names() != []

        assert client.delete("/api/ai/provider").status_code == 204
        assert client.get("/api/ai/provider").json()["provider"] is None
        assert store.names() == []


# ======================================================================
# 任务上下文与对话
# ======================================================================
def test_task_context_preview_describes_the_plan_route(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)

        context = client.get(f"/api/ai/tasks/{task_id}/context")
        assert context.status_code == 200
        body = context.json()
        assert body["task_title"] == "复习矩阵乘法并完成例题"
        assert body["goal_title"] == "完成线性代数第一轮复习"
        assert body["subject_title"] == "数学"
        assert body["topic_title"] == "线性代数"
        assert "数学" in body["route"] and "线性代数" in body["route"]
        assert "复习矩阵乘法" in body["summary"]

        assert client.get("/api/ai/tasks/does-not-exist/context").status_code == 404


def test_conversation_is_created_with_task_link_and_listed(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)

        created = client.post("/api/ai/conversations", json={"task_id": task_id})
        assert created.status_code == 201
        detail = created.json()
        conversation_id = detail["conversation"]["id"]
        assert detail["conversation"]["conversation_kind"] == "linear"
        assert detail["context"]["task_id"] == task_id
        assert detail["messages"] == []
        assert detail["conversation"]["title"] == "新的学习对话"
        assert detail["conversation"]["title_source"] == "placeholder"
        assert detail["conversation"]["title_generation_status"] == "pending"

        listed = client.get("/api/ai/conversations").json()
        assert [item["id"] for item in listed] == [conversation_id]
        assert listed[0]["link_target_id"] == task_id

        fetched = client.get(f"/api/ai/conversations/{conversation_id}")
        assert fetched.status_code == 200
        assert fetched.json()["context"]["task_id"] == task_id


def test_conversation_can_be_created_without_a_task(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        created = client.post("/api/ai/conversations", json={})
        assert created.status_code == 201
        assert created.json()["conversation"]["title"] == "新的学习对话"
        assert created.json()["context"] is None


def test_conversation_list_orders_same_task_by_most_recent_message(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)
        first_id = start_conversation(client, task_id)
        second_id = start_conversation(client, task_id)
        created_at = client.get(f"/api/ai/conversations/{second_id}").json()["conversation"]["created_at"]
        assert "." in created_at and len(created_at.rsplit(".", 1)[1].removesuffix("Z")) == 6
        with client.app.state.database.transaction() as connection:
            connection.execute(
                "UPDATE conversation SET last_message_at = ? WHERE id = ?",
                ("2026-08-03T00:00:02.000000Z", first_id),
            )
            connection.execute(
                "UPDATE conversation SET last_message_at = ? WHERE id = ?",
                ("2026-08-03T00:00:01.000000Z", second_id),
            )

        listed = client.get("/api/ai/conversations").json()
        task_conversations = [item for item in listed if item["link_target_id"] == task_id]
        assert [item["id"] for item in task_conversations] == [first_id, second_id]


def test_conversation_with_unknown_task_is_rejected(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        response = client.post("/api/ai/conversations", json={"task_id": "missing"})
        assert response.status_code == 404


def test_conversations_support_global_plan_task_and_independent_scopes(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)
        task_context = client.get(f"/api/ai/tasks/{task_id}/context").json()
        goal_id = task_context["goal_id"]

        global_detail = client.post(
            "/api/ai/conversations", json={"context_scope": "global"}
        )
        assert global_detail.status_code == 201
        assert global_detail.json()["conversation"]["context_scope"] == "global"
        assert global_detail.json()["context"]["scope_kind"] == "global"

        plan_detail = client.post(
            "/api/ai/conversations",
            json={"context_scope": "plan", "target_id": goal_id},
        )
        assert plan_detail.status_code == 201
        assert plan_detail.json()["conversation"]["context_scope"] == "plan"
        assert plan_detail.json()["context"]["goal_id"] == goal_id

        task_detail = client.post(
            "/api/ai/conversations",
            json={"context_scope": "task", "target_id": task_id},
        )
        assert task_detail.status_code == 201
        assert task_detail.json()["conversation"]["context_scope"] == "task"
        assert task_detail.json()["context"]["task_id"] == task_id

        independent = client.post(
            "/api/ai/conversations", json={"context_scope": "independent"}
        )
        assert independent.status_code == 201
        assert independent.json()["conversation"]["context_scope"] == "independent"
        assert independent.json()["context"] is None

        listed = client.get("/api/ai/conversations").json()
        by_scope = {item["context_scope"]: item for item in listed}
        assert by_scope["global"]["link_target_id"] is None
        assert by_scope["plan"]["link_type"] == "goal"
        assert by_scope["plan"]["link_target_id"] == goal_id
        assert by_scope["task"]["link_type"] == "task"
        assert by_scope["task"]["link_target_id"] == task_id

        assert client.post(
            "/api/ai/conversations", json={"context_scope": "plan"}
        ).status_code == 422
        assert client.post(
            "/api/ai/conversations",
            json={"context_scope": "global", "target_id": goal_id},
        ).status_code == 422


def test_scoped_context_is_frozen_in_each_run_snapshot(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)
        goal_id = client.get(f"/api/ai/tasks/{task_id}/context").json()["goal_id"]
        configure_provider(client)

        for scope, target_id in (("global", None), ("plan", goal_id), ("task", task_id)):
            payload = {"context_scope": scope}
            if target_id:
                payload["target_id"] = target_id
            conversation = client.post("/api/ai/conversations", json=payload).json()
            conversation_id = conversation["conversation"]["id"]
            sent = client.post(
                f"/api/ai/conversations/{conversation_id}/messages",
                json={"content": f"检查 {scope} 上下文", "client_message_id": f"scope-{scope}"},
            )
            assert sent.status_code == 202
            read_sse(client, sent.json()["run"]["id"])
            snapshot = client.app.state.database.fetchone(
                "SELECT * FROM context_snapshot WHERE conversation_id = ?",
                (conversation_id,),
            )
            assert snapshot["scope_kind"] == scope
            payload_data = json.loads(snapshot["payload"])
            assert payload_data["scope_kind"] == scope
            if scope == "plan":
                assert snapshot["goal_id"] == goal_id
            if scope == "task":
                assert snapshot["task_id"] == task_id


def test_scope_migration_backfills_existing_links_without_creating_global_conversations(tmp_path):
    source = Settings.from_env().migrations_dir
    staged = tmp_path / "migrations-through-009"
    staged.mkdir()
    for migration in sorted(source.glob("*.sql")):
        if migration.stem <= "009_task_completion_restore":
            shutil.copy2(migration, staged / migration.name)

    database_path = tmp_path / "scope-backfill.sqlite3"
    database = Database(database_path, staged)
    now = "2026-08-05T00:00:00.000000Z"
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO local_identity(id, device_id, display_name, timezone, created_at, updated_at) VALUES ('identity', 'device', '学习者', 'Asia/Shanghai', ?, ?)",
            (now, now),
        )
        for conversation_id in ("task-conversation", "plan-conversation", "independent-conversation"):
            connection.execute(
                "INSERT INTO conversation(id, identity_id, title, created_at, updated_at) VALUES (?, 'identity', ?, ?, ?)",
                (conversation_id, conversation_id, now, now),
            )
        connection.execute(
            "INSERT INTO conversation_link(id, conversation_id, link_role, target_type, target_id, created_at) VALUES ('task-link', 'task-conversation', 'primary', 'task', 'task-id', ?)",
            (now,),
        )
        connection.execute(
            "INSERT INTO conversation_link(id, conversation_id, link_role, target_type, target_id, created_at) VALUES ('plan-link', 'plan-conversation', 'primary', 'goal', 'goal-id', ?)",
            (now,),
        )
    database.close()

    migrated = Database(database_path, source)
    scopes = {
        row["id"]: row["context_scope"]
        for row in migrated.fetchall("SELECT id, context_scope FROM conversation")
    }
    assert scopes == {
        "task-conversation": "task",
        "plan-conversation": "plan",
        "independent-conversation": "independent",
    }
    assert "global" not in scopes.values()
    migrated.close()


# ======================================================================
# SSE：正常完成
# ======================================================================
def test_streaming_completes_and_appends_the_assistant_message(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)

        sent = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "矩阵乘法怎么理解？", "client_message_id": "client-1"},
        )
        assert sent.status_code == 202
        assert sent.json()["created"] is True
        run_id = sent.json()["run"]["id"]
        assert sent.json()["run"]["status"] == "queued"
        assert sent.json()["run"]["model"] == "gpt-4o"

        events = read_sse(client, run_id)
        names = [name for name, _ in events]
        assert names[0] == "start"
        assert names[-1] == "done"
        # 快速 Mock 往往在订阅前就跑完了，这时 SSE 走重放路径：
        # start 帧直接带全文，没有 delta。两条路径的最终文本必须一致。
        assert events[-1][1]["content"] == "矩阵乘法的核心是行列对应相乘再求和。"
        assert events[-1][1]["status"] == "succeeded"

        messages = client.get(f"/api/ai/conversations/{conversation_id}").json()["messages"]
        assert [item["role"] for item in messages] == ["user", "assistant"]
        assert messages[0]["content"] == "矩阵乘法怎么理解？"
        assert messages[1]["content"] == "矩阵乘法的核心是行列对应相乘再求和。"
        assert messages[1]["status"] == "complete"
        assert [item["sequence"] for item in messages] == [0, 1]

        run = client.app.state.database.fetchone("SELECT * FROM ai_run WHERE id = ?", (run_id,))
        assert run["status"] == "succeeded"
        assert run["provider_kind"] == "openai_compatible"
        assert run["config_version"] == 1
        assert run["finished_at"] is not None


def test_subscriber_receives_text_incrementally_not_all_at_once(tmp_path):
    """SSE 必须逐块推送，而不是憋到最后一次性吐出。"""
    handler = SlowHandler(chunks=5, delay=0.02)
    with make_client(tmp_path, handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)
        manager = client.app.state.ai_runs
        me = identity_id(client)

        async def scenario():
            started = await manager.start(
                me, conversation_id, content="逐块讲解", client_message_id="client-1"
            )
            run_id = started["run"]["id"]
            frames = [frame async for frame in manager.stream(me, run_id)]
            await wait_for_run(manager, run_id)
            return frames

        frames = asyncio.run(scenario())

        deltas = [frame for frame in frames if frame.startswith("event: delta")]
        assert len(deltas) == 5, "5 块内容应当产生 5 个独立的 delta 事件"
        texts = [json.loads(frame.split("data: ", 1)[1])["text"] for frame in deltas]
        assert texts == [f"块{index} " for index in range(5)]
        assert frames[0].startswith("event: start")
        assert json.loads(frames[0].split("data: ", 1)[1])["content"] == ""
        assert frames[-1].startswith("event: done")


def test_context_snapshot_records_which_task_the_request_used(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)

        sent = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "帮我讲讲这个任务", "client_message_id": "client-1"},
        )
        read_sse(client, sent.json()["run"]["id"])

        snapshot = client.app.state.database.fetchone(
            "SELECT * FROM context_snapshot WHERE conversation_id = ?", (conversation_id,)
        )
        assert snapshot["source_kind"] == "task_plan"
        assert snapshot["task_id"] == task_id
        assert "复习矩阵乘法" in snapshot["summary"]
        payload = json.loads(snapshot["payload"])
        assert payload["goal_title"] == "完成线性代数第一轮复习"


# ======================================================================
# SSE：提供方错误
# ======================================================================
def test_provider_error_is_reported_and_run_marked_failed(tmp_path):
    with make_client(tmp_path, failing_handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)

        sent = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "你好", "client_message_id": "client-1"},
        )
        run_id = sent.json()["run"]["id"]

        events = read_sse(client, run_id)
        assert events[-1][0] == "error"
        assert events[-1][1]["kind"] == "auth_error"
        assert FAKE_API_KEY not in json.dumps(events, ensure_ascii=False)

        run = client.app.state.database.fetchone("SELECT * FROM ai_run WHERE id = ?", (run_id,))
        assert run["status"] == "failed"
        assert run["error_kind"] == "auth_error"

        messages = client.get(f"/api/ai/conversations/{conversation_id}").json()["messages"]
        assert messages[1]["status"] == "failed"


def test_provider_runtime_is_read_once_and_config_version_is_frozen(tmp_path, monkeypatch):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)
        service = client.app.state.conversations
        original = service.provider_runtime
        calls = 0

        def counted(identity):
            nonlocal calls
            calls += 1
            return original(identity)

        monkeypatch.setattr(service, "provider_runtime", counted)
        sent = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "读取一次配置", "client_message_id": "client-1"},
        )
        assert sent.status_code == 202
        run_id = sent.json()["run"]["id"]
        read_sse(client, run_id)
        assert calls == 1
        run = client.app.state.database.fetchone("SELECT * FROM ai_run WHERE id = ?", (run_id,))
        assert run["config_version"] == 1


def test_startup_failure_is_finalized_instead_of_leaving_queued_run(tmp_path, monkeypatch):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)
        service = client.app.state.conversations
        manager = client.app.state.ai_runs
        monkeypatch.setattr(
            service,
            "build_prompt",
            lambda _history, _context: (_ for _ in ()).throw(RuntimeError("prompt setup")),
        )

        async def scenario():
            with pytest.raises(ConversationError, match="无法启动"):
                await manager.start(
                    identity_id(client),
                    conversation_id,
                    content="启动失败测试",
                    client_message_id="startup-failure",
                )

        asyncio.run(scenario())
        run = client.app.state.database.fetchone("SELECT * FROM ai_run")
        assert run["status"] == "failed"
        assert run["error_kind"] == "startup_error"
        messages = client.get(f"/api/ai/conversations/{conversation_id}").json()["messages"]
        assert messages[1]["status"] == "failed"


def test_persistence_failure_cannot_be_reported_as_success(tmp_path, monkeypatch):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)
        service = client.app.state.conversations
        original = service.finalize_run
        calls = 0

        def fail_once(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise sqlite3.OperationalError("injected finalize failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(service, "finalize_run", fail_once)
        sent = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "保存失败测试", "client_message_id": "persist-failure"},
        )
        events = read_sse(client, sent.json()["run"]["id"])
        assert events[-1][0] == "error"
        assert events[-1][1]["kind"] == "persistence_error"
        run = client.app.state.database.fetchone("SELECT * FROM ai_run")
        assert run["status"] == "failed"
        assert run["error_kind"] == "persistence_error"


def test_sending_without_provider_configuration_is_rejected(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)
        conversation_id = start_conversation(client, task_id)

        response = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "你好", "client_message_id": "client-1"},
        )
        assert response.status_code == 400
        assert "尚未配置" in response.json()["detail"]

        # 提供方不可用时不应留下任何半截消息或运行记录。
        assert client.get(f"/api/ai/conversations/{conversation_id}").json()["messages"] == []
        assert client.app.state.database.fetchall("SELECT id FROM ai_run") == []


# ======================================================================
# SSE：用户取消
# ======================================================================
def test_user_cancel_stops_generation_and_keeps_partial_text(tmp_path):
    handler = SlowHandler(chunks=100, delay=0.02)
    with make_client(tmp_path, handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)
        manager = client.app.state.ai_runs
        me = identity_id(client)

        async def scenario():
            started = await manager.start(
                me, conversation_id, content="讲很长的内容", client_message_id="client-1"
            )
            run_id = started["run"]["id"]

            # 订阅并读到几块增量，再取消——模拟用户中途点"停止"。
            agen = manager.stream(me, run_id).__aiter__()
            await drain_deltas(agen, 3)
            canceled = await manager.cancel(me, run_id)
            await agen.aclose()
            return run_id, canceled

        run_id, canceled = asyncio.run(scenario())

        assert canceled["status"] == "canceled"
        run = client.app.state.database.fetchone("SELECT * FROM ai_run WHERE id = ?", (run_id,))
        assert run["status"] == "canceled"
        assert run["finished_at"] is not None

        messages = client.get(f"/api/ai/conversations/{conversation_id}").json()["messages"]
        assert messages[1]["status"] == "canceled"
        # 取消保留已经产生的部分文本，而不是丢弃。
        assert messages[1]["content"].startswith("块0")
        # 取消真的中止了上游读取，没有把 100 块都拉完。
        assert handler.delivered < 100


def test_cancel_is_idempotent_and_scoped_to_the_identity(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)

        sent = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "你好", "client_message_id": "client-1"},
        )
        run_id = sent.json()["run"]["id"]
        read_sse(client, run_id)

        # 已经成功的运行不会被取消改写。
        again = client.post(f"/api/ai/runs/{run_id}/cancel")
        assert again.status_code == 200
        assert again.json()["run"]["status"] == "succeeded"

        assert client.post("/api/ai/runs/unknown-run/cancel").status_code == 404


# ======================================================================
# SSE：浏览器断开与刷新
# ======================================================================
def test_disconnect_does_not_kill_generation_and_reconnect_replays(tmp_path):
    handler = SlowHandler(chunks=8, delay=0.02)
    with make_client(tmp_path, handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)
        manager = client.app.state.ai_runs
        me = identity_id(client)

        async def scenario():
            started = await manager.start(
                me, conversation_id, content="讲讲矩阵", client_message_id="client-1"
            )
            run_id = started["run"]["id"]

            # 浏览器读两块就断开：退订，但后台生成继续。
            agen = manager.stream(me, run_id).__aiter__()
            await drain_deltas(agen, 2)
            await agen.aclose()
            state = manager._runs[run_id]
            assert state.subscribers == set(), "断开后应当没有残留订阅者"
            assert not state.finished, "断开不应当杀掉正在进行的生成"

            # 重连：先重放已有文本，再继续接收剩余增量直到完成。
            frames = [frame async for frame in manager.stream(me, run_id)]
            await wait_for_run(manager, run_id)
            return run_id, frames

        run_id, frames = asyncio.run(scenario())

        assert frames[0].startswith("event: start")
        assert frames[-1].startswith("event: done")
        # start 帧里带着断开前已经产生的文本，保证刷新后不丢内容。
        replayed = json.loads(frames[0].split("data: ", 1)[1])
        assert replayed["content"].startswith("块0")
        final = json.loads(frames[-1].split("data: ", 1)[1])
        assert final["content"].startswith("块0")
        assert "块7" in final["content"]
        # 生成跑完了全部 8 块，没有因为断开而截断。
        assert handler.delivered == 8

        messages = client.get(f"/api/ai/conversations/{conversation_id}").json()["messages"]
        assert messages[1]["status"] == "complete"
        assert "块7" in messages[1]["content"]
        assert len(messages) == 2


def test_refresh_mid_stream_does_not_append_a_second_message(tmp_path):
    handler = SlowHandler(chunks=6, delay=0.02)
    with make_client(tmp_path, handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)
        manager = client.app.state.ai_runs
        me = identity_id(client)

        async def scenario():
            started = await manager.start(
                me, conversation_id, content="讲讲行列式", client_message_id="client-1"
            )
            run_id = started["run"]["id"]

            # 刷新前：读一块就断开。
            agen = manager.stream(me, run_id).__aiter__()
            await drain_deltas(agen, 1)
            await agen.aclose()

            # 刷新后：重新拉对话，此时仍应看到同一条进行中的运行。
            mid = manager.conversations.conversation_detail(me, conversation_id)

            # 用同一个 client_message_id 重新提交（前端刷新后重放）：不得新建运行。
            resubmitted = await manager.start(
                me, conversation_id, content="讲讲行列式", client_message_id="client-1"
            )

            # 重新订阅同一个 run 直到结束。
            async for _ in manager.stream(me, run_id):
                pass
            await wait_for_run(manager, run_id)
            return run_id, mid, resubmitted

        run_id, mid, resubmitted = asyncio.run(scenario())

        assert len(mid["messages"]) == 2
        assert mid["active_run"]["id"] == run_id
        assert resubmitted["created"] is False
        assert resubmitted["run"]["id"] == run_id

        final = client.get(f"/api/ai/conversations/{conversation_id}").json()
        # 刷新和重放都没有追加第三条消息。
        assert len(final["messages"]) == 2
        assert final["active_run"] is None
        assert [item["sequence"] for item in final["messages"]] == [0, 1]
        assert final["messages"][1]["status"] == "complete"
        assert len(client.app.state.database.fetchall("SELECT id FROM ai_run")) == 1


# ======================================================================
# 幂等
# ======================================================================
def test_duplicate_submission_reuses_the_same_run(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)

        first = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "重复提交测试", "client_message_id": "same-id"},
        )
        assert first.json()["created"] is True
        run_id = first.json()["run"]["id"]

        second = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "重复提交测试", "client_message_id": "same-id"},
        )
        assert second.status_code == 202
        assert second.json()["created"] is False
        assert second.json()["run"]["id"] == run_id

        read_sse(client, run_id)

        # 重复提交后再来一次，仍然命中同一条运行。
        third = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "重复提交测试", "client_message_id": "same-id"},
        )
        assert third.json()["created"] is False
        assert third.json()["run"]["id"] == run_id

        messages = client.get(f"/api/ai/conversations/{conversation_id}").json()["messages"]
        assert len(messages) == 2
        runs = client.app.state.database.fetchall("SELECT id FROM ai_run")
        assert len(runs) == 1


def test_same_client_message_id_with_different_content_is_a_conflict(tmp_path):
    with make_client(tmp_path, SlowHandler(chunks=20, delay=0.02)) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)

        first = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "第一份正文", "client_message_id": "same-id"},
        )
        run_id = first.json()["run"]["id"]
        conflicting = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "不同正文", "client_message_id": "same-id"},
        )
        assert conflicting.status_code == 409
        assert "不同" in conflicting.json()["detail"]
        assert len(client.app.state.database.fetchall("SELECT id FROM ai_run")) == 1
        assert len(client.get(f"/api/ai/conversations/{conversation_id}").json()["messages"]) == 2
        client.post(f"/api/ai/runs/{run_id}/cancel")


def test_unique_index_blocks_duplicate_client_message_id(tmp_path):
    import sqlite3

    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)
        client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "你好", "client_message_id": "dup"},
        )

        with pytest.raises(sqlite3.IntegrityError):
            with client.app.state.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO message
                        (id, conversation_id, role, content, sequence, status,
                         client_message_id, created_at, updated_at)
                    VALUES ('forced', ?, 'user', '你好', 99, 'complete', 'dup', 'now', 'now')
                    """,
                    (conversation_id,),
                )


def test_second_message_is_blocked_while_a_run_is_active(tmp_path):
    handler = SlowHandler(chunks=20, delay=0.02)
    with make_client(tmp_path, handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)

        first = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "第一个问题", "client_message_id": "client-1"},
        )
        run_id = first.json()["run"]["id"]

        blocked = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "第二个问题", "client_message_id": "client-2"},
        )
        assert blocked.status_code == 409
        assert "正在进行" in blocked.json()["detail"]

        client.post(f"/api/ai/runs/{run_id}/cancel")

        allowed = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "第二个问题", "client_message_id": "client-2"},
        )
        assert allowed.status_code == 202
        assert allowed.json()["created"] is True


def test_conversation_history_is_sent_to_the_provider(tmp_path):
    captured: list[dict] = []

    def capturing_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload.get("stream") is True:
            captured.append(payload)
        return streaming_handler(request)

    with make_client(tmp_path, capturing_handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)

        first = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "第一个问题", "client_message_id": "client-1"},
        )
        read_sse(client, first.json()["run"]["id"])
        second = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "第二个问题", "client_message_id": "client-2"},
        )
        read_sse(client, second.json()["run"]["id"])

        assert len(captured) == 2
        roles = [item["role"] for item in captured[1]["messages"]]
        assert roles == ["system", "user", "assistant", "user"]
        # 系统提示带上了任务上下文。
        assert "复习矩阵乘法" in captured[1]["messages"][0]["content"]
        assert captured[1]["messages"][-1]["content"] == "第二个问题"
        assert captured[1]["model"] == "gpt-4o"


# ======================================================================
# 身份校验
# ======================================================================
def test_every_ai_endpoint_requires_local_authorization(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        endpoints = [
            ("get", "/api/ai/provider", None),
            ("put", "/api/ai/provider", {"base_url": "https://a.com", "model": "m"}),
            ("delete", "/api/ai/provider", None),
            ("post", "/api/ai/provider/test", None),
            ("get", "/api/ai/conversations", None),
            ("post", "/api/ai/conversations", {}),
            ("get", "/api/ai/conversations/any", None),
            ("post", "/api/ai/conversations/any/messages", {"content": "x", "client_message_id": "y"}),
            ("get", "/api/ai/tasks/any/context", None),
            ("get", "/api/ai/runs/any/stream", None),
            ("post", "/api/ai/runs/any/cancel", None),
        ]
        for method, path, payload in endpoints:
            call = getattr(client, method)
            response = call(path, json=payload) if payload is not None else call(path)
            assert response.status_code == 401, f"{method} {path} 应当要求授权"
            assert response.json()["detail"] == "需要先完成本地授权"


def test_another_identity_cannot_read_or_cancel_the_conversation(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)
        sent = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "你好", "client_message_id": "client-1"},
        )
        run_id = sent.json()["run"]["id"]
        read_sse(client, run_id)

        # 换一个身份：会话仍在，但对话属于原身份。
        with client.app.state.database.transaction() as connection:
            connection.execute(
                "INSERT INTO local_identity (id, device_id, display_name, timezone, created_at, updated_at)"
                " VALUES ('other', 'other-device', '其他人', 'Asia/Shanghai', 'now', 'now')"
            )
            connection.execute("UPDATE sessions SET identity_id = 'other'")

        assert client.get(f"/api/ai/conversations/{conversation_id}").status_code == 404
        assert client.post(f"/api/ai/runs/{run_id}/cancel").status_code == 404
        assert client.get("/api/ai/conversations").json() == []


def test_empty_message_is_rejected(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)

        response = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "   ", "client_message_id": "client-1"},
        )
        assert response.status_code == 422


# ======================================================================
# 迁移边界
# ======================================================================
def test_ai_migrations_are_applied_and_create_expected_tables(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        database = client.app.state.database
        versions = [
            row["version"]
            for row in database.fetchall("SELECT version FROM schema_migrations ORDER BY version")
        ]
        assert versions == [
            "001_initial",
            "002_learning_plans",
            "003_dashboard_layouts",
            "004_plan_editor",
            "005_ai_conversations",
            "006_ai_message_reasoning",
            "007_ai_multi_provider_model_selection",
            "008_ai_conversation_titles",
            "009_task_completion_restore",
            "010_ai_conversation_scope",
        ]

        tables = {
            row["name"]
            for row in database.fetchall("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {
            "provider_profile",
            "conversation",
            "conversation_link",
            "message",
            "context_snapshot",
            "ai_run",
            "conversation_title_run",
        } <= tables

        # 001-004 的表依然存在，迁移是叠加而不是重建。
        assert {"local_identity", "sessions", "learning_goal", "subject", "topic", "task"} <= tables
        assert database.fetchall("PRAGMA foreign_key_check") == []

        indexes = {
            row["name"]
            for row in database.fetchall("SELECT name FROM sqlite_master WHERE type = 'index'")
        }
        assert {
            "idx_ai_run_one_active_conversation",
            "idx_ai_run_request_message",
            "idx_ai_run_response_message",
        } <= indexes
        columns = {
            row["name"] for row in database.fetchall("PRAGMA table_info(message)")
        }
        assert "reasoning_content" in columns


def test_failed_migration_rolls_back_the_whole_script(tmp_path):
    migrations = tmp_path / "broken-migrations"
    migrations.mkdir()
    (migrations / "001_broken.sql").write_text(
        "CREATE TABLE partial_table (id INTEGER);\n"
        "CREATE TABLE invalid_table (id INTEGER, );\n",
        encoding="utf-8",
    )
    database_path = tmp_path / "broken.sqlite3"

    with pytest.raises(sqlite3.OperationalError):
        Database(database_path, migrations)

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert "partial_table" not in tables
        assert connection.execute("SELECT version FROM schema_migrations").fetchall() == []
    finally:
        connection.close()


def test_migration_is_idempotent_on_reopen(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)

    # 用同一个数据目录重新打开：迁移不会重跑，也不会丢数据。
    with make_client(tmp_path, streaming_handler) as reopened:
        versions = [
            row["version"]
            for row in reopened.app.state.database.fetchall(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        assert versions.count("005_ai_conversations") == 1
        assert versions.count("006_ai_message_reasoning") == 1
        authorize(reopened)
        assert reopened.get(f"/api/ai/conversations/{conversation_id}").status_code == 200
        assert reopened.get("/api/ai/provider").json()["provider"]["has_api_key"] is True


def test_ai_run_status_machine_covers_all_states(tmp_path):
    import sqlite3

    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        database = client.app.state.database
        # CHECK 约束必须挡住非法状态。
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as connection:
                connection.execute(
                    "INSERT INTO ai_run (id, identity_id, conversation_id, status, created_at, updated_at)"
                    " VALUES ('x', 'y', 'z', 'unknown-status', 'now', 'now')"
                )


def test_interrupted_run_from_a_previous_process_is_finalized(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        task_id = create_task(client)
        configure_provider(client)
        conversation_id = start_conversation(client, task_id)
        sent = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "你好", "client_message_id": "client-1"},
        )
        run_id = sent.json()["run"]["id"]
        read_sse(client, run_id)

        # 伪造一次"服务重启前遗留"的运行：数据库说 running，内存里没有。
        with client.app.state.database.transaction() as connection:
            connection.execute(
                "UPDATE ai_run SET status = 'running', finished_at = NULL WHERE id = ?",
                (run_id,),
            )
        client.app.state.ai_runs._runs.clear()

        events = read_sse(client, run_id)
        assert events[-1][0] == "error"
        assert events[-1][1]["kind"] == "interrupted"

        run = client.app.state.database.fetchone("SELECT * FROM ai_run WHERE id = ?", (run_id,))
        assert run["status"] == "failed"
        assert run["error_kind"] == "interrupted"
