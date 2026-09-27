"""Fork a selected discussion path while retaining its original question scope."""
import json
from uuid import NAMESPACE_URL, uuid4, uuid5

from .core.learning import utc_timestamp
from .learning_domain import DomainError
from .source_runtime import material_guard


def branch_metadata(connection, discussion_id):
    row = connection.execute('''SELECT provider_snapshot_json FROM learning_discussion_turn
        WHERE discussion_id=? AND json_type(provider_snapshot_json,'$.branch_origin')='object'
        ORDER BY rowid DESC LIMIT 1''', (discussion_id,)).fetchone()
    if row is None:
        return {}
    snapshot = json.loads(row[0])
    origin = snapshot['branch_origin']
    scope = snapshot.get('source_scope') or {}
    return {'branch_origin': {key: origin[key] for key in ('discussion_id', 'turn_id')},
            'branch_source_scope': ({key: scope[key] for key in ('mode', 'version_ids', 'conflict_policy') if key in scope}
                                    if scope.get('mode') and not scope.get('purged') else
                                    {'mode': 'unspecified', 'version_ids': []})}


@material_guard
def create_branch(self, identity, discussion_id, turn_id, request_key):
    owner = self.learning.principal(identity).owner_id
    bid = str(uuid5(NAMESPACE_URL, f'nautilus:discussion-branch:{owner}:{discussion_id}:{request_key}'))
    with self.db.transaction(immediate=True) as c:
        source = self._owned(owner, discussion_id)
        if source['purged_at']:
            raise DomainError('artifact_not_eligible', 409)
        self._source(identity, source, c)
        existing = c.execute('SELECT id,purged_at FROM learning_question_discussion WHERE id=? AND owner_id=?', (bid, owner)).fetchone()
        if existing:
            origin = branch_metadata(c, bid).get('branch_origin', {})
            if existing['purged_at'] or origin.get('turn_id') != turn_id:
                raise DomainError('idempotency_conflict', 409)
            return self._get(identity, owner, bid, c)
        turns = self._get(identity, owner, discussion_id, c)['turns']
        by_id = {turn['id']: turn for turn in turns}
        path, seen = [], set()
        cursor = turn_id
        while cursor:
            if cursor not in by_id or cursor in seen:
                raise DomainError('not_found', 404)
            turn = by_id[cursor]
            if turn['status'] in ('running', 'purged') or (turn.get('source_scope') or {}).get('purged'):
                raise DomainError('artifact_not_eligible', 409)
            seen.add(cursor)
            path.append(turn)
            cursor = turn['parent_turn_id']
        path.reverse()
        if not path:
            raise DomainError('not_found', 404)
        ids = {turn['id']: str(uuid4()) for turn in path}
        c.execute('''INSERT INTO learning_question_discussion
            (id,owner_id,verification_id,submission_id,question_id,evaluation_id,request_key,created_at,purged_at)
            VALUES (?,?,?,?,?,?,?,?,NULL)''', (bid, owner, source['verification_id'], source['submission_id'],
            source['question_id'], source['evaluation_id'], 'branch:' + bid, utc_timestamp()))
        from .branch_maps import compact_title
        c.execute('UPDATE learning_question_discussion SET branch_parent_id=?,branch_turn_id=?,title=? WHERE id=?',
                  (discussion_id, turn_id, compact_title(path[-1]['user_content']), bid))
        c.execute('INSERT INTO learning_discussion_dependency VALUES (?,?)', (bid, discussion_id))
        for turn in path:
            row = c.execute('SELECT * FROM learning_discussion_turn WHERE id=?', (turn['id'],)).fetchone()
            snapshot = json.loads(row['provider_snapshot_json'])
            history = (snapshot.get('reply') or {}).get('history_turn_ids', [])
            snapshot['reply'] = dict(schema_version=1, question_id=ids[turn['id']],
                question_version_id=ids[turn['id']], parent_turn_id=ids.get(turn['parent_turn_id']),
                history_turn_ids=list(dict.fromkeys([*history, turn['id']])))
            snapshot['branch_origin'] = dict(discussion_id=discussion_id, turn_id=turn_id, source_turn_id=turn['id'])
            snapshot['branch_material_version_ids'] = (snapshot.get('source_scope') or {}).get('version_ids', [])
            c.execute('''INSERT INTO learning_discussion_turn
                (id,discussion_id,request_key,user_content,assistant_content,status,reason,sources_json,
                 provider_snapshot_json,created_at,finished_at,reasoning_content) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (ids[turn['id']],bid,'inherited:'+ids[turn['id']],row['user_content'],row['assistant_content'],
                 row['status'],row['reason'],row['sources_json'],json.dumps(snapshot,ensure_ascii=False),
                 row['created_at'],row['finished_at'],row['reasoning_content']))
            # Only references actually present in the selected path are inherited.
            # The original question/submission link already covers its own erasure.
            for ref in json.loads(row['sources_json']):
                if ref.get('kind') == 'discussion':
                    c.execute('INSERT OR IGNORE INTO learning_discussion_dependency VALUES (?,?)',
                              (bid, ref['discussion_id']))
        return self._get(identity, owner, bid, c)
