import { useCallback, useEffect, useRef, useState } from 'react';
import { getLearningPurgeReport, type PurgeReport } from './api';

export default function PurgeStatus({ kind, objectId, onRetry, busy = false, refreshKey }: {
  kind: 'verification' | 'completion' | 'artifact' | 'practice';
  objectId: string;
  onRetry: () => Promise<void>;
  busy?: boolean;
  refreshKey?: string | number;
}) {
  const [report, setReport] = useState<PurgeReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState('');
  const request = useRef(0);
  const active = useRef(false);
  const identity = useRef(`${kind}:${objectId}`);
  identity.current = `${kind}:${objectId}`;
  const read = useCallback(async () => {
    const target = `${kind}:${objectId}`;
    if (!active.current || identity.current !== target) return;
    const current = ++request.current;
    setLoading(true); setError('');
    try {
      const value = await getLearningPurgeReport(kind, objectId);
      if (active.current && request.current === current && identity.current === target) setReport(value);
    } catch (reason) {
      if (active.current && request.current === current && identity.current === target) { setReport(null); setError(reason instanceof Error ? reason.message : '清除结果暂时无法读取'); }
    } finally {
      if (active.current && request.current === current && identity.current === target) setLoading(false);
    }
  }, [kind, objectId]);
  useEffect(() => {
    active.current = true;
    setReport(null);
    void read();
    return () => { active.current = false; request.current++; };
  }, [read, refreshKey]);
  async function retry() {
    if (retrying || busy) return;
    const target = `${kind}:${objectId}`;
    setRetrying(true); setError('');
    try { await onRetry(); }
    catch (reason) { if (active.current && identity.current === target) setError(reason instanceof Error ? reason.message : '重试清除失败'); }
    finally { if (active.current && identity.current === target) { await read(); setRetrying(false); } }
  }
  return <div className="verification-panel" aria-label="副本清除结果">
    <strong>副本清除结果</strong>
    {loading && <p role="status">正在读取清除结果…</p>}
    {error && <p role="alert">{error}</p>}
    {report && <>
      <p>{report.status === 'complete' ? 'Nautilus 管理的副本已处理完成。' : report.status === 'pending' ? '清除尚未确认完成，可能仍在处理或已经中断；可刷新结果或重试。' : report.status === 'partial' ? 'Nautilus 管理的副本仅部分清除，请查看失败项并重试。' : '在线内容已清除，受管理副本尚未完整清除。'}</p>
      {report.updated_at && <p className="form-hint">最近更新：{new Date(report.updated_at).toLocaleString()}</p>}
      {report.files.length > 0 && <ul>{report.files.map((file, index) => <li key={`${file.name}:${index}`}>{file.name}：{file.status === 'cleared' ? '已清除' : '失败'}{file.reason ? ` · ${file.reason}` : ''}</li>)}</ul>}
      {report.external_limits.length > 0 && <><p>以下外部副本无法由 Nautilus 核实清除：</p><ul>{report.external_limits.map((limit, index) => <li key={index}>{limit}</li>)}</ul></>}
      {report.status !== 'complete' && <button className="button button--quiet" type="button" disabled={busy || retrying || loading} onClick={() => void retry()}>{retrying ? '正在重试…' : '重试清除剩余副本'}</button>}
    </>}
    <button className="button button--quiet" type="button" disabled={busy || retrying || loading} onClick={() => void read()}>刷新清除结果</button>
  </div>;
}
