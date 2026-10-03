"""Confirmed learning rules with live, owner-scoped answer provenance.

Only enum configurations, source references and action digests are persisted.
Preference quotations and model explanations remain in the original answer,
so its existing deletion and managed-purge lifecycle also covers these views.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from uuid import NAMESPACE_URL, uuid4, uuid5

from .auth import utc_now
from .source_runtime import material_guard

CONFIGURATION_OPTIONS = {
    'scenario': {'general', 'concepts', 'problem_solving', 'coding', 'project'},
    'method': {'stepwise', 'socratic', 'feynman', 'practice_first', 'project', 'direct_answer', 'full_explanation'},
    'start': {'auto', 'example_first', 'try_first', 'explain_first'},
    'help': {'auto', 'one_hint', 'explain_when_stuck'},
}


class AdaptivePreferencesError(ValueError):
    def __init__(self, status_code=422):
        self.status_code = status_code
        super().__init__('个人学习偏好暂时无法处理')


def validate_configuration(value):
    if not isinstance(value, dict) or set(value) != set(CONFIGURATION_OPTIONS):
        raise AdaptivePreferencesError()
    if any(not isinstance(value[key], str) or value[key] not in options
           for key, options in CONFIGURATION_OPTIONS.items()):
        raise AdaptivePreferencesError()
    if (value['method'] in {'practice_first', 'feynman'} and value['start'] not in {'auto', 'try_first'}
            or value['method'] in {'direct_answer', 'full_explanation'} and value['start'] == 'try_first'):
        raise AdaptivePreferencesError()
    return {key: value[key] for key in CONFIGURATION_OPTIONS}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _fingerprint(configuration):
    return _canonical(configuration)


def _candidate_id(kind, answer_id):
    return str(uuid5(NAMESPACE_URL, f'nautilus:adaptive-draft:{kind}:{answer_id}'))


def _now():
    return utc_now().isoformat(timespec='microseconds').replace('+00:00', 'Z')


class AdaptivePreferencesService:
    def __init__(self, conversations, learning_database, credentials):
        self.chats = conversations
        self.database = conversations.database
        self.learning_database = learning_database
        self.credentials = credentials
        self._lock = threading.RLock()

    @material_guard
    def get(self, owner):
        with self._lock:
            state = self._load(owner)
            return self._view(state, self._candidates(owner))

    @material_guard
    def freeze(self, owner):
        """Expose enum rules only; no source text or explanations go to models."""
        with self._lock:
            state = self._load(owner)
            candidates = self._candidates(owner)
            view = self._view(state, candidates)
            configurations = [*state['suppressed'],
                              *(rule['configuration'] for rule in state['rules']),
                              *(draft['configuration'] for draft in view['drafts'])]
            suppressed = {_fingerprint(value): value for value in configurations}
            return {'revision': state['revision'],
                    'rules': [{'id': rule['id'], 'configuration': rule['configuration']}
                              for rule in view['rules'] if rule['enabled']],
                    'suppressed': list(suppressed.values())}

    @material_guard
    def change(self, owner, payload):
        payload = self._validate_change(payload)
        digest = hashlib.sha256(_canonical(payload).encode('utf-8')).hexdigest()
        request_id = hashlib.sha256(payload['request_key'].encode('utf-8')).hexdigest()
        with self._lock:
            # Share CredentialStore's write lock with other service instances;
            # one settings entry must have one read/modify/write operation.
            with self.credentials._lock:
                state = self._load(owner)
                candidates = self._candidates(owner)
                previous = state['requests'].get(request_id)
                if previous is not None:
                    if previous != digest:
                        raise AdaptivePreferencesError(409)
                    return self._view(state, candidates)
                if payload['expected_revision'] != state['revision']:
                    raise AdaptivePreferencesError(409)
                before = copy.deepcopy(state['rules'])
                action = payload['action']
                if action in ('accept', 'dismiss'):
                    draft = next((item for item in self._drafts(state, candidates)
                                  if item['id'] == payload['candidate_id']), None)
                    if draft is None:
                        raise AdaptivePreferencesError(404)
                    state['handled'].append(draft['id'])
                    state['reconsidered'] = [identifier for identifier in state['reconsidered'] if identifier != draft['id']]
                    self._suppress(state, draft['configuration'])
                    if action == 'accept':
                        state['rules'] = [rule for rule in state['rules']
                                          if rule['configuration']['scenario'] != draft['configuration']['scenario']]
                        state['rules'].append({'id': str(uuid4()), 'configuration': draft['configuration'],
                                               'enabled': True, 'source': {'candidate_id': draft['id'],
                                                   'start': draft['source']['start'], 'end': draft['source']['end']}})
                    else:
                        state['dismissed'][draft['id']] = copy.deepcopy(draft['configuration'])
                elif action == 'reconsider':
                    draft = next((item for item in self._ignored(state, candidates)
                                  if item['id'] == payload['candidate_id']), None)
                    if draft is None:
                        raise AdaptivePreferencesError(404)
                    state['dismissed'].pop(draft['id'])
                    state['handled'] = [identifier for identifier in state['handled'] if identifier != draft['id']]
                    state['reconsidered'].append(draft['id'])
                    fingerprint = _fingerprint(draft['configuration'])
                    if all(_fingerprint(value) != fingerprint for value in state['dismissed'].values()):
                        state['suppressed'] = [value for value in state['suppressed'] if _fingerprint(value) != fingerprint]
                elif action in ('edit', 'remove'):
                    rule = next((item for item in state['rules'] if item['id'] == payload['rule_id']), None)
                    if rule is None:
                        raise AdaptivePreferencesError(404)
                    if action == 'remove':
                        state['rules'].remove(rule)
                    else:
                        if payload['enabled'] and self._resolve(rule, candidates) is None:
                            raise AdaptivePreferencesError(404)
                        if any(other['id'] != rule['id'] and other['configuration']['scenario'] == payload['configuration']['scenario']
                               for other in state['rules']):
                            raise AdaptivePreferencesError(409)
                        rule.update(configuration=payload['configuration'], enabled=payload['enabled'])
                        self._suppress(state, rule['configuration'])
                else:
                    version = next((item for item in state['history'] if item['revision'] == payload['version']), None)
                    if version is None:
                        raise AdaptivePreferencesError(404)
                    state['rules'] = copy.deepcopy(version['rules'])
                    for rule in state['rules']:
                        if self._resolve(rule, candidates) is None:
                            rule['enabled'] = False
                if not any(item['revision'] == state['revision'] for item in state['history']):
                    state['history'].append({'revision': state['revision'], 'created_at': state['created_at'], 'rules': before})
                state['revision'] += 1
                state['created_at'] = _now()
                state['requests'][request_id] = digest
                self.credentials.set(self._key(owner), _canonical(state))
                return self._view(state, candidates)

    @staticmethod
    def _key(owner):
        return f'adaptive-learning:{owner}'

    @staticmethod
    def _suppress(state, configuration):
        fingerprint = _fingerprint(configuration)
        if all(_fingerprint(value) != fingerprint for value in state['suppressed']):
            state['suppressed'].append(copy.deepcopy(configuration))

    def _load(self, owner):
        raw = self.credentials.get(self._key(owner))
        if raw is None:
            return {'schema_version': 1, 'revision': 0, 'created_at': '1970-01-01T00:00:00Z',
                    'rules': [], 'history': [{'revision': 0, 'created_at': '1970-01-01T00:00:00Z', 'rules': []}],
                    'suppressed': [], 'handled': [], 'dismissed': {}, 'reconsidered': [], 'requests': {}}
        try:
            state = json.loads(raw)
            if (not isinstance(state, dict) or set(state) != {'schema_version', 'revision', 'created_at', 'rules', 'history', 'suppressed', 'handled', 'dismissed', 'reconsidered', 'requests'}
                    or state['schema_version'] != 1 or type(state['revision']) is not int or state['revision'] < 0
                    or not isinstance(state['created_at'], str)):
                raise ValueError()
            self._validate_saved_rules(state['rules'])
            if not isinstance(state['history'], list):
                raise ValueError()
            versions = set()
            for version in state['history']:
                if (not isinstance(version, dict) or set(version) != {'revision', 'created_at', 'rules'}
                        or type(version['revision']) is not int or not 0 <= version['revision'] <= state['revision']
                        or version['revision'] in versions or not isinstance(version['created_at'], str)):
                    raise ValueError()
                versions.add(version['revision'])
                self._validate_saved_rules(version['rules'])
            if 0 not in versions:
                raise ValueError()
            if not isinstance(state['suppressed'], list) or not isinstance(state['handled'], list):
                raise ValueError()
            for configuration in state['suppressed']:
                validate_configuration(configuration)
            if any(not isinstance(value, str) for value in state['handled']):
                raise ValueError()
            if not isinstance(state['dismissed'], dict) or any(not isinstance(key, str) for key in state['dismissed']):
                raise ValueError()
            for configuration in state['dismissed'].values():
                validate_configuration(configuration)
            if not isinstance(state['reconsidered'], list) or any(not isinstance(value, str) for value in state['reconsidered']):
                raise ValueError()
            if not isinstance(state['requests'], dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                                              for key, value in state['requests'].items()):
                raise ValueError()
            return state
        except (ValueError, TypeError, KeyError):
            raise AdaptivePreferencesError(503) from None

    @staticmethod
    def _validate_saved_rules(rules):
        if not isinstance(rules, list):
            raise ValueError()
        ids, scenarios = set(), set()
        for rule in rules:
            if (not isinstance(rule, dict) or set(rule) != {'id', 'configuration', 'enabled', 'source'}
                    or not isinstance(rule['id'], str) or type(rule['enabled']) is not bool):
                raise ValueError()
            configuration = validate_configuration(rule['configuration'])
            source = rule['source']
            if (not isinstance(source, dict) or set(source) != {'candidate_id', 'start', 'end'}
                    or not isinstance(source['candidate_id'], str) or type(source['start']) is not int
                    or type(source['end']) is not int or not 0 <= source['start'] < source['end']):
                raise ValueError()
            if rule['id'] in ids or configuration['scenario'] in scenarios:
                raise ValueError()
            ids.add(rule['id'])
            scenarios.add(configuration['scenario'])

    @staticmethod
    def _validate_change(payload):
        if not isinstance(payload, dict):
            raise AdaptivePreferencesError()
        common = {'expected_revision', 'request_key', 'action'}
        fields = {'accept': {'candidate_id'}, 'dismiss': {'candidate_id'}, 'reconsider': {'candidate_id'},
                  'edit': {'rule_id', 'configuration', 'enabled'}, 'remove': {'rule_id'}, 'restore': {'version'}}
        action = payload.get('action')
        if not isinstance(action, str) or action not in fields or set(payload) != common | fields[action]:
            raise AdaptivePreferencesError()
        if (type(payload['expected_revision']) is not int or payload['expected_revision'] < 0
                or not isinstance(payload['request_key'], str) or not 1 <= len(payload['request_key']) <= 120
                or not payload['request_key'].strip()):
            raise AdaptivePreferencesError()
        for key in ('candidate_id', 'rule_id'):
            if key in payload and (not isinstance(payload[key], str) or not 1 <= len(payload[key]) <= 120):
                raise AdaptivePreferencesError()
        if action == 'edit':
            validate_configuration(payload['configuration'])
            if type(payload['enabled']) is not bool:
                raise AdaptivePreferencesError()
        if action == 'restore' and (type(payload['version']) is not int or payload['version'] < 0):
            raise AdaptivePreferencesError()
        return copy.deepcopy(payload)

    def _candidates(self, owner):
        ordinary = self.database.fetchall('''SELECT c.id AS scope_id, r.response_message_id AS answer_id,
            u.id AS message_id, u.content AS user_text,
            json_extract(r.config_snapshot_json,'$.teaching') AS teaching_json
            FROM ai_run r JOIN conversation c ON c.id=r.conversation_id AND c.identity_id=r.identity_id
            JOIN message u ON u.id=COALESCE(json_extract(r.config_snapshot_json,'$.teaching.message_id'),
                                           json_extract(r.config_snapshot_json,'$.reply.question_id'),r.request_message_id)
                          AND u.conversation_id=c.id AND u.role='user'
            JOIN message a ON a.id=r.response_message_id AND a.conversation_id=c.id AND a.role='assistant'
            WHERE r.identity_id=? AND c.deleted_at IS NULL AND r.status='succeeded'
              AND u.status='complete' AND a.status='complete' AND u.content<>'' AND a.content<>''
              AND COALESCE(json_extract(r.config_snapshot_json,'$.source_scope.purged'),0)=0
              AND json_type(r.config_snapshot_json,'$.teaching.result.adaptation.draft')='object'
            ORDER BY r.created_at,c.id,r.response_message_id''', (owner,))
        discussions = self.learning_database.fetchall('''SELECT q.id AS scope_id, t.id AS answer_id,
            t.id AS message_id, t.user_content AS user_text,
            json_extract(t.provider_snapshot_json,'$.teaching') AS teaching_json
            FROM learning_discussion_turn t JOIN learning_question_discussion q ON q.id=t.discussion_id
            WHERE q.owner_id=? AND q.purged_at IS NULL AND t.status='succeeded'
              AND t.user_content IS NOT NULL AND t.user_content<>'' AND t.assistant_content IS NOT NULL AND t.assistant_content<>''
              AND COALESCE(json_extract(t.provider_snapshot_json,'$.source_scope.purged'),0)=0
              AND json_type(t.provider_snapshot_json,'$.teaching.result.adaptation.draft')='object'
            ORDER BY t.created_at,q.id,t.id''', (owner,))
        copies = []
        for kind, rows in (('conversation', ordinary), ('discussion', discussions)):
            for row in rows:
                candidate = self._read_candidate(kind, row)
                if candidate is not None:
                    copies.append(candidate)
        # Prefer the original location; a surviving accessible branch is an
        # equally valid source when its original conversation was deleted.
        copies.sort(key=lambda item: (not item['_original'], item['source']['scope_id'], item['source']['answer_id']))
        candidates = {}
        for item in copies:
            candidates.setdefault(item['id'], item)
        return candidates

    @staticmethod
    def _read_candidate(kind, row):
        try:
            teaching = json.loads(row['teaching_json'])
            if teaching.get('answer_id') != row['answer_id'] or teaching.get('message_id') != row['message_id']:
                return None
            origin = teaching['origin']
            if origin.get('kind') != kind or not isinstance(origin.get('answer_id'), str) or not origin['answer_id']:
                return None
            draft = teaching['result']['adaptation']['draft']
            if not isinstance(draft, dict) or set(draft) != {'configuration', 'source', 'reason'}:
                return None
            configuration = validate_configuration(draft['configuration'])
            reference = draft['source']
            if (not isinstance(reference, dict) or set(reference) != {'message_id', 'start', 'end'}
                    or reference['message_id'] != row['message_id']
                    or type(reference['start']) is not int or type(reference['end']) is not int
                    or not 0 <= reference['start'] < reference['end'] <= len(row['user_text'])
                    or not isinstance(draft['reason'], str) or not draft['reason'].strip()):
                return None
            source = {'kind': kind, 'scope_id': row['scope_id'], 'answer_id': row['answer_id'], **reference}
            return {'id': _candidate_id(kind, origin['answer_id']), 'configuration': configuration,
                    'reason': draft['reason'], 'source': source,
                    'original_text': row['user_text'][reference['start']:reference['end']],
                    '_user_text': row['user_text'], '_original': origin['answer_id'] == row['answer_id']}
        except (ValueError, TypeError, KeyError, AttributeError):
            return None

    @staticmethod
    def _resolve(rule, candidates):
        reference = rule['source']
        candidate = candidates.get(reference['candidate_id'])
        if candidate is None or reference['end'] > len(candidate['_user_text']):
            return None
        source = {**candidate['source'], 'start': reference['start'], 'end': reference['end']}
        return source, candidate['_user_text'][reference['start']:reference['end']]

    def _public_rule(self, rule, candidates):
        resolved = self._resolve(rule, candidates)
        return {'id': rule['id'], 'configuration': copy.deepcopy(rule['configuration']),
                'enabled': rule['enabled'] and resolved is not None,
                'source': resolved[0] if resolved else None, 'original_text': resolved[1] if resolved else None}

    @staticmethod
    def _public_draft(candidate):
        return {key: copy.deepcopy(candidate[key]) for key in ('id', 'configuration', 'reason', 'source', 'original_text')}

    def _ignored(self, state, candidates):
        return [self._public_draft(candidates[identifier]) for identifier in state['dismissed'] if identifier in candidates]

    def _drafts(self, state, candidates):
        handled = set(state['handled'])
        suppressed = {_fingerprint(value) for value in [*state['suppressed'], *(rule['configuration'] for rule in state['rules'])]}
        drafts = []
        reconsidered = set(state['reconsidered'])
        for candidate in sorted(candidates.values(), key=lambda item: item['id'] not in reconsidered):
            fingerprint = _fingerprint(candidate['configuration'])
            if candidate['id'] in handled or fingerprint in suppressed:
                continue
            suppressed.add(fingerprint)
            drafts.append(self._public_draft(candidate))
        return drafts

    def _view(self, state, candidates):
        return {'revision': state['revision'],
                'rules': [self._public_rule(rule, candidates) for rule in state['rules']],
                'drafts': self._drafts(state, candidates),
                'ignored': self._ignored(state, candidates),
                'history': [{'revision': item['revision'], 'created_at': item['created_at'],
                             'rules': [self._public_rule(rule, candidates) for rule in item['rules']]}
                            for item in reversed(state['history'])]}
