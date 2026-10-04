"""Plan route streams, exact positions, and retained route private originals."""
from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from ..goal_lifecycle import OPEN_GOAL_STATUSES
from ..learning_domain import DomainError
from .commands import EndSession, StartSession
from .events import append_event, canonical, digest
from .path_commands import (SavePathDraft, ConfirmPathDecision, SetPathPosition,
                            StartPathTask, PurgePathContent, PathFields, TransferFields, TransferPathToPlan, CreatePathTask, RemovePathTask)


PATH_EVENT_TYPES = frozenset({'path.draft_saved', 'path.decision_confirmed', 'path.transfer_departed',
                              'path.position_selected', 'path.content_purged'})
PATH_PROJECTION_TABLES = ('learning_path_checkpoint', 'learning_path_decision',
                         'learning_path_version', 'learning_path_draft', 'learning_plan_path_state')


def owned(connection, owner, table, identifier):
    row = connection.execute(f'SELECT * FROM {table} WHERE owner_id=? AND id=?', (owner, identifier)).fetchone()
    if row is None:
        raise DomainError('not_found', 404)
    return row


def plan_state(connection, owner, plan_id):
    owned(connection, owner, 'learning_plan', plan_id)
    row = connection.execute('SELECT * FROM learning_plan_path_state WHERE owner_id=? AND plan_id=?',
                             (owner, plan_id)).fetchone()
    return dict(row) if row else dict(owner_id=owner, plan_id=plan_id, revision=0,
                                     adopted_version_id=None, current_node_id=None,
                                     last_decision_id=None, status='active')


def organization_revision(connection, owner, plan_id):
    row = connection.execute('SELECT revision FROM learning_plan_organization WHERE owner_id=? AND plan_id=?',
                             (owner, plan_id)).fetchone()
    return row['revision'] if row else 0


def writable_plan(connection, owner, plan_id):
    plan = owned(connection, owner, 'learning_plan', plan_id)
    if plan['status'] != 'active':
        raise DomainError('path_plan_inactive')
    if plan['goal_id']:
        goal = owned(connection, owner, 'learning_goal', plan['goal_id'])
        if goal['status'] not in OPEN_GOAL_STATUSES:
            raise DomainError('goal_not_active')
    return plan


def read_private(connection, owner, object_id, revision):
    row = connection.execute('SELECT * FROM learning_path_private WHERE owner_id=? AND object_id=? AND revision=?',
                             (owner, object_id, revision)).fetchone()
    if row is None:
        raise DomainError('event_integrity_failed')
    if row['purged_at'] is not None:
        return None
    if hashlib.sha256(row['content_json'].encode()).hexdigest() != row['content_hash']:
        raise DomainError('event_integrity_failed')
    return json.loads(row['content_json'])


def reference_hash(connection, owner, plan_id, data):
    references = []
    for action_id in sorted({a for node in data['nodes'] for a in node['action_ids']}):
        action = owned(connection, owner, 'learning_action', action_id)
        link = connection.execute('SELECT plan_id FROM learning_action_link WHERE owner_id=? AND action_id=?',
                                  (owner, action_id)).fetchone()
        if link is None or link['plan_id'] != plan_id:
            raise DomainError('path_reference_scope')
        references.append(('action', action_id, action['version'], action['status']))
    for outcome_id in sorted({o for node in data['nodes'] for o in node['outcome_ids']}):
        outcome = owned(connection, owner, 'learning_outcome', outcome_id)
        # Outcome declarations are immutable; their established reference version is 1.
        references.append(('outcome', outcome_id, 1))
    return digest(references)


def structure(fields):
    value = fields.model_dump(mode='json')
    return dict(nodes=[{key: node[key] for key in ('id', 'action_ids', 'outcome_ids')} for node in value['nodes']],
                edges=value['edges'], entry_node_id=value['entry_node_id'], current_node_id=value['current_node_id'])


def version_fields(connection, owner, version_id):
    version = owned(connection, owner, 'learning_path_version', version_id)
    private = read_private(connection, owner, version['private_object_id'], version['private_revision'])
    if version['purged_at'] or private is None:
        raise DomainError('path_content_unavailable')
    data = json.loads(version['data_json'])
    return version, dict(title=private['title'], reason='', nodes=[
        {**node, 'title': private['node_titles'][node['id']]} for node in data['nodes']],
        edges=data['edges'], entry_node_id=data['entry_node_id'], current_node_id=data['current_node_id'])


def running_sessions(connection, owner, plan_id):
    return [dict(row) for row in connection.execute('''SELECT s.*,d.action_id,a.version AS action_version,
        a.title AS action_title FROM learning_session s
        JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
        JOIN learning_action a ON a.owner_id=d.owner_id AND a.id=d.action_id
        JOIN learning_action_link l ON l.owner_id=a.owner_id AND l.action_id=a.id
        WHERE s.owner_id=? AND l.plan_id=? AND s.status='running' ORDER BY s.id''', (owner, plan_id))]


def checkpoint(connection, owner, plan_id, state):
    if not state['adopted_version_id']:
        return None
    row = connection.execute('SELECT * FROM learning_path_checkpoint WHERE owner_id=? AND plan_id=? AND version_id=?',
                             (owner, plan_id, state['adopted_version_id'])).fetchone()
    value = dict(row) if row else dict(owner_id=owner, plan_id=plan_id,
                                     version_id=state['adopted_version_id'], node_id=state['current_node_id'],
                                     action_id=None, delegation_id=None, session_id=None, anchor_json='{}')
    if value['node_id']!=state['current_node_id']:
        value.update(action_id=None,delegation_id=None,session_id=None,anchor_json='{}')
    value['node_id'] = state['current_node_id']
    return value


def commitment_effects(connection,owner,plan_id,data,*,intent,pause_all=False):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='learning_plan_commitment_state'").fetchone():
        return dict(changes=[],affected_sessions=[],fingerprint=digest([]),available=False)
    from .commitments import route_change_review
    return route_change_review(connection,owner,plan_id,data,intent=intent,pause_all=pause_all)


def review(connection, owner, plan_id, draft_id):
    state = plan_state(connection, owner, plan_id)
    plan = writable_plan(connection, owner, plan_id)
    draft = owned(connection, owner, 'learning_path_draft', draft_id)
    if draft['plan_id'] != plan_id or draft['status'] != 'draft':
        raise DomainError('path_draft_inactive')
    data = json.loads(draft['data_json'])
    if (draft['base_version_id'] != state['adopted_version_id'] or draft['base_node_id'] != state['current_node_id']
            or draft['organization_revision'] != organization_revision(connection, owner, plan_id)
            or draft['reference_hash'] != reference_hash(connection, owner, plan_id, data)):
        raise DomainError('path_input_changed')
    if read_private(connection, owner, draft_id, draft['revision']) is None:
        raise DomainError('path_content_unavailable')
    for source in (draft['source_version_id'], draft['restore_version_id']):
        if source:
            source_version, _ = version_fields(connection, owner, source)
            if source_version['plan_id'] != plan_id:
                raise DomainError('path_reference_scope')
    current_actions = next(node['action_ids'] for node in data['nodes'] if node['id'] == data['current_node_id'])
    sessions = [s for s in running_sessions(connection, owner, plan_id) if s['action_id'] not in current_actions]
    commitments=commitment_effects(connection,owner,plan_id,data,intent=draft['intent'])
    sessions=sorted({s['id']:s for s in [*sessions,*commitments['affected_sessions']]}.values(),key=lambda s:s['id'])
    goal_version = owned(connection, owner, 'learning_goal', plan['goal_id'])['version'] if plan['goal_id'] else None
    fingerprint = dict(plan_id=plan_id, path_revision=state['revision'], draft_id=draft_id,
        draft_revision=draft['revision'], organization_revision=draft['organization_revision'],
        reference_hash=draft['reference_hash'], goal_version=goal_version, plan_status=plan['status'],
        sessions=[{key:s[key] for key in ('id','version','action_id','action_version')} for s in sessions],
        checkpoint=complete_checkpoint(connection, owner, plan_id, state),commitment_fingerprint=commitments['fingerprint'])
    return dict(review_key=digest(fingerprint), revision=state['revision'], draft_revision=draft['revision'],
                affected_sessions=sessions, checkpoint=fingerprint['checkpoint'], intent=draft['intent'],
                data=data, draft=dict(draft), state=state,commitments=commitments)


def capture_anchor(connection, owner, session_id):
    if not session_id:
        return {}
    row = connection.execute('''SELECT r.conversation_id FROM learning_room_conversation r
        JOIN learning_session s ON s.owner_id=r.owner_id AND s.id=r.session_id
        WHERE r.owner_id=? AND s.delegation_id=(SELECT delegation_id FROM learning_session WHERE owner_id=? AND id=?)
        ORDER BY r.selected_at DESC,r.conversation_id LIMIT 1''', (owner, owner, session_id)).fetchone()
    if row is None:
        return {}
    current = connection.execute("SELECT * FROM learning_conversation_current_state WHERE owner_id=? AND kind='conversation' AND scope_id=?",
                                 (owner, row['conversation_id'])).fetchone()
    return dict(kind='conversation', conversation_id=row['conversation_id'],
                leaf_id=current['leaf_id'] if current else None,
                paths=json.loads(current['paths_json']) if current else {},
                state_revision=current['revision'] if current else None,
                annotation_revision=None)


def complete_checkpoint(connection, owner, plan_id, state):
    value = checkpoint(connection, owner, plan_id, state)
    if value is None:
        return None
    version = owned(connection, owner, 'learning_path_version', state['adopted_version_id'])
    node = next(n for n in json.loads(version['data_json'])['nodes'] if n['id'] == state['current_node_id'])
    running = next((s for s in running_sessions(connection, owner, plan_id) if s['action_id'] in node['action_ids']), None)
    if running:
        value.update(action_id=running['action_id'], delegation_id=running['delegation_id'], session_id=running['id'])
        value['anchor_json'] = canonical(capture_anchor(connection, owner, value['session_id']))
    return {key:value.get(key) for key in ('version_id','node_id','action_id','delegation_id','session_id','anchor_json')}


def _append(connection, principal, command_id, key, now, plan_id, revision, event_type, payload):
    return append_event(connection, principal, command_id=command_id, key=key,
        aggregate_type='path', aggregate_id=plan_id, expected_version=revision,
        event_type=event_type, payload=payload, now=now)


def transfer_review(connection, owner, plan_id, fields):
    state=plan_state(connection,owner,plan_id)
    plan=writable_plan(connection,owner,plan_id)
    if state['adopted_version_id'] is None:
        raise DomainError('path_not_adopted')
    if fields.expected_revision!=state['revision'] or fields.expected_organization_revision!=organization_revision(connection,owner,plan_id):
        raise DomainError('version_conflict')
    if any(node.action_ids for node in fields.nodes):
        raise DomainError('path_transfer_tasks',422)
    references=reference_hash(connection,owner,plan_id,structure(fields))
    sessions=running_sessions(connection,owner,plan_id) if fields.pause_original else []
    commitments=commitment_effects(connection,owner,plan_id,{},intent='change_direction',pause_all=True) if fields.pause_original else dict(changes=[],fingerprint=digest([]),available=False)
    point=complete_checkpoint(connection,owner,plan_id,state)
    fingerprint=dict(plan_id=plan_id,revision=state['revision'],organization_revision=fields.expected_organization_revision,
        fields=fields.model_dump(mode='json',include=set(TransferFields.model_fields)),
        references=references,checkpoint=point,plan_status=plan['status'],commitment_fingerprint=commitments['fingerprint'],
        goal_version=owned(connection,owner,'learning_goal',plan['goal_id'])['version'] if plan['goal_id'] else None,
        sessions=[{key:s[key] for key in ('id','version','action_id','action_version')} for s in sessions])
    return dict(review_key=digest(fingerprint),revision=state['revision'],organization_revision=fields.expected_organization_revision,
        affected_sessions=sessions,checkpoint=point,destination_title=fields.destination_title,pause_original=fields.pause_original,commitments=commitments)


def dispatch_path(core, connection, principal, command, command_id, key, now):
    owner, plan_id = principal.owner_id, command.plan_id
    state = plan_state(connection, owner, plan_id)
    if command.expected_revision != state['revision']:
        raise DomainError('version_conflict')
    if isinstance(command, PurgePathContent):
        version = owned(connection, owner, 'learning_path_version', command.version_id)
        if version['plan_id'] != plan_id:
            raise DomainError('path_reference_scope')
        affected = erase_path_private(connection, owner, version['private_object_id'], now)
        event = _append(connection, principal, command_id, key, now, plan_id, state['revision'],
                        'path.content_purged', dict(object_ids=affected))
        return dict(plan_id=plan_id, version_id=version['id'], revision=event['aggregate_version'])
    writable_plan(connection, owner, plan_id)
    if isinstance(command, RemovePathTask):
        from .path_tasks import remove_path_task
        return remove_path_task(core, connection, principal, command, command_id, key, now)
    if isinstance(command, CreatePathTask):
        from .organization_commands import CreatePlanTask, TaskFields
        if command.expected_organization_revision != organization_revision(connection, owner, plan_id):
            raise DomainError('version_conflict')
        if command.version_id:
            if state['status'] != 'active':
                raise DomainError('path_paused')
            if command.version_id != state['adopted_version_id']:
                raise DomainError('path_not_current')
            version, fields = version_fields(connection, owner, command.version_id)
            fields['current_node_id'] = state['current_node_id']
            draft_options = dict(intent='change_scope', source_version_id=version['id'])
        else:
            existing = owned(connection, owner, 'learning_path_draft', command.draft_id)
            if existing['revision'] != command.expected_draft_revision:
                raise DomainError('version_conflict')
            reviewed = review(connection, owner, plan_id, command.draft_id)
            private = read_private(connection, owner, existing['id'], existing['revision'])
            fields = dict(title=private['title'], reason=private['reason'], **reviewed['data'])
            fields['nodes'] = [{**node, 'title': private['node_titles'][node['id']]} for node in fields['nodes']]
            # Restoring a historical snapshot must retain its exact associations.
            if existing['intent'] in {'restore', 'undo'}:
                raise DomainError('path_restore_changed')
            draft_options = {name: existing[name] for name in ('intent', 'source_version_id', 'restore_version_id')}
            draft_options.update(draft_id=existing['id'], expected_draft_revision=existing['revision'])
        node = next((node for node in fields['nodes'] if node['id'] == command.node_id), None)
        if node is None:
            raise DomainError('path_node_missing')
        if (len(node['action_ids']) >= 30 or
                (len(node['outcome_ids']) >= 30 and command.outcome_id not in node['outcome_ids'])):
            raise DomainError('path_node_task_limit', 422)
        result = core.execute_in_transaction(connection, principal, CreatePlanTask(plan_id=plan_id,
            expected_revision=command.expected_organization_revision,
            **command.model_dump(mode='json', include=set(TaskFields.model_fields))),
            'path-task:' + digest(command_id))
        node['action_ids'].append(result['action_id'])
        if result['outcome_id'] not in node['outcome_ids']:
            node['outcome_ids'].append(result['outcome_id'])
        if command.version_id:
            fields['reason'] = '在阶段中添加任务'
        saved = core.execute_in_transaction(connection, principal, SavePathDraft(plan_id=plan_id,
            **fields, **draft_options, expected_revision=state['revision'],
            expected_organization_revision=result['revision']), 'path-task-draft:' + digest(command_id))
        if command.draft_id:
            return {**result, 'draft_id': saved['draft_id'], 'node_id': command.node_id}
        # This addition changes no existing task, position or execution. Keep the
        # immutable old snapshot and carry its checkpoint into the new snapshot.
        saved_draft = owned(connection, owner, 'learning_path_draft', saved['draft_id'])
        data = json.loads(saved_draft['data_json'])
        point = complete_checkpoint(connection, owner, plan_id, state)
        version_id, decision_id = str(uuid4()), str(uuid4())
        _append(connection, principal, command_id, key, now, plan_id, saved['revision'],
            'path.decision_confirmed', dict(id=version_id, route_id=version['route_id'],
                decision_id=decision_id, draft_id=saved['draft_id'], private_revision=saved_draft['revision'],
                data=data, intent='change_scope', previous_version_id=version['id'],
                parent_version_id=version['id'], branch_node_id=command.node_id,
                previous_node_id=state['current_node_id'], old_checkpoint=point, new_checkpoint=point))
        effects = commitment_effects(connection, owner, plan_id, data, intent='change_scope')
        # Only carry arrangements whose existing association is retained. An
        # unrelated arrangement is unaffected by adding a task to this stage.
        effects['changes'] = [change for change in effects['changes'] if change['kind'] == 'keep']
        effects['affected_sessions'] = []
        if effects['changes']:
            from .commitments import apply_route_change
            apply_route_change(core, connection, principal, plan_id, version_id, effects, command_id, key, now)
        return {**result, 'version_id': version_id, 'node_id': command.node_id}
    if isinstance(command,TransferPathToPlan):
        preview=transfer_review(connection,owner,plan_id,command)
        if preview['review_key']!=command.review_key:
            raise DomainError('path_review_changed')
        from .organization_commands import CreatePlan
        for session in preview['affected_sessions']:
            core.execute_in_transaction(connection,principal,EndSession(session_id=session['id'],
                disposition='interrupted',expected_version=session['action_version']),'transfer-pause:'+digest([command_id,session['id']]))
        destination=core.execute_in_transaction(connection,principal,CreatePlan(title=command.destination_title,
            description=command.destination_description,goal_id=None),'transfer-plan:'+digest(command_id))
        new_plan=destination['plan_id']
        fields=command.model_dump(mode='json',include=set(PathFields.model_fields))
        saved=core.execute_in_transaction(connection,principal,SavePathDraft(plan_id=new_plan,**fields,intent='create',
            expected_revision=0,expected_organization_revision=organization_revision(connection,owner,new_plan)),'transfer-draft:'+digest(command_id))
        new_review=review(connection,owner,new_plan,saved['draft_id'])
        adopted=core.execute_in_transaction(connection,principal,ConfirmPathDecision(plan_id=new_plan,draft_id=saved['draft_id'],
            expected_revision=new_review['revision'],expected_draft_revision=new_review['draft_revision'],review_key=new_review['review_key']),
            'transfer-adopt:'+digest(command_id))
        event=_append(connection,principal,command_id,key,now,plan_id,state['revision'],'path.transfer_departed',dict(
            version_id=state['adopted_version_id'],node_id=state['current_node_id'],checkpoint=preview['checkpoint'],
            destination_plan_id=new_plan,destination_version_id=adopted['version_id'],pause_original=command.pause_original))
        if preview['commitments']['changes']:
            from .commitments import apply_route_change
            apply_route_change(core,connection,principal,plan_id,state['adopted_version_id'],preview['commitments'],command_id,key,now)
        return dict(plan_id=new_plan,source_plan_id=plan_id,revision=event['aggregate_version'])
    if isinstance(command, SavePathDraft):
        if command.expected_organization_revision != organization_revision(connection, owner, plan_id):
            raise DomainError('version_conflict')
        if command.intent == 'create' and state['adopted_version_id'] is not None:
            raise DomainError('path_already_exists')
        if command.intent != 'create' and state['adopted_version_id'] is None:
            raise DomainError('path_not_adopted')
        data = structure(command)
        refs = reference_hash(connection, owner, plan_id, data)
        if command.restore_version_id:
            original, values = version_fields(connection, owner, command.restore_version_id)
            if original['plan_id'] != plan_id or command.intent not in {'restore','undo'}:
                raise DomainError('path_reference_scope')
            original_structure = structure(PathFields(**values))
            if ({key:value for key,value in data.items() if key != 'current_node_id'}
                    != {key:value for key,value in original_structure.items() if key != 'current_node_id'}
                    or command.title != values['title']
                    or {n.id:n.title for n in command.nodes} != {n['id']:n['title'] for n in values['nodes']}):
                raise DomainError('path_restore_changed')
        elif command.intent in {'restore','undo'}:
            raise DomainError('path_restore_required')
        if command.source_version_id:
            source, _ = version_fields(connection, owner, command.source_version_id)
            if source['plan_id'] != plan_id:
                raise DomainError('path_reference_scope')
        draft_id = command.draft_id or str(uuid4())
        if command.draft_id:
            existing = owned(connection, owner, 'learning_path_draft', draft_id)
            if (existing['plan_id'] != plan_id or existing['status'] != 'draft'
                    or command.expected_draft_revision != existing['revision']):
                raise DomainError('path_draft_inactive')
        private = canonical(dict(title=command.title, node_titles={n.id:n.title for n in command.nodes}, reason=command.reason))
        event = _append(connection, principal, command_id, key, now, plan_id, state['revision'], 'path.draft_saved',
            dict(id=draft_id, intent=command.intent, base_version_id=state['adopted_version_id'],
                 base_node_id=state['current_node_id'], organization_revision=command.expected_organization_revision,
                 reference_hash=refs, data=data, source_version_id=command.source_version_id,
                 restore_version_id=command.restore_version_id, content=private))
        return dict(plan_id=plan_id, draft_id=draft_id, revision=event['aggregate_version'])
    if isinstance(command, ConfirmPathDecision):
        preview = review(connection, owner, plan_id, command.draft_id)
        if (preview['review_key'] != command.review_key
                or preview['draft_revision'] != command.expected_draft_revision):
            raise DomainError('path_review_changed')
        old_checkpoint = preview['checkpoint']
        for session in preview['affected_sessions']:
            core.execute_in_transaction(connection, principal,
                EndSession(session_id=session['id'], disposition='interrupted', expected_version=session['action_version']),
                'path-pause:' + digest((command_id, session['id'])))
        draft, data = preview['draft'], preview['data']
        route_id = str(uuid4())
        parent = state['adopted_version_id']
        if draft['restore_version_id']:
            restored = owned(connection, owner, 'learning_path_version', draft['restore_version_id'])
            route_id = restored['route_id']
        elif draft['intent'] == 'change_scope' and parent:
            route_id = owned(connection, owner, 'learning_path_version', parent)['route_id']
        decision_id, version_id = str(uuid4()), str(uuid4())
        active = next((s for s in running_sessions(connection, owner, plan_id)
                       if s['action_id'] in next(n['action_ids'] for n in data['nodes'] if n['id']==data['current_node_id'])), None)
        new_checkpoint = None
        if draft['restore_version_id']:
            old = connection.execute('SELECT * FROM learning_path_checkpoint WHERE owner_id=? AND plan_id=? AND version_id=?',
                                     (owner, plan_id, draft['restore_version_id'])).fetchone()
            if old and old['node_id'] == data['current_node_id']:
                new_checkpoint = {key:old[key] for key in ('node_id','action_id','delegation_id','session_id','anchor_json')}
        if active:
            new_checkpoint = dict(node_id=data['current_node_id'], action_id=active['action_id'],
                delegation_id=active['delegation_id'], session_id=active['id'],
                anchor_json=canonical(capture_anchor(connection, owner, active['id'])))
        payload = dict(id=version_id, route_id=route_id, decision_id=decision_id, draft_id=draft['id'],
            private_revision=draft['revision'], data=data, intent=draft['intent'],
            previous_version_id=parent, parent_version_id=parent, branch_node_id=state['current_node_id'],
            previous_node_id=state['current_node_id'], old_checkpoint=old_checkpoint, new_checkpoint=new_checkpoint)
        event = _append(connection, principal, command_id, key, now, plan_id, state['revision'],
                        'path.decision_confirmed', payload)
        if preview['commitments']['changes']:
            from .commitments import apply_route_change
            apply_route_change(core,connection,principal,plan_id,version_id,preview['commitments'],command_id,key,now)
        return dict(plan_id=plan_id, version_id=version_id, decision_id=decision_id, revision=event['aggregate_version'])
    if isinstance(command, SetPathPosition):
        if state['status']=='paused':
            raise DomainError('path_paused')
        if state['adopted_version_id'] != command.version_id:
            raise DomainError('path_not_current')
        version, _ = version_fields(connection, owner, command.version_id)
        node = next((n for n in json.loads(version['data_json'])['nodes'] if n['id'] == command.node_id), None)
        if node is None:
            raise DomainError('path_node_missing')
        selected_checkpoint = (dict(node_id=command.node_id,action_id=None,delegation_id=None,session_id=None,anchor_json='{}')
                               if state['current_node_id']!=command.node_id else None)
        result = {}
        if isinstance(command, StartPathTask):
            delegation = owned(connection, owner, 'learning_delegation', command.delegation_id)
            if delegation['action_id'] not in node['action_ids']:
                raise DomainError('path_reference_scope')
            action = owned(connection, owner, 'learning_action', delegation['action_id'])
            if action['version'] != command.expected_action_version:
                raise DomainError('version_conflict')
            if action['status'] != 'open' or delegation['status'] not in {'ready','active'}:
                raise DomainError('delegation_not_startable')
            previous_point=connection.execute('SELECT * FROM learning_path_checkpoint WHERE owner_id=? AND plan_id=? AND version_id=?',
                (owner,plan_id,command.version_id)).fetchone()
            resume_anchor=(json.loads(previous_point['anchor_json']) if command.use_checkpoint and previous_point
                and previous_point['node_id']==command.node_id and previous_point['delegation_id']==command.delegation_id else None)
            running = connection.execute("SELECT * FROM learning_session WHERE owner_id=? AND status='running'", (owner,)).fetchone()
            if running and running['delegation_id'] == command.delegation_id:
                session_id = running['id']
                resume_anchor=capture_anchor(connection,owner,session_id)
            else:
                if running:
                    running_delegation = owned(connection, owner, 'learning_delegation', running['delegation_id'])
                    other_action = owned(connection, owner, 'learning_action', running_delegation['action_id'])
                    core.execute_in_transaction(connection, principal, EndSession(session_id=running['id'],
                        disposition='interrupted', expected_version=other_action['version']), 'path-start-pause:' + digest(command_id))
                action = owned(connection, owner, 'learning_action', delegation['action_id'])
                started = core.execute_in_transaction(connection, principal,
                    StartSession(delegation_id=command.delegation_id, expected_version=action['version']),
                    'path-start:' + digest(command_id))
                session_id = started['id']
            selected_checkpoint = dict(node_id=command.node_id, action_id=action['id'],
                delegation_id=command.delegation_id, session_id=session_id,
                anchor_json=canonical(resume_anchor if resume_anchor is not None else capture_anchor(connection, owner, session_id)))
            result['session_id'] = session_id
            if resume_anchor and resume_anchor.get('conversation_id'):
                result['path_anchor']=resume_anchor
        event = _append(connection, principal, command_id, key, now, plan_id, state['revision'],
            'path.position_selected', dict(version_id=command.version_id, node_id=command.node_id,
                previous_node_id=state['current_node_id'], checkpoint=selected_checkpoint))
        return dict(plan_id=plan_id, revision=event['aggregate_version'], **result)
    raise DomainError('unsupported_command')


def erase_path_private(connection, owner, object_id, now):
    """Erase originals and only explicitly derived route-private copies."""
    present = connection.execute("SELECT 1 FROM sqlite_master WHERE name='learning_path_private'").fetchone()
    if not present:
        return []
    objects = {object_id}
    while True:
        marks = ','.join('?' for _ in objects)
        versions = [row['id'] for row in connection.execute(
            f'SELECT id FROM learning_path_version WHERE owner_id=? AND private_object_id IN ({marks})', (owner, *objects))]
        if not versions:
            break
        version_marks = ','.join('?' for _ in versions)
        dependent = {row['id'] for row in connection.execute(f'''SELECT id FROM learning_path_draft WHERE owner_id=?
            AND (source_version_id IN ({version_marks}) OR restore_version_id IN ({version_marks}))''',
            (owner, *versions, *versions))}
        if dependent.issubset(objects):
            break
        objects.update(dependent)
    for identifier in sorted(objects):
        connection.execute('INSERT OR IGNORE INTO learning_path_private_tombstone VALUES (?,?,?)', (owner, identifier, now))
        connection.execute('UPDATE learning_path_private SET content_json=NULL,content_hash=NULL,purged_at=COALESCE(purged_at,?) WHERE owner_id=? AND object_id=?',
                           (now, owner, identifier))
        connection.execute("UPDATE learning_path_draft SET status='purged',purged_at=COALESCE(purged_at,?) WHERE owner_id=? AND id=?", (now, owner, identifier))
        connection.execute('UPDATE learning_path_version SET purged_at=COALESCE(purged_at,?) WHERE owner_id=? AND private_object_id=?', (now, owner, identifier))
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='learning_commitment_source'").fetchone():
        from .commitments import erase_sources
        marks=','.join('?' for _ in objects)
        versions=[row[0] for row in connection.execute(f'SELECT id FROM learning_path_version WHERE owner_id=? AND private_object_id IN ({marks})',(owner,*objects))]
        erase_sources(connection,owner,'path_version',versions,now)
    return sorted(objects)


def _original(connection, event, payload):
    owner, object_id, revision = event['owner_id'], payload['id'], event['aggregate_version']
    row = connection.execute('SELECT * FROM learning_path_private WHERE owner_id=? AND object_id=? AND revision=?',
                             (owner, object_id, revision)).fetchone()
    if row is None:
        content = event.get('_private_content')
        if not isinstance(content, str) or hashlib.sha256(content.encode()).hexdigest() != payload['content_hash']:
            raise DomainError('event_integrity_failed')
        connection.execute('INSERT INTO learning_path_private VALUES (?,?,?,?,?,?,NULL)',
                           (owner, object_id, revision, event['event_id'], content, payload['content_hash']))
        row = connection.execute('SELECT * FROM learning_path_private WHERE owner_id=? AND object_id=? AND revision=?',
                                 (owner, object_id, revision)).fetchone()
    if row['event_id'] != event['event_id']:
        raise DomainError('event_integrity_failed')
    if row['purged_at'] is None:
        if row['content_hash'] != payload['content_hash'] or hashlib.sha256(row['content_json'].encode()).hexdigest() != payload['content_hash']:
            raise DomainError('event_integrity_failed')
    return row


def _checkpoint(connection, event, value, version_id=None):
    if not value:
        return
    version_id = version_id or value['version_id']
    connection.execute('''INSERT INTO learning_path_checkpoint VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(owner_id,plan_id,version_id) DO UPDATE SET node_id=excluded.node_id,
        action_id=excluded.action_id,delegation_id=excluded.delegation_id,session_id=excluded.session_id,
        anchor_json=excluded.anchor_json,event_id=excluded.event_id,updated_at=excluded.updated_at''',
        (event['owner_id'], event['aggregate_id'], version_id, value['node_id'],
         value.get('action_id'), value.get('delegation_id'), value.get('session_id'),
         value.get('anchor_json') or '{}', event['event_id'], event['occurred_at']))


def apply_path_event(connection, event, payload):
    owner, plan_id, revision, now = event['owner_id'], event['aggregate_id'], event['aggregate_version'], event['occurred_at']
    owned(connection, owner, 'learning_plan', plan_id)
    connection.execute('''INSERT OR IGNORE INTO learning_plan_path_state
        (owner_id,plan_id,revision,status) VALUES (?,?,?,'active')''', (owner, plan_id, revision))
    kind = event['event_type']
    if kind == 'path.draft_saved':
        private = _original(connection, event, payload)
        prior = connection.execute('SELECT created_at FROM learning_path_draft WHERE owner_id=? AND id=?', (owner, payload['id'])).fetchone()
        connection.execute('''INSERT INTO learning_path_draft VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,status=excluded.status,intent=excluded.intent,
            base_version_id=excluded.base_version_id,base_node_id=excluded.base_node_id,
            organization_revision=excluded.organization_revision,reference_hash=excluded.reference_hash,
            data_json=excluded.data_json,source_version_id=excluded.source_version_id,
            restore_version_id=excluded.restore_version_id,updated_at=excluded.updated_at,purged_at=excluded.purged_at''',
            (payload['id'],owner,plan_id,revision,'purged' if private['purged_at'] else 'draft',payload['intent'],
             payload['base_version_id'],payload['base_node_id'],payload['organization_revision'],payload['reference_hash'],
             canonical(payload['data']),payload['source_version_id'],payload['restore_version_id'],
             prior['created_at'] if prior else now,now,private['purged_at']))
    elif kind == 'path.decision_confirmed':
        draft = owned(connection, owner, 'learning_path_draft', payload['draft_id'])
        private = connection.execute('SELECT purged_at FROM learning_path_private WHERE owner_id=? AND object_id=? AND revision=?',
                                     (owner, draft['id'], payload['private_revision'])).fetchone()
        if private is None:
            raise DomainError('event_integrity_failed')
        connection.execute('INSERT INTO learning_path_version VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (payload['id'],owner,plan_id,payload['route_id'],payload['previous_version_id'],payload['parent_version_id'],
             payload['branch_node_id'],canonical(payload['data']),draft['id'],payload['private_revision'],now,private['purged_at']))
        connection.execute('INSERT INTO learning_path_decision VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (payload['decision_id'],owner,plan_id,payload['id'],payload['previous_version_id'],payload['previous_node_id'],
             payload['data']['current_node_id'],payload['intent'],draft['id'],event['event_id'],now))
        connection.execute("UPDATE learning_path_draft SET status=CASE WHEN purged_at IS NULL THEN 'confirmed' ELSE 'purged' END WHERE owner_id=? AND id=?",
                           (owner,draft['id']))
        _checkpoint(connection,event,payload['old_checkpoint'])
        _checkpoint(connection,event,payload['new_checkpoint'],payload['id'])
        connection.execute("UPDATE learning_plan_path_state SET adopted_version_id=?,current_node_id=?,last_decision_id=?,status='active' WHERE owner_id=? AND plan_id=?",
                           (payload['id'],payload['data']['current_node_id'],payload['decision_id'],owner,plan_id))
    elif kind == 'path.position_selected':
        if connection.execute('SELECT adopted_version_id FROM learning_plan_path_state WHERE owner_id=? AND plan_id=?',
                              (owner,plan_id)).fetchone()[0] != payload['version_id']:
            raise DomainError('event_integrity_failed')
        _checkpoint(connection,event,payload['checkpoint'],payload['version_id'])
        connection.execute("UPDATE learning_plan_path_state SET current_node_id=?,status='active' WHERE owner_id=? AND plan_id=?",
                           (payload['node_id'],owner,plan_id))
    elif kind == 'path.transfer_departed':
        current=plan_state(connection,owner,plan_id)
        if current['adopted_version_id']!=payload['version_id']:
            raise DomainError('event_integrity_failed')
        destination=owned(connection,owner,'learning_path_version',payload['destination_version_id'])
        if destination['plan_id']!=payload['destination_plan_id']:
            raise DomainError('event_integrity_failed')
        _checkpoint(connection,event,payload['checkpoint'])
        if payload['pause_original']:
            connection.execute("UPDATE learning_plan_path_state SET status='paused' WHERE owner_id=? AND plan_id=?",(owner,plan_id))
    elif kind == 'path.content_purged':
        for object_id in payload['object_ids']:
            erase_path_private(connection,owner,object_id,now)
    else:
        raise DomainError('unsupported_event')
    connection.execute('UPDATE learning_plan_path_state SET revision=? WHERE owner_id=? AND plan_id=?', (revision,owner,plan_id))
