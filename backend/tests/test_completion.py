import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from app.completion import CompletionRequest, CompletionService
from app.continuity import ContinuityService, record_usage
from app.core.commands import CreateDelegation
from app.learning_domain import DomainError
from app.outcome_review import OutcomeReview
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY, OWNER, FAIL, create_context, verification_service, response_transport
from test_verification_review import attempt


MATERIAL = '合成成绩：60分；评分表未提供。'
OPINION = dict(summary='仅观察这份材料', findings=[dict(kind='insufficient', quote=MATERIAL,
    comment='无法核对评分依据')], limitations='未核验机构、真伪和本人独立完成情况', next_step='可以补充评分表')


def request(kind='unverified', key='completion'):
    return CompletionRequest(request_key=key, verification_kind=kind, note='合成完成说明',
        report=None if kind == 'unverified' else dict(method='合成线下考试', result='未通过'),
        material=dict(kind='result', label='合成成绩材料', text=MATERIAL) if kind == 'external_material' else None)


@pytest.mark.parametrize('kind', ['unverified', 'external_material', 'external_report'])
def test_completion_without_provider_keeps_user_report_separate_and_replays(learning_database, kind):
    context = create_context(learning_database, start=False)
    verification = verification_service(learning_database, [])
    service = CompletionService(verification)
    before_claims = learning_database.fetchone('SELECT COUNT(*) FROM learning_evidence_claim')[0]
    payload = request(kind)
    result = service.create(IDENTITY, context['delegation_id'], payload)
    assert service.create(IDENTITY, context['delegation_id'], payload)['id'] == result['id']
    assert result['verification_kind'] == kind and result['reviews'] == []
    assert result['content']['report'] == (None if kind == 'unverified' else {'method': '合成线下考试', 'result': '未通过'})
    assert learning_database.fetchone('SELECT status FROM learning_delegation WHERE id=?', (context['delegation_id'],))[0] == 'completed'
    assert learning_database.fetchone('SELECT COUNT(*) FROM learning_verification')[0] == 0
    assert learning_database.fetchone('SELECT COUNT(*) FROM learning_evidence_claim')[0] == before_claims
    events = '\n'.join(r[0] for r in learning_database.fetchall('SELECT payload_json FROM learning_event'))
    assert result['id'] in events and '合成完成说明' not in events and MATERIAL not in events
    verification.learning.core.replay(OWNER)
    assert service.get(IDENTITY, context['delegation_id']) == result
    card = ContinuityService(verification.learning).get(IDENTITY)
    assert card['recommendation']['reason_code'] == 'completed'
    assert card['what_happened']['completion']['verification_kind'] == kind
    outcome = learning_database.fetchone('SELECT outcome_id FROM learning_delegation WHERE id=?', (context['delegation_id'],))[0]
    assert OutcomeReview(verification).get(IDENTITY, outcome)['completions'][0]['id'] == result['id']
    with pytest.raises(DomainError, match='not_found'):
        service.get({**IDENTITY, 'id': 'owner-b'}, context['delegation_id'])
    with pytest.raises(DomainError, match='not_found'):
        service.purge({**IDENTITY, 'id': 'owner-b'}, result['id'])


def test_other_delegations_stay_open_and_material_without_validation_is_unverified(learning_database):
    context = create_context(learning_database)
    verification = verification_service(learning_database, [])
    core = verification.learning.core
    original = learning_database.fetchone('SELECT outcome_id FROM learning_delegation WHERE id=?', (context['delegation_id'],))[0]
    other = core.execute(OWNER, CreateDelegation(action_id=context['action_id'], outcome_id=original, boundaries='',
        stop_conditions='另一次任务', expected_version=3), 'other')
    service = CompletionService(verification)
    payload = request().model_copy(update={'material': None})
    service.create(IDENTITY, context['delegation_id'], payload)
    assert learning_database.fetchone('SELECT status FROM learning_delegation WHERE id=?', (other['id'],))[0] == 'ready'
    assert learning_database.fetchone('SELECT status FROM learning_action WHERE id=?', (context['action_id'],))[0] == 'open'
    assert learning_database.fetchone('SELECT status FROM learning_session WHERE id=?', (context['session_id'],))[0] == 'ended'
    assert learning_database.fetchone("SELECT COUNT(*) FROM learning_usage_event WHERE kind='completed'")[0] == 0
    with pytest.raises(ValidationError):
        CompletionRequest(request_key='bad', verification_kind='external_material', material={'kind': 'work', 'label': '只有作品', 'text': '无已有验证'})
    work = CompletionRequest(request_key='work', verification_kind='unverified', material={'kind': 'work', 'label': '作品', 'text': '待审阅'})
    assert work.report is None


async def test_failed_ai_attempt_is_preserved_and_completion_updates_continuity_metrics(learning_database):
    verification, old = await attempt(learning_database, response=FAIL)
    before_card = ContinuityService(verification.learning).get(IDENTITY)
    with learning_database.transaction() as connection:
        record_usage(connection, IDENTITY['id'], 'started', 'test-start', review_id=before_card['id'],
            action_id=old['action_id'], delegation_id=old['delegation_id'], session_id=old['session_id'])
    service = CompletionService(verification)
    before = verification._owned(IDENTITY['id'], old['id'])
    service.create(IDENTITY, old['delegation_id'], request())
    assert verification._owned(IDENTITY['id'], old['id']) == before
    card = ContinuityService(verification.learning).get(IDENTITY)
    assert card['recommendation']['kind'] == 'choose_next'
    assert card['what_happened']['verification_status'] == 'failed'
    assert card['what_happened']['completion']['verification_kind'] == 'unverified'
    assert learning_database.fetchone("SELECT COUNT(*) FROM learning_usage_event WHERE kind='completed'")[0] == 1
    with pytest.raises(DomainError):
        await verification.submit(IDENTITY, old['id'], dict(request_key='late', responses={'q1': '不能覆盖已完成委托'}))


def test_return_card_follows_new_completion_even_without_a_learning_session(learning_database):
    first = create_context(learning_database)
    verification = verification_service(learning_database, [])
    service = CompletionService(verification)
    service.create(IDENTITY, first['delegation_id'], request())
    second = create_context(learning_database, key='without-session', start=False)
    service.create(IDENTITY, second['delegation_id'], request('external_report', 'second'))
    card = ContinuityService(verification.learning).get(IDENTITY)
    assert card['position']['delegation_id'] == second['delegation_id']
    assert card['position']['last_session'] is None
    assert card['what_happened']['completion']['verification_kind'] == 'external_report'


async def test_optional_review_failure_retry_response_and_purge_do_not_change_original_report(learning_database):
    context = create_context(learning_database)
    verification = verification_service(learning_database, ['invalid json', json.dumps(OPINION, ensure_ascii=False)])
    service = CompletionService(verification)
    saved = service.create(IDENTITY, context['delegation_id'], request('external_material'))
    failed = await service.review(IDENTITY, saved['id'], 'review-fail')
    assert failed['reviews'][0]['status'] == 'failed'
    reviewed = await service.review(IDENTITY, saved['id'], 'review-retry')
    assert reviewed['reviews'][0]['status'] == 'succeeded'
    assert reviewed['content'] == saved['content']
    assert len((await service.review(IDENTITY, saved['id'], 'review-retry'))['reviews']) == 2
    response = service.respond(IDENTITY, saved['id'], reviewed['reviews'][0]['id'], '我的合成回应')
    assert response['reviews'][0]['user_response'] == '我的合成回应'
    assert response['reviews'][0]['result'] == OPINION
    assert learning_database.fetchone('SELECT COUNT(*) FROM learning_evidence_claim')[0] == 0
    service.purge(IDENTITY, saved['id'])
    verification.learning.core.replay(OWNER)
    erased = service.get(IDENTITY, context['delegation_id'])
    assert erased['purged_at'] and erased['content'] is None and erased['contract'] is None
    assert all(r['result'] is None and r['user_response'] is None for r in erased['reviews'])
    serialized = json.dumps(erased, ensure_ascii=False)
    assert MATERIAL not in serialized and '我的合成回应' not in serialized
    with pytest.raises(DomainError, match='completion_content_deleted'):
        await service.review(IDENTITY, saved['id'], 'after-purge')
    with pytest.raises(DomainError, match='completion_content_deleted'):
        service.create(IDENTITY, context['delegation_id'], request('external_material'))


async def test_late_review_cannot_revive_deleted_material_and_interrupted_runs_can_retry(learning_database):
    context = create_context(learning_database)
    verification = verification_service(learning_database, [])
    service = CompletionService(verification)
    saved = service.create(IDENTITY, context['delegation_id'], request('external_material'))
    started, release = asyncio.Event(), asyncio.Event()
    async def provider(_request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(OPINION)}}]})
    verification.transport = httpx.MockTransport(provider)
    task = asyncio.create_task(service.review(IDENTITY, saved['id'], 'running'))
    await started.wait()
    service.purge(IDENTITY, saved['id'])
    release.set()
    result = await task
    assert result['reviews'][0]['result'] is None and result['content'] is None
    assert learning_database.fetchone('SELECT result_json FROM learning_completion_review')[0] is None

    fresh = create_context(learning_database, key='next')
    saved2 = service.create(IDENTITY, fresh['delegation_id'], request('external_material', 'next'))
    with learning_database.transaction() as connection:
        connection.execute('''INSERT INTO learning_completion_review (id,owner_id,completion_id,request_key,status,created_at)
            VALUES ('interrupted','owner-a',?,'interrupted','running','2026-09-26')''', (saved2['id'],))
    service.recover()
    assert service.get(IDENTITY, fresh['delegation_id'])['reviews'][0]['status'] == 'failed'
    verification.transport = response_transport([json.dumps({**OPINION, 'findings': [dict(kind='issue', quote='不存在的引文', comment='不可追溯')]}), json.dumps(OPINION)])
    assert (await service.review(IDENTITY, saved2['id'], 'bad-quote'))['reviews'][0]['status'] == 'failed'
    assert (await service.review(IDENTITY, saved2['id'], 'retry'))['reviews'][0]['status'] == 'succeeded'
