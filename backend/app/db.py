from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class DatabaseSchemaError(RuntimeError):
    """The database needs an explicitly authorized initialization or upgrade."""


class Database:
    """Small SQLite boundary shared by the local service modules."""

    def __init__(
        self, database_path: Path, migrations_dir: Path, *,
        migration_floor: int = 1, migration_ceiling: int | None = 10,
        migrate: bool = True,
    ) -> None:
        self.migration_floor = migration_floor
        self.migration_ceiling = migration_ceiling
        if migrate:
            database_path.parent.mkdir(parents=True, exist_ok=True)
            connection_target = database_path
        else:
            database_path = database_path.expanduser().resolve()
            if not database_path.is_file():
                raise DatabaseSchemaError(
                    f"Database does not exist: {database_path}. "
                    "Initialize it through an explicitly authorized database operation before starting Nautilus."
                )
            # mode=rw also prevents creation if the file disappears after the check.
            connection_target = database_path.as_uri() + "?mode=rw"
        self.connection = sqlite3.connect(
            connection_target,
            uri=not migrate,
            check_same_thread=False,
            isolation_level=None,
        )
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        try:
            if not migrate:
                self._require_current_schema(migrations_dir, database_path)
            self._configure()
            if migrate:
                self._migrate(migrations_dir)
        except Exception:
            self.connection.close()
            raise

    def _migration_paths(self, migrations_dir: Path) -> list[Path]:
        return [
            path for path in sorted(migrations_dir.glob("*.sql"))
            if int(path.name.split("_", 1)[0]) >= self.migration_floor
            and (
                self.migration_ceiling is None
                or int(path.name.split("_", 1)[0]) <= self.migration_ceiling
            )
        ]

    def _require_current_schema(self, migrations_dir: Path, database_path: Path) -> None:
        expected = [path.stem for path in self._migration_paths(migrations_dir)]
        try:
            applied = [
                row[0] for row in self.connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
        except sqlite3.DatabaseError as exc:
            raise DatabaseSchemaError(
                f"Database schema cannot be verified: {database_path}. "
                "Inspect and initialize or restore it through an explicitly authorized database operation."
            ) from exc
        if not expected or applied != expected:
            pending = [version for version in expected if version not in applied]
            detail = (
                "Pending migrations: " + ", ".join(pending)
                if pending else "Migration history does not match this application."
            )
            raise DatabaseSchemaError(
                f"Database schema is not ready: {database_path}. {detail} "
                "Back up and upgrade it through an explicitly authorized database operation before starting Nautilus."
            )

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
            for migration_path in self._migration_paths(migrations_dir):
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
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield self.connection
                self.connection.commit()
            except BaseException:
                self.connection.rollback()
                raise

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
