import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import LearningMarkdown from '../src/LearningMarkdown';
import './style.css';

type ProviderSettings = { base_url: string; model: string };
type Material = { id: string; title: string; content: string; version: number };
type Turn = {
  id: string; request_id: string; question: string; answer: string; reasoning: string;
  status: string; error: string | null; materials: Material[]; provider: ProviderSettings;
};
type Snapshot = {
  device_id: string; schema_version: number; materials: Material[]; turns: Turn[];
  settings: ProviderSettings;
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

function Markdown({ text }: { text: string }) {
  // The shared renderer opens links in a new tab. Keep this isolated WebView on the validation UI.
  return <div className="markdown" onClick={(event) => {
    if ((event.target as HTMLElement).closest('a')) event.preventDefault();
  }}><LearningMarkdown>{text}</LearningMarkdown></div>;
}

function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [settings, setSettings] = useState<ProviderSettings>({ base_url: '', model: '' });
  const [apiKey, setApiKey] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [materialId, setMaterialId] = useState<string | null>(null);
  const [materialTitle, setMaterialTitle] = useState('');
  const [materialContent, setMaterialContent] = useState('');
  const [draft, setDraft] = useState('');
  const [activeRequestId, setActiveRequestId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const alive = useRef(true);

  async function refresh() {
    const next = await bridge().core.invoke<Snapshot>('snapshot');
    if (alive.current) setSnapshot(next);
    return next;
  }

  useEffect(() => {
    alive.current = true;
    let unlisten: (() => void) | undefined;
    let disposed = false;
    (async () => {
      try {
        unlisten = await bridge().event.listen<Turn>('native-turn', ({ payload }) => {
          if (disposed) return;
          setSnapshot(current => current && ({
            ...current,
            turns: current.turns.some(turn => turn.id === payload.id)
              ? current.turns.map(turn => turn.id === payload.id ? payload : turn)
              : [...current.turns, payload],
          }));
        });
        if (disposed) { unlisten(); return; }
        const next = await refresh();
        if (!disposed) setSettings(next.settings);
      } catch (cause) {
        if (!disposed) setError(message(cause));
      }
    })();
    return () => { disposed = true; alive.current = false; unlisten?.(); };
  }, []);

  async function saveSettings() {
    setBusy('settings'); setError(''); setNotice('');
    try {
      await bridge().core.invoke<void>('save_settings', { settings });
      await refresh();
      setNotice('模型设置已保存在这台设备。');
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(null); }
  }

  async function saveMaterial() {
    setBusy('material'); setError(''); setNotice('');
    try {
      const saved = await bridge().core.invoke<Material>('save_material', {
        id: materialId, title: materialTitle, content: materialContent,
      });
      await refresh();
      if (!materialId) setSelected(ids => [...ids, saved.id]);
      setMaterialId(null); setMaterialTitle(''); setMaterialContent('');
      setNotice(`资料已保存为第 ${saved.version} 版。后续发送将使用当前版本。`);
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(null); }
  }

  async function send() {
    if (!draft.trim() || activeRequestId || busy || hasUnsavedSettings) return;
    const sentDraft = draft;
    const requestId = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
    setActiveRequestId(requestId); setError(''); setNotice('');
    try {
      const turn = await bridge().core.invoke<Turn>('send_message', {
        requestId, question: sentDraft, materialIds: selected, apiKey,
      });
      await refresh();
      if (turn.status === 'complete') { setDraft(current => current === sentDraft ? '' : current); setNotice('回答已保存。'); }
      else setNotice('本次回答未完成。问题仍留在输入框，可以修改后重新发送。');
    } catch (cause) {
      setError(message(cause));
      try { await refresh(); } catch { /* Keep the actionable send error visible. */ }
    } finally { setActiveRequestId(null); }
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
  return <main className="shell">
    <header className="masthead">
      <span className="eyebrow">NAUTILUS · 独立运行验证版</span>
      <h1>在这台设备上继续学习</h1>
      <p>此版只验证本机独立对话。资料和对话保存在本设备，不读取原有 trial 数据；设备间同步、联网搜索和完整产品流程尚未接入。卸载应用或清除应用数据可能移除这些本机记录。</p>
      {snapshot && <small>设备编号：<code>{snapshot.device_id}</code> · 本机数据版本 {snapshot.schema_version}</small>}
    </header>

    {error && <div className="alert alert--error" role="alert">{error}</div>}
    {notice && <div className="alert" role="status">{notice}</div>}
    {!snapshot ? <p role="status">正在读取本机数据…</p> : <div className="layout">
      <section className="panel settings" aria-labelledby="settings-heading">
        <div className="section-head"><div><span className="eyebrow">01 / 连接</span><h2 id="settings-heading">模型服务</h2></div></div>
        <label>兼容 OpenAI 的 HTTPS 地址（以 /v1 结尾）
          <input type="url" value={settings.base_url} onChange={e => setSettings({ ...settings, base_url: e.target.value })} placeholder="https://example.com/v1" autoComplete="url" />
        </label>
        <label>模型名称
          <input value={settings.model} onChange={e => setSettings({ ...settings, model: e.target.value })} placeholder="填写服务提供的模型名称" />
        </label>
        <button type="button" className="secondary" onClick={() => void saveSettings()} disabled={Boolean(busy) || Boolean(activeRequestId)}>保存模型设置</button>
        <label>API Key（只保留在当前应用内存，重启后需重新输入）
          <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} autoComplete="off" placeholder="本次使用的密钥" />
        </label>
        <p className="hint">{hasUnsavedSettings ? '模型设置已修改，请保存后再发送。' : `发送使用已保存的服务：${snapshot.settings.base_url || '尚未设置'}。`}</p>
        <p className="hint">发送时会把问题、所选资料，以及材料编号和版本一致的连续成功对话发送到此模型服务。修改选用资料或其版本会开始新的上下文范围。</p>
      </section>

      <section className="panel materials" aria-labelledby="materials-heading">
        <div className="section-head"><div><span className="eyebrow">02 / 参考</span><h2 id="materials-heading">本机资料</h2></div><span className="count">已选 {selected.length}</span></div>
        {snapshot.materials.length === 0 && <p className="empty">还没有资料。可先贴入文字保存，也可以不选资料直接提问。</p>}
        <div className="material-list">{snapshot.materials.map(material => <div className="material" key={material.id}>
          <label className="material-choice"><input type="checkbox" checked={selected.includes(material.id)} onChange={e => setSelected(ids => e.target.checked ? [...ids, material.id] : ids.filter(id => id !== material.id))} /><span><strong>{material.title || '未命名资料'}</strong><small>第 {material.version} 版</small></span></label>
          <div className="material-actions"><button type="button" className="text-button" onClick={() => { setMaterialId(material.id); setMaterialTitle(material.title); setMaterialContent(material.content); }}>编辑</button><details><summary>查看内容</summary><pre>{material.content}</pre></details></div>
        </div>)}</div>
        <form onSubmit={e => { e.preventDefault(); void saveMaterial(); }} className="material-form">
          <h3>{materialId ? '编辑资料（保存为新版本）' : '新增文字资料'}</h3>
          <label>标题<input value={materialTitle} onChange={e => setMaterialTitle(e.target.value)} placeholder="例如：课程笔记" /></label>
          <label>内容<textarea value={materialContent} onChange={e => setMaterialContent(e.target.value)} rows={6} placeholder="粘贴需要参考的文字" /></label>
          <div className="actions"><button type="submit" className="secondary" disabled={Boolean(busy) || Boolean(activeRequestId)}>{materialId ? '保存新版本' : '保存并选用'}</button>{materialId && <button type="button" className="text-button" onClick={() => { setMaterialId(null); setMaterialTitle(''); setMaterialContent(''); }}>取消编辑</button>}</div>
        </form>
      </section>

      <section className="panel conversation" aria-labelledby="conversation-heading">
        <div className="section-head"><div><span className="eyebrow">03 / 对话</span><h2 id="conversation-heading">学习对话</h2></div><span className="count">{snapshot.turns.length} 轮</span></div>
        {snapshot.turns.length === 0 && <p className="empty">输入一个问题，开始本机验证对话。</p>}
        <div className="turns" aria-live="polite">{snapshot.turns.map((turn, index) => <article className="turn" key={turn.id}>
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
          <div className="composer-footer"><small>本次选择 {selected.length} 份资料{pendingTurn?.status === 'pending' ? ' · 正在生成' : ''}</small><div className="actions">{activeRequestId && <button type="button" className="secondary" onClick={() => void cancel()} disabled={pendingTurn?.status !== 'pending'}>停止回答</button>}<button type="submit" disabled={!draft.trim() || Boolean(activeRequestId) || Boolean(busy) || hasUnsavedSettings}>发送</button></div></div>
        </form>
      </section>
    </div>}
  </main>;
}

createRoot(document.getElementById('root')!).render(<App />);
