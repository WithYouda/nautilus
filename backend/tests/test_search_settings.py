"""Search settings API checks use only temporary storage and mocked service calls."""
import json

import httpx
import pytest

from app.search_catalog import SEARCH_CATALOG
from app.search_service import SearchService
from app.search_adapters import SearchError


FAKE_SECRET = "search-test-credential-123456"


def authorize(client):
    token = client.app.state.settings.runtime_token_path.read_text(encoding="utf-8")
    response = client.post("/api/auth/authorize", json={"access_token": token})
    assert response.status_code == 200


def payload(settings, services, selected=None):
    return {"revision": settings["revision"], "services": services,
            "selected_service_id": selected, "result_size": 10,
            "timeout_seconds": 30, "max_requests": 3}


def make_service(row, index):
    options = {}
    secrets = {}
    for field in row["fields"]:
        key, kind = field["key"], field["type"]
        if kind == "secret":
            secrets[key] = f"{FAKE_SECRET}-{index}-{key}"
        elif kind == "select":
            options[key] = field["options"][-1]["value"]
        elif kind == "boolean":
            options[key] = not field["default"]
        elif kind == "number":
            options[key] = 17
        elif key in {"url", "search_url", "scrape_url", "custom_url"}:
            options[key] = f"https://example.com/{index}/{key}"
        else:
            options[key] = f"test-{index}-{key}"
    return {"id": f"service_{index}", "kind": row["kind"], "name": f"Configured {row['label']}",
            "options": options, "secret_updates": secrets}, secrets


def test_catalog_all_19_service_fields_save_read_and_encrypt(client):
    authorize(client)
    catalog = client.get("/api/search/catalog")
    assert catalog.status_code == 200
    rows = catalog.json()
    assert [row["kind"] for row in rows] == [row["kind"] for row in SEARCH_CATALOG]
    assert len(rows) == 19
    assert all(row["search_parameters"]["required"] == ["query"] for row in rows)
    assert all(all(field["type"] == "secret" for field in row["fields"] if field["key"] in {"api_key", "password"}) for row in rows)

    initial = client.get("/api/search/settings").json()
    services_and_secrets = [make_service(row, index) for index, row in enumerate(rows)]
    services = [part[0] for part in services_and_secrets]
    saved_response = client.put("/api/search/settings", json=payload(initial, services, services[3]["id"]))
    assert saved_response.status_code == 200, saved_response.text
    saved = saved_response.json()
    assert saved["revision"] == 1
    assert len(saved["services"]) == 19
    assert saved["selected_service_id"] == services[3]["id"]
    assert saved == client.get("/api/search/settings").json()

    for submitted, secret_values, returned in zip(services, [part[1] for part in services_and_secrets], saved["services"]):
        assert returned["id"] == submitted["id"]
        assert returned["kind"] == submitted["kind"]
        assert returned["options"] == submitted["options"]
        assert "secret_updates" not in returned and "secrets" not in returned
        assert returned["has_secrets"] == {key: True for key in secret_values}
        assert all(value not in saved_response.text for value in secret_values.values())

    store = client.app.state.credentials
    blob = store.store_path.read_bytes()
    assert FAKE_SECRET.encode() not in blob
    assert b"search-settings:" not in blob
    assert "search-settings:" not in str(client.app.state.database.fetchall("SELECT name FROM sqlite_master WHERE type='table'"))
    identity_id = client.app.state.auth.ensure_local_identity()["id"]
    decrypted = json.loads(store.get(f"search-settings:{identity_id}"))
    assert decrypted["services"][1]["secrets"]["api_key"].startswith(FAKE_SECRET)


def test_secret_keep_clear_and_api_errors_never_echo_content(client):
    authorize(client)
    original = client.get("/api/search/settings").json()
    service = {"id": "tavily_one", "kind": "tavily", "options": {"depth": "basic"},
               "secret_updates": {"api_key": FAKE_SECRET}}
    saved = client.put("/api/search/settings", json=payload(original, [service], service["id"])).json()
    assert saved["services"][0]["has_secrets"] == {"api_key": True}

    unchanged = {"id": service["id"], "kind": "tavily", "options": {"depth": "advanced"},
                 "secret_updates": {"api_key": ""}}
    retained = client.put("/api/search/settings", json=payload(saved, [unchanged], service["id"]))
    assert retained.status_code == 200
    assert retained.json()["services"][0]["has_secrets"]["api_key"] is True

    leaked_option = {**unchanged, "options": {"depth": "basic", "api_key": FAKE_SECRET}}
    bad = client.put("/api/search/settings", json=payload(retained.json(), [leaked_option], service["id"]))
    assert bad.status_code == 400
    assert FAKE_SECRET not in bad.text
    malformed = client.put("/api/search/settings", content=("{" + FAKE_SECRET).encode(), headers={"content-type": "application/json"})
    assert malformed.status_code == 422
    assert FAKE_SECRET not in malformed.text

    cleared = {**unchanged, "secret_updates": {"api_key": None}}
    result = client.put("/api/search/settings", json=payload(retained.json(), [cleared], service["id"]))
    assert result.status_code == 200
    assert result.json()["services"][0]["has_secrets"] == {}
    assert FAKE_SECRET not in result.text


def test_searxng_password_is_secret_and_can_be_cleared(client):
    authorize(client)
    initial = client.get("/api/search/settings").json()
    instance = {"id": "searxng_one", "kind": "searxng", "options": {"url": "https://example.com", "username": "reader"},
                "secret_updates": {"password": FAKE_SECRET}}
    saved = client.put("/api/search/settings", json=payload(initial, [instance], instance["id"]))
    assert saved.status_code == 200
    assert saved.json()["services"][0]["has_secrets"] == {"password": True}
    assert FAKE_SECRET not in saved.text

    retained = client.put("/api/search/settings", json=payload(saved.json(), [
        {"id": instance["id"], "kind": "searxng", "options": instance["options"]}], instance["id"]))
    assert retained.status_code == 200
    assert retained.json()["services"][0]["has_secrets"] == {"password": True}

    cleared = client.put("/api/search/settings", json=payload(retained.json(), [
        {**instance, "secret_updates": {"password": None}}], instance["id"]))
    assert cleared.status_code == 200
    assert cleared.json()["services"][0]["has_secrets"] == {}


def test_owner_isolation_and_revision_conflicts(client):
    authorize(client)
    search_service = client.app.state.search
    first_owner = client.app.state.auth.ensure_local_identity()["id"]
    second_owner = "other-owner"
    initial_a = search_service.get(first_owner)
    initial_b = search_service.get(second_owner)
    assert initial_a["services"][0]["id"] != initial_b["services"][0]["id"]

    service = {"id": "private_exa", "kind": "exa", "options": {}, "secret_updates": {"api_key": FAKE_SECRET}}
    saved = search_service.save(first_owner, payload(initial_a, [service], service["id"]))
    assert search_service.get(second_owner) == initial_b
    with pytest.raises(SearchError) as missing:
        search_service.prepare(second_owner, {"mode": "external", "service_id": service["id"]})
    assert missing.value.kind == "service_unavailable"

    conflict = client.put("/api/search/settings", json=payload(initial_a, [service], service["id"]))
    assert conflict.status_code == 409
    assert FAKE_SECRET not in conflict.text
    assert search_service.get(first_owner) == saved


def test_stable_id_reorder_delete_and_duplicate_rejection(client):
    authorize(client)
    initial = client.get("/api/search/settings").json()
    bing = {"id": "bing_1", "kind": "bing", "options": {}}
    brave = {"id": "brave_1", "kind": "brave", "options": {}, "secret_updates": {"api_key": FAKE_SECRET}}
    saved = client.put("/api/search/settings", json=payload(initial, [bing, brave], brave["id"]))
    assert saved.status_code == 200
    selected = saved.json()["selected_service_id"]

    reordered = client.put("/api/search/settings", json=payload(saved.json(), [brave, bing], selected))
    assert reordered.status_code == 200
    assert reordered.json()["selected_service_id"] == brave["id"]
    assert client.app.state.search.prepare(client.app.state.auth.ensure_local_identity()["id"], {"mode": "external"}).service["kind"] == "brave"

    duplicate = client.put("/api/search/settings", json=payload(reordered.json(), [brave, brave], selected))
    assert duplicate.status_code == 400
    assert "重复" in duplicate.json()["detail"]
    missing_selected = client.put("/api/search/settings", json=payload(reordered.json(), [bing], selected))
    assert missing_selected.status_code == 400
    assert client.get("/api/search/settings").json() == reordered.json()

    deleted = client.put("/api/search/settings", json=payload(reordered.json(), [bing], None))
    assert deleted.status_code == 200
    with pytest.raises(SearchError) as no_selected:
        client.app.state.search.prepare(client.app.state.auth.ensure_local_identity()["id"], {"mode": "external"})
    assert no_selected.value.kind == "service_unavailable"
    with pytest.raises(SearchError) as unavailable:
        client.app.state.search.prepare(client.app.state.auth.ensure_local_identity()["id"], {"mode": "external", "service_id": brave["id"]})
    assert unavailable.value.kind == "service_unavailable"


def test_unsaved_test_reuses_owner_secret_without_persisting_changes(client):
    authorize(client)
    initial = client.get("/api/search/settings").json()
    saved_service = {"id": "tavily_test", "kind": "tavily", "options": {"depth": "basic"},
                     "secret_updates": {"api_key": FAKE_SECRET}}
    saved = client.put("/api/search/settings", json=payload(initial, [saved_service], saved_service["id"]))
    assert saved.status_code == 200
    before = client.get("/api/search/settings").json()
    encrypted_before = client.app.state.credentials.store_path.read_bytes()
    seen = []

    def handler(request):
        seen.append(request)
        assert request.headers["Authorization"] == f"Bearer {FAKE_SECRET}"
        assert json.loads(request.content)["search_depth"] == "advanced"
        return httpx.Response(200, json={"results": [{"title": "A", "url": "https://example.com/a", "content": "T"}]})

    client.app.state.search.transport = httpx.MockTransport(handler)
    draft = {"id": saved_service["id"], "kind": "tavily", "options": {"depth": "advanced"}}
    tested = client.post("/api/search/test", json={"service": draft, "query": "test query"})
    assert tested.status_code == 200, tested.text
    assert tested.json()["ok"] is True
    assert len(seen) == 1
    assert client.get("/api/search/settings").json() == before
    assert client.app.state.credentials.store_path.read_bytes() == encrypted_before

    client.app.state.search.transport = httpx.MockTransport(lambda request: httpx.Response(401, text=f"{FAKE_SECRET} test query"))
    failure = client.post("/api/search/test", json={"service": draft, "query": "test query"})
    assert failure.status_code == 200 and failure.json()["ok"] is False
    assert FAKE_SECRET not in failure.text and "test query" not in failure.text
    assert client.get("/api/search/settings").json() == before
    assert client.app.state.credentials.store_path.read_bytes() == encrypted_before


def test_prepare_rejects_unknown_or_invalid_advanced_parameters_without_echo(client):
    authorize(client)
    owner = client.app.state.auth.ensure_local_identity()["id"]
    current = client.get("/api/search/settings").json()
    exa = {"id": "exa_contract", "kind": "exa", "options": {},
           "secret_updates": {"api_key": FAKE_SECRET}}
    saved = client.put("/api/search/settings", json=payload(current, [exa], exa["id"]))
    assert saved.status_code == 200
    service = client.app.state.search

    invalid = [
        {"mode": "external", "service_id": exa["id"], "hidden": FAKE_SECRET},
        {"mode": "external", "service_id": exa["id"], "parameters": {"hidden": FAKE_SECRET}},
        {"mode": "external", "service_id": exa["id"], "parameters": {"includeDomains": FAKE_SECRET}},
        {"mode": "external", "service_id": exa["id"], "parameters": {"includeDomains": [1]}},
        {"mode": "external", "service_id": exa["id"], "parameters": {"type": FAKE_SECRET}},
        {"mode": "external", "service_id": exa["id"], "parameters": {"maxAgeHours": True}},
        {"mode": "external", "service_id": exa["id"], "parameters": {"maxAgeHours": 721}},
    ]
    for selection in invalid:
        with pytest.raises(SearchError) as caught:
            service.prepare(owner, selection)
        assert caught.value.kind == "invalid_settings"
        assert FAKE_SECRET not in str(caught.value)

    valid = service.prepare(owner, {"mode": "external", "service_id": exa["id"],
                                    "parameters": {"type": "deep", "includeDomains": ["example.com"], "maxAgeHours": 24}})
    assert valid.service["kind"] == "exa"
