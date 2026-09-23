import { ArrowUpRight, Bot, MessageSquareText, SlidersHorizontal } from "lucide-react";
import type { AiProvider } from "./api";

export default function AiCompanionPanel({ provider, onOpenLearning, onOpenProvider }: {
  provider: AiProvider | null; onOpenLearning: () => void; onOpenProvider: () => void;
}) {
  const ready = Boolean(provider?.enabled && provider.has_api_key);
  return <aside className="v6-companion" aria-label="AI 学习伙伴">
    <header className="v6-companion-header"><div><span>NAUTILUS</span><h2>AI 学习伙伴</h2></div><Bot size={18} aria-hidden="true" /></header>
    <section className="v6-companion-note"><p>{ready ? "可以在学习室自由提问。要继续某项任务，请从学习首页或学习计划进入，原来的对话和验证会一起保留。" : "配置提供方后，就可以开始 AI 学习对话。"}</p></section>
    <div className="v6-companion-spacer" />
    <section className="v6-companion-compose"><div className="v6-companion-placeholder"><MessageSquareText size={16} /><span>有什么想聊的？</span></div>
      <div className="v6-companion-actions"><button className="v6-link-button" type="button" onClick={onOpenProvider}><SlidersHorizontal size={14} />提供方设置</button><button className="button button--accent button--with-icon" type="button" onClick={onOpenLearning}>进入学习室<ArrowUpRight size={15} /></button></div>
    </section>
  </aside>;
}
