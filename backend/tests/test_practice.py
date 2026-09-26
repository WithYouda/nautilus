import asyncio
import json

import httpx
import pytest

from app.learning_domain import DomainError
from app.outcome_review import OutcomeReview
from app.practice import PracticeService, PracticeCreate, PracticeAnswer, PracticeRun
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY, OWNER, response_transport
from test_verification_review import attempt


def proposal(question, answer, *, operation='exercise', status='supported'):
    basis = [dict(source='answer', quote=answer)]
    return json.dumps(dict(review=dict(status=status,summary='合成复核：练习只覆盖原范围',basis=basis),
        exercise=None if operation == 'recheck' or status == 'insufficient' else dict(kind='new_situation',focus='optional',
            reason='合成依据：检查同一边界',basis=basis,prompt='合成新情境：换一种输入解释边界',answer_guidance='SYNTHETIC_HIDDEN_GUIDANCE')))


async def setup(db):
    verification, current = await attempt(db)
    row = db.fetchone('SELECT id FROM learning_verification_evaluation WHERE submission_id=?', (current['latest_submission_id'],))
    payload = PracticeCreate(submission_id=current['latest_submission_id'],evaluation_id=row[0],question_id='q1',request_key='proposal')
    source_answer='合成原始作答'
    verification.transport=response_transport([proposal('',source_answer)])
    service=PracticeService(verification)
    return service,current,payload


@pytest.mark.asyncio
async def test_practice_keeps_original_versions_answers_and_help_conditions(learning_database):
    service,current,payload=await setup(learning_database)
    service.verification.confirm(IDENTITY, current['id'], current['latest_submission_id'], payload.evaluation_id)
    before=[tuple(row) for row in learning_database.fetchall('SELECT * FROM learning_event')]
    original=dict(learning_database.fetchone('SELECT * FROM learning_verification WHERE id=?',(current['id'],)))
    practice=await service.create(IDENTITY,current['id'],payload)
    assert practice['status']=='ready'
    assert 'SYNTHETIC_HIDDEN_GUIDANCE' not in json.dumps(practice)
    assert (await service.create(IDENTITY,current['id'],payload))['id']==practice['id']
    with pytest.raises(DomainError,match='idempotency_conflict'):
        await service.create(IDENTITY,current['id'],payload.model_copy(update={'requested_kind':'redo'}))
    service.choose(IDENTITY,practice['id'],'start')
    first=service.submit(IDENTITY,practice['id'],PracticeAnswer(answer='合成答案甲',evidence_condition='independent',request_key='one'))
    attempt_id=first['attempts'][0]['id']
    service.verification.transport=httpx.MockTransport(lambda _: httpx.Response(500))
    failed=await service.run(IDENTITY,practice['id'],PracticeRun(kind='evaluation',attempt_id=attempt_id,request_key='bad'))
    assert failed['runs'][0]['status']=='failed'
    assert failed['attempts'][0]['answer']=='合成答案甲'
    service.verification.transport=response_transport([json.dumps(dict(text='先看输入边界'))])
    hint=await service.run(IDENTITY,practice['id'],PracticeRun(kind='hint',request_key='hint'))
    shown=service.display(IDENTITY,practice['id'],hint['runs'][0]['id'])
    assert shown['runs'][0]['displayed_at']
    assert service.display(IDENTITY,practice['id'],hint['runs'][0]['id'])==shown
    assert shown['attempts'][0]['condition']['records']==[]
    second=service.submit(IDENTITY,practice['id'],PracticeAnswer(answer='合成答案乙',evidence_condition='independent',request_key='two'))
    assert second['attempts'][0]['condition']['evidence_condition']=='with_materials'
    assert second['attempts'][0]['condition']['user_report']=='independent'
    assert second['attempts'][0]['condition']['attempt_kind']=='same_question_retry'
    assert second['attempts'][1]==first['attempts'][0]
    service.verification.transport=response_transport([json.dumps(dict(assessment='meets',feedback='合成反馈',answer_quote='合成答案乙',remaining=[],next_step='可暂不继续'))])
    result=await service.run(IDENTITY,practice['id'],PracticeRun(kind='evaluation',attempt_id=second['attempts'][0]['id'],request_key='good'))
    assert result['runs'][0]['result']['assessment']=='meets'
    outcome=learning_database.fetchone('SELECT outcome_id FROM learning_delegation WHERE id=?',(current['delegation_id'],))[0]
    assert OutcomeReview(service.verification).get(IDENTITY,outcome)['practices'][0]['latest_feedback']=='合成反馈'
    assert [tuple(row) for row in learning_database.fetchall('SELECT * FROM learning_event')]==before
    assert dict(learning_database.fetchone('SELECT * FROM learning_verification WHERE id=?',(current['id'],)))==original
    with pytest.raises(DomainError):
        service.get({**IDENTITY,'id':'other'},practice['id'])


@pytest.mark.asyncio
async def test_dispute_review_precedes_practice_and_source_deletion_wins(learning_database):
    service,current,payload=await setup(learning_database)
    service.verification.transport=response_transport([proposal('','合成原始作答',operation='recheck',status='corrected')])
    review=await service.create(IDENTITY,current['id'],payload.model_copy(update={'operation':'recheck','objection':'原反馈依据不足'}))
    assert review['content']['exercise'] is None and review['status']=='reviewed'
    with pytest.raises(DomainError):
        service.choose(IDENTITY,review['id'],'start')
    started=asyncio.Event(); release=asyncio.Event()
    async def provider(_):
        started.set(); await release.wait()
        return httpx.Response(200,json={'choices':[{'message':{'content':proposal('','合成原始作答')}}]})
    service.verification.transport=httpx.MockTransport(provider)
    task=asyncio.create_task(service.create(IDENTITY,current['id'],payload.model_copy(update={'request_key':'child','recheck_id':review['id']})))
    await started.wait()
    service.purge(IDENTITY,review['id'])
    release.set()
    late=await task
    assert late['purged_at'] and late['content'] is None
    assert learning_database.fetchone('SELECT purged_at FROM learning_verification WHERE id=?',(current['id'],))[0] is None


@pytest.mark.asyncio
async def test_invalid_quotation_and_missing_feedback_do_not_generate_false_practice(learning_database):
    service,current,payload=await setup(learning_database)
    service.verification.transport=response_transport([proposal('','并不在原答案中的文字')])
    invalid=await service.create(IDENTITY,current['id'],payload)
    assert invalid['status']=='failed' and invalid['content'] is None
    with pytest.raises(DomainError):
        await service.create(IDENTITY,current['id'],payload.model_copy(update={'request_key':'wrong-question','question_id':'q-other'}))
    service.verification.purge(IDENTITY,current['id'])
    assert service.get(IDENTITY,invalid['id'])['purged_at']


@pytest.mark.asyncio
async def test_redo_preserves_source_help_without_relabeling_self_report(learning_database):
    service,current,payload=await setup(learning_database)
    response=json.loads(proposal('', '合成原始作答'))
    response['exercise']['kind']='redo'
    service.verification.transport=response_transport([json.dumps(response)])
    practice=await service.create(IDENTITY,current['id'],payload.model_copy(update={'requested_kind':'redo'}))
    service.choose(IDENTITY,practice['id'],'start')
    result=service.submit(IDENTITY,practice['id'],PracticeAnswer(answer='合成重做答案',evidence_condition='independent',request_key='redo'))
    condition=result['attempts'][0]['condition']
    assert condition['attempt_kind']=='redo' and condition['user_report']=='independent'
    assert condition['evidence_condition']=='with_materials'
    assert condition['records'][0]['kind']=='source_feedback'
    assert condition['records'][0]['displayed_at'] is None
