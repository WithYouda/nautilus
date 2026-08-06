from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .auth import utc_now, utc_string
from .db import Database
from .plans import PlanError, PlanService


def _id() -> str:
    return str(uuid.uuid4())


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class PlanEditorService:
    """Transactional write boundary for the four-level plan editor."""

    def __init__(self, database: Database, plans: PlanService) -> None:
        self.database = database
        self.plans = plans

    def update_goal(self, identity_id: str, goal_id: str, data: dict[str, Any]) -> dict[str, Any]:
        goal = self._owned_goal(identity_id, goal_id)
        if not data:
            return self.plans.get_plan(identity_id, goal_id)
        merged = {**goal, **data}
        if merged["start_date"] > merged["end_date"]:
            raise PlanError("计划结束日期不能早于开始日期")
        task_bounds = self.database.fetchone(
            """
            SELECT MIN(t.start_date) AS min_start, MAX(t.due_date) AS max_due
            FROM task AS t
            JOIN topic AS p ON p.id = t.topic_id AND p.deleted_at IS NULL
            JOIN subject AS s ON s.id = p.subject_id AND s.deleted_at IS NULL
            WHERE s.goal_id = ? AND t.deleted_at IS NULL
            """,
            (goal_id,),
        )
        if task_bounds and task_bounds["min_start"]:
            if task_bounds["min_start"] < merged["start_date"] or task_bounds["max_due"] > merged["end_date"]:
                raise PlanError("计划日期范围必须覆盖现有任务")
        allowed = {"title", "description", "start_date", "end_date", "status"}
        self._update_row("learning_goal", goal_id, {key: value for key, value in data.items() if key in allowed})
        return self.plans.get_plan(identity_id, goal_id)

    def create_subject(self, identity_id: str, goal_id: str, title: str) -> dict[str, Any]:
        self._owned_goal(identity_id, goal_id)
        subject_id = _id()
        now = utc_string(utc_now())
        position = self._next_position("subject", "goal_id", goal_id)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO subject(id, goal_id, title, position, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (subject_id, goal_id, title, position, now, now),
            )
        return self._owned_subject(identity_id, subject_id)

    def update_subject(self, identity_id: str, subject_id: str, title: str) -> dict[str, Any]:
        self._owned_subject(identity_id, subject_id)
        self._update_row("subject", subject_id, {"title": title})
        return self._owned_subject(identity_id, subject_id)

    def reorder_subjects(self, identity_id: str, goal_id: str, ordered_ids: list[str]) -> dict[str, Any]:
        self._owned_goal(identity_id, goal_id)
        self._reorder("subject", "goal_id", goal_id, ordered_ids)
        return self.plans.get_plan(identity_id, goal_id)

    def delete_goal(self, identity_id: str, goal_id: str) -> None:
        self._owned_goal(identity_id, goal_id)
        self._assert_no_active_timer("goal", goal_id)
        self._soft_delete("learning_goal", goal_id)

    def delete_subject(self, identity_id: str, subject_id: str) -> None:
        self._owned_subject(identity_id, subject_id)
        self._assert_no_active_timer("subject", subject_id)
        self._soft_delete("subject", subject_id)

    def create_topic(self, identity_id: str, subject_id: str, title: str) -> dict[str, Any]:
        self._owned_subject(identity_id, subject_id)
        topic_id = _id()
        now = utc_string(utc_now())
        position = self._next_position("topic", "subject_id", subject_id)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO topic(id, subject_id, title, position, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (topic_id, subject_id, title, position, now, now),
            )
        return self._owned_topic(identity_id, topic_id)

    def update_topic(self, identity_id: str, topic_id: str, title: str) -> dict[str, Any]:
        self._owned_topic(identity_id, topic_id)
        self._update_row("topic", topic_id, {"title": title})
        return self._owned_topic(identity_id, topic_id)

    def reorder_topics(self, identity_id: str, subject_id: str, ordered_ids: list[str]) -> dict[str, Any]:
        subject = self._owned_subject(identity_id, subject_id)
        self._reorder("topic", "subject_id", subject_id, ordered_ids)
        return self.plans.get_plan(identity_id, subject["goal_id"])

    def delete_topic(self, identity_id: str, topic_id: str) -> None:
        self._owned_topic(identity_id, topic_id)
        self._assert_no_active_timer("topic", topic_id)
        self._soft_delete("topic", topic_id)

    def create_task(self, identity_id: str, topic_id: str, data: dict[str, Any]) -> dict[str, Any]:
        self._owned_topic(identity_id, topic_id)
        self._validate_task_data(identity_id, topic_id, data)
        task_id = _id()
        now = utc_string(utc_now())
        position = self._next_position("task", "topic_id", topic_id)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO task(
                    id, topic_id, title, task_type, schedule_mode, start_date, due_date,
                    planned_start, planned_end, estimate_minutes, timer_mode, work_minutes,
                    break_minutes, position, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    topic_id,
                    data["title"],
                    data["task_type"],
                    data["schedule_mode"],
                    data["start_date"],
                    data["due_date"],
                    data.get("planned_start"),
                    data.get("planned_end"),
                    data["estimate_minutes"],
                    data["timer_mode"],
                    data["work_minutes"],
                    data["break_minutes"],
                    position,
                    now,
                    now,
                ),
            )
        return self.plans.owned_task(identity_id, task_id)

    def update_task(self, identity_id: str, task_id: str, data: dict[str, Any]) -> dict[str, Any]:
        task = self.plans.owned_task(identity_id, task_id)
        if not data:
            return task
        allowed = {
            "title",
            "task_type",
            "schedule_mode",
            "start_date",
            "due_date",
            "planned_start",
            "planned_end",
            "estimate_minutes",
            "timer_mode",
            "work_minutes",
            "break_minutes",
        }
        updates = {key: value for key, value in data.items() if key in allowed}
        self._validate_task_data(identity_id, task["topic_id"], updates, task)
        self._update_row("task", task_id, updates)
        return self.plans.owned_task(identity_id, task_id)

    def reschedule_task(self, identity_id: str, task_id: str, days: int) -> dict[str, Any]:
        task = self.plans.owned_task(identity_id, task_id)
        if task["status"] in {"completed", "canceled"}:
            raise PlanError("已完成或已取消任务不能重排")
        start_date = datetime.fromisoformat(task["start_date"]).date() + timedelta(days=days)
        due_date = datetime.fromisoformat(task["due_date"]).date() + timedelta(days=days)
        updates: dict[str, Any] = {
            "start_date": start_date.isoformat(),
            "due_date": due_date.isoformat(),
        }
        for field in ("planned_start", "planned_end"):
            value = task.get(field)
            if value:
                planned = _parse_datetime(value)
                if planned.tzinfo is None:
                    planned = planned.replace(tzinfo=timezone.utc)
                updates[field] = utc_string(planned.astimezone(timezone.utc) + timedelta(days=days))
        return self.update_task(identity_id, task_id, updates)

    def reorder_tasks(self, identity_id: str, topic_id: str, ordered_ids: list[str]) -> dict[str, Any]:
        topic = self._owned_topic(identity_id, topic_id)
        self._reorder("task", "topic_id", topic_id, ordered_ids)
        subject = self._owned_subject(identity_id, topic["subject_id"])
        return self.plans.get_plan(identity_id, subject["goal_id"])

    def delete_task(self, identity_id: str, task_id: str) -> None:
        self.plans.owned_task(identity_id, task_id)
        self._assert_no_active_timer("task", task_id)
        self._soft_delete("task", task_id)

    def _owned_goal(self, identity_id: str, goal_id: str) -> dict[str, Any]:
        row = self.database.fetchone(
            "SELECT * FROM learning_goal WHERE id = ? AND identity_id = ? AND deleted_at IS NULL",
            (goal_id, identity_id),
        )
        if not row:
            raise PlanError("学习计划不存在")
        return dict(row)

    def _owned_subject(self, identity_id: str, subject_id: str) -> dict[str, Any]:
        row = self.database.fetchone(
            """
            SELECT s.* FROM subject AS s
            JOIN learning_goal AS g ON g.id = s.goal_id
            WHERE s.id = ? AND g.identity_id = ?
              AND s.deleted_at IS NULL AND g.deleted_at IS NULL
            """,
            (subject_id, identity_id),
        )
        if not row:
            raise PlanError("科目不存在")
        return dict(row)

    def _owned_topic(self, identity_id: str, topic_id: str) -> dict[str, Any]:
        row = self.database.fetchone(
            """
            SELECT p.* FROM topic AS p
            JOIN subject AS s ON s.id = p.subject_id
            JOIN learning_goal AS g ON g.id = s.goal_id
            WHERE p.id = ? AND g.identity_id = ?
              AND p.deleted_at IS NULL AND s.deleted_at IS NULL AND g.deleted_at IS NULL
            """,
            (topic_id, identity_id),
        )
        if not row:
            raise PlanError("主题不存在")
        return dict(row)

    def _validate_task_data(
        self,
        identity_id: str,
        topic_id: str,
        data: dict[str, Any],
        existing: dict[str, Any] | None = None,
    ) -> None:
        values = {**(existing or {}), **data}
        if values["start_date"] > values["due_date"]:
            raise PlanError("任务截止日期不能早于开始日期")
        bounds = self.database.fetchone(
            """
            SELECT g.start_date, g.end_date
            FROM topic AS p
            JOIN subject AS s ON s.id = p.subject_id
            JOIN learning_goal AS g ON g.id = s.goal_id
            WHERE p.id = ? AND g.identity_id = ?
              AND p.deleted_at IS NULL AND s.deleted_at IS NULL AND g.deleted_at IS NULL
            """,
            (topic_id, identity_id),
        )
        if not bounds:
            raise PlanError("主题不存在")
        if values["start_date"] < bounds["start_date"] or values["due_date"] > bounds["end_date"]:
            raise PlanError("任务日期必须位于计划日期范围内")
        planned_start = values.get("planned_start")
        planned_end = values.get("planned_end")
        if planned_start and planned_end and _parse_datetime(planned_end) <= _parse_datetime(planned_start):
            raise PlanError("任务结束时间必须晚于开始时间")

    def _next_position(self, table: str, parent_column: str, parent_id: str) -> int:
        row = self.database.fetchone(
            f"SELECT COALESCE(MAX(position), -1) + 1 AS next_position FROM {table} "
            f"WHERE {parent_column} = ? AND deleted_at IS NULL",
            (parent_id,),
        )
        return int(row["next_position"]) if row else 0

    def _reorder(self, table: str, parent_column: str, parent_id: str, ordered_ids: list[str]) -> None:
        current = [
            row["id"]
            for row in self.database.fetchall(
                f"SELECT id FROM {table} WHERE {parent_column} = ? AND deleted_at IS NULL ORDER BY position, created_at",
                (parent_id,),
            )
        ]
        if set(current) != set(ordered_ids) or len(current) != len(ordered_ids):
            raise PlanError("排序列表必须包含全部同级节点")
        now = utc_string(utc_now())
        with self.database.transaction() as connection:
            for position, item_id in enumerate(ordered_ids):
                connection.execute(
                    f"UPDATE {table} SET position = ?, updated_at = ? WHERE id = ?",
                    (position, now, item_id),
                )

    def _update_row(self, table: str, item_id: str, data: dict[str, Any]) -> None:
        if not data:
            return
        now = utc_string(utc_now())
        columns = list(data)
        assignments = ", ".join(f"{column} = ?" for column in columns)
        values = [data[column] for column in columns]
        with self.database.transaction() as connection:
            connection.execute(
                f"UPDATE {table} SET {assignments}, updated_at = ? WHERE id = ?",
                (*values, now, item_id),
            )

    def _soft_delete(self, table: str, item_id: str) -> None:
        now = utc_string(utc_now())
        with self.database.transaction() as connection:
            connection.execute(
                f"UPDATE {table} SET deleted_at = ?, updated_at = ? WHERE id = ?",
                (now, now, item_id),
            )

    def _assert_no_active_timer(self, kind: str, item_id: str) -> None:
        filters = {
            "goal": "s.goal_id = ?",
            "subject": "p.subject_id = ?",
            "topic": "t.topic_id = ?",
            "task": "t.id = ?",
        }
        active = self.database.fetchone(
            f"""
            SELECT ss.id
            FROM study_session AS ss
            JOIN task AS t ON t.id = ss.task_id
            JOIN topic AS p ON p.id = t.topic_id
            JOIN subject AS s ON s.id = p.subject_id
            WHERE {filters[kind]} AND ss.status IN ('running', 'paused')
            LIMIT 1
            """,
            (item_id,),
        )
        if active:
            raise PlanError("请先结束该计划分支中的学习计时")
