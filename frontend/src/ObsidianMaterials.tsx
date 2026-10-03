import { useEffect, useRef, useState } from 'react';
import { captureObsidianNote, getObsidianConnection, getObsidianSourceStatus, searchObsidianNotes, type MaterialKind, type MaterialVersion, type ObsidianConnection, type ObsidianSearchItem, type ObsidianSearchResult, type ObsidianSourceStatus } from './api';
import './styles/task-materials.css';

export type ObsidianSource = {
  kind: 'obsidian_local'; schema_version: number; connection_id: string; vault_name: string;
  relative_path: string; sha256: string; captured_at: string;
  locator: { kind: string; start_line: number; end_line: number };
};

const messages: Record<string, string> = {
  obsidian_path_invalid: '请填写后端主机上存在、可读的目录绝对路径。',
  obsidian_path_unreadable: '这个目录当前无法读取，请检查路径和权限。',
  obsidian_connection_revision: '连接设置已被其他页面修改，请重新读取后再试。',
  obsidian_disconnected: 'Obsidian 连接已断开，请先在设置中重新连接。',
  obsidian_selection_invalid: '这次选择已失效，请重新检索后再保存。',
  obsidian_source_changed: '这份笔记在检索后已变化，请重新检索后再保存。',
  obsidian_purge_pending: '有一份资料的清除尚未完成，请先完成重试，再保存新的资料。',
  obsidian_search_invalidated: '检索期间连接或资料已变化，请重新检索。',
  obsidian_vault_unavailable: 'Vault 当前无法访问，请检查路径和磁盘状态。',
  obsidian_connection_unreadable: '已保存的 Obsidian 连接无法读取，请重新连接。',
  obsidian_note_encoding: '这份笔记不是 UTF-8 文本，暂不支持。',
  obsidian_note_empty: '这份笔记没有可保存的正文。',
  obsidian_note_unsupported: '这份笔记已经不是可读取的普通文件。',
  obsidian_query_invalid: '检索词或翻页位置无效，请重新检索。',
};

export function obsidianError(reason: unknown, fallback: string) {
  const message = reason instanceof Error ? reason.message : '';
  return messages[message] ?? fallback;
}

export function obsidianSource(version?: { provenance_json?: string | null } | null): ObsidianSource | null {
  if (!version?.provenance_json) return null;
  try {
    const value = JSON.parse(version.provenance_json) as Partial<ObsidianSource>;
    if (value?.kind !== 'obsidian_local' || typeof value.relative_path !== 'string'
      || typeof value.vault_name !== 'string' || typeof value.captured_at !== 'string'
      || !value.locator || typeof value.locator.end_line !== 'number') return null;
    return value as ObsidianSource;
  } catch {
    return null;
  }
}

export function obsidianUri(vault: string, relativePath: string) {
  const file = relativePath.replace(/\.md$/i, '');
  return `obsidian://open?vault=${encodeURIComponent(vault)}&file=${encodeURIComponent(file)}`;
}

const statusLabel: Record<ObsidianSourceStatus['status'], string> = {
  same_as_snapshot: '检查时与保存的快照内容相同；这不代表会持续同步。',
  changed: '外部原文已变化。已有快照和回答不受影响；需要重新检索并明确选用才会保存新版本。',
  missing: '外部原文没有找到，可能已删除、改名或移动；Nautilus 保存的快照仍然保留。',
  unavailable: '当前无法读取外部原文，可能没有权限或磁盘不可用。',
  disconnected: '连接已断开，本次没有读取磁盘。',
  not_applicable: '这份资料不是 Obsidian 快照。',
};

export function ObsidianSourceReview({ kind, id, version, disabled }: {
  kind: MaterialKind; id: string; version: MaterialVersion; disabled?: boolean;
}) {
  const source = obsidianSource(version);
  const [checking, setChecking] = useState(false);
  const [status, setStatus] = useState<ObsidianSourceStatus | null>(null);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState('');
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  if (!source) return null;
  async function check() {
    setChecking(true); setError(''); setCopied('');
    try {
      const result = await getObsidianSourceStatus(kind, id, version.id);
      if (mounted.current) setStatus(result);
    } catch (reason) {
      if (mounted.current) setError(obsidianError(reason, '无法检查外部原文，请稍后重试。'));
    } finally { if (mounted.current) setChecking(false); }
  }
  async function copy() {
    setError('');
    try {
      await navigator.clipboard.writeText(source!.relative_path);
      if (mounted.current) setCopied('已复制相对路径。');
    } catch {
      if (mounted.current) setCopied(`请手动复制：${source!.relative_path}`);
    }
  }
  return <div className="task-material-obsidian-source">
    <p><strong>Obsidian 保存快照</strong> · Vault「{source.vault_name}」· 相对路径 {source.relative_path} · Nautilus 第 {version.version} 版 · 保存于 {source.captured_at} · 内容指纹 {source.sha256.slice(0, 12)}… · 全文（第 {source.locator.start_line}–{source.locator.end_line} 行）</p>
    <div className="task-material-obsidian-source-actions">
      <a href={obsidianUri(source.vault_name, source.relative_path)} target="_blank" rel="noopener noreferrer">在 Obsidian 打开</a>
      <button type="button" className="text-button" onClick={() => void copy()}>复制相对路径</button>
      <button type="button" className="text-button" disabled={disabled || checking} onClick={() => void check()}>{checking ? '正在检查…' : '检查原文变化'}</button>
    </div>
    <small>这里显示的是 Nautilus 保存的快照；外部原文可能已经变化。在 Obsidian 打开需要当前设备已安装 Obsidian 且有同名 Vault，无法确认是否真的打开成功。</small>
    {status && <p role="status">{statusLabel[status.status]}{status.checked_at ? `（检查时间 ${status.checked_at}）` : ''}</p>}
    {copied && <p role="status">{copied}</p>}
    {error && <p role="alert">{error}</p>}
  </div>;
}

export default function ObsidianMaterials({ kind, id, disabled, onCaptured }: {
  kind: MaterialKind; id: string | null; disabled?: boolean;
  /** Resolves true only when the current conversation state accepted this version.
   *  The second argument lets the parent refuse an operation that was cancelled
   *  (panel closed, section collapsed, context switched) while it was waiting. */
  onCaptured: (version: MaterialVersion, isOperationCurrent: () => boolean) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [connection, setConnection] = useState<ObsidianConnection | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<ObsidianSearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [savingToken, setSavingToken] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  // session: which conversation/identity this component instance is showing.
  // page: which search or load request may still publish its result.
  // operation: which capture may still apply a selection after it returns.
  const session = useRef(0);
  const page = useRef(0);
  const operation = useRef(0);
  useEffect(() => {
    const context = ++session.current;
    const current = ++page.current;
    operation.current++;
    setResult(null); setQuery(''); setError(''); setNotice(''); setSavingToken(''); setBusy(false); setLoading(false); setOpen(false); setLoaded(false);
    void getObsidianConnection().then(data => { if (session.current === context && page.current === current) setConnection(data.connection); })
      .catch(() => { if (session.current === context && page.current === current) setConnection(null); });
    return () => { session.current++; };
  }, [kind, id]);
  async function load() {
    if (busy || loading) return;
    const context = session.current;
    const current = ++page.current;
    setLoading(true); setResult(null); setError('');
    try {
      const data = await getObsidianConnection();
      if (session.current === context && page.current === current) { setConnection(data.connection); setLoaded(true); }
    } catch (reason) {
      if (session.current === context && page.current === current) setError(obsidianError(reason, '无法读取 Obsidian 连接设置。'));
    } finally { if (session.current === context && page.current === current) setLoading(false); }
  }
  async function runSearch(after?: string) {
    if (!id || !connection?.enabled || busy || loading) return;
    const context = session.current;
    const current = ++page.current;
    setBusy(true); setError(''); setNotice('');
    try {
      const data = await searchObsidianNotes(kind, id, { connection_id: connection.connection_id, connection_revision: connection.revision, query, after });
      if (session.current === context && page.current === current) setResult(data);
    } catch (reason) {
      if (session.current === context && page.current === current) { setResult(null); setError(obsidianError(reason, '检索失败，可重试。')); }
    } finally { if (session.current === context && page.current === current) setBusy(false); }
  }
  async function saveSnapshot(item: ObsidianSearchItem) {
    if (!id) return;
    const context = session.current;
    const current = ++operation.current;
    // Collapsing this section, closing the outer panel, unmounting or switching the
    // conversation all advance one of these counters, so the capture stops applying.
    const isOperationCurrent = () => session.current === context && operation.current === current;
    setSavingToken(item.selection_token); setError(''); setNotice('');
    try {
      const version = await captureObsidianNote(kind, id, item.selection_token);
      if (!isOperationCurrent()) return;
      const applied = await onCaptured(version, isOperationCurrent);
      if (!isOperationCurrent()) return;
      if (applied === true) setNotice(`已保存「${item.relative_path}」的快照并选用第 ${version.version} 版。`);
      else setError('快照已保存，但当前选择未确认，请读取最新状态后重试。');
    } catch (reason) {
      if (isOperationCurrent()) setError(obsidianError(reason, '未能保存快照，可重试。'));
    } finally { if (isOperationCurrent()) setSavingToken(''); }
  }
  return <section className="task-material-obsidian" aria-label="从 Obsidian 选用">
    <button type="button" className="button button--quiet" aria-expanded={open} disabled={!id} onClick={() => {
      const next = !open;
      if (!next) {
        // Fold this entry away: nothing that is still in flight may apply a selection.
        operation.current++; page.current++;
        setResult(null); setSavingToken(''); setBusy(false); setLoading(false); setError(''); setNotice('');
      }
      setOpen(next);
      if (next) void load();
    }}>从 Obsidian 选用</button>
    {open && !id && <p>请先打开对话，再检索 Obsidian 笔记。</p>}
    {open && id && <div className="task-material-obsidian-panel">
      {loading && !loaded && <p role="status">正在读取连接设置…</p>}
      {loaded && !connection && <p>还没有连接本地 Vault。请到“设置 → 知识库”填写后端主机上的 Vault 路径。</p>}
      {loaded && connection && !connection.enabled && <p role="alert">Obsidian 连接已断开（Vault「{connection.vault_name}」）。重新连接后才能检索和保存新的快照；已保存的快照仍可查看。</p>}
      {loaded && connection?.enabled && <>
        <p>当前 Vault：<strong>{connection.vault_name}</strong>。检索只读取 .md 文件，不会修改 Obsidian 原文。</p>
        <div className="task-material-obsidian-search">
          <label>检索笔记<input value={query} disabled={busy || loading} placeholder="留空列出笔记" onChange={event => { setQuery(event.target.value); setResult(null); }} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); void runSearch(); } }} /></label>
          <button type="button" className="button button--quiet" disabled={busy || loading} onClick={() => void runSearch()}>{busy ? '检索中…' : '检索'}</button>
        </div>
        <p className="form-hint">按相对路径或正文文字匹配（不区分大小写）；一次检索最多显示 50 份，可翻页。检索不会自动导入或入库。</p>
        {result && result.unreadable_count > 0 && <p role="alert">有 {result.unreadable_count} 个文件或目录未能读取，结果可能不完整，不能当作“完整检索没有结果”。</p>}
        {result && result.items.length === 0 && !busy && <p>没有匹配的笔记（本次遍历{result.complete ? '未发现读取失败' : '存在读取失败'}）。</p>}
        {result && result.items.length > 0 && <ul className="task-material-obsidian-list">{result.items.map(item => <li key={item.selection_token}>
          <p><strong>{item.title}</strong> · {item.relative_path} · 第 {item.excerpt_start_line}–{item.excerpt_end_line} 行 · 内容指纹 {item.sha256.slice(0, 12)}…</p>
          {item.excerpt && <p className="task-material-obsidian-excerpt">{item.excerpt}</p>}
          <p className="form-hint">摘要只帮助选择文档，不代表模型实际引用过这一句。</p>
          <button type="button" className="button button--quiet" disabled={disabled || busy || loading || Boolean(savingToken)} onClick={() => void saveSnapshot(item)}>{savingToken === item.selection_token ? '正在保存…' : '保存快照并选用'}</button>
        </li>)}</ul>}
        {result && <p className="task-material-obsidian-hint">“保存快照并选用”会把这份笔记快照存入 Nautilus 资料库并用于当前对话；不会导入整个 Vault，也不会修改 Obsidian 原文。保存的正文会作为当前对话的教学模型输入。</p>}
        {result?.has_more && result.next_after && <button type="button" className="button button--quiet" disabled={busy || loading} onClick={() => void runSearch(result.next_after ?? undefined)}>下一页</button>}
        {result?.has_more && !result.next_after && <p role="alert">还有更多候选，但服务端没有返回可用的翻页位置。请重新检索，不要把它当作已看完。</p>}
        <button type="button" className="text-button" disabled={busy || loading} onClick={() => void load()}>{loading ? '正在读取…' : '重新读取连接状态'}</button>
      </>}
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert">{error}</p>}
    </div>}
  </section>;
}
