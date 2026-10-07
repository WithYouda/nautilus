"""Real D2/Core sources and injected clock; notifications never call a Provider."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import pytest
from app.core.commands import StartSession,EndSession
from app.learning_domain import Principal
from test_commitments import arranged,item,save,confirm,start,stop,base,view

BASE='/api/learning/coach/reminders'

@pytest.fixture
def reminder(arranged,monkeypatch):
    ctx=arranged
    ctx['now']=datetime(2027,3,17,8,59,tzinfo=timezone.utc)
    stamp=lambda:ctx['now'].isoformat().replace('+00:00','Z')
    ctx['client'].app.state.coach_reminders.clock=stamp
    import app.core.learning as core
    monkeypatch.setattr(core,'utc_timestamp',stamp)
    due=(ctx['now']+timedelta(minutes=1)).isoformat().replace('+00:00','Z')
    current=confirm(ctx,save(ctx,[item(ctx,due_at=due,timezone='UTC')]))
    ctx['item_id']=current['current_version']['items'][0]['id']
    return ctx

def settings(ctx,**changes):
    client=ctx['client'];old=client.get(BASE+'/settings').json()
    payload={**{k:v for k,v in old.items() if k!='revision'},'expected_revision':old['revision'],'request_key':'settings-'+str(old['revision']),**changes}
    response=client.put(BASE+'/settings',json=payload)
    assert response.status_code==200,response.text
    return response.json()['settings']

def state(ctx):
    response=ctx['client'].get(BASE);assert response.status_code==200,response.text
    assert response.headers['cache-control']=='no-store'
    return response.json()

def dispatch(ctx,row,key='dispatch'):
    response=ctx['client'].post(BASE+'/'+row['id']+'/dispatch',json={'expected_revision':row['revision'],'request_key':key})
    assert response.status_code==200,response.text
    return response.json()

def test_precise_due_followup_global_budget_replay_and_timezone_change(reminder):
    ctx=reminder;settings(ctx,enabled=True,quiet_enabled=False)
    assert state(ctx)['due']==[]
    ctx['now']+=timedelta(minutes=1);row=state(ctx)['due'][0]
    assert row['target']['item_id']==ctx['item_id']
    assert state(ctx)['budget']['used_today']==0
    first=dispatch(ctx,row);assert first['claimed'] and first['view']['budget']['used_today']==1
    assert not dispatch(ctx,row)['claimed']
    ctx['now']+=timedelta(minutes=29);assert not state(ctx)['due']
    ctx['now']+=timedelta(minutes=1);second=state(ctx)['due'][0];assert second['stage']=='followup'
    assert dispatch(ctx,second,'followup')['claimed']
    settings(ctx,timezone='Pacific/Honolulu')
    assert state(ctx)['budget']['used_today']==2 and not state(ctx)['budget']['remaining_today']
    assert ctx['db'].fetchone('SELECT COUNT(*) FROM learning_completion')[0]==0

def test_fixed_and_current_arrangement_same_time_merge_and_atomic_tabs(reminder):
    ctx=reminder;settings(ctx,enabled=True,quiet_enabled=False,study_times=[{'id':'morning','time':'09:00','weekdays':[3]}])
    ctx['now']+=timedelta(minutes=1);row=state(ctx)['due'][0]
    assert ctx['db'].fetchone('SELECT COUNT(*) FROM learning_coach_reminder WHERE stage=\'initial\' AND scheduled_at<=?',(ctx['now'].isoformat().replace('+00:00','Z'),))[0]==1
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(lambda key:dispatch(ctx,row,key),('tab-one','tab-two')))
    assert sum(result['claimed'] for result in results)==1
    assert state(ctx)['budget']['used_today']==1

def test_started_from_plain_task_suppresses_and_end_is_not_completion(reminder):
    ctx=reminder;settings(ctx,enabled=True,quiet_enabled=False)
    ctx['now']+=timedelta(minutes=1);row=state(ctx)['due'][0];dispatch(ctx,row)
    core=ctx['client'].app.state.learning.core;principal=Principal.user(ctx['identity']['id'])
    version=ctx['db'].fetchone('SELECT version FROM learning_action WHERE id=?',(ctx['first']['action_id'],))[0]
    session=core.execute(principal,StartSession(delegation_id=ctx['first']['delegation_id'],expected_version=version),'plain-start')['id']
    assert state(ctx)['learning_active'] and not state(ctx)['due']
    assert state(ctx)['recent'][0]['status']=='unavailable'
    version=ctx['db'].fetchone('SELECT version FROM learning_action WHERE id=?',(ctx['first']['action_id'],))[0]
    core.execute(principal,EndSession(session_id=session,disposition='interrupted',expected_version=version),'plain-end')
    ctx['now']+=timedelta(minutes=40)
    assert not state(ctx)['due'] and ctx['db'].fetchone('SELECT status FROM learning_action WHERE id=?',(ctx['first']['action_id'],))[0]=='open'

def test_explicit_item_early_start_completed_block_not_relabelled_unstarted(reminder):
    ctx=reminder;settings(ctx,enabled=True,quiet_enabled=False)
    ctx['now']-=timedelta(minutes=59)
    begun=start(ctx,ctx['item_id']);ctx['now']+=timedelta(minutes=30);stop(ctx,begun['session_id'],artifact=False)
    ctx['now']+=timedelta(minutes=30)
    assert not state(ctx)['due']
    assert ctx['db'].fetchone('SELECT status FROM learning_action WHERE id=?',(ctx['first']['action_id'],))[0]=='open'

def test_old_ended_session_before_new_time_does_not_fake_new_start(reminder):
    ctx=reminder;core=ctx['client'].app.state.learning.core;principal=Principal.user(ctx['identity']['id'])
    ctx['now']-=timedelta(minutes=120)
    version=lambda:ctx['db'].fetchone('SELECT version FROM learning_action WHERE id=?',(ctx['first']['action_id'],))[0]
    session=core.execute(principal,StartSession(delegation_id=ctx['first']['delegation_id'],expected_version=version()),'old-task-start')['id']
    ctx['now']+=timedelta(minutes=30)
    core.execute(principal,EndSession(session_id=session,disposition='interrupted',expected_version=version()),'old-task-end')
    ctx['now']+=timedelta(minutes=90);settings(ctx,enabled=True,quiet_enabled=False)
    ctx['now']+=timedelta(minutes=1)
    assert state(ctx)['due'][0]['target']['item_id']==ctx['item_id']

def test_real_reschedule_skip_and_disable_remove_stale_dispatched_targets(reminder):
    ctx=reminder;client=ctx['client'];settings(ctx,enabled=True,quiet_enabled=False)
    ctx['now']+=timedelta(minutes=1);row=state(ctx)['due'][0];dispatch(ctx,row)
    due=(ctx['now']+timedelta(hours=1)).isoformat().replace('+00:00','Z')
    preview=client.post(base(ctx)+'/items/'+ctx['item_id']+'/preview',json={'operation':'defer','due_at':due,'timezone':'UTC'}).json()
    result=client.post(base(ctx)+'/items/'+ctx['item_id']+'/defer',json={'expected_revision':preview['revision'],'review_key':preview['review_key'],'due_at':due,'timezone':'UTC','request_key':'move'})
    assert result.status_code==200,result.text
    assert not state(ctx)['due'] and state(ctx)['recent'][0]['status']=='unavailable'
    assert client.post(BASE+'/'+row['id']+'/resolve',json={'source_revision':row['source_revision']}).status_code==409
    ctx['now']+=timedelta(hours=1);new=state(ctx)['due'][0];assert new['id']!=row['id']
    dispatch(ctx,new,'new-time')
    settings(ctx,enabled=False)
    assert all(r['status']=='unavailable' for r in state(ctx)['recent']) and state(ctx)['budget']['used_today']==2

def test_quiet_merge_and_switchable_followup(reminder):
    ctx=reminder;settings(ctx,enabled=True,quiet_enabled=True,quiet_start='08:00',quiet_end='10:00')
    ctx['now']+=timedelta(minutes=1);assert not state(ctx)['due'] and state(ctx)['quiet_now']
    ctx['now']+=timedelta(hours=1);row=state(ctx)['due'][0];assert dispatch(ctx,row)['claimed']
    settings(ctx,followup_enabled=False)
    ctx['now']+=timedelta(minutes=45);assert not state(ctx)['due']

def test_policy_edit_preserves_initial_and_reschedules_followup(reminder):
    ctx=reminder;settings(ctx,enabled=True,quiet_enabled=False,study_times=[{'id':'morning','time':'09:00','weekdays':[3]}])
    ctx['now']+=timedelta(minutes=1);row=state(ctx)['due'][0];dispatch(ctx,row)
    ctx['now']+=timedelta(minutes=5);settings(ctx,browser_enabled=True,followup_delay_minutes=10)
    assert state(ctx)['budget']['used_today']==1
    ctx['now']+=timedelta(minutes=5);follow=state(ctx)['due'][0]
    assert follow['stage']=='followup' and follow['target']['item_id']==ctx['item_id']

def test_same_time_retarget_does_not_inherit_previous_items_followup(reminder):
    ctx=reminder;due=(ctx['now']+timedelta(minutes=1)).isoformat().replace('+00:00','Z')
    current=confirm(ctx,save(ctx,[item(ctx,due_at=due,timezone='UTC'),item(ctx,'second',due_at=due,timezone='UTC')],key='two-save'),key='two-confirm')
    first_id=current['current_version']['items'][0]['id'];ctx['item_id']=first_id
    settings(ctx,enabled=True,quiet_enabled=False);ctx['now']+=timedelta(minutes=1)
    row=state(ctx)['due'][0];dispatch(ctx,row)
    selected=row['target']['item_id']
    preview=ctx['client'].post(base(ctx)+'/items/'+selected+'/preview',json={'operation':'skip'}).json()
    response=ctx['client'].post(base(ctx)+'/items/'+selected+'/skip',json={'expected_revision':preview['revision'],'review_key':preview['review_key'],'request_key':'skip-selected'})
    assert response.status_code==200,response.text
    ctx['now']+=timedelta(minutes=30)
    assert not state(ctx)['due'] and state(ctx)['recent'][0]['status']=='unavailable'

def test_real_start_pause_next_fixed_time_resumes_unfinished_then_completion_invalidates(reminder):
    from app.completion import CompletionService
    from test_completion import request
    ctx=reminder;settings(ctx,enabled=True,quiet_enabled=False,study_times=[{'id':'return','time':'10:00','weekdays':[3]}])
    ctx['now']+=timedelta(minutes=1);initial=state(ctx)['due'][0];dispatch(ctx,initial)
    begun=start(ctx,ctx['item_id']);ctx['now']+=timedelta(minutes=15);stop(ctx,begun['session_id'],artifact=False)
    assert not state(ctx)['due'] and ctx['db'].fetchone('SELECT COUNT(*) FROM learning_completion')[0]==0
    ctx['now']+=timedelta(minutes=45);resume=state(ctx)['due'][0]
    assert resume['target']['item_id']==ctx['item_id'] and '继续上次' in resume['title'] and '还没有完成' in resume['body']
    assert dispatch(ctx,resume,'resume')['claimed']
    ctx['now']+=timedelta(minutes=31);assert not state(ctx)['due']
    completion=CompletionService(ctx['client'].app.state.verification).create(ctx['identity'],ctx['first']['delegation_id'],request())
    assert completion['verification_kind']=='unverified'
    assert state(ctx)['recent'][0]['status']=='unavailable'
    assert ctx['client'].post(BASE+'/'+resume['id']+'/resolve',json={'source_revision':resume['source_revision']}).status_code==409
