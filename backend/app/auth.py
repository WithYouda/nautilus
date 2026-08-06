from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import Database


PERSISTENT_SESSION_SECONDS = 10 * 365 * 24 * 60 * 60


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_string(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(self, database: Database, session_ttl_seconds: int) -> None:
        self.database = database
        self.session_ttl_seconds = session_ttl_seconds
        self.runtime_access_token = secrets.token_urlsafe(32)

    def ensure_local_identity(self) -> dict[str, Any]:
        existing = self.database.fetchone(
            "SELECT id, device_id, display_name, timezone, created_at FROM local_identity LIMIT 1"
        )
        if existing:
            return dict(existing)

        now = utc_string(utc_now())
        identity = {
            "id": str(uuid.uuid4()),
            "device_id": str(uuid.uuid4()),
            "display_name": "本地学习者",
            "timezone": "Asia/Shanghai",
            "created_at": now,
        }
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO local_identity
                    (id, device_id, display_name, timezone, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    identity["id"],
                    identity["device_id"],
                    identity["display_name"],
                    identity["timezone"],
                    identity["created_at"],
                    identity["created_at"],
                ),
            )
        return identity

    def authorize(self, provided_token: str) -> tuple[str, dict[str, Any]] | None:
        if not hmac.compare_digest(provided_token, self.runtime_access_token):
            return None

        identity = self.ensure_local_identity()
        session_token = secrets.token_urlsafe(32)
        now = utc_now()
        # The cookie and database session remain valid until explicit logout.
        # Keep a bounded timestamp for schema compatibility; lookup relies on revoked_at.
        expires_at = now + timedelta(
            seconds=max(self.session_ttl_seconds, PERSISTENT_SESSION_SECONDS)
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sessions
                    (id, identity_id, token_hash, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    identity["id"],
                    hash_token(session_token),
                    utc_string(now),
                    utc_string(expires_at),
                ),
            )
        return session_token, identity

    def identity_for_session(self, session_token: str | None) -> dict[str, Any] | None:
        if not session_token:
            return None
        row = self.database.fetchone(
            """
            SELECT
                i.id,
                i.device_id,
                i.display_name,
                i.timezone,
                i.created_at
            FROM sessions AS s
            JOIN local_identity AS i ON i.id = s.identity_id
            WHERE s.token_hash = ?
              AND s.revoked_at IS NULL
            """,
            (hash_token(session_token),),
        )
        return dict(row) if row else None

    def authorization_challenge(self) -> str:
        """Return the current process code used by the local authorization screen."""
        return self.runtime_access_token

    def revoke_session(self, session_token: str | None) -> None:
        if not session_token:
            return
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET revoked_at = ?
                WHERE token_hash = ? AND revoked_at IS NULL
                """,
                (utc_string(utc_now()), hash_token(session_token)),
            )
