import asyncio
import inspect
from collections.abc import Iterator

import pytest

from app.config import Settings
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


def build_settings(tmp_path) -> Settings:
    """所有测试都用临时目录，默认的 data/nautilus.sqlite3 不会被碰到。"""
    return Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "nautilus.sqlite3",
        migrations_dir=Settings.from_env().migrations_dir,
        runtime_token_path=tmp_path / "runtime" / "access-token",
        host="127.0.0.1",
        port=8000,
        session_ttl_seconds=3600,
        session_cookie_max_age_seconds=315360000,
        cookie_secure=False,
    )


@pytest.fixture
def test_app(tmp_path):
    return create_app(build_settings(tmp_path))


@pytest.fixture
def client(test_app) -> Iterator:
    from fastapi.testclient import TestClient

    with TestClient(test_app) as test_client:
        yield test_client
