"""Real Core/API route journeys against isolated synthetic learning data."""
import json
import sqlite3
from contextlib import closing

import pytest

from app.core.commands import EndSession
from app.core.learning_paths import PATH_PROJECTION_TABLES
from app.learning_production import (create_learning_backup, restore_learning_backup, ProductionLearningDatabaseError,
                                    _backup_loses_purge_barriers, file_sha256)
from test_evidence_claims import authorize
from test_managed_purge import absent
from test_plan_organization import plan, task, get, rows as snapshot


def seed(client):
    identity=authorize(client)
    organization=plan(client)
    plan_id=organization['plan']['id']
    first=task(client,organization,'first')
    second=task(client,get(client,plan_id),'second')
    return identity,plan_id,first,second


def path(client,plan_id):
    response=client.get(f'/api/learning/plans/{plan_id}/path')
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='no-store'
    return response.json()


def draft(client,plan_id,first,second,**changes):
    current=path(client,plan_id)
    body=dict(title='PRIVATE-ROUTE-EXAMPLE',
        nodes=[dict(id='entry',title='PRIVATE-ENTRY-EXAMPLE',action_ids=[first['action_id']],outcome_ids=[first['outcome_id']]),
               dict(id='practice',title='PRIVATE-PRACTICE-EXAMPLE',action_ids=[second['action_id']],outcome_ids=[second['outcome_id']])],
        edges=[dict(source='entry',target='practice')],entry_node_id='entry',current_node_id='entry',reason='PRIVATE-ROUTE-REASON',
        expected_revision=current['revision'],expected_organization_revision=current['organization_revision'],
        intent='create' if current['adopted_version_id'] is None else 'change_scope',request_key='draft-'+str(current['revision']))
    body.update(changes)
    response=client.post(f'/api/learning/plans/{plan_id}/path/drafts',json=body)
    assert response.status_code==200,response.text
    return response.json(),body


def preview(client,plan_id,value):
    response=client.post(f'/api/learning/plans/{plan_id}/path/previews',json={'draft_id':value['draft_id']})
    assert response.status_code==200,response.text
    return response.json()


def confirm(client,plan_id,value,key='confirm'):
    review=preview(client,plan_id,value)
    body=dict(draft_id=value['draft_id'],expected_draft_revision=review['draft_revision'],
              expected_revision=review['revision'],review_key=review['review_key'],request_key=key)
    response=client.post(f'/api/learning/plans/{plan_id}/path/decisions',json=body)
    assert response.status_code==200,response.text
    return response.json(),body


def start(client,plan_id,value,node,delegation_id,key='start',**changes):
    state=client.get('/api/learning/state').json()
    delegation=next(d for d in state['delegations'] if d['id']==delegation_id)
    action=next(a for a in state['actions'] if a['id']==delegation['action_id'])
    response=client.post(f'/api/learning/plans/{plan_id}/path/start',json=dict(
        version_id=value['adopted_version_id'],node_id=node,delegation_id=delegation_id,
        expected_action_version=action['version'],expected_revision=value['revision'],request_key=key,**changes))
    assert response.status_code==200,response.text
    return response.json()


def test_manual_route_draft_confirm_position_switch_history_and_replay(client):
    identity,plan_id,first,second=seed(client)
    db=client.app.state.learning.database
    original=snapshot(db,('learning_raw_artifact','learning_criterion_version','learning_evidence_claim'))
    value,body=draft(client,plan_id,first,second)
    assert value['adopted_version_id'] is None and not db.fetchall('SELECT * FROM learning_session')
    adopted,confirmed=confirm(client,plan_id,value)
    repeat=client.post(f'/api/learning/plans/{plan_id}/path/decisions',json=confirmed)
    assert repeat.status_code==200 and repeat.json()['adopted_version_id']==adopted['adopted_version_id']
    assert not db.fetchall('SELECT * FROM learning_session')
    old_version=adopted['adopted_version_id']
    session=start(client,plan_id,adopted,'entry',first['delegation_id'])
    assert path(client,plan_id)['current_node_id']=='entry'
    changed,_=draft(client,plan_id,first,second,intent='change_entry',entry_node_id='practice',
                    current_node_id='practice',edges=[dict(source='practice',target='entry')],request_key='change-entry')
    review=preview(client,plan_id,changed)
    assert [s['id'] for s in review['affected_sessions']]==[session['session_id']]
    new,_=confirm(client,plan_id,changed,'confirm-entry')
    assert db.fetchone('SELECT status FROM learning_session WHERE id=?',(session['session_id'],))[0]=='interrupted'
    assert len(db.fetchall('SELECT * FROM learning_session'))==1
    assert new['adopted_version_id']!=old_version and len(new['versions'])==2
    assert new['versions'][0]['checkpoint']['node_id']=='entry'
    assert snapshot(db,original.keys())==original
    replay=client.app.state.learning.core.replay(client.app.state.learning.principal(identity))
    assert replay['comparison']['matched']
    assert path(client,plan_id)['adopted_version_id']==new['adopted_version_id']


def test_explicit_task_position_does_not_fork_and_same_start_retry_is_idempotent(client):
    _identity,plan_id,first,second=seed(client)
    value,_=draft(client,plan_id,first,second)
    adopted,_=confirm(client,plan_id,value)
    action_version=next(a['version'] for a in client.get('/api/learning/state').json()['actions'] if a['id']==first['action_id'])
    started=start(client,plan_id,adopted,'entry',first['delegation_id'])
    repeated=client.post(f'/api/learning/plans/{plan_id}/path/start',json=dict(
        version_id=adopted['adopted_version_id'],node_id='entry',delegation_id=first['delegation_id'],
        expected_action_version=action_version,expected_revision=adopted['revision'],request_key='start'))
    assert repeated.status_code==200 and repeated.json()==started
    new=path(client,plan_id)
    started_second=start(client,plan_id,new,'practice',second['delegation_id'],'second-start')
    after=path(client,plan_id)
    assert len(after['versions'])==1 and after['current_node_id']=='practice'
    assert started_second['session_id']!=started['session_id']
    db=client.app.state.learning.database
    assert len(db.fetchall("SELECT * FROM learning_session WHERE status='running'"))==1
    # A normal return-card task switch has no authority to change the route marker.
    action=db.fetchone('SELECT version FROM learning_action WHERE id=?',(second['action_id'],))
    client.app.state.learning.core.execute(client.app.state.learning.principal(client.get('/api/auth/status').json()['identity']),
        EndSession(session_id=started_second['session_id'],disposition='interrupted',expected_version=action[0]),'ordinary-stop')
    assert path(client,plan_id)['current_node_id']=='practice'


def test_restore_is_new_decision_and_keeps_later_sessions(client):
    identity,plan_id,first,second=seed(client)
    value,_=draft(client,plan_id,first,second)
    adopted,_=confirm(client,plan_id,value)
    first_version=adopted['adopted_version_id']
    start(client,plan_id,adopted,'practice',second['delegation_id'])
    changed,_=draft(client,plan_id,first,second,current_node_id='entry',request_key='switch-back')
    updated,_=confirm(client,plan_id,changed,'switch-confirm')
    response=client.post(f'/api/learning/plans/{plan_id}/path/restore-draft',json=dict(
        version_id=first_version,intent='restore',expected_revision=updated['revision'],
        expected_organization_revision=updated['organization_revision'],request_key='restore-draft'))
    assert response.status_code==200,response.text
    restored,_=confirm(client,plan_id,response.json(),'restore-confirm')
    assert restored['current_node_id']=='practice'
    assert len(restored['versions'])==3 and len(client.app.state.learning.database.fetchall('SELECT * FROM learning_session'))==1
    assert client.app.state.learning.core.replay(client.app.state.learning.principal(identity))['comparison']['matched']


def test_cas_reference_scope_cycle_and_private_event_boundaries(client):
    _identity,plan_id,first,second=seed(client)
    value,body=draft(client,plan_id,first,second)
    endpoint=f'/api/learning/plans/{plan_id}/path/drafts'
    denied=client.post(endpoint,json={**body,'request_key':'stale'})
    assert denied.status_code==409
    assert client.post(endpoint,json={**body,'expected_revision':value['revision'],
        'edges':[{'source':'entry','target':'practice'},{'source':'practice','target':'entry'}],'request_key':'cycle'}).status_code==422
    other=plan(client,'other-plan')
    other_task=task(client,other,'other-task')
    assert client.post(endpoint,json={**body,'expected_revision':value['revision'],
        'nodes':[dict(id='entry',title='entry',action_ids=[other_task['action_id']],outcome_ids=[])],
        'edges':[],'request_key':'foreign-task'}).status_code==409
    db=client.app.state.learning.database
    event=db.fetchone("SELECT payload_json FROM learning_event WHERE event_type='path.draft_saved'")
    assert 'PRIVATE-ROUTE' not in event[0] and 'PRIVATE-ENTRY' not in event[0]
    assert 'PRIVATE-ROUTE' not in db.fetchone("SELECT result_json FROM learning_command WHERE command_type='SavePathDraft'")[0]


def test_route_private_purge_scrubs_original_and_explicit_copies_and_restores_barrier(client,tmp_path):
    identity,plan_id,first,second=seed(client)
    value,_=draft(client,plan_id,first,second)
    adopted,_=confirm(client,plan_id,value)
    old=adopted['adopted_version_id']
    copied,_=draft(client,plan_id,first,second,source_version_id=old,request_key='copied-draft')
    after,_=confirm(client,plan_id,copied,'copy-confirm')
    db=client.app.state.learning.database
    backup,_,_=create_learning_backup(db.database_path,tmp_path/'backups',label='path')
    result=client.post(f'/api/learning/plans/{plan_id}/path/versions/{old}/purge',json=dict(
        expected_revision=after['revision'],confirmation='PURGE',request_key='purge-route'))
    assert result.status_code==200,result.text
    assert result.json()['purge_report']['status']=='complete'
    assert all(not version['content_available'] for version in result.json()['path']['versions'])
    absent(db.database_path,'PRIVATE-ROUTE-EXAMPLE')
    absent(backup,'PRIVATE-ROUTE-EXAMPLE')
    assert client.app.state.learning.core.replay(client.app.state.learning.principal(identity))['comparison']['matched']
    # A scrubbed snapshot may be safe: its retained erasure barriers are the criterion.
    with closing(sqlite3.connect(backup)) as candidate:
        candidate.row_factory=sqlite3.Row
        assert not _backup_loses_purge_barriers(db.connection,candidate)
    bad,manifest,_=create_learning_backup(db.database_path,tmp_path/'backups',label='missing-route-barrier')
    with closing(sqlite3.connect(bad)) as candidate:
        candidate.execute('DELETE FROM learning_path_private_tombstone')
        candidate.commit()
    metadata=json.loads(manifest.read_text())
    metadata['sha256']=file_sha256(bad)
    manifest.write_text(json.dumps(metadata))
    with pytest.raises(ProductionLearningDatabaseError):
        restore_learning_backup(bad,db.database_path)


def link_chat(client,session_id):
    response=client.post('/api/ai/conversations',json={'context_scope':'independent'})
    assert response.status_code==201,response.text
    cid=response.json()['conversation']['id']
    response=client.put(f'/api/learning/sessions/{session_id}/room',json={'conversation_id':cid})
    assert response.status_code==200,response.text
    return cid


def test_generation_blocks_switch_and_confirm_rechecks_after_preview(client):
    identity,plan_id,first,second=seed(client)
    value,_=draft(client,plan_id,first,second)
    adopted,_=confirm(client,plan_id,value)
    session=start(client,plan_id,adopted,'entry',first['delegation_id'])
    cid=link_chat(client,session['session_id'])
    changed,_=draft(client,plan_id,first,second,current_node_id='practice',request_key='switch')
    review=preview(client,plan_id,changed)
    chatdb=client.app.state.conversations.database
    with chatdb.transaction() as connection:
        connection.execute("INSERT INTO ai_run(id,identity_id,conversation_id,status,created_at,updated_at) VALUES ('synthetic-active',?,?,'running','now','now')",(identity['id'],cid))
    url=f'/api/learning/plans/{plan_id}/path'
    blocked=client.post(url+'/previews',json={'draft_id':changed['draft_id']})
    assert blocked.status_code==409 and blocked.json()['detail']['kind']=='path_generation_running'
    blocked=client.post(url+'/decisions',json=dict(draft_id=changed['draft_id'],
        expected_draft_revision=review['draft_revision'],expected_revision=review['revision'],
        review_key=review['review_key'],request_key='busy-confirm'))
    assert blocked.status_code==409 and blocked.json()['detail']['kind']=='path_generation_running'
    db=client.app.state.learning.database
    assert db.fetchone('SELECT status FROM learning_session WHERE id=?',(session['session_id'],))[0]=='running'
    assert path(client,plan_id)['adopted_version_id']==adopted['adopted_version_id']
    with chatdb.transaction() as connection:
        connection.execute("UPDATE ai_run SET status='canceled' WHERE id='synthetic-active'")
    confirmed,_=confirm(client,plan_id,changed,'after-cancel')
    assert confirmed['adopted_version_id']!=adopted['adopted_version_id']


def test_restore_exact_answer_anchor_missing_source_and_explicit_task_fallback(client):
    identity,plan_id,first,second=seed(client)
    value,_=draft(client,plan_id,first,second)
    adopted,_=confirm(client,plan_id,value)
    old=adopted['adopted_version_id']
    session=start(client,plan_id,adopted,'entry',first['delegation_id'])
    cid=link_chat(client,session['session_id'])
    chatdb=client.app.state.conversations.database
    with chatdb.transaction() as connection:
        for index,leaf in enumerate(('original-answer','later-answer')):
            connection.execute("INSERT INTO message(id,conversation_id,role,content,sequence,created_at,updated_at) VALUES (?,?,'assistant','Synthetic answer',?,'now','now')",(leaf,cid,index))
    state_url=f'/api/conversation-state/conversation/{cid}'
    response=client.put(state_url,json={'expected_revision':0,'leaf_id':'original-answer','paths':{'original-answer':'original-answer'}})
    assert response.status_code==200,response.text
    changed,_=draft(client,plan_id,first,second,current_node_id='practice',request_key='leave-answer')
    after,_=confirm(client,plan_id,changed,'leave-confirm')
    old_view=next(v for v in after['versions'] if v['id']==old)
    assert old_view['checkpoint']['anchor']['leaf_id']=='original-answer'
    assert old_view['checkpoint']['precision']=='answer' and old_view['checkpoint']['available']
    response=client.put(state_url,json={'expected_revision':1,'leaf_id':'later-answer','paths':{'later-answer':'later-answer'}})
    assert response.status_code==200,response.text
    response=client.post(f'/api/learning/plans/{plan_id}/path/restore-draft',json=dict(
        version_id=old,intent='restore',expected_revision=after['revision'],
        expected_organization_revision=after['organization_revision'],request_key='restore-answer'))
    restored,_=confirm(client,plan_id,response.json(),'restore-answer-confirm')
    # Restoring without starting preserves that chosen answer even if the room's
    # global selection has since moved to another answer.
    leave_again,_=draft(client,plan_id,first,second,current_node_id='practice',request_key='inspect-stopped-anchor')
    stopped_preview=preview(client,plan_id,leave_again)
    assert stopped_preview['checkpoint']['anchor']['leaf_id']=='original-answer'
    restored=path(client,plan_id)
    resumed=start(client,plan_id,restored,'entry',first['delegation_id'],'resume-answer')
    assert resumed['path_anchor']['leaf_id']=='original-answer'
    assert resumed['path_anchor']['paths']=={'original-answer':'original-answer'}
    # Continuing a live session keeps its actual latest answer instead of rewinding it.
    continued=start(client,plan_id,path(client,plan_id),'entry',first['delegation_id'],'continue-live')
    assert continued['session_id']==resumed['session_id'] and continued['path_anchor']['leaf_id']=='later-answer'
    # Stop, then remove the anchored source. Repeating the exact resume cannot fabricate it.
    db=client.app.state.learning.database
    action=db.fetchone('SELECT version FROM learning_action WHERE id=?',(first['action_id'],))
    client.app.state.learning.core.execute(client.app.state.learning.principal(identity),
        EndSession(session_id=resumed['session_id'],disposition='interrupted',expected_version=action[0]),'stop-anchor')
    with chatdb.transaction() as connection:
        connection.execute("DELETE FROM message WHERE id='later-answer'")
    current=path(client,plan_id)
    endpoint=f'/api/learning/plans/{plan_id}/path/start'
    body=dict(version_id=current['adopted_version_id'],node_id='entry',delegation_id=first['delegation_id'],
        expected_revision=current['revision'],expected_action_version=db.fetchone('SELECT version FROM learning_action WHERE id=?',(first['action_id'],))[0],request_key='missing-anchor')
    blocked=client.post(endpoint,json=body)
    assert blocked.status_code==409 and blocked.json()['detail']['kind']=='path_anchor_unavailable'
    fallback=client.post(endpoint,json={**body,'use_checkpoint':False,'request_key':'explicit-fallback'})
    assert fallback.status_code==200 and 'path_anchor' not in fallback.json()


def test_path_confirm_pause_and_decision_roll_back_together(client,monkeypatch):
    _identity,plan_id,first,second=seed(client)
    value,_=draft(client,plan_id,first,second)
    adopted,_=confirm(client,plan_id,value)
    started=start(client,plan_id,adopted,'entry',first['delegation_id'])
    changed,_=draft(client,plan_id,first,second,current_node_id='practice',request_key='late-failure')
    from app.core import learning_paths
    append=learning_paths._append
    def fail(*args,**kwargs):
        if args[-2]=='path.decision_confirmed':
            raise RuntimeError('synthetic late projection failure')
        return append(*args,**kwargs)
    monkeypatch.setattr(learning_paths,'_append',fail)
    before=snapshot(client.app.state.learning.database,('learning_session','learning_event','learning_command','learning_plan_path_state'))
    with pytest.raises(RuntimeError,match='synthetic late'):
        confirm(client,plan_id,changed,'failed-decision')
    assert snapshot(client.app.state.learning.database,before.keys())==before
    assert client.app.state.learning.database.fetchone('SELECT status FROM learning_session WHERE id=?',(started['session_id'],))[0]=='running'


def transfer_body(view,first):
    return dict(title='PRIVATE-NEW-DIRECTION',destination_title='PRIVATE-NEW-PLAN',destination_description='',
        nodes=[dict(id='new-entry',title='PRIVATE-NEW-STAGE',action_ids=[],outcome_ids=[first['outcome_id']])],
        edges=[],entry_node_id='new-entry',current_node_id='new-entry',reason='PRIVATE-TRANSFER-REASON',pause_original=True,
        expected_revision=view['revision'],expected_organization_revision=view['organization_revision'])


def test_cross_plan_transfer_atomic_no_task_move_no_goal_or_session_fabrication(client):
    identity,plan_id,first,second=seed(client)
    value,_=draft(client,plan_id,first,second)
    adopted,_=confirm(client,plan_id,value)
    session=start(client,plan_id,adopted,'entry',first['delegation_id'])
    before=path(client,plan_id)
    db=client.app.state.learning.database
    preserved=snapshot(db,('learning_outcome','learning_goal','learning_action_link'))
    body=transfer_body(before,first)
    url=f'/api/learning/plans/{plan_id}/path'
    rejected=client.post(url+'/transfer-preview',json={**body,'nodes':[dict(id='new-entry',title='x',action_ids=[first['action_id']],outcome_ids=[])]})
    assert rejected.status_code==422
    previewed=client.post(url+'/transfer-preview',json=body)
    assert previewed.status_code==200,previewed.text
    assert len(previewed.json()['affected_sessions'])==1
    assert len(client.get('/api/learning/state').json()['plans'])==1
    payload={**body,'review_key':previewed.json()['review_key'],'request_key':'transfer-confirm'}
    response=client.post(url+'/transfer',json=payload)
    assert response.status_code==200,response.text
    result=response.json()
    assert result['source_path']['adopted_version_id']==before['adopted_version_id']
    assert result['source_path']['status']=='paused'
    assert result['path']['adopted_version_id'] and result['plan_id']!=plan_id
    assert db.fetchone('SELECT goal_id FROM learning_plan WHERE id=?',(result['plan_id'],))[0] is None
    assert snapshot(db,preserved.keys())==preserved
    assert len(db.fetchall('SELECT * FROM learning_session'))==1
    assert db.fetchone('SELECT status FROM learning_session WHERE id=?',(session['session_id'],))[0]=='interrupted'
    assert client.post(url+'/transfer',json=payload).json()['plan_id']==result['plan_id']
    assert len(client.get('/api/learning/state').json()['plans'])==2
    state=path(client,plan_id)
    blocked=client.post(url+'/start',json=dict(version_id=state['adopted_version_id'],node_id='entry',delegation_id=first['delegation_id'],
        expected_revision=state['revision'],expected_action_version=db.fetchone('SELECT version FROM learning_action WHERE id=?',(first['action_id'],))[0],request_key='paused-start'))
    assert blocked.status_code==409 and blocked.json()['detail']['kind']=='path_paused'
    assert len(result['source_path']['transfers'])==len(result['path']['transfers'])==1
    assert client.app.state.learning.core.replay(client.app.state.learning.principal(identity))['comparison']['matched']
    assert path(client,plan_id)['status']=='paused'
    for row in db.fetchall('SELECT payload_json FROM learning_event'):
        assert 'PRIVATE-NEW-PLAN' not in row[0] and 'PRIVATE-TRANSFER-REASON' not in row[0]


def test_transfer_last_event_failure_rolls_back_new_plan_and_pause(client,monkeypatch):
    _identity,plan_id,first,second=seed(client)
    value,_=draft(client,plan_id,first,second)
    adopted,_=confirm(client,plan_id,value)
    start(client,plan_id,adopted,'entry',first['delegation_id'])
    body=transfer_body(path(client,plan_id),first)
    url=f'/api/learning/plans/{plan_id}/path'
    review=client.post(url+'/transfer-preview',json=body).json()
    from app.core import learning_paths
    append=learning_paths._append
    def fail(*args,**kwargs):
        if args[-2]=='path.transfer_departed':
            raise RuntimeError('synthetic transfer failure')
        return append(*args,**kwargs)
    monkeypatch.setattr(learning_paths,'_append',fail)
    db=client.app.state.learning.database
    before=snapshot(db,('learning_plan','learning_session','learning_event','learning_command','learning_path_version','learning_plan_path_state'))
    with pytest.raises(RuntimeError,match='synthetic transfer failure'):
        client.post(url+'/transfer',json={**body,'review_key':review['review_key'],'request_key':'failed-transfer'})
    assert snapshot(db,before.keys())==before


def test_manual_marker_move_keeps_actual_session_but_does_not_relabel_its_anchor(client):
    _identity,plan_id,first,second=seed(client)
    value,_=draft(client,plan_id,first,second)
    adopted,_=confirm(client,plan_id,value)
    original=start(client,plan_id,adopted,'entry',first['delegation_id'])
    current=path(client,plan_id)
    response=client.post(f'/api/learning/plans/{plan_id}/path/position',json=dict(
        version_id=current['adopted_version_id'],node_id='practice',expected_revision=current['revision'],request_key='marker-only'))
    assert response.status_code==200,response.text
    view=response.json()
    assert view['current_node_id']=='practice' and len(view['versions'])==1
    point=view['versions'][0]['checkpoint']
    assert point['node_id']=='practice' and point['session_id'] is None and point['anchor']=={}
    assert client.app.state.learning.database.fetchone('SELECT status FROM learning_session WHERE id=?',(original['session_id'],))[0]=='running'
