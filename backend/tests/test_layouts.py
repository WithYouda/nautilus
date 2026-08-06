from test_plans import authorize


def test_default_layout_and_system_templates(client):
    authorize(client)

    layout = client.get("/api/layout")
    assert layout.status_code == 200
    assert [module["id"] for module in layout.json()["modules"]] == [
        "summary",
        "tasks",
        "timer",
        "context",
    ]

    templates = client.get("/api/layout/templates")
    assert templates.status_code == 200
    assert [template["name"] for template in templates.json() if template["is_system"]] == [
        "今日学习驾驶舱",
        "专注执行",
        "路线回顾",
    ]


def test_layout_visibility_order_and_template_lifecycle(client):
    authorize(client)
    modules = [
        {"id": "tasks", "visible": True},
        {"id": "timer", "visible": True},
        {"id": "summary", "visible": False},
        {"id": "context", "visible": False},
    ]
    updated = client.put("/api/layout", json={"modules": modules})
    assert updated.status_code == 200
    assert updated.json()["modules"] == modules

    saved = client.post("/api/layout/templates", json={"name": "冲刺布局"})
    assert saved.status_code == 201
    template_id = saved.json()["id"]
    assert saved.json()["is_system"] is False

    renamed = client.patch(
        f"/api/layout/templates/{template_id}", json={"name": "冲刺执行布局"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "冲刺执行布局"

    client.put(
        "/api/layout",
        json={
            "modules": [
                {"id": "summary", "visible": True},
                {"id": "tasks", "visible": True},
                {"id": "timer", "visible": True},
                {"id": "context", "visible": True},
            ]
        },
    )
    applied = client.post(f"/api/layout/templates/{template_id}/apply")
    assert applied.status_code == 200
    assert applied.json()["modules"] == modules

    deleted = client.delete(f"/api/layout/templates/{template_id}")
    assert deleted.status_code == 204
    assert all(
        template["id"] != template_id
        for template in client.get("/api/layout/templates").json()
    )


def test_system_layout_templates_cannot_be_changed_or_deleted(client):
    authorize(client)
    rename = client.patch(
        "/api/layout/templates/system-today-cockpit",
        json={"name": "覆盖系统模板"},
    )
    assert rename.status_code == 400
    assert client.delete("/api/layout/templates/system-today-cockpit").status_code == 400
