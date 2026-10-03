import { useEffect, useRef, useState } from 'react';
import { getObsidianConnection, type KnowledgeBaseSelection, type ObsidianConnection } from './api';
import { obsidianError } from './ObsidianMaterials';

/** Reading configuration does not search the Vault; the saved choice authorizes this conversation's tools. */
export default function ObsidianKnowledgeChoice({ value, disabled, onChange }: {
  value?: KnowledgeBaseSelection; disabled?: boolean;
  onChange: (value?: KnowledgeBaseSelection) => void;
}) {
  const [connection, setConnection] = useState<ObsidianConnection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const request = useRef(0);
  async function load() {
    const current = ++request.current;
    setLoading(true); setError('');
    try {
      const data = await getObsidianConnection();
      if (request.current === current) setConnection(data.connection);
    } catch (reason) {
      if (request.current === current) setError(obsidianError(reason, '无法读取知识库连接，请重试。'));
    } finally { if (request.current === current) setLoading(false); }
  }
  useEffect(() => { void load(); return () => { request.current++; }; }, []);
  const matches = Boolean(connection?.enabled && value?.connection_id === connection.connection_id && value.connection_revision === connection.revision);
  const selection = connection?.enabled ? { kind: 'obsidian_local' as const, connection_id: connection.connection_id, connection_revision: connection.revision } : undefined;
  return <section className="task-material-knowledge" aria-label="本对话知识库">
    <label><input type="checkbox" checked={Boolean(value)} disabled={disabled || loading || (!value && !selection)} onChange={event => onChange(event.target.checked ? selection : undefined)} />本对话使用 Obsidian 知识库{connection ? `（${connection.vault_name}）` : ''}</label>
    <p className="form-hint">选中后，AI 可在回复时检索这个 Vault 的相关笔记并保存本次使用的证据快照；使用远端 Provider 时，检索到的片段会发送给它。不会自动把笔记存入资料库，也不会修改 Obsidian 原文。</p>
    {loading && <p role="status">正在读取知识库连接…</p>}
    {!loading && !error && !connection && <p>请先在“设置 → 知识库”连接本地 Vault。</p>}
    {!loading && value && !matches && <p role="alert">原来选择的知识库连接已断开或更改；当前选择仍保留，请重新读取连接并明确选择后再发送。</p>}
    {!loading && !value && connection && !connection.enabled && <p>知识库连接已断开，请在设置中重新连接。</p>}
    {!loading && value && !matches && selection && <button type="button" className="text-button" disabled={disabled} onClick={() => onChange(selection)}>改用当前连接：{connection!.vault_name}</button>}
    <button type="button" className="text-button" disabled={loading} onClick={() => void load()}>重新读取知识库连接</button>
    {error && <p role="alert">{error}</p>}
  </section>;
}
