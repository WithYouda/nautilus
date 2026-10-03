"""Local Obsidian vault: read-only note search, process-local selection tokens and capture.

The vault is an external, user-owned directory. Nautilus only reads it: every path is
derived from the saved connection plus a server-side relative path, and every open is
descriptor-relative with ``O_NOFOLLOW`` so a replaced link cannot escape the root.
No note body, excerpt or index is ever persisted outside the explicit snapshot capture.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import threading
import time
from pathlib import Path
from uuid import uuid4

from .credentials import CredentialStore
from .learning_domain import DomainError
from .learning_production import utc_timestamp
from .purge_storage import receipts

CONFIG_PREFIX = 'obsidian-local:'
PAGE_LIMIT = 50
TOKEN_TTL_SECONDS = 600
MAX_QUERY_LENGTH = 500
MAX_CURSOR_LENGTH = 4096
DISPLAY_TITLE_LIMIT = 300
EXCERPT_LIMIT = 200
CHECK_INTERVAL = 25
SKIPPED_DIRECTORIES = frozenset({'.obsidian', '.git', '.trash'})
CONNECTION_FIELDS = frozenset({'connection_id', 'revision', 'root_path', 'vault_name', 'enabled'})


def _failure(code: str, status: int = 409) -> DomainError:
    return DomainError(code, status)


def canonical_root(value) -> str:
    """Validate and canonicalize a user-supplied vault path without reading the vault."""
    if not isinstance(value, str):
        raise _failure('obsidian_path_invalid', 422)
    raw = value.strip()
    if not raw or len(raw) > 4096 or '\x00' in raw:
        raise _failure('obsidian_path_invalid', 422)
    if not raw.startswith('/') or '..' in raw.split('/'):
        raise _failure('obsidian_path_invalid', 422)
    try:
        resolved = Path(raw).resolve(strict=True)
    except (OSError, RuntimeError):
        raise _failure('obsidian_path_invalid', 422) from None
    try:
        info = resolved.lstat()
    except OSError:
        raise _failure('obsidian_path_unreadable', 422) from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise _failure('obsidian_path_invalid', 422)
    if not os.access(resolved, os.R_OK | os.X_OK):
        raise _failure('obsidian_path_unreadable', 422)
    return str(resolved)


def display_title(relative_path: str) -> str:
    name = relative_path.rsplit('/', 1)[-1]
    stem = name[:-3] if name.lower().endswith('.md') else name
    return (stem.strip() or '未命名笔记')[:DISPLAY_TITLE_LIMIT]


def _relative_parts(relative_path: str) -> list[str]:
    if (not isinstance(relative_path, str) or not relative_path or len(relative_path) > 4096
            or '\x00' in relative_path or relative_path.startswith('/')):
        raise _failure('obsidian_path_invalid', 422)
    parts = relative_path.split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise _failure('obsidian_path_invalid', 422)
    return parts


def _required_flags() -> None:
    """Refuse to run where descriptor-relative no-follow reads are unavailable."""
    missing = [name for name in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK') if not getattr(os, name, 0)]
    if missing or os.open not in os.supports_dir_fd or os.stat not in os.supports_dir_fd:
        raise _failure('obsidian_platform_unsupported', 503)


def _directory_flags() -> int:
    _required_flags()
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _file_flags() -> int:
    # O_NONBLOCK keeps a replaced FIFO from blocking inside open; regular files ignore it.
    _required_flags()
    return os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def _open_root_descriptor(path: Path, guard=None) -> int:
    """Walk the saved absolute path component by component, rejecting every link.

    ``guard`` is consulted immediately before every component is opened, so a
    revoked authorization cannot start a root open, and a permission is never
    reused as a pass for the rest of the walk.
    """
    flags = _directory_flags()
    if not path.is_absolute():
        raise _failure('obsidian_path_invalid', 422)
    try:
        if guard is not None:
            guard()
        descriptor = os.open('/', flags)
    except OSError:
        raise _failure('obsidian_vault_unavailable', 503) from None
    try:
        for part in path.parts[1:]:
            if guard is not None:
                guard()
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError:
        os.close(descriptor)
        raise _failure('obsidian_vault_unavailable', 503) from None


class Vault:
    """Read-only descriptor-relative view of one validated vault root."""

    def __init__(self, root: Path, descriptor: int) -> None:
        self.root = root
        self.descriptor = descriptor

    @classmethod
    def open(cls, root_path: str, guard=None) -> 'Vault':
        path = Path(root_path)
        return cls(path, _open_root_descriptor(path, guard))

    def close(self) -> None:
        try:
            os.close(self.descriptor)
        except OSError:
            pass

    def __enter__(self) -> 'Vault':
        return self

    def __exit__(self, *_error) -> None:
        self.close()

    def notes(self, failures: list[str], guard=None) -> list[str]:
        found: list[str] = []
        self._scan(self.descriptor, '', found, failures, guard)
        found.sort()
        return found

    def _scan(self, directory_fd: int, prefix: str, found: list[str], failures: list[str],
              guard=None) -> None:
        entries = []
        try:
            if guard is not None:
                guard()
            with os.scandir(directory_fd) as iterator:
                for entry in iterator:
                    try:
                        entries.append((entry.name, entry.is_symlink(),
                                        entry.is_dir(follow_symlinks=False),
                                        entry.is_file(follow_symlinks=False)))
                    except OSError:
                        failures.append(prefix + entry.name)
        except OSError:
            failures.append(prefix or '.')
            return
        for name, is_link, is_dir, is_file in sorted(entries):
            if guard is not None:
                guard()  # every remaining entry re-acquires its own permission
            relative = prefix + name
            if is_link:
                continue
            if is_dir:
                if name in SKIPPED_DIRECTORIES:
                    continue
                try:
                    if guard is not None:
                        guard()
                    child = os.open(name, _directory_flags(), dir_fd=directory_fd)
                except OSError:
                    failures.append(relative)
                    continue
                try:
                    self._scan(child, relative + '/', found, failures, guard)
                finally:
                    os.close(child)
            elif is_file and name.lower().endswith('.md'):
                found.append(relative)

    def read(self, relative_path: str, guard=None) -> dict:
        """Return {'status','raw','stable'} without ever following a link out of the root.

        ``guard`` is consulted immediately before every open and before every read
        chunk, so an authorization that changed after the previous check stops here
        instead of being carried into the next read.
        """
        parts = _relative_parts(relative_path)
        opened: list[int] = []
        try:
            directory_fd = self.descriptor
            for part in parts[:-1]:
                if guard is not None:
                    guard()
                directory_fd = os.open(part, _directory_flags(), dir_fd=directory_fd)
                opened.append(directory_fd)
            if guard is not None:
                guard()
            file_fd = os.open(parts[-1], _file_flags(), dir_fd=directory_fd)
        except FileNotFoundError:
            _close_all(opened)
            return {'status': 'missing', 'raw': b'', 'stable': True}
        except NotADirectoryError:
            _close_all(opened)
            return {'status': 'missing', 'raw': b'', 'stable': True}
        except OSError as error:
            _close_all(opened)
            return {'status': 'unsupported' if error.errno in (getattr(os, 'ELOOP', 40),)
                    else 'unreadable', 'raw': b'', 'stable': True}
        except BaseException:
            _close_all(opened)
            raise
        try:
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode):
                return {'status': 'unsupported', 'raw': b'', 'stable': True}
            chunks: list[bytes] = []
            while True:
                if guard is not None:
                    guard()
                chunk = os.read(file_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(file_fd)
            raw = b''.join(chunks)
            stable = ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                      == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                      and len(raw) == after.st_size)
            return {'status': 'ok', 'raw': raw, 'stable': stable}
        except OSError:
            return {'status': 'unreadable', 'raw': b'', 'stable': True}
        finally:
            os.close(file_fd)
            _close_all(opened)


def _close_all(descriptors: list[int]) -> None:
    for descriptor in descriptors:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _decode(raw: bytes) -> str:
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise _failure('obsidian_note_encoding', 422) from None


def _excerpt_line(lines: list[str], query: str) -> tuple[str, int, int]:
    """First content hit, or the document opening when only the path matched."""
    folded = query.casefold()
    for index, line in enumerate(lines):
        if folded and folded in line.casefold():
            text = line.strip() or line
            return text[:EXCERPT_LIMIT], index + 1, index + 1
    for index, line in enumerate(lines):
        if line.strip():
            return line.strip()[:EXCERPT_LIMIT], index + 1, index + 1
    return '', 1, 1


class ObsidianService:
    """Owner-scoped connection settings plus the per-scope in-process candidate store."""

    def __init__(self, credentials: CredentialStore, materials) -> None:
        self.credentials = credentials
        self.materials = materials
        self._lock = threading.RLock()
        self._candidates: dict[tuple[str, str, str], dict] = {}
        self._generations: dict[str, int] = {}

    # ------------------------------------------------------------------
    # 连接配置
    # ------------------------------------------------------------------
    def _key(self, owner: str) -> str:
        return f'{CONFIG_PREFIX}{owner}'

    def connection(self, owner: str) -> dict | None:
        raw = self.credentials.get(self._key(owner))
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            raise _failure('obsidian_connection_unreadable', 503) from None
        if (not isinstance(value, dict) or set(value) != CONNECTION_FIELDS
                or not isinstance(value.get('connection_id'), str) or not value['connection_id']
                or not isinstance(value.get('revision'), int) or isinstance(value['revision'], bool)
                or value['revision'] < 1
                or not isinstance(value.get('root_path'), str) or not value['root_path'].startswith('/')
                or not isinstance(value.get('vault_name'), str)
                or not isinstance(value.get('enabled'), bool)):
            raise _failure('obsidian_connection_unreadable', 503)
        return dict(value)

    def connect(self, owner: str, root_path, expected_revision) -> dict:
        canonical = canonical_root(root_path)
        # Same order as capture/purge (materials.lock -> obsidian._lock): a capture that
        # already holds the commit boundary finishes first, otherwise it sees the new
        # revision and generation and must refuse.
        with self.materials.lock, self._lock:
            existing = self.connection(owner)
            if expected_revision is None:
                if existing is not None:
                    raise _failure('obsidian_connection_revision', 409)
                record = dict(connection_id=str(uuid4()), revision=1, root_path=canonical,
                              vault_name=Path(canonical).name or canonical, enabled=True)
            else:
                if (not isinstance(expected_revision, int) or isinstance(expected_revision, bool)
                        or existing is None or existing['revision'] != expected_revision):
                    raise _failure('obsidian_connection_revision', 409)
                same_root = existing['root_path'] == canonical
                record = dict(connection_id=existing['connection_id'] if same_root else str(uuid4()),
                              revision=existing['revision'] + 1, root_path=canonical,
                              vault_name=Path(canonical).name or canonical, enabled=True)
            self.credentials.set(self._key(owner), json.dumps(record, ensure_ascii=False))
            self.invalidate(owner)
            return record

    def disconnect(self, owner: str, expected_revision) -> dict:
        with self.materials.lock, self._lock:
            existing = self.connection(owner)
            if (not isinstance(expected_revision, int) or isinstance(expected_revision, bool)
                    or existing is None or existing['revision'] != expected_revision):
                raise _failure('obsidian_connection_revision', 409)
            record = {**existing, 'enabled': False, 'revision': existing['revision'] + 1}
            self.credentials.set(self._key(owner), json.dumps(record, ensure_ascii=False))
            self.invalidate(owner)
            return record

    # ------------------------------------------------------------------
    # 候选与读取代次
    # ------------------------------------------------------------------
    def invalidate(self, owner: str) -> None:
        """Drop this owner's candidates and advance the read generation."""
        with self._lock:
            self._generations[owner] = self._generations.get(owner, 0) + 1
            for key in [key for key in self._candidates if key[0] == owner]:
                self._candidates.pop(key, None)

    def _generation(self, owner: str) -> int:
        with self._lock:
            return self._generations.get(owner, 0)

    def require_generation(self, owner: str, generation: int) -> None:
        """Called under the material lock so a stale capture cannot write after a purge."""
        if self._generation(owner) != generation:
            raise _failure('obsidian_search_invalidated', 409)

    def _permit(self, owner: str, record: dict, generation: int) -> None:
        """Grant one local read for the operation's frozen connection snapshot.

        The check runs in a short critical section against the same lock that
        ``invalidate`` uses, so a completed revocation always wins over a read
        that has not been permitted yet.
        """
        with self._lock:
            if self._generations.get(owner, 0) != generation:
                raise _failure('obsidian_search_invalidated', 409)
            current = self.connection(owner)
            if (current is None or not current['enabled']
                    or current['connection_id'] != record['connection_id']
                    or current['revision'] != record['revision']):
                raise _failure('obsidian_connection_revision', 409)

    def _check(self, owner: str, record: dict, generation: int) -> None:
        self._permit(owner, record, generation)

    def _purge_pending(self, owner: str) -> bool:
        try:
            for report in receipts(self.materials.db.database_path):
                if (isinstance(report, dict) and report.get('owner') == owner
                        and report.get('kind') == 'material' and report.get('status') != 'complete'):
                    return True
        except (OSError, ValueError):
            return False
        return False

    def _enabled_record(self, identity, kind: str, scope_id: str) -> tuple[str, dict]:
        """Resolve owner/scope before any vault access, then require an enabled connection."""
        owner = self.materials.owned_scope(identity, kind, scope_id)
        record = self.connection(owner)
        if record is None or not record['enabled']:
            raise _failure('obsidian_disconnected', 409)
        return owner, record

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    def search(self, identity, kind: str, scope_id: str, *, connection_id, connection_revision,
               query, after) -> dict:
        owner, record = self._enabled_record(identity, kind, scope_id)
        if (not isinstance(query, str) or len(query) > MAX_QUERY_LENGTH or '\x00' in query):
            raise _failure('obsidian_query_invalid', 422)
        if after is not None and (not isinstance(after, str) or len(after) > MAX_CURSOR_LENGTH
                                  or '\x00' in after or after.startswith('/')):
            raise _failure('obsidian_query_invalid', 422)
        if record['connection_id'] != connection_id or record['revision'] != connection_revision:
            raise _failure('obsidian_connection_revision', 409)
        generation = self._generation(owner)

        def guard():
            self._check(owner, record, generation)

        failures: list[str] = []
        with Vault.open(record['root_path'], guard) as vault:
            paths = vault.notes(failures, guard)
            folded = query.casefold()
            matches: dict[str, tuple[str, str, int, int]] = {}
            for index, relative in enumerate(paths):
                if index % CHECK_INTERVAL == 0:
                    self._check(owner, record, generation)
                if not folded or folded in relative.casefold():
                    matches[relative] = ('', '', 0, 0)
            if folded:
                for relative in paths:
                    if relative in matches:
                        continue
                    result = vault.read(relative, guard)
                    if result['status'] != 'ok':
                        failures.append(relative)
                        continue
                    try:
                        text = _decode(result['raw'])
                    except DomainError:
                        failures.append(relative)
                        continue
                    lines = text.splitlines()
                    if folded in text.casefold():
                        excerpt, start, end = _excerpt_line(lines, query)
                        matches[relative] = (excerpt, hashlib.sha256(result['raw']).hexdigest(),
                                             start, end)
            self._check(owner, record, generation)
            ordered = sorted(matches)
            remaining = [path for path in ordered if after is None or path > after]
            page = remaining[:PAGE_LIMIT]
            has_more = len(remaining) > PAGE_LIMIT
            # The cursor advances by processed candidates, never by successfully
            # assembled items: a page whose files are all unreadable still moves on.
            next_after = page[-1] if has_more and page else None
            items = []
            tokens: dict[str, dict] = {}
            for index, relative in enumerate(page):
                if index % CHECK_INTERVAL == 0:
                    self._check(owner, record, generation)
                excerpt, digest, start, end = matches[relative]
                if not digest:
                    result = vault.read(relative, guard)
                    if result['status'] != 'ok':
                        failures.append(relative)
                        continue
                    try:
                        lines = _decode(result['raw']).splitlines()
                    except DomainError:
                        failures.append(relative)
                        continue
                    excerpt, start, end = _excerpt_line(lines, query if start else '')
                    digest = hashlib.sha256(result['raw']).hexdigest()
                token = secrets.token_urlsafe(24)
                tokens[token] = {'relative_path': relative, 'sha256': digest,
                                 'created_at': time.monotonic()}
                items.append({'relative_path': relative, 'title': display_title(relative),
                              'excerpt': excerpt, 'excerpt_start_line': start,
                              'excerpt_end_line': end, 'sha256': digest,
                              'selection_token': token})
            with self._lock:
                # Check and publish inside one critical section: an invalidation either
                # lands before this point (and the search refuses) or clears the entry
                # afterwards, so no stale candidate survives a completed revocation.
                self._check(owner, record, generation)
                self._release_expired()
                self._candidates[(owner, kind, scope_id)] = {
                    'generation': generation, 'connection_id': record['connection_id'],
                    'revision': record['revision'], 'tokens': tokens,
                    'created_at': time.monotonic()}
            return {'items': items, 'next_after': next_after,
                    'has_more': has_more, 'complete': not failures,
                    'unreadable_count': len(failures)}

    def _release_expired(self) -> None:
        now = time.monotonic()
        for key in [key for key, entry in self._candidates.items()
                    if now - entry['created_at'] > TOKEN_TTL_SECONDS]:
            self._candidates.pop(key, None)

    # ------------------------------------------------------------------
    # 捕获
    # ------------------------------------------------------------------
    def capture(self, identity, kind: str, scope_id: str, *, selection_token) -> dict:
        owner, record = self._enabled_record(identity, kind, scope_id)
        if not isinstance(selection_token, str) or not selection_token or len(selection_token) > 200:
            raise _failure('obsidian_selection_invalid', 409)
        now = time.monotonic()
        with self._lock:
            entry = self._candidates.get((owner, kind, scope_id))
            token = entry['tokens'].get(selection_token) if entry else None
            if token is None or now - token['created_at'] > TOKEN_TTL_SECONDS:
                raise _failure('obsidian_selection_invalid', 409)
            generation = entry['generation']
            connection_id = entry['connection_id']
            revision = entry['revision']
            relative_path = token['relative_path']
            expected = token['sha256']
        # A replaced or re-authorized connection, a purge, or a newer search page
        # all invalidate the page this token came from.
        if record['connection_id'] != connection_id or record['revision'] != revision:
            raise _failure('obsidian_selection_invalid', 409)
        if self._generation(owner) != generation:
            raise _failure('obsidian_selection_invalid', 409)
        if self._purge_pending(owner):
            raise _failure('obsidian_purge_pending', 409)
        def guard():
            self._check(owner, record, generation)

        with Vault.open(record['root_path'], guard) as vault:
            result = vault.read(relative_path, guard)
            if result['status'] == 'missing':
                raise _failure('obsidian_source_changed', 409)
            if result['status'] != 'ok':
                raise _failure('obsidian_note_unsupported', 422)
            digest = hashlib.sha256(result['raw']).hexdigest()
            if not result['stable'] or digest != expected:
                raise _failure('obsidian_source_changed', 409)
            content = _decode(result['raw'])
        if not content.strip():
            raise _failure('obsidian_note_empty', 422)
        filename = relative_path.rsplit('/', 1)[-1]
        return self.materials.capture_obsidian(
            identity, kind, scope_id, connection_id=record['connection_id'],
            vault_name=record['vault_name'], relative_path=relative_path, byte_sha256=digest,
            line_count=max(1, len(content.splitlines())), title=display_title(relative_path),
            filename=filename, content=content, raw=result['raw'], generation=generation)

    # ------------------------------------------------------------------
    # 来源变化检查
    # ------------------------------------------------------------------
    def source_status(self, identity, kind: str, scope_id: str, version_id: str) -> dict:
        owner = self.materials.owned_scope(identity, kind, scope_id)
        versions = self.materials.list(identity, kind, scope_id)['versions']
        version = next((item for item in versions if item['id'] == version_id), None)
        if version is None:
            raise DomainError('not_found', 404)
        try:
            provenance = json.loads(version.get('provenance_json') or '{}')
        except (TypeError, ValueError):
            provenance = {}
        if not isinstance(provenance, dict) or provenance.get('kind') != 'obsidian_local':
            return {'status': 'not_applicable', 'checked_at': None}
        relative_path = provenance.get('relative_path')
        expected = provenance.get('sha256')
        record = self.connection(owner)
        if (record is None or not record['enabled']
                or record['connection_id'] != provenance.get('connection_id')
                or not isinstance(relative_path, str) or not isinstance(expected, str)):
            return {'status': 'disconnected', 'checked_at': None}
        generation = self._generation(owner)

        def guard():
            self._check(owner, record, generation)

        try:
            with Vault.open(record['root_path'], guard) as vault:
                result = vault.read(relative_path, guard)
        except DomainError as error:
            # A revoked read is a conflict, not "this vault is unavailable"; it must
            # never be reported as a successful same/changed conclusion.
            if error.code == 'obsidian_vault_unavailable':
                return {'status': 'unavailable', 'checked_at': utc_timestamp()}
            raise
        self._check(owner, record, generation)
        if result['status'] == 'missing':
            return {'status': 'missing', 'checked_at': utc_timestamp()}
        if result['status'] != 'ok' or not result['stable']:
            return {'status': 'unavailable', 'checked_at': utc_timestamp()}
        digest = hashlib.sha256(result['raw']).hexdigest()
        return {'status': 'same_as_snapshot' if digest == expected else 'changed',
                'checked_at': utc_timestamp()}
