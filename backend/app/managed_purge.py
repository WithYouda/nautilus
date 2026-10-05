"""User-triggered erasure of online content and registered local snapshots."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing

from .learning_domain import DomainError
from .learning_production import file_sha256, utc_timestamp, validate_learning_path
from .purge_content import columns, erase
from .purge_storage import backups, receipt_path, register_backup, storage_lock, write_json
from .commitment_integrations import PURGE_TABLES
from .coach_integrations import PURGE_TABLES as COACH_PURGE_TABLES


EXTERNAL_LIMITS = [
    '外部 AI / 搜索服务已接收的内容：当前没有可核实的远端删除接口，未确认清除。',
    '用户自行复制、导出或手工粘贴到其他记录的内容，以及未登记的外部副本：无法自动定位，未确认清除。',
    '其他已打开的浏览器页面、浏览器自行保存的历史副本：不能远程确认清除，请关闭或刷新相关页面。',
    '操作系统快照、磁盘历史块及存储介质内部副本：应用无法验证清除；本结果针对受管理 SQLite 文件及其日志。',
]
TABLES = {'plan_content': ('learning_plan_private', 'object_id'),
          'path_content': ('learning_path_version','id'),
          'module_content': ('learning_plan_private', 'object_id'),
          'artifact': ('learning_raw_artifact', 'artifact_id'),
          'graph_relation': ('learning_outcome_relation', 'id'), 'graph_run': ('learning_graph_run','id'),
          'verification': ('learning_verification', 'id'), 'completion': ('learning_completion', 'id'),
          'practice': ('learning_practice', 'id'),
          'delayed': ('learning_delayed_follow_up', 'id')}
TABLES.update(PURGE_TABLES)
TABLES.update(COACH_PURGE_TABLES)


def compact(connection):
    # secure_delete also covers pages changed before VACUUM; MEMORY avoids a
    # separate temporary database on disk during compaction. Truncate old WAL.
    connection.execute('PRAGMA secure_delete=ON')
    connection.execute('PRAGMA temp_store=MEMORY')
    connection.execute('VACUUM')
    checkpoint = connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
    if checkpoint[0] != 0:
        raise sqlite3.OperationalError('checkpoint_busy')
    if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or connection.execute('PRAGMA foreign_key_check').fetchone():
        raise sqlite3.DatabaseError('purge_integrity_failed')


def scrub_snapshot(path, owner, kind, object_id, now, submission_ids=(), artifact_ids=()):
    path = validate_learning_path(path)
    # Opening a read-only WAL database can create equally read-only sidecars.
    # Refuse before opening so restoring the file's permission makes retry work.
    if not path.is_file() or not os.access(path, os.W_OK):
        raise PermissionError('backup_not_writable')
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, isolation_level=None)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA busy_timeout=1000')
        connection.execute('PRAGMA secure_delete=ON')
        connection.execute('PRAGMA synchronous=FULL')
        # Offline snapshots can predate WAL or use PERSIST journals. DELETE
        # mode removes old rollback-journal payloads after the scrub commits.
        if not columns(connection, 'learning_raw_artifact'):
            if columns(connection, 'ai_run') and columns(connection, 'conversation'):
                # Material erasure registers both databases. These learning-only
                # object kinds have no ordinary-chat copies in their contracts;
                # material erasure itself uses the dedicated cross-DB scrubber.
                return
            raise ValueError('unrecognized_backup')
        connection.execute('PRAGMA journal_mode=DELETE')
        connection.execute('BEGIN IMMEDIATE')
        try:
            erase(connection, owner, kind, object_id, now, submission_ids=submission_ids, artifact_ids=artifact_ids)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        compact(connection)
    manifest_path = path.with_suffix('.json')
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        manifest.update(sha256=file_sha256(path), content_erased_at=now)
        write_json(manifest_path, manifest)


class ManagedPurge:
    def __init__(self, learning):
        self.learning = learning
        self.db = learning.database
        self.path = self.db.database_path

    def _owner(self, identity, kind, object_id):
        if kind not in TABLES:
            raise DomainError('not_found', 404)
        owner = self.learning.principal(identity).owner_id
        table, key = TABLES[kind]
        suffix = ' AND kind=?' if kind in {'plan_content','module_content'} else ''
        params = (owner,object_id,kind.split('_')[0]) if suffix else (owner,object_id)
        if not self.db.fetchone(f'SELECT 1 FROM {table} WHERE owner_id=? AND {key}=?' + suffix, params):
            raise DomainError('not_found', 404)
        return owner

    def status(self, identity, kind, object_id):
        owner = self._owner(identity, kind, object_id)
        path = receipt_path(self.path, owner, kind, object_id)
        if not path.exists():
            return dict(status='not_requested', files=[], external_limits=EXTERNAL_LIMITS)
        report = json.loads(path.read_text())
        return {key: report[key] for key in ('status', 'files', 'external_limits', 'updated_at')}

    def run(self, identity, kind, object_id, online_purge):
        owner = self._owner(identity, kind, object_id)
        principal = self.learning.principal(identity)
        report_path = receipt_path(self.path, owner, kind, object_id)
        with storage_lock(self.path), self.db._lock:
            rows = self.db.fetchall('SELECT id,artifact_id FROM learning_verification_submission WHERE owner_id=? AND '
                + ('artifact_id=?' if kind == 'artifact' else 'verification_id=?'), (owner, object_id)) if kind in {'artifact', 'verification'} else []
            submissions = [row['id'] for row in rows]
            artifacts = [row['artifact_id'] for row in rows if row['artifact_id']]
            previous_report = json.loads(report_path.read_text()) if report_path.exists() else None
            report = dict(owner=owner, kind=kind, object_id=object_id, status='pending',
                          submission_ids=submissions, artifact_ids=artifacts, files=[], external_limits=EXTERNAL_LIMITS, updated_at=utc_timestamp())
            # Intent is durable BEFORE erasure. A process interruption remains
            # visibly unfinished, and the same object can safely be retried.
            write_json(report_path, report)
            self.db.connection.execute('PRAGMA secure_delete=ON')
            self.db.connection.execute('PRAGMA synchronous=FULL')
            try:
                result = online_purge()
            except DomainError:
                # A rejected command (e.g. stale version) has not authorized or
                # committed erasure. Do not turn it into a permanent pending job.
                if previous_report:
                    write_json(report_path, previous_report)
                else:
                    report_path.unlink()
                raise
            try:
                with self.db.transaction(immediate=True) as connection:
                    erase(connection, owner, kind, object_id, report['updated_at'], submission_ids=submissions, artifact_ids=artifacts)
                    self.learning.core._audit(connection, principal,
                                              'RedactManagedContent', 'succeeded', object_id)
                compact(self.db.connection)
                report['files'].append(dict(name='当前学习库及日志', status='cleared'))
            except (sqlite3.Error, ValueError, OSError):
                report['files'].append(dict(name='当前学习库及日志', status='failed', reason='内容已隐藏，但历史内容或数据库日志尚未确认清除，请重试。'))
            try:
                candidates = backups(self.path)
            except (ValueError, OSError):
                candidates = []
                report['files'].append(dict(name='备份目录', status='failed', reason='无法读取受管理备份清单，请检查目录后重试。'))
            for candidate in candidates:
                name = candidate.name
                try:
                    resolved = validate_learning_path(candidate)
                    if resolved == self.path.resolve() or (resolved.exists() and os.path.samefile(resolved, self.path)):
                        raise ValueError('backup_aliases_online_database')
                    if candidate.is_symlink():
                        raise ValueError('backup_is_symlink')
                    register_backup(self.path, candidate)
                    scrub_snapshot(resolved, owner, kind, object_id, report['updated_at'], submissions, artifacts)
                    report['files'].append(dict(name=name, status='cleared'))
                except (sqlite3.Error, ValueError, OSError, RuntimeError):
                    report['files'].append(dict(name=name, status='failed', reason='文件缺失、不可写、占用或格式异常；未确认清除，请检查后重试。'))
                write_json(report_path, report)
            report['status'] = 'complete' if all(item['status'] == 'cleared' for item in report['files']) else 'partial'
            report['updated_at'] = utc_timestamp()
            write_json(report_path, report)
            result['purge'] = self.status(identity, kind, object_id)
            return result
