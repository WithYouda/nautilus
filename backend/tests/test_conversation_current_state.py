import pytest
import sqlite3
from unittest.mock import patch

from app.conversation_state import CurrentConversationState
from app.materials import MaterialService
from app.question_discussion import QuestionDiscussionService
from app.routers.conversation_state import CurrentStatePut
from app.learning_domain import DomainError
from app.learning_production import _check_purge_receipts, ProductionLearningDatabaseError
from app.learning_production import upgrade_learning_database
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY, response_transport
from test_verification_review import attempt
from test_search_runtime import save_tavily

from test_ai_conversations import (make_client, authorize, configure_provider, create_task,
                                   start_conversation, read_sse, streaming_handler)


def test_current_state_revision_owner_material_and_replay(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        configure_provider(client)
        save_tavily(client)
        conversation = start_conversation(client, create_task(client))
        url = f'/api/conversation-state/conversation/{conversation}'
        assert client.get(url).json() == {
            'initialized': False, 'revision': 0, 'leaf_id': None, 'paths': {},
            'source_scope': {'mode': 'unspecified', 'version_ids': []},
            'search_override': None, 'issues': [],
        }
        other = start_conversation(client, create_task(client))
        invalid = client.put(url, json={'expected_revision': 0, 'leaf_id': other,
            'paths': {}, 'source_scope': {'mode': 'unspecified', 'version_ids': []}})
        assert invalid.status_code == 422
        material = client.post(f'/api/materials/conversation/{conversation}',
                               json={'title': 'Synthetic', 'content': 'No real data'}).json()
        scope = {'mode': 'only', 'version_ids': [material['id']]}
        payload = {'expected_revision': 0, 'leaf_id': None, 'paths': {},
                   'source_scope': scope, 'search_override': {'mode': 'external',
                       'service_id': 'tavily-test', 'parameters': {'query': 'PRIVATE-PARAMETER'}}}
        for invalid_search in ({'mode': 'unknown'}, {'mode': 'off', 'parameters': {}},
                               {'mode': 'native', 'service_id': 'tavily-test'},
                               {'mode': 'native', 'parameters': {}},
                               {'mode': 'external', 'parameters': {}}):
            rejected = client.put(url, json={**payload, 'search_override': invalid_search})
            assert rejected.status_code == 422
        saved = client.put(url, json=payload)
        assert saved.status_code == 200, saved.text
        assert saved.json()['revision'] == 1
        assert client.put(url, json=payload).status_code == 409
        messages = f'/api/ai/conversations/{conversation}/messages'
        send = {'content': 'Explain', 'client_message_id': 'first',
                'source_scope': scope, 'current_state_revision': 1}
        assert client.post(messages, json={**send, 'current_state_revision': 0}).status_code == 409
        assert client.post(messages, json={k: v for k, v in send.items() if k != 'current_state_revision'}).status_code == 409
        started = client.post(messages, json=send)
        assert started.status_code == 202, started.text
        run = started.json()['run']
        assert client.get(url).json()['leaf_id'] == run['response_message_id']
        assert client.get(url).json()['revision'] == 2
        assert client.get(url).json()['paths'][run['response_message_id']] == run['response_message_id']
        assert client.get(url).json()['issues'] == []
        assert client.get(url).headers['Cache-Control'] == 'no-store'
        read_sse(client, run['id'])
        replay = client.post(messages, json=send)
        assert replay.status_code == 202 and replay.json()['created'] is False
        followup = client.post(messages, json={**send, 'content': 'Follow up',
            'client_message_id': 'followup', 'parent_message_id': run['response_message_id'],
            'current_state_revision': 2})
        assert followup.status_code == 202, followup.text
        next_id = followup.json()['run']['response_message_id']
        assert client.get(url).json()['paths'][run['response_message_id']] == next_id
        assert client.get(url).json()['revision'] == 3
        read_sse(client, followup.json()['run']['id'])
        assert client.put(url, json={**payload, 'expected_revision': 3,
            'source_scope': {'mode': 'only', 'version_ids': ['missing']}}).status_code == 404
        assert client.get(url).json()['source_scope'] == scope
        deselected = client.put(url, json={**payload, 'expected_revision': 3,
            'leaf_id': next_id, 'paths': client.get(url).json()['paths'],
            'source_scope': {'mode': 'unspecified', 'version_ids': []}})
        assert deselected.status_code == 200, deselected.text
        client.post(f'/api/materials/conversation/{conversation}/{material["material_id"]}/purge')
        state = client.get(url).json()
        assert state['source_scope'] == {'mode': 'unspecified', 'version_ids': []}
        assert 'path_unavailable' in state['issues']
        assert 'search_unavailable' in state['issues']
        assert state['search_override'] == {'mode': 'external', 'service_id': 'tavily-test', 'parameters_purged': True}
        raw = client.app.state.learning.database.fetchone('''SELECT search_override_json
            FROM learning_conversation_current_state WHERE scope_id=?''', (conversation,))[0]
        assert 'PRIVATE-PARAMETER' not in raw
        candidate = tmp_path / 'restored-candidate.sqlite3'
        with sqlite3.connect(candidate) as backup:
            client.app.state.learning.database.connection.backup(backup)
            backup.execute('''UPDATE learning_conversation_current_state SET search_override_json=?
                WHERE scope_id=?''', ('{"mode":"external","service_id":"tavily-test","parameters":{"query":"PRIVATE-PARAMETER"}}', conversation))
        with pytest.raises(ProductionLearningDatabaseError, match='private content'):
            _check_purge_receipts(client.app.state.learning.database.database_path, candidate)
        invalid_send = client.post(messages, json={**send, 'client_message_id': 'second',
            'parent_message_id': state['leaf_id'], 'current_state_revision': state['revision']})
        assert invalid_send.status_code == 409
        assert invalid_send.json()['detail'] == 'conversation_state_invalid'


def test_current_state_wrong_owner_and_missing_scope(tmp_path):
    with make_client(tmp_path, streaming_handler) as client:
        authorize(client)
        url = '/api/conversation-state/conversation/not-owned'
        assert client.get(url).status_code == 404
        assert client.put(url, json={'expected_revision': 0}).status_code == 404


def test_ordinary_state_write_failure_rolls_back_message(tmp_path):
    provider_calls = []
    def handler(request):
        provider_calls.append(request)
        return streaming_handler(request)
    with make_client(tmp_path, handler) as client:
        authorize(client)
        configure_provider(client)
        cid = start_conversation(client, create_task(client))
        state_url = f'/api/conversation-state/conversation/{cid}'
        assert client.put(state_url, json={'expected_revision': 0}).status_code == 200
        with patch.object(client.app.state.conversation_state, 'advance', side_effect=RuntimeError('synthetic state failure')):
            with pytest.raises(RuntimeError, match='synthetic state failure'):
                client.post(f'/api/ai/conversations/{cid}/messages', json={
                    'content': 'Never persisted', 'client_message_id': 'fail', 'current_state_revision': 1})
        assert client.get(f'/api/ai/conversations/{cid}').json()['messages'] == []
        assert client.get(state_url).json()['revision'] == 1
        assert provider_calls == []


@pytest.mark.asyncio
async def test_discussion_current_state_revision_replay_and_purge(learning_database):
    verification, original = await attempt(learning_database)
    service = QuestionDiscussionService(verification)
    materials = MaterialService(service.learning, service.chats)
    service.chats.materials = materials
    state = CurrentConversationState(materials, service.chats, service, None)
    service.current_state = state
    discussion = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'current-state')
    did = discussion['id']
    assert state.get(IDENTITY, 'discussion', did)['revision'] == 0
    saved = state.put(IDENTITY, 'discussion', did, CurrentStatePut(expected_revision=0))
    assert saved['revision'] == 1
    with pytest.raises(DomainError, match='conversation_state_conflict'):
        service.start(IDENTITY, did, 'Synthetic question', 'first', current_state_revision=0)
    verification.transport = response_transport(['{"history_query":null}', 'Synthetic answer'])
    result = await service.send(IDENTITY, did, 'Synthetic question', 'first', current_state_revision=1)
    turn = result['turns'][0]
    assert state.get(IDENTITY, 'discussion', did)['leaf_id'] == turn['id']
    assert state.get(IDENTITY, 'discussion', did)['revision'] == 2
    assert state.get(IDENTITY, 'discussion', did)['paths'][f'group:{turn["question_id"]}'] == turn['id']
    replay = service.start(IDENTITY, did, 'Synthetic question', 'first', current_state_revision=1)
    assert len(replay['turns']) == 1
    with pytest.raises(DomainError, match='not_found'):
        state.get({**IDENTITY, 'id': 'owner-b'}, 'discussion', did)
    verification.purge(IDENTITY, original['id'])
    with pytest.raises(DomainError, match='not_found'):
        state.get(IDENTITY, 'discussion', did)


@pytest.mark.asyncio
async def test_formal_034_to_035_upgrade_preserves_discussion(tmp_path, learning_database):
    verification, original = await attempt(learning_database)
    service = QuestionDiscussionService(verification)
    discussion = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'old-034')
    for identity in learning_database.fetchall('SELECT * FROM local_identity'):
        verification.link_legacy_submissions(dict(identity))
    path = tmp_path / 'isolated-034.sqlite3'
    with sqlite3.connect(path) as old:
        learning_database.connection.backup(old)
        old.execute('DROP TRIGGER learning_discussion_purge_current_state')
        old.execute('DROP TABLE learning_conversation_current_state')
        old.execute("DELETE FROM schema_migrations WHERE version='035_conversation_current_state'")
        tables = [row[0] for row in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('schema_migrations','sqlite_sequence')")]
        before = {table: old.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall() for table in tables}
        assert old.execute('SELECT 1 FROM learning_question_discussion WHERE id=?', (discussion['id'],)).fetchone()
    result = upgrade_learning_database(path, tmp_path / 'backups', authorized=True)
    assert result['post_upgrade_backup']['applied_migrations'][-1] == '035_conversation_current_state'
    with sqlite3.connect(path) as upgraded:
        assert all(upgraded.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall() == rows
                   for table, rows in before.items())
        assert upgraded.execute('SELECT count(*) FROM learning_conversation_current_state').fetchone()[0] == 0
        assert upgraded.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert upgraded.execute('PRAGMA foreign_key_check').fetchall() == []
