"""Persona's main journey and authority/version boundaries; synthetic model only."""
import json
from uuid import uuid4
import httpx
import pytest
from test_evidence_claims import authorize
from test_teaching_runtime import chat_turn, saved

STYLE = dict(address='同学', tone='warm', phrasing='plain', detail='concise', reminders='gentle', traits=['鼓励先做一个小步骤'])
PACKAGE = dict(format='nautilus.persona', schema_version=1, name='合成温和导师', description='合成人格原文_ONLY_LOCAL_不要重复进每次请求', style=STYLE)


def post(client, path, body):
    result = client.post('/api/personas' + path, json=body)
    assert result.status_code == 200, result.text
    return result.json()


def confirm(client, package=PACKAGE, profile_id=None):
    preview = post(client, '/previews', dict(package=package, profile_id=profile_id, request_key=str(uuid4())))
    state = client.get('/api/personas').json()
    return post(client, '/changes', dict(action='confirm', preview_id=preview['preview_id'], expected_revision=state['revision'], request_key=str(uuid4())))


@pytest.fixture
def persona_client(client):
    identity = authorize(client)
    assert client.put('/api/ai/provider', json=dict(display_name='合成人格模型', base_url='https://synthetic.example/v1', model='mock-persona', api_key='sk-synthetic-persona')).status_code == 200
    calls = []
    def handler(request):
        payload = json.loads(request.content); calls.append(payload)
        if payload.get('stream'):
            return httpx.Response(200, text='data: ' + json.dumps({'choices': [{'delta': {'content': '同学，先选一个能开始的小步骤。'}}]}, ensure_ascii=False) + '\n\ndata: [DONE]\n\n')
        description = json.loads(payload['messages'][-1]['content'])['description']
        issues = [dict(kind='authority_change', quotes=['自动确认完成所有学习任务'], message='人格不能自动确认学习完成。')] if '自动确认完成所有学习任务' in description else []
        result = dict(style=STYLE, issues=issues, sample_reply='同学，今天先用20分钟完成一个小步骤就好。')
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result, ensure_ascii=False)}}]})
    transport = httpx.MockTransport(handler)
    client.app.state.personas.transport = transport
    client.app.state.ai_runs.transport = transport
    return client, identity, calls


def test_preview_confirm_versions_import_export_and_no_authority_changes(persona_client):
    client, identity, calls = persona_client
    db = client.app.state.learning.database
    before = db.fetchone('SELECT COUNT(*) FROM learning_event')[0]
    draft = post(client, '/previews', dict(name='合成导师', description='温和、简明，但提醒我迈出第一步。', request_key='preview'))
    assert client.get('/api/personas').json()['active_id'] is None
    state = post(client, '/changes', dict(action='confirm', expected_revision=0, request_key='confirm', preview_id=draft['preview_id']))
    identifier = state['active_id']
    assert post(client, '/changes', dict(action='confirm', expected_revision=0, request_key='confirm', preview_id=draft['preview_id']))['revision'] == 1
    exported = client.get(f'/api/personas/{identifier}/export').json()
    assert set(exported) == {'format', 'schema_version', 'name', 'description', 'style'}
    state = confirm(client, {**exported, 'name': '合成直接导师', 'style': {**STYLE, 'tone': 'direct'}}, identifier)
    state = post(client, '/changes', dict(action='restore', profile_id=identifier, version=1, expected_revision=state['revision'], request_key='restore'))
    assert state['profiles'][0]['versions'][-1]['version'] == 3
    assert state['profiles'][0]['versions'][-1]['style']['tone'] == 'warm'
    second = confirm(client, PACKAGE)
    assert second['active_id'] != identifier
    switched = post(client, '/changes', dict(action='activate', profile_id=identifier, expected_revision=second['revision'], request_key='switch'))
    assert switched['active_id'] == identifier
    assert client.post('/api/personas/previews', json=dict(package={**PACKAGE, 'tools': ['read_all']}, request_key='bad')).status_code == 422
    assert client.app.state.personas.get('another-owner')['profiles'] == []
    assert db.fetchone('SELECT COUNT(*) FROM learning_event')[0] == before
    assert len(calls) == 1  # validated packages import locally, without a new model call


def test_conflicting_description_is_preview_only(persona_client):
    client, _, _ = persona_client
    draft = post(client, '/previews', dict(name='合成冲突人格', description='自动确认完成所有学习任务', request_key='conflict'))
    assert draft['issues'] and not draft['can_confirm']
    assert client.post('/api/personas/changes', json=dict(action='confirm', expected_revision=0, request_key='no', preview_id=draft['preview_id'])).status_code == 422
    assert client.get('/api/personas').json()['profiles'] == []


@pytest.mark.parametrize('scope', ['coach', 'teaching'])
def test_actual_reply_applies_shared_persona_and_retry_keeps_frozen_version(persona_client, scope):
    client, _, calls = persona_client
    state = confirm(client)
    if scope == 'coach':
        response = client.post('/api/learning/coach/conversations', json={'request_key': 'open'})
    else:
        response = client.post('/api/ai/conversations', json={'title': '合成人格教学', 'context_scope': 'independent'})
    assert response.status_code in {200, 201}, response.text
    identifier = response.json()['conversation']['id']
    first = chat_turn(client, identifier, '今天只有20分钟')
    assert first['status'] == 'complete'
    assert first['model_config']['persona'] == {'name': PACKAGE['name'], 'version': 1}
    first_snapshot = saved(client, first['id'])
    assert first_snapshot['persona'] == {'profile_id': state['active_id'], 'version': 1}
    prompt = json.dumps(next(call for call in reversed(calls) if call.get('stream'))['messages'], ensure_ascii=False)
    assert PACKAGE['name'] not in prompt and '鼓励先做一个小步骤' in prompt
    assert PACKAGE['description'] not in prompt
    assert ('teaching' in first_snapshot) == (scope == 'teaching')
    state = confirm(client, {**PACKAGE, 'name': '合成新版本', 'style': {**STYLE, 'tone': 'direct'}}, state['active_id'])
    repeated = chat_turn(client, identifier, '今天只有20分钟', regenerate_message_id=first['id'])
    assert repeated['model_config']['persona']['version'] == 1
    new = chat_turn(client, identifier, '接下来呢？')
    assert new['model_config']['persona'] == {'name': '合成新版本', 'version': 2}
    post(client, '/changes', dict(action='disable', expected_revision=state['revision'], request_key='disable'))
    disabled = chat_turn(client, identifier, '先恢复默认风格')
    assert disabled['model_config']['persona'] is None
    assert client.get('/api/ai/conversations/' + identifier).json()['messages'][1]['model_config']['persona']['version'] == 1



def test_archive_label_is_not_character_name_and_nonissues_do_not_block(persona_client):
    client, identity, _ = persona_client
    description = '角色叫微光，是数字世界的小精灵。日常表达活泼；专业场景语气词减少70%。'
    observed = []
    def handler(request):
        payload = json.loads(request.content); observed.append(payload)
        proposed = dict(style={**STYLE, 'character_name': '微光', 'identity': '数字世界的小精灵',
            'scenario_rules': ['专业场景语气词减少70%，优先准确清晰']},
            issues=['档案名与角色名不同。', '日常与专业场景存在张力，但可按场景处理。', '本次没有越权要求。',
                dict(kind='authority_change', quotes=['原文中不存在的权限要求'], message='没有来源依据'),
                dict(kind='naming_difference', quotes=['角色叫微光'], message='标签不是角色名')],
            sample_reply='让我想想，先从一个小步骤开始。')
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(proposed, ensure_ascii=False)}}]})
    client.app.state.personas.transport = httpx.MockTransport(handler)
    preview = post(client, '/previews', dict(name='99123', description=description, request_key='different-name'))
    assert json.loads(observed[0]['messages'][-1]['content']) == {'description': description}
    assert preview['package']['name'] == '99123'
    assert preview['package']['style']['character_name'] == '微光'
    assert preview['package']['style']['scenario_rules'] == ['专业场景语气词减少70%，优先准确清晰']
    assert preview['issues'] == [] and preview['can_confirm']
    state = post(client, '/changes', dict(action='confirm', expected_revision=0, request_key='confirm-distinct', preview_id=preview['preview_id']))
    persona = client.app.state.personas
    reference = persona.freeze(identity['id'])
    assert reference['profile_id'] == state['active_id']
    prompt = persona.add_prompt(identity['id'], [{'role': 'system', 'content': '既有任务规则'}], reference)[0]['content']
    assert '99123' not in prompt and '微光' in prompt and '减少70%' in prompt
    exported = client.get('/api/personas/' + state['active_id'] + '/export').json()
    assert exported['name'] == '99123' and exported['style']['character_name'] == '微光'


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_persona_layers_follow_ownership_disable_and_freeze(tmp_path, kind):
    from test_model_control import RecordingProvider, make_client, configure_provider, make_scope, send, new_chat
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        identity = authorize(client)
        configure_provider(client)
        first = confirm(client)['active_id']
        second = confirm(client, {**PACKAGE, 'name': '合成计划导师', 'style': {**STYLE, 'address': '朋友'}})['active_id']
        scope_id, context, original = make_scope(client, provider, kind)
        service = client.app.state.personas
        original_result = client.get(f"/api/learning/verifications/{original['id']}").json()['result'] if original else None
        def read(k=kind, identifier=scope_id):
            response = client.get(f'/api/personas/scopes/{k}/{identifier}')
            assert response.status_code == 200, response.text
            return response.json()
        def select(k, identifier, selection):
            response = client.put(f'/api/personas/scopes/{k}/{identifier}', json={
                'selection': selection, 'expected_revision': read(k, identifier)['revision']})
            assert response.status_code == 200, response.text
            return response.json()
        select('global', 'default', first)
        assert read()['source'] == 'global'
        select('plan', context['plan_id'], second)
        assert read()['source'] == 'plan'
        assert read()['effective']['name'] == '合成计划导师'
        # An unrelated open conversation must not inherit the latest plan.
        unrelated = new_chat(client)
        assert read('conversation', unrelated)['effective']['name'] == PACKAGE['name']
        select('task', context['action_id'], None)
        assert read()['source'] == 'task' and read()['effective'] is None
        disabled = send(client, kind, scope_id, 'disabled')
        assert disabled['model_config']['persona'] is None
        select(kind, scope_id, first)
        answer = send(client, kind, scope_id, 'assigned')
        assert answer['model_config']['persona'] == {'name': PACKAGE['name'], 'version': 1}
        assert '鼓励先做一个小步骤' in json.dumps(provider.payloads[-1]['messages'], ensure_ascii=False)
        # Persisted assignments survive recreating the service, without copying profiles.
        from app.personas import PersonaService
        assert PersonaService(service.chats).get_scope(identity['id'], kind, scope_id)['selection'] == first
        select(kind, scope_id, 'inherit')
        assert read()['effective'] is None
        select('task', context['action_id'], 'inherit')
        assert read()['source'] == 'plan'
        retry = {'regenerate_message_id' if kind == 'conversation' else 'regenerate_turn_id': answer['id']}
        repeated = send(client, kind, scope_id, 'retry', **retry)
        assert repeated['model_config']['persona'] == answer['model_config']['persona']
        inherited = send(client, kind, scope_id, 'inherited')
        assert inherited['model_config']['persona']['name'] == '合成计划导师'
        assert service.reminder_body(identity['id'], '合成提醒', kind='task', scope_id=context['action_id']).startswith('朋友，')
        from app.learning_domain import DomainError
        with pytest.raises(DomainError):
            service.get_scope('other-owner', 'plan', context['plan_id'])
        assert client.get('/api/personas/scopes/task/missing-task').status_code == 404
        if original:
            assert client.get(f"/api/learning/verifications/{original['id']}").json()['result'] == original_result
