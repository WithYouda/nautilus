import { useEffect, useRef, useState } from 'react';
import { disconnectObsidianConnection, getObsidianConnection, saveObsidianConnection, type ObsidianConnection } from './api';
import { obsidianError } from './ObsidianMaterials';
import './styles/settings.css';

/** Connection settings for one local Obsidian vault. Never nested in the outer settings form. */
export default function ObsidianSettings() {
  const [connection, setConnection] = useState<ObsidianConnection | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [rootPath, setRootPath] = useState('');
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { void load(); }, []);
  async function load() {
    setBusy(true); setError('');
    try {
      const data = await getObsidianConnection();
      if (!alive.current) return;
      setConnection(data.connection); setRootPath(data.connection?.root_path ?? ''); setLoaded(true);
    } catch (reason) {
      if (alive.current) setError(obsidianError(reason, '无法读取 Obsidian 连接设置。'));
    } finally { if (alive.current) setBusy(false); }
  }
  async function connect() {
    setBusy(true); setError(''); setNotice('');
    try {
      const data = await saveObsidianConnection(rootPath.trim(), connection?.revision ?? null);
      if (!alive.current) return;
      setConnection(data.connection); setRootPath(data.connection.root_path); setEditing(false);
      setNotice(`已连接 Vault「${data.connection.vault_name}」。`);
    } catch (reason) {
      if (alive.current) setError(obsidianError(reason, '连接失败，请检查路径后重试。'));
    } finally { if (alive.current) setBusy(false); }
  }
  async function disconnect() {
    if (!connection) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const data = await disconnectObsidianConnection(connection.revision);
      if (!alive.current) return;
      setConnection(data.connection);
      setNotice('已断开连接：不会再有新的 Vault 读取；已保存的快照仍然保留。');
    } catch (reason) {
      if (alive.current) setError(obsidianError(reason, '断开失败，请重新读取设置后重试。'));
    } finally { if (alive.current) setBusy(false); }
  }
  const canConnect = Boolean(rootPath.trim()) && !busy;
  return <section className="obsidian-settings" aria-label="本地 Obsidian Vault">
    <h3>知识库：本地 Obsidian Vault</h3>
    <p>只读连接运行 Nautilus 后端的主机上的一个本地 Vault。路径由你填写，不会自动搜索磁盘；不需要 Obsidian 插件或 API Key。连接和检索只在本地进行：Nautilus 只读取 .md 笔记，不会自动上传整个 Vault，也不会创建、修改或删除 Vault 里的文件。只有你明确“保存快照并选用”的笔记才会成为当前对话的教学模型输入；使用远端 Provider 时，这部分正文会发送到相应服务。联网搜索或工具外发仍按既有的逐次授权处理。</p>
    {!loaded && !error && <p role="status">正在读取连接设置…</p>}
    {loaded && !connection && <>
      <label className="field"><span>Vault 路径（后端主机上的绝对路径）</span>
        <input value={rootPath} disabled={busy} placeholder="/home/用户名/我的Vault" onChange={event => setRootPath(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); if (canConnect) void connect(); } }} />
      </label>
      <button type="button" className="button button--quiet" disabled={!canConnect} onClick={() => void connect()}>{busy ? '连接中…' : '连接本地 Vault'}</button>
    </>}
    {connection && <>
      <p>当前 Vault：<strong>{connection.vault_name}</strong>（{connection.root_path}）· 配置修订 {connection.revision} · 状态{connection.enabled ? '已连接' : '已断开'}</p>
      <div className="obsidian-settings-actions">
        {connection.enabled
          ? <button type="button" className="button button--quiet" disabled={busy} onClick={() => void disconnect()}>断开连接</button>
          : <button type="button" className="button button--quiet" disabled={busy} onClick={() => void connect()}>{busy ? '连接中…' : '重新连接'}</button>}
        <button type="button" className="button button--quiet" disabled={busy} onClick={() => { setEditing(value => !value); setRootPath(connection.root_path); setError(''); }}>{editing ? '取消更改路径' : '更改 Vault 路径'}</button>
      </div>
      {editing && <div className="obsidian-settings-path">
        <label className="field"><span>Vault 路径（后端主机上的绝对路径）</span>
          <input value={rootPath} disabled={busy} onChange={event => setRootPath(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); if (canConnect) void connect(); } }} />
        </label>
        <button type="button" className="button button--dark" disabled={!canConnect} onClick={() => void connect()}>{busy ? '保存中…' : '保存新路径'}</button>
        <small className="form-hint">换成另一个根目录会建立新的连接；已保存的快照仍属于原连接，不会自动改绑。</small>
      </div>}
      <small className="form-hint">断开只停止新的读取并保留已保存的快照。清除 Nautilus 保存的资料不会删除 Obsidian 原文或其云端备份。</small>
    </>}
    {notice && <p role="status">{notice}</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </section>;
}
