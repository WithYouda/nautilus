"""Library visibility is independent of stored versions and erasure authorization."""
import sqlite3
import pytest
from app.learning_domain import DomainError
from app.learning_production import upgrade_learning_database
from test_task_materials import material_service  # noqa: F401
from test_material_library import add_chat, IDENTITY
from test_ai_conversations import authorize, create_task, start_conversation


def test_removal_preserves_references_and_can_be_readded(material_service):
    s = material_service
    add_chat(s, 'borrower')
    add_chat(s, 'newcomer')
    v = s.create(IDENTITY, 'conversation', 'chat', title='Keep', content='KEEP', original=(b'ORIGINAL', 'keep.txt', 'text/plain'))
    s.store_in_library(IDENTITY, 'conversation', 'chat', v['material_id'])
    s.use_library(IDENTITY, 'conversation', 'borrower', v['id'])
    with pytest.raises(DomainError):
        s.remove_from_library({'id': 'stranger'}, v['material_id'])
    s.remove_from_library(IDENTITY, v['material_id'])
    assert s.library(IDENTITY)['versions'] == []
    assert s.in_library('owner', v['material_id'])
    assert not s.list(IDENTITY, 'conversation', 'borrower')['versions'][0]['library']
    assert s.original(IDENTITY, 'conversation', 'borrower', v['id'])['content'] == b'ORIGINAL'
    assert s.freeze(IDENTITY, 'conversation', 'borrower', {'mode': 'only', 'version_ids': [v['id']]})['materials'][0]['content'] == 'KEEP'
    with pytest.raises(DomainError):
        s.use_library(IDENTITY, 'conversation', 'newcomer', v['id'])
    s.store_in_library(IDENTITY, 'conversation', 'borrower', v['material_id'])
    assert len(s.library(IDENTITY)['versions']) == 1


def test_library_purge_without_scope_and_partial_receipt_retry(client, monkeypatch):
    import app.material_purge as erasure
    assert client.post('/api/materials/library/unknown/remove').status_code == 401
    assert client.post('/api/materials/library/unknown/purge').status_code == 401
    authorize(client)
    chat = start_conversation(client, create_task(client))
    v = client.post(f'/api/materials/conversation/{chat}', json={'title': 'Private', 'content': 'DELETE_ME'}).json()
    base = f'/api/materials/library/{v["material_id"]}'
    assert client.post(base+'/remove').status_code == 404
    assert client.post(base+'/purge').status_code == 404
    client.post(f'/api/materials/conversation/{chat}/{v["material_id"]}/library')
    assert client.post(base+'/remove').json() == {'removed': True}
    assert client.get('/api/materials/library').json()['versions'] == []
    assert client.delete(f'/api/ai/conversations/{chat}').status_code == 204
    compact = erasure.compact
    calls = 0
    def fail_first(connection):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError('synthetic incomplete compaction')
        compact(connection)
    monkeypatch.setattr(erasure, 'compact', fail_first)
    result = client.post(base+'/purge')
    assert result.status_code == 200 and result.json()['purge']['status'] == 'partial'
    assert client.get('/api/materials/library').json() == {'versions': [], 'purge_retry_ids': [v['material_id']]}
    assert client.post(base+'/purge').json()['purge']['status'] == 'complete'
    assert client.get('/api/materials/library').json() == {'versions': []}
    assert client.post('/api/materials/library/unknown/purge').status_code == 404


def test_upgrade_037_preserves_membership_and_reference_rows(tmp_path):
    from app.config import Settings
    from app.db import Database
    from app.learning_service import LearningService
    db = Database(tmp_path/'learning.sqlite3', Settings.from_env().migrations_dir, migration_floor=11, migration_ceiling=37)
    LearningService(db).principal({'id':'owner','device_id':'device','display_name':'Synthetic','timezone':'UTC','created_at':'now'})
    with db.transaction() as c:
        c.execute("INSERT INTO learning_task_material(id,material_id,owner_id,scope_kind,scope_id,version,title,content,content_kind,created_at) VALUES ('v','m','owner','conversation','chat',1,'Keep','KEEP','text','now')")
        c.execute("INSERT INTO learning_material_library VALUES ('owner','m','now')")
        c.execute("INSERT INTO learning_material_link VALUES ('owner','conversation','borrower','v','now')")
    before = {}
    for (table,) in db.connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='schema_migrations'"):
        cols = [r[1] for r in db.connection.execute(f'PRAGMA table_info("{table}")')]
        before[table] = (cols, [tuple(r) for r in db.connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid')])
    db.close()
    result = upgrade_learning_database(tmp_path/'learning.sqlite3', tmp_path/'backups', authorized=True)
    assert result['status'] == 'upgraded'
    with sqlite3.connect(tmp_path/'learning.sqlite3') as c:
        for table, (cols, rows) in before.items():
            projection = ','.join('"'+col+'"' for col in cols)
            assert c.execute(f'SELECT {projection} FROM "{table}" ORDER BY rowid').fetchall() == rows
        assert c.execute('SELECT removed_at FROM learning_material_library').fetchone() == (None,)
