"""Goal closure preserves learning facts while gating new planned work."""
import json

import pytest

from app.core.commands import ChangeGoalStatus, StartSession, CompleteLearningAction
from app.core.learning import LearningCore
from app.continuity import ContinuityService
from app.goal_lifecycle import goal_review
from app.learning_domain import DomainError, Principal
from app.learning_service import LearningService
from test_learning_domain_schema import domain_rows, learning_database  # noqa: F401
from test_learning_setup import setup_command, OWNER, identity_payload


def review(db, goal_id):
    with db.transaction() as connection:
        return goal_review(connection, OWNER.owner_id, goal_id)


def change(core, goal_id, status, key, snapshot=None):
    snapshot = snapshot or review(core.database, goal_id)
    command = ChangeGoalStatus(goal_id=goal_id, status=status,
        expected_version=snapshot['goal']['version'], review_key=snapshot['review_key'])
    return core.execute(OWNER, command, key)


def version(db, action_id):
    return db.fetchone('SELECT version FROM learning_action WHERE id=?', (action_id,))[0]


@pytest.mark.parametrize('status', ['completed', 'paused', 'archived'])
def test_close_reopen_preserves_tasks_and_other_goal_and_replays(domain_rows, status):
    db = domain_rows
    core = LearningCore(db)
    first = core.execute(OWNER, setup_command(), 'goal-a')
    other = core.execute(OWNER, setup_command(goal_title='其他目标'), 'goal-b')
    session = core.execute(OWNER, StartSession(delegation_id=first['delegation_id'],
        expected_version=version(db, first['action_id'])), 'start')
    snapshot = review(db, first['goal_id'])
    before_other = dict(db.fetchone('SELECT * FROM learning_goal WHERE id=?', (other['goal_id'],)))
    closed = change(core, first['goal_id'], status, 'close', snapshot)
    assert closed['interrupted_session_ids'] == [session['id']]
    assert change(core, first['goal_id'], status, 'close', snapshot) == closed
    assert db.fetchone('SELECT status FROM learning_session WHERE id=?', (session['id'],))[0] == 'interrupted'
    assert db.fetchone('SELECT status FROM learning_action WHERE id=?', (first['action_id'],))[0] == 'open'
    assert db.fetchone('SELECT status FROM learning_delegation WHERE id=?', (first['delegation_id'],))[0] == 'active'
    assert dict(db.fetchone('SELECT * FROM learning_goal WHERE id=?', (other['goal_id'],))) == before_other
    assert db.fetchone('SELECT COUNT(*) FROM learning_completion')[0] == 0
    assert db.fetchone('SELECT COUNT(*) FROM learning_evidence_claim')[0] == 0
    for command in [
        StartSession(delegation_id=first['delegation_id'], expected_version=version(db, first['action_id'])),
        CompleteLearningAction(action_id=first['action_id'], delegation_id=first['delegation_id'], expected_version=version(db, first['action_id'])),
        setup_command(plan_id=first['plan_id']),
    ]:
        with pytest.raises(DomainError, match='goal_not_active'):
            core.execute(OWNER, command, f'blocked:{type(command).__name__}')
    with pytest.raises(DomainError, match='goal_invalid_transition'):
        change(core, first['goal_id'], 'paused', 'closed-to-closed')
    reopened = change(core, first['goal_id'], 'active', 'reopen')
    assert reopened['interrupted_session_ids'] == []
    assert db.fetchone("SELECT count(*) FROM learning_session WHERE status='running'")[0] == 0
    assert [row['status'] for row in review(db, first['goal_id'])['history']] == ['active', status]
    before_replay = [dict(row) for row in db.fetchall('SELECT * FROM learning_goal ORDER BY id')]
    core.replay(OWNER)
    assert [dict(row) for row in db.fetchall('SELECT * FROM learning_goal ORDER BY id')] == before_replay
    assert [row['status'] for row in review(db, first['goal_id'])['history']] == ['active', status]
    core.execute(OWNER, StartSession(delegation_id=first['delegation_id'],
        expected_version=version(db, first['action_id'])), 'resume-after-reopen')


def test_stale_review_wrong_owner_and_agent_cannot_close(domain_rows):
    core = LearningCore(domain_rows)
    first = core.execute(OWNER, setup_command(), 'a')
    snapshot = review(domain_rows, first['goal_id'])
    core.execute(OWNER, setup_command(plan_id=first['plan_id']), 'second-task')
    with pytest.raises(DomainError, match='goal_review_changed'):
        change(core, first['goal_id'], 'completed', 'stale', snapshot)
    snapshot = review(domain_rows, first['goal_id'])
    command = ChangeGoalStatus(goal_id=first['goal_id'], status='completed',
        expected_version=snapshot['goal']['version'], review_key=snapshot['review_key'])
    with pytest.raises(DomainError, match='not_found'):
        core.execute(Principal.user('owner-b'), command, 'foreign')
    with pytest.raises(DomainError, match='permission_denied'):
        core.execute(Principal.agent('owner-a', 'assistant', action_ids=frozenset({first['action_id']}), tools=frozenset()), command, 'agent')
    assert change(core, first['goal_id'], 'completed', 'confirmed')['status'] == 'completed'
    with pytest.raises(DomainError, match='idempotency_conflict'):
        core.execute(OWNER, command.model_copy(update={'status': 'paused'}), 'confirmed')


def test_return_card_stale_start_and_other_goal_selection(domain_rows):
    core = LearningCore(domain_rows)
    first = core.execute(OWNER, setup_command(), 'a')
    continuity = ContinuityService(LearningService(domain_rows))
    identity = identity_payload()
    card = continuity.get(identity)
    started = continuity.decide(identity, card['id'], 'continue', 'start-first')
    change(core, first['goal_id'], 'archived', 'close')
    with pytest.raises(DomainError, match='goal_not_active'):
        continuity.decide(identity, card['id'], 'continue', 'start-first')
    closed_card = continuity.get(identity)
    assert closed_card['position']['goal_status'] == 'archived'
    assert closed_card['recommendation']['reason_code'] == 'goal_closed'
    assert not closed_card['alternatives']
    with pytest.raises(DomainError, match='goal_not_active'):
        continuity.decide(identity, closed_card['id'], 'continue', 'stale-close')
    other = core.execute(OWNER, setup_command(goal_title='继续其他目标'), 'b')
    next_card = continuity.get(identity)
    assert next_card['position']['goal_id'] == other['goal_id']
    assert all(item['delegation_id'] != first['delegation_id'] for item in next_card['alternatives'])
    assert started['session_id'] != continuity.decide(identity, next_card['id'], 'continue', 'start-other')['session_id']


def test_goal_review_api_and_status_request(tmp_path):
    from test_ai_conversations import make_client, authorize
    with make_client(tmp_path, lambda request: None) as client:
        assert client.get('/api/learning/goals/missing/review').status_code == 401
        authorize(client)
        payload = setup_command().model_dump()
        created = client.post('/api/learning/setup/confirm', json={**payload, 'idempotency_key': 'setup'})
        assert created.status_code == 201, created.text
        goal_id = created.json()['goal_id']
        preview = client.get(f'/api/learning/goals/{goal_id}/review')
        assert preview.status_code == 200
        assert preview.headers['cache-control'] == 'no-store'
        data = preview.json()
        body = dict(status='completed', expected_version=data['goal']['version'], review_key=data['review_key'], idempotency_key='finish')
        changed = client.post(f'/api/learning/goals/{goal_id}/status', json=body)
        assert changed.status_code == 200, changed.text
        assert changed.json()['status'] == 'completed'
        assert client.post(f'/api/learning/goals/{goal_id}/status', json=body).json() == changed.json()
        assert client.get('/api/learning/goals/missing/review').status_code == 404
        assert client.get(f'/api/learning/goals/{goal_id}/review').json()['history'][0]['status'] == 'completed'


def test_goal_closure_keeps_completed_and_open_tasks_distinct(domain_rows):
    core = LearningCore(domain_rows)
    first = core.execute(OWNER, setup_command(), 'first')
    second = core.execute(OWNER, setup_command(plan_id=first['plan_id']), 'second')
    core.execute(OWNER, CompleteLearningAction(action_id=first['action_id'],
        delegation_id=first['delegation_id'], expected_version=version(domain_rows, first['action_id'])), 'complete-task')
    snapshot = review(domain_rows, first['goal_id'])
    assert snapshot['counts'] == dict(total_tasks=2, completed_tasks=1, open_tasks=1, running_sessions=0)
    change(core, first['goal_id'], 'completed', 'finish-goal')
    assert review(domain_rows, first['goal_id'])['counts'] == snapshot['counts']
    assert domain_rows.fetchone('SELECT status FROM learning_action WHERE id=?', (second['action_id'],))[0] == 'open'
    core.replay(OWNER)
    assert review(domain_rows, first['goal_id'])['counts'] == snapshot['counts']
