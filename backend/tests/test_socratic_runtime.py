"""C2 ladder decisions, corrected evidence and version-local recovery."""
import asyncio
import copy
import json
from uuid import uuid4

import httpx
import pytest

from app import teaching_runtime as teaching
from app.discussion_branches import create_branch as branch_discussion
from app.learning_domain import DomainError
from app.question_discussion import QuestionDiscussionService
from test_ai_conversations import authorize, configure_provider, make_client, read_sse
from test_conversation_branches import branch
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY
from test_teaching_runtime import TeachingProvider, chat_turn, new_chat, saved
from test_verification_review import attempt as verification_attempt


class SocraticProvider(TeachingProvider):
    def __call__(self, request):
        if 'raw' not in self.next:
            observation = None
            if 'attempt' in self.next:
                observation = {'quote': self.next['attempt'], 'needs_help': self.next.get('needs_help')}
            spec = {**self.next, 'raw': json.dumps({
                'step': self.next.get('step'), 'attempt': observation,
                'mode': self.next.get('mode'), 'help': self.next.get('help')}, ensure_ascii=False)}
            original, self.next = self.next, spec
            try:
                return super().__call__(request)
            finally:
                self.next = original
        return super().__call__(request)


def observation(provider, text, needs_help=True, **extra):
    provider.next = {'body': '请继续检查当前输入边界。', 'attempt': text, 'needs_help': needs_help, **extra}


def guide(answer):
    return answer['teaching']['current']['guidance']


def test_ladder_counts_real_attempts_and_explicit_help_with_ceiling(tmp_path):
    provider = SocraticProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        first = chat_turn(client, cid, '开始', teaching_mode='socratic')
        assert first['teaching']['requested_mode'] == 'socratic'
        assert provider.calls[0][1]['before']['mode'] == 'socratic'
        assert guide(first)['level'] == 0
        observation(provider, '我先令输入为空，但仍不知道如何判断')
        one = chat_turn(client, cid, provider.next['attempt'])
        assert guide(one)['stuck_count'] == 1
        provider.next = {'body': '继续思考同一边界。'}
        question = chat_turn(client, cid, '这里为什么要这样判断？')
        assert question['teaching']['attempt'] is None
        assert guide(question)['stuck_count'] == 1
        observation(provider, '我再检查长度，仍找不到拒绝条件')
        two = chat_turn(client, cid, provider.next['attempt'])
        assert two['teaching']['guidance'] == {'level': 1, 'reason': 'repeated_difficulty'}
        assert guide(two)['stuck_count'] == 0
        provider.next = {'body': '从另一种输入情境思考。'}
        example = chat_turn(client, cid, '换个例子', help_request='example')
        assert guide(example)['level'] == 1
        waiting = chat_turn(client, cid, '让我先试试', help_request='try_first')
        assert waiting['teaching']['attempt'] is None and guide(waiting)['level'] == 1
        for expected in (2, 3, 4, 4):
            hinted = chat_turn(client, cid, '给个提示', help_request='hint')
            assert guide(hinted)['level'] == expected
            assert hinted['teaching']['guidance']['reason'] == 'requested_hint'
        assert len(provider.calls) == 10  # No classification or repair call.


def test_correction_changes_future_count_but_does_not_rewrite_frozen_help(tmp_path):
    provider = SocraticProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        first = chat_turn(client, cid, '开始', teaching_mode='socratic')
        observation(provider, '我先检查空输入')
        one = chat_turn(client, cid, provider.next['attempt'])
        frozen = copy.deepcopy(saved(client, one['id'])['teaching'])
        endpoint = f"/api/ai/conversations/{cid}/messages/{one['id']}/teaching-attempt"
        change = {'expected_revision': 0, 'is_attempt': True, 'needs_help': False, 'request_key': 'progressed'}
        corrected = client.post(endpoint, json=change)
        assert corrected.status_code == 200
        assert corrected.json()['attempt']['needs_help'] is False
        assert client.post(endpoint, json=change).json() == corrected.json()
        assert client.post(endpoint, json={**change, 'needs_help': True}).status_code == 409
        assert client.post(endpoint, json={**change, 'needs_help': 'false'}).status_code == 422
        assert saved(client, one['id'])['teaching'] == frozen
        observation(provider, '我重新检查长度还是没弄清楚')
        after = chat_turn(client, cid, provider.next['attempt'])
        assert after['teaching']['before']['guidance']['stuck_count'] == 0
        assert guide(after)['level'] == 0 and guide(after)['stuck_count'] == 1
        assert provider.calls[-1][1]['attempt_context'][0]['needs_help'] is False
        # A correction can restore a previously dismissed observation. Future
        # preparation recounts both attempts, but it does not rewrite old help.
        restored = client.post(endpoint, json={**change, 'expected_revision': 1,
            'needs_help': True, 'request_key': 'restore-stuck'})
        assert restored.status_code == 200
        provider.next = {'body': '现在提醒相关概念。'}
        upgraded = chat_turn(client, cid, '继续')
        assert upgraded['teaching']['before']['guidance']['stuck_count'] == 2
        assert guide(upgraded)['level'] == 1
        assert guide(upgraded)['reset_answer_id'] == upgraded['id']
        client.post(endpoint, json={**change, 'expected_revision': 2, 'request_key': 'correct-again'})
        following = chat_turn(client, cid, '再继续')
        assert guide(following)['level'] == 1 and guide(following)['stuck_count'] == 0
        assert first['teaching']['current']['step'] == following['teaching']['current']['step']


@pytest.mark.parametrize('needs_help', [False, None])
def test_progress_or_unknown_breaks_stuck_streak_without_claiming_mastery(tmp_path, needs_help):
    provider = SocraticProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        chat_turn(client, cid, '开始', teaching_mode='socratic')
        for text, state in [('我先检查空输入', True), ('我给出了另一种判断', needs_help), ('我仍在尝试长度条件', True)]:
            observation(provider, text, state)
            last = chat_turn(client, cid, text)
        assert guide(last)['level'] == 0 and guide(last)['stuck_count'] == 1
        assert not {'completed', 'mastered', 'score'} & set(last['teaching'])


def test_explicit_explanation_and_one_turn_override_do_not_change_base_method(tmp_path):
    provider = SocraticProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        chat_turn(client, cid, '开始', teaching_mode='socratic')
        provider.next = {'body': '提醒输入与长度的关系。', 'help': {'kind': 'hint', 'quote': '给点提示'}}
        hint = chat_turn(client, cid, '请给点提示')
        assert guide(hint)['level'] == 1
        observation(provider, '我先看长度，还是不明白')
        chat_turn(client, cid, provider.next['attempt'])
        provider.next = {'body': '本轮完整解释。', 'mode': {
            'value': 'full_explanation', 'scope': 'turn', 'quote': '完整讲解', 'persistence_quote': None}}
        full = chat_turn(client, cid, '这次完整讲解')
        assert full['teaching']['current']['mode'] == 'socratic'
        assert guide(full)['level'] == 1 and guide(full)['stuck_count'] == 0
        assert full['teaching']['guidance']['level'] == 4
        provider.next = {'body': '回到提问引导。'}
        restored = chat_turn(client, cid, '继续')
        assert restored['teaching']['effective_mode'] == 'socratic'
        assert guide(restored)['level'] == 1
        explained = chat_turn(client, cid, '只解释这一步', help_request='explain_step')
        assert guide(explained)['level'] == 4
        provider.next = {'body': '下一个小点是正常输入。', 'step': '下一个小点是正常输入。'}
        next_point = chat_turn(client, cid, '换个新小点')
        assert guide(next_point)['level'] == 0


def test_mode_request_is_idempotent_survives_no_metadata_and_replays_original_choice(tmp_path):
    provider = SocraticProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        provider.next = {'body': '仍可使用这段回答。', 'no_metadata': True}
        payload = {'content': '开始', 'client_message_id': 'same', 'teaching_mode': 'socratic'}
        path = f'/api/ai/conversations/{cid}/messages'
        response = client.post(path, json=payload)
        assert response.status_code == 202
        read_sse(client, response.json()['run']['id'])
        assert client.post(path, json=payload).json()['created'] is False
        assert client.post(path, json={**payload, 'teaching_mode': 'stepwise'}).status_code == 409
        first = client.get(f'/api/ai/conversations/{cid}').json()['messages'][-1]
        assert first['teaching']['status'] == 'not_updated'
        assert first['teaching']['current']['mode'] == 'socratic'
        assert saved(client, first['id'])['teaching']['not_applied_reason'] == 'trailer_missing'
        provider.next = {'body': '检查输入边界。', 'step': '检查输入边界。'}
        chat_turn(client, cid, '这次改为分步', teaching_mode='stepwise')
        retry = chat_turn(client, cid, '开始', regenerate_message_id=first['id'])
        assert retry['teaching']['requested_mode'] == 'socratic'
        assert retry['teaching']['before']['mode'] == 'socratic'
        edited = chat_turn(client, cid, '编辑后的问题', edit_message_id=first['parent_message_id'])
        assert edited['teaching']['before']['mode'] == 'stepwise'
        assert len(provider.calls) == 4


def test_branches_remap_hint_reset_and_corrections_without_moving_original_path(tmp_path):
    provider = SocraticProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        chat_turn(client, cid, '开始', teaching_mode='socratic')
        provider.next = {'body': '给出一个线索。'}
        hint = chat_turn(client, cid, '给个提示', help_request='hint')
        observation(provider, '我还是先检查长度')
        one = chat_turn(client, cid, provider.next['attempt'])
        fork = branch(client, cid, one['id']).json()
        answers = [m for m in fork['messages'] if m['role'] == 'assistant']
        assert guide(answers[-1])['reset_answer_id'] == answers[-2]['id']
        assert guide(answers[-1])['reset_answer_id'] != hint['id']
        observation(provider, '我再试拒绝空输入，仍不确定')
        fork_reply = chat_turn(client, fork['conversation']['id'], provider.next['attempt'])
        assert guide(fork_reply)['level'] == 2
        assert guide(client.get(f'/api/ai/conversations/{cid}').json()['messages'][-1])['level'] == 1
        nested = branch(client, fork['conversation']['id'], fork_reply['id'], key='nested-c2').json()
        assert guide(nested['messages'][-1])['reset_answer_id'] == nested['messages'][-1]['id']


def test_natural_persistent_switch_counts_current_attempt_across_next_freeze_and_branch(tmp_path):
    provider = SocraticProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        point = chat_turn(client, cid, '先讲清楚边界')
        observation(provider, '我先检查长度但仍不确定', mode={
            'value': 'socratic', 'scope': 'conversation', 'quote': '提问引导',
            'persistence_quote': '以后都用提问引导'})
        switched = chat_turn(client, cid, '以后都用提问引导。我先检查长度但仍不确定')
        assert guide(switched)['stuck_count'] == 1
        assert guide(switched)['reset_answer_id'] == point['id']
        copied = branch(client, cid, switched['id']).json()
        inherited = [m for m in copied['messages'] if m['role'] == 'assistant']
        assert saved(client, inherited[-1]['id'])['teaching']['parent_answer_id'] == inherited[0]['id']
        observation(provider, '我再检查空输入还是不明白')
        follow = chat_turn(client, copied['conversation']['id'], provider.next['attempt'])
        assert follow['teaching']['before']['guidance']['stuck_count'] == 1
        assert guide(follow)['level'] == 1 and guide(follow)['stuck_count'] == 0


@pytest.mark.parametrize('change,reason', [
    ({'finish': None}, 'completion_unknown'),
    ({'raw': '{bad'}, 'trailer_invalid_json'),
    ({'step': '不在正文中的步骤'}, 'quote_mismatch'),
    ({'raw': '{"step":null,"attempt":null,"mode":null,"level":4}'}, 'proposal_invalid_schema'),
    ({'step': '偷偷换了步骤。', 'body': '偷偷换了步骤。', 'attempt': '我仍然卡住', 'needs_help': True}, 'step_changed_while_waiting'),
])
def test_invalid_reply_does_not_commit_ladder_and_reason_contains_no_source(tmp_path, change, reason):
    provider = SocraticProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        first = chat_turn(client, cid, '开始', teaching_mode='socratic')
        provider.next = {'body': '保持之前小点。', **change}
        last = chat_turn(client, cid, '我仍然卡住')
        assert last['teaching']['current'] == first['teaching']['current']
        frozen = saved(client, last['id'])['teaching']
        assert frozen['not_applied_reason'] == reason
        assert 'result' not in frozen
        assert not any(key in frozen for key in ('raw', 'proposal', 'quote'))


@pytest.mark.asyncio
async def test_discussion_counts_corrections_versions_cancel_and_formal_facts(learning_database):
    verification, original = await verification_attempt(learning_database)
    service = QuestionDiscussionService(verification)
    original_detail = copy.deepcopy(service.records.detail(IDENTITY, original['id']))
    did = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'c2')['id']
    provider = SocraticProvider()
    verification.transport = httpx.MockTransport(provider)
    async def send(text, **extra):
        return (await service.send(IDENTITY, did, text, str(uuid4()), **extra))['turns'][-1]
    first = await send('开始', teaching_mode='socratic')
    observation(provider, '我选择先检查空输入')
    one = await send(provider.next['attempt'])
    observed = service.correct_teaching_attempt(IDENTITY, did, one['id'], expected_revision=0,
        is_attempt=True, needs_help=False, request_key='progressed')
    assert observed['attempt']['needs_help'] is False
    observation(provider, '我再检查长度但仍不确定')
    after = await send(provider.next['attempt'])
    assert guide(after)['level'] == 0 and guide(after)['stuck_count'] == 1
    repeated = await send(provider.next['attempt'], regenerate_turn_id=after['id'])
    assert guide(repeated)['level'] == 0 and guide(repeated)['stuck_count'] == 1
    provider.next = {'body': '再给一个提示。'}
    hint = await send('给个提示', help_request='hint')
    assert guide(hint)['level'] == 1
    copied = branch_discussion(service, IDENTITY, did, hint['id'], 'fork-c2')
    assert guide(copied['turns'][-1])['reset_answer_id'] == copied['turns'][-1]['id']
    delivered = asyncio.Event()
    class Partial(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial teaching"}}]}\n\n'
            delivered.set()
            await asyncio.Event().wait()
    def partial(request):
        if not json.loads(request.content).get('stream'):
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"history_query":null}'}}]})
        return httpx.Response(200, stream=Partial())
    verification.transport = httpx.MockTransport(partial)
    running = service.start(IDENTITY, did, '给个提示', 'cancel', help_request='hint')['turns'][-1]
    await asyncio.wait_for(delivered.wait(), 3)
    with pytest.raises(DomainError, match='discussion_busy'):
        service.correct_teaching_attempt(IDENTITY, did, one['id'], expected_revision=1,
            is_attempt=True, needs_help=True, request_key='busy')
    await service.cancel(IDENTITY, did, running['id'])
    await asyncio.gather(*list(service.tasks.values()), return_exceptions=True)
    canceled = service.get(IDENTITY, did)['turns'][-1]
    assert canceled['id'] == running['id'] and canceled['reason'] == 'cancelled'
    assert canceled['teaching']['current'] == hint['teaching']['current']
    assert canceled['help_record']['provided']['partial'] is True
    actual = service.records.detail(IDENTITY, original['id'])
    excluded = {'discussions', 'purge_discussion_count'}
    assert {k: v for k, v in actual.items() if k not in excluded} == {
        k: v for k, v in original_detail.items() if k not in excluded}
    assert first['teaching']['current']['step'] == canceled['teaching']['current']['step']


def test_legacy_teaching_record_stays_readable_without_fabricated_observation():
    frozen = teaching.freeze([], answer_id='answer', message_id='message', kind='conversation', scope_id='scope')
    frozen['protocol'] = 'stepwise-v1'
    frozen.pop('requested_mode'); frozen.pop('help_kind')
    frozen['result'] = {'after': teaching.checkpoint(), 'effective_mode': 'stepwise',
        'mode_request': None, 'attempt': None, 'at': 'legacy'}
    record = teaching.public({'teaching': frozen}, 'complete')
    assert record['status'] == 'applied' and record['current'] == teaching.checkpoint()
    assert record['attempt'] is None and record['guidance'] is None
