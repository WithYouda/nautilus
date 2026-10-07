"""Clock-driven reminders: current facts decide eligibility, never an AI call."""
import json
import re
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .core.events import digest
from .core.learning import utc_timestamp
from .core.commitment_commands import valid_zone
from .goal_lifecycle import OPEN_GOAL_STATUSES
from .learning_domain import DomainError


def parse(value): return datetime.fromisoformat(value.replace('Z','+00:00'))
def iso(value): return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')


class StudyTime(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(min_length=1,max_length=100)
    weekdays:list[int]=Field(min_length=1,max_length=7)
    time:str
    @model_validator(mode='after')
    def valid(self):
        if len(set(self.weekdays))!=len(self.weekdays) or any(v<1 or v>7 for v in self.weekdays) or not clock_valid(self.time): raise ValueError('invalid study time')
        return self


def clock_valid(value): return bool(re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value))


class ReminderSettings(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled:bool=False
    timezone:str='UTC'
    browser_enabled:bool=False
    followup_enabled:bool=True
    quiet_enabled:bool=True
    study_times:list[StudyTime]=Field(default_factory=list,max_length=14)
    followup_delay_minutes:int=Field(default=30,ge=1,le=1440)
    max_per_day:int=Field(default=2,ge=1,le=100)
    quiet_start:str='22:00'
    quiet_end:str='08:00'
    @model_validator(mode='after')
    def valid(self):
        valid_zone(self.timezone)
        if not clock_valid(self.quiet_start) or not clock_valid(self.quiet_end) or self.quiet_enabled and self.quiet_start==self.quiet_end: raise ValueError('invalid quiet time')
        ids=set();slots=set()
        for item in self.study_times:
            if item.id in ids: raise ValueError('duplicate study time')
            ids.add(item.id)
            for day in item.weekdays:
                pair=(day,item.time)
                if pair in slots: raise ValueError('duplicate study time')
                slots.add(pair)
        return self


def current_items(c, owner):
    """Effective committed placements; immutable versions only supply estimates."""
    result=[];ordering={}
    for row in c.execute('''SELECT i.*,p.status AS plan_status,p.created_at AS plan_created_at,g.status AS goal_status,g.version AS goal_version,
        a.title,a.status AS action_status,a.version AS action_version,d.status AS delegation_status,
        ps.status AS path_status,ps.adopted_version_id,cs.current_version_id,cs.revision AS commitment_revision
        FROM learning_commitment_item i JOIN learning_plan p ON p.owner_id=i.owner_id AND p.id=i.plan_id
        LEFT JOIN learning_goal g ON g.owner_id=p.owner_id AND g.id=p.goal_id
        JOIN learning_action a ON a.owner_id=i.owner_id AND a.id=i.action_id
        JOIN learning_delegation d ON d.owner_id=i.owner_id AND d.id=i.delegation_id
        JOIN learning_plan_path_state ps ON ps.owner_id=i.owner_id AND ps.plan_id=i.plan_id
        JOIN learning_plan_commitment_state cs ON cs.owner_id=i.owner_id AND cs.plan_id=i.plan_id
        WHERE i.owner_id=? AND NOT EXISTS(SELECT 1 FROM learning_action_removal r WHERE r.owner_id=i.owner_id AND r.action_id=i.action_id)
        ORDER BY i.created_at,i.id''',(owner,)).fetchall():
        value=dict(row)
        if value['plan_status']!='active' or value['goal_status'] and value['goal_status'] not in OPEN_GOAL_STATUSES or value['path_status']=='paused': continue
        if value['action_status']!='open' or value['delegation_status'] not in {'ready','active'}: continue
        if value['status'] not in {'planned','started','deferred'} or value['route_version_id']!=value['adopted_version_id']: continue
        version=c.execute('SELECT data_json,purged_at FROM learning_commitment_version WHERE owner_id=? AND id=?',(owner,value['current_version_id'])).fetchone()
        if not version or version['purged_at']: continue
        version_items=json.loads(version['data_json'])
        original=next((item for item in version_items if item['id']==value['id']),None)
        if not original: continue
        ordering[value['id']]=(value['plan_created_at'],value['plan_id'],next(index for index,item in enumerate(version_items) if item['id']==value['id']))
        value['estimate_min_minutes']=original['estimate_min_minutes'];value['estimate_max_minutes']=original['estimate_max_minutes']
        # A direct task session also represents real learning, even without an item execution.
        value['execution_started']=bool(c.execute('''SELECT 1 FROM learning_commitment_execution x
            JOIN learning_session s ON s.owner_id=x.owner_id AND s.id=x.session_id
            WHERE x.owner_id=? AND x.item_id=? AND x.due_at IS ? LIMIT 1''',(owner,value['id'],value['future_due_at'])).fetchone())
        value['running']=bool(c.execute("SELECT 1 FROM learning_session WHERE owner_id=? AND delegation_id=? AND status='running' LIMIT 1",(owner,value['delegation_id'])).fetchone())
        value['begun']=value['execution_started'] or value['running'] or bool(c.execute('''SELECT 1 FROM learning_session
            WHERE owner_id=? AND delegation_id=? AND julianday(started_at)>=julianday(?) LIMIT 1''',
            (owner,value['delegation_id'],value['updated_at'])).fetchone())
        result.append({key:value[key] for key in ('id','plan_id','action_id','delegation_id','title','status','future_due_at','future_timezone',
            'action_version','goal_version','commitment_revision','estimate_min_minutes','estimate_max_minutes','running','begun','execution_started')})
    result.sort(key=lambda item:ordering[item['id']])
    return result


class CoachReminders:
    def __init__(self, learning, *, clock=utc_timestamp):
        self.learning,self.db,self.clock=learning,learning.database,clock

    def _owner(self, identity): return self.learning.principal(identity).owner_id
    def settings(self, identity):
        owner=self._owner(identity)
        with self.db._lock: return self._settings(self.db.connection,owner)
    def _settings(self,c,owner):
        row=c.execute('SELECT * FROM learning_coach_reminder_settings WHERE owner_id=?',(owner,)).fetchone()
        values=json.loads(row['settings_json']) if row else ReminderSettings().model_dump(mode='json')
        values.pop('activated_at',None)
        return {'revision':row['revision'] if row else 0,**values}

    def save(self,identity,settings,expected_revision,key):
        owner=self._owner(identity);data=ReminderSettings.model_validate(settings).model_dump(mode='json');fingerprint=digest({'settings':data,'revision':expected_revision})
        with self.db.transaction(immediate=True) as c:
            previous=c.execute("SELECT * FROM learning_coach_request WHERE owner_id=? AND scope='reminder_settings' AND request_key=?",(owner,key)).fetchone()
            if previous:
                if previous['fingerprint']!=fingerprint: raise DomainError('idempotency_conflict')
                return {'settings':self._settings(c,owner)}
            old=self._settings(c,owner)
            if old['revision']!=expected_revision: raise DomainError('version_conflict')
            if data['enabled'] and not data['study_times'] and not any(i['future_due_at'] for i in current_items(c,owner)): raise DomainError('coach_reminder_time_required',422)
            now=self.clock()
            old_row=c.execute('SELECT settings_json,updated_at FROM learning_coach_reminder_settings WHERE owner_id=?',(owner,)).fetchone()
            activated=(json.loads(old_row['settings_json']).get('activated_at',old_row['updated_at']) if old_row else now) if old['enabled'] and data['enabled'] else now
            stored={**data,'activated_at':activated}
            c.execute('INSERT INTO learning_coach_reminder_settings VALUES (?,?,?,?) ON CONFLICT(owner_id) DO UPDATE SET revision=excluded.revision,settings_json=excluded.settings_json,updated_at=excluded.updated_at',
                (owner,old['revision']+1,json.dumps(stored),now))
            c.execute('INSERT INTO learning_coach_request VALUES (?,\'reminder_settings\',?,?,NULL,?)',(owner,key,fingerprint,now))
            # Unsent occurrences are recomputed; dispatch history and its budget stay durable.
            c.execute("UPDATE learning_coach_reminder SET status='unavailable',reason='settings_changed',revision=revision+1 WHERE owner_id=? AND status='pending'",(owner,))
            return {'settings':self._settings(c,owner)}

    def _quiet(self, settings, now):
        local=now.astimezone(ZoneInfo(settings['timezone']));clock=local.strftime('%H:%M')
        start,end=settings['quiet_start'],settings['quiet_end']
        return settings['quiet_enabled'] and (start<=clock<end if start<end else clock>=start or clock<end)

    def _budget(self,c,owner,settings,now):
        row=c.execute('SELECT * FROM learning_coach_reminder_budget WHERE owner_id=?',(owner,)).fetchone()
        local=now.astimezone(ZoneInfo(settings['timezone']))
        if row and now<parse(row['window_end']): used=row['used_count'];start=row['window_start'];end=row['window_end']
        else:
            start=iso(local.replace(hour=0,minute=0,second=0,microsecond=0));end=iso((local+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0))
            used=c.execute('SELECT COUNT(*) FROM learning_coach_reminder WHERE owner_id=? AND dispatched_at>=? AND dispatched_at<?',(owner,start,end)).fetchone()[0]
        return {'used_today':used,'remaining_today':max(0,settings['max_per_day']-used),'local_date':local.date().isoformat()},start,end

    @staticmethod
    def _begun(item,due):
        # A previous, already-ended block before the new occurrence is not this start.
        return item['begun']

    def _source(self, items, scheduled, fixed=False):
        eligible=[i for i in items if not i['running'] and
            (fixed and (i['begun'] or not i['future_due_at'] or parse(i['future_due_at'])<=scheduled) or
             not fixed and i['future_due_at'] and parse(i['future_due_at'])==scheduled and not i['begun'])]
        selected=eligible[0] if eligible else None
        if selected: return {'kind':'item','id':selected['id'],'due_at':selected['future_due_at'],'fixed':fixed,'mode':'resume' if selected['begun'] else 'start',
            'revision':digest({k:v for k,v in selected.items() if k not in {'title','sessions'}})}
        return {'kind':'coach','fixed':True} if fixed else None

    def _valid_source(self,source,items):
        if source['kind']=='coach': return True
        item=next((i for i in items if i['id']==source['id']),None)
        return bool(item and item['future_due_at']==source['due_at'] and not item['running']
            and (item['begun'] if source.get('mode')=='resume' else not item['begun'])
            and source['revision']==digest({k:v for k,v in item.items() if k not in {'title','sessions'}}))

    def _sync(self,c,owner,settings,now):
        items=current_items(c,owner)
        active=bool(c.execute("SELECT 1 FROM learning_session WHERE owner_id=? AND status='running' LIMIT 1",(owner,)).fetchone())
        quiet=self._quiet(settings,now)
        for row in c.execute("SELECT * FROM learning_coach_reminder WHERE owner_id=? AND status IN ('pending','dispatched')",(owner,)).fetchall():
            if (not settings['enabled'] or not self._valid_source(json.loads(row['source_json']),items)
                or row['stage']=='followup' and not settings['followup_enabled']
                or row['status']=='pending' and row['settings_revision']!=settings['revision']):
                c.execute("UPDATE learning_coach_reminder SET status='unavailable',reason='source_changed',revision=revision+1 WHERE id=?",(row['id'],))
        if not settings['enabled']: return items,active,quiet
        local=now.astimezone(ZoneInfo(settings['timezone']));settings_row=c.execute('SELECT settings_json,updated_at FROM learning_coach_reminder_settings WHERE owner_id=?',(owner,)).fetchone()
        activated=parse(json.loads(settings_row['settings_json']).get('activated_at',settings_row['updated_at']))
        schedule={}
        for item in items:
            if item['future_due_at']:
                due=parse(item['future_due_at'])
                if due<=now+timedelta(days=1): schedule.setdefault(iso(due),False)
        for day_offset in (-1,0,1):
            day=local+timedelta(days=day_offset)
            for slot in settings['study_times']:
                if day.isoweekday() not in slot['weekdays']: continue
                hour,minute=map(int,slot['time'].split(':'));due=day.replace(hour=hour,minute=minute,second=0,microsecond=0)
                if due.astimezone(timezone.utc)>=activated: schedule[iso(due)]=True
        for scheduled,fixed in sorted(schedule.items()):
            due=parse(scheduled);source=self._source(items,due,fixed)
            if source is None: continue
            occurrence=digest({'owner':owner,'scheduled_at':scheduled})
            for stage,when in [('initial',due),('followup',due+timedelta(minutes=settings['followup_delay_minutes']))]:
                if stage=='followup':
                    if not settings['followup_enabled'] or source['kind']=='coach' or source.get('mode')=='resume': continue
                    first=c.execute("SELECT dispatched_at,source_json,status FROM learning_coach_reminder WHERE owner_id=? AND occurrence_key=? AND stage IN ('initial','quiet_digest')",(owner,occurrence)).fetchone()
                    if not first or not first[0] or first['status']!='dispatched' or json.loads(first['source_json'])!=source: continue
                    when=parse(first[0])+timedelta(minutes=settings['followup_delay_minutes'])
                existing=c.execute('SELECT * FROM learning_coach_reminder WHERE owner_id=? AND occurrence_key=? AND stage=?',(owner,occurrence,stage)).fetchone()
                if existing:
                    if existing['dispatched_at'] is None and existing['status'] in {'pending','unavailable'} and (existing['source_revision']!=digest(source) or existing['settings_revision']!=settings['revision']):
                        c.execute("UPDATE learning_coach_reminder SET status='pending',source_json=?,source_revision=?,settings_revision=?,scheduled_at=?,reason=NULL,revision=revision+1 WHERE id=?",
                            (json.dumps(source),digest(source),settings['revision'],iso(when),existing['id']))
                    continue
                identifier=str(uuid5(NAMESPACE_URL,owner+':'+occurrence+':'+stage))
                c.execute('INSERT INTO learning_coach_reminder VALUES (?,?,?,?,1,\'pending\',?,NULL,?,?,?,NULL,?)',
                    (identifier,owner,occurrence,stage,iso(when),json.dumps(source),digest(source),settings['revision'],iso(now)))
        # Ordinary nudges during active learning are consumed, not queued for a later interruption.
        if active:
            c.execute("UPDATE learning_coach_reminder SET status='suppressed',reason='learning_active',revision=revision+1 WHERE owner_id=? AND status='pending' AND scheduled_at<=?",(owner,iso(now)))
        return items,active,quiet

    def _public(self,row,items):
        value=dict(row);source=json.loads(value['source_json']);item=next((i for i in items if source.get('id')==i['id']),None)
        if value['status']=='unavailable' or source['kind']=='item' and item is None:
            target={'kind':'commitment_item','plan_id':None,'action_id':None,'delegation_id':None,'item_id':source.get('id'),'href':'','label':'当前不可用'}
            title='这条提醒已失效';body='安排或学习状态已经变化。'
        elif item:
            from urllib.parse import urlencode
            target={'kind':'commitment_item','plan_id':item['plan_id'],'action_id':item['action_id'],'delegation_id':item['delegation_id'],'item_id':item['id'],
                'href':'?'+urlencode({'view':'plans','plan':item['plan_id'],'plan_view':'commitments','item':item['id']}),'label':'查看安排'}
            if source.get('mode')=='resume':
                title='继续上次的学习：'+item['title'];body='这项学习还没有完成，可以接着上次的小步骤继续。'
            else:
                title='该开始：'+item['title'];body='可以先开始一小步。' if value['stage']!='followup' else '这项学习还没有开始，可以先做一点，或核对当前安排。'
        else:
            target={'kind':'coach','plan_id':None,'action_id':None,'delegation_id':None,'item_id':None,'href':'?view=home&coach=1','label':'打开教练'}
            title='到学习时间了';body='今天想从哪里开始？可以先和教练安排下一步。'
        return {k:value[k] for k in ('id','revision','occurrence_key','stage','status','scheduled_at','dispatched_at','source_revision','reason')} | {'title':title,'body':body,'target':target}

    def _view(self,c,owner,settings,now,items,active,quiet):
        rows=c.execute("SELECT * FROM learning_coach_reminder WHERE owner_id=? AND status='pending' ORDER BY scheduled_at,id",(owner,)).fetchall()
        budget,_,_=self._budget(c,owner,settings,now)
        due=[r for r in rows if parse(r['scheduled_at'])<=now]
        # After quiet hours merge current due reminders into one display; dispatch retires the rest.
        if quiet or active or not settings['enabled'] or not budget['remaining_today']: due=[]
        recent=c.execute("SELECT * FROM learning_coach_reminder WHERE owner_id=? AND dispatched_at IS NOT NULL ORDER BY dispatched_at DESC LIMIT 10",(owner,)).fetchall()
        return {'settings':settings,'due':[self._public(r,items) for r in due[:1]],'recent':[self._public(r,items) for r in recent],
            'learning_active':active,'quiet_now':quiet,'budget':budget,'next_due_at':rows[0]['scheduled_at'] if rows else None,
            'revision':digest([settings,[(r['id'],r['revision']) for r in rows],budget,active,quiet])}

    def view(self,identity):
        owner=self._owner(identity);now=parse(self.clock())
        with self.db.transaction(immediate=True) as c:
            settings=self._settings(c,owner);items,active,quiet=self._sync(c,owner,settings,now)
            return self._view(c,owner,settings,now,items,active,quiet)

    def dispatch(self,identity,identifier,expected_revision,key):
        owner=self._owner(identity);now=parse(self.clock());fingerprint=digest({'id':identifier,'revision':expected_revision})
        with self.db.transaction(immediate=True) as c:
            settings=self._settings(c,owner);items,active,quiet=self._sync(c,owner,settings,now)
            row=c.execute('SELECT * FROM learning_coach_reminder WHERE owner_id=? AND id=?',(owner,identifier)).fetchone()
            if not row: raise DomainError('not_found',404)
            previous=c.execute("SELECT * FROM learning_coach_request WHERE owner_id=? AND scope='dispatch' AND request_key=?",(owner,key)).fetchone()
            if previous and previous['fingerprint']!=fingerprint: raise DomainError('idempotency_conflict')
            budget,start,end=self._budget(c,owner,settings,now)
            reason='already_dispatched' if previous or row['status']!='pending' else 'source_changed' if row['revision']!=expected_revision else 'disabled' if not settings['enabled'] else 'learning_active' if active else 'quiet' if quiet else 'day_limit' if not budget['remaining_today'] else 'not_due' if parse(row['scheduled_at'])>now else None
            if reason is None:
                c.execute("UPDATE learning_coach_reminder SET status='dispatched',dispatched_at=?,revision=revision+1 WHERE id=?",(iso(now),identifier))
                c.execute('INSERT INTO learning_coach_reminder_budget VALUES (?,?,?,?) ON CONFLICT(owner_id) DO UPDATE SET window_start=excluded.window_start,window_end=excluded.window_end,used_count=excluded.used_count',
                    (owner,start,end,budget['used_today']+1))
                # A single current digest, not a burst of past notices after absence/quiet hours.
                c.execute("UPDATE learning_coach_reminder SET status='suppressed',reason='merged',revision=revision+1 WHERE owner_id=? AND id<>? AND status='pending' AND scheduled_at<=?",(owner,identifier,iso(now)))
            if not previous:
                c.execute('INSERT INTO learning_coach_request VALUES (?,\'dispatch\',?,?,?,?)',(owner,key,fingerprint,identifier,iso(now)))
            row=c.execute('SELECT * FROM learning_coach_reminder WHERE id=?',(identifier,)).fetchone()
            return {'reminder':self._public(row,items),'claimed':reason is None,'reason':reason,'view':self._view(c,owner,settings,now,items,active,quiet)}

    def resolve(self,identity,identifier,source_revision):
        owner=self._owner(identity)
        with self.db.transaction(immediate=True) as c:
            settings=self._settings(c,owner);items,_,_=self._sync(c,owner,settings,parse(self.clock()))
            row=c.execute('SELECT * FROM learning_coach_reminder WHERE owner_id=? AND id=?',(owner,identifier)).fetchone()
            if not row: raise DomainError('not_found',404)
            if not settings['enabled'] or row['status']=='unavailable' or row['source_revision']!=source_revision or not self._valid_source(json.loads(row['source_json']),items): raise DomainError('coach_source_unavailable')
            return {'target':self._public(row,items)['target']}
