"""INV-008: ordinary app startup cannot authorize a database migration."""

from contextlib import closing
import sqlite3

import pytest

from app.db import Database, DatabaseSchemaError
from app.learning_storage import open_learning_database
from app.main import create_app
from conftest import build_settings


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["main", "learning"])
async def test_startup_rejects_missing_database_without_initializing_it(tmp_path, missing):
    settings = build_settings(tmp_path, initialize_databases=False)
    if missing == "main":
        open_learning_database(settings.learning_database_path, migrate=True).close()
        absent = settings.database_path
    else:
        Database(settings.database_path, settings.migrations_dir, migrate=True).close()
        absent = settings.learning_database_path

    app = create_app(settings)
    with pytest.raises(DatabaseSchemaError, match="Database does not exist"):
        async with app.router.lifespan_context(app):
            pytest.fail("An incomplete database setup must not start")

    assert not absent.exists()
    assert not settings.runtime_token_path.parent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("outdated", ["main", "learning"])
async def test_startup_rejects_pending_migrations_without_changing_database(tmp_path, outdated):
    settings = build_settings(tmp_path, initialize_databases=False)
    Database(
        settings.database_path,
        settings.migrations_dir,
        migration_ceiling=4 if outdated == "main" else 10,
        migrate=True,
    ).close()
    if outdated == "learning":
        Database(
            settings.learning_database_path,
            settings.migrations_dir,
            migration_floor=11,
            migration_ceiling=20,
            migrate=True,
        ).close()
    else:
        open_learning_database(settings.learning_database_path, migrate=True).close()
    paths = (settings.database_path, settings.learning_database_path)
    before = {path: path.read_bytes() for path in paths}

    app = create_app(settings)
    with pytest.raises(DatabaseSchemaError, match="Pending migrations"):
        async with app.router.lifespan_context(app):
            pytest.fail("Pending migrations must not run during startup")

    assert {path: path.read_bytes() for path in paths} == before
    assert not settings.runtime_token_path.parent.exists()


def test_schema_check_does_not_create_missing_parent_directory(tmp_path):
    settings = build_settings(tmp_path, initialize_databases=False)
    path = tmp_path / "not-created" / "database.sqlite3"
    with pytest.raises(DatabaseSchemaError, match="Database does not exist"):
        Database(path, settings.migrations_dir, migrate=False)
    assert not path.parent.exists()


def test_schema_check_rejects_missing_history_without_creating_tables(tmp_path):
    settings = build_settings(tmp_path, initialize_databases=False)
    with closing(sqlite3.connect(settings.database_path)) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER)")
    before = settings.database_path.read_bytes()

    with pytest.raises(DatabaseSchemaError, match="schema cannot be verified"):
        Database(settings.database_path, settings.migrations_dir, migrate=False)

    assert settings.database_path.read_bytes() == before


@pytest.mark.parametrize("target", ["main", "learning"])
def test_schema_check_rejects_unknown_future_migration(tmp_path, target):
    settings = build_settings(tmp_path)
    path = settings.database_path if target == "main" else settings.learning_database_path
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("INSERT INTO schema_migrations VALUES ('999_future', 'synthetic')")
        connection.commit()
    with pytest.raises(DatabaseSchemaError, match="Migration history does not match"):
        if target == "main":
            Database(path, settings.migrations_dir, migrate=False)
        else:
            open_learning_database(path, migrate=False)


@pytest.mark.asyncio
async def test_explicitly_initialized_databases_can_start_without_migration(tmp_path, monkeypatch):
    settings = build_settings(tmp_path)

    def reject_migration(*_args, **_kwargs):
        pytest.fail("Ordinary startup must never invoke the migration writer")

    monkeypatch.setattr(Database, "_migrate", reject_migration)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        assert app.state.database.database_path == settings.database_path
        assert app.state.learning.database.database_path == settings.learning_database_path
    assert not settings.runtime_token_path.exists()
