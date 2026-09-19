from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    migrations_dir: Path
    runtime_token_path: Path
    host: str
    port: int
    session_ttl_seconds: int
    session_cookie_max_age_seconds: int
    cookie_secure: bool
    cookie_name: str = "nautilus_session"
    learning_database_path: Path | None = None

    @property
    def credentials_dir(self) -> Path:
        """本地加密凭据目录，始终跟随 NAUTILUS_DATA_DIR，测试自然落在临时目录。"""
        return self.data_dir / "runtime" / "credentials"

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("NAUTILUS_DATA_DIR", str(PROJECT_ROOT / "data"))).expanduser()
        if not data_dir.is_absolute():
            data_dir = PROJECT_ROOT / data_dir
        data_dir = data_dir.resolve()
        runtime_token_path = Path(
            os.getenv("NAUTILUS_RUNTIME_TOKEN_FILE", str(data_dir / "runtime" / "access-token"))
        ).expanduser()
        if not runtime_token_path.is_absolute():
            runtime_token_path = PROJECT_ROOT / runtime_token_path
        return cls(
            data_dir=data_dir,
            database_path=data_dir / "nautilus.sqlite3",
            migrations_dir=Path(__file__).with_name("migrations"),
            runtime_token_path=runtime_token_path.resolve(),
            host=os.getenv("NAUTILUS_HOST", "0.0.0.0"),
            port=int(os.getenv("NAUTILUS_BACKEND_PORT", "8000")),
            session_ttl_seconds=int(os.getenv("NAUTILUS_SESSION_TTL_SECONDS", "28800")),
            session_cookie_max_age_seconds=int(
                os.getenv("NAUTILUS_SESSION_COOKIE_MAX_AGE_SECONDS", "315360000")
            ),
            cookie_secure=_as_bool(os.getenv("NAUTILUS_COOKIE_SECURE"), default=False),
            learning_database_path=(
                Path(os.getenv("NAUTILUS_LEARNING_DATABASE", str(data_dir / "learning.sqlite3")))
                .expanduser()
                .resolve()
            ),
        )
