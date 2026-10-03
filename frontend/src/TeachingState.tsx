import { useEffect, useRef, useState } from 'react';
import {
  ApiError, correctAiTeachingAttempt, correctDiscussionTeachingAttempt,
  getAiConversation, getQuestionDiscussion, type AiMessage, type QuestionDiscussion,
  type TeachingMode, type TeachingRecord,
} from './api';
import './TeachingState.css';

type TeachingEntry = { id: string; teaching: TeachingRecord | null; userContent: string | null };
const modeLabels: Record<TeachingMode, string> = { stepwise: '分步讲解', direct_answer: '直接给答案', full_explanation: '完整讲解' };

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

export default function TeachingState({ kind, scopeId, pathKey, entries, disabled, onUpdated, standalone = false }: {
  kind: 'conversation' | 'discussion'; scopeId: string; pathKey: string; entries: TeachingEntry[];
  disabled: boolean; onUpdated: (answerId: string, teaching: TeachingRecord | null) => void; standalone?: boolean;
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
  if (!last && !attempts.length) return null;

  async function correct(entry: TeachingEntry) {
    const attempt = entry.teaching?.attempt;
    if (!attempt || disabledRef.current || request.current || needsRefresh) return;
    const controller = new AbortController();
    request.current = controller;
    setBusyId(entry.id); setNotice(null);
    const active = () => !controller.signal.aborted && currentIdentity.current === identity && !disabledRef.current;
    try {
      const payload = {
        expected_revision: attempt.revision, is_attempt: !attempt.is_attempt,
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
    {last?.status === 'applied' && last.mode_request?.scope === 'turn' && last.effective_mode && last.effective_mode !== checkpoint?.mode
      ? <p className="teaching-state__mode">本轮：{modeLabels[last.effective_mode]} · 下轮：{checkpoint?.mode ? modeLabels[checkpoint.mode] : '原方式'}</p>
      : checkpoint?.mode && <p className="teaching-state__mode">讲解方式 · {modeLabels[checkpoint.mode]}</p>}
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
          <button type="button" className="button button--quiet button--compact" disabled={disabled || Boolean(busyId) || needsRefresh || !excerpt} onClick={() => void correct(entry)}>
            {busyId === entry.id ? '正在保存…' : attempt.is_attempt ? '这不是一次尝试' : '恢复为尝试'}
          </button>
          {notice?.id === entry.id && <p className="teaching-attempt__notice" role="alert">{notice.text}</p>}
          {attempt.corrections.length > 0 && <details className="teaching-attempt__history"><summary>纠正历史</summary>
            <ul>{attempt.corrections.map(correction => <li key={correction.revision}>
              <time dateTime={correction.at}>{new Date(correction.at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</time>
              <span>{correction.is_attempt ? '恢复为尝试' : '改为非尝试'}</span>
            </li>)}</ul>
          </details>}
        </article>;
      })}
    </details>}
  </div>;
  return standalone ? <section className="ai-room-brief teaching-arrangement" aria-label="本次学习安排"><details><summary>学习安排</summary>{body}</details></section> : body;
}
