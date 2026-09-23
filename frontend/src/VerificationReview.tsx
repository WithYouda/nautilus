import { useEffect, useState } from 'react';
import QuestionFeedbackContent from './QuestionFeedbackContent';
import LearningMarkdown from './LearningMarkdown';
import { createQuestionDiscussion, getVerificationReview, purgeVerification, type VerificationReview as Review, type LearningVerification } from './api';

export default function VerificationReview({ id, refreshKey, onDiscuss, onPurged, onReadSolution }: {
  id: string; refreshKey?: string; onDiscuss: (id: string) => void;
  onPurged?: (verification: LearningVerification) => void; onReadSolution?: () => void;
}) {
  const [review, setReview] = useState<Review | null>(null);
  const [submission, setSubmission] = useState<string>();
  const [evaluation, setEvaluation] = useState<string>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { setSubmission(undefined); setEvaluation(undefined); }, [id]);
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
    if (!window.confirm(`彻底删除本次验证的题目、全部作答和评估？另有 ${review.purge_discussion_count} 段关联或引用它的题目讨论正文会一并清除。依赖证据失效，完成记录保留，内容不可恢复。`)) return;
    setBusy(true); setError('');
    try {
      const value = await purgeVerification(id);
      setSubmission(undefined); setEvaluation(undefined);
      setReview(await getVerificationReview(id));
      onPurged?.(value);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '删除未完成'); }
    finally { setBusy(false); }
  }
  const questions = review?.verification.challenge.questions?.length ? review.verification.challenge.questions : [{ id: 'material', prompt: '本次材料验证' }];
  return <section className="verification-review" aria-label="验证回看">
    {error && <p role="alert">{error}</p>}
    {!review && !error && <p role="status">正在读取保存的验证…</p>}
    {review && <>
      <p className="form-hint">题目、已提交作答和评估自动保存。继续讨论不会改写原验证结果。</p>
      {review.submissions.length > 0 && <label className="field"><span>查看哪次作答</span><select value={review.selected_submission_id ?? ''} onChange={event => { setEvaluation(undefined); setSubmission(event.target.value); }}>
        {review.submissions.map((s, i) => <option key={s.id} value={s.id}>第 {review.submissions.length - i} 次 · {new Date(s.created_at).toLocaleString()}{s.purged_at ? ' · 内容已删除' : ''}</option>)}
      </select></label>}
      {review.evaluations.length > 1 && <label className="field"><span>查看哪次评估</span><select value={review.selected_evaluation_id ?? ''} onChange={event => setEvaluation(event.target.value)}>
        {review.evaluations.map((e, i) => <option key={e.id} value={e.id}>第 {review.evaluations.length - i} 次评估 · {e.status === 'succeeded' ? '已完成' : e.status === 'running' ? '处理中' : '未完成'}</option>)}
      </select></label>}
      {!review.content ? <p>{review.verification.content_purged || review.submissions.find(s => s.id === review.selected_submission_id)?.purged_at ? '本次作答内容已彻底删除。完成事实仍保留。' : '尚未保存作答。'}</p> : <>
        {questions.map((question, index) => {
          const feedback = review.result?.question_feedback?.find(item => item.question_id === question.id);
          return <article className="verification-question" key={question.id} aria-label={`第 ${index + 1} 题回看`}>
            <div className="review-question-heading"><h3>第 {index + 1} 题</h3><button type="button" className="button button--quiet" disabled={busy} onClick={() => void discuss(question.id)}>讨论这道题</button></div>
            <div className="ai-markdown"><LearningMarkdown>{question.prompt}</LearningMarkdown></div>
            {review.content?.material && <details><summary>本次参考材料</summary><div className="ai-markdown"><LearningMarkdown>{review.content.material}</LearningMarkdown></div></details>}
            <h4>我当时的回答</h4><div className="ai-markdown review-answer"><LearningMarkdown>{review.content?.responses?.[question.id] ?? review.content?.learner_work ?? '没有提交本人作答'}</LearningMarkdown></div>
            {feedback ? <QuestionFeedbackContent feedback={feedback} onReadSolution={onReadSolution} /> : <p className="form-hint">{review.result ? '这次记录未保存逐题反馈，可在讨论中请 AI 重新讲解。' : '本题反馈尚未生成，作答已保存。'}</p>}
            {review.discussions.filter(d => d.question_id === question.id && d.submission_id === review.selected_submission_id).map((d, i) => <button type="button" key={d.id} className="text-button" onClick={() => onDiscuss(d.id)}>打开题目讨论 {i + 1}{d.purged_at ? '（内容已删除）' : ''}</button>)}
          </article>;
        })}
        {review.result && <div aria-label="整体验证总结" className={`verification-result${review.result.passed ? ' is-passed' : ' is-failed'}`} role="status"><div>
          <h3>整体验证总结</h3><strong>{review.result.passed ? '验证通过' : '还需要补强'}</strong>
          {!review.result.question_feedback && <p className="form-hint">这次记录只有整体反馈，尚无逐题反馈和参考解法。</p>}
          <div className="ai-markdown"><LearningMarkdown>{review.result.feedback}</LearningMarkdown><LearningMarkdown>{review.result.next_step}</LearningMarkdown></div>
        </div></div>}
      </>}
      {!review.verification.verification_purged && <details className="review-actions"><summary>更多操作</summary><p>彻底删除会清除本次验证内容及关联讨论，无法恢复；完成记录保留。</p><button className="button button--danger" type="button" disabled={busy} onClick={() => void purge()}>彻底删除本次验证内容</button></details>}
    </>}
  </section>;
}
