"""Adaptive choices stay version-local; only confirmed enum preferences travel."""
import copy
import json
from uuid import uuid4

import pytest

from app import teaching_runtime as teaching
from app.discussion_branches import create_branch as branch_discussion
from app.question_discussion import QuestionDiscussionService
from test_ai_conversations import authorize, configure_provider, make_client
from test_conversation_branches import branch
from test_feynman_runtime import formal_counts
from test_learning_verifications import IDENTITY
from test_project_runtime import ready_discussion, discussion_saved
from test_teaching_output_runtime import StructuredTeachingProvider, checked, defaults, send
from test_teaching_runtime import chat_turn, new_chat, saved

CONFIG = {'scenario': 'coding', 'method': 'practice_first', 'start': 'try_first', 'help': 'one_hint'}
QUOTE = '🍊 PRIVATE_PREFERENCE_实际原话：学编程时先让我试一道题，卡住后一次给一个提示。'
STEP = '先看空输入应该怎样处理。'
QUESTION = '输入为空时，取第一项会怎样？请先说出你的处理方式。'


def prop(**changes):
    return dict(step=None, attempt=None, mode=None, help=None, practice=None, project=None, adaptation=None) | changes


def adaptation(method=None, rule_id=None, draft=None):
    return {'method': method, 'rule_id': rule_id, 'reason': '依据当前任务选择教法。', 'draft': draft}


def draft(config=CONFIG, quote=QUOTE):
    return {**config, 'quote': quote, 'reason': '依据本轮明确的教学偏好；等待本人确认。'}


def reply(provider, body, method='stepwise', **changes):
    provider.next = {'body': body, 'proposal': prop(adaptation=adaptation(method), **changes)}


def ready(client):
    authorize(client)
    checked(client, configure_provider(client))
    defaults(client, 'adaptive')
    return new_chat(client)


def state(client):
    response = client.get('/api/adaptive-learning')
    assert response.status_code == 200, response.text
    return response.json()


def change(client, action, **extra):
    payload = {'action': action, 'expected_revision': state(client)['revision'], 'request_key': str(uuid4()), **extra}
    result = client.post('/api/adaptive-learning/changes', json=payload)
    assert result.status_code == 200, result.text
    return result.json()


def propose(client, provider, cid):
    provider.next = {'body': STEP, 'proposal': prop(step=STEP, adaptation=adaptation('stepwise', draft=draft()))}
    answer = chat_turn(client, cid, QUOTE)
    assert answer['teaching']['status'] == 'applied'
    return answer


def test_real_draft_confirmation_next_chat_profile_and_original_source_separation(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client)
        facts = formal_counts(client.app.state.learning.database)
        first = propose(client, provider, cid)
        record = first['teaching']
        assert record['current']['policy'] == 'adaptive' and record['current']['mode'] == 'stepwise'
        assert record['adaptation']['profile_revision'] == 0
        d = record['adaptation']['draft']
        assert d['configuration'] == CONFIG and d['source']['message_id'] == first['parent_message_id']
        pending = state(client)
        assert pending['rules'] == [] and len(pending['drafts']) == 1
        candidate = pending['drafts'][0]
        assert candidate['original_text'] == QUOTE and candidate['source']['answer_id'] == first['id']
        original = copy.deepcopy(saved(client, first['id'])['teaching'])
        accepted = change(client, 'accept', candidate_id=candidate['id'])
        assert len(accepted['rules']) == 1 and accepted['drafts'] == []
        rule = accepted['rules'][0]
        assert rule['configuration'] == CONFIG and rule['enabled'] is True
        assert client.get('/api/preferences').json()['teaching_mode'] == 'adaptive'
        assert saved(client, first['id'])['teaching'] == original
        second_cid = new_chat(client)
        provider.next = {'body': QUESTION, 'proposal': prop(practice={'question': QUESTION, 'feedback': None},
            adaptation=adaptation('practice_first', rule_id=rule['id']))}
        second = chat_turn(client, second_cid, '学习编程的空输入处理')
        assert second['teaching']['status'] == 'applied'
        assert second['teaching']['current']['mode'] == 'practice_first'
        assert second['teaching']['current']['policy'] == 'adaptive'
        assert second['teaching']['exercise_question']['id'] == second['id']
        assert second['teaching']['adaptation']['rule_id'] == rule['id']
        frozen = saved(client, second['id'])['teaching']
        assert frozen['adaptive_profile']['rules'] == [{'id': rule['id'], 'configuration': CONFIG}]
        assert 'PRIVATE_PREFERENCE_' not in json.dumps(provider.calls[-1], ensure_ascii=False)
        assert formal_counts(client.app.state.learning.database) == facts


def test_profile_edits_do_not_rewrite_accepted_run_or_regeneration(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client)
        propose(client, provider, cid)
        rule = change(client, 'accept', candidate_id=state(client)['drafts'][0]['id'])['rules'][0]
        other = new_chat(client)
        reply(provider, STEP, step=STEP)
        first, _, payload = send(client, other, '开始本轮学习')
        frozen = copy.deepcopy(saved(client, first['id'])['teaching'])
        updated = {**CONFIG, 'method': 'stepwise', 'start': 'example_first'}
        change(client, 'edit', rule_id=rule['id'], configuration=updated, enabled=True)
        replay = client.post(f'/api/ai/conversations/{other}/messages', json=payload)
        assert replay.status_code == 202 and replay.json()['created'] is False
        assert saved(client, first['id'])['teaching'] == frozen
        regenerated = chat_turn(client, other, payload['content'], regenerate_message_id=first['id'])
        assert saved(client, regenerated['id'])['teaching']['adaptive_profile'] == frozen['adaptive_profile']
        fresh = chat_turn(client, other, '再学另一点')
        assert saved(client, fresh['id'])['teaching']['adaptive_profile']['rules'][0]['configuration'] == updated
        assert state(client)['revision'] > frozen['adaptive_profile']['revision']


def test_current_request_wins_and_persistent_fixed_choice_stops_policy(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client)
        reply(provider, STEP, step=STEP)
        first = chat_turn(client, cid, '开始学习')
        request = {'value': 'direct_answer', 'scope': 'turn', 'quote': '直接给答案', 'persistence_quote': None}
        reply(provider, '直接解释空输入边界。', method='direct_answer', mode=request)
        direct = chat_turn(client, cid, '今天请直接给答案')
        assert direct['teaching']['effective_mode'] == 'direct_answer'
        assert direct['teaching']['current']['policy'] == 'adaptive'
        assert direct['teaching']['current']['mode'] == 'stepwise'
        reply(provider, '继续提问。', method='socratic', mode=request)
        wrong = chat_turn(client, cid, '直接给答案')
        assert wrong['teaching']['status'] == 'not_updated'
        assert saved(client, wrong['id'])['teaching']['not_applied_reason'] == 'adaptive_overrides_user'
        text = '以后都用分步讲解'
        reply(provider, STEP, mode={'value': 'stepwise', 'scope': 'conversation', 'quote': '分步讲解', 'persistence_quote': text})
        fixed = chat_turn(client, cid, text)
        assert fixed['teaching']['status'] == 'applied'
        assert 'policy' not in fixed['teaching']['current']
        assert client.get('/api/preferences').json()['teaching_mode'] == 'adaptive'
        assert first['teaching']['current']['policy'] == 'adaptive'


@pytest.mark.parametrize('method', ['practice_first', 'project', 'feynman'])
def test_adaptive_keeps_active_activity_and_requires_manual_next(tmp_path, method):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client)
        if method == 'practice_first':
            initial = {'practice': {'question': QUESTION, 'feedback': None}}
        elif method == 'project':
            initial = {'project': {'goal': '做一个小程序', 'instruction': QUESTION, 'feedback': None, 'change_quote': None}}
        else:
            initial = {'step': QUESTION}
        reply(provider, '做一个小程序\n'+QUESTION, method=method, **initial)
        first = chat_turn(client, cid, '开始当前任务')
        assert first['teaching']['status'] == 'applied'
        reply(provider, '改成另一个新主题。', method='stepwise', step='改成另一个新主题。')
        wrong = chat_turn(client, cid, '我需要帮助')
        assert wrong['teaching']['status'] == 'not_updated'
        assert wrong['teaching']['current'] == first['teaching']['current']
        reply(provider, '先想一想空输入。', method=method)
        hint = chat_turn(client, cid, '给个提示', help_request='hint')
        assert hint['teaching']['current'] == first['teaching']['current']
        if method != 'feynman':
            kwargs = {'practice': {'question': '下一道题。', 'feedback': None}} if method == 'practice_first' else {
                'project': {'goal': None, 'instruction': '下一道题。', 'feedback': None, 'change_quote': None}}
            reply(provider, '下一道题。', method=method, **kwargs)
            next_answer = chat_turn(client, cid, '继续', teaching_action='next_question' if method == 'practice_first' else 'next_step')
            assert next_answer['teaching']['status'] == 'applied'
            assert next_answer['teaching']['current']['policy'] == 'adaptive'
            assert next_answer['teaching']['current']['step']['id'] == next_answer['id']


def test_invalid_sources_unknown_rules_and_failed_answers_never_propose_personal_draft(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client)
        for candidate, rule in [(draft(quote='不在本轮的原文'), None), (draft(), 'invented')]:
            provider.next = {'body': STEP, 'proposal': prop(step=STEP, adaptation=adaptation('stepwise', rule, candidate))}
            answer = chat_turn(client, cid, QUOTE)
            assert answer['teaching']['status'] == 'not_updated'
            assert state(client)['drafts'] == []
        for failure in ('truncated', 'token', 'unknown'):
            provider.next = {'body': STEP, 'proposal': prop(step=STEP, adaptation=adaptation('stepwise', draft=draft())), 'failure': failure}
            answer = chat_turn(client, cid, QUOTE)
            assert answer['teaching']['status'] == 'not_updated' and state(client)['drafts'] == []
        defaults(client, 'stepwise')
        provider.next = {'body': STEP, 'proposal': prop(step=STEP, adaptation=adaptation('stepwise', draft=draft()))}
        fixed = chat_turn(client, new_chat(client), QUOTE)
        assert fixed['teaching']['status'] == 'not_updated' and state(client)['drafts'] == []


def test_nested_branches_remap_source_but_keep_one_canonical_draft_and_dismissal(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid = ready(client)
        first = propose(client, provider, cid)
        canonical = state(client)['drafts'][0]['id']
        copied = branch(client, cid, first['id'], 'adaptive-copy').json()
        nested = branch(client, copied['conversation']['id'], copied['messages'][-1]['id'], 'adaptive-nested').json()
        final = nested['messages'][-1]
        assert final['teaching']['adaptation']['draft']['source']['message_id'] == final['parent_message_id']
        assert saved(client, final['id'])['teaching']['origin']['answer_id'] == first['id']
        assert [d['id'] for d in state(client)['drafts']] == [canonical]
        change(client, 'dismiss', candidate_id=canonical)
        assert state(client)['drafts'] == []
        provider.next = {'body': STEP, 'proposal': prop(step=STEP, adaptation=adaptation('stepwise', draft=draft()))}
        repeated = chat_turn(client, cid, QUOTE)
        assert repeated['teaching']['status'] == 'applied'
        assert repeated['teaching']['adaptation']['draft'] is None
        assert state(client)['drafts'] == []


@pytest.mark.asyncio
async def test_discussion_adaptation_draft_branch_and_formal_source_isolation(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        service, did, verification, original = await ready_discussion(client, provider)
        chats = client.app.state.conversations
        chats.preferences.save(IDENTITY['id'], {'conflict_policy': 'ask', 'search': {'mode': 'off'}, 'teaching_mode': 'adaptive'})
        before = formal_counts(client.app.state.learning.database)
        provider.next = {'body': STEP, 'proposal': prop(step=STEP, adaptation=adaptation('socratic', draft=draft()))}
        first = (await service.send(IDENTITY, did, QUOTE, 'adaptive-discussion'))['turns'][-1]
        assert first['teaching']['status'] == 'applied'
        assert first['teaching']['current']['mode'] == 'socratic' and first['teaching']['current']['policy'] == 'adaptive'
        preferences = chats.adaptive_preferences
        candidates = preferences.get(IDENTITY['id'])['drafts']
        assert candidates[0]['original_text'] == QUOTE
        assert candidates[0]['source']['kind'] == 'discussion'
        copied = branch_discussion(service, IDENTITY, did, first['id'], 'adaptive-discussion-branch')
        assert copied['turns'][0]['teaching']['adaptation']['draft']['source']['message_id'] == copied['turns'][0]['id']
        assert len(preferences.get(IDENTITY['id'])['drafts']) == 1
        accepted = preferences.change(IDENTITY['id'], {'action': 'accept', 'expected_revision': 0,
            'request_key': 'accept-discussion', 'candidate_id': candidates[0]['id']})
        assert accepted['rules'][0]['configuration'] == CONFIG
        assert formal_counts(client.app.state.learning.database) == before
        verification.purge(IDENTITY, original['id'])
        state_after = preferences.get(IDENTITY['id'])
        assert state_after['drafts'] == [] and state_after['rules'][0]['enabled'] is False
        assert state_after['rules'][0]['original_text'] is None
        assert preferences.freeze(IDENTITY['id'])['rules'] == []
        assert discussion_saved(service, first['id']) == {}


def test_confirmed_help_preference_changes_ladder_without_inventing_user_help_request():
    configuration = {**CONFIG, 'method': 'socratic', 'start': 'auto', 'help': 'explain_when_stuck'}
    profile = {'revision': 3, 'rules': [{'id': 'confirmed-help', 'configuration': configuration}], 'suppressed': []}
    first = teaching.freeze([], answer_id='a1', message_id='u1', kind='conversation', scope_id='synthetic',
        default_mode='adaptive', adaptive_profile=profile)
    teaching.adopt(first, prop(step=STEP, adaptation=adaptation('socratic')), body=STEP, user_text='开始', at='now')
    path = [{'id': 'a1', 'teaching': teaching.public({'teaching': first}, 'complete')}]
    following = teaching.freeze(path, answer_id='a2', message_id='u2', kind='conversation', scope_id='synthetic',
        default_mode='adaptive', adaptive_profile=profile)
    proposal = prop(attempt={'quote': '我试着取第一项，但空列表没有这一项。', 'needs_help': True},
        adaptation=adaptation('socratic', rule_id='confirmed-help'))
    teaching.adopt(following, proposal, body='先判断列表是否为空，再决定是否取第一项。',
        user_text='我试着取第一项，但空列表没有这一项。', at='now')
    result = following['result']
    assert result['guidance'] == {'level': 4, 'reason': 'confirmed_preference'}
    assert result['help_request'] is None and result['after']['guidance']['level'] == 4
    assert result['after']['step'] == following['before']['step']


def test_explicit_choices_are_local_source_context_and_remap_with_branch():
    first = teaching.freeze([], answer_id='a1', message_id='u1', kind='conversation', scope_id='synthetic',
        default_mode='stepwise', requested_mode='socratic')
    teaching.adopt(first, prop(step=STEP), body=STEP, user_text='开始', at='now')
    public = teaching.public({'teaching': first}, 'complete')
    following = teaching.freeze([{'id': 'a1', 'teaching': public}], answer_id='a2', message_id='u2',
        kind='conversation', scope_id='synthetic', requested_mode='default', default_mode='adaptive')
    assert following['choice_context'] == [{'answer_id': 'a1', 'requested_mode': 'socratic',
        'mode_request': None, 'action': None, 'help': None}]
    wrapped = {'teaching': following}
    teaching.remap(wrapped, {'a1': 'b1', 'u1': 'v1', 'a2': 'b2', 'u2': 'v2'})
    assert following['choice_context'][0]['answer_id'] == 'b1'
    isolated = teaching.freeze([], answer_id='other', message_id='other-u', kind='conversation',
        scope_id='independent', default_mode='adaptive')
    assert isolated['choice_context'] == []


def test_regeneration_keeps_old_profile_version_but_cannot_revive_deleted_source(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        source_cid = ready(client)
        propose(client, provider, source_cid)
        rule = change(client, 'accept', candidate_id=state(client)['drafts'][0]['id'])['rules'][0]
        other = new_chat(client)
        reply(provider, STEP, step=STEP)
        first = chat_turn(client, other, '开始本轮学习')
        frozen = copy.deepcopy(saved(client, first['id'])['teaching'])
        assert frozen['adaptive_profile']['rules'][0]['id'] == rule['id']
        removed = client.delete(f'/api/ai/conversations/{source_cid}')
        assert removed.status_code in (200, 204), removed.text
        assert state(client)['rules'][0]['enabled'] is False
        regenerated = chat_turn(client, other, '开始本轮学习', regenerate_message_id=first['id'])
        profile = saved(client, regenerated['id'])['teaching']['adaptive_profile']
        assert profile['revision'] == frozen['adaptive_profile']['revision']
        assert profile['rules'] == []
        assert saved(client, first['id'])['teaching'] == frozen
