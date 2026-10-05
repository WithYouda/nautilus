"""Synthetic real-Core/API journeys and actual MockTransport Provider requests."""
import json
import time
from datetime import datetime,timedelta,timezone
import httpx
import pytest
from app.core.commands import StartSession,EndSession,SaveTextArtifact
from app.core.background_coach import budget,PROJECTION_TABLES
from app.core.learning import utc_timestamp
from app.learning_domain import Principal
from test_evidence_claims import authorize
from test_plan_organization import plan,task,get,rows

BASE='/api/learning/coach'

@pytest.fixture
def coach(client):
    identity=authorize(client);organization=plan(client);item=task(client,organization)
    service=client.app.state.background_coach
    configured=client.put('/api/ai/provider',json={'display_name':'synthetic coach','base_url':'https://synthetic.example.com/v1',
        'model':'mock-coach','api_key':'sk-synthetic-coach-key','request_timeout_seconds':11})
    assert configured.status_code==200,configured.text
    ctx=dict(client=client,identity=identity,db=service.db,service=service,plan_id=organization['plan']['id'],item=item,calls=[],error=False,slow=False)
    async def respond(request):
        import asyncio
        payload=json.loads(request.content);inputs=json.loads(payload['messages'][-1]['content']);ctx['calls'].append((payload,inputs))
        if ctx['slow']: await asyncio.sleep(2)
        if ctx['error']: return httpx.Response(401,json={'error':{'message':'SYNTHETIC_ONLY'}})
        candidate_target=next((t for t in inputs['targets'] if t['kind']==ctx.get('target_kind','task')),inputs['targets'][0])
        proposal={'candidates':[dict(title='合成建议',explanation='COACH_PRIVATE_REASON',unknowns=['仍未知'],
            source_refs=inputs['refs'][:1],target={k:candidate_target[k] for k in ('kind','plan_id','action_id','delegation_id','object_id')},
            access_request={'purpose':'核对本任务产出原文中的具体依据。','alternative':'可以本人补充摘要或在原任务核对。'} if candidate_target['kind']=='permission_review' else None)]}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(proposal,ensure_ascii=False)},'finish_reason':'stop'}]})
    service.transport=httpx.MockTransport(respond)
    return ctx

def end(ctx,key='session',artifact=True,item=None):
    item=item or ctx['item'];db=ctx['db'];core=ctx['service'].learning.core;p=Principal.user(ctx['identity']['id'])
    version=lambda:db.fetchone('SELECT version FROM learning_action WHERE id=?',(item['action_id'],))[0]
    session=core.execute(p,StartSession(delegation_id=item['delegation_id'],expected_version=version()),key+'start')['id']
    saved=core.execute(p,SaveTextArtifact(session_id=session,content='RAW_PRIVATE_ARTIFACT',expected_version=version()),key+'artifact') if artifact else None
    core.execute(p,EndSession(session_id=session,disposition='interrupted',expected_version=version()),key+'end')
    return session,saved

def settings(ctx,enabled=True,**changes):
    old=ctx['client'].get(BASE+'/settings').json()
    response=ctx['client'].put(BASE+'/settings',json={**{k:v for k,v in old.items() if k!='revision'},'enabled':enabled,
        'expected_revision':old['revision'],'request_key':'settings-'+str(old['revision']),**changes})
    assert response.status_code==200,response.text
    return response.json()

def check(ctx,key='manual',trigger='manual',scope='global',**changes):
    response=ctx['client'].post(BASE+'/checks',json={'scope':scope,'plan_id':ctx['plan_id'] if scope=='plan' else None,
        'trigger':trigger,'request_key':key,**changes})
    assert response.status_code==200,response.text
    return response.json()

def finish(ctx,identifier):
    for _ in range(200):
        response=ctx['client'].get(BASE+'/checks/'+identifier)
        assert response.status_code==200,response.text
        value=response.json()
        if value['run']['status'] not in {'queued','running'}: return value
        time.sleep(.01)
    raise AssertionError('synthetic coach did not finish')

def test_registered_no_store_default_off_manual_ai_and_actual_navigation(coach):
    ctx=coach;client=ctx['client'];end(ctx)
    assert client.get(BASE+'/settings').json()==dict(revision=0,enabled=False,timezone='UTC',max_calls_per_session=1,max_calls_per_day=3,cooldown_minutes=30)
    assert client.get(BASE).headers['cache-control']=='no-store'
    assert check(ctx,'automatic',trigger='return')['reason']=='coach_disabled'
    assert not ctx['calls']
    first=check(ctx);run=finish(ctx,first['run']['id']);assert run['run']['status']=='succeeded',run
    assert len(ctx['calls'])==1
    assert 'RAW_PRIVATE_ARTIFACT' not in json.dumps(ctx['calls'][0])
    candidate=run['candidates'][0];before=rows(ctx['db'],('learning_session','learning_delegation','learning_action','learning_plan'))
    accepted=client.post(BASE+'/candidates/'+candidate['id']+'/decisions',json={'operation':'accept','expected_revision':1,'request_key':'accept'})
    assert accepted.status_code==200,accepted.text
    assert accepted.json()['navigation']['href'].startswith('?view=plans&plan=')
    assert before==rows(ctx['db'],before)
    assert client.get(BASE+'?scope=plan&plan_id='+ctx['plan_id']).json()['history'][0]['id']==candidate['id']
    assert check(ctx,'reopen',trigger='return')['reason']=='coach_disabled'
    assert check(ctx,'same-sources')['reason']=='coach_no_new_signals'
    assert check(ctx)['run']['id']==first['run']['id'] and len(ctx['calls'])==1

def test_source_cross_scope_consumed_and_failure_only_explicit_retry(coach):
    ctx=coach;end(ctx);ctx['error']=True
    first=check(ctx);failed=finish(ctx,first['run']['id']);assert failed['run']['status']=='failed'
    settings(ctx)
    assert check(ctx,'return-plan',trigger='return',scope='plan')['reason']=='coach_no_new_signals'
    ctx['error']=False
    retry=check(ctx,'retry',retry_run_id=first['run']['id']);assert finish(ctx,retry['run']['id'])['run']['status']=='succeeded'
    assert len(ctx['calls'])==2
    assert ctx['client'].post(BASE+'/checks',json={'trigger':'return','scope':'global','request_key':'badretry','retry_run_id':first['run']['id']}).status_code==409

def test_sent_failure_counts_automatic_and_structured_feedback_keeps_session_quota(coach):
    ctx=coach;session,_=end(ctx);settings(ctx);ctx['error']=True
    started=check(ctx,'automatic',trigger='return');assert finish(ctx,started['run']['id'])['run']['status']=='failed'
    assert ctx['client'].get(BASE).json()['budget']['used_today']==1
    response=ctx['client'].post('/api/learning/sessions/'+session+'/feedback',json={'expected_revision':0,'request_key':'feedback','purpose':'real','progress':'difficulty','notes':'FEEDBACK_PRIVATE_NOTES'})
    assert response.status_code==200,response.text
    from app.coach_sources import collect,input_state
    with ctx['db'].transaction() as c:
        refs=collect(c,ctx['identity']['id'],'plan',ctx['plan_id'],utc_timestamp(),ctx['service'].chats)
        assert refs and all(r['session_id']==session and r['action_id']==ctx['item']['action_id'] for r in refs)
        inputs=input_state(c,ctx['identity']['id'],'plan',ctx['plan_id'],refs,ctx['service'].chats)
        assert inputs['feedback'][0]['progress']=='difficulty' and 'FEEDBACK_PRIVATE_NOTES' not in json.dumps(inputs)
        tomorrow=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        assert budget(c,ctx['identity']['id'],tomorrow)['session_counts'][session]==1

def test_live_context_change_invalidates_candidate_and_reject_ignore_undo_are_audited(coach):
    ctx=coach;end(ctx);result=finish(ctx,check(ctx)['run']['id']);candidate=result['candidates'][0]
    client=ctx['client'];route=BASE+'/candidates/'+candidate['id']+'/decisions'
    rejected=client.post(route,json={'operation':'reject','expected_revision':1,'request_key':'reject'});assert rejected.status_code==200,rejected.text
    undo=client.post(route,json={'operation':'undo','expected_revision':2,'request_key':'undo'});assert undo.status_code==200,undo.text
    ignored=client.post(route,json={'operation':'ignore','expected_revision':3,'request_key':'ignore'});assert ignored.status_code==200,ignored.text
    assert ctx['db'].fetchone('SELECT COUNT(*) FROM learning_coach_decision')[0]==3
    # A new formal task is a relevant frozen-context change, not an authorization
    # to silently retarget an old recommendation.
    task(client,get(client,ctx['plan_id']),'new-actual-task')
    assert client.get(BASE+'/candidates/'+candidate['id']).json()['status']=='unavailable'
    invalid=client.post(route,json={'operation':'undo','expected_revision':4,'request_key':'stale-undo'})
    assert invalid.status_code==409

def test_canceled_before_http_releases_reservation_and_close_blocks_late_candidates(coach):
    import asyncio
    ctx=coach;end(ctx);settings(ctx);ctx['service'].slots=asyncio.Semaphore(0)
    started=check(ctx,'queued',trigger='return');identifier=started['run']['id']
    assert ctx['client'].get(BASE).json()['budget']['used_today']==0
    response=ctx['client'].post(BASE+'/checks/'+identifier+'/cancel',json={'expected_revision':1,'request_key':'cancel'})
    assert response.status_code==200,response.text
    assert not ctx['calls'] and ctx['client'].get(BASE).json()['budget']['remaining_today']==3
    ctx['service'].slots=asyncio.Semaphore(4);ctx['slow']=True
    retried=check(ctx,'manual-retry',retry_run_id=identifier)
    for _ in range(100):
        if ctx['calls']: break
        time.sleep(.01)
    # Manual runs remain user-authorized while automatic collection is off.
    settings(ctx,False)
    assert finish(ctx,retried['run']['id'])['run']['status']=='succeeded'

def test_core_replay_retains_coach_projections_and_private_purge(coach,tmp_path):
    from app.learning_production import create_learning_backup,restore_learning_backup,ProductionLearningDatabaseError
    ctx=coach;end(ctx);result=finish(ctx,check(ctx)['run']['id']);identifier=result['run']['id']
    before=rows(ctx['db'],PROJECTION_TABLES)
    response=ctx['client'].post('/api/learning/replay')
    assert response.status_code==200,response.text
    assert before==rows(ctx['db'],PROJECTION_TABLES)
    create_learning_backup(ctx['db'].database_path,tmp_path/'backups',label='pre-coach-purge')
    response=ctx['client'].post(BASE+'/checks/'+identifier+'/purge',json={'expected_revision':result['run']['revision'],'request_key':'purge','confirmation':'PURGE'})
    assert response.status_code==200,response.text
    assert ctx['client'].get(BASE+'/checks/'+identifier).json()['inputs'] is None
    assert 'COACH_PRIVATE_REASON' not in json.dumps([dict(r) for r in ctx['db'].fetchall('SELECT * FROM learning_event')])
    from test_managed_purge import absent
    absent(ctx['db'].database_path,'COACH_PRIVATE_REASON')
    for path in (tmp_path/'backups').glob('*.sqlite3'): absent(path,'COACH_PRIVATE_REASON')
    before=rows(ctx['db'],PROJECTION_TABLES)
    response=ctx['client'].post('/api/learning/replay');assert response.status_code==200,response.text
    assert before==rows(ctx['db'],PROJECTION_TABLES)

def permission_candidate(ctx):
    ctx['target_kind']='permission_review';end(ctx)
    result=finish(ctx,check(ctx)['run']['id']);assert result['run']['status']=='succeeded',result
    candidate=result['candidates'][0];request=candidate['target']['permission_request']
    response=ctx['client'].post('/api/learning/agent/permission-requests',json={k:request[k] for k in
        ('purpose','target_id','content_granularity','ttl_seconds','request_key')})
    assert response.status_code==201,response.text
    requested=response.json()
    approved=ctx['client'].post('/api/learning/agent/permission-requests/'+requested['id']+'/approve')
    assert approved.status_code==200,approved.text
    return candidate,requested['id']

def test_manual_new_permission_reads_real_limited_context_once_and_explicit_retry(coach):
    ctx=coach;candidate,request_id=permission_candidate(ctx)
    assert 'RAW_PRIVATE_ARTIFACT' not in json.dumps(ctx['calls'][0])
    params=dict(permission_candidate_id=candidate['id'],permission_request_id=request_id)
    ctx['error']=True
    started=check(ctx,'with-permission',**params);failed=finish(ctx,started['run']['id'])
    assert failed['run']['status']=='failed' and failed['inputs']['authorization']['artifacts'][0]['content']=='RAW_PRIVATE_ARTIFACT'
    assert 'RAW_PRIVATE_ARTIFACT' in json.dumps(ctx['calls'][1])
    ctx['error']=False
    retried=check(ctx,'permission-retry',retry_run_id=started['run']['id'],**params)
    result=finish(ctx,retried['run']['id']);assert result['run']['status']=='succeeded',result
    assert check(ctx,'permission-repeat',**params)['run']['id']==retried['run']['id']
    assert len(ctx['calls'])==3
    # Same action/purpose full_text permission without this candidate's stable
    # request identity is not a substitute for its explicitly bound grant.
    other=ctx['client'].post('/api/learning/agent/permission-requests',json={'purpose':candidate['target']['permission_request']['purpose'],
        'target_id':ctx['item']['action_id'],'content_granularity':'full_text','ttl_seconds':300,'request_key':'unrelated-old-purpose'}).json()
    bad=ctx['client'].post(BASE+'/checks',json={'scope':'global','trigger':'manual','request_key':'wrong-grant',
        'permission_candidate_id':candidate['id'],'permission_request_id':other['id']})
    assert bad.status_code==403 and len(ctx['calls'])==3

def test_permission_revoke_before_send_and_after_send_stops_late_candidates(coach):
    import asyncio
    ctx=coach;candidate,request_id=permission_candidate(ctx)
    ctx['service'].slots=asyncio.Semaphore(0)
    params=dict(permission_candidate_id=candidate['id'],permission_request_id=request_id)
    run=check(ctx,'permission-queued',**params)['run']
    response=ctx['client'].post('/api/learning/agent/permission-requests/'+request_id+'/revoke',json={'reason':'合成撤回'})
    assert response.status_code==200,response.text
    ctx['client'].post(BASE+'/checks/'+run['id']+'/cancel',json={'expected_revision':run['revision'],'request_key':'cancel-permission'})
    assert len(ctx['calls'])==1
    invalid=ctx['client'].post(BASE+'/checks',json={'scope':'global','trigger':'manual','request_key':'retry-revoked','retry_run_id':run['id'],**params})
    assert invalid.status_code==403

def test_authorized_context_artifact_purge_scrubs_derived_requests_and_backups(coach,tmp_path):
    from app.core.commands import PurgeArtifact
    from app.managed_purge import ManagedPurge
    from app.learning_production import create_learning_backup
    from test_managed_purge import absent
    ctx=coach;candidate,request_id=permission_candidate(ctx)
    run=finish(ctx,check(ctx,'authorized',permission_candidate_id=candidate['id'],permission_request_id=request_id)['run']['id'])
    assert run['run']['status']=='succeeded',run
    create_learning_backup(ctx['db'].database_path,tmp_path/'permission-backups',label='pre-permission-purge')
    artifact=ctx['db'].fetchone('SELECT artifact_id FROM learning_raw_artifact WHERE content=?',('RAW_PRIVATE_ARTIFACT',))[0]
    version=ctx['db'].fetchone('SELECT version FROM learning_action WHERE id=?',(ctx['item']['action_id'],))[0]
    ManagedPurge(ctx['service'].learning).run(ctx['identity'],'artifact',artifact,
        lambda:ctx['service'].learning.core.execute(Principal.user(ctx['identity']['id']),PurgeArtifact(artifact_id=artifact,expected_version=version,confirmation='PURGE'),'purge-raw'))
    assert ctx['client'].get(BASE+'/checks/'+run['run']['id']).json()['inputs'] is None
    assert ctx['db'].fetchone('SELECT purpose FROM learning_agent_permission_request WHERE id=?',(request_id,))[0]=='内容已清除'
    assert ctx['db'].fetchone('SELECT status FROM learning_agent_permission_grant WHERE request_id=?',(request_id,))[0]=='revoked'
    absent(ctx['db'].database_path,'RAW_PRIVATE_ARTIFACT')
    for path in (tmp_path/'permission-backups').glob('*.sqlite3'): absent(path,'RAW_PRIVATE_ARTIFACT')

def test_terminal_permission_requires_explicit_new_attempt_and_old_grant_never_reopens(coach):
    ctx=coach;candidate,request_id=permission_candidate(ctx);client=ctx['client']
    old=candidate['target']['permission_request']['request_key']
    revoked=client.post('/api/learning/agent/permission-requests/'+request_id+'/revoke',json={'reason':'合成撤回'})
    assert revoked.status_code==200,revoked.text
    next_candidate=client.get(BASE+'/candidates/'+candidate['id']).json()
    requested=next_candidate['target']['permission_request']
    assert old.endswith(':1') and requested['request_key'].endswith(':2')
    invalid=client.post(BASE+'/checks',json={'scope':'global','trigger':'manual','request_key':'no-renew-old',
        'permission_candidate_id':candidate['id'],'permission_request_id':request_id})
    assert invalid.status_code==403 and len(ctx['calls'])==1
    new=client.post('/api/learning/agent/permission-requests',json={k:requested[k] for k in ('purpose','target_id','content_granularity','ttl_seconds','request_key')}).json()
    # Merely asking or viewing a new attempt does not approve it or invoke AI.
    assert client.get(BASE+'/candidates/'+candidate['id']).json()['target']['permission_request']['request_key']==requested['request_key']
    assert len(ctx['calls'])==1
    assert client.post('/api/learning/agent/permission-requests/'+new['id']+'/approve').status_code==200
    run=check(ctx,'new-approved-attempt',permission_candidate_id=candidate['id'],permission_request_id=new['id'])['run']
    assert finish(ctx,run['id'])['run']['status']=='succeeded' and len(ctx['calls'])==2

def test_permission_revoked_after_http_never_writes_late_candidates(coach):
    ctx=coach;candidate,request_id=permission_candidate(ctx);ctx['slow']=True
    run=check(ctx,'permission-sending',permission_candidate_id=candidate['id'],permission_request_id=request_id)['run']
    for _ in range(100):
        if len(ctx['calls'])==2: break
        time.sleep(.01)
    assert len(ctx['calls'])==2
    assert ctx['client'].post('/api/learning/agent/permission-requests/'+request_id+'/revoke',json={'reason':'合成撤回'}).status_code==200
    result=finish(ctx,run['id'])
    assert result['run']['status']=='failed' and result['candidates']==[]

def test_chinese_large_scope_is_bounded_and_unselected_events_stay_pending(coach):
    from app.coach_sources import input_bytes,MAX_INPUT_BYTES,collect
    ctx=coach;client=ctx['client']
    for n in range(12): task(client,get(client,ctx['plan_id']),'long-'+str(n),action_title='中'*220+str(n))
    end(ctx)
    result=finish(ctx,check(ctx)['run']['id']);assert result['run']['status']=='succeeded',result
    assert input_bytes(ctx['calls'][0][1])<=MAX_INPUT_BYTES
    for n in range(26): end(ctx,'additional-'+str(n),artifact=False)
    with ctx['db'].transaction() as c:
        pending=collect(c,ctx['identity']['id'],'global',None,utc_timestamp(),ctx['service'].chats)
        assert len(pending)==24
    next_result=finish(ctx,check(ctx,'next-bounded')['run']['id']);assert next_result['run']['status']=='succeeded',next_result
    assert ctx['client'].get(BASE).json()['pending_signals']>0

def test_automatic_selection_excludes_full_session_before_batch_cap(coach,monkeypatch):
    from app import core
    import app.core.learning as learning_module
    from app.coach_sources import collect
    ctx=coach;db=ctx['db'];p=Principal.user(ctx['identity']['id']);engine=ctx['service'].learning.core
    version=lambda:db.fetchone('SELECT version FROM learning_action WHERE id=?',(ctx['item']['action_id'],))[0]
    s1=engine.execute(p,StartSession(delegation_id=ctx['item']['delegation_id'],expected_version=version()),'large-s1-start')['id']
    for n in range(51): engine.execute(p,SaveTextArtifact(session_id=s1,content='synthetic '+str(n),expected_version=version()),'large-artifact-'+str(n))
    engine.execute(p,EndSession(session_id=s1,disposition='interrupted',expected_version=version()),'large-s1-end')
    settings(ctx)
    first=finish(ctx,check(ctx,'first-auto',trigger='return')['run']['id']);assert first['run']['status']=='succeeded'
    with db.transaction() as c:
        old=collect(c,ctx['identity']['id'],'global',None,utc_timestamp(),ctx['service'].chats)
        assert len(old)>=24 and all(r['session_id']==s1 for r in old)
    future=(datetime.now(timezone.utc)+timedelta(minutes=31)).isoformat().replace('+00:00','Z')
    monkeypatch.setattr(learning_module,'utc_timestamp',lambda:future);ctx['service'].clock=lambda:future
    s2,_=end(ctx,'new-session',artifact=False)
    value=check(ctx,'second-auto',trigger='return')
    run=value['run'] or value['view']['active_run'] or value['view']['latest_run']
    result=finish(ctx,run['id']);assert result['run']['status']=='succeeded',result
    assert len(ctx['calls'])==2 and any(r['session_id']==s2 for r in ctx['calls'][1][1]['refs'])
    assert all(r['session_id']!=s1 for r in ctx['calls'][1][1]['refs'])

def test_exact_claim_accept_points_to_original_review_without_adopting(coach):
    from test_evidence_claims import create_standard_chain
    ctx=coach;created=create_standard_chain(ctx['client'])
    ctx['client'].app.state.evidence.semantic_analyzer=lambda _:[]
    response=ctx['client'].post('/api/learning/artifacts/'+created['artifact']['id']+'/analysis',json={'request_key':'actual-claim'})
    assert response.status_code==200,response.text
    claim=response.json()['claims'][0]
    # Select an exact existing claim target, never inject a coach table row.
    original_transport=ctx['service'].transport
    async def exact(request):
        payload=json.loads(request.content);inputs=json.loads(payload['messages'][-1]['content'])
        chosen=next(t for t in inputs['targets'] if t['kind']=='evidence_review' and t['object_id']==claim['id'])
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'candidates':[dict(title='核对已有依据',explanation='复核来源与范围。',unknowns=[],
            source_refs=[r for r in inputs['refs'] if r['kind']=='claim' and r['id']==claim['id']],target={k:chosen[k] for k in ('kind','plan_id','action_id','delegation_id','object_id')})]})},'finish_reason':'stop'}]})
    ctx['service'].transport=httpx.MockTransport(exact)
    result=finish(ctx,check(ctx)['run']['id']);assert result['run']['status']=='succeeded',result
    candidate=result['candidates'][0]
    accepted=ctx['client'].post(BASE+'/candidates/'+candidate['id']+'/decisions',json={'operation':'accept','expected_revision':1,'request_key':'claim-accept'})
    assert accepted.status_code==200,accepted.text
    target=accepted.json()['navigation']
    assert target['object_id']==claim['id'] and 'review_claim='+claim['id'] in target['href']
    assert ctx['db'].fetchone('SELECT status FROM learning_evidence_claim WHERE id=?',(claim['id'],))[0]=='candidate'

def test_readonly_candidate_survives_completion_but_task_execution_requires_new_state(coach):
    from app.core.commands import CompleteLearningAction
    ctx=coach;end(ctx);ctx['target_kind']='evidence_review'
    result=finish(ctx,check(ctx)['run']['id']);candidate=result['candidates'][0]
    version=ctx['db'].fetchone('SELECT version FROM learning_action WHERE id=?',(ctx['item']['action_id'],))[0]
    ctx['service'].learning.core.execute(Principal.user(ctx['identity']['id']),CompleteLearningAction(
        action_id=ctx['item']['action_id'],delegation_id=ctx['item']['delegation_id'],expected_version=version),'complete-after-readonly')
    assert ctx['client'].get(BASE+'/candidates/'+candidate['id']).json()['status']=='pending'
    accepted=ctx['client'].post(BASE+'/candidates/'+candidate['id']+'/decisions',json={'operation':'accept','expected_revision':1,'request_key':'readonly-accept'})
    assert accepted.status_code==200,accepted.text
