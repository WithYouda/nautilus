"""Managed erasure of new coach chats and their source-dependent replies only."""
import json
import os
import sqlite3
from contextlib import closing
from .conversations import ConversationError, _now
from .core.events import digest
from .learning_production import validate_learning_path, file_sha256
from .managed_purge import compact, EXTERNAL_LIMITS
from .purge_storage import backups, receipts, receipt_path, storage_lock, write_json, register_backup


def has(c,table): return bool(c.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone())


def erase_learning(c, owner, identifier, now):
    if not has(c,'learning_coach_conversation'): return
    c.execute('UPDATE learning_coach_conversation SET purged_at=?,updated_at=? WHERE owner_id=? AND conversation_id=?',(now,now,owner,identifier))
    if has(c,'learning_conversation_current_state'):
        c.execute("DELETE FROM learning_conversation_current_state WHERE owner_id=? AND kind='conversation' AND scope_id=?",(owner,identifier))


def affected(c,owner,*,conversations=(),run_ids=(),plan_id=None):
    if not has(c,'ai_run'): return []
    rows=[dict(r) for r in c.execute('''SELECT r.* FROM ai_run r JOIN conversation v ON v.id=r.conversation_id
        WHERE r.identity_id=? AND v.identity_id=?''',(owner,owner))]
    selected=set(run_ids)
    for row in rows:
        if row['conversation_id'] in conversations: selected.add(row['id'])
        snapshot=json.loads(row['config_snapshot_json'] or '{}');inputs=(snapshot.get('coach') or {}).get('inputs',{})
        if plan_id and any(p['id']==plan_id for p in inputs.get('plans',[])): selected.add(row['id'])
    while True:
        response_ids={r['response_message_id'] for r in rows if r['id'] in selected}
        more={r['id'] for r in rows if json.loads(r['config_snapshot_json'] or '{}').get('coach') and
            response_ids.intersection(json.loads(r['config_snapshot_json'] or '{}').get('source_history_message_ids',[]))}
        if more<=selected: return [r for r in rows if r['id'] in selected]
        selected.update(more)


def erase_ordinary(c,owner,now,*,conversations=(),run_ids=(),plan_id=None):
    rows=affected(c,owner,conversations=conversations,run_ids=run_ids,plan_id=plan_id)
    if not has(c,'conversation'): return []
    conversations=[identifier for identifier in conversations if c.execute('SELECT 1 FROM conversation WHERE id=? AND identity_id=?',(identifier,owner)).fetchone()]
    messages={r['response_message_id'] for r in rows if r['response_message_id']}
    chats={r['conversation_id'] for r in rows}|set(conversations)
    for identifier in conversations:
        messages.update(r[0] for r in c.execute('SELECT id FROM message WHERE conversation_id=?',(identifier,)))
        c.execute("UPDATE conversation SET title='学习教练',deleted_at=?,updated_at=?,title_revision=title_revision+1,title_source='placeholder',title_generation_status='idle',title_generated_at=NULL WHERE identity_id=? AND id=?",(now,now,owner,identifier))
    for row in rows:
        snapshot=json.loads(row['config_snapshot_json'] or '{}')
        marker={'reply':snapshot.get('reply',{}),'source_scope':{'purged':True},'coach_source_purged':True}
        c.execute("UPDATE ai_run SET status='canceled',config_snapshot_json=?,error_kind='content_purged',error_message=NULL,finished_at=?,updated_at=? WHERE id=?",(json.dumps(marker),now,now,row['id']))
        if row['context_snapshot_id']: c.execute("UPDATE context_snapshot SET summary='',payload='{}' WHERE id=? AND conversation_id IN (SELECT id FROM conversation WHERE identity_id=?)",(row['context_snapshot_id'],owner))
    for identifier in messages:
        c.execute("UPDATE message SET content='',reasoning_content='',status='canceled',updated_at=? WHERE id=? AND conversation_id IN (SELECT id FROM conversation WHERE identity_id=?)",(now,identifier,owner))
    for identifier in chats:
        if has(c,'conversation_title_run'):
            c.execute("UPDATE conversation_title_run SET status='superseded',generated_title=NULL,input_message_ids_json='[]',config_snapshot_json='{}',error_kind='content_purged',error_message=NULL,finished_at=?,updated_at=? WHERE identity_id=? AND conversation_id=?",(now,now,owner,identifier))
        c.execute("UPDATE conversation SET title='学习教练',title_source='placeholder',title_generation_status='idle',title_generated_at=NULL,updated_at=? WHERE identity_id=? AND id=? AND title_source<>'manual'",(now,owner,identifier))
    return [r['id'] for r in rows]


def scrub(path,owner,identifier,now,*,run_ids=(),plan_id=None):
    if path.is_symlink(): raise ValueError('backup_is_symlink')
    path=validate_learning_path(path)
    if not path.is_file() or not os.access(path,os.W_OK): raise OSError('backup_not_writable')
    with closing(sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,isolation_level=None)) as c:
        c.row_factory=sqlite3.Row;c.execute('PRAGMA secure_delete=ON');c.execute('PRAGMA journal_mode=DELETE');c.execute('BEGIN IMMEDIATE')
        try:
            if has(c,'ai_run'): erase_ordinary(c,owner,now,conversations=[identifier] if identifier else [],run_ids=run_ids,plan_id=plan_id)
            elif has(c,'learning_raw_artifact'):
                if identifier: erase_learning(c,owner,identifier,now)
            else: raise ValueError('unrecognized_backup')
            c.commit()
        except BaseException: c.rollback();raise
        compact(c)
    manifest=path.with_suffix('.json')
    if manifest.exists():
        value=json.loads(manifest.read_text());value.update(sha256=file_sha256(path),content_erased_at=now);write_json(manifest,value)


class CoachConversationPurge:
    def __init__(self,service): self.service,self.db,self.chats=service,service.db,service.chats

    def status(self,identity,identifier):
        owner=self.service.learning.principal(identity).owner_id
        self._require_owner(owner,identifier)
        path=receipt_path(self.db.database_path,owner,'coach_conversation',identifier)
        report=json.loads(path.read_text()) if path.exists() else {'status':'not_requested','files':[],'external_limits':EXTERNAL_LIMITS}
        impact={'conversations':1,'messages':self.chats.database.fetchone('SELECT COUNT(*) FROM message WHERE conversation_id=?',(identifier,))[0],
            'runs':self.chats.database.fetchone('SELECT COUNT(*) FROM ai_run WHERE identity_id=? AND conversation_id=?',(owner,identifier))[0]}
        return {'purge_report':{k:v for k,v in report.items() if k in {'status','files','external_limits','updated_at'}},'impact':impact}

    def _ordinary(self,owner,now,**kwargs):
        db=self.chats.database
        with db._lock:
            db.connection.execute('PRAGMA secure_delete=ON')
            with db.transaction(immediate=True) as c: identifiers=erase_ordinary(c,owner,now,**kwargs)
            try: compact(db.connection)
            finally:
                if self.service.manager: self.service.manager.forget_material_runs(identifiers)
        return identifiers

    async def purge(self,identity,identifier,key):
        owner=self.service.learning.principal(identity).owner_id
        self._require_owner(owner,identifier)
        with self.service.lock,storage_lock(self.db.database_path),storage_lock(self.chats.database.database_path):
            now=_now();path=receipt_path(self.db.database_path,owner,'coach_conversation',identifier)
            previous=self.db.fetchone("SELECT result_id FROM learning_coach_request WHERE owner_id=? AND scope='purge' AND request_key=?",(owner,key))
            if previous and previous['result_id']!=identifier: raise ConversationError('本次清除请求已用于其他对话')
            if previous and path.exists() and json.loads(path.read_text())['status']=='complete':
                return {'coach':self.service.info(self.service.mapping(owner,identifier)),**self.status(identity,identifier)}
            if not previous:
                with self.db.transaction(immediate=True) as c: c.execute('INSERT INTO learning_coach_request VALUES (?,\'purge\',?,?,?,?)',(owner,key,digest(identifier),identifier,now))
            report={'kind':'coach_conversation','owner':owner,'object_id':identifier,'status':'pending','updated_at':now,'files':[],
                'external_limits':EXTERNAL_LIMITS,'conversation_ids':[identifier]}
            write_json(path,report)
            for name,operation in [('当前普通库及日志',lambda:self._ordinary(owner,now,conversations=[identifier])),('当前学习库及日志',lambda:self._learning(owner,identifier,now))]:
                try: operation();report['files'].append({'name':name,'status':'cleared'})
                except (OSError,sqlite3.Error,ValueError): report['files'].append({'name':name,'status':'failed','reason':'not_cleared'})
                write_json(path,report)
            snapshots=sorted(set(backups(self.db.database_path))|set(backups(self.chats.database.database_path)))
            for backup in snapshots:
                try:
                    if backup.resolve() in {self.db.database_path.resolve(),self.chats.database.database_path.resolve()} or backup.exists() and any(os.path.samefile(backup,p) for p in (self.db.database_path,self.chats.database.database_path)): raise ValueError('backup_alias')
                    register_backup(self.db.database_path,backup);scrub(backup,owner,identifier,now)
                    report['files'].append({'name':backup.name,'status':'cleared'})
                except (OSError,sqlite3.Error,ValueError): report['files'].append({'name':backup.name,'status':'failed','reason':'backup_not_cleared'})
                write_json(path,report)
            report['status']='complete' if all(v['status']=='cleared' for v in report['files']) else 'partial';write_json(path,report)
            return {'coach':self.service.info(self.service.mapping(owner,identifier)),**self.status(identity,identifier)}

    def _learning(self,owner,identifier,now):
        with self.db._lock:
            self.db.connection.execute('PRAGMA secure_delete=ON')
            with self.db.transaction(immediate=True) as c: erase_learning(c,owner,identifier,now)
            compact(self.db.connection)

    def _require_owner(self,owner,identifier):
        if not self.service.mapping(owner,identifier) or not self.chats.database.fetchone('SELECT 1 FROM conversation WHERE id=? AND identity_id=?',(identifier,owner)):
            raise ConversationError('教练对话不存在')

    def plan_dependencies(self,owner,plan_id,report):
        """Called under the original plan purge lock, with its durable receipt."""
        ids=sorted(set(report.get('coach_run_ids',[]))|{r['id'] for r in affected(self.chats.database.connection,owner,plan_id=plan_id)})
        relevant=[]
        for backup in backups(self.chats.database.database_path):
            with closing(sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True)) as c:
                c.row_factory=sqlite3.Row
                dependency=affected(c,owner,plan_id=plan_id)
            if dependency:
                ids=sorted(set(ids)|{r['id'] for r in dependency});relevant.append(backup)
        if not ids:
            return
        report['coach_run_ids']=ids
        write_json(receipt_path(self.db.database_path,owner,'plan_content',plan_id),report)
        self._ordinary(owner,report['updated_at'],run_ids=ids,plan_id=plan_id)
        for backup in relevant:
            register_backup(self.db.database_path,backup)

    def recover(self):
        """No normal read precedes receipt erasure when the ordinary DB is rolled back."""
        for report in receipts(self.db.database_path):
            if report['kind']=='coach_conversation':
                self._ordinary(report['owner'],report['updated_at'],conversations=[report['object_id']])
                self._learning(report['owner'],report['object_id'],report['updated_at'])
            elif report.get('coach_run_ids'):
                self._ordinary(report['owner'],report['updated_at'],run_ids=report['coach_run_ids'],plan_id=report['object_id'])
