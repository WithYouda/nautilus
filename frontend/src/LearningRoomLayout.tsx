import { useEffect, useLayoutEffect, useRef, useState, type FormEventHandler, type KeyboardEventHandler, type ReactNode, type RefObject } from 'react';
import { Bot, Check, ChevronLeft, ChevronRight, Copy, GitBranch, Pencil, RefreshCw, Send, UserRound } from 'lucide-react';

// Presentation only: both teaching and question discussions own their data and actions.
export function LearningChatPanel({ title, children, notice, composer, messagesRef, autoFollow = true, followToken }: {
  title: string; children: ReactNode; notice?: ReactNode; composer?: ReactNode;
  messagesRef?: RefObject<HTMLDivElement | null>; autoFollow?: boolean; followToken?: string | number;
}) {
  const localRef = useRef<HTMLDivElement>(null);
  const ref = messagesRef ?? localRef;
  const pinned = useRef(true);
  useLayoutEffect(() => { pinned.current = true; }, [followToken]);
  useLayoutEffect(() => {
    if (autoFollow && pinned.current && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [children, autoFollow, ref]);
  return <section className="ai-room-chat tool-panel">
    <div className="ai-chat-titlebar"><div className="ai-chat-title-copy"><h2>{title}</h2></div></div>
    <div className="ai-message-list" ref={ref} onScroll={event => { const node = event.currentTarget; pinned.current = node.scrollHeight - node.scrollTop - node.clientHeight < 48; }} aria-live="off">{children}</div>
    <div className="ai-chat-notice">{notice}</div>
    {composer}
  </section>;
}

export function LearningMessage({ role, status, state, children }: { role: 'user' | 'assistant'; status?: string; state?: string; children: ReactNode }) {
  return <article className={`ai-message ai-message--${role}${state ? ` ai-message--${state}` : ''}`}>
    <div className="ai-message-meta">{role === 'user' ? <UserRound size={14} /> : <Bot size={14} />}<span>{role === 'user' ? '我' : 'AI 学习伙伴'}</span>{status && <small>{status}</small>}</div>
    {children}
  </article>;
}

export type MessageVersion = { disabled?: boolean; index: number; count: number; onPrevious: () => void; onNext: () => void };

function MessageVersions({ version, label }: { version?: MessageVersion; label: '回答' | '消息' }) {
  if (!version || version.count < 2) return null;
  return <div className="ai-reply-versions" role="group" aria-label={`${label}版本`}>
    <button type="button" className="icon-button" aria-label={`上一个${label}`} title={`上一个${label}`} disabled={version.disabled || version.index === 0} onClick={version.onPrevious}><ChevronLeft size={15} /></button>
    <span aria-label={`${label} ${version.index + 1}/${version.count}`}>{version.index + 1}/{version.count}</span>
    <button type="button" className="icon-button" aria-label={`下一个${label}`} title={`下一个${label}`} disabled={version.disabled || version.index === version.count - 1} onClick={version.onNext}><ChevronRight size={15} /></button>
  </div>;
}

function CopyMessageButton({ content }: { content: string }) {
  const [copyState, setCopyState] = useState('');
  useEffect(() => {
    if (!copyState) return;
    const timer = window.setTimeout(() => setCopyState(''), 2500);
    return () => window.clearTimeout(timer);
  }, [copyState]);
  async function copy() {
    try {
      try {
        if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable');
        await navigator.clipboard.writeText(content);
      } catch {
        // WSL's HTTP IP address is not a secure context; keep copy usable there.
        const previous = document.activeElement as HTMLElement | null;
        const input = document.createElement('textarea');
        input.value = content;
        input.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
        document.body.appendChild(input);
        try {
          input.select();
          if (!document.execCommand('copy')) throw new Error('Copy rejected');
        } finally { input.remove(); previous?.focus({ preventScroll: true }); }
      }
      setCopyState('已复制');
    } catch { setCopyState('复制失败，请手动选择正文复制'); }
  }
  return <>
    <button className="icon-button" type="button" aria-label="复制" disabled={!content} onClick={() => void copy()} title={copyState || '复制'}>{copyState === '已复制' ? <Check size={15} /> : <Copy size={15} />}</button>
    {copyState && <span className={copyState === '已复制' ? 'reply-sr-only' : ''} role="status">{copyState}</span>}
  </>;
}

export function LearningReplyActions({ content, onRetry, retryDisabled, version }: {
  content: string; onRetry?: () => void; retryDisabled?: boolean; version?: MessageVersion;
}) {
  return <div className="ai-reply-actions" role="group" aria-label="回复操作">
    <MessageVersions version={version} label="回答" />
    <CopyMessageButton content={content} />
    <button className="icon-button" type="button" aria-label="重新生成" disabled={retryDisabled || !onRetry} onClick={onRetry} title="重新生成"><RefreshCw size={15} /></button>
    <button className="icon-button" type="button" aria-label="分支（尚未实现）" aria-disabled="true" title="分支（尚未实现）"><GitBranch size={15} /></button>
  </div>;
}

export function LearningUserMessage({ content, automatic, editing, onStartEdit, onCancelEdit, onSendEdit, editDisabled, sendDisabled, version, maxLength = 8000 }: {
  content: string; automatic?: boolean; editing: boolean; onStartEdit: () => void; onCancelEdit: () => void;
  onSendEdit: (content: string) => Promise<boolean>; editDisabled?: boolean; sendDisabled?: boolean;
  version?: MessageVersion; maxLength?: number;
}) {
  const [draft, setDraft] = useState(content);
  const [submitting, setSubmitting] = useState(false);
  const sending = useRef(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const editButton = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => {
    if (editing) { setDraft(content); input.current?.focus({ preventScroll: true }); }
  }, [editing, content]);
  useLayoutEffect(() => {
    if (editing && input.current) {
      input.current.style.height = 'auto';
      input.current.style.height = `${input.current.scrollHeight}px`;
    }
  }, [editing, draft]);
  function cancel() {
    if (sending.current) return;
    onCancelEdit();
    window.requestAnimationFrame(() => editButton.current?.focus({ preventScroll: true }));
  }
  async function submit() {
    if (sending.current || sendDisabled || !draft.trim()) return;
    sending.current = true; setSubmitting(true);
    try { if (await onSendEdit(draft.trim())) onCancelEdit(); }
    finally { sending.current = false; setSubmitting(false); }
  }
  const body = editing ? <form className="ai-message-editor" aria-label="修改消息" onSubmit={event => { event.preventDefault(); void submit(); }}>
    <textarea ref={input} aria-label="修改消息内容" value={draft} onChange={event => setDraft(event.target.value)} maxLength={maxLength} rows={2} disabled={submitting}
      onKeyDown={event => {
        if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return;
        if (event.key === 'Escape') { event.preventDefault(); cancel(); }
        if (event.key === 'Enter' && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey) { event.preventDefault(); void submit(); }
      }} />
    <div className="ai-message-editor-actions">
      <button className="button button--quiet" type="button" disabled={submitting} onClick={cancel}>取消</button>
      <button className="button button--accent" type="submit" disabled={submitting || sendDisabled || !draft.trim()}>{submitting ? '发送中…' : '发送'}</button>
    </div>
  </form> : <>
    <div className="ai-message-content">{content}</div>
    <div className="ai-reply-actions ai-user-actions" role="group" aria-label="消息操作">
      <MessageVersions version={version} label="消息" />
      <CopyMessageButton content={content} />
      <button ref={editButton} className="icon-button" type="button" aria-label="修改" title="修改" disabled={editDisabled} onClick={onStartEdit}><Pencil size={15} /></button>
    </div>
  </>;
  if (automatic && !editing) return <details className="ai-learning-prompt"><summary>自动发送的学习提示</summary>{body}</details>;
  return <LearningMessage role="user" state={editing ? 'editing' : undefined}>{body}</LearningMessage>;
}

export function LearningComposer({ id, label = '输入学习问题', value, onChange, onSubmit, onKeyDown, placeholder, disabled, maxLength = 8000, textareaRef, actions, sendLabel = '发送问题' }: {
  id: string; label?: string; value: string; onChange: (value: string) => void;
  onSubmit: FormEventHandler<HTMLFormElement>; onKeyDown?: KeyboardEventHandler<HTMLTextAreaElement>;
  placeholder: string; disabled?: boolean; maxLength?: number;
  textareaRef?: RefObject<HTMLTextAreaElement | null>; actions?: ReactNode; sendLabel?: string;
}) {
  const localRef = useRef<HTMLTextAreaElement>(null);
  const ref = textareaRef ?? localRef;
  useEffect(() => {
    const input = ref.current;
    if (input) { input.style.height = 'auto'; input.style.height = `${input.scrollHeight}px`; }
  }, [value, ref]);
  return <form className="ai-composer" onSubmit={onSubmit}>
    <label htmlFor={id}>{label}</label>
    <textarea ref={ref} id={id} value={value} onChange={event => onChange(event.target.value)}
      onKeyDown={onKeyDown ?? (event => {
        if (event.key === 'Enter' && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) {
          event.preventDefault();
          if (!disabled && value.trim()) event.currentTarget.form?.requestSubmit();
        }
      })} placeholder={placeholder} rows={1} maxLength={maxLength} disabled={disabled} />
    <div className="ai-composer-actions"><span>Enter 发送 · Shift+Enter 换行 · {value.length}/{maxLength}</span>
      <div>{actions}<button className="button button--accent button--with-icon" type="submit" disabled={disabled || !value.trim()}><Send size={14} />{sendLabel}</button></div>
    </div>
  </form>;
}

export function ReasoningBlock({ content, streaming }: { content: string; streaming: boolean }) {
  const [open, setOpen] = useState(streaming);

  useEffect(() => {
    setOpen(streaming);
  }, [streaming]);

  return (
    <details className="ai-reasoning" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>{streaming ? "思考中" : "已思考 · 点击展开"}</summary>
      <pre>{content}</pre>
    </details>
  );
}
