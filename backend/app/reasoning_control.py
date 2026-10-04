"""Documented native controls; never invent cross-provider effort mappings.

Sources and the implementation comparison are pinned in
docs/research/2026-10-04-nautilus-reasoning-controls.md.
"""
from __future__ import annotations

import copy
import hashlib
import json

from .auth import utc_now
from .conversations import ConversationConflict, ConversationError

VERSION = 1
EFFORT_LABELS = {'minimal': '极低', 'low': '低', 'medium': '中', 'high': '高',
                 'xhigh': '超高', 'max': '最高'}
OPENAI = 'https://developers.openai.com/api/docs/guides/reasoning'
CLAUDE = 'https://platform.claude.com/docs/en/build-with-claude/effort'
GEMINI = 'https://ai.google.dev/gemini-api/docs/generate-content/thinking'
DEEPSEEK = 'https://api-docs.deepseek.com/guides/thinking_mode/'
QWEN = 'https://help.aliyun.com/en/model-studio/qwen-api-via-dashscope'
KIMI = 'https://platform.kimi.ai/docs/guide/kimi-k3-quickstart'
GLM = 'https://docs.z.ai/guides/capabilities/thinking'
GROK = 'https://docs.x.ai/developers/model-capabilities/text/reasoning'


def _profile(label, style, efforts=(), *, protocols=('openai_compatible',), off=False,
             on=False, budget=None, source):
    return dict(label=label, style=style, efforts=list(efforts), protocols=list(protocols),
                supports_off=off, supports_on=on, budget=budget, reference_urls=[source])


_OPENAI_PROTOCOLS = ('openai_compatible', 'openai_responses')
_LMH = ('low', 'medium', 'high')
_LMHX = (*_LMH, 'xhigh')
_LMHXM = (*_LMHX, 'max')
PROFILES = {
    'openai_o': _profile('OpenAI o 系列 · 低 / 中 / 高', 'effort', _LMH, protocols=_OPENAI_PROTOCOLS, source=OPENAI),
    'openai_gpt5': _profile('OpenAI GPT-5 · 极低 / 低 / 中 / 高', 'effort', ('minimal', *_LMH), protocols=_OPENAI_PROTOCOLS, source=OPENAI),
    'openai_gpt51': _profile('OpenAI GPT-5.1 · 关闭 / 低 / 中 / 高', 'effort', _LMH, off=True, protocols=_OPENAI_PROTOCOLS, source=OPENAI),
    'openai_gpt54': _profile('OpenAI GPT-5.2 / 5.4 / 5.5', 'effort', _LMHX, off=True, protocols=_OPENAI_PROTOCOLS, source=OPENAI),
    'openai_gpt56': _profile('OpenAI GPT-5.6 / GPT-6 Sol、Luna', 'effort', _LMHXM, off=True, protocols=_OPENAI_PROTOCOLS, source=OPENAI),
    'openai_gpt6': _profile('OpenAI GPT-6 Astra / GPT-6.1 Sol', 'effort', _LMHXM, protocols=_OPENAI_PROTOCOLS, source=OPENAI),
    'claude_adaptive46': _profile('Claude 4.6 · 自适应思考', 'anthropic_adaptive', (*_LMH, 'max'), protocols=('anthropic',), off=True, on=True, source=CLAUDE),
    'claude_adaptive': _profile('Claude Opus 4.7 / 4.8 / 5、Sonnet 5', 'anthropic_adaptive', _LMHXM, protocols=('anthropic',), off=True, on=True, source=CLAUDE),
    'claude_always': _profile('Claude Opus / Sonnet 5.5、Fable / Mythos 5 · 持续思考', 'anthropic_adaptive', _LMHXM, protocols=('anthropic',), on=True, source=CLAUDE),
    'claude_budget': _profile('Claude 4.5 及较早版本 · 思考预算', 'anthropic_budget', protocols=('anthropic',), off=True,
        budget={'min': 1024, 'max': None, 'dynamic': False, 'efforts': []}, source='https://platform.claude.com/docs/en/build-with-claude/extended-thinking'),
    'claude_opus45': _profile('Claude Opus 4.5 · 预算及响应投入', 'anthropic_budget', protocols=('anthropic',), off=True,
        budget={'min': 1024, 'max': None, 'dynamic': False, 'efforts': list(_LMH)}, source='https://platform.claude.com/docs/en/build-with-claude/extended-thinking'),
    'gemini3_pro': _profile('Gemini 3 Pro · 低 / 高', 'google_level', ('low', 'high'), protocols=('google',), source=GEMINI),
    'gemini3_lmh': _profile('Gemini 3.1 Pro / 3.7、3.8 Flash', 'google_level', _LMH, protocols=('google',), source=GEMINI),
    'gemini3_minimal': _profile('Gemini 3 Flash / 3.5、3.6 Flash / Flash-Lite', 'google_level', ('minimal', *_LMH), protocols=('google',), source=GEMINI),
    'gemini3_image': _profile('Gemini 3.1 Flash Image · 极低 / 高', 'google_level', ('minimal', 'high'), protocols=('google',), source=GEMINI),
    'gemini25_pro': _profile('Gemini 2.5 Pro · 思考预算', 'google_budget', protocols=('google',), on=True,
        budget={'min': 128, 'max': 32768, 'dynamic': True, 'efforts': []}, source=GEMINI),
    'gemini25_flash': _profile('Gemini 2.5 Flash · 思考预算', 'google_budget', protocols=('google',), off=True, on=True,
        budget={'min': 1, 'max': 24576, 'dynamic': True, 'efforts': []}, source=GEMINI),
    'gemini25_lite': _profile('Gemini 2.5 Flash-Lite · 思考预算', 'google_budget', protocols=('google',), off=True, on=True,
        budget={'min': 512, 'max': 24576, 'dynamic': True, 'efforts': []}, source=GEMINI),
    'grok45': _profile('Grok 4.5 · 低 / 中 / 高', 'effort', _LMH, protocols=_OPENAI_PROTOCOLS, source=GROK),
    'grok46': _profile('Grok 4.6 / 4.7 · 低 / 中 / 高 / 超高', 'effort', _LMHX, protocols=_OPENAI_PROTOCOLS, source=GROK),
    'deepseek_v4': _profile('DeepSeek V4 · 低 / 高 / 最高', 'thinking_effort', ('low', 'high', 'max'),
        protocols=_OPENAI_PROTOCOLS, off=True, on=True, source=DEEPSEEK),
    'qwen38': _profile('千问 3.8 · 低 / 中 / 超高', 'qwen_effort', ('low', 'medium', 'xhigh'), off=True, on=True, source=QWEN),
    'qwen38_thinking': _profile('千问 3.8 纯思考模型 · 低 / 中 / 超高', 'qwen_effort', ('low', 'medium', 'xhigh'), on=True, source=QWEN),
    'qwen38_omni': _profile('千问 3.8 Omni · 原生等级', 'effort', ('minimal', *_LMHXM), off=True, source='https://help.aliyun.com/zh/model-studio/qwen3-8-omni-flash'),
    'qwen_budget': _profile('千问混合思考模型 · 开关与预算', 'qwen_budget', off=True, on=True,
        budget={'min': 1, 'max': None, 'dynamic': False, 'efforts': []}, source='https://help.aliyun.com/zh/model-studio/deep-thinking'),
    'kimi_k3': _profile('Kimi K3 · 低 / 高 / 最高', 'effort', ('low', 'high', 'max'), source=KIMI),
    'kimi_toggle': _profile('Kimi K2.5 / K2.6 · 思考开关', 'thinking_toggle', off=True, on=True,
        source='https://github.com/MoonshotAI/Kimi-K2.5/blob/master/README.md'),
    'glm52': _profile('GLM 5.2 · 高 / 最高', 'thinking_effort', ('high', 'max'), off=True, on=True, source=GLM),
    'glm53': _profile('GLM 5.3 · 低 / 高 / 最高', 'thinking_effort', ('low', 'high', 'max'), on=True, source=GLM),
    'glm_toggle': _profile('GLM 4.5–5.1 · 思考开关', 'thinking_toggle', off=True, on=True,
        source='https://docs.z.ai/guides/capabilities/thinking-mode'),
}

# Exact documented IDs only. An unfamiliar future name or gateway alias does
# not acquire capabilities by matching a speculative model-family regex.
MODEL_PROFILES = {}


def _register(profile_id, *models):
    for model in models:
        MODEL_PROFILES[model] = profile_id


_register('openai_o', 'o3', 'o3-mini', 'o4-mini', 'o1')
_register('openai_gpt5', 'gpt-5', 'gpt-5-mini', 'gpt-5-nano')
_register('openai_gpt51', 'gpt-5.1')
_register('openai_gpt54', 'gpt-5.2', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.4-nano', 'gpt-5.5')
_register('openai_gpt56', 'gpt-5.6', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-6-sol', 'gpt-6-luna')
_register('openai_gpt6', 'gpt-6-astra', 'gpt-6.1-sol')
_register('claude_adaptive46', 'claude-opus-4-6', 'claude-sonnet-4-6')
_register('claude_adaptive', 'claude-opus-4-7', 'claude-opus-4-8', 'claude-opus-5', 'claude-sonnet-5')
_register('claude_always', 'claude-opus-5-5', 'claude-sonnet-5-5', 'claude-fable-5', 'claude-fable-5-1', 'claude-mythos-5', 'claude-mythos-5-1')
_register('claude_budget', 'claude-sonnet-4-5', 'claude-haiku-4-5', 'claude-sonnet-4-20250514', 'claude-opus-4-20250514', 'claude-opus-4-1')
_register('claude_opus45', 'claude-opus-4-5')
_register('gemini3_pro', 'gemini-3-pro-preview')
_register('gemini3_lmh', 'gemini-3.1-pro-preview', 'gemini-3.7-flash', 'gemini-3.8-flash')
_register('gemini3_minimal', 'gemini-3-flash-preview', 'gemini-3.5-flash', 'gemini-3.6-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite')
_register('gemini3_image', 'gemini-3.1-flash-image', 'gemini-3.1-flash-lite-image')
_register('gemini25_pro', 'gemini-2.5-pro')
_register('gemini25_flash', 'gemini-2.5-flash')
_register('gemini25_lite', 'gemini-2.5-flash-lite')
_register('grok45', 'grok-4.5')
_register('grok46', 'grok-4.6', 'grok-4.7')
_register('deepseek_v4', 'deepseek-flash', 'deepseek-v4-pro', 'deepseek-v4-flash')
_register('qwen38', 'qwen3.8-max', 'qwen3.8-max-0902', 'qwen3.8-flash', 'qwen3.8-27b')
_register('qwen38_thinking', 'qwen3.8-2.4t-a95b')
_register('qwen38_omni', 'qwen3.8-omni-flash')
_register('qwen_budget', 'qwen3.7-max', 'qwen3.7-plus', 'qwen3.7-flash', 'qwen3.6-plus', 'qwen3.6-flash', 'qwen3.5-plus', 'qwen3.5-flash')
_register('kimi_k3', 'kimi-k3')
_register('kimi_toggle', 'kimi-k2.5', 'kimi-k2.6')
_register('glm52', 'glm-5.2')
_register('glm53', 'glm-5.3', 'glm-5.3-flash')
_register('glm_toggle', 'glm-4.5', 'glm-4.5-air', 'glm-4.6', 'glm-4.7', 'glm-5', 'glm-5.1')


def normalize_choice(value):
    """None inherits; default explicitly asks for the provider's native default."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConversationError('思考设置格式不正确')
    mode = value.get('mode')
    if not isinstance(mode, str):
        raise ConversationError('思考设置格式不正确')
    if mode in {'default', 'off', 'on'} and set(value) == {'mode'}:
        return {'mode': mode}
    if mode == 'effort' and set(value) == {'mode', 'effort'} and isinstance(value['effort'], str) and value['effort'] in EFFORT_LABELS:
        return dict(value)
    if mode == 'budget' and {'mode', 'budget_tokens'} <= set(value) <= {'mode', 'budget_tokens', 'effort'}:
        budget = value['budget_tokens']
        if type(budget) is not int or not 1 <= budget <= 2_147_479_551:
            raise ConversationError('思考预算须为正整数')
        result = {'mode': mode, 'budget_tokens': budget}
        if value.get('effort') is not None:
            if not isinstance(value['effort'], str) or value['effort'] not in EFFORT_LABELS:
                raise ConversationError('思考强度不支持')
            result['effort'] = value['effort']
        return result
    raise ConversationError('思考设置格式不正确')


def _tag(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]


def binding(profile, model, protocol):
    return {'protocol': protocol, 'model': model['model_id'],
            'endpoint': _tag(profile['base_url'].rstrip('/'))}


def capability(profile, model, protocol):
    saved = json.loads(model['capabilities_json'] or '{}').get('reasoning_control')
    source = 'official'
    profile_id = None
    stale = False
    if saved:
        source = 'manual'
        if saved.get('binding') == binding(profile, model, protocol):
            profile_id = saved.get('profile_id')
        else:
            stale = True
    else:
        model_id = model['model_id'].removeprefix('models/') if protocol == 'google' else model['model_id']
        profile_id = MODEL_PROFILES.get(model_id)
    definition = PROFILES.get(profile_id)
    discovered = json.loads(model['capabilities_json'] or '{}').get('reasoning_discovery')
    metadata = discovered.get('metadata') if isinstance(discovered, dict) and discovered.get('binding') == binding(profile, model, protocol) else None
    if not saved and isinstance(metadata, dict):
        if metadata.get('thinking_supported') is False:
            return {'profile_id': 'unsupported', 'state': 'unsupported', 'source': 'api',
                    'version': VERSION, 'label': None, 'style': None, 'efforts': [],
                    'supports_off': False, 'supports_on': False, 'budget': None, 'reference_urls': []}
        levels = metadata.get('effort_levels')
        shape = metadata.get('format')
        inferred = copy.deepcopy(definition) if definition and protocol in definition['protocols'] else None
        if shape == 'deepseek_effort' and protocol in _OPENAI_PROTOCOLS and isinstance(levels, list) and levels:
            inferred = inferred or _profile('接口返回的思考档位', 'thinking_effort', protocols=_OPENAI_PROTOCOLS, source=DEEPSEEK)
        elif shape == 'anthropic_capabilities' and protocol == 'anthropic':
            modes = metadata.get('thinking_modes', [])
            if 'adaptive' in modes and isinstance(levels, list) and levels:
                inferred = inferred or _profile('接口返回的思考档位', 'anthropic_adaptive', protocols=('anthropic',), on=True, source=CLAUDE)
            elif inferred is None and 'enabled' in modes:
                inferred = copy.deepcopy(PROFILES['claude_budget'])
                inferred['supports_off'] = False
        if inferred and isinstance(levels, list):
            ordered = [value for value in EFFORT_LABELS if value in levels]
            if inferred['style'] == 'anthropic_budget':
                inferred['budget']['efforts'] = ordered
            else:
                inferred['efforts'] = ordered
            if 'none' in levels:
                inferred['supports_off'] = True
            return {**inferred, 'profile_id': profile_id, 'state': 'available', 'source': 'api', 'version': VERSION}
    if definition and protocol in definition['protocols']:
        return {**copy.deepcopy(definition), 'profile_id': profile_id, 'state': 'available',
                'source': source, 'version': VERSION}
    return {'profile_id': profile_id if profile_id == 'unsupported' else None,
            'state': 'unsupported' if profile_id == 'unsupported' else 'unknown',
            'source': source if saved else 'unknown', 'version': VERSION, 'stale': stale,
            'label': None, 'style': None, 'efforts': [], 'supports_off': False,
            'supports_on': False, 'budget': None, 'reference_urls': []}


def model_default(model, support):
    """A model's explicit setting wins; high is the only implicit effort."""
    options = json.loads(model['overrides_json'] or '{}')
    configured = normalize_choice(options.get('reasoning_default'))
    if configured is not None:
        return configured, configured, False
    if support['state'] == 'available':
        if 'high' in support['efforts']:
            return {'mode': 'effort', 'effort': 'high'}, None, False
        return None, None, True
    return None, None, False


def configuration(profile, model, protocol):
    support = capability(profile, model, protocol)
    default, configured, required = model_default(model, support)
    saved = json.loads(model['capabilities_json'] or '{}').get('reasoning_control')
    return {'capability': support, 'default_choice': default, 'configured_default': configured,
            'default_required': required, 'configured_profile_id': saved.get('profile_id') if saved else None,
            'profiles': [{'id': key, 'label': value['label']} for key, value in PROFILES.items() if protocol in value['protocols']]}


def prepare_configuration(profile, model, protocol, settings=None, metadata=None):
    """Prepare a complete model edit before saving a provider or its credential."""
    model = dict(model)
    caps = json.loads(model['capabilities_json'] or '{}')
    options = json.loads(model['overrides_json'] or '{}')
    options['api_protocol'] = protocol
    if metadata is not None:
        caps['reasoning_discovery'] = {'binding': binding(profile, model, protocol), 'metadata': metadata}
    if settings is not None:
        if not isinstance(settings, dict) or set(settings) - {'profile_id', 'default_choice'}:
            raise ConversationError('模型思考设置格式不正确')
        if 'profile_id' in settings:
            selected = settings['profile_id']
            if selected is not None and (not isinstance(selected, str) or (selected != 'unsupported' and (selected not in PROFILES or protocol not in PROFILES[selected]['protocols']))):
                raise ConversationError('所选思考规格与当前接口不兼容')
            if selected is None:
                caps.pop('reasoning_control', None)
            else:
                caps['reasoning_control'] = {'profile_id': selected, 'binding': binding(profile, model, protocol)}
        if 'default_choice' in settings:
            choice = normalize_choice(settings['default_choice'])
            if choice is not None and choice['mode'] == 'default':
                raise ConversationError('请选择模型实际支持的默认思考档位')
            if choice is None:
                options.pop('reasoning_default', None)
            else:
                options['reasoning_default'] = choice
    model.update(capabilities_json=json.dumps(caps, ensure_ascii=False), overrides_json=json.dumps(options, ensure_ascii=False))
    return model, configuration(profile, model, protocol)


def validate_configuration(prepared, protocol):
    if prepared['default_required']:
        raise ConversationError('这个模型没有高档，请选择一个默认思考设置')
    if prepared['default_choice'] is not None:
        compile_parameters(prepared['default_choice'], prepared['capability'], protocol)


def persist_configuration(service, owner, provider_id, model_id, prepared_model):
    """Only previously validated, locally constructed JSON reaches this write."""
    with service._provider_lock:
        _owned(service, owner, provider_id, model_id)
        with service.database.transaction() as c:
            c.execute('UPDATE provider_model SET capabilities_json=?,overrides_json=?,updated_at=? WHERE id=?',
                      (prepared_model['capabilities_json'], prepared_model['overrides_json'], utc_now().isoformat(), model_id))


def compile_parameters(choice, support, protocol):
    """Build native parameters from one mutually exclusive, validated choice."""
    value = normalize_choice(choice) or {'mode': 'default'}
    mode = value['mode']
    if mode == 'default':
        return {}
    if support['state'] != 'available':
        raise ConversationError('当前模型尚未配置思考能力或不提供调节，请在提供方设置中确认')
    style = support['style']
    if mode == 'off':
        if not support['supports_off']:
            raise ConversationError('当前模型不能关闭思考，请选择支持的强度')
        if style in {'effort', 'thinking_effort'} and protocol == 'openai_responses':
            return {'reasoning': {'effort': 'none'}}
        if style == 'effort':
            return {'reasoning_effort': 'none'}
        if style in {'anthropic_adaptive', 'anthropic_budget', 'thinking_effort', 'thinking_toggle'}:
            return {'thinking': {'type': 'disabled'}}
        if style in {'qwen_effort', 'qwen_budget'}:
            return {'enable_thinking': False}
        if style == 'google_budget':
            return {'generationConfig': {'thinkingConfig': {'thinkingBudget': 0}}}
    elif mode == 'on':
        if not support['supports_on']:
            raise ConversationError('当前模型请直接选择思考等级或预算')
        if style == 'anthropic_adaptive':
            return {'thinking': {'type': 'adaptive'}}
        if style in {'thinking_effort', 'thinking_toggle'}:
            if protocol == 'openai_responses':
                # DeepSeek documents high as its default enabled effort.
                return {'reasoning': {'effort': 'high'}}
            return {'thinking': {'type': 'enabled'}}
        if style in {'qwen_effort', 'qwen_budget'}:
            return {'enable_thinking': True}
        if style == 'google_budget':
            return {'generationConfig': {'thinkingConfig': {'thinkingBudget': -1}}}
    elif mode == 'effort':
        effort = value['effort']
        if effort not in support['efforts']:
            raise ConversationError('当前模型不支持所选思考强度，请重新选择；不会自动降档')
        if style == 'effort' or (style == 'thinking_effort' and protocol == 'openai_responses'):
            return {'reasoning': {'effort': effort}} if protocol == 'openai_responses' else {'reasoning_effort': effort}
        if style == 'thinking_effort':
            return {'thinking': {'type': 'enabled'}, 'reasoning_effort': effort}
        if style == 'qwen_effort':
            return {'enable_thinking': True, 'reasoning_effort': effort}
        if style == 'anthropic_adaptive':
            return {'thinking': {'type': 'adaptive'}, 'output_config': {'effort': effort}}
        if style == 'google_level':
            return {'generationConfig': {'thinkingConfig': {'thinkingLevel': effort}}}
    elif mode == 'budget':
        budget = support.get('budget')
        amount = value['budget_tokens']
        if not budget or amount < budget['min'] or (budget['max'] is not None and amount > budget['max']):
            raise ConversationError('思考预算超出当前模型支持范围')
        effort = value.get('effort')
        if effort is not None and effort not in budget.get('efforts', []):
            raise ConversationError('当前预算模式不支持这个响应投入等级')
        if style == 'anthropic_budget':
            result = {'thinking': {'type': 'enabled', 'budget_tokens': amount}}
            if effort:
                result['output_config'] = {'effort': effort}
            return result
        if style == 'google_budget':
            return {'generationConfig': {'thinkingConfig': {'thinkingBudget': amount}}}
        if style == 'qwen_budget':
            return {'enable_thinking': True, 'thinking_budget': amount}
    raise ConversationError('当前模型不支持这种思考控制方式')


def _owned(service, owner, provider_id, model_id):
    profile = service._provider_by_id(owner, provider_id)
    row = service.database.fetchone('SELECT * FROM provider_model WHERE id=? AND provider_profile_id=?', (model_id, provider_id))
    if row is None:
        raise ConversationError('模型不存在')
    model = dict(row)
    return profile, model, service._protocol(profile, model['model_id'])


def status(service, owner, provider_id, model_id):
    with service._provider_lock:
        profile, model, protocol = _owned(service, owner, provider_id, model_id)
        stored = json.loads(model['capabilities_json'] or '{}').get('reasoning_control')
        return {'provider_id': provider_id, 'model_id': model_id, 'protocol': protocol,
                **configuration(profile, model, protocol),
                'revision': _tag([binding(profile, model, protocol), stored, model['updated_at'], model['overrides_json']])}


_UNSET = object()


def save_support(service, owner, provider_id, model_id, profile_id, expected_revision, default_choice=_UNSET):
    with service._provider_lock:
        current = status(service, owner, provider_id, model_id)
        if current['revision'] != expected_revision:
            raise ConversationConflict('模型思考能力已变化，请刷新后重新配置')
        if profile_id is not None and profile_id != 'unsupported' and profile_id not in {item['id'] for item in current['profiles']}:
            raise ConversationError('所选思考规格与当前接口不兼容')
        profile, model, protocol = _owned(service, owner, provider_id, model_id)
        settings = {'profile_id': profile_id}
        if default_choice is not _UNSET:
            settings['default_choice'] = default_choice
        prepared, view = prepare_configuration(profile, model, protocol, settings)
        # Legacy declaration-only clients may configure the native contract
        # first. Actual sends still require a usable model/conversation choice.
        if default_choice is not _UNSET:
            validate_configuration(view, protocol)
        persist_configuration(service, owner, provider_id, model_id, prepared)
        return status(service, owner, provider_id, model_id)
