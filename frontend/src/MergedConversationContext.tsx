import { useEffect, useState } from 'react';
import { GitMerge } from 'lucide-react';
import LearningMarkdown from './LearningMarkdown';
import { ModelConfigHistory } from './ModelControl';
import type { MergeSource, ModelRunConfig } from './api';
import './styles/merged-conversation.css';

export default function MergedConversationContext({ content, sources, continued, onNavigate, disabled, config, purged = false }: {
  content: string; sources: MergeSource[]; continued: boolean; onNavigate: (id: string, sourceId: string) => void;
  disabled?: boolean; config?: ModelRunConfig | null; purged?: boolean;
}) {
  const [open, setOpen] = useState(!continued);
  useEffect(() => setOpen(!continued), [continued]);
  return <section className="merged-context" aria-label="合并对话起点">
    <div className="merged-context__heading"><GitMerge size={16} /><strong>合并对话</strong></div>
    {!purged && <div className="merged-context__sources"><span>来自</span>{sources.map((source, index) => <span className="merged-context__source" key={source.id}>
      {index > 0 && <span aria-hidden="true">＋</span>}<button type="button" className="text-button" disabled={disabled || !source.available} onClick={() => onNavigate(source.id, source.source_id)}>{source.title}{source.available ? ' ↗' : ''}</button>
    </span>)}</div>}
    {purged ? <p>合并内容已清除。</p> : <details className="merged-context__content" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
      <summary>这次合并保留的内容</summary><LearningMarkdown>{content}</LearningMarkdown><ModelConfigHistory config={config} />
    </details>}
    <div className="merged-context__divider">从合并内容继续</div>
  </section>;
}
