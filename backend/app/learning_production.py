from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT
from .learning_storage import open_learning_database


class ProductionLearningDatabaseError(RuntimeError):
    pass


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_default_database() -> Path:
    return (PROJECT_ROOT / "data" / "nautilus.sqlite3").resolve()


def validate_learning_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    default_database = _protected_default_database()
    protected_names = {
        default_database.name,
        f"{default_database.name}-wal",
        f"{default_database.name}-shm",
    }
    if resolved == default_database or (
        resolved.parent == default_database.parent and resolved.name in protected_names
    ):
        raise ProductionLearningDatabaseError("refusing to operate on the default main database")
    if "diagnostic-backups" in resolved.parts:
        raise ProductionLearningDatabaseError("diagnostic-backups is not a Nautilus backup location")
    return resolved


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def inspect_learning_database(path: Path) -> dict[str, Any]:
    path = validate_learning_path(path)
    if not path.is_file():
        raise ProductionLearningDatabaseError(f"learning database does not exist: {path}")

    migrations_dir = PROJECT_ROOT / "backend" / "app" / "migrations"
    expected = [
        item.stem
        for item in sorted(migrations_dir.glob("*.sql"))
        if int(item.name[:3]) >= 11
    ]
    with closing(_connect_read_only(path)) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "schema_migrations" not in tables:
            raise ProductionLearningDatabaseError("learning database has no migration history")
        applied = [
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        if not applied or applied != expected[: len(applied)]:
            raise ProductionLearningDatabaseError(
                "learning database migration history is not a valid 011+ prefix"
            )
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ProductionLearningDatabaseError(f"learning database integrity check failed: {integrity}")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            raise ProductionLearningDatabaseError("learning database foreign key check failed")
        return {
            "path": str(path),
            "exists": True,
            "applied_migrations": applied,
            "expected_migrations": expected,
            "up_to_date": applied == expected,
            "integrity_check": integrity,
            "foreign_key_check": "ok",
        }


def _write_manifest(
    backup_path: Path,
    source_path: Path,
    label: str,
    inspection: dict[str, Any],
) -> Path:
    manifest_path = backup_path.with_suffix(".json")
    manifest = {
        "format_version": 1,
        "label": label,
        "created_at": utc_timestamp(),
        "source_database": str(source_path),
        "backup_database": str(backup_path),
        "sha256": file_sha256(backup_path),
        "applied_migrations": inspection["applied_migrations"],
        "integrity_check": inspection["integrity_check"],
        "foreign_key_check": inspection["foreign_key_check"],
        "content_note": "SQLite backup contains private learning content; keep local and access-restricted.",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(manifest_path, 0o600)
    return manifest_path


def create_learning_backup(
    database_path: Path,
    backup_dir: Path,
    *,
    label: str,
) -> tuple[Path, Path, dict[str, Any]]:
    database_path = validate_learning_path(database_path)
    backup_dir = backup_dir.expanduser().resolve()
    if "diagnostic-backups" in backup_dir.parts:
        raise ProductionLearningDatabaseError("diagnostic-backups is not a Nautilus backup location")
    inspection = inspect_learning_database(database_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_dir / f"learning-{label}-{timestamp}.sqlite3"
    if backup_path.exists():
        raise ProductionLearningDatabaseError(f"backup already exists: {backup_path}")

    with closing(sqlite3.connect(database_path)) as source, closing(sqlite3.connect(backup_path)) as target:
        source.backup(target)
    with closing(sqlite3.connect(backup_path)) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    os.chmod(backup_path, 0o600)

    backup_inspection = inspect_learning_database(backup_path)
    if backup_inspection["applied_migrations"] != inspection["applied_migrations"]:
        backup_path.unlink(missing_ok=True)
        raise ProductionLearningDatabaseError("backup migration history does not match source")
    manifest_path = _write_manifest(backup_path, database_path, label, backup_inspection)
    for suffix in ("-wal", "-shm"):
        sidecar = backup_path.with_name(backup_path.name + suffix)
        if sidecar.exists() and sidecar.stat().st_size == 0:
            sidecar.unlink()
    return backup_path, manifest_path, backup_inspection


def _purged_artifacts(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT artifact_id FROM learning_raw_artifact WHERE purged_at IS NOT NULL"
        )
    }


def _backup_contains_purged_content(
    backup_connection: sqlite3.Connection,
    purged_artifact_ids: set[str],
) -> list[str]:
    if not purged_artifact_ids:
        return []
    placeholders = ",".join("?" for _ in purged_artifact_ids)
    return [
        row[0]
        for row in backup_connection.execute(
            f"""SELECT artifact_id FROM learning_raw_artifact
                WHERE artifact_id IN ({placeholders})
                  AND (content IS NOT NULL OR content_hash IS NOT NULL)""",
            tuple(purged_artifact_ids),
        )
    ]


def _backup_restores_verification_content(current, backup):
    current_columns = {row[1] for row in current.execute("PRAGMA table_info(learning_verification_submission)")}
    backup_tables = {row[0] for row in backup.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    backup_verification_columns = {row[1] for row in backup.execute("PRAGMA table_info(learning_verification)")}
    if "purged_at" not in current_columns:
        return False
    # Ordinary artifacts have the same deletable evidence boundary. A backup
    # with erased raw text can still retain a quotation in a projection.
    for artifact_id in _purged_artifacts(current):
        if 'learning_evidence_claim' not in backup_tables:
            continue
        for claim in backup.execute("SELECT id, statement, scope, verification_method, status FROM learning_evidence_claim WHERE artifact_id=?", (artifact_id,)).fetchall():
            if tuple(claim)[1:] != ('内容已彻底删除', 'artifact', 'redacted', 'invalidated'):
                return True
            for table, column in (('learning_review_action', 'reason'), ('learning_evidence_follow_up', 'note')):
                if table in backup_tables and backup.execute(f'SELECT 1 FROM {table} WHERE claim_id=? AND {column} IS NOT NULL', (claim[0],)).fetchone():
                    return True
    for row in current.execute("SELECT id, verification_id FROM learning_verification_submission WHERE purged_at IS NOT NULL"):
        if "learning_verification_submission" in backup_tables:
            saved = backup.execute("SELECT content_json FROM learning_verification_submission WHERE id=?", (row[0],)).fetchone()
            if saved and saved[0] != '{}':
                return True
            if backup.execute("SELECT 1 FROM learning_verification_evaluation WHERE submission_id=? AND result_json IS NOT NULL", (row[0],)).fetchone():
                return True
        if "learning_verification" in backup_tables:
            latest_filter = " AND latest_submission_id=?" if "latest_submission_id" in backup_verification_columns else ""
            params = (row[1], row[0]) if latest_filter else (row[1],)
            saved = backup.execute("SELECT submission_json, result_json FROM learning_verification WHERE id=?" + latest_filter, params).fetchone()
            if saved and any(value is not None for value in saved):
                return True
    if "learning_verification" in backup_tables:
        for row in current.execute("SELECT id FROM learning_verification WHERE purged_at IS NOT NULL"):
            saved = backup.execute("SELECT answer_key_json, challenge_json, submission_json, result_json FROM learning_verification WHERE id=?", (row[0],)).fetchone()
            if saved and tuple(saved) != ('{}', '{}', None, None):
                return True
            if "contract_snapshot_json" in backup_verification_columns:
                snapshot = backup.execute("SELECT contract_snapshot_json FROM learning_verification WHERE id=?", (row[0],)).fetchone()
                if snapshot and json.loads(snapshot[0] or '{}') not in ({}, {"version": 0, "stop_conditions": ""}):
                    return True
    if "learning_question_discussion" in backup_tables and current.execute("SELECT 1 FROM sqlite_master WHERE name='learning_question_discussion'").fetchone():
        turn_columns = {row[1] for row in backup.execute('PRAGMA table_info(learning_discussion_turn)')}
        private_content = 'user_content IS NOT NULL OR assistant_content IS NOT NULL'
        if 'reasoning_content' in turn_columns:
            private_content += ' OR reasoning_content IS NOT NULL'
        for row in current.execute("SELECT id FROM learning_question_discussion WHERE purged_at IS NOT NULL"):
            saved = backup.execute("SELECT purged_at FROM learning_question_discussion WHERE id=?", (row[0],)).fetchone()
            if saved and (saved[0] is None or backup.execute(f"SELECT 1 FROM learning_discussion_turn WHERE discussion_id=? AND ({private_content})", (row[0],)).fetchone()):
                return True
    if "learning_evidence_private_content" in backup_tables:
        for row in current.execute("SELECT event_id FROM learning_evidence_private_content WHERE purged_at IS NOT NULL"):
            if backup.execute(
                "SELECT 1 FROM learning_evidence_private_content WHERE event_id=? AND content_json IS NOT NULL",
                (row[0],),
            ).fetchone():
                return True
    return False


def restore_learning_backup(
    backup_path: Path,
    target_path: Path,
    *,
    allow_missing_current: bool = False,
) -> dict[str, Any]:
    backup_path = validate_learning_path(backup_path)
    target_path = validate_learning_path(target_path)
    backup_inspection = inspect_learning_database(backup_path)

    if target_path.exists():
        current_inspection = inspect_learning_database(target_path)
        with closing(_connect_read_only(target_path)) as current, closing(_connect_read_only(backup_path)) as backup:
            purged = _purged_artifacts(current)
            conflicting = _backup_contains_purged_content(backup, purged)
            if _backup_restores_verification_content(current, backup):
                conflicting.append("verification_content")
        if conflicting:
            raise ProductionLearningDatabaseError(
                "backup would restore content that is purged in the current database; "
                "create a fresh post-purge backup instead"
            )
    elif not allow_missing_current:
        raise ProductionLearningDatabaseError(
            "current learning database is missing; purge verification is unavailable"
        )

    temporary_path = target_path.with_name(f".{target_path.name}.restore-{os.getpid()}")
    temporary_path.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(backup_path)) as source, closing(sqlite3.connect(temporary_path)) as target:
            source.backup(target)
        restored_inspection = inspect_learning_database(temporary_path)
        if restored_inspection["applied_migrations"] != backup_inspection["applied_migrations"]:
            raise ProductionLearningDatabaseError("restored database migration history does not match backup")
        os.replace(temporary_path, target_path)
        os.chmod(target_path, 0o600)
    finally:
        temporary_path.unlink(missing_ok=True)
    return inspect_learning_database(target_path)


def upgrade_learning_database(
    database_path: Path,
    backup_dir: Path,
    *,
    authorized: bool,
) -> dict[str, Any]:
    database_path = validate_learning_path(database_path)
    if not authorized:
        raise ProductionLearningDatabaseError("production learning database upgrade requires explicit authorization")

    preflight: dict[str, Any] | None = None
    pre_backup: dict[str, Any] | None = None
    existed_before = database_path.exists()
    if existed_before:
        preflight = inspect_learning_database(database_path)
        pending_import = False
        if preflight["up_to_date"]:
            with closing(_connect_read_only(database_path)) as connection:
                pending_import = connection.execute(
                    """SELECT 1 FROM learning_verification_submission s JOIN learning_verification v
                       ON v.owner_id=s.owner_id AND v.id=s.verification_id
                       WHERE s.artifact_id IS NULL AND s.purged_at IS NULL AND v.session_id IS NOT NULL LIMIT 1""",
                ).fetchone() is not None
        if preflight["up_to_date"] and not pending_import:
            return {
                "status": "already_up_to_date",
                "preflight": preflight,
                "pre_upgrade_backup": None,
                "post_upgrade_backup": None,
            }
        _backup, _manifest, pre_backup = create_learning_backup(
            database_path,
            backup_dir,
            label="pre-upgrade",
        )

    database = open_learning_database(database_path, migrate=True)
    try:
        from .learning_service import LearningService
        from .verification import VerificationService
        verification = VerificationService(LearningService(database), None)
        for identity in database.fetchall("SELECT * FROM local_identity"):
            verification.link_legacy_submissions(dict(identity))
        if database.fetchone("PRAGMA integrity_check")[0] != "ok":
            raise ProductionLearningDatabaseError("migrated learning database failed integrity check")
        if database.fetchall("PRAGMA foreign_key_check"):
            raise ProductionLearningDatabaseError("migrated learning database failed foreign key check")
    finally:
        database.close()
    os.chmod(database_path, 0o600)

    post_backup, _manifest, post_inspection = create_learning_backup(
        database_path,
        backup_dir,
        label="post-upgrade" if existed_before else "post-initialization",
    )
    return {
        "status": "upgraded" if existed_before else "initialized",
        "preflight": preflight,
        "pre_upgrade_backup": pre_backup,
        "post_upgrade_backup": post_inspection,
        "post_upgrade_backup_path": str(post_backup),
    }
