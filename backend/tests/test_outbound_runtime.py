"""A2 request approval through synthetic app runs and mocked HTTP transports."""
import json
import time

import httpx
import pytest

from app.outbound import ApprovalError
from test_ai_conversations import authorize, configure_provider, create_task, make_client, read_sse, start_conversation
from test_search_runtime import answer_chunk, chat_stream, save_tavily, search_call


SEARCH_URL = "https://api.tavily.com/search"
PRIVATE = "synthetic private material 4821"


def _handler(query=PRIVATE, **extra):
    calls = []

    def handle(request):
        payload = json.loads(request.content) if request.content else {}
        calls.append((str(request.url), payload))
        if str(request.url) == SEARCH_URL:
            return httpx.Response(200, json={"results": [{"title": "Source", "url": "https://source.example/a",
                                                       "content": "Public source"}]})
        if payload.get("stream") and payload.get("tools"):
            if any(message.get("role") == "tool" for message in payload.get("messages", [])):
                return httpx.Response(200, text=chat_stream(answer_chunk("Finished")))
            return httpx.Response(200, text=chat_stream(search_call(query, **extra)))
        if payload.get("stream"):
            return httpx.Response(200, text=chat_stream(answer_chunk("Finished")))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Title"}}]})

    return handle, calls


def _setup(client):
    authorize(client)
    configure_provider(client)
    save_tavily(client)
    return start_conversation(client, create_task(client))


def _send(client, conversation, key, *, public_query=None):
    body = {"content": "Explain with " + PRIVATE, "client_message_id": key,
            "search": {"mode": "external", "service_id": "tavily-test", "query": PRIVATE}}
    if public_query is not None:
        body["public_search_query"] = public_query
    response = client.post(f"/api/ai/conversations/{conversation}/messages", json=body)
    assert response.status_code == 202, response.text
    return response.json()


def _pending(client, conversation):
    endpoint = f"/api/outbound/requests?kind=conversation&scope_id={conversation}"
    for _ in range(100):
        response = client.get(endpoint)
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        if items:
            return items[0]
        time.sleep(.02)
    pytest.fail("approval request did not appear")


def _decide(client, item, decision, digest=None):
    return client.post(f"/api/outbound/requests/{item['id']}/decision",
                       json={"digest": digest or item["digest"], "decision": decision})


def _search_calls(calls):
    return [payload for url, payload in calls if url == SEARCH_URL]


def test_pending_survives_refresh_then_exact_approval_is_single_use(tmp_path):
    handler, calls = _handler()
    with make_client(tmp_path, handler) as client:
        conversation = _setup(client)
        sent = _send(client, conversation, "private-approve")
        item = _pending(client, conversation)
        assert PRIVATE in item["body"]
        assert item["url"] == SEARCH_URL
        assert _search_calls(calls) == []
        refreshed = client.get(f"/api/outbound/requests?kind=conversation&scope_id={conversation}").json()["items"]
        assert refreshed == [item]
        assert _decide(client, item, "approve", digest="wrong").status_code == 409
        with pytest.raises(ApprovalError):
            client.app.state.outbound.decide("another-owner", item["id"], item["digest"], "approve")
        assert _search_calls(calls) == []
        assert _decide(client, item, "approve").json() == {"status": "approve"}
        assert _decide(client, item, "approve").status_code == 409
        read_sse(client, sent["run"]["id"])
        assert len(_search_calls(calls)) == 1
        assert _search_calls(calls)[0]["query"] == PRIVATE
        replay = _send(client, conversation, "private-approve")
        assert replay["created"] is False
        assert len(_search_calls(calls)) == 1


@pytest.mark.parametrize("decision", ["deny", "cancel"])
def test_denial_or_cancellation_never_sends_private_search(tmp_path, decision):
    handler, calls = _handler()
    with make_client(tmp_path, handler) as client:
        conversation = _setup(client)
        sent = _send(client, conversation, "private-" + decision)
        item = _pending(client, conversation)
        assert _decide(client, item, decision).status_code == 200
        events = read_sse(client, sent["run"]["id"])
        assert _search_calls(calls) == []
        assert client.get(f"/api/outbound/requests?kind=conversation&scope_id={conversation}").json()["items"] == []
        if decision == "deny":
            assert events[-1][0] == "done"
            assert sum(bool(payload.get("stream")) for _, payload in calls) >= 2
        else:
            assert events[-1][0] != "done" or events[-1][1].get("run", {}).get("status") != "succeeded"


def test_explicit_public_query_autoruns_only_exact_parameters(tmp_path):
    handler, calls = _handler("public mathematics")
    with make_client(tmp_path, handler) as client:
        conversation = _setup(client)
        body = {"content": "public mathematics", "client_message_id": "public-exact",
                "search": {"mode": "external", "service_id": "tavily-test"},
                "public_search_query": "public mathematics"}
        sent = client.post(f"/api/ai/conversations/{conversation}/messages", json=body)
        assert sent.status_code == 202, sent.text
        read_sse(client, sent.json()["run"]["id"])
        assert len(_search_calls(calls)) == 1
        assert client.get(f"/api/outbound/requests?kind=conversation&scope_id={conversation}").json()["items"] == []

    handler, calls = _handler("public mathematics", topic="news")
    with make_client(tmp_path / "extra", handler) as client:
        conversation = _setup(client)
        sent = client.post(f"/api/ai/conversations/{conversation}/messages", json=body)
        assert sent.status_code == 202, sent.text
        item = _pending(client, conversation)
        assert json.loads(item["body"])["topic"] == "news"
        assert _search_calls(calls) == []
        assert _decide(client, item, "deny").status_code == 200
        read_sse(client, sent.json()["run"]["id"])


def test_purged_material_invalidates_pending_request(tmp_path):
    handler, calls = _handler()
    with make_client(tmp_path, handler) as client:
        conversation = _setup(client)
        material = client.post(f"/api/materials/conversation/{conversation}", json={
            "title": "Synthetic material", "content": PRIVATE})
        assert material.status_code == 201, material.text
        material = material.json()
        response = client.post(f"/api/ai/conversations/{conversation}/messages", json={
            "content": "Explain this material", "client_message_id": "purge-pending",
            "source_scope": {"mode": "reference", "version_ids": [material["id"]]},
            "search": {"mode": "external", "service_id": "tavily-test"}})
        assert response.status_code == 202, response.text
        item = _pending(client, conversation)
        assert _search_calls(calls) == []
        purged = client.post(f"/api/materials/conversation/{conversation}/{material['material_id']}/purge")
        assert purged.status_code == 200, purged.text
        assert _decide(client, item, "approve").status_code == 409
        assert _search_calls(calls) == []


def test_native_private_prompt_rejected_before_provider(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, text=chat_stream(answer_chunk()))

    with make_client(tmp_path, handler) as client:
        authorize(client)
        configured = client.put("/api/ai/provider", json={"display_name": "Native fake",
            "api_protocol": "openai_responses", "base_url": "https://api.example.com/v1",
            "model": "gpt-4o", "api_key": "fake-key"})
        assert configured.status_code == 200, configured.text
        conversation = start_conversation(client, create_task(client))
        response = client.post(f"/api/ai/conversations/{conversation}/messages", json={
            "content": PRIVATE, "client_message_id": "native-private", "search": {"mode": "native"},
            "public_search_query": "public mathematics"})
        assert response.status_code == 400, response.text
        assert calls == []
