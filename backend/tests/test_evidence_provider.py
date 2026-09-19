from __future__ import annotations

import json

import httpx

import pytest
from fastapi.testclient import TestClient

from app.conversations import ConversationError
from app.main import create_app
from conftest import build_settings
from test_evidence_claims import create_standard_chain

# 测试密钥只用于本地 MockTransport，不触碰真实 AI API。
FAKE_API_KEY = "sk-test-evidence-provider"


def authorize(client: TestClient) -> dict:
    challenge = client.get("/api/auth/challenge").json()["code"]
    response = client.post("/api/auth/authorize", json={"access_token": challenge})
    assert response.status_code == 200
    return response.json()["identity"]


def make_client(tmp_path, calls: list[str]) -> TestClient:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload["model"])
        claim = {
            "dimension_id": "syntax_semantics",
            "stance": "supports",
            "statement": "语义分析确认产出说明了正则表达式的匹配语义。",
            "source": "ai_analysis",
            "verification_method": "semantic_analysis",
            "evidence_condition": "independent",
            "scope": "artifact",
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(claim, ensure_ascii=False)}}]},
        )

    return TestClient(create_app(build_settings(tmp_path), provider_transport=httpx.MockTransport(handler)))


def configure_default_provider(client: TestClient) -> dict:
    response = client.put(
        "/api/ai/provider",
        json={
            "display_name": "默认提供方",
            "base_url": "https://default.example.com/v1",
            "model": "default-model",
            "api_key": FAKE_API_KEY,
            "request_timeout_seconds": 11,
        },
    )
    assert response.status_code == 200
    return response.json()["provider"]


def create_second_provider(client: TestClient) -> dict:
    response = client.post(
        "/api/ai/providers",
        json={
            "display_name": "证据分析提供方",
            "base_url": "https://evidence.example.com/v1",
            "model": "evidence-model",
            "api_key": f"{FAKE_API_KEY}-second",
            "request_timeout_seconds": 17,
        },
    )
    assert response.status_code == 201
    return response.json()["provider"]


def test_evidence_analysis_defaults_to_chat_provider_until_selection_exists(tmp_path):
    calls: list[str] = []
    with make_client(tmp_path, calls) as client:
        identity = authorize(client)
        provider = configure_default_provider(client)

        assert client.get("/api/learning/evidence-provider").json() is None
        runtime_profile, runtime_config = client.app.state.evidence_provider.provider_runtime(identity["id"])
        assert runtime_profile["id"] == provider["id"]
        assert runtime_config.model == "default-model"
        assert runtime_config.timeout_seconds == 11

        created = create_standard_chain(client)
        response = client.post(
            f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
            json={"request_key": "default-provider-analysis"},
        )
        assert response.status_code == 200
        assert response.json()["run"]["status"] == "succeeded"
        assert calls == ["default-model"]
        assert len(response.json()["claims"]) == 2
        run = client.app.state.learning.database.fetchone(
            "SELECT * FROM learning_analysis_run WHERE id=?",
            (response.json()["run"]["id"],),
        )
        assert run["provider_selection_source"] == "default"
        assert run["provider_profile_id"] == provider["id"]
        assert run["provider_model_id"] == provider["default_model"]["id"]
        assert run["provider_model"] == "default-model"
        assert run["provider_kind"] == "openai_compatible"
        assert run["provider_config_version"] == provider["config_version"]
        assert run["provider_timeout_seconds"] == 11
        assert run["analysis_prompt_schema_version"] == 1
        assert "api_key" not in dict(run)
        assert "credential_key" not in dict(run)


def test_evidence_provider_selection_persists_and_updates(tmp_path):
    calls: list[str] = []
    with make_client(tmp_path, calls) as client:
        identity = authorize(client)
        default = configure_default_provider(client)
        second = create_second_provider(client)
        service = client.app.state.evidence_provider

        selected = client.put(
            "/api/learning/evidence-provider",
            json={
                "provider_profile_id": second["id"],
                "provider_model_id": second["default_model"]["id"],
            },
        )
        assert selected.status_code == 200
        assert selected.json()["provider_profile_id"] == second["id"]
        assert selected.json()["provider_model_id"] == second["default_model"]["id"]
        assert client.get("/api/learning/evidence-provider").json() == selected.json()

        profile, config = service.provider_runtime(identity["id"])
        assert profile["id"] == second["id"]
        assert config.model == "evidence-model"
        assert config.timeout_seconds == 17

        created = create_standard_chain(client)
        analysis = client.post(
            f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
            json={"request_key": "selected-provider-analysis"},
        )
        assert analysis.status_code == 200
        assert analysis.json()["run"]["status"] == "succeeded"
        assert calls == ["evidence-model"]
        assert len(analysis.json()["claims"]) == 2
        explicit_run = client.app.state.learning.database.fetchone(
            "SELECT * FROM learning_analysis_run WHERE id=?",
            (analysis.json()["run"]["id"],),
        )
        assert explicit_run["provider_selection_source"] == "explicit"
        assert explicit_run["provider_profile_id"] == second["id"]
        assert explicit_run["provider_model_id"] == second["default_model"]["id"]
        assert explicit_run["provider_model"] == "evidence-model"
        assert explicit_run["provider_timeout_seconds"] == 17

        ended = client.post(
            f"/api/learning/sessions/{created['session']['id']}/end",
            json={
                "disposition": "ended",
                "expected_version": 4,
                "idempotency_key": "provider-explicit-end",
            },
        )
        assert ended.status_code == 200

        updated = client.put(
            "/api/learning/evidence-provider",
            json={
                "provider_profile_id": default["id"],
                "provider_model_id": default["default_model"]["id"],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["provider_profile_id"] == default["id"]
        profile, config = service.provider_runtime(identity["id"])
        assert profile["id"] == default["id"]
        assert config.model == "default-model"

        cleared = client.delete("/api/learning/evidence-provider")
        assert cleared.status_code == 204
        assert client.get("/api/learning/evidence-provider").json() is None

        switched = create_standard_chain(client, key_prefix="provider-switched")
        switched_analysis = client.post(
            f"/api/learning/artifacts/{switched['artifact']['id']}/analysis",
            json={"request_key": "switched-provider-analysis"},
        )
        assert switched_analysis.status_code == 200
        assert switched_analysis.json()["run"]["status"] == "succeeded"
        assert calls == ["evidence-model", "default-model"]
        switched_run = client.app.state.learning.database.fetchone(
            "SELECT * FROM learning_analysis_run WHERE id=?",
            (switched_analysis.json()["run"]["id"],),
        )
        assert switched_run["provider_selection_source"] == "default"
        assert switched_run["provider_profile_id"] == default["id"]
        assert switched_run["provider_model_id"] == default["default_model"]["id"]
        assert switched_run["provider_model"] == "default-model"
        assert explicit_run["provider_profile_id"] == second["id"]
        assert explicit_run["provider_model"] == "evidence-model"

        invalid = client.put(
            "/api/learning/evidence-provider",
            json={"provider_profile_id": "not-a-provider", "provider_model_id": "not-a-model"},
        )
        assert invalid.status_code == 400
        assert client.get("/api/learning/evidence-provider").json() is None
        row = client.app.state.learning.database.fetchone(
            "SELECT COUNT(*) FROM learning_evidence_provider"
        )
        assert row[0] == 0


def test_invalid_model_is_rejected_without_persisting_selection(tmp_path):
    calls: list[str] = []
    with make_client(tmp_path, calls) as client:
        authorize(client)
        provider = configure_default_provider(client)

        response = client.put(
            "/api/learning/evidence-provider",
            json={"provider_profile_id": provider["id"], "provider_model_id": "not-a-model"},
        )
        assert response.status_code == 400
        assert client.get("/api/learning/evidence-provider").json() is None
        assert client.app.state.learning.database.fetchone(
            "SELECT COUNT(*) FROM learning_evidence_provider"
        )[0] == 0


def test_disabled_or_deleted_provider_fails_closed_without_default_fallback(tmp_path):
    calls: list[str] = []
    with make_client(tmp_path, calls) as client:
        identity = authorize(client)
        configure_default_provider(client)
        second = create_second_provider(client)
        service = client.app.state.evidence_provider

        assert client.put(
            "/api/learning/evidence-provider",
            json={
                "provider_profile_id": second["id"],
                "provider_model_id": second["default_model"]["id"],
            },
        ).status_code == 200

        disabled = client.patch(f"/api/ai/providers/{second['id']}", json={"enabled": False})
        assert disabled.status_code == 200
        with pytest.raises(ConversationError, match="已停用"):
            service.provider_runtime(identity["id"])

        created = create_standard_chain(client)
        analysis = client.post(
            f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
            json={"request_key": "disabled-provider-analysis"},
        )
        assert analysis.status_code == 200
        assert analysis.json()["run"]["status"] == "failed"
        assert analysis.json()["run"]["reason"] == "provider_unavailable"
        assert analysis.json()["claims"] == []
        assert calls == []

        enabled = client.patch(f"/api/ai/providers/{second['id']}", json={"enabled": True})
        assert enabled.status_code == 200
        profile, _ = service.provider_runtime(identity["id"])
        assert profile["id"] == second["id"]

        assert client.delete(f"/api/ai/providers/{second['id']}").status_code == 204
        with pytest.raises(ConversationError, match="提供方不存在"):
            service.provider_runtime(identity["id"])
        assert calls == []



def test_provider_selection_cannot_use_another_owner_s_provider(tmp_path):
    calls: list[str] = []
    with make_client(tmp_path, calls) as client:
        authorize(client)
        provider = configure_default_provider(client)
        learning = client.app.state.learning
        other_identity = {
            "id": "other-owner-id",
            "device_id": "other-device-id",
            "display_name": "Other learner",
            "timezone": "UTC",
            "created_at": "2026-09-09T00:00:00Z",
        }
        learning.principal(other_identity)

        with pytest.raises(ConversationError, match="提供方不存在"):
            client.app.state.evidence_provider.set_selection(
                other_identity, provider["id"], provider["default_model"]["id"]
            )

        assert learning.database.fetchone(
            "SELECT COUNT(*) FROM learning_evidence_provider WHERE owner_id=?",
            ("user:other-owner-id",),
        )[0] == 0


def test_evidence_provider_endpoints_require_authorization(client):
    assert client.get("/api/learning/evidence-provider").status_code == 401
    assert client.put(
        "/api/learning/evidence-provider",
        json={"provider_profile_id": "provider", "provider_model_id": "model"},
    ).status_code == 401
    assert client.delete("/api/learning/evidence-provider").status_code == 401


def test_provider_timeout_has_no_automatic_retry_and_manual_retry_is_idempotent(tmp_path):
    calls: list[str] = []

    def timeout_then_success(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload["model"])
        if len(calls) == 1:
            raise TimeoutError()
        claim = {
            "dimension_id": "syntax_semantics",
            "stance": "supports",
            "statement": "重试后的语义分析确认产出说明了匹配语义。",
            "source": "ai_analysis",
            "verification_method": "semantic_analysis",
            "evidence_condition": "independent",
            "scope": "artifact",
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(claim, ensure_ascii=False)}}]},
        )

    settings = build_settings(tmp_path)
    app = create_app(settings, provider_transport=httpx.MockTransport(timeout_then_success))
    with TestClient(app) as client:
        authorize(client)
        configure_default_provider(client)
        created = create_standard_chain(client, key_prefix="provider-timeout")

        first = client.post(
            f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
            json={"request_key": "provider-timeout-analysis"},
        )
        assert first.status_code == 200
        assert first.json()["run"]["status"] == "timeout"
        assert first.json()["run"]["reason"] == "analysis_timeout"
        assert first.json()["claims"] == []
        assert calls == ["default-model"]

        retried = client.post(
            f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
            json={"request_key": "provider-timeout-analysis"},
        )
        assert retried.status_code == 200
        assert retried.json()["run"]["status"] == "succeeded"
        assert retried.json()["run"]["attempt"] == 2
        assert len(retried.json()["claims"]) == 2
        assert calls == ["default-model", "default-model"]

        duplicate = client.post(
            f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
            json={"request_key": "provider-timeout-analysis"},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["created"] is False
        assert duplicate.json()["run"]["id"] == retried.json()["run"]["id"]
        assert calls == ["default-model", "default-model"]
