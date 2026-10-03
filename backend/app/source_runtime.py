"""Keep explicit material boundaries out of unrelated context and tool history."""
from contextlib import nullcontext
from functools import wraps


def material_guard(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        materials = getattr(self, 'materials', None) or getattr(getattr(self, 'chats', None), 'materials', None)
        with materials.lock if materials else nullcontext():
            return method(self, *args, **kwargs)
    return guarded


def scope_key(scope):
    scope = scope or {}
    if scope.get('purged'):
        return ('purged',)
    knowledge = scope.get('knowledge_base')
    if knowledge:
        return (scope.get('mode', 'unspecified'),
                tuple(scope.get('selection_version_ids', scope.get('version_ids', []))),
                knowledge.get('kind'), knowledge.get('connection_id'), knowledge.get('connection_revision'))
    return (scope.get('mode', 'unspecified'), tuple(scope.get('version_ids', [])))


def scoped_path(path, scope):
    """Normal references keep discussion continuity; strict scopes stay isolated."""
    kept = []
    for item in reversed(path):
        paired_question = (kept and kept[-1].get('role') == 'assistant'
                           and kept[-1].get('parent_message_id') == item.get('id'))
        if not paired_question and not compatible_scope(item.get('source_scope'), scope):
            break
        kept.append(item)
    return list(reversed(kept))


def compatible_scope(previous, current):
    if (current or {}).get('mode') == 'reference':
        return not (previous or {}).get('purged') and (previous or {}).get('mode', 'unspecified') in ('unspecified', 'reference')
    return scope_key(previous) == scope_key(current)


def public_scope(scope, answer=''):
    if scope is None:
        return None
    result = {key: value for key, value in scope.items() if key != 'materials' and not key.startswith('_')}
    result['materials'] = [
        {**{key: value for key, value in material.items() if key != 'content'},
         'cited': f'【资料{index}】' in (answer or '')}
        for index, material in enumerate(scope.get('materials', []), 1)
    ]
    return result
