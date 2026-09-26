"""Version-local display observations and immutable submission conditions.

These are client observations, not proof of reading or independent performance.
No answer text is copied into an observation.
"""
import json

from .learning_domain import DomainError
from .core.learning import utc_timestamp


def record_solution_display(service, identity, verification_id, evaluation_id, question_id):
    owner = service.learning.principal(identity).owner_id
    with service.learning.database.transaction(immediate=True) as connection:
        current = service._owned(owner, verification_id)
        row = connection.execute('''SELECT e.*, s.purged_at AS submission_purged
            FROM learning_verification_evaluation e
            JOIN learning_verification_submission s ON s.id=e.submission_id AND s.owner_id=e.owner_id
            WHERE e.owner_id=? AND e.id=? AND s.verification_id=?''',
            (owner, evaluation_id, verification_id)).fetchone()
        if row is None:
            raise DomainError('not_found', 404)
        if current['purged_at'] or row['submission_purged']:
            raise DomainError('artifact_not_eligible', 409)
        feedback = json.loads(row['result_json'] or '{}').get('question_feedback', [])
        if not any(item['question_id'] == question_id and item.get('reference_answer', '').strip() for item in feedback):
            raise DomainError('not_found', 404)
        snapshot = json.loads(row['provider_snapshot_json'] or '{}')
        displays = snapshot.setdefault('help_displays', {})
        if question_id not in displays:
            displays[question_id] = dict(kind='reference_answer', at=utc_timestamp(), basis='client_report')
            connection.execute('UPDATE learning_verification_evaluation SET provider_snapshot_json=? WHERE id=?',
                (json.dumps(snapshot, ensure_ascii=False), evaluation_id))
        return displays[question_id]


def submission_help_context(connection, owner, verification_id, user_report, captured_at):
    """Freeze only observations about these questions before this submission.

    Prior teaching elsewhere is neither proof of help on this answer nor proof
    of independence. Later displays cannot mutate the returned snapshot.
    """
    records = []
    for row in connection.execute('''SELECT e.id, e.provider_snapshot_json
        FROM learning_verification_evaluation e
        JOIN learning_verification_submission s ON s.id=e.submission_id AND s.owner_id=e.owner_id
        WHERE s.owner_id=? AND s.verification_id=? AND s.purged_at IS NULL ORDER BY e.rowid''', (owner, verification_id)):
        for question_id, display in json.loads(row['provider_snapshot_json'] or '{}').get('help_displays', {}).items():
            records.append(dict(kind='reference_answer', evaluation_id=row['id'], question_id=question_id,
                                displayed_at=display['at']))
    for row in connection.execute('''SELECT t.*, d.question_id FROM learning_discussion_turn t
        JOIN learning_question_discussion d ON d.id=t.discussion_id
        WHERE d.owner_id=? AND d.verification_id=? AND d.purged_at IS NULL
        AND t.status!='purged' ORDER BY t.rowid''', (owner, verification_id)):
        if not (row['assistant_content'] or '').strip():
            continue
        snapshot = json.loads(row['provider_snapshot_json'] or '{}')
        records.append(dict(kind='discussion_reply', discussion_id=row['discussion_id'], turn_id=row['id'],
            question_id=row['question_id'], provided_at=row['finished_at'],
            displayed_at=snapshot.get('help_display', {}).get('at'), characters=len(row['assistant_content']),
            partial=row['status'] != 'succeeded'))
    return dict(captured_at=captured_at, user_report=user_report, coverage='same_verification',
                records=records, independence='not_inferred')
