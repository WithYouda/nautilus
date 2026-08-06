from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from .auth import utc_now, utc_string
from .db import Database


TASK_TYPES = {"study", "practice", "review", "output"}
SCHEDULE_MODES = {"fixed", "flexible"}
TIMER_MODES = {"pomodoro_25_5", "pomodoro_50_10", "custom", "count_up"}


class PlanError(ValueError):
    pass


def _id() -> str:
    return str(uuid.uuid4())


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class PlanService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_manual_plan(self, identity_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if data["start_date"] > data["end_date"]:
            raise PlanError("计划结束日期不能早于开始日期")
        if data["task_start_date"] > data["task_due_date"]:
            raise PlanError("任务截止日期不能早于开始日期")
        if not (data["start_date"] <= data["task_start_date"] <= data["end_date"]):
            raise PlanError("任务开始日期必须位于计划日期范围内")
        if not (data["start_date"] <= data["task_due_date"] <= data["end_date"]):
            raise PlanError("任务截止日期必须位于计划日期范围内")
        if data["task_type"] not in TASK_TYPES:
            raise PlanError("不支持的任务类型")
        if data["schedule_mode"] not in SCHEDULE_MODES:
            raise PlanError("不支持的排期方式")
        if data["timer_mode"] not in TIMER_MODES:
            raise PlanError("不支持的计时方式")

        now = utc_string(utc_now())
        goal_id, subject_id, topic_id, task_id = _id(), _id(), _id(), _id()
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO learning_goal
                    (id, identity_id, title, description, start_date, end_date, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    goal_id,
                    identity_id,
                    data["goal_title"],
                    data.get("description", ""),
                    data["start_date"],
                    data["end_date"],
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO subject(id, goal_id, title, position, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
                (subject_id, goal_id, data["subject_title"], now, now),
            )
            connection.execute(
                "INSERT INTO topic(id, subject_id, title, position, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
                (topic_id, subject_id, data["topic_title"], now, now),
            )
            connection.execute(
                """
                INSERT INTO task(
                    id, topic_id, title, task_type, schedule_mode, start_date, due_date,
                    planned_start, planned_end, estimate_minutes, timer_mode, work_minutes,
                    break_minutes, position, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    task_id,
                    topic_id,
                    data["task_title"],
                    data["task_type"],
                    data["schedule_mode"],
                    data["task_start_date"],
                    data["task_due_date"],
                    data.get("planned_start"),
                    data.get("planned_end"),
                    data["estimate_minutes"],
                    data["timer_mode"],
                    data["work_minutes"],
                    data["break_minutes"],
                    now,
                    now,
                ),
            )
        return self.get_plan(identity_id, goal_id)

    def list_plans(self, identity_id: str) -> list[dict[str, Any]]:
        goals = self.database.fetchall(
            """
            SELECT id, title, description, start_date, end_date, status, created_at, updated_at
            FROM learning_goal
            WHERE identity_id = ? AND status != 'archived' AND deleted_at IS NULL
            ORDER BY created_at DESC
            """,
            (identity_id,),
        )
        return [self._plan_tree(dict(goal)) for goal in goals]

    def list_plan_summaries(self, identity_id: str) -> list[dict[str, Any]]:
        rows = self.database.fetchall(
            """
            SELECT
                g.id, g.title, g.description, g.start_date, g.end_date, g.status,
                g.created_at, g.updated_at,
                (
                    SELECT COUNT(*) FROM subject AS s
                    WHERE s.goal_id = g.id AND s.deleted_at IS NULL
                ) AS subject_count,
                (
                    SELECT COUNT(*)
                    FROM topic AS p
                    JOIN subject AS s ON s.id = p.subject_id
                    WHERE s.goal_id = g.id
                      AND s.deleted_at IS NULL AND p.deleted_at IS NULL
                ) AS topic_count,
                (
                    SELECT COUNT(*)
                    FROM task AS t
                    JOIN topic AS p ON p.id = t.topic_id
                    JOIN subject AS s ON s.id = p.subject_id
                    WHERE s.goal_id = g.id
                      AND s.deleted_at IS NULL AND p.deleted_at IS NULL
                      AND t.deleted_at IS NULL AND t.status != 'canceled'
                ) AS task_count,
                (
                    SELECT COUNT(*)
                    FROM task AS t
                    JOIN topic AS p ON p.id = t.topic_id
                    JOIN subject AS s ON s.id = p.subject_id
                    WHERE s.goal_id = g.id
                      AND s.deleted_at IS NULL AND p.deleted_at IS NULL
                      AND t.deleted_at IS NULL AND t.status = 'completed'
                ) AS completed_task_count,
                (
                    SELECT COALESCE(SUM(t.estimate_minutes), 0)
                    FROM task AS t
                    JOIN topic AS p ON p.id = t.topic_id
                    JOIN subject AS s ON s.id = p.subject_id
                    WHERE s.goal_id = g.id
                      AND s.deleted_at IS NULL AND p.deleted_at IS NULL
                      AND t.deleted_at IS NULL AND t.status != 'canceled'
                ) AS estimate_minutes,
                (
                    SELECT COALESCE(SUM(t.actual_minutes), 0)
                    FROM task AS t
                    JOIN topic AS p ON p.id = t.topic_id
                    JOIN subject AS s ON s.id = p.subject_id
                    WHERE s.goal_id = g.id
                      AND s.deleted_at IS NULL AND p.deleted_at IS NULL
                      AND t.deleted_at IS NULL AND t.status != 'canceled'
                ) AS actual_minutes
            FROM learning_goal AS g
            WHERE g.identity_id = ? AND g.status != 'archived' AND g.deleted_at IS NULL
            ORDER BY g.created_at DESC, g.id DESC
            """,
            (identity_id,),
        )
        summaries: list[dict[str, Any]] = []
        for row in rows:
            summary = dict(row)
            task_count = int(summary["task_count"])
            completed = int(summary["completed_task_count"])
            summary["progress"] = round(completed / task_count * 100) if task_count else 0
            summary["next_task"] = self._next_task_for_goal(identity_id, summary["id"])
            summaries.append(summary)
        return summaries

    def get_plan(self, identity_id: str, goal_id: str) -> dict[str, Any]:
        goal = self.database.fetchone(
            """
            SELECT id, title, description, start_date, end_date, status, created_at, updated_at
            FROM learning_goal WHERE id = ? AND identity_id = ? AND deleted_at IS NULL
            """,
            (goal_id, identity_id),
        )
        if not goal:
            raise PlanError("学习计划不存在")
        return self._plan_tree(dict(goal))

    def get_plan_detail(self, identity_id: str, goal_id: str) -> dict[str, Any]:
        plan = self.get_plan(identity_id, goal_id)
        summary = next(
            (item for item in self.list_plan_summaries(identity_id) if item["id"] == goal_id),
            None,
        )
        if summary is None:
            raise PlanError("学习计划不存在")
        plan["summary"] = {
            key: summary[key]
            for key in (
                "subject_count",
                "topic_count",
                "task_count",
                "completed_task_count",
                "progress",
                "estimate_minutes",
                "actual_minutes",
                "next_task",
            )
        }
        return plan

    def plan_schedule(self, identity_id: str, goal_id: str) -> list[dict[str, Any]]:
        self.get_plan(identity_id, goal_id)
        rows = self.database.fetchall(
            """
            SELECT
                t.*, p.title AS topic_title, s.title AS subject_title,
                g.id AS goal_id, g.title AS goal_title
            FROM task AS t
            JOIN topic AS p ON p.id = t.topic_id
            JOIN subject AS s ON s.id = p.subject_id
            JOIN learning_goal AS g ON g.id = s.goal_id
            WHERE g.id = ? AND g.identity_id = ?
              AND g.deleted_at IS NULL AND s.deleted_at IS NULL
              AND p.deleted_at IS NULL AND t.deleted_at IS NULL
            ORDER BY t.start_date, t.planned_start IS NULL, t.planned_start,
                     t.due_date, s.position, p.position, t.position, t.created_at, t.id
            """,
            (goal_id, identity_id),
        )
        return [self._task_dict(row) for row in rows]

    def list_tasks(
        self,
        identity_id: str,
        query: str | None = None,
        status: str | None = None,
        task_type: str | None = None,
        schedule_mode: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        clauses = [
            "g.identity_id = ?",
            "g.status != 'archived'",
            "g.deleted_at IS NULL",
            "s.deleted_at IS NULL",
            "p.deleted_at IS NULL",
            "t.deleted_at IS NULL",
        ]
        params: list[Any] = [identity_id]
        if status:
            clauses.append("t.status = ?")
            params.append(status)
        if task_type:
            clauses.append("t.task_type = ?")
            params.append(task_type)
        if schedule_mode:
            clauses.append("t.schedule_mode = ?")
            params.append(schedule_mode)
        if start_date:
            clauses.append("t.due_date >= ?")
            params.append(start_date.isoformat())
        if end_date:
            clauses.append("t.start_date <= ?")
            params.append(end_date.isoformat())
        if query and query.strip():
            search = f"%{query.strip()}%"
            clauses.append("(t.title LIKE ? OR g.title LIKE ? OR s.title LIKE ? OR p.title LIKE ?)")
            params.extend([search, search, search, search])
        rows = self.database.fetchall(
            f"""
            SELECT
                t.*,
                p.title AS topic_title,
                s.title AS subject_title,
                g.id AS goal_id,
                g.title AS goal_title
            FROM task AS t
            JOIN topic AS p ON p.id = t.topic_id
            JOIN subject AS s ON s.id = p.subject_id
            JOIN learning_goal AS g ON g.id = s.goal_id
            WHERE {' AND '.join(clauses)}
            ORDER BY t.start_date, t.planned_start IS NULL, t.planned_start, t.position, t.created_at
            """,
            tuple(params),
        )
        return [self._task_dict(row) for row in rows]

    def _plan_tree(self, goal: dict[str, Any]) -> dict[str, Any]:
        subjects = [
            dict(row)
            for row in self.database.fetchall(
                "SELECT id, title, position FROM subject WHERE goal_id = ? AND deleted_at IS NULL ORDER BY position, created_at",
                (goal["id"],),
            )
        ]
        for subject in subjects:
            topics = [
                dict(row)
                for row in self.database.fetchall(
                    "SELECT id, title, position FROM topic WHERE subject_id = ? AND deleted_at IS NULL ORDER BY position, created_at",
                    (subject["id"],),
                )
            ]
            for topic in topics:
                topic["tasks"] = [
                    self._task_dict(row)
                    for row in self.database.fetchall(
                        """
                        SELECT * FROM task WHERE topic_id = ? AND deleted_at IS NULL
                        ORDER BY position, start_date, created_at
                        """,
                        (topic["id"],),
                    )
                ]
                self._attach_progress(topic, topic["tasks"])
            subject["topics"] = topics
            self._attach_progress(
                subject,
                [task for topic in topics for task in topic["tasks"]],
            )
        goal["subjects"] = subjects
        return goal

    @staticmethod
    def _attach_progress(node: dict[str, Any], tasks: list[dict[str, Any]]) -> None:
        active = [task for task in tasks if task["status"] != "canceled"]
        completed = sum(task["status"] == "completed" for task in active)
        node["task_count"] = len(active)
        node["completed_task_count"] = completed
        node["progress"] = round(completed / len(active) * 100) if active else 0

    def _next_task_for_goal(self, identity_id: str, goal_id: str) -> dict[str, Any] | None:
        active = self.database.fetchone(
            """
            SELECT
                t.*, p.title AS topic_title, s.title AS subject_title,
                g.id AS goal_id, g.title AS goal_title
            FROM study_session AS ss
            JOIN task AS t ON t.id = ss.task_id
            JOIN topic AS p ON p.id = t.topic_id
            JOIN subject AS s ON s.id = p.subject_id
            JOIN learning_goal AS g ON g.id = s.goal_id
            WHERE ss.identity_id = ? AND ss.status IN ('running', 'paused')
              AND g.id = ? AND g.deleted_at IS NULL AND s.deleted_at IS NULL
              AND p.deleted_at IS NULL AND t.deleted_at IS NULL
            ORDER BY ss.status = 'paused', ss.created_at, ss.id
            LIMIT 1
            """,
            (identity_id, goal_id),
        )
        if active:
            return self._task_dict(active)
        today = date.today().isoformat()
        row = self.database.fetchone(
            """
            SELECT
                t.*, p.title AS topic_title, s.title AS subject_title,
                g.id AS goal_id, g.title AS goal_title
            FROM task AS t
            JOIN topic AS p ON p.id = t.topic_id
            JOIN subject AS s ON s.id = p.subject_id
            JOIN learning_goal AS g ON g.id = s.goal_id
            WHERE g.id = ? AND g.identity_id = ?
              AND g.deleted_at IS NULL AND s.deleted_at IS NULL
              AND p.deleted_at IS NULL AND t.deleted_at IS NULL
              AND t.status IN ('pending', 'in_progress')
            ORDER BY
                CASE t.status WHEN 'in_progress' THEN 0 ELSE 1 END,
                CASE WHEN t.due_date < ? THEN 0 ELSE 1 END,
                CASE WHEN t.due_date < ? THEN t.due_date END,
                t.planned_start IS NULL,
                t.planned_start,
                t.due_date,
                s.position,
                p.position,
                t.position,
                t.created_at,
                t.id
            LIMIT 1
            """,
            (goal_id, identity_id, today, today),
        )
        return self._task_dict(row) if row else None

    def today_dashboard(self, identity_id: str, local_date: date | None = None) -> dict[str, Any]:
        selected_date = (local_date or date.today()).isoformat()
        rows = self.database.fetchall(
            """
            SELECT
                t.*,
                p.title AS topic_title,
                s.title AS subject_title,
                g.id AS goal_id,
                g.title AS goal_title
            FROM task AS t
            JOIN topic AS p ON p.id = t.topic_id
            JOIN subject AS s ON s.id = p.subject_id
            JOIN learning_goal AS g ON g.id = s.goal_id
            WHERE g.identity_id = ?
              AND g.status = 'active'
              AND g.deleted_at IS NULL
              AND s.deleted_at IS NULL
              AND p.deleted_at IS NULL
              AND t.deleted_at IS NULL
              AND t.status != 'canceled'
              AND t.start_date <= ?
              AND t.due_date >= ?
            ORDER BY t.status = 'completed', t.planned_start IS NULL, t.planned_start, t.position, t.created_at
            """,
            (identity_id, selected_date, selected_date),
        )
        tasks = [self._task_dict(row) for row in rows]
        completed = sum(task["status"] == "completed" for task in tasks)
        planned_minutes = sum(task["estimate_minutes"] for task in tasks)
        actual_minutes = sum(task["actual_minutes"] for task in tasks)
        active_session = self.database.fetchone(
            """
            SELECT task_id
            FROM study_session
            WHERE identity_id = ? AND status IN ('running', 'paused')
            ORDER BY created_at, id
            LIMIT 1
            """,
            (identity_id,),
        )
        active = (
            self.timer_snapshot(identity_id, active_session["task_id"])
            if active_session
            else None
        )
        return {
            "date": selected_date,
            "tasks": tasks,
            "summary": {
                "total": len(tasks),
                "completed": completed,
                "planned_minutes": planned_minutes,
                "actual_minutes": actual_minutes,
                "progress": round(completed / len(tasks) * 100) if tasks else 0,
            },
            "active_timer": active,
        }

    def complete_task(self, identity_id: str, task_id: str) -> dict[str, Any]:
        return self.set_task_completion(identity_id, task_id, True)

    def set_task_completion(
        self,
        identity_id: str,
        task_id: str,
        completed: bool,
    ) -> dict[str, Any]:
        task = self.owned_task(identity_id, task_id)
        if completed and task["status"] == "completed":
            return task
        if not completed and task["status"] != "completed":
            return task
        if completed and task["status"] == "canceled":
            raise PlanError("已取消任务不能直接标记完成")

        now = utc_string(utc_now())
        with self.database.transaction() as connection:
            if completed:
                active_row = connection.execute(
                    """
                    SELECT id, status, resumed_at, accumulated_seconds
                    FROM study_session
                    WHERE task_id = ? AND identity_id = ?
                      AND status IN ('running', 'paused')
                    """,
                    (task_id, identity_id),
                ).fetchone()
                elapsed = self._elapsed_seconds(dict(active_row)) if active_row else 0
                if active_row:
                    connection.execute(
                        """
                        UPDATE study_session
                        SET status = 'completed', ended_at = ?, accumulated_seconds = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (now, elapsed, now, active_row["id"]),
                    )
                connection.execute(
                    """
                    UPDATE task
                    SET completion_restore_status = ?, completion_restore_progress = ?,
                        actual_minutes = actual_minutes + ?, status = 'completed', progress = 100,
                        completed_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        task["status"],
                        task["progress"],
                        elapsed // 60,
                        now,
                        now,
                        task_id,
                    ),
                )
            else:
                restore_status = task.get("completion_restore_status")
                if restore_status not in {"pending", "in_progress"}:
                    restore_status = "pending"
                restore_progress = task.get("completion_restore_progress")
                if restore_progress is None:
                    restore_progress = 0
                connection.execute(
                    """
                    UPDATE task
                    SET status = ?, progress = ?, completed_at = NULL,
                        completion_restore_status = NULL,
                        completion_restore_progress = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (restore_status, restore_progress, now, task_id),
                )
        return self.owned_task(identity_id, task_id)

    def timer_action(
        self,
        identity_id: str,
        task_id: str,
        action: str,
        timer_mode: str | None = None,
        work_minutes: int | None = None,
        break_minutes: int | None = None,
    ) -> dict[str, Any]:
        task = self.owned_task(identity_id, task_id)
        session_row = self.database.fetchone(
            "SELECT * FROM study_session WHERE task_id = ? AND status IN ('running', 'paused')",
            (task_id,),
        )
        session = dict(session_row) if session_row else None
        now_dt = utc_now()
        now = utc_string(now_dt)

        if action == "start":
            if session:
                raise PlanError("该任务已有进行中的计时")
            other_active = self.database.fetchone(
                "SELECT task_id FROM study_session WHERE identity_id = ? AND status IN ('running', 'paused')",
                (identity_id,),
            )
            if other_active:
                raise PlanError("请先结束当前进行中的学习计时")
            if task["status"] == "completed":
                raise PlanError("已完成任务不能重新开始计时")
            selected_mode = timer_mode or task["timer_mode"]
            selected_work = work_minutes or task["work_minutes"]
            selected_break = break_minutes if break_minutes is not None else task["break_minutes"]
            if selected_mode not in TIMER_MODES or selected_work <= 0 or selected_break < 0:
                raise PlanError("计时配置无效")
            session_id = _id()
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO study_session(
                        id, task_id, identity_id, timer_mode, work_minutes, break_minutes,
                        status, started_at, resumed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?)
                    """,
                    (session_id, task_id, identity_id, selected_mode, selected_work, selected_break, now, now, now, now),
                )
                connection.execute(
                    """
                    UPDATE task SET status = 'in_progress', timer_mode = ?, work_minutes = ?,
                        break_minutes = ?, updated_at = ? WHERE id = ?
                    """,
                    (selected_mode, selected_work, selected_break, now, task_id),
                )
        elif action == "pause":
            if not session or session["status"] != "running":
                raise PlanError("当前没有可暂停的计时")
            elapsed = self._elapsed_seconds(session, now_dt)
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE study_session SET status = 'paused', paused_at = ?, accumulated_seconds = ?, updated_at = ? WHERE id = ?",
                    (now, elapsed, now, session["id"]),
                )
        elif action == "resume":
            if not session or session["status"] != "paused":
                raise PlanError("当前没有可继续的计时")
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE study_session SET status = 'running', resumed_at = ?, paused_at = NULL, updated_at = ? WHERE id = ?",
                    (now, now, session["id"]),
                )
        elif action == "finish":
            if not session:
                raise PlanError("当前没有可结束的计时")
            elapsed = self._elapsed_seconds(session, now_dt)
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE study_session SET status = 'completed', ended_at = ?, accumulated_seconds = ?, updated_at = ? WHERE id = ?",
                    (now, elapsed, now, session["id"]),
                )
                connection.execute(
                    "UPDATE task SET actual_minutes = actual_minutes + ?, status = 'pending', updated_at = ? WHERE id = ?",
                    (elapsed // 60, now, task_id),
                )
        else:
            raise PlanError("不支持的计时操作")
        return self.timer_snapshot(identity_id, task_id)

    def timer_snapshot(self, identity_id: str, task_id: str) -> dict[str, Any] | None:
        self.owned_task(identity_id, task_id)
        row = self.database.fetchone(
            "SELECT * FROM study_session WHERE task_id = ? AND status IN ('running', 'paused')",
            (task_id,),
        )
        if not row:
            return None
        session = dict(row)
        elapsed = self._elapsed_seconds(session)
        phase = "focus"
        remaining = None
        if session["timer_mode"] != "count_up":
            work_seconds = session["work_minutes"] * 60
            break_seconds = session["break_minutes"] * 60
            if break_seconds == 0:
                remaining = work_seconds - (elapsed % work_seconds)
            else:
                cycle_position = elapsed % (work_seconds + break_seconds)
                if cycle_position < work_seconds:
                    remaining = work_seconds - cycle_position
                else:
                    phase = "break"
                    remaining = work_seconds + break_seconds - cycle_position
        return {
            "id": session["id"],
            "task_id": session["task_id"],
            "status": session["status"],
            "timer_mode": session["timer_mode"],
            "work_minutes": session["work_minutes"],
            "break_minutes": session["break_minutes"],
            "started_at": session["started_at"],
            "elapsed_seconds": elapsed,
            "remaining_seconds": remaining,
            "phase": phase,
        }

    def owned_task(self, identity_id: str, task_id: str) -> dict[str, Any]:
        row = self.database.fetchone(
            """
            SELECT t.*, p.title AS topic_title, s.title AS subject_title,
                   g.id AS goal_id, g.title AS goal_title
            FROM task AS t
            JOIN topic AS p ON p.id = t.topic_id
            JOIN subject AS s ON s.id = p.subject_id
            JOIN learning_goal AS g ON g.id = s.goal_id
            WHERE t.id = ? AND g.identity_id = ?
              AND t.deleted_at IS NULL
              AND p.deleted_at IS NULL
              AND s.deleted_at IS NULL
              AND g.deleted_at IS NULL
            """,
            (task_id, identity_id),
        )
        if not row:
            raise PlanError("任务不存在")
        return self._task_dict(row)

    @staticmethod
    def _elapsed_seconds(session: dict[str, Any], now: datetime | None = None) -> int:
        elapsed = int(session["accumulated_seconds"])
        if session["status"] == "running":
            elapsed += max(0, int(((now or utc_now()) - _parse_utc(session["resumed_at"])).total_seconds()))
        return elapsed

    @staticmethod
    def _task_dict(row: Any) -> dict[str, Any]:
        task = dict(row)
        task["overdue"] = task["status"] != "completed" and task["due_date"] < date.today().isoformat()
        return task
