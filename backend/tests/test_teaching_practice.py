"""Optional conversational practice is version-local feedback, never evidence."""
import asyncio
import copy
import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import httpx
import pytest

from app import teaching_runtime as teaching
from app.discussion_branches import create_branch as branch_discussion
from app.learning_domain import DomainError
from app.purge_storage import register_backup, storage_lock
from app.question_discussion import QuestionDiscussionService
from test_ai_conversations import authorize, make_client, read_sse
from test_conversation_branches import branch
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY
from test_teaching_runtime import configure_provider, TeachingProvider, chat_turn, new_chat, saved
from test_verification_review import attempt as verification_attempt

QUESTION = '🍊 换成三个空箱，应该怎样判断是否有物品？请说明依据。'
ANSWER = '🍎 我先逐箱检查，三个都为空，所以没有物品。'
FEEDBACK = '🍐 你逐箱核对了条件；还可以说明只要一箱非空就要改变结论。'


class PracticeProvider(TeachingProvider):
    def __call__(self, request):
        original = self.next
        if 'raw' not in self.next:
            self.next = {**self.next, 'raw': json.dumps({
                'step': self.next.get('step'), 'mode': None, 'help': None,
                'attempt': {'quote': self.next['attempt'], 'needs_help': self.next.get('needs_help')}
                    if 'attempt' in self.next else None,
                'practice': self.next.get('practice')}, ensure_ascii=False)}
        try:
            return super().__call__(request)
        finally:
            self.next = original


def question(provider, text=QUESTION):
    provider.next = {'body': '试一道新题：\n' + text, 'practice': {'question': text, 'feedback': None}}


def feedback(provider):
    provider.next = {'body': FEEDBACK, 'attempt': ANSWER, 'needs_help': False,
                     'practice': {'question': None, 'feedback': FEEDBACK}}


def state(answer):
    return answer['teaching']['current']


def test_chat_practice_feedback_correction_replay_and_return(tmp_path):
    provider = PracticeProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        original = chat_turn(client, cid, '解释边界', teaching_mode='socratic')
        question(provider)
        q = chat_turn(client, cid, '换一道试试。', teaching_action='practice')
        frame = q['teaching']['practice_question']
        assert frame == state(q)['practice']
        assert frame['basis_step'] == state(original)['step']
        assert q['content'][frame['question']['start']:frame['question']['end']] == QUESTION
        assert q['teaching']['attempt'] is None
        feedback(provider)
        result = chat_turn(client, cid, ANSWER)
        assert provider.calls[-1][1]['practice_context']['question'] == QUESTION
        obs = result['teaching']['practice_observation']
        assert result['content'][obs['feedback_start']:obs['feedback_end']] == FEEDBACK
        assert obs['question_id'] == q['id'] and obs['eligible'] is True and obs['needs_help'] is False
        assert {item['answer_id'] for item in obs['help_context']} == {original['id'], q['id']}
        assert state(result)['practice']['phase'] == 'feedback_available'
        frozen = copy.deepcopy(saved(client, result['id'])['teaching'])
        endpoint = f"/api/ai/conversations/{cid}/messages/{result['id']}/teaching-attempt"
        correction = client.post(endpoint, json={'expected_revision': 0, 'is_attempt': False, 'request_key': 'correct'})
        assert correction.status_code == 200
        assert correction.json()['practice_observation']['eligible'] is False
        assert saved(client, result['id'])['teaching'] == frozen
        # A later display receipt must not rewrite the help available at submission.
        assert client.post(f"/api/ai/conversations/{cid}/messages/{q['id']}/help-display",
                           json={'characters': len(q['content'])}).status_code == 200
        assert saved(client, result['id'])['teaching']['result']['practice_observation']['help_context'] == obs['help_context']
        question(provider, '换成两个有物品的箱子，又该怎样判断？')
        again = chat_turn(client, cid, '换一道试试。', teaching_action='practice')
        assert state(again)['practice']['basis_step'] == state(original)['step']
        assert state(again)['practice']['id'] != frame['id']
        provider.next = {'body': '回到最初的输入边界继续。'}
        resumed = chat_turn(client, cid, '这道先不练了，继续学习。', teaching_action='continue')
        assert state(resumed)['practice'] is None and state(resumed)['step'] == state(original)['step']
        assert state(resumed)['guidance']['level'] == 0
        assert resumed['teaching']['attempt'] is None
        # Regeneration inherits the original explicit action, not the latest state.
        question(provider)
        regenerated = chat_turn(client, cid, '换一道试试。', regenerate_message_id=q['id'])
        assert regenerated['teaching']['requested_action'] == 'practice'
        assert state(regenerated)['practice']['id'] == regenerated['id']
        assert state(regenerated)['practice']['basis_step'] == state(original)['step']
        key = str(uuid4())
        payload = {'content': '换一道试试。', 'client_message_id': key, 'teaching_action': 'practice'}
        accepted = client.post(f'/api/ai/conversations/{cid}/messages', json=payload)
        assert accepted.status_code == 202
        read_sse(client, accepted.json()['run']['id'])
        replay = client.post(f'/api/ai/conversations/{cid}/messages', json=payload)
        assert replay.json()['run']['id'] == accepted.json()['run']['id']
        assert client.post(f'/api/ai/conversations/{cid}/messages', json={**payload, 'teaching_action': 'continue'}).status_code == 409


def test_nested_branches_remap_all_practice_references_and_edit_is_separate(tmp_path):
    provider = PracticeProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        original = chat_turn(client, cid, '开始', teaching_mode='socratic')
        question(provider)
        q = chat_turn(client, cid, '换一道试试。', teaching_action='practice')
        feedback(provider)
        result = chat_turn(client, cid, ANSWER)
        copied = branch(client, cid, result['id']).json()
        copied = branch(client, copied['conversation']['id'], copied['messages'][-1]['id']).json()
        messages = copied['messages']
        answers = [item for item in messages if item['role'] == 'assistant']
        point, copied_question, last = answers
        frame = state(last)['practice']
        assert frame['id'] == copied_question['id'] == frame['question']['answer_id']
        assert frame['basis_step']['id'] == point['id']
        assert frame['last_observation_id'] == last['id']
        obs = last['teaching']['practice_observation']
        assert obs['message_id'] == messages[-2]['id'] and obs['answer_id'] == last['id']
        assert {item['answer_id'] for item in obs['help_context']} == {point['id'], copied_question['id']}
        assert saved(client, last['id'])['teaching']['origin']['answer_id'] == result['id']
        provider.next = {'body': '改成普通问题后仍讨论原小点。'}
        edited = chat_turn(client, cid, '我想问原来的边界', edit_message_id=q['parent_message_id'])
        assert not state(edited).get('practice') and state(edited)['step']['id'] == original['id']
        assert state(client.get(f'/api/ai/conversations/{cid}').json()['messages'][5])['practice']['id'] == q['id']


def test_practice_counts_do_not_replace_original_point_and_corrected_return_is_recounted(tmp_path):
    provider = PracticeProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        chat_turn(client, cid, '开始', teaching_mode='socratic')
        provider.next = {'body': '还可以检查边界。', 'attempt': ANSWER, 'needs_help': True}
        original_attempt = chat_turn(client, cid, ANSWER)
        question(provider)
        q = chat_turn(client, cid, '换一道试试。', teaching_action='practice')
        assert state(q)['guidance']['stuck_count'] == 0
        assert state(q)['practice']['return_guidance']['stuck_count'] == 1
        feedback(provider)
        provider.next['needs_help'] = True
        chat_turn(client, cid, ANSWER)
        second = chat_turn(client, cid, ANSWER)
        assert state(second)['guidance']['level'] == 1
        endpoint = f"/api/ai/conversations/{cid}/messages/{original_attempt['id']}/teaching-attempt"
        assert client.post(endpoint, json={'expected_revision': 0, 'is_attempt': False, 'request_key': 'original-dismiss'}).status_code == 200
        provider.next = {'body': '回到原小点。'}
        resumed = chat_turn(client, cid, '继续学习。', teaching_action='continue')
        assert state(resumed)['guidance']['level'] == 0
        assert state(resumed)['guidance']['stuck_count'] == 0
        assert state(resumed)['step'] == state(original_attempt)['step']


@pytest.mark.parametrize('natural', [False, True])
def test_changing_base_method_during_practice_resets_original_point_ladder(tmp_path, natural):
    provider = PracticeProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        chat_turn(client, cid, '开始', teaching_mode='socratic')
        provider.next = {'body': '给一个概念提示。'}
        hint = chat_turn(client, cid, '给个提示', help_request='hint')
        assert state(hint)['guidance']['level'] == 1
        question(provider)
        chat_turn(client, cid, '换一道试试。', teaching_action='practice')
        for mode in ['stepwise', 'socratic']:
            provider.next = {'body': '继续当前练习。'}
            text = '以后都用' + ('分步讲解' if mode == 'stepwise' else '提问引导')
            if natural:
                provider.next['raw'] = json.dumps({'step': None, 'attempt': None,
                    'mode': {'value': mode, 'scope': 'conversation', 'quote': text, 'persistence_quote': text}})
            chat_turn(client, cid, text, **({} if natural else {'teaching_mode': mode}))
        provider.next = {'body': '回到原小点。'}
        resumed = chat_turn(client, cid, '继续学习。', teaching_action='continue')
        assert state(resumed)['guidance']['level'] == 0
        assert state(resumed)['guidance']['stuck_count'] == 0
        assert state(resumed)['step'] == state(hint)['step']


@pytest.mark.parametrize('case', ['no_step', 'unsolicited', 'bad_question', 'action_attempt',
                                  'missing_feedback', 'bad_feedback', 'new_step', 'not_an_attempt'])
def test_invalid_proposals_cannot_create_or_advance_practice(case):
    point = {'id': 'point', 'source_answer_id': 'point', 'text': '小点', 'start': 0, 'end': 2}
    frozen = teaching.freeze([], answer_id='q', message_id='u', kind='conversation', scope_id='c', action='practice')
    frozen['before']['step'] = point
    proposal = {'step': None, 'attempt': None, 'mode': None, 'practice': {'question': QUESTION, 'feedback': None}}
    if case == 'no_step':
        frozen['before']['step'] = None
    elif case == 'unsolicited':
        frozen['action'] = None
    elif case == 'bad_question':
        proposal['practice']['question'] = '没有实际输出的题目'
    elif case == 'action_attempt':
        proposal['attempt'] = {'quote': ANSWER}
    else:
        result = teaching.complete(frozen, proposal, body=QUESTION, user_text='换题', at='now')
        frozen['before'] = result['after']
        frozen['action'] = None
        proposal = {'step': None, 'attempt': {'quote': ANSWER}, 'mode': None,
                    'practice': {'question': None, 'feedback': FEEDBACK}}
        if case == 'missing_feedback':
            proposal['practice'] = None
        elif case == 'bad_feedback':
            proposal['practice']['feedback'] = '没有实际输出的反馈'
        elif case == 'new_step':
            proposal['step'] = FEEDBACK
        else:
            proposal['attempt'] = None
    before = copy.deepcopy(frozen)
    result, reason = teaching.evaluate(frozen, proposal, body=FEEDBACK if case in {
        'missing_feedback', 'bad_feedback', 'new_step', 'not_an_attempt'} else QUESTION, user_text=ANSWER, at='now')
    assert result is None and reason
    assert frozen == before


def test_partial_and_scope_change_leave_no_adopted_practice_and_purge_covers_backup(tmp_path):
    provider = PracticeProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        base = f'/api/materials/conversation/{cid}'
        material = client.post(base, json={'title': '合成资料', 'content': 'C2_PRIVATE_SOURCE'}).json()
        scope = {'mode': 'only', 'version_ids': [material['id']]}
        original = chat_turn(client, cid, '开始', source_scope=scope)
        question(provider, 'C2_PRIVATE_QUESTION：空箱内有物品吗？')
        provider.next['finish'] = 'length'
        partial = chat_turn(client, cid, '换一道试试。', teaching_action='practice', source_scope=scope)
        assert partial['teaching']['practice_question'] is None
        assert state(partial) == state(original)
        question(provider, 'C2_PRIVATE_QUESTION：空箱内有物品吗？')
        q = chat_turn(client, cid, '换一道试试。', teaching_action='practice', source_scope=scope)
        feedback(provider)
        result = chat_turn(client, cid, ANSWER, source_scope=scope)
        copied = branch(client, cid, result['id']).json()
        backup = tmp_path / 'practice-managed.sqlite3'
        with closing(sqlite3.connect(backup)) as target:
            client.app.state.database.connection.backup(target)
        with storage_lock(client.app.state.materials.db.database_path):
            register_backup(client.app.state.materials.db.database_path, backup)
        provider.next = {'body': '一个独立的问题。'}
        independent = chat_turn(client, cid, '独立讨论')
        assert state(independent) == teaching.checkpoint()
        assert provider.calls[-1][1]['practice_context'] is None
        assert 'C2_PRIVATE_' not in json.dumps(provider.calls[-1])
        purged = client.post(base + '/' + material['material_id'] + '/purge')
        assert purged.status_code == 200 and purged.json()['purge']['status'] == 'complete'
        for message in [q, result, copied['messages'][-1]]:
            assert 'teaching' not in saved(client, message['id'])
        with closing(sqlite3.connect(backup)) as connection:
            snapshots = connection.execute('SELECT config_snapshot_json FROM ai_run').fetchall()
            assert all('C2_PRIVATE_' not in row[0] and '"teaching"' not in row[0] for row in snapshots)


@pytest.mark.asyncio
async def test_discussion_practice_keeps_formal_verification_unchanged_and_clears(learning_database):
    verification, original = await verification_attempt(learning_database)
    service = QuestionDiscussionService(verification)
    did = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'practice')['id']
    before = copy.deepcopy(service.records.detail(IDENTITY, original['id']))
    provider = PracticeProvider()
    verification.transport = httpx.MockTransport(provider)
    async def send(text, **extra):
        return (await service.send(IDENTITY, did, text, str(uuid4()), **extra))['turns'][-1]
    point = await send('解释小点', teaching_mode='socratic')
    question(provider)
    q = await send('换一道试试。', teaching_action='practice')
    feedback(provider)
    result = await send(ANSWER)
    assert provider.calls[-1][1]['practice_context']['question'] == QUESTION
    obs = result['teaching']['practice_observation']
    assert obs['message_id'] == result['id'] == obs['answer_id']
    assert result['user_content'][obs['start']:obs['end']] == ANSWER
    assert result['assistant_content'][obs['feedback_start']:obs['feedback_end']] == FEEDBACK
    corrected = service.correct_teaching_attempt(IDENTITY, did, result['id'], expected_revision=0,
        is_attempt=False, request_key='dismiss')
    assert corrected['practice_observation']['eligible'] is False
    copied = branch_discussion(service, IDENTITY, did, result['id'], 'practice-branch')
    copied_q, copied_result = copied['turns'][-2:]
    assert state(copied_result)['practice']['question']['answer_id'] == copied_q['id']
    assert copied_result['teaching']['practice_observation']['message_id'] == copied_result['id']
    question(provider)
    regenerated = await send('换一道试试。', regenerate_turn_id=q['id'])
    assert regenerated['teaching']['requested_action'] == 'practice'
    assert state(regenerated)['practice']['basis_step'] == state(point)['step']
    provider.next = {'body': '继续原小点。'}
    resumed = await send('这道先不练了，继续学习。', teaching_action='continue')
    assert state(resumed)['practice'] is None and state(resumed)['step'] == state(point)['step']
    after = service.records.detail(IDENTITY, original['id'])
    excluded = {'discussions', 'purge_discussion_count'}
    assert {k: v for k, v in before.items() if k not in excluded} == {k: v for k, v in after.items() if k not in excluded}
    verification.purge(IDENTITY, original['id'])
    for item in [q, result, copied_q, copied_result]:
        assert learning_database.fetchone('SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?', (item['id'],))[0] == '{}'


@pytest.mark.asyncio
async def test_discussion_action_retry_and_cancelled_skip_restore_active_question(learning_database):
    verification, original = await verification_attempt(learning_database)
    service = QuestionDiscussionService(verification)
    did = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'practice-cancel')['id']
    provider = PracticeProvider()
    verification.transport = httpx.MockTransport(provider)
    await service.send(IDENTITY, did, '开始', 'point')
    question(provider)
    q = (await service.send(IDENTITY, did, '换一道试试。', 'question', teaching_action='practice'))['turns'][-1]
    assert service.start(IDENTITY, did, '换一道试试。', 'question', teaching_action='practice')['turns'][-1]['id'] == q['id']
    with pytest.raises(DomainError):
        service.start(IDENTITY, did, '换一道试试。', 'question', teaching_action='continue')
    delivered = asyncio.Event()
    class Partial(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial response"}}]}\n\n'
            delivered.set()
            await asyncio.Event().wait()
    def partial(request):
        if not json.loads(request.content).get('stream'):
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"history_query":null}'}}]})
        return httpx.Response(200, stream=Partial())
    verification.transport = httpx.MockTransport(partial)
    active = service.start(IDENTITY, did, '继续学习。', 'skip', teaching_action='continue')['turns'][-1]
    await asyncio.wait_for(delivered.wait(), 3)
    await service.cancel(IDENTITY, did, active['id'])
    await asyncio.gather(*list(service.tasks.values()), return_exceptions=True)
    canceled = service.get(IDENTITY, did)['turns'][-1]
    assert canceled['reason'] == 'cancelled'
    assert state(canceled) == state(q)
    assert canceled['teaching']['practice_observation'] is None
    assert canceled['help_record']['provided']['partial'] is True
