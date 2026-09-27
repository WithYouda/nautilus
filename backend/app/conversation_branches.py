"""Independent chat branches retain explicit lineage without duplicating materials."""
from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid4, uuid5

from .conversations import ConversationConflict, ConversationError, _now
from .source_runtime import material_guard


def _insert(connection, table, row):
    # Table and column names come solely from the existing database schema.
    columns = list(row)
    connection.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                       tuple(row[key] for key in columns))


def branch_metadata(service, owner, conversation_id):
    row = service.database.fetchone('''SELECT r.config_snapshot_json FROM ai_run r
        JOIN message m ON m.id=r.response_message_id
        WHERE r.identity_id=? AND r.conversation_id=?
          AND json_type(r.config_snapshot_json,'$.branch_origin')='object'
        ORDER BY m.sequence DESC LIMIT 1''', (owner, conversation_id))
    if row is None:
        return {}
    snapshot = json.loads(row[0])
    origin = snapshot['branch_origin']
    scope = snapshot.get('source_scope') or {}
    return {'branch_origin': {key: origin[key] for key in ('conversation_id', 'message_id')},
            'branch_source_scope': ({key: scope[key] for key in ('mode', 'version_ids', 'conflict_policy') if key in scope}
                                    if scope.get('mode') and not scope.get('purged') else
                                    {'mode': 'unspecified', 'version_ids': []})}


@material_guard
def create_branch(self, identity_id, conversation_id, message_id, request_key):
    branch_id = str(uuid5(NAMESPACE_URL, f'nautilus:branch:{identity_id}:{conversation_id}:{request_key}'))
    now = _now()
    with self.database.transaction() as c:
        source = self.owned_conversation(identity_id, conversation_id)
        existing = c.execute('SELECT id,deleted_at FROM conversation WHERE id=? AND identity_id=?',
                             (branch_id, identity_id)).fetchone()
        if existing:
            metadata = branch_metadata(self, identity_id, branch_id)
            if existing['deleted_at'] or metadata.get('branch_origin', {}).get('message_id') != message_id:
                raise ConversationConflict('分支请求已用于其他回答或对话已删除')
            return self.conversation_detail(identity_id, branch_id)
        messages = self.list_messages(identity_id, conversation_id)
        path = self.message_path(messages, message_id)
        if not path or path[-1]['role'] != 'assistant' or path[-1]['status'] == 'streaming':
            raise ConversationConflict('请选择已经结束的回答创建分支')
        if any(item['status'] == 'streaming' or (item.get('source_scope') or {}).get('purged') for item in path):
            raise ConversationConflict('路径中有正在生成或已清除的内容，无法创建分支')
        ids = {item['id']: str(uuid4()) for item in path}
        conversation = dict(source)
        from .branch_maps import compact_title
        question = next((item['content'] for item in reversed(path) if item['role'] == 'user'), source['title'])
        conversation.update(id=branch_id, title=compact_title(question), title_source='fallback', title_generation_status='idle',
                            title_revision=0, title_generated_at=None, created_at=now, updated_at=now,
                            last_message_at=now, status='active')
        _insert(c, 'conversation', conversation)
        for link in c.execute('SELECT * FROM conversation_link WHERE conversation_id=?', (conversation_id,)).fetchall():
            _insert(c, 'conversation_link', {**dict(link), 'id': str(uuid4()), 'conversation_id': branch_id})
        config = c.execute('SELECT * FROM conversation_config WHERE conversation_id=?', (conversation_id,)).fetchone()
        if config:
            _insert(c, 'conversation_config', {**dict(config), 'conversation_id': branch_id, 'updated_at': now})
        for sequence, item in enumerate(path):
            row = dict(c.execute('SELECT * FROM message WHERE id=?', (item['id'],)).fetchone())
            row.update(id=ids[item['id']], conversation_id=branch_id, sequence=sequence,
                       ai_run_id=None, client_message_id=None)
            _insert(c, 'message', row)
        for item in path:
            if item['role'] != 'assistant':
                continue
            original = c.execute('SELECT * FROM ai_run WHERE response_message_id=? AND identity_id=?',
                                 (item['id'], identity_id)).fetchone()
            if original is None or original['status'] in ('queued', 'running'):
                raise ConversationConflict('回答记录尚未完整，无法创建分支')
            run = dict(original)
            snapshot = json.loads(run['config_snapshot_json'] or '{}')
            question = item['parent_message_id']
            parent = next(m['parent_message_id'] for m in path if m['id'] == question)
            snapshot['reply'] = dict(schema_version=1, question_id=ids[question], question_version_id=ids[question],
                                     parent_answer_id=ids.get(parent))
            snapshot['source_history_message_ids'] = list(dict.fromkeys([
                *snapshot.get('source_history_message_ids', []), question, item['id']]))
            snapshot['branch_origin'] = dict(conversation_id=conversation_id, message_id=message_id,
                                             source_message_id=item['id'])
            snapshot['branch_material_version_ids'] = (snapshot.get('source_scope') or {}).get('version_ids', [])
            # A location summary belongs to its original conversation, not the new branch.
            snapshot.pop('learning_position', None)
            context_id = run['context_snapshot_id']
            if context_id:
                context = dict(c.execute('SELECT * FROM context_snapshot WHERE id=?', (context_id,)).fetchone())
                context.update(id=str(uuid4()), conversation_id=branch_id)
                _insert(c, 'context_snapshot', context)
                context_id = context['id']
            run.update(id=str(uuid4()), conversation_id=branch_id, context_snapshot_id=context_id,
                       request_message_id=ids[question], response_message_id=ids[item['id']],
                       config_snapshot_json=json.dumps(snapshot, ensure_ascii=False))
            _insert(c, 'ai_run', run)
            c.execute('UPDATE message SET ai_run_id=? WHERE id=?', (run['id'], ids[item['id']]))
    return self.conversation_detail(identity_id, branch_id)
