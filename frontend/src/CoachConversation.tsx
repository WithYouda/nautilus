import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Send } from 'lucide-react';
import { navigateCoach, coachHref } from './background-coach-api';
import { resolveCoachAction, type CoachAction } from './coach-conversation-api';
import './styles/coach-conversation.css';

export function CoachHomeEntry({ onOpen, opening = false }: { onOpen: (draft?: string) => void; opening?: boolean }) {
  const [draft, setDraft] = useState('');
  return <section className="coach-home-entry" aria-label="学习教练">
    <div className="coach-home-entry__heading"><h2>学习教练</h2><button className="text-button" type="button" disabled={opening} onClick={() => onOpen()}>{opening ? '打开中…' : '继续对话'}<ArrowUpRight size={14} /></button></div>
    <form onSubmit={event => { event.preventDefault(); if (draft.trim()) onOpen(draft.trim()); }}>
      <label className="sr-only" htmlFor="coach-home-input">和教练说说今天</label>
      <textarea id="coach-home-input" rows={2} disabled={opening} value={draft} onChange={event => setDraft(event.target.value)} placeholder="今天只有20分钟，有点累。接下来学什么？" onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (draft.trim() && !opening) onOpen(draft.trim()); } }} />
      <button className="button button--accent button--compact button--with-icon" type="submit" disabled={!draft.trim() || opening}><Send size={14} />{opening ? '打开中…' : '和教练聊聊'}</button>
    </form>
  </section>;
}

export function CoachActions({ conversationId, actions, current = false, canNavigate }: { conversationId: string; actions: CoachAction[]; current?: boolean; canNavigate?: () => boolean }) {
  const [busy, setBusy] = useState<string | null>(null), [error, setError] = useState('');
  const [expanded, setExpanded] = useState(false);
  const generation = useRef(0), alive = useRef(false);
  useEffect(() => { generation.current++; alive.current = true; setExpanded(false); return () => { generation.current++; alive.current = false; }; }, [conversationId]);
  if (!actions.length) return null;
  async function open(action: CoachAction) {
    if (busy) return;
    const acceptedGeneration = generation.current;
    const stillCurrent = () => alive.current && generation.current === acceptedGeneration && (canNavigate?.() ?? true);
    setBusy(action.id); setError('');
    try { const result = await resolveCoachAction(conversationId, action); if (!stillCurrent()) return; const href = coachHref(result.target.href); if (!href) throw new Error('这个入口暂时无法打开，请查看当前安排。'); navigateCoach(href); }
    catch (reason) { if (stillCurrent()) setError(reason instanceof Error ? reason.message : '当前安排已变化，请重新和教练核对。'); }
    finally { if (stillCurrent()) setBusy(null); }
  }
  const visible = current && !expanded ? actions.slice(0, 3) : actions;
  return <div className="coach-actions" aria-label={current ? '当前可用入口' : '教练建议的下一步'}>{current && <p className="coach-actions__label">当前可用入口</p>}<div>{visible.map(action => <button className="button button--quiet button--compact button--with-icon" type="button" key={action.id} disabled={Boolean(busy) || !action.available} title={action.reason ?? undefined} onClick={() => void open(action)}>{busy === action.id ? '正在核对…' : action.label}<ArrowUpRight size={13} /></button>)}</div>{current && actions.length > 3 && <button className="text-button coach-actions__expand" type="button" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? '收起入口' : `更多入口（${actions.length - 3}）`}</button>}{error && <p className="form-error" role="alert">{error}</p>}</div>;
}
