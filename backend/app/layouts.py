from __future__ import annotations

import json
import uuid
from typing import Any

from .auth import utc_now, utc_string
from .db import Database


MODULE_IDS = ("summary", "tasks", "timer", "context")
DEFAULT_MODULES = [
    {"id": "summary", "visible": True},
    {"id": "tasks", "visible": True},
    {"id": "timer", "visible": True},
    {"id": "context", "visible": True},
]


class LayoutError(ValueError):
    pass


class LayoutService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_layout(self, identity_id: str) -> dict[str, Any]:
        row = self.database.fetchone(
            "SELECT modules_json, source_template_id, updated_at FROM layout_config WHERE identity_id = ?",
            (identity_id,),
        )
        if row:
            return {
                "modules": json.loads(row["modules_json"]),
                "source_template_id": row["source_template_id"],
                "updated_at": row["updated_at"],
            }
        return {
            "modules": [dict(module) for module in DEFAULT_MODULES],
            "source_template_id": "system-today-cockpit",
            "updated_at": None,
        }

    def update_layout(
        self,
        identity_id: str,
        modules: list[dict[str, Any]],
        source_template_id: str | None = None,
    ) -> dict[str, Any]:
        clean_modules = self._validate_modules(modules)
        now = utc_string(utc_now())
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO layout_config(identity_id, modules_json, source_template_id, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(identity_id) DO UPDATE SET
                    modules_json = excluded.modules_json,
                    source_template_id = excluded.source_template_id,
                    updated_at = excluded.updated_at
                """,
                (identity_id, json.dumps(clean_modules, separators=(",", ":")), source_template_id, now),
            )
        return self.get_layout(identity_id)

    def list_templates(self, identity_id: str) -> list[dict[str, Any]]:
        rows = self.database.fetchall(
            """
            SELECT id, name, modules_json, is_system, created_at, updated_at
            FROM layout_template
            WHERE is_system = 1 OR identity_id = ?
            ORDER BY
                is_system DESC,
                CASE id
                    WHEN 'system-today-cockpit' THEN 0
                    WHEN 'system-focus' THEN 1
                    WHEN 'system-review' THEN 2
                    ELSE 3
                END,
                created_at,
                name
            """,
            (identity_id,),
        )
        return [self._template_dict(row) for row in rows]

    def save_personal_template(self, identity_id: str, name: str) -> dict[str, Any]:
        layout = self.get_layout(identity_id)
        now = utc_string(utc_now())
        template_id = str(uuid.uuid4())
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO layout_template
                    (id, identity_id, name, modules_json, is_system, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    template_id,
                    identity_id,
                    name.strip(),
                    json.dumps(layout["modules"], separators=(",", ":")),
                    now,
                    now,
                ),
            )
        return self._owned_template(identity_id, template_id)

    def apply_template(self, identity_id: str, template_id: str) -> dict[str, Any]:
        template = self._available_template(identity_id, template_id)
        return self.update_layout(identity_id, template["modules"], template_id)

    def rename_template(self, identity_id: str, template_id: str, name: str) -> dict[str, Any]:
        template = self._owned_template(identity_id, template_id)
        if template["is_system"]:
            raise LayoutError("系统模板不能重命名")
        now = utc_string(utc_now())
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE layout_template SET name = ?, updated_at = ? WHERE id = ? AND identity_id = ?",
                (name.strip(), now, template_id, identity_id),
            )
        return self._owned_template(identity_id, template_id)

    def delete_template(self, identity_id: str, template_id: str) -> None:
        template = self._available_template(identity_id, template_id)
        if template["is_system"]:
            raise LayoutError("系统模板不能删除")
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM layout_template WHERE id = ? AND identity_id = ?",
                (template_id, identity_id),
            )

    def _available_template(self, identity_id: str, template_id: str) -> dict[str, Any]:
        row = self.database.fetchone(
            """
            SELECT id, name, modules_json, is_system, created_at, updated_at
            FROM layout_template
            WHERE id = ? AND (is_system = 1 OR identity_id = ?)
            """,
            (template_id, identity_id),
        )
        if not row:
            raise LayoutError("布局模板不存在")
        return self._template_dict(row)

    def _owned_template(self, identity_id: str, template_id: str) -> dict[str, Any]:
        row = self.database.fetchone(
            """
            SELECT id, name, modules_json, is_system, created_at, updated_at
            FROM layout_template WHERE id = ? AND identity_id = ?
            """,
            (template_id, identity_id),
        )
        if not row:
            raise LayoutError("个人布局模板不存在")
        return self._template_dict(row)

    @staticmethod
    def _validate_modules(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ids = [module.get("id") for module in modules]
        if len(ids) != len(MODULE_IDS) or set(ids) != set(MODULE_IDS):
            raise LayoutError("布局必须包含全部驾驶舱模块且不能重复")
        return [{"id": module_id, "visible": bool(module.get("visible"))} for module_id, module in zip(ids, modules)]

    @staticmethod
    def _template_dict(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "modules": json.loads(row["modules_json"]),
            "is_system": bool(row["is_system"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
