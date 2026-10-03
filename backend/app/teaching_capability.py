"""Small, configuration-bound checks for teaching JSON, not model routing."""
from __future__ import annotations

import asyncio
import json
from contextlib import aclosing
from uuid import uuid4

from .auth import utc_now
from .providers import ProviderError, build_provider

VERSION = 3
MODES = ('plain', 'tools')


def binding(profile, config):
    return {'provider_id': profile.get('id'), 'provider_version': profile.get('config_version'),
            'credential_version': profile.get('credential_version', 1),
            'protocol': config.provider_kind, 'model': config.model}


def support(capabilities, profile, config):
    saved = capabilities.get('teaching_output') or {}
    current = saved.get('version') == VERSION and saved.get('binding') == binding(profile, config)
    return {mode: saved.get(mode, 'unchecked') if current else 'unchecked' for mode in MODES} | {
        'checked_at': saved.get('checked_at') if current else None}


def owned_model(service, owner, provider_id, model_id):
    profile, config = service.provider_runtime_for(owner, provider_id, model_id)
    row = service.database.fetchone('SELECT * FROM provider_model WHERE id=? AND provider_profile_id=?',
                                    (model_id, provider_id))
    if row is None:
        from .conversations import ConversationError
        raise ConversationError('模型不存在')
    return profile, config, dict(row)


def status(service, owner, provider_id, model_id):
    profile, config, row = owned_model(service, owner, provider_id, model_id)
    return support(json.loads(row['capabilities_json']), profile, config)


def output_for(service, owner, profile, config, *, search=None, scope=None):
    """Only previously checked combinations receive a constrained request."""
    row = service.database.fetchone('SELECT capabilities_json FROM provider_model WHERE provider_profile_id=? AND model_id=?',
                                    (profile['id'], config.model))
    capabilities = json.loads(row['capabilities_json']) if row else {}
    checked = support(capabilities, profile, config)
    mode = 'tools' if (scope or {}).get('knowledge_base') or (search or {}).get('mode') == 'external' else 'plain'
    # Native search has its own vendor-managed rounds/citation formats. Keep it
    # usable, but do not claim an unverified output/tool combination is supported.
    if (search or {}).get('mode') == 'native':
        return {'format': 'plain', 'version': VERSION, 'reason': 'native_search_unverified', 'mode': 'native'}
    available = checked[mode] == 'supported'
    return {'format': 'json' if available else 'plain', 'version': VERSION, 'mode': mode,
            'reason': None if available else 'not_supported' if checked[mode] == 'unavailable' else 'not_checked',
            'binding': binding(profile, config), 'checked_at': checked['checked_at']}


async def _check(provider, mode):
    from .function_tools import ToolSession, ToolTurn
    from .teaching_json import JsonTeachingDecoder
    token = uuid4().hex
    text = '检查通过 <think> 🍊\n第二行'
    proposal = dict(step=None, attempt=None, mode=None, help=None, practice=None, project=None, adaptation=None)
    expected = {'reply': text, 'teaching': proposal, 'token': token}
    messages = [
        {'role': 'system', 'content': '这是一次应用能力检查。只输出用户给出的完整JSON对象，不添加解释，不调用工具。'},
        {'role': 'user', '_teaching_runtime': True, '_teaching_output': 'json',
         'content': 'Nautilus 本轮执行上下文（下一条是合成检查内容）：\n' + json.dumps({'output_format': 'json', 'token': token})},
        {'role': 'user', 'content': json.dumps(expected, ensure_ascii=False)},
    ]
    decoder = JsonTeachingDecoder(token)
    visible = ''
    complete = False
    if mode == 'plain':
        stream = provider.stream_chat(messages)
    else:
        tools = [{'name': 'check_unused', 'description': '检查用工具，本次不需要调用。',
                  'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}]
        session = ToolSession(provider, messages)
        stream = session.stream_turn(tools)
    async with aclosing(stream):
        async for chunk in stream:
            if isinstance(chunk, ToolTurn):
                complete = not chunk.calls and chunk.completion == 'complete'
            elif chunk.kind == 'content':
                visible += decoder.feed(chunk.text)
                if decoder.reason or len(visible) > len(text):
                    return False
            elif chunk.kind == 'completion':
                complete = chunk.text == 'complete'
    decoder.finish()
    return complete and visible == text and decoder.proposal() == proposal


async def check(service, owner, provider_id, model_id, *, transport=None):
    from .conversations import ConversationConflict
    key = (owner, provider_id, model_id)
    with service._provider_lock:
        if key in service._teaching_checks:
            raise ConversationConflict('正在检查这个模型，请稍后重试')
        profile, config, row = owned_model(service, owner, provider_id, model_id)
        service._teaching_checks.add(key)
    try:
        previous = json.loads(row['capabilities_json'])
        prior = support(previous, profile, config)
        checked = {mode: prior[mode] for mode in MODES}
        failures = {}
        completed = {}
        for mode in MODES:
            try:
                async with asyncio.timeout(config.timeout_seconds):
                    passed = await _check(build_provider(config, transport=transport), mode)
                completed[mode] = 'supported' if passed else 'unavailable'
            except (TimeoutError, ProviderError) as error:
                kind = getattr(error, 'kind', 'timeout')
                failures[mode] = kind
                # A rejected constrained request is unusable for this config.
                # Network/auth/temporary failures do not erase a prior success.
                if kind in {'request_error', 'unsupported_provider'}:
                    completed[mode] = 'unavailable'
        checked.update(completed)
        with service._provider_lock:
            current_profile, current_config, current_row = owned_model(service, owner, provider_id, model_id)
            if binding(current_profile, current_config) != binding(profile, config):
                raise ConversationConflict('模型配置已改变，请重新检查')
            if completed:
                capabilities = json.loads(current_row['capabilities_json'])
                capabilities['teaching_output'] = {'version': VERSION, 'binding': binding(profile, config),
                    **checked, 'checked_at': utc_now().isoformat()}
                with service.database.transaction() as c:
                    c.execute('UPDATE provider_model SET capabilities_json=?,updated_at=? WHERE id=?',
                              (json.dumps(capabilities), utc_now().isoformat(), model_id))
        return {'support': status(service, owner, provider_id, model_id),
                'failures': failures, 'updated': bool(completed)}
    finally:
        with service._provider_lock:
            service._teaching_checks.discard(key)
