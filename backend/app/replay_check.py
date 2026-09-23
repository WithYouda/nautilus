"""Compare domain projections at a transaction-protected event cutoff."""
import hashlib
import json
from uuid import uuid4
from .learning_domain import DomainError

EVIDENCE_TABLES = ('learning_evidence_claim', 'learning_review_action', 'learning_batch_review_action',
    'learning_claim_replacement', 'learning_evidence_follow_up', 'learning_derived_state',
    'learning_derived_state_history', 'learning_revisit_item')

def projection_snapshot(connection, owner_id, tables):
    values, counts = {}, {}
    for table in tables:
        rows = [dict(row) for row in connection.execute(f'SELECT * FROM {table} WHERE owner_id=?', (owner_id,))]
        for row in rows:
            if table in ('learning_derived_state_history', 'learning_claim_replacement', 'learning_revisit_item'):
                row.pop('id', None)
            if table == 'learning_revisit_item':
                for key in ('created_at', 'updated_at', 'due_at'):
                    row.pop(key, None)
            for key, value in row.items():
                if key.endswith('_json') and value is not None:
                    row[key] = json.loads(value)
        values[table] = sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))
        counts[table] = len(rows)
    digest = hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    return digest, counts

def record_comparison(connection, owner_id, kind, cutoff, before, after):
    if connection.execute('PRAGMA foreign_key_check').fetchone():
        raise DomainError('projection_rebuild_incomplete')
    if connection.execute("SELECT 1 FROM learning_session WHERE owner_id=? AND status='running' GROUP BY owner_id HAVING COUNT(*)>1", (owner_id,)).fetchone():
        raise DomainError('projection_rebuild_incomplete')
    matched = before == after
    connection.execute("INSERT INTO learning_replay_check VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
        (str(uuid4()), owner_id, kind, cutoff, before[0], after[0], json.dumps({'before': before[1], 'after': after[1]}, sort_keys=True), int(matched)))
    return {'cutoff': cutoff, 'before_digest': before[0], 'after_digest': after[0], 'matched': matched, 'constraints_ok': True}
