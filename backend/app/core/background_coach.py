"""Transactional coach claims, persistent cost reservations and replay projections."""
import json
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from zoneinfo import ZoneInfo
from ..learning_domain import DomainError
from .events import append_event,canonical,digest
from .coach_commands import (SaveCoachSettings,RecordCoachSignal,CorrectCoachSignal,ClaimCoachRun,
    SendCoachRun,FinishCoachRun,CancelCoachRun,PurgeCoachRun,DecideCoachCandidate,SIGNAL_KINDS)

EVENT_TYPES=frozenset({'coach.settings_saved','coach.signal_recorded','coach.signal_corrected',
    'coach.run_claimed','coach.run_sent','coach.run_finished','coach.run_canceled','coach.run_purged','coach.candidate_decided'})
PROJECTION_TABLES=('learning_coach_decision','learning_coach_candidate','learning_coach_run_source',
    'learning_coach_consumed','learning_coach_run','learning_coach_signal','learning_coach_settings')

def owned(c,owner,table,identifier):
    row=c.execute(f'SELECT * FROM {table} WHERE owner_id=? AND id=?',(owner,identifier)).fetchone()
    if row is None: raise DomainError('not_found',404)
    return dict(row)

def settings(c,owner):
    row=c.execute('SELECT * FROM learning_coach_settings WHERE owner_id=?',(owner,)).fetchone()
    return dict(row) if row else dict(owner_id=owner,revision=0,enabled=0,timezone='UTC',
        max_calls_per_session=1,max_calls_per_day=3,cooldown_minutes=30,enabled_position=0)

def day(now,zone):
    return datetime.fromisoformat(now.replace('Z','+00:00')).astimezone(ZoneInfo(zone)).date().isoformat()

def source_key(ref):
    return digest({key:ref.get(key) for key in ('kind','id','revision')})

def budget(c,owner,now,config=None):
    config=config or settings(c,owner)
    today=day(now,config['timezone'])
    rows=[dict(r) for r in c.execute('SELECT sent_at,status,session_ids_json FROM learning_coach_run WHERE owner_id=? AND automatic=1',(owner,))]
    sent=[r for r in rows if r['sent_at']]
    used=sum(day(r['sent_at'],config['timezone'])==today for r in sent)
    reserved=sum(r['status'] in {'queued','running'} and not r['sent_at'] for r in rows)
    last=max((r['sent_at'] for r in sent),default=None)
    next_at=(datetime.fromisoformat(last.replace('Z','+00:00'))+timedelta(minutes=config['cooldown_minutes'])).isoformat().replace('+00:00','Z') if last else None
    counts={}
    for row in rows:
        if row['sent_at'] or row['status'] in {'queued','running'}:
            for session in json.loads(row['session_ids_json']): counts[session]=counts.get(session,0)+1
    return dict(used_today=used,remaining_today=max(0,config['max_calls_per_day']-used-reserved),
        next_allowed_at=next_at,session_counts=counts)

def original(c,owner,run_id,revision=None):
    if c.execute('SELECT 1 FROM learning_coach_tombstone WHERE owner_id=? AND run_id=?',(owner,run_id)).fetchone(): return None
    sql='SELECT * FROM learning_coach_private WHERE owner_id=? AND run_id=?'
    params=[owner,run_id]
    if revision is not None: sql+=' AND revision=?';params.append(revision)
    row=c.execute(sql+' ORDER BY revision DESC LIMIT 1',params).fetchone()
    if row is None or row['purged_at']: return None
    if not row['content_json'] or digest(json.loads(row['content_json']))!=row['content_hash']: raise DomainError('event_integrity_failed')
    return json.loads(row['content_json'])

def erase_private(c,owner,run_id,now):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='learning_coach_private'").fetchone(): return
    c.execute('INSERT OR IGNORE INTO learning_coach_tombstone VALUES(?,?,?)',(owner,run_id,now))
    now=c.execute('SELECT purged_at FROM learning_coach_tombstone WHERE owner_id=? AND run_id=?',(owner,run_id)).fetchone()[0]
    c.execute('UPDATE learning_coach_private SET content_json=NULL,content_hash=NULL,purged_at=COALESCE(purged_at,?) WHERE owner_id=? AND run_id=?',(now,owner,run_id))
    c.execute("UPDATE learning_coach_run SET status='purged',reason='content_purged',purged_at=COALESCE(purged_at,?),provider_snapshot_json='{}' WHERE owner_id=? AND id=?",(now,owner,run_id))
    for candidate in c.execute('SELECT id FROM learning_coach_candidate WHERE owner_id=? AND run_id=?',(owner,run_id)).fetchall():
        requests=c.execute('SELECT id FROM learning_agent_permission_request WHERE owner_id=? AND (request_key=? OR request_key LIKE ?)',(owner,'coach-permission:'+candidate['id'],'coach-permission:'+candidate['id']+':%')).fetchall()
        for request in requests:
            c.execute("UPDATE learning_agent_permission_request SET purpose='内容已清除',status=CASE WHEN status='pending' THEN 'denied' ELSE status END,decision_reason='coach_source_purged' WHERE owner_id=? AND id=?",(owner,request['id']))
            c.execute("UPDATE learning_agent_permission_grant SET status='revoked',revoked_at=COALESCE(revoked_at,?),revoke_reason='coach_source_purged' WHERE owner_id=? AND request_id=? AND status='active'",(now,owner,request['id']))
        for followup in c.execute('SELECT id FROM learning_coach_run WHERE owner_id=? AND permission_candidate_id=? AND purged_at IS NULL',(owner,candidate['id'])).fetchall():
            erase_private(c,owner,followup['id'],now)

def _private(c,event,payload):
    if 'content_hash' not in payload: return
    owner,run_id,rev=event['owner_id'],payload['run_id'],event['aggregate_version']
    old=c.execute('SELECT event_id FROM learning_coach_private WHERE owner_id=? AND run_id=? AND revision=?',(owner,run_id,rev)).fetchone()
    if old:
        if old['event_id']!=event['event_id']: raise DomainError('event_scope_invalid')
        value=original(c,owner,run_id,rev)
        if value is not None and digest(value)!=payload['content_hash']: raise DomainError('event_integrity_failed')
        return
    raw=event.get('_private_content')
    if raw is None or digest(json.loads(raw))!=payload['content_hash']: raise DomainError('event_integrity_failed')
    c.execute('INSERT INTO learning_coach_private VALUES(?,?,?,?,?,?,NULL)',(owner,run_id,rev,event['event_id'],raw,payload['content_hash']))

def _append(c,principal,command_id,key,now,aggregate,identifier,expected,event_type,payload):
    return append_event(c,principal,command_id=command_id,key=key,now=now,aggregate_type=aggregate,
        aggregate_id=identifier,expected_version=expected,event_type=event_type,payload=payload)

def dispatch(core,c,principal,command,command_id,key,now):
    owner=principal.owner_id
    chats=getattr(core,'coach_chats',None)
    from ..background_coach import source_available,input_state,validated_candidates,signal_available,target_available
    if isinstance(command,SaveCoachSettings):
        config=settings(c,owner)
        if config['revision']!=command.expected_revision: raise DomainError('version_conflict')
        values=command.model_dump(exclude={'expected_revision'})
        position=c.execute('SELECT COALESCE(MAX(position),0) FROM learning_event WHERE owner_id=?',(owner,)).fetchone()[0]
        values['enabled_position']=position if command.enabled and not config['enabled'] else config['enabled_position']
        _append(c,principal,command_id,key,now,'coach_config','default',config['revision'],'coach.settings_saved',values)
        if not command.enabled:
            for run in c.execute("SELECT * FROM learning_coach_run WHERE owner_id=? AND status IN ('queued','running') AND automatic=1",(owner,)).fetchall():
                dispatch(core,c,principal,CancelCoachRun(run_id=run['id'],expected_revision=run['revision'],reason='disabled'),command_id,key,now)
        return {'revision':config['revision']+1}
    if isinstance(command,RecordCoachSignal):
        value=dict(command.signal)
        if value.get('kind') not in SIGNAL_KINDS or not signal_available(c,owner,value,chats): raise DomainError('coach_source_unavailable')
        old=c.execute('SELECT id FROM learning_coach_signal WHERE owner_id=? AND (id=? OR (answer_kind=? AND answer_id=?))',(owner,value['id'],value['answer_kind'],value['answer_id'])).fetchone()
        if old: return {'id':old['id']}
        _append(c,principal,command_id,key,now,'coach_signal',value['id'],0,'coach.signal_recorded',value)
        return {'id':value['id'],'revision':1}
    if isinstance(command,CorrectCoachSignal):
        value=owned(c,owner,'learning_coach_signal',command.signal_id)
        if value['revision']!=command.expected_revision: raise DomainError('version_conflict')
        if command.operation=='restore' and not signal_available(c,owner,value,chats): raise DomainError('coach_source_unavailable')
        _append(c,principal,command_id,key,now,'coach_signal',value['id'],value['revision'],'coach.signal_corrected',dict(signal_id=value['id'],operation=command.operation))
        return {'id':value['id'],'revision':value['revision']+1}
    if isinstance(command,ClaimCoachRun):
        config=settings(c,owner);automatic=command.trigger!='manual';inputs=command.inputs
        from ..coach_sources import MAX_INPUT_BYTES,MAX_SOURCES,input_bytes
        if len(inputs['refs'])>MAX_SOURCES or input_bytes(inputs)>MAX_INPUT_BYTES: raise DomainError('coach_input_too_large',422)
        authorization=next((r for r in inputs['refs'] if r['kind']=='permission'),None)
        if bool(command.permission_candidate_id)!=bool(command.permission_request_id): raise DomainError('coach_permission_invalid',403)
        if authorization and (automatic or authorization['id']!=command.permission_request_id or authorization.get('candidate_id')!=command.permission_candidate_id): raise DomainError('coach_permission_invalid',403)
        if command.permission_request_id and not authorization: raise DomainError('coach_permission_invalid',403)
        if command.scope=='plan' and not command.plan_id or command.scope=='global' and command.plan_id: raise DomainError('coach_scope_invalid',422)
        if any(not source_available(c,owner,ref,chats) for ref in inputs['refs']): raise DomainError('coach_source_unavailable')
        if input_state(c,owner,command.scope,command.plan_id,inputs['refs'],chats)!=inputs: raise DomainError('coach_input_changed')
        if c.execute("SELECT 1 FROM learning_coach_run WHERE owner_id=? AND status IN ('queued','running')",(owner,)).fetchone(): raise DomainError('coach_active')
        keys=sorted(source_key(ref) for ref in inputs['refs'] if not authorization or ref['kind']=='permission');batch=digest(keys)
        if not keys: raise DomainError('coach_no_new_signals')
        consumed=[c.execute('SELECT run_id FROM learning_coach_consumed WHERE owner_id=? AND source_key=?',(owner,value)).fetchone() for value in keys]
        if command.retry_run_id:
            old=owned(c,owner,'learning_coach_run',command.retry_run_id)
            if automatic or old['batch_key']!=batch or old['status'] not in {'failed','canceled'}: raise DomainError('coach_retry_invalid')
        elif any(consumed): raise DomainError('coach_batch_consumed')
        sessions=sorted({ref['session_id'] for ref in inputs['refs'] if ref.get('session_id')})
        if automatic:
            if not config['enabled']: raise DomainError('coach_disabled')
            limits=budget(c,owner,now,config)
            if not limits['remaining_today']: raise DomainError('coach_day_limit')
            if limits['next_allowed_at'] and datetime.fromisoformat(limits['next_allowed_at'].replace('Z','+00:00'))>datetime.fromisoformat(now.replace('Z','+00:00')): raise DomainError('coach_cooldown')
            if any(limits['session_counts'].get(session,0)>=config['max_calls_per_session'] for session in sessions): raise DomainError('coach_session_limit')
        payload=dict(run_id=command.run_id,scope=command.scope,plan_id=command.plan_id,trigger=command.trigger,automatic=automatic,
            batch_key=batch,input_hash=digest(inputs),settings_revision=config['revision'],provider_snapshot=command.provider_snapshot,
            session_ids=sessions,reserved_day=day(now,config['timezone']),retry_run_id=command.retry_run_id,
            permission_candidate_id=command.permission_candidate_id,permission_request_id=command.permission_request_id,
            refs=inputs['refs'],content=canonical({'inputs':inputs}))
        _append(c,principal,command_id,key,now,'coach_run',command.run_id,0,'coach.run_claimed',payload)
        return {'run_id':command.run_id,'revision':1}
    if isinstance(command,DecideCoachCandidate):
        value=owned(c,owner,'learning_coach_candidate',command.candidate_id)
        if value['revision']!=command.expected_revision: raise DomainError('version_conflict')
        run=owned(c,owner,'learning_coach_run',value['run_id']);body=original(c,owner,run['id'])
        if command.operation in {'accept','undo'} and (body is None or run['status']!='succeeded'
            or not target_available(c,owner,json.loads(value['target_json']),body['inputs'],chats)): raise DomainError('coach_source_unavailable')
        if command.operation=='undo' and value['status']=='pending' or command.operation!='undo' and value['status']!='pending': raise DomainError('coach_decision_inactive')
        _append(c,principal,command_id,key,now,'coach_candidate',value['id'],value['revision']-1,'coach.candidate_decided',dict(candidate_id=value['id'],operation=command.operation))
        return {'candidate_id':value['id']}
    run=owned(c,owner,'learning_coach_run',command.run_id)
    if run['revision']!=command.expected_revision: raise DomainError('version_conflict')
    if isinstance(command,PurgeCoachRun):
        kind,payload='coach.run_purged',{'run_id':run['id']}
    else:
        if run['status'] not in {'queued','running'}: raise DomainError('coach_run_inactive')
        if isinstance(command,SendCoachRun):
            config=settings(c,owner)
            if run['automatic'] and (not config['enabled'] or config['revision']!=run['settings_revision']): raise DomainError('coach_disabled')
            body=original(c,owner,run['id'])
            if body is None or input_state(c,owner,run['scope'],run['plan_id'],body['inputs']['refs'],chats)!=body['inputs']: raise DomainError('coach_input_changed')
            kind,payload='coach.run_sent',{'run_id':run['id']}
        elif isinstance(command,FinishCoachRun):
            body=original(c,owner,run['id'])
            if command.status=='succeeded':
                config=settings(c,owner)
                if run['automatic'] and (not config['enabled'] or config['revision']!=run['settings_revision']): raise DomainError('coach_disabled')
                if body is None or input_state(c,owner,run['scope'],run['plan_id'],body['inputs']['refs'],chats)!=body['inputs']: raise DomainError('coach_input_changed')
                candidates=validated_candidates(command.candidates,body['inputs'])
            else: candidates=[]
            candidates=[{'id':str(uuid4()),**item} for item in candidates]
            kind='coach.run_finished';payload=dict(run_id=run['id'],status=command.status,reason=command.reason,
                candidates=[dict(id=item['id'],kind=item['target']['kind'],source_keys=[source_key(r) for r in item['source_refs']],target=item['target']) for item in candidates])
            if candidates: payload['content']=canonical({**body,'candidates':candidates})
        elif isinstance(command,CancelCoachRun): kind,payload='coach.run_canceled',dict(run_id=run['id'],reason=command.reason)
        else: raise DomainError('command_unsupported',422)
    event=_append(c,principal,command_id,key,now,'coach_run',run['id'],run['revision'],kind,payload)
    return {'run_id':run['id'],'revision':event['aggregate_version']}

def apply(c,event,payload):
    owner,rev,now,kind=event['owner_id'],event['aggregate_version'],event['occurred_at'],event['event_type']
    _private(c,event,payload)
    if kind=='coach.settings_saved':
        c.execute('INSERT OR REPLACE INTO learning_coach_settings VALUES(?,?,?,?,?,?,?,?,?)',(owner,rev,int(payload['enabled']),payload['timezone'],payload['max_calls_per_session'],payload['max_calls_per_day'],payload['cooldown_minutes'],payload['enabled_position'],now))
    elif kind=='coach.signal_recorded':
        names=('id','kind','plan_id','action_id','delegation_id','session_id','answer_kind','answer_id','source_id','source_revision','start_offset','end_offset')
        p={name:payload.get(name) for name in names}
        c.execute('INSERT INTO learning_coach_signal VALUES(?,?,?, ?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?)',(p['id'],owner,rev,p['kind'],'active',p['plan_id'],p['action_id'],p['delegation_id'],p['session_id'],p['answer_kind'],p['answer_id'],p['source_id'],p['source_revision'],p['start_offset'],p['end_offset'],now,now))
    elif kind=='coach.signal_corrected':
        c.execute('UPDATE learning_coach_signal SET revision=?,status=?,updated_at=? WHERE owner_id=? AND id=?',(rev,'excluded' if payload['operation']=='exclude' else 'active',now,owner,payload['signal_id']))
    elif kind=='coach.run_claimed':
        c.execute('INSERT INTO learning_coach_run VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,NULL,?,NULL,NULL,?,?)',(payload['run_id'],owner,rev,payload['scope'],payload['plan_id'],payload['trigger'],int(payload['automatic']),'queued',payload['batch_key'],payload['input_hash'],payload['settings_revision'],canonical(payload['provider_snapshot']),canonical(payload['session_ids']),payload['reserved_day'],payload.get('retry_run_id'),now,payload.get('permission_candidate_id'),payload.get('permission_request_id')))
        for ref in payload['refs']:
            key=source_key(ref)
            if not payload.get('permission_request_id') or ref['kind']=='permission':
                c.execute('INSERT OR IGNORE INTO learning_coach_consumed VALUES(?,?,?)',(owner,key,payload['run_id']))
            c.execute('INSERT INTO learning_coach_run_source VALUES(?,?,?,?,?,?)',(owner,payload['run_id'],key,ref['kind'],ref['id'],ref.get('revision')))
    elif kind=='coach.run_sent':
        c.execute("UPDATE learning_coach_run SET status='running',revision=?,sent_at=? WHERE owner_id=? AND id=?",(rev,now,owner,payload['run_id']))
    elif kind=='coach.run_finished':
        c.execute('UPDATE learning_coach_run SET revision=?,status=?,reason=?,finished_at=? WHERE owner_id=? AND id=?',(rev,payload['status'],payload.get('reason'),now,owner,payload['run_id']))
        for item in payload.get('candidates',[]):
            c.execute("INSERT INTO learning_coach_candidate VALUES(?,?,?,?,?,'pending',?,?,?,?,NULL)",(item['id'],owner,payload['run_id'],1,item['kind'],rev,canonical(item['source_keys']),canonical(item['target']),now))
    elif kind=='coach.run_canceled':
        c.execute('UPDATE learning_coach_run SET revision=?,status=?,reason=?,finished_at=? WHERE owner_id=? AND id=?',(rev,'failed' if payload['reason']=='interrupted' else 'canceled',payload['reason'],now,owner,payload['run_id']))
    elif kind=='coach.run_purged':
        c.execute('UPDATE learning_coach_run SET revision=? WHERE owner_id=? AND id=?',(rev,owner,payload['run_id']))
        erase_private(c,owner,payload['run_id'],now)
    elif kind=='coach.candidate_decided':
        candidate=owned(c,owner,'learning_coach_candidate',payload['candidate_id'])
        status={'accept':'accepted','reject':'rejected','ignore':'ignored','undo':'pending'}[payload['operation']]
        c.execute('UPDATE learning_coach_candidate SET status=?,revision=?,decided_at=? WHERE owner_id=? AND id=?',(status,rev+1,None if status=='pending' else now,owner,candidate['id']))
        c.execute('INSERT INTO learning_coach_decision VALUES(?,?,?,?,?)',(owner,candidate['id'],rev+1,payload['operation'],now))
    if payload.get('run_id') and c.execute('SELECT 1 FROM learning_coach_tombstone WHERE owner_id=? AND run_id=?',(owner,payload['run_id'])).fetchone(): erase_private(c,owner,payload['run_id'],now)
