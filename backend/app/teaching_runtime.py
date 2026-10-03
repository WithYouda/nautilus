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

MODES = {'stepwise', 'socratic', 'direct_answer', 'full_explanation'}
METHODS = {'stepwise', 'socratic'}
HELP_KINDS = {'hint', 'explain_step', 'example', 'try_first'}
PROTOCOL = 'teaching-v3'
READABLE_PROTOCOLS = {'stepwise-v1', 'teaching-v2', PROTOCOL}
MAX_METADATA = 16384

SYSTEM_PROMPT = """教学执行约定：这是学习讨论，不评分，不修改正式计划或完成/掌握结论。
按本轮执行上下文中的基础方式继续；stepwise 每轮只处理一个小点、最多一次理解确认，等待用户回应；socratic 用提问引导，让用户先实际尝试。
用户明确要求直接答案或完整讲解时本轮立即遵从，默认仅本轮；只有明确要求以后持续这样才改变本路径基础方式，不能改个人长期默认。
当前步骤是待讨论的小点，不是任务完成进度；先回应用户，帮助、换例子和请求先自行尝试时留在当前步骤，确实转向一个新小点才提出新步骤。
本轮执行上下文给出唯一 opening/closing 标记。在最终回答正文结束后，另起一行输出 opening，紧接严格 JSON，再输出 closing；不得用代码块包裹，不要在正文解释这些字段。调用工具前不要输出这段状态。
JSON 格式固定为 {"step":null,"attempt":null,"mode":null,"help":null,"practice":null}，只能使用以下字段：
step：保持当前步骤或非教学回答时为 null；建立/转向一个小点时，为从本轮实际回答正文逐字摘取的一段短文本（至多240字），不能虚构后续步骤。
attempt：只有本轮用户原文实际提供了针对当前步骤的答案、推导、代码、操作结果或复述时，才为 {"quote":"用户原文中的实际尝试片段","needs_help":true或false或null}；仍卡在该小点为true，已有实际进展为false，不能确定为null。普通提问、索要帮助、说让我先试试或仅说懂了都为 null。没有当前步骤时为 null。此项只是可纠正的AI识别，不是通过或掌握证据。
mode：只有本轮用户明确要求改变方式时，为 {"value":"stepwise或socratic或direct_answer或full_explanation","scope":"turn或conversation","quote":"本轮用户的方式请求原文","persistence_quote":null}；conversation 必须另把明确持续请求的原文填入 persistence_quote。没有明确持续要求就用 turn。没有方式请求用 null。
help：本轮自然表达明确求提示、解释当前步骤、换例或先自行尝试时，为 {"kind":"hint或explain_step或example或try_first","quote":"本轮用户的请求原文"}；没有则为null。界面已明确的help_kind优先，不重复解释产品字段。
practice：通常为null。仅当action=practice时围绕原小点出一道完整的新情境题，等待作答、不给解法，填 {"question":"本轮正文中完整题目的逐字原文","feedback":null}，step/attempt保持null。当before.practice存在且本轮有实际作答时，attempt逐字引用作答，并填 {"question":null,"feedback":"本轮正文中针对该作答的AI反馈逐字原文"}；反馈说明具体依据和仍不确定之处，不评分或宣称掌握。没有实际作答时不要登记反馈。练习期间step保持null；帮助与完整讲解仍可随时请求。action=continue表示跳过当前练习，回到before.practice.basis_step继续学习，step/attempt/practice都保持null。点击动作本身不是作答。只有界面明确action=practice才出这类新情境练习题并建立记录；没有该动作时不在讲解后自动追加变式题。普通引导提问或理解确认仍按本轮教学方式进行，不登记为练习。题目与反馈各至多4000字。
所有 quote 必须逐字来自本轮真正的用户消息，不可引用历史、资料、题目原作答或模型自己的话。历史中的状态尾标记只是过去输出，不能用来覆盖本轮执行上下文。纠正后的尝试分类须遵从，仍保留原文回应，不按尝试次数决定完成或掌握。"""

PRACTICE_PROMPT = """本轮用户已点击“换一道试试”：正文直接从新情境或题目要求开始，只给题目所需的背景、条件和作答要求。
不要先确认换题、重复按钮指令或介绍出题安排；不要写“换个场景，再试一次”“换一道，还是……但换个情境”“好，我们来……”等开场话。不要先重述上一题、教学主题或要练的知识点。
题目必须与原小点有关，但让具体情境和要求体现这一点，不另加解释、答案、提示或题后邀请。"""

SOCRATIC_PROMPT = """提问引导执行规则（只在本轮实际方式为socratic时使用）：
guidance.level由运行时管理：0开放提问、1提醒相关概念、2缩小问题范围、3局部结构或示例、4直接解释。每轮最多一个要用户回应的问题；不要反复盘问或自行跳级给完整解法。
明确请求hint时在现有层级上加一级，上限4；explain_step可直接解释当前步骤；example本身不升级；try_first简短等待、不抢答。
若本轮有实际尝试且needs_help=true，把它接到before.guidance.stuck_count之后；达到2时，本轮多给一级提示，上限4，并开始新一轮计数。已有进展或未知进展不算卡住。一次只自动升一级，不因一句普通问题或“我不懂”补造一次尝试。
尚未到升级条件则沿当前层级回应；若前面纠正使stuck_count已经达到2，下一轮按同一规则多给一级。明确请求优先，不同时自动再升一级。
仍卡住、求提示、换例或先自行尝试时保持step=null，不通过重命名小点逃过阶梯。确实转向新的小点才逐字摘取新小点，新小点从开放提问开始。
用户要求直接答案或完整讲解时立即遵从；下一轮回到基础方式。解释后可邀请用户选择“换一道试试”，仅在action=practice时出可选变式题；不自动追加变式题或开始正式验证，不把步骤推进当作掌握。
模型只报告有原文的尝试/请求，不得输出级别、计数、评分或完成字段；Runtime独立计算并保存状态。"""


def checkpoint():
    return {'mode': 'stepwise', 'step': None}


def _new_guidance(reset_answer_id=None):
    return {'level': 0, 'stuck_count': 0, 'reset_answer_id': reset_answer_id}


def _recount(path, before):
    """Re-read corrected observations, without undoing help already arranged.

    The reset answer excludes observations before a real level/step reset.
    Corrections never rewrite an old run's frozen checkpoint or output.
    """
    guide = before.get('guidance')
    if before['mode'] != 'socratic' or not guide or not before['step']:
        return
    active = guide['reset_answer_id'] is None
    count = 0
    for item in path:
        if item['id'] == guide['reset_answer_id']:
            active = True
            continue
        if not active:
            continue
        record = item.get('teaching') or {}
        attempt = record.get('attempt')
        if (not attempt or not attempt.get('is_attempt')
                or attempt['step_id'] != before['step']['id']):
            continue
        count = count + 1 if attempt.get('needs_help') is True else 0
    guide['stuck_count'] = count


def freeze(path, *, answer_id, message_id, kind, scope_id, requested_mode=None, help_kind=None, action=None):
    """Path has already passed the caller's material/ownership boundary."""
    before = checkpoint()
    if path and path[-1].get('teaching'):
        before = copy.deepcopy(path[-1]['teaching']['current'])
    allowed_answers = {item['id'] for item in path}
    if before['step'] and before['step']['source_answer_id'] not in allowed_answers:
        before['step'] = None
        if before.get('guidance'):
            before['guidance'] = _new_guidance()
    practice = before.get('practice')
    if practice:
        references = {practice['id'], practice['question']['answer_id'],
                      practice['basis_step']['id'], practice['basis_step']['source_answer_id']}
        for reference in (practice.get('last_observation_id'),
                          (practice.get('return_guidance') or {}).get('reset_answer_id')):
            if reference:
                references.add(reference)
        if not references <= allowed_answers:
            before['practice'] = None
            before['step'] = None
            before['guidance'] = _new_guidance() if before['mode'] == 'socratic' else None
        else:
            resume = {'mode': before['mode'], 'step': practice['basis_step'],
                      'guidance': practice.get('return_guidance')}
            _recount(path, resume)
    _recount(path, before)
    if requested_mode is not None:
        if requested_mode not in METHODS:
            raise ValueError('invalid_teaching_mode')
        if requested_mode != before['mode']:
            before['guidance'] = _new_guidance(path[-1]['id'] if path else None) if requested_mode == 'socratic' else None
            if before.get('practice'):
                before['practice']['return_guidance'] = copy.deepcopy(before['guidance'])
        before['mode'] = requested_mode
    if before['mode'] == 'socratic' and not before.get('guidance'):
        before['guidance'] = _new_guidance(path[-1]['id'] if path else None)
    observations = []
    for item in path:
        attempt = (item.get('teaching') or {}).get('attempt')
        if attempt and attempt['step_id'] in allowed_answers:
            observations.append({key: attempt[key] for key in
                                 ('message_id', 'step_id', 'is_attempt', 'revision', 'start', 'end')}
                                | {'answer_id': item['id'], 'needs_help': attempt.get('needs_help')})
    return {'protocol': PROTOCOL, 'token': uuid4().hex, 'before': before,
            'answer_id': answer_id, 'message_id': message_id,
            'parent_answer_id': path[-1]['id'] if path else None,
            'origin': {'kind': kind, 'scope_id': scope_id, 'answer_id': answer_id, 'message_id': message_id},
            'attempt_context': observations, 'requested_mode': requested_mode, 'help_kind': help_kind,
            'action': action, 'help_context': [
                {'answer_id': item['id'], **copy.deepcopy(item['help_record'])}
                for item in path if (item.get('help_record') or {}).get('provided')]
            if before.get('practice') else []}


def markers(frozen):
    return '<nautilus_teaching_' + frozen['token'] + '>', '</nautilus_teaching_' + frozen['token'] + '>'


def add_prompt(messages, frozen, attempt_texts=None, answer_texts=None):
    messages = copy.deepcopy(messages)
    messages[0]['content'] += '\n' + SYSTEM_PROMPT + '\n' + SOCRATIC_PROMPT
    if frozen.get('action') == 'practice':
        messages[0]['content'] += '\n' + PRACTICE_PROMPT
    opening, closing = markers(frozen)
    # Dynamic context follows native protocol history. Do not rewrite signed
    # thinking blocks or insert per-turn nonces into the system prefix.
    observations = copy.deepcopy(frozen['attempt_context'])
    for observation in observations:
        original = (attempt_texts or {}).get(observation['message_id'], '')
        observation['quote'] = original[observation['start']:observation['end']]
    practice_context = None
    practice = frozen['before'].get('practice')
    if practice:
        reference = practice['question']
        original = (answer_texts or {}).get(reference['answer_id'], '')
        practice_context = {'question': original[reference['start']:reference['end']]}
    messages.insert(len(messages) - 1, {'role': 'user', '_teaching_runtime': True, 'content':
        'Nautilus 本轮执行上下文（下一条才是本轮用户原文）：\n' + json.dumps({
            'before': frozen['before'], 'attempt_context': observations, 'help_kind': frozen.get('help_kind'),
            'action': frozen.get('action'), 'practice_context': practice_context,
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
        self.not_applied_reason = None

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
        self.not_applied_reason = None
        if not self.completed:
            self.not_applied_reason = 'completion_unknown'
            return None
        if self.metadata is None:
            self.not_applied_reason = 'trailer_missing'
            return None
        if self.overflow:
            self.not_applied_reason = 'trailer_oversized'
            return None
        value = self.metadata.strip()
        if not value.endswith(self.closing):
            self.not_applied_reason = 'trailer_unclosed'
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
            self.not_applied_reason = 'trailer_invalid_json'
            return None

    def outcome(self):
        proposal = self.proposal()
        return {'teaching_proposal': proposal, 'teaching_not_applied_reason': self.not_applied_reason}


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


def _guidance(frozen, after, effective_mode, help_kind, observed):
    """Core owns the ladder. The model supplies only source-bound observations.

    This records the arranged help, not a semantic claim about the actual body.
    Actual help remains the existing reply/display fact, including partial help.
    """
    before = frozen['before']
    answer_id = frozen['answer_id']
    changed_step = before['step'] != after['step']
    previous = copy.deepcopy(before.get('guidance') or _new_guidance())
    if after['mode'] != before['mode']:
        after['guidance'] = _new_guidance(answer_id) if after['mode'] == 'socratic' else None
        if after.get('practice'):
            after['practice']['return_guidance'] = copy.deepcopy(after['guidance'])
    if effective_mode != 'socratic':
        if after['mode'] == 'socratic':
            after['guidance'] = _new_guidance(answer_id) if changed_step else {
                **previous, 'stuck_count': 0, 'reset_answer_id': answer_id}
        return {'level': 4, 'reason': 'direct_explanation'} if effective_mode in {
            'direct_answer', 'full_explanation'} and before['mode'] == 'socratic' else None

    # A natural-language switch and an explicit selector choice start at the
    # same parent boundary; the current real attempt must survive recounting.
    guide = previous if before['mode'] == 'socratic' else _new_guidance(frozen.get('parent_answer_id'))
    level, count = guide['level'], guide['stuck_count']
    reason = 'initial' if not before['step'] else 'continue'
    if observed:
        count = count + 1 if observed.get('needs_help') is True else 0
    if help_kind == 'hint':
        level, count, reason = min(4, level + 1), 0, 'requested_hint'
        guide['reset_answer_id'] = answer_id
    elif help_kind == 'explain_step':
        level, count, reason = 4, 0, 'direct_explanation'
        guide['reset_answer_id'] = answer_id
    elif help_kind in {'example', 'try_first'}:
        reason = help_kind
    elif count >= 2:
        level, count, reason = min(4, level + 1), 0, 'repeated_difficulty'
        guide['reset_answer_id'] = answer_id
    if changed_step:
        # A first explicit hint may establish its topic at H1. A genuinely new
        # small point after an existing one starts with an open question.
        if before['step']:
            level, reason = 0, 'initial'
        count = 0
        guide['reset_answer_id'] = answer_id
    if after['mode'] == 'socratic':
        after['guidance'] = {**guide, 'level': level, 'stuck_count': count}
    return {'level': level, 'reason': reason}


class _InvalidProposal(ValueError):
    pass


def _practice_transition(frozen, proposal, after, observed, body):
    """Keep question, original point and feedback tied to actual answer versions."""
    before = frozen['before']
    active = before.get('practice')
    action = frozen.get('action')
    proposed = proposal.get('practice')
    if proposed is not None and (not isinstance(proposed, dict) or set(proposed) != {'question', 'feedback'}):
        raise _InvalidProposal('proposal_invalid_schema')
    if action is not None and observed is not None:
        raise _InvalidProposal('action_is_not_attempt')
    if (active or action) and proposal['step'] is not None:
        raise _InvalidProposal('practice_step_changed')
    if action == 'practice':
        if not before['step'] or not proposed or proposed['feedback'] is not None:
            raise _InvalidProposal('practice_question_required')
        span = _span(proposed['question'], body, 4000)
        frame = {'id': frozen['answer_id'],
                 'basis_step': copy.deepcopy(active['basis_step'] if active else before['step']),
                 'return_guidance': copy.deepcopy(active.get('return_guidance') if active else before.get('guidance')),
                 'question': {'answer_id': frozen['answer_id'], **span},
                 'phase': 'awaiting_attempt', 'last_observation_id': None}
        after['practice'] = frame
        after['step'] = {'id': frozen['answer_id'], 'source_answer_id': frozen['answer_id'],
                         'text': proposed['question'][:240], 'start': span['start'],
                         'end': span['start'] + min(240, span['end'] - span['start']), 'origin': frozen['origin']}
        return copy.deepcopy(frame), None, frozen
    if action == 'continue':
        if not active or proposed is not None:
            raise _InvalidProposal('practice_unavailable')
        after['step'] = copy.deepcopy(active['basis_step'])
        after['guidance'] = copy.deepcopy(active.get('return_guidance'))
        after['practice'] = None
        resume = {**before, 'step': after['step'], 'guidance': after['guidance'], 'practice': None}
        return None, None, {**frozen, 'before': resume}
    if action is not None:
        raise _InvalidProposal('proposal_invalid_schema')
    if active and observed:
        if not proposed or proposed['question'] is not None:
            raise _InvalidProposal('practice_feedback_required')
        span = _span(proposed['feedback'], body, 4000)
        observation = {'question_id': active['id'], 'message_id': frozen['message_id'],
                       'start': observed['start'], 'end': observed['end'], 'answer_id': frozen['answer_id'],
                       'feedback_start': span['start'], 'feedback_end': span['end'],
                       'help_context': copy.deepcopy(frozen.get('help_context', []))}
        after['practice']['phase'] = 'feedback_available'
        after['practice']['last_observation_id'] = frozen['answer_id']
        return None, observation, frozen
    if proposed is not None:
        raise _InvalidProposal('practice_without_action_or_attempt')
    return None, None, frozen


def evaluate(frozen, proposal, *, body, user_text, at):
    """Validate before adopting any model change; return a private reason enum."""
    if not body.strip():
        return None, 'empty_body'
    if (not frozen or not isinstance(proposal, dict)
            or not {'step', 'attempt', 'mode'} <= set(proposal)
            or not set(proposal) <= {'step', 'attempt', 'mode', 'help', 'practice'}):
        return None, 'proposal_invalid_schema'
    try:
        before = frozen['before']
        after = copy.deepcopy(before)
        effective_mode = before['mode']
        mode = proposal['mode']
        mode_request = None
        if mode is not None:
            if not isinstance(mode, dict) or set(mode) != {'value', 'scope', 'quote', 'persistence_quote'}:
                raise _InvalidProposal('proposal_invalid_schema')
            if mode['value'] not in MODES or mode['scope'] not in {'turn', 'conversation'}:
                raise _InvalidProposal('proposal_invalid_schema')
            mode_request = {'mode': mode['value'], 'scope': mode['scope'], **_span(mode['quote'], user_text, 1200)}
            if mode['scope'] == 'conversation':
                if _explicit_persistence(mode['persistence_quote'], user_text):
                    mode_request['persistence'] = _span(mode['persistence_quote'], user_text, 1200)
                    after['mode'] = mode['value']
                else:
                    mode_request['scope'] = 'turn'
            elif mode['persistence_quote'] is not None:
                raise _InvalidProposal('proposal_invalid_schema')
            effective_mode = mode['value']
        help_kind = frozen.get('help_kind')
        help_request = None
        proposed_help = proposal.get('help')
        if proposed_help is not None:
            if (not isinstance(proposed_help, dict) or set(proposed_help) != {'kind', 'quote'}
                    or proposed_help['kind'] not in HELP_KINDS):
                raise _InvalidProposal('proposal_invalid_schema')
            help_request = {'kind': proposed_help['kind'], **_span(proposed_help['quote'], user_text, 1200)}
            if not help_kind:
                help_kind = proposed_help['kind']
        step = proposal['step']
        if step is not None:
            span = _span(step, body, 240)
            if not before['step'] or before['step']['text'] != step:
                after['step'] = {'id': frozen['answer_id'], 'source_answer_id': frozen['answer_id'],
                                 'text': step, **span, 'origin': frozen['origin']}
        attempt = proposal['attempt']
        observed = None
        if attempt is not None:
            if not before['step']:
                raise _InvalidProposal('attempt_without_step')
            if (not isinstance(attempt, dict) or set(attempt) not in ({'quote'}, {'quote', 'needs_help'})
                    or (attempt.get('needs_help') is not None and type(attempt['needs_help']) is not bool)):
                raise _InvalidProposal('proposal_invalid_schema')
            observed = {'message_id': frozen['message_id'], 'step_id': before['step']['id'],
                        'source': 'ai', **_span(attempt['quote'], user_text, 4000), 'origin': frozen['origin'],
                        'needs_help': attempt.get('needs_help')}
        practice_question, practice_observation, guidance_frozen = _practice_transition(
            frozen, proposal, after, observed, body)
        if (not frozen.get('action') and effective_mode == 'socratic' and before['step'] and before['step'] != after['step']
                and (help_kind in HELP_KINDS or observed and observed['needs_help'] is True)):
            raise _InvalidProposal('step_changed_while_waiting')
        guidance = _guidance(guidance_frozen, after, effective_mode, help_kind, observed)
        return {'after': after, 'effective_mode': effective_mode, 'mode_request': mode_request,
                'attempt': observed, 'guidance': guidance, 'help_request': help_request, 'at': at,
                'practice_question': practice_question, 'practice_observation': practice_observation}, None
    except _InvalidProposal as error:
        return None, str(error)
    except ValueError:
        return None, 'quote_mismatch'
    except (TypeError, KeyError):
        return None, 'proposal_invalid_schema'


def complete(frozen, proposal, *, body, user_text, at):
    return evaluate(frozen, proposal, body=body, user_text=user_text, at=at)[0]


def adopt(frozen, proposal, *, body, user_text, at, not_applied_reason=None):
    """Called only inside the existing successful-answer save transaction."""
    result, reason = evaluate(frozen, proposal, body=body, user_text=user_text, at=at)
    if result:
        frozen['result'] = result
        frozen.pop('not_applied_reason', None)
    else:
        frozen['not_applied_reason'] = not_applied_reason or reason


def public(snapshot, status):
    frozen = snapshot.get('teaching')
    if not frozen or frozen.get('protocol') not in READABLE_PROTOCOLS or (snapshot.get('source_scope') or {}).get('purged'):
        return None
    result = frozen.get('result') if status in {'complete', 'succeeded'} else None
    def visible_practice(value):
        value = copy.deepcopy(value)
        if value and value.get('basis_step'):
            value['basis_step'].pop('origin', None)
        return value
    def visible_checkpoint(value):
        value = copy.deepcopy(value)
        if value['step']:
            value['step'].pop('origin', None)
        if value.get('practice'):
            value['practice'] = visible_practice(value['practice'])
        return value
    before = visible_checkpoint(frozen['before'])
    after = visible_checkpoint(result['after']) if result else None
    attempt = copy.deepcopy(result.get('attempt')) if result else None
    if attempt:
        attempt.pop('origin', None)
        corrections = snapshot.get('teaching_attempt_corrections', [])
        needs_help = attempt.get('needs_help')
        for correction in corrections:
            if 'needs_help' in correction:
                needs_help = correction['needs_help']
        attempt.update(is_attempt=corrections[-1]['is_attempt'] if corrections else True,
                       needs_help=needs_help, revision=len(corrections), corrections=[{key: item[key] for key in
                            ('revision', 'is_attempt', 'at', 'needs_help') if key in item} for item in corrections])
    observation = copy.deepcopy(result.get('practice_observation')) if result else None
    if observation:
        observation.update(eligible=bool(attempt and attempt['is_attempt']),
                           needs_help=attempt.get('needs_help') if attempt else None)
    return {'status': 'applied' if result else 'running' if status in {'queued', 'running', 'streaming'} else 'not_updated',
            'before': before, 'after': after, 'current': after or before,
            'effective_mode': result['effective_mode'] if result else None,
            'mode_request': {key: value for key, value in result['mode_request'].items() if key != 'persistence'}
                if result and result['mode_request'] else None,
            'attempt': attempt, 'requested_mode': frozen.get('requested_mode'),
            'guidance': result.get('guidance') if result else None,
            'requested_action': frozen.get('action'),
            'practice_question': visible_practice(result.get('practice_question')) if result else None,
            'practice_observation': observation}


_UNSET = object()


def correct(snapshot, *, expected_revision, is_attempt, request_key, at, needs_help=_UNSET):
    """Append an annotation; never rewrite the accepted execution checkpoint."""
    if not (snapshot.get('teaching', {}).get('result') or {}).get('attempt'):
        raise ValueError('attempt_unavailable')
    corrections = snapshot.setdefault('teaching_attempt_corrections', [])
    for item in corrections:
        if item['request_key'] == request_key:
            if (item['is_attempt'] != is_attempt or item['revision'] != expected_revision + 1
                    or item.get('needs_help', _UNSET) != needs_help):
                raise ValueError('attempt_revision_conflict')
            return
    if len(corrections) != expected_revision:
        raise ValueError('attempt_revision_conflict')
    corrections.append({'revision': len(corrections) + 1, 'is_attempt': is_attempt,
                        'at': at, 'request_key': request_key,
                        **({'needs_help': needs_help} if needs_help is not _UNSET else {})})


def remap(snapshot, ids):
    """Copy only local IDs on the selected ancestor path; keep original provenance."""
    frozen = snapshot.get('teaching')
    if not frozen:
        return
    def mapped(value):
        if value not in ids:
            raise ValueError('teaching_reference_outside_branch')
        return ids[value]
    def map_step(step):
        if step:
            step['id'] = mapped(step['id'])
            step['source_answer_id'] = mapped(step['source_answer_id'])
    def map_guidance(guide):
        if guide and guide.get('reset_answer_id'):
            guide['reset_answer_id'] = mapped(guide['reset_answer_id'])
    def map_practice(practice):
        if practice:
            practice['id'] = mapped(practice['id'])
            practice['question']['answer_id'] = mapped(practice['question']['answer_id'])
            map_step(practice['basis_step'])
            map_guidance(practice.get('return_guidance'))
            if practice.get('last_observation_id'):
                practice['last_observation_id'] = mapped(practice['last_observation_id'])
    frozen['answer_id'] = mapped(frozen['answer_id'])
    frozen['message_id'] = mapped(frozen['message_id'])
    if frozen.get('parent_answer_id'):
        frozen['parent_answer_id'] = mapped(frozen['parent_answer_id'])
    for state in [frozen['before'], (frozen.get('result') or {}).get('after')]:
        if state:
            map_step(state.get('step'))
            map_guidance(state.get('guidance'))
            map_practice(state.get('practice'))
    result = frozen.get('result') or {}
    map_practice(result.get('practice_question'))
    observation = result.get('practice_observation')
    if observation:
        for key in ('question_id', 'message_id', 'answer_id'):
            observation[key] = mapped(observation[key])
    for context in [frozen.get('help_context', []), (observation or {}).get('help_context', [])]:
        for item in context:
            item['answer_id'] = mapped(item['answer_id'])
    for attempt in [*frozen.get('attempt_context', []), (frozen.get('result') or {}).get('attempt')]:
        if attempt:
            for key in ('message_id', 'step_id', 'answer_id'):
                if key in attempt:
                    attempt[key] = mapped(attempt[key])
