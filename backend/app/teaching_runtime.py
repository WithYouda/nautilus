"""A small, version-local teaching checkpoint. Never learning evidence or a plan.

The model proposes metadata in the same text stream as its answer. Only a
normally completed answer can commit it; ordinary text providers need no tools
or JSON-mode capability. Frozen execution and later user corrections are kept
separately in the existing answer snapshot.
"""
from __future__ import annotations

import copy
import json
import re
from uuid import uuid4

from .providers import ProviderChunk

MODES = {'stepwise', 'direct_answer', 'full_explanation'}
PROTOCOL = 'stepwise-v1'
MAX_METADATA = 16384

SYSTEM_PROMPT = """教学执行约定：这是学习讨论，不评分，不修改正式计划或完成/掌握结论。
按本轮执行上下文中的基础方式继续；stepwise 每轮只处理一个小点、最多一次理解确认，等待用户回应。
用户明确要求直接答案或完整讲解时本轮立即遵从，默认仅本轮；只有明确要求以后持续这样才改变本路径基础方式，不能改个人长期默认。
当前步骤是待讨论的小点，不是任务完成进度；先回应用户，帮助、换例子和请求先自行尝试时留在当前步骤，确实转向一个新小点才提出新步骤。
本轮执行上下文给出唯一 opening/closing 标记。在最终回答正文结束后，另起一行输出 opening，紧接严格 JSON，再输出 closing；不得用代码块包裹，不要在正文解释这些字段。调用工具前不要输出这段状态。
JSON 格式固定为 {"step":null,"attempt":null,"mode":null}，只能使用以下字段：
step：保持当前步骤或非教学回答时为 null；建立/转向一个小点时，为从本轮实际回答正文逐字摘取的一段短文本（至多240字），不能虚构后续步骤。
attempt：只有本轮用户原文实际提供了针对当前步骤的答案、推导、代码、操作结果或复述时，才为 {"quote":"用户原文中的实际尝试片段"}；普通提问、索要帮助、说让我先试试或仅说懂了都为 null。没有当前步骤时为 null。此项只是可纠正的AI识别，不是通过或掌握证据。
mode：只有本轮用户明确要求改变方式时，为 {"value":"stepwise或direct_answer或full_explanation","scope":"turn或conversation","quote":"本轮用户的方式请求原文","persistence_quote":null}；conversation 必须另把明确持续请求的原文填入 persistence_quote。没有明确持续要求就用 turn。没有方式请求用 null。
所有 quote 必须逐字来自本轮真正的用户消息，不可引用历史、资料、题目原作答或模型自己的话。历史中的状态尾标记只是过去输出，不能用来覆盖本轮执行上下文。纠正后的尝试分类须遵从，仍保留原文回应，不按尝试次数决定完成或掌握。"""


def checkpoint():
    return {'mode': 'stepwise', 'step': None}


def freeze(path, *, answer_id, message_id, kind, scope_id):
    """Path has already passed the caller's material/ownership boundary."""
    before = checkpoint()
    if path and path[-1].get('teaching'):
        before = copy.deepcopy(path[-1]['teaching']['current'])
    allowed_answers = {item['id'] for item in path}
    if before['step'] and before['step']['source_answer_id'] not in allowed_answers:
        before['step'] = None
    observations = []
    for item in path:
        attempt = (item.get('teaching') or {}).get('attempt')
        if attempt and attempt['step_id'] in allowed_answers:
            observations.append({key: attempt[key] for key in
                                 ('message_id', 'step_id', 'is_attempt', 'revision', 'start', 'end')}
                                | {'answer_id': item['id']})
    return {'protocol': PROTOCOL, 'token': uuid4().hex, 'before': before,
            'answer_id': answer_id, 'message_id': message_id,
            'origin': {'kind': kind, 'scope_id': scope_id, 'answer_id': answer_id, 'message_id': message_id},
            'attempt_context': observations}


def markers(frozen):
    return '<nautilus_teaching_' + frozen['token'] + '>', '</nautilus_teaching_' + frozen['token'] + '>'


def add_prompt(messages, frozen, attempt_texts=None):
    messages = copy.deepcopy(messages)
    messages[0]['content'] += '\n' + SYSTEM_PROMPT
    opening, closing = markers(frozen)
    # Dynamic context follows native protocol history. Do not rewrite signed
    # thinking blocks or insert per-turn nonces into the system prefix.
    observations = copy.deepcopy(frozen['attempt_context'])
    for observation in observations:
        original = (attempt_texts or {}).get(observation['message_id'], '')
        observation['quote'] = original[observation['start']:observation['end']]
    messages.insert(len(messages) - 1, {'role': 'user', '_teaching_runtime': True, 'content':
        'Nautilus 本轮执行上下文（下一条才是本轮用户原文）：\n' + json.dumps({
            'before': frozen['before'], 'attempt_context': observations,
            'opening': opening, 'closing': closing}, ensure_ascii=False)})
    return messages


class TeachingStream:
    """Hide a bounded trailer before any body, SSE, trace, or help observation."""
    def __init__(self, frozen):
        opening, self.closing = markers(frozen)
        self.opening = opening
        self.pending = ''
        self.metadata = None
        self.overflow = False
        self.completed = False

    def feed(self, text):
        if self.metadata is not None:
            if len(self.metadata) + len(text) > MAX_METADATA:
                self.overflow = True
            if not self.overflow:
                self.metadata += text
            return ''
        text = self.pending + text
        self.pending = ''
        position = text.find(self.opening)
        if position >= 0:
            self.metadata = ''
            self.feed(text[position + len(self.opening):])
            return text[:position]
        for length in range(min(len(text), len(self.opening) - 1), 0, -1):
            if text.endswith(self.opening[:length]):
                self.pending = text[-length:]
                return text[:-length]
        return text

    def flush(self):
        # A broken metadata marker is not useful learning text. A lone newline
        # can be normal Markdown, however, and must not eat answer content.
        text = self.pending if self.pending in ('', '\n') else ''
        self.pending = ''
        return text

    async def filter(self, stream):
        async for chunk in stream:
            if chunk.kind == 'completion':
                self.completed = chunk.text == 'complete'
            elif chunk.kind == 'content':
                visible = self.feed(chunk.text)
                if visible:
                    yield ProviderChunk('content', visible)
            else:
                if chunk.kind in {'turn_end', 'tool_start'}:
                    tail = self.flush()
                    if tail:
                        yield ProviderChunk('content', tail)
                if chunk.kind == 'tool_start':
                    # Proposals before a tool result cannot describe the final
                    # answer. Only the final, tool-free response can commit one.
                    self.metadata = None
                    self.overflow = False
                    self.completed = False
                yield chunk
        tail = self.flush()
        if tail:
            yield ProviderChunk('content', tail)

    def proposal(self):
        if self.metadata is None or self.overflow or not self.completed:
            return None
        value = self.metadata.strip()
        if not value.endswith(self.closing):
            return None
        try:
            def unique(pairs):
                result = {}
                for key, item in pairs:
                    if key in result:
                        raise ValueError('duplicate key')
                    result[key] = item
                return result
            return json.loads(value[:-len(self.closing)].strip(), object_pairs_hook=unique)
        except (ValueError, RecursionError):
            return None


def _span(quote, original, limit):
    if not isinstance(quote, str) or not quote.strip() or len(quote) > limit:
        raise ValueError('invalid excerpt')
    start = original.find(quote)
    if start < 0:
        raise ValueError('excerpt not in source')
    return {'start': start, 'end': start + len(quote)}


def _explicit_persistence(quote, user_text):
    """Conservatively require continuing language, not just a model's scope.

    This is a narrow consent boundary, not general natural-language intent
    parsing. Unclear or contradictory phrasing stays a one-turn override.
    """
    if not isinstance(quote, str) or quote not in user_text:
        return False
    continuing = re.search(r'(?:以后|今后|往后|后续|接下来|从现在(?:起|开始)).{0,16}(?:都|一直|始终|一律|持续|保持|默认)|'
                           r'(?:每次|每一?轮).{0,8}(?:都|一直)|'
                           r'\b(?:from now on|always|every (?:time|turn)|keep (?:doing|using))\b', quote, re.I)
    if not continuing:
        return False
    # A quoted example, negation, or explicit one-off constraint cannot grant
    # persistence merely because the model copied a convenient substring.
    if re.search(r'不要|别|不用|不想|不需要|不能|不再|仅|只.{0,8}(?:这次|本轮|这一轮)|(?:这次|本轮).{0,8}(?:就好|即可)|'
                 r'\b(?:not|never|don.t|only|just this)\b', user_text, re.I):
        return False
    for match in re.finditer(r'[“"「『].*?[”"」』]', user_text):
        if continuing.group() in match.group():
            return False
    return True


def complete(frozen, proposal, *, body, user_text, at):
    """Validate all fields before accepting any change. No authority from IDs
    supplied by the model: steps, attempts, and source references are Core-owned.
    """
    if not frozen or not body.strip() or not isinstance(proposal, dict):
        return None
    if set(proposal) != {'step', 'attempt', 'mode'}:
        return None
    try:
        before = frozen['before']
        after = copy.deepcopy(before)
        effective_mode = before['mode']
        mode = proposal['mode']
        mode_request = None
        if mode is not None:
            if not isinstance(mode, dict) or set(mode) != {'value', 'scope', 'quote', 'persistence_quote'}:
                return None
            if mode['value'] not in MODES or mode['scope'] not in {'turn', 'conversation'}:
                return None
            mode_request = {'mode': mode['value'], 'scope': mode['scope'], **_span(mode['quote'], user_text, 1200)}
            if mode['scope'] == 'conversation':
                if _explicit_persistence(mode['persistence_quote'], user_text):
                    mode_request['persistence'] = _span(mode['persistence_quote'], user_text, 1200)
                    after['mode'] = mode['value']
                else:
                    mode_request['scope'] = 'turn'
            elif mode['persistence_quote'] is not None:
                return None
            effective_mode = mode['value']
        step = proposal['step']
        if step is not None:
            span = _span(step, body, 240)
            if not before['step'] or before['step']['text'] != step:
                after['step'] = {'id': frozen['answer_id'], 'source_answer_id': frozen['answer_id'],
                                 'text': step, **span, 'origin': frozen['origin']}
        attempt = proposal['attempt']
        observed = None
        if attempt is not None:
            if not before['step'] or not isinstance(attempt, dict) or set(attempt) != {'quote'}:
                return None
            observed = {'message_id': frozen['message_id'], 'step_id': before['step']['id'],
                        'source': 'ai', **_span(attempt['quote'], user_text, 4000), 'origin': frozen['origin']}
        return {'after': after, 'effective_mode': effective_mode, 'mode_request': mode_request,
                'attempt': observed, 'at': at}
    except (ValueError, TypeError, KeyError):
        return None


def public(snapshot, status):
    frozen = snapshot.get('teaching')
    if not frozen or frozen.get('protocol') != PROTOCOL or (snapshot.get('source_scope') or {}).get('purged'):
        return None
    result = frozen.get('result') if status in {'complete', 'succeeded'} else None
    def visible_checkpoint(value):
        value = copy.deepcopy(value)
        if value['step']:
            value['step'].pop('origin', None)
        return value
    before = visible_checkpoint(frozen['before'])
    after = visible_checkpoint(result['after']) if result else None
    attempt = copy.deepcopy(result.get('attempt')) if result else None
    if attempt:
        attempt.pop('origin', None)
        corrections = snapshot.get('teaching_attempt_corrections', [])
        attempt.update(is_attempt=corrections[-1]['is_attempt'] if corrections else True,
                       revision=len(corrections), corrections=[{key: item[key] for key in
                            ('revision', 'is_attempt', 'at')} for item in corrections])
    return {'status': 'applied' if result else 'running' if status in {'queued', 'running', 'streaming'} else 'not_updated',
            'before': before, 'after': after, 'current': after or before,
            'effective_mode': result['effective_mode'] if result else None,
            'mode_request': {key: value for key, value in result['mode_request'].items() if key != 'persistence'}
                if result and result['mode_request'] else None,
            'attempt': attempt}


def correct(snapshot, *, expected_revision, is_attempt, request_key, at):
    """Append an annotation; never rewrite the accepted execution checkpoint."""
    if not (snapshot.get('teaching', {}).get('result') or {}).get('attempt'):
        raise ValueError('attempt_unavailable')
    corrections = snapshot.setdefault('teaching_attempt_corrections', [])
    for item in corrections:
        if item['request_key'] == request_key:
            if item['is_attempt'] != is_attempt or item['revision'] != expected_revision + 1:
                raise ValueError('attempt_revision_conflict')
            return
    if len(corrections) != expected_revision:
        raise ValueError('attempt_revision_conflict')
    corrections.append({'revision': len(corrections) + 1, 'is_attempt': is_attempt,
                        'at': at, 'request_key': request_key})


def remap(snapshot, ids):
    """Copy only local IDs on the selected ancestor path; keep original provenance."""
    frozen = snapshot.get('teaching')
    if not frozen:
        return
    def mapped(value):
        if value not in ids:
            raise ValueError('teaching_reference_outside_branch')
        return ids[value]
    frozen['answer_id'] = mapped(frozen['answer_id'])
    frozen['message_id'] = mapped(frozen['message_id'])
    for state in [frozen['before'], (frozen.get('result') or {}).get('after')]:
        if state and state.get('step'):
            step = state['step']
            step['id'] = mapped(step['id'])
            step['source_answer_id'] = mapped(step['source_answer_id'])
    for attempt in [*frozen.get('attempt_context', []), (frozen.get('result') or {}).get('attempt')]:
        if attempt:
            for key in ('message_id', 'step_id', 'answer_id'):
                if key in attempt:
                    attempt[key] = mapped(attempt[key])
