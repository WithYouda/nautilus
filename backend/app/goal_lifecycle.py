"""Goal decisions are user intent; they never create task or mastery evidence."""
import hashlib
import json

from .learning_domain import DomainError

OPEN_GOAL_STATUSES = ('hypothesis', 'active')


def require_goal_active(connection, owner, action_id):
    row = connection.execute('''SELECT g.status FROM learning_action_link l
        JOIN learning_plan p ON p.owner_id=l.owner_id AND p.id=l.plan_id
        JOIN learning_goal g ON g.owner_id=p.owner_id AND g.id=p.goal_id
        WHERE l.owner_id=? AND l.action_id=?''', (owner, action_id)).fetchone()
    if row and row['status'] not in OPEN_GOAL_STATUSES:
        raise DomainError('goal_not_active')


def goal_review(connection, owner, goal_id):
    row = connection.execute('SELECT * FROM learning_goal WHERE owner_id=? AND id=?', (owner, goal_id)).fetchone()
    if row is None:
        raise DomainError('not_found', 404)
    goal = dict(row)
    plans = [dict(row) for row in connection.execute('''SELECT id,title,status,version
        FROM learning_plan WHERE owner_id=? AND goal_id=? ORDER BY created_at,id''', (owner, goal_id))]
    tasks = [dict(row) for row in connection.execute('''SELECT a.id,a.title,a.status,a.version,l.plan_id
        FROM learning_action a JOIN learning_action_link l ON l.owner_id=a.owner_id AND l.action_id=a.id
        JOIN learning_plan p ON p.owner_id=l.owner_id AND p.id=l.plan_id
        WHERE a.owner_id=? AND p.goal_id=? ORDER BY a.created_at,a.id''', (owner, goal_id))]
    for task in tasks:
        task['delegations'] = [dict(row) for row in connection.execute('''SELECT id,status,version
            FROM learning_delegation WHERE owner_id=? AND action_id=? ORDER BY id''', (owner, task['id']))]
        task['running_session_ids'] = [row['id'] for row in connection.execute('''SELECT s.id
            FROM learning_session s JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
            WHERE s.owner_id=? AND d.action_id=? AND s.status='running' ORDER BY s.id''', (owner, task['id']))]
    # The confirmation must refer to the task/session state the user actually saw.
    snapshot = dict(goal=(goal['id'], goal['status'], goal['version']), plans=plans, tasks=tasks)
    review_key = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    history = []
    for event in connection.execute('''SELECT event_id,payload_json,occurred_at FROM learning_event
        WHERE owner_id=? AND aggregate_type='goal' AND aggregate_id=? AND event_type='goal.status_changed'
        ORDER BY position DESC''', (owner, goal_id)):
        payload = json.loads(event['payload_json'])
        history.append(dict(id=event['event_id'], status=payload['status'],
                            previous_status=payload['previous_status'], occurred_at=event['occurred_at']))
    return dict(goal=goal, plans=plans, tasks=tasks, review_key=review_key, history=history,
                counts=dict(total_tasks=len(tasks), completed_tasks=sum(t['status'] == 'completed' for t in tasks),
                            open_tasks=sum(t['status'] == 'open' for t in tasks),
                            running_sessions=sum(len(t['running_session_ids']) for t in tasks)))
