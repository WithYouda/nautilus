"""Read one outcome's explicit links without creating another evidence archive."""
import json

from .learning_domain import DomainError
from .learning_records import LearningRecords
from .state_derivation import StateDerivationService


class OutcomeReview:
    def __init__(self, verification):
        self.learning = verification.learning
        self.db = self.learning.database
        self.records = LearningRecords(verification)

    def get(self, identity, outcome_id):
        owner = self.learning.principal(identity).owner_id
        with self.db.transaction() as connection:
            outcome = connection.execute(
                'SELECT id, object_description, behavior, context_key FROM learning_outcome WHERE owner_id=? AND id=?',
                (owner, outcome_id),
            ).fetchone()
            if outcome is None:
                raise DomainError('not_found', 404)
            states = {(s['criterion_id'], s['dimension_id']): s for s in
                      StateDerivationService(self.learning).states(identity, connection=connection)
                      if s['outcome_id'] == outcome_id}
            standards = []
            for row in connection.execute('''SELECT c.id, c.version, c.review_status, c.recipe_json,
                    p.title, a.reason AS availability FROM learning_criterion_version c
                    JOIN learning_standard_package p ON p.owner_id=c.owner_id AND p.id=c.package_id
                    LEFT JOIN learning_criterion_availability a ON a.owner_id=c.owner_id AND a.criterion_id=c.id
                    WHERE c.owner_id=? AND c.outcome_id=? ORDER BY c.created_at, c.version''', (owner, outcome_id)):
                standard = dict(row)
                recipe = json.loads(standard.pop('recipe_json'))
                standard['dimensions'] = [dict(id=d['id'], label=d['label'],
                    state=states.get((standard['id'], d['id']))) for d in recipe['dimensions']]
                standards.append(standard)
            return {
                'outcome': dict(outcome), 'standards': standards,
                'records': [r for r in self.records.list_owned(owner) if r['outcome_id'] == outcome_id],
                'attempts': self._attempts(connection, owner, outcome_id),
                'artifacts': self._artifacts(connection, owner, outcome_id),
                'claims': self._claims(connection, owner, outcome_id),
                'follow_ups': self._follow_ups(connection, owner, outcome_id),
                'completions': [dict(row) for row in connection.execute('''SELECT c.id,c.delegation_id,c.verification_kind,c.created_at,c.purged_at
                    FROM learning_completion c JOIN learning_delegation d ON d.owner_id=c.owner_id AND d.id=c.delegation_id
                    WHERE c.owner_id=? AND d.outcome_id=? ORDER BY c.created_at DESC''', (owner, outcome_id))],
            }

    @staticmethod
    def _attempts(connection, owner, outcome_id):
        rows = connection.execute('''SELECT v.id AS verification_id, s.id AS submission_id,
            e.id AS evaluation_id, v.delegation_id, a.title AS action_title, v.mode,
            COALESCE(s.created_at,v.created_at) AS created_at, v.contract_snapshot_json,
            e.status AS evaluation_status, e.result_json, s.artifact_id, s.content_json,
            s.purged_at AS submission_purged, v.purged_at AS verification_purged,
            raw.content, raw.purged_at AS raw_purged, ar.visibility
            FROM learning_verification v
            JOIN learning_delegation d ON d.owner_id=v.owner_id AND d.id=v.delegation_id
            JOIN learning_action a ON a.owner_id=d.owner_id AND a.id=d.action_id
            LEFT JOIN learning_verification_submission s ON s.owner_id=v.owner_id AND s.verification_id=v.id
            LEFT JOIN learning_verification_evaluation e ON e.owner_id=s.owner_id AND e.submission_id=s.id
            LEFT JOIN learning_artifact ar ON ar.owner_id=s.owner_id AND ar.id=s.artifact_id
            LEFT JOIN learning_raw_artifact raw ON raw.owner_id=s.owner_id AND raw.artifact_id=s.artifact_id AND raw.content_version=1
            WHERE v.owner_id=? AND d.outcome_id=? ORDER BY v.rowid DESC, s.rowid DESC, e.rowid DESC''', (owner, outcome_id))
        attempts = []
        for row in rows:
            item = dict(row)
            contract = json.loads(item.pop('contract_snapshot_json') or '{}')
            item.update(criterion_id=contract.get('criterion_id'), contract_version=contract.get('version'))
            criterion = connection.execute('SELECT version FROM learning_criterion_version WHERE owner_id=? AND id=?',
                                           (owner, item['criterion_id'])).fetchone()
            item['standard_version'] = criterion[0] if criterion else None
            purged = [item.pop(key) for key in ('submission_purged', 'verification_purged', 'raw_purged')]
            visibility = item.pop('visibility')
            body = item.pop('content') if item['artifact_id'] else item['content_json']
            item.pop('content', None)
            item.pop('content_json')
            reason = ('purged' if any(purged) or visibility == 'purged' else
                      'not_submitted' if item['submission_id'] is None else
                      'hidden' if not body or (item['artifact_id'] and visibility != 'visible') else None)
            item.update(available=reason is None, unavailable_reason=reason)
            content = json.loads(body) if reason is None else {}
            result = json.loads(item.pop('result_json') or 'null') if reason is None else None
            item.pop('result_json', None)
            item['condition'] = content.get('evidence_condition')
            item['condition_basis'] = 'submission_record' if item['condition'] else None
            item['feedback'] = result.get('feedback') if result else None
            item['passed'] = result.get('passed') if result else None
            attempts.append(item)
        return attempts

    @staticmethod
    def _artifacts(connection, owner, outcome_id):
        rows = connection.execute('''SELECT raw.artifact_id, raw.content_version, raw.created_at,
            s.delegation_id, a.title AS action_title, c.criterion_id, ar.visibility, ar.evidence_status,
            (ar.visibility='visible' AND raw.purged_at IS NULL AND raw.content IS NOT NULL) AS available
            FROM learning_raw_artifact raw
            JOIN learning_artifact ar ON ar.owner_id=raw.owner_id AND ar.id=raw.artifact_id
            JOIN learning_session s ON s.owner_id=raw.owner_id AND s.id=raw.session_id
            JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
            JOIN learning_action a ON a.owner_id=d.owner_id AND a.id=d.action_id
            JOIN learning_contract_version c ON c.owner_id=s.owner_id AND c.delegation_id=s.delegation_id AND c.version=s.contract_version
            WHERE raw.owner_id=? AND d.outcome_id=? AND NOT EXISTS (
                SELECT 1 FROM learning_verification_submission sub WHERE sub.owner_id=raw.owner_id AND sub.artifact_id=raw.artifact_id)
            ORDER BY raw.created_at DESC, raw.content_version DESC''', (owner, outcome_id))
        return [{**dict(row), 'available': bool(row['available'])} for row in rows]

    @staticmethod
    def _claims(connection, owner, outcome_id):
        rows = connection.execute('''SELECT c.id, c.criterion_id, c.dimension_id, c.status, c.stance,
            c.source, c.verification_method, c.evidence_condition, c.provenance_json, c.statement,
            c.created_at, c.artifact_id, c.content_version,
            (ar.visibility='visible' AND raw.purged_at IS NULL AND raw.content IS NOT NULL) AS available
            FROM learning_evidence_claim c
            JOIN learning_criterion_version criterion ON criterion.owner_id=c.owner_id AND criterion.id=c.criterion_id
            LEFT JOIN learning_artifact ar ON ar.owner_id=c.owner_id AND ar.id=c.artifact_id
            LEFT JOIN learning_raw_artifact raw ON raw.owner_id=c.owner_id AND raw.artifact_id=c.artifact_id AND raw.content_version=c.content_version
            WHERE c.owner_id=? AND criterion.outcome_id=? ORDER BY c.created_at DESC, c.id''', (owner, outcome_id))
        claims = []
        for row in rows:
            claim = dict(row)
            claim['available'] = bool(claim['available'])
            claim['condition_basis'] = json.loads(claim.pop('provenance_json') or '{}').get('condition_basis')
            if not claim['available']:
                claim['statement'] = None
            claim['reviews'] = [dict(review) for review in connection.execute(
                'SELECT id, action, reason, created_at FROM learning_review_action WHERE owner_id=? AND claim_id=? ORDER BY created_at, rowid', (owner, claim['id']))]
            if not claim['available']:
                for review in claim['reviews']:
                    review['reason'] = None
            claims.append(claim)
        return claims

    @staticmethod
    def _follow_ups(connection, owner, outcome_id):
        return [dict(row) for row in connection.execute('''SELECT f.id, f.claim_id, f.kind, f.status, f.due_at, f.created_at,
            CASE WHEN ar.visibility='visible' AND raw.purged_at IS NULL AND raw.content IS NOT NULL THEN f.note ELSE NULL END AS note
            FROM learning_evidence_follow_up f
            JOIN learning_evidence_claim c ON c.owner_id=f.owner_id AND c.id=f.claim_id
            JOIN learning_criterion_version criterion ON criterion.owner_id=c.owner_id AND criterion.id=c.criterion_id
            LEFT JOIN learning_artifact ar ON ar.owner_id=c.owner_id AND ar.id=c.artifact_id
            LEFT JOIN learning_raw_artifact raw ON raw.owner_id=c.owner_id AND raw.artifact_id=c.artifact_id AND raw.content_version=c.content_version
            WHERE f.owner_id=? AND criterion.outcome_id=? ORDER BY f.created_at DESC''', (owner, outcome_id))]
