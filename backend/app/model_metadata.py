"""Allowlisted public model-list facts; missing fields remain unknown.

The format identifies a returned wire schema, never a model family or URL.
Invalid enum lists are omitted as a whole instead of looking like a complete
list containing only the values this client happens to recognize.
"""
from __future__ import annotations

EFFORT_LEVELS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
CLAUDE_EFFORT_LEVELS = ('low', 'medium', 'high', 'xhigh', 'max')
CLAUDE_THINKING_MODES = ('adaptive', 'enabled')


def _positive_integer(value):
    return type(value) is int and value > 0


def _enum_list(value, allowed):
    if not isinstance(value, list) or any(not isinstance(item, str) or item not in allowed for item in value):
        return None
    return list(dict.fromkeys(value))


def _supported_flags(value, allowed):
    """A partial flag object does not establish the complete supported set."""
    if not isinstance(value, dict):
        return None
    if 'supported' in value and type(value['supported']) is not bool:
        return None
    if any(key not in {*allowed, 'supported'} and isinstance(entry, dict) and 'supported' in entry
           for key, entry in value.items()):
        return None
    flags = {}
    for name in allowed:
        entry = value.get(name)
        if not isinstance(entry, dict) or type(entry.get('supported')) is not bool:
            return None
        flags[name] = entry['supported']
    return [name for name in allowed if flags[name]]


def reasoning_metadata(item, kind):
    """None means absent; an empty/format-only object means reported but unknown."""
    if not isinstance(item, dict):
        return None
    result = {}
    seen = False
    if kind == 'google':
        if 'thinking' in item:
            seen = True
            result['format'] = 'google_thinking'
            if type(item['thinking']) is bool:
                result['thinking_supported'] = item['thinking']
    elif kind == 'anthropic':
        capabilities = item.get('capabilities')
        if 'capabilities' in item:
            seen = True
        if isinstance(capabilities, dict) and any(key in capabilities for key in ('effort', 'thinking')):
            result['format'] = 'anthropic_capabilities'
            effort = capabilities.get('effort')
            if isinstance(effort, dict):
                levels = _supported_flags(effort, CLAUDE_EFFORT_LEVELS)
                if effort.get('supported') is False:
                    if levels is None and any(isinstance(entry, dict) and entry.get('supported') is True
                                              for key, entry in effort.items() if key != 'supported'):
                        levels = None
                    elif not levels:
                        levels = []
                    else:
                        levels = None
                if levels is not None:
                    result['effort_levels'] = levels
            thinking = capabilities.get('thinking')
            if isinstance(thinking, dict):
                if type(thinking.get('supported')) is bool:
                    result['thinking_supported'] = thinking['supported']
                modes = _supported_flags(thinking.get('types'), CLAUDE_THINKING_MODES)
                if modes is not None and (thinking.get('supported') is not False or not modes):
                    result['thinking_modes'] = modes
        if 'max_tokens' in item:
            seen = True
            if _positive_integer(item['max_tokens']):
                result['max_output_tokens'] = item['max_tokens']
    else:
        if 'effort' in item:
            seen = True
        effort = item.get('effort')
        if isinstance(effort, dict) and any(key in effort for key in ('supported_levels', 'default_level')):
            result['format'] = 'deepseek_effort'
            levels = _enum_list(effort.get('supported_levels'), EFFORT_LEVELS)
            if levels is not None:
                result['effort_levels'] = levels
            default = effort.get('default_level')
            if isinstance(default, str) and default in EFFORT_LEVELS and (levels is None or default in levels):
                result['default_effort'] = default
        if 'max_output_tokens' in item:
            seen = True
            if _positive_integer(item['max_output_tokens']):
                result['max_output_tokens'] = item['max_output_tokens']
    return result if seen else None


def add_catalog_entry(catalog, model_id, item, kind, conflicts=None):
    """Keep duplicate IDs, but conflicting metadata cannot become trusted facts."""
    metadata = reasoning_metadata(item, kind)
    entry = catalog.setdefault(model_id, {'id': model_id})
    if metadata is None:
        return
    existing = entry.get('reasoning_metadata')
    if existing is None:
        entry['reasoning_metadata'] = metadata
    elif existing != metadata:
        # Conflicting duplicate records retain only identical facts. Missing
        # fields do not erase a separately reported fact.
        invalid = {key for key in existing.keys() & metadata.keys() if existing[key] != metadata[key]}
        if conflicts is not None:
            invalid = conflicts.setdefault(model_id, set()) | invalid
            conflicts[model_id] = invalid
        entry['reasoning_metadata'] = {key: value for key, value in {**existing, **metadata}.items()
                                       if key not in invalid}
