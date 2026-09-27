"""Owner-scoped conversation families; private labels are resolved from live content."""
import json

from .conversations import _clip
from .learning_domain import DomainError


def compact_title(text):
    return _clip(' '.join((text or '').split())) or '新的讨论'


def _origin(c, cid):
    row = c.execute('''SELECT config_snapshot_json FROM ai_run WHERE conversation_id=?
        AND json_type(config_snapshot_json,'$.branch_origin')='object' ORDER BY rowid DESC LIMIT 1''', (cid,)).fetchone()
    return json.loads(row[0])['branch_origin'] if row else {}


def conversation_title(c, row):
    # Old factory names were stored as manual with revision zero. A real rename increments it.
    if row['title'] == '分支对话' and row['title_source'] == 'manual' and row['title_revision'] == 0 and _origin(c, row['id']):
        question = c.execute("SELECT content FROM message WHERE conversation_id=? AND role='user' ORDER BY sequence DESC LIMIT 1", (row['id'],)).fetchone()
        return compact_title(question[0] if question else None)
    return row['title']


def discussion_title(c, row):
    if row['purged_at']:
        return '内容已清除'
    if row['title']:
        return row['title']
    turn = c.execute("SELECT user_content FROM learning_discussion_turn WHERE discussion_id=? AND user_content IS NOT NULL ORDER BY rowid LIMIT 1", (row['id'],)).fetchone()
    # A live question remains available after an individual material-dependent turn is erased.
    if turn:
        return compact_title(turn[0])
    verification = c.execute('SELECT challenge_json FROM learning_verification WHERE id=? AND owner_id=? AND purged_at IS NULL', (row['verification_id'], row['owner_id'])).fetchone()
    questions = json.loads(verification[0]).get('questions', []) if verification else []
    question = next((q['prompt'] for q in questions if q['id'] == row['question_id']), '题目讨论')
    return compact_title(question)


def name_new_conversation_turn(c, run_id):
    run = c.execute('SELECT * FROM ai_run WHERE id=?', (run_id,)).fetchone()
    snapshot = json.loads(run['config_snapshot_json'] or '{}')
    row = c.execute('SELECT * FROM conversation WHERE id=?', (run['conversation_id'],)).fetchone()
    legacy = row['title'] == '分支对话' and row['title_source'] == 'manual'
    if row['title_revision'] or (row['title_source'] != 'fallback' and not legacy) or not _origin(c, row['id']):
        return
    if snapshot.get('branch_origin') or snapshot.get('help_request'):
        return
    question = c.execute('SELECT content FROM message WHERE id=?', (run['request_message_id'],)).fetchone()
    if question and question[0].strip():
        c.execute("UPDATE conversation SET title=?,title_source='fallback',title_revision=1 WHERE id=?", (compact_title(question[0]), row['id']))


def name_new_discussion_turn(c, did, tid):
    turn = c.execute('SELECT user_content,provider_snapshot_json FROM learning_discussion_turn WHERE id=?', (tid,)).fetchone()
    snapshot = json.loads(turn['provider_snapshot_json'])
    if not snapshot.get('branch_origin') and not snapshot.get('help_request'):
        c.execute("UPDATE learning_question_discussion SET title=?,title_source='question' WHERE id=? AND title_source='source' AND purged_at IS NULL", (compact_title(turn['user_content']), did))


def _family(current_id, nodes):
    by_id = {node['id']: node for node in nodes}
    related = {current_id}
    while True:
        added = {node['id'] for node in nodes if node['parent_id'] in related}
        added.update(by_id[n]['parent_id'] for n in related if n in by_id and by_id[n]['parent_id'] in by_id)
        if added <= related:
            break
        related.update(added)
    return {'current_id': current_id, 'nodes': [node for node in nodes if node['id'] in related]}


def conversation_map(service, owner, cid):
    service.owned_conversation(owner, cid)
    with service.database.transaction() as c:
        rows = [dict(row) for row in c.execute('SELECT * FROM conversation WHERE identity_id=? ORDER BY created_at,rowid', (owner,))]
        by_id = {row['id']: row for row in rows}
        nodes = []
        for row in rows:
            origin = _origin(c, row['id'])
            parent = by_id.get(origin.get('conversation_id'))
            available = not row['deleted_at']
            excerpt = None
            if available and parent and not parent['deleted_at']:
                question = c.execute('''SELECT m.content FROM ai_run r JOIN message m ON m.id=r.request_message_id
                    WHERE r.conversation_id=? AND r.response_message_id=?''', (parent['id'], origin.get('message_id'))).fetchone()
                excerpt = compact_title(question[0]) if question and question[0] else None
            nodes.append(dict(id=row['id'], title=conversation_title(c, row) if available else '对话已删除',
                parent_id=parent['id'] if parent else None, source_id=origin.get('message_id') if excerpt else None,
                source_excerpt=excerpt, available=available, created_at=row['created_at']))
        return _family(cid, nodes)


def discussion_map(service, identity, did):
    owner = service.learning.principal(identity).owner_id
    service._owned(owner, did)
    with service.db.transaction() as c:
        rows = [dict(row) for row in c.execute('SELECT * FROM learning_question_discussion WHERE owner_id=? ORDER BY created_at,rowid', (owner,))]
        by_id = {row['id']: row for row in rows}
        nodes = []
        for row in rows:
            parent = by_id.get(row['branch_parent_id'])
            excerpt = None
            if not row['purged_at'] and parent and not parent['purged_at']:
                turn = c.execute("SELECT user_content FROM learning_discussion_turn WHERE discussion_id=? AND id=? AND status<>'purged'", (parent['id'], row['branch_turn_id'])).fetchone()
                excerpt = compact_title(turn[0]) if turn and turn[0] else None
            nodes.append(dict(id=row['id'], title=discussion_title(c, row), parent_id=parent['id'] if parent else None,
                source_id=row['branch_turn_id'] if excerpt else None, source_excerpt=excerpt,
                available=not bool(row['purged_at']), created_at=row['created_at']))
        return _family(did, nodes)


def rename_discussion(service, identity, did, title):
    owner = service.learning.principal(identity).owner_id
    if not title.strip():
        raise DomainError('invalid_title', 422)
    with service.db.transaction(immediate=True) as c:
        row = service._owned(owner, did)
        if row['purged_at']:
            raise DomainError('artifact_not_eligible', 409)
        c.execute("UPDATE learning_question_discussion SET title=?,title_source='manual' WHERE id=?", (compact_title(title), did))
    return service.get(identity, did)
