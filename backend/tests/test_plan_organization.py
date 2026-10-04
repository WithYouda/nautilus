"""Synthetic D2 organization journeys, replay and managed private boundaries."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from app.config import Settings
from app.db import Database
from app.core.commands import ConfirmLearningSetup
from app.core.organization_commands import CreateModule
from app.learning_domain import DomainError, Principal
from app.learning_production import (create_learning_backup, restore_learning_backup,
    upgrade_learning_database, ProductionLearningDatabaseError)
from app.learning_service import LearningService
from app.plan_organization import PlanOrganization
from test_evidence_claims import authorize
from test_learning_setup import setup_command
from test_learning_verifications import IDENTITY
from test_managed_purge import absent, snapshot

BASE = '/api/learning/plans'


def plan(client, key='plan', **changes):
    response = client.post(BASE,json={'title':'合成计划','description':'合成说明','goal_id':None,'request_key':key,**changes})
    assert response.status_code==201,response.text
    return response.json()['organization']


def task(client, view, key='task', **changes):
    response = client.post(BASE+'/'+view['plan']['id']+'/tasks',json={
        'action_title':'合成任务','context_key':'synthetic','object_description':'合成对象',
        'behavior':'能独立执行','outcome_context_key':'synthetic','boundaries':'',
        'stop_conditions':'完成后停止','time_budget_minutes':20,
        'expected_revision':view['revision'],'request_key':key,**changes})
    assert response.status_code==201,response.text
    return response.json()


def get(client, plan_id):
    response=client.get(BASE+'/'+plan_id+'/organization')
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='no-store'
    return response.json()


def module(client, view, key='module', parent=None, **changes):
    response=client.post(BASE+'/'+view['plan']['id']+'/modules',json={
        'title':'模块 '+key,'description':'模块说明 '+key,'parent_module_id':parent,
        'expected_revision':view['revision'],'request_key':key,**changes})
    assert response.status_code==201,response.text
    return {**response.json()['organization'],'object_id':response.json()['object_id']}


def rows(db, tables):
    return {name:sorted([tuple(row) for row in db.fetchall(f'SELECT * FROM {name}')],key=repr) for name in tables}


def test_goal_free_plan_tasks_nested_modules_mixed_order_preserve_facts_and_replay(client):
    identity=authorize(client)
    view=plan(client)
    plan_id=view['plan']['id']
    assert view['revision']==1 and view['plan']['goal_id'] is None and not view['tasks']
    first=task(client,view)
    view=get(client,plan_id)
    reused=task(client,view,'reuse-outcome',outcome_id=first['outcome_id'])
    assert reused['outcome_id']==first['outcome_id'] and reused['action_id']!=first['action_id']
    db=client.app.state.learning.database
    assert db.fetchone('SELECT COUNT(*) FROM learning_goal')[0]==0
    assert db.fetchone('SELECT COUNT(*) FROM learning_setup')[0]==0
    fact_tables=('learning_action','learning_delegation','learning_contract_version','learning_outcome','learning_session','learning_artifact')
    before=rows(db,fact_tables)
    view=module(client,get(client,plan_id),'outer')
    outer=view['object_id']
    view=module(client,view,'inner',outer)
    inner=view['object_id']
    moved=client.post(BASE+'/'+plan_id+'/tasks/'+first['action_id']+'/placement',json={
        'module_id':outer,'expected_revision':view['revision'],'request_key':'place'})
    assert moved.status_code==200,moved.text
    view=moved.json()['organization']
    ordered=client.post(BASE+'/'+plan_id+'/children-order',json={
        'parent_module_id':outer,'children':[{'kind':'task','id':first['action_id']},{'kind':'module','id':inner}],
        'expected_revision':view['revision'],'request_key':'sort'})
    assert ordered.status_code==200,ordered.text
    view=ordered.json()['organization']
    assert [(item['kind'],item['id'],item['position']) for item in view['children'] if item['parent_module_id']==outer]==[
        ('task',first['action_id'],0),('module',inner,1)]
    revised=client.post(BASE+'/'+plan_id+'/modules/'+inner+'/revise',json={
        'title':'子模块改名','description':'第二版','parent_module_id':None,
        'expected_revision':view['revision'],'request_key':'revise'})
    assert revised.status_code==200,revised.text
    assert rows(db,fact_tables)==before
    # The goal-free task can use the existing session lifecycle unchanged.
    from app.core.commands import StartSession, EndSession
    principal=client.app.state.learning.principal(identity)
    started=client.app.state.learning.core.execute(principal,StartSession(delegation_id=first['delegation_id'],expected_version=2),'start-goal-free')
    client.app.state.learning.core.execute(principal,EndSession(session_id=started['id'],disposition='interrupted',expected_version=3),'end-goal-free')
    assert db.fetchone('SELECT status FROM learning_session WHERE id=?',(started['id'],))[0]=='interrupted'
    view=get(client,plan_id)
    before_all=rows(db,('learning_plan_organization','learning_plan_child','learning_module','learning_action_link'))
    replay=client.app.state.learning.core.replay(Principal.user(identity['id']))
    assert replay['status']=='succeeded' and replay['comparison']['matched'] is True
    assert get(client,plan_id)==view
    assert rows(db,('learning_plan_organization','learning_plan_child','learning_module','learning_action_link'))==before_all


def test_legacy_setup_baseline_captures_members_and_append_updates_revision_replay(client):
    identity=authorize(client)
    learning=client.app.state.learning
    principal=learning.principal(identity)
    initial=learning.core.execute(principal,setup_command(),'legacy')
    plan_id=initial['plan_id']
    view=get(client,plan_id)
    assert view['revision']==0 and not view['plan']['can_purge_content']
    assert view['children']==[{'kind':'task','id':initial['action_id'],'parent_module_id':None,'position':0}]
    second=learning.core.execute(principal,setup_command(plan_id=plan_id),'legacy-before-org')
    db=learning.database
    # Synthetic pre-existing modules have no invented historical events. The
    # first organization event must capture them and their then-current parents.
    with db.transaction() as connection:
        connection.execute("INSERT INTO learning_module VALUES ('legacy-parent',?,?,NULL,'旧模块','旧说明',4,'active','old','old')", (principal.owner_id,plan_id))
        connection.execute("INSERT INTO learning_module VALUES ('legacy-child',?,?,'legacy-parent','旧子模块','',3,'active','old','old')", (principal.owner_id,plan_id))
        connection.execute("UPDATE learning_action_link SET module_id='legacy-parent' WHERE action_id=?", (second['action_id'],))
    view=get(client,plan_id)
    view=module(client,view,'initialize')
    assert view['revision']==2
    baseline=db.fetchone("SELECT position,payload_json FROM learning_event WHERE event_type='organization.initialized'")
    body=json.loads(baseline['payload_json'])
    assert body['cutoff_position']<baseline['position']
    assert {item['id'] for item in body['modules']}=={'legacy-parent','legacy-child'}
    assert {item['id'] for item in body['tasks']}=={initial['action_id'],second['action_id']}
    assert '旧模块' not in baseline['payload_json']
    third=learning.core.execute(principal,setup_command(plan_id=plan_id),'legacy-after-org')
    after=get(client,plan_id)
    assert after['revision']==3
    last=db.fetchall('SELECT event_type,payload_json FROM learning_event ORDER BY position DESC LIMIT 2')
    assert [item['event_type'] for item in last]==['organization.task_added','plan.step_added']
    assert json.loads(last[1]['payload_json'])['action_link']['module_id'] is None
    count=db.fetchone('SELECT COUNT(*) FROM learning_event')[0]
    assert learning.core.execute(principal,setup_command(plan_id=plan_id),'legacy-after-org')==third
    assert db.fetchone('SELECT COUNT(*) FROM learning_event')[0]==count
    before=rows(db,('learning_module','learning_action_link','learning_plan_child','learning_plan_organization'))
    assert learning.core.replay(principal)['comparison']['matched'] is True
    assert get(client,plan_id)==after
    assert rows(db,('learning_module','learning_action_link','learning_plan_child','learning_plan_organization'))==before


def test_cas_idempotency_owner_cross_plan_cycle_and_full_member_order(client):
    identity=authorize(client)
    view=plan(client)
    plan_id=view['plan']['id']
    request={'title':'一','description':'','parent_module_id':None,'expected_revision':view['revision'],'request_key':'idempotent'}
    first=client.post(BASE+'/'+plan_id+'/modules',json=request)
    assert first.status_code==201,first.text
    assert client.post(BASE+'/'+plan_id+'/modules',json=request).json()==first.json()
    assert client.post(BASE+'/'+plan_id+'/modules',json={**request,'title':'二'}).json()['detail']['kind']=='idempotency_conflict'
    assert client.post(BASE+'/'+plan_id+'/modules',json={**request,'request_key':'stale'}).json()['detail']['kind']=='version_conflict'
    view=first.json()['organization']; outer=first.json()['object_id']
    view=module(client,view,'child',outer); child=view['object_id']
    bad=client.post(BASE+'/'+plan_id+'/modules/'+outer+'/revise',json={'title':'一','description':'',
        'parent_module_id':child,'expected_revision':view['revision'],'request_key':'cycle'})
    assert bad.status_code==422 and bad.json()['detail']['kind']=='organization_module_cycle'
    bad=client.post(BASE+'/'+plan_id+'/children-order',json={'parent_module_id':None,'children':[],
        'expected_revision':view['revision'],'request_key':'missing-child'})
    assert bad.status_code==409 and bad.json()['detail']['kind']=='organization_members_changed'
    other=plan(client,'other')
    bad=client.post(BASE+'/'+other['plan']['id']+'/modules',json={'title':'x','description':'','parent_module_id':outer,
        'expected_revision':other['revision'],'request_key':'cross-plan'})
    assert bad.status_code==404
    learning=client.app.state.learning
    linked=task(client,view,'scope-task')
    view=get(client,plan_id)
    bad=client.post(BASE+'/'+other['plan']['id']+'/tasks/'+linked['action_id']+'/placement',json={
        'module_id':None,'expected_revision':other['revision'],'request_key':'cross-plan-task'})
    assert bad.status_code==404
    # A second valid owner still cannot access the first owner's plan.
    with learning.database.transaction() as connection:
        connection.execute("INSERT INTO local_identity (id,device_id,display_name,created_at,updated_at) VALUES ('other-owner','synthetic-other','Other','now','now')")
    command=CreateModule(plan_id=plan_id,title='agent',expected_revision=view['revision'])
    with pytest.raises(DomainError,match='permission_denied'):
        learning.core.execute(Principal.agent(identity['id'],'agent',action_ids=frozenset(),tools=frozenset()),command,'agent')
    with pytest.raises(DomainError,match='not_found'):
        learning.core.execute(Principal.user('other-owner'),command,'owner')
    assert get(client,plan_id)['revision']==view['revision']


def test_org_projection_failure_rolls_back_fact_private_and_request(client,monkeypatch):
    authorize(client)
    view=plan(client)
    db=client.app.state.learning.database
    tables=('learning_event','learning_command','learning_plan_private','learning_action','learning_delegation','learning_outcome')
    before=rows(db,tables)
    import app.core.plan_organization as organization
    apply=organization.apply_organization_event
    def fail(connection,event,payload):
        apply(connection,event,payload)
        if event['event_type']=='organization.task_added':
            raise DomainError('synthetic_failure')
    monkeypatch.setattr(organization,'apply_organization_event',fail)
    response=client.post(BASE+'/'+view['plan']['id']+'/tasks',json={'action_title':'fail',
        'context_key':'synthetic','object_description':'x','behavior':'x','outcome_context_key':'synthetic',
        'boundaries':'','stop_conditions':'stop','expected_revision':view['revision'],'request_key':'fail'})
    assert response.status_code==409
    assert rows(db,tables)==before
    assert get(client,view['plan']['id'])['revision']==view['revision']


def test_plan_and_module_private_all_revisions_online_backup_restore_replay(client,tmp_path):
    identity=authorize(client)
    learning=client.app.state.learning
    db=learning.database
    legacy=learning.core.execute(learning.principal(identity),setup_command(),'legacy-keep')
    legacy_text=db.fetchone('SELECT title,description FROM learning_plan WHERE id=?', (legacy['plan_id'],))
    view=plan(client,title='D2_PLAN_PRIVATE_1',description='D2_PLAN_DESCRIPTION_1')
    plan_id=view['plan']['id']
    saved=task(client,view)
    view=module(client,get(client,plan_id),'private',title='D2_MODULE_PRIVATE_1',description='D2_MODULE_DESCRIPTION_1')
    module_id=view['object_id']
    response=client.post(BASE+'/'+plan_id+'/modules/'+module_id+'/revise',json={
        'title':'D2_MODULE_PRIVATE_2','description':'D2_MODULE_DESCRIPTION_2','parent_module_id':None,
        'expected_revision':view['revision'],'request_key':'private-revise'})
    assert response.status_code==200,response.text
    view=response.json()['organization']
    unmanaged=snapshot(db,tmp_path/'unmanaged.sqlite3')
    backup,_,_=create_learning_backup(db.database_path,tmp_path/'registered',label='synthetic')
    before_facts=rows(db,('learning_action','learning_outcome','learning_delegation','learning_contract_version','learning_action_link'))
    result=client.post(BASE+'/'+plan_id+'/modules/'+module_id+'/content/purge',json={
        'confirmation':'PURGE','expected_revision':view['revision'],'request_key':'purge-module'})
    assert result.status_code==200,result.text
    assert result.json()['purge_report']['status']=='complete',result.json()
    view=result.json()['organization']
    assert not view['modules'][0]['content_available'] and view['modules'][0]['can_purge_content']
    result=client.post(BASE+'/'+plan_id+'/organization-content/purge',json={
        'confirmation':'PURGE','expected_revision':view['revision'],'request_key':'purge-plan'})
    assert result.status_code==200,result.text
    assert result.json()['purge_report']['status']=='complete',result.json()
    assert not result.json()['organization']['plan']['content_available']
    for path in (db.database_path,backup):
        absent(path,'D2_PLAN_PRIVATE_1','D2_PLAN_DESCRIPTION_1','D2_MODULE_PRIVATE_1','D2_MODULE_PRIVATE_2',
               'D2_MODULE_DESCRIPTION_1','D2_MODULE_DESCRIPTION_2')
    assert rows(db,('learning_action','learning_outcome','learning_delegation','learning_contract_version','learning_action_link'))==before_facts
    assert tuple(db.fetchone('SELECT title,description FROM learning_plan WHERE id=?',(legacy['plan_id'],)))==tuple(legacy_text)
    view=get(client,plan_id)
    assert learning.core.replay(Principal.user(identity['id']))['comparison']['matched'] is True
    assert get(client,plan_id)==view
    with pytest.raises(ProductionLearningDatabaseError,match='purged|deletion'):
        restore_learning_backup(unmanaged,db.database_path)
    # A pre-object backup with no private body must still retain the tombstones.
    empty=tmp_path/'pre-object.sqlite3'
    Database(empty,Settings.from_env().migrations_dir,migration_floor=11,migration_ceiling=42).close()
    with pytest.raises(ProductionLearningDatabaseError,match='deletion'):
        restore_learning_backup(empty,db.database_path)
    assert get(client,legacy['plan_id'])['plan']['can_purge_content'] is False
    denied=client.post(BASE+'/'+legacy['plan_id']+'/organization-content/purge',json={
        'confirmation':'PURGE','expected_revision':0,'request_key':'legacy-purge'})
    assert denied.status_code==404


def test_042_to_047_formal_upgrade_preserves_old_rows_columns(tmp_path):
    path=tmp_path/'old.sqlite3'
    db=Database(path,Settings.from_env().migrations_dir,migration_floor=11,migration_ceiling=42)
    learning=LearningService(db)
    principal=learning.principal(IDENTITY)
    learning.core.execute(principal,setup_command(),'old')
    tables=[row[0] for row in db.fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'schema_migrations'")]
    before=rows(db,tables)
    columns={table:[tuple(row) for row in db.fetchall('PRAGMA table_info('+table+')')] for table in tables}
    db.close()
    result=upgrade_learning_database(path,tmp_path/'backups',authorized=True)
    assert result['preflight']['applied_migrations'][-1]=='042_outcome_graph'
    assert result['post_upgrade_backup']['applied_migrations'][-1]=='047_learning_task_removal'
    assert result['post_upgrade_backup']['integrity_check']=='ok'
    with closing(sqlite3.connect(path)) as connection:
        for table in tables:
            assert sorted([tuple(row) for row in connection.execute('SELECT * FROM '+table)],key=repr)==before[table]
            assert [tuple(row) for row in connection.execute('PRAGMA table_info('+table+')')]==columns[table]
        new={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'schema_migrations'")}-set(tables)
        assert new=={'learning_plan_organization','learning_plan_child','learning_plan_private','learning_plan_private_tombstone',
            'learning_plan_path_state','learning_path_draft','learning_path_private','learning_path_private_tombstone',
            'learning_path_version','learning_path_decision','learning_path_checkpoint',
            'learning_plan_commitment_state','learning_commitment_draft','learning_commitment_version','learning_commitment_item',
            'learning_commitment_execution','learning_commitment_availability','learning_commitment_run','learning_commitment_private',
            'learning_commitment_private_tombstone','learning_commitment_source','learning_session_feedback','learning_session_feedback_history',
            'learning_action_removal'}


def test_goal_constraints_binding_and_new_plan_legacy_header_do_not_copy_private(client,tmp_path):
    identity=authorize(client)
    learning=client.app.state.learning
    principal=learning.principal(identity)
    initial=learning.core.execute(principal,setup_command(),'goal')
    goal_id=initial['goal_id']
    # A new plan may explicitly link to an existing open goal.
    view=plan(client,'goal-plan',goal_id=goal_id,title='NEW_D2_GOAL_PLAN_PRIVATE',description='NEW_D2_GOAL_PLAN_BODY')
    plan_id=view['plan']['id']
    old=learning.core.execute(principal,setup_command(plan_id=plan_id),'old-append-new-plan')
    view=get(client,plan_id)
    assert view['revision']==2 and old['action_id'] in {item['id'] for item in view['tasks']}
    event=learning.database.fetchone("SELECT payload_json FROM learning_event WHERE command_id=(SELECT id FROM learning_command WHERE idempotency_key='old-append-new-plan') AND event_type='plan.step_added'")
    header=json.loads(event['payload_json'])['plan']
    assert header=={'id':plan_id,'title':'计划','description':''}
    for row in learning.database.fetchall('SELECT payload_json FROM learning_event'):
        assert 'NEW_D2_GOAL_PLAN_PRIVATE' not in row[0] and 'NEW_D2_GOAL_PLAN_BODY' not in row[0]
    for row in learning.database.fetchall('SELECT result_json FROM learning_command'):
        assert 'NEW_D2_GOAL_PLAN_PRIVATE' not in row[0] and 'NEW_D2_GOAL_PLAN_BODY' not in row[0]
    # A non-verifiable composite cannot be bound even through this new command.
    from app.core.commands import CreateOutcome, ChangeGoalStatus
    composite=learning.core.execute(principal,CreateOutcome(kind='composite',object_description='综合',behavior='整体',context_key='synthetic'),'composite')
    rejected=client.post(BASE+'/'+plan_id+'/tasks',json={'action_title':'x','context_key':'synthetic',
        'object_description':'x','behavior':'x','outcome_context_key':'synthetic','outcome_id':composite['id'],
        'boundaries':'','stop_conditions':'stop','expected_revision':view['revision'],'request_key':'composite-bind'})
    assert rejected.status_code==422 and rejected.json()['detail']['kind']=='composite_not_verifiable'
    from app.goal_lifecycle import goal_review
    with learning.database.transaction() as connection:
        review=goal_review(connection,principal.owner_id,goal_id)
    learning.core.execute(principal,ChangeGoalStatus(goal_id=goal_id,status='paused',expected_version=review['goal']['version'],review_key=review['review_key']),'pause-goal')
    rejected=client.post(BASE+'/'+plan_id+'/modules',json={'title':'closed','parent_module_id':None,
        'expected_revision':view['revision'],'request_key':'closed-module'})
    assert rejected.status_code==409 and rejected.json()['detail']['kind']=='goal_not_active'
    rejected=client.post(BASE,json={'title':'closed','goal_id':goal_id,'request_key':'closed-plan'})
    assert rejected.status_code==409 and rejected.json()['detail']['kind']=='goal_not_active'
    # Content erasure is still available when its associated goal is closed.
    backup,_,_=create_learning_backup(learning.database.database_path,tmp_path/'managed',label='synthetic')
    result=client.post(BASE+'/'+plan_id+'/organization-content/purge',json={'confirmation':'PURGE',
        'expected_revision':view['revision'],'request_key':'purge-closed'})
    assert result.status_code==200 and result.json()['purge_report']['status']=='complete',result.text
    for path in (learning.database.database_path,backup):
        absent(path,'NEW_D2_GOAL_PLAN_PRIVATE','NEW_D2_GOAL_PLAN_BODY')
    assert learning.core.replay(principal)['comparison']['matched'] is True


def test_managed_purge_partial_retry_receipt_and_module_remains_movable(client,tmp_path,monkeypatch):
    identity=authorize(client)
    learning=client.app.state.learning
    view=plan(client)
    plan_id=view['plan']['id']
    view=module(client,view,'purge-target',title='RETRY_ORG_PRIVATE')
    module_id=view['object_id']
    view=module(client,view,'parent')
    parent=view['object_id']
    backup,_,_=create_learning_backup(learning.database.database_path,tmp_path/'managed',label='retry')
    import app.managed_purge as purge
    scrub=purge.scrub_snapshot
    def unavailable(*args):
        raise OSError('synthetic inaccessible snapshot')
    monkeypatch.setattr(purge,'scrub_snapshot',unavailable)
    request={'confirmation':'PURGE','expected_revision':view['revision'],'request_key':'retry-purge'}
    response=client.post(BASE+'/'+plan_id+'/modules/'+module_id+'/content/purge',json=request)
    assert response.status_code==200 and response.json()['purge_report']['status']=='partial'
    assert client.get(BASE+'/'+plan_id+'/modules/'+module_id+'/content/purge-status').json()['status']=='partial'
    with pytest.raises(ProductionLearningDatabaseError,match='incomplete'):
        create_learning_backup(learning.database.database_path,tmp_path/'more',label='not-yet')
    monkeypatch.setattr(purge,'scrub_snapshot',scrub)
    response=client.post(BASE+'/'+plan_id+'/modules/'+module_id+'/content/purge',json=request)
    assert response.status_code==200 and response.json()['purge_report']['status']=='complete'
    absent(backup,'RETRY_ORG_PRIVATE')
    view=response.json()['organization']
    response=client.post(BASE+'/'+plan_id+'/modules/'+module_id+'/revise',json={'title':'内容已清除','description':'',
        'parent_module_id':parent,'expected_revision':view['revision'],'request_key':'move-cleared'})
    assert response.status_code==200,response.text
    assert next(item for item in response.json()['organization']['modules'] if item['id']==module_id)['parent_module_id']==parent
    assert learning.core.replay(Principal.user(identity['id']))['comparison']['matched'] is True
