"""Feynman teaching keeps learner text, defaults and formal evidence separate."""
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
from app.credentials import CredentialError, CredentialStore
from app.discussion_branches import create_branch as branch_discussion
from app.preferences import PreferencesService
from app.purge_storage import register_backup, storage_lock
from app.question_discussion import QuestionDiscussionService
from app.search_service import SearchService
from test_ai_conversations import authorize, configure_provider, make_client, read_sse
from test_conversation_branches import branch
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY
from test_preferences import service as preference_service
from test_teaching_practice import PracticeProvider, state
from test_teaching_runtime import chat_turn, new_chat, saved
from test_verification_review import attempt as verification_attempt

INVITATION = '🍊 请用自己的话说明为什么空输入需要单独检查。'
RETELLING = '🍎 空输入没有元素，直接取第一项就会越界，所以要先判断是否为空。'
FEEDBACK = '🍐 你讲清了越界的原因；再补充空输入时应该返回什么。'
FORMAL_TABLES = ('learning_verification', 'learning_verification_submission',
                 'learning_verification_evaluation', 'learning_artifact',
                 'learning_evidence_claim', 'learning_practice', 'learning_practice_attempt')


def propose(provider, body, *, step=None, attempt=None, mode=None, practice=None, **extra):
    provider.next = {'body': body, 'raw': json.dumps({
        'step': step, 'attempt': {'quote': attempt, 'needs_help': False} if attempt else None,
        'mode': mode, 'help': None, 'practice': practice,
    }, ensure_ascii=False), **extra}


def defaults(client, mode):
    payload = {**client.get('/api/preferences').json(), 'teaching_mode': mode}
    response = client.put('/api/preferences', json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def formal_counts(database):
    return {table: database.fetchone('SELECT COUNT(*) FROM ' + table)[0] for table in FORMAL_TABLES}


def test_settings_legacy_records_and_put_keep_learning_mode_and_owner_isolation(tmp_path):
    preferences, store, search = preference_service(tmp_path)
    legacy = {'conflict_policy': 'materials', 'search': {'mode': 'native'}}
    store.set('learning-preferences:owner-a', json.dumps(legacy))
    assert preferences.get('owner-a') == {**legacy, 'teaching_mode': 'stepwise'}
    configured = preferences.save('owner-a', {**legacy, 'teaching_mode': 'feynman'})
    assert preferences.get('owner-b')['teaching_mode'] == 'stepwise'
    assert PreferencesService(store, search).get('owner-a') == configured
    # An older settings client changing search must not erase the new default.
    revised = preferences.save('owner-a', {'conflict_policy': 'balanced', 'search': {'mode': 'off'}})
    assert revised == {'conflict_policy': 'balanced', 'search': {'mode': 'off'}, 'teaching_mode': 'feynman'}


def test_settings_reject_bad_modes_and_failed_save_without_losing_prior_options(tmp_path, monkeypatch):
    with make_client(tmp_path, PracticeProvider()) as client:
        authorize(client)
        baseline = {'conflict_policy': 'materials', 'search': {'mode': 'native'}, 'teaching_mode': 'feynman'}
        assert client.put('/api/preferences', json=baseline).status_code == 200
        for invalid in ('default', 'direct_answer', None, {'mode': 'feynman'}):
            assert client.put('/api/preferences', json={**baseline, 'teaching_mode': invalid}).status_code == 422
            assert client.get('/api/preferences').json() == baseline
        credentials = client.app.state.preferences.credentials
        def fail(*_args, **_kwargs):
            raise CredentialError('synthetic failure')
        with monkeypatch.context() as patch:
            patch.setattr(credentials, 'set', fail)
            assert client.put('/api/preferences', json={**baseline, 'teaching_mode': 'stepwise'}).status_code == 503
        assert client.get('/api/preferences').json() == baseline


def test_continuous_retelling_original_quotes_corrections_refresh_and_branch(tmp_path):
    provider = PracticeProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client); defaults(client, 'feynman')
        cid = new_chat(client)
        before = formal_counts(client.app.state.learning.database)
        propose(provider, INVITATION, step=INVITATION)
        initial = chat_turn(client, cid, '先学空输入')
        checkpoint = state(initial)
        assert checkpoint['mode'] == 'feynman' and checkpoint['mode_source'] == 'default'
        assert checkpoint['retelling'] == {'step_id': initial['id'], 'phase': 'awaiting_retelling', 'last_observation_id': None}
        assert initial['teaching']['practice_question'] is None
        propose(provider, FEEDBACK, attempt=RETELLING)
        observed = chat_turn(client, cid, '我的解释：' + RETELLING)
        record = observed['teaching']['retelling_observation']
        user = next(message for message in client.get(f'/api/ai/conversations/{cid}').json()['messages']
                    if message['id'] == record['message_id'])
        assert user['content'][record['start']:record['end']] == RETELLING
        assert observed['content'][record['feedback_start']:record['feedback_end']] == observed['content']
        assert observed['content'].strip() == FEEDBACK
        assert record['question_id'] == initial['id'] and record['answer_id'] == observed['id']
        assert record['eligible'] is True and record['needs_help'] is False
        assert state(observed)['retelling']['phase'] == 'feedback_available'
        frozen = copy.deepcopy(saved(client, observed['id'])['teaching'])
        endpoint = f"/api/ai/conversations/{cid}/messages/{observed['id']}/teaching-attempt"
        corrected = client.post(endpoint, json={'expected_revision': 0, 'is_attempt': False, 'request_key': 'not-retelling'})
        assert corrected.status_code == 200 and corrected.json()['retelling_observation']['eligible'] is False
        assert saved(client, observed['id'])['teaching'] == frozen
        refreshed = next(item for item in client.get(f'/api/ai/conversations/{cid}').json()['messages'] if item['id'] == observed['id'])
        assert refreshed['teaching']['retelling_observation']['eligible'] is False
        fork = branch(client, cid, observed['id'], 'continuous-retelling').json()
        copied_initial, copied_observed = [message for message in fork['messages'] if message['role'] == 'assistant']
        copied = copied_observed['teaching']['retelling_observation']
        assert copied['question_id'] == copied_initial['id']
        assert copied['answer_id'] == copied_observed['id'] and copied['eligible'] is False
        assert copied['message_id'] == copied_observed['parent_message_id']
        assert state(copied_observed)['retelling']['last_observation_id'] == copied_observed['id']
        assert saved(client, copied_observed['id'])['teaching']['result']['attempt']['origin'] == frozen['result']['attempt']['origin']
        next_point = '请用自己的话说明只有一个元素时怎样避免越界。'
        propose(provider, next_point, step=next_point)
        continued = chat_turn(client, cid, '继续下一小点', teaching_action='continue')
        assert state(continued)['retelling']['step_id'] == continued['id']
        assert state(continued)['retelling']['phase'] == 'awaiting_retelling'
        assert state(continued)['mode'] == 'feynman'
        assert formal_counts(client.app.state.learning.database) == before


def test_defaults_path_overrides_temporary_requests_and_regeneration_are_frozen(tmp_path):
    provider = PracticeProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client); defaults(client, 'feynman')
        cid = new_chat(client)
        propose(provider, INVITATION, step=INVITATION)
        payload = {'content': '开始', 'client_message_id': 'frozen-default'}
        endpoint = f'/api/ai/conversations/{cid}/messages'
        accepted = client.post(endpoint, json=payload)
        assert accepted.status_code == 202
        read_sse(client, accepted.json()['run']['id'])
        initial = next(item for item in client.get(f'/api/ai/conversations/{cid}').json()['messages']
                       if item['id'] == accepted.json()['run']['response_message_id'])
        defaults(client, 'socratic')
        calls = len(provider.calls)
        replayed = client.post(endpoint, json=payload)
        assert replayed.status_code == 202 and replayed.json()['created'] is False
        assert len(provider.calls) == calls and saved(client, initial['id'])['teaching']['default_mode'] == 'feynman'
        regenerated = chat_turn(client, cid, '开始', regenerate_message_id=initial['id'])
        assert regenerated['teaching']['default_mode'] == 'feynman' and state(regenerated)['mode'] == 'feynman'
        propose(provider, '继续当前小点。')
        inherited = chat_turn(client, cid, '按新设置继续')
        assert state(inherited)['mode'] == 'socratic' and state(inherited)['mode_source'] == 'default'
        local = chat_turn(client, cid, '当前路径用分步', teaching_mode='stepwise')
        defaults(client, 'feynman')
        following = chat_turn(client, cid, '继续')
        assert state(following)['mode'] == 'stepwise' and state(following)['mode_source'] == 'conversation'
        restored = chat_turn(client, cid, '恢复沿设置', teaching_mode='default')
        assert state(restored)['mode'] == 'feynman' and state(restored)['mode_source'] == 'default'
        text = '这次完整讲解'
        propose(provider, '完整讲清当前边界。', mode={'value': 'full_explanation', 'scope': 'turn', 'quote': text, 'persistence_quote': None})
        temporary = chat_turn(client, cid, text)
        assert temporary['teaching']['effective_mode'] == 'full_explanation'
        assert state(temporary)['mode'] == 'feynman' and state(temporary)['mode_source'] == 'default'
        persistent_text = '以后都用提问引导'
        propose(provider, '从相关概念思考。', mode={'value': 'socratic', 'scope': 'conversation',
                'quote': '提问引导', 'persistence_quote': persistent_text})
        natural = chat_turn(client, cid, persistent_text)
        assert state(natural)['mode'] == 'socratic' and state(natural)['mode_source'] == 'conversation'
        assert client.get('/api/preferences').json()['teaching_mode'] == 'feynman'
        assert state(local)['mode'] == 'stepwise'  # Later settings never rewrite historical checkpoints.


def test_retelling_feedback_cannot_advance_to_an_unrequested_new_point(tmp_path):
    provider = PracticeProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client); defaults(client, 'feynman')
        cid = new_chat(client)
        propose(provider, INVITATION, step=INVITATION)
        original = chat_turn(client, cid, '开始')
        next_point = '接着复述单元素输入的边界。'
        propose(provider, FEEDBACK + '\n' + next_point, step=next_point, attempt=RETELLING)
        rejected = chat_turn(client, cid, RETELLING)
        assert rejected['status'] == 'complete' and FEEDBACK in rejected['content']
        assert rejected['teaching']['status'] == 'not_updated'
        assert state(rejected) == state(original)
        assert state(rejected)['retelling']['phase'] == 'awaiting_retelling'
        assert rejected['teaching']['retelling_observation'] is None
        assert 'result' not in saved(client, rejected['id'])['teaching']
        assert rejected['help_record']['provided'] is not None


def test_single_retelling_keeps_base_help_and_variant_distinct_and_branches(tmp_path):
    provider = PracticeProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        original = chat_turn(client, cid, '解释一个小点', teaching_mode='socratic')
        propose(provider, INVITATION, practice={'question': INVITATION, 'feedback': None})
        invitation = chat_turn(client, cid, '用自己的话说说。', teaching_action='retell')
        assert state(invitation)['practice']['kind'] == 'retelling'
        assert state(invitation)['mode'] == 'socratic'
        propose(provider, '提醒你检查空输入。')
        helped = chat_turn(client, cid, '给个提示', help_request='hint')
        assert helped['teaching']['practice_observation'] is None
        propose(provider, FEEDBACK, attempt=RETELLING, practice={'question': None, 'feedback': FEEDBACK})
        observed = chat_turn(client, cid, RETELLING)
        assert observed['teaching']['retelling_observation'] is None
        observation = observed['teaching']['practice_observation']
        assert {item['answer_id'] for item in observation['help_context']} == {original['id'], invitation['id'], helped['id']}
        assert state(observed)['mode'] == 'socratic'
        fork = branch(client, cid, observed['id'], 'single-retelling').json()
        copied = [item for item in fork['messages'] if item['role'] == 'assistant']
        assert state(copied[-1])['practice']['kind'] == 'retelling'
        assert state(copied[-1])['practice']['basis_step']['id'] == copied[0]['id']
        assert copied[-1]['teaching']['practice_observation']['question_id'] == copied[1]['id']
        assert saved(client, copied[-1]['id'])['teaching']['origin']['answer_id'] == observed['id']
        propose(provider, '继续原来的小点。')
        resumed = chat_turn(client, cid, '继续学习。', teaching_action='continue')
        assert state(resumed)['step'] == state(original)['step']
        assert state(resumed)['practice'] is None and state(resumed)['mode'] == 'socratic'
        variant = '换成有一个元素的输入，该怎样检查？'
        propose(provider, variant, practice={'question': variant, 'feedback': None})
        changed = chat_turn(client, cid, '换一道试试。', teaching_action='practice')
        assert state(changed)['practice']['kind'] == 'variant'
        assert state(changed)['practice']['basis_step'] == state(original)['step']


@pytest.mark.parametrize('activity', ['continuous', 'single'])
def test_truncated_and_cancelled_retelling_do_not_adopt_feedback(tmp_path, activity):
    provider = PracticeProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client); defaults(client, 'feynman' if activity == 'continuous' else 'stepwise')
        cid = new_chat(client)
        propose(provider, INVITATION, step=INVITATION)
        original = chat_turn(client, cid, '开始')
        if activity == 'single':
            propose(provider, INVITATION, practice={'question': INVITATION, 'feedback': None})
            original = chat_turn(client, cid, '用自己的话说说。', teaching_action='retell')
        propose(provider, FEEDBACK, attempt=RETELLING, finish='length',
                practice={'question': None, 'feedback': FEEDBACK} if activity == 'single' else None)
        partial = chat_turn(client, cid, RETELLING)
        assert state(partial) == state(original)
        assert partial['teaching']['retelling_observation'] is None and partial['help_record']['provided'] is not None
        class Waiting(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield ('data: ' + json.dumps({'choices': [{'delta': {'content': 'partial retelling feedback'}}]}) + '\n\n').encode()
                await asyncio.Event().wait()
        client.app.state.ai_runs.transport = httpx.MockTransport(lambda _request: httpx.Response(200, stream=Waiting()))
        accepted = client.post(f'/api/ai/conversations/{cid}/messages', json={
            'content': RETELLING, 'client_message_id': 'retelling-cancel'})
        assert accepted.status_code == 202
        run = accepted.json()['run']['id']
        for _ in range(100):
            if client.app.state.ai_runs._runs[run].text:
                break
            time.sleep(.01)
        assert client.post(f'/api/ai/runs/{run}/cancel').status_code == 200
        canceled = client.get(f'/api/ai/conversations/{cid}').json()['messages'][-1]
        assert canceled['content'].strip() == 'partial retelling feedback'
        assert state(canceled) == state(original) and canceled['teaching']['retelling_observation'] is None
        assert canceled['help_record']['provided']['partial'] is True


def test_strict_scope_and_managed_backup_remove_continuous_retelling_sources(tmp_path):
    provider = PracticeProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client); defaults(client, 'feynman')
        cid = new_chat(client)
        base = f'/api/materials/conversation/{cid}'
        material = client.post(base, json={'title': '合成复述资料', 'content': 'FEYNMAN_PRIVATE_SOURCE'}).json()
        scope = {'mode': 'only', 'version_ids': [material['id']]}
        propose(provider, 'FEYNMAN_PRIVATE_STEP', step='FEYNMAN_PRIVATE_STEP')
        point = chat_turn(client, cid, '开始', source_scope=scope)
        propose(provider, 'FEYNMAN_PRIVATE_FEEDBACK', attempt='FEYNMAN_PRIVATE_RETELLING')
        observation = chat_turn(client, cid, 'FEYNMAN_PRIVATE_RETELLING', source_scope=scope)
        copied = branch(client, cid, observation['id'], 'retelling-private').json()
        backup = tmp_path / 'feynman-managed.sqlite3'
        with closing(sqlite3.connect(backup)) as target:
            client.app.state.database.connection.backup(target)
        with storage_lock(client.app.state.materials.db.database_path):
            register_backup(client.app.state.materials.db.database_path, backup)
        propose(provider, '一个范围外的独立问题。')
        other = chat_turn(client, cid, '另外聊一个问题')
        assert state(other)['step'] is None and 'retelling' not in state(other)
        assert state(other)['mode'] == 'feynman'
        assert 'FEYNMAN_PRIVATE_' not in json.dumps(provider.calls[-1])
        purged = client.post(base + '/' + material['material_id'] + '/purge')
        assert purged.status_code == 200 and purged.json()['purge']['status'] == 'complete'
        for answer in [point, observation, copied['messages'][-1]]:
            assert 'teaching' not in saved(client, answer['id'])
        with closing(sqlite3.connect(backup)) as connection:
            snapshots = connection.execute('SELECT config_snapshot_json FROM ai_run').fetchall()
            assert all('FEYNMAN_PRIVATE_' not in row[0] and '"teaching"' not in row[0] for row in snapshots)


@pytest.mark.parametrize('protocol', ['stepwise-v1', 'teaching-v2', 'teaching-v3'])
def test_legacy_protocol_stays_readable_and_existing_local_mode_survives_new_default(protocol):
    frozen = teaching.freeze([], answer_id='old', message_id='user', kind='conversation', scope_id='chat', requested_mode='socratic')
    frozen['protocol'] = protocol
    frozen['before'].pop('mode_source')
    proposal = {'step': INVITATION, 'attempt': None, 'mode': None}
    teaching.adopt(frozen, proposal, body=INVITATION, user_text='开始', at='then')
    old = teaching.public({'teaching': frozen}, 'complete')
    assert old is not None
    next_run = teaching.freeze([{'id': 'old', 'teaching': old}], answer_id='new', message_id='u2',
                               kind='conversation', scope_id='chat', default_mode='feynman')
    assert next_run['before']['mode'] == 'socratic' and next_run['before']['mode_source'] == 'conversation'
    assert 'retelling' not in next_run['before']


@pytest.mark.asyncio
async def test_discussion_continuous_and_single_retelling_branch_retry_and_formal_isolation(learning_database, tmp_path):
    verification, original = await verification_attempt(learning_database)
    credentials = CredentialStore(tmp_path / 'discussion-credentials')
    preferences = PreferencesService(credentials, SearchService(credentials))
    preferences.save(IDENTITY['id'], {'conflict_policy': 'ask', 'search': {'mode': 'off'}, 'teaching_mode': 'feynman'})
    verification.conversations.preferences = preferences
    service = QuestionDiscussionService(verification)
    did = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'feynman-discussion')['id']
    before = copy.deepcopy(service.records.detail(IDENTITY, original['id']))
    before_counts = formal_counts(learning_database)
    provider = PracticeProvider()
    verification.transport = httpx.MockTransport(provider)
    async def send(text, **extra):
        return (await service.send(IDENTITY, did, text, str(uuid4()), **extra))['turns'][-1]
    propose(provider, INVITATION, step=INVITATION)
    initial = (await service.send(IDENTITY, did, '开始复述', 'frozen-discussion-default'))['turns'][-1]
    assert state(initial)['mode'] == 'feynman' and state(initial)['retelling']['phase'] == 'awaiting_retelling'
    propose(provider, FEEDBACK, attempt=RETELLING)
    observed = await send(RETELLING)
    record = observed['teaching']['retelling_observation']
    assert record['message_id'] == observed['id'] == record['answer_id']
    assert observed['user_content'][record['start']:record['end']] == RETELLING
    assert observed['assistant_content'][record['feedback_start']:record['feedback_end']] == observed['assistant_content']
    assert observed['assistant_content'].strip() == FEEDBACK
    original_snapshot = json.loads(learning_database.fetchone('SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?', (observed['id'],))[0])
    corrected = service.correct_teaching_attempt(IDENTITY, did, observed['id'], expected_revision=0,
        is_attempt=False, request_key='dismiss-retelling')
    assert corrected['retelling_observation']['eligible'] is False
    copied = branch_discussion(service, IDENTITY, did, observed['id'], 'feynman-branch')
    copied_initial, copied_observed = copied['turns'][-2:]
    assert copied_observed['teaching']['retelling_observation']['question_id'] == copied_initial['id']
    assert copied_observed['teaching']['retelling_observation']['message_id'] == copied_observed['id']
    copied_snapshot = json.loads(learning_database.fetchone('SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?', (copied_observed['id'],))[0])
    assert copied_snapshot['teaching']['result']['attempt']['origin'] == original_snapshot['teaching']['result']['attempt']['origin']
    preferences.save(IDENTITY['id'], {'conflict_policy': 'ask', 'search': {'mode': 'off'}, 'teaching_mode': 'stepwise'})
    calls = len(provider.calls)
    repeated = service.start(IDENTITY, did, '开始复述', 'frozen-discussion-default')
    assert next(item for item in repeated['turns'] if item['id'] == initial['id'])['teaching']['default_mode'] == 'feynman'
    assert len(provider.calls) == calls
    propose(provider, INVITATION, step=INVITATION)
    regenerated = await send('开始复述', regenerate_turn_id=initial['id'])
    assert regenerated['teaching']['default_mode'] == 'feynman' and state(regenerated)['mode'] == 'feynman'
    propose(provider, '沿新默认回应。')
    inherited = await send('继续当前小点')
    assert state(inherited)['mode'] == 'stepwise'
    propose(provider, INVITATION, practice={'question': INVITATION, 'feedback': None})
    single = await send('用自己的话说说。', teaching_action='retell')
    assert state(single)['practice']['kind'] == 'retelling' and state(single)['mode'] == 'stepwise'
    propose(provider, FEEDBACK, attempt=RETELLING, practice={'question': None, 'feedback': FEEDBACK})
    single_result = await send(RETELLING)
    assert single_result['teaching']['practice_observation']['eligible'] is True
    propose(provider, '继续原小点。')
    resumed = await send('继续学习。', teaching_action='continue')
    assert state(resumed)['practice'] is None and state(resumed)['step'] == state(inherited)['step']
    after = service.records.detail(IDENTITY, original['id'])
    excluded = {'discussions', 'purge_discussion_count'}
    assert {key: value for key, value in before.items() if key not in excluded} == {key: value for key, value in after.items() if key not in excluded}
    assert formal_counts(learning_database) == before_counts
    verification.purge(IDENTITY, original['id'])
    for turn in [initial, observed, copied_initial, copied_observed, single, single_result]:
        assert learning_database.fetchone('SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?', (turn['id'],))[0] == '{}'
