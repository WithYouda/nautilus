import { useId, useState } from 'react';
import { ArrowUpRight, Bot, SlidersHorizontal } from "lucide-react";
import type { AiProvider } from "./api";

export default function AiCompanionPanel({ provider, onOpenCoach, onOpenProvider, opening }: {
  provider: AiProvider | null; onOpenCoach: (draft?: string) => void; onOpenProvider: () => void; opening?: boolean;
}) {
  const [draft, setDraft] = useState('');
  const inputId = useId();
  const ready = Boolean(provider?.enabled && provider.has_api_key);
  return <aside className="v6-companion" aria-label="学习教练">
    <header className="v6-companion-header"><div><span>NAUTILUS</span><h2>学习教练</h2></div><Bot size={18} aria-hidden="true" /></header>
    <section className="v6-companion-note"><p>{ready ? "说说今天的时间、精力，或一起找回学习节奏。" : "配置提供方后，就可以和教练交流。"}</p></section>
    <div className="v6-companion-spacer" />
    <form className="v6-companion-compose" onSubmit={event => { event.preventDefault(); onOpenCoach(draft.trim() || undefined); }}><label className="sr-only" htmlFor={inputId}>和学习教练交流</label><textarea id={inputId} rows={3} maxLength={8000} value={draft} onChange={event => setDraft(event.target.value)} placeholder="今天想怎么学？" disabled={opening} />
      <div className="v6-companion-actions"><button className="v6-link-button" type="button" onClick={onOpenProvider}><SlidersHorizontal size={14} />提供方设置</button><button className="button button--accent button--with-icon" type="submit" disabled={opening}>{opening ? '打开中…' : draft.trim() ? '和教练聊聊' : '继续对话'}<ArrowUpRight size={15} /></button></div>
    </form>
  </aside>;
}
