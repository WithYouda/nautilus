import { useId, useLayoutEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import LearningMarkdown from './LearningMarkdown';
import type { QuestionDiscussion } from './api';

type Source = QuestionDiscussion['turns'][number]['sources'][number];

function SourceExcerpt({ source, index }: { source: Source; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const id = useId();
  useLayoutEffect(() => {
    const element = body.current;
    if (!element) return;
    const measure = () => {
      if (!expanded) setOverflowing(element.scrollHeight > element.clientHeight + 1);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [source.excerpt, expanded]);
  return <article className="discussion-source">
    <h4>记录 {index + 1} · {source.kind === 'teaching' ? '本委托学习对话' : '本委托题目讨论'}</h4>
    <div id={id} ref={body} className={`discussion-source__excerpt ai-markdown${expanded ? ' is-expanded' : overflowing ? ' is-truncated' : ''}`}>
      <LearningMarkdown>{source.excerpt}</LearningMarkdown>
    </div>
    {(overflowing || expanded) && <button type="button" className="discussion-source__toggle" aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded(value => !value)}>
      {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}{expanded ? '收起记录' : '展开记录'} {index + 1}
    </button>}
  </article>;
}

export default function DiscussionSources({ sources }: { sources: Source[] }) {
  return <details className="discussion-sources">
    <summary>实际查阅的 {sources.length} 段记录</summary>
    <div className="discussion-sources__list">{sources.map((source, index) => <SourceExcerpt key={index} source={source} index={index} />)}</div>
  </details>;
}
