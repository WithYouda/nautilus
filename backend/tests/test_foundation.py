def test_health_check(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "ok"


def test_local_identity_is_created_and_protected(client):
    status_response = client.get("/api/auth/status")
    assert status_response.status_code == 200
    assert status_response.json() == {"authenticated": False, "identity": None}

    me_response = client.get("/api/me")
    assert me_response.status_code == 401
    assert me_response.json()["detail"] == "需要先完成本地授权"


def test_authorization_issues_cookie_without_returning_session_token(client):
    token_path = client.app.state.settings.runtime_token_path
    assert client.get("/api/auth/challenge").status_code == 404
    assert token_path.parent.stat().st_mode & 0o777 == 0o700
    assert token_path.stat().st_mode & 0o777 == 0o600
    local_token = token_path.read_text(encoding="utf-8")

    invalid = client.post(
        "/api/auth/authorize",
        json={"access_token": "wrong-token"},
    )
    assert invalid.status_code == 401

    authorized = client.post(
        "/api/auth/authorize",
        json={"access_token": local_token},
    )
    assert authorized.status_code == 200
    body = authorized.json()
    assert body["authenticated"] is True
    assert "session" not in body
    assert "access_token" not in body
    assert "httponly" in authorized.headers.get("set-cookie", "").lower()
    assert "samesite=strict" in authorized.headers.get("set-cookie", "").lower()
    assert "max-age=315360000" in authorized.headers.get("set-cookie", "").lower()

    with client.app.state.database.transaction() as connection:
        connection.execute(
            "UPDATE sessions SET expires_at = ?",
            ("2000-01-01T00:00:00Z",),
        )

    me_response = client.get("/api/me")
    assert me_response.status_code == 200
    assert me_response.json()["display_name"] == "本地学习者"

    logged_out = client.post("/api/auth/logout")
    assert logged_out.status_code == 200
    assert client.get("/api/me").status_code == 401


def test_restart_rotates_local_code_and_preserves_existing_cookie(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from conftest import build_settings

    settings = build_settings(tmp_path)
    with TestClient(create_app(settings)) as first:
        old_code = settings.runtime_token_path.read_text(encoding="utf-8")
        assert first.post("/api/auth/authorize", json={"access_token": old_code}).status_code == 200
        session_cookie = first.cookies.get(settings.cookie_name)
        assert session_cookie

    with TestClient(create_app(settings)) as restarted:
        new_code = settings.runtime_token_path.read_text(encoding="utf-8")
        assert new_code != old_code
        assert restarted.post("/api/auth/authorize", json={"access_token": old_code}).status_code == 401
        restarted.cookies.set(settings.cookie_name, session_cookie)
        assert restarted.get("/api/me").status_code == 200
        assert restarted.post("/api/auth/authorize", json={"access_token": new_code}).status_code == 200


def test_database_uses_wal_and_foreign_keys(client):
    database = client.app.state.database
    journal_mode = database.fetchone("PRAGMA journal_mode")[0]
    foreign_keys = database.fetchone("PRAGMA foreign_keys")[0]
    migrations = database.fetchall(
        "SELECT version FROM schema_migrations ORDER BY version"
    )

    assert journal_mode.lower() == "wal"
    assert foreign_keys == 1
    assert [row["version"] for row in migrations] == [
        "001_initial",
        "002_learning_plans",
        "003_dashboard_layouts",
        "004_plan_editor",
        "005_ai_conversations",
        "006_ai_message_reasoning",
            "007_ai_multi_provider_model_selection",
            "008_ai_conversation_titles",
            "009_task_completion_restore",
            "010_ai_conversation_scope",
        ]
