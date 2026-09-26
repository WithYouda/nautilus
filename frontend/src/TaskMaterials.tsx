import { useEffect, useRef, useState } from 'react';
import type { SearchTrace } from './SearchResults';
import { getMaterialPurge, getMaterials, purgeMaterial, saveMaterial, type AppliedSourceScope, type MaterialKind, type MaterialVersion, type PurgeReport, type SourceScope } from './api';
import './styles/task-materials.css';

export const emptySourceScope = (): SourceScope => ({ mode: 'unspecified', version_ids: [] });
const storageKey = (kind: MaterialKind, identity: string, id: string) => `nautilus.material-selection:${identity}:${kind}:${id}`;
export function readSourceScope(kind: MaterialKind, identity: string, id: string): SourceScope {
  try {
    const value = JSON.parse(localStorage.getItem(storageKey(kind, identity, id)) || '{}');
    if (['unspecified', 'reference', 'only'].includes(value.mode) && Array.isArray(value.version_ids) && value.version_ids.every((item: unknown) => typeof item === 'string'))
      return { mode: value.mode, version_ids: value.version_ids.slice(0, 8) };
  } catch { /* Storage may be unavailable. */ }
  return emptySourceScope();
}
export function writeSourceScope(kind: MaterialKind, identity: string, id: string, value: SourceScope) {
  try { localStorage.setItem(storageKey(kind, identity, id), JSON.stringify(value)); } catch { /* In-memory selection still works. */ }
}
export type WebMaterialCandidate = { runId: string; itemIndex: number; title: string; url: string; text: string };
export function webMaterialCandidates(rows: Array<{ runId: string | null | undefined; trace?: SearchTrace | null; complete: boolean }>): WebMaterialCandidate[] {
  return rows.flatMap(({ runId, trace, complete }) => !runId || !complete || trace?.status !== 'succeeded' ? [] : (trace.items ?? []).flatMap((item, itemIndex) => item.text?.trim()
    ? [{ runId, itemIndex, title: item.title || item.url, url: item.url, text: item.text }] : []));
}

export function MaterialUse({ scope, versions }: { scope?: AppliedSourceScope | null; versions?: MaterialVersion[] }) {
  if (scope?.purged) return <p className="task-material-use">资料及关联内容已清除。</p>;
  if (!scope || scope.mode === 'unspecified') return null;
  return <details className="task-material-use"><summary>本回答资料范围：{scope.mode === 'only' ? '只依据所选资料' : '参考所选资料'} · {scope.materials.length} 个版本</summary>
    <p>这里记录回答中出现的【资料1】等标记；标记不证明引用准确，选入资料也不代表内容已核实或学会。</p>
    <ol>{scope.materials.map((item, index) => <li key={item.id}><strong>【资料{index + 1}】{item.title}</strong> · 第 {item.version} 版 · {materialKindLabel(item.content_kind)} · {item.cited ? '正文出现引用标记' : '正文未出现引用标记'}
      {safeSourceUrl(item.url) && <> · <a href={safeSourceUrl(item.url)!} target="_blank" rel="noopener noreferrer">来源网页</a></>}
      {versions?.find(version => version.id === item.id && !version.purged_at) && <details><summary>查看保存的版本</summary><pre>{versions.find(version => version.id === item.id)?.content}</pre></details>}
    </li>)}</ol>
  </details>;
}
const materialKindLabel = (kind: MaterialVersion['content_kind']) => ({ text: '粘贴文本', excerpt: '搜索摘录', page: '网页读取片段' })[kind];
function safeSourceUrl(value: string | null) {
  try { const url = new URL(value ?? ''); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; }
  catch { return null; }
}
const purgeStatusLabel = (status: PurgeReport['status']) => ({ not_requested: '尚未请求', pending: '处理中', partial: '部分完成', complete: '已完成' })[status];
const fileStatusLabel = (status: PurgeReport['files'][number]['status']) => ({ cleared: '已清除', failed: '失败' })[status];

export default function TaskMaterials({ kind, id, identity, scope, onChange, candidates, disabled, onEnsure, onPurged, onVersions }: {
  kind: MaterialKind; id: string | null; identity: string | null; scope: SourceScope; onChange: (scope: SourceScope) => void;
  candidates: WebMaterialCandidate[]; disabled?: boolean; onEnsure?: () => Promise<string>; onPurged: () => Promise<void>; onVersions?: (versions: MaterialVersion[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [versions, setVersions] = useState<MaterialVersion[]>([]);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [editing, setEditing] = useState<MaterialVersion | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [purgeId, setPurgeId] = useState<string | null>(null);
  const [purgeReport, setPurgeReport] = useState<{ materialId: string; report: PurgeReport } | null>(null);
  const previousId = useRef<string | null>(null);
  const epoch = useRef(0);
  useEffect(() => {
    const current = ++epoch.current;
    if (previousId.current && previousId.current !== id) setOpen(false);
    previousId.current = id;
    setVersions([]); onVersions?.([]); setEditing(null); setTitle(''); setContent(''); setError(''); setBusy(false); setPurgeId(null); setPurgeReport(null);
    if (id) void getMaterials(kind, id).then(data => { if (epoch.current === current) { setVersions(data.versions); onVersions?.(data.versions); } }).catch(() => { if (epoch.current === current) setError('资料列表加载失败，可重新打开重试。'); });
    return () => { epoch.current++; };
  }, [kind, id, identity]);
  async function refresh(target: string, expectedEpoch = epoch.current) {
    if (epoch.current !== expectedEpoch || (id && id !== target)) return [];
    const data = await getMaterials(kind, target);
    if (epoch.current === expectedEpoch) { setVersions(data.versions); onVersions?.(data.versions); }
    return data.versions;
  }
  async function targetId() { return id ?? (onEnsure ? await onEnsure() : null); }
  function change(value: SourceScope) { onChange(value); if (id && identity) writeSourceScope(kind, identity, id, value); }
  async function save(payload: { title: string; content?: string; material_id?: string; web_run_id?: string; web_item_index?: number }) {
    const current = epoch.current;
    setBusy(true); setError('');
    try { const target = await targetId(); if (!target) throw new Error('请先打开对话。'); await saveMaterial(kind, target, payload); if (epoch.current !== current) return; await refresh(target, current); if (epoch.current === current) { setTitle(''); setContent(''); setEditing(null); } }
    catch (reason) { if (epoch.current === current) setError(reason instanceof Error ? reason.message : '资料未保存'); }
    finally { if (epoch.current === current) setBusy(false); }
  }
  async function showPurgeReport(materialId: string) {
    if (!id) return;
    const current = epoch.current;
    try { const report = await getMaterialPurge(kind, id, materialId); if (epoch.current === current) setPurgeReport({ materialId, report }); }
    catch (reason) { if (epoch.current === current) setError(reason instanceof Error ? reason.message : '清除状态加载失败'); }
  }
  async function purge() {
    if (!id || !purgeId) return;
    const current = epoch.current;
    const materialId = purgeId;
    setBusy(true); setError('');
    try {
      const result = await purgeMaterial(kind, id, materialId);
      if (epoch.current !== current) return;
      setPurgeReport({ materialId, report: result.purge });
      const latest = await refresh(id, current);
      if (epoch.current !== current) return;
      const stillActive = new Set(latest.filter(item => !item.purged_at).map(item => item.id));
      const remaining = scope.version_ids.filter(versionId => stillActive.has(versionId));
      change(remaining.length ? { ...scope, version_ids: remaining } : emptySourceScope());
      await onPurged();
      if (epoch.current === current && result.purge.status === 'complete') setPurgeId(null);
    } catch (reason) { if (epoch.current === current) setError(reason instanceof Error ? reason.message : '清除未完成，可重试。'); }
    finally { if (epoch.current === current) setBusy(false); }
  }
  const active = versions.filter(item => !item.purged_at);
  const groups = [...new Map([...versions].sort((a, b) => a.version - b.version).map(item => [item.material_id, item])).values()];
  const selected = scope.version_ids.filter(versionId => active.some(item => item.id === versionId));
  return <div className="task-materials">
    <button className="button button--quiet" type="button" aria-expanded={open} onClick={() => { const current = epoch.current; setOpen(value => !value); if (id) void refresh(id, current).catch(() => { if (epoch.current === current) setError('资料列表加载失败'); }); else if (onEnsure) void onEnsure().catch(reason => { if (epoch.current === current) setError(reason instanceof Error ? reason.message : '无法创建对话'); }); }}>资料{scope.mode !== 'unspecified' ? ` · ${selected.length}` : ''}</button>
    {open && <section className="task-materials-panel" aria-label="本对话资料" onKeyDown={event => { if (event.key === 'Enter' && event.target instanceof HTMLInputElement) event.preventDefault(); }}>
      <h3>本对话资料</h3><p>按需指定资料；未指定时保留现有主动搜索。指定资料后，本轮不会联网。范围变化后的新回答不会带入此前对话历史。</p>
      <label>使用方式<select value={scope.mode} disabled={disabled || busy} onChange={event => change({ mode: event.target.value as SourceScope['mode'], version_ids: event.target.value === 'unspecified' ? [] : selected })}>
        <option value="unspecified">未指定资料</option><option value="reference">参考所选资料</option><option value="only">只依据所选资料</option>
      </select></label>
      {scope.mode !== 'unspecified' && <p>已选择 {selected.length}/8 个版本。{selected.length === 0 ? '请选择至少一个版本，才能发送。' : '资料不足时会指出缺口，由你决定是否扩展范围。'}</p>}
      {!id && <p>首次保存资料会为当前学习范围建立对话。</p>}
      {groups.length > 0 && <ul className="task-material-list">{groups.map(group => <li key={group.material_id}>
        <strong>{group.title || '已清除的资料'}</strong> · {materialKindLabel(group.content_kind)}{safeSourceUrl(group.url) && <> · <a href={safeSourceUrl(group.url)!} target="_blank" rel="noopener noreferrer">来源网页</a></>}{group.purged_at && <span> · 已清除</span>}
        {versions.filter(item => item.material_id === group.material_id && !item.purged_at).map(item => <div key={item.id}>
          <label><input type="checkbox" disabled={disabled || busy || scope.mode === 'unspecified' || (!selected.includes(item.id) && selected.length >= 8 && !versions.some(other => other.material_id === item.material_id && selected.includes(other.id)))} checked={selected.includes(item.id)} onChange={() => change({ ...scope, version_ids: selected.includes(item.id) ? selected.filter(value => value !== item.id) : [...selected.filter(value => !versions.some(other => other.id === value && other.material_id === item.material_id)), item.id] })} />第 {item.version} 版 · {item.title}</label>
          <details><summary>查看内容</summary><pre>{item.content}</pre></details>
          <button type="button" className="text-button" disabled={busy || disabled} onClick={() => { setEditing(item); setTitle(item.title ?? ''); setContent(item.content ?? ''); }}>编辑为新版本</button>
        </div>)}
        {!group.purged_at && <button type="button" className="text-button" disabled={busy || disabled} onClick={() => { setPurgeId(group.material_id); void showPurgeReport(group.material_id); }}>清除</button>}
        {group.purged_at && <button type="button" className="text-button" disabled={busy} onClick={() => void showPurgeReport(group.material_id)}>查看清除状态</button>}
        {group.purged_at && purgeReport?.materialId === group.material_id && ['partial', 'pending'].includes(purgeReport.report.status) && <button type="button" className="text-button" disabled={busy} onClick={() => setPurgeId(group.material_id)}>重试未完成的清除</button>}
      </li>)}</ul>}
      <div className="task-material-editor">
        <h4>{editing ? `编辑 ${editing.title}，保存为新版本` : '粘贴文本资料'}</h4>
        <label>标题<input value={title} maxLength={200} disabled={busy || disabled} onChange={event => setTitle(event.target.value)} /></label>
        <label>正文<textarea value={content} maxLength={30000} disabled={busy || disabled} onChange={event => setContent(event.target.value)} /></label>
        <button className="button button--quiet" type="button" disabled={busy || disabled || !title.trim() || !content.trim()} onClick={() => void save({ title: title.trim(), content: content.trim(), ...(editing ? { material_id: editing.material_id } : {}) })}>保存版本</button>
        {editing && <button type="button" className="text-button" onClick={() => { setEditing(null); setTitle(''); setContent(''); }}>取消编辑</button>}
      </div>
      {candidates.length > 0 && <details><summary>从本对话已取得内容的网页结果保存</summary><ul>{candidates.map(item => <li key={`${item.runId}:${item.itemIndex}`}><strong>{item.title}</strong><p>{item.text.slice(0, 200)}{item.text.length > 200 ? '…' : ''}</p><button type="button" className="text-button" disabled={busy || disabled} onClick={() => void save({ title: item.title, web_run_id: item.runId, web_item_index: item.itemIndex })}>保存此网页内容</button></li>)}</ul><p>搜索取得内容不代表已核实网页真伪。</p></details>}
      {purgeId && <div className="task-material-purge" role="alert"><p>确认彻底清除？这份资料的所有版本、取得该网页内容的原检索回答，以及使用它的后续回答都会一起清除。同一次检索保存的其他资料也可能联动清除。此操作不可撤销。</p><button type="button" className="button button--danger" disabled={busy} onClick={() => void purge()}>确认清除</button><button type="button" className="button button--quiet" onClick={() => setPurgeId(null)}>取消</button></div>}
      {purgeReport && <p role="status">清除状态：{purgeStatusLabel(purgeReport.report.status)}。{purgeReport.report.files.map(file => `${file.name} ${fileStatusLabel(file.status)}`).join('；')}{purgeReport.report.external_limits.length ? `；外部限制：${purgeReport.report.external_limits.join('；')}` : ''}</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
    </section>}
  </div>;
}
