import { useEffect, useRef, useState } from 'react';
import type { SearchTrace } from './SearchResults';
import { getMaterialLibrary, getMaterialPurge, getMaterials, purgeLibraryMaterial, purgeMaterial, removeMaterialFromLibrary, saveMaterial, storeMaterialInLibrary, useMaterialFromLibrary, type AppliedSourceScope, type MaterialKind, type MaterialVersion, type PurgeReport, type SourceScope } from './api';
import { getPreferences, type ConflictPolicy } from './preferences';
import DialogPortal from './DialogPortal';
import ObsidianMaterials, { ObsidianSourceReview, obsidianSource } from './ObsidianMaterials';
import './styles/task-materials.css';

export const emptySourceScope = (): SourceScope => ({ mode: 'unspecified', version_ids: [] });
export type WebMaterialCandidate = { runId: string; itemIndex: number; title: string; url: string; text: string };
export function webMaterialCandidates(rows: Array<{ runId: string | null | undefined; trace?: SearchTrace | null; complete: boolean }>): WebMaterialCandidate[] {
  return rows.flatMap(({ runId, trace, complete }) => !runId || !complete || trace?.status !== 'succeeded' ? [] : (trace.items ?? []).flatMap((item, itemIndex) => item.text?.trim()
    ? [{ runId, itemIndex, title: item.title || item.url, url: item.url, text: item.text }] : []));
}

function MaterialOriginal({ version, kind, scopeId }: { version: MaterialVersion; kind: MaterialKind; scopeId: string }) {
  return version.original
    ? <a href={`/api/materials/${kind}/${encodeURIComponent(scopeId)}/versions/${encodeURIComponent(version.id)}/original`} download={version.original.filename}>下载原件：{version.original.filename}</a>
    : <small>此版本未保存原件</small>;
}

export function MaterialUse({ scope, versions, kind, scopeId }: { scope?: AppliedSourceScope | null; versions?: MaterialVersion[]; kind: MaterialKind; scopeId: string }) {
  if (scope?.purged) return <p className="task-material-use">资料及关联内容已清除。</p>;
  if (!scope || scope.mode === 'unspecified') return null;
  return <details className="task-material-use"><summary>本回答资料范围：{scope.mode === 'only' ? '只依据所选资料' : '参考所选资料'} · {scope.materials.length} 个版本{scope.conflict_policy ? ` · 冲突时${policyLabel(scope.conflict_policy)}` : ''}</summary>
    <p>这里记录回答中出现的【资料1】等标记；标记不证明引用准确，选入资料也不代表内容已核实或学会。</p>
    <ol>{scope.materials.map((item, index) => {
      const saved = versions?.find(version => version.id === item.id);
      const source = obsidianSource(saved);
      return <li key={item.id}><strong>【资料{index + 1}】{item.title}</strong> · 第 {item.version} 版 · {materialKindLabel(item.content_kind)} · {item.cited ? '正文出现引用标记' : '正文未出现引用标记'}
      {safeSourceUrl(item.url) && <> · <a href={safeSourceUrl(item.url)!} target="_blank" rel="noopener noreferrer">来源网页</a></>}
      {source && <> · Obsidian 保存快照（{source.vault_name} · {source.relative_path}）</>}
      {saved && !saved.purged_at && <details><summary>查看保存的版本</summary><pre>{saved.content}</pre><MaterialOriginal version={saved} kind={kind} scopeId={scopeId} />{source && <ObsidianSourceReview kind={kind} id={scopeId} version={saved} />}</details>}
    </li>; })}</ol>
  </details>;
}
const materialKindLabel = (kind: MaterialVersion['content_kind']) => ({ text: '文本资料', excerpt: '搜索摘录', page: '网页读取片段' })[kind];
function safeSourceUrl(value: string | null) {
  try { const url = new URL(value ?? ''); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; }
  catch { return null; }
}
const policyLabel = (policy: ConflictPolicy) => ({ ask: '询问我', balanced: '由 AI 综合判断', materials: '以所选资料为准' })[policy];
function latestActive(versions: MaterialVersion[]) {
  return [...new Map(versions.filter(item => !item.purged_at).sort((a, b) => a.version - b.version).map(item => [item.material_id, item])).values()];
}
function uploadError(code: unknown) {
  const messages: Record<string, string> = {
    material_file_encoding: '文本文件需要使用 UTF-8 编码。',
    material_file_unsupported: '暂不支持此文件格式。',
    material_file_no_text: '没有读到可用文字。扫描版 PDF 和图片暂不支持。',
    material_file_unreadable: '文件无法读取，请检查文件是否损坏。',
    material_file_encrypted: '加密 PDF 暂不支持。',
  };
  return typeof code === 'string' ? messages[code] ?? `资料未保存：${code}` : '资料未保存，请重试。';
}

export default function TaskMaterials({ kind, id, identity, scope, onChange, candidates, disabled, onEnsure, onPurged, onVersions }: {
  kind: MaterialKind; id: string | null; identity: string | null; scope: SourceScope;
  /** Returns the real result of persisting the current-conversation scope (false = not confirmed). */
  onChange: (scope: SourceScope) => Promise<boolean> | void;
  candidates: WebMaterialCandidate[]; disabled?: boolean; onEnsure?: () => Promise<string>; onPurged: () => Promise<void>; onVersions?: (versions: MaterialVersion[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [versions, setVersions] = useState<MaterialVersion[]>([]);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [libraryVersions, setLibraryVersions] = useState<MaterialVersion[]>([]);
  const [libraryRetryIds, setLibraryRetryIds] = useState<string[]>([]);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [libraryError, setLibraryError] = useState('');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [editing, setEditing] = useState<MaterialVersion | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [fileReading, setFileReading] = useState(false);
  const [defaultPolicy, setDefaultPolicy] = useState<ConflictPolicy | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const purgeDialog = useRef<HTMLElement>(null);
  const purgeCancel = useRef<HTMLButtonElement>(null);
  const purgeReturnFocus = useRef<HTMLElement | null>(null);
  const purgeBusy = useRef(false);
  const [confirmation, setConfirmation] = useState<{ action: 'remove' | 'purge'; source: 'library' | 'scope'; materialId: string } | null>(null);
  const [purgeNotice, setPurgeNotice] = useState('');
  const [purgeHints, setPurgeHints] = useState<Record<string, PurgeReport['status']>>({});
  const previousId = useRef<string | null>(null);
  const epoch = useRef(0);
  // Latest scope from the parent, so a long capture never reapplies a stale selection.
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  // A capture may only apply its selection while the panel is still open and no newer
  // operation or context change has replaced it.
  const panelOpen = useRef(false);
  const selectionOperation = useRef(0);
  const libraryRequest = useRef(0);
  purgeBusy.current = busy;
  // The ref mirrors the rendered panel state (including programmatic closes) and a
  // closed panel invalidates a selection that has not been sent yet.
  useEffect(() => { panelOpen.current = open; if (!open) selectionOperation.current++; }, [open]);
  useEffect(() => {
    let active = true;
    const update = () => { void getPreferences().then(value => { if (active) setDefaultPolicy(value.conflict_policy); }).catch(() => { if (active) setDefaultPolicy(null); }); };
    update();
    window.addEventListener('nautilus:preferences-changed', update);
    return () => { active = false; window.removeEventListener('nautilus:preferences-changed', update); };
  }, [identity]);
  useEffect(() => {
    const current = ++epoch.current;
    libraryRequest.current++;
    selectionOperation.current++;   // a new context invalidates any pending selection
    if (previousId.current && previousId.current !== id) setOpen(false);
    previousId.current = id;
    setFileReading(false); setVersions([]); onVersions?.([]); setEditing(null); setTitle(''); setContent(''); setError(''); setBusy(false); setConfirmation(null); setPurgeNotice(''); setPurgeHints({}); setLibraryOpen(false); setLibraryVersions([]); setLibraryRetryIds([]); setLibraryError(''); setLibraryLoading(false);
    if (id) void getMaterials(kind, id).then(data => { if (epoch.current === current) { setVersions(data.versions); onVersions?.(data.versions); } }).catch(() => { if (epoch.current === current) setError('资料列表加载失败，可重新打开重试。'); });
    return () => { epoch.current++; };
  }, [kind, id, identity]);
  useEffect(() => {
    if (!id) return;
    const current = epoch.current;
    const cleared = [...new Set(versions.filter(item => item.purged_at).map(item => item.material_id))]
      .filter(materialId => versions.filter(item => item.material_id === materialId).every(item => item.purged_at));
    if (!cleared.length) return;
    void Promise.all(cleared.map(async materialId => {
      try {
        const report = await getMaterialPurge(kind, id, materialId);
        if (epoch.current === current) setPurgeHints(previous => ({ ...previous, [materialId]: report.status }));
      } catch { /* The cleared row stays hidden; retry state cannot be inferred from a failed lookup. */ }
    }));
  }, [kind, id, versions]);
  useEffect(() => {
    if (!confirmation) return;
    purgeReturnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    purgeCancel.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); if (!purgeBusy.current) setConfirmation(null); }
      if (event.key !== 'Tab' || !purgeDialog.current) return;
      const buttons = [...purgeDialog.current.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')];
      if (!buttons.length) { event.preventDefault(); return; }
      const first = buttons[0], last = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener('keydown', onKeyDown, true);
    return () => { document.removeEventListener('keydown', onKeyDown, true); purgeReturnFocus.current?.focus(); };
  }, [confirmation]);
  async function refresh(target: string, expectedEpoch = epoch.current) {
    if (epoch.current !== expectedEpoch || (id && id !== target)) return [];
    const data = await getMaterials(kind, target);
    if (epoch.current === expectedEpoch) { setVersions(data.versions); onVersions?.(data.versions); }
    return data.versions;
  }
  async function targetId() { return id; }
  function change(value: SourceScope) { return onChange(value); }
  function selectSaved(item: MaterialVersion) {
    const other = scope.version_ids.filter(versionId => !versions.some(version => version.id === versionId && version.material_id === item.material_id));
    change({ ...scope, mode: scope.mode === 'unspecified' ? 'reference' : scope.mode, version_ids: [...other, item.id] });
  }
  /** Returns true only when the current-conversation scope was persisted for this version. */
  async function useCaptured(version: MaterialVersion, isOperationCurrent: () => boolean): Promise<boolean> {
    if (!id) return false;
    const current = epoch.current;
    const operation = ++selectionOperation.current;
    // Checked on entry, after the list refresh and again right before the state write:
    // closing the panel must stop a selection that was never sent.
    const stillValid = () => isOperationCurrent() && panelOpen.current
      && epoch.current === current && selectionOperation.current === operation;
    if (!stillValid()) return false;
    setBusy(true); setError('');
    try {
      const fresh = await refresh(id, current);
      if (!stillValid()) return false;
      if (!fresh.some(item => item.id === version.id && !item.purged_at)) {
        setError('快照已保存，但当前选择未确认：这份资料当前不可用，请读取最新状态后重试。');
        return false;
      }
      const latest = scopeRef.current;
      const others = latest.version_ids.filter(versionId => !fresh.some(item => item.id === versionId && item.material_id === version.material_id));
      const selection = { ...latest, mode: latest.mode === 'unspecified' ? 'reference' as const : latest.mode, version_ids: [...others, version.id] };
      if (!stillValid()) return false;
      const applied = await change(selection);
      if (!stillValid() || applied !== true) return false;
      // An auxiliary library refresh must never turn a confirmed selection into a failure.
      if (libraryOpen) void loadLibrary(current);
      return true;
    } catch {
      if (stillValid()) setError('快照已保存，但资料列表刷新失败；请读取最新状态后重试。');
      return false;
    } finally { if (epoch.current === current) setBusy(false); }
  }
  async function loadLibrary(expectedEpoch = epoch.current) {
    if (epoch.current !== expectedEpoch) return;
    const request = ++libraryRequest.current;
    setLibraryLoading(true); setLibraryError('');
    try {
      const data = await getMaterialLibrary();
      if (epoch.current === expectedEpoch && libraryRequest.current === request) { setLibraryVersions(data.versions); setLibraryRetryIds(data.purge_retry_ids ?? []); }
    } catch (reason) {
      if (epoch.current === expectedEpoch && libraryRequest.current === request) setLibraryError(reason instanceof Error ? `资料库加载失败，可重试。${reason.message}` : '资料库加载失败，可重试。');
    } finally { if (epoch.current === expectedEpoch && libraryRequest.current === request) setLibraryLoading(false); }
  }
  async function storeInLibrary(materialId: string) {
    if (!id) return;
    const current = epoch.current;
    setBusy(true); setError('');
    try {
      await storeMaterialInLibrary(kind, id, materialId);
      if (epoch.current !== current) return;
      await refresh(id, current);
      if (libraryOpen) await loadLibrary(current);
    } catch (reason) { if (epoch.current === current) setError(reason instanceof Error ? `未能存入资料库，可重试。${reason.message}` : '未能存入资料库，可重试。'); }
    finally { if (epoch.current === current) setBusy(false); }
  }
  async function useFromLibrary(versionId: string) {
    if (!id) return;
    const current = epoch.current;
    setBusy(true); setError('');
    try {
      const used = await useMaterialFromLibrary(kind, id, versionId);
      if (epoch.current !== current) return;
      await refresh(id, current);
      if (epoch.current === current) selectSaved(used);
    } catch (reason) { if (epoch.current === current) setError(reason instanceof Error ? `未能选用资料，可重试。${reason.message}` : '未能选用资料，可重试。'); }
    finally { if (epoch.current === current) setBusy(false); }
  }
  async function save(payload: { title: string; content?: string; material_id?: string; web_run_id?: string; web_item_index?: number }) {
    const current = epoch.current;
    setBusy(true); setError('');
    try { const target = await targetId(); if (!target) throw new Error('请先打开对话。'); const saved = await saveMaterial(kind, target, payload); if (epoch.current !== current) return; await refresh(target, current); if (libraryOpen) await loadLibrary(current); if (epoch.current === current) { selectSaved(saved); setTitle(''); setContent(''); setEditing(null); } }
    catch (reason) { if (epoch.current === current) setError(reason instanceof Error ? reason.message : '资料未保存'); }
    finally { if (epoch.current === current) setBusy(false); }
  }
  async function upload(file: File) {
    const current = epoch.current;
    setFileReading(true); setBusy(true); setError('');
    try {
      const target = await targetId();
      if (!target) throw new Error('请先打开对话。');
      const response = await fetch(`/api/materials/${kind}/${target}/upload${editing ? `?material_id=${encodeURIComponent(editing.material_id)}` : ''}`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name) }, body: file });
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(uploadError(result?.detail));
      if (epoch.current !== current) return;
      await refresh(target, current);
      if (libraryOpen) await loadLibrary(current);
      if (epoch.current === current) { selectSaved(result as MaterialVersion); setEditing(null); setTitle(''); setContent(''); }
    } catch (reason) { if (epoch.current === current) setError(reason instanceof Error ? reason.message : '文件读取失败。'); }
    finally { if (epoch.current === current) { setFileReading(false); setBusy(false); } if (fileInput.current) fileInput.current.value = ''; }
  }
  async function removeFromLibrary(materialId: string) {
    const current = epoch.current;
    setBusy(true); setError('');
    let removed = false;
    try {
      await removeMaterialFromLibrary(materialId);
      if (epoch.current !== current) return;
      removed = true;
      setConfirmation(null);
      libraryRequest.current++;
      setLibraryVersions(previous => previous.filter(item => item.material_id !== materialId));
      const updatedVersions = versions.map(item => item.material_id === materialId ? { ...item, library: false } : item);
      setVersions(updatedVersions); onVersions?.(updatedVersions);
    } catch { if (epoch.current === current) setError('未能从资料库移除，请重试。'); }
    if (epoch.current === current && removed) {
      try {
        await loadLibrary(current);
        if (id) await refresh(id, current);
      } catch { if (epoch.current === current) setError('已从资料库移除，但资料列表刷新失败，请重新打开。'); }
    }
    if (epoch.current === current) setBusy(false);
  }
  async function purge() {
    if (!confirmation || confirmation.action !== 'purge' || (confirmation.source === 'scope' && !id)) return;
    const current = epoch.current;
    const { materialId, source } = confirmation;
    setBusy(true); setError('');
    try {
      const result = source === 'library' ? await purgeLibraryMaterial(materialId) : await purgeMaterial(kind, id!, materialId);
      if (epoch.current !== current) return;
      setPurgeHints(previous => ({ ...previous, [materialId]: result.purge.status }));
      setPurgeNotice(result.purge.status === 'complete' ? '资料及关联内容已清除。' : result.purge.status === 'pending' ? '清除仍在处理中，请稍后重试。' : '部分内容未能清除，请重试。');
      setConfirmation(null);
      libraryRequest.current++; setLibraryVersions([]); setLibraryRetryIds([]);
      try {
        if (id) await refresh(id, current);
        if (libraryOpen) await loadLibrary(current);
        if (epoch.current !== current) return;
        // Keep the invalid reference until the user explicitly chooses a new scope.
        if (id) await onPurged();
      } catch { if (epoch.current === current) setError('清除结果已返回，但资料或回答列表更新失败，请重新打开对话。'); }
    } catch { if (epoch.current === current) setError('清除未完成，可重试。'); }
    finally { if (epoch.current === current) setBusy(false); }
  }
  const active = versions.filter(item => !item.purged_at);
  const groups = [...new Map(versions.filter(item => !item.purged_at).sort((a, b) => a.version - b.version).map(item => [item.material_id, item])).values()];
  const libraryGroups = [...new Map(libraryVersions.filter(item => !item.purged_at).sort((a, b) => a.version - b.version).map(item => [item.material_id, item])).values()];
  const retryGroups = [...new Map(versions.map(item => [item.material_id, item])).values()]
    .filter(item => ['partial', 'pending'].includes(purgeHints[item.material_id]));
  const selected = scope.version_ids.filter(versionId => active.some(item => item.id === versionId));
  const selectedChars = active.filter(item => selected.includes(item.id)).reduce((total, item) => total + (item.content?.length ?? 0), 0);
  const confirmationHasObsidianSource = confirmation?.action === 'purge'
    && [...versions, ...libraryVersions].some(item => item.material_id === confirmation.materialId && obsidianSource(item));
  return <div className="task-materials">
    <button className="button button--quiet" type="button" aria-expanded={open} onClick={() => {
      const current = epoch.current;
      const next = !open;
      panelOpen.current = next;
      if (!next) selectionOperation.current++;   // closing drops any not-yet-sent selection
      setOpen(next);
      if (id) void refresh(id, current).catch(() => { if (epoch.current === current) setError('资料列表加载失败'); });
      else if (onEnsure) void onEnsure().catch(reason => { if (epoch.current === current) setError(reason instanceof Error ? reason.message : '无法创建对话'); });
    }}>资料{scope.mode !== 'unspecified' ? ` · ${selected.length}` : ''}</button>
    {open && <section className="task-materials-panel" aria-label="本对话资料" onKeyDown={event => { if (event.key === 'Enter' && event.target instanceof HTMLInputElement) event.preventDefault(); }}>
      <h3>本对话资料</h3>
      {purgeNotice && <p className="task-material-purge-notice" role="status">{purgeNotice}</p>}
      {retryGroups.map(group => <p className="task-material-purge-retry" role="alert" key={group.material_id}>“{group.title || '资料'}”{purgeHints[group.material_id] === 'pending' ? '的清除仍在处理中。' : '有部分内容未能清除。'}<button type="button" className="text-button" disabled={busy} onClick={() => { setConfirmation({ action: 'purge', source: 'scope', materialId: group.material_id }); setPurgeNotice(''); }}>重试清除</button></p>)}
      <p>保存或上传成功后即可在本对话参考。联网由工具栏单独控制。取消参考不会删除历史回答；明确选择严格范围时，会隔离范围外的旧对话，答案只依据所选资料。</p>
      {editing && <p>正在编辑“{editing.title}”。上传文件会保存为这份资料的新版本；旧版本和原件继续保留。</p>}
      <label className="task-material-upload">上传资料（UTF-8 文本、DOCX 或文字版 PDF）<input ref={fileInput} type="file" disabled={disabled || busy || !id} accept=".txt,.md,.markdown,.json,.csv,.tsv,.py,.js,.ts,.tsx,.jsx,.html,.css,.xml,.yaml,.yml,.sql,.sh,.rs,.go,.java,.c,.cpp,.h,.docx,.pdf" onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file); }} /></label>
      {fileReading && <p role="status">正在读取资料…</p>}
      <label><input type="checkbox" checked={scope.mode === 'only'} disabled={disabled || busy || selected.length === 0} onChange={event => change({ ...scope, mode: event.target.checked ? 'only' : selected.length ? 'reference' : 'unspecified' })} />只依据所选资料（严格范围）</label>
      <label>资料冲突时<select value={scope.conflict_policy ?? ''} disabled={disabled || busy || !id} onChange={event => change({ ...scope, conflict_policy: event.target.value ? event.target.value as ConflictPolicy : undefined })}>
        <option value="">沿用默认（{defaultPolicy ? policyLabel(defaultPolicy) : '读取后生效'}）</option><option value="ask">询问我</option><option value="balanced">由 AI 综合判断</option><option value="materials">以所选资料为准</option>
      </select></label>
      {scope.mode !== 'unspecified' && <p>当前参考 {selected.length} 份资料，共 {selectedChars} 字。{selected.length === 0 ? '请选择至少一个版本，才能发送。' : '资料不足时会指出缺口，由你决定是否扩展范围。'}</p>}
      {scope.version_ids.some(versionId => !active.some(item => item.id === versionId)) && <p role="alert">原来选择的部分资料已不可用。<button type="button" className="button button--quiet" disabled={disabled || busy} onClick={() => change({ ...scope, mode: 'unspecified', version_ids: [] })}>取消全部资料参考，重新选择</button></p>}
      {!id && <p>正在打开当前对话，随后即可上传资料。</p>}
      <ObsidianMaterials kind={kind} id={id} disabled={disabled || busy} onCaptured={useCaptured} />
      <section className="task-material-library" aria-label="资料库">
        <button type="button" className="button button--quiet" aria-expanded={libraryOpen} onClick={() => { setLibraryOpen(value => !value); if (!libraryOpen) void loadLibrary(); }}>从资料库选用</button>
        {libraryOpen && <div className="task-material-library-content">
          <p>选择明确版本加入当前参考；资料更新不会自动更换本对话已选版本。</p>
          {libraryLoading && <p role="status">正在加载资料库…</p>}
          {libraryError && <p role="alert">{libraryError} <button type="button" className="text-button" disabled={libraryLoading} onClick={() => void loadLibrary()}>重试加载</button></p>}
          {!libraryLoading && libraryRetryIds.map(materialId => <p className="task-material-purge-retry" role="alert" key={materialId}>一份资料的清除尚未完成。<button type="button" className="text-button" disabled={busy} onClick={() => { setConfirmation({ action: 'purge', source: 'library', materialId }); setPurgeNotice(''); }}>重试清除</button></p>)}
          {!libraryLoading && !libraryError && libraryGroups.length === 0 && libraryRetryIds.length === 0 && <p>资料库暂无资料。请在对话资料中点击“存入资料库”。</p>}
          {libraryGroups.length > 0 && <ul className="task-material-library-list">{libraryGroups.map(group => <li key={group.material_id}>
            <details><summary><strong>{group.title || '未命名资料'}</strong> · {materialKindLabel(group.content_kind)} · {libraryVersions.filter(item => item.material_id === group.material_id && !item.purged_at).length} 个版本</summary>
              {libraryVersions.filter(item => item.material_id === group.material_id && !item.purged_at).sort((a, b) => b.version - a.version).map(item => <div className="task-material-library-version" key={item.id}>
                <p>第 {item.version} 版 · {item.title || '未命名资料'}{selected.includes(item.id) ? ' · 当前使用' : ''}</p>
                <details><summary>查看保存的文本</summary><pre>{item.content}</pre></details>
                <button type="button" className="text-button" disabled={disabled || busy || !id} onClick={() => void useFromLibrary(item.id)}>选用第 {item.version} 版</button>
              </div>)}
            </details>
            <div className="task-material-library-actions"><button type="button" className="button button--quiet" disabled={busy || disabled} onClick={() => { setError(''); setConfirmation({ action: 'remove', source: 'library', materialId: group.material_id }); }}>从资料库移除</button><details><summary>更多操作</summary><button type="button" className="button button--danger" disabled={busy || disabled} onClick={() => { setError(''); setConfirmation({ action: 'purge', source: 'library', materialId: group.material_id }); setPurgeNotice(''); }}>彻底清除资料</button></details></div>
          </li>)}</ul>}
        </div>}
      </section>
      {groups.length > 0 && <ul className="task-material-list">{groups.map(group => <li key={group.material_id}>
        <label><input type="checkbox" disabled={disabled || busy} checked={versions.some(item => item.material_id === group.material_id && selected.includes(item.id))} onChange={() => { const own = versions.filter(item => item.material_id === group.material_id).map(item => item.id); const isSelected = own.some(value => selected.includes(value)); const remaining = selected.filter(value => !own.includes(value)); change({ ...scope, mode: isSelected && remaining.length === 0 ? 'unspecified' : scope.mode === 'unspecified' ? 'reference' : scope.mode, version_ids: isSelected ? remaining : [...remaining, group.id] }); }} /><strong>{group.title}</strong> · {materialKindLabel(group.content_kind)}{group.inherited && <span> · 从原对话继承（只读）</span>}</label>
        {safeSourceUrl(group.url) && <a href={safeSourceUrl(group.url)!} target="_blank" rel="noopener noreferrer">来源网页</a>}
        <details><summary>查看当前版本和历史</summary>{versions.filter(item => item.material_id === group.material_id && !item.purged_at).map(item => <div key={item.id}><p>第 {item.version} 版 · {item.title}{item.inherited ? ' · 继承（只读）' : ''}{selected.includes(item.id) ? ' · 当前使用' : ''}</p><pre>{item.content}</pre>{id && <MaterialOriginal version={item} kind={kind} scopeId={id} />}{id && <ObsidianSourceReview kind={kind} id={id} version={item} disabled={busy} />}{!item.inherited && <button type="button" className="text-button" disabled={busy || disabled || !id} onClick={() => { setEditing(item); setTitle(item.title ?? ''); setContent(item.content ?? ''); }}>编辑为新版本</button>}</div>)}</details>
        <div className="task-material-actions">
        {group.library ? <span className="task-material-library-status">已存入资料库</span> : <button type="button" className="button button--quiet" disabled={busy || disabled || !id} onClick={() => void storeInLibrary(group.material_id)}>存入资料库</button>}
        <button type="button" className="button button--danger" disabled={busy || disabled || !id} onClick={() => { setConfirmation({ action: 'purge', source: 'scope', materialId: group.material_id }); setPurgeNotice(''); }}>清除</button>
        </div>
      </li>)}</ul>}
      <div className="task-material-editor">
        <h4>{editing ? `编辑 ${editing.title}，保存为新版本` : '粘贴文本资料'}</h4>
        <label>标题<input value={title} maxLength={200} disabled={busy || disabled || !id} onChange={event => setTitle(event.target.value)} /></label>
        <label>正文<textarea value={content} disabled={busy || disabled || !id} onChange={event => setContent(event.target.value)} /></label>
        <button className="button button--quiet" type="button" disabled={busy || disabled || !id || !title.trim() || !content.trim()} onClick={() => void save({ title: title.trim(), content: content.trim(), ...(editing ? { material_id: editing.material_id } : {}) })}>保存版本</button>
        {editing && <button type="button" className="text-button" onClick={() => { setEditing(null); setTitle(''); setContent(''); }}>取消编辑</button>}
      </div>
      {candidates.length > 0 && <details><summary>从本对话已取得内容的网页结果保存</summary><ul>{candidates.map(item => <li key={`${item.runId}:${item.itemIndex}`}><strong>{item.title}</strong><p>{item.text.slice(0, 200)}{item.text.length > 200 ? '…' : ''}</p><button type="button" className="text-button" disabled={busy || disabled || !id} onClick={() => void save({ title: item.title, web_run_id: item.runId, web_item_index: item.itemIndex })}>保存此网页内容</button></li>)}</ul><p>搜索取得内容不代表已核实网页真伪。</p></details>}
      {error && <p className="form-error" role="alert">{error}</p>}
    </section>}
    {confirmation && <DialogPortal><div className="dialog-backdrop task-material-purge-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !busy) setConfirmation(null); }}><section ref={purgeDialog} className="task-material-purge-dialog" role="dialog" aria-modal="true" aria-labelledby="task-material-purge-title" onKeyDown={event => event.stopPropagation()}><h2 id="task-material-purge-title">{confirmation.action === 'remove' ? '从资料库移除这份资料？' : '清除这份资料？'}</h2><p>{confirmation.action === 'remove' ? '已有对话中的资料引用和回答将保留。这不会彻底清除资料文件。' : <>这会永久清除这份资料的所有版本和原件，包括资料库中的共享资料；所有选用它的对话、讨论及相关回答内容都可能受影响，同一次检索保存的其他资料也可能一并清除。无法撤销。已下载到设备的副本不会受影响。{confirmationHasObsidianSource && <><br />清除的是 Nautilus 保存的这份资料及相关内容；不会删除 Obsidian 原文或其云端备份。</>}</>}</p>{busy && <p role="status">{confirmation.action === 'remove' ? '正在移除…' : '正在清除…'}</p>}{error && <p className="form-error" role="alert">{error}</p>}<div className="task-material-purge-actions"><button ref={purgeCancel} type="button" className="button button--quiet" disabled={busy} onClick={() => setConfirmation(null)}>取消</button><button type="button" className="button button--danger" disabled={busy} onClick={() => confirmation.action === 'remove' ? void removeFromLibrary(confirmation.materialId) : void purge()}>{busy ? '处理中' : confirmation.action === 'remove' ? '确认移除' : '确认清除'}</button></div></section></div></DialogPortal>}
  </div>;
}
