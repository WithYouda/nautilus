"""Small deterministic return read model and content-free user decision linkage."""
import json
from uuid import uuid4

from .core.commands import EndSession, StartSession
from .core.events import digest
from .core.learning import utc_timestamp
from .learning_domain import DomainError, Principal, trusted_claim_method


def record_usage(connection, owner_id, kind, key, *, review_id=None, action_id=None, delegation_id=None, session_id=None):
    connection.execute(
        'INSERT OR IGNORE INTO learning_usage_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (str(uuid4()), owner_id, review_id, kind, action_id, delegation_id, session_id, key, utc_timestamp()),
    )


class ContinuityService:
    def __init__(self, learning):
        self.learning = learning
        self.database = learning.database

    def get(self, identity):
        principal = self.learning.principal(identity)
        with self.database.transaction(immediate=True) as connection:
            return self._card(connection, principal)

    def _card(self, connection, principal):
        owner = principal.owner_id
        sessions = [dict(row) for row in connection.execute(
            """SELECT s.* FROM learning_session s LEFT JOIN learning_event e
               ON e.owner_id=s.owner_id AND e.event_type='session.started' AND json_extract(e.payload_json,'$.id')=s.id
               WHERE s.owner_id=? ORDER BY (s.status='running') DESC, COALESCE(e.rowid,0) DESC, s.rowid DESC""", (owner,))]
        delegations = [dict(row) for row in connection.execute(
            "SELECT d.*, a.title, a.status AS action_status, a.version AS action_version FROM learning_delegation d JOIN learning_action a ON a.owner_id=d.owner_id AND a.id=d.action_id WHERE d.owner_id=? ORDER BY d.created_at DESC, d.rowid DESC", (owner,))]
        if not delegations:
            return None
        session = sessions[0] if sessions else None
        current = next((d for d in delegations if session and d['id'] == session['delegation_id']), delegations[0])
        open_items = [d for d in delegations if d['status'] in ('ready', 'active') and d['action_status'] == 'open']
        verification = connection.execute(
            'SELECT * FROM learning_verification WHERE owner_id=? AND delegation_id=? AND purged_at IS NULL ORDER BY created_at DESC, rowid DESC LIMIT 1', (owner, current['id']),
        ).fetchone()
        claims = [dict(row) for row in connection.execute(
            """SELECT c.* FROM learning_evidence_claim c JOIN learning_artifact a
               ON a.owner_id=c.owner_id AND a.id=c.artifact_id AND a.content_version=c.content_version
               JOIN learning_raw_artifact raw ON raw.owner_id=c.owner_id AND raw.artifact_id=c.artifact_id AND raw.content_version=c.content_version
               JOIN learning_session s ON s.owner_id=raw.owner_id AND s.id=raw.session_id
               WHERE c.owner_id=? AND s.delegation_id=? AND a.visibility='visible' AND a.evidence_status='eligible'
               AND c.status IN ('candidate','adopted','questioned') ORDER BY c.created_at DESC, c.id""", (owner, current['id']))]
        pending = any(c['status'] == 'candidate' for c in claims)
        target = current if current in open_items else (open_items[0] if open_items else None)
        verification_id = None
        if session and session['status'] == 'running' and current in open_items:
            kind, reason, explanation = 'resume', 'running', '这次学习尚在进行，先接着当前任务。'
        elif session and session['status'] == 'interrupted' and current in open_items:
            kind, reason, explanation = 'resume', 'interrupted', '你上次在这里中断，继续原来的任务可以保留学习上下文。'
        elif pending:
            kind, reason, explanation = 'review', 'candidate_evidence', '已有候选依据尚未复核，先核对它实际能说明什么。'
            target = current
        elif verification and verification['status'] in ('failed','submitted','ready') and verification['latest_submission_id']:
            kind, reason, explanation = 'supplemental_verification', 'saved_verification', '作答已保存，继续查看或重试本次验证。'
            target = current
            verification_id = verification['id']
        elif target:
            kind, reason, explanation = 'practice', 'open_delegation', '还有已经确认的开放任务，可以继续推进。'
        else:
            kind, reason, explanation = 'choose_next', 'no_open_delegation', '本次任务已结束；确认一个新的小步骤后再继续，不自动改变你的计划。'
        # A saved attempt remains attached to the original session when retried.
        if verification and verification['status'] != 'passed' and verification['latest_submission_id'] and reason in ('running','interrupted'):
            verification_id = verification['id']
        position = connection.execute(
            """SELECT g.title AS goal, p.title AS plan FROM learning_action_link l
               LEFT JOIN learning_plan p ON p.owner_id=l.owner_id AND p.id=l.plan_id
               LEFT JOIN learning_goal g ON g.owner_id=p.owner_id AND g.id=p.goal_id
               WHERE l.owner_id=? AND l.action_id=?""", (owner, current['action_id']),
        ).fetchone()
        supported = []
        for claim in claims:
            method = trusted_claim_method(claim)
            if claim['status'] != 'adopted' or claim['stance'] != 'supports' or not method:
                continue
            deterministic = method == 'deterministic_check'
            supported.append(dict(claim_id=claim['id'], label='当前样例的确定性检查通过' if deterministic else '已采纳的一次 AI 观察',
                basis_kind=method, scope='仅当前样例' if deterministic else '仅本次产出',
                user_facing_explanation='该表达式在这份样例中匹配成功；没有检查其他输入。' if deterministic else '这是对本次产出的解释，尚非独立复核。'))
        unknowns = [dict(reason_code='no_delayed_or_transfer', label='尚未观察延迟保持与不同情境下的迁移表现。')]
        if any(c['status']=='adopted' and c['stance']=='refutes' for c in claims):
            unknowns.insert(0, dict(reason_code='contradicting_evidence', label='已有观察与达成标准不一致，需要检查冲突。'))
        if not supported:
            unknowns.insert(0, dict(reason_code='no_adopted_evidence', label='还没有经过复核且来源可信的成果依据。'))
        if pending:
            unknowns.insert(0, dict(reason_code='pending_review', label='候选依据尚待你复核。'))
        if not current['criterion_id']:
            unknowns.insert(0, dict(reason_code='no_standard', label='尚无已审核标准，本次反馈不派生成果状态。'))
        if claims:
            unknowns.append(dict(reason_code='independence_unverified', label='独立完成只能依据你的自报，系统没有独立观察。'))
        happened = '学习仍在进行。' if session and session['status']=='running' else '上次学习已中断，产出仍按原记录保存。' if session and session['status']=='interrupted' else '学习安排已保存。'
        if verification and verification['status']=='passed':
            happened = '你已确认本次委托完成；验证结果与成果证据分别记录。'
        fingerprint = digest(dict(session=session, delegation=current, target=target, kind=kind,
            verification=dict(verification) if verification else None,
            claims=[(c['id'],c['status']) for c in claims]))
        existing = connection.execute('SELECT id FROM learning_return_review WHERE owner_id=? AND context_key=?', (owner, fingerprint)).fetchone()
        review_id = existing[0] if existing else str(uuid4())
        if not existing:
            connection.execute('INSERT INTO learning_return_review VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (review_id, owner, fingerprint, session['id'] if session else None, target['action_id'] if target else None,
                 target['id'] if target else None, verification_id, kind, reason, utc_timestamp()))
        return dict(id=review_id, position=dict(goal=position['goal'] if position else '', plan=position['plan'] if position else '',
            action=current['title'], action_id=current['action_id'], delegation_id=current['id'],
            last_session=session['id'] if session else None, last_activity_at=(session['ended_at'] or session['started_at']) if session else current['created_at']),
            what_happened=dict(summary=happened, action_status=current['action_status'], delegation_status=current['status'],
                verification_status=verification['status'] if verification else None),
            supported=supported[:4], unknowns=unknowns,
            recommendation=dict(kind=kind, action_id=target['action_id'] if target else None, delegation_id=target['id'] if target else None,
                label='复核本次依据' if kind=='review' else '继续已保存验证' if verification_id else target['title'] if target else '确认下一小步',
                reason_code=reason, explanation=explanation, verification_id=verification_id),
            choices=['continue','choose_other','stop_for_now'],
            alternatives=[dict(action_id=d['action_id'], delegation_id=d['id'], label=d['title']) for d in open_items],
            evidence_details=[dict(id=c['id'], status=c['status'], statement=c['statement'], source=c['source'], source_trusted=bool(trusted_claim_method(c)), scope=c['scope']) for c in claims[:12]])

    def decide(self, identity, review_id, kind, request_key, delegation_id=None, session_id=None):
        principal = self.learning.principal(identity)
        owner = principal.owner_id
        with self.database.transaction(immediate=True) as connection:
            review = connection.execute('SELECT * FROM learning_return_review WHERE owner_id=? AND id=?', (owner, review_id)).fetchone()
            if review is None:
                raise DomainError('not_found', 404)
            def record(event_kind, target=None, session=None):
                record_usage(connection, owner, event_kind, f'{request_key}:{event_kind}', review_id=review_id,
                    action_id=target['action_id'] if target else review['action_id'],
                    delegation_id=target['id'] if target else review['delegation_id'], session_id=session)
            previous = connection.execute("SELECT * FROM learning_usage_event WHERE owner_id=? AND review_id=? AND kind='started' ORDER BY rowid DESC LIMIT 1", (owner, review_id)).fetchone()
            if kind == 'entered':
                if previous is None or previous['session_id'] != session_id:
                    raise DomainError('verification_scope_invalid')
                record('entered', session=session_id)
                return dict(destination='room', session_id=session_id)
            if kind in ('review_card_shown','evidence_viewed','corrected'):
                record(kind)
                if kind=='review_card_shown' and review['reason_code']=='interrupted':
                    record('resume_candidate_presented', session=review['position_session_id'])
                return dict(destination='card')
            if kind == 'choose_other' and not delegation_id:
                record(kind)
                return dict(destination='choose')
            if kind in ('stop_for_now', 'choose_new'):
                if kind == 'choose_new':
                    if connection.execute("SELECT 1 FROM learning_usage_event WHERE owner_id=? AND request_key=?", (owner, f'{request_key}:switched')).fetchone():
                        return dict(destination='setup')
                    card = self._card(connection, principal)
                    if not card or card['id'] != review_id:
                        raise DomainError('version_conflict')
                running = connection.execute("SELECT s.*, d.action_id, a.version AS action_version FROM learning_session s JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id JOIN learning_action a ON a.owner_id=d.owner_id AND a.id=d.action_id WHERE s.owner_id=? AND s.status='running'", (owner,)).fetchone()
                if running:
                    self.learning.core.execute_in_transaction(connection, principal, EndSession(session_id=running['id'], disposition='interrupted', expected_version=running['action_version']), f'continuity-stop:{review_id}')
                if kind == 'choose_new':
                    record('choose_other')
                    record('switched')
                    return dict(destination='setup')
                record(kind)
                return dict(destination='stopped')
            if kind not in ('continue','choose_other'):
                raise DomainError('command_unsupported',422)
            if previous:
                return dict(destination='verification' if review['verification_id'] else 'room', session_id=previous['session_id'], review_id=review_id)
            card = self._card(connection, principal)
            if not card or card['id'] != review_id:
                raise DomainError('version_conflict')
            record(kind)
            if kind=='continue' and review['kind'] in ('review','choose_next'):
                return dict(destination='evidence' if review['kind']=='review' else 'setup')
            target_id = delegation_id if kind=='choose_other' else review['delegation_id']
            target = connection.execute("SELECT d.*, a.version AS action_version FROM learning_delegation d JOIN learning_action a ON a.owner_id=d.owner_id AND a.id=d.action_id WHERE d.owner_id=? AND d.id=? AND a.status='open' AND d.status IN ('ready','active')", (owner,target_id)).fetchone()
            if target is None:
                raise DomainError('delegation_not_startable')
            running = connection.execute("SELECT * FROM learning_session WHERE owner_id=? AND status='running'", (owner,)).fetchone()
            if running and running['delegation_id'] != target_id:
                version = connection.execute('SELECT a.version FROM learning_action a JOIN learning_delegation d ON d.owner_id=a.owner_id AND d.action_id=a.id WHERE d.owner_id=? AND d.id=?',(owner,running['delegation_id'])).fetchone()[0]
                self.learning.core.execute_in_transaction(connection, principal, EndSession(session_id=running['id'], disposition='interrupted', expected_version=version), f'continuity-switch:{review_id}')
                running = None
                record('switched', target)
            if review['verification_id'] and kind=='continue':
                selected = connection.execute('SELECT session_id FROM learning_verification WHERE owner_id=? AND id=?',(owner,review['verification_id'])).fetchone()[0]
                destination = 'verification'
            else:
                if running:
                    selected = running['id']
                else:
                    version = connection.execute('SELECT version FROM learning_action WHERE owner_id=? AND id=?',(owner,target['action_id'])).fetchone()[0]
                    selected = self.learning.core.execute_in_transaction(connection,principal,StartSession(delegation_id=target_id,expected_version=version),f'continuity-start:{review_id}')["id"]
                destination = 'room'
            if kind=='choose_other':
                record('switched',target,selected)
            record('started',target,selected)
            return dict(destination=destination,session_id=selected,review_id=review_id)
