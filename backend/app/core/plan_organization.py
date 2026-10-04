"""D2 organization decisions and replay. Original facts keep their identities."""
import hashlib
import json
from uuid import uuid4

from ..learning_domain import DomainError, LearningRepository
from ..goal_lifecycle import OPEN_GOAL_STATUSES
from .commands import CreateLearningAction, CreateOutcome, CreateDelegation
from .events import append_event, canonical, digest
from .outcome_graph import owned
from .organization_commands import (CreatePlan, CreateModule, ReviseModule, PlaceTask,
    OrderChildren, CreatePlanTask, RemovePlanTask, PurgePlanContent, PurgeModuleContent)

CLEARED_TITLE = '内容已清除'


def revision(connection, owner, plan_id):
    # Old-schema synthetic upgrade fixtures can still exercise legacy setup.
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='learning_plan_organization'").fetchone():
        return 0
    row = connection.execute('SELECT revision FROM learning_plan_organization WHERE owner_id=? AND plan_id=?',
                             (owner, plan_id)).fetchone()
    return row['revision'] if row else 0


def require_plan(connection, owner, plan_id, *, writable=True):
    plan = owned(connection, owner, 'learning_plan', plan_id)
    if writable:
        if plan['status'] != 'active':
            raise DomainError('plan_not_active')
        if plan['goal_id'] and owned(connection, owner, 'learning_goal', plan['goal_id'])['status'] not in OPEN_GOAL_STATUSES:
            raise DomainError('goal_not_active')
    return plan


def require_module(connection, owner, plan_id, module_id):
    if module_id is None:
        return
    module = owned(connection, owner, 'learning_module', module_id)
    if module['plan_id'] != plan_id:
        raise DomainError('not_found', 404)
    return module


def _private_key(kind, object_id):
    return kind + ':' + object_id


def private_payload(entries, org_revision):
    bodies = {_private_key(kind, object_id): fields for kind, object_id, fields in entries}
    refs = [{'kind':kind, 'id':object_id, 'revision':org_revision, 'hash':digest(fields)}
            for kind, object_id, fields in entries]
    return {'private_refs':refs, 'content':canonical(bodies)} if entries else {}


def read_private(connection, owner, kind, object_id, private_revision):
    if connection.execute('SELECT 1 FROM learning_plan_private_tombstone WHERE owner_id=? AND kind=? AND object_id=?',
                          (owner, kind, object_id)).fetchone():
        return None
    row = connection.execute('SELECT * FROM learning_plan_private WHERE owner_id=? AND kind=? AND object_id=? AND revision=?',
                             (owner, kind, object_id, private_revision)).fetchone()
    if row is None:
        raise DomainError('organization_source_missing')
    if row['purged_at'] or row['content_json'] is None:
        return None
    if hashlib.sha256(row['content_json'].encode()).hexdigest() != row['content_hash']:
        raise DomainError('event_integrity_failed')
    return json.loads(row['content_json'])


def _store_private(connection, event, payload):
    bodies = json.loads(event['_private_content']) if '_private_content' in event else None
    if bodies is not None and hashlib.sha256(event['_private_content'].encode()).hexdigest() != payload.get('content_hash'):
        raise DomainError('event_integrity_failed')
    for ref in payload.get('private_refs', []):
        kind, object_id, value = ref['kind'], ref['id'], ref['revision']
        if kind not in {'plan', 'module'} or value != event['aggregate_version']:
            raise DomainError('event_scope_invalid')
        row = connection.execute('SELECT * FROM learning_plan_private WHERE owner_id=? AND kind=? AND object_id=? AND revision=?',
                                 (event['owner_id'], kind, object_id, value)).fetchone()
        if row:
            if row['event_id'] != event['event_id']:
                raise DomainError('event_scope_invalid')
            actual = read_private(connection, event['owner_id'], kind, object_id, value)
            if actual is not None and digest(actual) != ref['hash']:
                raise DomainError('event_integrity_failed')
            continue
        if bodies is None:
            raise DomainError('organization_source_missing')
        body = bodies.get(_private_key(kind, object_id))
        if body is None or digest(body) != ref['hash'] or not isinstance(body.get('title'), str) or not body['title'].strip():
            raise DomainError('event_integrity_failed')
        if connection.execute('SELECT 1 FROM learning_plan_private_tombstone WHERE owner_id=? AND kind=? AND object_id=?',
                              (event['owner_id'], kind, object_id)).fetchone():
            raise DomainError('organization_content_purged')
        connection.execute('INSERT INTO learning_plan_private VALUES (?,?,?,?,?,?,?,NULL)',
                           (event['owner_id'], kind, object_id, value, event['event_id'], canonical(body), ref['hash']))


def _fields(connection, owner, kind, object_id, value):
    return read_private(connection, owner, kind, object_id, value) or {'title':CLEARED_TITLE, 'description':''}


def removed_task_ids(connection, owner, plan_id=None):
    # Retained older schema snapshots have no administrative removal records.
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='learning_action_removal'").fetchone():
        return set()
    if plan_id is None:
        return {row['action_id'] for row in connection.execute(
            'SELECT action_id FROM learning_action_removal WHERE owner_id=?', (owner,))}
    return {row['action_id'] for row in connection.execute(
        'SELECT action_id FROM learning_action_removal WHERE owner_id=? AND plan_id=?', (owner,plan_id))}


def children(connection, owner, plan_id):
    removed = removed_task_ids(connection,owner,plan_id)
    if revision(connection, owner, plan_id):
        return [dict(row) for row in connection.execute('''SELECT kind,child_id AS id,parent_module_id,position
            FROM learning_plan_child WHERE owner_id=? AND plan_id=? ORDER BY COALESCE(parent_module_id,''),position,kind,child_id''',
            (owner, plan_id)) if row['kind']!='task' or row['id'] not in removed]
    # This is today's deterministic compatibility view, not a historical move.
    members = [dict(kind='module', id=row['id'], parent_module_id=row['parent_module_id'], created_at=row['created_at'])
        for row in connection.execute('SELECT * FROM learning_module WHERE owner_id=? AND plan_id=?', (owner,plan_id))]
    members += [dict(kind='task', id=row['action_id'], parent_module_id=row['module_id'], created_at=row['created_at'])
        for row in connection.execute('SELECT * FROM learning_action_link WHERE owner_id=? AND plan_id=?', (owner,plan_id))
        if row['action_id'] not in removed]
    result, counts = [], {}
    for item in sorted(members, key=lambda row:(row['created_at'],row['id'],row['kind'])):
        parent = item['parent_module_id']
        result.append({key:item[key] for key in ('kind','id','parent_module_id')} | {'position':counts.get(parent,0)})
        counts[parent] = counts.get(parent,0) + 1
    return result


def _validate_children(connection, owner, plan_id, state):
    modules = {row['id'] for row in connection.execute('SELECT id FROM learning_module WHERE owner_id=? AND plan_id=?', (owner,plan_id))}
    tasks = {row['action_id'] for row in connection.execute('SELECT action_id FROM learning_action_link WHERE owner_id=? AND plan_id=?', (owner,plan_id))}
    tasks -= removed_task_ids(connection,owner,plan_id)
    expected = {('module',item) for item in modules} | {('task',item) for item in tasks}
    keys = [(row.get('kind'),row.get('id')) for row in state]
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise DomainError('organization_members_changed')
    parents, positions = {}, {}
    for row in state:
        parent, position = row.get('parent_module_id'), row.get('position')
        if parent is not None and parent not in modules:
            raise DomainError('event_scope_invalid')
        if isinstance(position, bool) or not isinstance(position,int) or position < 0:
            raise DomainError('event_scope_invalid')
        positions.setdefault(parent,[]).append(position)
        if row['kind'] == 'module':
            parents[row['id']] = parent
    if any(sorted(values) != list(range(len(values))) for values in positions.values()):
        raise DomainError('organization_order_invalid', 422)
    for module in modules:
        seen, current = set(), module
        while current is not None:
            if current in seen:
                raise DomainError('organization_module_cycle', 422)
            seen.add(current)
            current = parents[current]


def _write_children(connection, owner, plan_id, state):
    _validate_children(connection, owner, plan_id, state)
    connection.execute('DELETE FROM learning_plan_child WHERE owner_id=? AND plan_id=?', (owner,plan_id))
    for row in state:
        connection.execute('INSERT INTO learning_plan_child VALUES (?,?,?,?,?,?)',
                           (owner,plan_id,row['kind'],row['id'],row['parent_module_id'],row['position']))
        if row['kind'] == 'module':
            connection.execute('UPDATE learning_module SET parent_module_id=?,position=? WHERE owner_id=? AND id=?',
                               (row['parent_module_id'],row['position'],owner,row['id']))
        else:
            connection.execute('UPDATE learning_action_link SET module_id=? WHERE owner_id=? AND action_id=?',
                               (row['parent_module_id'],owner,row['id']))


def _normalized(state):
    result, counts = [], {}
    for row in sorted(state, key=lambda value:(value['parent_module_id'] or '',value['position'],value['kind'],value['id'])):
        parent = row['parent_module_id']
        result.append({**row, 'position':counts.get(parent,0)})
        counts[parent] = counts.get(parent,0) + 1
    return result


def _append_child(state, kind, object_id, parent):
    position = max([row['position'] for row in state if row['parent_module_id']==parent], default=-1) + 1
    return _normalized([*state, dict(kind=kind,id=object_id,parent_module_id=parent,position=position)])


def _event(connection, principal, command_id, key, now, plan_id, event_type, payload):
    return append_event(connection, principal, command_id=command_id, key=key, now=now,
        aggregate_type='plan_organization', aggregate_id=plan_id,
        expected_version=revision(connection,principal.owner_id,plan_id), event_type=event_type,
        payload={'id':plan_id, **payload})


def initialize(connection, principal, command_id, key, now, plan_id, new_plan=None):
    owner = principal.owner_id
    if revision(connection,owner,plan_id):
        return
    cutoff = connection.execute('SELECT COALESCE(MAX(position),0) FROM learning_event').fetchone()[0]
    modules = [dict(row) for row in connection.execute('SELECT * FROM learning_module WHERE owner_id=? AND plan_id=?', (owner,plan_id))] if not new_plan else []
    links = [dict(row) for row in connection.execute('SELECT * FROM learning_action_link WHERE owner_id=? AND plan_id=?', (owner,plan_id))] if not new_plan else []
    entries = [('module',row['id'],{'title':row['title'],'description':row['description']}) for row in modules]
    if new_plan:
        entries.append(('plan',plan_id,{'title':new_plan['title'],'description':new_plan['description']}))
    payload = {'cutoff_position':cutoff, 'modules':[{name:row[name] for name in
        ('id','parent_module_id','position','status','created_at','updated_at')} for row in modules],
        'tasks':[{'id':row['action_id'],'created_at':row['created_at']} for row in links],
        'children':children(connection,owner,plan_id) if not new_plan else [], **private_payload(entries,1)}
    if new_plan:
        payload['new_plan'] = {'goal_id':new_plan['goal_id'], 'status':'active'}
    _event(connection,principal,command_id,key,now,plan_id,'organization.initialized',payload)


def append_task(connection, principal, command_id, key, now, plan_id, action_id, delegation_id, outcome_id, *, existing_link=False):
    state = children(connection,principal.owner_id,plan_id)
    if existing_link:
        # Existing organization does not yet contain the newly linked setup step.
        state = [row for row in state if not (row['kind']=='task' and row['id']==action_id)]
    return _event(connection,principal,command_id,key,now,plan_id,'organization.task_added',
        {'task':{'id':action_id,'delegation_id':delegation_id,'outcome_id':outcome_id,'created_at':now},
         'existing_link':existing_link,'children':_append_child(state,'task',action_id,None)})


def dispatch_organization(core, connection, principal, command, command_id, key, now):
    owner = principal.owner_id
    if isinstance(command,CreatePlan):
        if not command.title.strip():
            raise DomainError('organization_title_required',422)
        if command.goal_id and owned(connection,owner,'learning_goal',command.goal_id)['status'] not in OPEN_GOAL_STATUSES:
            raise DomainError('goal_not_active')
        plan_id = str(uuid4())
        initialize(connection,principal,command_id,key,now,plan_id,command.model_dump())
        return {'plan_id':plan_id,'object_id':plan_id,'revision':revision(connection,owner,plan_id)}
    purge = isinstance(command,PurgePlanContent)
    require_plan(connection,owner,command.plan_id,writable=not purge)
    if revision(connection,owner,command.plan_id) != command.expected_revision:
        raise DomainError('version_conflict')
    if isinstance(command,(CreateModule,OrderChildren)):
        require_module(connection,owner,command.plan_id,command.parent_module_id)
    if isinstance(command,(PlaceTask,RemovePlanTask)):
        if isinstance(command,PlaceTask):
            require_module(connection,owner,command.plan_id,command.module_id)
        link = connection.execute('SELECT * FROM learning_action_link WHERE owner_id=? AND plan_id=? AND action_id=?',
                                  (owner,command.plan_id,command.action_id)).fetchone()
        if not link:
            raise DomainError('not_found',404)
        if command.action_id in removed_task_ids(connection,owner,command.plan_id):
            raise DomainError('task_removed')
        if isinstance(command,RemovePlanTask):
            action = owned(connection,owner,'learning_action',command.action_id)
            if action['version'] != command.expected_action_version:
                raise DomainError('version_conflict')
            if connection.execute('''SELECT 1 FROM learning_session s JOIN learning_delegation d
                ON d.owner_id=s.owner_id AND d.id=s.delegation_id
                WHERE d.owner_id=? AND d.action_id=? AND s.status='running' ''', (owner,command.action_id)).fetchone():
                raise DomainError('task_session_running')
    if isinstance(command,(ReviseModule,PurgeModuleContent)):
        require_module(connection,owner,command.plan_id,command.module_id)
    if isinstance(command,PurgePlanContent) and not isinstance(command,PurgeModuleContent):
        if not connection.execute("SELECT 1 FROM learning_plan_private WHERE owner_id=? AND kind='plan' AND object_id=?", (owner,command.plan_id)).fetchone():
            raise DomainError('organization_legacy_content_scope',422)
    initialize(connection,principal,command_id,key,now,command.plan_id)
    state = children(connection,owner,command.plan_id)
    next_revision = revision(connection,owner,command.plan_id) + 1
    object_id = command.plan_id
    if isinstance(command,CreateModule):
        if not command.title.strip():
            raise DomainError('organization_title_required',422)
        if isinstance(command,ReviseModule):
            object_id = command.module_id
            purged = connection.execute("SELECT 1 FROM learning_plan_private_tombstone WHERE owner_id=? AND kind='module' AND object_id=?", (owner,object_id)).fetchone()
            if purged and (command.title != CLEARED_TITLE or command.description):
                raise DomainError('organization_content_purged')
            old = next(row for row in state if row['kind']=='module' and row['id']==object_id)
            if old['parent_module_id'] != command.parent_module_id:
                state = _append_child([row for row in state if row is not old], 'module',object_id,command.parent_module_id)
            event_type = 'organization.module_revised'
        else:
            object_id = str(uuid4())
            state = _append_child(state,'module',object_id,command.parent_module_id)
            event_type = 'organization.module_created'
        # Cleared modules remain structural containers and may still move.
        # Their tombstone cannot be used to restore or rename erased content.
        private = {} if isinstance(command,ReviseModule) and purged else private_payload(
            [('module',object_id,{'title':command.title,'description':command.description})],next_revision)
        payload = {'module_id':object_id,'parent_module_id':command.parent_module_id,'children':state,**private}
    elif isinstance(command,PlaceTask):
        object_id = command.action_id
        old = next(row for row in state if row['kind']=='task' and row['id']==object_id)
        if old['parent_module_id'] != command.module_id:
            state = _append_child([row for row in state if row is not old], 'task',object_id,command.module_id)
        event_type, payload = 'organization.task_placed', {'action_id':object_id,'children':state}
    elif isinstance(command,RemovePlanTask):
        object_id = command.action_id
        append_event(connection,principal,command_id=command_id,key=key,now=now,
            aggregate_type='action',aggregate_id=object_id,expected_version=command.expected_action_version,
            event_type='action.removed',payload={'action_id':object_id,'plan_id':command.plan_id,
                                               'previous_status':action['status']})
        state = _normalized([row for row in state if row['kind']!='task' or row['id']!=object_id])
        event_type, payload = 'organization.task_removed', {'action_id':object_id,'children':state}
    elif isinstance(command,OrderChildren):
        current = [row for row in state if row['parent_module_id']==command.parent_module_id]
        desired = [(row.kind,row.id) for row in command.children]
        if len(desired) != len(set(desired)) or set(desired) != {(row['kind'],row['id']) for row in current}:
            raise DomainError('organization_members_changed')
        other = [row for row in state if row['parent_module_id']!=command.parent_module_id]
        state = [*other, *[dict(kind=kind,id=item,parent_module_id=command.parent_module_id,position=index)
                           for index,(kind,item) in enumerate(desired)]]
        event_type, payload = 'organization.children_ordered', {'children':state}
    elif isinstance(command,CreatePlanTask):
        repository = LearningRepository(core.database,principal)
        if command.criterion_id and not command.outcome_id:
            raise DomainError('criterion_outcome_required')
        if command.outcome_id:
            owned(connection,owner,'learning_outcome',command.outcome_id)
            outcome_id = command.outcome_id
        else:
            outcome_id = core._dispatch(connection,principal,CreateOutcome(object_description=command.object_description,
                behavior=command.behavior,context_key=command.outcome_context_key),command_id,key,now)['id']
        action_id = core._dispatch(connection,principal,CreateLearningAction(title=command.action_title,
            context_key=command.context_key),command_id,key,now)['id']
        repository.validate_binding(action_id,outcome_id,command.criterion_id)
        delegation_id = core._dispatch(connection,principal,CreateDelegation(action_id=action_id,outcome_id=outcome_id,
            criterion_id=command.criterion_id,boundaries=command.boundaries,stop_conditions=command.stop_conditions,
            time_budget_minutes=command.time_budget_minutes,expected_version=1),command_id,key,now)['id']
        append_task(connection,principal,command_id,key,now,command.plan_id,action_id,delegation_id,outcome_id)
        return dict(plan_id=command.plan_id,action_id=action_id,outcome_id=outcome_id,delegation_id=delegation_id,
                    revision=revision(connection,owner,command.plan_id))
    elif purge:
        kind = 'module' if isinstance(command,PurgeModuleContent) else 'plan'
        object_id = command.module_id if kind=='module' else command.plan_id
        event_type, payload = 'organization.content_purged', {'kind':kind,'object_id':object_id}
    else:
        raise DomainError('command_unsupported',422)
    _event(connection,principal,command_id,key,now,command.plan_id,event_type,payload)
    return dict(plan_id=command.plan_id,object_id=object_id,revision=revision(connection,owner,command.plan_id))


def erase_organization(connection, owner, kind, object_id, now):
    from ..purge_content import columns
    if not columns(connection,'learning_plan_private'):
        return
    # Older snapshots may predate this object's initialization. The erasure
    # receipt still forbids restoring them, even when no row exists here.
    present = connection.execute('SELECT 1 FROM learning_plan_private WHERE owner_id=? AND kind=? AND object_id=?',
                                 (owner,kind,object_id)).fetchone()
    if not present:
        return
    connection.execute('UPDATE learning_plan_private SET content_json=NULL,content_hash=NULL,purged_at=COALESCE(purged_at,?) WHERE owner_id=? AND kind=? AND object_id=?',
                       (now,owner,kind,object_id))
    connection.execute('INSERT INTO learning_plan_private_tombstone VALUES (?,?,?,?) ON CONFLICT(owner_id,kind,object_id) DO NOTHING',
                       (owner,kind,object_id,now))
    table = 'learning_plan' if kind=='plan' else 'learning_module'
    connection.execute(f'UPDATE {table} SET title=?,description=\'\' WHERE owner_id=? AND id=?', (CLEARED_TITLE,owner,object_id))
    if columns(connection,'learning_commitment_source'):
        from .commitments import erase_sources
        erase_sources(connection,owner,kind+'_content',[object_id],now)


def apply_organization_event(connection, event, payload):
    owner, plan_id, value, now = event['owner_id'],payload.get('id'),event['aggregate_version'],event['occurred_at']
    if event['aggregate_type'] != 'plan_organization' or plan_id != event['aggregate_id']:
        raise DomainError('event_scope_invalid')
    kind = event['event_type']
    _store_private(connection,event,payload)
    if kind == 'organization.initialized':
        if value != 1 or revision(connection,owner,plan_id):
            raise DomainError('event_scope_invalid')
        actual_position = connection.execute('SELECT position FROM learning_event WHERE event_id=?', (event['event_id'],)).fetchone()[0]
        prior_position = connection.execute('SELECT COALESCE(MAX(position),0) FROM learning_event WHERE position<?', (actual_position,)).fetchone()[0]
        if payload.get('cutoff_position') != prior_position:
            raise DomainError('event_scope_invalid')
        if 'new_plan' in payload:
            new = payload['new_plan']
            fields = _fields(connection,owner,'plan',plan_id,value)
            connection.execute('''INSERT INTO learning_plan (id,owner_id,goal_id,title,description,status,version,created_at,updated_at)
                VALUES (?,?,?,?,?,'active',1,?,?)''', (plan_id,owner,new['goal_id'],fields['title'],fields['description'],now,now))
        require_plan(connection,owner,plan_id,writable=False)
        for module in payload['modules']:
            fields = _fields(connection,owner,'module',module['id'],value)
            connection.execute('''INSERT INTO learning_module (id,owner_id,plan_id,parent_module_id,title,description,position,status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET parent_module_id=excluded.parent_module_id,
                title=excluded.title,description=excluded.description,position=excluded.position,status=excluded.status,
                created_at=excluded.created_at,updated_at=excluded.updated_at''',
                (module['id'],owner,plan_id,module['parent_module_id'],fields['title'],fields['description'],module['position'],module['status'],module['created_at'],module['updated_at']))
        for task in payload['tasks']:
            connection.execute('''INSERT INTO learning_action_link (owner_id,action_id,plan_id,module_id,created_at) VALUES (?,?,?,NULL,?)
                ON CONFLICT(owner_id,action_id) DO UPDATE SET plan_id=excluded.plan_id,created_at=excluded.created_at''',
                (owner,task['id'],plan_id,task['created_at']))
        _write_children(connection,owner,plan_id,payload['children'])
        connection.execute('INSERT INTO learning_plan_organization VALUES (?,?,?,?,?)',
                           (owner,plan_id,value,payload['cutoff_position'],event['event_id']))
        return
    if revision(connection,owner,plan_id) != value-1:
        raise DomainError('projection_gap')
    if kind in {'organization.module_created','organization.module_revised'}:
        module_id = payload['module_id']
        fields = _fields(connection,owner,'module',module_id,value)
        require_module(connection,owner,plan_id,payload['parent_module_id'])
        if kind == 'organization.module_created':
            connection.execute('INSERT INTO learning_module VALUES (?,?,?,?,?,?,0,\'active\',?,?)',
                               (module_id,owner,plan_id,payload['parent_module_id'],fields['title'],fields['description'],now,now))
        else:
            require_module(connection,owner,plan_id,module_id)
            connection.execute('UPDATE learning_module SET title=?,description=?,updated_at=? WHERE owner_id=? AND id=?',
                               (fields['title'],fields['description'],now,owner,module_id))
    elif kind == 'organization.task_added':
        task = payload['task']
        delegation = owned(connection,owner,'learning_delegation',task['delegation_id'])
        if delegation['action_id'] != task['id'] or delegation['outcome_id'] != task['outcome_id']:
            raise DomainError('event_scope_invalid')
        if payload['existing_link']:
            link = connection.execute('SELECT plan_id,module_id FROM learning_action_link WHERE owner_id=? AND action_id=?', (owner,task['id'])).fetchone()
            if not link or link['plan_id'] != plan_id or link['module_id'] is not None:
                raise DomainError('event_scope_invalid')
        else:
            connection.execute('INSERT INTO learning_action_link (owner_id,action_id,plan_id,module_id,created_at) VALUES (?,?,?,NULL,?)',
                               (owner,task['id'],plan_id,task['created_at']))
    elif kind == 'organization.task_placed':
        if not connection.execute('SELECT 1 FROM learning_action_link WHERE owner_id=? AND plan_id=? AND action_id=?', (owner,plan_id,payload['action_id'])).fetchone():
            raise DomainError('event_scope_invalid')
    elif kind == 'organization.task_removed':
        action_id = payload.get('action_id')
        if not connection.execute('''SELECT 1 FROM learning_action_removal r JOIN learning_action_link l
            ON l.owner_id=r.owner_id AND l.action_id=r.action_id AND l.plan_id=r.plan_id
            WHERE r.owner_id=? AND r.plan_id=? AND r.action_id=?''', (owner,plan_id,action_id)).fetchone():
            raise DomainError('event_scope_invalid')
        current = [dict(row) for row in connection.execute('''SELECT kind,child_id AS id,parent_module_id,position
            FROM learning_plan_child WHERE owner_id=? AND plan_id=?''', (owner,plan_id))]
        if not any(row['kind']=='task' and row['id']==action_id for row in current):
            raise DomainError('event_scope_invalid')
        expected = _normalized([row for row in current if row['kind']!='task' or row['id']!=action_id])
        if payload.get('children') != expected:
            raise DomainError('event_scope_invalid')
    elif kind == 'organization.content_purged':
        object_kind, object_id = payload['kind'],payload['object_id']
        if object_kind=='module':
            require_module(connection,owner,plan_id,object_id)
        elif object_kind!='plan' or object_id!=plan_id:
            raise DomainError('event_scope_invalid')
        erase_organization(connection,owner,object_kind,object_id,now)
    elif kind != 'organization.children_ordered':
        raise DomainError('event_type_unsupported')
    if 'children' in payload:
        _write_children(connection,owner,plan_id,payload['children'])
    connection.execute('UPDATE learning_plan_organization SET revision=?,last_event_id=? WHERE owner_id=? AND plan_id=?',
                       (value,event['event_id'],owner,plan_id))
