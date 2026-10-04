import { useEffect, useRef, useState } from 'react';
import { getGraphPurgeReport, purgeGraphContent, type PurgeReport } from './api';
import { AttachmentDialog } from './AttachmentReview';
import { graphError, requestKey } from './OutcomeGraphForms';

export default function OutcomeGraphPurge({ kind, id, revision, purged, onPurged, onDialogChange }: {
  kind: 'relation' | 'run'; id: string; revision: number; purged: boolean;
  onPurged: () => Promise<void>; onDialogChange?: (open: boolean) => void;
}) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [report, setReport] = useState<PurgeReport | null>(null);
  const attempt = useRef<{ key: string; revision: number } | null>(null);
  useEffect(() => {
    let active = true; setReport(null); setError(''); attempt.current = null;
    if (purged) getGraphPurgeReport(kind, id).then(value => { if (active) setReport(value); }).catch(reason => { if (active) setError(graphError(reason)); });
    return () => { active = false; };
  }, [id, kind, purged]);
  function dialog(value: boolean) { setOpen(value); onDialogChange?.(value); }
  async function read() {
    setBusy(true); setError('');
    try { setReport(await getGraphPurgeReport(kind, id)); } catch (reason) { setError(graphError(reason)); } finally { setBusy(false); }
  }
  async function clear() {
    if (busy) return;
    if (!attempt.current) attempt.current = { key: requestKey(), revision };
    setBusy(true); setError('');
    try { const result = await purgeGraphContent(kind, id, attempt.current.revision, attempt.current.key); setReport(result.purge_report); await onPurged(); dialog(false); }
    catch (reason) { setError(graphError(reason)); } finally { setBusy(false); }
  }
  const title = kind === 'relation' ? '清除这项关系说明？' : '清除这次分析内容？';
  return <>
    {!purged && <button className="text-button" type="button" disabled={busy} onClick={() => dialog(true)}>{kind === 'relation' ? '彻底清除关系说明' : '清除这次分析内容'}</button>}
    {purged && <div aria-label="内容清除结果"><p role="status">{!report ? '正在读取清除结果…' : report.status === 'complete' ? '内容及受管理副本已清除。' : '部分内容未能清除，请重试。'}</p>
      {report && report.status !== 'complete' && <button className="text-button" type="button" disabled={busy} onClick={() => void clear()}>重试清除</button>}
      <button className="text-button" type="button" disabled={busy} onClick={() => void read()}>刷新清除结果</button>
      {report && report.status !== 'complete' && <details><summary>清除详情</summary>{report.files.filter(file => file.status === 'failed').map((file, index) => <p key={index}>{file.name}{file.reason ? ` · ${file.reason}` : ''}</p>)}</details>}
    </div>}
    {error && !open && <p role="alert">{error}</p>}
    {open && <AttachmentDialog title={title} className="outcome-graph__dialog" closeLabel="取消清除内容" onClose={() => { if (!busy) dialog(false); }}><div className="outcome-graph__dialog-body">
      <p>{kind === 'relation' ? '永久清除这项关系的情境、说明与来源，并从图中移除这项关系。成果和原始依据仍保留。无法撤销。' : '永久清除这次分析的输入、建议及关联说明。已经采用的关联仍保留，成果和原始依据不变。无法撤销。'}</p>
      {error && <p role="alert">{error}</p>}<div className="outcome-graph__actions"><button className="button button--quiet" type="button" disabled={busy} onClick={() => dialog(false)}>取消</button><button className="button button--danger" type="button" disabled={busy} onClick={() => void clear()}>{busy ? '正在清除…' : '确认清除'}</button></div>
    </div></AttachmentDialog>}
  </>;
}
