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
    return (scope.get('mode', 'unspecified'), tuple(scope.get('version_ids', [])))


def scoped_path(path, scope):
    """Only a continuous suffix in the same scope may continue the model turn."""
    kept = []
    for item in reversed(path):
        paired_question = (kept and kept[-1].get('role') == 'assistant'
                           and kept[-1].get('parent_message_id') == item.get('id'))
        if not paired_question and scope_key(item.get('source_scope')) != scope_key(scope):
            break
        kept.append(item)
    return list(reversed(kept))


def public_scope(scope, answer=''):
    if scope is None:
        return None
    result = {key: value for key, value in scope.items() if key != 'materials'}
    result['materials'] = [
        {**{key: value for key, value in material.items() if key != 'content'},
         'cited': f'【资料{index}】' in (answer or '')}
        for index, material in enumerate(scope.get('materials', []), 1)
    ]
    return result
