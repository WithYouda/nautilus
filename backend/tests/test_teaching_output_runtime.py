"""Checked native output gates teaching state without interrupting ordinary chat."""

import copy
import json
from uuid import uuid4

import httpx
import pytest

from app import teaching_runtime as teaching
from app.providers import ProviderChunk
from app.question_discussion import QuestionDiscussionService
from app.teaching_capability import check as check_capability, output_for
from test_ai_conversations import FAKE_API_KEY, authorize, configure_provider, make_client, read_sse
from test_learning_verifications import IDENTITY
from test_teaching_runtime import chat_turn, new_chat, saved
from test_verification_review import attempt as verification_attempt


def proposal(**changes):
    return {'step': None, 'attempt': None, 'mode': None, 'help': None, 'practice': None, **changes}


class StructuredTeachingProvider:
    """Echo synthetic checks, then return configurable actual teaching envelopes."""

    def __init__(self):
        self.checks = []
        self.calls = []
        self.history_checks = []
        self.check_network_failure = False
        self.unsupported = set()
        self.next = {'body': '🍊 普通回答。', 'proposal': proposal()}

    def __call__(self, request):
        payload = json.loads(request.content)
        if not payload.get('stream'):
            assert payload['messages'][0]['content'].startswith('为题目讨论决定是否查阅当前委托的历史。')
            self.history_checks.append(payload)
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"history_query":null}'},
                                                          'finish_reason': 'stop'}]})
        assert payload.get('stream') is True
        messages = payload['messages']
        runtime = next((message['content'] for message in reversed(messages)
                        if str(message.get('content', '')).startswith('Nautilus 本轮执行上下文')), None)
        context = json.loads(runtime.split('\n', 1)[1]) if runtime else None
        if messages[0]['content'].startswith('这是一次应用能力检查。'):
            mode = 'tools' if payload.get('tools') else 'plain'
            self.checks.append((mode, payload))
            assert payload['response_format'] == {'type': 'json_object'}
            if mode == 'tools':
                assert payload['tools'][0]['function']['name'] == 'check_unused'
            if self.check_network_failure:
                raise httpx.ReadError('synthetic temporary network failure', request=request)
            raw = 'ordinary unsupported output' if mode in self.unsupported else messages[-1]['content']
            return self.response(raw)
        self.calls.append((payload, context))
        spec = self.next
        if context and context.get('output_format') == 'json':
            assert payload['response_format'] == {'type': 'json_object'}
            token = 'wrong-token' if spec.get('failure') == 'token' else context['token']
            raw = json.dumps({'reply': spec['body'], 'teaching': spec['proposal'], 'token': token},
                             ensure_ascii=False)
            if spec.get('failure') == 'truncated':
                raw = '{"reply":' + json.dumps(spec['body'], ensure_ascii=False)[:-1]
        else:
            assert 'response_format' not in payload
            assert context is None
            raw = spec['body']
        finish = 'length' if spec.get('failure') == 'truncated' else None if spec.get('failure') == 'unknown' else 'stop'
        return self.response(raw, finish=finish)

    @staticmethod
    def response(raw, *, finish='stop'):
        events = ['data: ' + json.dumps({'choices': [{'delta': {'content': raw[index:index + 3]}}]},
                                      ensure_ascii=False) + '\n\n'
                  for index in range(0, len(raw), 3)]
        if finish is not None:
            events.append('data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': finish}]}) + '\n\n')
        return httpx.Response(200, text=''.join(events) + 'data: [DONE]\n\n')


def support_path(profile):
    return f'/api/ai/providers/{profile["id"]}/models/{profile["default_model"]["id"]}/teaching-support'


def checked(client, profile):
    response = client.post(support_path(profile) + '/check')
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['support']['plain'] == result['support']['tools'] == 'supported'
    assert result['failures'] == {} and result['updated'] is True
    return result['support']


def defaults(client, mode):
    response = client.put('/api/preferences', json={**client.get('/api/preferences').json(), 'teaching_mode': mode})
    assert response.status_code == 200, response.text


def send(client, cid, content, **extra):
    payload = {'content': content, 'client_message_id': str(uuid4()), **extra}
    response = client.post(f'/api/ai/conversations/{cid}/messages', json=payload)
    assert response.status_code == 202, response.text
    run = response.json()['run']
    frames = read_sse(client, run['id'])
    answer = next(item for item in client.get(f'/api/ai/conversations/{cid}').json()['messages']
                  if item['id'] == run['response_message_id'])
    return answer, frames, payload


def test_unchecked_model_keeps_normal_chat_and_rejects_activity_without_new_messages(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        assert client.get(support_path(profile)).json() == {'plain': 'unchecked', 'tools': 'unchecked', 'checked_at': None}
        cid = new_chat(client)
        answer = chat_turn(client, cid, '普通问题')
        assert answer['content'] == provider.next['body']
        assert answer['teaching']['status'] == 'unavailable'
        assert answer['teaching']['recording'] == {'available': False, 'reason': 'not_checked'}
        frozen = saved(client, answer['id'])['teaching']
        assert frozen['output']['format'] == 'plain' and 'result' not in frozen
        before = client.get(f'/api/ai/conversations/{cid}').json()['messages']
        rejected = client.post(f'/api/ai/conversations/{cid}/messages', json={
            'content': '用自己的话说说', 'client_message_id': 'unchecked-action', 'teaching_action': 'retell'})
        assert rejected.status_code == 400
        assert client.get(f'/api/ai/conversations/{cid}').json()['messages'] == before
        assert len(provider.calls) == 1 and provider.checks == []


def test_explicit_check_then_actual_retelling_has_exact_reply_sources_after_refresh(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        support = checked(client, profile)
        assert client.get(support_path(profile)).json() == support
        assert [mode for mode, _ in provider.checks] == ['plain', 'tools']
        for _, payload in provider.checks:
            echoed = json.loads(payload['messages'][-1]['content'])
            assert echoed['reply'] == '检查通过 <think> 🍊\n第二行'
        defaults(client, 'feynman')
        cid = new_chat(client)
        invitation = '🍊 请说明空输入为什么需要单独判断。'
        provider.next = {'body': invitation, 'proposal': proposal(step=invitation)}
        initial, _, _ = send(client, cid, '先学空输入')
        quote = '🍎 我写了 <think>literal</think>；空输入没有第一项。'
        feedback = '🍐 <think>是原文标签</think>。\n你讲清了越界的原因。'
        provider.next = {'body': feedback, 'proposal': proposal(attempt={'quote': quote, 'needs_help': False})}
        observed, frames, _ = send(client, cid, '我的解释：' + quote)
        assert initial['content'] == invitation and observed['content'] == feedback
        assert initial['teaching']['status'] == observed['teaching']['status'] == 'applied'
        replay = next(data['content'] for event, data in frames if event == 'start')
        visible = replay + ''.join(data['text'] for event, data in frames if event == 'delta')
        assert visible == feedback and '"teaching"' not in visible
        assert frames[-1][0] == 'done' and frames[-1][1]['content'] == feedback
        assert frames[-1][1]['reasoning_content'] == ''
        parts = frames[-1][1]['generation_trace']['parts']
        assert [part['type'] for part in parts] == ['text'] and parts[0]['text'] == feedback
        refreshed = next(item for item in client.get(f'/api/ai/conversations/{cid}').json()['messages']
                         if item['id'] == observed['id'])
        assert refreshed == observed
        record = refreshed['teaching']['retelling_observation']
        user = next(item for item in client.get(f'/api/ai/conversations/{cid}').json()['messages']
                    if item['id'] == record['message_id'])
        assert user['content'][record['start']:record['end']] == quote
        assert refreshed['content'][record['feedback_start']:record['feedback_end']] == feedback
        assert record['question_id'] == initial['id'] and record['eligible'] is True
        assert len(provider.checks) == 2 and len(provider.calls) == 2


def test_replay_keeps_accepted_output_and_regenerate_uses_current_checked_binding(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        checked(client, profile)
        defaults(client, 'feynman')
        cid = new_chat(client)
        provider.next = {'body': '先看空输入。', 'proposal': proposal(step='先看空输入。')}
        initial = chat_turn(client, cid, '开始')
        invitation = '🍊 请用自己的话解释空输入。'
        provider.next = {'body': invitation, 'proposal': proposal(practice={'question': invitation, 'feedback': None})}
        invited, _, payload = send(client, cid, '用自己的话说说', teaching_action='retell', parent_message_id=initial['id'])
        accepted = copy.deepcopy(saved(client, invited['id'])['teaching'])
        assert accepted['action'] == 'retell' and accepted['default_mode'] == 'feynman'
        changed = client.patch(f'/api/ai/providers/{profile["id"]}', json={'base_url': 'https://changed.example.test/v1'})
        assert changed.status_code == 200, changed.text
        defaults(client, 'socratic')
        calls = len(provider.calls)
        replay = client.post(f'/api/ai/conversations/{cid}/messages', json=payload)
        assert replay.status_code == 202 and replay.json()['created'] is False
        assert len(provider.calls) == calls
        assert saved(client, invited['id'])['teaching'] == accepted
        assert client.get(support_path(profile)).json()['plain'] == 'unchecked'
        checked(client, profile)
        regenerated = chat_turn(client, cid, payload['content'], regenerate_message_id=invited['id'])
        current = saved(client, regenerated['id'])['teaching']
        assert current['output']['format'] == 'json'
        assert current['output']['binding'] != accepted['output']['binding']
        assert current['action'] == 'retell' and current['default_mode'] == 'feynman'
        assert regenerated['teaching']['current']['mode'] == 'feynman'
        assert client.get('/api/preferences').json()['teaching_mode'] == 'socratic'
        assert len(provider.calls) == calls + 1


def test_temporary_check_failure_retains_prior_success(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        prior = checked(client, profile)
        provider.check_network_failure = True
        failed = client.post(support_path(profile) + '/check')
        assert failed.status_code == 200, failed.text
        assert failed.json() == {'support': prior, 'failures': {'plain': 'network_error', 'tools': 'network_error'}, 'updated': False}
        assert client.get(support_path(profile)).json() == prior
        assert len(provider.checks) == 4 and provider.calls == []


def test_model_configuration_credential_and_protocol_changes_invalidate_support(tmp_path):
    for index, change in enumerate(({'base_url': 'https://changed.example.test/v1'},
                                    {'api_key': 'sk-synthetic-new-key'}, {'api_protocol': 'openai_responses'})):
        provider = StructuredTeachingProvider()
        with make_client(tmp_path / str(index), provider) as client:
            authorize(client)
            profile = configure_provider(client)
            checked(client, profile)
            response = client.patch(f'/api/ai/providers/{profile["id"]}', json=change)
            assert response.status_code == 200, response.text
            assert client.get(support_path(profile)).json() == {'plain': 'unchecked', 'tools': 'unchecked', 'checked_at': None}
            assert len(provider.checks) == 2 and provider.calls == []


def test_invalid_token_truncation_and_unknown_completion_keep_reply_without_state(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        checked(client, profile)
        for failure in ('token', 'truncated', 'unknown'):
            cid = new_chat(client)
            body = '🍊 <think>原文标签</think>\n保留下来的部分回答。'
            provider.next = {'body': body, 'proposal': proposal(step=body), 'failure': failure}
            answer, frames, _ = send(client, cid, '合成问题')
            assert answer['content'] == body
            assert answer['teaching']['status'] == 'not_updated'
            assert answer['teaching']['current']['step'] is None
            frozen = saved(client, answer['id'])['teaching']
            assert 'result' not in frozen
            if failure != 'truncated':
                assert frozen['not_applied_reason'] == {'token': 'envelope_token_mismatch', 'unknown': 'completion_unknown'}[failure]
                assert frames[-1][0] == 'done'
            else:
                assert frames[-1][0] == 'error' and frames[-1][1]['kind'] == 'output_truncated'
            assert frames[-1][1]['content'] == body and frames[-1][1]['reasoning_content'] == ''
        assert len(provider.calls) == 3 and len(provider.checks) == 2


def test_unsupported_tool_combination_does_not_disable_checked_plain_chat(tmp_path):
    provider = StructuredTeachingProvider()
    provider.unsupported = {'tools'}
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        result = client.post(support_path(profile) + '/check')
        assert result.status_code == 200, result.text
        assert result.json()['support']['plain'] == 'supported'
        assert result.json()['support']['tools'] == 'unavailable'
        assert result.json()['updated'] is True and result.json()['failures'] == {}
        cid = new_chat(client)
        provider.next = {'body': '新小点。', 'proposal': proposal(step='新小点。')}
        answer = chat_turn(client, cid, '普通讲解')
        assert answer['teaching']['status'] == 'applied'
        service = client.app.state.conversations
        owner = client.app.state.auth.ensure_local_identity()['id']
        selected, config = service.provider_runtime_for(owner, profile['id'], profile['default_model']['id'])
        search = {'mode': 'external'}
        assert output_for(service, owner, selected, config, search=search)['format'] == 'plain'
        native = {'mode': 'native'}
        output = output_for(service, owner, selected, config, search=native)
        assert output['format'] == 'plain' and output['reason'] == 'native_search_unverified'
        assert native == {'mode': 'native'} and search == {'mode': 'external'}


@pytest.mark.asyncio
async def test_discussion_json_retelling_exact_sources_refresh_and_truncated_feedback(tmp_path):
    provider = StructuredTeachingProvider()
    transport = httpx.MockTransport(provider)
    with make_client(tmp_path / 'discussion-runtime', provider) as client:
        chats = client.app.state.conversations
        learning_database = client.app.state.learning.database
        for database in (chats.database, learning_database):
            with database.transaction() as connection:
                connection.execute('''INSERT INTO local_identity
                    (id,device_id,display_name,timezone,created_at,updated_at) VALUES (?,?,?,?,?,?)''',
                    (IDENTITY['id'], IDENTITY['device_id'], IDENTITY['display_name'], IDENTITY['timezone'],
                     IDENTITY['created_at'], IDENTITY['created_at']))
        verification, original = await verification_attempt(learning_database)
        profile = chats.save_provider(IDENTITY['id'], display_name='合成题目讨论模型',
                                      base_url='https://api.example.com/v1', model='gpt-4o', api_key=FAKE_API_KEY)
        result = await check_capability(chats, IDENTITY['id'], profile['id'], profile['default_model']['id'],
                                        transport=transport)
        assert result['support']['plain'] == result['support']['tools'] == 'supported'
        assert result['updated'] is True and result['failures'] == {}
        chats.preferences.save(IDENTITY['id'], {'conflict_policy': 'ask', 'search': {'mode': 'off'},
                                               'teaching_mode': 'feynman'})
        verification.conversations = chats
        verification.transport = transport
        service = QuestionDiscussionService(verification)
        did = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1',
                             'json-discussion')['id']
        invitation = '🍊 请用自己的话解释为什么空输入需要单独判断。'
        provider.next = {'body': invitation, 'proposal': proposal(step=invitation)}
        initial = (await service.send(IDENTITY, did, '先学空输入', 'json-invitation'))['turns'][-1]
        quote = '🍎 空输入没有第一项；<think>是我写下的标签</think>。'
        user_text = '我的解释：' + quote
        feedback = '🍐 你讲清了越界的原因。\n<think>这里仍然是原文标签</think>。'
        provider.next = {'body': feedback, 'proposal': proposal(attempt={'quote': quote, 'needs_help': False})}
        observed = (await service.send(IDENTITY, did, user_text, 'json-retelling'))['turns'][-1]
        assert initial['assistant_content'] == invitation and observed['assistant_content'] == feedback
        assert initial['status'] == observed['status'] == 'succeeded'
        assert initial['teaching']['status'] == observed['teaching']['status'] == 'applied'
        assert observed['teaching']['current']['mode'] == 'feynman'
        assert observed['teaching']['current']['retelling']['phase'] == 'feedback_available'
        assert observed['reasoning_content'] in (None, '')
        record = observed['teaching']['retelling_observation']
        assert record['question_id'] == initial['id']
        assert record['message_id'] == record['answer_id'] == observed['id'] and record['eligible'] is True
        assert record['start'] == len('我的解释：') and record['end'] == len(user_text)
        assert observed['user_content'][record['start']:record['end']] == quote
        assert record['feedback_start'] == 0 and record['feedback_end'] == len(feedback)
        assert observed['assistant_content'][record['feedback_start']:record['feedback_end']] == feedback
        refreshed = QuestionDiscussionService(verification).get(IDENTITY, did)['turns'][-1]
        assert refreshed == observed
        snapshot = json.loads(learning_database.fetchone(
            'SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?', (observed['id'],))[0])
        assert snapshot['teaching']['output']['format'] == 'json' and 'result' in snapshot['teaching']

        retry_quote = '🍎 我还会检查返回值。'
        partial = '🍐 保留下来的部分反馈。'
        provider.next = {'body': partial, 'proposal': proposal(attempt={'quote': retry_quote, 'needs_help': False}),
                         'failure': 'truncated'}
        failed = (await service.send(IDENTITY, did, retry_quote, 'json-truncated'))['turns'][-1]
        assert failed['status'] == 'failed' and failed['assistant_content'] == partial
        assert failed['teaching']['status'] == 'not_updated'
        assert failed['teaching']['retelling_observation'] is None
        assert failed['teaching']['current'] == observed['teaching']['current']
        failed_snapshot = json.loads(learning_database.fetchone(
            'SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?', (failed['id'],))[0])
        assert 'result' not in failed_snapshot['teaching']
        assert next(turn for turn in service.get(IDENTITY, did)['turns'] if turn['id'] == observed['id']) == observed
        assert len(provider.checks) == 2 and len(provider.calls) == len(provider.history_checks) == 3


def frozen_json(*, default_mode='stepwise'):
    return teaching.freeze([], answer_id='final-answer', message_id='actual-user', kind='conversation',
                           scope_id='synthetic-scope', default_mode=default_mode,
                           output={'format': 'json', 'version': 1})


async def two_rounds(parser, frozen, before_reply, final_reply, final_proposal):
    def raw(reply, metadata):
        return json.dumps({'reply': reply, 'teaching': metadata, 'token': frozen['token']}, ensure_ascii=False)
    async def source():
        yield ProviderChunk('model_start', '')
        yield ProviderChunk('content', raw(before_reply, proposal(step=before_reply)))
        yield ProviderChunk('completion', 'complete')
        yield ProviderChunk('tool_start', '{}')
        yield ProviderChunk('model_start', '')
        final = raw(final_reply, final_proposal)
        for index in range(0, len(final), 2):
            yield ProviderChunk('content', final[index:index + 2])
        yield ProviderChunk('completion', 'complete')
    pieces = []
    async for chunk in parser.filter(source()):
        if chunk.kind == 'tool_start':
            assert parser.proposal() is None
        if chunk.kind == 'content':
            pieces.append(chunk.text)
        assert chunk.kind != 'reasoning'
    return ''.join(pieces)


@pytest.mark.asyncio
async def test_new_tool_round_discards_pre_answer_proposal_and_offsets_duplicate_final_step():
    frozen = frozen_json()
    parser = teaching.TeachingStream(frozen)
    reply = '🍊 <think>literal</think> 新小点。'
    final = proposal(step=reply)
    body = await two_rounds(parser, frozen, reply, reply, final)
    assert body == reply + '\n\n' + reply
    assert parser.proposal() == final
    start = len(reply) + 2
    assert parser.outcome()['teaching_reply_start'] == start
    teaching.adopt(frozen, parser.proposal(), body=body, user_text='actual input', at='synthetic', reply_start=start)
    step = frozen['result']['after']['step']
    assert step['start'] == start and step['end'] == len(body)
    assert body[step['start']:step['end']] == reply


@pytest.mark.asyncio
async def test_final_metadata_cannot_use_intermediate_tool_prose_as_its_source():
    frozen = frozen_json()
    parser = teaching.TeachingStream(frozen)
    body = await two_rounds(parser, frozen, '只在中间轮出现的小点。', '最终回复。', proposal(step='只在中间轮出现的小点。'))
    outcome = parser.outcome()
    teaching.adopt(frozen, outcome['teaching_proposal'], body=body, user_text='actual input', at='synthetic',
                   reply_start=outcome['teaching_reply_start'])
    assert 'result' not in frozen and frozen['not_applied_reason'] == 'quote_mismatch'
    assert frozen['before']['step'] is None


@pytest.mark.asyncio
async def test_final_feedback_offsets_shift_answer_spans_but_keep_user_and_prior_sources():
    frozen = frozen_json(default_mode='feynman')
    prior = {'id': 'prior-answer', 'source_answer_id': 'prior-answer', 'text': '旧小点。', 'start': 5, 'end': 10}
    frozen['before']['step'] = copy.deepcopy(prior)
    parser = teaching.TeachingStream(frozen)
    quote = '🍎 我认为空输入需要提前判断。'
    user_text = '我的解释：' + quote
    feedback = '🍐 你讲清了越界的原因。'
    body = await two_rounds(parser, frozen, feedback, feedback,
                            proposal(attempt={'quote': quote, 'needs_help': False}))
    outcome = parser.outcome()
    teaching.adopt(frozen, outcome['teaching_proposal'], body=body, user_text=user_text, at='synthetic',
                   reply_start=outcome['teaching_reply_start'])
    result = frozen['result']
    record = result['retelling_observation']
    assert record['feedback_start'] == len(feedback) + 2 and record['feedback_end'] == len(body)
    assert body[record['feedback_start']:record['feedback_end']] == feedback
    assert record['start'] == len('我的解释：') and user_text[record['start']:record['end']] == quote
    assert result['attempt']['start'] == record['start']
    assert result['after']['step'] == prior


@pytest.mark.asyncio
async def test_final_activity_question_uses_final_occurrence_and_preserves_its_basis():
    frozen = frozen_json()
    frozen['action'] = 'retell'
    prior = {'id': 'prior-answer', 'source_answer_id': 'prior-answer', 'text': '旧小点。', 'start': 5, 'end': 10}
    frozen['before']['step'] = copy.deepcopy(prior)
    parser = teaching.TeachingStream(frozen)
    invitation = '🍊 请用自己的话解释旧小点。'
    body = await two_rounds(parser, frozen, invitation, invitation,
                            proposal(practice={'question': invitation, 'feedback': None}))
    outcome = parser.outcome()
    teaching.adopt(frozen, outcome['teaching_proposal'], body=body, user_text='请求复述', at='synthetic',
                   reply_start=outcome['teaching_reply_start'])
    result = frozen['result']
    start = len(invitation) + 2
    for frame in (result['after']['practice'], result['practice_question']):
        question = frame['question']
        assert question['start'] == start and question['end'] == len(body)
        assert body[question['start']:question['end']] == invitation
        assert frame['basis_step'] == prior
    assert result['after']['step']['start'] == start
