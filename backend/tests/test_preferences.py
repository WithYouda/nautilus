import pytest

from app.credentials import CredentialStore
from app.preferences import PreferencesError, PreferencesService
from app.search_adapters import SearchError
from app.search_service import SearchService


def service(tmp_path):
    store = CredentialStore(tmp_path / "credentials")
    search = SearchService(store)
    return PreferencesService(store, search), store, search


def test_owner_defaults_are_private_and_persist(tmp_path):
    preferences, store, search = service(tmp_path)
    assert preferences.get("owner-a") == {"conflict_policy": "ask", "search": {"mode": "off"}, "teaching_mode": "stepwise"}
    service_id = search.get("owner-a")["selected_service_id"]
    saved = preferences.save("owner-a", {"conflict_policy": "materials", "search": {"mode": "external", "service_id": service_id}})
    assert saved == preferences.get("owner-a")
    assert preferences.get("owner-b")["search"] == {"mode": "off"}
    assert b"learning-preferences:" not in store.store_path.read_bytes()
    assert PreferencesService(store, search).get("owner-a") == saved


def test_unknown_service_and_unexpected_fields_are_rejected(tmp_path):
    preferences, _, search = service(tmp_path)
    with pytest.raises(PreferencesError):
        preferences.save("owner-a", {"conflict_policy": "ask", "search": {"mode": "external", "service_id": "missing"}})
    with pytest.raises(PreferencesError):
        preferences.save("owner-a", {"conflict_policy": "ask", "search": {"mode": "off"}, "secret": "x"})
    with pytest.raises(PreferencesError):
        preferences.save("owner-a", {"conflict_policy": "invalid", "search": {"mode": "off"}})
    service_id = search.get("owner-a")["selected_service_id"]
    with pytest.raises(SearchError):
        preferences.save("owner-a", {"conflict_policy": "ask", "search": {"mode": "external", "service_id": service_id, "parameters": {"unrecognized": "x"}}})


def test_preferences_route_requires_identity_and_saves_owner_defaults(client):
    assert client.get("/api/preferences").status_code == 401
    token = client.app.state.settings.runtime_token_path.read_text(encoding="utf-8")
    assert client.post("/api/auth/authorize", json={"access_token": token}).status_code == 200
    assert client.get("/api/preferences").json() == {"conflict_policy": "ask", "search": {"mode": "off"}, "teaching_mode": "stepwise"}
    updated = {"conflict_policy": "balanced", "search": {"mode": "native"}, "teaching_mode": "stepwise"}
    assert client.put("/api/preferences", json=updated).json() == updated
    assert client.get("/api/preferences").json() == updated
    assert client.put("/api/preferences", json={**updated, "unknown": True}).status_code == 422
