import { useLayoutEffect, useRef, useState } from 'react';

export type GraphNodeDisplay = { id: string; title: string; behavior: string; kind: 'atomic' | 'composite'; labels: Array<{ text: string; tone: string }> };
export type GraphEdgeDisplay = { id: string; source: string; target: string; kind: string; label: string };

/** The lines show organization only; each node retains its own evidence. */
export default function OutcomeGraphCanvas({ nodes, edges, selected, onSelect, onRelation }: {
  nodes: GraphNodeDisplay[]; edges: GraphEdgeDisplay[]; selected: string | null;
  onSelect: (id: string) => void; onRelation: (id: string) => void;
}) {
  const canvas = useRef<HTMLDivElement>(null);
  const [lines, setLines] = useState<Array<GraphEdgeDisplay & { path: string; x: number; y: number }>>([]);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const root = canvas.current;
    if (!root) return;
    const measure = () => {
      const bounds = root.getBoundingClientRect();
      const boxes = new Map([...root.querySelectorAll<HTMLElement>('[data-outcome]')].map(element => [element.dataset.outcome!, element.getBoundingClientRect()]));
      setSize({ width: root.scrollWidth, height: root.scrollHeight });
      setLines(edges.flatMap(edge => {
        const a = boxes.get(edge.source), b = boxes.get(edge.target);
        if (!a || !b) return [];
        const vertical = Math.abs(a.left - b.left) < 15;
        const x1 = (vertical ? a.left + a.width / 2 : a.right) - bounds.left;
        const y1 = (vertical ? a.bottom : a.top + a.height / 2) - bounds.top;
        const x2 = (vertical ? b.left + b.width / 2 : b.left) - bounds.left;
        const y2 = (vertical ? b.top : b.top + b.height / 2) - bounds.top;
        const middleX = (x1 + x2) / 2, middleY = (y1 + y2) / 2;
        return [{ ...edge, x: middleX, y: middleY, path: vertical
          ? `M ${x1} ${y1} C ${x1 + 28} ${middleY}, ${x2 + 28} ${middleY}, ${x2} ${y2}`
          : `M ${x1} ${y1} C ${middleX} ${y1}, ${middleX} ${y2}, ${x2} ${y2}` }];
      }));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(root);
    for (const element of root.querySelectorAll('[data-outcome]')) observer.observe(element);
    return () => observer.disconnect();
  }, [nodes, edges]);
  const parentIds = new Set(edges.filter(edge => edge.kind === 'contains').map(edge => edge.source));
  const ordered = [...nodes].sort((a, b) => Number(parentIds.has(b.id)) - Number(parentIds.has(a.id)));
  return <div className="outcome-graph__canvas" ref={canvas} aria-label="成果关系图">
    <svg className="outcome-graph__lines" width={size.width} height={size.height} aria-hidden="true">
      <defs><marker id="outcome-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 8 4 L 0 8 z" /></marker></defs>
      {lines.map(line => <path key={line.id} className={`outcome-graph__line outcome-graph__line--${line.kind}`} d={line.path} markerEnd={['contains', 'prerequisite'].includes(line.kind) ? 'url(#outcome-arrow)' : undefined} />)}
    </svg>
    <div className="outcome-graph__nodes">{ordered.map(node => <button key={node.id} data-outcome={node.id} className={`outcome-graph__node ${node.kind === 'composite' ? 'is-composite' : ''}`} type="button" aria-pressed={selected === node.id} onClick={() => onSelect(node.id)}>
      <small>{node.kind === 'composite' ? '综合成果' : '可验证成果'}</small><strong>{node.title}</strong><span>{node.behavior}</span>
      <div className="outcome-graph__badges">{node.labels.map(label => <span key={`${label.tone}:${label.text}`} className={`outcome-graph__badge outcome-graph__badge--${label.tone}`}>{label.text}</span>)}</div>
    </button>)}</div>
    {!!edges.length && <div className="outcome-graph__connections" aria-label="图中关系">{edges.map(edge => <button key={edge.id} className="text-button" type="button" onClick={() => onRelation(edge.id)}>{nodes.find(node => node.id === edge.source)?.title} <span>{edge.label}</span> {nodes.find(node => node.id === edge.target)?.title}</button>)}</div>}
  </div>;
}
