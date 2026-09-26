import { useEffect, useRef, useState } from 'react';
import QuestionFeedbackContent from './QuestionFeedbackContent';
import LearningMarkdown from './LearningMarkdown';
import { createQuestionDiscussion, getVerificationReview, purgeVerification, recordReferenceHelpDisplay, type VerificationReview as Review, type LearningVerification } from './api';
import PurgeStatus from './PurgeStatus';
import { PracticePanel } from './Practice';

export default function VerificationReview({ id, refreshKey, onDiscuss, onPurged, onReadSolution, initialSubmissionId, initialEvaluationId, onSelectionChange }: {
  id: string; refreshKey?: string; onDiscuss: (id: string) => void;
  onPurged?: (verification: LearningVerification) => void; onReadSolution?: () => void;
  initialSubmissionId?: string | null; initialEvaluationId?: string | null;
  onSelectionChange?: (submissionId: string | null, evaluationId: string | null) => void;
}) {
  const [review, setReview] = useState<Review | null>(null);
  const [submission, setSubmission] = useState<string | undefined>(initialSubmissionId ?? undefined);
  const [evaluation, setEvaluation] = useState<string | undefined>(initialEvaluationId ?? undefined);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const currentId = useRef(id);
  currentId.current = id;
  useEffect(() => { setSubmission(initialSubmissionId ?? undefined); setEvaluation(initialEvaluationId ?? undefined); }, [id, initialSubmissionId, initialEvaluationId]);
  useEffect(() => {
    let active = true;
    setReview(null); setError('');
    getVerificationReview(id, submission, evaluation).then(value => { if (active) setReview(value); })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : '记录暂时无法读取'); });
    return () => { active = false; };
  }, [id, submission, evaluation, refreshKey]);
  async function discuss(questionId: string) {
    if (!review?.selected_submission_id || busy) return;
    setBusy(true); setError('');
    try {
      const thread = await createQuestionDiscussion(id, review.selected_submission_id, questionId, crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`, review.selected_evaluation_id);
      onDiscuss(thread.id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '讨论暂未创建'); }
    finally { setBusy(false); }
  }
  async function purge() {
    if (!review || busy) return;
    if (!review.verification.verification_purged && !window.confirm(`彻底删除本次验证的题目、全部作答和评估？另有 ${review.purge_discussion_count} 段关联或引用它的题目讨论正文会一并清除。同时清除受管理历史版本和普通备份中的对应内容，不可恢复；其他记录保留。外部副本另列结果。依赖证据失效，完成记录保留。`)) return;
    setBusy(true); setError('');
    try {
      const value = await purgeVerification(id);
      if (currentId.current !== id) return;
      setSubmission(undefined); setEvaluation(undefined);
      setReview(null);
      onSelectionChange?.(null, null);
      onPurged?.(value);
      const next = await getVerificationReview(id);
      if (currentId.current === id) setReview(next);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '删除未完成'); }
    finally { setBusy(false); }
  }
  const questions = review?.verification.challenge.questions?.length ? review.verification.challenge.questions : [{ id: 'material', prompt: '本次材料验证' }];
  return <section className="verification-review" aria-label="验证回看">
    {error && <p role="alert">{error}</p>}
    {!review && !error && <p role="status">正在读取保存的验证…</p>}
    {review && <>
      <p className="form-hint">题目、已提交作答和评估自动保存。继续讨论不会改写原验证结果。</p>
      {review.submissions.length > 0 && <label className="field"><span>查看哪次作答</span><select value={review.selected_submission_id ?? ''} onChange={event => { setEvaluation(undefined); setSubmission(event.target.value); onSelectionChange?.(event.target.value, null); }}>
        {review.submissions.map((s, i) => <option key={s.id} value={s.id}>第 {review.submissions.length - i} 次 · {new Date(s.created_at).toLocaleString()}{s.purged_at ? ' · 内容已删除' : ''}</option>)}
      </select></label>}
      {review.evaluations.length > 1 && <label className="field"><span>查看哪次评估</span><select value={review.selected_evaluation_id ?? ''} onChange={event => { setEvaluation(event.target.value); onSelectionChange?.(review.selected_submission_id, event.target.value); }}>
        {review.evaluations.map((e, i) => <option key={e.id} value={e.id}>第 {review.evaluations.length - i} 次评估 · {e.status === 'succeeded' ? '已完成' : e.status === 'running' ? '处理中' : '未完成'}</option>)}
      </select></label>}
      {!review.content ? <p>{review.verification.content_purged || review.submissions.find(s => s.id === review.selected_submission_id)?.purged_at ? '本次作答在线内容已清除。完成事实仍保留；副本清除进度见下方结果。' : '尚未保存作答。'}</p> : <>
        {review.content.help_context && <div className="form-hint" aria-label="提交时帮助条件">
          <p>提交时自报：{review.content.help_context.user_report === 'independent' ? '自报独立完成' : review.content.help_context.user_report === 'with_materials' ? '自报借助资料或帮助' : '未填写'} · 截至 {new Date(review.content.help_context.captured_at).toLocaleString()}</p>
          <p>提交时同次验证的帮助记录：{review.content.help_context.records.length ? review.content.help_context.records.map(item => {
            const label = item.kind === 'reference_answer' ? '参考解法' : '讨论回复';
            const generated = item.kind === 'discussion_reply' ? `已生成${item.characters ?? 0}字符${item.partial ? '（部分输出）' : ''}${item.provided_at ? `，${new Date(item.provided_at).toLocaleString()}` : ''}` : '';
            const shown = item.displayed_at ? `页面呈现记录 ${new Date(item.displayed_at).toLocaleString()}` : '无页面呈现记录';
            return `${label}（${[generated, shown].filter(Boolean).join('；')}）`;
          }).join('、') : '无记录'}。无记录不证明独立完成；页面呈现不证明已阅读或理解；后续展示不会改写这次作答。</p>
        </div>}
        {questions.map((question, index) => {
          const feedback = review.result?.question_feedback?.find(item => item.question_id === question.id);
          return <article className="verification-question" key={question.id} aria-label={`第 ${index + 1} 题回看`}>
            <div className="review-question-heading"><h3>第 {index + 1} 题</h3><button type="button" className="button button--quiet" disabled={busy} onClick={() => void discuss(question.id)}>讨论这道题</button></div>
            <div className="ai-markdown"><LearningMarkdown>{question.prompt}</LearningMarkdown></div>
            {review.content?.material && <details><summary>本次参考材料</summary><div className="ai-markdown"><LearningMarkdown>{review.content.material}</LearningMarkdown></div></details>}
            <h4>我当时的回答</h4><div className="ai-markdown review-answer"><LearningMarkdown>{review.content?.responses?.[question.id] ?? review.content?.learner_work ?? '没有提交本人作答'}</LearningMarkdown></div>
            {feedback ? <QuestionFeedbackContent key={`${review.selected_evaluation_id}:${question.id}`} feedback={feedback} onReadSolution={onReadSolution} helpDisplay={review.help_displays?.[question.id]} onRecordDisplay={review.selected_evaluation_id ? async () => {
              const selectedEvaluation = review.selected_evaluation_id!;
              const value = await recordReferenceHelpDisplay(id, selectedEvaluation, question.id);
              setReview(previous => previous?.selected_evaluation_id === selectedEvaluation ? { ...previous, help_displays: { ...previous.help_displays, [question.id]: value } } : previous);
              return value;
            } : undefined} /> : <p className="form-hint">{review.result ? '这次记录未保存逐题反馈，可在讨论中请 AI 重新讲解。' : '本题反馈尚未生成，作答已保存。'}</p>}
            {feedback && review.selected_submission_id && review.selected_evaluation_id && <details className="practice-entry" key={`practice:${review.selected_submission_id}:${review.selected_evaluation_id}:${question.id}`}><summary>针对性补练</summary><PracticePanel verificationId={id} submissionId={review.selected_submission_id} evaluationId={review.selected_evaluation_id} questionId={question.id} /></details>}
            {review.discussions.filter(d => d.question_id === question.id && d.submission_id === review.selected_submission_id).map((d, i) => <button type="button" key={d.id} className="text-button" onClick={() => onDiscuss(d.id)}>打开题目讨论 {i + 1}{d.purged_at ? '（内容已删除）' : ''}</button>)}
          </article>;
        })}
        {review.result && <div aria-label="整体验证总结" className={`verification-result${review.result.passed ? ' is-passed' : ' is-failed'}`} role="status"><div>
          <h3>整体验证总结</h3><strong>{review.result.passed ? '验证通过' : '还需要补强'}</strong>
          {!review.result.question_feedback && <p className="form-hint">这次记录只有整体反馈，尚无逐题反馈和参考解法。</p>}
          <div className="ai-markdown"><LearningMarkdown>{review.result.feedback}</LearningMarkdown><LearningMarkdown>{review.result.next_step}</LearningMarkdown></div>
        </div></div>}
      </>}
      {review.verification.verification_purged ? <PurgeStatus kind="verification" objectId={id} onRetry={purge} busy={busy} /> : <details className="review-actions"><summary>更多操作</summary><p>彻底删除会清除本次验证内容、关联讨论及受管理副本，无法恢复；完成记录保留。外部副本另列结果。</p><button className="button button--danger" type="button" disabled={busy} onClick={() => void purge()}>彻底删除本次验证内容</button></details>}
    </>}
  </section>;
}
