from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    """Small SQLite boundary shared by the local service modules."""

    def __init__(self, database_path: Path, migrations_dir: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            database_path,
            check_same_thread=False,
            isolation_level=None,
        )
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        try:
            self._configure()
            self._migrate(migrations_dir)
        except Exception:
            self.connection.close()
            raise

    def _configure(self) -> None:
        with self._lock:
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.execute("PRAGMA journal_mode = WAL")
            self.connection.execute("PRAGMA synchronous = NORMAL")
            self.connection.execute("PRAGMA busy_timeout = 5000")

    def _migrate(self, migrations_dir: Path) -> None:
        with self._lock:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                row["version"]
                for row in self.connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                ).fetchall()
            }
            for migration_path in sorted(migrations_dir.glob("*.sql")):
                version = migration_path.stem
                if version in applied:
                    continue
                sql = migration_path.read_text(encoding="utf-8")
                # executescript 本身不保证失败时回滚整份脚本；显式包住
                # migration 与版本记录，避免留下半套表结构。
                try:
                    self.connection.executescript(
                        "BEGIN IMMEDIATE;\n"
                        + sql
                        + "\nINSERT INTO schema_migrations(version, applied_at) "
                        "VALUES ('"
                        + version.replace("'", "''")
                        + "', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));\nCOMMIT;"
                    )
                except Exception:
                    self.connection.rollback()
                    raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self.connection.execute("BEGIN")
            try:
                yield self.connection
            except Exception:
                self.connection.rollback()
                raise
            else:
                self.connection.commit()

    def fetchone(self, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.connection.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.connection.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    @property
    def database_path(self) -> Path:
        return Path(self.connection.execute("PRAGMA database_list").fetchone()[2])
