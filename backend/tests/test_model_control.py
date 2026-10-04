"""Model/timeout choices follow real learning ownership and accepted runs."""
import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest

from app.conversations import ConversationError
from app.learning_domain import DomainError
from test_ai_conversations import (
    FAKE_API_KEY, authorize, configure_provider, create_task, make_client, read_sse,
    start_conversation,
)
from test_learning_setup import setup_command
from test_learning_verifications import CHALLENGE, PASS


class HeldAnswer(httpx.AsyncByteStream):
    def __init__(self, provider):
        self.provider = provider

    async def __aiter__(self):
        self.provider.started.set()
        yield b'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n'
        while not self.provider.release.is_set():
            await asyncio.sleep(.005)
        yield b'data: [DONE]\n\n'


class RecordingProvider:
    """Only synthetic responses; the barrier exposes edits during a live run."""
    def __init__(self):
        self.calls = []
        self.payloads = []
        self.responses = []
        self.hold = False
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, request):
        body = json.loads(request.content)
        self.payloads.append(body)
        self.calls.append({
            'model': body['model'], 'host': request.url.host,
            'stream': bool(body.get('stream')),
            'timeout': request.extensions.get('timeout', {}).get('read'),
        })
        if body.get('stream'):
            if self.hold:
                return httpx.Response(200, stream=HeldAnswer(self))
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"answer"}}]}\n\ndata: [DONE]\n\n')
        answer = self.responses.pop(0) if self.responses else '{"history_query":null}'
        return httpx.Response(200, json={'choices': [{'message': {'content': answer}}]})


def checked(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def config_path(kind, scope_id):
    return f'/api/model-config/{kind}/{scope_id}'


def view(client, kind, scope_id):
    response = client.get(config_path(kind, scope_id))
    assert response.headers['cache-control'] == 'no-store'
    return checked(response)


def save(client, kind, scope_id, override):
    current = view(client, kind, scope_id)
    return checked(client.put(config_path(kind, scope_id), json={
        'expected_revision': current['revision'], 'override': override,
    }))


def preview(client, kind, scope_id, override):
    return checked(client.post(config_path(kind, scope_id) + '/preview', json={'override': override}))


def selection(profile):
    return {'provider_profile_id': profile['id'], 'provider_model_id': profile['default_model_id']}


def another_provider(client, name='second', *, api_key=FAKE_API_KEY, timeout=83):
    return checked(client.post('/api/ai/providers', json={
        'display_name': name, 'base_url': f'https://{name}.example.test/v1',
        'model': f'{name}-model', 'api_key': api_key, 'request_timeout_seconds': timeout,
    }), 201)['provider']


def seed_legacy_timeout(client, kind, scope_id, timeout):
    """Represent a scoped timeout already saved by the former five-level UI."""
    service = client.app.state.model_control
    owner = client.app.state.auth.ensure_local_identity()['id']
    stored = service._layer(owner, kind, scope_id)['override']
    service._write(owner, kind, scope_id, {**stored, 'timeout_seconds': timeout})
    with service.db.transaction() as connection:
        connection.execute('UPDATE learning_model_config SET timeout_seconds=? WHERE owner_id=? AND scope_kind=? AND scope_id=?',
                           (timeout, owner, kind, scope_id))


def stored_timeout(client, kind, scope_id):
    return client.app.state.learning.database.fetchone(
        'SELECT timeout_seconds FROM learning_model_config WHERE scope_kind=? AND scope_id=?', (kind, scope_id))[0]


def new_chat(client):
    return checked(client.post('/api/ai/conversations', json={}), 201)['conversation']['id']


def setup_room(client, key='setup'):
    created = checked(client.post('/api/learning/setup/confirm', json={
        **setup_command().model_dump(), 'idempotency_key': key,
    }), 201)
    session = checked(client.post('/api/learning/sessions', json={
        'delegation_id': created['delegation_id'], 'expected_version': 2,
        'idempotency_key': f'{key}-session',
    }), 201)
    cid = new_chat(client)
    checked(client.put(f"/api/learning/sessions/{session['id']}/room", json={'conversation_id': cid}))
    return {**created, 'session_id': session['id'], 'conversation_id': cid}


def create_discussion(client, provider, context):
    provider.responses = [CHALLENGE]
    original = checked(client.post('/api/learning/verifications', json={
        'action_id': context['action_id'], 'delegation_id': context['delegation_id'],
        'session_id': context['session_id'], 'mode': 'ai_challenge', 'request_key': str(uuid4()),
    }), 201)
    submitted = checked(client.post(f"/api/learning/verifications/{original['id']}/submit", json={
        'responses': {'q1': '合成作答'}, 'request_key': str(uuid4()), 'evidence_condition': 'independent',
    }))
    provider.responses = [PASS]
    evaluated = checked(client.post(f"/api/learning/verifications/{original['id']}/evaluate", json={
        'submission_id': submitted['latest_submission_id'], 'request_key': str(uuid4()),
    }))
    discussion = checked(client.post(f"/api/learning/verifications/{original['id']}/discussions", json={
        'submission_id': submitted['latest_submission_id'], 'question_id': 'q1',
        'request_key': str(uuid4()),
    }), 201)
    return discussion['id'], evaluated


def make_scope(client, provider, kind):
    context = setup_room(client)
    if kind == 'conversation':
        return context['conversation_id'], context, None
    did, original = create_discussion(client, provider, context)
    return did, context, original


def message_path(kind, scope_id):
    if kind == 'conversation':
        return f'/api/ai/conversations/{scope_id}/messages'
    return f'/api/learning/discussions/{scope_id}/messages'


def message_payload(kind, key='message', **extra):
    return {'content': '合成问题', 'client_message_id' if kind == 'conversation' else 'request_key': key, **extra}


def finish(client, kind, scope_id, accepted):
    if kind == 'conversation':
        run = accepted['run']
        read_sse(client, run['id'])
        messages = checked(client.get(f'/api/ai/conversations/{scope_id}'))['messages']
        return next(item for item in messages if item['id'] == run['response_message_id'])
    turn_id = accepted['turns'][-1]['id']
    response = client.get(f'/api/learning/discussions/{scope_id}/turns/{turn_id}/stream')
    assert response.status_code == 200, response.text
    result = checked(client.get(f'/api/learning/discussions/{scope_id}'))
    return next(item for item in result['turns'] if item['id'] == turn_id)


def send(client, kind, scope_id, key='message', **extra):
    accepted = checked(client.post(message_path(kind, scope_id), json=message_payload(kind, key, **extra)),
                       202 if kind == 'conversation' else 200)
    answer = finish(client, kind, scope_id, accepted)
    assert answer['status'] in {'complete', 'succeeded'}, answer
    return answer


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_five_model_layers_use_final_provider_timeout_and_inheritance_stays_live(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        default = configure_provider(client)
        second, third = another_provider(client), another_provider(client, 'third', timeout=104)
        scope_id, context, _ = make_scope(client, provider, kind)
        before_calls = len(provider.calls)
        save(client, 'global', 'default', {'model': selection(default), 'timeout_seconds': 61})
        save(client, 'plan', context['plan_id'], {'model': selection(second)})
        seed_legacy_timeout(client, 'task', context['action_id'], 37)
        save(client, kind, scope_id, {'model': selection(third)})
        seed_legacy_timeout(client, kind, scope_id, 44)
        current = view(client, kind, scope_id)
        assert current['effective']['model_id'] == 'third-model'
        assert current['effective']['timeout_seconds'] == 104
        assert current['override']['timeout_seconds'] is None
        assert current['effective']['timeout_policy'] == 'provider_default'
        assert current['sources'] == {'model': {'kind': kind, 'id': scope_id},
                                      'timeout': {'kind': 'global', 'id': 'default'}}
        assert [(layer['kind'], layer['id']) for layer in current['layers']] == [
            ('global', 'default'), ('plan', context['plan_id']), ('task', context['action_id']), (kind, scope_id)]
        transient = preview(client, kind, scope_id, {'model': selection(default), 'timeout_seconds': 75})
        assert transient['effective']['model_id'] == 'gpt-4o'
        assert transient['effective']['timeout_seconds'] == 75
        assert transient['effective']['timeout_policy'] == 'run_extension'
        assert transient['sources'] == {field: {'kind': 'run', 'id': scope_id} for field in ('model', 'timeout')}
        assert transient['revision'] == current['revision']
        model_only = preview(client, kind, scope_id, {'model': selection(default)})
        assert model_only['effective']['timeout_seconds'] == 61
        assert model_only['sources']['timeout'] == {'kind': 'global', 'id': 'default'}
        timeout_only = preview(client, kind, scope_id, {'timeout_seconds': 120})
        assert timeout_only['effective']['model_id'] == 'third-model'
        assert timeout_only['sources']['model'] == {'kind': kind, 'id': scope_id}
        assert view(client, kind, scope_id) == current
        inherited = save(client, kind, scope_id, {})
        assert inherited['effective']['model_id'] == 'second-model'
        assert inherited['effective']['timeout_seconds'] == 83
        assert stored_timeout(client, kind, scope_id) == 44
        save(client, 'plan', context['plan_id'], {'model': selection(third)})
        inherited = view(client, kind, scope_id)
        assert inherited['effective']['model_id'] == 'third-model' and inherited['effective']['timeout_seconds'] == 104
        save(client, 'task', context['action_id'], {})
        assert view(client, kind, scope_id)['effective']['timeout_seconds'] == 104
        assert stored_timeout(client, 'task', context['action_id']) == 37
        save(client, 'plan', context['plan_id'], {})
        final = view(client, kind, scope_id)
        assert final['effective']['model_id'] == 'gpt-4o' and final['effective']['timeout_seconds'] == 61
        assert final['sources'] == {field: {'kind': 'global', 'id': 'default'} for field in ('model', 'timeout')}
        assert len(provider.calls) == before_calls
        assert FAKE_API_KEY not in json.dumps(transient)
        assert all(secret not in transient['effective'] for secret in ('api_key', 'credential_key', 'base_url'))


def test_old_planning_links_do_not_invent_learning_domain_parents(tmp_path):
    with make_client(tmp_path, RecordingProvider()) as client:
        authorize(client); configure_provider(client)
        cid = start_conversation(client, create_task(client))
        assert [layer['kind'] for layer in view(client, 'conversation', cid)['layers']] == ['global', 'conversation']


@pytest.mark.parametrize('override', [
    {'timeout_seconds': 4}, {'timeout_seconds': 601}, {'timeout_seconds': True},
    {'model': {'provider_profile_id': 'partial'}}, {'reasoning_effort': 'high'},
])
def test_invalid_override_is_rejected_without_mutation(tmp_path, override):
    with make_client(tmp_path, RecordingProvider()) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        before = view(client, 'conversation', cid)
        response = client.put(config_path('conversation', cid), json={
            'expected_revision': before['revision'], 'override': override})
        assert response.status_code == 400
        assert view(client, 'conversation', cid) == before


def test_scoped_timeout_writes_are_explicitly_rejected_and_legacy_values_survive_model_saves(tmp_path):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        configure_provider(client)
        second = another_provider(client)
        did, context, _ = make_scope(client, provider, 'discussion')
        for kind, scope_id in [('plan', context['plan_id']), ('task', context['action_id']),
                               ('conversation', context['conversation_id']), ('discussion', did)]:
            seed_legacy_timeout(client, kind, scope_id, 37)
            before = view(client, kind, scope_id)
            rejected = client.put(config_path(kind, scope_id), json={
                'expected_revision': before['revision'], 'override': {'timeout_seconds': 97}})
            assert rejected.status_code == 400 and '仅本次' in rejected.text
            assert view(client, kind, scope_id) == before
            for override in ({'model': selection(second)}, {'model': selection(second), 'timeout_seconds': None}, {}):
                saved = save(client, kind, scope_id, override)
                assert saved['override']['timeout_seconds'] is None
                assert stored_timeout(client, kind, scope_id) == 37


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_one_run_timeout_can_only_extend_final_provider_default(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        configure_provider(client)
        second = another_provider(client)
        scope_id, _, _ = make_scope(client, provider, kind)
        persistent = view(client, kind, scope_id)
        for timeout in (None, 83, 105):
            override = {'model': selection(second), 'timeout_seconds': timeout}
            current = preview(client, kind, scope_id, override)
            assert current['effective']['timeout_seconds'] == (83 if timeout is None else timeout)
            assert current['sources']['timeout']['kind'] == ('global' if timeout is None else 'run')
            answer = send(client, kind, scope_id, str(timeout), model_override=override, model_config_token=current['token'])
            assert answer['model_config']['timeout_seconds'] == current['effective']['timeout_seconds']
        before_calls = len(provider.calls)
        for timeout in (82, 4, 601, True):
            override = {'model': selection(second), 'timeout_seconds': timeout}
            rejected = client.post(config_path(kind, scope_id) + '/preview', json={'override': override})
            assert rejected.status_code == 400
            rejected_send = client.post(message_path(kind, scope_id), json=message_payload(kind, f'bad-{timeout}', model_override=override))
            assert rejected_send.status_code == 400
        assert len(provider.calls) == before_calls
        assert view(client, kind, scope_id) == persistent


def test_cas_cross_owner_and_provider_model_pair_are_enforced(tmp_path):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        default = configure_provider(client)
        other = another_provider(client)
        did, context, _ = make_scope(client, provider, 'discussion')
        cid = context['conversation_id']
        before = view(client, 'conversation', cid)
        changed = save(client, 'conversation', cid, {'model': selection(other)})
        assert changed['revision'] != before['revision']
        assert client.put(config_path('conversation', cid), json={
            'expected_revision': before['revision'], 'override': {}}).status_code == 409
        wrong_pair = {'provider_profile_id': default['id'], 'provider_model_id': other['default_model_id']}
        assert client.put(config_path('conversation', cid), json={
            'expected_revision': changed['revision'], 'override': {'model': wrong_pair}}).status_code == 400
        owner = client.app.state.auth.ensure_local_identity()['id']
        db = client.app.state.database
        with db.transaction() as connection:
            connection.execute("INSERT INTO local_identity (id,device_id,display_name,timezone,created_at,updated_at) VALUES ('foreign-owner','foreign-device','Foreign','UTC','now','now')")
        foreign = client.app.state.conversations.create_provider('foreign-owner', display_name='Foreign',
            base_url='https://foreign.example.test/v1', model='foreign-model', api_key=FAKE_API_KEY)
        assert client.put(config_path('conversation', cid), json={
            'expected_revision': changed['revision'], 'override': {'model': selection(foreign)}}).status_code == 400
        service = client.app.state.model_control
        for kind, scope_id in [('plan', context['plan_id']), ('task', context['action_id']),
                               ('conversation', cid), ('discussion', did)]:
            with pytest.raises((ConversationError, DomainError)):
                service.get('foreign-owner', kind, scope_id)
        assert view(client, 'conversation', cid) == changed
        assert client.app.state.learning.database.fetchone(
            "SELECT COUNT(*) FROM learning_model_config WHERE owner_id<>?", (owner,))[0] == 0


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
@pytest.mark.parametrize('unavailable', ['disabled', 'deleted', 'credentials'])
def test_explicit_unavailable_model_fails_before_acceptance_instead_of_falling_back(tmp_path, kind, unavailable):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        selected = another_provider(client)
        scope_id, _, _ = make_scope(client, provider, kind)
        save(client, kind, scope_id, {'model': selection(selected)})
        if unavailable == 'disabled':
            checked(client.patch(f"/api/ai/providers/{selected['id']}", json={'enabled': False}))
        elif unavailable == 'deleted':
            assert client.delete(f"/api/ai/providers/{selected['id']}").status_code == 204
        else:
            credential = client.app.state.database.fetchone('SELECT credential_key FROM provider_profile WHERE id=?', (selected['id'],))[0]
            client.app.state.conversations.credentials.delete(credential)
        before_calls = len(provider.calls)
        current = view(client, kind, scope_id)
        assert current['issues'] and current['effective']['available'] is False
        response = client.post(message_path(kind, scope_id), json=message_payload(kind))
        assert response.status_code == 400, response.text
        assert len(provider.calls) == before_calls
        assert view(client, kind, scope_id)['override']['model'] == selection(selected)
        inherited = save(client, kind, scope_id, {})
        assert inherited['effective']['available'] is True and inherited['effective']['model_id'] == 'gpt-4o'


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_stale_persistent_and_one_run_preview_tokens_reject_new_requests(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        second = another_provider(client)
        scope_id, context, _ = make_scope(client, provider, kind)
        stale = view(client, kind, scope_id)['token']
        save(client, 'task', context['action_id'], {'model': selection(second)})
        before_calls = len(provider.calls)
        response = client.post(message_path(kind, scope_id), json=message_payload(kind, model_config_token=stale))
        assert response.status_code == 409, response.text
        override = {'model': selection(second), 'timeout_seconds': 97}
        stale_preview = preview(client, kind, scope_id, override)['token']
        checked(client.patch(f"/api/ai/providers/{second['id']}", json={'request_timeout_seconds': 88}))
        response = client.post(message_path(kind, scope_id), json=message_payload(kind,
            model_override=override, model_config_token=stale_preview))
        assert response.status_code == 409, response.text
        assert len(provider.calls) == before_calls
        fresh = preview(client, kind, scope_id, override)['token']
        assert fresh != stale_preview
        answer = send(client, kind, scope_id, model_override=override, model_config_token=fresh)
        assert answer['model_config']['timeout_seconds'] == 97


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_real_requests_freeze_one_run_config_and_replay_exact_override(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        default = configure_provider(client)
        second = another_provider(client)
        scope_id, _, _ = make_scope(client, provider, kind)
        persistent = view(client, kind, scope_id)
        override = {'model': selection(second), 'timeout_seconds': 97}
        token = preview(client, kind, scope_id, override)['token']
        payload = message_payload(kind, model_override=override, model_config_token=token)
        provider.calls.clear(); provider.hold = True
        try:
            accepted = checked(client.post(message_path(kind, scope_id), json=payload),
                               202 if kind == 'conversation' else 200)
            assert provider.started.wait(5), 'mock stream did not start'
            assert view(client, kind, scope_id) == persistent
            save(client, kind, scope_id, {'model': selection(default)})
            checked(client.patch(f"/api/ai/providers/{second['id']}", json={'display_name': 'Later provider name'}))
        finally:
            provider.release.set()
        answer = finish(client, kind, scope_id, accepted)
        saved = answer['model_config']
        assert saved['model_id'] == 'second-model' and saved['timeout_seconds'] == 97
        assert saved['provider_display_name'] == 'second'
        assert saved['sources'] == {field: {'kind': 'run', 'id': scope_id} for field in ('model', 'timeout')}
        answer_calls = provider.calls if kind == 'discussion' else [call for call in provider.calls if call['stream']]
        assert answer_calls
        assert all(call['model'] == 'second-model' and call['timeout'] == 97 for call in answer_calls), answer_calls
        before_calls = len(provider.calls)
        checked(client.patch(f"/api/ai/providers/{second['id']}", json={'enabled': False}))
        replay = checked(client.post(message_path(kind, scope_id), json=payload),
                         202 if kind == 'conversation' else 200)
        replay_answer = finish(client, kind, scope_id, replay)
        assert replay_answer['id'] == answer['id'] and replay_answer['model_config'] == saved
        assert len(provider.calls) == before_calls
        changed_override = {**override, 'timeout_seconds': 98}
        assert client.post(message_path(kind, scope_id), json={**payload, 'model_override': changed_override}).status_code == 409
        provider.hold = False
        retry_field = 'regenerate_message_id' if kind == 'conversation' else 'regenerate_turn_id'
        regenerated = send(client, kind, scope_id, 'regenerated', **{retry_field: answer['id']})
        assert regenerated['model_config']['model_id'] == 'gpt-4o'
        assert regenerated['model_config']['timeout_seconds'] == 60
        assert regenerated['model_config']['sources']['model'] == {'kind': kind, 'id': scope_id}
        if kind == 'conversation':
            history = checked(client.get(f'/api/ai/conversations/{scope_id}'))['messages']
        else:
            history = checked(client.get(f'/api/learning/discussions/{scope_id}'))['turns']
        assert next(item for item in history if item['id'] == answer['id'])['model_config'] == saved


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_accepted_legacy_timeout_replay_keeps_its_old_snapshot_after_policy_change(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        configure_provider(client)
        second = another_provider(client)
        scope_id, context, _ = make_scope(client, provider, kind)
        override = {'model': selection(second), 'timeout_seconds': 97}
        payload = message_payload(kind, model_override=override)
        accepted = checked(client.post(message_path(kind, scope_id), json=payload),
                           202 if kind == 'conversation' else 200)
        answer = finish(client, kind, scope_id, accepted)
        db = client.app.state.database if kind == 'conversation' else client.app.state.learning.database
        if kind == 'conversation':
            query = 'SELECT config_snapshot_json FROM ai_run WHERE response_message_id=?'
            update = 'UPDATE ai_run SET config_snapshot_json=? WHERE response_message_id=?'
        else:
            query = 'SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?'
            update = 'UPDATE learning_discussion_turn SET provider_snapshot_json=? WHERE id=?'
        snapshot = json.loads(db.fetchone(query, (answer['id'],))[0])
        # A fixture captured by the former policy: scoped/default timeout could
        # be shorter than the selected Provider and had no policy marker.
        snapshot['model_control'].pop('timeout_policy')
        snapshot['model_control']['timeout_seconds'] = 37
        snapshot['model_control']['sources']['timeout'] = {'kind': 'task', 'id': context['action_id']}
        snapshot['model_override']['timeout_seconds'] = 37
        if kind == 'conversation':
            snapshot['effective']['timeout_seconds'] = 37
        else:
            snapshot['timeout_seconds'] = 37
        saved_snapshot = json.dumps(snapshot)
        with db.transaction() as connection:
            connection.execute(update, (saved_snapshot, answer['id']))
        old_override = {**override, 'timeout_seconds': 37}
        assert client.post(config_path(kind, scope_id) + '/preview', json={'override': old_override}).status_code == 400
        checked(client.patch(f"/api/ai/providers/{second['id']}", json={'enabled': False}))
        before_calls = len(provider.calls)
        replay = checked(client.post(message_path(kind, scope_id), json={**payload, 'model_override': old_override}),
                         202 if kind == 'conversation' else 200)
        replay_answer = finish(client, kind, scope_id, replay)
        assert replay_answer['id'] == answer['id']
        assert replay_answer['model_config'] == snapshot['model_control']
        assert db.fetchone(query, (answer['id'],))[0] == saved_snapshot
        assert len(provider.calls) == before_calls


def test_discussion_inherits_original_task_while_formal_verification_uses_latest_room(tmp_path):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        task_model, room_model = another_provider(client, 'task'), another_provider(client, 'room', timeout=79)
        context = setup_room(client)
        seed_legacy_timeout(client, 'plan', context['plan_id'], 51)
        save(client, 'task', context['action_id'], {'model': selection(task_model)})
        did, original = create_discussion(client, provider, context)
        other_room = new_chat(client)
        save(client, 'conversation', other_room, {'model': selection(room_model)})
        checked(client.put(f"/api/learning/sessions/{context['session_id']}/room", json={'conversation_id': other_room}))
        current = view(client, 'discussion', did)
        assert current['effective']['model_id'] == 'task-model' and current['effective']['timeout_seconds'] == 83
        seed_legacy_timeout(client, 'discussion', did, 33)
        answer = send(client, 'discussion', did)
        assert answer['model_config']['model_id'] == 'task-model' and answer['model_config']['timeout_seconds'] == 83
        verification = client.app.state.verification
        owner = client.app.state.auth.ensure_local_identity()['id']
        _, formal = verification._runtime(owner, context['session_id'])
        assert formal.model == 'room-model' and formal.timeout_seconds == 79
        after = checked(client.get(f"/api/learning/verifications/{original['id']}"))
        assert after['content']['responses'] == {'q1': '合成作答'}


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_branches_copy_current_override_and_ownership_but_keep_original_run_history(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        default = configure_provider(client)
        second = another_provider(client)
        scope_id, context, original = make_scope(client, provider, kind)
        seed_legacy_timeout(client, 'task', context['action_id'], 51)
        save(client, kind, scope_id, {'model': selection(default)})
        seed_legacy_timeout(client, kind, scope_id, 44)
        answer = send(client, kind, scope_id, model_override={'model': selection(second), 'timeout_seconds': 97})
        base = f'/api/ai/conversations/{scope_id}' if kind == 'conversation' else f'/api/learning/discussions/{scope_id}'
        field = 'message_id' if kind == 'conversation' else 'turn_id'
        branch_payload = {field: answer['id'], 'request_key': 'fork'}
        before_calls = len(provider.calls)
        fork = checked(client.post(base + '/branches', json=branch_payload), 201)
        bid = fork['conversation']['id'] if kind == 'conversation' else fork['id']
        copied = fork['messages'][-1] if kind == 'conversation' else fork['turns'][-1]
        assert copied['model_config'] == answer['model_config']
        branch_config = view(client, kind, bid)
        assert branch_config['override'] == {'model': selection(default), 'timeout_seconds': None}
        assert stored_timeout(client, kind, bid) == 44
        assert [layer['id'] for layer in branch_config['layers'][:-1]] == ['default', context['plan_id'], context['action_id']]
        if kind == 'discussion':
            assert fork['verification_id'] == original['id']
        save(client, kind, scope_id, {'model': selection(second)})
        assert view(client, kind, bid) == branch_config
        save(client, kind, bid, {})
        assert view(client, kind, scope_id)['effective']['timeout_seconds'] == 83
        repeated = checked(client.post(base + '/branches', json=branch_payload), 201)
        assert (repeated['conversation']['id'] if kind == 'conversation' else repeated['id']) == bid
        assert view(client, kind, bid)['override'] == {'model': None, 'timeout_seconds': None}
        assert stored_timeout(client, kind, bid) == 44
        assert len(provider.calls) == before_calls


def test_legacy_conversation_override_is_used_until_explicit_inheritance_is_saved(tmp_path):
    with make_client(tmp_path, RecordingProvider()) as client:
        authorize(client)
        configure_provider(client)
        second = another_provider(client)
        cid = new_chat(client)
        db = client.app.state.database
        with db.transaction() as connection:
            connection.execute('''INSERT INTO conversation_config
                (conversation_id, provider_profile_id, provider_model_id, timeout_override_seconds, config_version, updated_at)
                VALUES (?,?,?,?,7,'synthetic-time')''', (cid, second['id'], second['default_model_id'], 37))
        legacy = view(client, 'conversation', cid)
        assert legacy['revision'] == 'legacy:7' and legacy['effective']['model_id'] == 'second-model'
        assert legacy['override']['timeout_seconds'] is None
        assert legacy['effective']['timeout_seconds'] == 83
        inherited = save(client, 'conversation', cid, {})
        assert inherited['effective']['model_id'] == 'gpt-4o'
        assert db.fetchone('SELECT config_version FROM conversation_config WHERE conversation_id=?', (cid,))[0] == 7
        assert db.fetchone('SELECT timeout_override_seconds FROM conversation_config WHERE conversation_id=?', (cid,))[0] == 37
        assert view(client, 'conversation', cid) == inherited


def test_hidden_chat_keeps_settings_inaccessible_and_verification_purge_removes_overrides(tmp_path):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        did, context, original = make_scope(client, provider, 'discussion')
        cid = context['conversation_id']
        seed_legacy_timeout(client, 'conversation', cid, 31)
        seed_legacy_timeout(client, 'discussion', did, 37)
        answer = send(client, 'discussion', did)
        fork = checked(client.post(f'/api/learning/discussions/{did}/branches', json={
            'turn_id': answer['id'], 'request_key': 'fork'}), 201)
        assert client.delete(f'/api/ai/conversations/{cid}').status_code == 204
        db = client.app.state.learning.database
        assert db.fetchone("SELECT timeout_seconds FROM learning_model_config WHERE scope_kind='conversation' AND scope_id=?", (cid,))[0] == 31
        assert client.get(config_path('conversation', cid)).status_code in {400, 404}
        assert client.post(message_path('conversation', cid), json=message_payload('conversation')).status_code == 404
        checked(client.post(f"/api/learning/verifications/{original['id']}/purge", json={'confirmation': 'PURGE'}))
        assert db.fetchone("SELECT COUNT(*) FROM learning_model_config WHERE scope_kind='discussion' AND scope_id IN (?,?)", (did, fork['id']))[0] == 0
        assert db.fetchone('PRAGMA integrity_check')[0] == 'ok'
        assert db.fetchall('PRAGMA foreign_key_check') == []


def test_interrupted_branch_copy_replays_creation_template_after_source_changes(tmp_path, monkeypatch):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        default = configure_provider(client)
        second = another_provider(client)
        context = setup_room(client)
        cid = context['conversation_id']
        save(client, 'conversation', cid, {'model': selection(second)})
        seed_legacy_timeout(client, 'conversation', cid, 31)
        answer = send(client, 'conversation', cid)
        payload = {'message_id': answer['id'], 'request_key': 'interrupted-copy'}
        service = client.app.state.model_control
        real_copy = service.copy_branch

        def interrupted(*args, **kwargs):
            raise RuntimeError('synthetic interruption between databases')

        monkeypatch.setattr(service, 'copy_branch', interrupted)
        with pytest.raises(RuntimeError, match='synthetic interruption'):
            client.post(f'/api/ai/conversations/{cid}/branches', json=payload)
        monkeypatch.setattr(service, 'copy_branch', real_copy)
        save(client, 'conversation', cid, {'model': selection(default)})
        copied = checked(client.post(f'/api/ai/conversations/{cid}/branches', json=payload), 201)
        bid = copied['conversation']['id']
        config = view(client, 'conversation', bid)
        assert config['override'] == {'model': selection(second), 'timeout_seconds': None}
        assert stored_timeout(client, 'conversation', bid) == 31
        assert [layer['id'] for layer in config['layers'][:-1]] == ['default', context['plan_id'], context['action_id']]
        assert copied['messages'][-1]['model_config'] == answer['model_config']


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_legacy_answer_configuration_does_not_invent_missing_sources_or_change_snapshot(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        default = configure_provider(client)
        scope_id, _, _ = make_scope(client, provider, kind)
        answer = send(client, kind, scope_id)
        db = client.app.state.database if kind == 'conversation' else client.app.state.learning.database
        if kind == 'conversation':
            query = 'SELECT config_snapshot_json FROM ai_run WHERE response_message_id=?'
            update = 'UPDATE ai_run SET config_snapshot_json=? WHERE response_message_id=?'
        else:
            query = 'SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?'
            update = 'UPDATE learning_discussion_turn SET provider_snapshot_json=? WHERE id=?'
        snapshot = json.loads(db.fetchone(query, (answer['id'],))[0])
        snapshot.pop('model_control')
        if kind == 'discussion':
            for field in ('provider_kind', 'timeout_seconds', 'runtime_snapshot_schema_version'):
                snapshot.pop(field)
        with db.transaction() as connection:
            connection.execute(update, (json.dumps(snapshot), answer['id']))
        checked(client.patch(f"/api/ai/providers/{default['id']}", json={'display_name': 'Current name', 'request_timeout_seconds': 97}))
        path = f'/api/ai/conversations/{scope_id}' if kind == 'conversation' else f'/api/learning/discussions/{scope_id}'
        history = checked(client.get(path))['messages' if kind == 'conversation' else 'turns']
        historical = next(item for item in history if item['id'] == answer['id'])['model_config']
        assert historical['model_id'] == 'gpt-4o'
        assert historical['provider_display_name'] is None
        assert historical['sources'] == {'model': None, 'timeout': None}
        assert historical['timeout_seconds'] == (60 if kind == 'conversation' else None)
        assert json.loads(db.fetchone(query, (answer['id'],))[0]) == snapshot


def test_concurrent_discussion_and_config_reads_and_saves_finish(tmp_path):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        did, _, _ = make_scope(client, provider, 'discussion')

        def read_or_save(index):
            if index % 3 == 0:
                return client.get(f'/api/learning/discussions/{did}').status_code
            current = client.get(config_path('discussion', did))
            assert current.status_code == 200
            if index % 3 == 1:
                return current.status_code
            return client.put(config_path('discussion', did), json={
                'expected_revision': current.json()['revision'], 'override': {},
            }).status_code

        executor = ThreadPoolExecutor(max_workers=3)
        try:
            pending = [executor.submit(read_or_save, index) for index in range(18)]
            assert all(future.result(timeout=5) in {200, 409} for future in pending)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


def test_native_search_uses_final_one_run_protocol_without_changing_saved_model_or_tool(tmp_path):
    from test_provider_image_inputs import json_reply, stream_reply

    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return stream_reply('openai_responses') if body.get('stream') else json_reply('openai_responses')

    with make_client(tmp_path, handler) as client:
        authorize(client); configure_provider(client)
        selected = another_provider(client)
        checked(client.patch(f"/api/ai/providers/{selected['id']}", json={'api_protocol': 'openai_responses'}))
        cid = new_chat(client)
        state_path = f'/api/conversation-state/conversation/{cid}'
        state = checked(client.put(state_path, json={
            'expected_revision': 0, 'source_scope': {'mode': 'unspecified', 'version_ids': []},
            'search_override': {'mode': 'native'},
        }))
        persistent = view(client, 'conversation', cid)
        rejected = client.post(message_path('conversation', cid), json=message_payload('conversation',
            search={'mode': 'native'}, current_state_revision=state['revision']))
        assert rejected.status_code == 400 and '没有接入模型内置搜索' in rejected.text
        assert calls == []
        assert checked(client.get(state_path))['search_override'] == {'mode': 'native'}
        override = {'model': selection(selected)}
        token = preview(client, 'conversation', cid, override)['token']
        answer = send(client, 'conversation', cid, 'supported', model_override=override,
            model_config_token=token, search={'mode': 'native'}, current_state_revision=state['revision'],
            public_search_query='合成问题')
        assert answer['model_config']['provider_kind'] == 'openai_responses'
        streamed = [call for call in calls if call.get('stream')]
        assert streamed and all(call['model'] == 'second-model' for call in streamed)
        assert streamed[0]['tools'] == [{'type': 'web_search'}]
        assert view(client, 'conversation', cid) == persistent
        assert checked(client.get(state_path))['search_override'] == {'mode': 'native'}


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_original_image_requires_capability_of_selected_one_run_model(tmp_path, kind):
    from test_material_file_inputs import image_bytes

    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        default = configure_provider(client)
        selected = another_provider(client)
        scope_id, _, _ = make_scope(client, provider, kind)
        for profile, support in ((default, False), (selected, True)):
            checked(client.put(f"/api/ai/providers/{profile['id']}/models/{profile['default_model_id']}/image-capability",
                               json={'supports_image_input': support}))
        uploaded = checked(client.post(f'/api/materials/{kind}/{scope_id}/upload', content=image_bytes(),
            headers={'X-Filename': 'synthetic.png', 'Content-Type': 'application/octet-stream'}), 201)
        scope = {'mode': 'reference', 'version_ids': [uploaded['id']]}
        before_calls = len(provider.calls)
        rejected = client.post(message_path(kind, scope_id), json=message_payload(kind,
            source_scope=scope, attachment_version_ids=[uploaded['id']], search={'mode': 'off'}))
        assert rejected.status_code in {400, 422}, rejected.text
        assert len(provider.calls) == before_calls
        persistent = view(client, kind, scope_id)
        assert persistent['effective']['supports_image_input'] is False
        override = {'model': selection(selected)}
        token = preview(client, kind, scope_id, override)['token']
        answer = send(client, kind, scope_id, 'image-supported', model_override=override,
            model_config_token=token, source_scope=scope, attachment_version_ids=[uploaded['id']], search={'mode': 'off'})
        assert answer['model_config']['model_id'] == 'second-model'
        body = next(call for call in reversed(provider.payloads) if call.get('stream'))
        assert body['model'] == 'second-model'
        assert any(part['type'] == 'image_url' for part in body['messages'][-1]['content'])
        assert view(client, kind, scope_id) == persistent
