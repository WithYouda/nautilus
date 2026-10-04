import { useId, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { LocateFixed, Maximize2, Minus, Plus } from 'lucide-react';
import type { LearningPathEdge, LearningPathNode } from './learning-path-api';

export type PathCanvasGroup = {
  id: string; kind: 'main' | 'history' | 'candidate'; title: string;
  nodes: LearningPathNode[]; edges: LearningPathEdge[]; entryNodeId: string; currentNodeId: string | null;
  parentId?: string | null; branchNodeId?: string | null;
};
type Point = { x: number; y: number };
type View = Point & { scale: number };
type PlacedNode = { key: string; group: PathCanvasGroup; node: LearningPathNode; position: Point };
const nodeWidth = 184, nodeHeight = 86, gap = 58;
const minScale = .35, maxScale = 1.8;
const clamp = (value: number) => Math.min(maxScale, Math.max(minScale, value));
export const pathNodeKey = (groupId: string, nodeId: string) => `${groupId}:${nodeId}`;
const groupLabels = { main: '当前路线', history: '暂停方向', candidate: '待采用' };
function nodeLabel(group: PathCanvasGroup, node: LearningPathNode) {
  if (node.id === group.currentNodeId && group.kind === 'main') return '当前位置';
  if (node.id === group.currentNodeId && group.kind === 'history') return '上次位置 · 暂停方向';
  return groupLabels[group.kind];
}

function layout(groups: PathCanvasGroup[], vertical: boolean) {
  const nodes: PlacedNode[] = [], positions = new Map<string, Point>();
  const lines: Array<{ id: string; source: string; target: string; kind: PathCanvasGroup['kind']; path: string }> = [];
  let rowOffset = 28, column = 0;
  for (const group of groups) {
    const depth = new Map(group.nodes.map(node => [node.id, 0]));
    // The API rejects cycles. Rank only the explicit edges within this snapshot.
    for (let pass = 0; pass < group.nodes.length; pass++) {
      let changed = false;
      for (const edge of group.edges) {
        if (!depth.has(edge.source) || !depth.has(edge.target)) continue;
        const rank = depth.get(edge.source)! + 1;
        if (rank > depth.get(edge.target)!) { depth.set(edge.target, rank); changed = true; }
      }
      if (!changed) break;
    }
    const occupied = new Map<number, number>();
    const branch = group.parentId && group.branchNodeId ? positions.get(pathNodeKey(group.parentId, group.branchNodeId)) : undefined;
    const baseX = vertical ? 26 + column * (nodeWidth + 64) : branch ? branch.x + nodeWidth + gap : 26;
    const baseY = vertical ? branch ? branch.y + nodeHeight + gap : 28 : rowOffset;
    let highestRow = 0;
    for (const node of group.nodes) {
      const rank = depth.get(node.id) ?? 0, slot = occupied.get(rank) ?? 0;
      occupied.set(rank, slot + 1); highestRow = Math.max(highestRow, slot);
      const position = vertical
        ? { x: baseX + slot * (nodeWidth + 34), y: baseY + rank * (nodeHeight + gap) }
        : { x: baseX + rank * (nodeWidth + gap), y: baseY + slot * (nodeHeight + 28) };
      const key = pathNodeKey(group.id, node.id);
      positions.set(key, position); nodes.push({ key, group, node, position });
    }
    rowOffset = baseY + (highestRow + 1) * (nodeHeight + 28) + 68;
    column++;
  }
  function connect(id: string, source: string, target: string, kind: PathCanvasGroup['kind']) {
    const first = positions.get(source), second = positions.get(target);
    if (!first || !second) return;
    let path: string;
    if (vertical) {
      const x1 = first.x + nodeWidth / 2, y1 = first.y + nodeHeight, x2 = second.x + nodeWidth / 2, y2 = second.y;
      const middle = (y1 + y2) / 2;
      path = `M ${x1} ${y1} C ${x1} ${middle}, ${x2} ${middle}, ${x2} ${y2}`;
    } else {
      const x1 = first.x + nodeWidth, y1 = first.y + nodeHeight / 2, x2 = second.x, y2 = second.y + nodeHeight / 2;
      const middle = (x1 + x2) / 2;
      path = `M ${x1} ${y1} C ${middle} ${y1}, ${middle} ${y2}, ${x2} ${y2}`;
    }
    lines.push({ id, source, target, kind, path });
  }
  for (const group of groups) {
    group.edges.forEach((edge, index) => connect(`${group.id}:edge:${index}`, pathNodeKey(group.id, edge.source), pathNodeKey(group.id, edge.target), group.kind));
    if (group.parentId && group.branchNodeId) connect(`${group.id}:branch`, pathNodeKey(group.parentId, group.branchNodeId), pathNodeKey(group.id, group.entryNodeId), group.kind === 'main' ? 'history' : group.kind);
  }
  return { nodes, positions, lines, width: Math.max(260, ...nodes.map(item => item.position.x + nodeWidth + 26)), height: Math.max(200, ...nodes.map(item => item.position.y + nodeHeight + 26)) };
}

export default function LearningPathCanvas({ groups, selected, onSelect, currentKey, focusTarget }: {
  groups: PathCanvasGroup[]; selected: string | null; onSelect: (key: string) => void; currentKey: string | null;
  focusTarget?: { key: string; request: number } | null;
}) {
  const viewport = useRef<HTMLDivElement>(null), viewRef = useRef<View>({ x: 0, y: 0, scale: 1 });
  const [view, setView] = useState(viewRef.current), [vertical, setVertical] = useState(() => window.innerWidth <= 760), [dragging, setDragging] = useState(false);
  const fitMode = useRef(true), size = useRef({ width: 0, height: 0 }), suppressed = useRef(false);
  const pointers = useRef(new Map<number, Point>()), gesture = useRef<{ points: Point[]; view: View; moved: boolean } | null>(null);
  const unique = useId().replaceAll(':', '');
  const signature = JSON.stringify(groups);
  const graph = useMemo(() => layout(groups, vertical), [signature, vertical]);
  function update(value: View) { viewRef.current = value; setView(value); }
  function locate(key: string) {
    const point = graph.positions.get(key);
    if (!point) return;
    const scale = Math.min(maxScale, Math.max(.9, viewRef.current.scale), (size.current.width - 32) / nodeWidth);
    fitMode.current = false;
    update({ scale, x: size.current.width / 2 - (point.x + nodeWidth / 2) * scale, y: size.current.height / 2 - (point.y + nodeHeight / 2) * scale });
  }
  function fit(readable = false) {
    if (!size.current.width || !size.current.height) return;
    const scale = Math.min((size.current.width - 28) / graph.width, (size.current.height - 28) / graph.height, 1);
    if (readable && scale < .9) {
      update({ scale: Math.max(.9, scale), x: 18, y: 18 });
      if (currentKey) locate(currentKey);
      else {
        const entry = graph.nodes.find(item => item.group.kind === 'main' && item.node.id === item.group.entryNodeId) ?? graph.nodes[0];
        if (entry) locate(entry.key);
      }
    } else update({ scale, x: Math.max(0, (size.current.width - graph.width * scale) / 2), y: Math.max(0, (size.current.height - graph.height * scale) / 2) });
    fitMode.current = true;
  }
  function zoom(next: number, point: Point) {
    const previous = viewRef.current, scale = clamp(next), ratio = scale / previous.scale;
    update({ scale, x: point.x - (point.x - previous.x) * ratio, y: point.y - (point.y - previous.y) * ratio }); fitMode.current = false;
  }
  useLayoutEffect(() => {
    const root = viewport.current;
    if (!root) return;
    fitMode.current = true;
    const measure = () => { size.current = { width: root.clientWidth, height: root.clientHeight }; setVertical(window.innerWidth <= 760); if (fitMode.current) fit(true); };
    measure(); const observer = new ResizeObserver(measure); observer.observe(root);
    const wheel = (event: WheelEvent) => { event.preventDefault(); const rect = root.getBoundingClientRect(); zoom(viewRef.current.scale * Math.exp(-event.deltaY * .0015), { x: event.clientX - rect.left, y: event.clientY - rect.top }); };
    root.addEventListener('wheel', wheel, { passive: false });
    return () => { observer.disconnect(); root.removeEventListener('wheel', wheel); };
  }, [graph, currentKey]);
  useLayoutEffect(() => { if (focusTarget) locate(focusTarget.key); }, [focusTarget, graph]);
  function point(event: ReactPointerEvent): Point { const rect = viewport.current!.getBoundingClientRect(); return { x: event.clientX - rect.left, y: event.clientY - rect.top }; }
  function begin(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    const interactive = (event.target as Element).closest('button');
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
    if (!start || start.points.length !== current.length) return;
    if (current.length === 1) {
      const x = current[0].x - start.points[0].x, y = current[0].y - start.points[0].y;
      if (!start.moved && Math.hypot(x, y) < 4) return;
      update({ ...start.view, x: start.view.x + x, y: start.view.y + y });
    } else {
      const middle = (points: Point[]) => ({ x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 });
      const distance = (points: Point[]) => Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
      const origin = middle(start.points), next = middle(current), scale = clamp(start.view.scale * distance(current) / Math.max(1, distance(start.points))), ratio = scale / start.view.scale;
      update({ scale, x: next.x - (origin.x - start.view.x) * ratio, y: next.y - (origin.y - start.view.y) * ratio });
    }
    start.moved = true; suppressed.current = true; fitMode.current = false; setDragging(true);
  }
  function end(event: ReactPointerEvent<HTMLDivElement>) {
    pointers.current.delete(event.pointerId);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    gesture.current = pointers.current.size ? { points: [...pointers.current.values()].slice(0, 2), view: viewRef.current, moved: false } : null;
    setDragging(false); if (!pointers.current.size) window.setTimeout(() => { suppressed.current = false; }, 0);
  }
  return <div className="learning-path-canvas">
    <div className="learning-path-canvas__toolbar" aria-label="路径图操作"><div className="learning-path-legend">{(['main', 'history', 'candidate'] as const).map(kind => <span key={kind}><i className={`is-${kind}`} />{groupLabels[kind]}</span>)}</div><div className="learning-path-canvas__controls">
      <button type="button" aria-label="缩小路径图" disabled={view.scale <= minScale} onClick={() => zoom(viewRef.current.scale / 1.25, { x: size.current.width / 2, y: size.current.height / 2 })}><Minus size={16} /></button><button type="button" aria-label="放大路径图" disabled={view.scale >= maxScale} onClick={() => zoom(viewRef.current.scale * 1.25, { x: size.current.width / 2, y: size.current.height / 2 })}><Plus size={16} /></button><button type="button" onClick={() => fit()}><Maximize2 size={15} />全图</button><button type="button" disabled={!currentKey} onClick={() => { if (currentKey) { locate(currentKey); onSelect(currentKey); } }}><LocateFixed size={15} />当前位置</button>
    </div></div>
    <p id={`${unique}-help`} className="learning-path-sr-only">拖动空白处移动，滚轮或双指缩放。键盘方向键移动，加减号缩放，Home 查看全图。选择阶段后查看任务和原记录。</p>
    <div ref={viewport} role="group" aria-label="学习路径图" aria-describedby={`${unique}-help`} tabIndex={0} className={`learning-path-canvas__viewport ${dragging ? 'is-dragging' : ''}`}
      onPointerDown={begin} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onClickCapture={event => { if (suppressed.current) { event.preventDefault(); event.stopPropagation(); } }}
      onKeyDown={event => {
        if (event.target !== event.currentTarget) return;
        const moves: Record<string, Point> = { ArrowLeft: { x: 48, y: 0 }, ArrowRight: { x: -48, y: 0 }, ArrowUp: { x: 0, y: 48 }, ArrowDown: { x: 0, y: -48 } };
        if (moves[event.key]) { event.preventDefault(); fitMode.current = false; update({ ...viewRef.current, x: viewRef.current.x + moves[event.key].x, y: viewRef.current.y + moves[event.key].y }); }
        else if (['+', '=', '-'].includes(event.key)) { event.preventDefault(); zoom(viewRef.current.scale * (event.key === '-' ? .8 : 1.25), { x: size.current.width / 2, y: size.current.height / 2 }); }
        else if (event.key === 'Home') { event.preventDefault(); fit(); }
      }}>
      <div className="learning-path-canvas__space" data-path-transform={`${view.x},${view.y},${view.scale}`} style={{ width: graph.width, height: graph.height, transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}>
        <svg className="learning-path-canvas__lines" width={graph.width} height={graph.height}><defs><marker id={`${unique}-arrow`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 8 4 L 0 8 z" /></marker></defs>{graph.lines.map(line => <path key={line.id} data-path-edge={line.id} className={`is-${line.kind}`} d={line.path} markerEnd={`url(#${unique}-arrow)`} />)}</svg>
        {graph.nodes.map(item => <button key={item.key} type="button" data-path-node={item.key} data-path-node-id={item.node.id} className={`learning-path-canvas__node is-${item.group.kind} ${item.group.kind === 'main' && item.node.id === item.group.currentNodeId ? 'is-current' : ''}`} style={{ left: item.position.x, top: item.position.y, width: nodeWidth, height: nodeHeight }} aria-pressed={selected === item.key} aria-label={`${item.node.title} · ${nodeLabel(item.group, item.node)}`} title={item.node.title} onClick={() => onSelect(item.key)} onFocus={event => { if (event.currentTarget.matches(':focus-visible')) { const rect = event.currentTarget.getBoundingClientRect(), outer = viewport.current!.getBoundingClientRect(); if (rect.left < outer.left || rect.right > outer.right || rect.top < outer.top || rect.bottom > outer.bottom) locate(item.key); } }}><small>{nodeLabel(item.group, item.node)}{item.node.action_ids.length > 0 && ` · ${item.node.action_ids.length}项任务`}</small><strong>{item.node.title}</strong></button>)}
      </div>
    </div>
  </div>;
}
