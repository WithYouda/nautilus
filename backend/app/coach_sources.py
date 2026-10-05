"""Explicit metadata whitelist and live source checks for bounded coach analysis."""
import json
import hashlib
from urllib.parse import urlencode
from .core.background_coach import source_key
from .goal_lifecycle import OPEN_GOAL_STATUSES

EVENTS={'session.ended','action.completed','delegation.completed','artifact.created','verification.artifact_recorded',
        'feedback.recorded','commitment.item_changed','commitment.confirmed','path.decision_confirmed'}
IMMEDIATE={'separate_work_requested','cannot_continue','permission_or_cost_change'}
MAX_SOURCES=24
MAX_PLANS=4
MAX_ACTIONS=32
MAX_DELEGATIONS=64
MAX_INPUT_BYTES=32768

def input_bytes(inputs):
    return len(json.dumps(inputs,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())

def row(c,table,owner,identifier,field='id'):
    value=c.execute(f'SELECT * FROM {table} WHERE owner_id=? AND {field}=?',(owner,identifier)).fetchone()
    return dict(value) if value else None

def link(c,owner,action):
    value=c.execute('SELECT plan_id FROM learning_action_link WHERE owner_id=? AND action_id=?',(owner,action)).fetchone()
    return value[0] if value else None

def task_link(c,owner,action):
    value=row(c,'learning_action',owner,action)
    return bool(value)

def answer(c,owner,signal,chats=None):
    if signal['answer_kind']=='discussion':
        turn=c.execute('SELECT t.* FROM learning_discussion_turn t JOIN learning_question_discussion d ON d.id=t.discussion_id WHERE d.owner_id=? AND t.id=? AND d.purged_at IS NULL',(owner,signal['answer_id'])).fetchone()
        if not turn or turn['status']!='succeeded': return None
        return {'snapshot':json.loads(turn['provider_snapshot_json'] or '{}'),'text':turn['user_content'] or '',
                'source_id':turn['id']}
    if chats is None: return None
    value=chats.database.fetchone('''SELECT r.config_snapshot_json,m.content,r.request_message_id FROM ai_run r
        JOIN message m ON m.id=r.request_message_id JOIN conversation q ON q.id=r.conversation_id
        WHERE r.identity_id=? AND r.response_message_id=? AND r.status='succeeded' AND q.deleted_at IS NULL''',(owner,signal['answer_id']))
    if value is None: return None
    return {'snapshot':json.loads(value['config_snapshot_json'] or '{}'),'text':value['content'],
            'source_id':value['request_message_id']}

def signal_available(c,owner,value,chats=None):
    if not task_link(c,owner,value['action_id']): return False
    source=answer(c,owner,value,chats)
    if source is None or source['snapshot'].get('branch_origin') or source['source_id']!=value['source_id']: return False
    teaching=source['snapshot'].get('teaching') or {}
    context=teaching.get('coach_context') or {}
    if any(context.get(k)!=value.get(k) for k in ('plan_id','action_id','delegation_id','session_id')): return False
    signal=teaching.get('assignment_signal')
    if not signal or signal.get('id')!=value['id'] or signal.get('kind')!=value['kind']: return False
    start,end=value['start_offset'],value['end_offset']
    if not 0<=start<end<=len(source['text']): return False
    if value['kind']=='repeated_blocker':
        reply=source['snapshot'].get('reply') or {}
        if reply.get('retry_of') or reply.get('edit_of'): return False
        attempt=(teaching.get('result') or {}).get('attempt')
        if not attempt or not attempt.get('is_attempt',True) or attempt.get('needs_help') is not True: return False
        corrections=source['snapshot'].get('teaching_attempt_corrections') or []
        if corrections and (not corrections[-1]['is_attempt'] or corrections[-1].get('needs_help',attempt.get('needs_help')) is not True): return False
    return True

def source_summary(c,owner,ref,chats=None):
    kind,identifier=ref['kind'],ref['id']
    if kind=='permission':
        from .coach_permissions import approved
        return approved(c,owner,ref,chats)
    if kind=='artifact':
        value=c.execute('''SELECT r.content_hash,r.purged_at,a.visibility,a.evidence_status,a.content_version,d.action_id
            FROM learning_raw_artifact r JOIN learning_artifact a ON a.owner_id=r.owner_id AND a.id=r.artifact_id
            JOIN learning_session s ON s.owner_id=r.owner_id AND s.id=r.session_id
            JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
            WHERE r.owner_id=? AND r.artifact_id=? AND r.content_version=?''',(owner,identifier,ref['revision'])).fetchone()
        if not value or value['purged_at'] or value['visibility']!='visible' or value['evidence_status']!='eligible' or value['content_version']!=ref['revision'] or value['action_id']!=ref['action_id']: return None
        return {'content_hash':value['content_hash'],'action_id':value['action_id']}
    if kind=='event':
        value=row(c,'learning_event',owner,identifier,'event_id')
        if value is None or value['aggregate_version']!=ref['revision'] or value['event_type'] not in EVENTS: return None
        payload=json.loads(value['payload_json']);action=ref.get('action_id')
        if action and not task_link(c,owner,action): return None
        if value['event_type'] in {'artifact.created','verification.artifact_recorded'}:
            art=payload.get('artifact_id') or payload.get('id')
            current=row(c,'learning_artifact',owner,art)
            if not current or current['visibility']!='visible' or current['evidence_status']!='eligible' or current['content_version']!=payload.get('content_version',1): return None
            raw=c.execute('SELECT purged_at FROM learning_raw_artifact WHERE owner_id=? AND artifact_id=? AND content_version=?',(owner,art,current['content_version'])).fetchone()
            if not raw or raw['purged_at']: return None
        elif value['event_type']=='feedback.recorded':
            feedback=row(c,'learning_session_feedback',owner,payload.get('session_id') or value['aggregate_id'])
            if not feedback or feedback['purged_at'] or feedback['revision']!=value['aggregate_version']: return None
        elif value['event_type']=='commitment.item_changed':
            item=row(c,'learning_commitment_item',owner,payload.get('item_id'))
            if not item: return None
            latest=c.execute("SELECT event_id FROM learning_event WHERE owner_id=? AND event_type='commitment.item_changed' AND json_extract(payload_json,'$.item_id')=? ORDER BY position DESC LIMIT 1",(owner,item['id'])).fetchone()
            if not latest or latest[0]!=identifier: return None
        return {'event_type':value['event_type'],'occurred_at':value['occurred_at']}
    if kind=='answer':
        value=row(c,'learning_coach_signal',owner,identifier)
        if not value or value['revision']!=ref['revision'] or value['status']!='active' or not signal_available(c,owner,value,chats): return None
        if value['kind']=='repeated_blocker':
            others=[dict(r) for r in c.execute("SELECT * FROM learning_coach_signal WHERE owner_id=? AND action_id=? AND kind='repeated_blocker' AND status='active'",(owner,value['action_id']))]
            sessions={r['session_id'] for r in others if r['session_id'] and signal_available(c,owner,r,chats)}
            if len(sessions)<2: return None
        return {'signal_kind':value['kind'],'immediate':value['kind'] in IMMEDIATE}
    if kind=='claim':
        value=row(c,'learning_evidence_claim',owner,identifier)
        if not value or value['status']!='candidate': return None
        art=row(c,'learning_artifact',owner,value['artifact_id'])
        if not art or art['visibility']!='visible' or art['evidence_status']!='eligible' or art['content_version']!=value['content_version']: return None
        raw=c.execute('SELECT purged_at FROM learning_raw_artifact WHERE owner_id=? AND artifact_id=? AND content_version=?',(owner,art['id'],art['content_version'])).fetchone()
        if not raw or raw['purged_at']: return None
        return {key:value[key] for key in ('status','stance','source','criterion_id','dimension_id')}
    if kind=='delayed_follow_up':
        value=row(c,'learning_delayed_follow_up',owner,identifier)
        if not value or value['purged_at'] or value['status']!='scheduled' or not value['due_at']: return None
        revision=len(json.loads(value['history_json'] or '[]'))+1
        if revision!=ref['revision']: return None
        art=row(c,'learning_artifact',owner,value['source_artifact_id'])
        raw=c.execute('SELECT purged_at FROM learning_raw_artifact WHERE owner_id=? AND artifact_id=? AND content_version=?',(owner,value['source_artifact_id'],value['source_content_version'])).fetchone()
        if not art or art['visibility']!='visible' or not raw or raw['purged_at']: return None
        return {'status':value['status'],'due_at':value['due_at'],'timezone':value['timezone']}
    if kind=='revisit':
        value=row(c,'learning_revisit_item',owner,identifier)
        if not value or value['status']!='pending': return None
        if value.get('claim_id'):
            claim=row(c,'learning_evidence_claim',owner,value['claim_id'])
            if not claim or claim['status']=='invalidated': return None
        return {key:value[key] for key in ('source_kind','source_id','reason','due_at','status')}
    return None

def source_available(c,owner,ref,chats=None):
    return source_summary(c,owner,ref,chats) is not None

def target(kind,plan_id=None,action_id=None,delegation_id=None,object_id=None,reference_kind=None,claim_id=None):
    params={'view':'plans','plan':plan_id,'plan_view':'tasks'}
    labels={'task':'查看任务','evidence_review':'查看依据','delayed_follow_up':'查看回访','path_review':'调整路线',
            'commitment_review':'核对安排','new_task':'单独安排','permission_review':'查看读取权限'}
    if kind=='task': params['action']=action_id
    elif kind=='evidence_review':
        if object_id:
            params={'view':'home','evidence_action':action_id,
                'review_claim':object_id if reference_kind=='claim' else claim_id,
                'review_revisit':object_id if reference_kind=='revisit' else None}
            labels['evidence_review']='复核这条依据' if reference_kind=='claim' else '核对这项回访' if claim_id else '查看这项回访'
        else: params={'view':'records','record':delegation_id}
    elif kind=='delayed_follow_up': params={'view':'home','follow_up':object_id}
    elif kind in {'path_review','commitment_review'}: params['plan_view']='path' if kind=='path_review' else 'commitments'
    elif kind=='new_task': params['new_task']='1'
    elif kind=='permission_review': params={'view':'home','permission_action':action_id}
    href='?'+urlencode({k:v for k,v in params.items() if v is not None})+('#coach-permissions' if kind=='permission_review' else '#coach-evidence' if kind=='evidence_review' and object_id else '')
    return dict(kind=kind,plan_id=plan_id,action_id=action_id,delegation_id=delegation_id,object_id=object_id,href=href,label=labels[kind])

def input_state(c,owner,scope,plan_id,refs,chats=None):
    actions=[];targets=[]
    sql='''SELECT a.id,a.title,a.status,a.version,l.plan_id FROM learning_action a
        LEFT JOIN learning_action_link l ON l.owner_id=a.owner_id AND l.action_id=a.id
        WHERE a.owner_id=? AND NOT EXISTS(SELECT 1 FROM learning_action_removal x WHERE x.owner_id=a.owner_id AND x.action_id=a.id)'''
    params=[owner]
    source_plans=sorted({ref['plan_id'] for ref in refs if ref.get('plan_id')})[:MAX_PLANS]
    source_actions={ref['action_id'] for ref in refs if ref.get('action_id')}
    if scope=='plan': sql+=' AND l.plan_id=?';params.append(plan_id)
    elif source_plans: sql+=' AND l.plan_id IN ('+','.join('?' for _ in source_plans)+')';params.extend(source_plans)
    else: sql+=' AND a.id IN ('+','.join('?' for _ in source_actions)+')' if source_actions else ' AND 0';params.extend(sorted(source_actions))
    available=[dict(r) for r in c.execute(sql+' ORDER BY a.id',params)]
    available.sort(key=lambda a:(a['id'] not in source_actions,a['status']!='open',a['id']))
    remaining=MAX_DELEGATIONS
    for action in available[:MAX_ACTIONS]:
        action['delegations']=[dict(r) for r in c.execute('SELECT id,status,contract_version,criterion_id,outcome_id FROM learning_delegation WHERE owner_id=? AND action_id=? ORDER BY id LIMIT ?',(owner,action['id'],remaining))]
        remaining-=len(action['delegations'])
        p=row(c,'learning_plan',owner,action['plan_id']) if action['plan_id'] else None
        g=row(c,'learning_goal',owner,p['goal_id']) if p and p['goal_id'] else None
        action['plan_status']=p['status'] if p else None;action['goal_status']=g['status'] if g else None
        action['goal_version']=g['version'] if g else None
        organization=c.execute('SELECT revision FROM learning_plan_organization WHERE owner_id=? AND plan_id=?',(owner,action['plan_id'])).fetchone() if p else None
        action['plan_revision']=organization[0] if organization else 0
        writable=(not p or p['status']=='active') and (not g or g['status'] in OPEN_GOAL_STATUSES)
        actions.append(action)
        for delegation in action['delegations']:
            if writable and action['status']=='open' and delegation['status'] in {'ready','active'}:
                targets.append(target('task',action['plan_id'],action['id'],delegation['id']))
            targets.append(target('evidence_review',action['plan_id'],action['id'],delegation['id']))
        has_artifact=c.execute('''SELECT 1 FROM learning_raw_artifact r JOIN learning_artifact a ON a.owner_id=r.owner_id AND a.id=r.artifact_id AND a.content_version=r.content_version
            JOIN learning_session s ON s.owner_id=r.owner_id AND s.id=r.session_id JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
            WHERE r.owner_id=? AND d.action_id=? AND a.visibility='visible' AND a.evidence_status='eligible' AND r.purged_at IS NULL LIMIT 1''',(owner,action['id'])).fetchone()
        if has_artifact: targets.append(target('permission_review',action['plan_id'],action['id']))
    plans=sorted({a['plan_id'] for a in actions if a['plan_id']})
    routes=[];arrangements=[];feedback=[]
    for identifier in plans:
        p=row(c,'learning_plan',owner,identifier)
        g=row(c,'learning_goal',owner,p['goal_id']) if p and p['goal_id'] else None
        if p and p['status']=='active' and (not g or g['status'] in OPEN_GOAL_STATUSES):
            targets.extend(target(kind,identifier) for kind in ('path_review','commitment_review','new_task'))
        path=c.execute('SELECT adopted_version_id,current_node_id,revision,status FROM learning_plan_path_state WHERE owner_id=? AND plan_id=?',(owner,identifier)).fetchone()
        if path:
            route={'plan_id':identifier,**dict(path)}
            version=row(c,'learning_path_version',owner,path['adopted_version_id']) if path['adopted_version_id'] else None
            if version and not version['purged_at']:
                data=json.loads(version['data_json']);nodes=sorted(data['nodes'],key=lambda n:(n['id']!=path['current_node_id'],not bool(set(n.get('action_ids',[]))&source_actions),n['id']))[:12]
                identifiers={n['id'] for n in nodes}
                route['topology']=dict(nodes=[{**n,'action_ids':n.get('action_ids',[])[:12],'outcome_ids':n.get('outcome_ids',[])[:12]} for n in nodes],
                    edges=[e for e in data['edges'] if e['source'] in identifiers and e['target'] in identifiers][:24])
                route['topology_hash']=hashlib.sha256(version['data_json'].encode()).hexdigest()
                route['topology_limited']=len(nodes)<len(data['nodes']) or len(route['topology']['edges'])<len(data['edges'])
            routes.append(route)
        for item in c.execute('SELECT id,node_id,action_id,delegation_id,status,future_due_at,future_timezone FROM learning_commitment_item WHERE owner_id=? AND plan_id=? ORDER BY id LIMIT 8',(owner,identifier)): arrangements.append(dict(item))
    summaries=[]
    for ref in refs:
        summary=source_summary(c,owner,ref,chats)
        if summary is None: summary={'unavailable':True}
        summaries.append({'source_key':source_key(ref),**summary})
        if (ref['kind']=='revisit' or ref['kind']=='claim' and ref.get('action_id')) and 'unavailable' not in summary:
            revisit=row(c,'learning_revisit_item',owner,ref['id']) if ref['kind']=='revisit' else None
            targets.append(target('evidence_review',ref.get('plan_id'),ref['action_id'],ref.get('delegation_id'),ref['id'],
                ref['kind'],revisit['claim_id'] if revisit else None))
        if ref['kind']=='delayed_follow_up' and 'unavailable' not in summary: targets.append(target('delayed_follow_up',ref.get('plan_id'),ref.get('action_id'),ref.get('delegation_id'),ref['id']))
        if ref.get('session_id'):
            value=row(c,'learning_session_feedback',owner,ref['session_id'])
            if value and not value['purged_at']:
                data=json.loads(value['data_json'])
                feedback.append({'id':value['id'],'revision':value['revision'],**{key:data.get(key) for key in ('purpose','actual_min_minutes','actual_max_minutes','grain','pace','method_feedback','progress','activity')}})
    result=dict(schema_version=1,scope=scope,plan_id=plan_id,refs=refs,signals=summaries,actions=actions,routes=routes,arrangements=arrangements,
        feedback=sorted({f['id']:f for f in feedback}.values(),key=lambda x:x['id']),targets=targets)
    permission=next((r for r in refs if r['kind']=='permission'),None)
    if permission:
        from .coach_permissions import context
        result['authorization']=context(c,owner,permission,chats)
        result['targets']=[t for t in targets if t['kind']!='permission_review']
    # Extra navigation context is optional. Preserve selected source actions,
    # then trim only other tasks instead of making a busy plan permanently too large.
    while input_bytes(result)>MAX_INPUT_BYTES:
        extra=next((a for a in reversed(result['actions']) if a['id'] not in source_actions),None)
        if extra is None: break
        result['actions'].remove(extra)
        result['targets']=[t for t in result['targets'] if t.get('action_id')!=extra['id']]
    return result

def target_available(c,owner,destination,inputs,chats=None):
    if any(not source_available(c,owner,r,chats) for r in inputs['refs']): return False
    if destination['kind']!='evidence_review':
        return input_state(c,owner,inputs['scope'],inputs['plan_id'],inputs['refs'],chats)==inputs
    if destination.get('object_id'):
        ref=next((r for r in inputs['refs'] if r['id']==destination['object_id'] and r['kind'] in {'claim','revisit'}),None)
        if not ref or ref.get('action_id')!=destination.get('action_id') or ref.get('delegation_id')!=destination.get('delegation_id'): return False
        if ref['kind']=='revisit' and not ref.get('action_id'): return source_available(c,owner,ref,chats)
    action=row(c,'learning_action',owner,destination.get('action_id'))
    delegation=row(c,'learning_delegation',owner,destination.get('delegation_id'))
    if not action or not delegation or delegation['action_id']!=action['id']: return False
    return True

def collect(c,owner,scope,plan_id,now,chats=None,excluded_sessions=frozenset()):
    refs=[]
    def add(kind,identifier,revision,action=None,session=None,delegation=None,plan=None):
        if session in excluded_sessions: return
        ref=dict(kind=kind,id=identifier,revision=revision,action_id=action,session_id=session,delegation_id=delegation,plan_id=plan or (link(c,owner,action) if action else None))
        if scope=='plan' and ref['plan_id']!=plan_id: return
        if c.execute('SELECT 1 FROM learning_coach_consumed WHERE owner_id=? AND source_key=?',(owner,source_key(ref))).fetchone(): return
        if source_available(c,owner,ref,chats): refs.append(ref)
    event_sql='''SELECT e.* FROM learning_event e WHERE e.owner_id=? AND e.event_type IN ('''+','.join('?' for _ in EVENTS)+''') AND NOT EXISTS (
        SELECT 1 FROM learning_coach_run_source x JOIN learning_coach_consumed m ON m.owner_id=x.owner_id AND m.source_key=x.source_key
        WHERE x.owner_id=e.owner_id AND x.source_kind='event' AND x.source_id=e.event_id AND x.source_revision=e.aggregate_version)
        ORDER BY e.position DESC'''
    for value in c.execute(event_sql,(owner,*sorted(EVENTS))):
        if len(refs)>=MAX_SOURCES*2: break
        payload=json.loads(value['payload_json']);session=payload.get('session_id') or (payload.get('id') if value['event_type']=='feedback.recorded' else None)
        action=value['aggregate_id'] if value['aggregate_type']=='action' else payload.get('action_id')
        delegation=payload.get('delegation_id')
        if not action and session:
            s=row(c,'learning_session',owner,session);d=row(c,'learning_delegation',owner,s['delegation_id']) if s else None
            action=d['action_id'] if d else None
            delegation=d['id'] if d else None
        plan=payload.get('plan_id') or (value['aggregate_id'] if value['aggregate_type'] in {'path','commitment'} else None)
        add('event',value['event_id'],value['aggregate_version'],action,session,delegation,plan=plan)
    for value in c.execute("SELECT * FROM learning_coach_signal WHERE owner_id=? AND status='active' ORDER BY id",(owner,)):
        if len(refs)>=MAX_SOURCES*3: break
        add('answer',value['id'],value['revision'],value['action_id'],value['session_id'],value['delegation_id'],value['plan_id'])
    for value in c.execute("SELECT x.*,d.action_id,d.id AS delegation_id,s.id AS session_id FROM learning_evidence_claim x JOIN learning_raw_artifact r ON r.owner_id=x.owner_id AND r.artifact_id=x.artifact_id AND r.content_version=x.content_version JOIN learning_session s ON s.owner_id=r.owner_id AND s.id=r.session_id JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id WHERE x.owner_id=? AND x.status='candidate' ORDER BY x.id",(owner,)):
        if len(refs)>=MAX_SOURCES*4: break
        add('claim',value['id'],value['content_version'],value['action_id'],value['session_id'],value['delegation_id'])
    for value in c.execute("SELECT f.*,d.action_id FROM learning_delayed_follow_up f JOIN learning_delegation d ON d.owner_id=f.owner_id AND d.id=f.delegation_id WHERE f.owner_id=? AND f.status='scheduled' AND f.due_at<=? ORDER BY f.id",(owner,now)):
        if len(refs)>=MAX_SOURCES*5: break
        add('delayed_follow_up',value['id'],len(json.loads(value['history_json'] or '[]'))+1,value['action_id'],delegation=value['delegation_id'])
    for value in c.execute("SELECT * FROM learning_revisit_item WHERE owner_id=? AND status='pending' AND due_at<=? ORDER BY id",(owner,now)):
        if len(refs)>=MAX_SOURCES*6: break
        action=session=delegation=None
        if value['claim_id']:
            position=c.execute('''SELECT d.action_id,d.id AS delegation_id,s.id AS session_id FROM learning_evidence_claim x
                JOIN learning_raw_artifact r ON r.owner_id=x.owner_id AND r.artifact_id=x.artifact_id AND r.content_version=x.content_version
                JOIN learning_session s ON s.owner_id=r.owner_id AND s.id=r.session_id
                JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id WHERE x.owner_id=? AND x.id=?''',(owner,value['claim_id'])).fetchone()
            if position: action,delegation,session=position['action_id'],position['delegation_id'],position['session_id']
        elif value['criterion_id']:
            positions=c.execute('SELECT action_id,id FROM learning_delegation WHERE owner_id=? AND criterion_id=?',(owner,value['criterion_id'])).fetchall()
            if len(positions)==1: action,delegation=positions[0]['action_id'],positions[0]['id']
        add('revisit',value['id'],1,action,session,delegation)
    priority={'delayed_follow_up':0,'answer':1,'revisit':2,'claim':3,'event':4}
    chosen=[];plans=set()
    for ref in sorted(refs,key=lambda r:(priority[r['kind']],source_key(r))):
        if ref.get('plan_id') and ref['plan_id'] not in plans and len(plans)>=MAX_PLANS: continue
        if ref.get('plan_id'): plans.add(ref['plan_id'])
        chosen.append(ref)
        if len(chosen)>=MAX_SOURCES: break
    return sorted(chosen,key=source_key)
