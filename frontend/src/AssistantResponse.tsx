import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, Clock3, ExternalLink, Globe2, Search, X } from 'lucide-react';
import LearningMarkdown from './LearningMarkdown';
import SearchResults, { SearchSuggestions, type SearchTrace } from './SearchResults';
import DialogPortal from './DialogPortal';

type ProcessStatus = 'running' | 'succeeded' | 'failed' | 'canceled' | 'interrupted';
export type ProcessPart = {
  id: string; type: 'reasoning' | 'text' | 'tool'; status: ProcessStatus;
  started_at: string; finished_at?: string; duration_ms: number;
  text?: string; call_id?: string; name?: string; query?: string; url?: string;
  service_name?: string; result?: SearchTrace; message?: string;
};
export type GenerationTrace = {
  version: 1; status: ProcessStatus; started_at: string; finished_at?: string;
  elapsed_ms: number; parts: ProcessPart[];
};

function formatDuration(ms: number) {
  const seconds = Math.max(0, ms) / 1000;
  return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} 秒`;
}

function useElapsed(part: ProcessPart, active: boolean) {
  const [receivedAt, setReceivedAt] = useState(() => performance.now());
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => { setReceivedAt(performance.now()); }, [part.id, part.duration_ms]);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(performance.now()), 100);
    return () => window.clearInterval(timer);
  }, [active]);
  return active ? part.duration_ms + Math.max(0, now - receivedAt) : part.duration_ms;
}

function ReasoningStep({ part, streaming }: { part: ProcessPart; streaming: boolean }) {
  const active = part.status === 'running' && streaming;
  const [open, setOpen] = useState(active);
  const elapsed = useElapsed(part, active);
  const label = active ? '思考中' : part.status === 'failed' ? '思考失败' : part.status === 'canceled' ? '思考已取消' : part.status === 'interrupted' || part.status === 'running' ? '思考已中断' : '已思考';
  useEffect(() => { setOpen(active); }, [active, part.id]);
  return <div className="ai-process-step ai-process-reasoning">
    <button className="ai-process-step-head" type="button" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      <Clock3 size={15} aria-hidden="true" /><span>{label}</span><small>{formatDuration(elapsed)}</small>{open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
    </button>
    {open && part.text && <div className={`ai-process-reasoning-text${active ? ' is-preview' : ''}`}>{part.text}</div>}
  </div>;
}

function ToolStep({ part, onExpandGroup }: { part: ProcessPart; onExpandGroup: () => void }) {
  const [open, setOpen] = useState(true);
  const [showDetail, setShowDetail] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const result = part.result;
  const count = result?.items?.length ?? 0;
  const domains = [...new Set((result?.items ?? []).flatMap(item => { try { const url = new URL(item.url); return ['http:', 'https:'].includes(url.protocol) ? [url.hostname.replace(/^www\./, '')] : []; } catch { return []; } }))].slice(0, 3);
  const title = part.name === 'scrape_web' ? '读取网页' : part.name === 'native_search' ? '模型内置搜索' : '联网搜索';
  useEffect(() => {
    if (!showDetail) return;
    dialogRef.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setShowDetail(false); return; }
      if (event.key !== 'Tab' || !dialogRef.current) return;
      const elements = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),[tabindex]:not([tabindex="-1"])'));
      if (!elements.length) return;
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', handleKey);
    return () => { document.removeEventListener('keydown', handleKey); triggerRef.current?.focus(); };
  }, [showDetail]);
  return <div className="ai-process-step ai-process-tool">
    <button className="ai-process-step-head" type="button" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      <Search size={15} aria-hidden="true" /><span>{title}{part.query ? `：${part.query}` : ''}</span><small>{part.status === 'running' ? '进行中' : part.status === 'failed' ? '失败' : part.status === 'canceled' ? '已取消' : part.status === 'interrupted' ? '已中断' : `${count} 条来源`}</small>{open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
    </button>
    {open && <div className="ai-process-tool-summary">
      {part.service_name && <span>{part.service_name}</span>}
      {part.url && <span className="ai-process-tool-url">{part.url}</span>}
      {result?.answer && <p>{result.answer}</p>}
      {part.message && <p>{part.message}</p>}
      {!!domains.length && <div className="ai-process-domains">{domains.map(domain => <span key={domain}><Globe2 size={12} />{domain}</span>)}{count > domains.length && <span>+{count - domains.length}</span>}</div>}
      {result && result.status === 'succeeded' && <button ref={triggerRef} type="button" className="ai-process-detail-trigger" onClick={() => { onExpandGroup(); setShowDetail(true); }}>查看来源与检索过程 <ExternalLink size={13} /></button>}
    </div>}
    {showDetail && result && <DialogPortal><div className="ai-process-detail-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setShowDetail(false); }}><section ref={dialogRef} tabIndex={-1} className="ai-process-detail" role="dialog" aria-modal="true" aria-label="联网搜索详情"><header><h2>{title}详情</h2><button type="button" className="icon-button" aria-label="关闭搜索详情" onClick={() => setShowDetail(false)}><X size={18} /></button></header><SearchResults trace={result} expanded showSuggestions={false} /></section></div></DialogPortal>}
  </div>;
}

function ThinkingGroup({ parts, streaming }: { parts: ProcessPart[]; streaming: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const collapsible = parts.length > 2;
  const visible = collapsible && !expanded ? parts.slice(-2) : parts;
  return <div className="ai-process-group" aria-label="思考与工具调用过程">
    {collapsible && <button className="ai-process-more" type="button" onClick={() => setExpanded(value => !value)}>{expanded ? '收起较早步骤' : `展开较早的 ${parts.length - 2} 个步骤`}{expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</button>}
    <div className="ai-process-timeline">{visible.map(part => part.type === 'reasoning' ? <ReasoningStep key={part.id} part={part} streaming={streaming} /> : <ToolStep key={part.id} part={part} onExpandGroup={() => setExpanded(true)} />)}</div>
  </div>;
}

function processBlocks(parts: ProcessPart[]) {
  const blocks: Array<{ type: 'thinking'; parts: ProcessPart[] } | { type: 'text'; part: ProcessPart }> = [];
  for (const part of parts) {
    if (part.type === 'text') blocks.push({ type: 'text', part });
    else {
      const last = blocks.at(-1);
      if (last?.type === 'thinking') last.parts.push(part);
      else blocks.push({ type: 'thinking', parts: [part] });
    }
  }
  return blocks;
}

export default function AssistantResponse({ trace, content, reasoningContent, searchTrace, streaming }: {
  trace?: GenerationTrace | null; content: string; reasoningContent?: string | null;
  searchTrace?: SearchTrace | null; streaming: boolean;
}) {
  if (trace?.version === 1 && trace.parts.length) {
    const hasText = trace.parts.some(part => part.type === 'text');
    return <div className="ai-assistant-response">{processBlocks(trace.parts).map(block => block.type === 'thinking'
      ? <ThinkingGroup key={`group-${block.parts[0].id}`} parts={block.parts} streaming={streaming} />
      : block.part.text && <div key={block.part.id} className="ai-message-content ai-markdown"><LearningMarkdown>{block.part.text}</LearningMarkdown></div>)}
      {!hasText && content && <div className="ai-message-content ai-markdown"><LearningMarkdown>{content}</LearningMarkdown></div>}
      {!hasText && !content && streaming && <p className="ai-message-content" role="status">…</p>}
      {trace.parts.filter(part => part.type === 'tool' && part.result?.search_suggestions_html).map(part => <SearchSuggestions key={`suggestions-${part.id}`} html={part.result?.search_suggestions_html} />)}
    </div>;
  }
  const actualSearch = searchTrace && searchTrace.mode !== 'off' && !['off', 'not_used', 'queued'].includes(searchTrace.status);
  return <div className="ai-assistant-response">
    {(reasoningContent || actualSearch) && <div className="ai-process-group" aria-label="思考与工具调用过程">
      {reasoningContent && <details className="ai-process-legacy-reasoning" open={streaming}><summary>{streaming ? '思考中' : '已思考'}</summary><pre>{reasoningContent}</pre></details>}
      {actualSearch && <details className="ai-process-legacy-search"><summary>{searchTrace.status === 'running' ? '正在搜索' : searchTrace.status === 'failed' ? '搜索失败' : '已搜索'}{searchTrace.query ? `：${searchTrace.query}` : ''}</summary><SearchResults trace={searchTrace} expanded showSuggestions={false} /></details>}
    </div>}
    {content ? <div className="ai-message-content ai-markdown"><LearningMarkdown>{content}</LearningMarkdown></div> : streaming && <p className="ai-message-content" role="status">…</p>}
    {actualSearch && <SearchSuggestions html={searchTrace.search_suggestions_html} />}
  </div>;
}
