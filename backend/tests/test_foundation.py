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
    auth = client.app.state.auth

    challenge = client.get("/api/auth/challenge")
    assert challenge.status_code == 200
    assert challenge.json() == {"code": auth.runtime_access_token}
    assert "no-store" in challenge.headers.get("cache-control", "")

    invalid = client.post(
        "/api/auth/authorize",
        json={"access_token": "wrong-token"},
    )
    assert invalid.status_code == 401

    authorized = client.post(
        "/api/auth/authorize",
        json={"access_token": auth.runtime_access_token},
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
