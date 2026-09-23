import { useEffect, useState } from 'react';
import { chooseReturnReview, getLearningRoom, reviewEvidenceClaim, type LearningRoomBrief, type ReturnReview } from './api';

export default function ReturnReviewCard({ card, onContinue, onSetup, onChanged }: {
  card: ReturnReview; onContinue: (brief: LearningRoomBrief) => void; onSetup: (reviewId?: string) => void; onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [details, setDetails] = useState(false);
  const [alternatives, setAlternatives] = useState(false);
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
      if (result.destination === 'choose') setAlternatives(true);
      else if (result.destination === 'stopped') { await onChanged(); setStopped(true); }
      else if (result.destination === 'evidence') setDetails(true);
      else if (result.destination === 'setup') { if (kind === 'choose_new') await onChanged(); onSetup(kind === 'choose_new' ? undefined : card.id); }
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
  return <section className="return-review" aria-label="继续学习复核卡">
    <p className="eyebrow">继续你的学习</p>
    <h2>{card.recommendation.reason_code === 'interrupted' ? '你上次在这里中断' : '从上次的位置继续'}</h2>
    <p className="return-review__position">上次你在：<strong>{card.position.action}</strong></p>
    {card.position.goal && <p className="return-review__route">{card.position.goal} · {card.position.plan}</p>}
    <p>{card.what_happened.summary}</p>
    <div className="return-review__next"><span>推荐下一步</span><h3>{card.recommendation.label}</h3><p>原因：{card.recommendation.explanation}</p></div>
    <div className="return-review__actions">
      <button className="button button--accent" disabled={busy} onClick={() => void choose('continue')}>继续</button>
      <button className="button button--quiet" disabled={busy} onClick={() => void choose('choose_other')}>换一个</button>
      <button className="button button--quiet" disabled={busy} onClick={() => void choose('stop_for_now')}>今天先停</button>
    </div>
    {stopped && <p role="status">今天先到这里。学习位置已保留，下次回来可以继续。</p>}
    {error && <p role="alert" className="workspace-alert">{error}</p>}
    {alternatives && <div className="return-review__alternatives"><h3>选择已有任务</h3>
      {card.alternatives.map(item => <button className="button button--quiet" key={item.delegation_id} disabled={busy} onClick={() => void choose('choose_other', item.delegation_id)}>{item.label}</button>)}
      <p>若有正在进行的学习，会先暂停；已保存记录仍保留。</p>
      <button className="button button--quiet" disabled={busy} onClick={() => void choose('choose_new')}>不继续这个方向，安排新的第一步</button>
    </div>}
    <div className="return-review__evidence"><div><h3>已有依据</h3>
      {card.supported.length ? card.supported.map(item => <p key={item.claim_id}><strong>{item.label}</strong><br />{item.user_facing_explanation}</p>) : <p>尚无经复核的可靠依据。保存或验证通过的记录仍然保留。</p>}
    </div><div><h3>仍然未知</h3><p>{card.unknowns[0]?.label}</p>
      {card.unknowns.length > 1 && <details><summary>其余 {card.unknowns.length - 1} 项待观察</summary>{card.unknowns.slice(1).map(item => <p key={item.reason_code}>{item.label}</p>)}</details>}
    </div></div>
    <button className="text-button" onClick={() => { setDetails(!details); if (!details) void chooseReturnReview(card.id, 'evidence_viewed', `evidence:${card.id}`).catch(() => setError('查看记录未保存。')); }}>查看依据</button>
    {details && <div className="return-review__details"><p>采纳表示保留这条观察，不等于独立验证或稳定掌握。</p>
      {card.evidence_details.length ? card.evidence_details.map(item => <article key={item.id}><p>{item.statement}</p><small>{item.status === 'candidate' ? '待你复核' : item.status === 'adopted' ? '已采纳观察' : '已提出疑问'} · {!item.source_trusted ? '来源待核实' : item.source === 'deterministic_check' ? '当前样例检查' : 'AI 观察'}</small>
        {item.status === 'candidate' && <div className="return-review__actions"><button className="button button--quiet" disabled={busy} onClick={() => void review(item.id, 'adopt')}>保留这条观察</button><button className="button button--quiet" disabled={busy} onClick={() => void review(item.id, 'question')}>提出疑问</button></div>}
      </article>) : <p>当前没有可复核的成果依据。</p>}
    </div>}
  </section>;
}
