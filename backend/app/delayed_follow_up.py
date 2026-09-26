"""Approved fixed-item follow-up. Saves bounded observations, never old ability state."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
from pathlib import Path
import platform
import re
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .core.events import canonical, digest
from .core.learning import utc_timestamp
from .learning_domain import DomainError, Principal


class CreateFollowUp(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_artifact_id: str
    source_content_version: int = Field(ge=1)
    request_key: str = Field(min_length=1, max_length=160)


class DraftAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0)
    answers: dict[str, StrictBool | None] = Field(max_length=8)
    user_report: Literal['none', 'used', 'unknown'] = 'unknown'


class SubmitAnswer(DraftAnswer):
    request_key: str = Field(min_length=1, max_length=160)


class ScheduleFollowUp(BaseModel):
    model_config = ConfigDict(extra='forbid')
    due_at: str = Field(max_length=64)
    timezone: str = Field(min_length=1, max_length=100)
    request_key: str = Field(min_length=1, max_length=160)


class ChooseFollowUp(BaseModel):
    model_config = ConfigDict(extra='forbid')
    choice: Literal['start', 'skip']
    request_key: str = Field(min_length=1, max_length=160)


def instant(value):
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if date.tzinfo is None:
            raise ValueError('offset required')
        return date.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise DomainError('delayed_invalid_time', 422)


def stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


@lru_cache(maxsize=1)
def approved_standard():
    package = json.loads((Path(__file__).with_name('standards') / 'python_regex_match_followup_v1.approved.json').read_text())
    if package['review_status'] != 'approved':
        raise DomainError('delayed_standard_unavailable', 409)
    return {**package, 'content_hash': digest(package)}


def public_standard(package):
    return {k: v for k, v in package.items() if k not in {'banks', 'source_context'}}


def check_answers(package, phase, answers):
    """Only execute the fixed bounded patterns from the frozen, approved bank."""
    checked = []
    for item in package['banks'][phase]:
        expected = re.fullmatch(item['pattern'], item['text']) is not None
        if expected != item['expected']:
            raise ValueError('standard executor mismatch')
        checked.append({**item, 'answer': answers[item['id']], 'correct': answers[item['id']] == expected})
    count = sum(item['correct'] for item in checked)
    return dict(executor_version=package['executor_version'], standard_hash=package['content_hash'],
        python_version=platform.python_version(), correct=count, total=len(checked), items=checked,
        description='本组匹配判断全部正确' if count == len(checked) else f'本组 {count}/{len(checked)} 项判断正确；查看各项匹配结果。')


class DelayedFollowUpService:
    def __init__(self, learning, *, clock=utc_timestamp):
        self.learning = learning
        self.db = learning.database
        self.clock = clock

    def _owner(self, identity):
        return self.learning.principal(identity).owner_id

    def _owned(self, c, owner, follow_up_id):
        row = c.execute('SELECT * FROM learning_delayed_follow_up WHERE owner_id=? AND id=?', (owner, follow_up_id)).fetchone()
        if row is None:
            raise DomainError('not_found', 404)
        return dict(row)

    def _sources(self, c, owner, outcome_id):
        if not c.execute('SELECT 1 FROM learning_outcome WHERE owner_id=? AND id=?', (owner, outcome_id)).fetchone():
            raise DomainError('not_found', 404)
        return [dict(row) for row in c.execute('''SELECT raw.artifact_id,raw.content_version,s.delegation_id,
            cv.id AS criterion_id,a.title AS action_title,raw.created_at
            FROM learning_raw_artifact raw
            JOIN learning_artifact ar ON ar.owner_id=raw.owner_id AND ar.id=raw.artifact_id
            JOIN learning_session s ON s.owner_id=raw.owner_id AND s.id=raw.session_id
            JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
            JOIN learning_action a ON a.owner_id=d.owner_id AND a.id=d.action_id
            JOIN learning_contract_version contract ON contract.owner_id=s.owner_id AND contract.delegation_id=s.delegation_id AND contract.version=s.contract_version
            JOIN learning_criterion_version cv ON cv.owner_id=contract.owner_id AND cv.id=contract.criterion_id
            LEFT JOIN learning_criterion_availability availability ON availability.owner_id=cv.owner_id AND availability.criterion_id=cv.id
            WHERE raw.owner_id=? AND d.outcome_id=? AND cv.outcome_id=d.outcome_id
              AND cv.context_key=? AND cv.review_status='approved' AND availability.criterion_id IS NULL
              AND ar.visibility='visible' AND raw.purged_at IS NULL AND raw.content IS NOT NULL
            ORDER BY raw.created_at DESC,raw.content_version DESC''', (owner, outcome_id, approved_standard()['source_context']))]

    def _available(self, c, owner, row):
        if row['purged_at']:
            raise DomainError('artifact_not_eligible', 409)
        source = c.execute('''SELECT ar.visibility,raw.content,raw.purged_at FROM learning_raw_artifact raw
            JOIN learning_artifact ar ON ar.owner_id=raw.owner_id AND ar.id=raw.artifact_id
            WHERE raw.owner_id=? AND raw.artifact_id=? AND raw.content_version=?''',
            (owner, row['source_artifact_id'], row['source_content_version'])).fetchone()
        if not source or source['visibility'] != 'visible' or source['purged_at'] or source['content'] is None:
            raise DomainError('delayed_source_unavailable', 409)

    @staticmethod
    def _package(row):
        package = json.loads(row['standard_snapshot_json'])
        if package != approved_standard():
            raise DomainError('delayed_standard_unavailable', 409)
        return package

    def _attempt(self, c, owner, follow_up_id, attempt_id):
        value = c.execute('SELECT * FROM learning_delayed_attempt WHERE owner_id=? AND follow_up_id=? AND id=?',
                          (owner, follow_up_id, attempt_id)).fetchone()
        if not value:
            raise DomainError('not_found', 404)
        return dict(value)

    def _audit(self, c, identity, operation, reference):
        self.learning.core._audit(c, Principal.user(identity['id']), operation, 'succeeded', reference)

    def _new_attempt(self, c, owner, follow_up_id, phase, now):
        c.execute('''INSERT OR IGNORE INTO learning_delayed_attempt
            (id,owner_id,follow_up_id,phase,answers_json,user_report,created_at) VALUES (?,?,?,?,?,'unknown',?)''',
            (str(uuid4()), owner, follow_up_id, phase, '{}', now))

    def _public(self, c, owner, row):
        available = True
        try:
            self._available(c, owner, row)
        except DomainError:
            available = False
        now = self.clock()
        result = {key: row[key] for key in ('id','outcome_id','delegation_id','source_artifact_id','source_content_version',
            'source_criterion_id','status','created_at','purged_at')}
        result.update(available=available, server_now=now, standard=public_standard(json.loads(row['standard_snapshot_json'])) if available else None,
            is_due=bool(available and row['due_at'] and instant(row['due_at']) <= instant(now)), items=[], active_attempt_id=None, attempts=[], comparison=None)
        for key in ('due_at','timezone','arranged_at','started_at'):
            result[key] = row[key] if available else None
        result['history'] = [{k:v for k,v in item.items() if k not in {'request_key','fingerprint'}}
                             for item in json.loads(row['history_json'] or '[]')] if available else []
        attempts = [dict(item) for item in c.execute('SELECT * FROM learning_delayed_attempt WHERE owner_id=? AND follow_up_id=? ORDER BY created_at,rowid', (owner,row['id']))]
        for attempt in attempts:
            item = {key: attempt[key] for key in ('id','phase','revision','submitted_at','check_status','checked_at','purged_at')}
            item.update(answers=json.loads(attempt['answers_json'] or '{}') if available and not attempt['submitted_at'] else None,
                user_report=attempt['user_report'] if available else None,
                condition=json.loads(attempt['condition_json'] or 'null') if available else None)
            result['attempts'].append(item)
            active = available and not attempt['submitted_at'] and ((attempt['phase']=='initial' and row['status']=='initial') or (attempt['phase']=='followup' and row['status']=='started'))
            if active:
                result['active_attempt_id'] = attempt['id']
                result['items'] = [{k:v for k,v in x.items() if k != 'expected'} for x in json.loads(row['standard_snapshot_json'])['banks'][attempt['phase']]]
        if available and len(attempts)==2 and all(a['submitted_at'] and a['check_status']=='succeeded' for a in attempts):
            initial, later = attempts
            elapsed = (instant(later['submitted_at'])-instant(initial['submitted_at'])).total_seconds()
            counts = [json.loads(a['result_json'])['correct'] for a in attempts]
            minimum = json.loads(row['standard_snapshot_json'])['minimum_interval_seconds']
            conditions = [json.loads(a['condition_json']) for a in attempts]
            assisted = any(x['user_report'] == 'used' or any(v['after_arranging'] for v in x['observed_views']) for x in conditions)
            unknown = any(x['user_report'] == 'unknown' for x in conditions)
            if elapsed < minimum:
                text = '实际间隔不足24小时，仅保留两次作答结果。'
            elif assisted:
                text = '存在自报帮助或安排后的资料提供或展示记录；分别查看相应帮助条件下的两次表现。'
            elif unknown:
                text = '帮助条件不确定；仅记录实际间隔和两次匹配判断表现。'
            elif counts == [8,8]:
                text = '在记录的间隔与条件下，两次同范围匹配判断均正确；自报未使用帮助，未独立核实。'
            else:
                text = '在记录的间隔内，两组匹配判断存在未答对项目；具体表现分别保留。'
            result['comparison'] = dict(interval_seconds=elapsed, minimum_interval_seconds=minimum, interval_met=elapsed>=minimum,
                initial_correct=counts[0],followup_correct=counts[1],description=text+' 不证明稳定掌握或迁移能力。')
        return result

    def for_outcome(self, identity, outcome_id):
        owner=self._owner(identity)
        with self.db.transaction() as c:
            sources=self._sources(c,owner,outcome_id)
            rows=c.execute('SELECT * FROM learning_delayed_follow_up WHERE owner_id=? AND outcome_id=? ORDER BY created_at DESC',(owner,outcome_id)).fetchall()
            return dict(standard=public_standard(approved_standard()),sources=sources,items=[self._public(c,owner,dict(row)) for row in rows])

    def due_list(self, identity):
        owner=self._owner(identity)
        with self.db.transaction() as c:
            rows=c.execute("SELECT * FROM learning_delayed_follow_up WHERE owner_id=? AND status IN ('scheduled','started') ORDER BY due_at",(owner,)).fetchall()
            items=[self._public(c,owner,dict(row)) for row in rows]
            return dict(items=[item for item in items if item['available']], server_now=self.clock())

    def get(self, identity, follow_up_id):
        owner=self._owner(identity)
        with self.db.transaction() as c:
            return self._public(c,owner,self._owned(c,owner,follow_up_id))

    def create(self, identity, outcome_id, payload: CreateFollowUp):
        owner=self._owner(identity)
        fingerprint=digest(dict(outcome_id=outcome_id,**payload.model_dump(exclude={'request_key'})))
        with self.db.transaction(immediate=True) as c:
            old=c.execute('SELECT * FROM learning_delayed_follow_up WHERE owner_id=? AND request_key=?',(owner,payload.request_key)).fetchone()
            if old:
                if old['purged_at']:
                    raise DomainError('artifact_not_eligible',409)
                if old['request_fingerprint']!=fingerprint:
                    raise DomainError('idempotency_conflict',409)
                return self._public(c,owner,dict(old))
            sources=self._sources(c,owner,outcome_id)
            source=next((s for s in sources if s['artifact_id']==payload.source_artifact_id and s['content_version']==payload.source_content_version),None)
            if source is None:
                raise DomainError('delayed_source_unavailable',409)
            old=c.execute('SELECT * FROM learning_delayed_follow_up WHERE owner_id=? AND outcome_id=? AND standard_id=?',
                          (owner,outcome_id,approved_standard()['id'])).fetchone()
            if old:
                return self._public(c,owner,dict(old))
            follow_up_id,now=str(uuid4()),self.clock()
            c.execute('''INSERT INTO learning_delayed_follow_up
                (id,owner_id,outcome_id,delegation_id,source_artifact_id,source_content_version,source_criterion_id,
                 standard_id,standard_snapshot_json,request_key,request_fingerprint,status,history_json,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,'initial','[]',?)''',
                (follow_up_id,owner,outcome_id,source['delegation_id'],source['artifact_id'],source['content_version'],source['criterion_id'],
                 approved_standard()['id'],canonical(approved_standard()),payload.request_key,fingerprint,now))
            self._new_attempt(c,owner,follow_up_id,'initial',now)
            self._audit(c,identity,'CreateDelayedFollowUp',follow_up_id)
            return self._public(c,owner,self._owned(c,owner,follow_up_id))

    def _answer(self, identity, follow_up_id, attempt_id, payload, submit):
        owner=self._owner(identity)
        with self.db.transaction(immediate=True) as c:
            row=self._owned(c,owner,follow_up_id)
            self._available(c,owner,row)
            package=self._package(row)
            attempt=self._attempt(c,owner,follow_up_id,attempt_id)
            fingerprint=digest(payload.model_dump(exclude={'request_key'}))
            if submit and attempt['submit_key']==payload.request_key:
                if fingerprint != attempt['submit_fingerprint']:
                    raise DomainError('idempotency_conflict',409)
                return self._public(c,owner,row)
            if attempt['submitted_at'] or attempt['revision']!=payload.revision:
                raise DomainError('delayed_stale_answer',409)
            if (attempt['phase']=='initial' and row['status']!='initial') or (attempt['phase']=='followup' and row['status']!='started'):
                raise DomainError('delayed_not_started',409)
            keys={item['id'] for item in package['banks'][attempt['phase']]}
            if not set(payload.answers).issubset(keys) or (submit and (set(payload.answers)!=keys or any(v is None for v in payload.answers.values()))):
                raise DomainError('delayed_incomplete_answer',422)
            now=self.clock()
            views=[dict(v) for v in c.execute('SELECT attempt_id,provided_at,displayed_at,after_arranging FROM learning_delayed_view WHERE owner_id=? AND follow_up_id=? AND purged_at IS NULL ORDER BY provided_at', (owner,follow_up_id))]
            for view in views:
                view['after_arranging']=bool(view['after_arranging'])
            condition=dict(user_report=payload.user_report, observed_views=views, independence='unverified')
            c.execute('''UPDATE learning_delayed_attempt SET answers_json=?,user_report=?,revision=revision+1,
                submitted_at=?,submit_key=?,submit_fingerprint=?,condition_json=? WHERE owner_id=? AND id=?''',
                (canonical(payload.answers),payload.user_report,now if submit else None,payload.request_key if submit else None,
                 fingerprint if submit else None,canonical(condition) if submit else None,owner,attempt_id))
            if submit:
                if attempt['phase']=='followup':
                    c.execute("UPDATE learning_delayed_follow_up SET status='completed' WHERE owner_id=? AND id=?",(owner,follow_up_id))
                self._audit(c,identity,'SubmitDelayedAnswer',attempt_id)
            return self._public(c,owner,self._owned(c,owner,follow_up_id))

    def draft(self,identity,follow_up_id,attempt_id,payload:DraftAnswer):
        return self._answer(identity,follow_up_id,attempt_id,payload,False)

    def submit(self,identity,follow_up_id,attempt_id,payload:SubmitAnswer):
        return self._answer(identity,follow_up_id,attempt_id,payload,True)

    def check(self,identity,follow_up_id,attempt_id):
        owner=self._owner(identity)
        with self.db.transaction(immediate=True) as c:
            row=self._owned(c,owner,follow_up_id)
            self._available(c,owner,row)
            attempt=self._attempt(c,owner,follow_up_id,attempt_id)
            if not attempt['submitted_at']:
                raise DomainError('delayed_not_submitted',409)
            if attempt['check_status']!='succeeded':
                try:
                    result=check_answers(self._package(row),attempt['phase'],json.loads(attempt['answers_json']))
                except (ValueError,KeyError,TypeError):
                    c.execute("UPDATE learning_delayed_attempt SET check_status='failed',checked_at=? WHERE owner_id=? AND id=?",(self.clock(),owner,attempt_id))
                else:
                    c.execute("UPDATE learning_delayed_attempt SET check_status='succeeded',result_json=?,checked_at=? WHERE owner_id=? AND id=?",(canonical(result),self.clock(),owner,attempt_id))
                    self._audit(c,identity,'CheckDelayedAnswer',attempt_id)
            return self._public(c,owner,row)

    def reveal(self,identity,follow_up_id,attempt_id):
        owner=self._owner(identity)
        with self.db.transaction(immediate=True) as c:
            row=self._owned(c,owner,follow_up_id)
            self._available(c,owner,row)
            attempt=self._attempt(c,owner,follow_up_id,attempt_id)
            if not attempt['submitted_at']:
                raise DomainError('delayed_not_submitted',409)
            view_id=str(uuid4())
            c.execute('INSERT INTO learning_delayed_view (id,owner_id,follow_up_id,attempt_id,provided_at,after_arranging) VALUES (?,?,?,?,?,?)',
                      (view_id,owner,follow_up_id,attempt_id,self.clock(),int(row['arranged_at'] is not None)))
            return dict(view_id=view_id,attempt_id=attempt_id,phase=attempt['phase'],answers=json.loads(attempt['answers_json']),
                items=[{k:v for k,v in item.items() if k != 'expected'} for item in self._package(row)['banks'][attempt['phase']]],
                result=json.loads(attempt['result_json'] or 'null'),condition=json.loads(attempt['condition_json']),submitted_at=attempt['submitted_at'])

    def display(self,identity,follow_up_id,view_id):
        owner=self._owner(identity)
        with self.db.transaction(immediate=True) as c:
            follow_up=self._owned(c,owner,follow_up_id)
            self._available(c,owner,follow_up)
            row=c.execute('SELECT * FROM learning_delayed_view WHERE owner_id=? AND follow_up_id=? AND id=?',(owner,follow_up_id,view_id)).fetchone()
            if row is None:
                raise DomainError('not_found',404)
            when=row['displayed_at'] or self.clock()
            c.execute('UPDATE learning_delayed_view SET displayed_at=?,after_arranging=? WHERE owner_id=? AND id=?',
                      (when,int(bool(row['after_arranging']) or (not row['displayed_at'] and follow_up['arranged_at'] is not None)),owner,view_id))
            return dict(id=view_id,displayed_at=when)

    def _history(self,row,key,payload):
        history=json.loads(row['history_json'] or '[]')
        fingerprint=digest(payload)
        previous=next((item for item in history if item['request_key']==key),None)
        if previous and previous['fingerprint']!=fingerprint:
            raise DomainError('idempotency_conflict',409)
        return history,fingerprint,previous is not None

    def schedule(self,identity,follow_up_id,payload:ScheduleFollowUp):
        owner=self._owner(identity)
        due=instant(payload.due_at)
        try:
            ZoneInfo(payload.timezone)
        except (ValueError,ZoneInfoNotFoundError):
            raise DomainError('delayed_invalid_time',422)
        with self.db.transaction(immediate=True) as c:
            row=self._owned(c,owner,follow_up_id)
            self._available(c,owner,row)
            history,fingerprint,replay=self._history(row,payload.request_key,dict(operation='schedule',due_at=stamp(due),timezone=payload.timezone))
            if replay:
                return self._public(c,owner,row)
            initial=c.execute("SELECT * FROM learning_delayed_attempt WHERE owner_id=? AND follow_up_id=? AND phase='initial'",(owner,follow_up_id)).fetchone()
            if row['status']=='completed' or not initial['submitted_at'] or initial['check_status']!='succeeded':
                raise DomainError('delayed_schedule_unavailable',409)
            now=self.clock()
            minimum=self._package(row)['minimum_interval_seconds']
            if due<=instant(now) or due<instant(initial['submitted_at'])+timedelta(seconds=minimum):
                raise DomainError('delayed_too_early',422)
            history.append(dict(operation='schedule',request_key=payload.request_key,fingerprint=fingerprint,at=now,due_at=stamp(due),timezone=payload.timezone))
            c.execute("UPDATE learning_delayed_follow_up SET status='scheduled',due_at=?,timezone=?,arranged_at=COALESCE(arranged_at,?),history_json=? WHERE owner_id=? AND id=?",
                      (stamp(due),payload.timezone,now,canonical(history),owner,follow_up_id))
            self._audit(c,identity,'ScheduleDelayedFollowUp',follow_up_id)
            return self._public(c,owner,self._owned(c,owner,follow_up_id))

    def choose(self,identity,follow_up_id,payload:ChooseFollowUp):
        owner=self._owner(identity)
        with self.db.transaction(immediate=True) as c:
            row=self._owned(c,owner,follow_up_id)
            self._available(c,owner,row)
            history,fingerprint,replay=self._history(row,payload.request_key,dict(operation=payload.choice))
            if replay:
                return self._public(c,owner,row)
            now=self.clock()
            if payload.choice=='start':
                if row['status']=='started':
                    return self._public(c,owner,row)
                if row['status']!='scheduled' or instant(row['due_at'])>instant(now):
                    raise DomainError('delayed_not_due',409)
                self._new_attempt(c,owner,follow_up_id,'followup',now)
                c.execute("UPDATE learning_delayed_follow_up SET status='started',started_at=COALESCE(started_at,?) WHERE owner_id=? AND id=?",(now,owner,follow_up_id))
            else:
                if row['status']=='skipped':
                    return self._public(c,owner,row)
                if row['status'] not in {'scheduled','started'}:
                    raise DomainError('delayed_schedule_unavailable',409)
                c.execute("UPDATE learning_delayed_follow_up SET status='skipped' WHERE owner_id=? AND id=?",(owner,follow_up_id))
            history.append(dict(operation=payload.choice,request_key=payload.request_key,fingerprint=fingerprint,at=now))
            c.execute('UPDATE learning_delayed_follow_up SET history_json=? WHERE owner_id=? AND id=?',(canonical(history),owner,follow_up_id))
            self._audit(c,identity,'ChooseDelayedFollowUp',follow_up_id)
            return self._public(c,owner,self._owned(c,owner,follow_up_id))

    def purge(self,identity,follow_up_id):
        owner=self._owner(identity)
        with self.db.transaction(immediate=True) as c:
            row=self._owned(c,owner,follow_up_id)
            if not row['purged_at']:
                c.execute('UPDATE learning_delayed_follow_up SET purged_at=? WHERE owner_id=? AND id=?',(self.clock(),owner,follow_up_id))
            return self._public(c,owner,self._owned(c,owner,follow_up_id))
