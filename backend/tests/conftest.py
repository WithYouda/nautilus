import asyncio
import inspect
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from app.config import PROJECT_ROOT, Settings
from app.db import Database
from app.learning_storage import open_learning_database
from app.main import create_app


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: 在临时事件循环中运行的协程测试")


def pytest_pyfunc_call(pyfuncitem):
    """用内置 asyncio 运行协程测试，避免为一个纵切片引入 pytest-asyncio。"""
    test_function = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_function):
        return None
    kwargs = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
    asyncio.run(test_function(**kwargs))
    return True


@pytest.fixture(autouse=True)
def database_access_guard(monkeypatch, tmp_path_factory):
    """Reject non-isolated SQLite paths before opening, including aliases and URIs."""
    connect = sqlite3.connect
    isolated_root = tmp_path_factory.getbasetemp().resolve()
    protected_paths = [PROJECT_ROOT / "data" / name for name in (
        "nautilus.sqlite3", "nautilus.sqlite3-wal", "nautilus.sqlite3-shm",
    )]

    def fingerprint(path):
        try:
            stat = path.stat()
            return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        except FileNotFoundError:
            return None

    before = [fingerprint(path) for path in protected_paths]
    protected_inodes = {item[:2] for item in before if item}
    audit = {"isolated_connections": 0, "protected_connections": 0}

    def guarded_connect(database, *args, **kwargs):
        raw = os.fsdecode(database)
        if raw == ":memory:":
            return connect(database, *args, **kwargs)
        if raw.startswith("file:"):
            raw = unquote(urlsplit(raw).path)
        path = Path(raw).resolve()
        in_recovery = any(
            parent.parent == Path("/tmp") and parent.name.startswith("nautilus-recovery.")
            for parent in path.parents
        )
        stamp = fingerprint(path)
        protected = path.is_relative_to(PROJECT_ROOT / "data") or (
            stamp is not None and stamp[:2] in protected_inodes
        )
        if protected or not (path.is_relative_to(isolated_root) or in_recovery):
            raise RuntimeError("SQLite tests require an isolated database")
        audit["isolated_connections"] += 1
        return connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    yield audit
    assert [fingerprint(path) for path in protected_paths] == before


def build_settings(tmp_path, *, initialize_databases: bool = True) -> Settings:
    """所有测试都用临时目录，默认的 data/nautilus.sqlite3 不会被碰到。"""
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "nautilus.sqlite3",
        migrations_dir=Settings.from_env().migrations_dir,
        runtime_token_path=tmp_path / "runtime" / "access-token",
        host="127.0.0.1",
        port=8000,
        session_ttl_seconds=3600,
        session_cookie_max_age_seconds=315360000,
        cookie_secure=False,
        learning_database_path=tmp_path / "learning.sqlite3",
    )
    if initialize_databases:
        Database(settings.database_path, settings.migrations_dir, migrate=True).close()
        open_learning_database(settings.learning_database_path, migrate=True).close()
    return settings


@pytest.fixture
def test_app(tmp_path):
    return create_app(build_settings(tmp_path))


@pytest.fixture
def client(test_app) -> Iterator:
    from fastapi.testclient import TestClient

    with TestClient(test_app) as test_client:
        yield test_client
