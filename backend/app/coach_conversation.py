"""Coach identity and bounded navigation, using the existing chat runtime."""
import json
from uuid import uuid4,uuid5,NAMESPACE_URL
from .conversations import ConversationError, ConversationConflict, _now
from .core.events import digest
from .goal_lifecycle import OPEN_GOAL_STATUSES
from .coach_sources import target
from .providers import ProviderChunk


def mapped(chats, owner, identifier):
    service = getattr(chats, 'coach_conversations', None)
    return service.mapping(owner, identifier) if service else None


class CoachConversationService:
    def __init__(self, learning, chats):
        self.learning, self.db, self.chats = learning, learning.database, chats
        self.lock = chats.materials.lock
        self.manager = None

    def mapping(self, owner, identifier):
        row = self.db.fetchone('SELECT * FROM learning_coach_conversation WHERE owner_id=? AND conversation_id=?', (owner, identifier))
        return dict(row) if row else None

    def require(self, owner, identifier):
        row = self.mapping(owner, identifier)
        if not row or row['purged_at']:
            raise ConversationError('教练对话不存在或内容已清除')
        conversation=self.chats.owned_conversation(owner, identifier)
        if conversation['context_scope']!='global': raise ConversationError('教练对话身份与范围不一致')
        return row

    @staticmethod
    def info(row):
        return {key: row[key] for key in ('conversation_id','role_version','created_at','updated_at','purged_at')} | {'role':'coach'}

    def list(self, identity):
        owner = self.learning.principal(identity).owner_id
        return self._list(owner)

    def _list(self, owner):
        result=[]
        for row in self.db.fetchall('SELECT * FROM learning_coach_conversation WHERE owner_id=? AND purged_at IS NULL ORDER BY updated_at DESC,conversation_id', (owner,)):
            try:
                self.chats.owned_conversation(owner, row['conversation_id'])
                result.append(self.info(dict(row)))
            except ConversationError:
                continue
        return {'items':result}

    def open(self, identity, request_key, new_conversation=False):
        owner=self.learning.principal(identity).owner_id
        fingerprint=digest({'new_conversation':new_conversation})
        created=None
        with self.lock:
            try:
                with self.db.transaction(immediate=True) as c:
                    previous=c.execute("SELECT * FROM learning_coach_request WHERE owner_id=? AND scope='open' AND request_key=?",(owner,request_key)).fetchone()
                    if previous:
                        if previous['fingerprint']!=fingerprint: raise ConversationConflict('本次打开请求内容已变化')
                        identifier=previous['result_id']
                    else:
                        latest=self._list(owner)['items'] if not new_conversation else []
                        if latest: identifier=latest[0]['conversation_id']
                        else:
                            created=identifier=str(uuid5(NAMESPACE_URL,'nautilus:coach:'+owner+':'+request_key));now=_now()
                            c.execute('INSERT INTO learning_coach_conversation VALUES (?,?,1,?,?,NULL)',(owner,identifier,now,now))
                        c.execute('INSERT INTO learning_coach_request VALUES (?,\'open\',?,?,?,?)',(owner,request_key,fingerprint,identifier,_now()))
                # The role intent is durable first, so a process crash cannot expose an unmarked old-global chat.
                if not self.chats.database.fetchone('SELECT 1 FROM conversation WHERE id=? AND identity_id=?',(identifier,owner)):
                    self.chats.create_conversation(owner,title='学习教练',context_scope='global',_conversation_id=identifier)
            except BaseException:
                if created:
                    with self.chats.database.transaction(immediate=True) as ordinary:
                        ordinary.execute('DELETE FROM conversation WHERE id=? AND identity_id=?',(created,owner))
                    with self.db.transaction(immediate=True) as c:
                        c.execute('DELETE FROM learning_coach_conversation WHERE owner_id=? AND conversation_id=?',(owner,created))
                        c.execute("DELETE FROM learning_coach_request WHERE owner_id=? AND scope='open' AND request_key=?",(owner,request_key))
                raise
        return self.detail(identity,identifier)

    def detail(self, identity, identifier):
        owner=self.learning.principal(identity).owner_id
        row=self.require(owner,identifier)
        detail=self.chats.conversation_detail(owner,identifier)
        ctx=self.context(owner)
        return {**detail,'coach':self.info(row),'coach_context':{'summary':ctx['summary'],'source_revision':ctx['coach_inputs']['source_revision'],'actions':ctx['coach_inputs']['actions']}}

    def context(self, owner):
        """Metadata whitelist only; no private texts, grants, old plans or history."""
        with self.db._lock:
            c=self.db.connection
            plans=[dict(r) for r in c.execute('''SELECT p.id,p.title,p.status,p.goal_id,g.status AS goal_status,g.version AS goal_version
                FROM learning_plan p LEFT JOIN learning_goal g ON g.owner_id=p.owner_id AND g.id=p.goal_id
                WHERE p.owner_id=? ORDER BY p.status<>'active',p.created_at,p.id LIMIT 32''',(owner,))]
            plan_total=c.execute('SELECT COUNT(*) FROM learning_plan WHERE owner_id=?',(owner,)).fetchone()[0]
            actions=[dict(r) for r in c.execute('''SELECT a.id,a.title,a.status,a.version,l.plan_id
                FROM learning_action a JOIN learning_action_link l ON l.owner_id=a.owner_id AND l.action_id=a.id
                WHERE a.owner_id=? AND NOT EXISTS(SELECT 1 FROM learning_action_removal x WHERE x.owner_id=a.owner_id AND x.action_id=a.id)
                ORDER BY a.status<>'open',a.created_at,a.id LIMIT 64''',(owner,))]
            action_total=c.execute('''SELECT COUNT(*) FROM learning_action a JOIN learning_action_link l ON l.owner_id=a.owner_id AND l.action_id=a.id
                WHERE a.owner_id=? AND NOT EXISTS(SELECT 1 FROM learning_action_removal x WHERE x.owner_id=a.owner_id AND x.action_id=a.id)''',(owner,)).fetchone()[0]
            from .coach_reminders import current_items
            all_items=current_items(c,owner)
            plan_ids={p['id'] for p in plans};actions=[a for a in actions if a['plan_id'] in plan_ids]
            action_ids={a['id'] for a in actions}
            items=[i for i in all_items if i['plan_id'] in plan_ids and i['action_id'] in action_ids][:24]
            paths=[dict(r) for r in c.execute('SELECT plan_id,current_node_id,adopted_version_id,status,revision FROM learning_plan_path_state WHERE owner_id=? ORDER BY plan_id',(owner,)) if r['plan_id'] in plan_ids]
            sessions=[dict(r) for r in c.execute("SELECT id,delegation_id,status,version FROM learning_session WHERE owner_id=? AND status='running' ORDER BY id LIMIT 1",(owner,))]
            sessions=[s for s in sessions if c.execute('SELECT 1 FROM learning_delegation WHERE owner_id=? AND id=? AND action_id IN ('+(','.join('?' for _ in action_ids) or 'NULL')+')',(owner,s['delegation_id'],*sorted(action_ids))).fetchone()]
            running_total=c.execute("SELECT COUNT(*) FROM learning_session WHERE owner_id=? AND status='running'",(owner,)).fetchone()[0]
            plan_by={p['id']:p for p in plans};path_by={p['plan_id']:p for p in paths}
            navigation=[]
            for action in actions:
                plan=plan_by.get(action['plan_id']);path=path_by.get(action['plan_id'])
                if not plan or plan['status']!='active' or plan['goal_status'] and plan['goal_status'] not in OPEN_GOAL_STATUSES or path and path['status']=='paused': continue
                if action['status']!='open': continue
                delegation=c.execute("SELECT id,status,contract_version FROM learning_delegation WHERE owner_id=? AND action_id=? AND status IN ('ready','active') ORDER BY id LIMIT 1",(owner,action['id'])).fetchone()
                if delegation:
                    navigation.append({'id':'task:'+delegation['id'],'label':'继续：'+action['title'],'target':target('task',action['plan_id'],action['id'],delegation['id']),
                        'binding':{'action_version':action['version'],'contract_version':delegation['contract_version']}})
            for plan in plans:
                if plan['status']=='active' and (not plan['goal_status'] or plan['goal_status'] in OPEN_GOAL_STATUSES):
                    navigation.append({'id':'arrange:'+plan['id'],'label':'核对安排：'+plan['title'],'target':target('commitment_review',plan['id']),'binding':{}})
            if not navigation:
                navigation.append({'id':'new','label':'安排下一步','target':target('new_task'),'binding':{}})
            inputs={'plans':plans,'tasks':actions,'arrangements':items,'paths':paths,'running_sessions':sessions,'targets':navigation}
            from .coach_sources import MAX_INPUT_BYTES,input_bytes
            while True:
                counts={'plans':{'total':plan_total,'included':len(plans),'truncated':plan_total>len(plans)},
                    'tasks':{'total':action_total,'included':len(actions),'truncated':action_total>len(actions)},
                    'arrangements':{'total':len(all_items),'included':len(inputs['arrangements']),'truncated':len(all_items)>len(inputs['arrangements'])},
                    'running_sessions':{'total':running_total,'included':len(sessions),'truncated':running_total>len(sessions)}}
                inputs['counts']=counts
                inputs['unknowns']=['当前只展示部分摘要，未展示的计划或任务情况仍未知。'] if any(v['truncated'] for v in counts.values()) else []
                inputs.pop('source_revision',None);inputs.pop('actions',None)
                revision=digest(inputs)
                allowed=[{'id':v['id'],'label':v['label'],'target':v['target'],'source_revision':revision,'available':True,'reason':None} for v in navigation]
                inputs.update(source_revision=revision,actions=allowed)
                if input_bytes(inputs)<=MAX_INPUT_BYTES-2048: break
                if actions:
                    removed=actions.pop();navigation[:]=[v for v in navigation if v['target'].get('action_id')!=removed['id']]
                    inputs['arrangements'][:]=[i for i in inputs['arrangements'] if i['action_id']!=removed['id']]
                    sessions[:]=[s for s in sessions if not c.execute('SELECT 1 FROM learning_delegation WHERE owner_id=? AND id=? AND action_id=?',(owner,s['delegation_id'],removed['id'])).fetchone()]
                elif len(plans)>1:
                    removed=plans.pop();navigation[:]=[v for v in navigation if v['target'].get('plan_id')!=removed['id']]
                    paths[:]=[p for p in paths if p['plan_id']!=removed['id']]
                else: raise ConversationError('当前教练摘要过大，请在对应计划核对')
            summary=f"当前摘要包含{len(plans)}个计划、{len(actions)}项任务。"
            if inputs['unknowns']: summary+='部分内容未展示，具体状态仍需到对应计划核对。'
            if sessions: summary+='目前正在学习；可以先继续当前任务。'
            else: summary+='可以按今天可用时间和精力核对下一步。'
            return {'scope_kind':'global','summary':summary,'plans':plans,'tasks':actions,
                'plan_counts':counts['plans'],'task_counts':{**counts['tasks'],'overdue':0},'coach_inputs':inputs}

    def freeze(self, owner, context, output):
        return {'role':'coach','schema_version':1,'token':str(uuid4()),'output':'json' if output['format']=='json' else 'plain',
                'inputs':context['coach_inputs'],'source_revision':context['coach_inputs']['source_revision'],'actions':[],'unknowns':[],'content_available':True}

    def check(self, owner, identifier, snapshot, *, sending=False):
        self.require(owner,identifier)
        frozen=snapshot.get('coach')
        if sending and frozen and self.context(owner)['coach_inputs']['source_revision']!=frozen['source_revision']:
            raise ConversationConflict('教练依据已变化，请读取当前安排后重新发送')

    def finish(self, owner, identifier, frozen, proposal):
        self.require(owner,identifier)
        valid=self.context(owner)['coach_inputs']['source_revision']==frozen['source_revision']
        allowed={a['id']:a for a in frozen['inputs']['actions']}
        if frozen['output']=='plain': chosen=list(allowed)[:3];unknowns=[]
        elif isinstance(proposal,dict) and set(proposal)<= {'actions','unknowns'}:
            chosen=proposal.get('actions',[]);unknowns=proposal.get('unknowns',[])
            if not isinstance(chosen,list) or len(chosen)>3 or any(not isinstance(v,str) or v not in allowed for v in chosen): chosen=[]
            if not isinstance(unknowns,list) or any(not isinstance(v,str) or len(v)>500 for v in unknowns): unknowns=[]
        else: chosen=[];unknowns=[]
        frozen['actions']=[{**allowed[k],'available':valid,'reason':None if valid else 'source_changed'} for k in dict.fromkeys(chosen)]
        frozen['unknowns']=list(dict.fromkeys([*frozen['inputs'].get('unknowns',[]),*unknowns]))[:5]
        return frozen

    def public(self, owner, identifier, frozen):
        if not frozen: return None
        mapping=self.mapping(owner,identifier)
        available=bool(mapping and not mapping['purged_at'])
        valid=available and self.context(owner)['coach_inputs']['source_revision']==frozen['source_revision']
        return {'role':'coach','schema_version':1,'source_revision':frozen['source_revision'],
            'actions':[{**a,'available':bool(valid and a['available']),'reason':a['reason'] if valid else 'source_changed'} for a in frozen.get('actions',[])] if available else [],
            'unknowns':frozen.get('unknowns',[]) if available else [],'content_available':available}

    def resolve(self, identity, identifier, action_id, source_revision):
        owner=self.learning.principal(identity).owner_id;self.require(owner,identifier)
        ctx=self.context(owner)['coach_inputs']
        if ctx['source_revision']!=source_revision: raise ConversationConflict('当前安排已变化，请重新核对教练建议')
        action=next((a for a in ctx['actions'] if a['id']==action_id),None)
        if not action: raise ConversationError('这项建议当前不可用')
        return {'target':action['target']}


def coach_prompt(history, context, frozen):
    system='你是学海无涯的学习教练，围绕今天时间、精力、拖延和中断恢复与本人持续交谈。用中文，简短回应本人当前想法，再给一个现实可行的下一步。不要布置一串待办、考试或宣称已开始/完成学习。只使用当前最小摘要和本对话本人提供的信息；未知不猜。原文不足可请本人概述或进入既有教练复盘的本次读取申请。动作只导航到已有任务/安排，修改计划或开始学习仍要本人在原流程确认。没有搜索、附件、任务原文或事实写入工具。'
    system+='\n当前最小摘要：'+json.dumps(context['coach_inputs'],ensure_ascii=False,sort_keys=True,separators=(',',':'))
    if frozen['output']=='json':
        system+='\n只返回JSON对象，reply是给本人的自然正文，coach={"actions":[本次targets中id字符串，至多3个],"unknowns":[仍未知事项]}，token必须为'+frozen['token']+'。先写reply；不得把技术字段写入正文。'
    result=[{'role':'system','content':system},*history]
    if frozen['output']=='json': result.append({'role':'system','content':'按照上述JSON协议回答。','_coach_runtime':True,'_teaching_output':'json'})
    return result


class CoachStream:
    def __init__(self, frozen):
        from .teaching_json import JsonTeachingDecoder
        self.decoder=JsonTeachingDecoder(frozen['token'],metadata_field='coach') if frozen['output']=='json' else None
        self.completed=False

    async def filter(self, stream):
        async for chunk in stream:
            if chunk.kind=='completion':
                self.completed=chunk.text=='complete'
                if self.decoder: self.decoder.finish()
            elif chunk.kind=='content' and self.decoder:
                body=self.decoder.feed(chunk.text)
                if body: yield ProviderChunk('content',body)
            else: yield chunk

    def proposal(self):
        return self.decoder.proposal() if self.decoder and self.completed else None
