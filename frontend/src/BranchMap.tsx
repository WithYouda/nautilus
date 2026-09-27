import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { GitBranch, Maximize2, Minus, Plus, X } from 'lucide-react';
import DialogPortal from './DialogPortal';
import { getBranchMap, renameBranchNode, type BranchMapData, type BranchMapNode } from './api';
import './styles/branch-map.css';

type BranchKind = 'conversation' | 'discussion';
type Props = {
  kind: BranchKind;
  id: string;
  disabled?: boolean;
  revision?: string;
  onNavigate: (id: string, sourceId?: string) => Promise<void> | void;
  onRenamed?: () => Promise<void> | void;
};

type PlacedNode = { node: BranchMapNode; depth: number; row: number; x: number; y: number };
const NODE_WIDTH = 184;
const NODE_HEIGHT = 66;
const COLUMN_GAP = 44;
const ROW_GAP = 22;
const PAD = 32;

function arrange(nodes: BranchMapNode[]): { placed: PlacedNode[]; width: number; height: number } {
  const byId = new Map(nodes.map(node => [node.id, node]));
  const children = new Map<string, BranchMapNode[]>();
  const roots: BranchMapNode[] = [];
  for (const node of nodes) {
    if (node.parent_id && node.parent_id !== node.id && byId.has(node.parent_id)) {
      const siblings = children.get(node.parent_id) ?? [];
      siblings.push(node);
      children.set(node.parent_id, siblings);
    } else roots.push(node);
  }
  const byDate = (a: BranchMapNode, b: BranchMapNode) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id);
  roots.sort(byDate);
  for (const siblings of children.values()) siblings.sort(byDate);
  const placed: PlacedNode[] = [];
  const visited = new Set<string>();
  let row = 0;
  let maxDepth = 0;
  const visit = (node: BranchMapNode, depth: number) => {
    if (visited.has(node.id)) return;
    visited.add(node.id);
    placed.push({ node, depth, row, x: PAD + depth * (NODE_WIDTH + COLUMN_GAP), y: PAD + row * (NODE_HEIGHT + ROW_GAP) });
    row += 1;
    maxDepth = Math.max(maxDepth, depth);
    for (const child of children.get(node.id) ?? []) visit(child, depth + 1);
  };
  for (const root of roots) visit(root, 0);
  for (const node of nodes) visit(node, 0);
  return { placed, width: PAD * 2 + (maxDepth + 1) * NODE_WIDTH + maxDepth * COLUMN_GAP, height: PAD * 2 + Math.max(row, 1) * NODE_HEIGHT + Math.max(row - 1, 0) * ROW_GAP };
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
      setSelectedId(result.current_id);
      setLoading(false);
    }).catch(reason => {
      if (request !== requestRef.current) return;
      setError(message(reason, '分支图加载失败'));
      setLoading(false);
    });
    return () => { if (request === requestRef.current) requestRef.current += 1; };
  }, [kind, id, revision, refresh]);

  const layout = useMemo(() => arrange(data?.nodes ?? []), [data]);
  const selected = data?.nodes.find(node => node.id === selectedId) ?? null;
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
  }, [open, fit]);

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busyRef.current) { setEditingId(null); setOpen(false); }
      if (event.key !== 'Tab') return;
      const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)') ?? []);
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

  function zoom(factor: number) {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const next = Math.min(2, Math.max(.3, view.scale * factor));
    const cx = viewport.clientWidth / 2;
    const cy = viewport.clientHeight / 2;
    setView({ scale: next, x: cx - (cx - view.x) * next / view.scale, y: cy - (cy - view.y) * next / view.scale });
  }

  function startDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || (event.target as HTMLElement).closest('button')) return;
    dragRef.current = { x: event.clientX, y: event.clientY, panX: view.x, panY: view.y };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveDrag(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (drag) setView(previous => ({ ...previous, x: drag.panX + event.clientX - drag.x, y: drag.panY + event.clientY - drag.y }));
  }

  const entries = layout.placed.map(({ node, depth }) => <button key={node.id} className={`branch-map-tree-item${node.id === currentId ? ' is-current' : ''}${!node.available ? ' is-unavailable' : ''}`} type="button" style={{ paddingLeft: `${10 + Math.min(depth, 8) * 14}px` }} disabled={!node.available || disabled || busy} aria-current={node.id === currentId ? 'page' : undefined} title={node.title} onClick={() => void navigate(node.id)}><span className="branch-map-tree-guide" aria-hidden="true">{depth > 0 ? '↳' : '●'}</span><span className="branch-map-tree-title">{node.title}</span>{node.id === currentId && <span className="branch-map-current">当前</span>}</button>);

  return <aside className="branch-map-sidebar" aria-label="分支图">
    <div className="branch-map-sidebar-main">
      <div className="branch-map-sidebar-heading"><span><GitBranch size={14} />分支图</span><button className="branch-map-expand" type="button" disabled={loading || Boolean(error)} onClick={() => setOpen(true)}><Maximize2 size={13} />放大分支图</button></div>
      {loading ? <p className="branch-map-state">正在加载分支图…</p> : error ? <div className="branch-map-state" role="alert"><p>{error}</p><button type="button" onClick={() => setRefresh(value => value + 1)}>重试</button></div> : entries.length ? <div className="branch-map-tree" role="group" aria-label="分支列表">{entries}</div> : <p className="branch-map-state">暂无分支。</p>}
    </div>
    <button className="branch-map-mobile-trigger" type="button" onClick={() => setOpen(true)}><GitBranch size={15} />分支图</button>
    {open && <DialogPortal><div className="branch-map-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !busy) setOpen(false); }}><section ref={dialogRef} className="branch-map-dialog" role="dialog" aria-modal="true" aria-label="分支图"><header className="branch-map-dialog-header"><div><strong>分支图</strong><span>查看对话之间的分出关系</span></div><button ref={closeRef} className="branch-map-icon" type="button" aria-label="关闭分支图" disabled={busy} onClick={() => setOpen(false)}><X size={18} /></button></header>
      <div className="branch-map-dialog-body"><div className="branch-map-visual">{loading ? <p className="branch-map-visual-state">正在加载分支图…</p> : error ? <div className="branch-map-visual-state" role="alert"><p>{error}</p><button type="button" onClick={() => setRefresh(value => value + 1)}>重试</button></div> : <><div className="branch-map-toolbar"><button type="button" aria-label="缩小" onClick={() => zoom(1 / 1.25)}><Minus size={15} /></button><span>{Math.round(view.scale * 100)}%</span><button type="button" aria-label="放大" onClick={() => zoom(1.25)}><Plus size={15} /></button><button type="button" onClick={fit}>适应画布</button></div><div ref={viewportRef} className="branch-map-viewport" onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={() => { dragRef.current = null; }} onPointerCancel={() => { dragRef.current = null; }}><div className="branch-map-canvas" style={{ width: layout.width, height: layout.height, transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}><svg className="branch-map-lines" width={layout.width} height={layout.height} aria-hidden="true">{layout.placed.map(child => { const parent = layout.placed.find(item => item.node.id === child.node.parent_id); return parent ? <path key={child.node.id} d={`M ${parent.x + NODE_WIDTH} ${parent.y + NODE_HEIGHT / 2} C ${parent.x + NODE_WIDTH + 22} ${parent.y + NODE_HEIGHT / 2}, ${child.x - 22} ${child.y + NODE_HEIGHT / 2}, ${child.x} ${child.y + NODE_HEIGHT / 2}`} /> : null; })}</svg>{layout.placed.map(({ node, x, y }) => <button key={node.id} className={`branch-map-node${node.id === currentId ? ' is-current' : ''}${node.id === selectedId ? ' is-selected' : ''}${!node.available ? ' is-unavailable' : ''}`} type="button" style={{ left: x, top: y, width: NODE_WIDTH, height: NODE_HEIGHT }} onClick={() => { setSelectedId(node.id); setEditingId(null); setActionError(''); }} aria-pressed={node.id === selectedId}><strong>{node.title}</strong><small>{node.id === currentId ? '当前' : node.available ? '可打开' : '不可打开'}</small></button>)}</div></div></>}</div>
      <div className="branch-map-detail"><strong>节点详情</strong>{selected ? <><p className="branch-map-detail-title">{selected.title}</p>{selected.source_excerpt && <p className="branch-map-excerpt">从这里分出：{selected.source_excerpt}</p>}{!selected.available && <p className="branch-map-muted">此节点不可打开</p>}<div className="branch-map-detail-actions"><button type="button" disabled={!selected.available || disabled || busy} onClick={() => void navigate(selected.id)}>打开{kind === 'conversation' ? '对话' : '讨论'}</button>{selected.parent_id && selected.source_id && <button type="button" disabled={disabled || busy || !data?.nodes.some(node => node.id === selected.parent_id && node.available)} onClick={() => void navigate(selected.parent_id!, selected.source_id!)}>查看分出位置</button>}</div>{selected.available && (editingId === selected.id ? <form className="branch-map-rename" onSubmit={event => void rename(event)}><label htmlFor="branch-map-title">修改标题</label><input id="branch-map-title" autoFocus maxLength={60} value={draft} disabled={disabled || busy} onChange={event => setDraft(event.target.value)} /><div><button type="submit" disabled={disabled || busy || !draft.trim()}>保存</button><button type="button" disabled={busy} onClick={() => setEditingId(null)}>取消</button></div></form> : <button className="branch-map-edit-trigger" type="button" disabled={disabled || busy} onClick={() => { setDraft(selected.title); setEditingId(selected.id); setActionError(''); }}>编辑标题</button>)}</> : <p className="branch-map-muted">选择一个节点查看详情。</p>}{actionError && <p className="branch-map-error" role="alert">{actionError}</p>}</div></div>
    </section></div></DialogPortal>}
  </aside>;
}
