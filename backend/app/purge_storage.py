"""Local purge receipts and the backup catalogue; never stores private content."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path


def directory(database_path: Path) -> Path:
    return database_path.parent / 'runtime' / ('purge-' + database_path.name)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        os.chmod(temporary, 0o600)
        json.dump(value, handle, ensure_ascii=False, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def storage_lock(database_path: Path):
    root = directory(database_path)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / 'operation.lock').open('a') as handle:
        os.chmod(handle.name, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def receipt_path(database_path: Path, owner: str, kind: str, object_id: str) -> Path:
    key = hashlib.sha256(json.dumps([owner, kind, object_id]).encode()).hexdigest()
    return directory(database_path) / (key + '.json')


def register_backup(database_path: Path, backup_path: Path) -> None:
    """Caller holds storage_lock, including throughout creation of the snapshot."""
    path = directory(database_path) / 'backups.json'
    entries = json.loads(path.read_text()) if path.exists() else []
    value = str(backup_path.resolve())
    if value not in entries:
        write_json(path, [*entries, value])


def unregister_missing_backup(database_path: Path, backup_path: Path) -> None:
    if backup_path.exists():
        return
    path = directory(database_path) / 'backups.json'
    if path.exists():
        write_json(path, [value for value in json.loads(path.read_text()) if value != str(backup_path.resolve())])


def backups(database_path: Path) -> list[Path]:
    catalogue = directory(database_path) / 'backups.json'
    paths = {Path(value) for value in json.loads(catalogue.read_text())} if catalogue.exists() else set()
    # Includes pre-catalogue trial snapshots and interrupted offline restores.
    paths.update((database_path.parent / 'backups').rglob('*.sqlite3'))
    paths.update(database_path.parent.glob('.' + database_path.name + '.restore-*'))
    return sorted(path for path in paths if not str(path).endswith(('-wal', '-shm', '-journal')))


def receipts(database_path: Path):
    for path in directory(database_path).glob('*.json'):
        if path.name != 'backups.json':
            yield json.loads(path.read_text())
