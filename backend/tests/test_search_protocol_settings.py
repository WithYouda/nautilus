"""Protocol selection is saved explicitly; testing a draft never changes it."""
import json

import httpx

from test_ai_conversations import FAKE_API_KEY, authorize, configure_provider, make_client


def test_saved_protocol_change_invalidates_old_test_and_draft_does_not(tmp_path):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        assert request.headers["Authorization"] == f"Bearer {FAKE_API_KEY}"
        body = json.loads(request.content)
        if request.url.path.endswith("/chat/completions"):
            assert body["stream"] is False
            return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})
        assert request.url.path.endswith("/responses")
        assert body["stream"] is False
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "pong"}]}
        ]})

    with make_client(tmp_path, handler) as client:
        authorize(client)
        first = configure_provider(client)
        assert first["api_protocol"] == "openai_compatible"
        assert first["config_version"] == 1

        tested = client.post("/api/ai/provider/test")
        assert tested.status_code == 200 and tested.json()["ok"] is True
        persisted = client.get("/api/ai/provider").json()["provider"]
        assert persisted["last_test_status"] == "succeeded"

        draft = client.post("/api/ai/provider/test", json={"api_protocol": "openai_responses"})
        assert draft.status_code == 200 and draft.json()["ok"] is True
        assert seen[-1].endswith("/responses")
        unchanged = client.get("/api/ai/provider").json()["provider"]
        assert unchanged["api_protocol"] == "openai_compatible"
        assert unchanged["config_version"] == persisted["config_version"]
        assert unchanged["last_test_status"] == "succeeded"

        changed = client.put("/api/ai/provider", json={
            "display_name": persisted["display_name"],
            "base_url": persisted["base_url"],
            "model": persisted["model"],
            "api_key": None,
            "api_protocol": "openai_responses",
        })
        assert changed.status_code == 200, changed.text
        updated = changed.json()["provider"]
        assert updated["api_protocol"] == "openai_responses"
        assert updated["config_version"] == persisted["config_version"] + 1
        assert updated["last_test_status"] is None
        assert updated["last_test_error"] is None
        assert updated["last_tested_at"] is None
        assert client.get("/api/ai/provider").json()["provider"]["api_protocol"] == "openai_responses"
        assert FAKE_API_KEY not in changed.text

        # Existing clients omit the new optional field. Changing the model must
        # inherit the saved API protocol, not reset it to Chat Completions.
        legacy_update = client.put("/api/ai/provider", json={
            "display_name": persisted["display_name"], "base_url": persisted["base_url"],
            "model": "another-model", "api_key": None,
        })
        assert legacy_update.status_code == 200, legacy_update.text
        assert legacy_update.json()["provider"]["api_protocol"] == "openai_responses"
