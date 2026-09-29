"""Explicit reusable versions, owner isolation and independent conversation lifetimes."""
import pytest
from app.learning_domain import DomainError
from test_task_materials import material_service  # noqa: F401

IDENTITY = {'id': 'owner'}


def add_chat(service, name, owner='owner'):
    with service.conversations.database.transaction() as c:
        c.execute('INSERT INTO conversation(id,identity_id,title,created_at,updated_at) VALUES (?,?,?,\'now\',\'now\')', (name, owner, name))


def test_manual_membership_exact_versions_and_update_from_another_chat(material_service):
    s = material_service
    add_chat(s, 'second')
    old = s.create(IDENTITY, 'conversation', 'chat', title='First', content='old content', original=(b'original old', 'first.txt', 'text/plain'))
    assert s.library(IDENTITY)['versions'] == []
    with pytest.raises(DomainError):
        s.use_library(IDENTITY, 'conversation', 'second', old['id'])
    s.store_in_library(IDENTITY, 'conversation', 'chat', old['material_id'])
    s.store_in_library(IDENTITY, 'conversation', 'chat', old['material_id'])
    assert len(s.library(IDENTITY)['versions']) == 1
    assert s.list(IDENTITY, 'conversation', 'second')['versions'] == []
    choice = {'mode': 'reference', 'version_ids': [old['id']]}
    with pytest.raises(DomainError):
        s.freeze(IDENTITY, 'conversation', 'second', choice)
    s.use_library(IDENTITY, 'conversation', 'second', old['id'])
    s.use_library(IDENTITY, 'conversation', 'second', old['id'])
    assert len(s.list(IDENTITY, 'conversation', 'second')['versions']) == 1
    assert s.original(IDENTITY, 'conversation', 'second', old['id'])['content'] == b'original old'
    newer = s.create(IDENTITY, 'conversation', 'second', title='Updated', content='new content', material_id=old['material_id'])
    assert newer['material_id'] == old['material_id'] and newer['version'] == 2
    assert s.freeze(IDENTITY, 'conversation', 'second', choice)['materials'][0]['content'] == 'old content'
    assert s.freeze(IDENTITY, 'conversation', 'chat', choice)['materials'][0]['content'] == 'old content'
    assert s.original(IDENTITY, 'conversation', 'second', old['id'])['content'] == b'original old'
    assert newer['original'] is None
    assert {v['id'] for v in s.library(IDENTITY)['versions']} == {old['id'], newer['id']}
    # No implicit scope change or deletion when the current reference is cancelled.
    assert s.freeze(IDENTITY, 'conversation', 'second', {'mode': 'unspecified', 'version_ids': []})['materials'] == []
    assert len(s.library(IDENTITY)['versions']) == 2


def test_deleted_origin_does_not_remove_library_or_other_chat(material_service):
    s = material_service
    add_chat(s, 'second')
    old = s.create(IDENTITY, 'conversation', 'chat', title='Shared', content='shared')
    s.store_in_library(IDENTITY, 'conversation', 'chat', old['material_id'])
    with s.conversations.database.transaction() as c:
        c.execute("UPDATE conversation SET deleted_at='deleted' WHERE id='chat'")
    assert s.library(IDENTITY)['versions'][0]['content'] == 'shared'
    s.use_library(IDENTITY, 'conversation', 'second', old['id'])
    updated = s.create(IDENTITY, 'conversation', 'second', title='Still editable', content='new', material_id=old['material_id'])
    assert updated['version'] == 2
    assert s.freeze(IDENTITY, 'conversation', 'second', {'mode': 'only', 'version_ids': [old['id']]})['materials'][0]['content'] == 'shared'


def test_owner_and_explicit_scope_access_still_required(material_service):
    s = material_service
    add_chat(s, 'unlinked')
    old = s.create(IDENTITY, 'conversation', 'chat', title='Private', content='private')
    s.store_in_library(IDENTITY, 'conversation', 'chat', old['material_id'])
    assert s.library({'id': 'stranger'})['versions'] == []
    with pytest.raises(DomainError):
        s.use_library({'id': 'stranger'}, 'conversation', 'chat', old['id'])
    with pytest.raises(DomainError):
        s.store_in_library(IDENTITY, 'conversation', 'unlinked', old['material_id'])
    with pytest.raises(DomainError):
        s.create(IDENTITY, 'conversation', 'unlinked', title='Overwrite', content='bad', material_id=old['material_id'])
    s.purge(IDENTITY, old['material_id'])
    assert s.library(IDENTITY)['versions'] == []
    with pytest.raises(DomainError):
        s.use_library(IDENTITY, 'conversation', 'unlinked', old['id'])
    with pytest.raises(DomainError):
        s.store_in_library(IDENTITY, 'conversation', 'chat', old['material_id'])


def test_library_http_requires_authorization_and_explicit_choice(client):
    from test_ai_conversations import authorize, create_task, start_conversation
    assert client.get('/api/materials/library').status_code == 401
    assert client.post('/api/materials/conversation/no-scope/no-material/library').status_code == 401
    assert client.post('/api/materials/conversation/no-scope/library-use', json={'version_id': 'no-version'}).status_code == 401
    authorize(client)
    origin = start_conversation(client, create_task(client))
    target = start_conversation(client, create_task(client))
    first = client.post(f'/api/materials/conversation/{origin}', json={'title': 'Shared', 'content': 'Synthetic source'}).json()
    assert client.get('/api/materials/library').json() == {'versions': []}
    assert client.post(f'/api/materials/conversation/{origin}/{first["material_id"]}/library').json() == {'stored': True}
    assert client.get('/api/materials/library').json()['versions'][0]['id'] == first['id']
    assert client.get(f'/api/materials/conversation/{target}').json()['versions'] == []
    selected = client.post(f'/api/materials/conversation/{target}/library-use', json={'version_id': first['id']})
    assert selected.status_code == 200 and selected.json()['library']
    assert client.get(f'/api/materials/conversation/{target}').json()['versions'][0]['id'] == first['id']
    updated = client.post(f'/api/materials/conversation/{target}', json={'title': 'Updated', 'content': 'New version', 'material_id': first['material_id']})
    assert updated.status_code == 201 and updated.json()['version'] == 2
    assert client.post(f'/api/materials/conversation/{target}/{first["material_id"]}/purge').json()['purge']['status'] == 'complete'
    assert client.get('/api/materials/library').json()['versions'] == []
