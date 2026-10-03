"""Execution configuration belongs to the accepted discussion answer version."""
import json

import httpx
import pytest

from app.conversations import ConversationError
from app.discussion_branches import create_branch
from app.learning_domain import DomainError
from app.providers import ProviderConfig
from app.question_discussion import QuestionDiscussionService
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY
from test_verification_review import attempt


def snapshot(db, turn_id):
    return json.loads(db.fetchone(
        'SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?', (turn_id,))[0])


async def room(db):
    verification, original = await attempt(db)
    service = QuestionDiscussionService(verification)
    discussion = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'runtime-room')
    return service, original, discussion['id']


@pytest.mark.asyncio
async def test_acceptance_freezes_model_before_requests_and_new_versions_use_new_selection(learning_database):
    service, _, discussion_id = await room(learning_database)
    settings = dict(profile={'id': 'profile-one', 'config_version': 7}, config=ProviderConfig(
        base_url='https://first.example/v1', model='first-model', api_key='synthetic-secret-key',
        timeout_seconds=31))
    service.chats.provider_runtime = lambda owner: (dict(settings['profile']), settings['config'])
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append((request.url.host, payload['model']))
        if payload.get('stream'):
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"合成讲解"}}]}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"history_query":null}'}}]})

    service.verification.transport = httpx.MockTransport(handler)
    accepted = service.start(IDENTITY, discussion_id, '解释这一小点', 'original')
    turn_id = accepted['turns'][0]['id']
    frozen = snapshot(learning_database, turn_id)
    assert calls == []
    assert {key: frozen[key] for key in (
        'runtime_snapshot_schema_version', 'provider_profile_id', 'provider_config_version',
        'provider_kind', 'base_url', 'model', 'timeout_seconds', 'discussion_prompt_schema_version')} == {
        'runtime_snapshot_schema_version': 1, 'provider_profile_id': 'profile-one',
        'provider_config_version': 7, 'provider_kind': 'openai_compatible',
        'base_url': 'https://first.example/v1', 'model': 'first-model', 'timeout_seconds': 31,
        'discussion_prompt_schema_version': 2,
    }
    assert 'synthetic-secret-key' not in json.dumps(frozen)
    settings.update(profile={'id': 'profile-two', 'config_version': 8}, config=ProviderConfig(
        base_url='https://second.example/v1', model='second-model', api_key='new-secret-key', timeout_seconds=47))
    await service.tasks[turn_id]
    assert calls == [('first.example', 'first-model'), ('first.example', 'first-model')]
    original_snapshot = snapshot(learning_database, turn_id)
    assert all(original_snapshot[key] == value for key, value in frozen.items() if key != 'teaching')
    assert {key: value for key, value in original_snapshot['teaching'].items()
            if key != 'not_applied_reason'} == frozen['teaching']
    assert original_snapshot['teaching']['not_applied_reason'] == 'completion_unknown'

    regenerated = await service.send(IDENTITY, discussion_id, '解释这一小点', 'regenerated', regenerate_turn_id=turn_id)
    next_id = regenerated['turns'][-1]['id']
    assert regenerated['turns'][-1]['question_id'] == turn_id
    assert snapshot(learning_database, turn_id) == original_snapshot
    next_snapshot = snapshot(learning_database, next_id)
    assert next_snapshot['model'] == 'second-model' and next_snapshot['timeout_seconds'] == 47
    assert calls[-2:] == [('second.example', 'second-model')] * 2

    def unavailable(owner):
        raise ConversationError('当前提供方已停用')

    service.chats.provider_runtime = unavailable
    replay = service.start(IDENTITY, discussion_id, '解释这一小点', 'original')
    assert len(replay['turns']) == 2 and len(calls) == 4
    assert snapshot(learning_database, turn_id) == original_snapshot
    with pytest.raises(DomainError, match='idempotency_conflict'):
        service.start(IDENTITY, discussion_id, '另一个问题', 'original')


@pytest.mark.asyncio
async def test_failure_before_reply_keeps_actual_runtime_and_source_facts(learning_database):
    service, original, discussion_id = await room(learning_database)
    before = service.records.detail(IDENTITY, original['id'])
    service.verification.transport = httpx.MockTransport(lambda request: httpx.Response(503))
    result = await service.send(IDENTITY, discussion_id, '继续说明', 'failure')
    turn = result['turns'][0]
    frozen = snapshot(learning_database, turn['id'])
    assert turn['status'] == 'failed' and turn['assistant_content'] is None
    assert frozen['model'] == 'verification-model'
    assert frozen['provider_kind'] == 'openai_compatible' and frozen['timeout_seconds'] == 60
    assert frozen['runtime_snapshot_schema_version'] == 1
    assert turn['help_record']['provided'] is None
    after = service.records.detail(IDENTITY, original['id'])
    # The discussion listing changes when a turn is saved; original work and
    # verification results must stay byte-for-byte equivalent in the detail.
    assert {key: value for key, value in after.items() if key != 'discussions'} == {
        key: value for key, value in before.items() if key != 'discussions'}


@pytest.mark.asyncio
async def test_runtime_follows_selected_branch_and_is_erased_with_its_source(learning_database):
    service, original, discussion_id = await room(learning_database)
    from test_learning_verifications import response_transport
    service.verification.transport = response_transport(['{"history_query":null}', '合成讲解'])
    result = await service.send(IDENTITY, discussion_id, '一个问题', 'first')
    turn = result['turns'][0]
    saved = snapshot(learning_database, turn['id'])
    branch = create_branch(service, IDENTITY, discussion_id, turn['id'], 'branch')
    copied = snapshot(learning_database, branch['turns'][0]['id'])
    assert all(copied[key] == saved[key] for key in (
        'runtime_snapshot_schema_version', 'provider_kind', 'base_url', 'model', 'timeout_seconds'))
    service.verification.purge(IDENTITY, original['id'])
    assert snapshot(learning_database, turn['id']) == {}
    assert snapshot(learning_database, branch['turns'][0]['id']) == {}


@pytest.mark.asyncio
async def test_old_discussion_runtime_is_not_reconstructed_from_current_settings(learning_database):
    service, _, discussion_id = await room(learning_database)
    from test_learning_verifications import response_transport
    service.verification.transport = response_transport(['{"history_query":null}', '旧版合成回答'])
    result = await service.send(IDENTITY, discussion_id, '旧问题', 'old')
    turn_id = result['turns'][0]['id']
    old = snapshot(learning_database, turn_id)
    for key in ('runtime_snapshot_schema_version', 'provider_kind', 'base_url', 'timeout_seconds'):
        old.pop(key)
    with learning_database.transaction() as connection:
        connection.execute('UPDATE learning_discussion_turn SET provider_snapshot_json=? WHERE id=?',
                           (json.dumps(old), turn_id))
    service.get(IDENTITY, discussion_id)
    service.start(IDENTITY, discussion_id, '旧问题', 'old')
    assert snapshot(learning_database, turn_id) == old
