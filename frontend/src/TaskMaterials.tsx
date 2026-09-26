import { useEffect, useRef, useState } from 'react';
import type { SearchTrace } from './SearchResults';
import { getMaterialPurge, getMaterials, purgeMaterial, saveMaterial, type AppliedSourceScope, type MaterialKind, type MaterialVersion, type PurgeReport, type SourceScope } from './api';
import { getPreferences, type ConflictPolicy } from './preferences';
import './styles/task-materials.css';

export const emptySourceScope = (): SourceScope => ({ mode: 'unspecified', version_ids: [] });
const storageKey = (kind: MaterialKind, identity: string, id: string) => `nautilus.material-selection:${identity}:${kind}:${id}`;
export function readSourceScope(kind: MaterialKind, identity: string, id: string): SourceScope {
  try {
    const value = JSON.parse(localStorage.getItem(storageKey(kind, identity, id)) || '{}');
    if (['unspecified', 'reference', 'only'].includes(value.mode) && Array.isArray(value.version_ids) && value.version_ids.every((item: unknown) => typeof item === 'string'))
      return { mode: value.mode, version_ids: value.version_ids.slice(0, 8), ...( ['ask', 'balanced', 'materials'].includes(value.conflict_policy) ? { conflict_policy: value.conflict_policy } : {}) };
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
  return <details className="task-material-use"><summary>本回答资料范围：{scope.mode === 'only' ? '只依据所选资料' : '参考所选资料'} · {scope.materials.length} 个版本{scope.conflict_policy ? ` · 冲突时${policyLabel(scope.conflict_policy)}` : ''}</summary>
    <p>这里记录回答中出现的【资料1】等标记；标记不证明引用准确，选入资料也不代表内容已核实或学会。</p>
    <ol>{scope.materials.map((item, index) => <li key={item.id}><strong>【资料{index + 1}】{item.title}</strong> · 第 {item.version} 版 · {materialKindLabel(item.content_kind)} · {item.cited ? '正文出现引用标记' : '正文未出现引用标记'}
      {safeSourceUrl(item.url) && <> · <a href={safeSourceUrl(item.url)!} target="_blank" rel="noopener noreferrer">来源网页</a></>}
      {versions?.find(version => version.id === item.id && !version.purged_at) && <details><summary>查看保存的版本</summary><pre>{versions.find(version => version.id === item.id)?.content}</pre></details>}
    </li>)}</ol>
  </details>;
}
const materialKindLabel = (kind: MaterialVersion['content_kind']) => ({ text: '文本资料', excerpt: '搜索摘录', page: '网页读取片段' })[kind];
function safeSourceUrl(value: string | null) {
  try { const url = new URL(value ?? ''); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; }
  catch { return null; }
}
const purgeStatusLabel = (status: PurgeReport['status']) => ({ not_requested: '尚未请求', pending: '处理中', partial: '部分完成', complete: '已完成' })[status];
const fileStatusLabel = (status: PurgeReport['files'][number]['status']) => ({ cleared: '已清除', failed: '失败' })[status];
const policyLabel = (policy: ConflictPolicy) => ({ ask: '询问我', balanced: '由 AI 综合判断', materials: '以所选资料为准' })[policy];
function latestActive(versions: MaterialVersion[]) {
  return [...new Map(versions.filter(item => !item.purged_at).sort((a, b) => a.version - b.version).map(item => [item.material_id, item])).values()].slice(0, 8);
}
function uploadError(code: unknown) {
  const messages: Record<string, string> = {
    material_file_too_large: '文件超过 5 MiB，请选较小的文件。',
    material_file_encoding: '文本文件需要使用 UTF-8 编码。',
    material_file_unsupported: '暂不支持此文件格式。',
    material_file_no_text: '没有读到可用文字。扫描版 PDF 和图片暂不支持。',
    material_file_text_too_long: '提取的文字超过 30000 字，请拆分文件。',
    material_file_unreadable: '文件无法读取，请检查文件是否损坏。',
    material_file_encrypted: '加密 PDF 暂不支持。',
    material_limit: '本对话最多保存 8 份资料。',
  };
  return typeof code === 'string' ? messages[code] ?? `资料未保存：${code}` : '资料未保存，请重试。';
}

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
  const [fileReading, setFileReading] = useState(false);
  const [defaultPolicy, setDefaultPolicy] = useState<ConflictPolicy | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [purgeId, setPurgeId] = useState<string | null>(null);
  const [purgeReport, setPurgeReport] = useState<{ materialId: string; report: PurgeReport } | null>(null);
  const previousId = useRef<string | null>(null);
  const epoch = useRef(0);
  useEffect(() => {
    let active = true;
    const update = () => { void getPreferences().then(value => { if (active) setDefaultPolicy(value.conflict_policy); }).catch(() => { if (active) setDefaultPolicy(null); }); };
    update();
    window.addEventListener('nautilus:preferences-changed', update);
    return () => { active = false; window.removeEventListener('nautilus:preferences-changed', update); };
  }, [identity]);
  useEffect(() => {
    const current = ++epoch.current;
    if (previousId.current && previousId.current !== id) setOpen(false);
    previousId.current = id;
    setFileReading(false); setVersions([]); onVersions?.([]); setEditing(null); setTitle(''); setContent(''); setError(''); setBusy(false); setPurgeId(null); setPurgeReport(null);
    if (id) void getMaterials(kind, id).then(data => { if (epoch.current === current) { setVersions(data.versions); onVersions?.(data.versions); let hasSaved = false; try { hasSaved = !!identity && localStorage.getItem(storageKey(kind, identity, id)) !== null; } catch { /* Storage may be unavailable. */ } if (!hasSaved && scope.mode === 'unspecified' && scope.version_ids.length === 0) { const latest = latestActive(data.versions); if (latest.length) change({ ...scope, mode: 'reference', version_ids: latest.map(item => item.id) }); } } }).catch(() => { if (epoch.current === current) setError('资料列表加载失败，可重新打开重试。'); });
    return () => { epoch.current++; };
  }, [kind, id, identity]);
  async function refresh(target: string, expectedEpoch = epoch.current) {
    if (epoch.current !== expectedEpoch || (id && id !== target)) return [];
    const data = await getMaterials(kind, target);
    if (epoch.current === expectedEpoch) { setVersions(data.versions); onVersions?.(data.versions); }
    return data.versions;
  }
  async function targetId() { return id; }
  function change(value: SourceScope) { onChange(value); if (id && identity) writeSourceScope(kind, identity, id, value); }
  function selectSaved(item: MaterialVersion) {
    const other = scope.version_ids.filter(versionId => !versions.some(version => version.id === versionId && version.material_id === item.material_id));
    change({ ...scope, mode: scope.mode === 'unspecified' ? 'reference' : scope.mode, version_ids: [...other, item.id].slice(0, 8) });
  }
  async function save(payload: { title: string; content?: string; material_id?: string; web_run_id?: string; web_item_index?: number }) {
    const current = epoch.current;
    setBusy(true); setError('');
    try { const target = await targetId(); if (!target) throw new Error('请先打开对话。'); const saved = await saveMaterial(kind, target, payload); if (epoch.current !== current) return; await refresh(target, current); if (epoch.current === current) { selectSaved(saved); setTitle(''); setContent(''); setEditing(null); } }
    catch (reason) { if (epoch.current === current) setError(reason instanceof Error ? reason.message : '资料未保存'); }
    finally { if (epoch.current === current) setBusy(false); }
  }
  async function upload(file: File) {
    const current = epoch.current;
    setFileReading(true); setBusy(true); setError('');
    try {
      if (file.size > 5 * 1024 * 1024) throw new Error('文件超过 5 MiB，请选较小的文件。');
      const target = await targetId();
      if (!target) throw new Error('请先打开对话。');
      const response = await fetch(`/api/materials/${kind}/${target}/upload`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name) }, body: file });
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(uploadError(result?.detail));
      if (epoch.current !== current) return;
      await refresh(target, current);
      if (epoch.current === current) selectSaved(result as MaterialVersion);
    } catch (reason) { if (epoch.current === current) setError(reason instanceof Error ? reason.message : '文件读取失败。'); }
    finally { if (epoch.current === current) { setFileReading(false); setBusy(false); } if (fileInput.current) fileInput.current.value = ''; }
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
      change({ ...scope, mode: remaining.length ? scope.mode : 'unspecified', version_ids: remaining });
      await onPurged();
      if (epoch.current === current && result.purge.status === 'complete') setPurgeId(null);
    } catch (reason) { if (epoch.current === current) setError(reason instanceof Error ? reason.message : '清除未完成，可重试。'); }
    finally { if (epoch.current === current) setBusy(false); }
  }
  const active = versions.filter(item => !item.purged_at);
  const groups = [...new Map([...versions].sort((a, b) => a.version - b.version).map(item => [item.material_id, item])).values()];
  const selected = scope.version_ids.filter(versionId => active.some(item => item.id === versionId));
  const selectedChars = active.filter(item => selected.includes(item.id)).reduce((total, item) => total + (item.content?.length ?? 0), 0);
  return <div className="task-materials">
    <button className="button button--quiet" type="button" aria-expanded={open} onClick={() => { const current = epoch.current; setOpen(value => !value); if (id) void refresh(id, current).catch(() => { if (epoch.current === current) setError('资料列表加载失败'); }); else if (onEnsure) void onEnsure().catch(reason => { if (epoch.current === current) setError(reason instanceof Error ? reason.message : '无法创建对话'); }); }}>资料{scope.mode !== 'unspecified' ? ` · ${selected.length}` : ''}</button>
    {open && <section className="task-materials-panel" aria-label="本对话资料" onKeyDown={event => { if (event.key === 'Enter' && event.target instanceof HTMLInputElement) event.preventDefault(); }}>
      <h3>本对话资料</h3><p>保存或上传成功后即可在本对话参考。联网由工具栏单独控制。取消参考不会删除历史回答；明确选择严格范围时，会隔离范围外的旧对话，答案只依据所选资料。</p>
      <label className="task-material-upload">上传资料（UTF-8 文本、DOCX 或文字版 PDF；最大 5 MiB）<input ref={fileInput} type="file" disabled={disabled || busy || !id} accept=".txt,.md,.markdown,.json,.csv,.tsv,.py,.js,.ts,.tsx,.jsx,.html,.css,.xml,.yaml,.yml,.sql,.sh,.rs,.go,.java,.c,.cpp,.h,.docx,.pdf" onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file); }} /></label>
      {fileReading && <p role="status">正在读取资料…</p>}
      <label><input type="checkbox" checked={scope.mode === 'only'} disabled={disabled || busy || selected.length === 0} onChange={event => change({ ...scope, mode: event.target.checked ? 'only' : selected.length ? 'reference' : 'unspecified' })} />只依据所选资料（严格范围）</label>
      <label>资料冲突时<select value={scope.conflict_policy ?? ''} disabled={disabled || busy || !id} onChange={event => change({ ...scope, conflict_policy: event.target.value ? event.target.value as ConflictPolicy : undefined })}>
        <option value="">沿用默认（{defaultPolicy ? policyLabel(defaultPolicy) : '读取后生效'}）</option><option value="ask">询问我</option><option value="balanced">由 AI 综合判断</option><option value="materials">以所选资料为准</option>
      </select></label>
      {scope.mode !== 'unspecified' && <p>当前参考 {selected.length}/8 份资料，共 {selectedChars}/60000 字。{selected.length === 0 ? '请选择至少一个版本，才能发送。' : '资料不足时会指出缺口，由你决定是否扩展范围。'}</p>}
      {selectedChars > 60000 && <p className="form-error" role="alert">本轮参考内容超过 60000 字，请取消部分资料的参考勾选后再发送；资料仍会保留。</p>}
      {!id && <p>正在打开当前对话，随后即可上传资料。</p>}
      {groups.length > 0 && <ul className="task-material-list">{groups.map(group => <li key={group.material_id}>
        <label><input type="checkbox" disabled={disabled || busy || !!group.purged_at || (!versions.some(item => item.material_id === group.material_id && selected.includes(item.id)) && selected.length >= 8)} checked={versions.some(item => item.material_id === group.material_id && selected.includes(item.id))} onChange={() => { const own = versions.filter(item => item.material_id === group.material_id).map(item => item.id); const isSelected = own.some(value => selected.includes(value)); const remaining = selected.filter(value => !own.includes(value)); change({ ...scope, mode: isSelected && remaining.length === 0 ? 'unspecified' : scope.mode === 'unspecified' ? 'reference' : scope.mode, version_ids: isSelected ? remaining : [...remaining, group.id] }); }} /><strong>{group.title || '已清除的资料'}</strong> · {materialKindLabel(group.content_kind)}{group.purged_at && <span> · 已清除</span>}</label>
        {safeSourceUrl(group.url) && <a href={safeSourceUrl(group.url)!} target="_blank" rel="noopener noreferrer">来源网页</a>}
        {!group.purged_at && <details><summary>查看当前版本和历史</summary>{versions.filter(item => item.material_id === group.material_id && !item.purged_at).map(item => <div key={item.id}><p>第 {item.version} 版 · {item.title}{selected.includes(item.id) ? ' · 当前使用' : ''}</p><pre>{item.content}</pre><button type="button" className="text-button" disabled={busy || disabled || !id} onClick={() => { setEditing(item); setTitle(item.title ?? ''); setContent(item.content ?? ''); }}>编辑为新版本</button></div>)}</details>}
        {!group.purged_at && <button type="button" className="text-button" disabled={busy || disabled || !id} onClick={() => { setPurgeId(group.material_id); void showPurgeReport(group.material_id); }}>清除</button>}
        {group.purged_at && <button type="button" className="text-button" disabled={busy} onClick={() => void showPurgeReport(group.material_id)}>查看清除状态</button>}
        {group.purged_at && purgeReport?.materialId === group.material_id && ['partial', 'pending'].includes(purgeReport.report.status) && <button type="button" className="text-button" disabled={busy} onClick={() => setPurgeId(group.material_id)}>重试未完成的清除</button>}
      </li>)}</ul>}
      <div className="task-material-editor">
        <h4>{editing ? `编辑 ${editing.title}，保存为新版本` : '粘贴文本资料'}</h4>
        <label>标题<input value={title} maxLength={200} disabled={busy || disabled || !id} onChange={event => setTitle(event.target.value)} /></label>
        <label>正文<textarea value={content} maxLength={30000} disabled={busy || disabled || !id} onChange={event => setContent(event.target.value)} /></label>
        <button className="button button--quiet" type="button" disabled={busy || disabled || !id || !title.trim() || !content.trim()} onClick={() => void save({ title: title.trim(), content: content.trim(), ...(editing ? { material_id: editing.material_id } : {}) })}>保存版本</button>
        {editing && <button type="button" className="text-button" onClick={() => { setEditing(null); setTitle(''); setContent(''); }}>取消编辑</button>}
      </div>
      {candidates.length > 0 && <details><summary>从本对话已取得内容的网页结果保存</summary><ul>{candidates.map(item => <li key={`${item.runId}:${item.itemIndex}`}><strong>{item.title}</strong><p>{item.text.slice(0, 200)}{item.text.length > 200 ? '…' : ''}</p><button type="button" className="text-button" disabled={busy || disabled || !id} onClick={() => void save({ title: item.title, web_run_id: item.runId, web_item_index: item.itemIndex })}>保存此网页内容</button></li>)}</ul><p>搜索取得内容不代表已核实网页真伪。</p></details>}
      {purgeId && <div className="task-material-purge" role="alert"><p>确认彻底清除？这份资料的所有版本、取得该网页内容的原检索回答，以及使用它的后续回答都会一起清除。同一次检索保存的其他资料也可能联动清除。此操作不可撤销。</p><button type="button" className="button button--danger" disabled={busy} onClick={() => void purge()}>确认清除</button><button type="button" className="button button--quiet" onClick={() => setPurgeId(null)}>取消</button></div>}
      {purgeReport && <p role="status">清除状态：{purgeStatusLabel(purgeReport.report.status)}。{purgeReport.report.files.map(file => `${file.name} ${fileStatusLabel(file.status)}`).join('；')}{purgeReport.report.external_limits.length ? `；外部限制：${purgeReport.report.external_limits.join('；')}` : ''}</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
    </section>}
  </div>;
}
