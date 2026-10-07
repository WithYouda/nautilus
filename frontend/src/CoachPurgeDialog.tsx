import { useEffect, useRef, useState } from 'react';
import { Trash2 } from 'lucide-react';
import DialogPortal from './DialogPortal';
import { type AiConversation, type PurgeReport } from './api';
import { coachKey, getCoachConversationPurge, purgeCoachConversation } from './coach-conversation-api';

export default function CoachPurgeDialog({ conversation, onClose, onCleared }: { conversation: AiConversation; onClose: () => void; onCleared: () => void }) {
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof getCoachConversationPurge>> | null>(null), [report, setReport] = useState<PurgeReport | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const alive = useRef(true), key = useRef(coachKey()), cleared = useRef(false), dialog = useRef<HTMLElement>(null);
  function clearMemory() { if (!cleared.current) { cleared.current = true; onCleared(); } }
  async function load() {
    setError('');
    try { const value = await getCoachConversationPurge(conversation.id); if (!alive.current) return; setPreview(value); setReport(value.purge_report); if (value.purge_report.status !== 'not_requested') clearMemory(); }
    catch (reason) { if (alive.current) setError(reason instanceof Error ? reason.message : '无法核对清除范围。'); }
  }
  useEffect(() => { alive.current = true; void load(); dialog.current?.querySelector<HTMLButtonElement>('button')?.focus(); return () => { alive.current = false; }; }, [conversation.id]);
  async function confirm() {
    if (!preview || busy) return;
    setBusy(true); setError('');
    try { const result = await purgeCoachConversation(conversation.id, key.current); if (!alive.current) return; clearMemory(); setReport(result.purge_report); }
    catch (reason) { if (!alive.current) return; setError(reason instanceof Error ? reason.message : '清除结果尚未确认，可核对进度后重试。'); try { const result = await getCoachConversationPurge(conversation.id); if (alive.current) { setReport(result.purge_report); if (result.purge_report.status !== 'not_requested') clearMemory(); } } catch { /* Keep the explicit error and retry entry. */ } }
    finally { if (alive.current) setBusy(false); }
  }
  return <DialogPortal><div className="dialog-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <section ref={dialog} className="confirm-dialog ai-conversation-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="coach-purge-title" onKeyDown={event => { if (event.key === 'Escape' && !busy) onClose(); if (event.key === 'Tab') { const buttons = [...(dialog.current?.querySelectorAll<HTMLButtonElement>('button:not([disabled])') ?? [])]; if (event.shiftKey && document.activeElement === buttons[0]) { event.preventDefault(); buttons.at(-1)?.focus(); } else if (!event.shiftKey && document.activeElement === buttons.at(-1)) { event.preventDefault(); buttons[0]?.focus(); } } }}>
      <div className="confirm-icon"><Trash2 size={20} /></div><h2 id="coach-purge-title">清除“{conversation.title}”的内容？</h2>
      {preview ? <div className="coach-purge-impact">涉及 {preview.impact.conversations} 个教练对话、{preview.impact.messages} 条消息及 {preview.impact.runs} 次回答。正文、思考、标题及相关备份副本将被清除，无法恢复。学习任务、完成记录和证据保留。</div> : !error && <p role="status">正在核对清除范围…</p>}
      {report?.status === 'complete' && <p role="status">教练内容已清除。</p>}
      {(report?.status === 'partial' || report?.status === 'pending') && <p role="status">当前对话内容已停止显示，部分副本尚未清除完成。请重试清除。</p>}
      {report?.files.some(file => file.status === 'failed') && <details><summary>未完成的清除</summary><ul>{report.files.filter(file => file.status === 'failed').map(file => <li key={file.name}>{file.name}：{file.reason ?? '待重试'}</li>)}</ul></details>}
      {error && <p className="form-error" role="alert">{error}<button className="text-button" type="button" disabled={busy} onClick={() => void load()}>核对清除范围与进度</button></p>}
      <div className="confirm-actions"><button className="button button--quiet" type="button" disabled={busy} onClick={onClose}>{report?.status === 'not_requested' || !report ? '取消' : '关闭'}</button>{report?.status !== 'complete' && <button className="button button--danger" type="button" disabled={busy || !preview} onClick={() => void confirm()}>{busy ? '清除中…' : report?.status === 'partial' || report?.status === 'pending' ? '重试清除' : '确认清除内容'}</button>}</div>
    </section></div></DialogPortal>;
}
