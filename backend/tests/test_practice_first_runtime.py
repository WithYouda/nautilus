"""Practice-first keeps one real question, source-linked feedback and explicit next."""
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
from app.question_discussion import QuestionDiscussionService
from app.purge_storage import register_backup, storage_lock
from app.teaching_capability import check as check_capability
from test_ai_conversations import FAKE_API_KEY, authorize, configure_provider, make_client, read_sse
from test_conversation_branches import branch
from test_feynman_runtime import formal_counts
from test_learning_verifications import IDENTITY
from test_preferences import service as preference_service
from test_teaching_output_runtime import (
    StructuredTeachingProvider, checked, defaults, frozen_json, proposal, send, two_rounds,
)
from test_teaching_practice import state
from test_teaching_runtime import chat_turn, new_chat, saved
from test_verification_review import attempt as verification_attempt

QUESTION = '🍊 三个箱子都为空。代码却直接取第一个箱子的第一件物品，会发生什么？请说明依据。'
ANSWER = '🍎 每个箱子都没有物品，取第一件会越界，所以要先检查是否为空。'
FEEDBACK = '🍐 你指出了越界的原因；再补充空箱时应该返回什么。'
NEXT_QUESTION = '🍇 一个箱子有一件物品，另外两个为空。怎样安全地找到第一件物品？'


def reply(provider, body, **changes):
    provider.next = {'body': body, 'proposal': proposal(**changes)}


def ask(provider, question=QUESTION):
    reply(provider, question, practice={'question': question, 'feedback': None})


def feedback(provider, quote=ANSWER, body=FEEDBACK):
    reply(provider, body, attempt={'quote': quote, 'needs_help': False},
          practice={'question': None, 'feedback': body})


def ready(client, provider):
    authorize(client)
    profile = configure_provider(client)
    checked(client, profile)
    defaults(client, 'practice_first')
    return new_chat(client)


def test_setting_is_private_persistent_and_legacy_put_preserves_practice_first(tmp_path):
    preferences, store, search = preference_service(tmp_path)
    legacy = {'conflict_policy': 'materials', 'search': {'mode': 'off'}}
    store.set('learning-preferences:owner-a', json.dumps(legacy))
    assert preferences.get('owner-a')['teaching_mode'] == 'stepwise'
    configured = preferences.save('owner-a', {**legacy, 'teaching_mode': 'practice_first'})
    assert preferences.get('owner-b')['teaching_mode'] == 'stepwise'
    assert type(preferences)(store, search).get('owner-a') == configured
    omitted = preferences.save('owner-a', {'conflict_policy': 'balanced', 'search': {'mode': 'off'}})
    assert omitted['teaching_mode'] == 'practice_first'
    with make_client(tmp_path / 'route', StructuredTeachingProvider()) as client:
        authorize(client)
        defaults(client, 'practice_first')
        baseline = client.get('/api/preferences').json()
        assert client.put('/api/preferences', json={**baseline, 'teaching_mode': 'next_question'}).status_code == 422
        assert client.get('/api/preferences').json() == baseline


def test_first_question_exact_unicode_feedback_waits_then_explicit_next_or_skip(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client, provider)
        before = formal_counts(client.app.state.learning.database)
        reply(provider, '你想先练习哪个主题？')
        clarified = chat_turn(client, cid, '我想学习')
        assert state(clarified)['mode'] == 'practice_first' and state(clarified)['step'] is None
        assert clarified['teaching']['exercise_question'] is None
        question = '🍊 <think>这是题面标签</think>\n' + QUESTION + '\n条件：' + '每次检查须说明箱号及空箱的处理依据。' * 12
        ask(provider, question)
        first, frames, _ = send(client, cid, '练习空输入')
        exercise = state(first)['exercise']
        assert first['teaching']['exercise_question'] == exercise
        assert exercise['id'] == first['id'] == exercise['question']['answer_id']
        assert first['content'][exercise['question']['start']:exercise['question']['end']] == question
        assert state(first)['step']['text'] == question[:240]
        assert first['content'][state(first)['step']['start']:state(first)['step']['end']] == question[:240]
        assert exercise['phase'] == 'awaiting_attempt' and exercise['last_observation_id'] is None
        assert first['teaching']['attempt'] is None and first['teaching']['practice_question'] is None
        assert frames[-1][1]['content'] == question and frames[-1][1]['reasoning_content'] == ''
        quote = ANSWER + ' <think>这也是我的原话</think>'
        body = '🍐 <think>反馈标签</think>\n' + FEEDBACK
        feedback(provider, quote, body)
        observed = chat_turn(client, cid, '我的答案：' + quote)
        record = observed['teaching']['exercise_observation']
        user = next(item for item in client.get(f'/api/ai/conversations/{cid}').json()['messages']
                    if item['id'] == record['message_id'])
        assert user['content'][record['start']:record['end']] == quote
        assert observed['content'][record['feedback_start']:record['feedback_end']] == body
        assert record['question_id'] == first['id'] and record['answer_id'] == observed['id']
        assert record['eligible'] is True and record['needs_help'] is False
        assert state(observed)['step'] == state(first)['step']
        assert state(observed)['exercise']['phase'] == 'feedback_available'
        assert state(observed)['exercise']['last_observation_id'] == observed['id']
        assert observed['teaching']['exercise_question'] is None
        assert observed['teaching']['practice_observation'] is None
        assert observed['teaching']['retelling_observation'] is None
        reply(provider, '可以继续补充你的处理办法。')
        waiting = chat_turn(client, cid, '懂了')
        assert state(waiting)['exercise'] == state(observed)['exercise']
        assert waiting['teaching']['attempt'] is None and waiting['teaching']['exercise_observation'] is None
        ask(provider, NEXT_QUESTION)
        next_answer = chat_turn(client, cid, '下一题', teaching_action='next_question')
        assert state(next_answer)['exercise']['id'] == next_answer['id'] != first['id']
        assert state(next_answer)['exercise']['phase'] == 'awaiting_attempt'
        assert next_answer['teaching']['attempt'] is None
        skipped = chat_turn(client, cid, '这道先跳过，下一题', teaching_action='next_question')
        assert state(skipped)['exercise']['id'] == skipped['id'] != next_answer['id']
        assert skipped['teaching']['exercise_observation'] is None
        assert formal_counts(client.app.state.learning.database) == before


def test_invalid_auto_question_step_action_attempt_and_bad_quotes_keep_original_state(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client, provider)
        ask(provider)
        first = chat_turn(client, cid, '练习空箱')
        cases = [
            ('我答完了', NEXT_QUESTION, {'practice': {'question': NEXT_QUESTION, 'feedback': None}}, {},
             'exercise_question_not_allowed'),
            (ANSWER, FEEDBACK + '\n' + NEXT_QUESTION,
             {'step': NEXT_QUESTION, 'attempt': {'quote': ANSWER, 'needs_help': False},
              'practice': {'question': None, 'feedback': FEEDBACK}}, {}, 'exercise_step_changed'),
            ('下一题', NEXT_QUESTION,
             {'attempt': {'quote': '下一题', 'needs_help': False},
              'practice': {'question': NEXT_QUESTION, 'feedback': None}},
             {'teaching_action': 'next_question'}, 'action_is_not_attempt'),
            (ANSWER, FEEDBACK, {'attempt': {'quote': '不在本轮用户原文中', 'needs_help': False},
                               'practice': {'question': None, 'feedback': FEEDBACK}}, {}, 'quote_mismatch'),
            (ANSWER, FEEDBACK, {'attempt': {'quote': ANSWER, 'needs_help': False},
                               'practice': {'question': None, 'feedback': '不在本轮反馈中'}}, {}, 'quote_mismatch'),
            ('懂了', FEEDBACK, {'practice': {'question': None, 'feedback': FEEDBACK}}, {}, 'exercise_without_attempt'),
        ]
        for text, body, changes, extra, reason in cases:
            reply(provider, body, **changes)
            invalid = chat_turn(client, cid, text, **extra)
            assert invalid['content'] == body
            assert invalid['teaching']['status'] == 'not_updated'
            assert state(invalid) == state(first)
            assert invalid['teaching']['exercise_question'] is None
            assert invalid['teaching']['exercise_observation'] is None
            assert saved(client, invalid['id'])['teaching']['not_applied_reason'] == reason


def test_help_temporary_answer_and_explicit_base_choices_preserve_or_leave_question(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client, provider)
        ask(provider)
        first = chat_turn(client, cid, '练习空箱')
        for kind in ('hint', 'example', 'try_first', 'explain_step'):
            reply(provider, '按你的请求处理当前题。')
            helped = chat_turn(client, cid, '帮助当前题', help_request=kind)
            assert state(helped)['exercise'] == state(first)['exercise']
            assert helped['teaching']['attempt'] is None and helped['teaching']['exercise_observation'] is None
            assert provider.calls[-1][1]['exercise_context']['question'] == QUESTION
        for mode in ('direct_answer', 'full_explanation'):
            text = '这次直接给答案' if mode == 'direct_answer' else '这次完整讲解'
            reply(provider, '空箱没有第一件物品，所以先检查。', mode={
                'value': mode, 'scope': 'turn', 'quote': text, 'persistence_quote': None})
            temporary = chat_turn(client, cid, text)
            assert temporary['teaching']['effective_mode'] == mode
            assert state(temporary)['mode'] == 'practice_first'
            assert state(temporary)['exercise'] == state(first)['exercise']
        reply(provider, '逐步解释当前问题。')
        local = chat_turn(client, cid, '当前路径改为分步', teaching_mode='stepwise')
        assert state(local)['mode'] == 'stepwise' and state(local)['mode_source'] == 'conversation'
        assert 'exercise' not in state(local)
        following = chat_turn(client, cid, '继续解释')
        assert state(following)['mode'] == 'stepwise' and 'exercise' not in state(following)
        ask(provider, NEXT_QUESTION)
        restored = chat_turn(client, cid, '恢复个人默认', teaching_mode='default')
        assert state(restored)['mode'] == 'practice_first' and state(restored)['mode_source'] == 'default'
        assert state(restored)['exercise']['id'] == restored['id']
        assert client.get('/api/preferences').json()['teaching_mode'] == 'practice_first'


def test_acceptance_replay_and_regeneration_freeze_default_action_and_new_question_ids(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client, provider)
        ask(provider)
        payload = {'content': '练习空箱', 'client_message_id': 'frozen-first'}
        endpoint = f'/api/ai/conversations/{cid}/messages'
        accepted = client.post(endpoint, json=payload)
        assert accepted.status_code == 202
        defaults(client, 'socratic')
        read_sse(client, accepted.json()['run']['id'])
        first_id = accepted.json()['run']['response_message_id']
        first = next(item for item in client.get(f'/api/ai/conversations/{cid}').json()['messages']
                     if item['id'] == first_id)
        frozen = copy.deepcopy(saved(client, first_id)['teaching'])
        assert state(first)['mode'] == 'practice_first' and frozen['default_mode'] == 'practice_first'
        calls = len(provider.calls)
        replayed = client.post(endpoint, json=payload)
        assert replayed.status_code == 202 and replayed.json()['created'] is False
        assert saved(client, first_id)['teaching'] == frozen and len(provider.calls) == calls
        regenerated = chat_turn(client, cid, payload['content'], regenerate_message_id=first_id)
        assert regenerated['teaching']['default_mode'] == 'practice_first'
        assert state(regenerated)['exercise']['id'] == regenerated['id'] != first_id
        assert saved(client, regenerated['id'])['teaching']['token'] != frozen['token']
        defaults(client, 'practice_first')
        ask(provider, NEXT_QUESTION)
        next_answer, _, next_payload = send(client, cid, '下一题', teaching_action='next_question')
        next_frozen = copy.deepcopy(saved(client, next_answer['id'])['teaching'])
        calls = len(provider.calls)
        defaults(client, 'stepwise')
        assert client.post(endpoint, json=next_payload).json()['created'] is False
        assert len(provider.calls) == calls and saved(client, next_answer['id'])['teaching'] == next_frozen
        assert client.post(endpoint, json={**next_payload, 'teaching_action': 'continue'}).status_code == 409
        next_regenerated = chat_turn(client, cid, '下一题', regenerate_message_id=next_answer['id'])
        assert next_regenerated['teaching']['requested_action'] == 'next_question'
        assert state(next_regenerated)['exercise']['id'] == next_regenerated['id'] != next_answer['id']
        assert state(next_regenerated)['mode'] == 'practice_first'


def test_natural_one_turn_question_returns_to_base_and_persistent_request_does_not_change_setting(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        checked(client, configure_provider(client))
        cid = new_chat(client)
        text = '这次练习优先，练习空箱'
        ask(provider)
        provider.next['proposal']['mode'] = {
            'value': 'practice_first', 'scope': 'turn', 'quote': '练习优先', 'persistence_quote': None}
        single = chat_turn(client, cid, text)
        assert single['teaching']['effective_mode'] == 'practice_first'
        assert state(single)['mode'] == 'stepwise' and state(single)['exercise']['id'] == single['id']
        ask(provider, NEXT_QUESTION)
        unavailable_next = chat_turn(client, cid, '下一题', teaching_action='next_question')
        assert unavailable_next['teaching']['status'] == 'not_updated' and state(unavailable_next) == state(single)
        assert saved(client, unavailable_next['id'])['teaching']['not_applied_reason'] == 'exercise_unavailable'
        feedback(provider)
        observed = chat_turn(client, cid, ANSWER)
        assert observed['teaching']['exercise_observation']['question_id'] == single['id']
        assert state(observed)['mode'] == 'stepwise' and 'exercise' not in state(observed)
        persistent_text = '以后都用练习优先，练习空箱'
        ask(provider)
        provider.next['proposal']['mode'] = {
            'value': 'practice_first', 'scope': 'conversation', 'quote': '练习优先',
            'persistence_quote': persistent_text}
        persistent = chat_turn(client, cid, persistent_text)
        assert state(persistent)['mode'] == 'practice_first' and state(persistent)['mode_source'] == 'conversation'
        assert state(persistent)['exercise']['id'] == persistent['id']
        assert client.get('/api/preferences').json()['teaching_mode'] == 'stepwise'


def test_single_retelling_priority_and_continue_restore_exact_original_exercise(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client, provider)
        ask(provider)
        first = chat_turn(client, cid, '练习空箱')
        invitation = '请用自己的话解释你会怎样检查这些空箱。'
        reply(provider, invitation, practice={'question': invitation, 'feedback': None})
        single = chat_turn(client, cid, '用自己的话说说', teaching_action='retell')
        assert state(single)['practice']['kind'] == 'retelling'
        assert state(single)['exercise'] == state(first)['exercise']
        ask(provider, NEXT_QUESTION)
        invalid = chat_turn(client, cid, '下一题', teaching_action='next_question')
        assert invalid['teaching']['status'] == 'not_updated' and state(invalid) == state(single)
        feedback(provider)
        observed = chat_turn(client, cid, ANSWER)
        assert observed['teaching']['practice_observation']['question_id'] == single['id']
        assert observed['teaching']['exercise_observation'] is None
        assert state(observed)['exercise'] == state(first)['exercise']
        reply(provider, '回到原题，继续你的作答。')
        resumed = chat_turn(client, cid, '继续学习', teaching_action='continue')
        assert state(resumed)['practice'] is None
        assert state(resumed)['step'] == state(first)['step']
        assert state(resumed)['exercise'] == state(first)['exercise']
        assert resumed['teaching']['attempt'] is None
        feedback(provider)
        result = chat_turn(client, cid, ANSWER)
        assert provider.calls[-1][1]['exercise_context']['question'] == QUESTION
        assert result['teaching']['exercise_observation']['question_id'] == first['id']


def test_nested_branches_remap_exercise_observation_help_and_preserve_corrections(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client, provider)
        ask(provider)
        first = chat_turn(client, cid, '练习空箱')
        reply(provider, '先想想空箱有没有第一件物品。')
        helped = chat_turn(client, cid, '给个提示', help_request='hint')
        feedback(provider)
        observed = chat_turn(client, cid, ANSWER)
        frozen = copy.deepcopy(saved(client, observed['id'])['teaching'])
        endpoint = f"/api/ai/conversations/{cid}/messages/{observed['id']}/teaching-attempt"
        corrected = client.post(endpoint, json={'expected_revision': 0, 'is_attempt': False,
                                               'request_key': 'ordinary-inquiry'})
        assert corrected.status_code == 200 and corrected.json()['exercise_observation']['eligible'] is False
        assert saved(client, observed['id'])['teaching'] == frozen
        copied = branch(client, cid, observed['id'], 'exercise-branch').json()
        copied = branch(client, copied['conversation']['id'], copied['messages'][-1]['id'], 'exercise-nested').json()
        answers = [item for item in copied['messages'] if item['role'] == 'assistant']
        q, hint, result = answers
        frame = state(result)['exercise']
        assert frame['id'] == frame['question']['answer_id'] == state(result)['step']['id'] == q['id']
        assert frame['last_observation_id'] == result['id']
        record = result['teaching']['exercise_observation']
        assert record['question_id'] == q['id'] and record['answer_id'] == result['id']
        assert record['message_id'] == result['parent_message_id'] and record['eligible'] is False
        assert {item['answer_id'] for item in record['help_context']} == {q['id'], hint['id']}
        assert q['teaching']['exercise_question']['id'] == q['id']
        remapped = saved(client, result['id'])['teaching']
        assert remapped['result']['attempt']['origin'] == frozen['result']['attempt']['origin']
        assert remapped['origin']['answer_id'] == observed['id']
        assert {item['answer_id'] for item in observed['teaching']['exercise_observation']['help_context']} == {
            first['id'], helped['id']}


def test_truncated_and_cancelled_next_question_keep_original_question(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client, provider)
        ask(provider)
        first = chat_turn(client, cid, '练习空箱')
        ask(provider, NEXT_QUESTION)
        provider.next['failure'] = 'truncated'
        partial = chat_turn(client, cid, '下一题', teaching_action='next_question')
        assert partial['content'] == NEXT_QUESTION
        assert state(partial) == state(first) and partial['teaching']['exercise_question'] is None
        assert 'result' not in saved(client, partial['id'])['teaching']

        class Waiting(httpx.AsyncByteStream):
            async def __aiter__(self):
                raw = json.dumps({'reply': NEXT_QUESTION}, ensure_ascii=False)[:-1]
                event = {'choices': [{'delta': {'content': raw}}]}
                yield ('data: ' + json.dumps(event, ensure_ascii=False) + '\n\n').encode()
                await asyncio.Event().wait()

        client.app.state.ai_runs.transport = httpx.MockTransport(lambda _request: httpx.Response(200, stream=Waiting()))
        accepted = client.post(f'/api/ai/conversations/{cid}/messages', json={
            'content': '下一题', 'client_message_id': 'cancel-next', 'teaching_action': 'next_question'})
        assert accepted.status_code == 202
        run = accepted.json()['run']['id']
        for _ in range(100):
            if client.app.state.ai_runs._runs[run].text:
                break
            time.sleep(.01)
        assert client.app.state.ai_runs._runs[run].text == NEXT_QUESTION
        assert client.post(f'/api/ai/runs/{run}/cancel').status_code == 200
        canceled = next(item for item in client.get(f'/api/ai/conversations/{cid}').json()['messages']
                        if item['id'] == accepted.json()['run']['response_message_id'])
        assert canceled['content'] == NEXT_QUESTION and state(canceled) == state(first)
        assert canceled['teaching']['exercise_question'] is None
        assert canceled['help_record']['provided']['partial'] is True


def test_strict_scope_and_managed_purge_drop_exercise_sources_without_reintroducing_text(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client, provider)
        base = f'/api/materials/conversation/{cid}'
        material = client.post(base, json={'title': '合成练习资料', 'content': 'EXERCISE_PRIVATE_SOURCE'}).json()
        scope = {'mode': 'only', 'version_ids': [material['id']]}
        ask(provider, 'EXERCISE_PRIVATE_QUESTION')
        first = chat_turn(client, cid, '开始练习', source_scope=scope)
        feedback(provider, 'EXERCISE_PRIVATE_ANSWER', 'EXERCISE_PRIVATE_FEEDBACK')
        observed = chat_turn(client, cid, 'EXERCISE_PRIVATE_ANSWER', source_scope=scope)
        copied = branch(client, cid, observed['id'], 'exercise-private').json()
        backup = tmp_path / 'exercise-managed.sqlite3'
        with closing(sqlite3.connect(backup)) as target:
            client.app.state.database.connection.backup(target)
        with storage_lock(client.app.state.materials.db.database_path):
            register_backup(client.app.state.materials.db.database_path, backup)
        reply(provider, '请说明新问题的学习主题。')
        other = chat_turn(client, cid, '换到独立资料范围')
        assert state(other)['step'] is None and 'exercise' not in state(other)
        assert provider.calls[-1][1]['exercise_context'] is None
        assert 'EXERCISE_PRIVATE_' not in json.dumps(provider.calls[-1])
        purged = client.post(base + '/' + material['material_id'] + '/purge')
        assert purged.status_code == 200 and purged.json()['purge']['status'] == 'complete'
        for answer in (first, observed, copied['messages'][-1]):
            assert 'teaching' not in saved(client, answer['id'])
        with closing(sqlite3.connect(backup)) as connection:
            snapshots = connection.execute('SELECT config_snapshot_json FROM ai_run').fetchall()
            assert all('EXERCISE_PRIVATE_' not in row[0] and '"teaching"' not in row[0] for row in snapshots)


@pytest.mark.asyncio
async def test_discussion_json_first_feedback_wait_next_and_formal_records_unchanged(tmp_path):
    provider = StructuredTeachingProvider()
    transport = httpx.MockTransport(provider)
    with make_client(tmp_path, provider) as client:
        chats = client.app.state.conversations
        database = client.app.state.learning.database
        for target in (chats.database, database):
            with target.transaction() as connection:
                connection.execute('''INSERT INTO local_identity
                    (id,device_id,display_name,timezone,created_at,updated_at) VALUES (?,?,?,?,?,?)''',
                    (IDENTITY['id'], IDENTITY['device_id'], IDENTITY['display_name'], IDENTITY['timezone'],
                     IDENTITY['created_at'], IDENTITY['created_at']))
        verification, original = await verification_attempt(database)
        profile = chats.save_provider(IDENTITY['id'], display_name='合成练习模型',
            base_url='https://api.example.com/v1', model='gpt-4o', api_key=FAKE_API_KEY)
        checked_result = await check_capability(chats, IDENTITY['id'], profile['id'],
                                                profile['default_model']['id'], transport=transport)
        assert checked_result['support']['plain'] == checked_result['support']['tools'] == 'supported'
        chats.preferences.save(IDENTITY['id'], {'conflict_policy': 'ask', 'search': {'mode': 'off'},
                                               'teaching_mode': 'practice_first'})
        verification.conversations = chats
        verification.transport = transport
        service = QuestionDiscussionService(verification)
        did = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'exercise-discussion')['id']
        before = copy.deepcopy(service.records.detail(IDENTITY, original['id']))
        before_counts = formal_counts(database)

        async def turn(text, **extra):
            return (await service.send(IDENTITY, did, text, str(uuid4()), **extra))['turns'][-1]

        ask(provider)
        first = await turn('练习空箱')
        assert first['status'] == 'succeeded' and first['teaching']['exercise_question'] == state(first)['exercise']
        quote = ANSWER + ' <think>作答原文</think>'
        feedback(provider, quote)
        observed = await turn('我的答案：' + quote)
        record = observed['teaching']['exercise_observation']
        assert record['message_id'] == record['answer_id'] == observed['id']
        assert record['question_id'] == first['id'] and record['eligible'] is True
        assert observed['user_content'][record['start']:record['end']] == quote
        assert observed['assistant_content'][record['feedback_start']:record['feedback_end']] == FEEDBACK
        assert state(observed)['exercise']['phase'] == 'feedback_available'
        assert QuestionDiscussionService(verification).get(IDENTITY, did)['turns'][-1] == observed
        reply(provider, '可以补充空箱时的处理。')
        waiting = await turn('懂了')
        assert state(waiting)['exercise'] == state(observed)['exercise'] and waiting['teaching']['attempt'] is None
        ask(provider, NEXT_QUESTION)
        next_answer = await turn('下一题', teaching_action='next_question')
        assert state(next_answer)['exercise']['id'] == next_answer['id'] != first['id']
        skipped = await turn('跳过，下一题', teaching_action='next_question')
        assert state(skipped)['exercise']['id'] == skipped['id'] != next_answer['id']
        assert skipped['teaching']['attempt'] is None
        after = service.records.detail(IDENTITY, original['id'])
        excluded = {'discussions', 'purge_discussion_count'}
        assert {key: value for key, value in after.items() if key not in excluded} == {
            key: value for key, value in before.items() if key not in excluded}
        assert formal_counts(database) == before_counts
        assert len(provider.calls) == len(provider.history_checks) == 5


@pytest.mark.asyncio
async def test_final_tool_round_offsets_question_and_feedback_without_moving_prior_or_user_sources():
    first = frozen_json(default_mode='practice_first')
    parser = teaching.TeachingStream(first)
    body = await two_rounds(parser, first, QUESTION, QUESTION,
                            proposal(practice={'question': QUESTION, 'feedback': None}))
    outcome = parser.outcome()
    teaching.adopt(first, outcome['teaching_proposal'], body=body, user_text='练习空箱', at='synthetic',
                   reply_start=outcome['teaching_reply_start'])
    start = len(QUESTION) + 2
    for frame in (first['result']['after']['exercise'], first['result']['exercise_question']):
        assert frame['question']['start'] == start and frame['question']['end'] == len(body)
        assert body[frame['question']['start']:frame['question']['end']] == QUESTION
    assert first['result']['after']['step']['start'] == start
    path = [{'id': first['answer_id'], 'teaching': teaching.public({'teaching': first}, 'complete')}]
    follow = teaching.freeze(path, answer_id='feedback-answer', message_id='attempt-user', kind='conversation',
                             scope_id='synthetic-scope', default_mode='practice_first', output={'format': 'json', 'version': 1})
    parser = teaching.TeachingStream(follow)
    user_text = '我的答案：' + ANSWER
    body = await two_rounds(parser, follow, FEEDBACK, FEEDBACK,
        proposal(attempt={'quote': ANSWER, 'needs_help': False}, practice={'question': None, 'feedback': FEEDBACK}))
    outcome = parser.outcome()
    teaching.adopt(follow, outcome['teaching_proposal'], body=body, user_text=user_text, at='synthetic',
                   reply_start=outcome['teaching_reply_start'])
    record = follow['result']['exercise_observation']
    assert record['feedback_start'] == len(FEEDBACK) + 2 and record['feedback_end'] == len(body)
    assert body[record['feedback_start']:record['feedback_end']] == FEEDBACK
    assert record['start'] == len('我的答案：') and user_text[record['start']:record['end']] == ANSWER
    assert follow['result']['after']['exercise']['question'] == first['result']['after']['exercise']['question']
    assert follow['result']['after']['step'] == follow['before']['step']
