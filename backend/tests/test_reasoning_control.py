"""Conversation choices bind one actual model; accepted history stays frozen."""
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


def bind(client, profile, profile_id='openai_gpt54', **settings):
    current = checked(client.get(support_path(profile)))
    return checked(client.put(support_path(profile), json={
        'expected_revision': current['revision'], 'profile_id': profile_id, **settings,
    }))


def stream_payloads(provider):
    return [payload for payload in provider.payloads if payload.get('stream')]


def saved_choice(client, kind, scope_id):
    raw = client.app.state.learning.database.fetchone(
        'SELECT reasoning_json FROM learning_model_config WHERE scope_kind=? AND scope_id=?', (kind, scope_id))[0]
    return json.loads(raw) if raw else None


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_model_high_default_and_persistent_bound_choice_reach_later_sends(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        bind(client, profile)
        scope_id, _, _ = make_scope(client, provider, kind)
        current = view(client, kind, scope_id)
        assert current['effective']['reasoning'] == effort('high')
        assert current['sources']['reasoning'] == {'kind': 'model', 'id': profile['default_model_id']}
        provider.payloads.clear()
        send(client, kind, scope_id, 'model-high')
        persistent = save(client, kind, scope_id, {'reasoning': effort('low')})
        assert persistent['override']['reasoning_model'] == selection(profile)
        assert saved_choice(client, kind, scope_id) == {'choice': effort('low'), 'model': selection(profile)}
        send(client, kind, scope_id, 'low-one')
        send(client, kind, scope_id, 'low-two')
        assert [body['reasoning_effort'] for body in stream_payloads(provider)] == ['high', 'low', 'low']
        assert view(client, kind, scope_id) == persistent
        restored = save(client, kind, scope_id, {'reasoning': {'mode': 'default'}})
        assert restored['override']['reasoning'] is None and saved_choice(client, kind, scope_id) is None
        assert restored['effective']['reasoning'] == effort('high')


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_old_global_plan_task_records_stay_saved_but_new_reasoning_writes_and_once_are_rejected(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        bind(client, profile)
        scope_id, context, _ = make_scope(client, provider, kind)
        owner = client.app.state.auth.ensure_local_identity()['id']
        database = client.app.state.learning.database
        with database.transaction() as connection:
            connection.execute('INSERT INTO learning_model_defaults VALUES (?,?,7,?)', (owner, json.dumps(effort('low')), 'old-time'))
            for layer, target in [('plan', context['plan_id']), ('task', context['action_id'])]:
                connection.execute('''INSERT INTO learning_model_config
                    (owner_id,scope_kind,scope_id,reasoning_json,revision,updated_at) VALUES (?,?,?,?,7,'old-time')''',
                    (owner, layer, target, json.dumps(effort('low'))))
        before = [tuple(row) for row in database.fetchall('SELECT * FROM learning_model_config ORDER BY scope_kind')]
        old_global = tuple(database.fetchone('SELECT * FROM learning_model_defaults'))
        assert view(client, kind, scope_id)['effective']['reasoning'] == effort('high')
        for layer, target in [('plan', context['plan_id']), ('task', context['action_id']), ('global', 'default')]:
            current = view(client, layer, target)
            rejected = client.put(config_path(layer, target), json={'expected_revision': current['revision'],
                                                                  'override': {'reasoning': effort('medium')}})
            assert rejected.status_code == 400
        current = view(client, 'global', 'default')
        assert client.put('/api/model-config/global/default/reasoning', json={
            'expected_revision': current['revision'], 'reasoning': effort('medium')}).status_code == 400
        calls = len(provider.calls)
        assert client.post(config_path(kind, scope_id) + '/preview', json={'override': {'reasoning': effort('low')}}).status_code == 400
        assert client.post(message_path(kind, scope_id), json=message_payload(kind, model_override={'reasoning': effort('low')})).status_code == 400
        assert len(provider.calls) == calls
        assert [tuple(row) for row in database.fetchall('SELECT * FROM learning_model_config ORDER BY scope_kind')] == before
        assert tuple(database.fetchone('SELECT * FROM learning_model_defaults')) == old_global
        for layer, target in [('plan', context['plan_id']), ('task', context['action_id'])]:
            save(client, layer, target, {'model': None})
            raw = database.fetchone('SELECT reasoning_json FROM learning_model_config WHERE scope_kind=? AND scope_id=?', (layer, target))[0]
            assert json.loads(raw) == effort('low')
        assert view(client, kind, scope_id)['effective']['reasoning'] == effort('high')


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
@pytest.mark.parametrize('choice', [effort('max'), {'mode': 'on'}, {'mode': 'budget', 'budget_tokens': 512}, effort('ultra')])
def test_invalid_or_unsupported_bound_choice_rejects_without_mutation(tmp_path, kind, choice):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        bind(client, profile)
        scope_id, _, _ = make_scope(client, provider, kind)
        before = view(client, kind, scope_id)
        calls = len(provider.calls)
        rejected = client.put(config_path(kind, scope_id), json={'expected_revision': before['revision'],
            'override': {'reasoning': choice, 'reasoning_model': selection(profile)}})
        assert rejected.status_code == 400, rejected.text
        assert view(client, kind, scope_id) == before and len(provider.calls) == calls


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_switching_models_preserves_one_bound_choice_and_never_leaks_it_to_another_model(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        first = configure_provider(client)
        bind(client, first)
        second = another_provider(client)
        bind(client, second, default_choice=effort('medium'))
        scope_id, _, _ = make_scope(client, provider, kind)
        save(client, kind, scope_id, {'reasoning': effort('low')})
        switched = save(client, kind, scope_id, {'model': selection(second)})
        assert switched['override']['reasoning_model'] == selection(first)
        assert switched['effective']['reasoning'] == effort('medium')
        provider.payloads.clear()
        send(client, kind, scope_id, 'second-default')
        save(client, kind, scope_id, {'model': selection(first)})
        assert view(client, kind, scope_id)['effective']['reasoning'] == effort('low')
        save(client, kind, scope_id, {'model': selection(second), 'reasoning': effort('xhigh')})
        assert saved_choice(client, kind, scope_id) == {'choice': effort('xhigh'), 'model': selection(second)}
        switched_back = save(client, kind, scope_id, {'model': selection(first)})
        assert switched_back['effective']['reasoning'] == effort('high')
        assert stream_payloads(provider)[0]['reasoning_effort'] == 'medium'


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_quick_choice_for_temporary_model_binds_it_without_persisting_the_model(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        first = configure_provider(client); bind(client, first)
        second = another_provider(client); bind(client, second)
        scope_id, _, _ = make_scope(client, provider, kind)
        configured = save(client, kind, scope_id, {'reasoning': effort('low'), 'reasoning_model': selection(second)})
        assert configured['override']['model'] is None
        assert configured['effective']['model_id'] == 'gpt-4o' and configured['effective']['reasoning'] == effort('high')
        assert saved_choice(client, kind, scope_id) == {'choice': effort('low'), 'model': selection(second)}
        provider.payloads.clear()
        send(client, kind, scope_id, 'temporary', model_override={'model': selection(second)})
        send(client, kind, scope_id, 'persistent')
        assert [(body['model'], body['reasoning_effort']) for body in stream_payloads(provider)] == [('second-model', 'low'), ('gpt-4o', 'high')]
        assert view(client, kind, scope_id) == configured


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_model_default_change_stales_new_requests_but_freezes_running_history_and_branch(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client); bind(client, profile)
        scope_id, _, _ = make_scope(client, provider, kind)
        token = view(client, kind, scope_id)['token']
        payload = message_payload(kind, model_config_token=token)
        provider.payloads.clear(); provider.hold = True
        try:
            accepted = checked(client.post(message_path(kind, scope_id), json=payload), 202 if kind == 'conversation' else 200)
            assert provider.started.wait(5)
            bind(client, profile, default_choice=effort('low'))
            rejected = client.post(message_path(kind, scope_id), json=message_payload(kind, 'stale', model_config_token=token))
            assert rejected.status_code == 409
        finally:
            provider.release.set()
        answer = finish(client, kind, scope_id, accepted)
        frozen = answer['model_config']
        assert frozen['reasoning'] == effort('high')
        calls = provider.payloads if kind == 'discussion' else stream_payloads(provider)
        assert calls and all(body['reasoning_effort'] == 'high' for body in calls)
        count = len(provider.calls)
        replay = checked(client.post(message_path(kind, scope_id), json=payload), 202 if kind == 'conversation' else 200)
        assert finish(client, kind, scope_id, replay)['model_config'] == frozen and len(provider.calls) == count
        provider.hold = False
        save(client, kind, scope_id, {'reasoning': effort('medium')})
        base = f'/api/ai/conversations/{scope_id}' if kind == 'conversation' else f'/api/learning/discussions/{scope_id}'
        fork = checked(client.post(base + '/branches', json={
            'message_id' if kind == 'conversation' else 'turn_id': answer['id'], 'request_key': 'branch'}), 201)
        bid = fork['conversation']['id'] if kind == 'conversation' else fork['id']
        copied = fork['messages'][-1] if kind == 'conversation' else fork['turns'][-1]
        assert copied['model_config'] == frozen
        assert saved_choice(client, kind, bid) == {'choice': effort('medium'), 'model': selection(profile)}
        save(client, kind, scope_id, {'reasoning': effort('low')})
        assert send(client, kind, bid, 'next')['model_config']['reasoning'] == effort('medium')
        save(client, kind, bid, {'reasoning': None})
        assert send(client, kind, bid, 'model-default')['model_config']['reasoning'] == effort('low')


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_accepted_legacy_once_request_replays_saved_choice_after_new_policy(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client); bind(client, profile)
        scope_id, _, _ = make_scope(client, provider, kind)
        save(client, kind, scope_id, {'reasoning': effort('low')})
        answer = send(client, kind, scope_id, 'legacy-once')
        database = client.app.state.database if kind == 'conversation' else client.app.state.learning.database
        query = 'SELECT config_snapshot_json FROM ai_run WHERE response_message_id=?' if kind == 'conversation' else 'SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?'
        update = 'UPDATE ai_run SET config_snapshot_json=? WHERE response_message_id=?' if kind == 'conversation' else 'UPDATE learning_discussion_turn SET provider_snapshot_json=? WHERE id=?'
        snapshot = json.loads(database.fetchone(query, (answer['id'],))[0])
        snapshot['model_override'] = {'model': None, 'timeout_seconds': None, 'reasoning': effort('low')}
        snapshot['model_control']['sources']['reasoning'] = {'kind': 'run', 'id': scope_id}
        with database.transaction() as connection:
            connection.execute(update, (json.dumps(snapshot), answer['id']))
        save(client, kind, scope_id, {'reasoning': None})
        count = len(provider.calls)
        payload = message_payload(kind, 'legacy-once', model_override={'reasoning': effort('low')}, model_config_token='old-token')
        replay = checked(client.post(message_path(kind, scope_id), json=payload), 202 if kind == 'conversation' else 200)
        restored = finish(client, kind, scope_id, replay)
        assert restored['id'] == answer['id'] and restored['model_config'] == snapshot['model_control']
        assert json.loads(database.fetchone(query, (answer['id'],))[0]) == snapshot and len(provider.calls) == count
        assert client.post(message_path(kind, scope_id), json={**payload,
            'model_override': {'reasoning': effort('high')}}).status_code == 409


@pytest.mark.parametrize('changed', ['endpoint', 'protocol'])
def test_manual_alias_binding_staleness_rejects_old_token_and_requires_refresh(tmp_path, changed):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client); bind(client, profile)
        cid = new_chat(client)
        save(client, 'conversation', cid, {'reasoning': effort('high')})
        token = view(client, 'conversation', cid)['token']
        mutation = {'base_url': 'https://changed.example.test/v1'} if changed == 'endpoint' else {'api_protocol': 'openai_responses'}
        checked(client.patch(f"/api/ai/providers/{profile['id']}", json=mutation))
        stale = checked(client.get(support_path(profile)))
        assert stale['capability']['state'] == 'unknown' and stale['capability']['stale'] is True
        assert client.post(message_path('conversation', cid), json=message_payload('conversation', model_config_token=token)).status_code == 409
        assert client.post(message_path('conversation', cid), json=message_payload('conversation')).status_code == 400
        assert provider.calls == []
        assert bind(client, profile)['capability']['state'] == 'available'


def test_bound_choice_owner_model_pair_and_cas_prevent_foreign_or_stale_updates(tmp_path):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        first = configure_provider(client); bind(client, first)
        second = another_provider(client); bind(client, second)
        cid = new_chat(client)
        before = view(client, 'conversation', cid)
        saved = save(client, 'conversation', cid, {'reasoning': effort('low')})
        assert client.put(config_path('conversation', cid), json={'expected_revision': before['revision'],
            'override': {'reasoning': effort('high')}}).status_code == 409
        bad_pair = {'provider_profile_id': first['id'], 'provider_model_id': second['default_model_id']}
        assert client.put(config_path('conversation', cid), json={'expected_revision': saved['revision'],
            'override': {'reasoning': effort('low'), 'reasoning_model': bad_pair}}).status_code == 400
        database = client.app.state.database
        with database.transaction() as connection:
            connection.execute("INSERT INTO local_identity (id,device_id,display_name,timezone,created_at,updated_at) VALUES ('foreign','foreign-device','Foreign','UTC','now','now')")
        foreign = client.app.state.conversations.create_provider('foreign', display_name='Foreign', base_url='https://foreign.example.test/v1', model='foreign-model', api_key=FAKE_API_KEY)
        assert client.put(config_path('conversation', cid), json={'expected_revision': saved['revision'],
            'override': {'reasoning': effort('low'), 'reasoning_model': selection(foreign)}}).status_code == 400
        assert view(client, 'conversation', cid) == saved and provider.calls == []


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
