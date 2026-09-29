"""Opt-in local diagnostic events. Never serializes request bodies or log messages."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

from .purge_storage import write_json

MAX_BYTES = 1024 * 1024
BACKUP_COUNT = 3


class DiagnosticService:
    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.RLock()
        self.writers = {}
        self.failures = set()

    def directory(self, owner):
        return self.root / hashlib.sha256(owner.encode()).hexdigest()

    def enabled(self, owner):
        path = self.directory(owner) / 'settings.json'
        try:
            return json.loads(path.read_text()).get('enabled') is True if path.exists() else False
        except (OSError, ValueError):
            self.failures.add(owner)
            return False

    def status(self, owner):
        with self.lock:
            return {'enabled': self.enabled(owner), 'storage_error': owner in self.failures,
                    'retention_bytes': MAX_BYTES * (BACKUP_COUNT + 1)}

    def configure(self, owner, enabled):
        with self.lock:
            write_json(self.directory(owner) / 'settings.json', {'enabled': enabled})
            self.failures.discard(owner)
            if not enabled and owner in self.writers:
                self.writers.pop(owner).close()
            return self.status(owner)

    def record(self, owner, *, module, event, level='info', request_id=None, **fields):
        # These keyword fields come from explicit instrumentation, never arbitrary payloads.
        with self.lock:
            if not self.enabled(owner):
                return
            row = {'id': str(uuid4()), 'at': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                   'module': module, 'event': event, 'level': level}
            if request_id:
                row['request_id'] = request_id
            row.update({key: value for key, value in fields.items() if key in {
                'method', 'route', 'status', 'duration_ms', 'code', 'result', 'failed_count', 'cleared_count',
                'source', 'line',
            }})
            try:
                writer = self.writers.get(owner)
                if writer is None:
                    directory = self.directory(owner)
                    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                    path = directory / 'events.jsonl'
                    writer = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding='utf-8')
                    os.chmod(path, 0o600)
                    self.writers[owner] = writer
                value = json.dumps(row, ensure_ascii=False, separators=(',', ':'))
                record = logging.LogRecord('diagnostic', logging.INFO, '', 0, value, (), None)
                # Call the write path directly so errors remain observable in settings.
                if writer.shouldRollover(record):
                    writer.doRollover()
                    os.chmod(writer.baseFilename, 0o600)
                writer.stream.write(value + '\n')
                writer.flush()
                self.failures.discard(owner)
            except (OSError, ValueError):
                self.failures.add(owner)

    def read(self, owner):
        with self.lock:
            rows = []
            directory = self.directory(owner)
            for suffix in [f'.{number}' for number in range(BACKUP_COUNT, 0, -1)] + ['']:
                path = directory / ('events.jsonl' + suffix)
                try:
                    if path.exists():
                        for line in path.read_text().splitlines():
                            try:
                                rows.append(json.loads(line))
                            except ValueError:
                                continue  # Interrupted final line is not a complete event.
                except OSError:
                    self.failures.add(owner)
            return {**self.status(owner), 'entries': rows[-500:]}

    def clear(self, owner):
        with self.lock:
            if owner in self.writers:
                self.writers.pop(owner).close()
            directory = self.directory(owner)
            for suffix in ['', *[f'.{number}' for number in range(1, BACKUP_COUNT + 1)]]:
                (directory / ('events.jsonl' + suffix)).unlink(missing_ok=True)
            self.failures.discard(owner)

    def close(self):
        with self.lock:
            for writer in self.writers.values():
                writer.close()
            self.writers.clear()


class RuntimeDiagnosticHandler(logging.Handler):
    """Expose source location and exception category, never message/args/traceback text."""
    def __init__(self, service, owner):
        super().__init__(logging.WARNING)
        self.service, self.owner = service, owner

    def emit(self, record):
        error = record.exc_info[1] if record.exc_info else None
        known = {'TimeoutError', 'ValueError', 'OSError', 'RuntimeError', 'CancelledError',
                 'ConnectError', 'ReadTimeout', 'OperationalError', 'IntegrityError', 'DomainError'}
        code = type(error).__name__ if error and type(error).__name__ in known else 'runtime_error' if error else 'runtime_warning'
        self.service.record(self.owner, module='runtime', event='runtime.error' if record.levelno >= logging.ERROR else 'runtime.warning',
                            level='error' if record.levelno >= logging.ERROR else 'warning', code=code,
                            source=record.module, line=record.lineno)
