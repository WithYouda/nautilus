"""Search integration checks through real app state and mocked outbound protocols."""
import asyncio
import json

import httpx
import pytest

from test_ai_conversations import authorize, configure_provider, create_task, make_client, read_sse, start_conversation
from test_learning_domain_schema import learning_database  # noqa: F401
from app.search_service import SearchService


SEARCH_URL = "https://source.example/article"


def chat_stream(*events):
    return "".join(f"data: {json.dumps({'choices': [event]})}\n\n" for event in events) + "data: [DONE]\n\n"


def search_call(query="focused", *, call_id="search-1", **parameters):
    return {"delta": {"tool_calls": [{"index": 0, "id": call_id, "type": "function",
            "function": {"name": "search_web", "arguments": json.dumps({"query": query, **parameters})}}]},
            "finish_reason": "tool_calls"}


def answer_chunk(content="Answer"):
    return {"delta": {"content": content}, "finish_reason": "stop"}


def save_tavily(client):
    current = client.get("/api/search/settings").json()
    saved = client.put("/api/search/settings", json={
        "revision": current["revision"],
        "services": [{"id": "tavily-test", "kind": "tavily", "name": "Test search",
                      "options": {"depth": "basic"}, "secret_updates": {"api_key": "fake-search-key"}}],
        "selected_service_id": "tavily-test", "result_size": 3, "timeout_seconds": 5, "max_requests": 1,
    })
    assert saved.status_code == 200, saved.text
    return saved.json()


def handler_factory(*, search_failure=False):
    calls = []

    def handler(request):
        url = str(request.url)
        payload = json.loads(request.content) if request.content else {}
        calls.append((url, payload))
        if url == "https://api.tavily.com/search":
            assert request.headers["Authorization"] == "Bearer fake-search-key"
            if search_failure:
                return httpx.Response(503, json={"error": "synthetic failure"})
            return httpx.Response(200, json={"results": [{"title": "Source", "url": SEARCH_URL, "content": "Verified source"}]})
        if payload.get("stream") and payload.get("tools"):
            if any(message.get("role") == "tool" for message in payload["messages"]):
                return httpx.Response(200, text=chat_stream(answer_chunk()))
            return httpx.Response(200, text=chat_stream(search_call("focused")))
        if payload.get("stream"):
            return httpx.Response(200, text=chat_stream(answer_chunk()))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Title"}}]})
    return handler, calls


def send(client, conversation_id, key, search=None, **extra):
    body = {"content": "Question", "client_message_id": key, **extra}
    if search is not None:
        body["search"] = search
    return client.post(f"/api/ai/conversations/{conversation_id}/messages", json=body)


def test_off_external_sources_replay_versions_and_conflict(tmp_path):
    handler, calls = handler_factory()
    with make_client(tmp_path, handler) as client:
        authorize(client)
        task = create_task(client)
        configure_provider(client)
        save_tavily(client)
        conversation = start_conversation(client, task)
        off = send(client, conversation, "off")
        assert off.status_code == 202, off.text
        read_sse(client, off.json()["run"]["id"])
        assert not any(url == "https://api.tavily.com/search" for url, _ in calls)
        messages = client.get(f"/api/ai/conversations/{conversation}").json()["messages"]
        assert messages[1]["search_trace"]["status"] == "off"

        selected = {"mode": "external", "service_id": "tavily-test", "query": "focused"}
        first = send(client, conversation, "external", selected, public_search_query="focused")
        assert first.status_code == 202, first.text
        first_id = first.json()["run"]["id"]
        events = read_sse(client, first_id)
        assert events[-1][0] == "done"
        # A completed run replays its final trace in start/done; live subscribers
        # receive separate search events while the provider is still running.
        assert events[0][1]["search_trace"]["items"][0]["url"] == SEARCH_URL
        assert events[-1][1]["search_trace"]["items"][0]["url"] == SEARCH_URL
        search_calls = [payload for url, payload in calls if url == "https://api.tavily.com/search"]
        assert len(search_calls) == 1 and search_calls[0]["query"] == "focused"
        urls = [url for url, _ in calls]
        assert urls.index("https://api.tavily.com/search") > next(i for i, (url, payload) in enumerate(calls)
            if payload.get("stream") and payload.get("tools"))
        replay = next(payload for url, payload in calls if payload.get("stream") and
            any(message.get("role") == "tool" for message in payload.get("messages", [])))
        assert replay["messages"][-1]["tool_call_id"] == "search-1"
        assert SEARCH_URL in replay["messages"][-1]["content"]
        repeated = send(client, conversation, "external", selected)
        assert repeated.status_code == 202 and repeated.json()["created"] is False
        conflict = send(client, conversation, "external", {"mode": "off"})
        assert conflict.status_code == 409

        detail = client.get(f"/api/ai/conversations/{conversation}").json()
        answered = detail["messages"][-1]
        regenerated = send(client, conversation, "regenerated", {"mode": "off"}, regenerate_message_id=answered["id"])
        assert regenerated.status_code == 202, regenerated.text
        read_sse(client, regenerated.json()["run"]["id"])
        versions = client.get(f"/api/ai/conversations/{conversation}").json()["messages"]
        assert any(item.get("search_trace", {}).get("items", [{}])[0].get("url") == SEARCH_URL for item in versions if item.get("search_trace", {}).get("items"))
        assert versions[-1]["search_trace"]["status"] == "off"
        assert len([url for url, _ in calls if url == "https://api.tavily.com/search"]) == 1


def test_search_failure_still_answers_with_failed_trace(tmp_path):
    handler, calls = handler_factory(search_failure=True)
    with make_client(tmp_path, handler) as client:
        authorize(client)
        configure_provider(client)
        save_tavily(client)
        conversation = start_conversation(client, create_task(client))
        result = send(client, conversation, "failure", {"mode": "external", "service_id": "tavily-test"},
                      public_search_query="focused")
        assert result.status_code == 202, result.text
        events = read_sse(client, result.json()["run"]["id"])
        assert events[-1][0] == "done" and events[-1][1]["content"] == "Answer"
        assert events[-1][1]["search_trace"]["status"] == "failed"
        assert len([url for url, _ in calls if url == "https://api.tavily.com/search"]) == 1


def test_native_rejected_for_legacy_provider(tmp_path):
    handler, calls = handler_factory()
    with make_client(tmp_path, handler) as client:
        authorize(client)
        configure_provider(client)
        conversation = start_conversation(client, create_task(client))
        result = send(client, conversation, "unsupported", {"mode": "native"})
        assert result.status_code == 400
        assert not calls


@pytest.mark.parametrize("with_material", [False, True])
def test_native_responses_requires_real_tool_event_and_citation(tmp_path, with_material):
    invoked = []

    def handler(request):
        payload = json.loads(request.content)
        invoked.append(payload)
        if payload.get("stream"):
            assert payload.get("tools") == [{"type": "web_search"}]
            lines = [
                {"type": "response.output_item.done", "item": {"type": "web_search_call", "status": "completed"}},
                {"type": "response.output_text.delta", "delta": "Grounded answer"},
                {"type": "response.output_text.annotation.added", "annotation": {"type": "url_citation", "url": SEARCH_URL, "title": "Source"}},
                {"type": "response.completed", "response": {"output": []}},
            ]
            return httpx.Response(200, text="".join(f"data: {json.dumps(line)}\n\n" for line in lines))
        return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Title"}]}]})

    with make_client(tmp_path, handler) as client:
        authorize(client)
        provider = client.put("/api/ai/provider", json={"display_name": "Responses", "api_protocol": "openai_responses", "base_url": "https://api.example.com/v1", "model": "gpt-test", "api_key": "fake-key"})
        assert provider.status_code == 200, provider.text
        conversation = start_conversation(client, create_task(client) if with_material else None)
        extra = {}
        if with_material:
            material = client.post(f'/api/materials/conversation/{conversation}', json={
                'title': '教材', 'content': 'NATIVE-MATERIAL-TEXT'}).json()
            extra['source_scope'] = {'mode': 'reference', 'version_ids': [material['id']]}
        sent = send(client, conversation, "native", {"mode": "native"}, public_search_query="Question", **extra)
        if with_material:
            assert sent.status_code == 400, sent.text
            assert not invoked
            return
        assert sent.status_code == 202, sent.text
        events = read_sse(client, sent.json()["run"]["id"])
        trace = events[-1][1]["search_trace"]
        assert trace["status"] == "succeeded" and trace["items"][0]["url"] == SEARCH_URL
        assert events[-1][1]["content"] == "Grounded answer"
        assert any(call.get("stream") is False and "tools" not in call for call in invoked)


def test_native_without_tool_is_not_used(tmp_path):
    def handler(request):
        payload = json.loads(request.content)
        if payload.get("stream"):
            assert payload["tools"] == [{"type": "web_search"}]
            return httpx.Response(200, text="".join(
                f"data: {json.dumps(event)}\n\n" for event in [
                    {"type": "response.output_text.delta", "delta": "No search needed"},
                    {"type": "response.completed", "response": {"output": []}},
                ]))
        return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Title"}]}]})
    with make_client(tmp_path, handler) as client:
        authorize(client)
        provider = client.put("/api/ai/provider", json={"display_name": "Responses", "api_protocol": "openai_responses", "base_url": "https://api.example.com/v1", "model": "gpt-test", "api_key": "fake-key"})
        assert provider.status_code == 200
        conversation = start_conversation(client, None)
        sent = send(client, conversation, "native-unused", {"mode": "native"}, public_search_query="Question")
        assert sent.status_code == 202
        events = read_sse(client, sent.json()["run"]["id"])
        assert events[-1][1]["search_trace"]["status"] == "not_used"
        assert events[-1][1]["search_trace"]["items"] == []


@pytest.mark.parametrize("search_status", ["running", "succeeded"])
def test_restart_closes_pending_search_but_preserves_completed_sources(tmp_path, search_status):
    handler, calls = handler_factory()
    with make_client(tmp_path, handler) as client:
        authorize(client)
        configure_provider(client)
        save_tavily(client)
        conversation = start_conversation(client, create_task(client))
        service = client.app.state.conversations
        owner = client.app.state.auth.ensure_local_identity()["id"]
        prepared = service.prepare_run(owner, conversation, content="Question", client_message_id="restart",
                                       search={"mode": "external", "service_id": "tavily-test"})
        trace = {"mode": "external", "status": search_status, "items": [{"url": SEARCH_URL, "title": "Source"}]}
        service.save_search_trace(prepared["run"]["id"], trace)
        events = read_sse(client, prepared["run"]["id"])
        assert events[-1][1]["kind"] == "interrupted"
        saved = service.conversation_detail(owner, conversation)["messages"][-1]["search_trace"]
        assert saved["status"] == ("failed" if search_status == "running" else "succeeded")
        assert saved["items"] == trace["items"]
        assert events[-1][1]["search_trace"] == saved
        assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("search_status", ["running", "succeeded"])
async def test_discussion_restart_retains_sources_and_finalizes_only_pending_search(learning_database, search_status):
    from app.question_discussion import QuestionDiscussionService
    from test_verification_review import IDENTITY, attempt
    verification, current = await attempt(learning_database)
    discussion = QuestionDiscussionService(verification)
    created = discussion.create(IDENTITY, current["id"], current["latest_submission_id"], "q1", "search-restart")
    with learning_database.transaction() as connection:
        trace = {"mode": "external", "status": search_status, "items": [{"url": SEARCH_URL}]}
        connection.execute("""INSERT INTO learning_discussion_turn
            (id,discussion_id,request_key,user_content,status,created_at,provider_snapshot_json)
            VALUES (?,?,?,'Question','running','2026-09-26T00:00:00Z',?)""",
            (f"restart-{search_status}", created["id"], search_status, json.dumps({"search_trace": trace})))
    discussion.recover()
    for turn in discussion.get(IDENTITY, created["id"])["turns"]:
        assert turn["status"] == "failed" and turn["reason"] == "interrupted"
        assert turn["search_trace"]["status"] == ("failed" if turn["request_key"] == "running" else "succeeded")
        assert turn["search_trace"]["items"][0]["url"] == SEARCH_URL


def test_external_selection_is_frozen_while_settings_are_removed(tmp_path):
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def handler(request):
        url = str(request.url)
        calls.append(url)
        if url == "https://api.tavily.com/search":
            entered.set()
            await release.wait()
            return httpx.Response(200, json={"results": [{"title": "Source", "url": SEARCH_URL, "content": "Evidence"}]})
        payload = json.loads(request.content)
        if payload.get("stream") and payload.get("tools") and not any(m.get("role") == "tool" for m in payload["messages"]):
            return httpx.Response(200, text=chat_stream(search_call("Question")))
        if payload.get("stream"):
            return httpx.Response(200, text=chat_stream(answer_chunk()))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Title"}}]})

    with make_client(tmp_path, handler) as client:
        authorize(client)
        configure_provider(client)
        save_tavily(client)
        conversation = start_conversation(client, create_task(client))
        manager = client.app.state.ai_runs
        owner = client.app.state.auth.ensure_local_identity()["id"]

        async def scenario():
            started = await manager.start(owner, conversation, content="Question", client_message_id="frozen",
                                          search={"mode": "external", "service_id": "tavily-test"},
                                          public_search_query="Question")
            await asyncio.wait_for(entered.wait(), 2)
            settings = client.app.state.search.get(owner)
            client.app.state.search.save(owner, {"revision": settings["revision"], "services": [],
                                                 "selected_service_id": None, "result_size": 3,
                                                 "timeout_seconds": 5, "max_requests": 1})
            subscriber = manager.stream(owner, started["run"]["id"])
            first_frame = await anext(subscriber)
            release.set()
            remaining_frames = [frame async for frame in subscriber]
            await manager._runs[started["run"]["id"]].task
            return manager.conversations.conversation_detail(owner, conversation), first_frame + "".join(remaining_frames)

        detail, frames = asyncio.run(scenario())
        assert detail["messages"][-1]["search_trace"]["status"] == "succeeded"
        assert detail["messages"][-1]["search_trace"]["items"][0]["url"] == SEARCH_URL
        assert "event: search" in frames and SEARCH_URL in frames
        assert "event: process" in frames and '"generation_trace"' in frames
        assert calls.count("https://api.tavily.com/search") == 1


def test_cancel_during_search_does_not_accept_late_trace(tmp_path):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(request):
        if str(request.url) == "https://api.tavily.com/search":
            entered.set()
            await release.wait()
            return httpx.Response(200, json={"results": [{"title": "Secret", "url": SEARCH_URL, "content": "Private"}]})
        payload = json.loads(request.content)
        if payload.get("stream") and payload.get("tools") and not any(m.get("role") == "tool" for m in payload["messages"]):
            return httpx.Response(200, text=chat_stream(search_call("Question")))
        if payload.get("stream"):
            return httpx.Response(200, text=chat_stream(answer_chunk()))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Title"}}]})

    with make_client(tmp_path, handler) as client:
        authorize(client)
        configure_provider(client)
        save_tavily(client)
        conversation = start_conversation(client, create_task(client))
        manager = client.app.state.ai_runs
        owner = client.app.state.auth.ensure_local_identity()["id"]

        async def scenario():
            started = await manager.start(owner, conversation, content="Question", client_message_id="cancel",
                                          search={"mode": "external", "service_id": "tavily-test"},
                                          public_search_query="Question")
            await asyncio.wait_for(entered.wait(), 2)
            await manager.cancel(owner, started["run"]["id"])
            release.set()
            await asyncio.sleep(.01)
            return manager.conversations.conversation_detail(owner, conversation)

        detail = asyncio.run(scenario())
        answer = detail["messages"][-1]
        assert answer["status"] == "canceled"
        assert answer["search_trace"]["status"] == "failed"
        assert answer["search_trace"]["items"] == []


@pytest.mark.asyncio
async def test_discussion_purge_while_search_waits_cannot_resurrect_trace(learning_database):
    from app.question_discussion import QuestionDiscussionService
    from app.search_service import SearchRun
    from test_verification_review import IDENTITY, attempt

    verification, current = await attempt(learning_database)
    discussion = QuestionDiscussionService(verification)
    created = discussion.create(IDENTITY, current["id"], current["latest_submission_id"], "q1", "search-purge")
    entered = asyncio.Event()
    release = asyncio.Event()
    private = "synthetic-private-search-query"

    class HeldSearch:
        def prepare(self, owner, selection, protocol):
            assert owner == IDENTITY["id"] and protocol == "openai_compatible"
            return SearchRun(dict(selection), {"result_size": 1, "timeout_seconds": 5, "max_requests": 1},
                             {"id": "held", "kind": "tavily", "name": "Held", "options": {"api_key": "fake"}})

        def _catalog(self, kind):
            assert kind == "tavily"
            return SearchService._catalog(kind)

        _validate_parameters = staticmethod(SearchService._validate_parameters)

        async def invoke(self, run, params, *, fetch=False, before_request=None):
            assert params["query"] == private
            entered.set()
            await release.wait()
            return {"answer": None, "items": [{"title": "Private", "url": SEARCH_URL, "text": "private source"}],
                    "images": [], "retrieved_at": "2026-09-26T00:00:00Z"}

    verification.conversations.search_service = HeldSearch()

    def ai_handler(request):
        payload = json.loads(request.content)
        if payload.get("stream"):
            return httpx.Response(200, text=chat_stream(search_call(private)))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"history_query":null}'}}]})

    verification.transport = httpx.MockTransport(ai_handler)
    started = discussion.start(IDENTITY, created["id"], "Question", "turn", search={"mode": "external", "service_id": "held", "query": private})
    turn_id = started["turns"][0]["id"]
    await asyncio.wait_for(entered.wait(), 2)
    verification.purge(IDENTITY, current["id"])
    release.set()
    await discussion.tasks[turn_id]
    after = discussion.get(IDENTITY, created["id"])
    assert after["purged"] is True
    assert after["turns"][0]["status"] == "purged"
    assert after["turns"][0]["assistant_content"] is None
    assert after["turns"][0]["search_trace"] is None
    assert after["turns"][0]["generation_trace"] is None
    assert private not in json.dumps(after, ensure_ascii=False)
    stored = learning_database.fetchone("SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?", (turn_id,))
    assert private not in stored[0] and SEARCH_URL not in stored[0]


@pytest.mark.asyncio
async def test_discussion_keeps_completed_search_if_answer_stream_fails(learning_database):
    from app.question_discussion import QuestionDiscussionService
    from app.search_service import SearchRun
    from test_verification_review import IDENTITY, attempt

    verification, current = await attempt(learning_database)
    discussion = QuestionDiscussionService(verification)
    created = discussion.create(IDENTITY, current["id"], current["latest_submission_id"], "q1", "search-then-fail")

    class CompletedSearch:
        def prepare(self, owner, selection, protocol):
            return SearchRun(dict(selection), {"result_size": 1, "timeout_seconds": 5, "max_requests": 1},
                             {"id": "mock", "kind": "tavily", "name": "Mock search", "options": {"api_key": "fake"}})

        def _catalog(self, kind):
            return SearchService._catalog(kind)

        _validate_parameters = staticmethod(SearchService._validate_parameters)

        async def invoke(self, run, params, *, fetch=False, before_request=None):
            return {"answer": None, "items": [{"title": "Source", "url": SEARCH_URL, "text": "Verified evidence"}],
                    "images": [], "retrieved_at": "2026-09-26T00:00:00Z"}

    verification.conversations.search_service = CompletedSearch()

    def ai_handler(request):
        payload = json.loads(request.content)
        if payload.get("stream"):
            if any(m.get("role") == "tool" for m in payload["messages"]):
                return httpx.Response(503, json={"error": {"message": "Synthetic model failure"}})
            return httpx.Response(200, text=chat_stream(search_call("focused")))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"history_query":null}'}}]})

    verification.transport = httpx.MockTransport(ai_handler)
    final = await discussion.send(IDENTITY, created["id"], "Question", "turn",
                                  search={"mode": "external", "service_id": "mock", "query": "focused"})
    turn = final["turns"][0]
    assert turn["status"] == "failed"
    assert turn["search_trace"]["status"] == "succeeded"
    assert turn["search_trace"]["items"][0]["url"] == SEARCH_URL
    assert turn["generation_trace"]["status"] == "failed"
    assert [part["type"] for part in turn["generation_trace"]["parts"]] == ["tool"]
    assert turn["generation_trace"]["parts"][0]["status"] == "succeeded"
    replay = discussion.turn_snapshot(IDENTITY, created["id"], turn["id"])["turn"]
    assert replay["search_trace"] == turn["search_trace"]
    assert replay["generation_trace"] == turn["generation_trace"]


@pytest.mark.asyncio
async def test_discussion_cancel_while_search_waits_finalizes_trace(learning_database):
    from app.question_discussion import QuestionDiscussionService
    from app.search_service import SearchRun
    from test_verification_review import IDENTITY, attempt

    verification, current = await attempt(learning_database)
    discussion = QuestionDiscussionService(verification)
    created = discussion.create(IDENTITY, current["id"], current["latest_submission_id"], "q1", "search-cancel")
    entered = asyncio.Event()
    release = asyncio.Event()

    class HeldSearch:
        def prepare(self, owner, selection, protocol):
            return SearchRun(dict(selection), {"result_size": 1, "timeout_seconds": 5, "max_requests": 1},
                             {"id": "mock", "kind": "tavily", "name": "Mock search", "options": {"api_key": "fake"}})

        def _catalog(self, kind):
            return SearchService._catalog(kind)

        _validate_parameters = staticmethod(SearchService._validate_parameters)

        async def invoke(self, run, params, *, fetch=False, before_request=None):
            entered.set()
            await release.wait()
            return {"answer": None, "items": [{"title": "Late", "url": SEARCH_URL, "text": "late private"}],
                    "images": [], "retrieved_at": "2026-09-26T00:00:00Z"}

    verification.conversations.search_service = HeldSearch()

    def ai_handler(request):
        payload = json.loads(request.content)
        if payload.get("stream"):
            return httpx.Response(200, text=chat_stream(search_call("focused")))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"history_query":null}'}}]})

    verification.transport = httpx.MockTransport(ai_handler)
    started = discussion.start(IDENTITY, created["id"], "Question", "turn",
                               search={"mode": "external", "service_id": "mock", "query": "focused"})
    turn_id = started["turns"][0]["id"]
    await asyncio.wait_for(entered.wait(), 2)
    cancelled = await discussion.cancel(IDENTITY, created["id"], turn_id)
    release.set()
    await asyncio.sleep(.01)
    turn = cancelled["turns"][0]
    assert turn["reason"] == "cancelled"
    assert turn["search_trace"]["status"] == "failed"
    assert "取消" in turn["search_trace"]["message"]
    assert turn["generation_trace"]["status"] == "canceled"
    assert [part["type"] for part in turn["generation_trace"]["parts"]] == ["tool"]
    assert turn["generation_trace"]["parts"][0]["status"] == "canceled"
    replay = discussion.turn_snapshot(IDENTITY, created["id"], turn_id)["turn"]
    assert replay["search_trace"] == turn["search_trace"]
    assert replay["generation_trace"] == turn["generation_trace"]
    assert SEARCH_URL not in json.dumps(replay, ensure_ascii=False)
