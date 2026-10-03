"""Project work keeps source-linked versions and waits for an explicit next step."""
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
from app.purge_storage import register_backup, storage_lock
from app.question_discussion import QuestionDiscussionService
from app.teaching_capability import check as check_capability
from test_ai_conversations import FAKE_API_KEY, authorize, configure_provider, make_client
from test_conversation_branches import branch
from test_feynman_runtime import formal_counts
from test_learning_verifications import IDENTITY
from test_preferences import service as preference_service
from test_teaching_output_runtime import StructuredTeachingProvider, checked, defaults, send, support_path, two_rounds
from test_teaching_practice import state
from test_teaching_runtime import chat_turn, new_chat, saved
from test_verification_review import attempt as verification_attempt

GOAL = '🍊 做一个读取空箱数据并给出物品总数的小程序。'
INSTRUCTION = '🍇 当前一步：写出 count_items 的函数签名，并说明空输入时应返回什么。'
WORK = '🍎 def count_items(boxes):\n    return sum(len(box) for box in boxes)\n运行结果：count_items([]) == 0'
FEEDBACK = '🍐 你给出了函数和空输入结果；这份代码会累计各箱的物品数量。'
NEXT = '🍒 下一步：贴出一组非空输入及其实际运行结果，检查总数。'
REVISION = '🍋 修改后的当前要求：保持函数签名，空输入时返回一段提示文字。'
CHANGE = '把当前要求改成空输入时返回提示文字'


def proposal(**changes):
    return dict(step=None, attempt=None, mode=None, help=None, practice=None, project=None) | changes


def project(**changes):
    return dict(goal=None, instruction=None, feedback=None, change_quote=None) | changes


def reply(provider, body, **changes):
    provider.next = {'body': body, 'proposal': proposal(**changes)}


def start_project(provider, goal=GOAL, instruction=INSTRUCTION):
    reply(provider, goal + '\n\n' + instruction, project=project(goal=goal, instruction=instruction))


def observe(provider, quote=WORK, body=FEEDBACK):
    reply(provider, body, attempt={'quote': quote, 'needs_help': False}, project=project(feedback=body))


def advance(provider, instruction=NEXT):
    reply(provider, instruction, project=project(instruction=instruction))


def revise(provider, change=CHANGE, instruction=REVISION, goal=None):
    body = (goal + '\n\n' if goal else '') + instruction
    reply(provider, body, project=project(goal=goal, instruction=instruction, change_quote=change))


def ready(client):
    authorize(client)
    checked(client, configure_provider(client))
    defaults(client, 'project')
    return new_chat(client)


def messages(client, cid):
    return client.get(f'/api/ai/conversations/{cid}').json()['messages']


def extract(answer, reference, *, body='content'):
    assert reference['answer_id'] == answer['id']
    return answer[body][reference['start']:reference['end']]


def unchanged(answer, original):
    assert answer['teaching']['status'] == 'not_updated'
    assert state(answer) == state(original)
    assert answer['teaching']['project_step'] is None
    assert answer['teaching']['project_observation'] is None


def test_project_setting_is_private_persistent_and_legacy_save_preserves_it(tmp_path):
    preferences, store, search = preference_service(tmp_path)
    legacy = {'conflict_policy': 'materials', 'search': {'mode': 'off'}}
    store.set('learning-preferences:owner-a', json.dumps(legacy))
    assert preferences.get('owner-a')['teaching_mode'] == 'stepwise'
    configured = preferences.save('owner-a', legacy | {'teaching_mode': 'project'})
    assert preferences.get('owner-b')['teaching_mode'] == 'stepwise'
    assert type(preferences)(store, search).get('owner-a') == configured
    assert preferences.save('owner-a', legacy)['teaching_mode'] == 'project'
    with make_client(tmp_path / 'route', StructuredTeachingProvider()) as client:
        authorize(client)
        defaults(client, 'project')
        baseline = client.get('/api/preferences').json()
        assert client.put('/api/preferences', json=baseline | {'teaching_mode': 'next_step'}).status_code == 422
        assert client.get('/api/preferences').json() == baseline


def test_chat_real_work_exact_sources_waits_then_explicit_next_without_formal_completion(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client)
        before = formal_counts(client.app.state.learning.database)
        reply(provider, '你想做一个怎样的小作品？')
        clarified = chat_turn(client, cid, '我想做点东西')
        assert state(clarified)['mode'] == 'project' and state(clarified)['step'] is None
        assert clarified['teaching']['project_step'] is None
        instruction = INSTRUCTION + '\n条件：' + '逐项说明输入结构、空输入处理和预期结果。' * 15
        goal = GOAL + ' <think>作品文字</think>'
        start_project(provider, goal, instruction)
        first, frames, _ = send(client, cid, '做一个箱子计数程序')
        frame = state(first)['project']
        assert first['teaching']['project_step'] == frame
        assert frame['id'] == first['id']
        assert extract(first, frame['goal']) == goal
        assert extract(first, frame['step']['instruction']) == instruction
        assert frame['step'] == {
            'id': first['id'], 'instruction': frame['step']['instruction'], 'change': 'start',
            'previous_step_id': None, 'phase': 'awaiting_work', 'last_observation_id': None, 'change_request': None}
        assert state(first)['step']['text'] == instruction[:240]
        assert first['teaching']['attempt'] is None and first['teaching']['practice_question'] is None
        assert frames[-1][1]['content'] == first['content'] and frames[-1][1]['reasoning_content'] == ''
        work = WORK + '\n<think>代码中的原文标签</think>'
        feedback = FEEDBACK + '\n<think>反馈文字标签</think>'
        observe(provider, work, feedback)
        observed = chat_turn(client, cid, '这是我的代码和结果：\n' + work)
        record = observed['teaching']['project_observation']
        user = next(item for item in messages(client, cid) if item['id'] == record['message_id'])
        assert user['content'][record['start']:record['end']] == work
        assert observed['content'][record['feedback_start']:record['feedback_end']] == feedback
        assert record['project_id'] == record['question_id'] == first['id']
        assert record['answer_id'] == observed['id'] and record['eligible'] is True and record['needs_help'] is False
        assert state(observed)['step'] == state(first)['step']
        assert state(observed)['project']['step']['phase'] == 'feedback_available'
        assert state(observed)['project']['step']['last_observation_id'] == observed['id']
        assert observed['teaching']['project_step'] is None
        assert observed['teaching']['practice_observation'] is None
        assert observed['teaching']['exercise_observation'] is None
        assert observed['teaching']['retelling_observation'] is None
        reply(provider, '可以继续补充你的代码或实际结果。')
        for text in ('懂了', '做完了', '为什么使用 sum？'):
            waiting = chat_turn(client, cid, text)
            assert state(waiting)['project'] == state(observed)['project']
            assert waiting['teaching']['attempt'] is None and waiting['teaching']['project_observation'] is None
        assert provider.calls[-1][1]['project_context'] == {'goal': goal, 'instruction': instruction}
        advance(provider)
        next_answer = chat_turn(client, cid, '下一步', teaching_action='next_step')
        frame = state(next_answer)['project']
        assert frame['id'] == first['id'] and frame['goal'] == state(first)['project']['goal']
        assert frame['step']['id'] == next_answer['id'] and frame['step']['previous_step_id'] == first['id']
        assert frame['step']['change'] == 'next' and frame['step']['phase'] == 'awaiting_work'
        assert next_answer['teaching']['attempt'] is None
        skipped = chat_turn(client, cid, '这一步先跳过，下一步', teaching_action='next_step')
        assert state(skipped)['project']['step']['previous_step_id'] == next_answer['id']
        assert state(skipped)['project']['step']['id'] == skipped['id']
        assert formal_counts(client.app.state.learning.database) == before
        assert next(item for item in messages(client, cid) if item['id'] == observed['id']) == observed


def test_revision_records_request_and_new_sources_without_rewriting_previous_work(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client)
        start_project(provider)
        first = chat_turn(client, cid, '写一个箱子计数程序')
        observe(provider)
        observed = chat_turn(client, cid, WORK)
        prior = copy.deepcopy(saved(client, observed['id'])['teaching'])
        new_goal = '🍊 做一个对空输入提供文字提示的箱子计数程序。'
        revise(provider, goal=new_goal)
        revised = chat_turn(client, cid, '我想修改一下：' + CHANGE)
        frame = state(revised)['project']
        assert frame['id'] == first['id']
        assert extract(revised, frame['goal']) == new_goal
        assert extract(revised, frame['step']['instruction']) == REVISION
        assert frame['step']['change'] == 'revision' and frame['step']['previous_step_id'] == first['id']
        assert frame['step']['phase'] == 'awaiting_work' and frame['step']['last_observation_id'] is None
        request = frame['step']['change_request']
        assert request['message_id'] == revised['parent_message_id']
        user = next(item for item in messages(client, cid) if item['id'] == request['message_id'])
        assert user['content'][request['start']:request['end']] == CHANGE
        assert revised['teaching']['project_step'] == frame and revised['teaching']['attempt'] is None
        assert revised['teaching']['project_observation'] is None
        assert saved(client, observed['id'])['teaching'] == prior
        assert next(item for item in messages(client, cid) if item['id'] == observed['id']) == observed
        revise(provider, change='修改当前步骤：只写函数签名')
        second = chat_turn(client, cid, '修改当前步骤：只写函数签名')
        assert state(second)['project']['goal'] == frame['goal']
        assert state(second)['project']['step']['previous_step_id'] == revised['id']
        change = '请修改当前要求，改成用两句话记录，不用标题。'
        revise(provider, change=change)
        permitted = chat_turn(client, cid, change)
        assert permitted['teaching']['status'] == 'applied'
        assert state(permitted)['project']['step']['previous_step_id'] == second['id']


def test_invalid_auto_next_malformed_work_quotes_and_revisions_keep_current_step(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client)
        start_project(provider)
        first = chat_turn(client, cid, '写一个箱子计数程序')
        cases = [
            ('做完了', NEXT, {'project': project(instruction=NEXT)}, {}),
            (WORK, FEEDBACK + '\n' + NEXT, {'step': NEXT, 'attempt': {'quote': WORK, 'needs_help': False},
                'project': project(feedback=FEEDBACK)}, {}),
            (WORK, FEEDBACK, {'attempt': {'quote': WORK, 'needs_help': False}}, {}),
            (WORK, FEEDBACK, {'attempt': {'quote': '并非用户本轮文字', 'needs_help': False},
                'project': project(feedback=FEEDBACK)}, {}),
            (WORK, FEEDBACK, {'attempt': {'quote': WORK, 'needs_help': False},
                'project': project(feedback='并非本轮反馈文字')}, {}),
            ('懂了', FEEDBACK, {'project': project(feedback=FEEDBACK)}, {}),
            ('下一步', NEXT, {'attempt': {'quote': '下一步', 'needs_help': False},
                'project': project(instruction=NEXT)}, {'teaching_action': 'next_step'}),
            ('下一步', NEXT, {'project': project(goal=GOAL, instruction=NEXT)}, {'teaching_action': 'next_step'}),
            (CHANGE, REVISION, {'project': project(instruction=REVISION, change_quote='并非修改原话')}, {}),
            (CHANGE, REVISION, {'project': project(instruction=REVISION, change_quote=CHANGE,
                feedback=REVISION)}, {}),
            (CHANGE, REVISION, {'project': project(goal='并非本轮目标文字', instruction=REVISION,
                change_quote=CHANGE)}, {}),
            (CHANGE, REVISION, {'project': {'instruction': REVISION, 'change_quote': CHANGE}}, {}),
            ('不要' + CHANGE, REVISION, {'project': project(instruction=REVISION, change_quote=CHANGE)}, {}),
            ('以下是作品文字：\n```text\n' + CHANGE + '\n```', REVISION,
                {'project': project(instruction=REVISION, change_quote=CHANGE)}, {}),
            ('引用老师的话：“' + CHANGE + '”。我没有要求修改。', REVISION,
                {'project': project(instruction=REVISION, change_quote=CHANGE)}, {}),
            ('下面是作品里的文字：\n> ' + CHANGE, REVISION,
                {'project': project(instruction=REVISION, change_quote=CHANGE)}, {}),
            ('我不修改当前要求，只想问这段代码。', REVISION,
                {'project': project(instruction=REVISION, change_quote='修改当前要求')}, {}),
        ]
        for text, body, changes, extra in cases:
            reply(provider, body, **changes)
            invalid = chat_turn(client, cid, text, **extra)
            assert invalid['content'] == body
            unchanged(invalid, first)
            assert 'result' not in saved(client, invalid['id'])['teaching']


def test_help_temporary_explanations_and_base_switch_preserve_history(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client)
        start_project(provider)
        first = chat_turn(client, cid, '写一个箱子计数程序')
        for kind in ('hint', 'example', 'try_first', 'explain_step'):
            reply(provider, '按你的请求处理当前一步。')
            helped = chat_turn(client, cid, '帮助当前步骤', help_request=kind)
            assert state(helped)['project'] == state(first)['project']
            assert helped['teaching']['attempt'] is None and helped['teaching']['project_observation'] is None
            assert provider.calls[-1][1]['project_context'] == {'goal': GOAL, 'instruction': INSTRUCTION}
        for mode, text in (('direct_answer', '这次直接给答案'), ('full_explanation', '这次完整讲解')):
            reply(provider, '可以用 sum 累计各箱物品数量。', mode={
                'value': mode, 'scope': 'turn', 'quote': text, 'persistence_quote': None})
            temporary = chat_turn(client, cid, text)
            assert temporary['teaching']['effective_mode'] == mode
            assert state(temporary)['mode'] == 'project' and state(temporary)['project'] == state(first)['project']
        reply(provider, '继续讨论箱子计数。')
        switched = chat_turn(client, cid, '改成逐步讲解', teaching_mode='stepwise')
        assert state(switched)['mode'] == 'stepwise' and 'project' not in state(switched)
        assert state(switched)['mode_source'] == 'conversation'
        assert client.get('/api/preferences').json()['teaching_mode'] == 'project'
        advance(provider)
        unavailable = chat_turn(client, cid, '下一步', teaching_action='next_step')
        unchanged(unavailable, switched)
        assert next(item for item in messages(client, cid) if item['id'] == first['id']) == first
        reply(provider, '你想做哪个小作品？')
        returned = chat_turn(client, cid, '采用个人默认方式', teaching_mode='default')
        assert state(returned)['mode'] == 'project' and state(returned)['mode_source'] == 'default'
        assert 'project' not in state(returned)


def test_natural_one_turn_project_records_work_then_restores_base_and_persistent_choice_is_local(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        checked(client, configure_provider(client))
        cid = new_chat(client)
        start_project(provider)
        provider.next['proposal']['mode'] = {
            'value': 'project', 'scope': 'turn', 'quote': '项目实践', 'persistence_quote': None}
        single = chat_turn(client, cid, '这次用项目实践，写一个箱子计数程序')
        assert single['teaching']['effective_mode'] == 'project'
        assert state(single)['mode'] == 'stepwise' and state(single)['project']['id'] == single['id']
        advance(provider)
        rejected = chat_turn(client, cid, '下一步', teaching_action='next_step')
        unchanged(rejected, single)
        observe(provider)
        observed = chat_turn(client, cid, WORK)
        assert observed['teaching']['project_observation']['project_id'] == single['id']
        assert state(observed)['mode'] == 'stepwise' and 'project' not in state(observed)
        persistent_text = '以后都用项目实践，写一个箱子计数程序'
        start_project(provider)
        provider.next['proposal']['mode'] = {
            'value': 'project', 'scope': 'conversation', 'quote': '项目实践',
            'persistence_quote': persistent_text}
        persistent = chat_turn(client, cid, persistent_text)
        assert state(persistent)['mode'] == 'project' and state(persistent)['mode_source'] == 'conversation'
        assert state(persistent)['project']['id'] == persistent['id']
        assert client.get('/api/preferences').json()['teaching_mode'] == 'stepwise'


def test_default_acceptance_replay_and_regeneration_freeze_mode_and_next_action(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client)
        start_project(provider)
        first, _, payload = send(client, cid, '写一个箱子计数程序')
        endpoint = f'/api/ai/conversations/{cid}/messages'
        frozen = copy.deepcopy(saved(client, first['id'])['teaching'])
        assert frozen['protocol'] == 'teaching-v9' and frozen['output']['version'] == 4
        defaults(client, 'stepwise')
        calls = len(provider.calls)
        replayed = client.post(endpoint, json=payload)
        assert replayed.status_code == 202 and replayed.json()['created'] is False
        assert saved(client, first['id'])['teaching'] == frozen and len(provider.calls) == calls
        regenerated = chat_turn(client, cid, payload['content'], regenerate_message_id=first['id'])
        assert regenerated['teaching']['default_mode'] == 'project'
        assert state(regenerated)['project']['id'] == regenerated['id'] != first['id']
        defaults(client, 'project')
        advance(provider)
        next_answer, _, next_payload = send(client, cid, '下一步', teaching_action='next_step')
        accepted = copy.deepcopy(saved(client, next_answer['id'])['teaching'])
        calls = len(provider.calls)
        defaults(client, 'socratic')
        assert client.post(endpoint, json=next_payload).json()['created'] is False
        assert len(provider.calls) == calls and saved(client, next_answer['id'])['teaching'] == accepted
        assert client.post(endpoint, json=next_payload | {'teaching_action': 'continue'}).status_code == 409
        alternate = chat_turn(client, cid, '下一步', regenerate_message_id=next_answer['id'])
        assert alternate['teaching']['requested_action'] == 'next_step'
        assert alternate['teaching']['default_mode'] == 'project'
        assert state(alternate)['project']['step']['id'] == alternate['id'] != next_answer['id']
        assert state(alternate)['project']['step']['previous_step_id'] == regenerated['id']


def test_old_capability_check_requires_recheck_before_recording_project_or_explicit_action(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        profile = configure_provider(client)
        checked(client, profile)
        database = client.app.state.database
        row = database.fetchone('SELECT capabilities_json FROM provider_model WHERE id=?', (profile['default_model']['id'],))
        capabilities = json.loads(row[0])
        capabilities['teaching_output']['version'] = 1
        with database.transaction() as connection:
            connection.execute('UPDATE provider_model SET capabilities_json=? WHERE id=?',
                (json.dumps(capabilities), profile['default_model']['id']))
        assert client.get(support_path(profile)).json() == {'plain': 'unchecked', 'tools': 'unchecked', 'checked_at': None}
        defaults(client, 'project')
        cid = new_chat(client)
        reply(provider, '可以讨论你想做的作品。')
        ordinary = chat_turn(client, cid, '写一个箱子计数程序')
        assert ordinary['teaching']['status'] == 'unavailable'
        assert ordinary['teaching']['recording'] == {'available': False, 'reason': 'not_checked'}
        before = messages(client, cid)
        rejected = client.post(f'/api/ai/conversations/{cid}/messages', json={
            'content': '下一步', 'client_message_id': 'old-support-next', 'teaching_action': 'next_step'})
        assert rejected.status_code == 400 and messages(client, cid) == before
        checked(client, profile)
        start_project(provider)
        initial = chat_turn(client, cid, '写一个箱子计数程序')
        assert initial['teaching']['status'] == 'applied' and state(initial)['project']['id'] == initial['id']
        assert saved(client, initial['id'])['teaching']['output']['version'] == 4
        assert len(provider.checks) == 4 and len(provider.calls) == 2


def test_natural_persistent_project_and_practice_first_switches_keep_one_active_frame(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client)
        start_project(provider)
        first = chat_turn(client, cid, '写一个箱子计数程序')
        question = '三个空箱和一个有两件物品的箱子，总数是多少？'
        text = '以后都用练习优先，练习箱子计数'
        reply(provider, question, practice={'question': question, 'feedback': None}, mode={
            'value': 'practice_first', 'scope': 'conversation', 'quote': '练习优先', 'persistence_quote': text})
        exercise = chat_turn(client, cid, text)
        assert exercise['teaching']['status'] == 'applied' and state(exercise)['mode'] == 'practice_first'
        assert state(exercise)['exercise']['id'] == exercise['id'] and 'project' not in state(exercise)
        text = '以后都用项目实践，继续写一个箱子计数程序'
        start_project(provider)
        provider.next['proposal']['mode'] = {
            'value': 'project', 'scope': 'conversation', 'quote': '项目实践', 'persistence_quote': text}
        active = chat_turn(client, cid, text)
        assert active['teaching']['status'] == 'applied' and state(active)['mode'] == 'project'
        assert state(active)['project']['id'] == active['id'] and 'exercise' not in state(active)
        assert state(active)['project']['id'] != first['id']
        assert client.get('/api/preferences').json()['teaching_mode'] == 'project'
        assert next(item for item in messages(client, cid) if item['id'] == first['id']) == first


@pytest.mark.parametrize('action', ['retell', 'practice'])
def test_single_activity_priority_and_continue_restore_exact_project_step(tmp_path, action):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client)
        start_project(provider)
        first = chat_turn(client, cid, '写一个箱子计数程序')
        invitation = '请用自己的话说明空输入返回零的依据。' if action == 'retell' else '两个空箱与一个装有三件物品的箱子，总数是多少？'
        reply(provider, invitation, practice={'question': invitation, 'feedback': None})
        activity = chat_turn(client, cid, '用自己的话说说' if action == 'retell' else '换一道试试', teaching_action=action)
        assert state(activity)['practice']['kind'] == ('retelling' if action == 'retell' else 'variant')
        assert state(activity)['project'] == state(first)['project']
        advance(provider)
        invalid = chat_turn(client, cid, '下一步', teaching_action='next_step')
        unchanged(invalid, activity)
        quote = '空箱没有物品；另外一个箱子有三件，所以总数是三。'
        reply(provider, FEEDBACK, attempt={'quote': quote, 'needs_help': False},
            practice={'question': None, 'feedback': FEEDBACK})
        observed = chat_turn(client, cid, quote)
        assert observed['teaching']['practice_observation']['question_id'] == activity['id']
        assert observed['teaching']['project_observation'] is None
        assert state(observed)['project'] == state(first)['project']
        reply(provider, '回到原项目当前一步，继续提供代码或结果。')
        resumed = chat_turn(client, cid, '继续学习', teaching_action='continue')
        assert state(resumed)['practice'] is None
        assert state(resumed)['step'] == state(first)['step']
        assert state(resumed)['project'] == state(first)['project']
        observe(provider)
        result = chat_turn(client, cid, WORK)
        assert result['teaching']['project_observation']['question_id'] == first['id']


def test_nested_branch_maps_goal_instructions_versions_requests_work_and_help_with_corrections(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client)
        start_project(provider)
        first = chat_turn(client, cid, '写一个箱子计数程序')
        revise(provider)
        revision = chat_turn(client, cid, CHANGE)
        advance(provider)
        following = chat_turn(client, cid, '下一步', teaching_action='next_step')
        reply(provider, '先检查传入的每一个箱子。')
        helped = chat_turn(client, cid, '给个提示', help_request='hint')
        observe(provider)
        observed = chat_turn(client, cid, WORK)
        frozen = copy.deepcopy(saved(client, observed['id'])['teaching'])
        endpoint = f"/api/ai/conversations/{cid}/messages/{observed['id']}/teaching-attempt"
        corrected = client.post(endpoint, json={'expected_revision': 0, 'is_attempt': False, 'request_key': 'not-project-work'})
        assert corrected.status_code == 200 and corrected.json()['project_observation']['eligible'] is False
        assert saved(client, observed['id'])['teaching'] == frozen
        copied = branch(client, cid, observed['id'], 'project-branch').json()
        copied = branch(client, copied['conversation']['id'], copied['messages'][-1]['id'], 'project-nested').json()
        answers = [item for item in copied['messages'] if item['role'] == 'assistant']
        start, changed, next_step, hint, result = answers
        frame = state(result)['project']
        assert frame['id'] == frame['goal']['answer_id'] == start['id']
        assert frame['step']['id'] == frame['step']['instruction']['answer_id'] == next_step['id']
        assert frame['step']['previous_step_id'] == changed['id']
        assert frame['step']['last_observation_id'] == result['id']
        changed_frame = changed['teaching']['project_step']
        assert changed_frame['step']['previous_step_id'] == start['id']
        assert changed_frame['step']['change_request']['message_id'] == changed['parent_message_id']
        assert changed_frame['goal']['answer_id'] == start['id']
        assert next_step['teaching']['project_step']['step']['previous_step_id'] == changed['id']
        record = result['teaching']['project_observation']
        assert record['project_id'] == start['id'] and record['question_id'] == next_step['id']
        assert record['answer_id'] == result['id'] and record['message_id'] == result['parent_message_id']
        assert record['eligible'] is False and result['teaching']['attempt']['revision'] == 1
        assert {item['answer_id'] for item in record['help_context']} == {start['id'], changed['id'], next_step['id'], hint['id']}
        remapped = saved(client, result['id'])['teaching']
        assert remapped['result']['attempt']['origin'] == frozen['result']['attempt']['origin']
        assert remapped['origin']['answer_id'] == observed['id']
        assert state(first)['project']['step']['id'] == first['id']
        assert state(revision)['project']['step']['previous_step_id'] == first['id']
        assert {item['answer_id'] for item in observed['teaching']['project_observation']['help_context']} == {
            first['id'], revision['id'], following['id'], helped['id']}


def test_truncated_unknown_token_and_cancelled_next_do_not_adopt_partial_step(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client)
        start_project(provider)
        first = chat_turn(client, cid, '写一个箱子计数程序')
        for failure in ('truncated', 'unknown', 'token'):
            advance(provider)
            provider.next['failure'] = failure
            partial = chat_turn(client, cid, '下一步', teaching_action='next_step')
            assert partial['content'] == NEXT
            unchanged(partial, first)
            assert 'result' not in saved(client, partial['id'])['teaching']

        class Waiting(httpx.AsyncByteStream):
            async def __aiter__(self):
                raw = json.dumps({'reply': NEXT}, ensure_ascii=False)[:-1]
                event = {'choices': [{'delta': {'content': raw}}]}
                yield ('data: ' + json.dumps(event, ensure_ascii=False) + '\n\n').encode()
                await asyncio.Event().wait()

        client.app.state.ai_runs.transport = httpx.MockTransport(lambda _request: httpx.Response(200, stream=Waiting()))
        accepted = client.post(f'/api/ai/conversations/{cid}/messages', json={
            'content': '下一步', 'client_message_id': 'cancel-project-next', 'teaching_action': 'next_step'})
        assert accepted.status_code == 202
        run = accepted.json()['run']['id']
        for _ in range(100):
            if client.app.state.ai_runs._runs[run].text:
                break
            time.sleep(.01)
        assert client.app.state.ai_runs._runs[run].text == NEXT
        assert client.post(f'/api/ai/runs/{run}/cancel').status_code == 200
        canceled = next(item for item in messages(client, cid) if item['id'] == accepted.json()['run']['response_message_id'])
        assert canceled['content'] == NEXT
        unchanged(canceled, first)
        assert canceled['help_record']['provided']['partial'] is True


def test_strict_scope_and_managed_purge_remove_project_sources_without_text_reintroduction(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client)
        base = f'/api/materials/conversation/{cid}'
        material = client.post(base, json={'title': '合成项目资料', 'content': 'PROJECT_PRIVATE_MATERIAL'}).json()
        scope = {'mode': 'only', 'version_ids': [material['id']]}
        start_project(provider, 'PROJECT_PRIVATE_GOAL', 'PROJECT_PRIVATE_INSTRUCTION')
        first = chat_turn(client, cid, '开始项目', source_scope=scope)
        observe(provider, 'PROJECT_PRIVATE_WORK', 'PROJECT_PRIVATE_FEEDBACK')
        observed = chat_turn(client, cid, 'PROJECT_PRIVATE_WORK', source_scope=scope)
        copied = branch(client, cid, observed['id'], 'project-private').json()
        backup = tmp_path / 'project-managed.sqlite3'
        with closing(sqlite3.connect(backup)) as target:
            client.app.state.database.connection.backup(target)
        with storage_lock(client.app.state.materials.db.database_path):
            register_backup(client.app.state.materials.db.database_path, backup)
        reply(provider, '请说明新项目的目标。')
        independent = chat_turn(client, cid, '换到独立资料范围')
        assert state(independent)['step'] is None and 'project' not in state(independent)
        assert provider.calls[-1][1]['project_context'] is None
        assert 'PROJECT_PRIVATE_' not in json.dumps(provider.calls[-1])
        purged = client.post(base + '/' + material['material_id'] + '/purge')
        assert purged.status_code == 200 and purged.json()['purge']['status'] == 'complete'
        for answer in (first, observed, copied['messages'][-1]):
            assert 'teaching' not in saved(client, answer['id'])
        assert next(item for item in messages(client, cid) if item['id'] == independent['id']) == independent
        with closing(sqlite3.connect(backup)) as connection:
            snapshots = connection.execute('SELECT config_snapshot_json FROM ai_run').fetchall()
            assert all('PROJECT_PRIVATE_' not in row[0] and '"teaching"' not in row[0] for row in snapshots)


async def ready_discussion(client, provider):
    chats = client.app.state.conversations
    database = client.app.state.learning.database
    for target in (chats.database, database):
        with target.transaction() as connection:
            connection.execute('''INSERT INTO local_identity
                (id,device_id,display_name,timezone,created_at,updated_at) VALUES (?,?,?,?,?,?)''',
                (IDENTITY['id'], IDENTITY['device_id'], IDENTITY['display_name'], IDENTITY['timezone'],
                 IDENTITY['created_at'], IDENTITY['created_at']))
    verification, original = await verification_attempt(database)
    profile = chats.save_provider(IDENTITY['id'], display_name='合成项目模型',
        base_url='https://api.example.com/v1', model='gpt-4o', api_key=FAKE_API_KEY)
    transport = httpx.MockTransport(provider)
    result = await check_capability(chats, IDENTITY['id'], profile['id'], profile['default_model']['id'], transport=transport)
    assert result['support']['plain'] == result['support']['tools'] == 'supported'
    chats.preferences.save(IDENTITY['id'], {'conflict_policy': 'ask', 'search': {'mode': 'off'}, 'teaching_mode': 'project'})
    verification.conversations = chats
    verification.transport = transport
    service = QuestionDiscussionService(verification)
    did = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'project-discussion')['id']
    return service, did, verification, original


def discussion_saved(service, tid):
    return json.loads(service.db.fetchone('SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?', (tid,))[0])


@pytest.mark.asyncio
async def test_discussion_real_work_revision_explicit_next_refresh_and_formal_isolation(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        service, did, verification, original = await ready_discussion(client, provider)
        database = client.app.state.learning.database
        before = copy.deepcopy(service.records.detail(IDENTITY, original['id']))
        before_counts = formal_counts(database)

        async def turn(text, **extra):
            return (await service.send(IDENTITY, did, text, str(uuid4()), **extra))['turns'][-1]

        start_project(provider)
        first = await turn('写一个箱子计数程序')
        assert first['status'] == 'succeeded' and first['teaching']['project_step'] == state(first)['project']
        frame = state(first)['project']
        assert extract(first, frame['goal'], body='assistant_content') == GOAL
        assert extract(first, frame['step']['instruction'], body='assistant_content') == INSTRUCTION
        observe(provider)
        observed = await turn('我的代码和结果：\n' + WORK)
        record = observed['teaching']['project_observation']
        assert record['message_id'] == record['answer_id'] == observed['id']
        assert record['project_id'] == record['question_id'] == first['id'] and record['eligible'] is True
        assert observed['user_content'][record['start']:record['end']] == WORK
        assert observed['assistant_content'][record['feedback_start']:record['feedback_end']] == FEEDBACK
        assert state(observed)['project']['step']['phase'] == 'feedback_available'
        assert QuestionDiscussionService(verification).get(IDENTITY, did)['turns'][-1] == observed
        reply(provider, '等待补充当前作品。')
        waiting = await turn('我已经做完了')
        assert state(waiting)['project'] == state(observed)['project'] and waiting['teaching']['attempt'] is None
        revise(provider)
        changed = await turn(CHANGE)
        request = state(changed)['project']['step']['change_request']
        assert request['message_id'] == changed['id']
        assert changed['user_content'][request['start']:request['end']] == CHANGE
        advance(provider)
        next_answer = await turn('下一步', teaching_action='next_step')
        assert state(next_answer)['project']['id'] == first['id']
        assert state(next_answer)['project']['step']['previous_step_id'] == changed['id']
        assert next_answer['teaching']['attempt'] is None
        after = service.records.detail(IDENTITY, original['id'])
        excluded = {'discussions', 'purge_discussion_count'}
        assert {key: value for key, value in after.items() if key not in excluded} == {
            key: value for key, value in before.items() if key not in excluded}
        assert formal_counts(database) == before_counts
        assert len(provider.calls) == len(provider.history_checks) == 5


@pytest.mark.asyncio
async def test_discussion_nested_branch_corrections_frozen_replay_regeneration_and_source_purge(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        service, did, verification, original = await ready_discussion(client, provider)

        async def turn(text, **extra):
            return (await service.send(IDENTITY, did, text, str(uuid4()), **extra))['turns'][-1]

        start_project(provider)
        first = (await service.send(IDENTITY, did, '写一个箱子计数程序', 'project-frozen-first'))['turns'][-1]
        revise(provider)
        changed = await turn(CHANGE)
        reply(provider, '检查空输入时生成的总数。')
        await turn('给个提示', help_request='hint')
        observe(provider)
        observed = await turn(WORK)
        frozen = copy.deepcopy(discussion_saved(service, observed['id'])['teaching'])
        corrected = service.correct_teaching_attempt(IDENTITY, did, observed['id'], expected_revision=0,
            is_attempt=False, request_key='dismiss-project-work')
        assert corrected['project_observation']['eligible'] is False
        assert discussion_saved(service, observed['id'])['teaching'] == frozen
        copied = branch_discussion(service, IDENTITY, did, observed['id'], 'project-discussion-branch')
        copied = branch_discussion(service, IDENTITY, copied['id'], copied['turns'][-1]['id'], 'project-discussion-nested')
        initial, revision, hint, result = copied['turns']
        frame = state(result)['project']
        assert frame['id'] == frame['goal']['answer_id'] == initial['id']
        assert frame['step']['id'] == frame['step']['instruction']['answer_id'] == revision['id']
        assert frame['step']['previous_step_id'] == initial['id']
        assert frame['step']['change_request']['message_id'] == revision['id']
        assert frame['step']['last_observation_id'] == result['id']
        record = result['teaching']['project_observation']
        assert record['project_id'] == initial['id'] and record['question_id'] == revision['id']
        assert record['message_id'] == record['answer_id'] == result['id'] and record['eligible'] is False
        assert {item['answer_id'] for item in record['help_context']} == {initial['id'], revision['id'], hint['id']}
        assert discussion_saved(service, result['id'])['teaching']['result']['attempt']['origin'] == frozen['result']['attempt']['origin']
        chats = client.app.state.conversations
        chats.preferences.save(IDENTITY['id'], {'conflict_policy': 'ask', 'search': {'mode': 'off'}, 'teaching_mode': 'socratic'})
        calls = len(provider.calls)
        replay = service.start(IDENTITY, did, '写一个箱子计数程序', 'project-frozen-first')
        assert next(item for item in replay['turns'] if item['id'] == first['id'])['teaching']['default_mode'] == 'project'
        assert len(provider.calls) == calls
        start_project(provider)
        regenerated = await turn('写一个箱子计数程序', regenerate_turn_id=first['id'])
        assert regenerated['teaching']['default_mode'] == 'project' and state(regenerated)['mode'] == 'project'
        assert state(regenerated)['project']['id'] == regenerated['id'] != first['id']
        assert regenerated['teaching']['before'] == first['teaching']['before']
        verification.purge(IDENTITY, original['id'])
        for answer in (first, changed, observed, initial, revision, result, regenerated):
            assert discussion_saved(service, answer['id']) == {}


@pytest.mark.asyncio
async def test_final_tool_round_offsets_project_goal_instruction_feedback_and_revision_sources():
    first = teaching.freeze([], answer_id='project-start', message_id='start-user', kind='conversation',
        scope_id='synthetic-project', default_mode='project', output={'format': 'json', 'version': 2})
    parser = teaching.TeachingStream(first)
    start_body = GOAL + '\n\n' + INSTRUCTION
    body = await two_rounds(parser, first, start_body, start_body,
        proposal(project=project(goal=GOAL, instruction=INSTRUCTION)))
    outcome = parser.outcome()
    teaching.adopt(first, outcome['teaching_proposal'], body=body, user_text='写一个箱子计数程序', at='synthetic',
        reply_start=outcome['teaching_reply_start'])
    offset = len(start_body) + 2
    for frame in (first['result']['after']['project'], first['result']['project_step']):
        assert frame['goal']['start'] == offset
        assert body[frame['goal']['start']:frame['goal']['end']] == GOAL
        assert frame['step']['instruction']['start'] == offset + len(GOAL) + 2
        assert body[frame['step']['instruction']['start']:frame['step']['instruction']['end']] == INSTRUCTION
    path = [{'id': first['answer_id'], 'teaching': teaching.public({'teaching': first}, 'complete')}]
    follow = teaching.freeze(path, answer_id='work-feedback', message_id='work-user', kind='conversation',
        scope_id='synthetic-project', default_mode='project', output={'format': 'json', 'version': 2})
    parser = teaching.TeachingStream(follow)
    user_text = '代码和结果：\n' + WORK
    body = await two_rounds(parser, follow, FEEDBACK, FEEDBACK,
        proposal(attempt={'quote': WORK, 'needs_help': False}, project=project(feedback=FEEDBACK)))
    outcome = parser.outcome()
    teaching.adopt(follow, outcome['teaching_proposal'], body=body, user_text=user_text, at='synthetic',
        reply_start=outcome['teaching_reply_start'])
    record = follow['result']['project_observation']
    assert record['feedback_start'] == len(FEEDBACK) + 2 and record['feedback_end'] == len(body)
    assert body[record['feedback_start']:record['feedback_end']] == FEEDBACK
    assert record['start'] == len('代码和结果：\n') and user_text[record['start']:record['end']] == WORK
    assert follow['result']['after']['project']['goal'] == first['result']['after']['project']['goal']
    assert follow['result']['after']['project']['step']['instruction'] == first['result']['after']['project']['step']['instruction']
    path.append({'id': follow['answer_id'], 'teaching': teaching.public({'teaching': follow}, 'complete')})
    revised = teaching.freeze(path, answer_id='project-revised', message_id='revision-user', kind='conversation',
        scope_id='synthetic-project', default_mode='project', output={'format': 'json', 'version': 2})
    parser = teaching.TeachingStream(revised)
    body = await two_rounds(parser, revised, REVISION, REVISION,
        proposal(project=project(instruction=REVISION, change_quote=CHANGE)))
    outcome = parser.outcome()
    user_text = '请求：' + CHANGE
    teaching.adopt(revised, outcome['teaching_proposal'], body=body, user_text=user_text, at='synthetic',
        reply_start=outcome['teaching_reply_start'])
    frame = revised['result']['after']['project']
    assert frame['goal'] == first['result']['after']['project']['goal']
    assert frame['step']['instruction']['start'] == len(REVISION) + 2
    assert frame['step']['previous_step_id'] == first['answer_id']
    assert frame['step']['change_request']['start'] == len('请求：')
    request = frame['step']['change_request']
    assert user_text[request['start']:request['end']] == CHANGE
    rejected = teaching.freeze([], answer_id='invalid-source', message_id='actual-user', kind='conversation',
        scope_id='synthetic-project', default_mode='project', output={'format': 'json', 'version': 2})
    parser = teaching.TeachingStream(rejected)
    body = await two_rounds(parser, rejected, GOAL, INSTRUCTION,
        proposal(project=project(goal=GOAL, instruction=INSTRUCTION)))
    outcome = parser.outcome()
    teaching.adopt(rejected, outcome['teaching_proposal'], body=body, user_text='写一个箱子计数程序', at='synthetic',
        reply_start=outcome['teaching_reply_start'])
    assert 'result' not in rejected and rejected['not_applied_reason'] == 'quote_mismatch'
