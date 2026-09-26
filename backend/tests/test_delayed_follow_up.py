"""Bounded follow-up: actual interval, independent storage, exposure and ownership."""
import json

import pytest
from pydantic import ValidationError

from app import delayed_follow_up as module
from app.delayed_follow_up import (
    DelayedFollowUpService, CreateFollowUp, DraftAnswer, SubmitAnswer,
    ScheduleFollowUp, ChooseFollowUp, approved_standard,
)
from app.learning_domain import DomainError
from test_evidence_claims import authorize, create_standard_chain


@pytest.fixture
def context(client):
    identity = authorize(client)
    chain = create_standard_chain(client)
    now = ['2026-09-26T15:55:00Z']
    service = DelayedFollowUpService(client.app.state.learning, clock=lambda: now[0])
    outcome = chain['standard']['outcome_id']
    payload = CreateFollowUp(source_artifact_id=chain['artifact']['id'], source_content_version=1, request_key='create')
    item = service.create(identity, outcome, payload)
    return service, identity, chain, now, item, payload


def answer(service, identity, item, *, report='none'):
    attempt = next(a for a in item['attempts'] if a['id'] == item['active_attempt_id'])
    values = {f"{attempt['phase']}-{n}": value for n,value in enumerate([True,False,False,False,True,True,False,False],1)}
    payload = SubmitAnswer(revision=attempt['revision'], answers=values, user_report=report, request_key='submit-'+attempt['id'])
    return service.submit(identity,item['id'],attempt['id'],payload), attempt['id'], payload


def schedule(service, identity, item, *, key='schedule', date='2026-09-29T15:55:00Z'):
    return service.schedule(identity,item['id'],ScheduleFollowUp(due_at=date,timezone='Asia/Shanghai',request_key=key))


def start(service, identity, item):
    return service.choose(identity,item['id'],ChooseFollowUp(choice='start',request_key='start'))


def stable_tables(db):
    return {name: [tuple(row) for row in db.fetchall(f'SELECT * FROM {name} ORDER BY rowid')]
        for name in ('learning_event','learning_delegation','learning_criterion_version','learning_evidence_claim','learning_derived_state')}


def test_complete_actual_interval_and_retry_preserve_old_facts(context):
    s,i,chain,clock,item,create = context
    # Public standard and initial response contain no expected outcomes or B bank.
    assert 'banks' not in item['standard']
    assert all('expected' not in x for x in item['items'])
    assert 'CD34' not in json.dumps(item)
    before = stable_tables(s.db)
    item,initial,payload = answer(s,i,item)
    assert item['attempts'][0]['answers'] is None
    assert item['attempts'][0]['check_status']=='not_checked'
    assert s.submit(i,item['id'],initial,payload)==item
    item=s.check(i,item['id'],initial)
    result=s.reveal(i,item['id'],initial)
    assert result['result']['correct']==8
    assert result['result']['standard_hash']==approved_standard()['content_hash']
    item=schedule(s,i,item)
    assert not item['is_due'] and item['items']==[]
    with pytest.raises(DomainError,match='delayed_not_due'):
        start(s,i,item)
    clock[0]='2026-09-29T15:55:00Z'
    item=start(s,i,item)
    assert len(item['attempts'])==2
    clock[0]='2026-09-29T16:05:00Z'
    item,later,_=answer(s,i,item)
    assert item['comparison'] is None and item['status']=='completed'
    item=s.check(i,item['id'],later)
    assert item['comparison']['interval_seconds']==3*86400+600
    assert '自报未使用帮助，未独立核实' in item['comparison']['description']
    assert s.due_list(i)['items']==[]
    assert stable_tables(s.db)==before
    assert s.create(i,chain['standard']['outcome_id'],create.model_copy(update={'request_key':'new-key'}))['id']==item['id']
    with pytest.raises(DomainError,match='delayed_schedule_unavailable'):
        schedule(s,i,item,key='again',date='2026-10-03T00:00:00Z')


def test_draft_conflict_incomplete_submit_and_failed_check_recovery(context,monkeypatch):
    s,i,_,_,item,_=context
    a=item['active_attempt_id']
    draft=DraftAnswer(revision=0,answers={'initial-1':True})
    item=s.draft(i,item['id'],a,draft)
    assert s.get(i,item['id'])['attempts'][0]['answers']=={'initial-1':True}
    with pytest.raises(DomainError,match='delayed_stale_answer'):
        s.draft(i,item['id'],a,draft)
    with pytest.raises(DomainError,match='delayed_incomplete_answer'):
        s.submit(i,item['id'],a,SubmitAnswer(revision=1,answers={'initial-1':True},request_key='incomplete'))
    with pytest.raises(ValidationError):
        DraftAnswer(revision=1,answers={'initial-1':'false'})
    item,a,_=answer(s,i,item)
    checker=module.check_answers
    def fail(*args):
        raise ValueError('synthetic check failure')
    monkeypatch.setattr(module,'check_answers',fail)
    item=s.check(i,item['id'],a)
    assert item['attempts'][0]['check_status']=='failed'
    saved=s.reveal(i,item['id'],a)
    assert len(saved['answers'])==8 and len(saved['items'])==8
    assert all('expected' not in x for x in saved['items'])
    monkeypatch.setattr(module,'check_answers',checker)
    item=s.check(i,item['id'],a)
    assert item['attempts'][0]['check_status']=='succeeded'
    monkeypatch.setattr(module,'check_answers',fail)
    assert s.check(i,item['id'],a)['attempts'][0]['check_status']=='succeeded'


@pytest.mark.parametrize('date,tz',[
    ('2026-09-27T00:05:00+08:00','Asia/Shanghai'), # midnight crossed, only ten minutes
    ('2026-09-27T15:54:59Z','UTC'),
    ('2026-09-29T15:55:00','UTC'),
    ('2026-09-29T15:55:00Z','not/a/zone'),
])
def test_schedule_rejects_short_or_ambiguous_interval(context,date,tz):
    s,i,_,_,item,_=context
    item,a,_=answer(s,i,item)
    s.check(i,item['id'],a)
    with pytest.raises(DomainError):
        s.schedule(i,item['id'],ScheduleFollowUp(due_at=date,timezone=tz,request_key='bad-time'))


def test_skip_reschedule_preserves_first_exposure_and_draft(context):
    s,i,_,clock,item,_=context
    item,a,_=answer(s,i,item)
    s.check(i,item['id'],a)
    item=schedule(s,i,item,date='2026-09-27T23:55:00+08:00') # exact 24h, UTC comparison
    first_arranged=item['arranged_at']
    clock[0]='2026-09-27T15:55:00Z'
    item=start(s,i,item)
    later=item['active_attempt_id']
    s.draft(i,item['id'],later,DraftAnswer(revision=0,answers={'followup-1':True}))
    exposed=s.reveal(i,item['id'],a)
    item=s.choose(i,item['id'],ChooseFollowUp(choice='skip',request_key='skip'))
    assert item['items']==[] and s.due_list(i)['items']==[]
    item=schedule(s,i,item,key='reschedule',date='2026-09-30T00:00:00Z')
    assert item['arranged_at']==first_arranged
    clock[0]='2026-09-30T00:00:00Z'
    item=s.choose(i,item['id'],ChooseFollowUp(choice='start',request_key='restart'))
    assert item['active_attempt_id']==later and len(item['attempts'])==2
    assert item['attempts'][1]['answers']=={'followup-1':True}
    item,_,_=answer(s,i,item)
    condition=item['attempts'][1]['condition']
    assert condition['observed_views'][0]['after_arranging'] is True
    assert condition['observed_views'][0]['displayed_at'] is None
    s.display(i,item['id'],exposed['view_id'])
    assert s.get(i,item['id'])['attempts'][1]['condition']==condition
    item=s.check(i,item['id'],later)
    assert '安排后的资料提供或展示记录' in item['comparison']['description']
    assert s.get(i,item['id'])['attempts'][0]['condition']['observed_views']==[]
    assert all('request_key' not in entry for entry in item['history'])


@pytest.mark.parametrize('report,expected',[('used','自报帮助'),('unknown','帮助条件不确定')])
def test_comparison_does_not_infer_independence(context,report,expected):
    s,i,_,clock,item,_=context
    item,a,_=answer(s,i,item,report=report)
    s.check(i,item['id'],a)
    schedule(s,i,item)
    clock[0]='2026-09-29T15:55:00Z'
    item=start(s,i,item)
    item,a,_=answer(s,i,item)
    item=s.check(i,item['id'],a)
    assert expected in item['comparison']['description']


def test_owner_source_visibility_and_purge_boundary(context):
    s,i,chain,_,item,payload=context
    other={**i,'id':'other-owner','device_id':'other-device'}
    with pytest.raises(DomainError,match='not_found'):
        s.get(other,item['id'])
    with pytest.raises(DomainError,match='delayed_source_unavailable'):
        s.create(i,chain['standard']['outcome_id'],payload.model_copy(update={'request_key':'wrong-version','source_content_version':99}))
    item,a,_=answer(s,i,item)
    with s.db.transaction() as c:
        c.execute("UPDATE learning_artifact SET visibility='soft_deleted' WHERE id=?",(chain['artifact']['id'],))
    private=s.get(i,item['id'])
    assert private['available'] is False and private['standard'] is None
    assert private['attempts'][0]['condition'] is None
    with pytest.raises(DomainError,match='delayed_source_unavailable'):
        s.reveal(i,item['id'],a)
    item=s.purge(i,item['id'])
    assert item['status']=='purged'
    assert s.db.fetchone('SELECT answers_json FROM learning_delayed_attempt WHERE id=?',(a,))[0] is None


def test_api_auth_validation_no_store_and_single_series(client):
    assert client.get('/api/learning/delayed-follow-ups').status_code==401
    authorize(client)
    chain=create_standard_chain(client)
    url=f"/api/learning/outcomes/{chain['standard']['outcome_id']}/delayed-follow-ups"
    result=client.get(url)
    assert result.status_code==200 and result.headers['cache-control']=='no-store'
    data={'source_artifact_id':chain['artifact']['id'],'source_content_version':1,'request_key':'api-create'}
    result=client.post(url,json=data)
    assert result.status_code==200
    item=result.json()
    assert client.post(url,json={**data,'request_key':'api-retry'}) .json()['id']==item['id']
    assert client.post(url,json={**data,'source_content_version':2}).status_code==409
    assert client.post(f"/api/learning/delayed-follow-ups/{item['id']}/choice",json={'choice':'start','request_key':'early'}).status_code==409
    purged=client.post(f"/api/learning/delayed-follow-ups/{item['id']}/purge")
    assert purged.status_code==200 and purged.json()['status']=='purged'
    assert purged.json()['purge']['status']=='complete'
    assert client.get(f"/api/learning/purges/delayed/{item['id']}").json()['status']=='complete'
    assert client.post(url,json=data).status_code==409
    assert client.post(url,json={**data,'request_key':'create-after-purge'}).json()['status']=='purged'



def test_answer_provided_before_arranging_but_displayed_after_is_recorded(context):
    s,i,_,clock,item,_=context
    item,a,_=answer(s,i,item)
    s.check(i,item['id'],a)
    view=s.reveal(i,item['id'],a)
    schedule(s,i,item)
    # Same timestamp, but first page display really happened after arranging.
    s.display(i,item['id'],view['view_id'])
    clock[0]='2026-09-29T15:55:00Z'
    item=start(s,i,item)
    item,_,_=answer(s,i,item)
    assert item['attempts'][1]['condition']['observed_views'][0]['after_arranging'] is True


def test_without_approved_regex_relationship_no_source_is_offered(client):
    from test_learning_facts_api import create_fact_chain
    authorize(client)
    chain=create_fact_chain(client)
    url=f"/api/learning/outcomes/{chain['outcome']['id']}/delayed-follow-ups"
    assert client.get(url).json()['sources']==[]
    response=client.post(url,json={'source_artifact_id':chain['artifact']['id'],
        'source_content_version':1,'request_key':'unrelated'})
    assert response.status_code==409
