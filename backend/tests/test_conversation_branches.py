import json
from uuid import uuid4
import sqlite3
import pytest
from app.conversation_branches import create_branch
from app.conversations import ConversationError
from contextlib import closing

from app.purge_storage import register_backup, storage_lock
from test_ai_conversations import make_client, authorize, configure_provider, read_sse
from test_material_runtime import body_response


def new_chat(client):
    result = client.post('/api/ai/conversations', json={})
    assert result.status_code == 201
    return result.json()['conversation']['id']


def send(client, cid, text, **extra):
    result = client.post(f'/api/ai/conversations/{cid}/messages', json={
        'content': text, 'client_message_id': str(uuid4()), **extra})
    assert result.status_code == 202, result.text
    run = result.json()['run']
    read_sse(client, run['id'])
    return run['response_message_id']


def branch(client, cid, mid, key='branch-one'):
    return client.post(f'/api/ai/conversations/{cid}/branches', json={'message_id': mid, 'request_key': key})


def test_branch_selected_version_path_idempotency_and_continuation(tmp_path):
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return body_response('ANSWER-' + str(len(calls)))
    with make_client(tmp_path, handler) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        first = send(client, cid, 'first-question', help_request='hint')
        alternate = send(client, cid, 'first-question', regenerate_message_id=first)
        later = send(client, cid, 'LATER-QUESTION', parent_message_id=first)
        source = client.get(f'/api/ai/conversations/{cid}').json()
        before = len(calls)
        result = branch(client, cid, alternate)
        assert result.status_code == 201, result.text
        fork = result.json(); bid = fork['conversation']['id']
        assert len(calls) == before  # Branching does not run a provider.
        assert len(fork['messages']) == 2
        assert fork['messages'][0]['content'] == 'first-question'
        assert fork['messages'][1]['content'] == next(m['content'] for m in source['messages'] if m['id'] == alternate)
        assert fork['messages'][1]['parent_message_id'] == fork['messages'][0]['id']
        assert fork['messages'][1]['inherited_from']['message_id'] == alternate
        assert fork['messages'][1]['help_record'] == next(m['help_record'] for m in source['messages'] if m['id'] == alternate)
        assert branch(client, cid, alternate).json()['conversation']['id'] == bid
        assert branch(client, cid, first).status_code == 409
        assert branch(client, cid, source['messages'][0]['id'], 'bad-role').status_code == 409
        assert branch(client, cid, 'missing', 'missing').status_code == 404
        assert client.get(f'/api/ai/conversations/{cid}').json() == source
        send(client, bid, 'BRANCH-QUESTION')
        payload = json.dumps(calls[-1])
        assert 'LATER-QUESTION' not in payload and 'first-question' in payload
        nested = branch(client, bid, fork['messages'][1]['id'], 'nested').json()
        assert len(nested['messages']) == 2
        client.delete(f'/api/ai/conversations/{bid}')
        assert branch(client, cid, alternate).status_code == 409


def test_branch_material_versions_and_transitive_purge_in_backup(tmp_path):
    with make_client(tmp_path, lambda _: body_response('PRIVATE-ANSWER【资料1】')) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        base = f'/api/materials/conversation/{cid}'
        material = client.post(base, json={'title': 'original', 'content': 'PRIVATE-MATERIAL'}).json()
        scope = {'mode': 'only', 'version_ids': [material['id']], 'conflict_policy': 'materials'}
        mid = send(client, cid, 'PRIVATE-QUESTION', source_scope=scope)
        new_version = client.post(base, json={'title': 'later', 'content': 'LATER-MATERIAL',
                                  'material_id': material['material_id']}).json()
        result = branch(client, cid, mid)
        assert result.status_code == 201, result.text
        fork = result.json(); bid = fork['conversation']['id']
        assert fork['branch_source_scope'] == scope
        branch_base = f'/api/materials/conversation/{bid}'
        inherited = client.get(branch_base).json()['versions']
        assert [v['id'] for v in inherited] == [material['id']] and inherited[0]['inherited']
        assert client.post(branch_base, json={'title': 'bad-edit', 'content': 'bad',
                            'material_id': material['material_id']}).status_code == 409
        bad = client.post(f'/api/ai/conversations/{bid}/messages', json={'content': 'bad',
            'client_message_id': 'bad', 'source_scope': {**scope, 'version_ids': [new_version['id']]}})
        assert bad.status_code == 400
        send(client, bid, 'BRANCH-FOLLOWUP', source_scope=scope)
        db = client.app.state.database
        service = client.app.state.materials
        backup = tmp_path / 'branch-backup.sqlite3'
        with closing(sqlite3.connect(backup)) as target:
            db.connection.backup(target)
        with storage_lock(service.db.database_path):
            register_backup(service.db.database_path, backup)
        client.delete(f'/api/ai/conversations/{cid}')
        purged = client.post(branch_base + '/' + material['material_id'] + '/purge')
        assert purged.status_code == 200, purged.text
        assert purged.json()['purge']['status'] == 'complete'
        after = client.get(f'/api/ai/conversations/{bid}').json()
        assert all(m['content'] == '' for m in after['messages'])
        assert after['branch_origin']['conversation_id'] == cid
        assert after['branch_source_scope']['mode'] == 'unspecified'
        assert client.get(branch_base).json()['versions'][0]['purged_at']
        with closing(sqlite3.connect(backup)) as c:
            assert c.execute('SELECT count(*) FROM message WHERE conversation_id=? AND content<>?', (bid, '')).fetchone()[0] == 0
            assert 'PRIVATE' not in '\n'.join(c.iterdump())
        assert branch(client, bid, after['messages'][-1]['id'], 'purged').status_code == 409


def test_branch_auth_and_other_owner(tmp_path):
    with make_client(tmp_path, lambda _: body_response('answer')) as client:
        assert branch(client, 'unknown', 'unknown').status_code == 401
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        mid = send(client, cid, 'owned-question')
        with pytest.raises(ConversationError):
            create_branch(client.app.state.materials.conversations, 'another-owner', cid, mid, 'foreign')
        with client.app.state.database.transaction() as c:
            c.execute('UPDATE provider_profile SET enabled=0')
        assert branch(client, cid, mid, 'no-provider').status_code == 201
        # An unrelated conversation cannot be used to select this message.
        assert branch(client, new_chat(client), mid).status_code == 404
        with client.app.state.database.transaction() as c:
            # Ownership lookup rejects the source before any copies are created.
            c.execute('UPDATE conversation SET deleted_at=? WHERE id=?', ('now', cid))
        assert branch(client, cid, mid).status_code == 404


def test_branch_purge_follows_history_across_changed_material_scope(tmp_path):
    with make_client(tmp_path, lambda _: body_response('DERIVED-PRIVATE-ANSWER')) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        base = f'/api/materials/conversation/{cid}'
        a = client.post(base, json={'title': 'a', 'content': 'PRIVATE-A'}).json()
        send(client, cid, 'first', source_scope={'mode':'reference', 'version_ids':[a['id']]})
        b = client.post(base, json={'title': 'b', 'content': 'PRIVATE-B'}).json()
        second = send(client, cid, 'second', source_scope={'mode':'reference', 'version_ids':[b['id']]})
        fork = branch(client, cid, second).json()
        bid = fork['conversation']['id']
        nested = branch(client, bid, fork['messages'][-1]['id'], 'nested').json()['conversation']['id']
        send(client, nested, 'descendant', source_scope={'mode':'reference','version_ids':[b['id']]})
        assert client.post(base + '/' + a['material_id'] + '/purge').status_code == 200
        for target in (cid, bid, nested):
            messages = client.get(f'/api/ai/conversations/{target}').json()['messages']
            assert all(not message['content'] for message in messages)
        # An independently supplied second material is not itself erased.
        assert next(v for v in client.get(base).json()['versions'] if v['id'] == b['id'])['content'] == 'PRIVATE-B'
