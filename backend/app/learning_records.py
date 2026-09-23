"""Owner-only review reads; summaries never copy answer bodies."""
import json

from .learning_domain import DomainError
from .learning_room import LearningRoomService
from .verification_content import submission_content


class LearningRecords:
    def __init__(self, verification):
        self.verification = verification
        self.learning = verification.learning
        self.db = self.learning.database

    def detail(self, identity, verification_id, submission_id=None, evaluation_id=None):
        owner = self.learning.principal(identity).owner_id
        # Keep content and purge status in one snapshot.
        with self.db.transaction() as connection:
            return self.read_detail(connection, owner, verification_id, submission_id, evaluation_id)

    def read_detail(self, connection, owner, verification_id, submission_id=None, evaluation_id=None):
        current = self.verification._owned(owner, verification_id)
        public = self.verification._public(current)
        submissions = [dict(r) for r in connection.execute(
            'SELECT id, created_at, purged_at FROM learning_verification_submission WHERE owner_id=? AND verification_id=? ORDER BY rowid DESC',
            (owner, verification_id))]
        selected_id = submission_id or current['latest_submission_id']
        selected = next((s for s in submissions if s['id'] == selected_id), None)
        if selected_id and selected is None:
            raise DomainError('not_found', 404)
        content = None
        evaluations = []
        if selected and not selected['purged_at'] and not current['purged_at']:
            row = connection.execute('SELECT * FROM learning_verification_submission WHERE owner_id=? AND id=?', (owner, selected_id)).fetchone()
            content = submission_content(connection, owner, row)
            evaluations = [dict(r) for r in connection.execute(
                'SELECT id, status, reason, created_at, finished_at, result_json FROM learning_verification_evaluation WHERE owner_id=? AND submission_id=? ORDER BY rowid DESC',
                (owner, selected_id))]
        for evaluation in evaluations:
            evaluation['result'] = json.loads(evaluation.pop('result_json') or 'null')
        chosen = next((e for e in evaluations if e['id'] == evaluation_id), None) if evaluation_id else (evaluations[0] if evaluations else None)
        if evaluation_id and chosen is None:
            raise DomainError('not_found', 404)
        discussions = [dict(r) for r in connection.execute(
            'SELECT id, question_id, submission_id, created_at, purged_at FROM learning_question_discussion WHERE owner_id=? AND verification_id=? ORDER BY rowid DESC', (owner, verification_id))]
        return dict(verification=public, submissions=submissions, selected_submission_id=selected_id,
                    content=content, evaluations=evaluations, selected_evaluation_id=chosen['id'] if chosen else None,
                    result=chosen['result'] if chosen else None, discussions=discussions,
                    purge_discussion_count=self.purge_impact(connection, owner, verification_id))

    @staticmethod
    def purge_impact(connection, owner, verification_id):
        return connection.execute('''WITH RECURSIVE affected(id) AS (
            SELECT id FROM learning_question_discussion WHERE owner_id=? AND verification_id=?
            UNION SELECT d.discussion_id FROM learning_discussion_dependency d JOIN affected a ON d.source_discussion_id=a.id
        ) SELECT COUNT(*) FROM learning_question_discussion WHERE id IN (SELECT id FROM affected) AND purged_at IS NULL''', (owner, verification_id)).fetchone()[0]

    def list(self, identity):
        owner = self.learning.principal(identity).owner_id
        return [dict(r) for r in self.db.fetchall('''SELECT d.id, d.status, d.action_id, a.title,
            COALESCE(g.title,'') AS goal_title, COALESCE(p.title,'') AS plan_title, d.created_at,
            (SELECT id FROM learning_session s WHERE s.owner_id=d.owner_id AND s.delegation_id=d.id ORDER BY s.rowid DESC LIMIT 1) AS session_id,
            (SELECT COUNT(*) FROM learning_verification v WHERE v.owner_id=d.owner_id AND v.delegation_id=d.id) AS verification_count
            FROM learning_delegation d JOIN learning_action a ON a.owner_id=d.owner_id AND a.id=d.action_id
            LEFT JOIN learning_action_link l ON l.owner_id=d.owner_id AND l.action_id=d.action_id
            LEFT JOIN learning_plan p ON p.owner_id=l.owner_id AND p.id=l.plan_id
            LEFT JOIN learning_goal g ON g.owner_id=p.owner_id AND g.id=p.goal_id
            WHERE d.owner_id=? ORDER BY d.rowid DESC''', (owner,))]

    def delegation(self, identity, delegation_id):
        item = next((r for r in self.list(identity) if r['id'] == delegation_id), None)
        if item is None:
            raise DomainError('not_found', 404)
        owner = self.learning.principal(identity).owner_id
        verifications = [dict(r) for r in self.db.fetchall('''SELECT id, mode, status, session_id, created_at, submitted_at, purged_at
            FROM learning_verification WHERE owner_id=? AND delegation_id=? ORDER BY rowid DESC''', (owner, delegation_id))]
        room = LearningRoomService(self.learning, self.verification.conversations).get(identity, item['session_id']) if item['session_id'] else None
        return dict(record=item, verifications=verifications, brief=room['brief'] if room else None)
