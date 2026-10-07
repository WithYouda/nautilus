import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { GitBranch, Minus, Plus, X } from 'lucide-react';
import DialogPortal from './DialogPortal';
import { getBranchMap, renameBranchNode, type BranchMapData, type BranchMapNode } from './api';
import './styles/branch-map.css';
import BranchComparison from './BranchComparison';

type BranchKind = 'conversation' | 'discussion';
type Props = {
  kind: BranchKind;
  id: string;
  disabled?: boolean;
  revision?: string;
  onNavigate: (id: string, sourceId?: string) => Promise<void> | void;
  onRenamed?: () => Promise<void> | void;
};

type VisibleNode = BranchMapNode & { displayParentId: string | null; missingSource: boolean };
type PlacedNode = { node: VisibleNode; depth: number; row: number; x: number; y: number };
const NODE_WIDTH = 184;
const NODE_HEIGHT = 66;
const COLUMN_GAP = 44;
const ROW_GAP = 22;
const PAD = 32;

function visibleNodes(nodes: BranchMapNode[]): VisibleNode[] {
  const byId = new Map(nodes.map(node => [node.id, node]));
  return nodes.filter(node => node.available).map(node => {
    if (node.merge_sources?.length) return { ...node, displayParentId: null, missingSource: node.merge_sources.some(source => !source.available) };
    let parent = node.parent_id ? byId.get(node.parent_id) : undefined;
    let missingSource = Boolean(node.parent_id && !parent);
    const seen = new Set([node.id]);
    while (parent && !parent.available && !seen.has(parent.id)) {
      seen.add(parent.id);
      missingSource = true;
      parent = parent.parent_id ? byId.get(parent.parent_id) : undefined;
    }
    return { ...node, displayParentId: parent && !seen.has(parent.id) ? parent.id : null, missingSource };
  });
}

function inputNodes(node: VisibleNode, byId: Map<string, VisibleNode>) {
  return node.merge_sources?.length
    ? node.merge_sources.filter(source => source.available && byId.has(source.id)).map(source => byId.get(source.id)!)
    : node.displayParentId && byId.has(node.displayParentId) ? [byId.get(node.displayParentId)!] : [];
}

function arrange(nodes: VisibleNode[]): { placed: PlacedNode[]; width: number; height: number } {
  const byId = new Map(nodes.map(node => [node.id, node]));
  const depths = new Map<string, number>();
  const depthOf = (node: VisibleNode, visiting = new Set<string>()): number => {
    if (depths.has(node.id)) return depths.get(node.id)!;
    if (visiting.has(node.id)) return 0;
    const next = new Set(visiting).add(node.id);
    const parents = inputNodes(node, byId);
    const depth = parents.length ? Math.max(...parents.map(parent => depthOf(parent, next))) + 1 : 0;
    depths.set(node.id, depth); return depth;
  };
  const layers = new Map<number, VisibleNode[]>();
  for (const node of nodes) {
    const depth = depthOf(node); layers.set(depth, [...(layers.get(depth) ?? []), node]);
  }
  const maxDepth = Math.max(0, ...layers.keys());
  const y = new Map<string, number>();
  const step = NODE_HEIGHT + ROW_GAP;
  const average = (items: VisibleNode[]) => items.reduce((sum, item) => sum + (y.get(item.id) ?? 0), 0) / items.length;
  function pack(items: VisibleNode[], desired: (node: VisibleNode, index: number) => number) {
    const ordered = items.map((node, index) => ({ node, target: desired(node, index) }))
      .sort((a, b) => a.target - b.target || a.node.created_at.localeCompare(b.node.created_at) || a.node.id.localeCompare(b.node.id));
    let previous = -Infinity;
    for (let start = 0; start < ordered.length;) {
      let end = start + 1;
      while (end < ordered.length && Math.abs(ordered[end].target - ordered[start].target) < 1) end++;
      for (let index = start; index < end; index++) {
        const preferred = ordered[start].target + (index - start - (end - start - 1) / 2) * step;
        previous = Math.max(preferred, previous + step); y.set(ordered[index].node.id, previous);
      }
      start = end;
    }
  }
  for (let depth = 0; depth <= maxDepth; depth++) pack(layers.get(depth) ?? [], (node, index) => {
    const parents = inputNodes(node, byId); return parents.length ? average(parents) : index * step;
  });
  // Center upstream nodes on their children while keeping each column collision-free.
  for (let depth = maxDepth - 1; depth >= 0; depth--) pack(layers.get(depth) ?? [], node => {
    const children = nodes.filter(child => inputNodes(child, byId).some(parent => parent.id === node.id));
    return children.length ? average(children) : y.get(node.id) ?? 0;
  });
  const minimum = Math.min(0, ...y.values());
  const placed = nodes.map(node => ({ node, depth: depths.get(node.id)!, row: 0,
    x: PAD + depths.get(node.id)! * (NODE_WIDTH + COLUMN_GAP), y: PAD + y.get(node.id)! - minimum }));
  return { placed, width: PAD * 2 + (maxDepth + 1) * NODE_WIDTH + maxDepth * COLUMN_GAP,
    height: Math.max(PAD * 2 + NODE_HEIGHT, ...placed.map(item => item.y + NODE_HEIGHT + PAD)) };
}

function connectionPath(parent: PlacedNode, child: PlacedNode) {
  const x1 = parent.x + NODE_WIDTH, y1 = parent.y + NODE_HEIGHT / 2;
  const x2 = child.x, y2 = child.y + NODE_HEIGHT / 2;
  if (child.depth - parent.depth > 1) return `M ${x1} ${y1} H ${x1 + 14} V ${PAD / 3} H ${x2 - 14} V ${y2} H ${x2}`;
  return `M ${x1} ${y1} C ${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}`;
}

function message(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export default function BranchMap({ kind, id, disabled = false, revision, onNavigate, onRenamed }: Props) {
  const [data, setData] = useState<BranchMapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [open, setOpen] = useState(false);
  const [comparing, setComparing] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [actionError, setActionError] = useState('');
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const actionRef = useRef(0);
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 });
  const requestRef = useRef(0);
  const identityRef = useRef(`${kind}:${id}`);

  useEffect(() => {
    const identity = `${kind}:${id}`;
    if (identityRef.current !== identity) {
      identityRef.current = identity;
      actionRef.current += 1;
      busyRef.current = false;
      setBusy(false);
      setOpen(false);
    }
    if (!open) return;
    const request = ++requestRef.current;
    setData(null);
    setLoading(true);
    setError('');
    setActionError('');
    setSelectedId(null);
    setEditingId(null);
    getBranchMap(kind, id).then(result => {
      if (request !== requestRef.current) return;
      setData(result);
      setSelectedId(result.nodes.find(node => node.id === result.current_id && node.available)?.id ?? result.nodes.find(node => node.available)?.id ?? null);
      setLoading(false);
    }).catch(reason => {
      if (request !== requestRef.current) return;
      setError(message(reason, '分支图加载失败'));
      setLoading(false);
    });
    return () => { if (request === requestRef.current) requestRef.current += 1; };
  }, [kind, id, revision, refresh, open]);

  const nodes = useMemo(() => visibleNodes(data?.nodes ?? []), [data]);
  const layout = useMemo(() => arrange(nodes), [nodes]);
  const selected = nodes.find(node => node.id === selectedId) ?? null;
  const currentId = data?.current_id ?? id;

  const fit = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const scale = Math.min(1, (viewport.clientWidth - 32) / layout.width, (viewport.clientHeight - 32) / layout.height);
    setView({ scale, x: (viewport.clientWidth - layout.width * scale) / 2, y: (viewport.clientHeight - layout.height * scale) / 2 });
  }, [layout.width, layout.height]);

  useEffect(() => {
    if (!open) return;
    const frame = requestAnimationFrame(fit);
    const viewport = viewportRef.current;
    if (!viewport) return () => cancelAnimationFrame(frame);
    const observer = new ResizeObserver(fit);
    observer.observe(viewport);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); };
  }, [open, comparing, fit, loading, error]);

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busyRef.current) { setEditingId(null); setOpen(false); }
      if (event.key !== 'Tab') return;
      const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary') ?? []);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!dialogRef.current?.contains(document.activeElement)) { event.preventDefault(); first.focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => { window.removeEventListener('keydown', onKeyDown); if (previousFocus?.isConnected) previousFocus.focus(); };
  }, [open]);

  async function navigate(targetId: string, sourceId?: string) {
    if (disabled || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setActionError('');
    const action = ++actionRef.current;
    try {
      await onNavigate(targetId, sourceId);
      if (action === actionRef.current) setOpen(false);
    } catch (reason) {
      if (action === actionRef.current) setActionError(message(reason, '打开失败，请重试'));
    } finally {
      if (action === actionRef.current) { busyRef.current = false; setBusy(false); }
    }
  }

  async function rename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !selected.available || disabled || busyRef.current) return;
    const title = draft.trim();
    if (!title) return;
    busyRef.current = true;
    setBusy(true);
    setActionError('');
    const request = requestRef.current;
    const action = ++actionRef.current;
    try {
      await renameBranchNode(kind, selected.id, title);
      if (request !== requestRef.current || action !== actionRef.current) return;
      setData(previous => previous ? { ...previous, nodes: previous.nodes.map(node => node.id === selected.id ? { ...node, title } : node) } : previous);
      setEditingId(null);
      await onRenamed?.();
    } catch (reason) {
      if (request === requestRef.current && action === actionRef.current) setActionError(message(reason, '标题保存失败，请重试'));
    } finally {
      if (action === actionRef.current) { busyRef.current = false; setBusy(false); }
    }
  }

  const zoomAt = useCallback((factor: number, cx: number, cy: number) => {
    setView(previous => {
      const scale = Math.min(8, Math.max(.02, previous.scale * factor));
      return { scale, x: cx - (cx - previous.x) * scale / previous.scale,
        y: cy - (cy - previous.y) * scale / previous.scale };
    });
  }, []);

  function zoom(factor: number) {
    const viewport = viewportRef.current;
    if (viewport) zoomAt(factor, viewport.clientWidth / 2, viewport.clientHeight / 2);
  }

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!open || loading || error || !viewport) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const bounds = viewport.getBoundingClientRect();
      const pixels = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.clientHeight : 1);
      zoomAt(Math.exp(-Math.max(-500, Math.min(500, pixels)) * .002), event.clientX - bounds.left, event.clientY - bounds.top);
    };
    viewport.addEventListener('wheel', wheel, { passive: false });
    return () => viewport.removeEventListener('wheel', wheel);
  }, [open, comparing, loading, error, zoomAt]);

  function startDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || (event.target as HTMLElement).closest('button')) return;
    dragRef.current = { x: event.clientX, y: event.clientY, panX: view.x, panY: view.y };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveDrag(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (drag) setView(previous => ({ ...previous, x: drag.panX + event.clientX - drag.x, y: drag.panY + event.clientY - drag.y }));
  }

  return <aside className="branch-map-sidebar" aria-label="分支图">
    <button className="branch-map-trigger" type="button" aria-haspopup="dialog" aria-expanded={open} onClick={() => { setData(null); setSelectedId(null); setLoading(true); setComparing(false); setOpen(true); }}><GitBranch size={15} />分支图</button>
    {open && <DialogPortal><div className="branch-map-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !busy) setOpen(false); }}><section ref={dialogRef} className="branch-map-dialog" role="dialog" aria-modal="true" aria-label="分支图"><header className="branch-map-dialog-header"><div><strong>分支图</strong><span>滚轮缩放 · 拖动画布</span></div>{!comparing && <button className="branch-map-compare" type="button" disabled={disabled || busy || (data?.nodes.filter(node => node.available).length ?? 0) < 2} onClick={() => setComparing(true)}>合并对话</button>}<button ref={closeRef} className="branch-map-icon" type="button" aria-label="关闭分支图" disabled={busy} onClick={() => setOpen(false)}><X size={18} /></button></header>
      {comparing && data ? <BranchComparison kind={kind} nodes={data.nodes} onBack={() => setComparing(false)} onSaved={async target => { await navigate(target); }} onBusy={value => { busyRef.current = value; setBusy(value); }} /> : <div className="branch-map-dialog-body"><div className="branch-map-visual">{loading ? <p className="branch-map-visual-state">正在加载分支图…</p> : error ? <div className="branch-map-visual-state" role="alert"><p>{error}</p><button type="button" onClick={() => setRefresh(value => value + 1)}>重试</button></div> : !layout.placed.length ? <p className="branch-map-visual-state">暂无可打开的对话。</p> : <><div className="branch-map-toolbar"><button type="button" aria-label="缩小" onClick={() => zoom(1 / 1.25)}><Minus size={15} /></button><span>{Math.round(view.scale * 100)}%</span><button type="button" aria-label="放大" onClick={() => zoom(1.25)}><Plus size={15} /></button><button type="button" onClick={fit}>适应画布</button></div><div ref={viewportRef} className="branch-map-viewport" onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={() => { dragRef.current = null; }} onPointerCancel={() => { dragRef.current = null; }}><div className="branch-map-canvas" style={{ width: layout.width, height: layout.height, transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}><svg className="branch-map-lines" width={layout.width} height={layout.height} aria-hidden="true"><defs><marker id={`merge-arrow-${kind}-${id}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><polygon points="0,0 10,5 0,10" className="branch-map-merge-arrow" /></marker></defs>{layout.placed.flatMap(child => inputNodes(child.node, new Map(layout.placed.map(item => [item.node.id, item.node]))).map(source => { const parent = layout.placed.find(item => item.node.id === source.id)!; const merged = Boolean(child.node.merge_sources?.length); return <path key={`${source.id}:${child.node.id}`} data-source-id={source.id} data-target-id={child.node.id} className={merged ? 'branch-map-merge-line' : undefined} markerEnd={merged ? `url(#merge-arrow-${kind}-${id})` : undefined} strokeDasharray={!merged && child.node.missingSource ? '6 4' : undefined} d={connectionPath(parent, child)} />; }))}</svg>{layout.placed.map(({ node, x, y }) => <button key={node.id} className={`branch-map-node${node.id === currentId ? ' is-current' : ''}${node.id === selectedId ? ' is-selected' : ''}${!node.available ? ' is-unavailable' : ''}${node.merge_sources?.length ? ' is-merged' : ''}`} type="button" style={{ left: x, top: y, width: NODE_WIDTH, height: NODE_HEIGHT }} onClick={() => { setSelectedId(node.id); setEditingId(null); setActionError(''); }} aria-pressed={node.id === selectedId}><strong>{node.title}</strong><small>{node.merge_sources?.length ? '合并对话 · ' : ''}{node.id === currentId ? '当前' : '可打开'}{node.missingSource && ` · ${node.merge_sources?.length ? '部分来源不可用' : node.displayParentId ? '中间对话已删除' : '来源对话已删除'}`}</small></button>)}</div></div></>}</div>
      <div className="branch-map-detail"><strong>节点详情</strong>{selected ? <><p className="branch-map-detail-title">{selected.title}</p>{selected.missingSource && !selected.merge_sources?.length && <p className="branch-map-muted">{selected.displayParentId ? '中间对话已删除，虚线表示经由已删除对话的来源关系。' : '来源对话已删除。'}</p>}{!selected.merge_sources?.length && !selected.missingSource && selected.source_excerpt && <p className="branch-map-excerpt">从这里分出：{selected.source_excerpt}</p>}{!selected.available && <p className="branch-map-muted">此节点不可打开</p>}{Boolean(selected.merge_sources?.length) && <div className="branch-map-merge-sources"><strong>合并来源</strong>{selected.merge_sources?.map((source, index) => <button key={source.id} type="button" disabled={!source.available || busy || disabled} onClick={() => void navigate(source.id, source.source_id)}>{source.available ? `来源${index + 1}：${data?.nodes.find(node => node.id === source.id)?.title ?? '原分支'}` : `来源${index + 1}已不可用`}</button>)}</div>}<div className="branch-map-detail-actions"><button type="button" disabled={!selected.available || disabled || busy} onClick={() => void navigate(selected.id)}>打开{kind === 'conversation' ? '对话' : '讨论'}</button>{!selected.merge_sources?.length && selected.parent_id && selected.source_id && <button type="button" disabled={disabled || busy || !data?.nodes.some(node => node.id === selected.parent_id && node.available)} onClick={() => void navigate(selected.parent_id!, selected.source_id!)}>查看分出位置</button>}</div>{selected.available && (editingId === selected.id ? <form className="branch-map-rename" onSubmit={event => void rename(event)}><label htmlFor="branch-map-title">修改标题</label><input id="branch-map-title" autoFocus maxLength={60} value={draft} disabled={disabled || busy} onChange={event => setDraft(event.target.value)} /><div><button type="submit" disabled={disabled || busy || !draft.trim()}>保存</button><button type="button" disabled={busy} onClick={() => setEditingId(null)}>取消</button></div></form> : <button className="branch-map-edit-trigger" type="button" disabled={disabled || busy} onClick={() => { setDraft(selected.title); setEditingId(selected.id); setActionError(''); }}>编辑标题</button>)}</> : <p className="branch-map-muted">选择一个节点查看详情。</p>}{actionError && <p className="branch-map-error" role="alert">{actionError}</p>}</div></div>}
    {comparing && actionError && <p className="branch-map-error" role="alert">{actionError}</p>}
    </section></div></DialogPortal>}
  </aside>;
}
