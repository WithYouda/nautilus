"""D2 commitments and feedback: owner commands, private originals and replay."""
from datetime import datetime,timedelta,timezone
import hashlib
import json
from uuid import uuid4
from ..learning_domain import DomainError
from ..commitment_calibration import calibrate,route_context,known_origin,source_available,signal_summary,RULE_VERSION
from .events import append_event,canonical,digest
from .learning_paths import owned,plan_state,writable_plan
from .path_commands import StartPathTask
from .commands import EndSession
from .commitment_commands import (SaveCommitmentDraft,ConfirmCommitments,StartCommitmentItem,
    ChangeCommitmentItem,SaveAvailability,StartCommitmentRun,FinishCommitmentRun,
    CancelCommitmentRun,PurgeCommitmentRun,PurgeCommitmentDraft,RecordSessionFeedback,PurgeSessionFeedback)

EVENT_TYPES=frozenset({'commitment.draft_saved','commitment.confirmed','commitment.item_started',
    'commitment.item_changed','commitment.route_changed','commitment.availability_saved','commitment.content_purged',
    'commitment.run_started','commitment.run_finished','commitment.run_canceled','commitment.run_purged',
    'feedback.recorded','feedback.purged'})
PROJECTION_TABLES=('learning_session_feedback_history','learning_session_feedback','learning_commitment_execution',
    'learning_commitment_item','learning_commitment_version','learning_commitment_draft',
    'learning_commitment_availability','learning_commitment_run','learning_plan_commitment_state')


def state(connection,owner,plan_id):
    owned(connection,owner,'learning_plan',plan_id)
    row=connection.execute('SELECT * FROM learning_plan_commitment_state WHERE owner_id=? AND plan_id=?',(owner,plan_id)).fetchone()
    return dict(row) if row else dict(owner_id=owner,plan_id=plan_id,revision=0,current_version_id=None,availability_revision=0)


def _append(connection,principal,command_id,key,now,aggregate,identifier,expected,event_type,payload):
    return append_event(connection,principal,command_id=command_id,key=key,now=now,aggregate_type=aggregate,
        aggregate_id=identifier,expected_version=expected,event_type=event_type,payload=payload)


def _plan_event(connection,principal,command_id,key,now,plan_id,event_type,payload):
    return _append(connection,principal,command_id,key,now,'commitment',plan_id,
        state(connection,principal.owner_id,plan_id)['revision'],event_type,{'plan_id':plan_id,**payload})


def original(connection,owner,kind,identifier,value,*,check_sources=True):
    row=connection.execute('SELECT * FROM learning_commitment_private WHERE owner_id=? AND kind=? AND object_id=? AND revision=?',
                           (owner,kind,identifier,value)).fetchone()
    if row is None:
        raise DomainError('commitment_source_missing')
    if row['purged_at'] or connection.execute('SELECT 1 FROM learning_commitment_private_tombstone WHERE owner_id=? AND kind=? AND object_id=?',
                                             (owner,kind,identifier)).fetchone():
        return None
    if hashlib.sha256(row['content_json'].encode()).hexdigest()!=row['content_hash']:
        raise DomainError('event_integrity_failed')
    body=json.loads(row['content_json'])
    if check_sources and any(not source_available(connection,owner,ref) for ref in body.get('source_refs',[])):
        return None
    return body


def _private(connection,event,payload):
    private=payload.get('private')
    if not private:
        return
    kind,identifier,value=private['kind'],private['id'],private['revision']
    if value!=event['aggregate_version']:
        raise DomainError('event_scope_invalid')
    existing=connection.execute('SELECT event_id FROM learning_commitment_private WHERE owner_id=? AND kind=? AND object_id=? AND revision=?',
                               (event['owner_id'],kind,identifier,value)).fetchone()
    if existing:
        if existing['event_id']!=event['event_id']:
            raise DomainError('event_scope_invalid')
        body=original(connection,event['owner_id'],kind,identifier,value,check_sources=False)
        if body is not None and digest(body)!=payload['content_hash']:
            raise DomainError('event_integrity_failed')
        return
    content=event.get('_private_content')
    if content is None or hashlib.sha256(content.encode()).hexdigest()!=payload['content_hash']:
        raise DomainError('event_integrity_failed')
    body=json.loads(content)
    connection.execute('INSERT INTO learning_commitment_private VALUES (?,?,?,?,?,?,?,NULL)',
        (event['owner_id'],kind,identifier,value,event['event_id'],content,payload['content_hash']))
    for ref in body.get('source_refs',[]):
        connection.execute('INSERT OR IGNORE INTO learning_commitment_source VALUES (?,?,?,?,?,?,?)',
            (event['owner_id'],kind,identifier,value,ref['kind'],ref['id'],ref.get('revision',1)))


def _body(kind,identifier,value,body):
    return {'private':{'kind':kind,'id':identifier,'revision':value},'content':canonical(body)}


def _public_items(items):
    return [{key:value for key,value in item.items() if key!='reason'} for item in items]


def _refs(items,route_id,extra=()):
    result=[{'kind':'path_version','id':route_id,'revision':1},*extra]
    for item in items:
        for ref in item.get('source_refs',[]):
            if ref not in result:result.append(ref)
    return result


def item_status(connection,owner,item):
    action=owned(connection,owner,'learning_action',item['action_id'])
    delegation=owned(connection,owner,'learning_delegation',item['delegation_id'])
    return 'completed' if action['status']=='completed' or delegation['status']=='completed' else item['status']


def validate_items(connection,owner,plan_id,route_version_id,items,*,source='manual',calibration=None):
    path=plan_state(connection,owner,plan_id)
    if path['status']=='paused':raise DomainError('path_paused')
    if path['adopted_version_id']!=route_version_id:
        raise DomainError('commitment_route_changed')
    version=owned(connection,owner,'learning_path_version',route_version_id)
    if version['purged_at'] or not source_available(connection,owner,{'kind':'path_version','id':route_version_id,'revision':1}):
        raise DomainError('commitment_source_unavailable')
    nodes={node['id']:node for node in json.loads(version['data_json'])['nodes']}
    identifiers=[]
    for item in items:
        if item['id'] in identifiers:
            raise DomainError('commitment_duplicate_item',422)
        identifiers.append(item['id'])
        node=nodes.get(item['node_id'])
        if not node or item['action_id'] not in node['action_ids']:
            raise DomainError('commitment_reference_scope',422)
        link=connection.execute('SELECT plan_id FROM learning_action_link WHERE owner_id=? AND action_id=?',(owner,item['action_id'])).fetchone()
        delegation=owned(connection,owner,'learning_delegation',item['delegation_id'])
        if not link or link['plan_id']!=plan_id or delegation['action_id']!=item['action_id']:
            raise DomainError('commitment_reference_scope',422)
        existing=connection.execute('SELECT * FROM learning_commitment_item WHERE owner_id=? AND id=?',(owner,item['id'])).fetchone()
        if existing:
            if existing['plan_id']!=plan_id or (existing['action_id'],existing['delegation_id'])!=(item['action_id'],item['delegation_id']):
                raise DomainError('commitment_item_identity_changed')
            execution=connection.execute('SELECT 1 FROM learning_commitment_execution WHERE owner_id=? AND item_id=?',(owner,item['id'])).fetchone()
            if execution:
                original_item=dict(connection.execute('SELECT estimate_min_minutes,estimate_max_minutes FROM learning_commitment_execution WHERE owner_id=? AND item_id=? ORDER BY linked_at,session_id LIMIT 1',(owner,item['id'])).fetchone())
                if any(item.get(key)!=original_item.get(key) for key in ('estimate_min_minutes','estimate_max_minutes')):
                    raise DomainError('commitment_executed_item_changed')
                if (item['due_at'],item['timezone'])!=(existing['future_due_at'],existing['future_timezone']):
                    raise DomainError('commitment_item_preview_required')
        elif owned(connection,owner,'learning_action',item['action_id'])['status']!='open' or delegation['status'] not in {'ready','active'}:
            raise DomainError('delegation_not_startable')
        for ref in item.get('source_refs',[]):
            if not source_available(connection,owner,ref):
                raise DomainError('commitment_source_unavailable')
    if source=='ai':
        if len(items)>calibration['max_sessions']:
            raise DomainError('commitment_calibration_scope',422)
        if any(item['due_at'] for item in items):
            if calibration['range']!='dated':
                raise DomainError('commitment_calendar_not_supported',422)
            validate_capacity(connection,owner,plan_id,items,calibration['horizon_days'])
        effort=next(axis for axis in calibration['axes'] if axis['name']=='effort')
        if effort['state']!='covered' and any(item['estimate_min_minutes'] is not None and item['estimate_min_minutes']==item['estimate_max_minutes'] for item in items):
            raise DomainError('commitment_effective_effort_unknown',422)


def validate_capacity(connection,owner,plan_id,items,horizon):
    row=connection.execute('SELECT data_json FROM learning_commitment_availability WHERE owner_id=? AND plan_id=?',(owner,plan_id)).fetchone()
    if not row:
        raise DomainError('commitment_availability_required')
    settings=json.loads(row['data_json']);now=datetime.now(timezone.utc);totals={}
    occupied=[]
    for item in items:
        if not item['due_at']:continue
        if item['estimate_max_minutes'] is None:
            raise DomainError('commitment_effective_effort_unknown',422)
        start=datetime.fromisoformat(item['due_at']);end=start+timedelta(minutes=item['estimate_max_minutes'])
        if not now<=start<=now+timedelta(days=horizon) or item['estimate_max_minutes']>settings['block_max_minutes']:
            raise DomainError('commitment_capacity_exceeded',422)
        if not any(datetime.fromisoformat(slot['start_at'])<=start and end<=datetime.fromisoformat(slot['end_at']) for slot in settings['slots']):
            raise DomainError('commitment_capacity_exceeded',422)
        if any(start<other_end and other_start<end for other_start,other_end in occupied):
            raise DomainError('commitment_capacity_exceeded',422)
        occupied.append((start,end))
        week=(start-now).days//7
        totals[week]=totals.get(week,0)+item['estimate_max_minutes']
    if any(total>settings['weekly_budget_minutes'] for total in totals.values()):
        raise DomainError('commitment_capacity_exceeded',422)


def input_context(connection,owner,plan_id):
    plan=writable_plan(connection,owner,plan_id)
    actual_path=plan_state(connection,owner,plan_id)
    if actual_path['status']=='paused':raise DomainError('path_paused')
    path,tasks,intent=route_context(connection,owner,plan_id)
    calibration=calibrate(connection,owner,plan_id)
    current=state(connection,owner,plan_id)
    refs=list(calibration['sources'])
    if path:refs.append({'kind':'path_version','id':path['id'],'revision':1})
    for task in tasks:
        refs.extend([{'kind':'action','id':task['id'],'revision':task['version']},
                     {'kind':'outcome','id':task['outcome_id'],'revision':1}])
    private=connection.execute("SELECT MAX(revision) FROM learning_plan_private WHERE owner_id=? AND kind='plan' AND object_id=? AND purged_at IS NULL",(owner,plan_id)).fetchone()[0]
    if private:refs.append({'kind':'plan_content','id':plan_id,'revision':private})
    blocks=[]
    for ref in calibration['sources']:
        if ref['kind']=='feedback':
            row=owned(connection,owner,'learning_session_feedback',ref['id'])
            data=json.loads(row['data_json'])
            blocks.append({'id':row['id'],'revision':row['revision'],**{key:data[key] for key in
                ('purpose','origin_basis','actual_min_minutes','actual_max_minutes','grain','pace','method_feedback','progress','activity','source_refs')}})
    settings=connection.execute('SELECT revision,data_json FROM learning_commitment_availability WHERE owner_id=? AND plan_id=?',(owner,plan_id)).fetchone()
    if len(tasks)>100:raise DomainError('commitment_input_scope_too_large',422)
    promises=[]
    if current['current_version_id']:
        confirmed=owned(connection,owner,'learning_commitment_version',current['current_version_id'])
        for item in json.loads(confirmed['data_json']):
            placement=owned(connection,owner,'learning_commitment_item',item['id'])
            promises.append({**item,'route_version_id':placement['route_version_id'],'node_id':placement['node_id'],
                'due_at':placement['future_due_at'],'timezone':placement['future_timezone'],'status':item_status(connection,owner,placement),
                'executed':bool(connection.execute('SELECT 1 FROM learning_commitment_execution WHERE owner_id=? AND item_id=?',(owner,item['id'])).fetchone())})
    route=None
    if path:
        from .learning_paths import version_fields
        _,fields=version_fields(connection,owner,path['id'])
        route={'version_id':path['id'],'route_id':path['route_id'],'nodes':fields['nodes'],'edges':fields['edges'],
            'title':fields['title'],'entry_node_id':fields['entry_node_id'],'current_node_id':actual_path['current_node_id'],'revision':actual_path['revision']}
    goal=owned(connection,owner,'learning_goal',plan['goal_id']) if plan['goal_id'] else None
    goal_state={key:goal[key] for key in ('id','version','status')} if goal else None
    inputs=dict(plan_id=plan_id,plan_title=plan['title'],plan_status=plan['status'],goal_state=goal_state,route=route,route_version_id=path['id'] if path else None,
        direction_fingerprint=digest({'route':path['id'] if path else None,'structure':route,'intent':intent}),
        commitment_revision=current['revision'],current_items=promises,tasks=tasks,feedback=blocks,calibration=calibration,
        availability=json.loads(settings['data_json']) if settings else None,source_refs=refs,
        source_summaries=[signal_summary(connection,owner,ref) for ref in refs if ref['kind'] in {'feedback','artifact','submission','delayed_attempt'}])
    inputs['input_hash']=digest(inputs)
    return inputs


def review(connection,owner,plan_id,draft_id):
    plan=writable_plan(connection,owner,plan_id)
    goal=owned(connection,owner,'learning_goal',plan['goal_id']) if plan['goal_id'] else None
    current=state(connection,owner,plan_id)
    draft=owned(connection,owner,'learning_commitment_draft',draft_id)
    if draft['plan_id']!=plan_id or draft['status']!='draft' or draft['purged_at']:
        raise DomainError('commitment_draft_inactive')
    body=original(connection,owner,'draft',draft_id,draft['revision'])
    if body is None:
        raise DomainError('commitment_source_unavailable')
    items=json.loads(draft['data_json'])
    calibration=calibrate(connection,owner,plan_id)
    if draft['source']=='ai':
        run=owned(connection,owner,'learning_commitment_run',draft['run_id'])
        frozen=original(connection,owner,'run',run['id'],1)
        if run['status']!='succeeded' or frozen is None:
            raise DomainError('commitment_source_unavailable')
        latest=input_context(connection,owner,plan_id)
        # The suggestion's own draft save advances commitment revision once.
        latest['commitment_revision']=run['base_revision'];latest.pop('input_hash')
        latest['input_hash']=digest(latest)
        if latest['input_hash']!=run['input_hash']:
            raise DomainError('commitment_input_changed')
    validate_items(connection,owner,plan_id,draft['route_version_id'],items,source=draft['source'],calibration=calibration)
    if draft['base_version_id']!=current['current_version_id']:
        raise DomainError('commitment_input_changed')
    previous=owned(connection,owner,'learning_commitment_version',current['current_version_id']) if current['current_version_id'] else None
    old=json.loads(previous['data_json']) if previous else []
    new_by={item['id']:item for item in items};changes=[]
    for item in old:
        row=owned(connection,owner,'learning_commitment_item',item['id'])
        executed=bool(connection.execute('SELECT 1 FROM learning_commitment_execution WHERE owner_id=? AND item_id=?',(owner,item['id'])).fetchone())
        if item['id'] in new_by:
            changed=any(item.get(key)!=new_by[item['id']].get(key) for key in ('estimate_min_minutes','estimate_max_minutes','due_at','timezone'))
            changes.append({'kind':'replace' if changed else 'keep','item_id':item['id'],'executed':executed})
        elif executed or item_status(connection,owner,row)=='completed' or row['status']=='skipped':
            changes.append({'kind':'keep','item_id':item['id'],'executed':executed,
                'reason_code':'skipped_preserved' if row['status']=='skipped' else 'execution_preserved'})
        else:
            changes.append({'kind':'defer','item_id':item['id'],'executed':False})
    changes.extend({'kind':'replace','item_id':item['id'],'executed':False,'reason_code':'new_promise'} for item in items if item['id'] not in {old_item['id'] for old_item in old})
    fingerprint={'plan_id':plan_id,'goal_state':{key:goal[key] for key in ('id','version','status')} if goal else None,'revision':current['revision'],'draft_id':draft_id,'draft_revision':draft['revision'],
        'data':items,'changes':changes,'calibration_hash':calibration['input_hash'],'route_version_id':draft['route_version_id'],
        'item_states':[(item['id'],owned(connection,owner,'learning_commitment_item',item['id'])['status']) for item in old]}
    return dict(review_key=digest(fingerprint),revision=current['revision'],draft_revision=draft['revision'],changes=changes,
        calibration=calibration,unknowns=calibration['unknowns'],draft=dict(draft),items=items,old_items=old)


def item_review(connection,owner,plan_id,item_id,operation,due_at=None,zone=None):
    writable_plan(connection,owner,plan_id)
    item=owned(connection,owner,'learning_commitment_item',item_id)
    if item['plan_id']!=plan_id:raise DomainError('not_found',404)
    if item_status(connection,owner,item)=='completed':raise DomainError('commitment_item_completed')
    sessions=[dict(row) for row in connection.execute('''SELECT s.id,s.version,a.id AS action_id,a.version AS action_version
        FROM learning_commitment_execution x JOIN learning_session s ON s.owner_id=x.owner_id AND s.id=x.session_id
        JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
        JOIN learning_action a ON a.owner_id=d.owner_id AND a.id=d.action_id
        WHERE x.owner_id=? AND x.item_id=? AND s.status='running' ORDER BY s.id''',(owner,item_id))]
    current=state(connection,owner,plan_id)
    fingerprint=dict(plan_id=plan_id,item_id=item_id,revision=current['revision'],status=item['status'],operation=operation,
        due_at=due_at,timezone=zone,sessions=sessions,action_version=owned(connection,owner,'learning_action',item['action_id'])['version'])
    return dict(review_key=digest(fingerprint),revision=current['revision'],operation=operation,item_id=item_id,
        affected_sessions=sessions,due_at=due_at,timezone=zone)


def _draft(connection,principal,command_id,key,now,plan_id,route_id,items,reason,*,source='manual',run_id=None,draft_id=None,input_hash=None):
    owner=principal.owner_id;current=state(connection,owner,plan_id);value=current['revision']+1
    draft_id=draft_id or str(uuid4())
    extra=[{'kind':'run','id':run_id,'revision':1}] if run_id else []
    body={'reason':reason,'item_reasons':{item['id']:item.get('reason','') for item in items},'source_refs':_refs(items,route_id,extra)}
    _plan_event(connection,principal,command_id,key,now,plan_id,'commitment.draft_saved',dict(id=draft_id,
        route_version_id=route_id,base_version_id=current['current_version_id'],source=source,run_id=run_id,
        input_hash=input_hash or calibrate(connection,owner,plan_id)['input_hash'],items=_public_items(items),
        **_body('draft',draft_id,value,body)))
    return draft_id


def validate_feedback(connection,owner,session_id,value):
    session=owned(connection,owner,'learning_session',session_id)
    delegation=owned(connection,owner,'learning_delegation',session['delegation_id'])
    link=connection.execute('SELECT plan_id FROM learning_action_link WHERE owner_id=? AND action_id=?',(owner,delegation['action_id'])).fetchone()
    refs=[]
    if value['artifact_id']:
        artifact=owned(connection,owner,'learning_artifact',value['artifact_id'])
        number=value['artifact_version'] or artifact['content_version']
        raw=connection.execute('SELECT session_id FROM learning_raw_artifact WHERE owner_id=? AND artifact_id=? AND content_version=?',(owner,value['artifact_id'],number)).fetchone()
        if not raw or raw['session_id']!=session_id:raise DomainError('commitment_feedback_scope',422)
        refs.append({'kind':'artifact','id':value['artifact_id'],'revision':number});value['artifact_version']=number
    if value['submission_id']:
        submission=owned(connection,owner,'learning_verification_submission',value['submission_id'])
        verification=owned(connection,owner,'learning_verification',submission['verification_id'])
        if verification['delegation_id']!=session['delegation_id'] or verification['session_id']!=session_id:
            raise DomainError('commitment_feedback_scope',422)
        refs.append({'kind':'submission','id':value['submission_id'],'revision':1})
    if value['delayed_attempt_id']:
        attempt=owned(connection,owner,'learning_delayed_attempt',value['delayed_attempt_id'])
        follow=owned(connection,owner,'learning_delayed_follow_up',attempt['follow_up_id'])
        if follow['delegation_id']!=session['delegation_id'] or not attempt['submitted_at']:
            raise DomainError('commitment_feedback_scope',422)
        refs.append({'kind':'delayed_attempt','id':attempt['id'],'revision':attempt['revision']})
        # This is the owner's new association, never a claim that the delayed
        # attempt happened inside this historical session.
        value['association_basis']='user_report'
        value['association_description_code']='linked_result_to_session'
    if any(not source_available(connection,owner,ref) for ref in refs):raise DomainError('commitment_source_unavailable')
    origin,basis=known_origin(connection,owner,delegation['action_id'])
    if origin and value['purpose']=='real':raise DomainError('commitment_synthetic_origin_locked',422)
    value['origin_basis']=basis or 'user_report';value['known_origin']=origin;value['source_refs']=refs
    return link['plan_id'] if link else None,value


def dispatch_commitment(core,connection,principal,command,command_id,key,now):
    owner=principal.owner_id
    if isinstance(command,(RecordSessionFeedback,PurgeSessionFeedback)):
        session=owned(connection,owner,'learning_session',command.session_id)
        old=connection.execute('SELECT * FROM learning_session_feedback WHERE owner_id=? AND id=?',(owner,command.session_id)).fetchone()
        value=old['revision'] if old else 0
        if value!=command.expected_revision:raise DomainError('version_conflict')
        if isinstance(command,PurgeSessionFeedback):
            if old is None:raise DomainError('not_found',404)
            payload={'id':command.session_id,'plan_id':old['plan_id']};event_type='feedback.purged'
        else:
            if old and old['purged_at']:raise DomainError('commitment_source_unavailable')
            fields=command.model_dump(exclude={'session_id','expected_revision','notes'})
            plan_id,fields=validate_feedback(connection,owner,command.session_id,fields)
            payload={'id':command.session_id,'plan_id':plan_id,'data':fields,
                **_body('feedback',command.session_id,value+1,{'notes':command.notes,'source_refs':fields['source_refs']})}
            event_type='feedback.recorded'
        event=_append(connection,principal,command_id,key,now,'session_feedback',command.session_id,value,event_type,payload)
        return dict(session_id=command.session_id,revision=event['aggregate_version'])
    if isinstance(command,(FinishCommitmentRun,CancelCommitmentRun)):
        run=owned(connection,owner,'learning_commitment_run',command.run_id)
        if run['revision']!=command.expected_revision:raise DomainError('version_conflict')
        if isinstance(command,PurgeCommitmentRun):
            event_type,payload='commitment.run_purged',{'id':run['id']}
        else:
            if run['status']!='running':raise DomainError('commitment_run_inactive')
            if isinstance(command,CancelCommitmentRun):event_type,payload='commitment.run_canceled',{'id':run['id']}
            else:
                draft_id=None
                if command.status=='succeeded':
                    frozen=original(connection,owner,'run',run['id'],1)
                    latest=input_context(connection,owner,run['plan_id'])
                    if frozen is None or latest['input_hash']!=run['input_hash']:raise DomainError('commitment_input_changed')
                    allowed={(ref['kind'],ref['id'],ref['revision']) for ref in frozen['inputs']['source_refs']}
                    known_items={item['id'] for item in frozen['inputs']['current_items']}
                    if any(item.id and item.id not in known_items for item in command.items):raise DomainError('commitment_ai_item_out_of_scope',422)
                    items=[{**item.model_dump(mode='json'),'id':item.id or str(uuid4())} for item in command.items]
                    if any((ref['kind'],ref['id'],ref['revision']) not in allowed for item in items for ref in item['source_refs']):
                        raise DomainError('commitment_ai_source_out_of_scope',422)
                    validate_items(connection,owner,run['plan_id'],latest['route_version_id'],items,source='ai',calibration=latest['calibration'])
                    draft_id=_draft(connection,principal,command_id,key,now,run['plan_id'],latest['route_version_id'],items,
                        command.explanation,source='ai',run_id=run['id'],input_hash=run['input_hash'])
                elif command.items:raise DomainError('event_scope_invalid')
                event_type,payload='commitment.run_finished',{'id':run['id'],'status':command.status,'reason':command.reason,'draft_id':draft_id}
        event=_append(connection,principal,command_id,key,now,'commitment_run',run['id'],run['revision'],event_type,payload)
        return dict(run_id=run['id'],revision=event['aggregate_version'],draft_id=payload.get('draft_id'))
    plan_id=command.plan_id;current=state(connection,owner,plan_id)
    if current['revision']!=command.expected_revision:raise DomainError('version_conflict')
    if not isinstance(command,PurgeCommitmentDraft):writable_plan(connection,owner,plan_id)
    if isinstance(command,SaveCommitmentDraft):
        items=[{**item.model_dump(mode='json'),'id':item.id or str(uuid4())} for item in command.items]
        source,run_id,frozen_hash='manual',None,None
        if command.draft_id:
            old=owned(connection,owner,'learning_commitment_draft',command.draft_id)
            if old['plan_id']!=plan_id or old['status']!='draft' or old['revision']!=command.expected_draft_revision:
                raise DomainError('commitment_draft_inactive')
            source,run_id,frozen_hash=old['source'],old['run_id'],old['input_hash']
            if source=='ai':
                run=owned(connection,owner,'learning_commitment_run',run_id)
                frozen=original(connection,owner,'run',run_id,1)
                if frozen is None or run['status']!='succeeded':raise DomainError('commitment_source_unavailable')
                latest=input_context(connection,owner,plan_id)
                latest['commitment_revision']=run['base_revision'];latest.pop('input_hash')
                if digest(latest)!=run['input_hash']:raise DomainError('commitment_input_changed')
                allowed={(ref['kind'],ref['id'],ref['revision']) for ref in frozen['inputs']['source_refs']}
                if any((ref['kind'],ref['id'],ref['revision']) not in allowed for item in items for ref in item['source_refs']):
                    raise DomainError('commitment_ai_source_out_of_scope',422)
        validate_items(connection,owner,plan_id,command.route_version_id,items,source=source,calibration=calibrate(connection,owner,plan_id))
        draft_id=_draft(connection,principal,command_id,key,now,plan_id,command.route_version_id,items,command.reason,
            source=source,run_id=run_id,input_hash=frozen_hash,draft_id=command.draft_id)
        return dict(plan_id=plan_id,draft_id=draft_id,revision=current['revision']+1)
    if isinstance(command,ConfirmCommitments):
        checked=review(connection,owner,plan_id,command.draft_id)
        if checked['draft_revision']!=command.expected_draft_revision or checked['review_key']!=command.review_key:
            raise DomainError('commitment_review_changed')
        version_id=str(uuid4());draft=checked['draft'];items=list(checked['items'])
        # Executed promises remain part of history and keep their stable block ID.
        for previous in checked['old_items']:
            if any(item['id']==previous['id'] for item in items):continue
            row=owned(connection,owner,'learning_commitment_item',previous['id'])
            if row['status']=='skipped' or item_status(connection,owner,row)=='completed' or connection.execute('SELECT 1 FROM learning_commitment_execution WHERE owner_id=? AND item_id=?',(owner,previous['id'])).fetchone():
                items.append(previous)
        _plan_event(connection,principal,command_id,key,now,plan_id,'commitment.confirmed',dict(id=version_id,draft_id=draft['id'],
            private_revision=draft['revision'],route_version_id=draft['route_version_id'],source=draft['source'],items=items,changes=checked['changes']))
        return dict(plan_id=plan_id,version_id=version_id,revision=current['revision']+1)
    if isinstance(command,StartCommitmentItem):
        item=owned(connection,owner,'learning_commitment_item',command.item_id)
        if item['plan_id']!=plan_id:raise DomainError('not_found',404)
        if item_status(connection,owner,item)=='completed':raise DomainError('commitment_item_completed')
        path=plan_state(connection,owner,plan_id)
        if path['adopted_version_id']!=item['route_version_id']:raise DomainError('commitment_route_changed')
        action=owned(connection,owner,'learning_action',item['action_id'])
        if action['version']!=command.expected_action_version:raise DomainError('version_conflict')
        running=connection.execute("SELECT s.id,x.item_id FROM learning_session s LEFT JOIN learning_commitment_execution x ON x.owner_id=s.owner_id AND x.session_id=s.id WHERE s.owner_id=? AND s.delegation_id=? AND s.status='running'",(owner,item['delegation_id'])).fetchone()
        if running and running['item_id'] and running['item_id']!=item['id']:
            # Selecting another explicit promise is a new work block, even when
            # it references the same still-open task. Keep the old execution.
            core._dispatch(connection,principal,EndSession(session_id=running['id'],disposition='interrupted',expected_version=action['version']),command_id,key,now)
        expected=owned(connection,owner,'learning_action',item['action_id'])['version']
        result=core._dispatch(connection,principal,StartPathTask(plan_id=plan_id,version_id=item['route_version_id'],node_id=item['node_id'],
            delegation_id=item['delegation_id'],expected_action_version=expected,expected_revision=path['revision'],use_checkpoint=command.use_checkpoint),command_id,key,now)
        linked=connection.execute('SELECT item_id FROM learning_commitment_execution WHERE owner_id=? AND session_id=?',(owner,result['session_id'])).fetchone()
        if linked and linked['item_id']!=item['id']:raise DomainError('commitment_session_already_linked')
        version=owned(connection,owner,'learning_commitment_version',current['current_version_id'])
        estimate=next((value for value in json.loads(version['data_json']) if value['id']==item['id']),None)
        if estimate is None:
            version=owned(connection,owner,'learning_commitment_version',item['first_version_id'])
            estimate=next(value for value in json.loads(version['data_json']) if value['id']==item['id'])
        _plan_event(connection,principal,command_id,key,now,plan_id,'commitment.item_started',dict(item_id=item['id'],session_id=result['session_id'],
            version_id=version['id'],estimate_min_minutes=estimate['estimate_min_minutes'],estimate_max_minutes=estimate['estimate_max_minutes'],
            due_at=item['future_due_at'],availability_revision=current['availability_revision']))
        return dict(plan_id=plan_id,session_id=result['session_id'],revision=current['revision']+1,**({'path_anchor':result['path_anchor']} if result.get('path_anchor') else {}))
    if isinstance(command,ChangeCommitmentItem):
        checked=item_review(connection,owner,plan_id,command.item_id,command.operation,command.due_at,command.timezone)
        if checked['review_key']!=command.review_key:raise DomainError('commitment_review_changed')
        for session in checked['affected_sessions']:
            core._dispatch(connection,principal,EndSession(session_id=session['id'],disposition='interrupted',expected_version=session['action_version']),command_id,key,now)
        _plan_event(connection,principal,command_id,key,now,plan_id,'commitment.item_changed',dict(item_id=command.item_id,
            status='deferred' if command.operation=='defer' else 'skipped',due_at=command.due_at,timezone=command.timezone))
        return dict(plan_id=plan_id,revision=current['revision']+1)
    if isinstance(command,SaveAvailability):
        data=command.model_dump(exclude={'plan_id','expected_revision'},mode='json')
        _plan_event(connection,principal,command_id,key,now,plan_id,'commitment.availability_saved',{'data':data})
        return dict(plan_id=plan_id,revision=current['revision']+1)
    if isinstance(command,StartCommitmentRun):
        if connection.execute("SELECT 1 FROM learning_commitment_run WHERE owner_id=? AND plan_id=? AND status='running'",(owner,plan_id)).fetchone():
            raise DomainError('commitment_generation_running')
        inputs=input_context(connection,owner,plan_id)
        if not inputs['route_version_id']:raise DomainError('commitment_route_required')
        if inputs!=command.inputs or inputs['input_hash']!=command.input_hash:raise DomainError('commitment_input_changed')
        run_id=str(uuid4())
        event=_append(connection,principal,command_id,key,now,'commitment_run',run_id,0,'commitment.run_started',dict(id=run_id,
            plan_id=plan_id,input_hash=command.input_hash,base_revision=current['revision'],provider_snapshot=command.provider_snapshot,
            **_body('run',run_id,1,{'inputs':inputs,'source_refs':inputs['source_refs']})))
        return dict(plan_id=plan_id,run_id=run_id,revision=event['aggregate_version'])
    if isinstance(command,PurgeCommitmentDraft):
        draft=owned(connection,owner,'learning_commitment_draft',command.draft_id)
        if draft['plan_id']!=plan_id:raise DomainError('not_found',404)
        _plan_event(connection,principal,command_id,key,now,plan_id,'commitment.content_purged',{'draft_id':draft['id']})
        return dict(plan_id=plan_id,revision=current['revision']+1)
    raise DomainError('command_unsupported',422)


def erase_private(connection,owner,kind,identifier,now):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='learning_commitment_private'").fetchone():return
    queue=[(kind,identifier)];visited=set()
    while queue:
        target=queue.pop()
        if target in visited:continue
        visited.add(target);private_kind,object_id=target
        connection.execute('INSERT OR IGNORE INTO learning_commitment_private_tombstone VALUES (?,?,?,?)',(owner,private_kind,object_id,now))
        connection.execute('UPDATE learning_commitment_private SET content_json=NULL,content_hash=NULL,purged_at=COALESCE(purged_at,?) WHERE owner_id=? AND kind=? AND object_id=?',(now,owner,private_kind,object_id))
        if private_kind=='draft':
            connection.execute("UPDATE learning_commitment_draft SET status='purged',purged_at=COALESCE(purged_at,?) WHERE owner_id=? AND id=?",(now,owner,object_id))
            connection.execute('UPDATE learning_commitment_version SET purged_at=COALESCE(purged_at,?) WHERE owner_id=? AND draft_id=?',(now,owner,object_id))
        elif private_kind=='run':
            connection.execute("UPDATE learning_commitment_run SET status='purged',reason='content_purged',purged_at=COALESCE(purged_at,?) WHERE owner_id=? AND id=?",(now,owner,object_id))
        elif private_kind=='feedback':
            if connection.execute("SELECT 1 FROM sqlite_master WHERE name='learning_session_feedback'").fetchone():
                connection.execute('UPDATE learning_session_feedback SET purged_at=COALESCE(purged_at,?) WHERE owner_id=? AND id=?',(now,owner,object_id))
        queue.extend((row['kind'],row['object_id']) for row in connection.execute('SELECT DISTINCT kind,object_id FROM learning_commitment_source WHERE owner_id=? AND source_kind=? AND source_id=?',(owner,private_kind,object_id)))


def erase_sources(connection,owner,source_kind,identifiers,now):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='learning_commitment_source'").fetchone():return
    for identifier in identifiers:
        for row in connection.execute('SELECT DISTINCT kind,object_id FROM learning_commitment_source WHERE owner_id=? AND source_kind=? AND source_id=?',(owner,source_kind,identifier)).fetchall():
            erase_private(connection,owner,row['kind'],row['object_id'],now)


def apply_commitment_event(connection,event,payload):
    owner,value,now,kind=event['owner_id'],event['aggregate_version'],event['occurred_at'],event['event_type']
    _private(connection,event,payload)
    if kind.startswith('feedback.'):
        if event['aggregate_type']!='session_feedback' or event['aggregate_id']!=payload['id']:raise DomainError('event_scope_invalid')
        identifier=payload['id']
        if kind=='feedback.recorded':
            purged=connection.execute("SELECT purged_at FROM learning_commitment_private_tombstone WHERE owner_id=? AND kind='feedback' AND object_id=?",(owner,identifier)).fetchone()
            connection.execute('''INSERT INTO learning_session_feedback VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                revision=excluded.revision,data_json=excluded.data_json,updated_at=excluded.updated_at,purged_at=excluded.purged_at''',
                (identifier,owner,payload['plan_id'],identifier,value,canonical(payload['data']),now,now,purged[0] if purged else None))
            connection.execute('INSERT INTO learning_session_feedback_history VALUES (?,?,?,?,?,?)',(owner,identifier,value,canonical(payload['data']),event['event_id'],now))
        else:
            erase_private(connection,owner,'feedback',identifier,now)
            connection.execute('UPDATE learning_session_feedback SET revision=?,updated_at=? WHERE owner_id=? AND id=?',(value,now,owner,identifier))
        return
    if kind.startswith('commitment.run_'):
        identifier=payload['id']
        if event['aggregate_type']!='commitment_run' or event['aggregate_id']!=identifier:raise DomainError('event_scope_invalid')
        if kind=='commitment.run_started':
            purged=connection.execute("SELECT purged_at FROM learning_commitment_private_tombstone WHERE owner_id=? AND kind='run' AND object_id=?",(owner,identifier)).fetchone()
            connection.execute('INSERT INTO learning_commitment_run VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (identifier,owner,payload['plan_id'],value,'purged' if purged else 'running',payload['input_hash'],payload['base_revision'],
                 canonical(payload['provider_snapshot']),None,'content_purged' if purged else None,now,None,purged[0] if purged else None))
        elif kind=='commitment.run_purged':
            erase_private(connection,owner,'run',identifier,now)
            connection.execute('UPDATE learning_commitment_run SET revision=?,finished_at=? WHERE owner_id=? AND id=?',(value,now,owner,identifier))
        else:
            row=owned(connection,owner,'learning_commitment_run',identifier)
            status='purged' if row['purged_at'] else 'canceled' if kind=='commitment.run_canceled' else payload['status']
            connection.execute('UPDATE learning_commitment_run SET revision=?,status=?,reason=?,draft_id=?,finished_at=? WHERE owner_id=? AND id=?',
                (value,status,'content_purged' if row['purged_at'] else payload.get('reason'),payload.get('draft_id'),now,owner,identifier))
        return
    plan_id=payload['plan_id']
    if event['aggregate_type']!='commitment' or event['aggregate_id']!=plan_id:raise DomainError('event_scope_invalid')
    current=state(connection,owner,plan_id)
    if current['revision']!=value-1:raise DomainError('projection_gap')
    if kind=='commitment.draft_saved':
        purged=connection.execute("SELECT purged_at FROM learning_commitment_private_tombstone WHERE owner_id=? AND kind='draft' AND object_id=?",(owner,payload['id'])).fetchone()
        connection.execute('''INSERT INTO learning_commitment_draft VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            revision=excluded.revision,data_json=excluded.data_json,input_hash=excluded.input_hash,updated_at=excluded.updated_at,status=excluded.status,purged_at=excluded.purged_at,route_version_id=excluded.route_version_id,base_version_id=excluded.base_version_id,source=excluded.source,run_id=excluded.run_id''',
            (payload['id'],owner,plan_id,value,'purged' if purged else 'draft',payload['route_version_id'],payload['base_version_id'],payload['input_hash'],payload['source'],payload['run_id'],canonical(payload['items']),now,now,purged[0] if purged else None))
    elif kind=='commitment.confirmed':
        draft=owned(connection,owner,'learning_commitment_draft',payload['draft_id'])
        if draft['plan_id']!=plan_id or draft['revision']!=payload['private_revision']:raise DomainError('event_scope_invalid')
        connection.execute('INSERT INTO learning_commitment_version VALUES (?,?,?,?,?,?,?,?,?,?)',
            (payload['id'],owner,plan_id,payload['route_version_id'],draft['id'],payload['private_revision'],payload['source'],canonical(payload['items']),now,draft['purged_at']))
        retained={change['item_id'] for change in payload['changes'] if change.get('reason_code') in {'execution_preserved','skipped_preserved'}}
        for item in payload['items']:
            old=connection.execute('SELECT * FROM learning_commitment_item WHERE owner_id=? AND id=?',(owner,item['id'])).fetchone()
            if old:
                if old['plan_id']!=plan_id or old['action_id']!=item['action_id'] or old['delegation_id']!=item['delegation_id']:raise DomainError('event_scope_invalid')
                if item['id'] in retained or old['status']=='skipped' or item_status(connection,owner,old)=='completed':
                    continue
                disposition=next((change for change in payload['changes'] if change['item_id']==item['id']),None)
                preserved=bool(disposition and disposition.get('reason_code')=='execution_preserved')
                if preserved or item_status(connection,owner,old)=='completed' or old['status']=='skipped':continue
                executed=connection.execute('SELECT 1 FROM learning_commitment_execution WHERE owner_id=? AND item_id=?',(owner,item['id'])).fetchone()
                if executed:
                    connection.execute('UPDATE learning_commitment_item SET route_version_id=?,node_id=? WHERE owner_id=? AND id=?', (payload['route_version_id'],item['node_id'],owner,item['id']))
                else:
                    connection.execute("UPDATE learning_commitment_item SET route_version_id=?,node_id=?,future_due_at=?,future_timezone=?,status='planned',updated_at=? WHERE owner_id=? AND id=?",
                        (payload['route_version_id'],item['node_id'],item['due_at'],item['timezone'],now,owner,item['id']))
            else:
                delegation=owned(connection,owner,'learning_delegation',item['delegation_id'])
                if delegation['action_id']!=item['action_id']:raise DomainError('event_scope_invalid')
                connection.execute("INSERT INTO learning_commitment_item VALUES (?,?,?,?,?,?,?,?,'planned',?,?,?,?)",
                    (item['id'],owner,plan_id,payload['id'],payload['route_version_id'],item['node_id'],item['action_id'],item['delegation_id'],item['due_at'],item['timezone'],now,now))
        for change in payload['changes']:
            if change['kind']=='defer':
                connection.execute("UPDATE learning_commitment_item SET status='deferred',updated_at=? WHERE owner_id=? AND id=?",(now,owner,change['item_id']))
        connection.execute("UPDATE learning_commitment_draft SET status=CASE WHEN purged_at IS NULL THEN 'confirmed' ELSE 'purged' END WHERE owner_id=? AND id=?",(owner,draft['id']))
        current['current_version_id']=payload['id']
    elif kind=='commitment.item_started':
        item=owned(connection,owner,'learning_commitment_item',payload['item_id'])
        session=owned(connection,owner,'learning_session',payload['session_id'])
        if item['plan_id']!=plan_id or session['delegation_id']!=item['delegation_id']:raise DomainError('event_scope_invalid')
        existing=connection.execute('SELECT item_id FROM learning_commitment_execution WHERE owner_id=? AND session_id=?',(owner,session['id'])).fetchone()
        if existing and existing['item_id']!=item['id']:raise DomainError('event_scope_invalid')
        connection.execute('INSERT OR IGNORE INTO learning_commitment_execution VALUES (?,?,?,?,?,?,?,?,?)',
            (owner,item['id'],session['id'],payload['version_id'],payload['estimate_min_minutes'],payload['estimate_max_minutes'],payload['due_at'],payload['availability_revision'],now))
        connection.execute("UPDATE learning_commitment_item SET status='started',updated_at=? WHERE owner_id=? AND id=?",(now,owner,item['id']))
    elif kind=='commitment.item_changed':
        item=owned(connection,owner,'learning_commitment_item',payload['item_id'])
        if item['plan_id']!=plan_id:raise DomainError('event_scope_invalid')
        connection.execute('UPDATE learning_commitment_item SET status=?,future_due_at=?,future_timezone=?,updated_at=? WHERE owner_id=? AND id=?',
            (payload['status'],payload['due_at'],payload['timezone'],now,owner,item['id']))
    elif kind=='commitment.route_changed':
        for change in payload['changes']:
            item=owned(connection,owner,'learning_commitment_item',change['item_id'])
            if item['plan_id']!=plan_id:raise DomainError('event_scope_invalid')
            if change['completed'] or change.get('skip_preserved'):continue
            if change['kind']=='keep':
                connection.execute('UPDATE learning_commitment_item SET route_version_id=?,node_id=?,updated_at=? WHERE owner_id=? AND id=?', (payload['route_version_id'],change['to_node_id'],now,owner,item['id']))
            else:
                connection.execute("UPDATE learning_commitment_item SET status='deferred',updated_at=? WHERE owner_id=? AND id=?",(now,owner,item['id']))
    elif kind=='commitment.availability_saved':
        connection.execute('INSERT INTO learning_commitment_availability VALUES (?,?,?,?) ON CONFLICT(owner_id,plan_id) DO UPDATE SET revision=excluded.revision,data_json=excluded.data_json',
            (owner,plan_id,value,canonical(payload['data'])))
        current['availability_revision']=value
    elif kind=='commitment.content_purged':erase_private(connection,owner,'draft',payload['draft_id'],now)
    else:raise DomainError('event_type_unsupported')
    connection.execute('INSERT INTO learning_plan_commitment_state VALUES (?,?,?,?,?,?) ON CONFLICT(owner_id,plan_id) DO UPDATE SET revision=excluded.revision,current_version_id=excluded.current_version_id,availability_revision=excluded.availability_revision,last_event_id=excluded.last_event_id',
        (owner,plan_id,value,current['current_version_id'],current['availability_revision'],event['event_id']))


def route_change_review(connection,owner,plan_id,proposed_data,*,intent,pause_all=False):
    """Preview changes to remaining promises, preserving execution identities."""
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='learning_plan_commitment_state'").fetchone():
        return dict(revision=0,changes=[],item_states=[],affected_sessions=[],available=False,fingerprint=digest([]))
    current=state(connection,owner,plan_id);changes=[];states=[];sessions=[]
    nodes=proposed_data.get('nodes',[])
    for raw in connection.execute('SELECT * FROM learning_commitment_item WHERE owner_id=? AND plan_id=? ORDER BY created_at,id',(owner,plan_id)):
        item=dict(raw);status=item_status(connection,owner,item)
        possible=[node['id'] for node in nodes if item['action_id'] in node['action_ids']]
        target=item['node_id'] if item['node_id'] in possible else possible[0] if len(possible)==1 else None
        skipped=item['status']=='skipped';completed=status=='completed'
        keep=completed or skipped or (not pause_all and intent!='change_direction' and target is not None)
        action=owned(connection,owner,'learning_action',item['action_id'])
        states.append(dict(item_id=item['id'],status=status,route_version_id=item['route_version_id'],node_id=item['node_id'],
            action_id=item['action_id'],action_version=action['version'],delegation_id=item['delegation_id'],
            execution_session_ids=[r[0] for r in connection.execute('SELECT session_id FROM learning_commitment_execution WHERE owner_id=? AND item_id=? ORDER BY session_id',(owner,item['id']))]))
        changes.append(dict(item_id=item['id'],action_title=action['title'],kind='keep' if keep else 'defer',
            from_node_id=item['node_id'],to_node_id=target if keep and not completed and not skipped else item['node_id'],
            completed=completed,skip_preserved=skipped,executed=bool(states[-1]['execution_session_ids']),
            reason_code='completed_preserved' if completed else 'skipped_preserved' if skipped else 'explicit_direction_change' if intent=='change_direction' or pause_all else 'same_task_position' if keep else 'position_ambiguous_or_missing'))
        if not keep:
            sessions.extend(dict(r) for r in connection.execute('''SELECT s.id,s.version,d.action_id,a.version AS action_version,a.title AS action_title
                FROM learning_commitment_execution x JOIN learning_session s ON s.owner_id=x.owner_id AND s.id=x.session_id
                JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id JOIN learning_action a ON a.owner_id=d.owner_id AND a.id=d.action_id
                WHERE x.owner_id=? AND x.item_id=? AND s.status='running' ''',(owner,item['id'])))
    fingerprint=digest({'revision':current['revision'],'item_states':states,'changes':[{k:v for k,v in change.items() if k!='action_title'} for change in changes]})
    return dict(revision=current['revision'],changes=changes,item_states=states,affected_sessions=sessions,available=True,fingerprint=fingerprint)


def apply_route_change(core,connection,principal,plan_id,new_route_version_id,review,command_id,key,now):
    if not review.get('available',True):return dict(revision=review['revision'])
    current=state(connection,principal.owner_id,plan_id)
    if current['revision']!=review['revision']:raise DomainError('version_conflict')
    # The path transaction owns normal session interruption before this hook.
    # Refuse a missed running effect rather than changing a live promise silently.
    for session in review.get('affected_sessions',[]):
        actual=owned(connection,principal.owner_id,'learning_session',session['id'])
        if actual['status']=='running':raise DomainError('commitment_session_pause_required')
    changes=[{key:value for key,value in change.items() if key!='action_title'} for change in review['changes']]
    event=_plan_event(connection,principal,command_id,key,now,plan_id,'commitment.route_changed',
        {'route_version_id':new_route_version_id,'changes':changes})
    return dict(revision=event['aggregate_version'])
