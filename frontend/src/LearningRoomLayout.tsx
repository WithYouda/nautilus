import { useEffect, useLayoutEffect, useRef, useState, type FormEventHandler, type KeyboardEventHandler, type ReactNode, type RefObject } from 'react';
import { Bot, Send, UserRound } from 'lucide-react';

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
