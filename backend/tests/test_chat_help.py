"""Focused checks for help facts attached to one chat reply version."""

from test_ai_conversations import (
    authorize, configure_provider, create_task, identity_id, make_client,
    read_sse, start_conversation, streaming_handler,
)


def test_help_request_replay_regeneration_and_display_version(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        configure_provider(client)
        conversation_id = start_conversation(client, create_task(client))
        url = f"/api/ai/conversations/{conversation_id}/messages"
        payload = {"content": "给个提示", "client_message_id": "help-1", "help_request": "hint"}
        first = client.post(url, json=payload).json()
        read_sse(client, first["run"]["id"])
        reply = next(m for m in client.get(f"/api/ai/conversations/{conversation_id}").json()["messages"] if m["role"] == "assistant")
        assert reply["help_record"]["request"]["kind"] == "hint"
        assert reply["help_record"]["provided"]["characters"] == len(reply["content"])
        assert reply["help_record"]["display"] is None
        assert client.post(url, json=payload).json()["created"] is False
        assert client.post(url, json={**payload, "help_request": "example"}).status_code == 409

        ack_url = f"{url}/{reply['id']}/help-display"
        acknowledged = client.post(ack_url, json={"characters": len(reply["content"])}).json()
        assert acknowledged["display"]["basis"] == "client_report"
        assert client.post(ack_url, json={"characters": len(reply["content"])}).json() == acknowledged
        assert client.post(ack_url, json={"characters": len(reply["content"]) + 1}).status_code == 400

        regenerated = client.post(url, json={"content": "给个提示", "client_message_id": "help-regen", "regenerate_message_id": reply["id"]}).json()
        assert regenerated["created"] is True
        read_sse(client, regenerated["run"]["id"])
        messages = client.get(f"/api/ai/conversations/{conversation_id}").json()["messages"]
        second = next(m for m in messages if m["role"] == "assistant" and m["id"] != reply["id"])
        assert second["help_record"]["request"]["kind"] == "hint"
        assert second["help_record"]["display"] is None


def test_failed_partial_reply_is_provided_only_when_body_exists(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        configure_provider(client)
        conversation_id = start_conversation(client, create_task(client))
        service = client.app.state.conversations
        owner = identity_id(client)
        first = service.prepare_run(owner, conversation_id, content="请提示", client_message_id="partial", help_request="hint")
        run_id = first["run"]["id"]
        service.finalize_run(run_id, "failed", content="半段提示")
        answer = next(m for m in service.list_messages(owner, conversation_id) if m["ai_run_id"] == run_id)
        assert answer["help_record"]["provided"] == {"kind": "reply_body", "characters": 4, "at": answer["updated_at"], "partial": True}
        assert service.record_help_display(owner, conversation_id, answer["id"], 4)["display"]["characters"] == 4

        empty = service.prepare_run(owner, conversation_id, content="再提示", client_message_id="empty", help_request="hint")
        service.finalize_run(empty["run"]["id"], "failed", content="")
        no_body = next(m for m in service.list_messages(owner, conversation_id) if m["ai_run_id"] == empty["run"]["id"])
        assert no_body["help_record"]["request"]["kind"] == "hint"
        assert no_body["help_record"]["provided"] is None
