"""Task removal from current/candidate routes retains the original learning facts."""
import pytest

from app.core.commands import SaveTextArtifact
from test_learning_paths import seed, path, draft, confirm, start
from test_plan_organization import get as organization, rows
from test_commitments import arranged, save as arrange, confirm as adopt_arrangement, item


def body(client, plan_id, action_id, node_id='entry', mode='detach', **changes):
    current = path(client, plan_id)
    action = next(action for action in client.get('/api/learning/state').json()['actions'] if action['id'] == action_id)
    value = dict(action_id=action_id, node_id=node_id, version_id=current['adopted_version_id'],
        expected_revision=current['revision'], expected_organization_revision=current['organization_revision'],
        expected_action_version=action['version'], mode=mode)
    value.update(changes)
    return value


def preview_removal(client, plan_id, value):
    response = client.post(f'/api/learning/plans/{plan_id}/path/task-removal-preview', json=value)
    assert response.status_code == 200, response.text
    return response.json()


def remove(client, plan_id, value, key='remove-task'):
    reviewed = preview_removal(client, plan_id, value)
    response = client.post(f'/api/learning/plans/{plan_id}/path/task-removals',
        json={**value, 'review_key': reviewed['review_key'], 'request_key': key})
    assert response.status_code == 200, response.text
    return response.json(), reviewed


def test_detach_only_selected_stage_keeps_task_plan_outcome_and_original_snapshot(client):
    identity, plan_id, first, second = seed(client)
    saved, _ = draft(client, plan_id, first, second)
    adopted, _ = confirm(client, plan_id, saved)
    db = client.app.state.learning.database
    before = rows(db, ('learning_action', 'learning_delegation', 'learning_action_link', 'learning_outcome', 'learning_action_removal'))
    value = body(client, plan_id, second['action_id'], 'practice')
    checked = preview_removal(client, plan_id, value)
    assert checked['affected_sessions'] == []
    assert rows(db, before.keys()) == before
    changed, _ = remove(client, plan_id, value)
    current = next(version for version in changed['versions'] if version['id'] == changed['adopted_version_id'])
    old = next(version for version in changed['versions'] if version['id'] == adopted['adopted_version_id'])
    assert current['nodes'][1]['action_ids'] == []
    assert current['nodes'][1]['outcome_ids'] == [second['outcome_id']]
    assert old['nodes'][1]['action_ids'] == [second['action_id']]
    assert changed['current_node_id'] == adopted['current_node_id']
    assert second['action_id'] in {task['id'] for task in organization(client, plan_id)['tasks']}
    assert rows(db, before.keys()) == before
    repeated = client.post(f'/api/learning/plans/{plan_id}/path/task-removals',
        json={**value, 'review_key': checked['review_key'], 'request_key': 'remove-task'})
    assert repeated.status_code == 200 and repeated.json() == changed
    assert client.app.state.learning.core.replay(client.app.state.learning.principal(identity))['comparison']['matched']


def test_delete_pauses_only_target_and_defers_remaining_arrangement_without_erasing_work(arranged):
    ctx = arranged
    client, db, plan_id = ctx['client'], ctx['db'], ctx['plan_id']
    commitment = adopt_arrangement(ctx, arrange(ctx, [item(ctx), item(ctx, 'second')]))
    current_path = path(client, plan_id)
    running = start(client, plan_id, current_path, 'entry', ctx['first']['delegation_id'])
    action = next(action for action in client.get('/api/learning/state').json()['actions'] if action['id'] == ctx['first']['action_id'])
    artifact = client.app.state.learning.core.execute(client.app.state.learning.principal(ctx['identity']),
        SaveTextArtifact(session_id=running['session_id'], content='SYNTHETIC WORK TO KEEP', expected_version=action['version']), 'work-before-delete')
    original = rows(db, ('learning_raw_artifact', 'learning_artifact', 'learning_outcome', 'learning_evidence_claim', 'learning_completion'))
    value = body(client, plan_id, ctx['first']['action_id'], mode='delete')
    changed, checked = remove(client, plan_id, value)
    assert [session['id'] for session in checked['affected_sessions']] == [running['session_id']]
    target_item = commitment['current_version']['items'][0]['id']
    assert next(change for change in checked['commitment_changes'] if change['item_id'] == target_item)['kind'] == 'defer'
    state = client.get('/api/learning/state').json()
    removed = next(action for action in state['actions'] if action['id'] == ctx['first']['action_id'])
    assert removed['deleted'] and removed['status'] == 'cancelled'
    assert db.fetchone('SELECT status FROM learning_session WHERE id=?', (running['session_id'],))[0] == 'interrupted'
    assert rows(db, original.keys()) == original
    assert db.fetchone('SELECT content FROM learning_raw_artifact WHERE artifact_id=?', (artifact['id'],))[0] == 'SYNTHETIC WORK TO KEEP'
    assert ctx['first']['action_id'] not in {task['id'] for task in organization(client, plan_id)['tasks']}
    current = next(version for version in changed['versions'] if version['id'] == changed['adopted_version_id'])
    assert all(ctx['first']['action_id'] not in node['action_ids'] for node in current['nodes'])
    old = next(version for version in changed['versions'] if version['id'] == current_path['adopted_version_id'])
    assert old['checkpoint']['session_id'] == running['session_id']
    assert current['checkpoint']['session_id'] is None
    assert client.app.state.learning.core.replay(client.app.state.learning.principal(ctx['identity']))['comparison']['matched']


def test_candidate_delete_updates_current_and_candidate_without_adopting_candidate(client):
    identity, plan_id, first, second = seed(client)
    saved, _ = draft(client, plan_id, first, second)
    adopted, _ = confirm(client, plan_id, saved)
    candidate, _ = draft(client, plan_id, first, second)
    selected = candidate['drafts'][0]
    value = body(client, plan_id, first['action_id'], mode='delete', version_id=None,
        draft_id=selected['id'], expected_draft_revision=selected['revision'])
    changed, _ = remove(client, plan_id, value)
    assert changed['adopted_version_id'] != adopted['adopted_version_id']
    assert len(changed['versions']) == 2
    assert changed['drafts'][0]['id'] == selected['id'] and not changed['drafts'][0]['stale']
    assert all(first['action_id'] not in node['action_ids'] for node in changed['drafts'][0]['nodes'])
    current = next(version for version in changed['versions'] if version['id'] == changed['adopted_version_id'])
    assert all(first['action_id'] not in node['action_ids'] for node in current['nodes'])
    assert not client.get('/api/learning/state').json()['sessions']
    assert client.app.state.learning.core.replay(client.app.state.learning.principal(identity))['comparison']['matched']


def test_removal_rejects_stale_or_wrong_reference_and_late_failure_rolls_back_all_changes(client, monkeypatch):
    _identity, plan_id, first, second = seed(client)
    saved, _ = draft(client, plan_id, first, second)
    adopted, _ = confirm(client, plan_id, saved)
    running = start(client, plan_id, adopted, 'entry', first['delegation_id'])
    value = body(client, plan_id, first['action_id'], mode='delete')
    checked = preview_removal(client, plan_id, value)
    for invalid in [dict(expected_revision=0), dict(expected_organization_revision=999),
                    dict(expected_action_version=999), dict(node_id='practice')]:
        response = client.post(f'/api/learning/plans/{plan_id}/path/task-removal-preview', json={**value, **invalid})
        assert response.status_code in {409, 422}
    wrong_preview = client.post(f'/api/learning/plans/{plan_id}/path/task-removals',
        json={**value, 'review_key': 'wrong', 'request_key': 'wrong-review'})
    assert wrong_preview.status_code == 409
    from app.core import learning_paths
    append = learning_paths._append
    def fail(*args, **kwargs):
        if args[-2] == 'path.decision_confirmed':
            raise RuntimeError('synthetic last route removal failure')
        return append(*args, **kwargs)
    monkeypatch.setattr(learning_paths, '_append', fail)
    db = client.app.state.learning.database
    tables = ('learning_action', 'learning_delegation', 'learning_action_removal', 'learning_plan_child',
        'learning_plan_organization', 'learning_action_link', 'learning_session', 'learning_path_version',
        'learning_plan_path_state', 'learning_path_checkpoint', 'learning_path_draft', 'learning_path_private',
        'learning_event', 'learning_command', 'learning_stream_head')
    original = rows(db, tables)
    with pytest.raises(RuntimeError, match='last route removal'):
        client.post(f'/api/learning/plans/{plan_id}/path/task-removals',
            json={**value, 'review_key': checked['review_key'], 'request_key': 'late-removal'})
    assert rows(db, tables) == original
    assert db.fetchone('SELECT status FROM learning_session WHERE id=?', (running['session_id'],))[0] == 'running'


def test_delete_rechecks_generation_after_preview_without_interrupting_or_removing(client):
    from test_learning_paths import link_chat
    identity, plan_id, first, second = seed(client)
    saved, _ = draft(client, plan_id, first, second)
    adopted, _ = confirm(client, plan_id, saved)
    running = start(client, plan_id, adopted, 'entry', first['delegation_id'])
    conversation_id = link_chat(client, running['session_id'])
    value = body(client, plan_id, first['action_id'], mode='delete')
    checked = preview_removal(client, plan_id, value)
    chatdb = client.app.state.conversations.database
    with chatdb.transaction() as connection:
        connection.execute("INSERT INTO ai_run(id,identity_id,conversation_id,status,created_at,updated_at) VALUES ('synthetic-removal-run',?,?,'running','now','now')", (identity['id'], conversation_id))
    original = rows(client.app.state.learning.database, ('learning_action_removal', 'learning_action', 'learning_session', 'learning_plan_path_state'))
    response = client.post(f'/api/learning/plans/{plan_id}/path/task-removals',
        json={**value, 'review_key': checked['review_key'], 'request_key': 'busy-remove'})
    assert response.status_code == 409 and response.json()['detail']['kind'] == 'path_generation_running'
    assert rows(client.app.state.learning.database, original.keys()) == original
    with chatdb.transaction() as connection:
        connection.execute("UPDATE ai_run SET status='canceled' WHERE id='synthetic-removal-run'")
    remove(client, plan_id, value)


def test_candidate_task_delete_does_not_resume_a_paused_original_direction(client):
    from test_learning_paths import transfer_body
    _identity, plan_id, first, second = seed(client)
    saved, _ = draft(client, plan_id, first, second)
    adopted, _ = confirm(client, plan_id, saved)
    candidate, _ = draft(client, plan_id, first, second)
    url = f'/api/learning/plans/{plan_id}/path'
    transfer = transfer_body(candidate, first)
    review = client.post(url+'/transfer-preview', json=transfer)
    assert review.status_code == 200, review.text
    moved = client.post(url+'/transfer', json={**transfer, 'review_key': review.json()['review_key'], 'request_key': 'pause-original'})
    assert moved.status_code == 200, moved.text
    current = path(client, plan_id)
    assert current['status'] == 'paused'
    selected = current['drafts'][0]
    value = body(client, plan_id, first['action_id'], mode='delete', version_id=None,
        draft_id=selected['id'], expected_draft_revision=selected['revision'])
    changed, _ = remove(client, plan_id, value)
    assert changed['status'] == 'paused' and changed['adopted_version_id'] == adopted['adopted_version_id']
    assert not changed['drafts'][0]['stale']
    assert all(first['action_id'] not in node['action_ids'] for node in changed['drafts'][0]['nodes'])
