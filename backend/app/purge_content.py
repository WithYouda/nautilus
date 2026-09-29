"""Erase the selected object's explicit copies, including older backup schemas.

Runs in the caller's transaction. Historical evidence text is the sole exception
to append-only events: redact it and rebuild the affected hash chains atomically.
"""
from __future__ import annotations

import json

from .evidence_events import _canonical, _event_hash


def columns(connection, table):
    return {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}


def _ids(connection, table, field, where, params):
    if not columns(connection, table):
        return set()
    return {row[0] for row in connection.execute(f'SELECT {field} FROM {table} WHERE {where}', params)}


def _update(connection, table, values, where, params):
    available = columns(connection, table)
    values = {key: value for key, value in values.items() if key in available}
    if values:
        connection.execute(f'UPDATE {table} SET ' + ','.join(f'{key}=?' for key in values) + ' WHERE ' + where,
                           (*values.values(), *params))


def _event_claims(event, payload):
    result = set(payload.get('claim_ids', []))
    result.update(payload[key] for key in ('claim_id', 'superseded_claim_id', 'replacement_claim_id') if payload.get(key))
    if event['aggregate_type'] == 'claim':
        result.add(event['aggregate_id'])
    return result


def _redact_events(connection, owner, claim_ids, now):
    if not columns(connection, 'learning_evidence_event'):
        return
    events = [dict(row) for row in connection.execute('''SELECT * FROM learning_evidence_event
        WHERE owner_id=? ORDER BY aggregate_type,aggregate_id,event_version''', (owner,))]
    originals = [dict(event) for event in events]
    shared_review_keys = set()
    for event in events:
        payload = json.loads(event['payload_json'])
        if event['event_type'] == 'batch.reviewed' and claim_ids.intersection(payload.get('claim_ids', [])):
            shared_review_keys.update(f"{payload['request_key']}:{claim}" for claim in payload['claim_ids'])
    changed = set()
    for event in events:
        payload = json.loads(event['payload_json'])
        if not claim_ids.intersection(_event_claims(event, payload)) and payload.get('request_key') not in shared_review_keys:
            continue
        if columns(connection, 'learning_evidence_private_content'):
            connection.execute('''UPDATE learning_evidence_private_content SET content_json=NULL,purged_at=?
                WHERE event_id=? AND purged_at IS NULL''', (now, event['id']))
        redacted = dict(payload)
        for key, value in {'statement': '内容已彻底删除', 'reason': None, 'note': None,
                           'scope': 'artifact', 'verification_method': 'redacted'}.items():
            if key in redacted:
                redacted[key] = '内容已彻底删除' if key == 'reason' and event['event_type'] == 'claim.replaced' else value
        # This private fingerprint is unnecessary after erasure.
        redacted.pop('private_content_hash', None)
        if redacted != payload:
            if event['event_hash'] != _event_hash(event):
                raise ValueError('evidence_integrity_failed')
            event['payload_json'] = _canonical(redacted)
            changed.add((event['aggregate_type'], event['aggregate_id']))
    if not changed:
        return
    chains = {}
    for event in originals:
        stream = (event['aggregate_type'], event['aggregate_id'])
        if stream in changed:
            version, previous_hash = chains.get(stream, (0, None))
            if (event['event_hash'] != _event_hash(event) or event['previous_hash'] != previous_hash
                    or event['event_version'] != version + 1):
                raise ValueError('evidence_integrity_failed')
            chains[stream] = (event['event_version'], event['event_hash'])
    trigger = connection.execute("SELECT sql FROM sqlite_master WHERE name='learning_evidence_event_no_update'").fetchone()
    if trigger:
        connection.execute('DROP TRIGGER learning_evidence_event_no_update')
    previous = {}
    for event in events:
        stream = (event['aggregate_type'], event['aggregate_id'])
        if stream not in changed:
            continue
        event['previous_hash'] = previous.get(stream)
        event['event_hash'] = _event_hash(event)
        previous[stream] = event['event_hash']
        connection.execute('UPDATE learning_evidence_event SET payload_json=?,previous_hash=?,event_hash=? WHERE id=?',
                           (event['payload_json'], event['previous_hash'], event['event_hash'], event['id']))
    if trigger:
        connection.execute(trigger[0])


def _erase_practices(connection, owner, practice_ids, now):
    """Erase one practice and exercises derived from its private recheck result."""
    if not columns(connection, 'learning_practice'):
        return
    affected = set(practice_ids)
    pending = set(affected)
    while pending:
        children = set()
        for practice_id in pending:
            children.update(_ids(connection, 'learning_practice', 'id',
                "owner_id=? AND (json_extract(request_json,'$.recheck_id')=? "
                "OR json_extract(request_json,'$.previous_id')=?)", (owner, practice_id, practice_id)))
        pending = children - affected
        affected.update(pending)
    for practice_id in affected:
        _update(connection, 'learning_practice', dict(request_json=None, request_fingerprint=None,
            contract_snapshot_json=None, content_json=None, provider_name=None, model=None,
            status='purged', reason='content_purged', purged_at=now), 'owner_id=? AND id=?', (owner, practice_id))
        _update(connection, 'learning_practice_attempt', dict(answer=None, condition_json=None,
            request_fingerprint=None, purged_at=now), 'owner_id=? AND practice_id=?', (owner, practice_id))
        _update(connection, 'learning_practice_run', dict(result_json=None, provider_name=None,
            model=None, displayed_at=None, status='failed', reason='content_purged',
            finished_at=now, purged_at=now), 'owner_id=? AND practice_id=?', (owner, practice_id))


def _erase_delayed(connection, owner, follow_up_ids, now):
    """Explicitly scrub children, including snapshots without the 032 triggers."""
    if not columns(connection, 'learning_delayed_follow_up'):
        return
    for follow_up_id in follow_up_ids:
        _update(connection, 'learning_delayed_follow_up', dict(
            standard_snapshot_json=None, request_fingerprint=None, history_json=None,
            due_at=None, timezone=None, arranged_at=None, started_at=None,
            status='purged', purged_at=now), 'owner_id=? AND id=?', (owner, follow_up_id))
        _update(connection, 'learning_delayed_attempt', dict(
            answers_json=None, user_report=None, condition_json=None,
            submit_fingerprint=None, result_json=None, check_status='not_checked',
            purged_at=now), 'owner_id=? AND follow_up_id=?', (owner, follow_up_id))
        _update(connection, 'learning_delayed_view', dict(
            provided_at=None, displayed_at=None, after_arranging=None, purged_at=now),
            'owner_id=? AND follow_up_id=?', (owner, follow_up_id))


def erase(connection, owner, kind, object_id, now, *, submission_ids=(), artifact_ids=()):
    """Keeps unrelated rows, object identities and execution facts intact."""
    if kind == 'completion':
        _update(connection, 'learning_completion', dict(content_json=None, contract_snapshot_json=None,
            request_fingerprint=None, purged_at=now), 'owner_id=? AND id=?', (owner, object_id))
        _update(connection, 'learning_completion_review', dict(result_json=None, user_response=None,
            provider_name=None, model=None, status='failed', reason='completion_content_deleted', finished_at=now),
            'owner_id=? AND completion_id=?', (owner, object_id))
        return

    if kind == 'practice':
        _erase_practices(connection, owner, {object_id}, now)
        return

    if kind == 'delayed':
        _erase_delayed(connection, owner, {object_id}, now)
        return

    artifacts = {object_id} if kind == 'artifact' else set()
    artifacts.update(artifact_ids)
    submissions = set()
    if kind == 'verification' or (kind == 'artifact' and 'artifact_id' in columns(connection, 'learning_verification_submission')):
        submissions = _ids(connection, 'learning_verification_submission', 'id',
            'owner_id=? AND ' + ('verification_id=?' if kind == 'verification' else 'artifact_id=?'), (owner, object_id))
    for submission_id in submission_ids:
        submissions.update(_ids(connection, 'learning_verification_submission', 'id', 'owner_id=? AND id=?', (owner, submission_id)))
    practice_ids = set()
    for submission in submissions:
        practice_ids.update(_ids(connection, 'learning_practice', 'id',
            'owner_id=? AND submission_id=?', (owner, submission)))
    _erase_practices(connection, owner, practice_ids, now)
    for submission in submissions:
        if 'artifact_id' in columns(connection, 'learning_verification_submission'):
            artifacts.update(_ids(connection, 'learning_verification_submission', 'artifact_id', 'owner_id=? AND id=? AND artifact_id IS NOT NULL', (owner, submission)))
        _update(connection, 'learning_verification_submission', dict(content_json='{}', purged_at=now),
                'owner_id=? AND id=?', (owner, submission))
        _update(connection, 'learning_verification_evaluation', dict(result_json=None, provider_snapshot_json=None,
                reason='content_purged'), 'owner_id=? AND submission_id=?', (owner, submission))
        if 'latest_submission_id' in columns(connection, 'learning_verification'):
            _update(connection, 'learning_verification', dict(submission_json=None, result_json=None),
                    'owner_id=? AND latest_submission_id=?', (owner, submission))
    if artifacts and columns(connection, 'learning_delayed_follow_up'):
        delayed_ids = set()
        for artifact in artifacts:
            delayed_ids.update(_ids(connection, 'learning_delayed_follow_up', 'id',
                'owner_id=? AND source_artifact_id=?', (owner, artifact)))
        _erase_delayed(connection, owner, delayed_ids, now)
    if kind == 'verification':
        _update(connection, 'learning_verification', dict(answer_key_json='{}', challenge_json='{}',
            submission_json=None, result_json=None, contract_snapshot_json='{"version":0,"stop_conditions":""}', purged_at=now),
            'owner_id=? AND id=?', (owner, object_id))
    # Also handles backups made before the discussion-erasure triggers existed.
    discussions = set()
    for submission in submissions:
        discussions.update(_ids(connection, 'learning_question_discussion', 'id', 'owner_id=? AND submission_id=?', (owner, submission)))
    while True:
        expanded = set(discussions)
        for discussion in discussions:
            expanded.update(_ids(connection, 'learning_discussion_dependency', 'discussion_id', 'source_discussion_id=?', (discussion,)))
        if expanded == discussions:
            break
        discussions = expanded
    for discussion in discussions:
        _update(connection, 'learning_question_discussion', dict(purged_at=now, title=None, title_source='source'), 'owner_id=? AND id=?', (owner, discussion))
        _update(connection, 'learning_discussion_turn', dict(user_content=None, assistant_content=None, reasoning_content=None,
            sources_json='[]', provider_snapshot_json='{}', status='purged', reason='content_purged', finished_at=now),
            'discussion_id=?', (discussion,))
        # A saved library group has its own lifecycle. Older snapshots lack the
        # library table and retain the original discussion-owned behavior.
        library_filter = (''' AND NOT EXISTS (SELECT 1 FROM learning_material_library library
            WHERE library.owner_id=learning_task_material.owner_id
              AND library.material_id=learning_task_material.material_id)'''
            if columns(connection, 'learning_material_library') else '')
        _update(connection, 'learning_task_material', dict(title=None, content=None, url=None,
            provenance_json='{}', purged_at=now),
            'owner_id=? AND scope_kind=? AND scope_id=?' + library_filter,
            (owner, 'discussion', discussion))
        _update(connection, 'learning_material_original', dict(filename=None, media_type=None,
            content=None, sha256=None, purged_at=now),
            '''version_id IN (SELECT id FROM learning_task_material
                WHERE owner_id=? AND scope_kind=? AND scope_id=? AND purged_at IS NOT NULL)''',
            (owner, 'discussion', discussion))

    claims = set()
    for artifact in artifacts:
        connection.execute('''UPDATE learning_raw_artifact SET content=NULL,content_hash=NULL,purged_at=?
            WHERE owner_id=? AND artifact_id=? AND purged_at IS NULL''', (now, owner, artifact))
        _update(connection, 'learning_artifact', dict(visibility='purged', evidence_status='invalidated'), 'owner_id=? AND id=?', (owner, artifact))
        claims.update(_ids(connection, 'learning_evidence_claim', 'id', 'owner_id=? AND artifact_id=?', (owner, artifact)))
    for claim in claims:
        _update(connection, 'learning_evidence_claim', dict(statement='内容已彻底删除', scope='artifact', verification_method='redacted', status='invalidated'), 'owner_id=? AND id=?', (owner, claim))
        _update(connection, 'learning_review_action', dict(reason=None), 'owner_id=? AND claim_id=?', (owner, claim))
        _update(connection, 'learning_evidence_follow_up', dict(note=None, status='cancelled'), 'owner_id=? AND claim_id=?', (owner, claim))
        _update(connection, 'learning_claim_replacement', dict(reason='内容已彻底删除'), 'owner_id=? AND (superseded_claim_id=? OR replacement_claim_id=?)', (owner, claim, claim))
    if columns(connection, 'learning_batch_review_action'):
        for row in connection.execute('SELECT id,claim_ids_json,request_key FROM learning_batch_review_action WHERE owner_id=?', (owner,)).fetchall():
            if claims.intersection(json.loads(row['claim_ids_json'])):
                _update(connection, 'learning_batch_review_action', dict(reason=None), 'id=?', (row['id'],))
                # A batch's per-claim reviews share the same private reason.
                for claim in json.loads(row['claim_ids_json']):
                    _update(connection, 'learning_review_action', dict(reason=None), 'owner_id=? AND claim_id=? AND request_key=?', (owner, claim, f"{row['request_key']}:{claim}"))
    _redact_events(connection, owner, claims, now)
