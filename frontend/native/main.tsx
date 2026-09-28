import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import LearningMarkdown from '../src/LearningMarkdown';
import './style.css';

type ProviderSettings = { base_url: string; model: string };
type Material = { id: string; title: string; content: string; version: number; revision_id: string };
type MaterialConflict = { material_id: string; versions: Material[] };
type SelectionRevision = { id: string; parents: string[]; material_ids: string[] };
type Turn = {
  id: string; request_id: string; question: string; answer: string; reasoning: string;
  status: string; error: string | null; materials: Material[]; provider: ProviderSettings;
  parent_id: string | null; origin_device: string;
};
type Snapshot = {
  device_id: string; schema_version: number; materials: Material[];
  material_conflicts: MaterialConflict[]; selection_heads: SelectionRevision[];
  turns: Turn[]; settings: ProviderSettings;
};
type LocalStatus = { needs_upgrade: boolean; error: string | null };
type SyncStatus = {
  device_name: string; invitation: string | null;
  peers: { id: string; name: string; status: string }[];
  pending: { id: string; name: string; confirmed: boolean }[];
};
type TauriBridge = {
  core: { invoke<T>(name: string, args?: Record<string, unknown>): Promise<T> };
  event: { listen<T>(name: string, handler: (event: { payload: T }) => void): Promise<() => void> };
};

declare global { interface Window { __TAURI__?: TauriBridge } }

const bridge = () => {
  if (!window.__TAURI__) throw new Error('请在 Nautilus 验证应用中打开此页面。');
  return window.__TAURI__;
};
const message = (error: unknown) => error instanceof Error ? error.message : String(error);
const statusLabel: Record<string, string> = {
  pending: '生成中', complete: '已完成', failed: '失败', canceled: '已取消', interrupted: '已中断',
};
const selectedHead = (snapshot: Snapshot) => snapshot.selection_heads.length === 1 ? snapshot.selection_heads[0] : null;
const leafTurns = (turns: Turn[]) => {
  const parents = new Set(turns.map(turn => turn.parent_id));
  return turns.filter(turn => !parents.has(turn.id));
};
const branchPath = (turns: Turn[], tipId: string | null) => {
  const byId = new Map(turns.map(turn => [turn.id, turn]));
  const path: Turn[] = [];
  const seen = new Set<string>();
  let id = tipId;
  while (id && !seen.has(id)) {
    const turn = byId.get(id);
    if (!turn) break;
    path.unshift(turn);
    seen.add(id);
    id = turn.parent_id;
  }
  return path;
};

function Markdown({ text }: { text: string }) {
  return <div className="markdown" onClick={(event) => {
    if ((event.target as HTMLElement).closest('a')) event.preventDefault();
  }}><LearningMarkdown>{text}</LearningMarkdown></div>;
}

function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [localStatus, setLocalStatus] = useState<LocalStatus | null>(null);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [deviceName, setDeviceName] = useState('');
  const [joinCode, setJoinCode] = useState('');
  const [settings, setSettings] = useState<ProviderSettings>({ base_url: '', model: '' });
  const [apiKey, setApiKey] = useState('');
  const [keySaved, setKeySaved] = useState<boolean | null>(null);
  const [keyError, setKeyError] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [selectionDirty, setSelectionDirty] = useState(false);
  const [selectionChanged, setSelectionChanged] = useState(false);
  const [materialId, setMaterialId] = useState<string | null>(null);
  const [materialRevisionId, setMaterialRevisionId] = useState<string | null>(null);
  const [materialTitle, setMaterialTitle] = useState('');
  const [materialContent, setMaterialContent] = useState('');
  const [draft, setDraft] = useState('');
  const [activeTip, setActiveTip] = useState<string | null>(null);
  const [branchReady, setBranchReady] = useState(false);
  const [activeRequestId, setActiveRequestId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const activeRequestRef = useRef<string | null>(null);
  const alive = useRef(true);
  const initialized = useRef(false);
  const selectionDirtyRef = useRef(false);
  const selectionHeadRef = useRef<string | null>(null);
  const nameDirtyRef = useRef(false);
  const refreshSequence = useRef(0);
  const knownTurnIds = useRef(new Set<string>());

  async function refresh() {
    const sequence = ++refreshSequence.current;
    const next = await bridge().core.invoke<Snapshot>('snapshot');
    if (!alive.current || sequence !== refreshSequence.current) return next;
    const previousIds = knownTurnIds.current;
    knownTurnIds.current = new Set(next.turns.map(turn => turn.id));
    if (initialized.current && !activeRequestRef.current) {
      setActiveTip(current => {
        // Follow new continuations only; do not switch to a sibling or leave an
        // explicitly selected empty conversation when history already exists.
        if (current === null && previousIds.size > 0) return current;
        let tip = current;
        while (true) {
          const children = next.turns.filter(turn => turn.parent_id === tip);
          if (children.length !== 1 || previousIds.has(children[0].id)) return tip;
          tip = children[0].id;
        }
      });
    }
    setSnapshot(next);
    const head = selectedHead(next);
    if (!initialized.current) {
      initialized.current = true;
      selectionHeadRef.current = head?.id ?? null;
      setSelected(head?.material_ids ?? []);
      const leaves = leafTurns(next.turns);
      if (leaves.length <= 1) { setActiveTip(leaves[0]?.id ?? null); setBranchReady(true); }
    } else if (selectionDirtyRef.current) {
      if (selectionHeadRef.current !== (head?.id ?? null) || next.selection_heads.length > 1) setSelectionChanged(true);
    } else {
      selectionHeadRef.current = head?.id ?? null;
      setSelected(head?.material_ids ?? []);
      setSelectionChanged(false);
    }
    return next;
  }

  async function refreshSync() {
    const next = await bridge().core.invoke<SyncStatus>('sync_status');
    if (alive.current) {
      setSyncStatus(next);
      if (!nameDirtyRef.current) setDeviceName(next.device_name);
    }
  }

  useEffect(() => {
    alive.current = true;
    let unlistenTurn: (() => void) | undefined;
    let unlistenSync: (() => void) | undefined;
    let disposed = false;
    (async () => {
      try {
        unlistenTurn = await bridge().event.listen<Turn>('native-turn', ({ payload }) => {
          if (disposed) return;
          if (payload.request_id === activeRequestRef.current) setActiveTip(payload.id);
          setSnapshot(current => current && ({
            ...current,
            turns: current.turns.some(turn => turn.id === payload.id)
              ? current.turns.map(turn => turn.id === payload.id ? payload : turn)
              : [...current.turns, payload],
          }));
        });
        unlistenSync = await bridge().event.listen<null>('native-sync', () => {
          if (disposed) return;
          void Promise.all([refresh(), refreshSync()]).catch(cause => setError(message(cause)));
        });
        if (disposed) { unlistenTurn(); unlistenSync(); return; }
        const status = await bridge().core.invoke<LocalStatus>('local_status');
        if (disposed) return;
        setLocalStatus(status);
        if (status.error) setError(status.error);
        if (!status.needs_upgrade && !status.error) {
          const next = await refresh();
          if (!disposed) setSettings(next.settings);
          await refreshSync();
        }
      } catch (cause) {
        if (!disposed) setError(message(cause));
      }
    })();
    return () => { disposed = true; alive.current = false; unlistenTurn?.(); unlistenSync?.(); };
  }, []);

  useEffect(() => { setApiKey(''); }, [settings.base_url]);
  useEffect(() => {
    let canceled = false;
    setKeySaved(null); setKeyError('');
    const baseUrl = snapshot?.settings.base_url;
    if (baseUrl) void bridge().core.invoke<boolean>('credential_status', { baseUrl })
      .then(saved => { if (!canceled) setKeySaved(saved); })
      .catch(cause => { if (!canceled) setKeyError(message(cause)); });
    return () => { canceled = true; };
  }, [snapshot?.settings.base_url]);

  async function changeKey(remove: boolean) {
    if (!snapshot || hasUnsavedSettings) return;
    const baseUrl = snapshot.settings.base_url;
    setBusy('key'); setError(''); setNotice('');
    try {
      if (remove) await bridge().core.invoke<void>('delete_credential', { baseUrl });
      else await bridge().core.invoke<void>('save_credential', { baseUrl, key: apiKey });
      setKeySaved(!remove); setKeyError(''); setApiKey('');
      setNotice(remove ? '已删除此接口在本机保存的 Key，其他设备不受影响。' : 'Key 已保存在本机，重开应用后会自动使用。');
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(null); }
  }

  async function upgrade() {
    setBusy('upgrade'); setError(''); setNotice('');
    try {
      const backup = await bridge().core.invoke<string>('upgrade_local_data');
      const next = await refresh();
      setSettings(next.settings);
      await refreshSync();
      setLocalStatus({ needs_upgrade: false, error: null });
      setNotice(`本机数据已升级。升级前备份：${backup}`);
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(null); }
  }

  async function saveSettings() {
    setBusy('settings'); setError(''); setNotice('');
    try {
      await bridge().core.invoke<void>('save_settings', { settings });
      await refresh();
      setNotice('模型设置已保存在这台设备。');
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(null); }
  }

  function clearMaterialEditor() {
    setMaterialId(null); setMaterialRevisionId(null); setMaterialTitle(''); setMaterialContent('');
  }

  async function saveMaterial() {
    setBusy('material'); setError(''); setNotice('');
    try {
      const saved = await bridge().core.invoke<Material>('save_material', {
        id: materialId, title: materialTitle, content: materialContent,
        expectedRevisionId: materialRevisionId,
      });
      const next = await refresh();
      if (!materialId) await saveSelection([...selected, saved.id], next.selection_heads.map(head => head.id));
      clearMaterialEditor();
      setNotice(`资料已保存为第 ${saved.version} 版。后续发送将使用当前版本。`);
    } catch (cause) {
      setError(message(cause));
      try { await refresh(); } catch { /* Preserve the save error and the editor draft. */ }
    } finally { setBusy(null); }
  }

  async function saveSelection(ids: string[], expectedSelectionIds = snapshot?.selection_heads.map(head => head.id) ?? []) {
    setBusy('selection');
    selectionDirtyRef.current = true;
    setSelectionDirty(true);
    setSelected(ids);
    setError('');
    try {
      await bridge().core.invoke<void>('save_selection', { materialIds: ids, expectedSelectionIds });
      const next = await refresh();
      const head = selectedHead(next);
      if (head && head.material_ids.length === ids.length && head.material_ids.every(id => ids.includes(id))) {
        selectionHeadRef.current = head.id;
        selectionDirtyRef.current = false;
        setSelectionDirty(false);
        setSelectionChanged(false);
      } else {
        setSelectionChanged(true);
      }
    } catch (cause) {
      setError(message(cause));
      try { await refresh(); } catch { /* Keep the local selection and actionable error. */ }
    } finally { setBusy(null); }
  }

  async function resolveSelection(chosenRevisionId: string) {
    setBusy('selection'); setError('');
    try {
      await bridge().core.invoke<void>('resolve_selection', {
        chosenRevisionId, expectedHeadIds: snapshot?.selection_heads.map(head => head.id) ?? [],
      });
      selectionDirtyRef.current = false;
      setSelectionDirty(false);
      setSelectionChanged(false);
      await refresh();
    } catch (cause) {
      setError(message(cause));
      try { await refresh(); } catch { /* Keep the resolution error visible. */ }
    }
    finally { setBusy(null); }
  }

  async function resolveMaterial(materialId: string, chosenRevisionId: string) {
    setBusy('material-conflict'); setError('');
    try {
      await bridge().core.invoke<void>('resolve_material', {
        materialId, chosenRevisionId,
        expectedHeadIds: snapshot?.material_conflicts.find(conflict => conflict.material_id === materialId)?.versions.map(version => version.revision_id) ?? [],
      });
      await refresh();
      setNotice('已选定资料版本。');
    } catch (cause) {
      setError(message(cause));
      try { await refresh(); } catch { /* Keep the resolution error visible. */ }
    }
    finally { setBusy(null); }
  }

  async function syncAction(name: string, args?: Record<string, unknown>) {
    setBusy('sync'); setError(''); setNotice('');
    try {
      const result = await bridge().core.invoke<void | string>(name, args);
      await refreshSync();
      if (name === 'sync_set_name') nameDirtyRef.current = false;
      if (name === 'sync_join') setJoinCode('');
      if (name === 'sync_invite' && typeof result === 'string') setSyncStatus(current => current && ({ ...current, invitation: result }));
      if (name === 'sync_unpair') setNotice('已解除配对，两台设备已保存的资料和对话仍各自保留。');
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(null); }
  }

  async function send() {
    if (!draft.trim() || activeRequestId || busy || hasUnsavedSettings || !branchReady || selectionDirty || selectionChanged || (snapshot?.selection_heads.length ?? 0) > 1 || selected.some(id => snapshot?.material_conflicts.some(conflict => conflict.material_id === id))) return;
    const expectedRevisionIds = selected.map(id => snapshot?.materials.find(material => material.id === id)?.revision_id);
    if (expectedRevisionIds.some(id => !id)) { setError('所选资料已变化，请重新确认资料选择。'); return; }
    const sentDraft = draft;
    const requestId = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
    activeRequestRef.current = requestId;
    setActiveRequestId(requestId); setError(''); setNotice('');
    try {
      const turn = await bridge().core.invoke<Turn>('send_message', {
        requestId, question: sentDraft, materialIds: selected, apiKey, parentId: activeTip,
        expectedBaseUrl: snapshot?.settings.base_url,
        expectedSelectionIds: snapshot?.selection_heads.map(head => head.id) ?? [],
        expectedRevisionIds,
      });
      setActiveTip(turn.id);
      await refresh();
      if (turn.status === 'complete') { setDraft(current => current === sentDraft ? '' : current); setNotice('回答已保存。'); }
      else setNotice('本次回答未完成。问题仍留在输入框，可以修改后重新发送。');
    } catch (cause) {
      setError(message(cause));
      try { await refresh(); } catch { /* Keep the actionable send error visible. */ }
    } finally { activeRequestRef.current = null; setActiveRequestId(null); }
  }

  async function cancel() {
    if (!activeRequestId) return;
    setError('');
    try {
      await bridge().core.invoke<void>('cancel_generation', { requestId: activeRequestId });
      setNotice('已请求停止，正在保存已生成的部分。');
    } catch (cause) { setError(message(cause)); }
  }

  const hasUnsavedSettings = Boolean(snapshot && (settings.base_url !== snapshot.settings.base_url || settings.model !== snapshot.settings.model));
  const pendingTurn = snapshot?.turns.find(turn => turn.request_id === activeRequestId);
  const leaves = snapshot ? leafTurns(snapshot.turns) : [];
  const path = snapshot && branchReady ? branchPath(snapshot.turns, activeTip) : [];
  const selectionBlocked = selectionDirty || selectionChanged || (snapshot?.selection_heads.length ?? 0) > 1;
  const sendBlocked = !draft.trim() || Boolean(activeRequestId) || Boolean(busy) || hasUnsavedSettings || !branchReady || selectionBlocked || selected.some(id => snapshot?.material_conflicts.some(conflict => conflict.material_id === id));
  return <main className="shell">
    <header className="masthead">
      <span className="eyebrow">NAUTILUS · 独立运行验证版</span>
      <h1>在这台设备上继续学习</h1>
      <p>文字资料和已保存对话留在本设备。配对后可在同一局域网、两台应用都运行时同步；不会读取原有 trial 数据，也不会同步 API Key。卸载应用或清除应用数据可能移除本机记录。</p>
      {snapshot && <small>设备编号：<code>{snapshot.device_id}</code> · 本机数据版本 {snapshot.schema_version}</small>}
    </header>

    {error && <div className="alert alert--error" role="alert">{error}</div>}
    {notice && <div className="alert" role="status">{notice}</div>}
    {localStatus?.needs_upgrade && <section className="panel upgrade"><h2>需要升级本机数据</h2><p>此设备已有旧版验证数据。升级前会先创建备份，并保留已有文字资料和对话。升级由你明确启动。</p><button type="button" onClick={() => void upgrade()} disabled={Boolean(busy)}>备份并升级本机数据</button></section>}
    {!snapshot && !localStatus?.needs_upgrade && !error && <p role="status">正在读取本机数据…</p>}
    {snapshot && <div className="layout">
      <section className="panel settings" aria-labelledby="settings-heading">
        <div className="section-head"><div><span className="eyebrow">01 / 连接</span><h2 id="settings-heading">模型服务</h2></div></div>
        <label>兼容 OpenAI 的 HTTPS 地址（以 /v1 结尾）
          <input type="url" disabled={Boolean(busy) || Boolean(activeRequestId)} value={settings.base_url} onChange={e => setSettings({ ...settings, base_url: e.target.value })} placeholder="https://example.com/v1" autoComplete="url" />
        </label>
        <label>模型名称
          <input disabled={Boolean(busy) || Boolean(activeRequestId)} value={settings.model} onChange={e => setSettings({ ...settings, model: e.target.value })} placeholder="填写服务提供的模型名称" />
        </label>
        <button type="button" className="secondary" onClick={() => void saveSettings()} disabled={Boolean(busy) || Boolean(activeRequestId)}>保存模型设置</button>
        <label>API Key
          <input type="password" value={apiKey} disabled={Boolean(busy) || Boolean(activeRequestId) || hasUnsavedSettings} onChange={e => setApiKey(e.target.value)} autoComplete="off" placeholder={keySaved ? '已保存，输入可替换' : '输入此接口的 Key'} />
        </label>
        <p className="hint" role="status">{hasUnsavedSettings ? '先保存模型设置，再管理此接口的 Key。' : keyError || (keySaved === true ? '此接口的 Key 已保存在本机，重开后自动使用。' : keySaved === false ? '此接口尚未保存 Key。' : '请先设置模型接口。')}</p>
        {apiKey && <p className="hint">当前输入尚未保存；直接发送仅用于本次运行。点击“保存 Key”后，重开应用也能使用。</p>}
        <div className="actions"><button type="button" className="secondary" disabled={!apiKey.trim() || hasUnsavedSettings || Boolean(busy) || Boolean(activeRequestId)} onClick={() => void changeKey(false)}>保存 Key</button><button type="button" className="text-button" disabled={!snapshot.settings.base_url || hasUnsavedSettings || keySaved === false || Boolean(busy) || Boolean(activeRequestId)} onClick={() => void changeKey(true)}>删除本机 Key</button></div>
        <p className="hint">Key 按接口地址分别保存，由本机系统保护，不参与设备同步。同一接口切换模型无需重新填写。</p>
        <p className="hint">{hasUnsavedSettings ? '模型设置已修改，请保存后再发送。' : `发送使用已保存的服务：${snapshot.settings.base_url || '尚未设置'}。`}</p>
        <p className="hint">发送时会把问题、所选资料，以及当前对话分支中资料版本一致的连续成功对话发送到此模型服务。修改选用资料或其版本会开始新的上下文范围。</p>
      </section>

      <section className="panel materials" aria-labelledby="materials-heading">
        <div className="section-head"><div><span className="eyebrow">02 / 参考</span><h2 id="materials-heading">本机资料</h2></div><span className="count">已选 {selected.length}</span></div>
        {snapshot.selection_heads.length > 1 && <div className="choice-block"><h3>选用资料有不同版本</h3><p className="hint">两台设备更改了资料选择。请选择一份选择结果，才能继续发送。</p>{snapshot.selection_heads.map(head => <div className="choice-row" key={head.id}><span>{head.material_ids.length ? head.material_ids.map(id => snapshot.materials.find(material => material.id === id)?.title || id).join('、') : '不选资料'}</span><button type="button" className="secondary" disabled={Boolean(busy)} onClick={() => void resolveSelection(head.id)}>采用这份选择</button></div>)}</div>}
        {selectionDirty && snapshot.selection_heads.length <= 1 && <div className="choice-block"><p>{selectionChanged ? '其他设备更新了资料选择。你当前的选择仍在此处，请决定如何继续。' : '当前选择尚未保存。你可以重试，或采用已保存的选择。'}</p><div className="actions"><button type="button" className="secondary" disabled={Boolean(busy)} onClick={() => void saveSelection(selected)}>重新应用我的选择</button><button type="button" className="secondary" disabled={Boolean(busy)} onClick={() => { selectionDirtyRef.current = false; setSelectionDirty(false); setSelectionChanged(false); setSelected(selectedHead(snapshot)?.material_ids ?? []); selectionHeadRef.current = selectedHead(snapshot)?.id ?? null; }}>采用已保存的选择</button></div></div>}
        {snapshot.material_conflicts.map(conflict => <div className="choice-block" key={conflict.material_id}><h3>资料“{conflict.versions[0]?.title || '未命名资料'}”有不同版本</h3><p className="hint">各版本都保留。展开阅读完整内容，然后选定后续使用的版本。</p>{conflict.versions.map(version => <div className="conflict-version" key={version.revision_id}><strong>{version.title || '未命名资料'} · 第 {version.version} 版</strong><details><summary>查看完整内容</summary><pre>{version.content}</pre></details><button type="button" className="secondary" disabled={Boolean(busy)} onClick={() => void resolveMaterial(conflict.material_id, version.revision_id)}>采用此版本</button></div>)}</div>)}
        {snapshot.materials.length === 0 && <p className="empty">还没有资料。可先贴入文字保存，也可以不选资料直接提问。</p>}
        <div className="material-list">{snapshot.materials.map(material => <div className="material" key={material.id}>
          <label className="material-choice"><input type="checkbox" checked={selected.includes(material.id)} disabled={Boolean(busy) || snapshot.selection_heads.length > 1} onChange={e => void saveSelection(e.target.checked ? [...selected, material.id] : selected.filter(id => id !== material.id))} /><span><strong>{material.title || '未命名资料'}</strong><small>第 {material.version} 版</small></span></label>
          <div className="material-actions"><button type="button" className="text-button" onClick={() => { setMaterialId(material.id); setMaterialRevisionId(material.revision_id); setMaterialTitle(material.title); setMaterialContent(material.content); }}>编辑</button><details><summary>查看内容</summary><pre>{material.content}</pre></details></div>
        </div>)}</div>
        <form onSubmit={e => { e.preventDefault(); void saveMaterial(); }} className="material-form">
          <h3>{materialId ? '编辑资料（保存为新版本）' : '新增文字资料'}</h3>
          <label>标题<input value={materialTitle} onChange={e => setMaterialTitle(e.target.value)} placeholder="例如：课程笔记" /></label>
          <label>内容<textarea value={materialContent} onChange={e => setMaterialContent(e.target.value)} rows={6} placeholder="粘贴需要参考的文字" /></label>
          <div className="actions"><button type="submit" className="secondary" disabled={Boolean(busy) || Boolean(activeRequestId)}>{materialId ? '保存新版本' : '保存并选用'}</button>{materialId && <button type="button" className="text-button" onClick={clearMaterialEditor}>取消编辑</button>}</div>
        </form>
      </section>

      <section className="panel conversation" aria-labelledby="conversation-heading">
        <div className="section-head"><div><span className="eyebrow">03 / 对话</span><h2 id="conversation-heading">学习对话</h2></div><span className="count">{snapshot.turns.length} 轮</span></div>
        {leaves.length > 0 && <div className="branch-picker"><h3>选择继续的对话</h3><p className="hint">不同设备接续同一轮时会形成分支。选择一条路径后继续提问；切换不会删除任何对话。</p>{leaves.map(leaf => <button type="button" className={branchReady && activeTip === leaf.id ? 'branch active' : 'branch'} key={leaf.id} onClick={() => { setActiveTip(leaf.id); setBranchReady(true); }}><span>{leaf.question || '未命名对话'}</span><small>{leaf.origin_device === snapshot.device_id ? '本设备' : '其他设备'} · {statusLabel[leaf.status] || leaf.status}</small></button>)}<button type="button" className={branchReady && activeTip === null ? 'branch active' : 'branch'} onClick={() => { setActiveTip(null); setBranchReady(true); }}>开始新对话</button></div>}
        {snapshot.turns.length === 0 && <p className="empty">输入一个问题，开始本机验证对话。</p>}
        {!branchReady && snapshot.turns.length > 0 && <p className="empty">请选择一条对话路径，再继续提问。</p>}
        <div className="turns" aria-live="polite">{path.map((turn, index) => <article className="turn" key={turn.id}>
          <div className="turn-head"><strong>第 {index + 1} 轮</strong><span className={`status status--${turn.status}`}>{statusLabel[turn.status] || turn.status}</span></div>
          <div className="question"><span className="eyebrow">我的问题</span><Markdown text={turn.question} /></div>
          <div className="answer"><span className="eyebrow">回答</span>{turn.answer ? <Markdown text={turn.answer} /> : <p className="hint">{turn.status === 'pending' ? '正在等待回答…' : '没有生成回答正文。'}</p>}</div>
          {turn.reasoning && <details><summary>查看模型思考内容</summary><Markdown text={turn.reasoning} /></details>}
          {turn.error && <p className="turn-error">{turn.error}</p>}
          <details className="turn-context"><summary>本轮使用条件</summary><p>模型：{turn.provider.model || '未设置'} · 地址：{turn.provider.base_url || '未设置'}</p><p>资料：{turn.materials.length ? turn.materials.map(material => `${material.title || '未命名资料'}（第 ${material.version} 版）`).join('、') : '未选用'}</p></details>
        </article>)}</div>
        <form className="composer" onSubmit={e => { e.preventDefault(); void send(); }}>
          <label htmlFor="question">继续提问</label>
          <textarea id="question" value={draft} onChange={e => setDraft(e.target.value)} rows={4} placeholder="写下想弄明白的问题" />
          {selectionBlocked && <p className="hint">请先确认选用资料，再发送问题。</p>}
          {selected.some(id => snapshot.material_conflicts.some(conflict => conflict.material_id === id)) && <p className="hint">所选资料存在不同版本，请先选择要使用的版本。</p>}
          <div className="composer-footer"><small>本次选择 {selected.length} 份资料{pendingTurn?.status === 'pending' ? ' · 正在生成' : ''}</small><div className="actions">{activeRequestId && <button type="button" className="secondary" onClick={() => void cancel()} disabled={pendingTurn?.status !== 'pending'}>停止回答</button>}<button type="submit" disabled={sendBlocked}>发送</button></div></div>
        </form>
      </section>

      <section className="panel sync" aria-labelledby="sync-heading">
        <div className="section-head"><div><span className="eyebrow">04 / 同步</span><h2 id="sync-heading">局域网设备同步</h2></div><button type="button" className="secondary" disabled={Boolean(busy)} onClick={() => void syncAction('sync_restart')}>重试连接</button></div>
        <p className="hint">两台设备需在同一局域网，且应用保持运行。仅同步本验证版的文字资料和已保存对话；不经过外部中转服务。模型设置和 API Key 留在各自设备。手机如提示本地网络权限，请允许；允许后可点“重试连接”。</p>
        <label>这台设备的名称<input value={deviceName} onChange={e => { nameDirtyRef.current = true; setDeviceName(e.target.value); }} /></label>
        <button type="button" className="secondary" disabled={Boolean(busy) || !deviceName.trim()} onClick={() => void syncAction('sync_set_name', { name: deviceName })}>保存设备名称</button>
        <div className="sync-group"><h3>邀请另一台设备</h3><button type="button" className="secondary" disabled={Boolean(busy)} onClick={() => void syncAction('sync_invite')}>生成配对码</button>{syncStatus?.invitation && <><p className="hint">配对码 10 分钟内有效，请在另一台设备输入：</p><input className="invitation" readOnly value={syncStatus.invitation} onFocus={e => e.currentTarget.select()} aria-label="配对码" /><button type="button" className="text-button" onClick={() => { if (navigator.clipboard) void navigator.clipboard.writeText(syncStatus.invitation!).catch(() => setNotice('复制未成功，请选中上方配对码手动复制。')); else setNotice('请选中上方配对码手动复制。'); }}>复制配对码</button></>}</div>
        <form className="sync-group" onSubmit={e => { e.preventDefault(); void syncAction('sync_join', { code: joinCode.trim() }); }}><h3>输入另一台设备的配对码</h3><input value={joinCode} onChange={e => setJoinCode(e.target.value)} placeholder="输入 10 分钟内生成的配对码" /><button type="submit" className="secondary" disabled={Boolean(busy) || !joinCode.trim()}>发送配对请求</button></form>
        {(syncStatus?.pending.length ?? 0) > 0 && <div className="sync-group"><h3>等待配对确认</h3><p className="hint">请核对两台设备显示的名称，并在两台设备分别确认后开始交换内容。</p>{syncStatus?.pending.map(peer => <div className="peer" key={peer.id}><strong>{peer.name}</strong><span>{peer.confirmed ? '这台设备已确认，等待对方确认' : '等待这台设备确认'}</span><div className="actions">{!peer.confirmed && <button type="button" className="secondary" disabled={Boolean(busy)} onClick={() => void syncAction('sync_confirm', { peerId: peer.id })}>确认配对</button>}<button type="button" className="text-button" disabled={Boolean(busy)} onClick={() => void syncAction('sync_reject', { peerId: peer.id })}>拒绝</button></div></div>)}</div>}
        {(syncStatus?.peers.length ?? 0) > 0 && <div className="sync-group"><h3>已配对设备</h3>{syncStatus?.peers.map(peer => <div className="peer" key={peer.id}><strong>{peer.name}</strong><span>{peer.status}</span><button type="button" className="text-button" disabled={Boolean(busy)} onClick={() => { if (window.confirm(`解除与“${peer.name}”的配对？两台设备已保存的资料和对话会各自保留，之后需要重新配对才能同步。`)) void syncAction('sync_unpair', { peerId: peer.id }); }}>解除配对</button></div>)}</div>}
      </section>
    </div>}
  </main>;
}

createRoot(document.getElementById('root')!).render(<App />);
