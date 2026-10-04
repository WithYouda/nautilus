"""Reviewed task association changes without erasing learning history."""
from __future__ import annotations

import json
from uuid import uuid4

from ..learning_domain import DomainError
from .commands import EndSession
from .events import digest
from .path_commands import SavePathDraft, PathTaskRemovalFields
from . import learning_paths as paths


def task_target(connection, owner, plan_id, command, state):
    if command.expected_revision != state['revision'] or command.expected_organization_revision != paths.organization_revision(connection, owner, plan_id):
        raise DomainError('version_conflict')
    if command.version_id:
        if state['status'] != 'active':
            raise DomainError('path_paused')
        if command.version_id != state['adopted_version_id']:
            raise DomainError('path_not_current')
        version, fields = paths.version_fields(connection, owner, command.version_id)
        fields['current_node_id'] = state['current_node_id']
        options = dict(intent='change_scope', source_version_id=version['id'])
    else:
        version = None
        existing = paths.owned(connection, owner, 'learning_path_draft', command.draft_id)
        if existing['revision'] != command.expected_draft_revision:
            raise DomainError('version_conflict')
        reviewed = paths.review(connection, owner, plan_id, command.draft_id)
        private = paths.read_private(connection, owner, existing['id'], existing['revision'])
        fields = dict(title=private['title'], reason=private['reason'], **reviewed['data'])
        fields['nodes'] = [{**node, 'title': private['node_titles'][node['id']]} for node in fields['nodes']]
        if existing['intent'] in {'restore', 'undo'}:
            raise DomainError('path_restore_changed')
        options = {name: existing[name] for name in ('intent', 'source_version_id', 'restore_version_id')}
        options.update(draft_id=existing['id'], expected_draft_revision=existing['revision'])
    node = next((node for node in fields['nodes'] if node['id'] == command.node_id), None)
    if node is None:
        raise DomainError('path_node_missing')
    return version, fields, options, node


def save_task_snapshot(core, connection, principal, plan_id, fields, command_id, key, now,
                       *, version=None, options=None, old_checkpoint=None):
    state = paths.plan_state(connection, principal.owner_id, plan_id)
    saved = core.execute_in_transaction(connection, principal, SavePathDraft(plan_id=plan_id,
        **fields, **(options or dict(intent='change_scope', source_version_id=version['id'])),
        expected_revision=state['revision'],
        expected_organization_revision=paths.organization_revision(connection, principal.owner_id, plan_id)),
        'task-route-draft:' + digest((command_id, version['id'] if version else options['draft_id'])))
    if version is None:
        return saved
    draft = paths.owned(connection, principal.owner_id, 'learning_path_draft', saved['draft_id'])
    data = json.loads(draft['data_json'])
    current_actions = next(node['action_ids'] for node in data['nodes'] if node['id'] == data['current_node_id'])
    point = old_checkpoint
    if point and point.get('action_id') and point['action_id'] not in current_actions:
        point = dict(node_id=data['current_node_id'], action_id=None, delegation_id=None, session_id=None, anchor_json='{}')
    version_id, decision_id = str(uuid4()), str(uuid4())
    event = paths._append(connection, principal, command_id, key, now, plan_id, saved['revision'],
        'path.decision_confirmed', dict(id=version_id, route_id=version['route_id'], decision_id=decision_id,
            draft_id=saved['draft_id'], private_revision=draft['revision'], data=data, intent='change_scope',
            previous_version_id=version['id'], parent_version_id=version['id'],
            branch_node_id=state['current_node_id'], previous_node_id=state['current_node_id'],
            old_checkpoint=old_checkpoint, new_checkpoint=point))
    return dict(version_id=version_id, revision=event['aggregate_version'])


def task_removal_review(connection, owner, plan_id, command):
    state = paths.plan_state(connection, owner, plan_id)
    paths.writable_plan(connection, owner, plan_id)
    version, fields, options, node = task_target(connection, owner, plan_id, command, state)
    action = paths.owned(connection, owner, 'learning_action', command.action_id)
    if action['version'] != command.expected_action_version:
        raise DomainError('version_conflict')
    link = connection.execute('SELECT plan_id FROM learning_action_link WHERE owner_id=? AND action_id=?', (owner, action['id'])).fetchone()
    if not link or link['plan_id'] != plan_id or action['id'] not in node['action_ids']:
        raise DomainError('path_task_missing')
    if connection.execute('SELECT 1 FROM learning_action_removal WHERE owner_id=? AND action_id=?', (owner, action['id'])).fetchone():
        raise DomainError('task_removed')
    node['action_ids'] = [identifier for identifier in node['action_ids'] if identifier != action['id']]
    adopted, adopted_fields = version, fields if version else None
    if command.mode == 'delete':
        for item in fields['nodes']:
            item['action_ids'] = [identifier for identifier in item['action_ids'] if identifier != action['id']]
        if not version and state['adopted_version_id'] and state['status'] == 'active':
            adopted, adopted_fields = paths.version_fields(connection, owner, state['adopted_version_id'])
            adopted_fields['current_node_id'] = state['current_node_id']
        if adopted_fields:
            for item in adopted_fields['nodes']:
                item['action_ids'] = [identifier for identifier in item['action_ids'] if identifier != action['id']]
    point = paths.complete_checkpoint(connection, owner, plan_id, state)
    effects = paths.commitment_effects(connection, owner, plan_id,
        paths.structure(paths.PathFields(**adopted_fields)) if adopted_fields else {}, intent='change_scope')
    if command.mode == 'detach' and not version:
        effects['changes'] = []
        effects['affected_sessions'] = []
    else:
        item_actions = {item['item_id']:item['action_id'] for item in effects.get('item_states', [])}
        effects['changes'] = [change for change in effects['changes']
                             if change['kind'] == 'keep' or item_actions.get(change['item_id']) == action['id']]
        effects['affected_sessions'] = [session for session in effects['affected_sessions'] if session['action_id'] == action['id']]
    affected = effects['affected_sessions'][:]
    removing_current = bool(version and command.node_id == state['current_node_id'] and
        action['id'] not in next(item['action_ids'] for item in fields['nodes'] if item['id'] == state['current_node_id']))
    if command.mode == 'delete' or removing_current:
        affected.extend(session for session in paths.running_sessions(connection, owner, plan_id) if session['action_id'] == action['id'])
    affected = sorted({session['id']:session for session in affected}.values(), key=lambda session:session['id'])
    fingerprint = dict(plan_id=plan_id, target=command.model_dump(mode='json', include=set(PathTaskRemovalFields.model_fields)),
        checkpoint=point, sessions=[{name:session[name] for name in ('id', 'version', 'action_id', 'action_version')} for session in affected],
        commitment_fingerprint=effects['fingerprint'], fields=fields, adopted_fields=adopted_fields)
    return dict(review_key=digest(fingerprint), state=state, action=dict(action), version=version,
        fields=fields, options=options, adopted=adopted, adopted_fields=adopted_fields,
        checkpoint=point, affected_sessions=affected, commitments=effects)


def remove_path_task(core, connection, principal, command, command_id, key, now):
    owner, plan_id = principal.owner_id, command.plan_id
    checked = task_removal_review(connection, owner, plan_id, command)
    if checked['review_key'] != command.review_key:
        raise DomainError('path_review_changed')
    for session in checked['affected_sessions']:
        core.execute_in_transaction(connection, principal, EndSession(session_id=session['id'], disposition='interrupted',
            expected_version=paths.owned(connection, owner, 'learning_action', session['action_id'])['version']),
            'task-removal-pause:' + digest((command_id, session['id'])))
    if command.mode == 'delete':
        from .organization_commands import RemovePlanTask
        core.execute_in_transaction(connection, principal, RemovePlanTask(plan_id=plan_id, action_id=command.action_id,
            expected_revision=command.expected_organization_revision,
            expected_action_version=paths.owned(connection, owner, 'learning_action', command.action_id)['version']),
            'task-removal-plan:' + digest(command_id))
    version_id = checked['state']['adopted_version_id']
    if checked['adopted_fields'] is not None:
        checked['adopted_fields']['reason'] = '删除任务，保留学习记录' if command.mode == 'delete' else '将任务移出阶段'
        saved = save_task_snapshot(core, connection, principal, plan_id, checked['adopted_fields'], command_id, key, now,
            version=checked['adopted'], old_checkpoint=checked['checkpoint'])
        version_id = saved['version_id']
    if not checked['version']:
        save_task_snapshot(core, connection, principal, plan_id, checked['fields'], command_id, key, now, options=checked['options'])
    if checked['commitments']['changes']:
        from .commitments import apply_route_change
        apply_route_change(core, connection, principal, plan_id, version_id, checked['commitments'], command_id, key, now)
    return dict(plan_id=plan_id, action_id=command.action_id,
        revision=paths.plan_state(connection, owner, plan_id)['revision'])
