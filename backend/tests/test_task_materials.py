"""Synthetic material scope, version, snapshot erasure and restore checks."""
import json
import os
import sqlite3
from contextlib import closing
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.db import Database
from app.learning_domain import DomainError, Principal
from app.learning_production import create_learning_backup, restore_learning_backup, ProductionLearningDatabaseError
from app.materials import MaterialService
from app.conversations import ConversationError
from app.purge_storage import register_backup, storage_lock, receipt_path


@pytest.fixture
def material_service(tmp_path):
    migrations = Settings.from_env().migrations_dir
    ordinary = Database(tmp_path / 'ordinary.sqlite3', migrations)
    learning = Database(tmp_path / 'learning.sqlite3', migrations, migration_floor=11, migration_ceiling=None)
    for db in (ordinary, learning):
        with db.transaction() as c:
            c.execute("""INSERT INTO local_identity(id,device_id,display_name,created_at,updated_at)
                VALUES ('owner','device','Synthetic','now','now')""")
    with ordinary.transaction() as c:
        c.execute("""INSERT INTO conversation(id,identity_id,title,created_at,updated_at)
            VALUES ('chat','owner','Synthetic','now','now')""")
    conversations = SimpleNamespace(database=ordinary, owned_conversation=lambda owner, scope_id:
        ordinary.fetchone('SELECT * FROM conversation WHERE identity_id=? AND id=? AND deleted_at IS NULL',
                          (owner,scope_id)) or (_ for _ in ()).throw(ConversationError('not_found')))
    service = MaterialService(SimpleNamespace(database=learning,principal=lambda identity:Principal.user(identity['id'])), conversations)
    yield service
    ordinary.close()
    learning.close()


def test_material_versions_freeze_and_purge_two_databases(material_service, tmp_path):
    service = material_service
    identity = {'id':'owner'}
    first = service.create(identity,'conversation','chat',title='Text',content='PRIVATE_MATERIAL_1')
    second = service.create(identity,'conversation','chat',title='Text 2',content='PRIVATE_MATERIAL_2',material_id=first['material_id'])
    assert second['version'] == 2
    frozen = service.freeze(identity,'conversation','chat',{'mode':'only','version_ids':[second['id']]})
    assert 'PRIVATE_MATERIAL_2' in service.prompt(frozen)
    assert service.public(frozen,'【资料1】')['materials'][0]['cited']
    assert 'content' not in service.public(frozen)['materials'][0]
    with pytest.raises(DomainError):
        service.freeze({'id':'other'},'conversation','chat',{'mode':'only','version_ids':[second['id']]})
    ordinary = service.conversations.database
    with ordinary.transaction() as c:
        c.execute("INSERT INTO conversation(id,identity_id,title,created_at,updated_at) VALUES ('other-chat','owner','Other','now','now')")
    with pytest.raises(DomainError, match='material_not_found'):
        service.freeze(identity, 'conversation', 'other-chat', {'mode':'only', 'version_ids':[first['id']]})
    with pytest.raises(DomainError):
        service.freeze(identity, 'conversation', 'chat', {'mode':'only', 'version_ids':[first['id'],second['id']]})
    with ordinary.transaction() as c:
        c.execute("""INSERT INTO message(id,conversation_id,role,content,sequence,created_at,updated_at)
            VALUES ('user','chat','user','PRIVATE_MATERIAL_2',0,'now','now')""")
        c.execute("""INSERT INTO message(id,conversation_id,role,content,sequence,created_at,updated_at)
            VALUES ('answer','chat','assistant','PRIVATE_MATERIAL_2',1,'now','now')""")
        c.execute("""INSERT INTO context_snapshot(id,conversation_id,summary,payload,created_at)
            VALUES ('context','chat','PRIVATE_MATERIAL_2','{"copy":"PRIVATE_MATERIAL_2"}','now')""")
        c.execute("""INSERT INTO ai_run(id,identity_id,conversation_id,status,request_message_id,response_message_id,
            context_snapshot_id,config_snapshot_json,created_at,updated_at)
            VALUES ('run','owner','chat','succeeded','user','answer','context',?,'now','now')""",
            (json.dumps({'source_scope':service.public(frozen),'model_turn':'PRIVATE_MATERIAL_2'}),))
    learning_backup,_,_ = create_learning_backup(service.db.database_path,tmp_path/'backups',label='synthetic')
    unmanaged = tmp_path/'unmanaged.sqlite3'
    with closing(sqlite3.connect(unmanaged)) as target:
        service.db.connection.backup(target)
    ordinary_backup = tmp_path/'backups'/'ordinary-synthetic.sqlite3'
    with closing(sqlite3.connect(ordinary_backup)) as target:
        ordinary.connection.backup(target)
    with storage_lock(service.db.database_path):
        register_backup(service.db.database_path,ordinary_backup)
    result = service.purge(identity,first['material_id'])
    assert result['purge']['status']=='complete', result
    assert result['affected_run_ids']==['run']
    assert service.db.fetchone('SELECT content FROM learning_task_material WHERE id=?',(second['id'],))[0] is None
    assert ordinary.fetchone('SELECT content FROM message WHERE id=?',('answer',))[0]==''
    assert ordinary.fetchone('SELECT payload FROM context_snapshot WHERE id=?',('context',))[0]=='{}'
    for path in (service.db.database_path,ordinary.database_path,learning_backup,ordinary_backup):
        assert b'PRIVATE_MATERIAL_2' not in path.read_bytes()
    # A registered ordinary snapshot must not make later learning-only purges
    # permanently partial merely because its schema is intentionally different.
    from app.managed_purge import scrub_snapshot
    scrub_snapshot(ordinary_backup, 'owner', 'artifact', 'unrelated', 'now')
    with pytest.raises(ProductionLearningDatabaseError):
        restore_learning_backup(unmanaged,service.db.database_path)


def test_web_import_requires_obtained_text_and_erases_source_history(material_service,tmp_path):
    service = material_service
    identity = {'id':'owner'}
    db = service.conversations.database
    trace = {'search_trace':{'items':[{'title':'Hit','url':'https://example.test/a'},
                                      {'title':'Fetched','url':'https://example.test/b',
                                       'text':'PRIVATE_WEB_EXCERPT','content_kind':'page'},
                                      {'title':'Second','url':'https://example.test/c',
                                       'text':'PRIVATE_SECOND_ITEM','content_kind':'excerpt'}]}}
    with db.transaction() as c:
        for message_id, sequence in (('origin-answer',0),('later-answer',1),('separate-answer',2)):
            c.execute('''INSERT INTO message(id,conversation_id,role,content,sequence,created_at,updated_at)
                VALUES (?,'chat','assistant',?,?,'now','now')''',
                (message_id,'SAFE_SEPARATE' if message_id=='separate-answer' else 'PRIVATE_WEB_EXCERPT',sequence))
        c.execute('''INSERT INTO ai_run(id,identity_id,conversation_id,status,response_message_id,
            config_snapshot_json,created_at,updated_at) VALUES ('origin','owner','chat','succeeded',
            'origin-answer',?,'now','now')''',(json.dumps(trace),))
        c.execute('''INSERT INTO ai_run(id,identity_id,conversation_id,status,response_message_id,
            config_snapshot_json,created_at,updated_at) VALUES ('later','owner','chat','succeeded',
            'later-answer',?,'now','now')''',(json.dumps({'source_history_message_ids':['origin-answer']}),))
        c.execute('''INSERT INTO ai_run(id,identity_id,conversation_id,status,response_message_id,
            config_snapshot_json,created_at,updated_at) VALUES ('separate','owner','chat','succeeded',
            'separate-answer',?,'now','now')''',
            (json.dumps({'source_history_message_ids':[], 'reply':{'parent_answer_id':'origin-answer'}}),))
    with pytest.raises(DomainError,match='material_content_missing'):
        service.create(identity,'conversation','chat',title='URL only',web_run_id='origin',web_item_index=0)
    saved = service.create(identity,'conversation','chat',title='Fetched',web_run_id='origin',web_item_index=1)
    sibling = service.create(identity,'conversation','chat',title='Second',web_run_id='origin',web_item_index=2)
    assert saved['content_kind']=='page'
    sibling_scope = service.public(service.freeze(identity,'conversation','chat',
        {'mode':'only','version_ids':[sibling['id']]}))
    with db.transaction() as c:
        c.execute('''INSERT INTO message(id,conversation_id,role,content,sequence,created_at,updated_at)
            VALUES ('sibling-answer','chat','assistant','PRIVATE_SECOND_ITEM',3,'now','now')''')
        c.execute('''INSERT INTO ai_run(id,identity_id,conversation_id,status,response_message_id,
            config_snapshot_json,created_at,updated_at) VALUES ('sibling-run','owner','chat','succeeded',
            'sibling-answer',?,'now','now')''',
            (json.dumps({'source_scope':sibling_scope}),))
    with pytest.raises(DomainError,match='material_source_already_saved'):
        service.create(identity,'conversation','chat',title='Duplicate',web_run_id='origin',web_item_index=1)
    learning_backup,_,_ = create_learning_backup(service.db.database_path,tmp_path/'backups',label='web')
    ordinary_backup = tmp_path/'backups'/'web-ordinary.sqlite3'
    with closing(sqlite3.connect(ordinary_backup)) as target:
        db.connection.backup(target)
    with storage_lock(service.db.database_path):
        register_backup(service.db.database_path,ordinary_backup)
    result = service.purge(identity,saved['material_id'])
    assert result['purge']['status']=='complete', result
    assert set(result['affected_run_ids'])=={'origin','later','sibling-run'}
    assert set(result['affected_material_ids'])=={saved['material_id'],sibling['material_id']}
    for group in (saved['material_id'], sibling['material_id']):
        receipt = json.loads(receipt_path(service.db.database_path, 'owner', 'material', group).read_text())
        assert receipt['status'] == 'complete' and receipt['object_id'] == group
    assert db.fetchone('SELECT content FROM message WHERE id=?',('later-answer',))[0]==''
    assert service.db.fetchone('SELECT content FROM learning_task_material WHERE id=?',(sibling['id'],))[0] is None
    for path in (learning_backup,ordinary_backup):
        assert b'PRIVATE_SECOND_ITEM' not in path.read_bytes()
    assert db.fetchone('SELECT content FROM message WHERE id=?',('separate-answer',))[0]=='SAFE_SEPARATE'


def test_hardlinked_online_database_is_not_scrubbed_as_backup(material_service, tmp_path):
    service = material_service
    saved = service.create({'id':'owner'},'conversation','chat',title='Text',content='SYNTHETIC_PRIVATE')
    alias = tmp_path/'ordinary-alias.sqlite3'
    os.link(service.conversations.database.database_path,alias)
    with storage_lock(service.db.database_path):
        register_backup(service.db.database_path,alias)
    result = service.purge({'id':'owner'},saved['material_id'])
    assert result['purge']['status']=='partial'
    assert any(item['name']==alias.name and item['status']=='failed' for item in result['purge']['files'])


def test_failed_ordinary_erase_still_returns_run_ids_for_memory_cancel(material_service, monkeypatch):
    service = material_service
    saved = service.create({'id':'owner'},'conversation','chat',title='Text',content='PRIVATE')
    frozen = service.freeze({'id':'owner'},'conversation','chat',
                            {'mode':'only','version_ids':[saved['id']]})
    db = service.conversations.database
    with db.transaction() as c:
        c.execute('''INSERT INTO ai_run(id,identity_id,conversation_id,status,config_snapshot_json,created_at,updated_at)
            VALUES ('running','owner','chat','running',?,'now','now')''',
            (json.dumps({'source_scope':service.public(frozen)}),))
    @contextmanager
    def fail(*args,**kwargs):
        raise sqlite3.OperationalError('synthetic failure')
        yield
    monkeypatch.setattr(db,'transaction',fail)
    result = service.purge({'id':'owner'},saved['material_id'])
    assert result['purge']['status']=='partial'
    assert result['affected_run_ids']==['running']
