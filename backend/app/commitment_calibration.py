"""Explainable D2 signal admission. No time, count or AI praise implies mastery."""
from datetime import datetime,timezone,timedelta
import json
from .core.events import digest

RULE_VERSION='d2-calibration-1'
RULES={'version':RULE_VERSION,'window_work_blocks':7,'short_default':2,'short_max':3,
       'same_scope_max':5,'covered_scope_max':7,'overrun_ratio':1.5}
DEMO_CONTEXT='演示/合成：Python 3 文本处理；仅供界面试用'
DEMO_PREFIX='outcome-graph-demo-v1'


def known_origin(connection,owner,action_id):
    action=connection.execute('SELECT context_key FROM learning_action WHERE owner_id=? AND id=?',(owner,action_id)).fetchone()
    if action and action['context_key']==DEMO_CONTEXT:
        return 'demo','demo_script'
    derived=connection.execute('''SELECT d.outcome_id,d.criterion_id,o.context_key FROM learning_delegation d
        JOIN learning_outcome o ON o.owner_id=d.owner_id AND o.id=d.outcome_id WHERE d.owner_id=? AND d.action_id=?''',(owner,action_id)).fetchall()
    if any(row['context_key']==DEMO_CONTEXT or row['outcome_id'].startswith(DEMO_PREFIX+':') or (row['criterion_id'] or '').startswith(DEMO_PREFIX+':') for row in derived):
        return 'demo','demo_script'
    rows=connection.execute("SELECT idempotency_key FROM learning_event WHERE owner_id=? AND aggregate_type='action' AND aggregate_id=?",(owner,action_id))
    keys=[row[0] for row in rows]
    if any(key.startswith(DEMO_PREFIX+':') for key in keys):
        return 'demo','demo_script'
    if any(key.startswith(('nautilus-test:','test:')) for key in keys):
        return 'test','test_script'
    return None,None


def source_available(connection,owner,ref):
    kind,identifier,value=ref['kind'],ref['id'],ref.get('revision',1)
    if kind=='run':
        row=connection.execute('SELECT status,purged_at FROM learning_commitment_run WHERE owner_id=? AND id=?',(owner,identifier)).fetchone()
        body=connection.execute("SELECT content_json,purged_at FROM learning_commitment_private WHERE owner_id=? AND kind='run' AND object_id=? AND revision=1",(owner,identifier)).fetchone()
        return bool(value==1 and row and row['status']=='succeeded' and not row['purged_at'] and body and not body['purged_at'] and body['content_json'] is not None and all(source_available(connection,owner,r) for r in json.loads(body['content_json']).get('source_refs',[])))
    if kind=='feedback':
        row=connection.execute('SELECT revision,data_json,purged_at FROM learning_session_feedback WHERE owner_id=? AND id=?',(owner,identifier)).fetchone()
        return bool(row and row['revision']==value and not row['purged_at'] and json.loads(row['data_json'])['purpose']=='real' and all(source_available(connection,owner,r) for r in json.loads(row['data_json']).get('source_refs',[])))
    if kind=='artifact':
        row=connection.execute('''SELECT a.content_version,a.visibility,a.evidence_status,r.content,r.purged_at
            FROM learning_artifact a JOIN learning_raw_artifact r ON r.owner_id=a.owner_id AND r.artifact_id=a.id AND r.content_version=?
            WHERE a.owner_id=? AND a.id=?''',(value,owner,identifier)).fetchone()
        return bool(row and row['content_version']==value and row['visibility']=='visible' and row['evidence_status']=='eligible' and row['content'] is not None and not row['purged_at'])
    if kind=='submission':
        row=connection.execute('''SELECT s.*,v.purged_at AS verification_purged FROM learning_verification_submission s
            JOIN learning_verification v ON v.owner_id=s.owner_id AND v.id=s.verification_id WHERE s.owner_id=? AND s.id=?''',(owner,identifier)).fetchone()
        if not row or row['purged_at'] or row['verification_purged'] or value!=1:
            return False
        return not row['artifact_id'] or source_available(connection,owner,{'kind':'artifact','id':row['artifact_id'],'revision':1})
    if kind=='delayed_attempt':
        row=connection.execute('''SELECT a.revision,a.submitted_at,a.purged_at,f.purged_at AS source_purged
            FROM learning_delayed_attempt a JOIN learning_delayed_follow_up f ON f.owner_id=a.owner_id AND f.id=a.follow_up_id
            WHERE a.owner_id=? AND a.id=?''',(owner,identifier)).fetchone()
        return bool(row and row['revision']==value and row['submitted_at'] and not row['purged_at'] and not row['source_purged'])
    if kind=='completion':
        row=connection.execute('SELECT purged_at FROM learning_completion WHERE owner_id=? AND id=?',(owner,identifier)).fetchone()
        return bool(row and not row['purged_at'] and value==1)
    if kind=='path_version':
        row=connection.execute('''SELECT v.purged_at,p.purged_at AS private_purged FROM learning_path_version v
            JOIN learning_path_private p ON p.owner_id=v.owner_id AND p.object_id=v.private_object_id AND p.revision=v.private_revision
            WHERE v.owner_id=? AND v.id=?''',(owner,identifier)).fetchone()
        return bool(row and value==1 and not row['purged_at'] and not row['private_purged'])
    if kind=='plan_content':
        row=connection.execute("SELECT purged_at FROM learning_plan_private WHERE owner_id=? AND kind='plan' AND object_id=? AND revision=?",(owner,identifier,value)).fetchone()
        return bool(row and not row['purged_at'])
    if kind=='action':
        row=connection.execute('SELECT version FROM learning_action WHERE owner_id=? AND id=?',(owner,identifier)).fetchone()
        return bool(row and row['version']>=value)
    if kind=='outcome':
        return value==1 and bool(connection.execute('SELECT 1 FROM learning_outcome WHERE owner_id=? AND id=?',(owner,identifier)).fetchone())
    return False


def route_context(connection,owner,plan_id):
    state=connection.execute('SELECT adopted_version_id,last_decision_id FROM learning_plan_path_state WHERE owner_id=? AND plan_id=?',(owner,plan_id)).fetchone()
    if not state or not state['adopted_version_id']:
        return None,[],None
    version=connection.execute('SELECT * FROM learning_path_version WHERE owner_id=? AND id=?',(owner,state['adopted_version_id'])).fetchone()
    if not version or not source_available(connection,owner,{'kind':'path_version','id':version['id'],'revision':1}):
        return None,[],None
    data=json.loads(version['data_json'])
    identifiers={action for node in data['nodes'] for action in node['action_ids']}
    tasks=[]
    for identifier in sorted(identifiers):
        row=connection.execute('''SELECT a.id,a.title,a.context_key,a.status,a.version,d.id AS delegation_id,d.outcome_id,d.status AS delegation_status,
            o.context_key AS outcome_context,o.object_description,o.behavior,c.boundaries,c.stop_conditions,c.time_budget_minutes FROM learning_action a
            JOIN learning_action_link l ON l.owner_id=a.owner_id AND l.action_id=a.id
            JOIN learning_delegation d ON d.owner_id=a.owner_id AND d.action_id=a.id
            JOIN learning_outcome o ON o.owner_id=d.owner_id AND o.id=d.outcome_id
            JOIN learning_contract_version c ON c.owner_id=d.owner_id AND c.delegation_id=d.id AND c.version=d.contract_version
            WHERE a.owner_id=? AND a.id=? AND l.plan_id=? ORDER BY d.created_at DESC,d.id DESC LIMIT 1''',(owner,identifier,plan_id)).fetchone()
        if row:
            task=dict(row)
            task['node_ids']=[node['id'] for node in data['nodes'] if identifier in node['action_ids']]
            tasks.append(task)
    decision=connection.execute('SELECT intent FROM learning_path_decision WHERE owner_id=? AND id=?',(owner,state['last_decision_id'])).fetchone()
    return dict(version),tasks,decision['intent'] if decision else None


def scope_key(value):
    # A default context label is not evidence that two learning objects or
    # differently sized tasks are comparable. Cross-action reuse requires an
    # explicitly shared outcome, scope, stop boundary and budget.
    declared=bool(value['time_budget_minutes'] is not None and value['boundaries'].strip() and value['stop_conditions'].strip())
    return (value['outcome_id'],value['object_description'],value['behavior'],value['context_key'],value['outcome_context'],
            value['boundaries'],value['stop_conditions'],value['time_budget_minutes'],None if declared else value.get('action_id',value.get('id')))


def direction_routes(connection,owner,version):
    routes={version['route_id']};current=version
    while current:
        decision=connection.execute('SELECT intent FROM learning_path_decision WHERE owner_id=? AND version_id=?',(owner,current['id'])).fetchone()
        intent=decision['intent'] if decision else None
        if intent not in {'change_entry','change_scope'}:break
        parent=current['previous_version_id']
        current=connection.execute('SELECT * FROM learning_path_version WHERE owner_id=? AND id=?',(owner,parent)).fetchone() if parent else None
        if current:routes.add(current['route_id'])
    return routes


def _axis(name,state,refs,unknowns=()):
    unique=[]
    for ref in refs:
        if ref not in unique:unique.append(ref)
    return dict(name=name,state=state,source_refs=unique,unknowns=list(unknowns))


def calibrate(connection,owner,plan_id,*,now=None):
    now=now or datetime.now(timezone.utc)
    version,tasks,intent=route_context(connection,owner,plan_id)
    path_state=connection.execute('SELECT status FROM learning_plan_path_state WHERE owner_id=? AND plan_id=?',(owner,plan_id)).fetchone()
    paused=bool(path_state and path_state['status']=='paused')
    proposed={scope_key(task) for task in tasks if task['status']=='open' and task['delegation_status'] in {'ready','active'}}
    availability=connection.execute('SELECT revision,data_json FROM learning_commitment_availability WHERE owner_id=? AND plan_id=?',(owner,plan_id)).fetchone()
    settings=json.loads(availability['data_json']) if availability else None
    future=[slot for slot in settings['slots'] if datetime.fromisoformat(slot['end_at'])>now] if settings else []
    rows=connection.execute('''SELECT f.*,s.delegation_id,s.started_at,s.ended_at,d.action_id,d.outcome_id,
        a.context_key,o.context_key AS outcome_context,o.object_description,o.behavior,c.boundaries,c.stop_conditions,c.time_budget_minutes,x.item_id,x.version_id,x.estimate_min_minutes,x.estimate_max_minutes,x.due_at,x.availability_revision,
        cv.route_version_id,cv.created_at AS promise_created_at,pv.route_id FROM learning_session_feedback f
        JOIN learning_session s ON s.owner_id=f.owner_id AND s.id=f.session_id
        JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
        JOIN learning_action a ON a.owner_id=d.owner_id AND a.id=d.action_id
        JOIN learning_outcome o ON o.owner_id=d.owner_id AND o.id=d.outcome_id
        JOIN learning_contract_version c ON c.owner_id=d.owner_id AND c.delegation_id=d.id AND c.version=d.contract_version
        LEFT JOIN learning_commitment_execution x ON x.owner_id=s.owner_id AND x.session_id=s.id
        LEFT JOIN learning_commitment_version cv ON cv.owner_id=x.owner_id AND cv.id=x.version_id
        LEFT JOIN learning_path_version pv ON pv.owner_id=cv.owner_id AND pv.id=cv.route_version_id
        WHERE f.owner_id=? AND f.plan_id=? ORDER BY f.updated_at DESC,f.session_id''',(owner,plan_id)).fetchall()
    blocks,excluded={},[]
    current_actions={task['id'] for task in tasks}
    allowed_routes=direction_routes(connection,owner,version) if version else set()
    for row in rows:
        data=json.loads(row['data_json'])
        reason=None
        if row['purged_at'] or data['purpose']!='real':
            reason='origin_not_real'
        elif known_origin(connection,owner,row['action_id'])[0] is not None:
            reason='synthetic_source'
        elif not version or row['action_id'] not in current_actions:
            reason='outside_current_direction'
        elif (row['route_id'] and row['route_id'] not in allowed_routes) or (intent=='change_direction' and not row['route_id']):
            reason='outside_current_direction'
        elif any(not source_available(connection,owner,ref) for ref in data.get('source_refs',[])):
            reason='source_unavailable'
        if reason:
            excluded.append({'kind':'feedback','id':row['id'],'revision':row['revision'],'reason':reason})
            continue
        block_id=row['item_id'] or ('session:'+row['session_id'])
        block=blocks.setdefault(block_id,dict(id=block_id,feedback=[],source_refs=[],context=scope_key(dict(row)),
            actual_min=0,actual_max=0,effort_known=True,estimate_min=row['estimate_min_minutes'],estimate_max=row['estimate_max_minutes'],
            version_id=row['version_id'],due_at=row['due_at'],started_at=row['started_at'],session_started_ats=[],availability_revision=row['availability_revision'],updated_at=row['ended_at'] or row['started_at']))
        block['feedback'].append(data)
        block['session_started_ats'].append(row['started_at'])
        block['source_refs'].append({'kind':'feedback','id':row['id'],'revision':row['revision']})
        block['source_refs'].extend(data.get('source_refs',[]))
        block['effort_known'] &= data['actual_min_minutes'] is not None and bool(row['promise_created_at'] and row['started_at']>=row['promise_created_at'])
        if data['actual_min_minutes'] is not None:
            block['actual_min']+=data['actual_min_minutes'];block['actual_max']+=data['actual_max_minutes']
    ordered=sorted(blocks.values(),key=lambda row:(row['updated_at'],row['id']),reverse=True)
    window=ordered[:RULES['window_work_blocks']]
    older=[{'block_id':row['id'],'reason':'outside_recent_window','source_refs':row['source_refs']} for row in ordered[7:]]
    for block in ordered:
        if not block['id'].startswith('session:'):
            sessions=connection.execute('SELECT COUNT(*) FROM learning_commitment_execution WHERE owner_id=? AND item_id=?',(owner,block['id'])).fetchone()[0]
            block['effort_known'] &= sessions==len(block['feedback'])
        feedback=block['feedback']
        block['experience']=all(data['grain']=='ok' and data['pace']=='ok' and data['method_feedback']=='ok' for data in feedback)
        block['burden']=any(data['grain']=='too_large' or data['pace']=='too_tight' or data['method_feedback']=='unsuitable' for data in feedback)
        block['conflict']=any(data['progress']=='difficulty' for data in feedback)
        block['performance']=any(data['activity'] in {'recall','variation','transfer'} and data['progress']=='progress'
            and data.get('source_refs') for data in feedback)
        block['match']=bool(block['effort_known'] and block['estimate_min'] is not None and block['estimate_min']<=block['actual_min']<=block['actual_max']<=block['estimate_max'])
        block['timing_match']=bool(settings and block['due_at'] and block['availability_revision']==availability['revision'] and block['effort_known'] and block['actual_max']<=settings['block_max_minutes'] and any(
            all(slot['start_at']<=instant<=slot['end_at'] for instant in block['session_started_ats']) and slot['start_at']<=block['due_at']<=slot['end_at']
            and block['actual_max']<=(datetime.fromisoformat(slot['end_at'])-datetime.fromisoformat(slot['start_at'])).total_seconds()/60 for slot in settings['slots']))
        block['overrun']=bool(block['effort_known'] and block['estimate_max'] is not None and block['actual_min']>RULES['overrun_ratio']*block['estimate_max'])
    representatives={}
    for block in ordered:
        if block['performance'] and block['context'] in proposed:
            representatives.setdefault(block['context'],block)
    coverage_blocks=[*window,*[block for block in representatives.values() if block['id'] not in {b['id'] for b in window}]]
    refs=[]
    for block in coverage_blocks:
        for ref in block['source_refs']:
            if ref not in refs:refs.append(ref)
    experienced=[block for block in coverage_blocks if block['experience']]
    performance=[block for block in coverage_blocks if block['performance']]
    matched=[block for block in coverage_blocks if block['match']]
    observed={block['context'] for block in coverage_blocks}
    new_context=bool(proposed-observed)
    burden=any(block['burden'] for block in window)
    conflict=any(block['conflict'] for block in window)
    comparable=[block for block in window if block['estimate_max'] is not None and block['effort_known']][:3]
    overrun=sum(block['overrun'] for block in comparable)>=2
    state='short';maximum=3;horizon=None;codes=[]
    if not window:codes.append('insufficient_real_execution')
    if not version:codes.append('route_missing')
    if new_context:codes.append('new_context')
    if conflict:codes.append('performance_conflict')
    if burden:codes.append('reported_burden')
    if overrun:codes.append('comparable_effort_overrun')
    limited_coverage=bool(proposed and all(any(b['context']==context and b['performance'] and b['experience'] for b in coverage_blocks) for context in proposed))
    if version and window and not new_context and not conflict and not burden and not overrun and limited_coverage:
        state,maximum='extended',5
        codes.append('same_scope_supported')
        coverage=all(any(b['context']==context and b['performance'] and b['experience'] and b['match'] for b in coverage_blocks) for context in proposed)
        if len(observed)>=2 and coverage:
            maximum=7;codes.append('representative_contexts_supported')
        rounds={block['version_id'] for block in window if block['version_id'] and block['due_at'] and block['timing_match'] and block['match'] and block['experience'] and not block['conflict']}
        repeated=bool(len(rounds)>=2 and coverage and all(b['match'] and b['experience'] and b['timing_match'] for b in window if b['due_at']))
        same_availability=bool(availability and all(b['availability_revision']==availability['revision'] for b in window if b['due_at']))
        if repeated and same_availability and future and settings['weekly_budget_minutes'] and settings['block_max_minutes']:
            state,horizon='dated',7
            if settings['preferred_days']==14 and max(datetime.fromisoformat(slot['end_at']) for slot in future)-now>=timedelta(days=13):
                horizon=14
            maximum=min(horizon,len(future));codes.append('repeated_rhythm_with_future_availability')
    unknowns=[]
    if not performance:unknowns.append('performance_attempt_missing')
    if not experienced:unknowns.append('experienced_method_grain_pace_unknown')
    if not matched:unknowns.append('comparable_effective_effort_unknown')
    if not future:unknowns.append('future_availability_missing')
    if availability and window and any(b['due_at'] and b['availability_revision']!=availability['revision'] for b in window):
        unknowns.append('availability_changed')
    if paused:
        state,maximum,horizon='short',3,None
        codes.append('route_paused');unknowns.append('route_requires_restore')
    axes=[_axis('execution','covered' if window else 'unknown',refs,[] if window else ['real_work_block_missing']),
          _axis('performance','conflict' if conflict else 'covered' if performance else 'unknown',
                [r for b in performance for r in b['source_refs']],['help_conditions_not_inferred']),
          _axis('effort','conflict' if overrun else 'covered' if matched else 'partial' if any(b['effort_known'] for b in window) else 'unknown',
                [r for b in matched for r in b['source_refs']],[] if matched else ['budget_and_session_span_do_not_supply_effective_effort']),
          _axis('experience','conflict' if burden else 'covered' if experienced else 'unknown',
                [r for b in experienced for r in b['source_refs']],[] if experienced else ['personal_experience_missing']),
          _axis('rhythm','covered' if state=='dated' else 'partial' if future else 'unknown',refs,
                [] if state=='dated' else ['repeated_rhythm_or_future_capacity_unknown'])]
    if state=='short':
        recommended=1 if len([task for task in tasks if task['status']=='open'])==1 else 2
        minimum=1
    elif state=='extended':
        recommended=5 if maximum==7 else 3
        minimum=3
    else:
        upper=max([block['estimate_max'] for block in matched if block['estimate_max'] is not None],default=None)
        slots_capacity=sum(int(min((datetime.fromisoformat(slot['end_at'])-max(now,datetime.fromisoformat(slot['start_at']))).total_seconds()/60,settings['block_max_minutes'])//upper) for slot in future) if upper else 0
        budget_capacity=(settings['weekly_budget_minutes']*(horizon//7))//upper if upper else 0
        maximum=min(maximum,slots_capacity,budget_capacity)
        recommended=maximum
        minimum=1 if maximum else 0
        if not maximum:
            unknowns.append('future_capacity_insufficient')
            codes.append('future_capacity_insufficient')
    if paused:recommended,minimum=0,0
    result=dict(rule_version=RULE_VERSION,range=state,max_sessions=maximum,
        min_sessions=minimum,recommended_sessions=recommended,
        horizon_days=horizon,reason_codes=codes,axes=axes,sources=refs,unknowns=unknowns,
        excluded_sources=excluded,older_sources=older,representative_sources=[{'block_id':b['id'],'outcome_id':b['context'][0],'scope_hash':digest(b['context']),'source_refs':b['source_refs'],'reason_code':'latest_comparable_source'} for b in representatives.values()],work_block_ids=[b['id'] for b in window],
        scope='new' if new_context or not window else 'covered' if maximum==7 else 'same')
    result['input_hash']=digest({'result':result,'route_version_id':version['id'] if version else None,
        'route_intent':intent,'tasks':[{key:task[key] for key in ('id','version','status','delegation_id','outcome_id','object_description','behavior','context_key','outcome_context','boundaries','stop_conditions','time_budget_minutes')} for task in tasks],
        'availability':dict(availability) if availability else None})
    return result


def signal_summary(connection,owner,ref):
    """Only declared assessment metadata; never answer, note or chat content."""
    result=dict(ref,available=source_available(connection,owner,ref),independence='not_inferred')
    if not result['available']:return result
    if ref['kind']=='submission':
        row=connection.execute('''SELECT s.content_json,s.created_at,v.status,v.stop_condition_confirmed
            FROM learning_verification_submission s JOIN learning_verification v ON v.owner_id=s.owner_id AND v.id=s.verification_id
            WHERE s.owner_id=? AND s.id=?''',(owner,ref['id'])).fetchone()
        content=json.loads(row['content_json']);help_context=content.get('help_context',{})
        result.update(source_type='criterion_verification' if row['stop_condition_confirmed'] else 'saved_attempt',
            verification_status=row['status'],submitted_at=row['created_at'],reported_condition=content.get('evidence_condition','unknown'),
            observed_help_count=len(help_context.get('records',[])),help_coverage=help_context.get('coverage','unknown'))
    elif ref['kind']=='delayed_attempt':
        row=connection.execute('SELECT * FROM learning_delayed_attempt WHERE owner_id=? AND id=?',(owner,ref['id'])).fetchone()
        condition=json.loads(row['condition_json'] or '{}')
        initial=connection.execute("SELECT submitted_at FROM learning_delayed_attempt WHERE owner_id=? AND follow_up_id=? AND phase='initial'",(owner,row['follow_up_id'])).fetchone()
        elapsed=None
        if row['phase']=='followup' and initial and initial[0] and row['submitted_at']:
            elapsed=(datetime.fromisoformat(row['submitted_at'])-datetime.fromisoformat(initial[0])).total_seconds()
        result.update(source_type='delayed_attempt',phase=row['phase'],submitted_at=row['submitted_at'],check_status=row['check_status'],
            actual_interval_seconds=elapsed,reported_help=condition.get('user_report','unknown'),
            observed_help_count=sum(bool(value.get('displayed_at') or value.get('provided_at')) for value in condition.get('observed_views',[])),
            association_basis='user_report',association_description_code='linked_result_to_session')
    elif ref['kind']=='artifact':result['source_type']='saved_artifact_with_user_feedback'
    elif ref['kind']=='feedback':result['source_type']='user_report'
    return result
