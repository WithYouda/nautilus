"""C1: checkpoints follow actual answer versions, never formal learning facts."""
import asyncio
import copy
import json
import sqlite3
import time
from contextlib import closing
from uuid import uuid4

import httpx
import pytest

from app import teaching_runtime as teaching
from app.discussion_branches import create_branch as branch_discussion
from app.providers import ProviderChunk
from app.question_discussion import QuestionDiscussionService
from app.purge_storage import register_backup, storage_lock
from test_ai_conversations import make_client, authorize, configure_provider as configure_base_provider, read_sse
from test_conversation_branches import branch
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY
from test_verification_review import attempt


def configure_provider(client):
    """Exercise legacy semantic fixtures; JSON transport has separate coverage."""
    configure_base_provider(client)
    client.app.state.conversations.teaching_output = lambda *_args, **_kwargs: {'format': 'legacy', 'version': 1}


class TeachingProvider:
    def __init__(self):
        self.calls = []
        self.next = {'body': '先看输入的边界。', 'step': '先看输入的边界。'}

    def __call__(self, request):
        payload = json.loads(request.content)
        if not payload.get('stream'):
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"history_query":null}'}}]})
        runtime = next(m['content'] for m in reversed(payload['messages'])
                       if str(m.get('content', '')).startswith('Nautilus 本轮执行上下文'))
        context = json.loads(runtime.split('\n', 1)[1])
        self.calls.append((payload, context))
        spec = self.next
        proposal = {'step': spec.get('step'), 'attempt': {'quote': spec['attempt']} if 'attempt' in spec else None,
                    'mode': spec.get('mode')}
        raw = spec['body']
        if not spec.get('no_metadata'):
            raw += '\n' + context['opening'] + (spec.get('raw') or json.dumps(proposal, ensure_ascii=False)) + context['closing']
        events = ['data: ' + json.dumps({'choices': [{'delta': {'content': raw[i:i + 3]}}]}, ensure_ascii=False)
                  + '\n\n' for i in range(0, len(raw), 3)]
        if spec.get('finish', 'stop') is not None:
            events.append('data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': spec.get('finish', 'stop')}]}) + '\n\n')
        events.append('data: [DONE]\n\n')
        return httpx.Response(200, text=''.join(events))


def new_chat(client):
    result = client.post('/api/ai/conversations', json={'title': '合成C1检查'})
    assert result.status_code == 201
    return result.json()['conversation']['id']


def chat_turn(client, cid, content, **extra):
    response = client.post(f'/api/ai/conversations/{cid}/messages', json={
        'content': content, 'client_message_id': str(uuid4()), **extra})
    assert response.status_code == 202, response.text
    run = response.json()['run']
    frames = read_sse(client, run['id'])
    assert 'nautilus_teaching_' not in json.dumps(frames, ensure_ascii=False)
    messages = client.get(f'/api/ai/conversations/{cid}').json()['messages']
    answer = next(m for m in messages if m['id'] == run['response_message_id'])
    return answer


def saved(client, mid):
    return json.loads(client.app.state.database.fetchone(
        'SELECT config_snapshot_json FROM ai_run WHERE response_message_id=?', (mid,))[0])


def test_attempt_correction_versions_edit_and_nested_branches(tmp_path):
    provider = TeachingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        first = chat_turn(client, cid, '开始解释')
        assert first['teaching']['current']['step']['id'] == first['id']
        assert provider.calls[0][1]['before']['step'] is None
        provider.next = {'body': '先检查空输入的情况。', 'attempt': '我认为空输入应该拒绝'}
        second = chat_turn(client, cid, '我认为空输入应该拒绝', parent_message_id=first['id'])
        original_frozen = copy.deepcopy(saved(client, second['id'])['teaching'])
        assert second['teaching']['attempt']['message_id'] == second['parent_message_id']
        assert second['teaching']['attempt']['step_id'] == first['id']
        endpoint = f"/api/ai/conversations/{cid}/messages/{second['id']}/teaching-attempt"
        correction = {'expected_revision': 0, 'is_attempt': False, 'request_key': 'correct'}
        updated = client.post(endpoint, json=correction)
        assert updated.status_code == 200, updated.text
        assert updated.json()['attempt']['is_attempt'] is False
        assert client.post(endpoint, json=correction).json() == updated.json()
        assert client.post(endpoint, json={**correction, 'request_key': 'stale'}).status_code == 409
        assert saved(client, second['id'])['teaching'] == original_frozen
        assert client.post(endpoint, json={**correction, 'is_attempt': 'false'}).status_code == 422
        provider.next = {'body': '继续核对空输入。'}
        follow = chat_turn(client, cid, '为什么这样', parent_message_id=second['id'])
        assert follow['teaching']['attempt'] is None
        observation = provider.calls[-1][1]['attempt_context'][0]
        assert observation['is_attempt'] is False and observation['revision'] == 1
        assert observation['quote'] == '我认为空输入应该拒绝'
        provider.next = {'body': '另一版解释。', 'step': '另一版解释。', 'attempt': '我认为空输入应该拒绝'}
        alternate = chat_turn(client, cid, '我认为空输入应该拒绝', regenerate_message_id=second['id'])
        assert alternate['teaching']['before'] == second['teaching']['before']
        assert alternate['teaching']['attempt']['is_attempt'] is True
        provider.next = {'body': '编辑后的小点。', 'step': '编辑后的小点。'}
        edited = chat_turn(client, cid, '其实是在提问', edit_message_id=second['parent_message_id'])
        assert edited['teaching']['before'] == second['teaching']['before']
        assert edited['parent_message_id'] != second['parent_message_id']
        assert saved(client, second['id'])['teaching'] == original_frozen
        fork = branch(client, cid, second['id']).json()
        bid = fork['conversation']['id']
        inherited = [m for m in fork['messages'] if m['role'] == 'assistant']
        copied = inherited[-1]['teaching']
        assert copied['current']['step']['id'] == inherited[0]['id']
        assert copied['attempt']['message_id'] == inherited[-1]['parent_message_id']
        assert copied['attempt']['is_attempt'] is False
        assert saved(client, inherited[-1]['id'])['teaching']['origin'] == original_frozen['origin']
        nested = branch(client, bid, inherited[-1]['id'], key='nested').json()
        assert len(nested['messages']) == 4
        assert len(provider.calls) == 5  # State identification adds no model call.
        assert client.get(f'/api/ai/conversations/{cid}').json()['messages'][-1]['id'] == edited['id']


def test_one_turn_and_persistent_modes_are_frozen_per_path(tmp_path):
    provider = TeachingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        first = chat_turn(client, cid, '先解释一点')
        provider.next = {'body': '完整说明这个例子。', 'mode': {
            'value': 'full_explanation', 'scope': 'turn', 'quote': '完整讲解', 'persistence_quote': None}}
        temporary = chat_turn(client, cid, '完整讲解', parent_message_id=first['id'])
        assert temporary['teaching']['effective_mode'] == 'full_explanation'
        assert temporary['teaching']['current']['mode'] == 'stepwise'
        provider.next = {'body': '再讲一个小点。'}
        chat_turn(client, cid, '继续', parent_message_id=temporary['id'])
        assert provider.calls[-1][1]['before']['mode'] == 'stepwise'
        provider.next = {'body': '完整说明这个例子。', 'mode': {
            'value': 'full_explanation', 'scope': 'conversation', 'quote': '完整讲解', 'persistence_quote': '以后都这样'}}
        persistent = chat_turn(client, cid, '完整讲解，以后都这样', parent_message_id=temporary['id'])
        assert persistent['teaching']['current']['mode'] == 'full_explanation'
        provider.next = {'body': '沿用完整讲解。'}
        chat_turn(client, cid, '继续', parent_message_id=persistent['id'])
        assert provider.calls[-1][1]['before']['mode'] == 'full_explanation'
        chat_turn(client, cid, '从旧版继续', parent_message_id=first['id'])
        assert provider.calls[-1][1]['before']['mode'] == 'stepwise'
        other = new_chat(client)
        chat_turn(client, other, '新对话')
        assert provider.calls[-1][1]['before'] == teaching.checkpoint()


@pytest.mark.parametrize('change', [
    {'no_metadata': True}, {'raw': '{bad'}, {'step': '不在正文中的小点'},
    {'finish': None}, {'finish': 'length'}, {'body': ''},
])
def test_unavailable_or_incomplete_metadata_never_advances(tmp_path, change):
    provider = TeachingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        first = chat_turn(client, cid, '开始')
        provider.next = {'body': '新的小点。', 'step': '新的小点。', **change}
        reply = chat_turn(client, cid, '继续', parent_message_id=first['id'])
        assert reply['teaching']['status'] == 'not_updated'
        assert reply['teaching']['current'] == first['teaching']['current']
        assert reply['teaching']['attempt'] is None
        if change.get('body') == '':
            assert reply['status'] == 'failed' and reply['help_record']['provided'] is None
        else:
            assert reply['help_record']['provided'] is not None
        provider.next = {'body': '保留小点继续回应。'}
        chat_turn(client, cid, '再继续', parent_message_id=reply['id'])
        assert provider.calls[-1][1]['before'] == first['teaching']['current']


@pytest.mark.asyncio
async def test_trailer_boundaries_and_tool_round_do_not_publish_metadata():
    frozen = teaching.freeze([], answer_id='a', message_id='u', kind='conversation', scope_id='c')
    opening, closing = teaching.markers(frozen)
    bad_round = opening + '{"step":"工具前内容","attempt":null,"mode":null}' + closing
    final = opening + '{"step":"最终小点。","attempt":null,"mode":null}' + closing
    async def stream():
        for text in '工具前内容\n' + bad_round:
            yield ProviderChunk('content', text)
        yield ProviderChunk('turn_end', '')
        yield ProviderChunk('tool_start', '{}')
        yield ProviderChunk('tool_end', '{}')
        for text in '\n最终小点。\n' + final:
            yield ProviderChunk('content', text)
        yield ProviderChunk('turn_end', '')
        yield ProviderChunk('completion', 'complete')
    parser = teaching.TeachingStream(frozen)
    chunks = [item async for item in parser.filter(stream())]
    visible = ''.join(item.text for item in chunks if item.kind == 'content')
    assert visible == '工具前内容\n\n最终小点。\n'
    assert parser.proposal()['step'] == '最终小点。'
    parser.metadata = '{"step":null,"step":null,"attempt":null,"mode":null}' + closing
    assert parser.proposal() is None


@pytest.mark.parametrize('user_text,persistence,persistent', [
    ('这次完整讲解', '完整讲解', False),
    ('不要以后都这样，这次完整讲解', '以后都这样', False),
    ('“以后都这样”是例子，完整讲解', '以后都这样', False),
    ('完整讲解，以后都这样', '以后都这样', True),
    ('完整讲解', None, False),
])
def test_model_cannot_promote_one_turn_request_to_persistent(user_text, persistence, persistent):
    frozen = teaching.freeze([], answer_id='a', message_id='u', kind='conversation', scope_id='c')
    result = teaching.complete(frozen, {'step': None, 'attempt': None, 'mode': {
        'value': 'full_explanation', 'scope': 'conversation', 'quote': '完整讲解', 'persistence_quote': persistence}},
        body='一次完整讲解。', user_text=user_text, at='2026-10-03T00:00:00Z')
    assert result['mode_request']['scope'] == ('conversation' if persistent else 'turn')
    assert result['after']['mode'] == ('full_explanation' if persistent else 'stepwise')
    assert result['effective_mode'] == 'full_explanation'


@pytest.mark.parametrize('kind', ['openai_compatible', 'openai_responses', 'anthropic', 'google'])
def test_native_replay_restores_original_teaching_input_without_rewriting_signatures(kind):
    from app.function_tools import ToolSession
    from app.providers import ProviderConfig, build_provider
    from app.provider_messages import encode_message
    provider = build_provider(ProviderConfig(base_url='https://example.test/v1', model='model', api_key='fake', provider_kind=kind))
    runtime = {'role': 'user', 'content': '原运行上下文，旧nonce、原来的步骤和纠正状态'}
    answer = {'role': 'assistant', 'content': '原回答'}
    native = encode_message(answer, kind)
    if kind == 'google':
        native['parts'][0]['thoughtSignature'] = 'ORIGINAL-SIGNATURE'
    elif kind == 'anthropic':
        native['content'] = [{'type': 'thinking', 'thinking': 'original', 'signature': 'ORIGINAL-SIGNATURE'},
                             {'type': 'text', 'text': '原回答'}]
    saved_turn = {'provider_kind': kind, 'model': 'model', 'base_url': provider.config.base_url,
                  'messages': [native], 'teaching_input': runtime}
    messages = [{'role': 'system', 'content': 'fixed'}, {'role': 'user', 'content': '原问题'},
                {**answer, '_model_turn': saved_turn}, {'role': 'user', '_teaching_runtime': True, 'content': '新的运行上下文'},
                {'role': 'user', 'content': '继续'}]
    session = ToolSession(provider, messages)
    replay = session._initial()
    prefix = ([encode_message(messages[0], kind)] if kind.startswith('openai') else [])
    assert replay[:len(prefix) + 3] == prefix + [encode_message(runtime, kind), encode_message(messages[1], kind), native]
    assert saved_turn['messages'] == [native]
    # Export records the exact per-run input only for native replay, never in
    # the observation record or public teaching state.
    session._history = replay + [native]
    session._initial_history_length = len(replay)
    exported = session.export_turn()
    assert exported['teaching_input']['content'] == '新的运行上下文'


def test_partial_cancel_and_restart_restore_checkpoint_and_keep_help(tmp_path):
    provider = TeachingProvider()
    class Waiting(httpx.AsyncByteStream):
        def __init__(self, request):
            messages = json.loads(request.content)['messages']
            runtime = next(m['content'] for m in messages if str(m.get('content', '')).startswith('Nautilus 本轮执行上下文'))
            context = json.loads(runtime.split('\n', 1)[1])
            self.text = ('partial body\n' + context['opening']
                         + '{"step":"partial body","attempt":null,"mode":null}' + context['closing'])
        async def __aiter__(self):
            yield ('data: ' + json.dumps({'choices': [{'delta': {'content': self.text}}]}) + '\n\n').encode()
            await asyncio.sleep(60)
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        first = chat_turn(client, cid, '开始')
        client.app.state.ai_runs.transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=Waiting(request)))
        result = client.post(f'/api/ai/conversations/{cid}/messages', json={
            'content': '给个提示', 'client_message_id': 'cancel', 'parent_message_id': first['id'], 'help_request': 'hint'}).json()
        rid = result['run']['id']
        for _ in range(100):
            if client.app.state.ai_runs._runs[rid].text:
                break
            time.sleep(.01)
        assert client.post(f'/api/ai/runs/{rid}/cancel').status_code == 200
        canceled = client.get(f'/api/ai/conversations/{cid}').json()['messages'][-1]
        assert canceled['content'].strip() == 'partial body'
        assert canceled['teaching']['current'] == first['teaching']['current']
        assert canceled['help_record']['provided']['partial'] is True
        # Simulate a saved in-progress stream at process death. Startup's normal
        # recovery must retain text but never adopt a next checkpoint.
        with client.app.state.database.transaction() as c:
            c.execute("UPDATE ai_run SET status='running' WHERE id=?", (rid,))
            c.execute("UPDATE message SET status='streaming' WHERE id=?", (canceled['id'],))
    with make_client(tmp_path, provider) as client:
        authorize(client)
        read_sse(client, rid)  # Existing chat recovery seals an orphan on resubscription.
        recovered = client.get(f'/api/ai/conversations/{cid}').json()['messages'][-1]
        assert recovered['content'].strip() == 'partial body'
        assert recovered['teaching']['status'] == 'not_updated'
        assert recovered['teaching']['current'] == first['teaching']['current']
        assert len(provider.calls) == 1


def test_reply_persistence_failure_cannot_commit_next_checkpoint(tmp_path):
    provider = TeachingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        first = chat_turn(client, cid, '开始')
        with client.app.state.database.transaction() as c:
            c.execute("CREATE TRIGGER reject_c1_success BEFORE UPDATE ON message WHEN NEW.status='complete' AND OLD.status='streaming' BEGIN SELECT RAISE(ABORT, 'synthetic save failure'); END")
        provider.next = {'body': '另一个小点。', 'step': '另一个小点。'}
        reply = chat_turn(client, cid, '继续')
        assert reply['status'] == 'failed'
        assert reply['teaching']['current'] == first['teaching']['current']
        assert 'result' not in saved(client, reply['id'])['teaching']


def test_material_scope_and_managed_backup_erase_teaching_references(tmp_path):
    provider = TeachingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        base = f'/api/materials/conversation/{cid}'
        material = client.post(base, json={'title': '合成资料', 'content': 'C1_PRIVATE_SOURCE'}).json()
        scope = {'mode': 'only', 'version_ids': [material['id']]}
        provider.next = {'body': 'C1_PRIVATE_STEP', 'step': 'C1_PRIVATE_STEP'}
        first = chat_turn(client, cid, '开始', source_scope=scope)
        provider.next = {'body': '回应原文', 'attempt': 'C1_PRIVATE_ATTEMPT'}
        second = chat_turn(client, cid, 'C1_PRIVATE_ATTEMPT', source_scope=scope)
        fork = branch(client, cid, second['id']).json()
        bid = fork['conversation']['id']
        backup = tmp_path / 'c1-managed.sqlite3'
        db = client.app.state.database
        with closing(sqlite3.connect(backup)) as target:
            db.connection.backup(target)
        with storage_lock(client.app.state.materials.db.database_path):
            register_backup(client.app.state.materials.db.database_path, backup)
        provider.next = {'body': '独立回答。'}
        independent = chat_turn(client, cid, '换成独立问题')
        assert provider.calls[-1][1]['before'] == teaching.checkpoint()
        assert 'C1_PRIVATE_' not in json.dumps(provider.calls[-1])
        result = client.post(base + '/' + material['material_id'] + '/purge')
        assert result.status_code == 200 and result.json()['purge']['status'] == 'complete'
        for scope_id in (cid, bid):
            messages = client.get(f'/api/ai/conversations/{scope_id}').json()['messages']
            for item in messages:
                if item['role'] == 'assistant' and item['id'] != independent['id']:
                    assert item['teaching'] is None
                    assert 'teaching' not in saved(client, item['id'])
        with closing(sqlite3.connect(backup)) as c:
            snapshots = c.execute('SELECT config_snapshot_json FROM ai_run').fetchall()
            assert all('C1_PRIVATE_' not in row[0] and '"teaching"' not in row[0] for row in snapshots)
        assert client.post(f"/api/ai/conversations/{cid}/messages/{second['id']}/teaching-attempt",
            json={'expected_revision': 0, 'is_attempt': False, 'request_key': 'after-purge'}).status_code == 409


@pytest.mark.asyncio
async def test_discussion_checkpoint_correction_branch_and_formal_facts(learning_database):
    verification, original = await attempt(learning_database)
    service = QuestionDiscussionService(verification)
    did = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'c1-room')['id']
    original_detail = service.records.detail(IDENTITY, original['id'])
    provider = TeachingProvider()
    verification.transport = httpx.MockTransport(provider)
    first = (await service.send(IDENTITY, did, '解释小点', 'one'))['turns'][-1]
    provider.next = {'body': '按原条件讨论。', 'attempt': '我认为空输入应该拒绝'}
    second = (await service.send(IDENTITY, did, '我认为空输入应该拒绝', 'two'))['turns'][-1]
    assert second['teaching']['attempt']['step_id'] == first['id']
    assert second['teaching']['attempt']['message_id'] == second['id']
    frozen = json.loads(learning_database.fetchone('SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?', (second['id'],))[0])['teaching']
    service.correct_teaching_attempt(IDENTITY, did, second['id'], expected_revision=0, is_attempt=False, request_key='correction')
    assert json.loads(learning_database.fetchone('SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?', (second['id'],))[0])['teaching'] == frozen
    provider.next = {'body': '下一轮回应。'}
    later = (await service.send(IDENTITY, did, '继续', 'three'))['turns'][-1]
    assert provider.calls[-1][1]['attempt_context'][0]['is_attempt'] is False
    copied = branch_discussion(service, IDENTITY, did, second['id'], 'branch')
    assert len(copied['turns']) == 2
    assert copied['turns'][-1]['teaching']['attempt']['step_id'] == copied['turns'][0]['id']
    assert copied['turns'][-1]['teaching']['attempt']['message_id'] == copied['turns'][-1]['id']
    assert copied['turns'][-1]['teaching']['attempt']['is_attempt'] is False
    current_detail = service.records.detail(IDENTITY, original['id'])
    assert {k: v for k, v in current_detail.items() if k not in {'discussions', 'purge_discussion_count'}} == {
        k: v for k, v in original_detail.items() if k not in {'discussions', 'purge_discussion_count'}}
    assert len(provider.calls) == 3
    assert 'nautilus_teaching_' not in json.dumps(service.get(IDENTITY, did), ensure_ascii=False)
    verification.purge(IDENTITY, original['id'])
    for identifier in (first['id'], second['id'], later['id'], copied['turns'][-1]['id']):
        assert learning_database.fetchone('SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?', (identifier,))[0] == '{}'


@pytest.mark.asyncio
async def test_discussion_modes_versions_cancel_and_recovery(learning_database):
    verification, original = await attempt(learning_database)
    service = QuestionDiscussionService(verification)
    did = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'c1-versions')['id']
    provider = TeachingProvider()
    verification.transport = httpx.MockTransport(provider)
    first = (await service.send(IDENTITY, did, '开始', 'first'))['turns'][-1]
    provider.next = {'body': '本轮直接说明。', 'mode': {
        'value': 'direct_answer', 'scope': 'turn', 'quote': '直接给答案', 'persistence_quote': None}}
    second = (await service.send(IDENTITY, did, '直接给答案', 'second'))['turns'][-1]
    assert second['teaching']['effective_mode'] == 'direct_answer'
    assert second['teaching']['current']['mode'] == 'stepwise'
    provider.next = {'body': '沿用这种方式。', 'mode': {
        'value': 'full_explanation', 'scope': 'conversation', 'quote': '完整讲解', 'persistence_quote': '以后都这样'}}
    third = (await service.send(IDENTITY, did, '完整讲解，以后都这样', 'third'))['turns'][-1]
    assert third['teaching']['current']['mode'] == 'full_explanation'
    provider.next = {'body': '新回答。', 'step': '新回答。'}
    alternate = (await service.send(IDENTITY, did, '直接给答案', 'alternate', regenerate_turn_id=second['id']))['turns'][-1]
    assert alternate['teaching']['before'] == first['teaching']['current']
    edited = (await service.send(IDENTITY, did, '改成普通提问', 'edited', edit_turn_id=third['id']))['turns'][-1]
    assert edited['teaching']['before'] == second['teaching']['current']
    assert service.get(IDENTITY, did)['turns'][2]['teaching']['current']['mode'] == 'full_explanation'
    delivered = asyncio.Event()
    class Partial(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial discussion"}}]}\n\n'
            delivered.set()
            await asyncio.Event().wait()
    def partial(request):
        if not json.loads(request.content).get('stream'):
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"history_query":null}'}}]})
        return httpx.Response(200, stream=Partial())
    verification.transport = httpx.MockTransport(partial)
    active = service.start(IDENTITY, did, '继续', 'partial', parent_turn_id=third['id'])['turns'][-1]
    await asyncio.wait_for(delivered.wait(), 2)
    canceled = (await service.cancel(IDENTITY, did, active['id']))['turns'][-1]
    assert canceled['assistant_content'] == 'partial discussion'
    assert canceled['teaching']['current'] == third['teaching']['current']
    assert canceled['help_record']['provided']['partial']
    with learning_database.transaction() as c:
        c.execute("UPDATE learning_discussion_turn SET status='running', reason=NULL WHERE id=?", (active['id'],))
    service.recover()
    recovered = service.get(IDENTITY, did)['turns'][-1]
    assert recovered['reason'] == 'interrupted'
    assert recovered['teaching']['current'] == third['teaching']['current']
    assert recovered['assistant_content'] == 'partial discussion'
