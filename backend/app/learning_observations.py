"""Source-bound teaching observations; never formal mastery or completion facts."""
from __future__ import annotations

import copy

STATES = {'progress', 'difficulty', 'uncertain'}


def help_context(path, before):
    def position(checkpoint):
        return (checkpoint.get('practice') or checkpoint.get('step') or {}).get('id')
    point = position(before)
    records = []
    for entry in path:
        teaching = entry.get('teaching') or {}
        help_record = entry.get('help_record') or {}
        method = teaching.get('effective_mode')
        if (point and position(teaching.get('before') or {}) == point and help_record.get('provided')
                and (help_record.get('request') or method in {'direct_answer', 'full_explanation'})):
            records.append({'answer_id': entry['id'], **copy.deepcopy(help_record), 'method': method})
    return records


def _text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('learning_observation_invalid')
    return value.strip()


def _span(quote, original, limit):
    if not isinstance(quote, str) or not quote.strip() or len(quote) > limit:
        raise ValueError('learning_observation_source_invalid')
    start = original.find(quote)
    if start < 0:
        raise ValueError('learning_observation_source_invalid')
    return {'start': start, 'end': start + len(quote)}


def evaluate(value, frozen, attempt, *, body, user_text, at):
    if value is None:
        return [], []
    if not isinstance(value, dict) or set(value) != {'observations', 'used'}:
        raise ValueError('learning_observation_invalid')
    observations, used = value['observations'], value['used']
    if not isinstance(observations, list) or len(observations) > 4 or not isinstance(used, list) or len(used) > 12:
        raise ValueError('learning_observation_invalid')
    available = {record['id'] for point in frozen.get('learning_context', []) for record in point['observations']}
    if any(not isinstance(identifier, str) or identifier not in available for identifier in used) or len(set(used)) != len(used):
        raise ValueError('learning_observation_reference_unavailable')
    if observations and not attempt:
        raise ValueError('learning_observation_without_attempt')
    points = {item['point_id'] for item in frozen.get('learning_context', [])}
    records = []
    used_points = set()
    for index, item in enumerate(observations):
        if not isinstance(item, dict) or set(item) != {'point_id', 'topic', 'state', 'quote', 'feedback'}:
            raise ValueError('learning_observation_invalid')
        point_id = item['point_id']
        if point_id is not None and (not isinstance(point_id, str) or point_id not in points):
            raise ValueError('learning_observation_point_unavailable')
        topic = _text(item['topic'], 120)
        if not isinstance(item['state'], str) or item['state'] not in STATES:
            raise ValueError('learning_observation_invalid')
        source = _span(item['quote'], user_text, 1200)
        if not attempt['start'] <= source['start'] < source['end'] <= attempt['end']:
            raise ValueError('learning_observation_source_outside_attempt')
        feedback = _span(item['feedback'], body, 1200)
        identifier = f"{frozen['answer_id']}:{index}"
        point_id = point_id or identifier
        if point_id in used_points:
            raise ValueError('learning_observation_duplicate_point')
        used_points.add(point_id)
        records.append({'id': identifier, 'point_id': point_id, 'topic': topic, 'state': item['state'],
                        'source': {'message_id': frozen['message_id'], **source},
                        'feedback': {'answer_id': frozen['answer_id'], **feedback}, 'at': at,
                        'help_context': copy.deepcopy(frozen.get('learning_help_context', []))})
    return records, used


def context(path):
    """Rebuild from corrected observations on this exact, already-authorized path."""
    allowed = {entry['id'] for entry in path}
    points = {}
    for entry in path:
        for item in (entry.get('teaching') or {}).get('learning_observations', []):
            if not item.get('eligible') or item['point_id'].rsplit(':', 1)[0] not in allowed:
                continue
            point = points.pop(item['point_id'], {'point_id': item['point_id'], 'topic': item['topic'], 'observations': []})
            point['topic'] = item['topic']
            observation = {key: copy.deepcopy(item[key]) for key in
                           ('id', 'point_id', 'topic', 'state', 'source', 'feedback', 'at', 'note', 'revision')}
            observation['help_context'] = [copy.deepcopy(help_item) for help_item in item.get('help_context', [])
                                           if help_item['answer_id'] in allowed][-3:]
            observation['recorded_help_count'] = sum(help_item['answer_id'] in allowed for help_item in item.get('help_context', []))
            point['observations'] = [*point['observations'], observation][-3:]
            points[item['point_id']] = point
    return list(points.values())[-12:]


def prompt_context(frozen, user_texts, answer_texts):
    points = copy.deepcopy(frozen.get('learning_context', []))
    for point in points:
        for item in point['observations']:
            source, feedback = item['source'], item['feedback']
            original = (user_texts or {}).get(source['message_id'], '')
            answer = (answer_texts or {}).get(feedback['answer_id'], '')
            item['user_quote'] = original[source['start']:source['end']]
            item['feedback_quote'] = answer[feedback['start']:feedback['end']]
    return points


def public(snapshot, attempt):
    result = (snapshot.get('teaching') or {}).get('result') or {}
    annotations = snapshot.get('learning_observation_corrections', [])
    records = copy.deepcopy(result.get('learning_observations', []))
    for record in records:
        corrections = [item for item in annotations if item['observation_id'] == record['id']]
        record['original'] = {key: record[key] for key in ('topic', 'state')}
        record.update(note='', excluded=False, revision=len(corrections),
                      corrections=[{key: item[key] for key in
                                    ('revision', 'topic', 'state', 'note', 'excluded', 'at')}
                                   for item in corrections])
        if corrections:
            record.update({key: corrections[-1][key] for key in ('topic', 'state', 'note', 'excluded')})
        record['eligible'] = bool(attempt and attempt.get('is_attempt') and not record['excluded'])
    return records


def correct(snapshot, *, observation_id, expected_revision, topic, state, note, excluded, request_key, at):
    original = next((item for item in (snapshot.get('teaching', {}).get('result') or {}).get('learning_observations', [])
                     if item['id'] == observation_id), None)
    if original is None:
        raise ValueError('learning_observation_unavailable')
    topic = _text(topic, 120)
    if (state not in STATES or type(excluded) is not bool or not isinstance(note, str) or len(note) > 600
            or type(expected_revision) is not int or expected_revision < 0
            or not isinstance(request_key, str) or not 1 <= len(request_key) <= 100):
        raise ValueError('learning_observation_invalid')
    payload = dict(observation_id=observation_id, revision=expected_revision + 1, topic=topic,
                   state=state, note=note.strip(), excluded=excluded, request_key=request_key)
    annotations = snapshot.setdefault('learning_observation_corrections', [])
    for item in annotations:
        if item['request_key'] == request_key:
            if any(item[key] != value for key, value in payload.items()):
                raise ValueError('learning_observation_changed')
            return
    if sum(item['observation_id'] == observation_id for item in annotations) != expected_revision:
        raise ValueError('learning_observation_changed')
    annotations.append({**payload, 'at': at})


def remap(snapshot, mapped):
    def identifier(value):
        answer_id, index = value.rsplit(':', 1)
        return f'{mapped(answer_id)}:{index}'

    def record(value):
        value['id'] = identifier(value['id'])
        value['point_id'] = identifier(value['point_id'])
        value['source']['message_id'] = mapped(value['source']['message_id'])
        value['feedback']['answer_id'] = mapped(value['feedback']['answer_id'])
        for help_item in value.get('help_context', []):
            help_item['answer_id'] = mapped(help_item['answer_id'])

    frozen = snapshot.get('teaching') or {}
    for item in frozen.get('learning_help_context', []):
        item['answer_id'] = mapped(item['answer_id'])
    for item in (frozen.get('result') or {}).get('learning_observations', []):
        record(item)
    result = frozen.get('result') or {}
    if 'learning_used' in result:
        result['learning_used'] = [identifier(value) for value in result['learning_used']]
    for item in snapshot.get('learning_observation_corrections', []):
        item['observation_id'] = identifier(item['observation_id'])
    for point in frozen.get('learning_context', []):
        point['point_id'] = identifier(point['point_id'])
        for item in point['observations']:
            record(item)
