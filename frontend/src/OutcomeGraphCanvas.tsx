import { useId, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { Maximize2, Minus, Plus } from 'lucide-react';
import { GRAPH_NODE_HEIGHT, GRAPH_NODE_WIDTH, layoutOutcomeGraph } from './OutcomeGraphLayout';

export type GraphNodeDisplay = { id: string; title: string; behavior: string; kind: 'atomic' | 'composite'; labels: Array<{ text: string; tone: string }> };
export type GraphEdgeDisplay = { id: string; source: string; target: string; kind: string; label: string };
type View = { x: number; y: number; scale: number };
type Point = { x: number; y: number };
const minimumScale = .25, maximumScale = 1.8;
const clampScale = (value: number) => Math.min(maximumScale, Math.max(minimumScale, value));
const legend = [{ kind: 'contains', text: '包含' }, { kind: 'prerequisite', text: '前置' }, { kind: 'equivalent', text: '等价' }, { kind: 'overlap', text: '重叠' }];

export default function OutcomeGraphCanvas({ nodes, edges, selected, selectedRelation, onSelect, onRelation }: {
  nodes: GraphNodeDisplay[]; edges: GraphEdgeDisplay[]; selected: string | null; selectedRelation?: string | null;
  onSelect: (id: string) => void; onRelation: (id: string) => void;
}) {
  const viewport = useRef<HTMLDivElement>(null), viewRef = useRef<View>({ x: 0, y: 0, scale: 1 });
  const [view, setView] = useState<View>(viewRef.current), [dragging, setDragging] = useState(false);
  const size = useRef({ width: 0, height: 0 }), fitMode = useRef(true), suppressedClick = useRef(false);
  const pointers = useRef(new Map<number, Point>());
  const gesture = useRef<{ points: Point[]; view: View; moved: boolean } | null>(null);
  const unique = useId().replaceAll(':', ''), instructions = `${unique}-instructions`;
  const signature = nodes.map(node => node.id).join(',') + edges.map(edge => `${edge.id}:${edge.kind}:${edge.source}:${edge.target}`).join(',');
  const graph = useMemo(() => layoutOutcomeGraph(nodes, edges), [signature]);
  const nodeMap = new Map(nodes.map(node => [node.id, node]));
  const updateView = (value: View) => { viewRef.current = value; setView(value); };
  function fit(readable = false) {
    const { width, height } = size.current;
    if (!width || !height) return;
    const available = Math.min((width - 24) / graph.width, (height - 24) / graph.height, 1);
    const scale = readable ? Math.max(.85, available) : clampScale(available);
    const rootNode = readable && width < 600 ? nodes.find(node => edges.some(edge => edge.kind === 'contains' && edge.source === node.id) && !edges.some(edge => edge.kind === 'contains' && edge.target === node.id)) : undefined;
    const focus = rootNode ? graph.positions.get(rootNode.id) : undefined;
    updateView({ scale, x: focus ? 32 - focus.x * scale : Math.max(0, (width - graph.width * scale) / 2), y: focus ? height / 2 - (focus.y + GRAPH_NODE_HEIGHT / 2) * scale : Math.max(0, (height - graph.height * scale) / 2) });
    fitMode.current = true;
  }
  function zoomAt(nextScale: number, point: Point) {
    const previous = viewRef.current, scale = clampScale(nextScale), ratio = scale / previous.scale;
    updateView({ scale, x: point.x - (point.x - previous.x) * ratio, y: point.y - (point.y - previous.y) * ratio });
    fitMode.current = false;
  }
  useLayoutEffect(() => {
    const root = viewport.current;
    if (!root) return;
    const measure = () => {
      size.current = { width: root.clientWidth, height: root.clientHeight };
      if (fitMode.current) fit(true);
    };
    fitMode.current = true; measure();
    const observer = new ResizeObserver(measure); observer.observe(root);
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const bounds = root.getBoundingClientRect();
      zoomAt(viewRef.current.scale * Math.exp(-event.deltaY * .0015), { x: event.clientX - bounds.left, y: event.clientY - bounds.top });
    };
    root.addEventListener('wheel', wheel, { passive: false });
    return () => { observer.disconnect(); root.removeEventListener('wheel', wheel); };
  }, [graph]);
  function point(event: ReactPointerEvent): Point {
    const bounds = viewport.current!.getBoundingClientRect();
    return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
  }
  function begin(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    const interactive = (event.target as Element).closest('[data-graph-interactive]');
    if (interactive && event.pointerType !== 'touch') return;
    pointers.current.set(event.pointerId, point(event));
    if (interactive && pointers.current.size === 1) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    gesture.current = { points: [...pointers.current.values()].slice(0, 2), view: viewRef.current, moved: false };
  }
  function move(event: ReactPointerEvent<HTMLDivElement>) {
    if (!pointers.current.has(event.pointerId)) return;
    pointers.current.set(event.pointerId, point(event));
    const start = gesture.current, current = [...pointers.current.values()].slice(0, 2);
    if (!start || current.length !== start.points.length) return;
    const deltaX = current[0].x - start.points[0].x, deltaY = current[0].y - start.points[0].y;
    if (current.length === 1) {
      if (!start.moved && Math.hypot(deltaX, deltaY) < 4) return;
      updateView({ ...start.view, x: start.view.x + deltaX, y: start.view.y + deltaY });
    } else {
      const middle = (points: Point[]) => ({ x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 });
      const original = middle(start.points), next = middle(current);
      const distance = (points: Point[]) => Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
      const scale = clampScale(start.view.scale * distance(current) / Math.max(1, distance(start.points))), ratio = scale / start.view.scale;
      updateView({ scale, x: next.x - (original.x - start.view.x) * ratio, y: next.y - (original.y - start.view.y) * ratio });
    }
    start.moved = true; suppressedClick.current = true; fitMode.current = false; setDragging(true);
  }
  function end(event: ReactPointerEvent<HTMLDivElement>) {
    pointers.current.delete(event.pointerId);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    gesture.current = pointers.current.size ? { points: [...pointers.current.values()], view: viewRef.current, moved: false } : null;
    setDragging(false);
    // A pointer click follows pointerup; it must not open a card after a pan or pinch.
    if (!pointers.current.size) window.setTimeout(() => { suppressedClick.current = false; }, 0);
  }
  return <div className="outcome-graph__canvas">
    <div className="outcome-graph__legend" aria-label="关系图例">{legend.map(item => <span key={item.kind}><i className={`outcome-graph__legend-line outcome-graph__legend-line--${item.kind}`} aria-hidden="true" />{item.text}</span>)}</div>
    <p id={instructions} className="outcome-graph__sr-only">拖动空白处移动，滚轮或双指缩放。键盘方向键移动，加减号缩放，Home 查看全图。点成果查看依据，点关系查看来源与历史。</p>
    <div ref={viewport} className={`outcome-graph__viewport ${dragging ? 'is-dragging' : ''}`} role="group" aria-label="成果关系图" aria-describedby={instructions} tabIndex={0}
      onPointerDown={begin} onPointerMove={move} onPointerUp={end} onPointerCancel={end}
      onClickCapture={event => { if (suppressedClick.current) { event.preventDefault(); event.stopPropagation(); } }}
      onKeyDown={event => {
        if (event.target !== event.currentTarget) return;
        const delta: Record<string, Point> = { ArrowLeft: { x: 48, y: 0 }, ArrowRight: { x: -48, y: 0 }, ArrowUp: { x: 0, y: 48 }, ArrowDown: { x: 0, y: -48 } };
        if (delta[event.key]) { event.preventDefault(); fitMode.current = false; updateView({ ...viewRef.current, x: viewRef.current.x + delta[event.key].x, y: viewRef.current.y + delta[event.key].y }); }
        else if (['+', '=', '-'].includes(event.key)) { event.preventDefault(); zoomAt(viewRef.current.scale * (event.key === '-' ? .8 : 1.25), { x: size.current.width / 2, y: size.current.height / 2 }); }
        else if (event.key === 'Home') { event.preventDefault(); fit(); }
      }}>
      <div className="outcome-graph__space" data-graph-transform={`${view.x},${view.y},${view.scale}`} style={{ width: graph.width, height: graph.height, transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}>
        <svg className="outcome-graph__lines" width={graph.width} height={graph.height}>
          <defs>{['contains', 'prerequisite'].map(kind => <marker key={kind} id={`${unique}-${kind}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path className={`outcome-graph__arrow--${kind}`} d="M 0 0 L 8 4 L 0 8 z" /></marker>)}</defs>
          {graph.lines.map(line => <g key={line.id} className={`outcome-graph__edge ${selectedRelation === line.id ? 'is-selected' : ''}`}>
            <path aria-hidden="true" className={`outcome-graph__line outcome-graph__line--${line.kind}`} d={line.path} markerEnd={['contains', 'prerequisite'].includes(line.kind) ? `url(#${unique}-${line.kind})` : undefined} />
            <path data-graph-interactive="true" aria-hidden="true" className="outcome-graph__line-hit" d={line.path} onClick={() => onRelation(line.id)} />
          </g>)}
          {graph.lines.map(line => {
            const label = `${nodeMap.get(line.source)?.title} ${line.label} ${nodeMap.get(line.target)?.title}`;
            return <g key={line.id} data-relation={line.id} className={`outcome-graph__edge ${selectedRelation === line.id ? 'is-selected' : ''}`}>
              <g data-graph-interactive="true" role="button" tabIndex={0} aria-label={label} aria-pressed={selectedRelation === line.id} className={`outcome-graph__edge-label outcome-graph__edge-label--${line.kind}`} transform={`translate(${line.x},${line.y})`} onClick={() => onRelation(line.id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onRelation(line.id); } }}>
                <rect x={-28} y={-13} width="56" height="26" rx="4" /><text textAnchor="middle" dominantBaseline="central">{line.kind === 'prerequisite' ? '前置' : line.label}</text>
              </g>
            </g>;
          })}
        </svg>
        {nodes.map(node => {
          const position = graph.positions.get(node.id)!;
          return <button key={node.id} data-graph-interactive="true" data-outcome={node.id} className={`outcome-graph__node ${node.kind === 'composite' ? 'is-composite' : ''}`} style={{ left: position.x, top: position.y, width: GRAPH_NODE_WIDTH, height: GRAPH_NODE_HEIGHT }} type="button" aria-pressed={selected === node.id} aria-label={`${node.title} · ${node.kind === 'composite' ? '综合成果' : '可验证成果'} · ${node.labels.map(label => label.text).join('、')}`} title={node.title} onClick={() => onSelect(node.id)} onFocus={event => {
            if (!event.currentTarget.matches(':focus-visible')) return;
            const current = viewRef.current, x = position.x * current.scale + current.x, y = position.y * current.scale + current.y;
            if (x < 0 || y < 40 || x + GRAPH_NODE_WIDTH * current.scale > size.current.width || y + GRAPH_NODE_HEIGHT * current.scale > size.current.height - 54) {
              fitMode.current = false; updateView({ ...current, x: size.current.width / 2 - (position.x + GRAPH_NODE_WIDTH / 2) * current.scale, y: size.current.height / 2 - (position.y + GRAPH_NODE_HEIGHT / 2) * current.scale });
            }
          }}>
            <small>{node.kind === 'composite' ? '综合成果' : '可验证成果'}</small><strong>{node.title}</strong>
            <div className="outcome-graph__badges">{node.labels.map(label => <span key={`${label.tone}:${label.text}`} className={`outcome-graph__badge outcome-graph__badge--${label.tone}`}>{label.text}</span>)}</div>
          </button>;
        })}
      </div>
    </div>
    <div className="outcome-graph__navigation" aria-label="移动与缩放成果图"><span aria-hidden="true">{Math.round(view.scale * 100)}%</span><button type="button" aria-label="缩小成果图" disabled={view.scale <= minimumScale} onClick={() => zoomAt(viewRef.current.scale / 1.25, { x: size.current.width / 2, y: size.current.height / 2 })}><Minus size={16} /></button><button type="button" aria-label="放大成果图" disabled={view.scale >= maximumScale} onClick={() => zoomAt(viewRef.current.scale * 1.25, { x: size.current.width / 2, y: size.current.height / 2 })}><Plus size={16} /></button><button type="button" aria-label="查看全图" onClick={() => fit()}><Maximize2 size={16} /><span>全图</span></button></div>
  </div>;
}
