import { useEffect, useState } from 'react';
import { listLearningRecords, getLearningRecord, type LearningRecord, type LearningRecordDetail, type LearningRoomBrief } from './api';
import VerificationReview from './VerificationReview';
import OutcomeReview from './OutcomeReview';
import OutcomeGraph from './OutcomeGraph';
import QuestionDiscussion from './QuestionDiscussion';
import LearningPageHeader from './LearningPageHeader';
import LearningCompletion from './LearningCompletion';
import SessionFeedback from './SessionFeedback';

const labels: Record<string, string> = { ready: '待开始', active: '进行中', paused: '已暂停', completed: '已完成', cancelled: '已取消', passed: '已确认完成', submitted: '已评估', failed: '待补强' };
export function setReviewLocation(key: string, value: string | null) {
  const url = new URL(window.location.href);
  if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
  window.history.replaceState(null, '', url);
}
export default function LearningRecords({ onClose, onLearning }: { onClose: () => void; onLearning?: (brief: LearningRoomBrief) => void }) {
  const query = new URLSearchParams(window.location.search);
  const [items, setItems] = useState<LearningRecord[]>([]);
  const [recordId, setRecordId] = useState<string | null>(query.get('record'));
  const [record, setRecord] = useState<LearningRecordDetail | null>(null);
  const [outcomeId, setOutcomeId] = useState<string | null>(query.get('outcome'));
  const [graph, setGraph] = useState(query.get('graph') === '1');
  const [verificationId, setVerificationId] = useState<string | null>(query.get('verification'));
  const [submissionId, setSubmissionId] = useState<string | null>(query.get('submission'));
  const [evaluationId, setEvaluationId] = useState<string | null>(query.get('evaluation'));
  const [outcomeRefresh, setOutcomeRefresh] = useState(0);
  const [discussionId, setDiscussionId] = useState<string | null>(query.get('discussion'));
  const [error, setError] = useState('');
  const [recordRefresh, setRecordRefresh] = useState(0);
  useEffect(() => { listLearningRecords().then(setItems).catch(reason => setError(reason.message)); }, []);
  useEffect(() => {
    let active = true;
    setRecord(null);
    if (recordId) getLearningRecord(recordId).then(value => { if (active) setRecord(value); }).catch(reason => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [recordId, recordRefresh]);
  function refreshRecords() {
    setRecordRefresh(value => value + 1);
    setOutcomeRefresh(value => value + 1);
    listLearningRecords().then(setItems).catch(reason => setError(reason instanceof Error ? reason.message : '记录暂时无法刷新'));
  }
  function discuss(id: string | null) { setDiscussionId(id); setReviewLocation('discussion', id); }
  function selectVerification(id: string | null, submission: string | null = null, evaluation: string | null = null) {
    setVerificationId(id); setSubmissionId(submission); setEvaluationId(evaluation);
    setReviewLocation('verification', id); setReviewLocation('submission', submission); setReviewLocation('evaluation', evaluation);
  }
  if (discussionId) return <QuestionDiscussion id={discussionId} onNavigate={discuss} onBack={() => discuss(null)} />;
  if (graph && !outcomeId && !verificationId) return <OutcomeGraph onBack={() => { setGraph(false); for (const key of ['graph', 'graph_plan', 'graph_node']) setReviewLocation(key, null); }} onEvidence={id => { setOutcomeId(id); setReviewLocation('outcome', id); }} />;
  return <section className="learning-records learning-page" aria-label="学习记录">
    <LearningPageHeader title="学习记录" description="查看学习对话、历次作答和 AI 反馈。记录会自动保存。">
      <button className="button button--quiet" type="button" onClick={() => { setGraph(true); setRecordId(null); setRecord(null); setOutcomeId(null); selectVerification(null); setReviewLocation('record', null); setReviewLocation('outcome', null); setReviewLocation('graph', '1'); }}>成果图</button>
      <button className="button button--quiet" type="button" onClick={() => { for (const key of ['record', 'outcome', 'verification', 'submission', 'evaluation', 'discussion', 'graph', 'graph_plan', 'graph_node']) setReviewLocation(key, null); onClose(); }}>返回首页</button>
    </LearningPageHeader>
    {error && <p role="alert">{error}</p>}
    {!graph && <div className="learning-records-list">{items.map(item => <button type="button" className="verification-panel" key={item.id} aria-pressed={recordId === item.id && !outcomeId} onClick={() => { setRecordId(item.id); setOutcomeId(null); setReviewLocation('outcome', null); selectVerification(null); setReviewLocation('record', item.id); }}>
      <strong>{item.title}</strong><span>{labels[item.status] ?? '已记录'} · {item.verification_count} 次 AI 验证</span><small>{item.goal_title || '独立学习'}{item.plan_title ? ` · ${item.plan_title}` : ''}</small>
    </button>)}</div>}
    {!graph && !items.length && !error && <p>还没有学习记录。创建计划并开始学习后，记录会出现在这里。</p>}
    {record && !outcomeId && <section aria-label="委托历史"><h3>{record.record.title}</h3>
      <p>任务状态：{labels[record.record.status] ?? '已记录'}</p>
      <div className="record-verification-list"><button className="button" type="button" onClick={() => { setOutcomeId(record.record.outcome_id); setReviewLocation('outcome', record.record.outcome_id); selectVerification(null); }}>查看这个成果的依据</button>
        {record.brief && onLearning && <button className="button button--quiet" type="button" onClick={() => { for (const key of ['record', 'outcome', 'verification', 'submission', 'evaluation', 'discussion']) setReviewLocation(key, null); onLearning({ ...record.brief!, history_only: true }); }}>查看原学习对话</button>}</div>
      <div className="record-verification-list">{record.verifications.map((v, i) => <button type="button" className="button button--quiet" key={v.id} aria-pressed={verificationId === v.id} onClick={() => selectVerification(v.id)}>验证 {record.verifications.length - i} · {v.mode === 'ai_challenge' ? 'AI 出题' : '提交材料'} · {v.purged_at ? '内容已删除' : labels[v.status] ?? '已保存'}</button>)}</div>
      {!record.verifications.length && <p>尚未发起 AI 验证；原学习记录仍保留。</p>}
      <LearningCompletion key={record.record.id} delegationId={record.record.id} allowCreate={record.record.status !== 'completed' && record.record.status !== 'cancelled'} onCompleted={refreshRecords} onPurged={refreshRecords} />
      {!!record.sessions?.length && <details><summary>各次学习的本人体验</summary>{record.sessions.map(session=><section key={session.id}><p>{new Date(session.started_at).toLocaleString()}</p><SessionFeedback sessionId={session.id} onSaved={refreshRecords} /></section>)}</details>}
    </section>}
    {outcomeId && !verificationId && <OutcomeReview id={outcomeId} refreshKey={outcomeRefresh} backLabel={graph ? '返回成果图' : undefined} onBack={() => { setOutcomeId(null); setReviewLocation('outcome', null); selectVerification(null); }} onOpenRecord={id => { setGraph(false); setReviewLocation('graph', null); setRecordId(id); setReviewLocation('record', id); setOutcomeId(null); setReviewLocation('outcome', null); selectVerification(null); }} onOpenVerification={attempt => selectVerification(attempt.verification_id, attempt.submission_id, attempt.evaluation_id)} />}
    {verificationId && <div className="record-verification-detail"><div className="record-verification-list"><button className="button button--quiet" type="button" onClick={() => selectVerification(null)}>{outcomeId ? '返回成果依据' : '收起验证回看'}</button></div><VerificationReview key={verificationId} id={verificationId} initialSubmissionId={submissionId} initialEvaluationId={evaluationId} onSelectionChange={(submission, evaluation) => { setSubmissionId(submission); setEvaluationId(evaluation); setReviewLocation('submission', submission); setReviewLocation('evaluation', evaluation); }} onPurged={() => setOutcomeRefresh(value => value + 1)} onDiscuss={id => discuss(id)} /></div>}
  </section>;
}
