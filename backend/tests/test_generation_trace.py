"""Timing and ordering guarantees for the visible model/tool process."""
import json

import pytest

import httpx

from app.generation_trace import GenerationRecorder, interrupt_trace
from app.providers import ProviderChunk
from test_ai_conversations import authorize, configure_provider, create_task, make_client, read_sse, start_conversation
from test_search_runtime import SEARCH_URL, answer_chunk, chat_stream, save_tavily


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def chunk(kind, value):
    return ProviderChunk(kind, value)


def test_ordered_reasoning_text_tool_reasoning_text_uses_segment_times():
    clock = Clock()
    published = []
    recorder = GenerationRecorder(published.append, clock=clock)
    recorder.observe(chunk("reasoning", "Need evidence"))
    clock.advance(.125)
    recorder.observe(chunk("content", "Checking a source."))
    clock.advance(.075)
    recorder.observe(chunk("tool_start", json.dumps({"call_id": "call-1", "name": "search_web", "query": "focused"})))
    clock.advance(1.5)
    recorder.observe(chunk("tool_end", json.dumps({"call_id": "call-1", "status": "succeeded"})))
    recorder.observe(chunk("reasoning", "Source confirms it"))
    clock.advance(.25)
    recorder.observe(chunk("content", "Final answer"))
    clock.advance(.05)
    recorder.finish("succeeded")

    trace = recorder.trace
    assert trace["status"] == "succeeded"
    assert [part["type"] for part in trace["parts"]] == ["reasoning", "text", "tool", "reasoning", "text"]
    assert [part["duration_ms"] for part in trace["parts"]] == [125, 75, 1500, 250, 50]
    assert trace["elapsed_ms"] == 2000
    assert all(part["status"] == "succeeded" for part in trace["parts"])
    assert published[-1] == trace


def test_tool_only_response_never_invents_thinking():
    clock = Clock()
    recorder = GenerationRecorder(lambda _: None, clock=clock)
    recorder.observe(chunk("tool_start", json.dumps({"call_id": "call-1", "name": "search_web"})))
    clock.advance(.4)
    recorder.observe(chunk("tool_end", json.dumps({"call_id": "call-1", "status": "failed"})))
    recorder.observe(chunk("content", "The search failed."))
    recorder.finish("succeeded")
    assert [part["type"] for part in recorder.trace["parts"]] == ["tool", "text"]
    assert recorder.trace["parts"][0]["duration_ms"] == 400
    assert recorder.trace["parts"][0]["status"] == "failed"


def test_interruption_seals_last_observed_duration_without_server_downtime():
    clock = Clock()
    recorder = GenerationRecorder(lambda _: None, clock=clock)
    recorder.observe(chunk("reasoning", "Still working"))
    clock.advance(.2)
    recorder.flush(force=True)
    saved = json.loads(json.dumps(recorder.trace))
    restored = interrupt_trace(saved)
    assert restored["status"] == "interrupted"
    assert restored["finished_at"] == saved["updated_at"]
    assert restored["parts"][0]["status"] == "interrupted"
    assert restored["parts"][0]["duration_ms"] == 200
    assert restored["parts"][0]["finished_at"] == saved["updated_at"]
    assert saved["status"] == "running"


def test_app_process_replays_and_next_external_turn_retains_tool_history(tmp_path):
    calls = []
    first_question_turns = 0

    def handler(request):
        nonlocal first_question_turns
        url = str(request.url)
        payload = json.loads(request.content)
        calls.append((url, payload))
        if url == "https://api.tavily.com/search":
            return httpx.Response(200, json={"results": [{"title": "Source", "url": SEARCH_URL, "content": "Synthetic evidence"}]})
        if not payload.get("stream"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "Title"}}]})
        messages = payload["messages"]
        if messages[-1].get("role") == "user" and messages[-1].get("content") == "First question":
            first_question_turns += 1
            if first_question_turns == 2:
                assert all(m.get("content") != "Second question" for m in messages)
                assert not any(m.get("role") == "tool" and m.get("tool_call_id") == "source-1" for m in messages)
                return httpx.Response(200, text=chat_stream(answer_chunk("Revised first answer")))
            return httpx.Response(200, text=chat_stream(
                {"delta": {"reasoning_content": "Need evidence", "tool_calls": [{"index": 0, "id": "source-1",
                    "type": "function", "function": {"name": "search_web", "arguments": '{"query":"focused source"}'}}]},
                 "finish_reason": "tool_calls"}))
        if messages[-1].get("role") == "tool":
            assert messages[-1]["tool_call_id"] == "source-1"
            return httpx.Response(200, text=chat_stream({"delta": {"reasoning_content": "Evidence checked"}},
                answer_chunk("First answer")))
        if messages[-1].get("role") == "user" and messages[-1].get("content") == "Second question":
            assert sum(m.get("role") == "user" and m.get("content") == "First question" for m in messages) == 1
            assert any(m.get("role") == "tool" and m.get("tool_call_id") == "source-1" for m in messages)
            assert any(m.get("role") == "assistant" and m.get("reasoning_content") == "Evidence checked" for m in messages)
            return httpx.Response(200, text=chat_stream(answer_chunk("Second answer")))
        raise AssertionError(messages)

    with make_client(tmp_path, handler) as client:
        authorize(client)
        configure_provider(client)
        save_tavily(client)
        conversation = start_conversation(client, create_task(client))
        first = client.post(f"/api/ai/conversations/{conversation}/messages", json={
            "content": "First question", "client_message_id": "first", "search": {"mode": "external", "service_id": "tavily-test"}})
        assert first.status_code == 202, first.text
        first_events = read_sse(client, first.json()["run"]["id"])
        assert first_events[-1][0] == "done", first_events
        first_trace = first_events[-1][1]["generation_trace"]
        assert [part["type"] for part in first_trace["parts"]] == ["reasoning", "tool", "reasoning", "text"]
        assert first_trace["parts"][1]["call_id"] == "source-1"
        assert first_trace["parts"][1]["result"]["items"][0]["url"] == SEARCH_URL
        detail = client.get(f"/api/ai/conversations/{conversation}").json()
        assert detail["messages"][-1]["generation_trace"] == first_trace
        assert "_model_turn" not in json.dumps(detail)
        repeated = client.post(f"/api/ai/conversations/{conversation}/messages", json={
            "content": "First question", "client_message_id": "first", "search": {"mode": "external", "service_id": "tavily-test"}})
        assert repeated.json()["created"] is False
        assert "model_turn" not in json.loads(repeated.json()["run"]["config_snapshot_json"])


        second = client.post(f"/api/ai/conversations/{conversation}/messages", json={
            "content": "Second question", "client_message_id": "second", "search": {"mode": "external", "service_id": "tavily-test"}})
        assert second.status_code == 202, second.text
        second_events = read_sse(client, second.json()["run"]["id"])
        assert second_events[-1][0] == "done", second_events
        assert second_events[-1][1]["generation_trace"]["parts"][-1]["text"] == "Second answer"

        first_answer_id = detail["messages"][-1]["id"]
        revised = client.post(f"/api/ai/conversations/{conversation}/messages", json={
            "content": "First question", "client_message_id": "revised-first", "regenerate_message_id": first_answer_id,
            "search": {"mode": "external", "service_id": "tavily-test"}})
        assert revised.status_code == 202, revised.text
        revised_events = read_sse(client, revised.json()["run"]["id"])
        assert revised_events[-1][0] == "done", revised_events
        assert revised_events[-1][1]["content"] == "Revised first answer"


@pytest.mark.parametrize("cancel", [False, True])
def test_orphaned_process_stops_timer_and_keeps_partial_text(tmp_path, cancel):
    def handler(_request):
        raise AssertionError("Recovery must not invoke the model")

    with make_client(tmp_path, handler) as client:
        authorize(client)
        configure_provider(client)
        conversation = start_conversation(client, create_task(client))
        service = client.app.state.conversations
        owner = client.app.state.auth.ensure_local_identity()["id"]
        prepared = service.prepare_run(owner, conversation, content="Synthetic question", client_message_id="interrupted")
        clock = Clock()
        recorder = GenerationRecorder(lambda _: None, clock=clock)
        recorder.observe(chunk("reasoning", "Synthetic thought"))
        clock.advance(.2)
        recorder.observe(chunk("content", "Partial answer"))
        clock.advance(.3)
        recorder.flush(force=True)
        service.save_generation_trace(prepared["run"]["id"], recorder.trace)
        if cancel:
            response = client.post(f"/api/ai/runs/{prepared['run']['id']}/cancel")
            assert response.status_code == 200
        else:
            events = read_sse(client, prepared["run"]["id"])
            assert events[-1][0] == "error"
        answer = client.get(f"/api/ai/conversations/{conversation}").json()["messages"][-1]
        assert answer["content"] == "Partial answer"
        trace = answer["generation_trace"]
        assert trace["status"] == ("canceled" if cancel else "interrupted")
        assert trace["parts"][-1]["duration_ms"] == 300
        assert trace["parts"][-1]["status"] == trace["status"]
