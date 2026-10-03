"""Fine-grained teaching references follow the selected path, corrections and purge."""
import copy
import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest

from app import teaching_runtime as teaching
from app.discussion_branches import create_branch as branch_discussion
from app.purge_storage import register_backup, storage_lock
from test_ai_conversations import authorize, configure_provider, make_client
from test_conversation_branches import branch
from test_feynman_runtime import formal_counts
from test_learning_verifications import IDENTITY
from test_project_runtime import ready_discussion, discussion_saved
from test_teaching_output_runtime import StructuredTeachingProvider, checked, defaults, send, two_rounds
from test_teaching_runtime import chat_turn, new_chat, saved

STEP = '先检查循环累加和空输入边界。'
WORK = '🍊 我用循环把每一项累加；但空列表时我会访问第一项。'
FEEDBACKS = ('循环累加的思路有进展。', '空列表没有第一项，这个边界仍需检查。')
BODY = '\n'.join(FEEDBACKS)


def prop(**changes):
    return dict(step=None, attempt=None, mode=None, help=None, practice=None, project=None, adaptation=None, learning=None) | changes


def observations(points=(None, None)):
    return [{'point_id': points[0], 'topic': '循环累加', 'state': 'progress',
             'quote': '我用循环把每一项累加', 'feedback': FEEDBACKS[0]},
            {'point_id': points[1], 'topic': '空输入边界', 'state': 'difficulty',
             'quote': '但空列表时我会访问第一项', 'feedback': FEEDBACKS[1]}]


def observe(provider, points=(None, None), used=()):
    provider.next = {'body': BODY, 'proposal': prop(attempt={'quote': WORK, 'needs_help': True},
        learning={'observations': observations(points), 'used': list(used)})}


def reply(provider, used=()):
    provider.next = {'body': '围绕当前空输入边界继续。',
                     'proposal': prop(learning={'observations': [], 'used': list(used)})}


def ready(client, provider, *, scope=None):
    authorize(client)
    checked(client, configure_provider(client))
    defaults(client, 'adaptive')
    cid = new_chat(client)
    provider.next = {'body': STEP, 'proposal': prop(step=STEP)}
    first = chat_turn(client, cid, '开始学习', **({'source_scope': scope} if scope else {}))
    assert first['teaching']['status'] == 'applied'
    return cid, first


def correction(record, **changes):
    return {'observation_id': record['id'], 'expected_revision': record['revision'], 'topic': record['topic'],
            'state': record['state'], 'note': record['note'], 'excluded': record['excluded'],
            'request_key': str(uuid4()), **changes}


def correct(client, cid, answer, record, **changes):
    response = client.post(f'/api/ai/conversations/{cid}/messages/{answer}/learning-observation',
                           json=correction(record, **changes))
    assert response.status_code == 200, response.text
    return response.json()


def test_two_source_points_correction_real_next_request_frozen_replay_and_isolation(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid, first = ready(client, provider)
        facts = formal_counts(client.app.state.learning.database)
        observe(provider)
        answer = chat_turn(client, cid, WORK)
        records = answer['teaching']['learning_observations']
        assert len(records) == 2 and [r['state'] for r in records] == ['progress', 'difficulty']
        assert records[0]['source']['message_id'] == answer['parent_message_id']
        for index, record in enumerate(records):
            source, feedback = record['source'], record['feedback']
            assert WORK[source['start']:source['end']] == observations()[index]['quote']
            assert answer['content'][feedback['start']:feedback['end']] == FEEDBACKS[index]
            assert record['help_context'] == [] and record['eligible'] is True
        original = copy.deepcopy(saved(client, answer['id'])['teaching'])
        updated = correct(client, cid, answer['id'], records[1], state='uncertain', note='需要再确认空列表情况。')
        current = updated['learning_observations'][1]
        assert current['original']['state'] == 'difficulty' and current['state'] == 'uncertain'
        assert current['revision'] == 1 and saved(client, answer['id'])['teaching'] == original
        reply(provider, [current['id']])
        following, _, payload = send(client, cid, '按我的纠正继续')
        context = provider.calls[-1][1]['learning_context']
        assert context[1]['observations'][0]['state'] == 'uncertain'
        assert context[1]['observations'][0]['note'] == current['note']
        assert context[1]['observations'][0]['user_quote'] == observations()[1]['quote']
        assert context[1]['observations'][0]['feedback_quote'] == FEEDBACKS[1]
        assert following['teaching']['learning_used'] == [current['id']]
        frozen = copy.deepcopy(saved(client, following['id'])['teaching'])
        correct(client, cid, answer['id'], current, state='progress')
        replay = client.post(f'/api/ai/conversations/{cid}/messages', json=payload)
        assert replay.status_code == 202 and replay.json()['created'] is False
        assert saved(client, following['id'])['teaching'] == frozen
        reply(provider)
        other = chat_turn(client, new_chat(client), '讨论同样的循环累加与空输入')
        assert provider.calls[-1][1]['learning_context'] == []
        assert other['teaching']['learning_observations'] == []
        assert formal_counts(client.app.state.learning.database) == facts
        assert first['teaching']['learning_observations'] == []


def test_excluded_and_non_attempt_records_do_not_reenter_context_and_restore_is_explicit(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid, _ = ready(client, provider)
        observe(provider)
        answer = chat_turn(client, cid, WORK)
        record = answer['teaching']['learning_observations'][1]
        endpoint = f'/api/ai/conversations/{cid}/messages/{answer["id"]}/learning-observation'
        payload = correction(record, excluded=True)
        changed = client.post(endpoint, json=payload)
        assert changed.status_code == 200
        assert client.post(endpoint, json=payload).json() == changed.json()
        assert client.post(endpoint, json={**payload, 'request_key': 'stale'}).status_code == 409
        assert client.post(endpoint, json={**payload, 'excluded': False}).status_code == 409
        assert changed.json()['learning_observations'][1]['eligible'] is False
        reply(provider)
        chat_turn(client, cid, '继续')
        assert len(provider.calls[-1][1]['learning_context']) == 1
        updated = correct(client, cid, answer['id'], changed.json()['learning_observations'][1], excluded=False)
        assert updated['learning_observations'][1]['eligible']
        attempt_endpoint = f'/api/ai/conversations/{cid}/messages/{answer["id"]}/teaching-attempt'
        withdrawn = client.post(attempt_endpoint, json={'expected_revision': 0, 'is_attempt': False, 'request_key': 'not-attempt'})
        assert withdrawn.status_code == 200 and not any(r['eligible'] for r in withdrawn.json()['learning_observations'])
        chat_turn(client, cid, '检查更正后的状态')
        assert provider.calls[-1][1]['learning_context'] == []
        assert client.post(attempt_endpoint, json={'expected_revision': 1, 'is_attempt': True, 'request_key': 'restore-attempt'}).status_code == 200
        chat_turn(client, cid, '再次继续')
        assert len(provider.calls[-1][1]['learning_context']) == 2


def test_same_point_preserves_conflicting_observations_nested_branches_and_local_corrections(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid, _ = ready(client, provider)
        observe(provider)
        first = chat_turn(client, cid, WORK)
        records = first['teaching']['learning_observations']
        observe(provider, [r['point_id'] for r in records], [records[1]['id']])
        provider.next['proposal']['learning']['observations'][1]['state'] = 'uncertain'
        second = chat_turn(client, cid, WORK)
        reply(provider)
        third = chat_turn(client, cid, '继续')
        assert [item['state'] for item in provider.calls[-1][1]['learning_context'][1]['observations']] == ['difficulty', 'uncertain']
        copied = branch(client, cid, third['id'], 'fine-branch').json()
        copied = branch(client, copied['conversation']['id'], copied['messages'][-1]['id'], 'fine-nested').json()
        answers = [item for item in copied['messages'] if item['role'] == 'assistant']
        branched_records = answers[1]['teaching']['learning_observations']
        later = answers[2]['teaching']['learning_observations']
        assert later[1]['point_id'] == branched_records[1]['id']
        assert answers[2]['teaching']['learning_used'] == [branched_records[1]['id']]
        assert branched_records[1]['source']['message_id'] == answers[1]['parent_message_id']
        assert branched_records[1]['feedback']['answer_id'] == answers[1]['id']
        frozen = saved(client, answers[-1]['id'])['teaching']['learning_context']
        assert frozen[1]['observations'][0]['id'] == branched_records[1]['id']
        correct(client, copied['conversation']['id'], answers[1]['id'], branched_records[1], state='progress')
        original = client.get(f'/api/ai/conversations/{cid}').json()['messages']
        assert next(m for m in original if m['id'] == first['id'])['teaching']['learning_observations'][1]['state'] == 'difficulty'
        assert second['teaching']['learning_observations'][1]['point_id'] == records[1]['point_id']


@pytest.mark.parametrize('bad', ['quote', 'feedback', 'point', 'used', 'outside_attempt', 'no_attempt', 'too_many'])
def test_invalid_observation_cannot_publish_state(bad):
    first = teaching.freeze([], answer_id='first', message_id='initial', kind='conversation', scope_id='synthetic')
    teaching.adopt(first, prop(step=STEP), body=STEP, user_text='开始', at='now')
    path = [{'id': 'first', 'teaching': teaching.public({'teaching': first}, 'complete')}]
    frozen = teaching.freeze(path, answer_id='result', message_id='work', kind='conversation', scope_id='synthetic')
    proposal = prop(attempt={'quote': WORK, 'needs_help': True}, learning={'observations': observations(), 'used': []})
    if bad == 'quote': proposal['learning']['observations'][0]['quote'] = '不存在的原文'
    if bad == 'feedback': proposal['learning']['observations'][0]['feedback'] = '未生成的反馈'
    if bad == 'point': proposal['learning']['observations'][0]['point_id'] = 'outside:0'
    if bad == 'used': proposal['learning']['used'] = ['outside:0']
    if bad == 'outside_attempt': proposal['attempt']['quote'] = '但空列表时我会访问第一项'
    if bad == 'no_attempt': proposal['attempt'] = None
    if bad == 'too_many': proposal['learning']['observations'] *= 3
    teaching.adopt(frozen, proposal, body=BODY, user_text=WORK, at='now')
    public = teaching.public({'teaching': frozen}, 'complete')
    assert public['status'] == 'not_updated' and public['learning_observations'] == []
    assert public['current'] == path[0]['teaching']['current']


def test_help_is_frozen_before_attempt_and_failure_does_not_create_observations(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid, first = ready(client, provider)
        reply(provider)
        hinted = chat_turn(client, cid, '给个提示', help_request='hint')
        observe(provider)
        answer = chat_turn(client, cid, WORK)
        help_before = answer['teaching']['learning_observations'][0]['help_context']
        assert [r['answer_id'] for r in help_before] == [hinted['id']]
        assert help_before[0]['request']['kind'] == 'hint' and help_before[0]['display'] is None
        assert first['id'] not in {r['answer_id'] for r in help_before}
        client.post(f'/api/ai/conversations/{cid}/messages/{hinted["id"]}/help-display', json={'characters': 1})
        reloaded = client.get(f'/api/ai/conversations/{cid}').json()['messages']
        assert next(m for m in reloaded if m['id'] == answer['id'])['teaching']['learning_observations'][0]['help_context'] == help_before
        for failure in ('token', 'truncated', 'unknown'):
            observe(provider)
            provider.next['failure'] = failure
            failed = chat_turn(client, cid, WORK)
            assert failed['teaching']['learning_observations'] == [] and failed['teaching']['learning_used'] == []


def test_strict_scope_purge_and_registered_backup_remove_all_observation_text_and_corrections(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        cid, _ = ready(client, provider)
        base = f'/api/materials/conversation/{cid}'
        material = client.post(base, json={'title': '合成资料', 'content': 'PRIVATE_FINE_SOURCE'}).json()
        scope = {'mode': 'only', 'version_ids': [material['id']]}
        provider.next = {'body': STEP, 'proposal': prop(step=STEP)}
        chat_turn(client, cid, '开始限定学习', source_scope=scope)
        observe(provider)
        answer = chat_turn(client, cid, WORK, source_scope=scope)
        correct(client, cid, answer['id'], answer['teaching']['learning_observations'][0], note='PRIVATE_FINE_CORRECTION')
        reply(provider)
        descendant = chat_turn(client, cid, '继续', source_scope=scope)
        assert 'PRIVATE_FINE_CORRECTION' in json.dumps(provider.calls[-1], ensure_ascii=False)
        copied = branch(client, cid, descendant['id'], 'fine-purge-branch').json()
        backup = tmp_path / 'fine-managed.sqlite3'
        with closing(sqlite3.connect(backup)) as target:
            client.app.state.database.connection.backup(target)
        with storage_lock(client.app.state.materials.db.database_path):
            register_backup(client.app.state.materials.db.database_path, backup)
        isolated = chat_turn(client, cid, '独立资料范围')
        assert provider.calls[-1][1]['learning_context'] == []
        assert 'PRIVATE_FINE_' not in json.dumps(provider.calls[-1], ensure_ascii=False)
        purged = client.post(base + '/' + material['material_id'] + '/purge')
        assert purged.status_code == 200 and purged.json()['purge']['status'] == 'complete'
        for item in (answer, descendant, copied['messages'][-1]):
            assert 'teaching' not in saved(client, item['id']) and 'learning_observation_corrections' not in saved(client, item['id'])
        with closing(sqlite3.connect(backup)) as connection:
            assert all('PRIVATE_FINE_' not in row[0] for row in connection.execute('SELECT config_snapshot_json FROM ai_run'))
        assert isolated['teaching']['learning_observations'] == []


@pytest.mark.asyncio
async def test_discussion_sources_correction_next_context_branch_and_formal_purge(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        service, did, verification, original = await ready_discussion(client, provider)
        service.chats.preferences.save(IDENTITY['id'], {'conflict_policy': 'ask', 'search': {'mode': 'off'}, 'teaching_mode': 'adaptive'})
        facts = formal_counts(client.app.state.learning.database)
        provider.next = {'body': STEP, 'proposal': prop(step=STEP)}
        await service.send(IDENTITY, did, '开始', 'start')
        observe(provider)
        answer = (await service.send(IDENTITY, did, WORK, 'observed'))['turns'][-1]
        record = answer['teaching']['learning_observations'][1]
        updated = service.correct_learning_observation(IDENTITY, did, answer['id'], **correction(record, state='uncertain', note='需要核对。'))
        assert updated['learning_observations'][1]['revision'] == 1
        reply(provider, [record['id']])
        following = (await service.send(IDENTITY, did, '继续', 'follow'))['turns'][-1]
        used = provider.calls[-1][1]['learning_context'][1]['observations'][0]
        assert used['user_quote'] == observations()[1]['quote'] and used['feedback_quote'] == FEEDBACKS[1]
        assert used['state'] == 'uncertain' and used['note'] == '需要核对。'
        copied = branch_discussion(service, IDENTITY, did, following['id'], 'copy')
        copied = branch_discussion(service, IDENTITY, copied['id'], copied['turns'][-1]['id'], 'nested')
        copied_record = copied['turns'][1]['teaching']['learning_observations'][1]
        assert copied_record['source']['message_id'] == copied_record['feedback']['answer_id'] == copied['turns'][1]['id']
        assert copied['turns'][-1]['teaching']['learning_used'] == [copied_record['id']]
        assert formal_counts(client.app.state.learning.database) == facts
        verification.purge(IDENTITY, original['id'])
        assert discussion_saved(service, answer['id']) == {} and discussion_saved(service, following['id']) == {}


@pytest.mark.asyncio
async def test_only_final_tool_answer_can_supply_feedback_span():
    first = teaching.freeze([], answer_id='first', message_id='initial', kind='conversation', scope_id='synthetic')
    teaching.adopt(first, prop(step=STEP), body=STEP, user_text='开始', at='now')
    frozen = teaching.freeze([{'id': 'first', 'teaching': teaching.public({'teaching': first}, 'complete')}],
        answer_id='final', message_id='work', kind='conversation', scope_id='synthetic', output={'format': 'json', 'version': 4})
    parser = teaching.TeachingStream(frozen)
    body = await two_rounds(parser, frozen, BODY, BODY, prop(attempt={'quote': WORK, 'needs_help': True},
        learning={'observations': observations(), 'used': []}))
    outcome = parser.outcome()
    teaching.adopt(frozen, outcome['teaching_proposal'], body=body, user_text=WORK, at='now', reply_start=outcome['teaching_reply_start'])
    records = frozen['result']['learning_observations']
    for index, record in enumerate(records):
        reference = record['feedback']
        assert reference['start'] >= len(BODY) + 2
        assert body[reference['start']:reference['end']] == FEEDBACKS[index]


def test_observation_endpoint_auth_payload_and_answer_ownership(tmp_path):
    provider = StructuredTeachingProvider()
    with make_client(tmp_path, provider) as client:
        endpoint = '/api/ai/conversations/missing/messages/missing/learning-observation'
        payload = dict(observation_id='missing:0', expected_revision=0, topic='边界', state='uncertain', note='', excluded=False, request_key='new')
        assert client.post(endpoint, json=payload).status_code == 401
        cid, first = ready(client, provider)
        path = f'/api/ai/conversations/{cid}/messages/{first["id"]}/learning-observation'
        assert client.post(path, json=payload).status_code == 409
        assert client.post(path, json={**payload, 'state': 'mastered'}).status_code == 422
        assert client.post(path, json={**payload, 'excluded': 'false'}).status_code == 422
        observe(provider)
        answer = chat_turn(client, cid, WORK)
        other = new_chat(client)
        response = client.post(f'/api/ai/conversations/{other}/messages/{answer["id"]}/learning-observation',
            json=correction(answer['teaching']['learning_observations'][0]))
        assert response.status_code in (400, 404)
