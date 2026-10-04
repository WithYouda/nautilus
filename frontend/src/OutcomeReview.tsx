import { useEffect, useMemo, useState } from 'react';
import { getLearningArtifact, getOutcomeReview, type LearningArtifact, type OutcomeReview as Review } from './api';
import LearningMarkdown from './LearningMarkdown';
import { PracticeDetail } from './Practice';
import { DelayedOutcomePanel } from './DelayedFollowUp';
import './styles/outcome-review.css';

const stateLabels: Record<string, string> = {
  awaiting_evidence: '等待依据', pending_review: '等待复核', insufficient_evidence: '依据不足',
  partially_supported: '部分支持', supported: '已有支持', contradicted: '不同表现',
};
const reasonLabels: Record<string, string> = {
  contradictory_evidence: '有相互冲突的依据', ai_observation_only: '目前仅有 AI 观察',
  requirements_met: '已满足当前标准要求', requirements_partially_met: '只满足部分标准要求',
  independence_unverified: '独立性尚未核实', insufficient_adopted_evidence: '已采纳的依据仍不足',
  candidate_awaiting_review: '候选依据等待复核', adopted_claim_does_not_match_recipe: '已采纳依据与标准要求不符',
  no_current_evidence: '暂无当前可用依据', execution_provenance_unverified: '依据来源尚未核实',
};
const stanceLabels: Record<string, string> = { supports: '支持', refutes: '不同表现', insufficient: '依据不足' };
const claimLabels: Record<string, string> = { candidate: '候选', adopted: '已采纳', questioned: '已质疑', withdrawn: '已撤回', superseded: '已替代', invalidated: '已失效' };
const conditionLabels: Record<string, string> = { independent: '记录为独立（含自报，未独立核实）', with_materials: '有资料', with_hints: '有提示' };
const sourceLabels: Record<string, string> = { ai_analysis: 'AI 分析', human_review: '人工复核', deterministic_check: '规则检查' };
const reviewLabels: Record<string, string> = { adopt: '采纳', question: '质疑', withdraw: '撤回', supersede: '替代', defer: '暂缓' };
const unavailableLabels: Record<string, string> = { purged: '内容已删除', hidden: '当前不可查看', not_submitted: '尚未提交' };
const standardStatusLabels: Record<string, string> = { approved: '已批准', candidate: '候选' };
const standardAvailabilityLabels: Record<string, string> = { retired: '已停用', invalidated: '已失效' };
const methodLabels: Record<string, string> = { semantic_analysis: 'AI 语义分析', independent_review: '独立复核', deterministic_check: '规则检查', python_re_search: '正则规则检查', redacted: '内容已删除' };
const evaluationLabels: Record<string, string> = { queued: '排队中', running: '处理中', succeeded: '已完成', failed: '失败', timeout: '超时', cancelled: '已取消', invalid_output: '结果无效' };
const time = (value: string) => new Date(value).toLocaleString();
const completionLabel = { unverified: '未经过验证', external_material: '用户报告非 AI 验证 · 已附材料 · 平台未核验', external_report: '用户报告外部验证 · 未附材料 · 平台未核验' };
const condition = (value: string | null) => value ? conditionLabels[value] ?? value : '帮助条件未记录';

type Attempt = Review['attempts'][number];
export default function OutcomeReview({ id, refreshKey, onBack, onOpenVerification, onOpenRecord, backLabel = '返回委托历史' }: {
  id: string; refreshKey?: number; onBack: () => void; backLabel?: string;
  onOpenVerification: (attempt: Attempt) => void; onOpenRecord: (id: string) => void;
}) {
  const [review, setReview] = useState<Review | null>(null);
  const [error, setError] = useState('');
  const [selectedArtifact, setSelectedArtifact] = useState<{ id: string; version: number } | null>(null);
  const [artifact, setArtifact] = useState<LearningArtifact | null>(null);
  const [artifactError, setArtifactError] = useState('');
  const [selectedPracticeId, setSelectedPracticeId] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    setReview(null); setSelectedArtifact(null); setSelectedPracticeId(null); setArtifact(null); setError('');
    getOutcomeReview(id).then(value => { if (active) setReview(value); })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : '依据暂时无法读取'); });
    return () => { active = false; };
  }, [id, refreshKey]);
  useEffect(() => {
    let active = true;
    setArtifact(null); setArtifactError('');
    if (selectedArtifact) getLearningArtifact(selectedArtifact.id, selectedArtifact.version)
      .then(value => { if (active) setArtifact(value); })
      .catch(reason => { if (active) setArtifactError(reason instanceof Error ? reason.message : '原始产出暂时无法读取'); });
    return () => { active = false; };
  }, [selectedArtifact]);
  const activeStandards = useMemo(() => review?.standards.filter(s => s.review_status === 'approved' && s.availability === null) ?? [], [review]);
  const otherStandards = useMemo(() => review?.standards.filter(s => s.review_status !== 'approved' || s.availability !== null) ?? [], [review]);
  const grouped = useMemo(() => {
    const dimensions = activeStandards.flatMap(standard => standard.dimensions.map(dimension => ({ standard, dimension })));
    return {
      supported: dimensions.filter(({ dimension }) => dimension.state?.status === 'supported' || dimension.state?.status === 'partially_supported'),
      different: dimensions.filter(({ dimension }) => dimension.state?.status === 'contradicted'),
      unknown: dimensions.filter(({ dimension }) => !dimension.state || ['awaiting_evidence', 'pending_review', 'insufficient_evidence'].includes(dimension.state.status)),
    };
  }, [activeStandards]);
  const artifactVersions = useMemo(() => new Set(review?.artifacts.filter(a => a.available).map(a => `${a.artifact_id}:${a.content_version}`)), [review]);
  const standardsById = useMemo(() => new Map(review?.standards.map(standard => [standard.id, standard]) ?? []), [review]);
  function standardName(id: string | null) {
    const standard = id ? standardsById.get(id) : null;
    return standard ? `${standard.title} · v${standard.version}` : '未关联可用标准';
  }
  function dimensionName(criterionId: string, dimensionId: string) {
    return standardsById.get(criterionId)?.dimensions.find(dimension => dimension.id === dimensionId)?.label ?? '维度信息暂不可用';
  }
  function rawArtifact(artifactId: string, version: number) { setSelectedArtifact({ id: artifactId, version }); }
  return <section className="outcome-review" aria-label="单成果依据回看">
    <div className="outcome-review__heading"><h3>这个成果的依据</h3><button className="button button--quiet" type="button" onClick={onBack}>{backLabel}</button></div>
    {error && <p role="alert">{error}</p>}
    {!review && !error && <p role="status">正在读取成果记录…</p>}
    {review && <>
      <div className="outcome-review__identity"><strong>{review.outcome.object_description}</strong><p>{review.outcome.behavior}</p>{review.outcome.context_key && <small>情境：{review.outcome.context_key}</small>}</div>
      <section aria-label="当前依据状态"><h4>按当前已批准标准整理的依据状态</h4>
        {!activeStandards.length ? <p>目前没有可用的已批准标准。以下仅展示原始记录和反馈，无法判断当前支持程度。</p> : <div className="outcome-review__states">
          {([['supported', '已有支持'], ['different', '不同表现'], ['unknown', '仍待判断']] as const).map(([key, title]) => <div key={key}><h5>{title}</h5>{grouped[key].length ? <ul>{grouped[key].map(({ standard, dimension }) => <li key={`${standard.id}:${dimension.id}`}><strong>{dimension.label}</strong><span>{standard.title} · v{standard.version} · {dimension.state ? stateLabels[dimension.state.status] ?? '状态待确认' : '尚无状态计算'}</span>{dimension.state && <small>原因：{reasonLabels[dimension.state.reason_code] ?? '原因待确认'} · {time(dimension.state.calculated_at)} · 参与依据 {dimension.state.participating_claim_ids.length} 条，排除 {dimension.state.excluded_claim_ids.length} 条</small>}</li>)}</ul> : <p>暂无</p>}</div>)}
        </div>}
        <p className="form-hint">这里仅整理当前可用的已批准标准；逐条记录、AI 反馈与人工复核见下方。不同时间、标准和帮助条件的记录分别保留。</p>
      </section>
      {!!otherStandards.length && <details><summary>其他标准版本（历史或候选，不计入当前支持）</summary><ul>{otherStandards.map(s => <li key={s.id}>{s.title} · v{s.version} · {standardStatusLabels[s.review_status] ?? '审核状态待确认'}{s.availability ? ` · ${standardAvailabilityLabels[s.availability] ?? '当前不可用'}` : ''}</li>)}</ul></details>}
      <section aria-label="关联委托"><h4>关联委托</h4>{review.records.length ? <ul className="outcome-review__plain-list">{review.records.map(record => <li key={record.id}><button className="text-button" type="button" onClick={() => onOpenRecord(record.id)}>{record.title}</button><small>{time(record.created_at)}</small></li>)}</ul> : <p>暂无明确关联的委托。</p>}</section>
        <section aria-label="执行完成记录"><h4>执行完成记录</h4>{review.completions?.length ? <div className="outcome-review__timeline">{review.completions.map(item => <article key={item.id}><div className="outcome-review__item-head"><strong>{item.purged_at && item.verification_kind === 'external_material' ? '用户报告非 AI 验证 · 曾附材料，内容已删除 · 平台未核验' : completionLabel[item.verification_kind]}</strong><time>{time(item.created_at)}</time></div>{item.purged_at && <p>内容已删除</p>}<button className="button button--quiet" type="button" onClick={() => onOpenRecord(item.delegation_id!)}>查看原委托记录</button></article>)}</div> : <p>暂无执行完成记录。</p>}</section>
      <section aria-label="作答与反馈"><h4>作答与反馈</h4>{review.attempts.length ? <div className="outcome-review__timeline">{review.attempts.map((attempt, index) => <article key={`${attempt.verification_id}:${attempt.submission_id ?? 'none'}:${attempt.evaluation_id ?? 'none'}:${index}`}>
        <div className="outcome-review__item-head"><strong>{attempt.action_title}</strong><time>{time(attempt.created_at)}</time></div>
        <p>{attempt.mode === 'ai_challenge' ? 'AI 出题' : '提交材料'} · {condition(attempt.condition)} · {standardName(attempt.criterion_id)}{attempt.contract_version !== null ? ` · 当时任务约定 v${attempt.contract_version}` : ''}</p>
        {!attempt.available ? <p>{unavailableLabels[attempt.unavailable_reason ?? ''] ?? '内容不可查看'}</p> : <>
          <p>{attempt.evaluation_status ? `AI 评估：${evaluationLabels[attempt.evaluation_status] ?? '状态待确认'}` : '尚无评估'}{attempt.passed !== null ? ` · ${attempt.passed ? 'AI 判断通过' : 'AI 判断待补强'}` : ''}</p>
          {attempt.feedback && <details><summary>查看 AI 反馈</summary><div className="ai-markdown"><LearningMarkdown>{attempt.feedback}</LearningMarkdown></div></details>}
          <button className="button button--quiet" type="button" onClick={() => onOpenVerification(attempt)}>查看当时作答与评估版本</button>
        </>}
      </article>)}</div> : <p>暂无明确关联的作答。</p>}
      <p className="form-hint">AI 反馈是当时的评估记录，包括“通过”时也不代表平台已独立核实。</p></section>
      <section aria-label="针对性补练记录"><h4>针对性补练</h4><p className="form-hint">补练与原验证分别保存；这里展示练习和反馈，不据此自动推断正式能力。</p>{review.practices?.length ? <div className="outcome-review__timeline">{review.practices.map(item => <article key={item.id}><div className="outcome-review__item-head"><strong>{item.question_id} · {item.status === 'purged' ? '内容已删除' : '补练记录'}</strong><time>{time(item.created_at)}</time></div><p>作答 {item.attempt_count} 次{item.latest_feedback ? ` · 最新 AI 反馈：${item.latest_feedback}` : ''}</p><button className="button button--quiet" type="button" disabled={!item.available} onClick={() => setSelectedPracticeId(item.id)}>查看这项补练</button></article>)}</div> : <p>暂无针对性补练记录。</p>}{selectedPracticeId && <div className="outcome-review__raw"><button className="text-button" type="button" onClick={() => setSelectedPracticeId(null)}>返回补练列表</button>{(() => { const selected = review.practices?.find(item => item.id === selectedPracticeId); const original = selected && review.attempts.find(item => item.verification_id === selected.verification_id && item.submission_id === selected.submission_id && item.evaluation_id === selected.evaluation_id); return original ? <button className="text-button" type="button" onClick={() => onOpenVerification(original)}>查看原验证版本</button> : null; })()}<PracticeDetail key={selectedPracticeId} id={selectedPracticeId} readOnly /></div>}</section>
      <section aria-label="产出与证据"><h4>原始产出与证据</h4>{review.artifacts.length ? <div className="outcome-review__timeline">{review.artifacts.map(item => <article key={`${item.artifact_id}:${item.content_version}`}>
        <div className="outcome-review__item-head"><strong>{item.action_title} · 产出 v{item.content_version}</strong><time>{time(item.created_at)}</time></div><p>{item.evidence_status === 'withdrawn' ? '当前产出记录已撤回 · ' : item.evidence_status === 'invalidated' ? '当前产出记录已失效 · ' : ''}{standardName(item.criterion_id)}</p>
        {item.available ? <button className="button button--quiet" type="button" onClick={() => rawArtifact(item.artifact_id, item.content_version)}>查看这个版本的原始产出</button> : <p>{item.visibility === 'purged' ? '内容已删除' : '当前不可查看'}</p>}
      </article>)}</div> : <p>暂无明确关联的产出。</p>}
      {selectedArtifact && <div className="outcome-review__raw" aria-label="原始产出版本"><div className="outcome-review__item-head"><strong>原始产出 · v{selectedArtifact.version}</strong><button className="text-button" type="button" onClick={() => setSelectedArtifact(null)}>收起</button></div>{artifactError && <p role="alert">{artifactError}</p>}{!artifact && !artifactError && <p role="status">正在读取原始版本…</p>}{artifact && (artifact.purged_at || artifact.content === null || !review.artifacts.some(item => item.artifact_id === selectedArtifact.id && item.content_version === selectedArtifact.version && item.available) ? <p>这个版本当前不可查看。</p> : <div className="ai-markdown"><LearningMarkdown>{artifact.content}</LearningMarkdown></div>)}</div>}
      </section>
      <section aria-label="证据判断与质疑"><h4>证据判断与质疑</h4>{review.claims.length ? <div className="outcome-review__timeline">{review.claims.map(claim => <article key={claim.id}>
        <div className="outcome-review__item-head"><strong>{stanceLabels[claim.stance] ?? claim.stance} · {claimLabels[claim.status] ?? claim.status}</strong><time>{time(claim.created_at)}</time></div>
        <p>{sourceLabels[claim.source] ?? claim.source} · {condition(claim.condition_basis === 'unobserved' || !claim.condition_basis ? null : claim.evidence_condition)} · 产出 v{claim.content_version}</p>
        <p>{standardName(claim.criterion_id)} · {dimensionName(claim.criterion_id, claim.dimension_id)} · 核验方式：{methodLabels[claim.verification_method] ?? '方式待确认'}</p>
        {claim.available && claim.statement && <p>{claim.statement}</p>}
        {!claim.available && <p>关联内容当前不可查看。</p>}
        {claim.available && artifactVersions.has(`${claim.artifact_id}:${claim.content_version}`) && <button className="text-button" type="button" onClick={() => rawArtifact(claim.artifact_id, claim.content_version)}>查看所引用的产出 v{claim.content_version}</button>}
        {claim.available && !artifactVersions.has(`${claim.artifact_id}:${claim.content_version}`) && review.attempts.some(attempt => attempt.available && attempt.artifact_id === claim.artifact_id) && <button className="text-button" type="button" onClick={() => {
          const attempt = review.attempts.find(item => item.available && item.artifact_id === claim.artifact_id);
          if (attempt) onOpenVerification(attempt);
        }}>查看关联的作答与评估</button>}
        {!!claim.reviews.length && <details><summary>质疑与复核记录（{claim.reviews.length}）</summary><ul>{claim.reviews.map(action => <li key={action.id}>{time(action.created_at)} · {reviewLabels[action.action] ?? action.action}{action.reason ? ` · ${action.reason}` : ''}</li>)}</ul></details>}
      </article>)}</div> : <p>暂无明确关联的证据判断。</p>}</section>
      <DelayedOutcomePanel key={id} outcomeId={id} refreshKey={refreshKey} />
      <section aria-label="后续安排"><h4>后续安排</h4><p className="form-hint">安排记录，不等于实际验证结果。当前没有关联的实际回访结果时，结果仍待判断。</p>{review.follow_ups.length ? <ul className="outcome-review__plain-list">{review.follow_ups.map(item => <li key={item.id}><strong>{item.kind === 'human_review' ? '人工复核' : '补充验证'} · {item.status === 'pending' ? '待处理' : item.status === 'completed' ? '安排已处理' : '已取消'}</strong><span>创建于 {time(item.created_at)}{item.due_at ? ` · 计划 ${time(item.due_at)}` : ''}</span>{item.note && <p>{item.note}</p>}</li>)}</ul> : <p>暂无后续安排记录。</p>}</section>
    </>}
  </section>;
}
