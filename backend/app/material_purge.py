"""Erase a material group and run copies from both local databases and managed snapshots."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing

from .learning_domain import DomainError
from .learning_production import utc_timestamp, validate_learning_path, file_sha256
from .managed_purge import EXTERNAL_LIMITS, compact
from .purge_storage import backups, receipt_path, register_backup, storage_lock, write_json


def _has_table(c, table):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _references(snapshot, material_id):
    try:
        scope = json.loads(snapshot or '{}').get('source_scope') or {}
    except (TypeError, ValueError):
        return False
    return material_id in scope.get('material_ids', [])


def _marker(snapshot, material_ids):
    try:
        old = json.loads(snapshot or '{}')
    except (TypeError, ValueError):
        old = {}
    # Keep reply lineage so existing UI history remains navigable.
    all_ids = list(dict.fromkeys([*(old.get('source_scope') or {}).get('material_ids', []), *material_ids]))
    return json.dumps({'reply':old.get('reply', {}),
                       'source_scope':{'purged':True,'material_ids':all_ids}}, ensure_ascii=False)


def _source_run_ids(c, owner, material_id, kind):
    if not _has_table(c, 'learning_task_material'):
        return set()
    result = set()
    for row in c.execute('SELECT provenance_json,scope_kind FROM learning_task_material WHERE owner_id=? AND material_id=?',
                         (owner,material_id)):
        if row['scope_kind'] != kind:
            continue
        try:
            provenance = json.loads(row['provenance_json'] or '{}')
        except ValueError:
            continue
        if provenance.get('kind') == 'web' and provenance.get('run_id'):
            result.add(provenance['run_id'])
    return result


def erase_learning(c, owner, material_id, now, source_message_ids=(), source_turn_ids=()):
    source_ids = _source_run_ids(c,owner,material_id,'discussion') | set(source_turn_ids)
    if _has_table(c, 'learning_task_material'):
        c.execute('''UPDATE learning_task_material SET title=NULL,content=NULL,url=NULL,provenance_json='{}',purged_at=?
            WHERE owner_id=? AND material_id=? AND purged_at IS NULL''', (now, owner, material_id))
    if not _has_table(c, 'learning_discussion_turn'):
        return []
    direct = [row['id'] for row in c.execute('''SELECT t.id,t.provider_snapshot_json,t.sources_json FROM learning_discussion_turn t
        JOIN learning_question_discussion q ON q.id=t.discussion_id WHERE q.owner_id=?''', (owner,))
        if row['id'] in source_ids or _references(row['provider_snapshot_json'], material_id)
        or any(ref.get('message_id') in source_message_ids for ref in json.loads(row['sources_json'] or '[]'))]
    # Same-discussion history and explicit cross-discussion retrieval may carry source text.
    all_turns = [dict(row) for row in c.execute('''SELECT t.id,t.provider_snapshot_json,t.sources_json FROM learning_discussion_turn t
        JOIN learning_question_discussion q ON q.id=t.discussion_id WHERE q.owner_id=?''', (owner,))]
    changed = True
    while changed:
        expanded = set(direct)
        for row in all_turns:
            snapshot = json.loads(row['provider_snapshot_json'] or '{}')
            history = (snapshot.get('reply') or {}).get('history_turn_ids', [])
            refs = json.loads(row['sources_json'] or '[]')
            if (set(history).intersection(direct) or any(ref.get('turn_id') in direct for ref in refs)):
                expanded.add(row['id'])
        changed = len(expanded) > len(direct)
        direct = sorted(expanded)
    # A discussion may have copied the source turn via local retrieval. Erase its downstream discussions too.
    affected = set(direct)
    if _has_table(c, 'learning_discussion_dependency') and direct:
        discussion_ids = {row[0] for row in c.execute(
            'SELECT DISTINCT discussion_id FROM learning_discussion_turn WHERE id IN (' + ','.join('?' for _ in direct) + ')', direct)}
        while discussion_ids:
            children = {row[0] for row in c.execute('SELECT discussion_id FROM learning_discussion_dependency WHERE source_discussion_id IN (' + ','.join('?' for _ in discussion_ids) + ')', tuple(discussion_ids))}
            new_turns = {row[0] for row in c.execute('SELECT id FROM learning_discussion_turn WHERE discussion_id IN (' + ','.join('?' for _ in children) + ')', tuple(children))} if children else set()
            if not new_turns - affected:
                break
            affected.update(new_turns)
            discussion_ids = children
    for turn_id in affected:
        row = c.execute('SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?', (turn_id,)).fetchone()
        c.execute('''UPDATE learning_discussion_turn SET user_content=NULL,assistant_content=NULL,reasoning_content=NULL,
            sources_json='[]',provider_snapshot_json=?,status='purged',reason='content_purged',finished_at=?
            WHERE id=?''', (_marker(row[0], [material_id]), now, turn_id))
    return sorted(affected)


def _ordinary_targets(c, owner, material_id, source_run_ids=()):
    if not _has_table(c,'ai_run'):
        return []
    rows = [dict(row) for row in c.execute('''SELECT id,conversation_id,request_message_id,response_message_id,
        context_snapshot_id,config_snapshot_json FROM ai_run WHERE identity_id=?''',(owner,))]
    targets = {row['id'] for row in rows if row['id'] in source_run_ids or _references(row['config_snapshot_json'], material_id)}
    while True:
        messages = {mid for row in rows if row['id'] in targets
                    for mid in (row['request_message_id'],row['response_message_id']) if mid}
        expanded = set(targets)
        for row in rows:
            snapshot = json.loads(row['config_snapshot_json'] or '{}')
            reply = snapshot.get('reply') or {}
            history = (snapshot.get('source_history_message_ids') or [])
            legacy_parent = ('source_history_message_ids' not in snapshot and
                             (reply.get('parent_answer_id') in messages or reply.get('requested_parent') in messages))
            if row['id'] not in targets and (set(history).intersection(messages) or legacy_parent or
                reply.get('question_id') in messages):
                expanded.add(row['id'])
        if expanded == targets:
            return [row for row in rows if row['id'] in targets]
        targets = expanded


def _discussion_targets(c, owner, material_ids, source_turn_ids=(), source_message_ids=()):
    if not _has_table(c,'learning_discussion_turn'):
        return set()
    rows = [dict(row) for row in c.execute('''SELECT t.id,t.discussion_id,t.provider_snapshot_json,t.sources_json
        FROM learning_discussion_turn t JOIN learning_question_discussion q ON q.id=t.discussion_id
        WHERE q.owner_id=?''',(owner,))]
    targets = set(source_turn_ids)
    for row in rows:
        refs = json.loads(row['sources_json'] or '[]')
        if any(_references(row['provider_snapshot_json'], group) for group in material_ids) or any(
            ref.get('message_id') in source_message_ids for ref in refs):
            targets.add(row['id'])
    while True:
        expanded = set(targets)
        source_discussions = {row['discussion_id'] for row in rows if row['id'] in targets}
        dependent_discussions = set()
        if source_discussions and _has_table(c,'learning_discussion_dependency'):
            dependent_discussions = {row[0] for row in c.execute('''SELECT discussion_id FROM learning_discussion_dependency
                WHERE source_discussion_id IN (''' + ','.join('?' for _ in source_discussions) + ')',tuple(source_discussions))}
        for row in rows:
            snapshot = json.loads(row['provider_snapshot_json'] or '{}')
            refs = json.loads(row['sources_json'] or '[]')
            if (row['discussion_id'] in dependent_discussions or
                set((snapshot.get('reply') or {}).get('history_turn_ids',[])).intersection(targets) or
                any(ref.get('turn_id') in targets for ref in refs)):
                expanded.add(row['id'])
        if expanded == targets:
            return targets
        targets = expanded


def _group_closure(learning, ordinary, owner, initial, previous):
    groups = set(previous.get('material_ids',[])) | {initial}
    rows = [dict(row) for row in learning.execute('''SELECT material_id,provenance_json FROM learning_task_material
        WHERE owner_id=? AND purged_at IS NULL''',(owner,))]
    while True:
        ordinary_sources = set(previous.get('source_run_ids',[]))
        discussion_sources = set(previous.get('source_turn_ids',[]))
        for group in groups:
            ordinary_sources.update(_source_run_ids(learning,owner,group,'conversation'))
            discussion_sources.update(_source_run_ids(learning,owner,group,'discussion'))
        ordinary_targets = {run['id']:run for group in groups
                            for run in _ordinary_targets(ordinary,owner,group,ordinary_sources)}
        message_ids = {mid for run in ordinary_targets.values()
                       for mid in (run['request_message_id'],run['response_message_id']) if mid}
        message_ids.update(previous.get('source_message_ids',[]))
        discussion_targets = _discussion_targets(learning,owner,groups,discussion_sources,message_ids)
        expanded = set(groups)
        for row in rows:
            try:
                origin = json.loads(row['provenance_json'] or '{}')
            except ValueError:
                continue
            if origin.get('kind') == 'web' and origin.get('run_id') in (ordinary_targets.keys() | discussion_targets):
                expanded.add(row['material_id'])
        if expanded == groups:
            return sorted(groups), ordinary_sources, discussion_sources, list(ordinary_targets.values()), message_ids
        groups = expanded


def erase_ordinary(c, owner, material_id, now, source_run_ids=()):
    if not _has_table(c, 'ai_run'):
        return []
    runs = _ordinary_targets(c,owner,material_id,source_run_ids)
    affected = [run['id'] for run in runs]
    affected_messages = {mid for run in runs for mid in (run['request_message_id'],run['response_message_id']) if mid}
    for run in runs:
        c.execute('''UPDATE ai_run SET status='canceled',config_snapshot_json=?,error_kind='content_purged',
            error_message=NULL,finished_at=?,updated_at=? WHERE id=?''',
            (_marker(run['config_snapshot_json'], [material_id]), now, now, run['id']))
        if run['context_snapshot_id']:
            c.execute("UPDATE context_snapshot SET summary='',payload='{}' WHERE id=?", (run['context_snapshot_id'],))
    for message_id in affected_messages:
        c.execute("UPDATE message SET content='',reasoning_content='',status='canceled',updated_at=? WHERE id=?", (now,message_id))
    if affected and _has_table(c, 'conversation_title_run'):
        title_runs = [dict(row) for row in c.execute('SELECT id,conversation_id,trigger_ai_run_id,input_message_ids_json FROM conversation_title_run WHERE identity_id=?', (owner,))]
        for title_run in title_runs:
            try:
                inputs = json.loads(title_run['input_message_ids_json'] or '[]')
            except ValueError:
                inputs = []
            if title_run['trigger_ai_run_id'] in affected or bool(affected_messages.intersection(inputs)):
                c.execute('''UPDATE conversation_title_run SET status='superseded',generated_title=NULL,
                    input_message_ids_json='[]',config_snapshot_json='{}',error_message=NULL,
                    error_kind='content_purged',finished_at=?,updated_at=? WHERE id=?''', (now,now,title_run['id']))
        for conversation_id in {run['conversation_id'] for run in runs}:
            c.execute("""UPDATE conversation SET title='新的学习对话',title_source='placeholder',
                title_generation_status='idle',title_revision=title_revision+1,title_generated_at=NULL,updated_at=?
                WHERE id=? AND identity_id=? AND title_source IN ('ai','fallback')""", (now,conversation_id,owner))
    return affected


def _scrub_snapshot(path, owner, material_ids, now, source_run_ids=(), source_message_ids=(), source_turn_ids=()):
    if path.is_symlink():
        raise ValueError('backup_is_symlink')
    path = validate_learning_path(path)
    if not path.is_file() or not os.access(path, os.W_OK):
        raise OSError('backup_not_writable')
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw',uri=True,isolation_level=None)) as c:
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA secure_delete=ON')
        c.execute('PRAGMA journal_mode=DELETE')
        if not (_has_table(c, 'learning_raw_artifact') or _has_table(c, 'ai_run')):
            raise ValueError('unrecognized_backup')
        c.execute('BEGIN IMMEDIATE')
        try:
            for material_id in material_ids:
                if _has_table(c, 'learning_raw_artifact'):
                    erase_learning(c,owner,material_id,now,source_message_ids,source_turn_ids)
                else:
                    erase_ordinary(c,owner,material_id,now,source_run_ids)
            c.commit()
        except BaseException:
            c.rollback()
            raise
        compact(c)
    manifest = path.with_suffix('.json')
    if manifest.exists():
        value = json.loads(manifest.read_text())
        value.update(sha256=file_sha256(path),content_erased_at=now)
        write_json(manifest,value)


def purge(service, identity, material_id):
    """Caller may hold service.lock across start/freeze; never await while holding it."""
    owner = service.learning.principal(identity).owner_id
    row = service.db.fetchone('SELECT scope_kind,scope_id FROM learning_task_material WHERE owner_id=? AND material_id=? LIMIT 1', (owner,material_id))
    if row is None:
        raise DomainError('not_found',404)
    service.owned_scope(identity,row['scope_kind'],row['scope_id'])
    learning_path = service.db.database_path
    ordinary_path = service.conversations.database.database_path
    report_path = receipt_path(learning_path,owner,'material',material_id)
    now = utc_timestamp()
    affected_run_ids = []
    with service.lock, storage_lock(learning_path), service.db._lock, service.conversations.database._lock:
        previous = json.loads(report_path.read_text()) if report_path.exists() else {}
        material_ids,ordinary_source_ids,discussion_source_ids,ordinary_targets,source_message_ids = _group_closure(
            service.db.connection,service.conversations.database.connection,owner,material_id,previous)
        report = dict(owner=owner,kind='material',object_id=material_id,status='pending',files=[],
                      material_ids=material_ids,
                      source_run_ids=sorted(ordinary_source_ids),source_message_ids=sorted(source_message_ids),
                      source_turn_ids=sorted(discussion_source_ids),
                      external_limits=EXTERNAL_LIMITS,updated_at=now)
        def save_report():
            # Every group exposed by the UI must expose the same durable status;
            # retrying any affected group also completes the original receipt.
            for group in material_ids:
                write_json(receipt_path(learning_path, owner, 'material', group),
                           {**report, 'object_id': group})
        save_report()
        for name,db,erase in [('当前学习库及日志',service.db,erase_learning),
                              ('当前普通库及日志',service.conversations.database,erase_ordinary)]:
            try:
                with db._lock:
                    db.connection.execute('PRAGMA secure_delete=ON')
                    with db.transaction(immediate=True) as c:
                        ids = []
                        for group in material_ids:
                            ids.extend(erase(c,owner,group,now,ordinary_source_ids)
                                       if erase is erase_ordinary else erase(c,owner,group,now,source_message_ids,discussion_source_ids))
                    if erase is erase_ordinary:
                        affected_run_ids = sorted(set(ids))
                    compact(db.connection)
                report['files'].append(dict(name=name,status='cleared'))
            except (sqlite3.Error,ValueError,OSError,RuntimeError) as error:
                report['files'].append(dict(name=name,status='failed',reason=type(error).__name__))
            save_report()
        try:
            snapshots = sorted(set(backups(learning_path)) | set(backups(ordinary_path)))
        except (ValueError,OSError):
            snapshots = []
            report['files'].append(dict(name='备份目录',status='failed',reason='unreadable'))
        for path in snapshots:
            try:
                if path.resolve() in (learning_path.resolve(),ordinary_path.resolve()) or (
                    path.exists() and (os.path.samefile(path,learning_path) or os.path.samefile(path,ordinary_path))):
                    raise ValueError('backup_alias')
                register_backup(learning_path,path)
                _scrub_snapshot(path,owner,material_ids,now,ordinary_source_ids,source_message_ids,discussion_source_ids)
                report['files'].append(dict(name=path.name,status='cleared'))
            except (sqlite3.Error,ValueError,OSError,RuntimeError):
                report['files'].append(dict(name=path.name,status='failed',reason='backup_not_cleared'))
            save_report()
        report['status'] = 'complete' if all(x['status']=='cleared' for x in report['files']) else 'partial'
        report['updated_at'] = utc_timestamp()
        save_report()
    return {'purge':{key:report[key] for key in ('status','files','external_limits','updated_at')},
            'affected_run_ids':affected_run_ids or [run['id'] for run in ordinary_targets],
            'affected_material_ids':material_ids}
