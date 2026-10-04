"""Draft and saved model defaults use returned facts before any private write."""
import json

import httpx
import pytest

from test_ai_conversations import FAKE_API_KEY, authorize, configure_provider, make_client
from test_model_control import RecordingProvider, checked, make_scope, new_chat, send, view
from test_reasoning_control import bind, effort, support_path


class CatalogProvider(RecordingProvider):
    def __init__(self, item):
        super().__init__()
        self.item = item
        self.catalog_calls = []

    def __call__(self, request):
        if request.method == 'GET':
            self.catalog_calls.append(request)
            return httpx.Response(200, json={'data': [self.item]})
        return super().__call__(request)


def provider_payload(model='custom-alias', **changes):
    return {'display_name': 'Synthetic', 'base_url': 'https://metadata.example.test/v1',
            'api_protocol': 'openai_compatible', 'model': model, 'api_key': FAKE_API_KEY,
            'is_default': True, **changes}


def facts(client):
    database = client.app.state.database
    return {table: [tuple(row) for row in database.fetchall(f'SELECT * FROM {table} ORDER BY rowid')]
            for table in ('provider_profile', 'provider_model')}


def encrypted_credentials(client):
    store = client.app.state.credentials
    return store.store_path.read_bytes() if store.store_path.exists() else None


def preview_body(profile=None, **changes):
    body = provider_payload()
    for key in ('display_name', 'is_default'):
        body.pop(key)
    if profile:
        body.update(provider_id=profile['id'], base_url=profile['base_url'], model=profile['model'])
        body.pop('api_key')
    return {**body, **changes}


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
@pytest.mark.parametrize('levels', [['low', 'high', 'max'], ['minimal', 'low', 'medium', 'high', 'xhigh'], ['max', 'low', 'high']])
def test_actual_discovery_levels_preview_and_implicit_high_reach_both_learning_routes(tmp_path, kind, levels):
    provider = CatalogProvider({'id': 'custom-alias', 'effort': {'supported_levels': levels, 'default_level': 'high'},
                                'max_output_tokens': 8192, 'api_key': FAKE_API_KEY})
    with make_client(tmp_path, provider) as client:
        authorize(client)
        discovered = checked(client.post('/api/ai/provider/models', json={
            'base_url': provider_payload()['base_url'], 'api_key': FAKE_API_KEY, 'api_protocol': 'openai_compatible'}))
        assert discovered['reasoning_metadata']['custom-alias']['effort_levels'] == levels
        before = facts(client), encrypted_credentials(client)
        draft = checked(client.post('/api/ai/provider/reasoning-preview', json=preview_body()))
        ordered = sorted(levels, key=['minimal', 'low', 'medium', 'high', 'xhigh', 'max'].index)
        assert draft['capability']['efforts'] == ordered and draft['capability']['source'] == 'api'
        assert draft['default_choice'] == effort('high') and draft['configured_default'] is None
        assert (facts(client), encrypted_credentials(client)) == before and len(provider.catalog_calls) == 1
        profile = checked(client.post('/api/ai/providers', json=provider_payload(reasoning_settings={})), 201)['provider']
        support = checked(client.get(support_path(profile)))
        assert support['capability']['efforts'] == ordered and support['capability']['source'] == 'api'
        assert support['default_choice'] == effort('high') and support['configured_default'] is None
        scope_id, _, _ = make_scope(client, provider, kind)
        provider.payloads.clear()
        answer = send(client, kind, scope_id)
        assert answer['model_config']['reasoning'] == effort('high')
        assert answer['model_config']['reasoning_parameters'] == {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high'}
        assert all(body['reasoning_effort'] == 'high' for body in provider.payloads if body.get('stream'))
        assert len(provider.catalog_calls) == 1


@pytest.mark.parametrize('profile_id', ['qwen_budget', 'kimi_toggle'])
def test_models_without_high_require_an_explicit_default_and_preview_never_invents_one(tmp_path, profile_id):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        before = facts(client), encrypted_credentials(client)
        draft = checked(client.post('/api/ai/provider/reasoning-preview', json=preview_body(profile_id=profile_id)))
        assert draft['default_required'] is True and draft['default_choice'] is None
        rejected = client.post('/api/ai/providers', json=provider_payload(reasoning_settings={'profile_id': profile_id}))
        assert rejected.status_code == 400
        assert (facts(client), encrypted_credentials(client)) == before and provider.calls == []
        choice = {'mode': 'budget', 'budget_tokens': 2048} if profile_id == 'qwen_budget' else {'mode': 'on'}
        profile = checked(client.post('/api/ai/providers', json=provider_payload(
            reasoning_settings={'profile_id': profile_id, 'default_choice': choice})), 201)['provider']
        configured = checked(client.get(support_path(profile)))
        assert configured['configured_default'] == choice and configured['default_choice'] == choice
        saved = facts(client), encrypted_credentials(client)
        rejected = client.put(support_path(profile), json={'expected_revision': configured['revision'],
            'profile_id': profile_id, 'default_choice': None})
        assert rejected.status_code == 400
        assert (facts(client), encrypted_credentials(client)) == saved
        assert checked(client.get(support_path(profile))) == configured
        cid = new_chat(client)
        answer = send(client, 'conversation', cid)
        assert answer['model_config']['reasoning'] == choice


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_custom_model_default_is_sent_and_default_changes_make_existing_preview_stale(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        bind(client, profile, default_choice=effort('medium'))
        scope_id, _, _ = make_scope(client, provider, kind)
        token = view(client, kind, scope_id)['token']
        provider.payloads.clear()
        answer = send(client, kind, scope_id)
        assert answer['model_config']['reasoning_parameters'] == {'reasoning_effort': 'medium'}
        bind(client, profile, default_choice=effort('low'))
        current = view(client, kind, scope_id)
        assert current['token'] != token and current['effective']['reasoning'] == effort('low')
        assert all(body['reasoning_effort'] == 'medium' for body in provider.payloads if body.get('stream'))


@pytest.mark.parametrize('settings', [
    {'profile_id': 'openai_gpt54', 'default_choice': effort('max')},
    {'profile_id': 'qwen_budget'}, {'profile_id': 'not-a-profile'},
    {'profile_id': 'openai_gpt54', 'default_choice': {'mode': 'default'}},
])
def test_invalid_provider_settings_never_mutate_profile_model_or_credentials(tmp_path, settings):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        before = facts(client), encrypted_credentials(client)
        rejected = client.patch(f"/api/ai/providers/{profile['id']}", json={
            'display_name': 'Changed', 'model': 'new-alias', 'api_key': 'sk-new-synthetic-key-012345',
            'reasoning_settings': settings})
        assert rejected.status_code == 400, rejected.text
        assert (facts(client), encrypted_credentials(client)) == before and provider.calls == []
        rejected = client.post('/api/ai/providers', json=provider_payload(reasoning_settings=settings))
        assert rejected.status_code == 400
        assert (facts(client), encrypted_credentials(client)) == before


def test_support_default_save_cas_and_saved_credential_draft_discovery_preserve_manual_precedence(tmp_path):
    provider = CatalogProvider({'id': 'gpt-4o', 'effort': {'supported_levels': ['low', 'high', 'max']}})
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        bound = bind(client, profile, default_choice=effort('medium'))
        checked(client.post('/api/ai/provider/models', json={'provider_id': profile['id']}))
        assert provider.catalog_calls[0].headers['authorization'] == 'Bearer ' + FAKE_API_KEY
        before = facts(client), encrypted_credentials(client)
        draft = checked(client.post('/api/ai/provider/reasoning-preview', json=preview_body(profile)))
        assert draft['capability']['source'] == 'manual'
        assert draft['capability']['efforts'] == ['low', 'medium', 'high', 'xhigh']
        assert draft['default_choice'] == effort('medium')
        assert (facts(client), encrypted_credentials(client)) == before and len(provider.catalog_calls) == 1
        checked(client.post(f"/api/ai/providers/{profile['id']}/models/discover", json={}))
        after = checked(client.get(support_path(profile)))
        assert after['capability']['source'] == 'manual' and after['configured_default'] == effort('medium')
        assert len(provider.catalog_calls) == 1
        assert client.put(support_path(profile), json={'expected_revision': bound['revision'],
            'profile_id': 'openai_gpt54', 'default_choice': effort('low')}).status_code == 409
        assert checked(client.get(support_path(profile))) == after


def test_foreign_owner_cannot_preview_saved_keys_discover_or_change_model_defaults(tmp_path):
    provider = CatalogProvider({'id': 'gpt-4o'})
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        bound = bind(client, profile)
        database = client.app.state.database
        before = facts(client), encrypted_credentials(client)
        with database.transaction() as connection:
            connection.execute("INSERT INTO local_identity (id,device_id,display_name,timezone,created_at,updated_at) VALUES ('foreign','foreign-device','Foreign','UTC','now','now')")
            connection.execute("UPDATE sessions SET identity_id='foreign'")
        assert client.post('/api/ai/provider/reasoning-preview', json=preview_body(profile)).status_code == 404
        assert client.post('/api/ai/provider/models', json={'provider_id': profile['id']}).status_code == 404
        assert client.put(support_path(profile), json={'expected_revision': bound['revision'],
            'profile_id': 'openai_gpt54', 'default_choice': effort('low')}).status_code == 404
        assert client.patch(f"/api/ai/providers/{profile['id']}", json={'reasoning_settings': {
            'profile_id': 'openai_gpt54', 'default_choice': effort('low')}}).status_code == 404
        assert (facts(client), encrypted_credentials(client)) == before
        assert provider.catalog_calls == [] and provider.calls == []


@pytest.mark.parametrize('name,thinking,state,levels', [
    ('gemini-3.8-flash', True, 'available', ['low', 'medium', 'high']),
    ('unknown-google-alias', True, 'unknown', []),
    ('gemini-3.8-flash', False, 'unsupported', []),
])
def test_google_boolean_discovery_does_not_invent_levels_and_only_known_model_uses_registry(tmp_path, name, thinking, state, levels):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == 'GET'
        return httpx.Response(200, json={'models': [{'name': 'models/' + name, 'thinking': thinking}]})

    with make_client(tmp_path, handler) as client:
        authorize(client)
        base = 'https://google.example.test/v1beta'
        checked(client.post('/api/ai/provider/models', json={'base_url': base, 'api_key': FAKE_API_KEY, 'api_protocol': 'google'}))
        result = checked(client.post('/api/ai/provider/reasoning-preview', json={
            'base_url': base, 'api_key': FAKE_API_KEY, 'api_protocol': 'google', 'model': name}))
        assert result['capability']['state'] == state and result['capability']['efforts'] == levels
        assert result['default_choice'] == (effort('high') if state == 'available' else None)
        assert len(calls) == 1


def test_claude_actual_capabilities_define_alias_efforts_without_inventing_off(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == 'GET'
        return httpx.Response(200, json={'data': [{'id': 'custom-claude-alias', 'max_tokens': 8192,
            'capabilities': {'effort': {'supported': True, **{level: {'supported': level != 'xhigh'}
                for level in ('low', 'medium', 'high', 'xhigh', 'max')}},
                'thinking': {'supported': True, 'types': {'adaptive': {'supported': True}, 'enabled': {'supported': False}}}}}]})

    with make_client(tmp_path, handler) as client:
        authorize(client)
        base = 'https://claude.example.test/v1'
        checked(client.post('/api/ai/provider/models', json={'base_url': base, 'api_key': FAKE_API_KEY, 'api_protocol': 'anthropic'}))
        result = checked(client.post('/api/ai/provider/reasoning-preview', json={
            'base_url': base, 'api_key': FAKE_API_KEY, 'api_protocol': 'anthropic', 'model': 'custom-claude-alias'}))
        assert result['capability']['source'] == 'api'
        assert result['capability']['efforts'] == ['low', 'medium', 'high', 'max']
        assert result['capability']['supports_off'] is False and result['default_choice'] == effort('high')
        assert len(calls) == 1


@pytest.mark.parametrize('operation', ['create', 'model_patch'])
def test_known_model_without_high_cannot_be_created_or_selected_without_default_even_if_settings_omitted(tmp_path, operation):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        before = facts(client), encrypted_credentials(client)
        if operation == 'create':
            rejected = client.post('/api/ai/providers', json=provider_payload(
                model='gemini-2.5-flash', api_protocol='google', base_url='https://google.example.test/v1beta'))
        else:
            rejected = client.patch(f"/api/ai/providers/{profile['id']}", json={
                'model': 'gemini-2.5-flash', 'api_protocol': 'google', 'base_url': 'https://google.example.test/v1beta',
                'api_key': 'sk-replacement-synthetic-key-012345'})
        assert rejected.status_code == 400, rejected.text
        assert (facts(client), encrypted_credentials(client)) == before and provider.calls == []


def test_unrelated_update_of_legacy_incomplete_model_is_allowed_but_sending_stays_blocked(tmp_path):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = checked(client.put('/api/ai/provider', json={
            'display_name': 'Legacy incomplete', 'base_url': 'https://google.example.test/v1beta',
            'api_protocol': 'google', 'model': 'gemini-2.5-flash', 'api_key': FAKE_API_KEY}))['provider']
        support = checked(client.get(support_path(profile)))
        assert support['default_required'] is True and support['default_choice'] is None
        updated = checked(client.patch(f"/api/ai/providers/{profile['id']}", json={'enabled': False}))['provider']
        assert updated['enabled'] is False
        updated = checked(client.patch(f"/api/ai/providers/{profile['id']}", json={'enabled': True}))['provider']
        assert updated['enabled'] is True
        cid = new_chat(client)
        assert view(client, 'conversation', cid)['effective']['available'] is False
        assert client.post(f'/api/ai/conversations/{cid}/messages', json={
            'content': 'Synthetic', 'client_message_id': 'missing-default'}).status_code == 400
        assert provider.calls == []
