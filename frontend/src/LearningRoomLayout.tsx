import { useEffect, useLayoutEffect, useRef, useState, type FormEventHandler, type KeyboardEventHandler, type ReactNode, type RefObject } from 'react';
import { Bot, Copy, GitBranch, RefreshCw, Send, UserRound } from 'lucide-react';

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

export function LearningReplyActions({ content, onRetry, retryDisabled }: {
  content: string; onRetry?: () => void; retryDisabled?: boolean;
}) {
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
  return <div className="ai-reply-actions" role="group" aria-label="回复操作">
    <button className="text-button" type="button" disabled={!content} onClick={() => void copy()} title="复制回答正文（Markdown）"><Copy size={13} />复制</button>
    <button className="text-button" type="button" disabled={retryDisabled || !onRetry} onClick={onRetry} title="重新发送对应问题，保留已有回答"><RefreshCw size={13} />重试</button>
    <button className="text-button" type="button" disabled title="对话分支尚未实现"><GitBranch size={13} />分支（尚未实现）</button>
    {copyState && <span role="status">{copyState}</span>}
  </div>;
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
