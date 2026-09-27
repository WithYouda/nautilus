"""Current browser-independent path and run selections; no message or material text."""
from __future__ import annotations

import json

from .core.learning import utc_timestamp
from .learning_domain import DomainError
from .conversations import ConversationError
from .search_adapters import SearchError


DEFAULT_SCOPE = {'mode': 'unspecified', 'version_ids': []}


class CurrentConversationState:
    def __init__(self, materials, conversations, discussions, search):
        self.materials = materials
        self.conversations = conversations
        self.discussions = discussions
        self.search = search
        self.db = materials.db
        # Send operations already hold this lock. Never await while it is held.
        self.lock = materials.lock

    def _owner(self, identity, kind, scope_id):
        return self.materials.owned_scope(identity, kind, scope_id)

    def _row(self, owner, kind, scope_id, connection=None):
        db = connection or self.db.connection
        return db.execute('''SELECT * FROM learning_conversation_current_state
            WHERE owner_id=? AND kind=? AND scope_id=?''', (owner, kind, scope_id)).fetchone()

    @staticmethod
    def _decode(row):
        if row is None:
            return dict(initialized=False, revision=0, leaf_id=None, paths={},
                        source_scope=dict(DEFAULT_SCOPE), search_override=None, issues=[])
        return dict(initialized=True, revision=row['revision'], leaf_id=row['leaf_id'],
                    paths=json.loads(row['paths_json']), source_scope=json.loads(row['source_scope_json']),
                    search_override=json.loads(row['search_override_json']) if row['search_override_json'] else None,
                    issues=[])

    def _nodes(self, identity, kind, scope_id, connection=None):
        if kind == 'conversation':
            rows = self.conversations.list_messages(identity['id'], scope_id)
            return {r['id']: r for r in rows if r['role'] in ('user', 'assistant') and
                    not (r.get('source_scope') or {}).get('purged')}
        if connection is not None:
            rows = []
            previous = None
            for row in connection.execute('''SELECT id,status,provider_snapshot_json FROM learning_discussion_turn
                    WHERE discussion_id=? ORDER BY rowid''', (scope_id,)):
                reply = json.loads(row['provider_snapshot_json'] or '{}').get('reply', {})
                rows.append({'id': row['id'], 'status': row['status'],
                             'question_id': reply.get('question_id', row['id']),
                             'parent_turn_id': reply.get('parent_turn_id', previous)})
                previous = row['id']
        else:
            rows = self.discussions.get(identity, scope_id)['turns']
        return {r['id']: r for r in rows if r['status'] != 'purged'}

    def _validate_path(self, identity, kind, scope_id, leaf, paths):
        if not isinstance(paths, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in paths.items()
        ):
            raise DomainError('conversation_state_path_invalid', 422)
        nodes = self._nodes(identity, kind, scope_id)
        if leaf is not None and (not isinstance(leaf, str) or leaf not in nodes):
            raise DomainError('conversation_state_path_invalid', 422)
        for ancestor, descendant in paths.items():
            if ancestor.startswith('group:'):
                if kind != 'discussion' or descendant not in nodes or nodes[descendant]['question_id'] != ancestor[6:]:
                    raise DomainError('conversation_state_path_invalid', 422)
                continue
            if ancestor not in nodes or descendant not in nodes:
                raise DomainError('conversation_state_path_invalid', 422)
            seen = set()
            current = descendant
            while current and current != ancestor and current not in seen:
                seen.add(current)
                parent = nodes[current].get('parent_message_id' if kind == 'conversation' else 'parent_turn_id')
                current = parent
            if current != ancestor:
                raise DomainError('conversation_state_path_invalid', 422)

    def _validate_scope(self, identity, kind, scope_id, scope):
        if not isinstance(scope, dict) or set(scope) - {'mode', 'version_ids', 'conflict_policy'}:
            raise DomainError('invalid_material_selection', 422)
        self.materials.freeze(identity, kind, scope_id, scope)

    def _validate_search(self, owner, selection, kind=None, scope_id=None):
        if selection is None:
            return
        if not isinstance(selection, dict) or set(selection) - {'mode', 'service_id', 'parameters'}:
            raise DomainError('conversation_state_search_invalid', 422)
        mode = selection.get('mode')
        if mode not in {'off', 'external', 'native'}:
            raise DomainError('conversation_state_search_invalid', 422)
        if mode in {'off', 'native'} and (selection.get('service_id') is not None or 'parameters' in selection):
            raise DomainError('conversation_state_search_invalid', 422)
        if selection.get('mode') == 'external' and not selection.get('service_id'):
            raise DomainError('conversation_state_search_invalid', 422)
        try:
            protocol = 'openai_responses'
            if selection.get('mode') == 'native' and kind == 'conversation':
                protocol = self.conversations.runtime_for_conversation(owner, scope_id)[1].provider_kind
            elif selection.get('mode') == 'native' and kind == 'discussion':
                discussion = self.discussions._owned(owner, scope_id)
                protocol = self.discussions.verification._runtime(owner, discussion['session_id'])[1].provider_kind
            self.search.prepare(owner, selection, protocol)
        except (SearchError, ConversationError, DomainError) as error:
            raise DomainError('conversation_state_search_invalid', 422) from error

    def get(self, identity, kind, scope_id):
        with self.lock:
            owner = self._owner(identity, kind, scope_id)
            state = self._decode(self._row(owner, kind, scope_id))
            if not state['initialized']:
                nodes = self._nodes(identity, kind, scope_id)
                state['leaf_id'] = next(reversed(nodes), None)
                return state
            issues = []
            if state['leaf_id'] is None and self._nodes(identity, kind, scope_id):
                issues.append('path_unavailable')
            try:
                self._validate_path(identity, kind, scope_id, state['leaf_id'], state['paths'])
            except DomainError:
                issues.append('path_unavailable')
            try:
                self._validate_scope(identity, kind, scope_id, state['source_scope'])
            except DomainError:
                issues.append('material_unavailable')
            try:
                self._validate_search(owner, state['search_override'], kind, scope_id)
            except DomainError:
                issues.append('search_unavailable')
            state['issues'] = issues
            return state

    def put(self, identity, kind, scope_id, payload):
        with self.lock:
            owner = self._owner(identity, kind, scope_id)
            previous = self._decode(self._row(owner, kind, scope_id))
            if payload.expected_revision != previous['revision']:
                raise DomainError('conversation_state_conflict', 409)
            editable = payload.model_dump(exclude={'expected_revision'})
            # Validate outside the SQLite write transaction: material ownership
            # lookup may itself initialize identity-scoped standard records.
            for field, validator in (
                ('path', lambda: self._validate_path(identity, kind, scope_id, editable['leaf_id'], editable['paths'])),
                ('material', lambda: self._validate_scope(identity, kind, scope_id, editable['source_scope'])),
                ('search', lambda: self._validate_search(owner, editable['search_override'], kind, scope_id)),
            ):
                keys = {'path': ('leaf_id', 'paths'), 'material': ('source_scope',), 'search': ('search_override',)}[field]
                if any(editable[key] != previous[key] for key in keys) or not previous['initialized']:
                    validator()
            with self.db.transaction(immediate=True) as connection:
                previous = self._decode(self._row(owner, kind, scope_id, connection))
                if payload.expected_revision != previous['revision']:
                    raise DomainError('conversation_state_conflict', 409)
                revision = previous['revision'] + 1
                connection.execute('''INSERT INTO learning_conversation_current_state
                    (owner_id,kind,scope_id,revision,leaf_id,paths_json,source_scope_json,search_override_json,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(owner_id,kind,scope_id) DO UPDATE SET
                    revision=excluded.revision,leaf_id=excluded.leaf_id,paths_json=excluded.paths_json,
                    source_scope_json=excluded.source_scope_json,search_override_json=excluded.search_override_json,
                    updated_at=excluded.updated_at''',
                    (owner, kind, scope_id, revision, editable['leaf_id'], json.dumps(editable['paths']),
                     json.dumps(editable['source_scope']), json.dumps(editable['search_override']) if editable['search_override'] is not None else None,
                     utc_timestamp()))
            return self.get(identity, kind, scope_id)

    def check_send(self, owner, kind, scope_id, revision, source_scope=None, search=None,
                   parent_id=None, branch_operation=False):
        row = self._row(owner, kind, scope_id)
        if row is not None and (revision is None or revision != row['revision']):
            raise DomainError('conversation_state_conflict', 409)
        if row is None and revision not in (None, 0):
            raise DomainError('conversation_state_conflict', 409)
        if row is not None:
            state = self._decode(row)
            identity = {'id': owner}
            if state['leaf_id'] is None and self._nodes(identity, kind, scope_id):
                raise DomainError('conversation_state_invalid', 409)
            try:
                self._validate_path(identity, kind, scope_id, state['leaf_id'], state['paths'])
            except DomainError as error:
                raise DomainError('conversation_state_invalid', 409) from error
            if not branch_operation and parent_id != state['leaf_id']:
                raise DomainError('conversation_state_conflict', 409)
            if (source_scope or DEFAULT_SCOPE) != state['source_scope']:
                raise DomainError('conversation_state_conflict', 409)
            try:
                self._validate_scope(identity, kind, scope_id, state['source_scope'])
                self._validate_search(owner, state['search_override'], kind, scope_id)
            except DomainError as error:
                raise DomainError('conversation_state_invalid', 409) from error

    def advance(self, owner, kind, scope_id, leaf_id, connection=None):
        if connection is None:
            with self.db.transaction(immediate=True) as c:
                return self.advance(owner, kind, scope_id, leaf_id, c)
        row = self._row(owner, kind, scope_id, connection)
        if row is None:
            return
        nodes = self._nodes({'id': owner}, kind, scope_id, connection)
        if leaf_id not in nodes:
            raise DomainError('conversation_state_invalid', 409)
        paths = json.loads(row['paths_json'])
        current = leaf_id
        seen = set()
        while current and current in nodes and current not in seen:
            seen.add(current)
            paths[current] = leaf_id
            if kind == 'discussion':
                group = nodes[current].get('question_id')
                if group:
                    paths[f'group:{group}'] = current
            current = nodes[current].get('parent_message_id' if kind == 'conversation' else 'parent_turn_id')
        connection.execute('''UPDATE learning_conversation_current_state
            SET leaf_id=?,paths_json=?,revision=revision+1,updated_at=?
            WHERE owner_id=? AND kind=? AND scope_id=?''',
            (leaf_id, json.dumps(paths), utc_timestamp(), owner, kind, scope_id))

    def erase(self, owner, kind, scope_id):
        with self.lock, self.db.transaction(immediate=True) as connection:
            connection.execute('DELETE FROM learning_conversation_current_state WHERE owner_id=? AND kind=? AND scope_id=?',
                               (owner, kind, scope_id))
