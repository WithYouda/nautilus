import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { ApiError, cancelMaterialOcr, confirmMaterialOcr, getMaterialOcr, materialPreviewUrl, startMaterialOcr, type AttachmentPage, type MaterialKind, type MaterialOcrJob, type MaterialVersion } from './api';
import DialogPortal from './DialogPortal';
import ImageModelSettings from './ImageModelSettings';
import { attachmentChanged, attachmentError, attachmentName } from './AttachmentSupport';
import './styles/composer-attachments.css';

export function AttachmentDialog({ title, onClose, children, className = '', closeLabel = '关闭附件预览', suspended = false }: { title: string; onClose: () => void; children: ReactNode; className?: string; closeLabel?: string; suspended?: boolean }) {
  const dialog = useRef<HTMLElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const closeRef = useRef(onClose); closeRef.current = onClose;
  const heading = useId();
  useEffect(() => {
    if (suspended) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    close.current?.focus();
    const handle = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeRef.current(); }
      if (event.key !== 'Tab' || !dialog.current) return;
      const controls = [...dialog.current.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], summary')].filter(item => item.getClientRects().length > 0);
      const first = controls[0], last = controls[controls.length - 1];
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', handle, true);
    return () => { document.removeEventListener('keydown', handle, true); if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  }, [suspended]);
  return <DialogPortal><div className="dialog-backdrop attachment-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className={`attachment-dialog ${className}`} ref={dialog} role="dialog" aria-modal="true" aria-labelledby={heading} aria-hidden={suspended || undefined}>
      <header><h2 id={heading}>{title}</h2><button ref={close} type="button" className="icon-button" aria-label={closeLabel} onClick={onClose}>×</button></header>{children}
    </section>
  </div></DialogPortal>;
}

function OriginalPage({ kind, id, version, number }: { kind: MaterialKind; id: string; version: MaterialVersion; number: number }) {
  const [failed, setFailed] = useState(false);
  const url = materialPreviewUrl(kind, id, version.id, number);
  useEffect(() => setFailed(false), [url]);
  return <div className="attachment-original-page"><h3>保存的原件 · 第 {number} 页</h3>{failed ? <p role="alert">这一页预览无法读取，请重试或下载保存的原件。</p> : <img src={url} alt={`${version.original?.filename ?? version.title} 原件第 ${number} 页`} onError={() => setFailed(true)} />}
    {failed && <button type="button" className="text-button" onClick={() => setFailed(false)}>重试预览</button>}</div>;
}

export function AttachmentPreview({ kind, id, version, pageNumbers, onClose, children }: { kind: MaterialKind; id: string; version: MaterialVersion; pageNumbers?: number[]; onClose: () => void; children?: ReactNode }) {
  const [pageIndex, setPageIndex] = useState(1);
  const numbers = pageNumbers?.length ? pageNumbers : Array.from({ length: version.attachment?.page_count ?? 1 }, (_, index) => index + 1);
  const page = numbers[pageIndex - 1];
  const count = numbers.length;
  const paged = version.attachment && ['image', 'pdf'].includes(version.attachment.kind);
  return <AttachmentDialog title={`附件详情 · ${attachmentName(version)}`} onClose={onClose}>
    {version.attachment?.origin === 'ocr' && <p>这是已核对的 OCR 文字派生版本。下方文字是该版本保存的内容，不代表原件内容已核实。</p>}
    {paged && count > 1 && <PageNavigation page={pageIndex} count={count} setPage={setPageIndex} />}
    <div className="attachment-review-columns">{paged && <OriginalPage kind={kind} id={id} version={version} number={page} />}
      {version.content !== null && version.attachment?.mode !== 'image' && <div><h3>{version.attachment?.origin === 'ocr' ? '已核对的 OCR 文字' : '读取的文字'}</h3><pre>{version.attachment?.pages.find(item => item.number === page)?.text ?? version.content}</pre></div>}</div>
    {children && <div className="attachment-detail-actions">{children}</div>}
    {version.original && <a href={`/api/materials/${kind}/${encodeURIComponent(id)}/versions/${encodeURIComponent(version.id)}/original`} download={version.original.filename}>下载原件：{version.original.filename}</a>}
  </AttachmentDialog>;
}
function PageNavigation({ page, count, setPage }: { page: number; count: number; setPage: (number: number) => void }) {
  return <div className="attachment-page-navigation"><button type="button" className="button button--quiet" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button><span>第 {page} / {count} 页</span><button type="button" className="button button--quiet" disabled={page >= count} onClick={() => setPage(page + 1)}>下一页</button></div>;
}
function provenanceJob(version: MaterialVersion): string | null {
  try { const source = version.provenance ?? JSON.parse(version.provenance_json ?? '{}'); return typeof source.ocr_job_id === 'string' ? source.ocr_job_id : null; }
  catch { return null; }
}
export function AttachmentOcrReview({ kind, id, version, onClose, onConfirmed }: { kind: MaterialKind; id: string; version: MaterialVersion; onClose: () => void; onConfirmed: (version: MaterialVersion) => Promise<boolean> }) {
  const [job, setJob] = useState<MaterialOcrJob | null>(null);
  const [pages, setPages] = useState<AttachmentPage[]>(version.attachment?.origin === 'ocr' ? version.attachment.pages : []);
  const [page, setPage] = useState(1);
  const [reviewed, setReviewed] = useState<number[]>([]);
  const [incomplete, setIncomplete] = useState(false);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const alive = useRef(true);
  const jobRef = useRef(job); jobRef.current = job;
  const readonly = version.inherited && !version.library;
  const derived = version.attachment?.origin === 'ocr';
  function failure(reason: unknown) {
    if (!alive.current) return;
    if (reason instanceof ApiError && reason.status === 404) { setUnavailable(true); setPages([]); setJob(null); setReviewed([]); setNotice(''); }
    else setError(attachmentError(reason));
  }
  function accept(value: MaterialOcrJob | null, initial = false) {
    if (!alive.current) return;
    const savedJob = initial && version.attachment?.origin === 'ocr' ? provenanceJob(version) : null;
    if (savedJob && value) {
      setJob({ ...value, id: savedJob, status: 'confirmed', pages: version.attachment!.pages, result_version_id: version.id });
      setPages(version.attachment!.pages); return;
    }
    setJob(value); if (value) setPages(value.pages);
  }
  useEffect(() => {
    alive.current = true;
    if (readonly) { setLoading(false); return () => { alive.current = false; }; }
    void getMaterialOcr(kind, id, version.id).then(result => accept(result.job, true)).catch(reason => { failure(reason); }).finally(() => { if (alive.current) setLoading(false); });
    return () => { alive.current = false; };
  }, [kind, id, version.id]);
  useEffect(() => {
    if (job?.status !== 'running') return;
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try { const result = await getMaterialOcr(kind, id, version.id, jobRef.current?.id); if (active && alive.current) { accept(result.job); setError(''); } }
      catch (reason) { if (active) failure(reason); }
      if (active && alive.current && jobRef.current?.status === 'running') timer = window.setTimeout(() => void poll(), 1500);
    };
    timer = window.setTimeout(() => void poll(), 1500);
    return () => { active = false; window.clearTimeout(timer); };
  }, [kind, id, version.id, job?.status]);
  async function start() {
    setBusy(true); setError(''); setNotice('');
    try { const value = await startMaterialOcr(kind, id, version.id); accept(value.job); if (alive.current) { setReviewed([]); setIncomplete(false); } }
    catch (reason) { if (alive.current) { failure(reason); setSettings(true); } }
    finally { if (alive.current) setBusy(false); }
  }
  async function cancel() {
    if (!job) return;
    setBusy(true); setError('');
    try { accept((await cancelMaterialOcr(kind, id, version.id, job.id)).job); }
    catch (reason) { failure(reason); }
    finally { if (alive.current) setBusy(false); }
  }
  async function confirm() {
    if (!job) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const saved = await confirmMaterialOcr(kind, id, version.id, job.id, pages.map(item => ({ number: item.number, text: item.text })), incomplete);
      attachmentChanged(kind, id);
      if (!alive.current) return;
      const applied = await onConfirmed(saved);
      if (alive.current) { setPages(saved.attachment?.pages ?? pages); setNotice(applied ? '已保存核对后的文字，并加入本次附件。' : '核对文字已保存，尚未加入本次附件。请关闭后重试添加。'); setJob(previous => previous ? { ...previous, status: 'confirmed', result_version_id: saved.id } : null); }
    } catch (reason) { failure(reason); }
    finally { if (alive.current) setBusy(false); }
  }
  const current = pages.find(item => item.number === page);
  const canReview = job && ['review', 'failed', 'confirmed'].includes(job.status);
  const hasEmpty = pages.some(item => !item.text.trim());
  const allReviewed = pages.length > 0 && pages.every(item => reviewed.includes(item.number));
  if (unavailable) return <AttachmentDialog title="附件已不可用" onClose={onClose}><p role="alert">资料或原件已不可用，已停止读取并移除识别草稿。请关闭后重新读取当前资料列表。</p></AttachmentDialog>;
  return <AttachmentDialog title={`${derived ? '修改核对文字' : '识别与核对文字'} · ${version.title ?? '附件'}`} onClose={onClose}>
    <p>优先用当前支持图片的对话模型直接看图。OCR 是你主动选择的文字识别；草稿不会进入参考，核对确认后才保存文字版本。</p>
    {readonly ? <p>这份继承资料为只读。可在原对话或可编辑的资料库资料中进行识别与核对。</p> : <>
      {derived && <p>这里修改这份保存版本的核对文字。若要重新识别，请在“资料”的版本历史中打开原件版本，使用“识别与核对文字”。</p>}
      <div className="attachment-review-actions">{!derived && <button type="button" className="button button--quiet" disabled={loading || busy || job?.status === 'running'} onClick={() => void start()}>{job ? '重新识别' : '开始识别文字'}</button>}
        <button type="button" className="text-button" onClick={() => setSettings(value => !value)} aria-expanded={settings}>图片与 OCR 模型设置</button>
        {job?.status === 'running' && <button type="button" className="button button--quiet" disabled={busy} onClick={() => void cancel()}>取消识别</button>}</div>
      {settings && <ImageModelSettings />}
      {loading && <p role="status">正在读取识别状态…</p>}
      {job?.status === 'running' && <p role="status">正在识别…已取得文字仍是未核对草稿。</p>}
      {job?.status === 'canceled' && <p role="status">已取消识别，原件保留，可重新开始。</p>}
      {job?.error_code && <p role="alert">{attachmentError(new Error(job.error_code))}</p>}
      <PageNavigation page={page} count={version.attachment?.page_count ?? 1} setPage={setPage} />
      <div className="attachment-review-columns"><OriginalPage kind={kind} id={id} version={version} number={page} />
        <div className="attachment-page-text"><h3>{version.attachment?.origin === 'ocr' && job?.status === 'confirmed' ? '已核对文字（修改后保存新版本）' : '识别草稿 · 确认前不会参考'}</h3>
          {current?.status === 'failed' && (current.reviewed && job?.status === 'confirmed' ? <p>该页曾识别失败，文字已由你补充并核对。</p> : <p role="alert">这一页识别失败，请对照原件补充文字。</p>)}
          {current?.status === 'empty' && <p>这一页未识别出文字，请核对原件。</p>}
          <label>第 {page} 页文字<textarea value={current?.text ?? ''} disabled={!canReview || busy} onChange={event => { const text = event.target.value; setPages(previous => previous.map(item => item.number === page ? { ...item, text, reviewed: false } : item)); setReviewed(previous => previous.filter(number => number !== page)); setNotice(''); }} /></label>
          {canReview && <label className="attachment-review-check"><input type="checkbox" checked={reviewed.includes(page)} disabled={busy} onChange={event => setReviewed(previous => event.target.checked ? [...new Set([...previous, page])] : previous.filter(number => number !== page))} />我已对照原件核对第 {page} 页</label>}
        </div></div>
      {canReview && <><p>已核对 {reviewed.length}/{pages.length} 页。识别文字不等于理解图表，也不代表内容已核实。</p>
        {hasEmpty && <label className="attachment-review-check"><input type="checkbox" checked={incomplete} disabled={busy} onChange={event => setIncomplete(event.target.checked)} />仍有空白页；我确认保存的文字不完整，仅参考已核对的非空文字。</label>}
        <button type="button" className="button button--accent" disabled={busy || !allReviewed || !pages.some(item => item.text.trim()) || hasEmpty && !incomplete} onClick={() => void confirm()}>确认文字并参考</button></>}
    </>}
    {error && <p className="form-error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
  </AttachmentDialog>;
}
