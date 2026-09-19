#!/usr/bin/env python3
"""Playwright 专用 OpenAI-compatible Mock HTTP/SSE 服务。

只处理测试中的假数据；不会记录 Authorization、API key、请求正文或用户内容。
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


SUCCESS_CHUNKS = [
    "## 学习步骤\n\n",
    "1. 先明确目标。\n2. 再拆成步骤。\n\n",
    "| 检查项 | 方法 |\n| --- | --- |\n| 理解 | 用例题检查 |\n\n`完成`",
]
REFRESH_CHUNKS = [f"刷新块 {index}。" for index in range(1, 13)]
SLOW_CHUNKS = [f"慢速块 {index}。" for index in range(1, 61)]


class MockState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: Counter[str] = Counter()
        self.delivered: Counter[str] = Counter()
        self.disconnects: Counter[str] = Counter()

    def reset(self) -> None:
        with self._lock:
            self.requests.clear()
            self.delivered.clear()
            self.disconnects.clear()

    def requested(self, scenario: str) -> None:
        with self._lock:
            self.requests[scenario] += 1

    def chunk_delivered(self, scenario: str) -> None:
        with self._lock:
            self.delivered[scenario] += 1

    def disconnected(self, scenario: str) -> None:
        with self._lock:
            self.disconnects[scenario] += 1

    def snapshot(self) -> dict[str, dict[str, int]]:
        with self._lock:
            return {
                "requests": dict(self.requests),
                "delivered": dict(self.delivered),
                "disconnects": dict(self.disconnects),
            }


STATE = MockState()


class MockOpenAIHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: Any) -> None:
        # 严禁把 Authorization、请求正文或测试假密钥写入日志。
        return

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/health":
            self._json(200, {"status": "ok"})
            return
        if self.path == "/__mock__/stats":
            self._json(200, STATE.snapshot())
            return
        if self.path.endswith("/models"):
            if not self.headers.get("Authorization", "").startswith("Bearer "):
                self._json(401, {"error": {"message": "missing API key"}})
                return
            STATE.requested("models")
            self._json(
                200,
                {
                    "data": [
                        {"id": "mock-success"},
                        {"id": "mock-reasoning"},
                        {"id": "mock-refresh"},
                        {"id": "mock-slow"},
                        {"id": "mock-evidence"},
                        {"id": "mock-error"},
                    ]
                },
            )
            return
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/__mock__/reset":
            STATE.reset()
            self._json(200, {"ok": True})
            return
        if not self.path.endswith("/chat/completions"):
            self._json(404, {"error": {"message": "not found"}})
            return

        payload = self._read_json()
        if payload is None:
            self._json(400, {"error": {"message": "invalid json"}})
            return
        if not self.headers.get("Authorization", "").startswith("Bearer "):
            self._json(401, {"error": {"message": "missing API key"}})
            return

        model = str(payload.get("model", "mock-success"))
        scenario = model if model in {"mock-success", "mock-reasoning", "mock-refresh", "mock-slow", "mock-evidence", "mock-error"} else "mock-success"
        is_title_request = payload.get("stream") is not True and int(payload.get("max_tokens") or 0) >= 256
        STATE.requested(f"title:{scenario}" if is_title_request else scenario)

        if scenario == "mock-error":
            self._json(401, {"error": {"message": "Mock provider rejected the API key"}})
            return
        if payload.get("stream") is not True:
            if scenario == "mock-evidence":
                content = json.dumps(
                    {
                        "dimension_id": "syntax_semantics",
                        "stance": "supports",
                        "source": "ai_analysis",
                        "statement": "语义分析确认产出说明了正则表达式的匹配语义。",
                        "verification_method": "semantic_analysis",
                        "evidence_condition": "independent",
                        "scope": "artifact",
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            else:
                content = "学习步骤与目标拆解" if is_title_request else "pong"
            self._json(
                200,
                {
                    "model": model,
                    "choices": [{"message": {"role": "assistant", "content": content}}],
                },
            )
            return

        chunks, delay = self._scenario_stream(scenario)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            if scenario == "mock-reasoning":
                for reasoning in ["先识别题目条件。", "再核对推导路径。"]:
                    event = json.dumps(
                        {"choices": [{"delta": {"reasoning_content": reasoning}}]},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    self.wfile.write(f"data: {event}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    STATE.chunk_delivered(scenario)
                    time.sleep(0.10)
            for chunk in chunks:
                event = json.dumps(
                    {"choices": [{"delta": {"content": chunk}}]},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                self.wfile.write(f"data: {event}\n\n".encode("utf-8"))
                self.wfile.flush()
                STATE.chunk_delivered(scenario)
                time.sleep(delay)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            STATE.disconnected(scenario)
        finally:
            self.close_connection = True

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _scenario_stream(scenario: str) -> tuple[list[str], float]:
        if scenario == "mock-refresh":
            return REFRESH_CHUNKS, 0.12
        if scenario == "mock-slow":
            return SLOW_CHUNKS, 0.08
        return SUCCESS_CHUNKS, 0.10

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        self.close_connection = True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8013)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), MockOpenAIHandler)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
