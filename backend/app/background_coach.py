"""Event-gated, metadata-only coach proposals using the existing Provider runtime."""
import asyncio
import json
from datetime import datetime,timezone
from uuid import uuid4
from pydantic import BaseModel,ConfigDict,Field,ValidationError
from .learning_domain import DomainError,Principal
from .conversations import ConversationError
from .providers import build_provider,ProviderError
from .provider_network import ProviderDiagnostics
from .core.events import digest
from .core.background_coach import settings,budget,original,owned,source_key
from .core.coach_commands import (SaveCoachSettings,RecordCoachSignal,CorrectCoachSignal,ClaimCoachRun,SendCoachRun,
    FinishCoachRun,CancelCoachRun,PurgeCoachRun,DecideCoachCandidate)
from .coach_sources import (input_state,source_available,source_summary,signal_available,collect,target,IMMEDIATE,link,MAX_INPUT_BYTES,input_bytes,target_available)
from .managed_purge import ManagedPurge
from .core.learning import utc_timestamp

MAX_OUTPUT_TOKENS=8192
GATES={'coach_disabled','coach_active','coach_no_new_signals','coach_day_limit','coach_session_limit','coach_cooldown','coach_batch_consumed'}

class CandidateProposal(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind: str | None = None
    title: str = Field(min_length=1,max_length=160)
    explanation: str = Field(min_length=1,max_length=1200)
    unknowns: list[str] = Field(default_factory=list,max_length=8)
    source_refs: list[dict] = Field(min_length=1,max_length=64)
    target: dict
    access_request: dict | None = None

class Proposal(BaseModel):
    model_config=ConfigDict(extra='forbid')
    candidates: list[CandidateProposal] = Field(max_length=8)

def validated_candidates(items,inputs):
    result=[];seen=set();refs={source_key(r):r for r in inputs['refs']}
    names=('kind','plan_id','action_id','delegation_id','object_id')
    for value in items:
        item=CandidateProposal.model_validate(value).model_dump()
        proposal=item['target']
        if not set(proposal)<=set(names): raise DomainError('coach_target_out_of_scope',422)
        chosen=next((t for t in inputs['targets'] if all(t.get(key)==proposal.get(key) for key in names)),None)
        if chosen is None: raise DomainError('coach_target_out_of_scope',422)
        if chosen['kind']=='permission_review':
            access=item['access_request']
            if (not isinstance(access,dict) or set(access)!={'purpose','alternative'} or any(not isinstance(access[k],str) or not 1<=len(access[k])<=500 for k in ('purpose','alternative'))):
                raise DomainError('coach_permission_purpose_required',422)
        elif item['access_request'] is not None: raise DomainError('coach_permission_out_of_scope',422)
        selected=[]
        for ref in item['source_refs']:
            key=source_key(ref)
            if key not in refs: raise DomainError('coach_source_out_of_scope',422)
            selected.append(refs[key])
        fingerprint=digest([chosen,[source_key(r) for r in selected]])
        if fingerprint in seen: continue
        seen.add(fingerprint)
        result.append({**item,'target':chosen,'source_refs':selected})
    return result

def messages(inputs):
    return [{'role':'system','content':(
        '为Nautilus用户作一次后台学习复盘，只返回JSON {"candidates":[...]}。'
        '只根据所给最小结构摘要判断哪些下一步真正值得提醒。可以没有候选；不要为了填满生成建议。'
        '每项含title、explanation、unknowns、source_refs、target；解释简短、具体，区分本人报告、AI观察、已审核证据及未知。'
        'target只能从inputs.targets选择，输出其kind/plan_id/action_id/delegation_id/object_id五字段，不输出href/label。'
        'source_refs只能引用inputs.refs中的kind/id/revision，可复制完整ref；不得造ID、原话、数据或费用事实。'
        'permission_review仅在该任务现有产出原文能支持一个明确缺失判断时使用，额外access_request={"purpose":"本次具体判断为什么需要产出原文","alternative":"拒绝后由本人概述或在原任务核对的办法"}；其余为null。只申请当前task的full_text，300秒，许可不扩大工具权限。'
        '不读取原始消息、资料、证据statement、反馈notes或私有路径标题，不猜这些未授权内容。'
        '根据真实来源解释任务恢复、待复核依据、跨会话重复阻塞、到期回访、路线/近期安排调整或单独安排。'
        'source_kind与status是依据，不是掌握证明；会话跨度不是有效投入，重复阻塞不等于用户能力不足。'
        '建议仅打开现有入口；不能创建/确认正式委托、路线、安排、成果或个人偏好，不能自动开始学习。'
        '不足时明确仍未知，可建议权限入口但不得扩大读取或启用工具。不得输出完整D2草案。')},
        {'role':'user','content':json.dumps(inputs,ensure_ascii=False,sort_keys=True,separators=(',',':'))}]

class BackgroundCoach:
    def __init__(self,learning,chats,*,transport=None,provider_slots=None,clock=utc_timestamp):
        self.learning,self.chats,self.db=learning,chats,learning.database
        self.transport,self.slots,self.clock=transport,provider_slots or asyncio.Semaphore(4),clock
        self.tasks={};self.monitor=None;self._stopping=False
        self.learning.core.coach_chats=chats
        self.boundary_position=self.db.fetchone('SELECT COALESCE(MAX(position),0) FROM learning_event')[0]

    def _owner(self,identity): return self.learning.principal(identity).owner_id
    def _scope(self,c,owner,scope,plan_id):
        if scope not in {'global','plan'} or (scope=='global' and plan_id is not None) or (scope=='plan' and not plan_id): raise DomainError('coach_scope_invalid',422)
        if plan_id: owned(c,owner,'learning_plan',plan_id)

    def get_settings(self,identity):
        owner=self._owner(identity)
        with self.db.transaction() as c: return self._settings(c,owner)

    def _settings(self,c,owner):
        value=settings(c,owner)
        return {key:(bool(value[key]) if key=='enabled' else value[key]) for key in
            ('revision','enabled','timezone','max_calls_per_session','max_calls_per_day','cooldown_minutes')}

    async def save_settings(self,identity,payload,key):
        self.learning.core.execute(self.learning.principal(identity),SaveCoachSettings(**payload),key)
        for identifier,task in list(self.tasks.items()):
            run=self.db.fetchone('SELECT status FROM learning_coach_run WHERE owner_id=? AND id=?',(identity['id'],identifier))
            if run and run['status'] not in {'queued','running'}: task.cancel()
        return self.get_settings(identity)

    def _source(self,c,owner,ref):
        labels={'event':'学习状态变化','answer':'当前回答中的委托信号','claim':'待复核依据','revisit':'待回访事项','delayed_follow_up':'已安排回访','permission':'本次读取授权','artifact':'本次授权产出'}
        href=None
        if ref.get('delegation_id'): href=target('evidence_review',ref.get('plan_id'),ref.get('action_id'),ref['delegation_id'])['href']
        elif ref.get('plan_id'): href=target('task',ref['plan_id'],ref.get('action_id'))['href']
        return dict(kind=ref['kind'],id=ref['id'],revision=ref.get('revision'),label=labels.get(ref['kind'],'既有学习记录'),
            available=source_available(c,owner,ref,self.chats),href=href)

    def _run(self,c,owner,value):
        return {key:value[key] for key in ('id','revision','scope','plan_id','status','reason','created_at','finished_at')} | {
            'provider_snapshot':json.loads(value['provider_snapshot_json']) if not value['purged_at'] else None,
            'content_available':original(c,owner,value['id']) is not None,
            'permission_candidate_id':value['permission_candidate_id'],'permission_request_id':value['permission_request_id']}

    def _candidate(self,c,owner,value):
        run=owned(c,owner,'learning_coach_run',value['run_id']);body=original(c,owner,run['id'])
        private=next((item for item in (body or {}).get('candidates',[]) if item.get('id')==value['id']),None)
        refs=(body or {}).get('inputs',{}).get('refs',[])
        available=bool(private and run['status']=='succeeded' and target_available(c,owner,json.loads(value['target_json']),body['inputs'],self.chats))
        sources=[self._source(c,owner,r) for r in refs if source_key(r) in json.loads(value['source_keys_json'])]
        destination=json.loads(value['target_json']) if available else None
        if destination and destination['kind']=='permission_review':
            from .coach_permissions import request_fields
            destination['permission_request']=request_fields(c,owner,value['id'])
        return {key:value[key] for key in ('id','run_id','revision','created_at','decided_at')} | {
            'scope':run['scope'],'plan_id':json.loads(value['target_json']).get('plan_id') or run['plan_id'],'status':value['status'] if available else 'unavailable',
            'title':private['title'] if private else None,'explanation':private['explanation'] if private else None,
            'unknowns':private.get('unknowns',[]) if private else [],'target':destination,
            'sources':sources,'content_available':bool(private)}

    def candidate(self,identity,identifier):
        owner=self._owner(identity)
        with self.db.transaction() as c: return self._candidate(c,owner,owned(c,owner,'learning_coach_candidate',identifier))

    def view(self,identity,scope='global',plan_id=None):
        owner=self._owner(identity);self.sync_signals(owner)
        with self.db.transaction() as c:
            self._scope(c,owner,scope,plan_id)
            runs=[dict(r) for r in c.execute('SELECT * FROM learning_coach_run WHERE owner_id=? ORDER BY created_at DESC,rowid DESC LIMIT 100',(owner,))]
            candidates=[]
            for run in runs:
                for r in c.execute('SELECT * FROM learning_coach_candidate WHERE owner_id=? AND run_id=? ORDER BY created_at,id',(owner,run['id'])):
                    value=self._candidate(c,owner,dict(r))
                    if scope=='global' or value['plan_id']==plan_id: candidates.append(value)
            limits=budget(c,owner,self.clock());limits.pop('session_counts')
            return dict(settings=self._settings(c,owner),candidates=[x for x in candidates if x['status']=='pending'],
                history=[x for x in candidates if x['status']!='pending'][:100],
                active_run=next((self._run(c,owner,r) for r in runs if r['status'] in {'queued','running'}),None),
                latest_run=next((self._run(c,owner,r) for r in runs if scope=='global' or r['plan_id']==plan_id or any(x['run_id']==r['id'] for x in candidates)),None),
                pending_signals=len(collect(c,owner,scope,plan_id,self.clock(),self.chats)),budget=limits)

    def run(self,identity,identifier):
        owner=self._owner(identity)
        with self.db.transaction() as c:
            value=owned(c,owner,'learning_coach_run',identifier);body=original(c,owner,identifier)
            return dict(run=self._run(c,owner,value),candidates=[self._candidate(c,owner,dict(r)) for r in c.execute('SELECT * FROM learning_coach_candidate WHERE owner_id=? AND run_id=? ORDER BY id',(owner,identifier))],inputs=body.get('inputs') if body else None)

    async def check(self,identity,payload,key):
        owner=self._owner(identity);scope=payload['scope'];plan_id=payload.get('plan_id');trigger=payload['trigger'];retry=payload.get('retry_run_id')
        permission_candidate=payload.get('permission_candidate_id');permission_request=payload.get('permission_request_id')
        if bool(permission_candidate)!=bool(permission_request) or permission_request and trigger!='manual': raise DomainError('coach_permission_invalid',403)
        self.sync_signals(owner)
        previous=self.db.fetchone('SELECT command_type,result_json FROM learning_command WHERE owner_id=? AND actor_id=? AND idempotency_key=?',(owner,owner,key))
        if previous:
            result=json.loads(previous['result_json'])
            if previous['command_type']!='ClaimCoachRun': raise DomainError('idempotency_conflict')
            run=owned(self.db.connection,owner,'learning_coach_run',result['run_id'])
            if (run['scope'],run['plan_id'],run['trigger'],run['retry_run_id'],run['permission_candidate_id'],run['permission_request_id'])!=(scope,plan_id,trigger,retry,permission_candidate,permission_request): raise DomainError('idempotency_conflict')
            return dict(view=self.view(identity,scope,plan_id),run=self.run(identity,run['id'])['run'],reason=None)
        if permission_request:
            from .agent_runtime import AgentRuntime
            candidate=self.candidate(identity,permission_candidate)
            with self.db.transaction() as c:
                parent=owned(c,owner,'learning_coach_run',candidate['run_id'])
            if parent['scope']!=scope or parent['plan_id']!=plan_id or candidate['target'] is None or candidate['target']['kind']!='permission_review': raise DomainError('coach_permission_invalid',403)
            approved_context=AgentRuntime(self.learning).agent_context(identity,candidate['target']['action_id'])
            if approved_context['authorization']['status']!='approved' or approved_context['authorization']['request_id']!=permission_request or approved_context['authorization']['content_granularity']!='full_text': raise DomainError('coach_permission_invalid',403)
            if not retry:
                existing=self.db.fetchone('''SELECT * FROM learning_coach_run WHERE owner_id=? AND permission_candidate_id=?
                    AND permission_request_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1''',(owner,permission_candidate,permission_request))
                if existing:
                    if existing['scope']!=scope or existing['plan_id']!=plan_id: raise DomainError('idempotency_conflict')
                    return dict(view=self.view(identity,scope,plan_id),run=self.run(identity,existing['id'])['run'],reason='coach_batch_consumed')
        with self.db.transaction() as c:
            self._scope(c,owner,scope,plan_id);config=settings(c,owner)
            if trigger!='manual' and not config['enabled']: return_value='coach_disabled';refs=[]
            elif c.execute("SELECT 1 FROM learning_coach_run WHERE owner_id=? AND status IN ('queued','running')",(owner,)).fetchone(): return_value='coach_active';refs=[]
            elif retry:
                old=owned(c,owner,'learning_coach_run',retry);body=original(c,owner,retry)
                if trigger!='manual' or old['scope']!=scope or old['plan_id']!=plan_id or old['status'] not in {'failed','canceled'} or body is None or (old['permission_candidate_id'],old['permission_request_id'])!=(permission_candidate,permission_request): raise DomainError('coach_retry_invalid')
                refs=body['inputs']['refs'];return_value=None
            elif permission_request:
                from .coach_permissions import context
                action=candidate['target']['action_id']
                ref=dict(kind='permission',id=permission_request,revision=1,candidate_id=permission_candidate,action_id=action,
                    plan_id=link(c,owner,action),session_id=None,delegation_id=None)
                approved_body=context(c,owner,ref,self.chats)
                if approved_body is None or not approved_body['artifacts']: raise DomainError('coach_permission_invalid',403)
                refs=[ref,*[dict(kind='artifact',id=a['id'],revision=a['version'],action_id=action,plan_id=ref['plan_id'],session_id=a['session_id'],delegation_id=None) for a in approved_body['artifacts']]]
                return_value=None
            else:
                counts=budget(c,owner,self.clock(),config)['session_counts'] if trigger!='manual' else {}
                excluded={session for session,count in counts.items() if count>=config['max_calls_per_session']}
                refs=collect(c,owner,scope,plan_id,self.clock(),self.chats,excluded);return_value=None if refs else 'coach_no_new_signals'
            inputs=input_state(c,owner,scope,plan_id,refs,self.chats) if refs else None
            while inputs and input_bytes(inputs)>MAX_INPUT_BYTES and len(refs)>1 and not permission_request:
                refs=refs[:-1];inputs=input_state(c,owner,scope,plan_id,refs,self.chats)
            if inputs and input_bytes(inputs)>MAX_INPUT_BYTES: raise DomainError('coach_input_too_large',422)
        if return_value: return dict(view=self.view(identity,scope,plan_id),run=None,reason=return_value)
        try: _,config,snapshot=self.chats.model_control.runtime(owner,scope,'default' if scope=='global' else plan_id)
        except ConversationError as error: raise DomainError('coach_provider_unavailable',503) from error
        maximum=MAX_OUTPUT_TOKENS;limit=snapshot['model']['capabilities'].get('max_output_tokens')
        if type(limit) is int and limit>0: maximum=min(maximum,limit)
        frozen={**snapshot['model_control'],'max_tokens':maximum,'prompt_schema_version':1}
        try:
            result=self.learning.core.execute(self.learning.principal(identity),ClaimCoachRun(run_id=str(uuid4()),scope=scope,plan_id=plan_id,
                trigger=trigger,inputs=inputs,provider_snapshot=frozen,retry_run_id=retry,
                permission_candidate_id=permission_candidate,permission_request_id=permission_request),key)
        except DomainError as error:
            if error.code not in GATES: raise
            return dict(view=self.view(identity,scope,plan_id),run=None,reason=error.code)
        task=asyncio.create_task(self._generate(identity,result['run_id'],config,inputs,maximum))
        self.tasks[result['run_id']]=task;task.add_done_callback(lambda _:self.tasks.pop(result['run_id'],None))
        return dict(view=self.view(identity,scope,plan_id),run=self.run(identity,result['run_id'])['run'],reason=None)

    async def _generate(self,identity,identifier,config,inputs,maximum):
        owner=identity['id'];failure=None;reason=None
        diagnostic=ProviderDiagnostics(getattr(self.chats,'diagnostics',None),owner,identifier,'coach',config.provider_kind)
        def current(send=False):
            with self.db.transaction() as c:
                run=owned(c,owner,'learning_coach_run',identifier);body=original(c,owner,identifier)
                active=run['status'] in {'queued','running'}
                if not active or body is None or input_state(c,owner,run['scope'],run['plan_id'],inputs['refs'],self.chats)!=inputs: raise DomainError('coach_input_changed')
            if send and not run['sent_at']:
                self.learning.core.execute(Principal.user(owner),SendCoachRun(run_id=identifier,expected_revision=run['revision']),'coach-send:'+identifier)
        diagnostic.check=lambda:current(True)
        try:
            async with self.slots:
                current()
                provider=build_provider(config,transport=self.transport);provider.diagnostics=diagnostic
                text=await provider.generate_text(messages(inputs),max_tokens=maximum,json_mode=True)
            diagnostic.phase='output_validation';output=Proposal.model_validate_json(text)
            current()
            row=self.db.fetchone('SELECT revision FROM learning_coach_run WHERE owner_id=? AND id=?',(owner,identifier))
            self.learning.core.execute(Principal.user(owner),FinishCoachRun(run_id=identifier,expected_revision=row['revision'],status='succeeded',
                candidates=[x.model_dump() for x in output.candidates]),'coach-finish:'+identifier)
        except asyncio.CancelledError as error: failure=error;reason='interrupted'
        except (ProviderError,TimeoutError,ValueError,DomainError) as error:
            failure=error;reason=error.code if isinstance(error,DomainError) else 'invalid_proposal' if isinstance(error,ValueError) else 'generation_failed'
        finally:
            row=self.db.fetchone('SELECT status,revision FROM learning_coach_run WHERE owner_id=? AND id=?',(owner,identifier))
            if row and row['status'] in {'queued','running'} and reason:
                self.learning.core.execute(Principal.user(owner),FinishCoachRun(run_id=identifier,expected_revision=row['revision'],status='failed',reason=reason),'coach-failure:'+identifier)
            row=self.db.fetchone('SELECT status FROM learning_coach_run WHERE owner_id=? AND id=?',(owner,identifier))
            diagnostic.finish(row['status'] if row else 'failed',failure,reason)

    async def cancel(self,identity,identifier,payload,key):
        self.run(identity,identifier)
        self.learning.core.execute(self.learning.principal(identity),CancelCoachRun(run_id=identifier,**payload),key)
        if identifier in self.tasks: self.tasks[identifier].cancel()
        return self.run(identity,identifier)

    async def purge(self,identity,identifier,payload,key):
        result=ManagedPurge(self.learning).run(identity,'coach_run',identifier,
            lambda:self.learning.core.execute(self.learning.principal(identity),PurgeCoachRun(run_id=identifier,**payload),key))
        if identifier in self.tasks: self.tasks[identifier].cancel()
        return {**self.run(identity,identifier),'purge_report':result['purge']}

    def decide(self,identity,identifier,payload,key):
        self.learning.core.execute(self.learning.principal(identity),DecideCoachCandidate(candidate_id=identifier,**payload),key)
        value=self.candidate(identity,identifier)
        return {'candidate':value,'navigation':value['target'] if payload['operation']=='accept' else None}

    def _signal(self,c,owner,value):
        available=signal_available(c,owner,value,self.chats)
        kind='new_task' if value['kind']=='separate_work_requested' else 'task'
        t=target(kind,value['plan_id'],value['action_id'],value['delegation_id'])
        return {key:value[key] for key in ('id','revision','kind','plan_id','action_id','delegation_id','session_id','created_at')} | {
            'status':value['status'] if available else 'unavailable','source_available':available,'immediate':value['kind'] in IMMEDIATE,
            'source':dict(kind='answer',id=value['answer_id'],revision=value['source_revision'],label='当前回答中的委托信号',available=available,
                href=target('evidence_review',value['plan_id'],value['action_id'],value['delegation_id'])['href']),
            'target':t if available else None}

    def signals(self,identity,scope='global',plan_id=None):
        owner=self._owner(identity);self.sync_signals(owner)
        with self.db.transaction() as c:
            self._scope(c,owner,scope,plan_id)
            return {'items':[self._signal(c,owner,dict(r)) for r in c.execute('SELECT * FROM learning_coach_signal WHERE owner_id=?'+(' AND plan_id=?' if plan_id else '')+' ORDER BY created_at DESC',(owner,plan_id) if plan_id else (owner,))]}

    def correct_signal(self,identity,identifier,payload,key):
        self.sync_signals(identity['id'])
        self.learning.core.execute(self.learning.principal(identity),CorrectCoachSignal(signal_id=identifier,**payload),key)
        with self.db.transaction() as c: return self._signal(c,identity['id'],owned(c,identity['id'],'learning_coach_signal',identifier))

    def sync_signals(self,owner):
        # Successful immutable snapshots only. Branch copies retain origin and
        # never count as new attempts. No Provider call is made here.
        ordinary=self.chats.database.fetchall("SELECT response_message_id,config_snapshot_json FROM ai_run WHERE identity_id=? AND status='succeeded' AND json_type(config_snapshot_json,'$.teaching.assignment_signal')='object'",(owner,))
        discussion=self.db.fetchall("SELECT t.id,t.provider_snapshot_json FROM learning_discussion_turn t JOIN learning_question_discussion d ON d.id=t.discussion_id WHERE d.owner_id=? AND t.status='succeeded' AND json_type(t.provider_snapshot_json,'$.teaching.assignment_signal')='object'",(owner,))
        for kind,values in [('conversation',ordinary),('discussion',discussion)]:
            for row in values:
                snapshot=json.loads(row['config_snapshot_json'] if kind=='conversation' else row['provider_snapshot_json'])
                if snapshot.get('branch_origin'): continue
                teaching=snapshot['teaching'];signal=teaching['assignment_signal'];context=teaching.get('coach_context') or {}
                if not context.get('action_id') or self.db.fetchone('SELECT 1 FROM learning_coach_signal WHERE owner_id=? AND id=?',(owner,signal['id'])): continue
                value=dict(id=signal['id'],kind=signal['kind'],plan_id=context.get('plan_id'),action_id=context['action_id'],delegation_id=context.get('delegation_id'),
                    session_id=context.get('session_id'),answer_kind=kind,answer_id=teaching['answer_id'],source_id=teaching['message_id'],source_revision=1,
                    start_offset=signal['start'],end_offset=signal['end'])
                try: self.learning.core.execute(Principal.user(owner),RecordCoachSignal(signal=value),'coach-signal:'+signal['id'])
                except DomainError: continue  # A correction/clear may have won the race; never damage the saved answer.

    def recover(self):
        for row in self.db.fetchall("SELECT owner_id,id,revision FROM learning_coach_run WHERE status IN ('queued','running')"):
            self.learning.core.execute(Principal.user(row['owner_id']),CancelCoachRun(run_id=row['id'],expected_revision=row['revision'],reason='interrupted'),'coach-recover:'+row['id'])

    def start_monitor(self):
        self.monitor=asyncio.create_task(self._monitor())

    async def _monitor(self):
        while not self._stopping:
            await asyncio.sleep(1)
            rows=self.db.fetchall("SELECT * FROM learning_event WHERE position>? ORDER BY position",(self.boundary_position,))
            if rows: self.boundary_position=rows[-1]['position']
            plans={}
            for event in rows:
                if event['event_type']!='session.ended' or event['actor_kind']!='user': continue
                config=settings(self.db.connection,event['owner_id'])
                if not config['enabled'] or event['position']<=config['enabled_position']: continue
                payload=json.loads(event['payload_json'])
                row=self.db.fetchone('''SELECT l.plan_id FROM learning_session s JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
                    JOIN learning_action_link l ON l.owner_id=d.owner_id AND l.action_id=d.action_id WHERE s.owner_id=? AND s.id=?''',(event['owner_id'],payload['session_id']))
                if row: plans[(event['owner_id'],row[0])]=event['event_id']
            for (owner,plan_id),event_id in plans.items():
                try: await self.check({'id':owner},{'scope':'plan','plan_id':plan_id,'trigger':'boundary'},'coach-boundary:'+event_id)
                except (DomainError,ConversationError): pass

    async def shutdown(self):
        self._stopping=True
        if self.monitor: self.monitor.cancel();await asyncio.gather(self.monitor,return_exceptions=True)
        for task in list(self.tasks.values()): task.cancel()
        if self.tasks: await asyncio.gather(*list(self.tasks.values()),return_exceptions=True)
        self.recover()
