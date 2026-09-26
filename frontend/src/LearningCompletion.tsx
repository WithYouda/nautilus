import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react';
import { createLearningCompletion, getLearningCompletion, purgeLearningCompletion, respondToCompletionReview, reviewLearningCompletion, type CompletionKind, type LearningCompletion as Completion } from './api';

const kindLabel: Record<CompletionKind, string> = {
  unverified: '未经过验证',
  external_material: '用户报告非 AI 验证 · 已附材料 · 平台未核验',
  external_report: '用户报告外部验证 · 未附材料 · 平台未核验',
};
const findingLabel = { issue: '有依据的问题', question: '疑点', insufficient: '资料不足', no_issue: '暂未发现问题' };
const newKey = () => globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;

export default function LearningCompletion({ delegationId, allowCreate = true, onCompleted, onPurged }: {
  delegationId: string; allowCreate?: boolean; onCompleted?: () => void; onPurged?: () => void;
}) {
  const [completion, setCompletion] = useState<Completion | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [error, setError] = useState('');
  const [kind, setKind] = useState<CompletionKind>('unverified');
  const [note, setNote] = useState('');
  const [method, setMethod] = useState('');
  const [result, setResult] = useState('');
  const [materialKind, setMaterialKind] = useState<'work' | 'result'>('result');
  const [materialLabel, setMaterialLabel] = useState('');
  const [materialText, setMaterialText] = useState('');
  const [includeWork, setIncludeWork] = useState(false);
  const [responses, setResponses] = useState<Record<string, string>>({});
  const generation = useRef(0);
  const saveKey = useRef(newKey());
  useEffect(() => {
    const current = ++generation.current;
    setLoading(true); setLoadFailed(false); setCompletion(null); setError(''); setBusy(false); setReviewing(false); setResponses({});
    setKind('unverified'); setNote(''); setMethod(''); setResult(''); setMaterialKind('result'); setMaterialLabel(''); setMaterialText(''); setIncludeWork(false);
    saveKey.current = newKey();
    getLearningCompletion(delegationId).then(value => { if (generation.current === current) setCompletion(value); })
      .catch(reason => { if (generation.current === current) { setLoadFailed(true); setError(reason instanceof Error ? reason.message : '完成记录暂时无法读取'); } })
      .finally(() => { if (generation.current === current) setLoading(false); });
    return () => { generation.current++; };
  }, [delegationId]);

  async function readTextFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!/\.(txt|md|json|py|js|ts)$/i.test(file.name)) { setError('请选择 txt、md、json、py、js 或 ts 文本文件。'); return; }
    if (file.size > 100_000) { setError('文件过大，请摘取相关文字，最多 30000 字。'); return; }
    const current = generation.current;
    try {
      const text = await file.text();
      if (generation.current !== current) return;
      if (text.length > 30_000) { setError('文字超过 30000 字，请摘取相关内容。'); return; }
      setMaterialLabel(file.name.slice(0, 200)); setMaterialText(text); setError('');
    } catch { if (generation.current === current) setError('文件无法读取，请粘贴文字。'); }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const hasMaterial = kind === 'external_material' || (kind === 'unverified' && includeWork);
    if (kind !== 'unverified' && (!method.trim() || !result.trim())) { setError('请填写原验证方式和用户报告的结果。'); return; }
    if (hasMaterial && (!materialLabel.trim() || !materialText.trim())) { setError('请填写材料名称和文字内容。'); return; }
    const current = generation.current;
    setBusy(true); setError('');
    try {
      const saved = await createLearningCompletion(delegationId, {
        request_key: saveKey.current, verification_kind: kind, note: note.trim(),
        report: kind === 'unverified' ? null : { method: method.trim(), result: result.trim() },
        material: hasMaterial ? { kind: kind === 'unverified' ? 'work' : materialKind, label: materialLabel.trim(), text: materialText.trim() } : null,
      });
      if (generation.current !== current) return;
      setCompletion(saved); onCompleted?.();
    } catch (reason) { if (generation.current === current) setError(reason instanceof Error ? reason.message : '完成记录未保存，请重试。'); }
    finally { if (generation.current === current) setBusy(false); }
  }

  async function review() {
    if (!completion || busy || completion.purged_at || !completion.content?.material) return;
    const current = generation.current;
    setBusy(true); setReviewing(true); setError('');
    try { const saved = await reviewLearningCompletion(completion.id, newKey()); if (generation.current === current) setCompletion(saved); }
    catch (reason) { if (generation.current === current) setError(reason instanceof Error ? reason.message : 'AI 审查未完成，可重新发起。'); }
    finally { if (generation.current === current) { setBusy(false); setReviewing(false); } }
  }

  async function refresh() {
    const current = generation.current;
    setBusy(true); setError('');
    try { const value = await getLearningCompletion(delegationId); if (generation.current === current) { setCompletion(value); setLoadFailed(false); } }
    catch (reason) { if (generation.current === current) { setLoadFailed(true); setError(reason instanceof Error ? reason.message : '完成记录暂时无法刷新'); } }
    finally { if (generation.current === current) setBusy(false); }
  }

  async function respond(reviewId: string) {
    if (!completion || busy || !responses[reviewId]?.trim()) return;
    const current = generation.current;
    setBusy(true); setError('');
    try { const saved = await respondToCompletionReview(completion.id, reviewId, responses[reviewId].trim()); if (generation.current === current) { setCompletion(saved); setResponses(previous => ({ ...previous, [reviewId]: '' })); } }
    catch (reason) { if (generation.current === current) setError(reason instanceof Error ? reason.message : '回应未保存，请重试。'); }
    finally { if (generation.current === current) setBusy(false); }
  }

  async function purge() {
    if (!completion || busy || completion.purged_at || !window.confirm('删除这条完成记录的说明、材料、约定与审查内容？完成事实和验证来源类别仍会保留。')) return;
    const current = generation.current;
    setBusy(true); setError('');
    try { const saved = await purgeLearningCompletion(completion.id); if (generation.current === current) { setCompletion(saved); setResponses({}); onPurged?.(); } }
    catch (reason) { if (generation.current === current) setError(reason instanceof Error ? reason.message : '内容删除失败，请重试。'); }
    finally { if (generation.current === current) setBusy(false); }
  }

  if (!loading && !loadFailed && !completion && !allowCreate) return null;
  return <section className="verification-panel" aria-label="本次执行完成记录">
    <h3>本次执行完成</h3>
    {loading && <p role="status">正在读取完成记录…</p>}
    {error && <p role="alert">{error}</p>}
    {loadFailed && <button className="button button--quiet" type="button" disabled={busy} onClick={() => void refresh()}>重新读取完成记录</button>}
    {!loading && completion && <>
      <p><strong>已记录完成</strong> · {completion.purged_at && completion.verification_kind === 'external_material' ? '用户报告非 AI 验证 · 曾附材料，内容已删除 · 平台未核验' : kindLabel[completion.verification_kind]} · {new Date(completion.created_at).toLocaleString()}</p>
      {completion.purged_at || !completion.content ? <p>内容已删除。完成事实及验证来源类别仍保留。</p> : <>
        {completion.content.note && <p>说明：{completion.content.note}</p>}
        {completion.content.report && <p>用户报告的原验证：{completion.content.report.method} · 结果：{completion.content.report.result}。平台未核验此结果。</p>}
        {completion.content.material && <details><summary>查看{completion.content.material.kind === 'work' ? '原始作答或作品' : '验证结果材料'}：{completion.content.material.label}</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{completion.content.material.text}</pre></details>}
        {completion.contract && <details><summary>记录时的任务约定 v{completion.contract.version}</summary><p>停止条件：{completion.contract.stop_conditions}</p><p>边界：{completion.contract.boundaries}</p></details>}
        {completion.content.material && <button className="button button--quiet" type="button" disabled={busy} onClick={() => void review()}>{reviewing ? '正在审查…' : '请 AI 审查这份材料（可选）'}</button>}
        {reviewing && <p role="status">正在审查材料，完成记录已保存。</p>}
        {!!completion.reviews.length && <button className="button button--quiet" type="button" disabled={busy} onClick={() => void refresh()}>刷新审查结果</button>}
        {!!completion.reviews.length && <div>{completion.reviews.map(item => <article key={item.id} className="verification-panel"><h4>AI 材料审查 · {item.status === 'succeeded' ? '已完成' : item.status === 'running' ? '进行中' : '失败'}</h4>
          <p>{new Date(item.created_at).toLocaleString()}{item.provider_name ? ` · ${item.provider_name}` : ''}{item.model ? ` · ${item.model}` : ''}</p>
          {item.reason && <p>{item.reason}</p>}
          {item.result && <><p>{item.result.summary}</p>{item.result.findings.map((finding, index) => <div key={index}><strong>{findingLabel[finding.kind]}</strong>{finding.quote && <blockquote>{finding.quote}</blockquote>}<p>{finding.comment}</p></div>)}<p>判断限制：{item.result.limitations}</p><p>建议下一步：{item.result.next_step}</p></>}
          {item.user_response && <p>我的回应：{item.user_response}</p>}
          {item.status === 'succeeded' && <div><label className="field"><span>回应这次审查</span><textarea maxLength={4000} value={responses[item.id] ?? ''} onChange={event => setResponses(previous => ({ ...previous, [item.id]: event.target.value }))} /></label><button className="button button--quiet" type="button" disabled={busy || !(responses[item.id] ?? '').trim()} onClick={() => void respond(item.id)}>保存回应</button></div>}
        </article>)}</div>}
        <button className="button button--quiet" type="button" disabled={busy} onClick={() => void purge()}>删除完成记录内容</button>
        <p className="form-hint">此处删除当前完成记录的内容；受管理副本的完整清除仍是后续功能。</p>
      </>}
    </>}
    {!loading && !loadFailed && !completion && allowCreate && <form onSubmit={save}>
      <p>明确记录这次委托的执行已完成。完成不代表目标已达成或能力已掌握，也无需先进行 AI 验证。</p>
      <label className="field"><span>实际验证情况</span><select value={kind} onChange={event => setKind(event.target.value as CompletionKind)}><option value="unverified">未经过验证</option><option value="external_material">已有非 AI 验证，提供材料</option><option value="external_report">已有外部验证，暂不提供材料</option></select></label>
      {kind !== 'unverified' && <><p className="form-hint">请记录原验证的方式与实际结果。这里保存的是你的报告，平台尚未核验，也不会自动记为通过。</p><label className="field"><span>原验证方式</span><input maxLength={300} value={method} onChange={event => setMethod(event.target.value)} placeholder="例如：线下考试、导师批改" /></label><label className="field"><span>用户报告的验证结果</span><textarea maxLength={2000} value={result} onChange={event => setResult(event.target.value)} placeholder="如实记录结果，包括未通过或部分通过" /></label></>}
      {kind === 'unverified' && <label className="verification-stop-check"><input type="checkbox" checked={includeWork} onChange={event => setIncludeWork(event.target.checked)} /> <span>同时保存原始作答或作品，供以后查看或审查</span></label>}
      {(kind === 'external_material' || (kind === 'unverified' && includeWork)) && <><label className="field"><span>材料类型</span><select value={kind === 'unverified' ? 'work' : materialKind} disabled={kind === 'unverified'} onChange={event => setMaterialKind(event.target.value as 'work' | 'result')}><option value="work">原始作答或作品</option><option value="result">已有验证结果材料</option></select></label><label className="field"><span>材料名称</span><input maxLength={200} value={materialLabel} onChange={event => setMaterialLabel(event.target.value)} /></label><label className="field"><span>材料文字</span><textarea maxLength={30000} value={materialText} onChange={event => setMaterialText(event.target.value)} placeholder="粘贴相关文字；请保留题目、评分依据等必要上下文" /></label><label className="field"><span>读取本地文本文件</span><input type="file" accept=".txt,.md,.json,.py,.js,.ts" onChange={event => void readTextFile(event)} /></label><p className="form-hint">仅读取这些文本格式到当前表单；保存的是文字内容，不会上传原文件。</p></>}
      <label className="field"><span>补充说明（可选）</span><textarea maxLength={4000} value={note} onChange={event => setNote(event.target.value)} /></label>
      <button className="button button--accent" type="submit" disabled={busy}>{busy ? '正在保存…' : '记录本次完成'}</button>
    </form>}
  </section>;
}
