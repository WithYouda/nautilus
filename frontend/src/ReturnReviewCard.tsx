import { useEffect, useState } from 'react';
import { chooseReturnReview, getLearningRoom, reviewEvidenceClaim, type LearningRoomBrief, type ReturnReview } from './api';

export default function ReturnReviewCard({ card, onContinue, onSetup, onChanged, onOpenRecord, onOpenPlan }: {
  card: ReturnReview; onContinue: (brief: LearningRoomBrief) => void; onSetup: (reviewId?: string, planId?: string) => void; onChanged: () => Promise<void>;
  onOpenRecord: (id: string, verificationId?: string | null) => void; onOpenPlan: (id?: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [details, setDetails] = useState(false);
  const [stopped, setStopped] = useState(false);
  useEffect(() => {
    setStopped(false);
    void chooseReturnReview(card.id, 'review_card_shown', `shown:${card.id}`).catch(() => setError('展示记录暂未保存，请刷新后重试。'));
  }, [card.id]);
  async function choose(kind: 'continue' | 'choose_other' | 'choose_new' | 'stop_for_now', delegationId?: string) {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const result = await chooseReturnReview(card.id, kind, `${card.id}:${kind}:${delegationId ?? ''}`, delegationId);
      if (result.destination === 'stopped') { await onChanged(); setStopped(true); }
      else if (result.destination === 'evidence') setDetails(true);
      else if (result.destination === 'setup') { if (kind === 'choose_new') await onChanged(); onSetup(kind === 'choose_new' ? undefined : card.id, kind === 'choose_new' ? undefined : card.position.plan_id ?? undefined); }
      else if (result.session_id) {
        const room = await getLearningRoom(result.session_id);
        onContinue({ ...room.brief, continuity_review_id: card.id, open_verification: result.destination === 'verification' });
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : '暂时无法继续，请重试。'); }
    finally { setBusy(false); }
  }
  async function review(id: string, action: 'adopt' | 'question') {
    setBusy(true); setError('');
    try { await reviewEvidenceClaim(id, { action, request_key: `${card.id}:${id}:${action}` }); await onChanged(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '复核未保存。'); }
    finally { setBusy(false); }
  }
  const completed = card.what_happened.delegation_status === 'completed';
  const saved = !completed && card.what_happened.has_saved_answer;
  const started = card.what_happened.session_status !== null;
  const status = completed ? '已完成' : saved || !started ? '已保存' : '正在学习';
  return <section className="return-review" aria-label="当前学习">
    <span className={`learning-state-label learning-state-label--${completed ? 'complete' : 'active'}`}>{status}</span>
    <h2>{card.position.action}</h2>
    {card.position.goal && <p className="return-review__route">{card.position.goal}{card.position.plan && ` · ${card.position.plan}`}</p>}
    <p className="return-review__fact">{completed ? card.what_happened.verification_id ? '本次学习已完成，作答和验证反馈已保存。' : '本次学习已完成，学习记录已保留。' : saved ? '作答已保存，可以查看反馈并继续验证。' : card.what_happened.session_status === 'interrupted' ? '学习位置已保存，可以接着上次的内容继续。' : started ? '接着当前任务学习，对话和验证记录会保留。' : '学习安排已保存，可以开始这项任务。'}</p>
    <div className="return-review__actions">
      {completed ? <>
        <button className="button button--accent" onClick={() => onOpenRecord(card.position.delegation_id, card.what_happened.verification_id)}>{card.what_happened.verification_id ? '查看验证记录' : '查看记录'}</button>
        {card.position.plan_id && <button className="button button--quiet" disabled={busy} onClick={() => card.recommendation.kind === 'choose_next' ? void choose('continue') : onSetup(undefined, card.position.plan_id!)}>添加下一步</button>}
      </> : <>
        <button className="button button--accent" disabled={busy} onClick={() => void choose('continue')}>{saved ? '继续验证' : started ? '继续学习' : '开始学习'}</button>
        {saved && <button className="button button--quiet" onClick={() => onOpenRecord(card.position.delegation_id, card.what_happened.verification_id)}>查看作答与反馈</button>}
        {card.what_happened.session_status === 'running' && <button className="text-button" disabled={busy} onClick={() => void choose('stop_for_now')}>暂停学习</button>}
      </>}
      {card.position.plan_id && <button className="text-button" onClick={() => onOpenPlan(card.position.plan_id!)}>查看计划</button>}
    </div>
    {stopped && <p role="status">学习位置已保存。</p>}
    {error && <p role="alert" className="workspace-alert">{error}</p>}
    <button className="text-button learning-observations-toggle" aria-expanded={details} onClick={() => { setDetails(!details); if (!details) void chooseReturnReview(card.id, 'evidence_viewed', `evidence:${card.id}`).catch(() => setError('查看记录未保存。')); }}>学习判断详情{card.evidence_details.filter(item => item.status === 'candidate').length ? ' · 有待复核观察' : ''}</button>
    {details && <div className="return-review__details"><h3>对掌握情况的观察</h3><p>这里单独说明学习记录能支持哪些能力判断。</p><p>采纳表示保留这条观察，不等于稳定掌握。</p>{card.supported.map(item => <p key={item.claim_id}>{item.user_facing_explanation}</p>)}<details><summary>判断范围与待观察内容</summary>{card.unknowns.map(item => <p key={item.reason_code}>{item.label}</p>)}</details>
      {card.evidence_details.length ? card.evidence_details.map(item => <article key={item.id}><p>{item.statement}</p><small>{item.status === 'candidate' ? '待你复核' : item.status === 'adopted' ? '已采纳观察' : '已提出疑问'} · {!item.source_trusted ? '来源待核实' : item.source === 'deterministic_check' ? '当前样例检查' : 'AI 观察'}</small>
        {item.status === 'candidate' && <div className="return-review__actions"><button className="button button--quiet" disabled={busy} onClick={() => void review(item.id, 'adopt')}>保留这条观察</button><button className="button button--quiet" disabled={busy} onClick={() => void review(item.id, 'question')}>提出疑问</button></div>}
      </article>) : <p>当前没有额外的能力观察需要复核。</p>}
    </div>}
  </section>;
}
