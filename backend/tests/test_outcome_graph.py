"""D1 API journeys, identity preservation, and managed private-content boundaries."""
import asyncio
import json
import sqlite3
import time
from contextlib import closing

import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.commands import CreateOutcome
from app.core.graph_commands import FinishGraphRun
from app.learning_domain import Principal, DomainError
from app.learning_production import create_learning_backup, restore_learning_backup, ProductionLearningDatabaseError
from app.purge_storage import register_backup, storage_lock
from conftest import build_settings
from test_evidence_claims import authorize, create_standard_chain
from test_managed_purge import absent, snapshot

BASE='/api/learning/outcome-graph'


def node(client,key,kind='atomic',context='synthetic'):
    result=client.post(BASE+'/outcomes',json={'request_key':key,'kind':kind,'object_description':key,
        'behavior':'能独立解释并实践','context_key':context})
    assert result.status_code==201,result.text
    return result.json()['id']


def fields(left,right,kind='contains',context='synthetic',**kwargs):
    return {'source_outcome_id':left,'target_outcome_id':right,'relation_type':kind,'context_key':context,
            'rationale':'合成关系说明','uncertainty':'尚需独立核验','source_refs':[],**kwargs}


def relation(client,key,left,right,kind='contains',**kwargs):
    result=client.post(BASE+'/relations',json={'request_key':key,**fields(left,right,kind,**kwargs)})
    assert result.status_code==201,result.text
    return result.json()


def wait_run(client,run_id):
    for _ in range(200):
        value=client.get(BASE+'/suggestions/'+run_id).json()
        if value['status']!='running':
            return value
        time.sleep(.01)
    raise AssertionError('mock run did not finish')


def test_manual_full_journey_history_cas_identity_and_replay(client):
    identity=authorize(client)
    chain=create_standard_chain(client)
    db=client.app.state.learning.database
    before={table:[tuple(r) for r in db.fetchall(f'SELECT * FROM {table}')] for table in
            ('learning_criterion_version','learning_raw_artifact','learning_artifact')}
    parent=node(client,'overall','composite')
    child=node(client,'child')
    same_name=node(client,'child-copy')
    # Distinct IDs remain distinct even when declarations are exactly the same.
    duplicate=client.post(BASE+'/outcomes',json={'request_key':'duplicate-name','object_description':'child',
        'behavior':'能独立解释并实践','context_key':'synthetic'}).json()['id']
    assert duplicate!=child
    first=relation(client,'contains',parent,chain['standard']['outcome_id'])
    relation(client,'contains-child',parent,child)
    symmetric=relation(client,'equivalent',child,same_name,'equivalent')
    relation(client,'overlap',child,duplicate,'overlap')
    relation(client,'pre',same_name,duplicate,'prerequisite')
    assert symmetric['aggregate_version']==1
    view=client.get(BASE).json()
    assert len(view['relations'])==5
    assert next(n for n in view['nodes'] if n['id']==parent)['coverage']['status']=='unknown'
    assert next(n for n in view['nodes'] if n['id']==child)['coverage']['status']=='no_standard'
    assert client.get('/api/learning/outcomes/'+chain['standard']['outcome_id']+'/review').status_code==200
    revision=client.post(BASE+'/relations/'+first['id']+'/revise',json={
        'request_key':'revise','expected_revision':1,**fields(parent,chain['standard']['outcome_id'],rationale='第二版说明')})
    assert revision.status_code==200,revision.text
    assert revision.json()['aggregate_version']==2
    stale=client.post(BASE+'/relations/'+first['id']+'/revoke',json={'request_key':'stale','expected_revision':1})
    assert stale.status_code==409 and stale.json()['detail']['kind']=='version_conflict'
    revoke={'request_key':'revoke','expected_revision':2}
    removed=client.post(BASE+'/relations/'+first['id']+'/revoke',json=revoke)
    assert removed.status_code==200
    assert client.post(BASE+'/relations/'+first['id']+'/revoke',json=revoke).json()==removed.json()
    history=client.get(BASE+'/relations/'+first['id']).json()['history']
    assert [r['revision'] for r in history]==[1,2,3]
    assert [r['status'] for r in history]==['active','active','revoked']
    assert history[0]['rationale']=='合成关系说明' and history[1]['rationale']=='第二版说明'
    for table,rows in before.items():
        assert [tuple(r) for r in db.fetchall(f'SELECT * FROM {table}')]==rows
    original=client.get(BASE).json()
    replay=client.app.state.learning.replay(identity)
    assert replay['comparison']['matched'],replay
    assert client.get(BASE).json()==original
    assert client.get(BASE).headers['cache-control']=='no-store'


@pytest.mark.parametrize('kind',['contains','prerequisite','equivalent','overlap'])
def test_relation_constraints_owner_and_idempotency(client,kind):
    identity=authorize(client)
    left=node(client,'left','composite')
    right=node(client,'right','composite')
    value=relation(client,'one',left,right,kind)
    assert client.post(BASE+'/relations',json={'request_key':'one',**fields(left,right,kind)}).json()==value
    changed=client.post(BASE+'/relations',json={'request_key':'one',**fields(left,right,kind,rationale='changed')})
    assert changed.status_code==409 and changed.json()['detail']['kind']=='idempotency_conflict'
    repeat=client.post(BASE+'/relations',json={'request_key':'duplicate',**fields(right,left,kind)})
    assert repeat.status_code==409
    assert repeat.json()['detail']['kind']==('graph_relation_cycle' if kind in {'contains','prerequisite'} else 'graph_duplicate_relation')
    self_ref=client.post(BASE+'/relations',json={'request_key':'self',**fields(left,left,kind)})
    assert self_ref.status_code==422
    other={**identity,'id':'foreign-owner','device_id':'foreign-device'}
    foreign=client.app.state.learning.create_outcome(other,{'object_description':'private','behavior':'private','context_key':'foreign'},'foreign')
    denied=client.post(BASE+'/relations',json={'request_key':'foreign',**fields(left,foreign['id'],kind)})
    assert denied.status_code==404
    with pytest.raises(DomainError,match='not_found'):
        client.app.state.outcome_graph.relation(other,value['id'])
    assert client.get(BASE+'?plan_id=foreign').status_code==404


def test_contains_cross_scope_cycles_conflicts_and_composite_binding(client):
    authorize(client)
    parent=node(client,'parent','composite')
    middle=node(client,'middle','composite')
    child=node(client,'last')
    relation(client,'a',parent,middle,context='one')
    bad=client.post(BASE+'/relations',json={'request_key':'b',**fields(middle,parent,context='two')})
    assert bad.status_code==409 and bad.json()['detail']['kind']=='graph_relation_cycle'
    assert client.post(BASE+'/relations',json={'request_key':'atomic-contains',**fields(child,parent)}).status_code==422
    conflict=client.post(BASE+'/relations',json={'request_key':'conflict',**fields(middle,parent,'equivalent',context='one')})
    assert conflict.status_code==409 and conflict.json()['detail']['kind']=='graph_relation_conflict'
    action=client.post('/api/learning/actions',json={'title':'test','context_key':'synthetic','idempotency_key':'act'}).json()
    bind=client.post('/api/learning/delegations',json={'action_id':action['id'],'outcome_id':parent,'criterion_id':None,
        'boundaries':'test','stop_conditions':'test','expected_version':1,'idempotency_key':'bind'})
    assert bind.status_code==422


def test_real_coverage_versions_claim_identity_and_source_disappearance(client,tmp_path):
    identity=authorize(client)
    chain=create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer=None
    run=client.post('/api/learning/artifacts/'+chain['artifact']['id']+'/analysis',json={'request_key':'analysis'}).json()
    claim=run['claims'][0]
    client.post('/api/learning/evidence-claims/'+claim['id']+'/review',json={'action':'adopt','request_key':'adopt'})
    db=client.app.state.learning.database
    with db.transaction() as connection:
        connection.execute('''INSERT INTO learning_criterion_version SELECT id||':v2',owner_id,package_id,outcome_id,
            2,source,context_key,recipe_json,review_status,reviewed_by,reviewed_at,created_at FROM learning_criterion_version WHERE id=?''',(chain['standard']['id'],))
    parent=node(client,'coverage','composite')
    record=relation(client,'source',parent,chain['standard']['outcome_id'],rationale='SOURCE_PRIVATE_SENTINEL',
        source_refs=[{'kind':'artifact','id':chain['artifact']['id'],'version':1}])
    graph=client.get(BASE).json()
    outcome=next(n for n in graph['nodes'] if n['id']==chain['standard']['outcome_id'])
    assert [s['version'] for s in outcome['coverage']['standards']]==[1,2]
    assert outcome['coverage']['status']=='mixed'
    assert outcome['evidence_links'][0]['claim_id']==claim['id']
    assert outcome['evidence_links'][0]['artifact_id']==chain['artifact']['id']
    assert outcome['evidence_links'][0]['fact_event_id']==claim['fact_event_id']
    backup,_,_=create_learning_backup(db.database_path,tmp_path/'backups',label='graph')
    unmanaged=snapshot(db,tmp_path/'unmanaged.sqlite3')
    hide=client.post('/api/learning/artifacts/'+chain['artifact']['id']+'/soft-delete',json={'expected_version':4,'idempotency_key':'hide'})
    assert hide.status_code==200,hide.text
    hidden=client.get(BASE+'/relations/'+record['id']).json()
    assert hidden['available'] is False and hidden['rationale'] is None
    assert not hidden['source_refs'][0]['available']
    assert client.app.state.learning.replay(identity)['comparison']['matched']
    purge=client.post('/api/learning/artifacts/'+chain['artifact']['id']+'/purge',json={'expected_version':5,'idempotency_key':'purge','confirmation':'PURGE'})
    assert purge.status_code==200,purge.text
    assert purge.json()['purge']['status']=='complete'
    assert all(r['rationale'] is None for r in client.get(BASE+'/relations/'+record['id']).json()['history'])
    absent(db.database_path,'SOURCE_PRIVATE_SENTINEL')
    absent(backup,'SOURCE_PRIVATE_SENTINEL')
    with pytest.raises(ProductionLearningDatabaseError,match='purged|deletion'):
        restore_learning_backup(unmanaged,db.database_path)
    assert client.app.state.learning.replay(identity)['comparison']['matched']


def test_relation_private_history_managed_purge_and_restore_barrier(client,tmp_path):
    identity=authorize(client)
    parent=node(client,'purge-parent','composite')
    child=node(client,'purge-child')
    record=relation(client,'private',parent,child,rationale='GRAPH_PRIVATE_V1',context='GRAPH_PRIVATE_SCOPE')
    client.post(BASE+'/relations/'+record['id']+'/revise',json={'request_key':'private2','expected_revision':1,
        **fields(parent,child,rationale='GRAPH_PRIVATE_V2',context='GRAPH_PRIVATE_SCOPE')})
    db=client.app.state.learning.database
    backup,_,_=create_learning_backup(db.database_path,tmp_path/'backups',label='graph')
    unmanaged=snapshot(db,tmp_path/'unmanaged.sqlite3')
    value=client.post(BASE+'/relations/'+record['id']+'/purge',json={'request_key':'erase','expected_revision':2,'confirmation':'PURGE'})
    assert value.status_code==200,value.text
    assert value.json()['purge_report']['status']=='complete'
    assert client.get(BASE+'/relations/'+record['id']+'/purge-status').json()['status']=='complete'
    assert all(r['rationale'] is None for r in client.get(BASE+'/relations/'+record['id']).json()['history'])
    for path in (db.database_path,backup):
        absent(path,'GRAPH_PRIVATE_V1','GRAPH_PRIVATE_V2','GRAPH_PRIVATE_SCOPE')
    with pytest.raises(ProductionLearningDatabaseError,match='purged|deletion'):
        restore_learning_backup(unmanaged,db.database_path)
    assert client.app.state.learning.replay(identity)['comparison']['matched']


def ai_client(tmp_path,calls,mode='success',delay=None):
    async def handler(request):
        payload=json.loads(request.content)
        calls.append(payload)
        inputs=json.loads(payload['messages'][-1]['content'])['selected_outcomes']
        if delay:
            await delay.wait()
        if mode=='error':
            return httpx.Response(500,json={'error':{'message':'synthetic failure'}})
        candidates=[fields(inputs[0]['id'],item['id'],'contains',rationale='AI_PRIVATE_SENTINEL',
            source_refs=[{'kind':'outcome','id':inputs[0]['id'],'version':1},{'kind':'outcome','id':item['id'],'version':1}]) for item in inputs[1:]]
        if mode=='invalid':
            candidates[0]['target_outcome_id']='outside-selection'
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'candidates':candidates})}}]})
    return TestClient(create_app(build_settings(tmp_path),provider_transport=httpx.MockTransport(handler)))


def configure(client):
    response=client.put('/api/ai/provider',json={'display_name':'synthetic graph','base_url':'https://synthetic.example.com/v1',
        'model':'mock-graph','api_key':'sk-synthetic-graph-key','request_timeout_seconds':11})
    assert response.status_code==200,response.text


def test_ai_scope_freeze_per_item_edit_reject_idempotency_and_no_evidence_mutation(tmp_path):
    calls=[]
    with ai_client(tmp_path,calls) as client:
        identity=authorize(client)
        configure(client)
        chosen=[node(client,'AI_INPUT_PRIVATE','composite'),*[node(client,'selected-'+str(i)) for i in range(3)]]
        node(client,'UNSELECTED_PRIVATE')
        start={'request_key':'suggest','outcome_ids':chosen}
        response=client.post(BASE+'/suggestions',json=start)
        assert response.status_code==201,response.text
        run=wait_run(client,response.json()['id'])
        assert run['status']=='succeeded',run
        assert client.get(BASE).json()['relations']==[]
        assert len(run['candidates'])==3 and len(calls)==1
        assert 'UNSELECTED_PRIVATE' not in json.dumps(calls)
        assert 'AI_INPUT_PRIVATE' in json.dumps(calls)
        assert 'sk-synthetic' not in json.dumps(run)
        assert client.post(BASE+'/suggestions',json=start).json()==run
        assert len(calls)==1
        candidate=run['candidates'][0]
        review={'request_key':'accept','expected_revision':1,'decision':'accept'}
        accepted=client.post(BASE+f"/suggestions/{run['id']}/candidates/{candidate['id']}/review",json=review)
        assert accepted.status_code==200,accepted.text
        assert client.post(BASE+f"/suggestions/{run['id']}/candidates/{candidate['id']}/review",json=review).json()==accepted.json()
        second=run['candidates'][1]
        edited=client.post(BASE+f"/suggestions/{run['id']}/candidates/{second['id']}/review",json={
            'request_key':'edit','expected_revision':1,'decision':'accept','relation':fields(chosen[0],chosen[2],'overlap',rationale='USER_EDIT_PRIVATE')})
        assert edited.status_code==200,edited.text
        last=run['candidates'][2]
        reject=client.post(BASE+f"/suggestions/{run['id']}/candidates/{last['id']}/review",json={
            'request_key':'reject','expected_revision':1,'decision':'reject'})
        assert reject.status_code==200,reject.text
        assert len(client.get(BASE).json()['relations'])==2
        assert client.app.state.learning.database.fetchone('SELECT COUNT(*) FROM learning_evidence_claim')[0]==0
        assert client.app.state.learning.replay(identity)['comparison']['matched']
        assert client.get(BASE+'/suggestions/'+run['id']).json()['candidates'][0]['status']=='accepted'
        backup,_,_=create_learning_backup(client.app.state.learning.database.database_path,tmp_path/'backups',label='ai')
        purged=client.post(BASE+'/suggestions/'+run['id']+'/purge',json={'request_key':'purge-ai','expected_revision':2,'confirmation':'PURGE'})
        assert purged.status_code==200,purged.text
        assert purged.json()['purge_report']['status']=='complete'
        assert all(not r['available'] for r in client.get(BASE).json()['relations'])
        for path in (client.app.state.learning.database.database_path,backup):
            # Input outcome declaration remains its own original identity. Derived rationale is erased everywhere.
            absent(path,'AI_PRIVATE_SENTINEL','USER_EDIT_PRIVATE')
        assert client.app.state.learning.replay(identity)['comparison']['matched']


@pytest.mark.parametrize('mode',['error','invalid'])
def test_ai_failure_does_not_publish_candidates_or_formal_relations(tmp_path,mode):
    calls=[]
    with ai_client(tmp_path,calls,mode) as client:
        authorize(client);configure(client)
        ids=[node(client,'parent','composite'),node(client,'child')]
        run=client.post(BASE+'/suggestions',json={'request_key':'failed','outcome_ids':ids}).json()
        result=wait_run(client,run['id'])
        assert result['status']=='failed' and result['candidates']==[]
        assert client.get(BASE).json()['relations']==[]
        assert len(calls)==1


def test_cancel_and_late_response_are_durable_and_cross_owner_hidden(tmp_path):
    calls=[]
    delay=asyncio.Event()
    with ai_client(tmp_path,calls,delay=delay) as client:
        identity=authorize(client);configure(client)
        ids=[node(client,'parent','composite'),node(client,'child')]
        run=client.post(BASE+'/suggestions',json={'request_key':'slow','outcome_ids':ids}).json()
        response=client.post(BASE+'/suggestions/'+run['id']+'/cancel',json={'request_key':'cancel','expected_revision':1})
        assert response.status_code==200,response.text
        assert response.json()['status']=='canceled'
        assert client.get(BASE+'/suggestions/'+run['id']).json()['candidates']==[]
        with pytest.raises(DomainError,match='version_conflict|graph_run_inactive'):
            client.app.state.learning.core.execute(Principal.user(identity['id']),FinishGraphRun(run_id=run['id'],
                expected_revision=1,status='succeeded',candidates=[]),'late')
        assert client.get(BASE).json()['relations']==[]
        other={**identity,'id':'other','device_id':'other'}
        with pytest.raises(DomainError,match='not_found'):
            client.app.state.outcome_graph.run(other,run['id'])
        assert client.app.state.learning.replay(identity)['comparison']['matched']


def test_restart_marks_running_proposal_interrupted_without_new_model_calls(tmp_path):
    calls=[]
    with ai_client(tmp_path,calls,delay=asyncio.Event()) as client:
        identity=authorize(client);configure(client)
        ids=[node(client,'restart-parent','composite'),node(client,'restart-child')]
        current=client.post(BASE+'/suggestions',json={'request_key':'restart-run','outcome_ids':ids}).json()
        client.app.state.outcome_graph.recover()  # Same recovery invoked on app startup/shutdown.
        interrupted=client.get(BASE+'/suggestions/'+current['id']).json()
        assert interrupted['status']=='failed' and interrupted['reason']=='interrupted'
        assert interrupted['revision']==2 and interrupted['candidates']==[]
        assert client.app.state.learning.replay(identity)['comparison']['matched']
    with TestClient(create_app(build_settings(tmp_path,initialize_databases=False))) as reopened:
        authorize(reopened)
        assert reopened.get(BASE+'/suggestions/'+current['id']).json()==interrupted
        assert reopened.get(BASE).json()['relations']==[]
        with pytest.raises(DomainError,match='version_conflict'):
            reopened.app.state.learning.core.execute(Principal.user(identity['id']),FinishGraphRun(run_id=current['id'],
                expected_revision=1,status='succeeded',candidates=[]),'restart-late')
    assert len(calls)<=1


def test_changed_selected_input_fails_run_and_purge_blocks_late_publish(tmp_path):
    calls=[]
    with ai_client(tmp_path,calls,delay=asyncio.Event()) as client:
        identity=authorize(client);configure(client)
        ids=[node(client,'freeze-parent','composite'),node(client,'freeze-child')]
        current=client.post(BASE+'/suggestions',json={'request_key':'freeze','outcome_ids':ids}).json()
        db=client.app.state.learning.database
        with db.transaction() as connection:
            # Simulates a future authorized declaration revision arriving during the call.
            connection.execute('UPDATE learning_outcome SET behavior=? WHERE owner_id=? AND id=?',('changed',identity['id'],ids[1]))
        with pytest.raises(DomainError,match='graph_input_changed'):
            client.app.state.learning.core.execute(Principal.user(identity['id']),FinishGraphRun(run_id=current['id'],
                expected_revision=1,status='succeeded',candidates=[]),'input-late')
        failed=client.app.state.learning.core.execute(Principal.user(identity['id']),FinishGraphRun(run_id=current['id'],
            expected_revision=1,status='failed',reason='generation_failed'), 'input-failed')
        assert failed['aggregate_version']==2
        assert client.get(BASE+'/suggestions/'+current['id']).json()['status']=='failed'
        # Source simulation is restored before replay; frozen history itself stays unchanged.
        with db.transaction() as connection:
            connection.execute('UPDATE learning_outcome SET behavior=? WHERE owner_id=? AND id=?',('能独立解释并实践',identity['id'],ids[1]))
        purged=client.post(BASE+'/suggestions/'+current['id']+'/purge',json={'request_key':'purge-frozen',
            'expected_revision':2,'confirmation':'PURGE'})
        assert purged.status_code==200,purged.text
        assert purged.json()['status']=='purged'
        with pytest.raises(DomainError,match='version_conflict'):
            client.app.state.learning.core.execute(Principal.user(identity['id']),FinishGraphRun(run_id=current['id'],
                expected_revision=1,status='succeeded',candidates=[]),'purged-late')
        assert client.get(BASE).json()['relations']==[]
        assert client.app.state.learning.replay(identity)['comparison']['matched']


def test_graph_projection_failure_rolls_back_event_private_payload_and_idempotency(client,monkeypatch):
    authorize(client)
    parent=node(client,'atomic-parent','composite')
    child=node(client,'atomic-child')
    db=client.app.state.learning.database
    before=db.fetchone('SELECT COUNT(*) FROM learning_event')[0]
    import app.core.outcome_graph as graph_core
    apply=graph_core.apply_graph_event
    def interrupted(connection,event,payload):
        apply(connection,event,payload)
        raise sqlite3.OperationalError('synthetic projection interruption')
    monkeypatch.setattr(graph_core,'apply_graph_event',interrupted)
    payload={'request_key':'atomic-save',**fields(parent,child,rationale='ROLLBACK_PRIVATE')}
    response=client.post(BASE+'/relations',json=payload)
    assert response.status_code==503
    assert db.fetchone('SELECT COUNT(*) FROM learning_event')[0]==before
    assert db.fetchone('SELECT COUNT(*) FROM learning_outcome_relation')[0]==0
    assert db.fetchone('SELECT COUNT(*) FROM learning_graph_private')[0]==0
    assert db.fetchone("SELECT 1 FROM learning_command WHERE idempotency_key='atomic-save'") is None
    monkeypatch.setattr(graph_core,'apply_graph_event',apply)
    assert client.post(BASE+'/relations',json=payload).status_code==201


def test_ai_accept_rechecks_changed_input_and_must_not_approve_standards(tmp_path):
    calls=[]
    with ai_client(tmp_path,calls) as client:
        identity=authorize(client);configure(client)
        ids=[node(client,'accept-parent','composite'),node(client,'accept-child')]
        run=wait_run(client,client.post(BASE+'/suggestions',json={'request_key':'accept-freeze','outcome_ids':ids}).json()['id'])
        db=client.app.state.learning.database
        before=[tuple(row) for row in db.fetchall('SELECT * FROM learning_criterion_version')]
        with db.transaction() as connection:
            connection.execute('UPDATE learning_outcome SET behavior=? WHERE owner_id=? AND id=?',('changed',identity['id'],ids[1]))
        review={'request_key':'accept-changed','expected_revision':1,'decision':'accept'}
        rejected=client.post(BASE+f"/suggestions/{run['id']}/candidates/{run['candidates'][0]['id']}/review",json=review)
        assert rejected.status_code==409 and rejected.json()['detail']['kind']=='graph_input_changed'
        assert client.get(BASE).json()['relations']==[]
        assert [tuple(row) for row in db.fetchall('SELECT * FROM learning_criterion_version')]==before
        assert client.get(BASE+'/suggestions/'+run['id']).json()['candidates'][0]['status']=='pending'


def test_repeat_after_adopt_skips_redundant_and_preserves_new_candidates(tmp_path):
    calls=[]
    with ai_client(tmp_path,calls) as client:
        authorize(client);configure(client)
        parent=node(client,'repeat-parent','composite')
        first=node(client,'repeat-first')
        extra=node(client,'repeat-extra')
        run=wait_run(client,client.post(BASE+'/suggestions',json={'request_key':'repeat-original','outcome_ids':[parent,first]}).json()['id'])
        adopted=client.post(BASE+f"/suggestions/{run['id']}/candidates/{run['candidates'][0]['id']}/review",json={
            'request_key':'repeat-adopt','expected_revision':1,'decision':'accept'})
        assert adopted.status_code==200,adopted.text
        before=client.get(BASE).json()['relations']
        repeat=wait_run(client,client.post(BASE+'/suggestions',json={'request_key':'repeat-all-linked','outcome_ids':[parent,first]}).json()['id'])
        assert repeat['status']=='succeeded' and repeat['candidates']==[]
        assert client.get(BASE).json()['relations']==before
        mixed=wait_run(client,client.post(BASE+'/suggestions',json={'request_key':'repeat-mixed','outcome_ids':[parent,first,extra]}).json()['id'])
        assert mixed['status']=='succeeded' and len(mixed['candidates'])==1
        assert mixed['candidates'][0]['target_outcome_id']==extra
        assert client.get(BASE).json()['relations']==before
        assert len(calls)==3  # Exactly one call for each of the three explicit requests.
