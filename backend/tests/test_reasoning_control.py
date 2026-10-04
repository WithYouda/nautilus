"""Reasoning selections reach accepted requests and stay scoped to their owner."""
import json
import sqlite3
from contextlib import closing

import pytest

from app.config import Settings
from app.db import Database
from app.learning_production import upgrade_learning_database
from app.learning_service import LearningService
from test_ai_conversations import FAKE_API_KEY, authorize, configure_provider, make_client
from test_learning_verifications import IDENTITY
from test_model_control import (
    RecordingProvider, another_provider, checked, config_path, finish, make_scope,
    message_path, message_payload, new_chat, preview, save, selection, send, view,
)


def effort(level):
    return {'mode': 'effort', 'effort': level}


def support_path(profile):
    return f"/api/ai/providers/{profile['id']}/models/{profile['default_model_id']}/reasoning-support"


def bind(client, profile, profile_id='openai_gpt54'):
    current = checked(client.get(support_path(profile)))
    return checked(client.put(support_path(profile), json={
        'expected_revision': current['revision'], 'profile_id': profile_id,
    }))


def global_reasoning(client, choice):
    before = view(client, 'global', 'default')
    return checked(client.put('/api/model-config/global/default/reasoning', json={
        'expected_revision': before['revision'], 'reasoning': choice,
    }))


def stream_payloads(provider):
    return [payload for payload in provider.payloads if payload.get('stream')]


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_persistent_effort_applies_to_later_sends_and_once_does_not_change_it(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        bind(client, profile)
        scope_id, _, _ = make_scope(client, provider, kind)
        persistent = save(client, kind, scope_id, {'reasoning': effort('high')})
        assert persistent['effective']['reasoning_parameters'] == {'reasoning_effort': 'high'}
        provider.payloads.clear()
        first = send(client, kind, scope_id, 'first')
        send(client, kind, scope_id, 'second')
        override = {'reasoning': effort('low')}
        token = preview(client, kind, scope_id, override)['token']
        once = send(client, kind, scope_id, 'once', model_override=override, model_config_token=token)
        assert view(client, kind, scope_id) == persistent
        after = send(client, kind, scope_id, 'after-once')
        assert [payload['reasoning_effort'] for payload in stream_payloads(provider)] == ['high', 'high', 'low', 'high']
        assert first['model_config']['reasoning'] == effort('high')
        assert first['model_config']['sources']['reasoning'] == {'kind': kind, 'id': scope_id}
        assert once['model_config']['reasoning_parameters'] == {'reasoning_effort': 'low'}
        assert once['model_config']['sources']['reasoning'] == {'kind': 'run', 'id': scope_id}
        assert after['model_config']['reasoning'] == effort('high')


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_reasoning_inherits_real_global_plan_task_and_default_stops_inheritance(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        bind(client, profile)
        scope_id, context, _ = make_scope(client, provider, kind)
        provider_version = view(client, 'global', 'default')['effective']['provider_config_version']
        global_reasoning(client, effort('high'))
        assert view(client, 'global', 'default')['effective']['provider_config_version'] == provider_version
        save(client, 'plan', context['plan_id'], {'reasoning': effort('medium')})
        save(client, 'task', context['action_id'], {'reasoning': effort('low')})
        inherited = view(client, kind, scope_id)
        assert inherited['effective']['reasoning'] == effort('low')
        assert inherited['sources']['reasoning'] == {'kind': 'task', 'id': context['action_id']}
        provider.payloads.clear()
        send(client, kind, scope_id, 'inherited')
        explicit_default = save(client, kind, scope_id, {'reasoning': {'mode': 'default'}})
        assert explicit_default['sources']['reasoning'] == {'kind': kind, 'id': scope_id}
        assert explicit_default['effective']['reasoning_parameters'] == {}
        answer = send(client, kind, scope_id, 'default')
        assert answer['model_config']['reasoning'] == {'mode': 'default'}
        assert stream_payloads(provider)[0]['reasoning_effort'] == 'low'
        assert 'reasoning_effort' not in stream_payloads(provider)[1]
        assert 'reasoning' not in stream_payloads(provider)[1]
        restored = save(client, kind, scope_id, {'reasoning': None})
        assert restored['effective']['reasoning'] == effort('low')
        save(client, 'task', context['action_id'], {})
        assert view(client, kind, scope_id)['effective']['reasoning'] == effort('medium')
        save(client, 'plan', context['plan_id'], {})
        assert view(client, kind, scope_id)['effective']['reasoning'] == effort('high')
        global_reasoning(client, None)
        final = view(client, kind, scope_id)
        assert final['effective']['reasoning'] == {'mode': 'default'}
        assert final['sources']['reasoning'] is None


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
@pytest.mark.parametrize('choice', [effort('max'), {'mode': 'on'},
    {'mode': 'budget', 'budget_tokens': 512}, effort('ultra')])
def test_invalid_or_unsupported_choice_rejects_save_and_send_without_mutation(tmp_path, kind, choice):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        bind(client, profile)
        scope_id, _, _ = make_scope(client, provider, kind)
        before = view(client, kind, scope_id)
        database = client.app.state.learning.database
        rows = [tuple(row) for row in database.fetchall('SELECT * FROM learning_model_config ORDER BY scope_kind,scope_id')]
        before_calls = len(provider.calls)
        rejected = client.put(config_path(kind, scope_id), json={
            'expected_revision': before['revision'], 'override': {'reasoning': choice},
        })
        assert rejected.status_code == 400, rejected.text
        rejected = client.post(message_path(kind, scope_id), json=message_payload(kind,
            model_override={'reasoning': choice}))
        assert rejected.status_code == 400, rejected.text
        assert view(client, kind, scope_id) == before
        assert [tuple(row) for row in database.fetchall('SELECT * FROM learning_model_config ORDER BY scope_kind,scope_id')] == rows
        assert len(provider.calls) == before_calls


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_switching_model_revalidates_inherited_effort_and_cannot_silently_downgrade(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        bind(client, profile)
        other = another_provider(client)
        bind(client, other, 'kimi_k3')
        scope_id, _, _ = make_scope(client, provider, kind)
        global_reasoning(client, effort('xhigh'))
        before = view(client, kind, scope_id)
        assert before['sources']['reasoning'] == {'kind': 'global', 'id': 'default'}
        calls = len(provider.calls)
        response = client.put(config_path(kind, scope_id), json={
            'expected_revision': before['revision'], 'override': {'model': selection(other)},
        })
        assert response.status_code == 400 and '不会自动降档' in response.text
        response = client.post(message_path(kind, scope_id), json=message_payload(kind,
            model_override={'model': selection(other)}))
        assert response.status_code == 400 and '不会自动降档' in response.text
        assert len(provider.calls) == calls and view(client, kind, scope_id) == before
        compatible = save(client, kind, scope_id, {'model': selection(other), 'reasoning': {'mode': 'default'}})
        assert compatible['effective']['model_id'] == 'second-model'
        assert compatible['effective']['reasoning_parameters'] == {}


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_ongoing_reasoning_is_frozen_replay_checks_choice_and_branch_copies_persistent_choice(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        bind(client, profile)
        scope_id, _, _ = make_scope(client, provider, kind)
        save(client, kind, scope_id, {'reasoning': effort('high')})
        override = {'reasoning': effort('low')}
        token = preview(client, kind, scope_id, override)['token']
        payload = message_payload(kind, model_override=override, model_config_token=token)
        provider.payloads.clear(); provider.hold = True
        try:
            accepted = checked(client.post(message_path(kind, scope_id), json=payload),
                               202 if kind == 'conversation' else 200)
            assert provider.started.wait(5)
            save(client, kind, scope_id, {'reasoning': effort('medium')})
        finally:
            provider.release.set()
        answer = finish(client, kind, scope_id, accepted)
        frozen = answer['model_config']
        assert frozen['reasoning'] == effort('low')
        answer_calls = provider.payloads if kind == 'discussion' else stream_payloads(provider)
        assert answer_calls and all(body['reasoning_effort'] == 'low' for body in answer_calls)
        calls = len(provider.calls)
        replay = checked(client.post(message_path(kind, scope_id), json=payload), 202 if kind == 'conversation' else 200)
        assert finish(client, kind, scope_id, replay)['model_config'] == frozen
        assert len(provider.calls) == calls
        mismatch = {**payload, 'model_override': {'reasoning': effort('high')}}
        assert client.post(message_path(kind, scope_id), json=mismatch).status_code == 409
        provider.hold = False
        base = f'/api/ai/conversations/{scope_id}' if kind == 'conversation' else f'/api/learning/discussions/{scope_id}'
        branch_field = 'message_id' if kind == 'conversation' else 'turn_id'
        fork = checked(client.post(base + '/branches', json={branch_field: answer['id'], 'request_key': 'reasoning-branch'}), 201)
        bid = fork['conversation']['id'] if kind == 'conversation' else fork['id']
        inherited_answer = fork['messages'][-1] if kind == 'conversation' else fork['turns'][-1]
        assert inherited_answer['model_config'] == frozen
        assert view(client, kind, bid)['override']['reasoning'] == effort('medium')
        save(client, kind, scope_id, {'reasoning': effort('high')})
        assert view(client, kind, bid)['effective']['reasoning'] == effort('medium')
        continued = send(client, kind, bid, 'continued-branch')
        assert continued['model_config']['reasoning_parameters'] == {'reasoning_effort': 'medium'}


@pytest.mark.parametrize('changed', ['endpoint', 'protocol'])
def test_manual_alias_binding_becomes_stale_and_cannot_use_previously_previewed_choice(tmp_path, changed):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        initial = checked(client.get(support_path(profile)))
        assert initial['capability']['state'] == 'unknown'
        bound = bind(client, profile)
        assert bound['capability']['state'] == 'available' and bound['capability']['source'] == 'manual'
        cid = new_chat(client)
        save(client, 'conversation', cid, {'reasoning': effort('high')})
        token = view(client, 'conversation', cid)['token']
        mutation = {'base_url': 'https://changed.example.test/v1'} if changed == 'endpoint' else {'api_protocol': 'openai_responses'}
        checked(client.patch(f"/api/ai/providers/{profile['id']}", json=mutation))
        stale = checked(client.get(support_path(profile)))
        assert stale['capability']['state'] == 'unknown' and stale['capability']['stale'] is True
        assert stale['revision'] != bound['revision']
        assert view(client, 'conversation', cid)['effective']['available'] is False
        response = client.post(message_path('conversation', cid), json=message_payload('conversation', model_config_token=token))
        assert response.status_code == 409 and provider.calls == []
        response = client.post(message_path('conversation', cid), json=message_payload('conversation'))
        assert response.status_code == 400 and provider.calls == []
        response = client.put(support_path(profile), json={'expected_revision': bound['revision'], 'profile_id': 'openai_gpt54'})
        assert response.status_code == 409
        rebound = bind(client, profile)
        assert rebound['capability']['state'] == 'available'
        assert view(client, 'conversation', cid)['effective']['available'] is True
        expected = {'reasoning': {'effort': 'high'}} if changed == 'protocol' else {'reasoning_effort': 'high'}
        assert view(client, 'conversation', cid)['effective']['reasoning_parameters'] == expected


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
@pytest.mark.parametrize('profile_id,choice,parameters', [
    ('openai_gpt54', {'mode': 'off'}, {'reasoning_effort': 'none'}),
    ('deepseek_v4', {'mode': 'on'}, {'thinking': {'type': 'enabled'}}),
    ('qwen_budget', {'mode': 'budget', 'budget_tokens': 512}, {'enable_thinking': True, 'thinking_budget': 512}),
])
def test_supported_off_on_and_budget_are_persisted_and_sent_as_native_parameters(tmp_path, kind, profile_id, choice, parameters):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        bind(client, profile, profile_id)
        scope_id, _, _ = make_scope(client, provider, kind)
        current = save(client, kind, scope_id, {'reasoning': choice})
        assert current['effective']['reasoning_parameters'] == parameters
        provider.payloads.clear()
        answer = send(client, kind, scope_id)
        assert answer['model_config']['reasoning'] == choice
        for body in stream_payloads(provider):
            assert {key: body[key] for key in parameters} == parameters
        assert view(client, kind, scope_id) == current


def test_unknown_alias_only_allows_explicit_model_default_and_does_not_guess_capability(tmp_path):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        initial = view(client, 'conversation', cid)
        assert initial['effective']['reasoning_capability']['state'] == 'unknown'
        current = save(client, 'conversation', cid, {'reasoning': {'mode': 'default'}})
        answer = send(client, 'conversation', cid)
        assert answer['model_config']['reasoning_parameters'] == {}
        assert 'reasoning_effort' not in stream_payloads(provider)[0]
        assert client.put(config_path('conversation', cid), json={
            'expected_revision': current['revision'], 'override': {'reasoning': effort('high')},
        }).status_code == 400
        assert view(client, 'conversation', cid) == current


def test_existing_global_save_preserves_reasoning_and_rejects_cross_database_changes(tmp_path):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        bind(client, profile)
        global_reasoning(client, effort('high'))
        owner = client.app.state.auth.ensure_local_identity()['id']
        learning = client.app.state.learning.database
        original_default = tuple(learning.fetchone('SELECT * FROM learning_model_defaults WHERE owner_id=?', (owner,)))
        changed = save(client, 'global', 'default', {'model': selection(profile), 'timeout_seconds': 97})
        assert changed['effective']['reasoning'] == effort('high')
        assert changed['effective']['timeout_seconds'] == 97
        assert tuple(learning.fetchone('SELECT * FROM learning_model_defaults WHERE owner_id=?', (owner,))) == original_default
        provider_before = tuple(client.app.state.database.fetchone('SELECT * FROM provider_profile WHERE id=?', (profile['id'],)))
        rejected = client.put(config_path('global', 'default'), json={
            'expected_revision': changed['revision'], 'override': {
                'model': selection(profile), 'timeout_seconds': 120, 'reasoning': effort('low'),
            },
        })
        assert rejected.status_code == 400
        assert tuple(client.app.state.database.fetchone('SELECT * FROM provider_profile WHERE id=?', (profile['id'],))) == provider_before
        assert tuple(learning.fetchone('SELECT * FROM learning_model_defaults WHERE owner_id=?', (owner,))) == original_default
        assert view(client, 'global', 'default') == changed and provider.calls == []


@pytest.mark.parametrize('protocol,profile_id,choice,parameters', [
    ('openai_compatible', 'deepseek_v4', effort('low'), {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'low'}),
    ('openai_compatible', 'deepseek_v4', effort('max'), {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'max'}),
    ('openai_compatible', 'deepseek_v4', {'mode': 'off'}, {'thinking': {'type': 'disabled'}}),
    ('google', 'gemini25_flash', {'mode': 'budget', 'budget_tokens': 2048}, {'generationConfig': {'thinkingConfig': {'thinkingBudget': 2048}}}),
    ('anthropic', 'claude_opus45', {'mode': 'budget', 'budget_tokens': 2048, 'effort': 'high'},
     {'thinking': {'type': 'enabled', 'budget_tokens': 2048}, 'output_config': {'effort': 'high'}}),
    ('openai_compatible', 'openai_gpt6', {'mode': 'off'}, None),
])
def test_profile_specific_controls_compile_after_http_selection_and_reach_native_request(tmp_path, protocol, profile_id, choice, parameters):
    from test_provider_image_inputs import json_reply, stream_reply

    calls = []

    def handler(request):
        body = json.loads(request.content)
        streaming = body.get('stream') or 'streamGenerateContent' in str(request.url)
        calls.append((streaming, body))
        return stream_reply(protocol) if streaming else json_reply(protocol)

    with make_client(tmp_path, handler) as client:
        authorize(client)
        profile = configure_provider(client)
        checked(client.patch(f"/api/ai/providers/{profile['id']}", json={'api_protocol': protocol}))
        bind(client, profile, profile_id)
        cid = new_chat(client)
        before = view(client, 'conversation', cid)
        if parameters is None:
            assert client.put(config_path('conversation', cid), json={
                'expected_revision': before['revision'], 'override': {'reasoning': choice},
            }).status_code == 400
            assert client.post(message_path('conversation', cid), json=message_payload('conversation',
                model_override={'reasoning': choice})).status_code == 400
            assert view(client, 'conversation', cid) == before and calls == []
            return
        current = save(client, 'conversation', cid, {'reasoning': choice})
        assert current['effective']['reasoning_parameters'] == parameters
        answer = send(client, 'conversation', cid)
        assert answer['model_config']['reasoning_parameters'] == parameters
        streamed = [body for streaming, body in calls if streaming]
        assert streamed
        for body in streamed:
            if protocol == 'google':
                assert body['generationConfig']['thinkingConfig'] == {'thinkingBudget': 2048}
                assert 'thinkingLevel' not in body['generationConfig']['thinkingConfig']
            else:
                assert {key: body[key] for key in parameters} == parameters


def test_support_owner_pair_cas_and_global_reasoning_cas_are_enforced_without_provider_mutation(tmp_path):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        other = another_provider(client)
        original = checked(client.get(support_path(profile)))
        bound = bind(client, profile)
        assert client.put(support_path(profile), json={'expected_revision': original['revision'], 'profile_id': None}).status_code == 409
        assert client.get(f"/api/ai/providers/{profile['id']}/models/{other['default_model_id']}/reasoning-support").status_code == 404
        assert checked(client.get(support_path(profile))) == bound
        database = client.app.state.database
        with database.transaction() as connection:
            connection.execute("INSERT INTO local_identity (id,device_id,display_name,timezone,created_at,updated_at) VALUES ('foreign','foreign-device','Foreign','UTC','now','now')")
            connection.execute("UPDATE sessions SET identity_id='foreign'")
        assert client.get(support_path(profile)).status_code == 404
        assert client.put(support_path(profile), json={'expected_revision': bound['revision'], 'profile_id': None}).status_code == 404
        with database.transaction() as connection:
            connection.execute('UPDATE sessions SET identity_id=?', (client.app.state.auth.ensure_local_identity()['id'],))
        before = view(client, 'global', 'default')
        defaults = global_reasoning(client, effort('high'))
        assert defaults['effective']['provider_config_version'] == before['effective']['provider_config_version']
        assert client.put('/api/model-config/global/default/reasoning', json={
            'expected_revision': before['revision'], 'reasoning': None}).status_code == 409
        assert view(client, 'global', 'default') == defaults
        assert provider.calls == [] and FAKE_API_KEY not in json.dumps(bound)


def test_040_to_041_preserves_old_columns_rows_and_backups(tmp_path):
    path = tmp_path / 'learning-040.sqlite3'
    database = Database(path, Settings.from_env().migrations_dir, migration_floor=11, migration_ceiling=40)
    LearningService(database).principal(IDENTITY)
    with database.transaction() as connection:
        connection.execute('''INSERT INTO learning_model_config
            (owner_id,scope_kind,scope_id,provider_profile_id,provider_model_id,timeout_seconds,revision,updated_at)
            VALUES (?,'conversation','old-chat','old-profile','old-model',37,7,'old-time')''', (IDENTITY['id'],))
    tables = [row[0] for row in database.connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'schema_migrations'")]
    columns = {table: [row[1] for row in database.connection.execute(f'PRAGMA table_info("{table}")')] for table in tables}
    before = {table: [tuple(row) for row in database.connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid')] for table in tables}
    database.close()
    result = upgrade_learning_database(path, tmp_path / 'backups', authorized=True)
    assert result['preflight']['applied_migrations'][-1] == '040_model_control'
    assert result['post_upgrade_backup']['applied_migrations'][-1] == '041_reasoning_control'
    assert len(list((tmp_path / 'backups').glob('*.sqlite3'))) == 2
    with closing(sqlite3.connect(path)) as connection:
        for table, fields in columns.items():
            selected = ','.join('"' + field + '"' for field in fields)
            assert connection.execute(f'SELECT {selected} FROM "{table}" ORDER BY rowid').fetchall() == before[table]
        assert connection.execute('SELECT reasoning_json FROM learning_model_config').fetchone() == (None,)
        assert connection.execute('SELECT COUNT(*) FROM learning_model_defaults').fetchone() == (0,)
        assert connection.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
