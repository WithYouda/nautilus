from datetime import date, datetime, timedelta, timezone


def authorize(client):
    token = client.app.state.auth.runtime_access_token
    response = client.post("/api/auth/authorize", json={"access_token": token})
    assert response.status_code == 200


def plan_payload() -> dict:
    today = date.today()
    return {
        "goal_title": "完成线性代数第一轮复习",
        "description": "建立矩阵、向量空间和特征值的知识框架",
        "start_date": today.isoformat(),
        "end_date": (today + timedelta(days=30)).isoformat(),
        "subject_title": "数学",
        "topic_title": "线性代数",
        "task_title": "复习矩阵乘法并完成例题",
        "task_type": "review",
        "schedule_mode": "flexible",
        "task_start_date": today.isoformat(),
        "task_due_date": today.isoformat(),
        "estimate_minutes": 50,
        "timer_mode": "pomodoro_50_10",
        "work_minutes": 50,
        "break_minutes": 10,
    }


def task_payload(title: str = "新增任务") -> dict:
    today = date.today().isoformat()
    return {
        "title": title,
        "task_type": "study",
        "schedule_mode": "flexible",
        "start_date": today,
        "due_date": today,
        "estimate_minutes": 40,
        "timer_mode": "pomodoro_25_5",
        "work_minutes": 25,
        "break_minutes": 5,
    }


def test_manual_plan_creates_four_level_tree_and_today_dashboard(client):
    authorize(client)

    created = client.post("/api/plans/manual", json=plan_payload())
    assert created.status_code == 201
    plan = created.json()
    task = plan["subjects"][0]["topics"][0]["tasks"][0]
    assert plan["title"] == "完成线性代数第一轮复习"
    assert plan["subjects"][0]["title"] == "数学"
    assert plan["subjects"][0]["topics"][0]["title"] == "线性代数"
    assert task["task_type"] == "review"

    dashboard = client.get("/api/dashboard/today")
    assert dashboard.status_code == 200
    assert dashboard.json()["summary"]["total"] == 1
    assert dashboard.json()["tasks"][0]["id"] == task["id"]


def test_plan_write_requires_authorization_and_valid_date_range(client):
    payload = plan_payload()
    assert client.post("/api/plans/manual", json=payload).status_code == 401

    authorize(client)
    payload["end_date"] = (date.today() - timedelta(days=1)).isoformat()
    response = client.post("/api/plans/manual", json=payload)
    assert response.status_code == 400
    assert "结束日期" in response.json()["detail"]


def test_timer_state_machine_and_one_click_completion(client):
    authorize(client)
    plan = client.post("/api/plans/manual", json=plan_payload()).json()
    task_id = plan["subjects"][0]["topics"][0]["tasks"][0]["id"]

    started = client.post(
        f"/api/tasks/{task_id}/timer",
        json={"action": "start", "timer_mode": "count_up"},
    )
    assert started.status_code == 200
    assert started.json()["status"] == "running"

    with client.websocket_connect(f"/api/ws/timers/{task_id}") as websocket:
        snapshot = websocket.receive_json()
        assert snapshot["task_id"] == task_id
        assert snapshot["status"] == "running"
        assert snapshot["phase"] == "focus"

    paused = client.post(f"/api/tasks/{task_id}/timer", json={"action": "pause"})
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    resumed = client.post(f"/api/tasks/{task_id}/timer", json={"action": "resume"})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "running"

    completed = client.post(f"/api/tasks/{task_id}/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["progress"] == 100
    assert client.get("/api/dashboard/today").json()["summary"]["completed"] == 1


def test_task_completion_can_be_reversed_without_losing_progress_or_history(client):
    authorize(client)
    plan = client.post("/api/plans/manual", json=plan_payload()).json()
    task_id = plan["subjects"][0]["topics"][0]["tasks"][0]["id"]
    client.app.state.database.connection.execute(
        "UPDATE task SET status = 'in_progress', progress = 61, actual_minutes = 18 WHERE id = ?",
        (task_id,),
    )

    completed = client.put(f"/api/tasks/{task_id}/completion", json={"completed": True})
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["progress"] == 100

    repeated = client.put(f"/api/tasks/{task_id}/completion", json={"completed": True})
    assert repeated.status_code == 200

    restored = client.put(f"/api/tasks/{task_id}/completion", json={"completed": False})
    assert restored.status_code == 200
    assert restored.json()["status"] == "in_progress"
    assert restored.json()["progress"] == 61
    assert restored.json()["actual_minutes"] == 18
    assert restored.json()["completed_at"] is None
    assert client.app.state.database.fetchone(
        "SELECT id FROM study_session WHERE task_id = ? AND status IN ('running', 'paused')",
        (task_id,),
    ) is None


def test_task_completion_undo_keeps_completed_timer_history(client):
    authorize(client)
    plan = client.post("/api/plans/manual", json=plan_payload()).json()
    task_id = plan["subjects"][0]["topics"][0]["tasks"][0]["id"]
    assert client.post(
        f"/api/tasks/{task_id}/timer",
        json={"action": "start", "timer_mode": "count_up"},
    ).status_code == 200

    assert client.put(f"/api/tasks/{task_id}/completion", json={"completed": True}).status_code == 200
    session = client.app.state.database.fetchone(
        "SELECT status FROM study_session WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
        (task_id,),
    )
    assert session["status"] == "completed"

    restored = client.put(f"/api/tasks/{task_id}/completion", json={"completed": False})
    assert restored.status_code == 200
    assert restored.json()["status"] == "in_progress"
    session_after = client.app.state.database.fetchone(
        "SELECT status FROM study_session WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
        (task_id,),
    )
    assert session_after["status"] == "completed"


def test_legacy_completed_task_undo_uses_explicit_fallback(client):
    authorize(client)
    plan = client.post("/api/plans/manual", json=plan_payload()).json()
    task_id = plan["subjects"][0]["topics"][0]["tasks"][0]["id"]
    client.app.state.database.connection.execute(
        """
        UPDATE task
        SET status = 'completed', progress = 100, completed_at = ?,
            completion_restore_status = NULL, completion_restore_progress = NULL
        WHERE id = ?
        """,
        (datetime.now(timezone.utc).isoformat(), task_id),
    )

    restored = client.put(f"/api/tasks/{task_id}/completion", json={"completed": False})
    assert restored.status_code == 200
    assert restored.json()["status"] == "pending"
    assert restored.json()["progress"] == 0


def test_plan_summary_detail_and_schedule_use_stable_server_read_models(client):
    authorize(client)
    payload = plan_payload()
    payload["start_date"] = (date.today() - timedelta(days=3)).isoformat()
    payload["end_date"] = (date.today() + timedelta(days=30)).isoformat()
    payload["task_start_date"] = (date.today() - timedelta(days=2)).isoformat()
    payload["task_due_date"] = (date.today() - timedelta(days=1)).isoformat()
    payload["task_title"] = "已经逾期的任务"
    plan = client.post("/api/plans/manual", json=payload).json()
    goal_id = plan["id"]
    topic_id = plan["subjects"][0]["topics"][0]["id"]
    overdue_task_id = plan["subjects"][0]["topics"][0]["tasks"][0]["id"]

    future = task_payload("未来任务")
    future["start_date"] = (date.today() + timedelta(days=2)).isoformat()
    future["due_date"] = (date.today() + timedelta(days=2)).isoformat()
    future_task = client.post(f"/api/topics/{topic_id}/tasks", json=future).json()
    completed = task_payload("已完成任务")
    completed["start_date"] = date.today().isoformat()
    completed["due_date"] = date.today().isoformat()
    completed_task = client.post(f"/api/topics/{topic_id}/tasks", json=completed).json()
    assert client.put(
        f"/api/tasks/{completed_task['id']}/completion", json={"completed": True}
    ).status_code == 200

    summaries = client.get("/api/plans/summary")
    assert summaries.status_code == 200
    summary = summaries.json()[0]
    assert summary["id"] == goal_id
    assert "subjects" not in summary
    assert summary["subject_count"] == 1
    assert summary["topic_count"] == 1
    assert summary["task_count"] == 3
    assert summary["completed_task_count"] == 1
    assert summary["progress"] == 33
    assert summary["next_task"]["id"] == overdue_task_id

    assert client.post(
        f"/api/tasks/{future_task['id']}/timer", json={"action": "start"}
    ).status_code == 200
    summary_with_timer = client.get("/api/plans/summary").json()[0]
    assert summary_with_timer["next_task"]["id"] == future_task["id"]

    detail = client.get(f"/api/plans/{goal_id}")
    assert detail.status_code == 200
    assert detail.json()["summary"]["task_count"] == 3
    assert detail.json()["subjects"][0]["progress"] == 33

    schedule = client.get(f"/api/plans/{goal_id}/schedule")
    assert schedule.status_code == 200
    assert {item["id"] for item in schedule.json()} == {
        overdue_task_id,
        future_task["id"],
        completed_task["id"],
    }
    assert all(item["goal_id"] == goal_id for item in schedule.json())


def test_only_one_timer_can_be_active_for_local_identity(client):
    authorize(client)
    first_plan = client.post("/api/plans/manual", json=plan_payload()).json()
    second_payload = plan_payload()
    second_payload["goal_title"] = "第二学习目标"
    second_payload["task_title"] = "第二项任务"
    second_plan = client.post("/api/plans/manual", json=second_payload).json()
    first_task = first_plan["subjects"][0]["topics"][0]["tasks"][0]["id"]
    second_task = second_plan["subjects"][0]["topics"][0]["tasks"][0]["id"]

    assert client.post(f"/api/tasks/{first_task}/timer", json={"action": "start"}).status_code == 200
    conflict = client.post(f"/api/tasks/{second_task}/timer", json={"action": "start"})
    assert conflict.status_code == 400
    assert "当前进行中" in conflict.json()["detail"]


def test_plan_editor_crud_reorder_and_soft_delete(client):
    authorize(client)
    plan = client.post("/api/plans/manual", json=plan_payload()).json()
    goal_id = plan["id"]
    initial_subject = plan["subjects"][0]

    updated_goal = client.patch(
        f"/api/plans/{goal_id}",
        json={"title": "线性代数系统复习", "description": "按主题持续推进"},
    )
    assert updated_goal.status_code == 200
    assert updated_goal.json()["title"] == "线性代数系统复习"

    second_subject = client.post(
        f"/api/plans/{goal_id}/subjects", json={"title": "应用数学"}
    ).json()
    third_subject = client.post(
        f"/api/plans/{goal_id}/subjects", json={"title": "数学工具"}
    ).json()
    reordered = client.put(
        f"/api/plans/{goal_id}/subjects/order",
        json={"ordered_ids": [third_subject["id"], second_subject["id"], initial_subject["id"]]},
    )
    assert reordered.status_code == 200
    assert [item["title"] for item in reordered.json()["subjects"]] == [
        "数学工具",
        "应用数学",
        "数学",
    ]

    renamed_subject = client.patch(
        f"/api/subjects/{second_subject['id']}", json={"title": "应用与建模"}
    )
    assert renamed_subject.json()["title"] == "应用与建模"

    first_topic = client.post(
        f"/api/subjects/{second_subject['id']}/topics", json={"title": "最优化"}
    ).json()
    second_topic = client.post(
        f"/api/subjects/{second_subject['id']}/topics", json={"title": "数值方法"}
    ).json()
    topic_order = client.put(
        f"/api/subjects/{second_subject['id']}/topics/order",
        json={"ordered_ids": [second_topic["id"], first_topic["id"]]},
    )
    edited_subject = next(
        item for item in topic_order.json()["subjects"] if item["id"] == second_subject["id"]
    )
    assert [item["title"] for item in edited_subject["topics"]] == ["数值方法", "最优化"]

    renamed_topic = client.patch(
        f"/api/topics/{first_topic['id']}", json={"title": "凸优化"}
    )
    assert renamed_topic.json()["title"] == "凸优化"

    first_task = client.post(
        f"/api/topics/{first_topic['id']}/tasks", json=task_payload("学习梯度下降")
    ).json()
    second_task = client.post(
        f"/api/topics/{first_topic['id']}/tasks", json=task_payload("完成最优化练习")
    ).json()
    edited_task = client.patch(
        f"/api/tasks/{first_task['id']}",
        json={"title": "推导梯度下降", "estimate_minutes": 60, "task_type": "practice"},
    )
    assert edited_task.status_code == 200
    assert edited_task.json()["title"] == "推导梯度下降"
    assert edited_task.json()["estimate_minutes"] == 60

    task_order = client.put(
        f"/api/topics/{first_topic['id']}/tasks/order",
        json={"ordered_ids": [second_task["id"], first_task["id"]]},
    )
    selected_topic = next(
        topic
        for subject in task_order.json()["subjects"]
        for topic in subject["topics"]
        if topic["id"] == first_topic["id"]
    )
    assert [item["id"] for item in selected_topic["tasks"]] == [
        second_task["id"],
        first_task["id"],
    ]

    assert client.delete(f"/api/tasks/{second_task['id']}").status_code == 204
    deleted_task = client.app.state.database.fetchone(
        "SELECT deleted_at FROM task WHERE id = ?", (second_task["id"],)
    )
    assert deleted_task["deleted_at"] is not None
    visible_plan = client.get("/api/plans").json()[0]
    assert all(
        task["id"] != second_task["id"]
        for subject in visible_plan["subjects"]
        for topic in subject["topics"]
        for task in topic["tasks"]
    )

    assert client.delete(f"/api/topics/{second_topic['id']}").status_code == 204
    assert client.delete(f"/api/subjects/{third_subject['id']}").status_code == 204


def test_plan_editor_rejects_invalid_reorder_and_active_timer_deletion(client):
    authorize(client)
    plan = client.post("/api/plans/manual", json=plan_payload()).json()
    goal_id = plan["id"]
    task_id = plan["subjects"][0]["topics"][0]["tasks"][0]["id"]

    invalid = client.put(
        f"/api/plans/{goal_id}/subjects/order",
        json={"ordered_ids": ["missing-subject"]},
    )
    assert invalid.status_code == 400
    assert "全部同级节点" in invalid.json()["detail"]

    assert client.post(f"/api/tasks/{task_id}/timer", json={"action": "start"}).status_code == 200
    blocked = client.delete(f"/api/plans/{goal_id}")
    assert blocked.status_code == 400
    assert "结束该计划分支" in blocked.json()["detail"]


def test_goal_date_update_must_cover_existing_tasks(client):
    authorize(client)
    plan = client.post("/api/plans/manual", json=plan_payload()).json()
    response = client.patch(
        f"/api/plans/{plan['id']}",
        json={"start_date": (date.today() + timedelta(days=1)).isoformat()},
    )
    assert response.status_code == 400
    assert "覆盖现有任务" in response.json()["detail"]


def test_soft_deleted_goal_is_hidden_but_retained(client):
    authorize(client)
    plan = client.post("/api/plans/manual", json=plan_payload()).json()
    assert client.delete(f"/api/plans/{plan['id']}").status_code == 204
    assert client.get("/api/plans").json() == []
    row = client.app.state.database.fetchone(
        "SELECT deleted_at FROM learning_goal WHERE id = ?", (plan["id"],)
    )
    assert row["deleted_at"] is not None


def test_task_list_filters_searches_and_date_range(client):
    authorize(client)
    first = client.post("/api/plans/manual", json=plan_payload()).json()
    second_payload = plan_payload()
    second_payload.update(
        {
            "goal_title": "英语阅读提升",
            "subject_title": "英语",
            "topic_title": "阅读理解",
            "task_title": "完成真题阅读",
            "task_type": "practice",
            "schedule_mode": "fixed",
            "task_start_date": (date.today() + timedelta(days=4)).isoformat(),
            "task_due_date": (date.today() + timedelta(days=5)).isoformat(),
        }
    )
    client.post("/api/plans/manual", json=second_payload)

    tasks = client.get("/api/tasks")
    assert tasks.status_code == 200
    assert len(tasks.json()) == 2
    assert tasks.json()[0]["id"] == first["subjects"][0]["topics"][0]["tasks"][0]["id"]

    searched = client.get("/api/tasks", params={"query": "英语", "task_type": "practice"})
    assert searched.status_code == 200
    assert [task["title"] for task in searched.json()] == ["完成真题阅读"]
    assert searched.json()[0]["goal_title"] == "英语阅读提升"

    date_filtered = client.get(
        "/api/tasks",
        params={
            "start_date": (date.today() + timedelta(days=3)).isoformat(),
            "end_date": (date.today() + timedelta(days=6)).isoformat(),
        },
    )
    assert [task["title"] for task in date_filtered.json()] == ["完成真题阅读"]

    invalid = client.get(
        "/api/tasks",
        params={"start_date": date.today().isoformat(), "end_date": (date.today() - timedelta(days=1)).isoformat()},
    )
    assert invalid.status_code == 400


def test_task_reschedule_shifts_dates_and_fixed_times_transactionally(client):
    authorize(client)
    payload = plan_payload()
    payload["end_date"] = (date.today() + timedelta(days=30)).isoformat()
    planned_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc).replace(hour=8)
    payload["planned_start"] = planned_start.isoformat().replace("+00:00", "Z")
    payload["planned_end"] = (planned_start + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    plan = client.post("/api/plans/manual", json=payload).json()
    task_id = plan["subjects"][0]["topics"][0]["tasks"][0]["id"]

    shifted = client.post(f"/api/tasks/{task_id}/reschedule", json={"days": 3})
    assert shifted.status_code == 200
    assert shifted.json()["start_date"] == (date.today() + timedelta(days=3)).isoformat()
    assert shifted.json()["due_date"] == (date.today() + timedelta(days=3)).isoformat()
    assert shifted.json()["planned_start"] == (planned_start + timedelta(days=3)).isoformat(timespec="seconds").replace("+00:00", "Z")

    rejected = client.post(f"/api/tasks/{task_id}/reschedule", json={"days": 40})
    assert rejected.status_code == 400
    assert "计划日期范围" in rejected.json()["detail"]
    unchanged = client.get("/api/tasks").json()[0]
    assert unchanged["start_date"] == (date.today() + timedelta(days=3)).isoformat()


def test_plan_migration_is_applied(client):
    migrations = client.app.state.database.fetchall(
        "SELECT version FROM schema_migrations ORDER BY version"
    )
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
