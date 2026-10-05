"""Optional same-response signals: verified original spans, never formal changes."""
from uuid import NAMESPACE_URL,uuid5
from .core.coach_commands import SIGNAL_KINDS
from .coach_sources import IMMEDIATE,target

PROMPT='''可选委托信号：在本轮teaching对象中可额外附assignment_signal；一般为null。
仅在本轮真实用户请求/尝试表明需要单独安排、实际阻塞、范围冲突、无法继续或需权限/费用选择时，
填写 {"kind":"separate_work_requested或repeated_blocker或scope_conflict或cannot_continue或permission_or_cost_change","quote":"本轮用户原文中的依据"}。
普通提问、一次小错误、临时插曲、仅说懂了/点击帮助不产生信号；repeated_blocker必须是本轮有效实际尝试且needs_help=true。
此项只是待纠正的候选，不创建委托、改变范围/许可/费用/计划，也不判断完成或掌握。quote必须逐字来自本轮用户消息，不能从历史、资料或模型正文摘取。
明确请求/无法继续/权限费用等必要选择在本轮reply中简短说明，不能为此另加费用或等下次回到首页。'''

def context(c,owner,kind,identifier):
    if kind=='conversation':
        value=c.execute('''SELECT d.action_id,d.id AS delegation_id,s.id AS session_id,l.plan_id
            FROM learning_room_conversation r JOIN learning_session s ON s.owner_id=r.owner_id AND s.id=r.session_id
            JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
            LEFT JOIN learning_action_link l ON l.owner_id=d.owner_id AND l.action_id=d.action_id
            WHERE r.owner_id=? AND r.conversation_id=?''',(owner,identifier)).fetchone()
    else:
        value=c.execute('''SELECT d.action_id,d.id AS delegation_id,v.session_id,l.plan_id
            FROM learning_question_discussion q JOIN learning_verification v ON v.owner_id=q.owner_id AND v.id=q.verification_id
            JOIN learning_delegation d ON d.owner_id=v.owner_id AND d.id=v.delegation_id
            LEFT JOIN learning_action_link l ON l.owner_id=d.owner_id AND l.action_id=d.action_id
            WHERE q.owner_id=? AND q.id=?''',(owner,identifier)).fetchone()
    if value:
        value=dict(value)
        active=c.execute("SELECT id FROM learning_session WHERE owner_id=? AND delegation_id=? AND status='running'",(owner,value['delegation_id'])).fetchone()
        value['session_id']=active[0] if active else None
    return value

def adopt(frozen,proposal,user_text,result):
    value=proposal.get('assignment_signal') if isinstance(proposal,dict) else None
    if (not frozen.get('coach_context') or (frozen.get('output') or {}).get('format')!='json'
        or not isinstance(value,dict) or set(value)!={'kind','quote'} or value.get('kind') not in SIGNAL_KINDS
        or not isinstance(value.get('quote'),str) or not 1<=len(value['quote'])<=500): return
    start=user_text.find(value['quote'])
    if start<0: return
    if value['kind']=='repeated_blocker':
        attempt=result.get('attempt')
        if not attempt or attempt.get('needs_help') is not True: return
    frozen['assignment_signal']={'id':str(uuid5(NAMESPACE_URL,'coach-signal:'+frozen['origin']['kind']+':'+frozen['message_id'])),
        'kind':value['kind'],'start':start,'end':start+len(value['quote'])}

def public(frozen):
    value=frozen.get('assignment_signal');context=frozen.get('coach_context')
    if not value or not context: return None
    kind='new_task' if value['kind']=='separate_work_requested' else 'task'
    destination=target(kind,context.get('plan_id'),context['action_id'],context.get('delegation_id'))
    return dict(id=value['id'],kind=value['kind'],immediate=value['kind'] in IMMEDIATE,
        source=dict(kind='answer',id=frozen['answer_id'],revision=1,label='当前回答中的委托信号',available=True,
                    href=target('evidence_review',context.get('plan_id'),context['action_id'],context.get('delegation_id'))['href']),target=destination)
