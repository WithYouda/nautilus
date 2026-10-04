"""Administrative task removal retains facts and hides only current membership."""
import sqlite3
from contextlib import closing

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.core.commands import CreateDelegation, EndSession, SaveTextArtifact, StartSession
from app.core.learning import PROJECTION_TABLES
from app.core.organization_commands import (CreateModule, CreatePlan, CreatePlanTask,
    OrderChildren, PlaceTask, RemovePlanTask)
from app.db import Database
from app.learning_domain import DomainError, Principal
from app.learning_production import upgrade_learning_database
from app.learning_service import LearningService
from app.plan_organization import PlanOrganization
from test_evidence_claims import authorize
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_setup import setup_command
from test_learning_verifications import IDENTITY


def rows(db, tables):
    return {table:sorted([tuple(row) for row in db.fetchall('SELECT * FROM '+table)],key=repr)
            for table in tables}


def seed(db, identity=IDENTITY):
    learning = LearningService(db)
    principal = learning.principal(identity)
    plan = learning.core.execute(principal,CreatePlan(title='合成计划'),'plan-'+identity['id'])
    return learning,principal,plan['plan_id']


def task(learning, principal, plan_id, key='task', **changes):
    view = PlanOrganization(learning).organization({'id':principal.owner_id},plan_id)
    payload = dict(plan_id=plan_id,expected_revision=view['revision'],action_title='合成原任务 '+key,
        context_key='synthetic',object_description='合成对象',behavior='能执行',
        outcome_context_key='synthetic',stop_conditions='完成后停止')
    payload.update(changes)
    return learning.core.execute(principal,CreatePlanTask(**payload),key)


def removal(learning, principal, plan_id, action_id, **changes):
    payload = dict(plan_id=plan_id,action_id=action_id,
        expected_revision=PlanOrganization(learning).organization({'id':principal.owner_id},plan_id)['revision'],
        expected_action_version=learning.database.fetchone('SELECT version FROM learning_action WHERE id=?',(action_id,))[0])
    payload.update(changes)
    return RemovePlanTask(**payload)


def execute(learning, principal, command, key='remove'):
    return learning.core.execute(principal,command,key)


@pytest.mark.parametrize('completed',[False,True])
def test_removal_preserves_execution_completion_evidence_originals_and_replay(client, completed):
    identity = authorize(client)
    db = client.app.state.learning.database
    learning,principal,plan_id = seed(db,identity)
    standard = learning.overview(identity)['standards'][0]
    created = task(learning,principal,plan_id,context_key=standard['context_key'],
                   outcome_id=standard['outcome_id'],criterion_id=standard['id'])
    action_id,delegation_id = created['action_id'],created['delegation_id']
    others = []
    if not completed:
        others.append(execute(learning,principal,CreateDelegation(action_id=action_id,
            outcome_id=standard['outcome_id'],criterion_id=standard['id'],boundaries='',
            stop_conditions='另一轮',expected_version=2),'other')['id'])
    version = db.fetchone('SELECT version FROM learning_action WHERE id=?',(action_id,))[0]
    started = execute(learning,principal,StartSession(delegation_id=delegation_id,expected_version=version),'start')
    artifact = execute(learning,principal,SaveTextArtifact(session_id=started['id'],
        content='regex: ^Nautilus\\d+$\nsample: Nautilus42',expected_version=started['version']),'artifact')
    client.app.state.evidence.semantic_analyzer = lambda _request: []
    analyzed = client.post('/api/learning/artifacts/'+artifact['id']+'/analysis',json={'request_key':'analysis'})
    assert analyzed.status_code==200,analyzed.text
    assert analyzed.json()['claims']
    completion = client.post('/api/learning/delegations/'+delegation_id+'/completion',json={
        'request_key':'completed-original','verification_kind':'unverified','note':'合成完成原文'})
    assert completion.status_code==200,completion.text
    if not completed:
        version = db.fetchone('SELECT version FROM learning_action WHERE id=?',(action_id,))[0]
        active = execute(learning,principal,StartSession(delegation_id=others[0],expected_version=version),'other-start')
        execute(learning,principal,EndSession(session_id=active['id'],disposition='interrupted',
            expected_version=active['version']),'other-end')
        for suffix in ('ready','paused'):
            version = db.fetchone('SELECT version FROM learning_action WHERE id=?',(action_id,))[0]
            new = execute(learning,principal,CreateDelegation(action_id=action_id,outcome_id=standard['outcome_id'],
                criterion_id=standard['id'],boundaries='',stop_conditions='合成委托 '+suffix,
                expected_version=version),'other-'+suffix)
            others.append(new['id'])
        # Paused is an existing valid lifecycle state; administrative removal
        # must treat it identically to ready/active without adding a new fact.
        with db.transaction() as connection:
            connection.execute("UPDATE learning_delegation SET status='paused' WHERE id=?",(others[-1],))
    preserved = ('learning_session','learning_raw_artifact','learning_artifact','learning_completion',
        'learning_completion_review','learning_evidence_claim','learning_analysis_run','learning_outcome',
        'learning_action_link','learning_setup','learning_contract_version','learning_criterion_version')
    before = rows(db,preserved)
    action = dict(db.fetchone('SELECT * FROM learning_action WHERE id=?',(action_id,)))
    delegations = [dict(row) for row in db.fetchall('SELECT * FROM learning_delegation WHERE action_id=?',(action_id,))]
    command = removal(learning,principal,plan_id,action_id)
    result = execute(learning,principal,command)
    assert set(result)=={'plan_id','object_id','revision'} and result['object_id']==action_id
    assert result['revision']==command.expected_revision+1
    assert rows(db,preserved)==before
    after = dict(db.fetchone('SELECT * FROM learning_action WHERE id=?',(action_id,)))
    assert after=={**action,'version':action['version']+1,'status':'completed' if completed else 'cancelled'}
    marker = dict(db.fetchone('SELECT * FROM learning_action_removal WHERE action_id=?',(action_id,)))
    assert marker['previous_status']==action['status'] and marker['plan_id']==plan_id
    for delegation in delegations:
        actual = dict(db.fetchone('SELECT * FROM learning_delegation WHERE id=?',(delegation['id'],)))
        assert actual==(delegation if delegation['status']=='completed' else
                       {**delegation,'status':'cancelled','version':delegation['version']+1})
    view = PlanOrganization(learning).organization(identity,plan_id)
    assert not view['tasks'] and not view['children']
    state = learning.overview(identity)
    retained = next(item for item in state['actions'] if item['id']==action_id)
    assert retained['deleted'] is True and retained['title']==action['title']
    assert any(item['action_id']==action_id for item in state['action_links'])
    assert next(item for item in state['sessions'] if item['id']==started['id'])['action_title']==action['title']
    original_completion = client.get('/api/learning/delegations/'+delegation_id+'/completion')
    assert original_completion.status_code==200 and original_completion.json()==completion.json()
    emitted = db.fetchall("SELECT event_type,payload_json FROM learning_event WHERE event_type IN ('action.removed','organization.task_removed') ORDER BY position")
    assert [row['event_type'] for row in emitted]==['action.removed','organization.task_removed']
    assert all(action['title'] not in row['payload_json'] and '合成完成原文' not in row['payload_json'] for row in emitted)
    events = db.fetchone('SELECT COUNT(*) FROM learning_event')[0]
    assert execute(learning,principal,command)==result
    assert db.fetchone('SELECT COUNT(*) FROM learning_event')[0]==events
    with pytest.raises(DomainError,match='idempotency_conflict'):
        execute(learning,principal,command.model_copy(update={'expected_action_version':after['version']}))
    with pytest.raises(DomainError,match='task_removed'):
        execute(learning,principal,removal(learning,principal,plan_id,action_id),'remove-again')
    assert learning.core.replay(principal)['comparison']['matched'] is True
    assert rows(db,preserved)==before and PlanOrganization(learning).organization(identity,plan_id)==view
    assert dict(db.fetchone('SELECT * FROM learning_action_removal WHERE action_id=?',(action_id,)))==marker
    assert client.get('/api/learning/delegations/'+delegation_id+'/completion').json()==completion.json()


@pytest.mark.parametrize('kind,code',[
    ('organization','version_conflict'),('action','version_conflict'),('other_plan','not_found'),
    ('other_owner','not_found'),('agent','permission_denied'),('running','task_session_running')])
def test_rejected_removal_has_no_partial_writes(learning_database, kind, code):
    learning,principal,plan_id = seed(learning_database)
    created = task(learning,principal,plan_id)
    command = removal(learning,principal,plan_id,created['action_id'])
    actor = principal
    if kind=='organization':
        command = command.model_copy(update={'expected_revision':command.expected_revision-1})
    elif kind=='action':
        command = command.model_copy(update={'expected_action_version':command.expected_action_version-1})
    elif kind=='other_plan':
        second = execute(learning,principal,CreatePlan(title='别的计划'),'other-plan')
        command = command.model_copy(update={'plan_id':second['plan_id'],'expected_revision':second['revision']})
    elif kind=='other_owner':
        actor = Principal.user('owner-b')
    elif kind=='agent':
        actor = Principal.agent(principal.owner_id,'worker',action_ids=frozenset([created['action_id']]),tools=frozenset())
    else:
        execute(learning,principal,StartSession(delegation_id=created['delegation_id'],expected_version=2),'start')
        command = removal(learning,principal,plan_id,created['action_id'])
    before = rows(learning_database,(*PROJECTION_TABLES,'learning_event','learning_command'))
    with pytest.raises(DomainError,match=code):
        execute(learning,actor,command)
    assert rows(learning_database,before)==before


def test_removal_normalizes_only_affected_siblings_and_later_organization_writes(learning_database):
    learning,principal,plan_id = seed(learning_database)
    first = task(learning,principal,plan_id,'first')
    second = task(learning,principal,plan_id,'second')
    third = task(learning,principal,plan_id,'third')
    view = PlanOrganization(learning).organization(IDENTITY,plan_id)
    module = execute(learning,principal,CreateModule(plan_id=plan_id,expected_revision=view['revision'],title='模块'),'module')
    execute(learning,principal,PlaceTask(plan_id=plan_id,action_id=second['action_id'],module_id=module['object_id'],
        expected_revision=module['revision']),'place')
    execute(learning,principal,removal(learning,principal,plan_id,first['action_id']))
    view = PlanOrganization(learning).organization(IDENTITY,plan_id)
    assert [(item['id'],item['position']) for item in view['children'] if item['parent_module_id'] is None]==[
        (third['action_id'],0),(module['object_id'],1)]
    assert [(item['id'],item['position']) for item in view['children'] if item['parent_module_id']==module['object_id']]==[(second['action_id'],0)]
    with pytest.raises(DomainError,match='task_removed'):
        execute(learning,principal,PlaceTask(plan_id=plan_id,action_id=first['action_id'],
            module_id=None,expected_revision=view['revision']),'revive-placement')
    fourth = task(learning,principal,plan_id,'fourth')
    view = PlanOrganization(learning).organization(IDENTITY,plan_id)
    ordered = execute(learning,principal,OrderChildren(plan_id=plan_id,expected_revision=view['revision'],children=[
        dict(kind='module',id=module['object_id']),dict(kind='task',id=fourth['action_id']),dict(kind='task',id=third['action_id'])]),'order')
    assert ordered['revision']==view['revision']+1
    assert learning.core.replay(principal)['comparison']['matched'] is True


def test_caller_transaction_rolls_back_prior_session_end_and_removal(learning_database):
    learning,principal,plan_id = seed(learning_database)
    created = task(learning,principal,plan_id)
    started = execute(learning,principal,StartSession(delegation_id=created['delegation_id'],expected_version=2),'start')
    command = removal(learning,principal,plan_id,created['action_id'])
    before = rows(learning_database,(*PROJECTION_TABLES,'learning_event','learning_command','learning_audit'))
    with pytest.raises(DomainError,match='version_conflict'):
        with learning_database.transaction(immediate=True) as connection:
            learning.core.execute_in_transaction(connection,principal,
                EndSession(session_id=started['id'],disposition='interrupted',expected_version=started['version']),'end-for-removal')
            # A stale outer preflight cannot commit the session interruption.
            learning.core.execute_in_transaction(connection,principal,command,'remove')
    assert rows(learning_database,before)==before
    with pytest.raises(DomainError,match='outer_decision_rejected'):
        with learning_database.transaction(immediate=True) as connection:
            learning.core.execute_in_transaction(connection,principal,
                EndSession(session_id=started['id'],disposition='interrupted',expected_version=started['version']),'end-for-removal')
            learning.core.execute_in_transaction(connection,principal,
                command.model_copy(update={'expected_action_version':command.expected_action_version+1}),'remove')
            # A later route-decision failure must roll back both removal events.
            raise DomainError('outer_decision_rejected')
    assert rows(learning_database,before)==before
    with learning_database.transaction(immediate=True) as connection:
        learning.core.execute_in_transaction(connection,principal,
            EndSession(session_id=started['id'],disposition='interrupted',expected_version=started['version']),'end-for-removal')
        result = learning.core.execute_in_transaction(connection,principal,
            command.model_copy(update={'expected_action_version':command.expected_action_version+1}),'remove')
    assert result['object_id']==created['action_id']
    assert learning_database.fetchone('SELECT status FROM learning_session WHERE id=?',(started['id'],))[0]=='interrupted'
    assert learning.core.replay(principal)['comparison']['matched'] is True


def test_legacy_setup_baseline_removal_is_replayable(learning_database):
    learning = LearningService(learning_database)
    principal = learning.principal(IDENTITY)
    created = execute(learning,principal,setup_command(),'legacy')
    command = removal(learning,principal,created['plan_id'],created['action_id'])
    assert command.expected_revision==0
    result = execute(learning,principal,command)
    assert result['revision']==2
    assert learning.core.replay(principal)['comparison']['matched'] is True
    assert learning_database.fetchone('SELECT COUNT(*) FROM learning_setup')[0]==1


def test_046_read_and_real_upgrade_preserve_old_tables_rows_and_columns(tmp_path):
    path = tmp_path/'old.sqlite3'
    db = Database(path,Settings.from_env().migrations_dir,migration_floor=11,migration_ceiling=46)
    learning,principal,plan_id = seed(db)
    created = task(learning,principal,plan_id)
    view = PlanOrganization(learning).organization(IDENTITY,plan_id)
    assert next(a for a in learning.overview(IDENTITY)['actions'] if a['id']==created['action_id'])['deleted'] is False
    tables = [row[0] for row in db.fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'schema_migrations'")]
    before = rows(db,tables)
    columns = {table:[tuple(row) for row in db.fetchall('PRAGMA table_info('+table+')')] for table in tables}
    db.close()
    upgraded = upgrade_learning_database(path,tmp_path/'backups',authorized=True)
    assert upgraded['preflight']['applied_migrations'][-1]=='046_learning_signal_feedback'
    assert upgraded['post_upgrade_backup']['applied_migrations'][-1]=='047_learning_task_removal'
    assert upgraded['post_upgrade_backup']['integrity_check']=='ok'
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        for table in tables:
            assert sorted([tuple(row) for row in connection.execute('SELECT * FROM '+table)],key=repr)==before[table]
            assert [tuple(row) for row in connection.execute('PRAGMA table_info('+table+')')]==columns[table]
        new = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'schema_migrations'")}-set(tables)
        assert new=={'learning_action_removal'}
    upgraded_db = Database(path,Settings.from_env().migrations_dir,migration_floor=11,migration_ceiling=None,migrate=False)
    try:
        assert PlanOrganization(LearningService(upgraded_db)).organization(IDENTITY,plan_id)==view
    finally:
        upgraded_db.close()


def test_removal_command_rejects_extra_fields_and_invalid_versions():
    base = dict(plan_id='plan',action_id='task',expected_revision=0,expected_action_version=1)
    for changes in ({'purge':True},{'expected_revision':-1},{'expected_action_version':0}):
        with pytest.raises(ValidationError):
            RemovePlanTask(**(base|changes))
