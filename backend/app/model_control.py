"""Explicit model/timeout inheritance. Never grants data or tool permissions."""
from __future__ import annotations

import hashlib
import json

from .conversations import ConversationConflict, ConversationError
from .core.learning import utc_timestamp
from .learning_domain import DomainError
from .providers import ProviderConfig


def normalize_override(value):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - {'model', 'timeout_seconds'}:
        raise ConversationError('模型设置格式不正确')
    model = value.get('model')
    if model is not None:
        if (not isinstance(model, dict) or set(model) != {'provider_profile_id', 'provider_model_id'}
                or any(not isinstance(v, str) or not v.strip() or len(v) > 200 for v in model.values())):
            raise ConversationError('请选择提供方和它的模型')
        model = dict(model)
    timeout = value.get('timeout_seconds')
    if timeout is not None and (type(timeout) is not int or not 5 <= timeout <= 600):
        raise ConversationError('超时须为5到600秒的整数')
    return {'model': model, 'timeout_seconds': timeout}


def _tag(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]


def public_snapshot(snapshot):
    """Read only what was captured for this answer; no current-setting lookup."""
    saved = snapshot.get('model_control')
    if isinstance(saved, dict):
        return saved
    provider = snapshot.get('provider') if isinstance(snapshot.get('provider'), dict) else {}
    model = snapshot.get('model')
    if isinstance(model, dict):
        return dict(provider_profile_id=provider.get('id'), provider_display_name=None,
                    provider_model_id=model.get('id'), model_id=model.get('model_id'),
                    model_display_name=model.get('display_name'), provider_kind=provider.get('kind'),
                    provider_config_version=provider.get('config_version'),
                    timeout_seconds=(snapshot.get('effective') or {}).get('timeout_seconds'),
                    sources={'model': None, 'timeout': None})
    if isinstance(model, str) and model:
        return dict(provider_profile_id=snapshot.get('provider_profile_id'), provider_display_name=None,
                    provider_model_id=snapshot.get('provider_model_id'), model_id=model,
                    model_display_name=model, provider_kind=snapshot.get('provider_kind'),
                    provider_config_version=snapshot.get('provider_config_version'),
                    timeout_seconds=snapshot.get('timeout_seconds'), sources={'model': None, 'timeout': None})
    return None


class ModelControlService:
    def __init__(self, learning, chats):
        self.learning = learning
        self.db = learning.database
        self.chats = chats
        # Send/branch/material operations already take this reentrant lock.
        self.lock = chats.materials.lock

    def _parent_scope(self, owner, kind, scope_id):
        if kind == 'global':
            if scope_id != 'default':
                raise DomainError('not_found', 404)
            return None, None
        if kind == 'plan':
            if self.db.fetchone('SELECT 1 FROM learning_plan WHERE owner_id=? AND id=?', (owner, scope_id)) is None:
                raise DomainError('not_found', 404)
            return scope_id, None
        if kind == 'task':
            if self.db.fetchone('SELECT 1 FROM learning_action WHERE owner_id=? AND id=?', (owner, scope_id)) is None:
                raise DomainError('not_found', 404)
            action_id = scope_id
        elif kind == 'conversation':
            self.chats.owned_conversation(owner, scope_id)
            row = self.db.fetchone('''SELECT d.action_id FROM learning_room_conversation r
                JOIN learning_session s ON s.owner_id=r.owner_id AND s.id=r.session_id
                JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
                WHERE r.owner_id=? AND r.conversation_id=?''', (owner, scope_id))
            action_id = row['action_id'] if row else None
        elif kind == 'discussion':
            self.chats.materials._owned_scope(owner, kind, scope_id)
            row = self.db.fetchone('''SELECT v.action_id FROM learning_question_discussion q
                JOIN learning_verification v ON v.owner_id=q.owner_id AND v.id=q.verification_id
                WHERE q.owner_id=? AND q.id=?''', (owner, scope_id))
            action_id = row['action_id'] if row else None
        else:
            raise DomainError('not_found', 404)
        row = self.db.fetchone('SELECT plan_id FROM learning_action_link WHERE owner_id=? AND action_id=?',
                               (owner, action_id)) if action_id else None
        return row['plan_id'] if row else None, action_id

    def _global(self, owner):
        row = self.chats.database.fetchone('''SELECT * FROM provider_profile
            WHERE identity_id=? AND is_default=1 AND deleted_at IS NULL''', (owner,))
        profile = dict(row) if row else None
        override = normalize_override(None)
        override['timeout_seconds'] = profile['request_timeout_seconds'] if profile else 60
        if profile:
            override['model'] = {'provider_profile_id': profile['id'], 'provider_model_id': profile['default_model_id']}
        return {'kind': 'global', 'id': 'default', 'revision': _tag([
            profile['id'], profile['config_version'], profile['credential_version'], override
        ] if profile else None), 'override': override}

    def _layer(self, owner, kind, scope_id):
        row = self.db.fetchone('''SELECT * FROM learning_model_config
            WHERE owner_id=? AND scope_kind=? AND scope_id=?''', (owner, kind, scope_id))
        if row is not None:
            model = {'provider_profile_id': row['provider_profile_id'], 'provider_model_id': row['provider_model_id']} if row['provider_profile_id'] else None
            return {'kind': kind, 'id': scope_id, 'revision': str(row['revision']),
                    'override': {'model': model, 'timeout_seconds': row['timeout_seconds']}}
        if kind == 'conversation':
            legacy = self.chats.database.fetchone('SELECT * FROM conversation_config WHERE conversation_id=?', (scope_id,))
            if legacy:
                return {'kind': kind, 'id': scope_id, 'revision': 'legacy:' + str(legacy['config_version']),
                        'override': {'model': {'provider_profile_id': legacy['provider_profile_id'], 'provider_model_id': legacy['provider_model_id']},
                                     'timeout_seconds': legacy['timeout_override_seconds']}}
        return {'kind': kind, 'id': scope_id, 'revision': '0', 'override': normalize_override(None)}

    def _layers(self, owner, kind, scope_id):
        plan, task = self._parent_scope(owner, kind, scope_id)
        layers = [self._global(owner)]
        if plan:
            layers.append(self._layer(owner, 'plan', plan))
        if task:
            layers.append(self._layer(owner, 'task', task))
        if kind in {'conversation', 'discussion'}:
            layers.append(self._layer(owner, kind, scope_id))
        return layers

    def _selected(self, owner, model):
        if model is None:
            return None, None, ['尚未配置默认模型，请在设置中选择']
        profile_row = self.chats.database.fetchone('''SELECT * FROM provider_profile
            WHERE identity_id=? AND id=? AND deleted_at IS NULL''', (owner, model['provider_profile_id']))
        model_row = self.chats.database.fetchone('SELECT * FROM provider_model WHERE provider_profile_id=? AND id=?',
            (model['provider_profile_id'], model['provider_model_id'])) if profile_row else None
        if profile_row is None or model_row is None:
            return None, None, ['所选提供方或模型已不存在，请重新选择或恢复继承']
        profile, row = dict(profile_row), dict(model_row)
        issues = []
        if not profile['enabled'] or not row['enabled']:
            issues.append('所选提供方或模型已停用，请重新选择或恢复继承')
        if row.get('discovery_status') == 'unavailable':
            issues.append('所选模型已不可用，请重新选择或恢复继承')
        return profile, row, issues

    def _resolve(self, owner, kind, scope_id, run_override=None):
        layers = self._layers(owner, kind, scope_id)
        values = normalize_override(None)
        sources = {'model': None, 'timeout': None}
        for layer in layers:
            for field in values:
                if layer['override'][field] is not None:
                    values[field] = layer['override'][field]
                    sources['model' if field == 'model' else 'timeout'] = {'kind': layer['kind'], 'id': layer['id']}
        override = normalize_override(run_override)
        for field in values:
            if override[field] is not None:
                values[field] = override[field]
                sources['model' if field == 'model' else 'timeout'] = {'kind': 'run', 'id': scope_id}
        profile, model, issues = self._selected(owner, values['model'])
        # Check both the inheritance chain and the selected one-run model. A
        # changed endpoint/capability must invalidate an already shown preview.
        token = _tag([layers, override,
                      [profile.get(k) for k in ('id', 'enabled', 'config_version', 'credential_version')] if profile else None,
                      [model.get(k) for k in ('id', 'enabled', 'discovery_status', 'updated_at', 'overrides_json', 'capabilities_json')] if model else None])
        has_key = False
        if profile:
            try:
                has_key = self.chats.credentials.has(profile['credential_key'])
            except Exception:
                issues.append('无法读取所选提供方的凭据，请在设置中检查')
            if not has_key and not issues:
                issues.append('所选提供方尚未保存API密钥')
        capabilities = self.chats._decode_json(model['capabilities_json'], {}) if model else {}
        effective = dict(provider_profile_id=values['model']['provider_profile_id'] if values['model'] else None,
            provider_model_id=values['model']['provider_model_id'] if values['model'] else None,
            provider_display_name=profile['display_name'] if profile else None,
            model_id=model['model_id'] if model else None, model_display_name=model['display_name'] if model else None,
            provider_kind=self.chats._protocol(profile, model['model_id']) if profile and model else None,
            timeout_seconds=values['timeout_seconds'], provider_config_version=profile['config_version'] if profile else None,
            supports_image_input=capabilities.get('supports_image_input'), supports_reasoning=capabilities.get('supports_reasoning'),
            has_api_key=has_key, available=not issues)
        view = dict(scope_kind=kind, scope_id=scope_id, revision=layers[-1]['revision'], token=token,
                    override=layers[-1]['override'], effective=effective, sources=sources, layers=layers, issues=issues)
        return view, profile, model

    def get(self, owner, kind, scope_id, run_override=None):
        with self.lock, self.chats._provider_lock:
            return self._resolve(owner, kind, scope_id, run_override)[0]

    def save(self, owner, kind, scope_id, override, expected_revision):
        value = normalize_override(override)
        self._ensure_owner(owner)
        with self.lock, self.chats._provider_lock:
            current = self._layers(owner, kind, scope_id)[-1]
            if current['revision'] != expected_revision:
                raise ConversationConflict('模型设置已变化，请刷新后重新选择')
            if value['model'] is not None:
                profile, model, issues = self._selected(owner, value['model'])
                if issues:
                    raise ConversationError(issues[0])
            if kind == 'global':
                if value['model'] is None or value['timeout_seconds'] is None:
                    raise ConversationError('全局默认须选择模型并设置超时')
                with self.chats.database.transaction() as c:
                    now = utc_timestamp()
                    c.execute('UPDATE provider_profile SET is_default=0 WHERE identity_id=? AND is_default=1', (owner,))
                    c.execute('''UPDATE provider_profile SET is_default=1,default_model_id=?,model=?,
                        request_timeout_seconds=?,config_version=config_version+1,updated_at=? WHERE identity_id=? AND id=?''',
                        (model['id'], model['model_id'], value['timeout_seconds'], now, owner, profile['id']))
            else:
                self._write(owner, kind, scope_id, value)
            return self.get(owner, kind, scope_id)

    def _ensure_owner(self, owner):
        if self.db.fetchone('SELECT 1 FROM local_identity WHERE id=?', (owner,)) is None:
            row = self.chats.database.fetchone('SELECT * FROM local_identity WHERE id=?', (owner,))
            if row is None:
                raise DomainError('not_found', 404)
            self.learning.principal(dict(row))

    def _write(self, owner, kind, scope_id, value, connection=None):
        def write(c):
            model = value['model'] or {}
            c.execute('''INSERT INTO learning_model_config
                (owner_id,scope_kind,scope_id,provider_profile_id,provider_model_id,timeout_seconds,revision,updated_at)
                VALUES (?,?,?,?,?,?,1,?) ON CONFLICT(owner_id,scope_kind,scope_id) DO UPDATE SET
                provider_profile_id=excluded.provider_profile_id,provider_model_id=excluded.provider_model_id,
                timeout_seconds=excluded.timeout_seconds,revision=learning_model_config.revision+1,updated_at=excluded.updated_at''',
                (owner, kind, scope_id, model.get('provider_profile_id'), model.get('provider_model_id'), value['timeout_seconds'], utc_timestamp()))
        if connection is not None:
            write(connection)
        else:
            with self.db.transaction(immediate=True) as c:
                write(c)

    def runtime(self, owner, kind, scope_id, run_override=None, expected_token=None):
        with self.lock, self.chats._provider_lock:
            view, profile, model = self._resolve(owner, kind, scope_id, run_override)
            if expected_token is not None and expected_token != view['token']:
                raise ConversationConflict('模型设置已变化，请刷新配置后重新发送')
            if view['issues']:
                raise ConversationError(view['issues'][0])
            key = self.chats._read_key(profile['credential_key'])
            if not key:
                raise ConversationError('所选提供方尚未保存API密钥')
            effective = view['effective']
            config = ProviderConfig(base_url=profile['base_url'], model=model['model_id'], api_key=key,
                                    timeout_seconds=effective['timeout_seconds'], provider_kind=effective['provider_kind'])
            public = {key: value for key, value in effective.items()
                      if key not in {'has_api_key', 'available', 'supports_image_input', 'supports_reasoning'}}
            public.update(sources=view['sources'], captured_at=utc_timestamp(), layers=view['layers'])
            snapshot = {'schema_version': 1,
                'provider': {'id': profile['id'], 'kind': config.provider_kind, 'base_url': config.base_url, 'config_version': profile['config_version']},
                'model': {'id': model['id'], 'model_id': model['model_id'], 'display_name': model['display_name'],
                          'capabilities': self.chats._decode_json(model['capabilities_json'], {})},
                'effective': {'timeout_seconds': config.timeout_seconds, 'conversation_config_version': int(view['revision'].removeprefix('legacy:')) if kind != 'global' else 0},
                'credential': {'ref': profile['credential_key'], 'version': profile['credential_version']},
                'model_control': public, 'model_override': normalize_override(run_override)}
            return profile, config, snapshot

    def copy_branch(self, owner, kind, source_id, branch_id, connection=None):
        """Idempotent copy; existing branch choices are never overwritten."""
        self._ensure_owner(owner)
        value = self._layer(owner, kind, source_id)['override']
        room = None
        if kind == 'conversation':
            # The primary chat commit precedes this learning-db copy. A retry
            # repairs that gap using the creation-time template, not settings
            # that the source may have changed since the first request.
            row = self.chats.database.fetchone('''SELECT config_snapshot_json FROM ai_run
                WHERE identity_id=? AND conversation_id=? ORDER BY rowid LIMIT 1''', (owner, branch_id))
            template = ((json.loads(row[0]).get('branch_origin') or {}).get('model_config_copy') if row else None)
            if template is not None:
                value, room = template['override'], template.get('room')
            else:
                link = self.db.fetchone('SELECT session_id,selected_at FROM learning_room_conversation WHERE owner_id=? AND conversation_id=?', (owner, source_id))
                room = dict(link) if link else None
        def copy(c):
            exists = c.execute('''SELECT 1 FROM learning_model_config
                WHERE owner_id=? AND scope_kind=? AND scope_id=?''', (owner, kind, branch_id)).fetchone()
            if not exists:
                self._write(owner, kind, branch_id, value, c)
            if kind == 'conversation' and room:
                c.execute('''INSERT OR IGNORE INTO learning_room_conversation(owner_id,session_id,conversation_id,selected_at)
                    VALUES (?,?,?,?)''', (owner, room['session_id'], branch_id, room['selected_at']))
        if connection is not None:
            copy(connection)
        else:
            with self.db.transaction(immediate=True) as c:
                copy(c)
