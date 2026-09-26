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
from .purge_storage import register_backup, unregister_missing_backup, storage_lock, receipts


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
    with storage_lock(database_path):
        return _create_learning_backup(database_path, backup_dir, label=label)


def _create_learning_backup(database_path, backup_dir, *, label):
    if any(receipt['status'] != 'complete' for receipt in receipts(database_path)):
        raise ProductionLearningDatabaseError('purged content cleanup is incomplete; finish it before creating a backup')
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

    register_backup(database_path, backup_path)
    try:
        with closing(sqlite3.connect(database_path)) as source, closing(sqlite3.connect(backup_path)) as target:
            source.backup(target)
    except BaseException:
        unregister_missing_backup(database_path, backup_path)
        raise
    with closing(sqlite3.connect(backup_path)) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    os.chmod(backup_path, 0o600)

    backup_inspection = inspect_learning_database(backup_path)
    if backup_inspection["applied_migrations"] != inspection["applied_migrations"]:
        backup_path.unlink(missing_ok=True)
        unregister_missing_backup(database_path, backup_path)
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


def _backup_loses_purge_barriers(
    current: sqlite3.Connection,
    backup: sqlite3.Connection,
) -> bool:
    # Checking only for old text is insufficient: an even older backup may
    # predate the object, discard its tombstone, and allow the text back on a
    # subsequent restore. Preserve every known erasure, including shared
    # private evidence and discussions reached through deletion propagation.
    if current.execute("SELECT 1 FROM sqlite_master WHERE name='learning_event'").fetchone():
        purges = {row[0] for row in current.execute("SELECT event_id FROM learning_event WHERE event_type='artifact.purged'")}
        retained = {row[0] for row in backup.execute("SELECT event_id FROM learning_event WHERE event_type='artifact.purged'")}
        if not purges.issubset(retained):
            return True
    barriers = (
        ("learning_raw_artifact", ("owner_id", "artifact_id", "content_version")),
        ("learning_verification", ("owner_id", "id")),
        ("learning_verification_submission", ("owner_id", "id")),
        ("learning_evidence_private_content", ("owner_id", "event_id")),
        ("learning_question_discussion", ("owner_id", "id")),
        ("learning_completion", ("owner_id", "id")),
    )
    for table, keys in barriers:
        current_columns = {row[1] for row in current.execute(f"PRAGMA table_info({table})")}
        if "purged_at" not in current_columns:
            continue
        erased = {
            tuple(row) for row in current.execute(
                f"SELECT {', '.join(keys)} FROM {table} WHERE purged_at IS NOT NULL"
            )
        }
        if not erased:
            continue
        backup_columns = {row[1] for row in backup.execute(f"PRAGMA table_info({table})")}
        if not {*keys, "purged_at"}.issubset(backup_columns):
            return True
        retained = {
            tuple(row) for row in backup.execute(
                f"SELECT {', '.join(keys)} FROM {table} WHERE purged_at IS NOT NULL"
            )
        }
        if not erased.issubset(retained):
            return True
    return False


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
    if current.execute("SELECT 1 FROM sqlite_master WHERE name='learning_completion'").fetchone():
        for owner_id, completion_id in current.execute(
            "SELECT owner_id, id FROM learning_completion WHERE purged_at IS NOT NULL"
        ):
            if "learning_completion" in backup_tables and backup.execute(
                """SELECT 1 FROM learning_completion
                   WHERE owner_id=? AND id=? AND
                         (content_json IS NOT NULL OR contract_snapshot_json IS NOT NULL
                          OR request_fingerprint IS NOT NULL)""",
                (owner_id, completion_id),
            ).fetchone():
                return True
            if "learning_completion_review" in backup_tables and backup.execute(
                """SELECT 1 FROM learning_completion_review
                   WHERE owner_id=? AND completion_id=? AND
                         (result_json IS NOT NULL OR provider_name IS NOT NULL
                          OR model IS NOT NULL OR user_response IS NOT NULL
                          OR status <> 'failed' OR reason <> 'completion_content_deleted')""",
                (owner_id, completion_id),
            ).fetchone():
                return True
    return False


def restore_learning_backup(
    backup_path: Path,
    target_path: Path,
    *,
    allow_missing_current: bool = False,
) -> dict[str, Any]:
    target_path = validate_learning_path(target_path)
    with storage_lock(target_path):
        return _restore_learning_backup(backup_path, target_path, allow_missing_current=allow_missing_current)


def _restore_learning_backup(backup_path, target_path, *, allow_missing_current=False):
    """Restore an offline database; callers must stop all database users first."""
    backup_path = validate_learning_path(backup_path)
    target_path = validate_learning_path(target_path)
    backup_inspection = inspect_learning_database(backup_path)

    if not target_path.exists() and not allow_missing_current:
        raise ProductionLearningDatabaseError(
            "current learning database is missing; purge verification is unavailable"
        )

    temporary_path = target_path.with_name(f".{target_path.name}.restore-{os.getpid()}")
    temporary_path.unlink(missing_ok=True)
    try:
        # Validate the snapshot that will actually be installed. Reopening the
        # source after checking it could otherwise copy a different backup.
        temporary_path.touch(mode=0o600, exist_ok=False)
        with closing(_connect_read_only(backup_path)) as source, closing(sqlite3.connect(temporary_path)) as target:
            source.backup(target)
        restored_inspection = inspect_learning_database(temporary_path)
        if restored_inspection["applied_migrations"] != backup_inspection["applied_migrations"]:
            raise ProductionLearningDatabaseError("restored database migration history does not match backup")
        _check_purge_receipts(target_path, temporary_path)
        if target_path.exists():
            inspect_learning_database(target_path)
            with closing(_connect_read_only(target_path)) as current, closing(_connect_read_only(temporary_path)) as backup:
                if _backup_loses_purge_barriers(current, backup):
                    raise ProductionLearningDatabaseError(
                        "backup would lose deletion barriers for content purged in the current database; "
                        "create a fresh post-purge backup instead"
                    )
                conflicting = _backup_contains_purged_content(backup, _purged_artifacts(current))
                if conflicting or _backup_restores_verification_content(current, backup):
                    raise ProductionLearningDatabaseError(
                        "backup would restore content that is purged in the current database; "
                        "create a fresh post-purge backup instead"
                    )
        elif not allow_missing_current:
            raise ProductionLearningDatabaseError(
                "current learning database is missing; purge verification is unavailable"
            )
        os.replace(temporary_path, target_path)
        os.chmod(target_path, 0o600)
    finally:
        for suffix in ("", "-wal", "-shm"):
            temporary_path.with_name(temporary_path.name + suffix).unlink(missing_ok=True)
    return inspect_learning_database(target_path)


def _check_purge_receipts(target_path, candidate_path):
    # The local receipt survives a database rollback or missing-current restore.
    # Incomplete cleanup cannot be disguised by restoring a different snapshot.
    from .purge_content import columns, erase
    for receipt in receipts(target_path):
        if receipt['status'] != 'complete':
            raise ProductionLearningDatabaseError('purged content cleanup is incomplete; finish it before restoring')
        kind, owner, object_id = (receipt[key] for key in ('kind', 'owner', 'object_id'))
        table, key = {'artifact': ('learning_raw_artifact', 'artifact_id'),
                      'verification': ('learning_verification', 'id'), 'completion': ('learning_completion', 'id')}[kind]
        with closing(sqlite3.connect(candidate_path)) as connection:
            connection.row_factory = sqlite3.Row
            if 'purged_at' not in columns(connection, table):
                raise ProductionLearningDatabaseError('backup would lose deletion barriers for purged content')
            rows = connection.execute(f'SELECT purged_at FROM {table} WHERE owner_id=? AND {key}=?', (owner, object_id)).fetchall()
            if not rows or any(not row[0] for row in rows):
                raise ProductionLearningDatabaseError('backup would lose deletion barriers for purged content')
            for artifact_id in receipt.get('artifact_ids', []) + ([object_id] if kind == 'artifact' else []):
                if not connection.execute("SELECT 1 FROM learning_event WHERE owner_id=? AND event_type='artifact.purged' AND json_extract(payload_json,'$.artifact_id')=?", (owner, artifact_id)).fetchone():
                    raise ProductionLearningDatabaseError('backup would lose deletion facts for purged content')
            private_columns = {
                'learning_raw_artifact': ['content', 'content_hash'],
                'learning_verification': ['challenge_json', 'answer_key_json', 'submission_json', 'result_json', 'contract_snapshot_json'],
                'learning_verification_submission': ['content_json'],
                'learning_verification_evaluation': ['result_json', 'provider_snapshot_json'],
                'learning_discussion_turn': ['user_content', 'assistant_content', 'reasoning_content', 'sources_json', 'provider_snapshot_json'],
                'learning_evidence_event': ['payload_json'],
                'learning_evidence_private_content': ['content_json'],
                'learning_completion': ['content_json', 'contract_snapshot_json', 'request_fingerprint'],
                'learning_completion_review': ['result_json', 'user_response', 'provider_name', 'model'],
            }
            def snapshot():
                result = {}
                for name, wanted in private_columns.items():
                    fields = [field for field in wanted if field in columns(connection, name)]
                    if fields:
                        result[name] = [tuple(row) for row in connection.execute(f"SELECT {','.join(fields)} FROM {name} ORDER BY rowid")]
                return result
            connection.execute('BEGIN')
            try:
                before = snapshot()
                erase(connection, owner, kind, object_id, receipt['updated_at'],
                      submission_ids=receipt.get('submission_ids', []), artifact_ids=receipt.get('artifact_ids', []))
                if snapshot() != before:
                    raise ProductionLearningDatabaseError('backup would restore purged private content')
            finally:
                connection.rollback()


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
