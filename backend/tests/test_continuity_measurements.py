import pytest
from uuid import uuid4
from app.learning_service import LearningService
from app.measurements import MeasurementService
from app.core.commands import EndSession, StartSession
from test_learning_fact_hardening import core, running, save, USER
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY


def test_unlinked_session_and_success_audit_are_not_product_evidence(core, running):
    artifact = save(core, running)
    core.execute(USER, EndSession(session_id=running['session']['id'], disposition='interrupted', expected_version=4), 'interrupt')
    new = core.execute(USER, StartSession(delegation_id=running['delegation']['id'], expected_version=5), 'resume')
    core.execute(USER, EndSession(session_id=new['id'], disposition='ended', expected_version=6), 'end')
    with core.database.transaction() as c:
        c.execute("INSERT INTO learning_audit VALUES (?, 'owner-a', 'owner-a', 'Replay', 'succeeded', NULL, NULL, '2026-09-19')", (str(uuid4()),))
    report = MeasurementService(LearningService(core.database)).report(IDENTITY)
    assert report.product_metrics['interrupted_delegation_recovery'].status == 'no_sample'
    assert report.product_metrics['review_to_next_action'].status == 'no_sample'
    assert report.hard_guards['event_rebuild_consistency'].status == 'no_sample'
    core.replay(USER)
    assert MeasurementService(LearningService(core.database)).report(IDENTITY).hard_guards['event_rebuild_consistency'].status == 'pass'


def test_linked_recovery_correction_and_action_completion_contract(core, running):
    db = core.database
    now='2026-09-19T00:00:00Z'
    with db.transaction() as c:
        c.execute('INSERT INTO learning_return_review VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)',
            ('review', 'owner-a', 'context', running['session']['id'], running['action']['id'], running['delegation']['id'], 'resume','interrupted',now))
        def event(kind, stamp=now):
            c.execute('INSERT INTO learning_usage_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (str(uuid4()), 'owner-a','review',kind,running['action']['id'],running['delegation']['id'],running['session']['id'],kind,stamp))
        for kind in ('review_card_shown','resume_candidate_presented','continue','started','entered'): event(kind)
    metrics=MeasurementService(LearningService(db))
    assert metrics.report(IDENTITY).product_metrics['interrupted_delegation_recovery'].status=='observed'
    assert metrics.report(IDENTITY).product_metrics['interrupted_delegation_recovery'].value==1
    assert metrics.report(IDENTITY).product_metrics['review_to_next_action'].numerator==0
    with db.transaction() as c:
        for kind in ('corrected','completed'):
            c.execute('INSERT INTO learning_usage_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (str(uuid4()),'owner-a','review',kind,running['action']['id'],running['delegation']['id'],running['session']['id'],kind,'2026-09-19T01:00:00Z'))
    assert metrics.report(IDENTITY).product_metrics['interrupted_delegation_recovery'].value==0
    assert metrics.report(IDENTITY).product_metrics['review_to_next_action'].numerator==0

from app.continuity import ContinuityService
from app.learning_domain import DomainError


def test_card_return_choices_are_owned_idempotent_and_linked(core, running):
    learning = LearningService(core.database)
    continuity = ContinuityService(learning)
    core.execute(USER, EndSession(session_id=running['session']['id'], disposition='interrupted', expected_version=3), 'interrupt')
    card = continuity.get(IDENTITY)
    assert card['recommendation']['reason_code']=='interrupted'
    assert continuity.get(IDENTITY)['id']==card['id']
    assert card['supported']==[] and card['unknowns']
    continuity.decide(IDENTITY, card['id'], 'review_card_shown', 'shown')
    result=continuity.decide(IDENTITY, card['id'], 'continue', 'choose')
    assert result==continuity.decide(IDENTITY, card['id'], 'continue', 'repeat')
    assert result['session_id']!=running['session']['id']
    assert core.database.fetchone('SELECT delegation_id FROM learning_session WHERE id=?',(result['session_id'],))[0]==running['delegation']['id']
    continuity.decide(IDENTITY, card['id'], 'entered', 'entered', session_id=result['session_id'])
    assert MeasurementService(learning).report(IDENTITY).product_metrics['interrupted_delegation_recovery'].value==1
    continuity.decide(IDENTITY, card['id'], 'corrected', 'corrected')
    assert MeasurementService(learning).report(IDENTITY).product_metrics['interrupted_delegation_recovery'].value==0
    with pytest.raises(DomainError, match='not_found'):
        continuity.decide({**IDENTITY,'id':'owner-b','device_id':'owner-b-device'},card['id'],'continue','foreign')

@pytest.mark.asyncio
async def test_completed_verification_returns_honest_card_without_plan_mutation(learning_database):
    from test_verification_evidence import chain
    service, evidence, events, saved = await chain(learning_database)
    evaluated=await service.evaluate(IDENTITY,saved['id'],saved['latest_submission_id'],'evaluate')
    service.confirm(IDENTITY,saved['id'],saved['latest_submission_id'],evaluated['evaluation']['id'])
    continuity=ContinuityService(service.learning)
    card=continuity.get(IDENTITY)
    assert card['what_happened']['verification_status']=='passed'
    assert card['supported']==[]
    assert card['recommendation']['kind']=='choose_next'
    assert continuity.decide(IDENTITY,card['id'],'continue','next')['destination']=='setup'
    assert learning_database.fetchone('SELECT COUNT(*) FROM learning_action')[0]==1

@pytest.mark.asyncio
async def test_recommended_execution_requires_formal_completion(learning_database, monkeypatch):
    from test_verification_evidence import chain
    service, _, _, saved = await chain(learning_database)
    continuity = ContinuityService(service.learning)
    card = continuity.get(IDENTITY)
    assert card['recommendation']['reason_code']=='running'
    continuity.decide(IDENTITY,card['id'],'review_card_shown','shown')
    result=continuity.decide(IDENTITY,card['id'],'continue','continue')
    assert result['destination']=='verification'
    continuity.decide(IDENTITY,card['id'],'entered','entered',session_id=result['session_id'])
    metrics = MeasurementService(service.learning)
    assert metrics.report(IDENTITY).product_metrics['review_to_next_action'].numerator == 0
    evaluated=await service.evaluate(IDENTITY,saved['id'],saved['latest_submission_id'],'evaluate')
    assert metrics.report(IDENTITY).product_metrics['review_to_next_action'].numerator == 0
    from datetime import datetime, timedelta
    started=learning_database.fetchone("SELECT created_at FROM learning_usage_event WHERE kind='started'")[0]
    earlier=(datetime.fromisoformat(started.replace('Z','+00:00'))-timedelta(seconds=2)).isoformat().replace('+00:00','Z')
    monkeypatch.setattr('app.continuity.utc_timestamp', lambda: earlier)
    service.confirm(IDENTITY,saved['id'],saved['latest_submission_id'],evaluated['evaluation']['id'])
    metric=metrics.report(IDENTITY).product_metrics['review_to_next_action']
    assert (metric.status, metric.numerator, metric.denominator)==('observed',1,1)

@pytest.mark.asyncio
async def test_setup_change_measurement_has_no_private_text(learning_database):
    import json
    from test_learning_setup import draft_payload, setup_service, identity_payload
    service=setup_service(learning_database,json.dumps(draft_payload(None)))
    identity=identity_payload()
    draft=await service.draft(identity,'Synthetic private learning intention')
    payload={k:v for k,v in draft.items() if k not in ('rationale','recommended_criterion_id','outcome_object','outcome_behavior')}
    payload.update(original_intent='Synthetic private learning intention',criterion_id=None,outcome_id=None,
        object_description=draft['outcome_object'],behavior=draft['outcome_behavior'])
    service.confirm(identity,payload,'original')
    assert learning_database.fetchone("SELECT COUNT(*) FROM learning_usage_event WHERE kind='setup_modified'")[0]==0
    payload['action_title']='Synthetic learner edit'
    service.confirm(identity,payload,'edited')
    service.confirm(identity,payload,'edited')
    assert learning_database.fetchone("SELECT COUNT(*) FROM learning_usage_event WHERE kind='setup_modified'")[0]==1
    rows=str([tuple(r) for r in learning_database.fetchall('SELECT * FROM learning_usage_event')])
    assert 'Synthetic' not in rows

@pytest.mark.asyncio
async def test_pending_review_and_failed_saved_attempt_recommendations(learning_database):
    from test_verification_evidence import chain
    service, evidence, _, saved=await chain(learning_database)
    continuity=ContinuityService(service.learning)
    await evidence.analyze(IDENTITY,saved['artifact_id'],'analysis')
    version=learning_database.fetchone('SELECT version FROM learning_action')[0]
    service.learning.core.execute(USER,EndSession(session_id=saved['session_id'],disposition='ended',expected_version=version),'end')
    card=continuity.get(IDENTITY)
    assert card['recommendation']['kind']=='review'
    assert continuity.decide(IDENTITY,card['id'],'continue','review')['destination']=='evidence'
    from app.review import ReviewService
    from app.state_derivation import StateDerivationService
    review=ReviewService(service.learning,StateDerivationService(service.learning))
    for claim in evidence.claims(IDENTITY):
        review.review(IDENTITY,claim['id'],'question',None,'question:'+claim['id'])
    card=continuity.get(IDENTITY)
    assert card['recommendation']['kind']=='supplemental_verification'
    assert card['recommendation']['verification_id']==saved['id']
    assert card['supported']==[]

def test_return_position_uses_committed_order_after_clock_moves_back(core, running, monkeypatch):
    from app import continuity as continuity_module
    from app.core import learning as core_module
    continuity=ContinuityService(LearningService(core.database))
    core.execute(USER,EndSession(session_id=running['session']['id'],disposition='ended',expected_version=3),'end-old')
    monkeypatch.setattr(core_module,'utc_timestamp',lambda:'2001-01-01T00:00:00Z')
    later=core.execute(USER,StartSession(delegation_id=running['delegation']['id'],expected_version=4),'later')
    core.execute(USER,EndSession(session_id=later['id'],disposition='interrupted',expected_version=5),'interrupt-later')
    assert continuity.get(IDENTITY)['position']['last_session']==later['id']
    assert continuity.get(IDENTITY)['recommendation']['reason_code']=='interrupted'

@pytest.mark.asyncio
async def test_formal_completion_after_resume_finishes_original_recommendation(learning_database):
    from test_verification_evidence import chain, WORK
    service, _, _, saved=await chain(learning_database)
    continuity=ContinuityService(service.learning)
    card=continuity.get(IDENTITY)
    continuity.decide(IDENTITY,card['id'],'review_card_shown','shown')
    continuity.decide(IDENTITY,card['id'],'continue','continue')
    version=learning_database.fetchone('SELECT version FROM learning_action')[0]
    core=service.learning.core
    core.execute(USER,EndSession(session_id=saved['session_id'],disposition='interrupted',expected_version=version),'interrupt')
    next_session=core.execute(USER,StartSession(delegation_id=saved['delegation_id'],expected_version=version+1),'resume')
    metrics=MeasurementService(service.learning)
    assert metrics.report(IDENTITY).product_metrics['review_to_next_action'].numerator==0
    verification=await service.start(IDENTITY,dict(action_id=saved['action_id'],delegation_id=saved['delegation_id'],session_id=next_session['id'],mode='user_material'),'verify-again')
    submission=await service.submit(IDENTITY,verification['id'],dict(material='Synthetic reference',learner_work=WORK,request_key='new-answer'))
    evaluated=await service.evaluate(IDENTITY,verification['id'],submission['latest_submission_id'],'evaluate')
    service.confirm(IDENTITY,verification['id'],submission['latest_submission_id'],evaluated['evaluation']['id'])
    assert metrics.report(IDENTITY).product_metrics['review_to_next_action'].numerator==1


def test_choosing_new_direction_pauses_running_session_and_retry_does_not_stop_next_one(core, running):
    continuity = ContinuityService(LearningService(core.database))
    card = continuity.get(IDENTITY)
    assert continuity.decide(IDENTITY, card['id'], 'choose_new', 'new-direction') == {'destination': 'setup'}
    assert core.database.fetchone('SELECT status FROM learning_session WHERE id=?', (running['session']['id'],))[0] == 'interrupted'
    version = core.database.fetchone('SELECT version FROM learning_action WHERE id=?', (running['action']['id'],))[0]
    resumed = core.execute(USER, StartSession(delegation_id=running['delegation']['id'], expected_version=version), 'resumed-after-new-choice')
    continuity.decide(IDENTITY, card['id'], 'choose_new', 'new-direction')
    assert core.database.fetchone('SELECT status FROM learning_session WHERE id=?', (resumed['id'],))[0] == 'running'
    kinds = [r[0] for r in core.database.fetchall('SELECT kind FROM learning_usage_event')]
    assert kinds.count('choose_other') == 1
    assert kinds.count('switched') == 1
    assert 'stop_for_now' not in kinds
