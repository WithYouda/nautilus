"""Synthetic owner journeys using the registered application and real Core."""
import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import httpx
import pytest
from app.commitments import Commitments
from app.core.commitment_commands import CommitmentCommand,StartCommitmentRun,FinishCommitmentRun
from app.core.commitments import (dispatch_commitment,apply_commitment_event,EVENT_TYPES,PROJECTION_TABLES,input_context)
from app.core.commands import EndSession,SaveTextArtifact
from app.learning_domain import Principal,DomainError
from app.learning_production import create_learning_backup,restore_learning_backup,ProductionLearningDatabaseError
from app.commitment_calibration import calibrate,DEMO_CONTEXT
from app.commitment_integrations import PURGE_TABLES,erase_managed
from app.providers import ProviderConfig
from app.routers import commitments as routes
from test_evidence_claims import authorize
from test_plan_organization import plan,task,get as org
from test_learning_paths import draft as path_draft,confirm as path_confirm
from test_managed_purge import absent,snapshot


@pytest.fixture
def arranged(client):
    db=client.app.state.learning.database
    assert db.fetchone("SELECT 1 FROM sqlite_master WHERE name='learning_session_feedback'")
    service=client.app.state.commitments
    identity=authorize(client);view=plan(client);plan_id=view['plan']['id']
    first=task(client,view,'first',boundaries='同一练习范围');second=task(client,org(client,plan_id),'second',outcome_id=first['outcome_id'],boundaries='同一练习范围')
    value,_=path_draft(client,plan_id,first,second)
    path,_=path_confirm(client,plan_id,value)
    yield dict(client=client,db=db,service=service,identity=identity,plan_id=plan_id,first=first,second=second,route_id=path['adopted_version_id'])
    client.portal.call(service.shutdown)


def base(ctx):return '/api/learning/plans/'+ctx['plan_id']+'/commitments'
def view(ctx):
    result=ctx['client'].get(base(ctx));assert result.status_code==200,result.text
    assert result.headers['cache-control']=='no-store';return result.json()
def item(ctx,which='first',**changes):
    value=ctx[which]
    return {**dict(node_id='entry' if which=='first' else 'practice',action_id=value['action_id'],delegation_id=value['delegation_id'],
        estimate_min_minutes=10,estimate_max_minutes=20,due_at=None,timezone=None,reason='COMMITMENT_ITEM_PRIVATE'),**changes}
def save(ctx,items=None,key='save'):
    current=view(ctx);response=ctx['client'].post(base(ctx)+'/drafts',json=dict(expected_revision=current['revision'],route_version_id=ctx['route_id'],
        items=items if items is not None else [item(ctx)],reason='COMMITMENT_DRAFT_PRIVATE',request_key='commitment:'+key))
    assert response.status_code==201,response.text;return response.json()
def confirm(ctx,draft,key='confirm'):
    response=ctx['client'].post(base(ctx)+'/previews',json={'draft_id':draft['draft_id']});assert response.status_code==200,response.text
    checked=response.json()
    response=ctx['client'].post(base(ctx)+'/confirm',json=dict(draft_id=draft['draft_id'],expected_revision=checked['revision'],
        expected_draft_revision=checked['draft_revision'],review_key=checked['review_key'],request_key='commitment:'+key))
    assert response.status_code==200,response.text;return response.json()
def start(ctx,item_id,key='start'):
    current=view(ctx);row=ctx['db'].fetchone('SELECT action_id FROM learning_commitment_item WHERE id=?',(item_id,))
    version=ctx['db'].fetchone('SELECT version FROM learning_action WHERE id=?',(row[0],))[0]
    response=ctx['client'].post(base(ctx)+'/items/'+item_id+'/start',json=dict(expected_revision=current['revision'],expected_action_version=version,
        use_checkpoint=True,request_key='commitment:'+key));assert response.status_code==200,response.text;return response.json()
def stop(ctx,session_id,key='stop',artifact=True):
    core=ctx['client'].app.state.learning.core;principal=Principal.user(ctx['identity']['id'])
    delegation=ctx['db'].fetchone('SELECT delegation_id FROM learning_session WHERE id=?',(session_id,))[0]
    action_id=ctx['db'].fetchone('SELECT action_id FROM learning_delegation WHERE id=?',(delegation,))[0]
    version=lambda:ctx['db'].fetchone('SELECT version FROM learning_action WHERE id=?',(action_id,))[0]
    saved=core.execute(principal,SaveTextArtifact(session_id=session_id,content='SYNTHETIC_ACTUAL_ARTIFACT',expected_version=version()),key+'-artifact') if artifact else None
    core.execute(principal,EndSession(session_id=session_id,disposition='interrupted',expected_version=version()),key)
    return saved

def feedback(ctx,session_id,artifact_id=None,key='feedback',**changes):
    route='/api/learning/sessions/'+session_id+'/feedback'
    current=ctx['client'].get(route).json()
    response=ctx['client'].post(route,json={**dict(expected_revision=current['revision'],request_key=key,
        actual_min_minutes=15,actual_max_minutes=15,purpose='real',grain='ok',pace='ok',method_feedback='ok',progress='progress',activity='recall',
        artifact_id=artifact_id,notes='SESSION_FEEDBACK_PRIVATE'),**changes})
    assert response.status_code==200,response.text;return response.json()


def test_manual_preview_confirm_start_resume_defer_skip_preserve_history_and_replay(arranged):
    ctx=arranged;db=ctx['db'];client=ctx['client']
    before={table:[tuple(row) for row in db.fetchall('SELECT * FROM '+table)] for table in ('learning_action','learning_outcome','learning_delegation','learning_session','learning_artifact')}
    draft=save(ctx);current=confirm(ctx,draft);item_id=current['current_version']['items'][0]['id']
    assert before=={table:[tuple(row) for row in db.fetchall('SELECT * FROM '+table)] for table in before}
    first=start(ctx,item_id);saved=stop(ctx,first['session_id'])
    feedback(ctx,first['session_id'],saved['id'])
    resumed=start(ctx,item_id,'resume')
    assert resumed['session_id']!=first['session_id']
    assert db.fetchone('SELECT COUNT(*) FROM learning_commitment_execution WHERE item_id=?',(item_id,))[0]==2
    assert view(ctx)['calibration']['work_block_ids']==[item_id]
    assert next(axis for axis in view(ctx)['calibration']['axes'] if axis['name']=='effort')['state']=='unknown'
    preview=client.post(base(ctx)+'/items/'+item_id+'/preview',json={'operation':'defer','due_at':'2027-01-01T10:00:00Z','timezone':'UTC'}).json()
    assert [s['id'] for s in preview['affected_sessions']]==[resumed['session_id']]
    deferred=client.post(base(ctx)+'/items/'+item_id+'/defer',json={'due_at':'2027-01-01T10:00:00Z','timezone':'UTC',
        'expected_revision':preview['revision'],'review_key':preview['review_key'],'request_key':'defer'})
    assert deferred.status_code==200,deferred.text
    assert db.fetchone('SELECT status FROM learning_session WHERE id=?',(resumed['session_id'],))[0]=='interrupted'
    assert deferred.json()['current_version']['items'][0]['status']=='deferred'
    original=db.fetchone('SELECT data_json FROM learning_commitment_version')[0]
    assert json.loads(original)[0]['due_at'] is None
    preview=client.post(base(ctx)+'/items/'+item_id+'/preview',json={'operation':'skip'}).json()
    skipped=client.post(base(ctx)+'/items/'+item_id+'/skip',json={'expected_revision':preview['revision'],'review_key':preview['review_key'],'request_key':'skip'})
    assert skipped.status_code==200,skipped.text
    assert skipped.json()['current_version']['items'][0]['status']=='skipped'
    assert db.fetchone('SELECT status FROM learning_action WHERE id=?',(ctx['first']['action_id'],))[0]=='open'
    assert db.fetchone('SELECT COUNT(*) FROM learning_completion')[0]==0
    before_view=view(ctx)
    result=ctx['client'].app.state.learning.core.replay(Principal.user(ctx['identity']['id']))
    assert result['comparison']['matched'] is True
    assert view(ctx)==before_view


def test_feedback_correction_unknown_origin_synthetic_lock_owner_and_scope(arranged):
    ctx=arranged;client=ctx['client'];db=ctx['db']
    current=confirm(ctx,save(ctx));item_id=current['current_version']['items'][0]['id']
    started=start(ctx,item_id);saved=stop(ctx,started['session_id'])
    value=feedback(ctx,started['session_id'],saved['id'],purpose='unknown',actual_min_minutes=None,actual_max_minutes=None)
    assert value['current']['actual_min_minutes'] is None
    assert value['session_span_minutes'] is not None
    assert view(ctx)['calibration']['range']=='short'
    corrected=feedback(ctx,started['session_id'],saved['id'],key='correct')
    assert corrected['revision']==2 and len(corrected['history'])==2
    assert corrected['history'][0]['purpose']=='unknown' and corrected['current']['purpose']=='real'
    # The known demo marker is a stable source marker, never a title heuristic.
    with db.transaction() as connection:connection.execute('UPDATE learning_action SET context_key=? WHERE id=?',(DEMO_CONTEXT,ctx['first']['action_id']))
    response=client.post('/api/learning/sessions/'+started['session_id']+'/feedback',json=dict(expected_revision=2,request_key='demo-real',purpose='real'))
    assert response.status_code==422 and response.json()['detail']['kind']=='commitment_synthetic_origin_locked'
    assert view(ctx)['calibration']['range']=='short'
    command=__import__('app.core.commitment_commands',fromlist=['RecordSessionFeedback']).RecordSessionFeedback(session_id=started['session_id'],expected_revision=2)
    with pytest.raises(DomainError,match='permission_denied'):
        client.app.state.learning.core.execute(Principal.agent(ctx['identity']['id'],'agent',action_ids=frozenset(),tools=frozenset()),command,'agent-feedback')


def test_cas_preview_stale_idempotence_and_transaction_rollback(arranged,monkeypatch):
    ctx=arranged;client=ctx['client'];db=ctx['db']
    draft=save(ctx);preview=client.post(base(ctx)+'/previews',json={'draft_id':draft['draft_id']}).json()
    another=save(ctx,[item(ctx,'second')],'another')
    stale=client.post(base(ctx)+'/confirm',json={'draft_id':draft['draft_id'],'expected_revision':preview['revision'],
        'expected_draft_revision':preview['draft_revision'],'review_key':preview['review_key'],'request_key':'stale'})
    assert stale.status_code==409
    import app.core.commitments as commands
    previous=commands._plan_event
    def fail(*args,**kwargs):
        previous(*args,**kwargs)
        raise DomainError('synthetic_failure')
    monkeypatch.setattr(commands,'_plan_event',fail)
    counts={table:db.fetchone('SELECT COUNT(*) FROM '+table)[0] for table in ('learning_event','learning_command','learning_commitment_private','learning_commitment_version')}
    checked=client.post(base(ctx)+'/previews',json={'draft_id':another['draft_id']}).json()
    failed=client.post(base(ctx)+'/confirm',json={'draft_id':another['draft_id'],'expected_revision':checked['revision'],
        'expected_draft_revision':checked['draft_revision'],'review_key':checked['review_key'],'request_key':'rollback'})
    assert failed.status_code==409
    assert {table:db.fetchone('SELECT COUNT(*) FROM '+table)[0] for table in counts}==counts


def test_private_draft_feedback_bytes_registered_backup_and_replay(arranged,tmp_path):
    ctx=arranged;client=ctx['client'];db=ctx['db']
    draft=save(ctx);current=confirm(ctx,draft);item_id=current['current_version']['items'][0]['id']
    started=start(ctx,item_id);saved=stop(ctx,started['session_id']);feedback(ctx,started['session_id'],saved['id'])
    backup,_,_=create_learning_backup(db.database_path,tmp_path/'managed',label='commitment')
    result=client.post(base(ctx)+'/drafts/'+draft['draft_id']+'/purge',json={'expected_revision':view(ctx)['revision'],
        'confirmation':'PURGE','request_key':'purge-draft'})
    assert result.status_code==200 and result.json()['purge_report']['status']=='complete',result.text
    result=client.post('/api/learning/sessions/'+started['session_id']+'/feedback/purge',json={'expected_revision':1,
        'confirmation':'PURGE','request_key':'purge-feedback'})
    assert result.status_code==200 and result.json()['purge_report']['status']=='complete',result.text
    for path in (db.database_path,backup):absent(path,'COMMITMENT_ITEM_PRIVATE','COMMITMENT_DRAFT_PRIVATE','SESSION_FEEDBACK_PRIVATE')
    assert db.fetchone('SELECT COUNT(*) FROM learning_commitment_execution')[0]==1
    assert db.fetchone('SELECT COUNT(*) FROM learning_artifact')[0]==1
    assert client.app.state.learning.core.replay(Principal.user(ctx['identity']['id']))['comparison']['matched'] is True


def learned(ctx,which='first',key='block',**feedback_changes):
    current=confirm(ctx,save(ctx,[item(ctx,which)],key+'-draft'),key+'-confirm')
    item_id=next(value['id'] for value in current['current_version']['items'] if value['action_id']==ctx[which]['action_id'] and not value['execution_session_ids'])
    started=start(ctx,item_id,key+'-start');saved=stop(ctx,started['session_id'],key+'-stop')
    feedback(ctx,started['session_id'],saved['id'],key+'-feedback',**feedback_changes)
    return item_id,started['session_id']


def test_calibration_axes_same_scope_conflict_burden_overrun_and_direction(arranged):
    ctx=arranged;client=ctx['client']
    assert view(ctx)['calibration']['range']=='short'
    first,first_session=learned(ctx,key='first-real')
    supported=view(ctx)['calibration']
    assert supported['range']=='extended' and supported['max_sessions']==5
    assert supported['work_block_ids']==[first]
    assert next(axis for axis in supported['axes'] if axis['name']=='rhythm')['state']=='unknown'
    feedback(ctx,first_session,key='burden',pace='too_tight',artifact_id=None)
    shortened=view(ctx)['calibration']
    assert shortened['range']=='short' and 'reported_burden' in shortened['reason_codes']
    feedback(ctx,first_session,key='conflict',progress='difficulty',artifact_id=None)
    assert 'performance_conflict' in view(ctx)['calibration']['reason_codes']
    # A range outside its estimate is distinct from a session's wall-clock span.
    feedback(ctx,first_session,key='overrun-a',actual_min_minutes=35,actual_max_minutes=40,artifact_id=None)
    learned(ctx,'second','overrun-b',actual_min_minutes=35,actual_max_minutes=40)
    calibration=view(ctx)['calibration']
    assert 'comparable_effort_overrun' in calibration['reason_codes'] and calibration['range']=='short'
    changed,_=path_draft(client,ctx['plan_id'],ctx['first'],ctx['second'],intent='change_direction',request_key='change-direction')
    new_path,_=path_confirm(client,ctx['plan_id'],changed,'change-direction-confirm')
    ctx['route_id']=new_path['adopted_version_id']
    calibration=view(ctx)['calibration']
    assert calibration['range']=='short' and not calibration['work_block_ids']
    assert all(source['reason']=='outside_current_direction' for source in calibration['excluded_sources'])


def configure_mock(ctx,monkeypatch,scenario='good'):
    calls=[];runtime=[]
    def resolve(owner,kind,scope):
        runtime.append((owner,kind,scope))
        return {},ProviderConfig(base_url='https://synthetic.invalid/v1',model='frozen-plan-model',api_key='FAKE_KEY_DO_NOT_PERSIST',
            timeout_seconds=111,reasoning_parameters_json='{"reasoning_effort":"high"}'),{
            'model':{'capabilities':{'max_output_tokens':1024}},
            'model_control':{'provider_name':'synthetic','model':'frozen-plan-model','timeout_seconds':111,'reasoning_parameters':{'reasoning_effort':'high'}}}
    monkeypatch.setattr(ctx['service'].chats.model_control,'runtime',resolve)
    def handler(request):
        sent=json.loads(request.content);calls.append(sent)
        if scenario=='http':return httpx.Response(503,json={'error':{'message':'DO_NOT_EXPOSE_PRIVATE_RESPONSE'}})
        inputs=json.loads(sent['messages'][-1]['content']);selected=inputs['tasks'][0]
        proposal={'items':[dict(node_id=selected['node_ids'][0],action_id=selected['id'],delegation_id=selected['delegation_id'],
            estimate_min_minutes=None,estimate_max_minutes=None,due_at=None,timezone=None,reason='AI_ITEM_PRIVATE',
            source_refs=[inputs['source_refs'][0]])],'explanation':'AI_EXPLANATION_PRIVATE'}
        if scenario=='outside':proposal['items'][0]['source_refs']=[{'kind':'feedback','id':'not-in-input','revision':1}]
        if scenario=='oversize':proposal['items']=proposal['items']*4
        if scenario=='invalid':text='DO_NOT_EXPOSE_PRIVATE_RESPONSE'
        else:text=json.dumps(proposal)
        return httpx.Response(200,json={'choices':[{'message':{'content':text},'finish_reason':'length' if scenario=='length' else 'stop'}]})
    ctx['service'].transport=httpx.MockTransport(handler)
    return calls,runtime


def wait_run(ctx,run_id):
    import time
    for _ in range(100):
        response=ctx['client'].get(base(ctx)+'/suggestions/'+run_id);assert response.status_code==200,response.text
        value=response.json()
        if value['status']!='running':return value
        time.sleep(.01)
    raise AssertionError('mock suggestion did not finish')


def test_ai_frozen_plan_runtime_single_call_bounded_sources_preview_confirmation(arranged,monkeypatch):
    ctx=arranged;calls,runtime=configure_mock(ctx,monkeypatch)
    request={'expected_revision':view(ctx)['revision'],'request_key':'suggest'}
    response=ctx['client'].post(base(ctx)+'/suggestions',json=request);assert response.status_code==201,response.text
    run=wait_run(ctx,response.json()['id'])
    assert run['status']=='succeeded',run
    assert len(calls)==1 and runtime==[(ctx['identity']['id'],'plan',ctx['plan_id'])]
    assert calls[0]['max_tokens']==1024 and calls[0]['reasoning_effort']=='high'
    assert run['provider_snapshot']['timeout_seconds']==111
    assert 'SESSION_FEEDBACK_PRIVATE' not in json.dumps(calls[0])
    absent(ctx['db'].database_path,'FAKE_KEY_DO_NOT_PERSIST')
    assert view(ctx)['current_version'] is None
    assert ctx['client'].post(base(ctx)+'/suggestions',json=request).json()['id']==run['id']
    assert len(calls)==1
    current=confirm(ctx,{'draft_id':run['draft_id']},'accept-ai')
    assert len(current['current_version']['items'])==1 and current['current_version']['source']=='ai'
    assert ctx['db'].fetchone('SELECT COUNT(*) FROM learning_session')[0]==0
    assert ctx['client'].app.state.learning.core.replay(Principal.user(ctx['identity']['id']))['comparison']['matched'] is True


@pytest.mark.parametrize('scenario,reason',[('http','upstream_error'),('length','output_truncated'),('invalid','invalid_json'),
    ('outside','commitment_ai_source_out_of_scope'),('oversize','commitment_calibration_scope')])
def test_ai_failure_preserves_current_arrangement_and_does_not_retry_model(arranged,monkeypatch,scenario,reason):
    ctx=arranged;current=confirm(ctx,save(ctx));before=current['current_version'];calls,_=configure_mock(ctx,monkeypatch,scenario)
    response=ctx['client'].post(base(ctx)+'/suggestions',json={'expected_revision':current['revision'],'request_key':'failure-run'})
    assert response.status_code==201,response.text
    run=wait_run(ctx,response.json()['id'])
    assert run['status']=='failed' and run['reason']==reason,run
    assert len(calls)==1 and view(ctx)['current_version']==before
    assert 'DO_NOT_EXPOSE_PRIVATE_RESPONSE' not in json.dumps(run)


def test_run_cancel_late_result_recovery_and_source_correction_do_not_write(arranged):
    ctx=arranged;learning=ctx['client'].app.state.learning;principal=Principal.user(ctx['identity']['id']);db=ctx['db']
    with db.transaction() as connection:inputs=input_context(connection,principal.owner_id,ctx['plan_id'])
    command=lambda:StartCommitmentRun(plan_id=ctx['plan_id'],expected_revision=inputs['commitment_revision'],input_hash=inputs['input_hash'],inputs=inputs,provider_snapshot={'model':'mock'})
    run=learning.core.execute(principal,command(),'run-cancel')
    from app.core.commitment_commands import CancelCommitmentRun
    learning.core.execute(principal,CancelCommitmentRun(run_id=run['run_id'],expected_revision=1),'cancel')
    with pytest.raises(DomainError,match='commitment_run_inactive'):
        learning.core.execute(principal,FinishCommitmentRun(run_id=run['run_id'],expected_revision=2,status='succeeded',items=[item(ctx)]),'late')
    interrupted=learning.core.execute(principal,command(),'run-restart')
    ctx['service'].recover()
    assert ctx['service'].run(ctx['identity'],ctx['plan_id'],interrupted['run_id'])['reason']=='interrupted'
    assert not view(ctx)['drafts']
    first,session=learned(ctx,key='source')
    with db.transaction() as connection:inputs=input_context(connection,principal.owner_id,ctx['plan_id'])
    changing=learning.core.execute(principal,command(),'run-source')
    feedback(ctx,session,key='source-change',pace='too_tight')
    with pytest.raises(DomainError,match='commitment_input_changed'):
        learning.core.execute(principal,FinishCommitmentRun(run_id=changing['run_id'],expected_revision=1,status='succeeded',items=[item(ctx)]),'source-late')
    assert db.fetchone('SELECT COUNT(*) FROM learning_commitment_draft')[0]==1


def test_context_coverage_and_actual_multiround_dates_capacity_availability_change(arranged,monkeypatch):
    from datetime import datetime,timedelta,timezone
    ctx=arranged;db=ctx['db'];client=ctx['client'];now=datetime.now(timezone.utc)
    # Explicit declarations distinguish contexts; titles never classify them.
    with db.transaction() as connection:
        connection.execute("UPDATE learning_action SET context_key='context-b' WHERE id=?",(ctx['second']['action_id'],))
        connection.execute("UPDATE learning_outcome SET context_key='context-b' WHERE id=?",(ctx['second']['outcome_id'],))
    learned(ctx,key='context-a')
    assert view(ctx)['calibration']['range']=='short' and 'new_context' in view(ctx)['calibration']['reason_codes']
    learned(ctx,'second','context-b')
    assert view(ctx)['calibration']['range']=='extended' and view(ctx)['calibration']['max_sessions']==7
    # The historical declarations above are deliberately a rule fixture; the
    # separate journey test verifies replay from formally recorded declarations.
    slots=[]
    for offset in (-2,-1,1,2,3,4,5,6,14):
        begin=now+timedelta(days=offset)
        slots.append({'start_at':begin.isoformat(),'end_at':(begin+timedelta(hours=1)).isoformat()})
    availability={'expected_revision':view(ctx)['revision'],'request_key':'availability','timezone':'UTC',
        'slots':slots,'weekly_budget_minutes':120,'block_max_minutes':30,'preferred_days':14}
    response=client.post(base(ctx)+'/availability',json=availability);assert response.status_code==200,response.text
    import app.core.learning as core
    for index,which in enumerate(('first','second')):
        due=slots[index]['start_at']
        dated=item(ctx,which,due_at=due,timezone='UTC')
        instant=datetime.fromisoformat(due)
        monkeypatch.setattr(core,'utc_timestamp',lambda value=instant-timedelta(minutes=1):value.isoformat().replace('+00:00','Z'))
        current=confirm(ctx,save(ctx,[dated],'round-'+str(index)), 'round-confirm-'+str(index))
        item_id=next(value['id'] for value in current['current_version']['items'] if not value['execution_session_ids'])
        instant=datetime.fromisoformat(due)
        monkeypatch.setattr(core,'utc_timestamp',lambda value=instant:value.isoformat().replace('+00:00','Z'))
        started=start(ctx,item_id,'dated-start-'+str(index));saved=stop(ctx,started['session_id'],'dated-stop-'+str(index))
        feedback(ctx,started['session_id'],saved['id'],'dated-feedback-'+str(index))
    calibrated=view(ctx)['calibration']
    assert calibrated['range']=='dated' and calibrated['horizon_days']==14,calibrated
    with db.transaction() as connection:
        from app.core.commitments import validate_capacity
        start_time=slots[2]['start_at']
        proposed=[item(ctx,due_at=start_time,timezone='UTC',estimate_min_minutes=10,estimate_max_minutes=20)]
        validate_capacity(connection,ctx['identity']['id'],ctx['plan_id'],proposed,14)
        with pytest.raises(DomainError,match='commitment_capacity_exceeded'):
            validate_capacity(connection,ctx['identity']['id'],ctx['plan_id'],[item(ctx,due_at=start_time,timezone='UTC',estimate_min_minutes=35,estimate_max_minutes=40)],14)
    # New time preferences invalidate rhythm, without discarding effective effort.
    response=client.post(base(ctx)+'/availability',json={**availability,'expected_revision':view(ctx)['revision'],'request_key':'new-availability'})
    assert response.status_code==200,response.text
    calibration=view(ctx)['calibration']
    assert calibration['range']=='extended' and 'availability_changed' in calibration['unknowns']
    assert next(axis for axis in calibration['axes'] if axis['name']=='effort')['state']=='covered'


def test_only_future_dates_never_supply_real_learning_or_stability(arranged):
    ctx=arranged
    current=confirm(ctx,save(ctx,[item(ctx,due_at='2030-01-01T10:00:00Z',timezone='UTC')]))
    assert current['calibration']['range']=='short' and not current['calibration']['sources']
    assert ctx['db'].fetchone('SELECT COUNT(*) FROM learning_session')[0]==0


def test_artifact_purge_clears_exactly_derived_feedback_run_draft_and_backup(arranged,tmp_path,monkeypatch):
    ctx=arranged;client=ctx['client'];db=ctx['db']
    _,session=learned(ctx,key='source-real')
    artifact=db.fetchone('SELECT id FROM learning_artifact')[0]
    configure_mock(ctx,monkeypatch)
    response=client.post(base(ctx)+'/suggestions',json={'expected_revision':view(ctx)['revision'],'request_key':'source-suggestion'})
    run=wait_run(ctx,response.json()['id']);assert run['status']=='succeeded',run
    confirm(ctx,{'draft_id':run['draft_id']},'source-ai-confirm')
    backup,_,_=create_learning_backup(db.database_path,tmp_path/'managed',label='source')
    # The old artifact endpoint owns its lifecycle; the new hook follows only
    # declared references, retaining sessions, commitments and unrelated bodies.
    version=db.fetchone('SELECT a.version FROM learning_action a JOIN learning_delegation d ON d.owner_id=a.owner_id AND d.action_id=a.id JOIN learning_session s ON s.owner_id=d.owner_id AND s.delegation_id=d.id JOIN learning_raw_artifact r ON r.owner_id=s.owner_id AND r.session_id=s.id WHERE r.artifact_id=?',(artifact,))[0]
    response=client.post('/api/learning/artifacts/'+artifact+'/purge',json={'expected_version':version,'confirmation':'PURGE','idempotency_key':'source-purge'})
    assert response.status_code==200,response.text
    assert response.json()['purge']['status']=='complete'
    for file in (db.database_path,backup):absent(file,'SESSION_FEEDBACK_PRIVATE','AI_ITEM_PRIVATE','AI_EXPLANATION_PRIVATE')
    assert db.fetchone('SELECT COUNT(*) FROM learning_commitment_execution')[0]==1
    assert db.fetchone('SELECT COUNT(*) FROM learning_session')[0]==1
    assert view(ctx)['current_version'] is not None and view(ctx)['current_version']['content_available'] is False
    assert view(ctx)['calibration']['range']=='short'
    assert client.app.state.learning.core.replay(Principal.user(ctx['identity']['id']))['comparison']['matched'] is True


def test_formal_044_to_046_upgrade_preserves_every_old_row_column_and_table(tmp_path,monkeypatch):
    import shutil
    from app.config import Settings
    from app.db import Database
    from app.learning_service import LearningService
    from app.core.commands import ConfirmLearningSetup
    from app.learning_production import upgrade_learning_database
    from test_learning_setup import setup_command
    from test_learning_verifications import IDENTITY
    from app.core.organization_commands import CreateModule
    migrations=Path(__file__).resolve().parents[1]/'app'/'migrations'
    old=tmp_path/'old.sqlite3';db=Database(old,migrations,migration_floor=11,migration_ceiling=44)
    learning=LearningService(db);principal=learning.principal(IDENTITY)
    initial=learning.core.execute(principal,setup_command(),'old-setup')
    learning.core.execute(principal,CreateModule(plan_id=initial['plan_id'],expected_revision=0,title='old module'),'old-module')
    tables=[row[0] for row in db.fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'schema_migrations'")]
    before={table:[tuple(row) for row in db.fetchall('SELECT * FROM '+table+' ORDER BY rowid')] for table in tables}
    definitions={table:db.fetchone('SELECT sql FROM sqlite_master WHERE name=?',(table,))[0] for table in tables}
    columns={table:[tuple(row) for row in db.fetchall('PRAGMA table_info('+table+')')] for table in tables};db.close()
    # Publish copies only inside this isolated migration fixture, keeping the
    # live application's migration glob unchanged until the lead releases it.
    fixture_root=tmp_path/'fixture';target=fixture_root/'backend'/'app'/'migrations';target.mkdir(parents=True)
    for file in migrations.glob('*.sql'):
        if int(file.name[:3])<=44:shutil.copyfile(file,target/file.name)
    for stem in ('045_learning_commitments','046_learning_signal_feedback'):
        source=migrations/(stem+'.sql.pending')
        if not source.exists():source=migrations/(stem+'.sql')
        shutil.copyfile(source,target/(stem+'.sql'))
    import app.learning_production as production
    import app.learning_storage as storage
    monkeypatch.setattr(production,'PROJECT_ROOT',fixture_root)
    monkeypatch.setattr(storage,'__file__',str(fixture_root/'backend'/'app'/'learning_storage.py'))
    result=upgrade_learning_database(old,tmp_path/'backups',authorized=True)
    assert result['preflight']['applied_migrations'][-1]=='044_learning_paths'
    assert result['post_upgrade_backup']['applied_migrations'][-1]=='046_learning_signal_feedback'
    with closing(sqlite3.connect(old)) as connection:
        for table in tables:
            assert connection.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()==before[table]
            assert connection.execute('PRAGMA table_info('+table+')').fetchall()==columns[table]
            assert connection.execute('SELECT sql FROM sqlite_master WHERE name=?',(table,)).fetchone()[0]==definitions[table]
        assert connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert connection.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_commitment_exact_answer_anchor_running_output_new_start_false_and_retry(arranged):
    from test_learning_paths import link_chat
    ctx=arranged;client=ctx['client'];db=ctx['db']
    current=confirm(ctx,save(ctx));item_id=current['current_version']['items'][0]['id']
    first=start(ctx,item_id,'anchor-first');cid=link_chat(client,first['session_id'])
    chatdb=client.app.state.conversations.database
    with chatdb.transaction() as connection:
        for index,leaf in enumerate(('commit-answer-old','commit-answer-latest')):
            connection.execute("INSERT INTO message(id,conversation_id,role,content,sequence,created_at,updated_at) VALUES (?,?,'assistant','Synthetic answer',?,'now','now')",(leaf,cid,index))
    endpoint='/api/conversation-state/conversation/'+cid
    response=client.put(endpoint,json={'expected_revision':0,'leaf_id':'commit-answer-old','paths':{'commit-answer-old':'commit-answer-old'}})
    assert response.status_code==200,response.text
    recorded=start(ctx,item_id,'anchor-record')
    assert recorded['session_id']==first['session_id'] and recorded['path_anchor']['leaf_id']=='commit-answer-old'
    stop(ctx,first['session_id'],'anchor-pause',artifact=False)
    response=client.put(endpoint,json={'expected_revision':1,'leaf_id':'commit-answer-latest','paths':{'commit-answer-latest':'commit-answer-latest'}})
    assert response.status_code==200,response.text
    body={'expected_revision':view(ctx)['revision'],'expected_action_version':db.fetchone('SELECT version FROM learning_action WHERE id=?',(ctx['first']['action_id'],))[0],
        'use_checkpoint':True,'request_key':'anchor-resume'}
    start_url=base(ctx)+'/items/'+item_id+'/start'
    response=client.post(start_url,json=body);assert response.status_code==200,response.text
    resumed=response.json();assert resumed['path_anchor']['leaf_id']=='commit-answer-old'
    assert client.post(start_url,json=body).json()==resumed
    # Viewing the same live work block's generated output must remain possible.
    with chatdb.transaction() as connection:
        connection.execute("INSERT INTO ai_run(id,identity_id,conversation_id,status,created_at,updated_at) VALUES ('commit-active',?,?,'running','now','now')",(ctx['identity']['id'],cid))
    continued=start(ctx,item_id,'anchor-live')
    assert continued['session_id']==resumed['session_id'] and continued['path_anchor']['leaf_id']=='commit-answer-latest'
    assert db.fetchone('SELECT COUNT(*) FROM learning_session')[0]==2
    with chatdb.transaction() as connection:
        connection.execute("UPDATE ai_run SET status='canceled' WHERE id='commit-active'")
    stop(ctx,resumed['session_id'],'anchor-stop',artifact=False)
    with chatdb.transaction() as connection:connection.execute("DELETE FROM message WHERE id='commit-answer-latest'")
    body={'expected_revision':view(ctx)['revision'],'expected_action_version':db.fetchone('SELECT version FROM learning_action WHERE id=?',(ctx['first']['action_id'],))[0],
        'use_checkpoint':True,'request_key':'missing-commit-anchor'}
    rejected=client.post(start_url,json=body)
    assert rejected.status_code==409 and rejected.json()['detail']['kind']=='path_anchor_unavailable'
    fallback=client.post(start_url,json={**body,'use_checkpoint':False,'request_key':'commit-explicit-fallback'})
    assert fallback.status_code==200 and 'path_anchor' not in fallback.json(),fallback.text


def test_default_context_does_not_cover_new_object_or_different_task_grain(arranged):
    ctx=arranged;client=ctx['client']
    learned(ctx,key='scoped-existing')
    assert view(ctx)['calibration']['range']=='extended'
    # Same opaque/default context, new stable outcome and declaration.
    new=task(client,org(client,ctx['plan_id']),'new-object',context_key='synthetic',outcome_context_key='synthetic',
        object_description='A different learning object',behavior='A different observable behavior',boundaries='同一练习范围')
    changed,_=path_draft(client,ctx['plan_id'],ctx['first'],new,intent='change_scope',request_key='new-object-path')
    current,_=path_confirm(client,ctx['plan_id'],changed,'new-object-confirm')
    ctx['route_id']=current['adopted_version_id']
    calibration=view(ctx)['calibration']
    assert calibration['range']=='short' and 'new_context' in calibration['reason_codes']
    # An explicitly shared outcome still cannot borrow another task's grain.
    grain=task(client,org(client,ctx['plan_id']),'new-grain',outcome_id=ctx['first']['outcome_id'],
        boundaries='A wider independent practice',time_budget_minutes=60)
    changed,_=path_draft(client,ctx['plan_id'],ctx['first'],grain,intent='change_scope',request_key='grain-path')
    current,_=path_confirm(client,ctx['plan_id'],changed,'grain-confirm');ctx['route_id']=current['adopted_version_id']
    assert view(ctx)['calibration']['range']=='short'


def test_real_route_decisions_keep_stable_items_pause_direction_and_stale_review(arranged,monkeypatch):
    ctx=arranged;client=ctx['client'];db=ctx['db']
    current=confirm(ctx,save(ctx));item_id=current['current_version']['items'][0]['id']
    started=start(ctx,item_id,'route-start')
    # Same-scope adopted route remaps only the future route identity.
    changed,_=path_draft(client,ctx['plan_id'],ctx['first'],ctx['second'],intent='change_scope',request_key='keep-route')
    adopted,_=path_confirm(client,ctx['plan_id'],changed,'keep-route-confirm')
    row=db.fetchone('SELECT route_version_id,node_id FROM learning_commitment_item WHERE id=?',(item_id,))
    assert row['route_version_id']==adopted['adopted_version_id'] and row['node_id']=='entry'
    assert db.fetchone('SELECT COUNT(*) FROM learning_commitment_execution')[0]==1
    # A manual promise written after path preview invalidates its confirmation.
    changed,_=path_draft(client,ctx['plan_id'],ctx['first'],ctx['second'],intent='change_scope',request_key='stale-route')
    checked=client.post('/api/learning/plans/'+ctx['plan_id']+'/path/previews',json={'draft_id':changed['draft_id']}).json()
    ctx['route_id']=adopted['adopted_version_id'];save(ctx,[item(ctx,'second')],'between-preview')
    response=client.post('/api/learning/plans/'+ctx['plan_id']+'/path/decisions',json={'draft_id':changed['draft_id'],
        'expected_revision':checked['revision'],'expected_draft_revision':checked['draft_revision'],'review_key':checked['review_key'],'request_key':'stale-route-confirm'})
    assert response.status_code==409
    # Explicit direction change defers the remaining promise and pauses even
    # when the new current node happens to contain the same action.
    changed,_=path_draft(client,ctx['plan_id'],ctx['first'],ctx['second'],intent='change_direction',request_key='direction-route')
    response=client.post('/api/learning/plans/'+ctx['plan_id']+'/path/previews',json={'draft_id':changed['draft_id']})
    assert response.status_code==200,response.text
    checked=response.json()
    assert any(change['item_id']==item_id and change['kind']=='defer' for change in checked['commitment_changes'])
    assert started['session_id'] in {session['id'] for session in checked['affected_sessions']}
    import app.core.commitments as commitments
    previous=commitments.apply_route_change
    def fail(*args,**kwargs):
        previous(*args,**kwargs);raise DomainError('synthetic_hook_failure')
    monkeypatch.setattr(commitments,'apply_route_change',fail)
    payload={'draft_id':changed['draft_id'],'expected_revision':checked['revision'],'expected_draft_revision':checked['draft_revision'],
        'review_key':checked['review_key'],'request_key':'direction-rollback'}
    events=db.fetchone('SELECT COUNT(*) FROM learning_event')[0]
    response=client.post('/api/learning/plans/'+ctx['plan_id']+'/path/decisions',json=payload)
    assert response.status_code==409
    assert db.fetchone('SELECT status FROM learning_session WHERE id=?',(started['session_id'],))[0]=='running'
    assert db.fetchone('SELECT COUNT(*) FROM learning_event')[0]==events
    monkeypatch.setattr(commitments,'apply_route_change',previous)
    response=client.post('/api/learning/plans/'+ctx['plan_id']+'/path/decisions',json={**payload,'request_key':'direction-actual'})
    assert response.status_code==200,response.text
    assert db.fetchone('SELECT status FROM learning_commitment_item WHERE id=?',(item_id,))[0]=='deferred'
    assert db.fetchone('SELECT status FROM learning_session WHERE id=?',(started['session_id'],))[0]=='interrupted'
    assert db.fetchone('SELECT COUNT(*) FROM learning_commitment_execution')[0]==1
    assert client.app.state.learning.core.replay(Principal.user(ctx['identity']['id']))['comparison']['matched'] is True


def test_distinct_promises_share_task_but_never_share_one_actual_session(arranged):
    from test_learning_paths import link_chat
    ctx=arranged;client=ctx['client'];db=ctx['db']
    current=confirm(ctx,save(ctx,[item(ctx),item(ctx)],'two-promises'))
    first,second=[i['id'] for i in current['current_version']['items']]
    running=start(ctx,first,'first-promise');cid=link_chat(client,running['session_id'])
    chatdb=client.app.state.conversations.database
    with chatdb.transaction() as connection:
        connection.execute("INSERT INTO ai_run(id,identity_id,conversation_id,status,created_at,updated_at) VALUES ('distinct-busy',?,?,'running','now','now')",(ctx['identity']['id'],cid))
    body={'expected_revision':view(ctx)['revision'],'expected_action_version':db.fetchone('SELECT version FROM learning_action WHERE id=?',(ctx['first']['action_id'],))[0],
          'use_checkpoint':True,'request_key':'second-promise'}
    response=client.post(base(ctx)+'/items/'+second+'/start',json=body)
    assert response.status_code==409 and response.json()['detail']['kind']=='path_generation_running'
    assert db.fetchone('SELECT COUNT(*) FROM learning_commitment_execution')[0]==1
    with chatdb.transaction() as connection:connection.execute("UPDATE ai_run SET status='canceled' WHERE id='distinct-busy'")
    response=client.post(base(ctx)+'/items/'+second+'/start',json=body)
    assert response.status_code==200,response.text
    assert response.json()['session_id']!=running['session_id']
    assert db.fetchone('SELECT status FROM learning_session WHERE id=?',(running['session_id'],))[0]=='interrupted'
    assert len({row['item_id'] for row in db.fetchall('SELECT * FROM learning_commitment_execution')})==2
    assert db.fetchone('SELECT status FROM learning_action WHERE id=?',(ctx['first']['action_id'],))[0]=='open'
    assert client.app.state.learning.core.replay(Principal.user(ctx['identity']['id']))['comparison']['matched']


def test_new_arrangement_preserves_old_executed_route_anchor_after_direction_change(arranged):
    ctx=arranged;client=ctx['client'];db=ctx['db']
    original=confirm(ctx,save(ctx));old_item=original['current_version']['items'][0]['id']
    session=start(ctx,old_item);stop(ctx,session['session_id'])
    old=dict(db.fetchone('SELECT * FROM learning_commitment_item WHERE id=?',(old_item,)))
    changed,_=path_draft(client,ctx['plan_id'],ctx['first'],ctx['second'],intent='change_direction',
        nodes=[dict(id='practice',title='New independent stage',action_ids=[ctx['second']['action_id']],outcome_ids=[ctx['second']['outcome_id']])],
        edges=[],entry_node_id='practice',current_node_id='practice',request_key='replace-old-node')
    adopted,_=path_confirm(client,ctx['plan_id'],changed,'replace-old-node-confirm');ctx['route_id']=adopted['adopted_version_id']
    current=confirm(ctx,save(ctx,[item(ctx,'second')],'new-future'),'new-future-confirm')
    retained=next(i for i in current['current_version']['items'] if i['id']==old_item)
    assert retained['route_version_id']==old['route_version_id'] and retained['node_id']==old['node_id']
    assert retained['status']=='deferred' and retained['execution_session_ids']==[session['session_id']]
    assert db.fetchone('SELECT COUNT(*) FROM learning_commitment_execution')[0]==1
    assert client.app.state.learning.core.replay(Principal.user(ctx['identity']['id']))['comparison']['matched']


def test_ai_draft_edit_keeps_origin_and_sources_and_purge_erases_all_revisions(arranged,monkeypatch,tmp_path):
    from app.core.commitment_commands import ItemFields
    ctx=arranged;client=ctx['client'];calls,_=configure_mock(ctx,monkeypatch)
    response=client.post(base(ctx)+'/suggestions',json={'expected_revision':view(ctx)['revision'],'request_key':'editable-ai'})
    run=wait_run(ctx,response.json()['id']);assert run['status']=='succeeded'
    current=view(ctx);draft=next(d for d in current['drafts'] if d['id']==run['draft_id'])
    items=[{k:v for k,v in i.items() if k in ItemFields.model_fields} for i in draft['items']]
    assert items[0]['source_refs']
    items[0]['reason']='AI_EDITED_PRIVATE_COPY'
    payload={'expected_revision':current['revision'],'route_version_id':ctx['route_id'],'draft_id':draft['id'],
             'expected_draft_revision':draft['revision'],'items':items,'reason':'AI_EDITED_PRIVATE_EXPLANATION','request_key':'edit-ai-draft'}
    response=client.post(base(ctx)+'/drafts',json=payload);assert response.status_code==201,response.text
    edited=next(d for d in response.json()['drafts'] if d['id']==draft['id'])
    assert edited['source']=='ai' and edited['run_id']==run['id'] and edited['items'][0]['source_refs']==items[0]['source_refs']
    accepted=confirm(ctx,{'draft_id':draft['id']},'edited-ai-confirm')
    assert accepted['current_version']['source']=='ai' and len(calls)==1
    backup,_,_=create_learning_backup(ctx['db'].database_path,tmp_path/'backups',label='edited-ai')
    response=client.post(base(ctx)+'/suggestions/'+run['id']+'/purge',json={'expected_revision':run['revision'],'confirmation':'PURGE','request_key':'erase-ai-origin'})
    assert response.status_code==200 and response.json()['purge_report']['status']=='complete',response.text
    for file in (ctx['db'].database_path,backup):absent(file,'AI_EDITED_PRIVATE_COPY','AI_EDITED_PRIVATE_EXPLANATION','AI_ITEM_PRIVATE')
    assert client.app.state.learning.core.replay(Principal.user(ctx['identity']['id']))['comparison']['matched']


def test_feedback_source_choices_are_session_scoped_and_contain_no_original_text(arranged):
    ctx=arranged;current=confirm(ctx,save(ctx));item_id=current['current_version']['items'][0]['id']
    first=start(ctx,item_id,'choice-first');original=stop(ctx,first['session_id'],'choice-first-stop')
    second=start(ctx,item_id,'choice-second');other=stop(ctx,second['session_id'],'choice-second-stop')
    response=ctx['client'].get('/api/learning/sessions/'+first['session_id']+'/feedback')
    assert response.status_code==200,response.text
    ids={value['id'] for value in response.json()['source_choices']['artifacts']}
    assert ids=={original['id']} and other['id'] not in ids
    assert 'SYNTHETIC_ACTUAL_ARTIFACT' not in response.text
    record=ctx['client'].get('/api/learning/records/'+ctx['first']['delegation_id']).json()
    assert {row['id'] for row in record['sessions']}=={first['session_id'],second['session_id']}


def test_purge_partial_refresh_and_retry_keep_a_visible_managed_entry(arranged,monkeypatch,tmp_path):
    import app.managed_purge as purge
    ctx=arranged;client=ctx['client'];draft=save(ctx);backup,_,_=create_learning_backup(ctx['db'].database_path,tmp_path/'backups',label='partial')
    previous=purge.scrub_snapshot
    def fail(path,*args,**kwargs):
        if Path(path)==backup:raise PermissionError('synthetic inaccessible snapshot')
        return previous(path,*args,**kwargs)
    monkeypatch.setattr(purge,'scrub_snapshot',fail)
    response=client.post(base(ctx)+'/drafts/'+draft['draft_id']+'/purge',json={'expected_revision':view(ctx)['revision'],
        'confirmation':'PURGE','request_key':'first-partial'})
    assert response.status_code==200 and response.json()['purge_report']['status']=='partial',response.text
    refreshed=view(ctx);cleared=next(d for d in refreshed['drafts'] if d['id']==draft['draft_id'])
    assert cleared['can_purge_content'] and not cleared['content_available']
    assert draft['draft_id'] in refreshed['purge_retry_ids']
    monkeypatch.setattr(purge,'scrub_snapshot',previous)
    response=client.post(base(ctx)+'/drafts/'+draft['draft_id']+'/purge',json={'expected_revision':refreshed['revision'],
        'confirmation':'PURGE','request_key':'retry-partial'})
    assert response.status_code==200 and response.json()['purge_report']['status']=='complete',response.text
    absent(backup,'COMMITMENT_DRAFT_PRIVATE')
    assert not view(ctx)['purge_retry_ids']


def test_source_purge_while_waiting_for_provider_slot_prevents_any_send(arranged,monkeypatch):
    ctx=arranged;client=ctx['client'];calls,_=configure_mock(ctx,monkeypatch)
    async def hold():ctx['service'].slots=asyncio.Semaphore(0)
    client.portal.call(hold)
    response=client.post(base(ctx)+'/suggestions',json={'expected_revision':view(ctx)['revision'],'request_key':'queued-source'})
    run=response.json()
    route=client.get('/api/learning/plans/'+ctx['plan_id']+'/path').json()
    response=client.post('/api/learning/plans/'+ctx['plan_id']+'/path/versions/'+ctx['route_id']+'/purge',json={
        'expected_revision':route['revision'],'confirmation':'PURGE','request_key':'erase-queued-source'})
    assert response.status_code==200,response.text
    async def release():ctx['service'].slots.release()
    client.portal.call(release)
    assert wait_run(ctx,run['id'])['status']=='purged'
    async def settled():await asyncio.gather(*list(ctx['service'].tasks.values()),return_exceptions=True)
    client.portal.call(settled)
    assert not calls and view(ctx)['current_version'] is None


def test_one_active_run_per_plan_is_discoverable_and_same_key_is_reused(arranged,monkeypatch):
    ctx=arranged;client=ctx['client'];calls,_=configure_mock(ctx,monkeypatch)
    async def hold():ctx['service'].slots=asyncio.Semaphore(0)
    client.portal.call(hold)
    payload={'expected_revision':view(ctx)['revision'],'request_key':'discoverable-run'}
    response=client.post(base(ctx)+'/suggestions',json=payload);assert response.status_code==201,response.text
    run=response.json()
    assert client.post(base(ctx)+'/suggestions',json=payload).json()['id']==run['id']
    another=client.post(base(ctx)+'/suggestions',json={**payload,'request_key':'another-page'})
    assert another.status_code==409 and another.json()['detail']['kind']=='commitment_generation_running'
    summaries=view(ctx)['runs']
    assert len(summaries)==1 and summaries[0]['id']==run['id'] and summaries[0]['status']=='running'
    assert 'provider_snapshot' not in summaries[0] and 'calibration' not in summaries[0]
    response=client.post(base(ctx)+'/suggestions/'+run['id']+'/cancel',json={'expected_revision':run['revision'],'request_key':'cancel-found'})
    assert response.status_code==200,response.text
    assert view(ctx)['runs'][0]['status']=='canceled' and not calls
