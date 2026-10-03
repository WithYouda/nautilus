#!/usr/bin/env python3
"""Playwright 专用 OpenAI-compatible Mock HTTP/SSE 服务。

只处理测试中的假数据；不会记录 Authorization、API key、请求正文或用户内容。
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


SUCCESS_CHUNKS = [
    "## 学习步骤\n\n",
    "1. 先明确目标。\n2. 再拆成步骤。\n\n",
    "| 检查项 | 方法 |\n| --- | --- |\n| 理解 | 用例题检查 |\n\n`完成`",
]
REFRESH_CHUNKS = [f"刷新块 {index}。" for index in range(1, 13)]
SLOW_CHUNKS = [f"慢速块 {index}。" for index in range(1, 61)]
MATH_TEXT = (
    "## 合成公式讲解\n\n行内 $x^2$ 与 \\(y^2\\)。\n\n"
    "$$\n\\frac{1}{2}\n$$\n\n\\[\\sum_{i=1}^{n} i\\]\n\n"
    "`\\(literal_code\\)`\n\n```text\n\\[literal_block\\]\n```\n\n"
    "$$\\underbrace{a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a+a}_{n}$$"
)


def teaching_chunks(body: list[str], proposal: dict[str, Any], context: dict[str, Any]) -> list[str]:
    proposal = {key: proposal.get(key) for key in ('step', 'attempt', 'mode', 'help', 'practice', 'project', 'adaptation')}
    proposal['adaptation'] = context.get('_mock_adaptation', proposal['adaptation'])
    if context.get('output_format') == 'json':
        chunks = ['{"reply":"', *(json.dumps(piece, ensure_ascii=False)[1:-1] for piece in body)]
        metadata = ',"teaching":' + json.dumps(proposal, ensure_ascii=False) + ',"token":' + json.dumps(context['token']) + '}'
        return [*chunks, '"', *(metadata[index:index + 17] for index in range(0, len(metadata), 17))]
    trailer = '\n' + context['opening'] + json.dumps(proposal, ensure_ascii=False) + context['closing']
    return [*body, *(trailer[index:index + 17] for index in range(0, len(trailer), 17))]


def adaptive_proposal(context: dict[str, Any], user_text: str, requested_mode: dict[str, Any] | None,
                      requested_help: dict[str, Any] | None) -> dict[str, Any] | None:
    """Synthetic teaching choice and traced preference, within the same streamed reply."""
    before = context['before']
    if before.get('policy') != 'adaptive':
        return None
    profile = context.get('adaptive_profile', {'rules': [], 'suppressed': []})
    scenario = ('project' if '[ADAPT项目]' in user_text or '[C2项目' in user_text
                else 'problem_solving' if '[ADAPT练习]' in user_text or '[C2练习' in user_text
                else 'coding' if '写代码' in user_text else 'concepts')
    rules = profile.get('rules', [])
    rule = next((item for item in rules if item['configuration']['scenario'] == scenario), None)
    rule = rule or next((item for item in rules if item['configuration']['scenario'] == 'general'), None)
    locked = bool(context.get('action') or context.get('help_kind') or requested_help
                  or any(before.get(key) for key in ('exercise', 'project', 'practice', 'retelling'))
                  or any(marker in user_text for marker in ('[C2尝试]', '[C2卡住]', '[C2复述作答]')))
    explicit = (requested_mode or {}).get('value')
    method = (explicit if explicit and explicit != 'adaptive' else before['mode'] if locked
              else rule['configuration']['method'] if rule
              else 'project' if scenario == 'project' else 'practice_first' if scenario == 'problem_solving'
              else 'stepwise')
    draft = None
    if '[ADAPT偏好]' in user_text:
        one_hint = '一次给一个提示' in user_text
        draft = dict(scenario='concepts', method='socratic', start='try_first',
                     help='one_hint' if one_hint else 'explain_when_stuck', quote=user_text,
                     reason='你明确希望理解概念时先自己试、一次接收一个提示。' if one_hint
                     else '你明确希望理解概念时先自己试、卡住时再听讲解。')
    elif '[ADAPT忽略]' in user_text:
        draft = dict(scenario='coding', method='stepwise', start='example_first', help='one_hint',
                     quote=user_text, reason='你明确提出写代码时先看例子、一次只接收一个提示。')
    if draft and {key: draft[key] for key in ('scenario', 'method', 'start', 'help')} in profile.get('suppressed', []):
        draft = None
    # The mock dispatch needs the chosen method to generate its real activity;
    # this local context is not the server's saved checkpoint.
    before['mode'] = method if not explicit or explicit == 'adaptive' else before['mode']
    return dict(method=method, reason='继续当前活动。' if locked else '参考已确认的个人偏好。' if rule else '按当前任务安排学习方式。',
                rule_id=rule['id'] if rule and not explicit and (not locked or rule['configuration']['method'] == method) else None, draft=draft)


class MockState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: Counter[str] = Counter()
        self.delivered: Counter[str] = Counter()
        self.disconnects: Counter[str] = Counter()
        self.teaching_check_failures = 0

    def reset(self) -> None:
        with self._lock:
            self.requests.clear()
            self.delivered.clear()
            self.disconnects.clear()
            self.teaching_check_failures = 0

    def fail_teaching_checks(self) -> None:
        with self._lock:
            self.teaching_check_failures = 2

    def reject_teaching_check(self) -> bool:
        with self._lock:
            if self.teaching_check_failures:
                self.teaching_check_failures -= 1
                return True
            return False

    def requested(self, scenario: str) -> None:
        with self._lock:
            self.requests[scenario] += 1

    def chunk_delivered(self, scenario: str) -> None:
        with self._lock:
            self.delivered[scenario] += 1

    def disconnected(self, scenario: str) -> None:
        with self._lock:
            self.disconnects[scenario] += 1

    def snapshot(self) -> dict[str, dict[str, int]]:
        with self._lock:
            return {
                "requests": dict(self.requests),
                "delivered": dict(self.delivered),
                "disconnects": dict(self.disconnects),
            }


STATE = MockState()


class MockOpenAIHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: Any) -> None:
        # 严禁把 Authorization、请求正文或测试假密钥写入日志。
        return

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.startswith('/search?'):
            STATE.requested('outbound-search')
            self._json(200, {'results': [{'title': '合成公开来源', 'url': 'https://example.com/outbound-proof', 'content': '合成检索响应，仅用于隔离验证。'}]})
            return
        if self.path == "/health":
            self._json(200, {"status": "ok"})
            return
        if self.path == "/__mock__/stats":
            self._json(200, STATE.snapshot())
            return
        if self.path.endswith("/models"):
            if not self.headers.get("Authorization", "").startswith("Bearer "):
                self._json(401, {"error": {"message": "missing API key"}})
                return
            STATE.requested("models")
            self._json(
                200,
                {
                    "data": [
                        {"id": "mock-success"},
                        {"id": "mock-reasoning"},
                        {"id": "mock-refresh"},
                        {"id": "mock-slow"},
                        {"id": "mock-evidence"},
                        {"id": "mock-error"},
                        {"id": "mock-unsupported"},
                    ]
                },
            )
            return
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/__mock__/reset":
            STATE.reset()
            self._json(200, {"ok": True})
            return
        if self.path == "/__mock__/teaching-check/fail-next":
            STATE.fail_teaching_checks()
            self._json(200, {"ok": True})
            return
        if not self.path.endswith("/chat/completions"):
            self._json(404, {"error": {"message": "not found"}})
            return

        payload = self._read_json()
        if payload is None:
            self._json(400, {"error": {"message": "invalid json"}})
            return
        if not self.headers.get("Authorization", "").startswith("Bearer "):
            self._json(401, {"error": {"message": "missing API key"}})
            return

        model = str(payload.get("model", "mock-success"))
        capability_check = any(message.get('role') == 'system' and '这是一次应用能力检查' in str(message.get('content', ''))
                               for message in payload.get('messages', []))
        if capability_check:
            STATE.requested('teaching-check:tools' if payload.get('tools') else 'teaching-check:plain')
            if STATE.reject_teaching_check():
                self._json(401, {"error": {"message": "Synthetic temporary teaching-check rejection"}})
                return
        scenario = model if model in {"mock-success", "mock-reasoning", "mock-refresh", "mock-slow", "mock-evidence", "mock-error", "mock-math", "mock-review", "mock-search-tools", "mock-process-tools", "mock-knowledge-tools"} else "mock-success"
        is_title_request = payload.get("stream") is not True and int(payload.get("max_tokens") or 0) >= 256
        STATE.requested(f"title:{scenario}" if is_title_request else scenario)

        if scenario == "mock-error":
            self._json(401, {"error": {"message": "Mock provider rejected the API key"}})
            return
        if payload.get("stream") is not True:
            prompt = " ".join(str(message.get('content', '')) for message in payload.get('messages', []))
            if 'output_schema' in prompt and 'goal_title' in prompt:
                content = json.dumps(dict(goal_title='解释一个日志匹配', goal_description='合成学习目标',
                    plan_title='一次小练习', plan_description='合成学习安排', action_title='解释日志样例',
                    context_key='synthetic-continuity', outcome_object='日志样例', outcome_behavior='解释匹配过程',
                    outcome_context_key='synthetic-continuity', boundaries='仅一份样例',
                    stop_conditions='写出自己的判断与过程', time_budget_minutes=15,
                    recommended_criterion_id=None, rationale='先完成一个可观察的小步骤'), ensure_ascii=False)
            elif '"purpose":"practice_' in prompt or '"purpose": "practice_' in prompt:
                context = json.loads(payload['messages'][-1]['content'])
                purpose = context['purpose']
                if purpose == 'practice_hint':
                    result = dict(text='合成补练提示：先单独检查输入边界。')
                elif purpose == 'practice_evaluation':
                    result = dict(assessment='meets', feedback='合成补练反馈：这次已说明边界处理。',
                        answer_quote=context['answer'][:30], remaining=[], next_step='可以暂不继续。')
                else:
                    basis = [dict(source='answer', quote=context['source']['answer'][:30])]
                    result = dict(review=dict(status='corrected' if purpose == 'practice_recheck' else 'supported',
                        summary='合成复核：按原题范围判断，不增加要求。', basis=basis), exercise=None)
                    if purpose == 'practice_exercise':
                        prompt_text = ('合成补练：换为两个编号时，怎样检查边界？' if context.get('avoid_repeating_prompt')
                                       else '合成补练：输入只包含一个编号时，怎样检查边界？')
                        result['exercise'] = dict(kind=context['request']['requested_kind'], focus='optional', reason='合成理由：沿用原题的边界判断。',
                            basis=basis, prompt=context['source']['question'] if context['request']['requested_kind'] == 'redo' else prompt_text,
                            answer_guidance='SYNTHETIC_PRIVATE_PRACTICE_GUIDANCE')
                content = json.dumps(result, ensure_ascii=False)
            elif 'completion_material_review' in prompt:
                content = json.dumps(dict(summary='合成审查：仅能确认材料报告的内容',
                    findings=[dict(kind='insufficient', quote='', comment='没有题目和评分依据，无法判断具体能力。')],
                    limitations='未核验材料真伪、本人独立完成或机构记录。', next_step='可选择补充题目；不影响已记录的完成。'), ensure_ascii=False)
            elif '你为Nautilus整理学习位置' in prompt:
                content = json.dumps(dict(current='正在讨论如何定位日志编号，尚未验证理解。',
                    next='可以解释一次自己的判断过程。'), ensure_ascii=False)
            elif '评估本次作答' in prompt:
                evaluation_prompt = json.loads(payload['messages'][-1]['content'])
                question_ids = [q['id'] for q in evaluation_prompt['questions']]
                content = json.dumps(dict(passed=True, stop_condition_met=True,
                    feedback=r'合成评估：本次说明符合当前任务要求。\(x^2\) 与 $\frac{1}{2}$。' if scenario == 'mock-math' else '合成评估：本次说明符合当前任务要求。', next_step='再观察不同输入。',
                    question_feedback=[dict(question_id=qid, feedback='合成逐题反馈：已说明过程和未知。' if qid != 'q2' else '第二题反馈：应单独检查空输入，不能据此泛化。', reference_answer='合成参考解法：先定位，再检查边界。', follow_up_questions=['换一个输入时，你会怎样检查？'], unmet_requirements=[]) for qid in question_ids]), ensure_ascii=False)
            elif '为题目讨论决定是否查阅' in prompt:
                content = '{"history_query":"合成"}'
            elif '你在 Nautilus 题目学习室中' in prompt:
                content = '合成续学讲解：可以继续分析不同输入；此前的记录见[记录1]。'
            elif '验证设计助手' in prompt:
                content = json.dumps(dict(questions=[dict(id='q1', type='short_response',
                    prompt=MATH_TEXT if scenario == 'mock-math' else '解释合成样例中如何定位一个编号，并说明一个未知情况。', source_urls=[],
                    pass_criteria='说明过程与未知', answer_key='通过说明边界判断本次表现')] + ([dict(id='q2', type='short_response', prompt='第二题：请说明空输入的处理。', source_urls=[], pass_criteria='说明边界', answer_key='检查空输入')] if scenario == 'mock-review' else [])), ensure_ascii=False)
            elif scenario == "mock-evidence":
                content = json.dumps(
                    {
                        "dimension_id": "syntax_semantics",
                        "stance": "supports",
                        "statement": "语义分析确认产出说明了正则表达式的匹配语义。",
                        "scope": "artifact",
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            else:
                content = "学习步骤与目标拆解" if is_title_request else "pong"
            self._json(
                200,
                {
                    "model": model,
                    "choices": [{"message": {"role": "assistant", "content": content}}],
                },
            )
            return

        chunks, delay = self._scenario_stream(scenario)
        discussion_stream = any('你在 Nautilus 题目学习室中' in str(message.get('content', '')) for message in payload.get('messages', []))
        if discussion_stream:
            chunks = ['合成续学讲解：', '可以继续分析不同输入；', '此前的记录见[记录1]。']
            delay = 0.8
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            messages = payload.get("messages", [])
            last_user = max((i for i, message in enumerate(messages) if message.get("role") == "user"), default=-1)
            if capability_check:
                result = str(messages[last_user]['content']) if model != 'mock-unsupported' else '合成普通回答。'
                for index in range(0, len(result), 7):
                    event = json.dumps({"choices": [{"delta": {"content": result[index:index + 7]}}]}, ensure_ascii=False)
                    self.wfile.write(f'data: {event}\n\n'.encode())
                    self.wfile.flush()
                    time.sleep(.002)
                self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
                self.wfile.flush()
                return
            has_result = any(message.get("role") == "tool" for message in messages[last_user + 1:])
            if scenario == "mock-knowledge-tools":
                results = [message for message in messages[last_user + 1:] if message.get("role") == "tool"]
                available = {tool.get("function", {}).get("name") for tool in payload.get("tools", [])}
                name = None
                arguments = {}
                if "search_knowledge_base" in available and not results:
                    name = "search_knowledge_base"
                    arguments = {"query": "KNOWLEDGE_B2_MARKER"}
                elif "read_knowledge_note" in available and len(results) == 1:
                    result = json.loads(results[0].get("content", "{}"))
                    items = result.get("items", [])
                    if items:
                        name = "read_knowledge_note"
                        arguments = {"version_id": items[0]["version_id"], "start_line": 1,
                                     "end_line": min(items[0]["total_lines"], 80)}
                if name and payload.get("tool_choice") != "none":
                    call = {"index": 0, "id": f"mock-knowledge-{len(results)}", "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)}}
                    self.wfile.write(('data: ' + json.dumps({"choices": [{"delta": {"tool_calls": [call]}, "finish_reason": "tool_calls"}]}) + '\n\ndata: [DONE]\n\n').encode())
                    self.wfile.flush()
                    return
                marker = ""
                if results:
                    result = json.loads(results[0].get("content", "{}"))
                    if result.get("items"):
                        marker = result["items"][0]["marker"]
                chunks = [f"本次依据知识库保存证据解释合成笔记 {marker}。"]
                delay = 0.1
            if scenario == "mock-process-tools":
                results = [message for message in messages[last_user + 1:] if message.get("role") == "tool"]
                phase = len(results)
                thought = ["先核对这个问题需要哪些外部依据。", "第一份资料还不充分，需要补查发布日期。", "两次搜索的依据已到齐，现在整理回答。"][min(phase, 2)]
                for piece in [thought[:8], thought[8:16], thought[16:]]:
                    self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {"reasoning_content": piece}}]}, ensure_ascii=False) + "\n\n").encode())
                    self.wfile.flush()
                    time.sleep(.35)
                if payload.get("tools") and payload.get("tool_choice") != "none" and phase < 2:
                    if phase == 0:
                        self.wfile.write(('data: ' + json.dumps({"choices": [{"delta": {"content": "我先查阅相关资料。"}}]}, ensure_ascii=False) + '\n\n').encode())
                    query = ["Nautilus process reference", "Nautilus publication date"][phase]
                    call = {"index": 0, "id": f"mock-process-{phase}", "type": "function", "function": {"name": "search_web", "arguments": json.dumps({"query": query})}}
                    self.wfile.write(('data: ' + json.dumps({"choices": [{"delta": {"tool_calls": [call]}, "finish_reason": "tool_calls"}]}) + '\n\ndata: [DONE]\n\n').encode())
                    self.wfile.flush()
                    return
                chunks = ["这是根据实际资料整理的合成回答。", "思考与工具步骤已按发生顺序保留。"]
            if scenario == "mock-search-tools" and payload.get("tools") and payload.get("tool_choice") != "none" and not has_result:
                arguments = json.dumps({"query": "Nautilus search reference"})
                for delta in [
                    {"tool_calls": [{"index": 0, "id": "mock-call-search", "type": "function", "function": {"name": "search_web", "arguments": arguments[:12]}}]},
                    {"tool_calls": [{"index": 0, "function": {"arguments": arguments[12:]}}]},
                ]:
                    self.wfile.write(("data: " + json.dumps({"choices": [{"delta": delta}]}) + "\n\n").encode())
                self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\ndata: [DONE]\n\n')
                self.wfile.flush()
                return
            c1_request = str(messages[last_user].get('content', '')) if last_user >= 0 else ''
            runtime = next((str(message.get('content', '')) for message in reversed(messages)
                if str(message.get('content', '')).startswith('Nautilus 本轮执行上下文')), None)
            practice_context = json.loads(runtime.split('\n', 1)[1]) if runtime else None
            practice_reply = None
            requested_mode = None
            for phrase, value in [('完整讲解', 'full_explanation'), ('直接给答案', 'direct_answer'),
                                  ('提问引导', 'socratic'), ('分步讲解', 'stepwise'), ('费曼复述', 'feynman'),
                                  ('练习优先', 'practice_first'), ('项目实践', 'project'), ('个人自适应', 'adaptive')]:
                if phrase in c1_request:
                    persistent = any(word in c1_request for word in ['以后', '今后', '接下来都'])
                    requested_mode = {'value': value, 'scope': 'conversation' if persistent else 'turn',
                                      'quote': c1_request, 'persistence_quote': c1_request if persistent else None}
                    break
            requested_help = None
            for phrase, kind in [('给个提示', 'hint'), ('给我提示', 'hint'), ('只解释这一步', 'explain_step'),
                                 ('换个例子', 'example'), ('让我先试试', 'try_first')]:
                if phrase in c1_request:
                    requested_help = {'kind': kind, 'quote': c1_request}
                    break
            if practice_context:
                practice_context['_mock_adaptation'] = adaptive_proposal(practice_context, c1_request, requested_mode, requested_help)
            if practice_context and practice_context.get('action') == 'retell':
                invitation = '请用自己的话说说，为什么要先检查输入边界；也可以举一个简单例子。'
                practice_reply = (invitation, {'step': None, 'attempt': None, 'mode': None, 'help': None,
                    'practice': {'question': invitation, 'feedback': None}})
            elif practice_context and practice_context.get('action') == 'practice':
                sequence = STATE.snapshot()['requests'].get(scenario, 1)
                question = f'🧩合成变式{sequence}：输入换成两个编号，其中一个缺失。你会怎样检查输入边界，并说明理由？'
                practice_reply = (question, {'step': None, 'attempt': None, 'mode': None, 'help': None,
                    'practice': {'question': question, 'feedback': None}})
            elif practice_context and practice_context.get('action') == 'continue':
                if not practice_context['before'].get('practice') and practice_context['before'].get('retelling'):
                    point = '正常输入检查（合成C2复述）。'
                    practice_reply = (point + '请用自己的话说说，输入正常时你会先检查什么？',
                        {'step': point, 'attempt': None, 'mode': None, 'help': None, 'practice': None})
                else:
                    practice_reply = ('先继续原来的小点。你会先检查哪一种输入？',
                        {'step': None, 'attempt': None, 'mode': None, 'help': None, 'practice': None})
            elif practice_context and (practice_context['before'].get('practice') or {}).get('kind') == 'retelling' and '[C2复述作答]' in c1_request:
                feedback = '💬合成复述反馈：你讲清了先检查边界的原因。待补充：说明输入为空时如何处理，并举一个例子。'
                practice_reply = (feedback, {'step': None, 'attempt': {'quote': c1_request, 'needs_help': '[C2卡住]' in c1_request},
                    'mode': None, 'help': None, 'practice': {'question': None, 'feedback': feedback}})
            elif practice_context and practice_context['before'].get('practice') and '[C2作答]' in c1_request:
                needs_help = '[C2卡住]' in c1_request
                feedback = ('💡合成练习反馈：你已经检查了缺失编号；还可以单独说明缺失时返回什么。' if needs_help
                            else '💡合成练习反馈：你先检查了缺失编号，并说明了边界处理的理由；可以继续比较两个编号都存在时的情况。')
                practice_reply = (feedback, {'step': None, 'attempt': {'quote': c1_request, 'needs_help': needs_help},
                    'mode': None, 'help': None, 'practice': {'question': None, 'feedback': feedback}})
            elif practice_context and not practice_context['before'].get('practice') and (
                    practice_context.get('action') == 'next_step'
                    or (requested_mode or {}).get('value', practice_context['before'].get('mode')) == 'project'
                    or practice_context['before'].get('project') and (requested_mode or {}).get('value') in {'full_explanation', 'direct_answer'}):
                project = practice_context['before'].get('project')
                help_kind = practice_context.get('help_kind') or (requested_help or {}).get('kind')
                direct = (requested_mode or {}).get('value') in {'full_explanation', 'direct_answer'}
                proposal = {'step': None, 'attempt': None, 'mode': requested_mode, 'help': requested_help,
                            'practice': None, 'project': None}
                if practice_context.get('action') == 'next_step':
                    sequence = STATE.snapshot()['requests'].get(scenario, 1)
                    instruction = f'🛠️合成实践步骤{sequence}：补充第二个缺失编号的输入，运行你的小程序，并贴出这次输入和返回结果。'
                    body = instruction
                    proposal['project'] = {'goal': None, 'instruction': instruction, 'feedback': None, 'change_quote': None}
                elif project and '[C2项目调整]' in c1_request:
                    goal = '做一个检查输入边界的小程序，缺失编号时返回空列表。'
                    instruction = '🛠️调整后的这一步：修改缺失编号的处理，让程序返回空列表；贴出修改后的代码和运行结果。'
                    body = goal + '\n\n' + instruction
                    proposal['project'] = {'goal': goal, 'instruction': instruction, 'feedback': None, 'change_quote': c1_request}
                elif project and '[C2项目作品]' in c1_request:
                    needs_help = '[C2卡住]' in c1_request
                    body = ('💬合成实践反馈：你贴出了检查缺失编号的代码，还需要提供实际运行结果。' if needs_help
                            else '💬合成实践反馈：这版代码检查了缺失编号，贴出的运行结果与这一版处理一致；可以补充其他输入。')
                    proposal['attempt'] = {'quote': c1_request, 'needs_help': needs_help}
                    proposal['project'] = {'goal': None, 'instruction': None, 'feedback': body, 'change_quote': None}
                elif direct:
                    body = '合成完整讲解：先检查编号是否存在，缺失时返回明确结果，再处理正常输入。'
                elif help_kind:
                    body = {'hint': '想想缺失编号时，程序能否继续读取。', 'explain_step': '先检查编号是否存在，再使用它。',
                            'example': '例如第二个编号缺失时，先返回缺失提示。', 'try_first': '你可以先贴出自己写出的处理方法。'}[help_kind]
                elif not project and '[C2澄清]' not in c1_request:
                    goal = '做一个检查输入边界的小程序。'
                    instruction = '🛠️开始这一步：写出检查缺失编号的代码，用一组包含缺失编号的输入运行，并贴出代码和结果。'
                    body = goal + '\n\n' + instruction
                    proposal['project'] = {'goal': goal, 'instruction': instruction, 'feedback': None, 'change_quote': None}
                elif not project:
                    body = '你想做一个什么小作品？'
                else:
                    body = '可以继续修改这一步的内容，或贴出你的代码和运行结果。'
                practice_reply = (body, proposal)
            elif practice_context and not practice_context['before'].get('practice') and (
                    practice_context.get('action') == 'next_question'
                    or (requested_mode or {}).get('value', practice_context['before'].get('mode')) == 'practice_first'
                    or practice_context['before'].get('exercise') and (requested_mode or {}).get('value') in {'full_explanation', 'direct_answer'}):
                before = practice_context['before']
                exercise = before.get('exercise')
                help_kind = practice_context.get('help_kind') or (requested_help or {}).get('kind')
                direct = (requested_mode or {}).get('value') in {'full_explanation', 'direct_answer'}
                proposal = {'step': None, 'attempt': None, 'mode': requested_mode, 'help': requested_help, 'practice': None}
                if practice_context.get('action') == 'next_question' or not exercise and not help_kind and not direct and '[C2澄清]' not in c1_request:
                    sequence = STATE.snapshot()['requests'].get(scenario, 1)
                    body = f'🧩合成练习{sequence}：输入包含两个编号，其中一个缺失。你会怎样检查输入边界，并说明缺失时的处理？'
                    proposal['practice'] = {'question': body, 'feedback': None}
                elif exercise and ('[C2练习作答]' in c1_request or '[C2作答]' in c1_request):
                    needs_help = '[C2卡住]' in c1_request
                    body = ('💡合成练习反馈：你已检查缺失编号；还需要说明缺失时的处理。' if needs_help
                            else '💡合成练习反馈：你检查了缺失编号，并说明了边界处理；可以补充另一种输入。')
                    proposal['attempt'] = {'quote': c1_request, 'needs_help': needs_help}
                    proposal['practice'] = {'question': None, 'feedback': body}
                elif direct:
                    body = '合成完整讲解：先检查编号是否缺失，缺失时返回明确提示，再处理正常输入。'
                elif help_kind:
                    body = {'hint': '想想缺失编号时，程序能否继续读取。', 'explain_step': '先检查编号是否存在，再使用它。',
                            'example': '例如第二个编号缺失时，先返回缺失提示。', 'try_first': '你可以先写出自己的处理方法。'}[help_kind]
                elif not exercise:
                    body = '你想先练习哪个主题？'
                else:
                    body = '可以继续补充这道题的处理方法。'
                practice_reply = (body, proposal)
            elif practice_context and not practice_context['before'].get('practice') and practice_context['before'].get('mode') == 'feynman':
                point = (practice_context['before'].get('step') or {}).get('text') or '输入边界检查（合成C2复述）。'
                if '[C2复述作答]' in c1_request and practice_context['before'].get('step'):
                    body = '💬合成复述反馈：你讲清了先检查边界的原因。待补充：说明输入为空时如何处理，并举一个例子。'
                    attempt = {'quote': c1_request, 'needs_help': '[C2卡住]' in c1_request}
                    step = None
                else:
                    body = point + '请用自己的话说说，为什么要先检查输入边界；也可以举一个简单例子。'
                    attempt = None
                    step = None if practice_context['before'].get('step') else point
                practice_reply = (body, {'step': step, 'attempt': attempt, 'mode': None, 'help': None, 'practice': None})
            if practice_reply:
                body, proposal = practice_reply
                chunks = ([body] if '[C2慢流]' not in c1_request else ['正在分析新的情境。', *SLOW_CHUNKS, body])
                chunks = teaching_chunks(chunks, proposal, practice_context)
                delay = .08 if '[C2慢流]' in c1_request else .005
            elif '[C1' in c1_request:
                runtime = next((str(m.get('content', '')) for m in reversed(messages)
                    if str(m.get('content', '')).startswith('Nautilus 本轮执行上下文')), None)
                if runtime:
                    context = practice_context or json.loads(runtime.split('\n', 1)[1])
                    sequence = STATE.snapshot()['requests'].get(scenario, 1)
                    point = f'输入边界检查（合成{sequence}）。'
                    proposal = {'step': point, 'attempt': {'quote': c1_request}
                        if '[C1尝试]' in c1_request and context['before']['step'] else None, 'mode': None, 'practice': None}
                    chunks = ([point, '请说明你的判断。'] if '[C1慢流]' not in c1_request
                              else ['正在分析输入边界。', *SLOW_CHUNKS, point])
                    chunks = teaching_chunks(chunks, proposal, context)
                    delay = .08 if '[C1慢流]' in c1_request else .005
            elif any('[C2' in str(message.get('content', '')) for message in messages if message.get('role') == 'user'):
                runtime = next((str(message.get('content', '')) for message in reversed(messages)
                    if str(message.get('content', '')).startswith('Nautilus 本轮执行上下文')), None)
                if runtime:
                    context = practice_context or json.loads(runtime.split('\n', 1)[1])
                    before = context['before']
                    mode = requested_mode
                    help_request = requested_help
                    attempt = None
                    if before['step'] and ('[C2尝试]' in c1_request or '[C2卡住]' in c1_request):
                        attempt = {'quote': c1_request, 'needs_help': '[C2卡住]' in c1_request}
                    point = (before.get('step') or {}).get('text') or '输入边界检查（合成C2）。'
                    new_step = point if not before['step'] else None
                    if '[C2新点]' in c1_request:
                        point = '正常输入检查（合成C2）。'
                        new_step = point
                    level = (before.get('guidance') or {}).get('level', 0)
                    stuck_count = (before.get('guidance') or {}).get('stuck_count', 0)
                    kind = context.get('help_kind') or (help_request or {}).get('kind')
                    if kind == 'hint':
                        level = min(4, level + 1)
                    elif kind == 'explain_step':
                        level = 4
                    elif kind is None and stuck_count + int(bool(attempt and attempt['needs_help'])) >= 2:
                        level = min(4, level + 1)
                    effective_mode = (mode or {}).get('value', before['mode'])
                    body = ('合成完整讲解：先检查空输入，再逐个检查正常输入。' if effective_mode in {'full_explanation', 'direct_answer'}
                            else ['你会先检查哪一种输入？', '想想空输入和输入边界。', '先只考虑空输入时应返回什么。',
                                  '局部例子：输入为空时，先走空输入分支。', '直接解释：先判断输入是否为空，再检查正常输入。'][level])
                    proposal = {'step': new_step, 'attempt': attempt, 'mode': mode, 'help': help_request, 'practice': None}
                    chunks = ([point, body] if '[C2慢流]' not in c1_request
                              else ['正在分析输入边界。', *SLOW_CHUNKS, point, body])
                    chunks = teaching_chunks(chunks, proposal, context)
                    delay = .08 if '[C2慢流]' in c1_request else .005
            elif practice_context and practice_context.get('output_format') == 'json':
                chunks = teaching_chunks(chunks, {'step': None, 'attempt': None, 'mode': None, 'help': None, 'practice': None}, practice_context)
            if scenario == "mock-reasoning" or discussion_stream:
                for reasoning in ["先识别题目条件。", "再核对推导路径。"]:
                    event = json.dumps(
                        {"choices": [{"delta": {"reasoning_content": reasoning}}]},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    self.wfile.write(f"data: {event}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    STATE.chunk_delivered(scenario)
                    time.sleep(0.8 if discussion_stream else 0.10)
            for chunk in chunks:
                event = json.dumps(
                    {"choices": [{"delta": {"content": chunk}}]},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                self.wfile.write(f"data: {event}\n\n".encode("utf-8"))
                self.wfile.flush()
                STATE.chunk_delivered(scenario)
                time.sleep(delay)
            self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            STATE.disconnected(scenario)
        finally:
            self.close_connection = True

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _scenario_stream(scenario: str) -> tuple[list[str], float]:
        if scenario == "mock-math":
            return [MATH_TEXT[:35], MATH_TEXT[35:80], MATH_TEXT[80:]], 0.1
        if scenario == "mock-refresh":
            return REFRESH_CHUNKS, 0.12
        if scenario == "mock-slow":
            return SLOW_CHUNKS, 0.08
        return SUCCESS_CHUNKS, 0.10

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        self.close_connection = True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8013)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), MockOpenAIHandler)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
