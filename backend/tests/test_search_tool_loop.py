"""The external-search path follows actual provider tool calls."""
import json

import httpx

from test_ai_conversations import authorize, configure_provider, create_task, make_client, read_sse, start_conversation
from test_search_runtime import SEARCH_URL, answer_chunk, chat_stream, save_tavily, search_call, send


def _setup(client, *, max_requests=1):
    authorize(client)
    configure_provider(client)
    saved = save_tavily(client)
    if max_requests != 1:
        saved = client.put("/api/search/settings", json={
            "revision": saved["revision"], "services": saved["services"],
            "selected_service_id": "tavily-test", "result_size": 3,
            "timeout_seconds": 5, "max_requests": max_requests,
        })
        assert saved.status_code == 200, saved.text
    return start_conversation(client, create_task(client))


def _run(client, conversation, key, *, search=None, content="Question"):
    selected = search or {"mode": "external", "service_id": "tavily-test"}
    sent = send(client, conversation, key, selected, content=content)
    assert sent.status_code == 202, sent.text
    events = read_sse(client, sent.json()["run"]["id"])
    assert events[-1][0] == "done", events
    return events[-1][1]


def test_model_can_answer_without_external_request(tmp_path):
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append((str(request.url), payload))
        if payload.get("stream"):
            assert payload["tools"][0]["function"]["name"] == "search_web"
            return httpx.Response(200, text=chat_stream(answer_chunk("Known from context")))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Title"}}]})

    with make_client(tmp_path, handler) as client:
        conversation = _setup(client)
        done = _run(client, conversation, "no-call", content="Explain the definition already given")
        assert done["content"] == "Known from context"
        assert done["search_trace"]["status"] == "not_used"
        assert done["search_trace"]["requests"] == []
        assert all(url != "https://api.tavily.com/search" for url, _ in calls)


def test_model_uses_conversation_referent_for_focused_query(tmp_path):
    calls = []
    focused = "Mira theorem publication year"

    def handler(request):
        url = str(request.url)
        payload = json.loads(request.content)
        calls.append((url, payload))
        if url == "https://api.tavily.com/search":
            assert payload["query"] == focused
            return httpx.Response(200, json={"results": [{"title": "Source", "url": SEARCH_URL, "content": "Published in 2022", "publishedDate": "2022-03-01", "highlights": ["Publication date confirmed"]}]})
        if payload.get("stream") and payload.get("tools"):
            if any(m.get("role") == "tool" for m in payload["messages"]):
                evidence = json.loads(payload["messages"][-1]["content"])
                assert evidence["items"][0]["published_date"] == "2022-03-01"
                assert evidence["items"][0]["highlights"] == ["Publication date confirmed"]
                return httpx.Response(200, text=chat_stream(answer_chunk("It was published in 2022.")))
            assert "Mira theorem" in json.dumps(payload["messages"])
            return httpx.Response(200, text=chat_stream(search_call(focused)))
        if payload.get("stream"):
            return httpx.Response(200, text=chat_stream(answer_chunk("Mira theorem")))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Title"}}]})

    with make_client(tmp_path, handler) as client:
        conversation = _setup(client)
        off = _run(client, conversation, "history", search={"mode": "off"}, content="Let's discuss Mira theorem.")
        assert off["content"] == "Mira theorem"
        done = _run(client, conversation, "referent", content="When was it published?")
        assert done["search_trace"]["status"] == "succeeded"
        assert done["search_trace"]["requests"][0]["query"] == focused
        assert done["search_trace"]["items"][0]["url"] == SEARCH_URL
        assert done["content"] == "It was published in 2022."
        first_search = next(i for i, (url, _) in enumerate(calls) if url == "https://api.tavily.com/search")
        first_tool_turn = next(i for i, (_, payload) in enumerate(calls) if payload.get("stream") and payload.get("tools"))
        assert first_tool_turn < first_search


def test_followup_calls_replay_results_and_stop_at_budget(tmp_path):
    calls = []

    def handler(request):
        url = str(request.url)
        payload = json.loads(request.content)
        calls.append((url, payload))
        if url == "https://api.tavily.com/search":
            return httpx.Response(200, json={"results": [{"title": "Source", "url": SEARCH_URL, "content": "Evidence"}]})
        if url == "https://api.tavily.com/extract":
            return httpx.Response(200, json={"results": [{"url": SEARCH_URL, "raw_content": "Full evidence"}]})
        if payload.get("stream") and payload.get("tools"):
            history = payload["messages"]
            tool_results = [m for m in history if m.get("role") == "tool"]
            if not tool_results:
                return httpx.Response(200, text=chat_stream(search_call("focused", call_id="first")))
            if len(tool_results) == 1:
                assert tool_results[0]["tool_call_id"] == "first"
                assert SEARCH_URL in tool_results[0]["content"]
                return httpx.Response(200, text=chat_stream({"delta": {"tool_calls": [{"index": 0, "id": "second",
                    "type": "function", "function": {"name": "scrape_web", "arguments": json.dumps({"url": SEARCH_URL})}}]},
                    "finish_reason": "tool_calls"}))
            assert tool_results[-1]["tool_call_id"] == "second"
            assert "Full evidence" in tool_results[-1]["content"]
            assert payload["tool_choice"] == "none"
            return httpx.Response(200, text=chat_stream(answer_chunk("Grounded answer")))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Title"}}]})

    with make_client(tmp_path, handler) as client:
        conversation = _setup(client, max_requests=2)
        done = _run(client, conversation, "followup")
        assert done["content"] == "Grounded answer"
        assert [entry["action"] for entry in done["search_trace"]["requests"]] == ["search", "scrape"]
        assert len([url for url, _ in calls if url == "https://api.tavily.com/search"]) == 1
        assert len([url for url, _ in calls if url == "https://api.tavily.com/extract"]) == 1


def test_unknown_tool_uses_budget_without_outbound_request(tmp_path):
    calls = []

    def handler(request):
        url = str(request.url)
        payload = json.loads(request.content)
        calls.append((url, payload))
        if payload.get("stream"):
            if not any(m.get("role") == "tool" for m in payload["messages"]):
                return httpx.Response(200, text=chat_stream({"delta": {"tool_calls": [{"index": 0,
                    "id": "bad-1", "type": "function", "function": {"name": "unapproved_tool",
                    "arguments": "{}"}}]}, "finish_reason": "tool_calls"}))
            assert "error" in payload["messages"][-1]["content"]
            assert payload["tool_choice"] == "none"
            return httpx.Response(200, text=chat_stream(answer_chunk("Cannot verify externally.")))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Title"}}]})

    with make_client(tmp_path, handler) as client:
        conversation = _setup(client)
        done = _run(client, conversation, "unknown-tool")
        assert done["content"] == "Cannot verify externally."
        assert done["search_trace"]["status"] == "failed"
        assert done["search_trace"]["requests"][0]["status"] == "failed"
        assert all(url != "https://api.tavily.com/search" for url, _ in calls)


def test_user_filter_overrides_model_filter_and_failure_still_answers(tmp_path):
    calls = []

    def handler(request):
        url = str(request.url)
        payload = json.loads(request.content)
        calls.append((url, payload))
        if url == "https://api.tavily.com/search":
            assert payload["topic"] == "finance"
            assert payload["query"] == "focused evidence"
            return httpx.Response(503, json={"error": "synthetic outage"})
        if payload.get("stream"):
            if not any(m.get("role") == "tool" for m in payload["messages"]):
                return httpx.Response(200, text=chat_stream(search_call("focused evidence", topic="news")))
            assert "error" in payload["messages"][-1]["content"]
            return httpx.Response(200, text=chat_stream(answer_chunk("The source is unavailable.")))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Title"}}]})

    with make_client(tmp_path, handler) as client:
        conversation = _setup(client)
        done = _run(client, conversation, "filter-failure", search={"mode": "external", "service_id": "tavily-test",
            "parameters": {"topic": "finance"}})
        assert done["content"] == "The source is unavailable."
        assert done["search_trace"]["status"] == "failed"
        assert done["search_trace"]["items"] == []
        assert len([url for url, _ in calls if url == "https://api.tavily.com/search"]) == 1


def test_malformed_tool_arguments_fail_without_outbound_request(tmp_path):
    calls = []

    def handler(request):
        url = str(request.url)
        payload = json.loads(request.content)
        calls.append((url, payload))
        if payload.get("stream"):
            return httpx.Response(200, text=chat_stream({"delta": {"tool_calls": [{"index": 0,
                "id": "malformed", "type": "function", "function": {"name": "search_web",
                "arguments": "{not-json"}}]}, "finish_reason": "tool_calls"}))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Title"}}]})

    with make_client(tmp_path, handler) as client:
        conversation = _setup(client)
        sent = send(client, conversation, "malformed", {"mode": "external", "service_id": "tavily-test"})
        assert sent.status_code == 202, sent.text
        events = read_sse(client, sent.json()["run"]["id"])
        assert events[-1][0] == "error"
        assert events[-1][1]["kind"] == "protocol_error"
        assert all(url != "https://api.tavily.com/search" for url, _ in calls)


def test_parallel_calls_over_budget_receive_results_without_extra_search(tmp_path):
    searches = []

    def handler(request):
        payload = json.loads(request.content)
        if str(request.url) == 'https://api.tavily.com/search':
            searches.append(payload['query'])
            return httpx.Response(200, json={'results': [{'title': 'Source', 'url': SEARCH_URL, 'content': 'Evidence'}]})
        if not payload.get('stream'):
            return httpx.Response(200, json={'choices': [{'message': {'content': 'Title'}}]})
        if not any(m.get('role') == 'tool' for m in payload['messages']):
            calls = [{'index': index, 'id': f'parallel-{index}', 'type': 'function',
                      'function': {'name': 'search_web', 'arguments': json.dumps({'query': f'focused-{index}'})}}
                     for index in range(3)]
            return httpx.Response(200, text=chat_stream({'delta': {'tool_calls': calls}, 'finish_reason': 'tool_calls'}))
        results = [m for m in payload['messages'] if m.get('role') == 'tool']
        assert [m['tool_call_id'] for m in results] == ['parallel-0', 'parallel-1', 'parallel-2']
        assert SEARCH_URL in results[0]['content']
        assert all('budget exhausted' in m['content'] for m in results[1:])
        assert payload['tool_choice'] == 'none'
        return httpx.Response(200, text=chat_stream(answer_chunk('Answer from available evidence')))

    with make_client(tmp_path, handler) as client:
        conversation = _setup(client)
        done = _run(client, conversation, 'parallel-budget')
        assert searches == ['focused-0']
        assert done['search_trace']['status'] == 'succeeded'
        assert len(done['search_trace']['requests']) == 1
