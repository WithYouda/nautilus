"""Real model-list HTTP parsing retains only bounded public metadata facts."""
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from app import model_discovery
from app.model_discovery import ModelDiscoveryService
from app.providers import ProviderConfig, ProviderError, build_provider


SECRET = 'sk-metadata-fixture-secret-319742'
KINDS = ('openai_compatible', 'openai_responses', 'google', 'anthropic')


def config(kind='openai_compatible'):
    return ProviderConfig(base_url='https://catalog.example.test/v1', model='unused-alias',
                          api_key=SECRET, provider_kind=kind)


def response_body(kind, items):
    return {'models' if kind == 'google' else 'data': items}


async def catalog(kind, items):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == 'GET'
        assert request.url.path.endswith('/models')
        return httpx.Response(200, json=response_body(kind, items))

    provider = build_provider(config(kind), httpx.MockTransport(handler))
    result = await provider.list_model_catalog()
    assert len(calls) == 1
    return result


@pytest.mark.parametrize('kind', ['openai_compatible', 'openai_responses'])
async def test_deepseek_public_fields_use_wire_schema_without_id_or_endpoint_inference(kind):
    result = await catalog(kind, [{'id': ' renamed-alias ', 'created': 123, 'owned_by': SECRET,
        'effort': {'supported_levels': ['low', 'high', 'max'], 'default_level': 'high', 'api_key': SECRET},
        'max_output_tokens': 131072, 'credentials': {'api_key': SECRET}}, {'id': 'z'}, 'a'])
    assert result == [{'id': 'a'}, {'id': 'renamed-alias', 'reasoning_metadata': {
        'format': 'deepseek_effort', 'effort_levels': ['low', 'high', 'max'],
        'default_effort': 'high', 'max_output_tokens': 131072}}, {'id': 'z'}]
    assert SECRET not in json.dumps(result)


async def test_claude_flags_retain_supported_levels_modes_and_max_tokens_without_inventing_off():
    result = await catalog('anthropic', [{'id': 'custom-alias', 'capabilities': {
        'effort': {'supported': True, **{level: {'supported': level != 'xhigh'}
                    for level in ('low', 'medium', 'high', 'xhigh', 'max')}, 'secret': SECRET},
        'thinking': {'supported': True, 'types': {'adaptive': {'supported': True}, 'enabled': {'supported': False}},
                     'credentials': SECRET}, 'api_key': SECRET}, 'max_tokens': 8192, 'api_key': SECRET}])
    assert result == [{'id': 'custom-alias', 'reasoning_metadata': {
        'format': 'anthropic_capabilities', 'effort_levels': ['low', 'medium', 'high', 'max'],
        'thinking_supported': True, 'thinking_modes': ['adaptive'], 'max_output_tokens': 8192}}]
    assert 'off' not in json.dumps(result) and SECRET not in json.dumps(result)


async def test_google_thinking_boolean_preserves_false_and_does_not_infer_tiers():
    result = await catalog('google', [
        {'name': 'models/model-true', 'thinking': True, 'effort': {'supported_levels': ['high']}, 'api_key': SECRET},
        {'name': 'models/model-false', 'thinking': False},
        {'name': 'models/gemini-3.8-name-only'},
    ])
    assert result == [{'id': 'gemini-3.8-name-only'},
        {'id': 'model-false', 'reasoning_metadata': {'format': 'google_thinking', 'thinking_supported': False}},
        {'id': 'model-true', 'reasoning_metadata': {'format': 'google_thinking', 'thinking_supported': True}}]


@pytest.mark.parametrize('kind', ['openai_compatible', 'openai_responses'])
async def test_standard_openai_fields_and_familiar_names_do_not_establish_reasoning_metadata(kind):
    result = await catalog(kind, [{'id': 'gpt-6-future', 'created': 123, 'owned_by': 'openai', 'object': 'model',
                                  'unknown_reasoning': {'api_key': SECRET}}, {'id': 'deepseek-v4-pro'}])
    assert result == [{'id': 'deepseek-v4-pro'}, {'id': 'gpt-6-future'}]


@pytest.mark.parametrize('value,expected', [
    (['low', 'ultra'], None), (['low', 1], None), ('low', None), (None, None),
    ([], []), (['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'],
              ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']),
])
async def test_invalid_effort_list_is_wholly_unknown_while_explicit_empty_stays_empty(value, expected):
    metadata = (await catalog('openai_compatible', [{'id': 'alias', 'effort': {'supported_levels': value}}]))[0]['reasoning_metadata']
    assert metadata == {'format': 'deepseek_effort', **({'effort_levels': expected} if expected is not None else {})}


@pytest.mark.parametrize('item,expected', [
    ({'effort': []}, {}),
    ({'effort': {'supported_levels': ['low'], 'default_level': 'ultra'}}, {'format': 'deepseek_effort', 'effort_levels': ['low']}),
    ({'effort': {'supported_levels': ['low'], 'default_level': 'high'}}, {'format': 'deepseek_effort', 'effort_levels': ['low']}),
    ({'effort': {'default_level': 'high'}}, {'format': 'deepseek_effort', 'default_effort': 'high'}),
    ({'max_output_tokens': True}, {}), ({'max_output_tokens': -1}, {}),
])
async def test_partial_and_malformed_fields_do_not_create_defaults_or_cast_types(item, expected):
    result = await catalog('openai_compatible', [{'id': 'alias', **item}])
    assert result == [{'id': 'alias', 'reasoning_metadata': expected}]


@pytest.mark.parametrize('capabilities,expected', [
    ({'effort': {'supported': True, 'low': {'supported': True}}}, {}),
    ({'effort': {'supported': False}, 'thinking': {'supported': False}}, {'effort_levels': [], 'thinking_supported': False}),
    ({'thinking': {'supported': True, 'types': {'adaptive': {'supported': True}}}}, {'thinking_supported': True}),
    ({'thinking': {'supported': 'yes', 'types': {'adaptive': {'supported': 'yes'}, 'enabled': {'supported': False}}}}, {}),
    ({'effort': {'supported': True, **{level: {'supported': True} for level in ('low', 'medium', 'high', 'xhigh', 'max')},
                  'ultra': {'supported': True}}}, {}),
])
async def test_claude_partial_or_unknown_flags_cannot_be_promoted_to_a_complete_list(capabilities, expected):
    result = await catalog('anthropic', [{'id': 'alias', 'capabilities': capabilities}])
    assert result == [{'id': 'alias', 'reasoning_metadata': {'format': 'anthropic_capabilities', **expected}}]


async def test_google_invalid_thinking_is_reported_as_unknown_metadata():
    assert await catalog('google', [{'name': 'models/alias', 'thinking': 'true'}]) == [
        {'id': 'alias', 'reasoning_metadata': {'format': 'google_thinking'}}]


@pytest.mark.parametrize('kind', KINDS)
async def test_catalog_and_existing_name_list_keep_sort_deduplication_and_exact_http_behavior(kind):
    calls = []
    field = 'name' if kind == 'google' else 'id'
    values = [{field: 'models/z' if kind == 'google' else ' z '}, {field: 'a'}, {field: 'a'}, 12, {}, 'b']

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response_body(kind, values))

    provider = build_provider(config(kind), httpx.MockTransport(handler))
    assert await provider.list_models() == ['a', 'b', 'z']
    assert await provider.list_model_catalog() == [{'id': name} for name in ('a', 'b', 'z')]
    assert len(calls) == 2 and all(request.method == 'GET' for request in calls)
    if kind == 'anthropic':
        assert calls[0].headers['x-api-key'] == SECRET
    elif kind == 'google':
        assert calls[0].headers['x-goog-api-key'] == SECRET
    else:
        assert calls[0].headers['authorization'] == 'Bearer ' + SECRET


@pytest.mark.parametrize('kind', KINDS)
async def test_original_scan_limits_are_preserved(kind):
    field = 'name' if kind == 'google' else 'id'
    items = [{} for _ in range(499)] + [{field: 'first'}, {field: 'second'}]
    expected = ['first', 'second'] if kind == 'openai_compatible' else ['first']
    assert [item['id'] for item in await catalog(kind, items)] == expected


async def test_conflicting_duplicate_metadata_stays_unknown_even_after_another_duplicate():
    result = await catalog('openai_compatible', [{'id': 'same', 'effort': {'default_level': value}}
                                               for value in ('high', 'low', 'high')])
    assert result == [{'id': 'same', 'reasoning_metadata': {'format': 'deepseek_effort'}}]


async def test_discovery_caches_metadata_names_and_protects_nested_values_from_callers(monkeypatch):
    calls = []
    clock = [100.0]
    monkeypatch.setattr(model_discovery, 'time', SimpleNamespace(monotonic=lambda: clock[0]))

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'data': [{'id': 'alias', 'effort': {
            'supported_levels': ['low', 'high'] if len(calls) == 1 else ['low'], 'default_level': 'low'},
            'api_key': SECRET}]})

    service = ModelDiscoveryService(httpx.MockTransport(handler))
    assert service.peek_metadata('owner-a', config()) == {} and calls == []
    names, metadata, cached = await service.discover_details('owner-a', config())
    assert names == ['alias'] and cached is False and len(calls) == 1
    names.append('poison')
    metadata['alias']['effort_levels'].append('poison')
    metadata['injected'] = {'api_key': SECRET}
    again, saved, cached = await service.discover_details('owner-a', config())
    assert again == ['alias'] and saved['alias']['effort_levels'] == ['low', 'high'] and cached is True
    saved['alias']['effort_levels'].clear()
    old_names, cached = await service.discover('owner-a', config())
    assert old_names == ['alias'] and cached is True and len(calls) == 1
    assert (await service.discover_details('owner-a', config()))[1]['alias']['effort_levels'] == ['low', 'high']
    peeked = service.peek_metadata('owner-a', config())
    assert peeked['alias']['effort_levels'] == ['low', 'high'] and len(calls) == 1
    peeked['alias']['effort_levels'].append('poison')
    assert service.peek_metadata('owner-a', config())['alias']['effort_levels'] == ['low', 'high']
    assert service.peek_metadata('other-owner', config()) == {}
    _, refreshed, cached = await service.discover_details('owner-a', config(), force_refresh=True)
    assert refreshed['alias']['effort_levels'] == ['low'] and cached is False and len(calls) == 2
    clock[0] += 601
    assert service.peek_metadata('owner-a', config()) == {} and len(calls) == 2
    assert (await service.discover_details('owner-a', config()))[2] is False and len(calls) == 3
    assert SECRET not in repr(service._cache)


async def test_cache_isolated_by_identity_protocol_endpoint_and_key_and_shared_with_legacy_discover():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'data': [{'id': 'alias', 'effort': {'supported_levels': ['low']}}],
                                      'models': [{'name': 'models/alias', 'thinking': True}]})

    service = ModelDiscoveryService(httpx.MockTransport(handler))
    assert (await service.discover('owner-a', config())) == (['alias'], False)
    assert (await service.discover_details('owner-a', replace(config(), base_url=config().base_url + '/')))[2] is True
    assert len(calls) == 1
    for owner, selected in [('owner-b', config()), ('owner-a', replace(config(), api_key='different-fixture-key')),
                            ('owner-a', replace(config(), base_url='https://other.example.test/v1')),
                            ('owner-a', config('openai_responses')), ('owner-a', config('google')),
                            ('owner-a', config('anthropic'))]:
        names, _metadata, cached = await service.discover_details(owner, selected)
        assert names == ['alias'] and cached is False
    assert len(calls) == 7 and len(service._cache) == 7
    assert SECRET not in repr(service._cache)


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('status,expected', [(401, 'auth_error'), (429, 'rate_limited'), (503, 'upstream_error')])
async def test_discovery_errors_keep_kind_and_redaction_without_caching_raw_metadata(kind, status, expected):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={'error': {'message': SECRET}, 'data': [{'id': 'alias', 'api_key': SECRET}]})

    service = ModelDiscoveryService(httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as error:
        await service.discover_details('owner-a', config(kind))
    assert error.value.kind == expected and SECRET not in str(error.value)
    assert len(calls) == 1 and service._cache == {}
