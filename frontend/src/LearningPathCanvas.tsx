import { useId, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { ChevronDown, ChevronRight, LocateFixed, Maximize2, Minus, Plus } from 'lucide-react';
import type { LearningAction } from './api';
import type { LearningPathEdge, LearningPathNode } from './learning-path-api';

export type PathCanvasGroup = {
  id: string; kind: 'main' | 'history' | 'candidate'; title: string;
  nodes: LearningPathNode[]; edges: LearningPathEdge[]; entryNodeId: string; currentNodeId: string | null;
  parentId?: string | null; branchNodeId?: string | null;
};
type Point = { x: number; y: number };
type View = Point & { scale: number };
type PlacedNode = { key: string; group: PathCanvasGroup; node: LearningPathNode; position: Point; height: number; expanded: boolean };
const nodeWidth = 232, nodeHeight = 104, taskHeight = 98, taskGap = 8, gap = 58;
const minScale = .35, maxScale = 1.8;
const clamp = (value: number) => Math.min(maxScale, Math.max(minScale, value));
export const pathNodeKey = (groupId: string, nodeId: string) => `${groupId}:${nodeId}`;
const groupLabels = { main: '当前路线', history: '暂停方向', candidate: '待采用' };
function nodeLabel(group: PathCanvasGroup, node: LearningPathNode) {
  if (node.id === group.currentNodeId && group.kind === 'main') return '当前位置';
  if (node.id === group.currentNodeId && group.kind === 'history') return '上次位置 · 暂停方向';
  return groupLabels[group.kind];
}

function layout(groups: PathCanvasGroup[], vertical: boolean, expansions: Record<string, boolean>) {
  const nodes: PlacedNode[] = [], positions = new Map<string, PlacedNode>();
  const lines: Array<{ id: string; source: string; target: string; kind: PathCanvasGroup['kind']; path: string }> = [];
  const groupBounds = new Map<string, { left: number; top: number; bottom: number; right: number }>();
  const edgeChannels = new Map<string, number>();
  let branchChannel = 0;
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
    const sizes = new Map(group.nodes.map(node => {
      const key = pathNodeKey(group.id, node.id);
      const expanded = expansions[key] ?? group.kind !== 'history';
      return [node.id, { expanded, height: nodeHeight + (expanded && node.action_ids.length ? 14 + node.action_ids.length * (taskHeight + taskGap) : 0) }];
    }));
    const rankHeights = new Map<number, number>();
    for (const node of group.nodes) rankHeights.set(depth.get(node.id)!, Math.max(rankHeights.get(depth.get(node.id)!) ?? 0, sizes.get(node.id)!.height));
    const rankOffsets = new Map<number, number>();
    let nextRankY = 0;
    for (let rank = 0; rank <= Math.max(0, ...depth.values()); rank++) { rankOffsets.set(rank, nextRankY); nextRankY += (rankHeights.get(rank) ?? nodeHeight) + gap; }
    const occupied = new Map<number, { count: number; height: number }>();
    const branch = group.parentId && group.branchNodeId ? positions.get(pathNodeKey(group.parentId, group.branchNodeId)) : undefined;
    const baseX = vertical ? 26 + column * (nodeWidth + 90) : branch ? branch.position.x + nodeWidth + gap : 52;
    const baseY = vertical ? branch ? branch.position.y + branch.height + gap : 28 : rowOffset;
    let bottom = baseY, right = baseX + nodeWidth;
    for (const node of group.nodes) {
      const rank = depth.get(node.id) ?? 0, slot = occupied.get(rank) ?? { count: 0, height: 0 }, dimensions = sizes.get(node.id)!;
      occupied.set(rank, { count: slot.count + 1, height: slot.height + dimensions.height + 28 });
      const position = vertical
        ? { x: baseX + slot.count * (nodeWidth + 34), y: baseY + rankOffsets.get(rank)! }
        : { x: baseX + rank * (nodeWidth + gap), y: baseY + slot.height };
      const key = pathNodeKey(group.id, node.id);
      const placed = { key, group, node, position, ...dimensions };
      positions.set(key, placed); nodes.push(placed);
      bottom = Math.max(bottom, position.y + dimensions.height); right = Math.max(right, position.x + nodeWidth);
    }
    groupBounds.set(group.id, { left: baseX, top: baseY, bottom, right });
    rowOffset = bottom + 68 + group.edges.length * 8;
    column += Math.max(1, ...[...occupied.values()].map(slot => slot.count));
  }
  const globalRight = Math.max(0, ...nodes.map(item => item.position.x + nodeWidth));
  const globalBottom = Math.max(0, ...nodes.map(item => item.position.y + item.height));
  function connect(id: string, source: string, target: string, kind: PathCanvasGroup['kind'], branch = false) {
    const first = positions.get(source), second = positions.get(target);
    if (!first || !second) return;
    const channelIndex = edgeChannels.get(first.group.id) ?? 0;
    edgeChannels.set(first.group.id, channelIndex + 1);
    const sourceBounds = groupBounds.get(first.group.id)!, targetBounds = groupBounds.get(second.group.id)!;
    const sourceRankBottom = Math.max(...nodes.filter(item => item.group.id === first.group.id && item.position.y === first.position.y).map(item => item.position.y + item.height));
    let path: string;
    if (branch) {
      const index = branchChannel++;
      if (vertical) {
        const x1 = first.position.x + nodeWidth / 2, y1 = first.position.y + first.height, x2 = second.position.x + nodeWidth / 2, y2 = second.position.y;
        const sourceLane = sourceBounds.right + 22, targetLane = targetBounds.left - 22, bottomLane = globalBottom + 22 + index * 6;
        path = `M ${x1} ${y1} L ${x1} ${sourceRankBottom + gap / 2} L ${sourceLane} ${sourceRankBottom + gap / 2} L ${sourceLane} ${bottomLane} L ${targetLane} ${bottomLane} L ${targetLane} ${targetBounds.top - 22} L ${x2} ${targetBounds.top - 22} L ${x2} ${y2}`;
      } else {
        const x1 = first.position.x + nodeWidth, y1 = first.position.y + nodeHeight / 2, x2 = second.position.x, y2 = second.position.y + nodeHeight / 2;
        const rightLane = globalRight + 22 + index * 6;
        path = `M ${x1} ${y1} L ${x1 + gap / 2} ${y1} L ${x1 + gap / 2} ${sourceBounds.top - 22} L ${rightLane} ${sourceBounds.top - 22} L ${rightLane} ${targetBounds.top - 22} L ${x2 - gap / 2} ${targetBounds.top - 22} L ${x2 - gap / 2} ${y2} L ${x2} ${y2}`;
      }
    } else if (vertical) {
      const x1 = first.position.x + nodeWidth / 2, y1 = first.position.y + first.height, x2 = second.position.x + nodeWidth / 2, y2 = second.position.y;
      if (first.group.id === second.group.id && nodes.some(item => item.group.id === first.group.id && item.position.y > first.position.y && item.position.y < second.position.y)) {
        const channel = sourceBounds.right + 22 + channelIndex * 6;
        path = `M ${x1} ${y1} L ${x1} ${sourceRankBottom + gap / 2} L ${channel} ${sourceRankBottom + gap / 2} L ${channel} ${y2 - gap / 2} L ${x2} ${y2 - gap / 2} L ${x2} ${y2}`;
      } else path = `M ${x1} ${y1} L ${x1} ${y2 - gap / 2} L ${x2} ${y2 - gap / 2} L ${x2} ${y2}`;
    } else {
      const x1 = first.position.x + nodeWidth, y1 = first.position.y + nodeHeight / 2, x2 = second.position.x, y2 = second.position.y + nodeHeight / 2;
      const middle = (x1 + x2) / 2;
      if (first.group.id === second.group.id && x2 - x1 > gap + 1) {
        const channel = groupBounds.get(first.group.id)!.bottom + 22 + channelIndex * 6;
        path = `M ${x1} ${y1} L ${x1 + 18} ${y1} L ${x1 + 18} ${channel} L ${x2 - 18} ${channel} L ${x2 - 18} ${y2} L ${x2} ${y2}`;
      } else path = `M ${x1} ${y1} C ${middle} ${y1}, ${middle} ${y2}, ${x2} ${y2}`;
    }
    lines.push({ id, source, target, kind, path });
  }
  for (const group of groups) {
    group.edges.forEach((edge, index) => connect(`${group.id}:edge:${index}`, pathNodeKey(group.id, edge.source), pathNodeKey(group.id, edge.target), group.kind));
    if (group.parentId && group.branchNodeId) connect(`${group.id}:branch`, pathNodeKey(group.parentId, group.branchNodeId), pathNodeKey(group.id, group.entryNodeId), group.kind === 'main' ? 'history' : group.kind, true);
  }
  return { nodes, positions, lines, width: Math.max(284, globalRight + 48 + lines.length * 6), height: Math.max(200, globalBottom + 48 + lines.length * 8) };
}

export default function LearningPathCanvas({ groups, selected, selectedTask, actions, onSelect, onTaskSelect, currentKey, focusTarget }: {
  groups: PathCanvasGroup[]; selected: string | null; onSelect: (key: string) => void; currentKey: string | null;
  actions: LearningAction[]; selectedTask: { nodeKey: string; actionId: string } | null; onTaskSelect: (key: string, actionId: string) => void;
  focusTarget?: { key: string; request: number } | null;
}) {
  const viewport = useRef<HTMLDivElement>(null), viewRef = useRef<View>({ x: 0, y: 0, scale: 1 });
  const selectionRef = useRef(selected), taskRef = useRef(selectedTask); selectionRef.current = selected; taskRef.current = selectedTask;
  const [view, setView] = useState(viewRef.current), [vertical, setVertical] = useState(() => window.innerWidth <= 760), [dragging, setDragging] = useState(false);
  const [expansions, setExpansions] = useState<Record<string, boolean>>({});
  const fitMode = useRef(true), size = useRef({ width: 0, height: 0 }), suppressed = useRef(false);
  const pointers = useRef(new Map<number, Point>()), gesture = useRef<{ points: Point[]; view: View; moved: boolean } | null>(null);
  const unique = useId().replaceAll(':', '');
  const signature = JSON.stringify(groups);
  const graph = useMemo(() => layout(groups, vertical, expansions), [signature, vertical, expansions]);
  useLayoutEffect(() => { if (selectedTask) setExpansions(previous => previous[selectedTask.nodeKey] === true ? previous : { ...previous, [selectedTask.nodeKey]: true }); }, [selectedTask?.nodeKey, selectedTask?.actionId]);
  function update(value: View) { viewRef.current = value; setView(value); }
  function locate(key: string, actionId?: string) {
    const placed = graph.positions.get(key);
    if (!placed) return;
    const point = placed.position;
    const scale = Math.min(maxScale, Math.max(.9, viewRef.current.scale), (size.current.width - 32) / nodeWidth);
    fitMode.current = false;
    const taskId = actionId ?? (taskRef.current?.nodeKey === key ? taskRef.current.actionId : undefined);
    const taskIndex = taskId ? placed.node.action_ids.indexOf(taskId) : -1;
    const centerY = taskIndex >= 0 ? point.y + nodeHeight + 14 + taskIndex * (taskHeight + taskGap) + taskHeight / 2 : point.y + nodeHeight / 2;
    update({ scale, x: size.current.width / 2 - (point.x + nodeWidth / 2) * scale, y: size.current.height / 2 - centerY * scale });
  }
  function fit(readable = false) {
    if (!size.current.width || !size.current.height) return;
    const scale = Math.min((size.current.width - 28) / graph.width, (size.current.height - 28) / graph.height, 1);
    if (readable && scale < .9) {
      update({ scale: Math.max(.9, scale), x: 18, y: 18 });
      if (selectionRef.current) locate(selectionRef.current);
      else if (currentKey) locate(currentKey);
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
        {graph.nodes.map(item => <section key={item.key} data-path-stage={item.key} className={`learning-path-canvas__stage is-${item.group.kind} ${item.group.kind === 'main' && item.node.id === item.group.currentNodeId ? 'is-current' : ''} ${selected === item.key ? 'is-selected' : ''}`} style={{ left: item.position.x, top: item.position.y, width: nodeWidth, height: item.height }} aria-label={item.node.title}>
          <div className="learning-path-canvas__stage-header"><button type="button" data-path-node={item.key} data-path-node-id={item.node.id} className="learning-path-canvas__node" aria-pressed={selected === item.key} aria-label={`${item.node.title} · ${nodeLabel(item.group, item.node)}`} title={item.node.title} onClick={() => onSelect(item.key)} onFocus={event => { if (event.currentTarget.matches(':focus-visible')) { const rect = event.currentTarget.getBoundingClientRect(), outer = viewport.current!.getBoundingClientRect(); if (rect.left < outer.left || rect.right > outer.right || rect.top < outer.top || rect.bottom > outer.bottom) locate(item.key); } }}><small>{nodeLabel(item.group, item.node)}</small><strong>{item.node.title}</strong></button>
            {!!item.node.action_ids.length && <button className="learning-path-canvas__expand" type="button" aria-label={`${item.expanded ? '收起' : '展开'}阶段任务：${item.node.title}`} aria-expanded={item.expanded} onClick={() => { if (selectedTask?.nodeKey === item.key) onSelect(item.key); setExpansions(previous => ({ ...previous, [item.key]: !item.expanded })); }}>{item.expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}<span>{item.node.action_ids.length}项任务</span></button>}
          </div>
          {item.expanded && !!item.node.action_ids.length && <div className="learning-path-canvas__tasks">{item.node.action_ids.map(id => {
            const task = actions.find(action => action.id === id), removed = task?.deleted || task?.status === 'cancelled';
            return <button key={id} type="button" data-path-task={id} data-path-canvas-task={`${item.key}:${id}`} data-path-action-id={id} className="learning-path-canvas__task" aria-pressed={selectedTask?.nodeKey === item.key && selectedTask.actionId === id} aria-label={task?.title ?? '任务当前不可查看'} title={task?.title ?? '任务当前不可查看'} onClick={() => onTaskSelect(item.key, id)} onFocus={event => { if (event.currentTarget.matches(':focus-visible')) { const rect = event.currentTarget.getBoundingClientRect(), outer = viewport.current!.getBoundingClientRect(); if (rect.left < outer.left || rect.right > outer.right || rect.top < outer.top || rect.bottom > outer.bottom) locate(item.key, id); } }}><strong>{task?.title ?? '任务当前不可查看'}</strong><small>{removed ? '已删除 · 查看记录' : task?.status === 'completed' ? '已完成 · 回看记录' : item.group.kind === 'history' ? '查看记录' : item.group.kind === 'candidate' ? '待采用' : '任务'}</small></button>;
          })}</div>}
        </section>)}
      </div>
    </div>
  </div>;
}
