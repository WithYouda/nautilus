"""Confirmed preferences and private source lifecycle, using synthetic data."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from uuid import uuid4

import pytest

from app.adaptive_preferences import AdaptivePreferencesError, AdaptivePreferencesService, validate_configuration
from app.config import Settings
from app.conversation_branches import create_branch
from app.conversations import ConversationService
from app.credentials import CredentialStore
from app.db import Database
from app.learning_production import create_learning_backup
from app.managed_purge import ManagedPurge
from app import teaching_runtime as teaching
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY
from test_verification_review import attempt


CONFIGURATION = {'scenario': 'concepts', 'method': 'socratic', 'start': 'try_first', 'help': 'one_hint'}
QUOTE = '以后解释概念时请先让我自己试一试'
REASON = '合成说明：用户提出了明确的长期偏好'
NOW = '2026-10-04T00:00:00Z'


@pytest.fixture
def adaptive(tmp_path, learning_database):
    db = Database(tmp_path / 'ordinary.sqlite3', Settings.from_env().migrations_dir)
    with db.transaction() as c:
        for owner in ('owner-a', 'owner-b'):
            c.execute('INSERT INTO local_identity VALUES (?,?,?,?,?,?)',
                      (owner, owner, 'Synthetic learner', 'UTC', NOW, NOW))
    credentials = CredentialStore(tmp_path / 'preferences-credentials')
    chats = ConversationService(db, None, credentials)
    service = AdaptivePreferencesService(chats, learning_database, credentials)
    yield service
    db.close()


def snapshot(kind, scope_id, answer_id, message_id, user_text, configuration=None):
    start = user_text.index(QUOTE)
    return {'reply': {'question_id': message_id, 'question_version_id': message_id,
                       'parent_answer_id': None, 'parent_turn_id': None},
            'teaching': {'protocol': teaching.PROTOCOL, 'answer_id': answer_id, 'message_id': message_id,
                         'origin': {'kind': kind, 'scope_id': scope_id, 'answer_id': answer_id, 'message_id': message_id},
                         'before': teaching.checkpoint(),
                         'result': {'after': teaching.checkpoint(), 'effective_mode': 'stepwise', 'mode_request': None,
                                    'adaptation': {'draft': {'configuration': configuration or CONFIGURATION,
                                        'source': {'message_id': message_id, 'start': start, 'end': start + len(QUOTE)},
                                        'reason': REASON}}}}}


def ordinary_source(service, *, owner='owner-a', configuration=None, status='succeeded', purged=False):
    cid, uid, aid, rid = [str(uuid4()) for _ in range(4)]
    user_text = '合成隐私正文😀\n' + QUOTE + '。其他合成内容不应外发。'
    value = snapshot('conversation', cid, aid, uid, user_text, configuration)
    if purged:
        value['source_scope'] = {'purged': True}
    with service.database.transaction() as c:
        c.execute('INSERT INTO conversation(id,identity_id,title,created_at,updated_at) VALUES (?,?,?,?,?)',
                  (cid, owner, 'Synthetic discussion', NOW, NOW))
        c.execute('INSERT INTO message(id,conversation_id,role,content,sequence,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                  (uid, cid, 'user', user_text, 0, NOW, NOW))
        c.execute('INSERT INTO message(id,conversation_id,role,content,sequence,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                  (aid, cid, 'assistant', '合成成功回答', 1, NOW, NOW))
        c.execute('''INSERT INTO ai_run(id,identity_id,conversation_id,status,request_message_id,response_message_id,
                     config_snapshot_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)''',
                  (rid, owner, cid, status, uid, aid, json.dumps(value, ensure_ascii=False), NOW, NOW))
        c.execute('UPDATE message SET ai_run_id=? WHERE id=?', (rid, aid))
    return {'conversation_id': cid, 'answer_id': aid, 'message_id': uid, 'run_id': rid, 'user_text': user_text}


def change(service, action, *, revision=None, key=None, owner='owner-a', **fields):
    return service.change(owner, {'action': action, 'expected_revision': service.get(owner)['revision'] if revision is None else revision,
                                 'request_key': key or str(uuid4()), **fields})


def accept(service, **options):
    draft = service.get('owner-a')['drafts'][0]
    return change(service, 'accept', candidate_id=draft['id'], **options)


def assert_error(status, callback):
    with pytest.raises(AdaptivePreferencesError) as captured:
        callback()
    assert captured.value.status_code == status


def test_owner_isolation_successful_live_sources_and_unicode_spans(adaptive):
    source = ordinary_source(adaptive)
    ordinary_source(adaptive, owner='owner-b', configuration={**CONFIGURATION, 'method': 'feynman'})
    ordinary_source(adaptive, status='failed', configuration={**CONFIGURATION, 'scenario': 'coding'})
    ordinary_source(adaptive, purged=True, configuration={**CONFIGURATION, 'scenario': 'project'})
    result = adaptive.get('owner-a')
    assert result['revision'] == 0 and result['rules'] == []
    assert [version['revision'] for version in result['history']] == [0]
    assert len(result['drafts']) == 1
    draft = result['drafts'][0]
    assert draft['original_text'] == QUOTE and draft['reason'] == REASON
    assert draft['source'] == {'kind': 'conversation', 'scope_id': source['conversation_id'],
                              'answer_id': source['answer_id'], 'message_id': source['message_id'],
                              'start': len('合成隐私正文😀\n'), 'end': len('合成隐私正文😀\n') + len(QUOTE)}
    other = adaptive.get('owner-b')['drafts'][0]
    assert other['id'] != draft['id'] and other['configuration']['method'] == 'feynman'
    assert_error(404, lambda: change(adaptive, 'accept', owner='owner-b', candidate_id=draft['id']))
    assert adaptive.freeze('owner-a') == {'revision': 0, 'rules': [], 'suppressed': [CONFIGURATION]}


def test_accept_edit_disable_remove_restore_and_immutable_prior_versions(adaptive):
    ordinary_source(adaptive)
    accepted = accept(adaptive)
    rule = accepted['rules'][0]
    assert accepted['revision'] == 1 and accepted['drafts'] == []
    assert rule['configuration'] == CONFIGURATION and rule['enabled']
    assert adaptive.freeze('owner-a')['rules'] == [{'id': rule['id'], 'configuration': CONFIGURATION}]
    edited_config = {**CONFIGURATION, 'method': 'feynman', 'start': 'auto', 'help': 'explain_when_stuck'}
    edited = change(adaptive, 'edit', rule_id=rule['id'], configuration=edited_config, enabled=False)
    assert edited['rules'][0]['configuration'] == edited_config and not edited['rules'][0]['enabled']
    assert adaptive.freeze('owner-a')['rules'] == []
    history_one = next(version for version in edited['history'] if version['revision'] == 1)
    assert history_one['rules'] == accepted['rules']
    removed = change(adaptive, 'remove', rule_id=rule['id'])
    assert removed['rules'] == [] and removed['revision'] == 3
    restored = change(adaptive, 'restore', version=1)
    assert restored['rules'] == accepted['rules'] and restored['revision'] == 4
    assert next(version for version in restored['history'] if version['revision'] == 1) == history_one
    assert change(adaptive, 'restore', version=0)['rules'] == []
    reopened = AdaptivePreferencesService(adaptive.chats, adaptive.learning_database, CredentialStore(adaptive.credentials.credentials_dir))
    assert reopened.get('owner-a') == adaptive.get('owner-a')


def test_idempotency_stale_revision_and_concurrent_changes(adaptive):
    ordinary_source(adaptive)
    draft_id = adaptive.get('owner-a')['drafts'][0]['id']
    payload = {'action': 'accept', 'expected_revision': 0, 'request_key': 'accept-once', 'candidate_id': draft_id}
    result = adaptive.change('owner-a', payload)
    assert adaptive.change('owner-a', payload) == result
    assert_error(409, lambda: adaptive.change('owner-a', {**payload, 'action': 'dismiss'}))
    assert_error(409, lambda: change(adaptive, 'restore', revision=0, version=0))
    rule_id = result['rules'][0]['id']
    sibling = AdaptivePreferencesService(adaptive.chats, adaptive.learning_database, adaptive.credentials)
    def update(service, key):
        try:
            return service.change('owner-a', {'action': 'edit', 'expected_revision': 1, 'request_key': key,
                                 'rule_id': rule_id, 'configuration': CONFIGURATION, 'enabled': False})['revision']
        except AdaptivePreferencesError as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda pair: update(*pair), [(adaptive, 'one'), (sibling, 'two')]))
    assert sorted(outcomes) == [2, 409]
    assert adaptive.get('owner-a')['revision'] == 2


def test_accept_replaces_same_scenario_edit_collision_and_dismiss_suppression(adaptive):
    ordinary_source(adaptive)
    first = accept(adaptive)['rules'][0]
    second_config = {**CONFIGURATION, 'method': 'feynman'}
    ordinary_source(adaptive, configuration=second_config)
    second = accept(adaptive)['rules'][0]
    assert second['id'] != first['id'] and second['configuration'] == second_config
    ordinary_source(adaptive, configuration={**CONFIGURATION, 'scenario': 'coding'})
    another = accept(adaptive)['rules']
    assert len(another) == 2
    assert_error(409, lambda: change(adaptive, 'edit', rule_id=second['id'],
                                    configuration={**second_config, 'scenario': 'coding'}, enabled=True))
    dismissed_config = {**CONFIGURATION, 'scenario': 'project'}
    dismissed_source = ordinary_source(adaptive, configuration=dismissed_config)
    draft_id = adaptive.get('owner-a')['drafts'][0]['id']
    change(adaptive, 'dismiss', candidate_id=draft_id)
    ordinary_source(adaptive, configuration=dismissed_config)
    assert adaptive.get('owner-a')['drafts'] == []
    assert dismissed_config in adaptive.freeze('owner-a')['suppressed']
    assert [item['id'] for item in adaptive.get('owner-a')['ignored']] == [draft_id]
    reconsider = {'action': 'reconsider', 'expected_revision': adaptive.get('owner-a')['revision'],
                  'request_key': 'reconsider-once', 'candidate_id': draft_id}
    assert_error(404, lambda: adaptive.change('owner-b', {**reconsider, 'expected_revision': 0}))
    assert_error(409, lambda: adaptive.change('owner-a', {**reconsider, 'expected_revision': 0}))
    reconsidered = adaptive.change('owner-a', reconsider)
    assert reconsidered['ignored'] == [] and [item['id'] for item in reconsidered['drafts']] == [draft_id]
    assert adaptive.change('owner-a', reconsider) == reconsidered
    assert reconsidered['rules'] == another  # Explicit reconsideration does not adopt a rule.
    assert change(adaptive, 'dismiss', candidate_id=draft_id)['ignored'][0]['id'] == draft_id
    with adaptive.database.transaction() as c:
        c.execute('UPDATE conversation SET deleted_at=? WHERE id=?', (NOW, dismissed_source['conversation_id']))
    assert adaptive.get('owner-a')['ignored'] == []
    assert_error(404, lambda: change(adaptive, 'reconsider', candidate_id=draft_id))


def test_deleted_sources_disable_current_history_and_restore_without_raw_copies(adaptive):
    source = ordinary_source(adaptive)
    first = accept(adaptive, key=QUOTE)
    rule_id = first['rules'][0]['id']
    change(adaptive, 'edit', rule_id=rule_id, configuration={**CONFIGURATION, 'help': 'auto'}, enabled=True)
    raw = adaptive.credentials.get('adaptive-learning:owner-a')
    assert all(text not in raw for text in (source['user_text'], QUOTE, REASON))
    state = json.loads(raw)
    assert set(state['rules'][0]['source']) == {'candidate_id', 'start', 'end'}
    with adaptive.database.transaction() as c:
        c.execute('UPDATE conversation SET deleted_at=? WHERE id=?', (NOW, source['conversation_id']))
    disabled = adaptive.get('owner-a')
    for rule in [*disabled['rules'], *(rule for version in disabled['history'] for rule in version['rules'])]:
        assert not rule['enabled'] and rule['source'] is None and rule['original_text'] is None
    assert adaptive.freeze('owner-a')['rules'] == []
    restored = change(adaptive, 'restore', version=1)
    assert not restored['rules'][0]['enabled']
    assert_error(404, lambda: change(adaptive, 'edit', rule_id=rule_id, configuration=CONFIGURATION, enabled=True))
    assert QUOTE not in json.dumps(restored, ensure_ascii=False)


def test_real_branch_deduplicates_origin_and_resolves_surviving_copy(adaptive):
    source = ordinary_source(adaptive)
    original = adaptive.get('owner-a')['drafts'][0]
    fork = create_branch(adaptive.chats, 'owner-a', source['conversation_id'], source['answer_id'], 'branch')
    assert adaptive.get('owner-a')['drafts'] == [original]
    accepted = accept(adaptive)
    with adaptive.database.transaction() as c:
        c.execute('UPDATE conversation SET deleted_at=? WHERE id=?', (NOW, source['conversation_id']))
    rule = adaptive.get('owner-a')['rules'][0]
    assert rule['enabled'] and rule['id'] == accepted['rules'][0]['id']
    assert rule['original_text'] == QUOTE and rule['source']['scope_id'] == fork['conversation']['id']
    assert rule['source']['message_id'] != source['message_id']
    assert adaptive.get('owner-a')['drafts'] == []


def test_successful_regeneration_resolves_frozen_user_source(adaptive):
    source = ordinary_source(adaptive)
    with adaptive.database.transaction() as c:
        # Regenerations reserve no second unique request-message link.
        c.execute('UPDATE ai_run SET request_message_id=NULL WHERE id=?', (source['run_id'],))
    draft = adaptive.get('owner-a')['drafts'][0]
    assert draft['source']['message_id'] == source['message_id']
    assert accept(adaptive)['rules'][0]['original_text'] == QUOTE
    foreign = ordinary_source(adaptive, owner='owner-b', configuration={**CONFIGURATION, 'method': 'feynman'})
    with adaptive.database.transaction() as c:
        c.execute("UPDATE ai_run SET config_snapshot_json=json_set(config_snapshot_json,'$.teaching.message_id',?) WHERE id=?",
                  (source['message_id'], foreign['run_id']))
    assert adaptive.get('owner-b')['drafts'] == []


async def test_discussion_managed_purge_scrubs_draft_and_history_sources(adaptive, tmp_path):
    verification, current = await attempt(adaptive.learning_database)
    did, tid = str(uuid4()), str(uuid4())
    user_text = '合成讨论隐私😀 ' + QUOTE
    value = snapshot('discussion', did, tid, tid, user_text)
    with adaptive.learning_database.transaction() as c:
        c.execute('''INSERT INTO learning_question_discussion
            (id,owner_id,verification_id,submission_id,question_id,request_key,created_at)
            VALUES (?,?,?,?,?,?,?)''', (did, 'owner-a', current['id'], current['latest_submission_id'], 'q1', did, NOW))
        c.execute('''INSERT INTO learning_discussion_turn
            (id,discussion_id,request_key,user_content,assistant_content,status,provider_snapshot_json,created_at)
            VALUES (?,?,?,?,?,'succeeded',?,?)''', (tid, did, tid, user_text, '合成讨论回答', json.dumps(value, ensure_ascii=False), NOW))
    assert adaptive.get('owner-a')['drafts'][0]['source']['kind'] == 'discussion'
    accepted = accept(adaptive)
    rule_id = accepted['rules'][0]['id']
    change(adaptive, 'edit', rule_id=rule_id, configuration={**CONFIGURATION, 'start': 'auto'}, enabled=True)
    backup, _, _ = create_learning_backup(adaptive.learning_database.database_path, tmp_path / 'backups', label='adaptive')
    result = ManagedPurge(verification.learning).run(IDENTITY, 'verification', current['id'],
                                                  lambda: verification.purge(IDENTITY, current['id']))
    assert result['purge']['status'] == 'complete'
    for path in (adaptive.learning_database.database_path, backup):
        with closing(sqlite3.connect(path)) as c:
            assert c.execute('SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?', (tid,)).fetchone()[0] == '{}'
            dump = '\n'.join(c.iterdump())
            assert user_text not in dump and REASON not in dump
    public = adaptive.get('owner-a')
    assert public['drafts'] == [] and not public['rules'][0]['enabled']
    assert public['rules'][0]['source'] is None
    assert all(not rule['enabled'] and rule['original_text'] is None for version in public['history'] for rule in version['rules'])
    restored = change(adaptive, 'restore', version=1)
    assert not restored['rules'][0]['enabled'] and restored['rules'][0]['original_text'] is None
    raw = adaptive.credentials.get('adaptive-learning:owner-a')
    assert user_text not in raw and QUOTE not in raw and REASON not in raw


@pytest.mark.parametrize('patch', [
    {'unknown': QUOTE}, {'expected_revision': True}, {'request_key': ''}, {'action': 'unknown'},
    {'configuration': {**CONFIGURATION, 'method': 'invented'}}, {'enabled': 'true'},
])
def test_change_rejects_generic_invalid_payloads(adaptive, patch):
    base = {'action': 'edit', 'expected_revision': 0, 'request_key': 'test', 'rule_id': 'missing',
            'configuration': CONFIGURATION, 'enabled': True}
    assert_error(422, lambda: adaptive.change('owner-a', {**base, **patch}))


def test_route_auth_conflicts_errors_and_private_cache(client):
    app = client.app
    app.state.adaptive_preferences = AdaptivePreferencesService(app.state.conversations, app.state.learning.database,
                                                               app.state.conversations.credentials)
    assert client.get('/api/adaptive-learning').status_code == 401
    assert client.post('/api/adaptive-learning/changes', json={}).status_code == 401
    assert client.post('/api/auth/authorize', json={'access_token': app.state.auth.runtime_access_token}).status_code == 200
    response = client.get('/api/adaptive-learning')
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert response.json()['revision'] == 0
    assert client.post('/api/adaptive-learning/changes', content='bad-json').status_code == 422
    bad = {'action': 'accept', 'expected_revision': 0, 'request_key': 'route', 'candidate_id': 'private-missing'}
    response = client.post('/api/adaptive-learning/changes', json=bad)
    assert response.status_code == 404 and 'private-missing' not in response.text
    stale = {**bad, 'expected_revision': 1}
    assert client.post('/api/adaptive-learning/changes', json=stale).status_code == 409
    oversized = client.post('/api/adaptive-learning/changes', content='x' * 9000)
    assert oversized.status_code == 413


def test_configuration_starts_respect_existing_teaching_protocols():
    valid = [('practice_first', 'try_first'), ('feynman', 'auto'),
             ('direct_answer', 'explain_first'), ('full_explanation', 'example_first'),
             ('socratic', 'example_first'), ('project', 'try_first')]
    invalid = [('practice_first', 'explain_first'), ('feynman', 'example_first'),
               ('direct_answer', 'try_first'), ('full_explanation', 'try_first')]
    for method, start in valid:
        configuration = {**CONFIGURATION, 'method': method, 'start': start}
        assert validate_configuration(configuration) == configuration
    for method, start in invalid:
        assert_error(422, lambda: validate_configuration({**CONFIGURATION, 'method': method, 'start': start}))
