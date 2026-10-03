import { useEffect, useRef, useState } from 'react';
import {
  ApiError, correctAiTeachingAttempt, correctDiscussionTeachingAttempt,
  getAiConversation, getQuestionDiscussion, type AiMessage, type QuestionDiscussion,
  type TeachingMethod, type TeachingMode, type TeachingRecord,
} from './api';
import './TeachingState.css';

type TeachingEntry = { id: string; teaching: TeachingRecord | null; userContent: string | null };
const modeLabels: Record<TeachingMode, string> = { stepwise: '分步讲解', socratic: '提问引导', direct_answer: '直接给答案', full_explanation: '完整讲解' };
const guidanceLabels = ['开放提问', '相关概念', '缩小范围', '局部示例', '直接解释'];
const progressLabel = (needsHelp: boolean | null | undefined) => needsHelp === true ? '仍需帮助' : needsHelp === false ? '已推进' : '未判断';

export function conversationTeachingEntries(messages: AiMessage[]): TeachingEntry[] {
  return messages.filter(message => message.role === 'assistant').map(message => ({
    id: message.id,
    teaching: message.teaching ?? null,
    userContent: messages.find(source => source.role === 'user' && source.id === message.teaching?.attempt?.message_id)?.content ?? null,
  }));
}

export function discussionTeachingEntries(turns: QuestionDiscussion['turns']): TeachingEntry[] {
  return turns.map(turn => ({
    id: turn.id,
    teaching: turn.status === 'purged' ? null : turn.teaching ?? null,
    userContent: turns.find(source => source.status !== 'purged' && source.id === turn.teaching?.attempt?.message_id)?.user_content ?? null,
  }));
}

export default function TeachingState({ kind, scopeId, pathKey, entries, disabled, onUpdated, selectedMode, onModeChange, standalone = false }: {
  kind: 'conversation' | 'discussion'; scopeId: string; pathKey: string; entries: TeachingEntry[];
  disabled: boolean; onUpdated: (answerId: string, teaching: TeachingRecord | null) => void; standalone?: boolean;
  selectedMode: TeachingMethod | null; onModeChange: (mode: TeachingMethod) => void;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ id: string; text: string } | null>(null);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const request = useRef<AbortController | null>(null);
  const identity = `${kind}:${scopeId}:${pathKey}`;
  const currentIdentity = useRef(identity);
  currentIdentity.current = identity;
  const disabledRef = useRef(disabled);
  disabledRef.current = disabled;
  useEffect(() => {
    setBusyId(null); setNotice(null); setNeedsRefresh(false);
    return () => { request.current?.abort(); request.current = null; };
  }, [identity]);

  // The final selected answer owns this position. Legacy answers remain unknown;
  // cancellation and incomplete runs use their own saved pre-generation state.
  const last = entries.at(-1)?.teaching;
  const checkpoint = last?.status === 'applied' ? last.current : last?.before;
  const attempts = entries.filter(entry => entry.teaching?.attempt);
  const currentMode = checkpoint?.mode ?? 'stepwise';
  const method = selectedMode ?? (currentMode === 'stepwise' || currentMode === 'socratic' ? currentMode : '');
  const guidance = last?.status === 'applied' ? last.guidance ?? checkpoint?.guidance : checkpoint?.guidance;

  async function correct(entry: TeachingEntry, change: { is_attempt: boolean; needs_help?: boolean | null }) {
    const attempt = entry.teaching?.attempt;
    if (!attempt || disabledRef.current || request.current || needsRefresh) return;
    const controller = new AbortController();
    request.current = controller;
    setBusyId(entry.id); setNotice(null);
    const active = () => !controller.signal.aborted && currentIdentity.current === identity && !disabledRef.current;
    try {
      const payload = {
        expected_revision: attempt.revision, ...change,
        request_key: crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`,
      };
      const saved = await (kind === 'conversation'
        ? correctAiTeachingAttempt(scopeId, entry.id, payload, controller.signal)
        : correctDiscussionTeachingAttempt(scopeId, entry.id, payload, controller.signal));
      if (active()) onUpdated(entry.id, saved);
    } catch (reason) {
      if (!active()) return;
      if (reason instanceof ApiError && reason.status === 409) {
        try {
          const latest = kind === 'conversation'
            ? (await getAiConversation(scopeId, controller.signal)).messages.find(message => message.id === entry.id)?.teaching
            : (await getQuestionDiscussion(scopeId, controller.signal)).turns.find(turn => turn.id === entry.id)?.teaching;
          if (!active()) return;
          onUpdated(entry.id, latest ?? null);
          setNotice({ id: entry.id, text: '识别记录已更新。已读取最新记录，请核对后再操作。' });
        } catch {
          if (active()) {
            setNeedsRefresh(true);
            setNotice({ id: entry.id, text: '识别记录已更新，暂时无法读取最新记录。请刷新后再操作。' });
          }
        }
      } else {
        setNotice({ id: entry.id, text: '纠正未确认，请刷新核对识别记录后再操作。' });
        setNeedsRefresh(true);
      }
    } finally {
      if (currentIdentity.current === identity && !controller.signal.aborted) setBusyId(null);
      if (request.current === controller) request.current = null;
    }
  }

  const body = <div className="teaching-state" aria-label="当前教学安排">
    <label className="teaching-state__choice">讲解方式
      <select aria-label="讲解方式" value={method} disabled={disabled || Boolean(busyId)} onChange={event => onModeChange(event.target.value as TeachingMethod)}>
        {!method && <option value="" disabled>选择方式</option>}
        <option value="stepwise">分步讲解</option><option value="socratic">提问引导</option>
      </select>
    </label>
    {selectedMode && <p className="form-hint" role="status">下次发送时使用{modeLabels[selectedMode]}。</p>}
    {last?.status === 'applied' && last.mode_request?.scope === 'turn' && last.effective_mode && last.effective_mode !== checkpoint?.mode
      ? <p className="teaching-state__mode">本轮：{modeLabels[last.effective_mode]} · 下轮：{checkpoint?.mode ? modeLabels[checkpoint.mode] : '原方式'}</p>
      : currentMode !== 'stepwise' && currentMode !== 'socratic' && <p className="teaching-state__mode">当前方式 · {modeLabels[currentMode]}</p>}
    {(last?.effective_mode ?? checkpoint?.mode) === 'socratic' && guidance && <p className="teaching-state__mode">提示安排 · {guidanceLabels[guidance.level]}</p>}
    {checkpoint?.step && <div className="teaching-state__step"><b>当前小点</b><p>{checkpoint.step.text}</p></div>}
    {last?.status === 'running' && <p className="form-hint" role="status">正在回复，教学位置暂不更新。</p>}
    {last?.status === 'not_updated' && <p className="form-hint">本轮未更新教学位置。</p>}
    {attempts.length > 0 && <details className="teaching-state__attempts">
      <summary>尝试识别</summary>
      {attempts.map(entry => {
        const attempt = entry.teaching!.attempt!;
        const step = entry.teaching!.before.step;
        // Offsets from the server refer to Unicode code points, as in Python.
        const excerpt = entry.userContent === null ? null : Array.from(entry.userContent).slice(attempt.start, attempt.end).join('');
        return <article className="teaching-attempt" key={entry.id} aria-label="AI识别的尝试">
          <p className="teaching-attempt__label">AI识别{!attempt.is_attempt && <span> · 已改为非尝试</span>}</p>
          {excerpt ? <blockquote>{excerpt}</blockquote> : <p className="form-hint">对应原文已不可用。</p>}
          {entry.userContent && entry.userContent !== excerpt && <details className="teaching-attempt__original"><summary>完整原文</summary><blockquote>{entry.userContent}</blockquote></details>}
          {step?.id === attempt.step_id && <p className="teaching-attempt__step"><b>当时的小点</b>{step.text}</p>}
          {attempt.is_attempt && <label className="teaching-attempt__progress">尝试进展
            <select aria-label="尝试进展" value={attempt.needs_help === true ? 'stuck' : attempt.needs_help === false ? 'progressed' : 'unknown'} disabled={disabled || Boolean(busyId) || needsRefresh || !excerpt}
              onChange={event => void correct(entry, { is_attempt: true, needs_help: event.target.value === 'stuck' ? true : event.target.value === 'progressed' ? false : null })}>
              <option value="unknown">未判断</option><option value="stuck">仍需帮助</option><option value="progressed">已推进</option>
            </select>
          </label>}
          <button type="button" className="button button--quiet button--compact" disabled={disabled || Boolean(busyId) || needsRefresh || !excerpt} onClick={() => void correct(entry, { is_attempt: !attempt.is_attempt })}>
            {busyId === entry.id ? '正在保存…' : attempt.is_attempt ? '这不是一次尝试' : '恢复为尝试'}
          </button>
          {notice?.id === entry.id && <p className="teaching-attempt__notice" role="alert">{notice.text}</p>}
          {attempt.corrections.length > 0 && <details className="teaching-attempt__history"><summary>纠正历史</summary>
            <ul>{attempt.corrections.map((correction, index) => <li key={correction.revision}>
              <time dateTime={correction.at}>{new Date(correction.at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</time>
              <span>{!correction.is_attempt ? '改为非尝试' : index > 0 && !attempt.corrections[index - 1].is_attempt ? '恢复为尝试' : 'needs_help' in correction ? `尝试 · ${progressLabel(correction.needs_help)}` : '恢复为尝试'}</span>
            </li>)}</ul>
          </details>}
        </article>;
      })}
    </details>}
  </div>;
  return standalone ? <section className="ai-room-brief teaching-arrangement" aria-label="本次学习安排"><details><summary>学习安排</summary>{body}</details></section> : body;
}
