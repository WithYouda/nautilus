"""Disposable recovery rehearsal, not a user backup or restore API."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from app.db import Database


class RecoveryError(ValueError):
    pass


def migration_manifest(directory: Path) -> dict[str, str]:
    paths = sorted(directory.glob("*.sql"))
    numbers = []
    for path in paths:
        match = re.fullmatch(r"(\d{3})_[a-z0-9_]+\.sql", path.name)
        if not match or int(match[1]) < 11:
            raise RecoveryError("rehearsal migrations must start at 011")
        numbers.append(int(match[1]))
    if not numbers or numbers != list(range(11, 11 + len(numbers))):
        raise RecoveryError("rehearsal migrations must be contiguous from 011")
    return {path.stem: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


class RecoveryWorkspace:
    def __init__(self, migrations_dir: Path):
        self.migrations_dir = migrations_dir
        self.manifest = migration_manifest(migrations_dir)
        self._directory = TemporaryDirectory(prefix="nautilus-recovery.", dir="/tmp")
        self.root = Path(self._directory.name).resolve()
        self._databases: list[Database] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        try:
            for database in self._databases:
                database.close()
        finally:
            self._directory.cleanup()

    def _owned(self, path: Path) -> Path:
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise RecoveryError("path is outside the recovery workspace")
        return path

    def _open_new(self, path: Path) -> Database:
        self._owned(path)
        if migration_manifest(self.migrations_dir) != self.manifest:
            raise RecoveryError("migration manifest changed before creation")
        if path.exists():
            raise RecoveryError("refusing to overwrite an existing database")
        database = Database(path, self.migrations_dir, migration_floor=11, migration_ceiling=None)
        self._databases.append(database)
        return database

    def create_database(self) -> Database:
        return self._open_new(self.root / "source.sqlite3")

    def _verify_connection(self, connection: sqlite3.Connection) -> dict:
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            raise RecoveryError("integrity_check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RecoveryError("foreign key check failed")
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
        if versions != list(self.manifest):
            raise RecoveryError("migration versions do not match")
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        counts = {}
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            counts[name] = connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
        digest = hashlib.sha256()
        for statement in connection.iterdump():
            digest.update(statement.encode("utf-8"))
            digest.update(b"\n")
        return {
            "integrity_check": "ok",
            "foreign_key_violations": 0,
            "versions": versions,
            "table_counts": counts,
            "logical_digest": digest.hexdigest(),
        }

    def verify(self, database: Database) -> dict:
        self._owned(database.database_path)
        with database._lock:
            return self._verify_connection(database.connection)

    def backup(self, database: Database) -> Path:
        self._owned(database.database_path)
        snapshot = self.root / f"snapshot-{list(self.manifest)[-1]}-{uuid4().hex}.sqlite3"
        with database._lock:
            if database.connection.in_transaction:
                raise RecoveryError("cannot back up an active transaction")
            self._verify_connection(database.connection)
            with closing(sqlite3.connect(snapshot)) as target:
                database.connection.backup(target)
                report = self._verify_connection(target)
        snapshot.chmod(0o600)
        metadata = {
            "format_version": 1,
            "migration_manifest": self.manifest,
            "snapshot_digest": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            "verification": report,
        }
        manifest_path = snapshot.with_suffix(".json")
        manifest_path.write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")
        manifest_path.chmod(0o600)
        return snapshot

    def restore(self, snapshot: Path) -> Database:
        self._owned(snapshot)
        manifest_path = self._owned(snapshot.with_suffix(".json"))
        try:
            metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                raise RecoveryError("invalid snapshot manifest")
            if metadata.get("format_version") != 1:
                raise RecoveryError("unsupported snapshot format")
            if metadata["migration_manifest"] != migration_manifest(self.migrations_dir):
                raise RecoveryError("migration manifest changed since backup")
            if hashlib.sha256(snapshot.read_bytes()).hexdigest() != metadata["snapshot_digest"]:
                raise RecoveryError("snapshot digest mismatch")
            target_path = self.root / f"restored-{uuid4().hex}.sqlite3"
            with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)) as source:
                report = self._verify_connection(source)
                if report != metadata["verification"]:
                    raise RecoveryError("snapshot verification mismatch")
                with closing(sqlite3.connect(target_path)) as target:
                    source.backup(target)
                    if self._verify_connection(target) != report:
                        raise RecoveryError("restored verification mismatch")
            restored = Database(target_path, self.migrations_dir, migration_floor=11, migration_ceiling=None)
            self._databases.append(restored)
            return restored
        except (OSError, sqlite3.Error, KeyError, json.JSONDecodeError) as exc:
            raise RecoveryError("snapshot cannot be restored") from exc
