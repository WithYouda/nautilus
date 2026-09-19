from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .config import PROJECT_ROOT
from .db import Database


def open_learning_database(path: Path, *, migrate: bool = True) -> Database:
    path = path.expanduser().resolve()
    default_database = (PROJECT_ROOT / "data" / "nautilus.sqlite3").resolve()
    protected_names = {
        default_database.name,
        f"{default_database.name}-wal",
        f"{default_database.name}-shm",
    }
    if path.parent == default_database.parent and path.name in protected_names:
        raise ValueError("default database is not authorized for the learning baseline")
    if path.exists() and default_database.exists() and path.samefile(default_database):
        raise ValueError("default database alias is not authorized")
    migrations_dir = Path(__file__).with_name("migrations")
    paths = sorted(p for p in migrations_dir.glob("*.sql") if int(p.name[:3]) >= 11)
    expected = [p.stem for p in paths]
    if [int(p.name[:3]) for p in paths] != list(range(11, 11 + len(paths))) or not paths:
        raise ValueError("learning migrations must be contiguous from 011")
    if migrate and path.exists():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables:
                if "schema_migrations" not in tables:
                    raise ValueError("an independent learning database is required")
                applied = [r[0] for r in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
                if applied != expected[:len(applied)] or not applied:
                    raise ValueError("an independent learning database is required")
    return Database(path, migrations_dir, migration_floor=11, migration_ceiling=None, migrate=migrate)
