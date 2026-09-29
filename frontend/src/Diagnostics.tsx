import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { Bug, Minus, Maximize2, Minimize2, Grip, Pause, Play, RefreshCw, Trash2 } from 'lucide-react';
import { clearDiagnostics, getDiagnosticEntries, getDiagnosticStatus, setDiagnosticEnabled, type DiagnosticEntry, type DiagnosticStatus } from './diagnostics';
import DialogPortal from './DialogPortal';
import './styles/diagnostics.css';

export function DiagnosticSettings({ onOpen }: { onOpen: () => void }) {
  const [status, setStatus] = useState<DiagnosticStatus | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function load() {
    setError('');
    try { setStatus(await getDiagnosticStatus()); }
    catch (cause) { setError(cause instanceof Error ? cause.message : '日志设置无法读取。'); }
  }
  useEffect(() => { void load(); }, []);
  async function toggle(enabled: boolean) {
    setBusy(true); setError('');
    try { setStatus(await setDiagnosticEnabled(enabled)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : '日志设置未保存。'); }
    finally { setBusy(false); }
  }
  return <details className="diagnostic-settings"><summary>高级设置</summary>
    <label className="diagnostic-toggle"><input type="checkbox" checked={status?.enabled ?? false} disabled={!status || busy} onChange={event => void toggle(event.target.checked)} />开启诊断日志</label>
    <p>开启后，右下角显示“日志”入口，可拖动窗口、调整大小或最大化，最小化后回到“日志”按钮。设置立即生效；关闭后停止新增，已记录内容保留，可再次开启后查看或清空。</p>
    <p>仅记录操作结果、错误类别与关联编号，不记录资料、对话正文或凭据。本机自动轮转保留最近约 4 MiB，窗口显示最近 500 条；服务重启后仍可查看。</p>
    {status?.storage_error && <p role="alert">日志文件暂时无法读写，请检查本机存储。</p>}
    {status?.enabled && <button type="button" className="button button--quiet" onClick={onOpen}>打开日志窗口</button>}
    {error && <p role="alert">{error} <button type="button" className="text-button" onClick={() => void load()}>重试</button></p>}
  </details>;
}

const levels = { info: '信息', warning: '警告', error: '错误' };
const modules: Record<string, string> = { system: '系统', runtime: '运行时', materials: '资料', ai: 'AI', learning: '学习', search: '搜索', settings: '设置' };
const events: Record<string, string> = { 'request.finished': '请求结束', 'material.purge': '资料清除', 'service.started': '服务启动', 'service.stopped': '服务停止', 'runtime.error': '运行异常', 'runtime.warning': '运行警告' };

type WindowBounds = { x: number; y: number; width: number; height: number };
function fitWindow(bounds: WindowBounds): WindowBounds {
  const width = Math.min(Math.max(300, bounds.width), window.innerWidth);
  const height = Math.min(Math.max(240, bounds.height), window.innerHeight);
  return { width, height, x: Math.max(0, Math.min(bounds.x, window.innerWidth - width)), y: Math.max(0, Math.min(bounds.y, window.innerHeight - height)) };
}

export default function Diagnostics() {
  const [enabled, setEnabled] = useState(false);
  const [open, setOpen] = useState(false);
  const [maximized, setMaximized] = useState(false);
  const [bounds, setBounds] = useState<WindowBounds>(() => fitWindow({ x: Math.max(16, (window.innerWidth - 760) / 2), y: 80, width: 760, height: 420 }));
  const panel = useRef<HTMLElement>(null);
  const gesture = useRef<{ pointerId: number; x: number; y: number; bounds: WindowBounds; resize: boolean } | null>(null);
  useEffect(() => {
    const fit = () => { gesture.current = null; setBounds(value => fitWindow(value)); };
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, []);
  useEffect(() => { if (open) panel.current?.focus(); }, [open]);
  function startGesture(event: ReactPointerEvent<HTMLElement>, resize: boolean) {
    if (maximized || event.button !== 0 || (event.target as HTMLElement).closest('button')) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    gesture.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, bounds, resize };
  }
  function moveGesture(event: ReactPointerEvent<HTMLElement>) {
    const current = gesture.current;
    if (!current || current.pointerId !== event.pointerId) return;
    const dx = event.clientX - current.x, dy = event.clientY - current.y;
    const initial = current.bounds;
    setBounds(fitWindow(current.resize
      ? { ...initial, width: Math.min(window.innerWidth - initial.x, Math.max(300, initial.width + dx)), height: Math.min(window.innerHeight - initial.y, Math.max(240, initial.height + dy)) }
      : { ...initial, x: initial.x + dx, y: initial.y + dy }));
  }
  function stopGesture() { gesture.current = null; }

  const [entries, setEntries] = useState<DiagnosticEntry[]>([]);
  const [paused, setPaused] = useState(false);
  const [level, setLevel] = useState('all');
  const [module, setModule] = useState('all');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const list = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const sequence = useRef(0);
  const following = useRef(true);
  useEffect(() => {
    let active = true;
    const update = () => { void getDiagnosticStatus().then(value => { if (active) { setEnabled(value.enabled); if (!value.enabled) { setOpen(false); setEntries([]); sequence.current++; } } }).catch(() => { /* Settings offers an explicit retry; learning is independent of diagnostics. */ }); };
    const show = () => { setOpen(true); setPaused(false); };
    update(); window.addEventListener('nautilus:diagnostics-changed', update); window.addEventListener('nautilus:open-diagnostics', show);
    return () => { active = false; sequence.current++; window.removeEventListener('nautilus:diagnostics-changed', update); window.removeEventListener('nautilus:open-diagnostics', show); };
  }, []);
  async function refresh() {
    const request = ++sequence.current;
    try {
      const value = await getDiagnosticEntries();
      if (request !== sequence.current) return;
      setEnabled(value.enabled);
      if (!value.enabled) { setOpen(false); setEntries([]); return; }
      setEntries(value.entries); setError(value.storage_error ? '部分日志文件无法读写，请检查本机存储。' : '');
    } catch (cause) { if (request === sequence.current) setError(cause instanceof Error ? cause.message : '日志读取失败。'); }
  }
  useEffect(() => {
    if (!open || !enabled) return;
    void refresh();
    if (paused) return;
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 2000);
    return () => { window.clearInterval(timer); sequence.current++; };
  }, [open, enabled, paused]);
  useEffect(() => { if (open && following.current && list.current) list.current.scrollTop = list.current.scrollHeight; }, [entries, open]);
  if (!enabled) return null;
  async function clear() {
    if (!window.confirm('清空本机诊断日志？这不会删除学习资料或对话。')) return;
    sequence.current++; setBusy(true); setError('');
    try { await clearDiagnostics(); setEntries([]); await refresh(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : '日志未清空。'); }
    finally { setBusy(false); }
  }
  const visible = entries.filter(entry => (level === 'all' || entry.level === level) && (module === 'all' || entry.module === module));
  return <>
    <button ref={trigger} type="button" className="diagnostic-launcher button button--quiet" aria-expanded={open} onClick={() => setOpen(value => !value)}><Bug size={15} />日志</button>
    {open && <DialogPortal><section ref={panel} tabIndex={-1} role="dialog" aria-modal="false" className={`diagnostic-panel${maximized ? ' is-maximized' : ''}`} style={maximized ? { left: 0, top: 0, width: '100vw', height: '100dvh' } : { left: bounds.x, top: bounds.y, width: bounds.width, height: bounds.height }} aria-label="诊断日志" onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); setOpen(false); requestAnimationFrame(() => trigger.current?.focus()); } }}>
      <header className="diagnostic-titlebar" onPointerDown={event => startGesture(event, false)} onPointerMove={moveGesture} onPointerUp={stopGesture} onPointerCancel={stopGesture} onLostPointerCapture={stopGesture}>
        <strong tabIndex={0} title="拖动标题栏移动窗口；方向键微调位置" onKeyDown={event => { if (!maximized && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) { event.preventDefault(); setBounds(value => fitWindow({ ...value, x: value.x + (event.key === 'ArrowRight' ? 10 : event.key === 'ArrowLeft' ? -10 : 0), y: value.y + (event.key === 'ArrowDown' ? 10 : event.key === 'ArrowUp' ? -10 : 0) })); } }}>诊断日志</strong>
        <button type="button" className="icon-button" title={maximized ? '还原窗口' : '最大化日志'} aria-label={maximized ? '还原窗口' : '最大化日志'} onClick={() => setMaximized(value => !value)}>{maximized ? <Minimize2 size={16} /> : <Maximize2 size={16} />}</button>
        <button type="button" className="icon-button" title="最小化日志" aria-label="最小化日志" onClick={() => { setOpen(false); requestAnimationFrame(() => trigger.current?.focus()); }}><Minus size={18} /></button>
      </header>
      <div className="diagnostic-toolbar"><span>{paused ? '已暂停刷新，记录继续' : '实时刷新'} · {visible.length} 条</span>
        <label>级别<select aria-label="级别" value={level} onChange={event => setLevel(event.target.value)}><option value="all">全部</option><option value="info">信息</option><option value="warning">警告</option><option value="error">错误</option></select></label>
        <label>模块<select aria-label="模块" value={module} onChange={event => setModule(event.target.value)}><option value="all">全部</option>{Array.from(new Set(entries.map(entry => entry.module))).sort().map(value => <option key={value} value={value}>{modules[value] ?? value}</option>)}</select></label>
        <button type="button" className="icon-button" title={paused ? '继续刷新' : '暂停刷新'} aria-label={paused ? '继续刷新' : '暂停刷新'} onClick={() => setPaused(value => !value)}>{paused ? <Play size={15} /> : <Pause size={15} />}</button>
        <button type="button" className="icon-button" title="刷新日志" aria-label="刷新日志" onClick={() => void refresh()}><RefreshCw size={15} /></button>
        <button type="button" className="icon-button" title="清空日志" aria-label="清空日志" disabled={busy} onClick={() => void clear()}><Trash2 size={15} /></button>
      </div>
      {error && <p role="alert">{error}</p>}
      <div ref={list} className="diagnostic-entries" onScroll={event => { const node = event.currentTarget; following.current = node.scrollHeight - node.scrollTop - node.clientHeight < 40; }}>
        {!visible.length && <p>暂无符合条件的日志。操作应用后可在这里查看。</p>}
        {visible.map(entry => <article key={entry.id} className={`diagnostic-entry diagnostic-entry--${entry.level}`}><time>{new Date(entry.at).toLocaleTimeString()}</time><strong>{levels[entry.level]}</strong><span>{modules[entry.module] ?? entry.module}</span><div>
          <span>{events[entry.event] ?? entry.event}{entry.method ? ` · ${entry.method} ${entry.route}` : ''}{entry.status !== undefined ? ` · ${entry.status}` : ''}{entry.duration_ms !== undefined ? ` · ${entry.duration_ms} ms` : ''}{entry.result ? ` · ${entry.result === 'complete' ? '完成' : '未全部完成'}` : ''}</span>
          {entry.code && <code>{entry.code}</code>}{entry.source && <code>{entry.source}:{entry.line}</code>}
          {entry.failed_count !== undefined && <span>完成 {entry.cleared_count} 项，失败 {entry.failed_count} 项</span>}
          {entry.request_id && <small>关联编号：{entry.request_id}</small>}
        </div></article>)}
      </div>
      {!maximized && <div className="diagnostic-resize" role="slider" aria-label="调整日志窗口大小" aria-valuetext={`${Math.round(bounds.width)} × ${Math.round(bounds.height)}`} aria-valuenow={Math.round(bounds.width)} aria-valuemin={Math.min(300, window.innerWidth)} aria-valuemax={window.innerWidth} tabIndex={0} title="拖动调整大小；方向键微调" onPointerDown={event => startGesture(event, true)} onPointerMove={moveGesture} onPointerUp={stopGesture} onPointerCancel={stopGesture} onLostPointerCapture={stopGesture} onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
        event.preventDefault();
        setBounds(value => fitWindow({ ...value, width: Math.min(window.innerWidth - value.x, Math.max(300, value.width + (event.key === 'ArrowRight' ? 10 : event.key === 'ArrowLeft' ? -10 : 0))), height: Math.min(window.innerHeight - value.y, Math.max(240, value.height + (event.key === 'ArrowDown' ? 10 : event.key === 'ArrowUp' ? -10 : 0))) }));
      }}><Grip size={16} /></div>}
    </section></DialogPortal>}
  </>;
}
