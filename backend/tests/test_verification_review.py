import asyncio
import json
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from app.core.commands import PurgeArtifact
from app.core.learning import LearningCore
from app.learning_domain import DomainError
from app.learning_production import _backup_restores_verification_content
from app.learning_records import LearningRecords
from app.question_discussion import QuestionDiscussionService
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import CHALLENGE, IDENTITY, OWNER, PASS, create_context, verification_service, response_transport


async def attempt(db, *, response=PASS):
    context = create_context(db)
    service = verification_service(db, [CHALLENGE, response])
    current = await service.start(IDENTITY, {**context, 'mode': 'ai_challenge'}, 'review-start')
    current = await service.submit(IDENTITY, current['id'], dict(responses={'q1': '合成原始作答'}, request_key='answer1', evidence_condition='independent'))
    current = await service.evaluate(IDENTITY, current['id'], current['latest_submission_id'], 'eval1')
    return service, current


@pytest.mark.asyncio
async def test_owner_review_preserves_versions_and_never_releases_hidden_answer(learning_database):
    service, current = await attempt(learning_database)
    records = LearningRecords(service)
    first = current['latest_submission_id']
    detail = records.detail(IDENTITY, current['id'])
    assert detail['content']['responses']['q1'] == '合成原始作答'
    assert '服务端评估依据' not in json.dumps(detail, ensure_ascii=False)
    assert '合成原始作答' not in json.dumps(service.list(IDENTITY), ensure_ascii=False)
    assert records.list(IDENTITY)[0]['verification_count'] == 1
    await service.submit(IDENTITY, current['id'], dict(responses={'q1': '合成原始作答'}, request_key='answer1', evidence_condition='independent'))
    payload = dict(responses={'q1': '合成第二次作答'}, request_key='answer2', evidence_condition='independent')
    await service.submit(IDENTITY, current['id'], payload)
    await service.submit(IDENTITY, current['id'], payload)
    assert records.detail(IDENTITY, current['id'], first)['content']['responses']['q1'] == '合成原始作答'
    assert records.detail(IDENTITY, current['id'])['content']['responses']['q1'] == '合成第二次作答'
    assert records.detail(IDENTITY, current['id'])['content']['evidence_condition'] == 'with_materials'
    assert records.detail(IDENTITY, current['id'], first)['content']['evidence_condition'] == 'independent'
    for action in (lambda: records.detail({**IDENTITY, 'id': 'owner-b'}, current['id']),
                   lambda: records.detail(IDENTITY, current['id'], 'not-owned')):
        with pytest.raises(DomainError, match='not_found'):
            action()


@pytest.mark.asyncio
async def test_per_question_feedback_blocks_contradictory_pass(learning_database):
    response = json.loads(PASS)
    response['question_feedback'] = [dict(question_id='q1', feedback='还缺少原要求', reference_answer='合成参考解法', follow_up_questions=['可选拓展'], unmet_requirements=['原要求未满足'])]
    service, current = await attempt(learning_database, response=json.dumps(response))
    assert current['result']['passed'] is False
    assert current['result']['stop_condition_met'] is False
    assert 'question_feedback' not in current['result']
    detail = LearningRecords(service).detail(IDENTITY, current['id'])
    assert detail['result']['question_feedback'][0]['reference_answer'] == '合成参考解法'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['missing', 'blank', 'partial', 'duplicate'])
async def test_incomplete_feedback_cannot_pass_and_retry_preserves_submission(learning_database, kind):
    context = create_context(learning_database)
    challenge = json.loads(CHALLENGE)
    challenge['questions'].append({**challenge['questions'][0], 'id': 'q2', 'prompt': '第二题：说明一个边界情况。'})
    complete = json.loads(PASS)
    complete['question_feedback'].append({**complete['question_feedback'][0], 'question_id': 'q2', 'feedback': '第二题建议：检查空输入。'})
    invalid = json.loads(json.dumps(complete))
    if kind == 'missing':
        invalid.pop('question_feedback')
    elif kind == 'blank':
        invalid['question_feedback'][1]['feedback'] = '  \n '
    elif kind == 'partial':
        invalid['question_feedback'].pop()
    else:
        invalid['question_feedback'][1]['question_id'] = 'q1'
    service = verification_service(learning_database, [json.dumps(challenge), json.dumps(invalid)])
    current = await service.start(IDENTITY, {**context, 'mode': 'ai_challenge'}, 'start')
    saved = await service.submit(IDENTITY, current['id'], dict(responses={'q1': '合成答案一', 'q2': '合成答案二'}, request_key='save'))
    failed = await service.evaluate(IDENTITY, current['id'], saved['latest_submission_id'], 'first')
    assert failed['evaluation']['status'] == 'failed'
    assert failed['result'] is None
    assert LearningRecords(service).detail(IDENTITY, current['id'])['content']['responses'] == {'q1': '合成答案一', 'q2': '合成答案二'}
    with pytest.raises(DomainError, match='verification_state_conflict'):
        service.confirm(IDENTITY, current['id'], saved['latest_submission_id'], failed['evaluation']['id'])
    def evaluate(request):
        prompt = json.loads(json.loads(request.content)['messages'][1]['content'])
        assert [q['id'] for q in prompt['questions']] == ['q1', 'q2']
        assert prompt['questions'][1]['prompt'] == challenge['questions'][1]['prompt']
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(complete)}}]})
    service.transport = httpx.MockTransport(evaluate)
    retried = await service.evaluate(IDENTITY, current['id'], saved['latest_submission_id'], 'retry')
    assert retried['evaluation']['status'] == 'succeeded'
    assert LearningRecords(service).detail(IDENTITY, current['id'])['result'] == complete
    assert learning_database.fetchone('SELECT COUNT(*) FROM learning_verification_submission')[0] == 1
    thread = QuestionDiscussionService(service).create(IDENTITY, current['id'], saved['latest_submission_id'], 'q2', 'discussion')
    assert thread['source']['feedback'] == complete['question_feedback'][1]


@pytest.mark.asyncio
async def test_legacy_overall_feedback_is_preserved_and_identified_in_discussion(learning_database):
    service, current = await attempt(learning_database)
    legacy = json.loads(PASS)
    legacy.pop('question_feedback')
    with learning_database.transaction() as c:
        c.execute('UPDATE learning_verification_evaluation SET result_json=? WHERE id=?', (json.dumps(legacy), current['evaluation']['id']))
        c.execute('UPDATE learning_verification SET result_json=? WHERE id=?', (json.dumps(legacy), current['id']))
    assert LearningRecords(service).detail(IDENTITY, current['id'])['result'] == legacy
    thread = QuestionDiscussionService(service).create(IDENTITY, current['id'], current['latest_submission_id'], 'q1', 'legacy')
    assert thread['source']['feedback'] == dict(feedback=legacy['feedback'], next_step=legacy['next_step'], legacy=True)
    service.confirm(IDENTITY, current['id'], current['latest_submission_id'], current['evaluation']['id'])
    assert service._owned(OWNER.owner_id, current['id'])['status'] == 'passed'


@pytest.mark.asyncio
async def test_completed_question_can_be_discussed_without_reopening_and_purges_transitively(learning_database, tmp_path):
    service, current = await attempt(learning_database)
    confirmed = service.confirm(IDENTITY, current['id'], current['latest_submission_id'], current['evaluation']['id'])
    assert confirmed['status'] == 'passed'
    discussions = QuestionDiscussionService(service)
    first = discussions.create(IDENTITY, current['id'], current['latest_submission_id'], 'q1', 'discussion1')
    assert discussions.create(IDENTITY, current['id'], current['latest_submission_id'], 'q1', 'discussion1')['id'] == first['id']
    with pytest.raises(DomainError, match='not_found'):
        discussions.get({**IDENTITY, 'id': 'owner-b'}, first['id'])
    service.transport = response_transport(['{"history_query":null}', '合成继续讲解'])
    reply = await discussions.send(IDENTITY, first['id'], '合成追问', 'turn1')
    assert reply['turns'][0]['assistant_content'] == '合成继续讲解'
    assert (await discussions.send(IDENTITY, first['id'], '合成追问', 'turn1'))['turns'] == reply['turns']
    second = discussions.create(IDENTITY, current['id'], current['latest_submission_id'], 'q1', 'discussion2')
    service.transport = response_transport(['{"history_query":"合成追问"}', '引用前次讲解[记录1]'])
    second = await discussions.send(IDENTITY, second['id'], '再问', 'turn2')
    assert second['turns'][0]['sources'][0]['discussion_id'] == first['id']
    assert service._owned(OWNER.owner_id, current['id'])['status'] == 'passed'
    assert LearningRecords(service).list(IDENTITY)[0]['status'] == 'completed'
    backup = sqlite3.connect(tmp_path / 'before.sqlite3')
    learning_database.connection.backup(backup)
    service.purge(IDENTITY, current['id'])
    assert discussions.get(IDENTITY, first['id'])['source'] is None
    assert discussions.get(IDENTITY, second['id'])['turns'][0]['assistant_content'] is None
    assert learning_database.fetchone('SELECT COUNT(*) FROM learning_discussion_turn WHERE user_content IS NOT NULL OR assistant_content IS NOT NULL')[0] == 0
    assert _backup_restores_verification_content(learning_database.connection, backup)
    backup.close()
    LearningCore(learning_database).replay(OWNER)
    assert discussions.get(IDENTITY, first['id'])['purged'] is True
    assert LearningRecords(service).detail(IDENTITY, current['id'])['content'] is None


@pytest.mark.asyncio
async def test_late_reply_cannot_resurrect_purged_discussion(learning_database):
    service, current = await attempt(learning_database)
    discussions = QuestionDiscussionService(service)
    thread = discussions.create(IDENTITY, current['id'], current['latest_submission_id'], 'q1', 'thread')
    waiting, release = asyncio.Event(), asyncio.Event()
    calls = 0
    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            answer = '{"history_query":null}'
        else:
            waiting.set()
            await release.wait()
            answer = '不能复活的迟到正文'
        if json.loads(request.content).get('stream'):
            event = json.dumps({'choices': [{'delta': {'content': answer}}]})
            return httpx.Response(200, content=f'data: {event}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={'choices': [{'message': {'content': answer}}]})
    service.transport = httpx.MockTransport(handler)
    task = asyncio.create_task(discussions.send(IDENTITY, thread['id'], '待清除的问题', 'turn'))
    await asyncio.wait_for(waiting.wait(), 2)
    with pytest.raises(DomainError, match='discussion_busy'):
        await discussions.send(IDENTITY, thread['id'], '并发问题', 'another')
    service.purge(IDENTITY, current['id'])
    release.set()
    result = await task
    assert result['purged'] is True
    assert result['turns'][0]['status'] == 'purged'
    assert result['turns'][0]['assistant_content'] is None


@pytest.mark.asyncio
async def test_search_filters_owner_delegation_and_deleted_teaching_history(learning_database):
    service, current = await attempt(learning_database)
    discussion_service = QuestionDiscussionService(service)
    thread = discussion_service.create(IDENTITY, current['id'], current['latest_submission_id'], 'q1', 'search')
    raw = sqlite3.connect(':memory:')
    raw.row_factory = sqlite3.Row
    raw.executescript('CREATE TABLE conversation(id,identity_id,deleted_at); CREATE TABLE message(id,conversation_id,role,content,status,sequence);')
    raw.executemany('INSERT INTO conversation VALUES (?,?,?)', [('same', 'owner-a', None), ('foreign', 'owner-b', None), ('deleted', 'owner-a', 'now'), ('unlinked', 'owner-a', None)])
    for key in ('same', 'foreign', 'deleted', 'unlinked'):
        raw.execute('INSERT INTO message VALUES (?,?,?,?,?,?)', (key, key, 'user', '合成关键词 '+key, 'complete', 1))
    service.conversations.database = SimpleNamespace(fetchall=lambda sql, args: raw.execute(sql, args).fetchall(), fetchone=lambda sql, args: raw.execute(sql, args).fetchone())
    with learning_database.transaction() as c:
        for key in ('same', 'foreign', 'deleted'):
            c.execute('INSERT INTO learning_room_conversation VALUES (?,?,?,?)', ('owner-a', current['session_id'], key, 'now'))
    hits = discussion_service.search('owner-a', discussion_service._owned('owner-a', thread['id']), '关键词')
    assert [hit['conversation_id'] for hit in hits] == ['same']
    assert discussion_service.search('owner-b', discussion_service._owned('owner-a', thread['id']), '关键词') == []
    raw.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('feedback', [[], [dict(question_id='foreign', feedback='', reference_answer='', follow_up_questions=[], unmet_requirements=[])]])
async def test_partial_or_foreign_question_feedback_fails_without_losing_answer(learning_database, feedback):
    service, current = await attempt(learning_database, response=json.dumps({**json.loads(PASS), 'question_feedback': feedback}))
    assert current['evaluation']['status'] == 'failed'
    assert LearningRecords(service).detail(IDENTITY, current['id'])['content']['responses']['q1'] == '合成原始作答'


@pytest.mark.asyncio
async def test_artifact_purge_erases_other_verification_discussion_that_retrieved_it(learning_database, tmp_path):
    service, current = await attempt(learning_database)
    discussions = QuestionDiscussionService(service)
    first = discussions.create(IDENTITY, current['id'], current['latest_submission_id'], 'q1', 'one')
    service.transport = response_transport(['{"history_query":null}', '合成引用来源'])
    await discussions.send(IDENTITY, first['id'], '合成来源问题', 'one-turn')
    service.transport = response_transport([CHALLENGE, PASS])
    second_verification = await service.start(IDENTITY, {key: current[key] for key in ('action_id', 'delegation_id', 'session_id', 'mode')}, 'second-verification')
    second_verification = await service.submit(IDENTITY, second_verification['id'], dict(responses={'q1': '另一份合成作答'}, request_key='second-answer'))
    second_verification = await service.evaluate(IDENTITY, second_verification['id'], second_verification['latest_submission_id'], 'second-evaluation')
    second = discussions.create(IDENTITY, second_verification['id'], second_verification['latest_submission_id'], 'q1', 'two')
    service.transport = response_transport(['{"history_query":"合成来源"}', '可能引用原文的合成衍生回答'])
    await discussions.send(IDENTITY, second['id'], '再次讨论', 'two-turn')
    with learning_database.transaction() as c:
        c.execute("UPDATE learning_discussion_turn SET reasoning_content='合成引用思考'")
    assert LearningRecords(service).detail(IDENTITY, current['id'])['purge_discussion_count'] == 2
    core = LearningCore(learning_database)
    version = learning_database.fetchone('SELECT version FROM learning_action WHERE id=?', (current['action_id'],))[0]
    core.execute(OWNER, PurgeArtifact(artifact_id=current['artifact_id'], expected_version=version, confirmation='PURGE'), 'purge-through-artifact')
    assert discussions.get(IDENTITY, first['id'])['purged']
    assert discussions.get(IDENTITY, second['id'])['purged']
    assert discussions.get(IDENTITY, first['id'])['turns'][0]['reasoning_content'] is None
    assert discussions.get(IDENTITY, second['id'])['turns'][0]['reasoning_content'] is None
    assert LearningRecords(service).detail(IDENTITY, second_verification['id'])['content']['responses']['q1'] == '另一份合成作答'
    # A copy whose ordinary artifact/verification erasure is intact can still
    # contain discussion text; restore must reject that copy independently.
    backup = sqlite3.connect(tmp_path / 'partial-erasure.sqlite3')
    learning_database.connection.backup(backup)
    assert not _backup_restores_verification_content(learning_database.connection, backup)
    backup.execute("UPDATE learning_discussion_turn SET assistant_content='合成残留正文' WHERE discussion_id=?", (second['id'],))
    assert _backup_restores_verification_content(learning_database.connection, backup)
    backup.execute("UPDATE learning_discussion_turn SET assistant_content=NULL, reasoning_content='合成残留思考' WHERE discussion_id=?", (second['id'],))
    assert _backup_restores_verification_content(learning_database.connection, backup)
    backup.execute("UPDATE learning_discussion_turn SET reasoning_content=NULL")
    backup.execute("DROP TRIGGER learning_discussion_erase_turns")
    backup.execute("ALTER TABLE learning_discussion_turn DROP COLUMN reasoning_content")
    assert not _backup_restores_verification_content(learning_database.connection, backup)
    backup.close()
    core.replay(OWNER)
    assert discussions.get(IDENTITY, second['id'])['turns'][0]['assistant_content'] is None


@pytest.mark.asyncio
async def test_discussion_failure_retry_recovery_and_request_conflict(learning_database):
    service, current = await attempt(learning_database)
    discussions = QuestionDiscussionService(service)
    thread = discussions.create(IDENTITY, current['id'], current['latest_submission_id'], 'q1', 'thread')
    service.transport = response_transport(['not json'])
    failed = await discussions.send(IDENTITY, thread['id'], '保留合成追问', 'same')
    assert failed['turns'][0]['status'] == 'failed'
    assert failed['turns'][0]['user_content'] == '保留合成追问'
    with pytest.raises(DomainError, match='idempotency_conflict'):
        await discussions.send(IDENTITY, thread['id'], '不同问题', 'same', True)
    service.transport = response_transport(['{"history_query":null}', '重试后的合成回复'])
    retried = await discussions.send(IDENTITY, thread['id'], '保留合成追问', 'same', True)
    assert len(retried['turns']) == 1
    assert retried['turns'][0]['status'] == 'succeeded'
    with learning_database.transaction() as c:
        c.execute("UPDATE learning_discussion_turn SET status='running' WHERE id=?", (retried['turns'][0]['id'],))
    discussions.recover()
    assert discussions.get(IDENTITY, thread['id'])['turns'][0]['reason'] == 'interrupted'


@pytest.mark.asyncio
async def test_027_upgrade_preserves_answers_and_enables_discussions_only_after_upgrade(tmp_path):
    from pathlib import Path
    from app.db import Database, DatabaseSchemaError
    from app.learning_storage import open_learning_database
    from app.learning_production import upgrade_learning_database

    path = tmp_path / 'learning.sqlite3'
    migrations = Path(__file__).resolve().parents[1] / 'app' / 'migrations'
    old = Database(path, migrations, migration_floor=11, migration_ceiling=27)
    verification_service(old, []).learning.principal(IDENTITY)
    service, current = await attempt(old)
    old.close()
    with pytest.raises(DatabaseSchemaError, match='028_verification_discussions'):
        open_learning_database(path, migrate=False)
    result = upgrade_learning_database(path, tmp_path / 'backups', authorized=True)
    assert result['status'] == 'upgraded'
    upgraded = open_learning_database(path, migrate=False)
    try:
        current_service = verification_service(upgraded, [])
        detail = LearningRecords(current_service).detail(IDENTITY, current['id'])
        assert detail['content']['responses']['q1'] == '合成原始作答'
        assert detail['result'] == json.loads(PASS)
        thread = QuestionDiscussionService(current_service).create(IDENTITY, current['id'], current['latest_submission_id'], 'q1', 'post-upgrade-discussion')
        assert thread['source']['answer'] == '合成原始作答'
        assert upgraded.fetchall('PRAGMA foreign_key_check') == []
    finally:
        upgraded.close()
