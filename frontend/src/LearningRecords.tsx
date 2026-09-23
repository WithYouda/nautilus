import { useEffect, useState } from 'react';
import { listLearningRecords, getLearningRecord, type LearningRecord, type LearningRecordDetail, type LearningRoomBrief } from './api';
import VerificationReview from './VerificationReview';
import QuestionDiscussion from './QuestionDiscussion';

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
  const [verificationId, setVerificationId] = useState<string | null>(query.get('verification'));
  const [discussionId, setDiscussionId] = useState<string | null>(query.get('discussion'));
  const [error, setError] = useState('');
  useEffect(() => { listLearningRecords().then(setItems).catch(reason => setError(reason.message)); }, []);
  useEffect(() => {
    let active = true;
    setRecord(null);
    if (recordId) getLearningRecord(recordId).then(value => { if (active) setRecord(value); }).catch(reason => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [recordId]);
  function discuss(id: string | null) { setDiscussionId(id); setReviewLocation('discussion', id); }
  if (discussionId) return <QuestionDiscussion id={discussionId} onBack={() => discuss(null)} />;
  return <section className="learning-records" aria-label="学习记录">
    <div className="review-question-heading"><h2>学习记录</h2><button className="button button--quiet" type="button" onClick={() => { for (const key of ['record', 'verification', 'discussion']) setReviewLocation(key, null); onClose(); }}>返回开始学习</button></div>
    <p>进行中和已完成的委托都保留在这里。题目、已提交作答和反馈自动保存，无需另点保存。</p>
    {error && <p role="alert">{error}</p>}
    <div className="learning-records-list">{items.map(item => <button type="button" className="verification-panel" key={item.id} aria-pressed={recordId === item.id} onClick={() => { setRecordId(item.id); setVerificationId(null); setReviewLocation('record', item.id); setReviewLocation('verification', null); }}>
      <strong>{item.title}</strong><span>{labels[item.status] ?? '已记录'} · {item.verification_count} 次验证</span><small>{item.goal_title || '独立学习'}{item.plan_title ? ` · ${item.plan_title}` : ''}</small>
    </button>)}</div>
    {!items.length && !error && <p>还没有学习委托记录。</p>}
    {record && <section aria-label="委托历史"><h3>{record.record.title}</h3>
      <p>委托状态：{labels[record.record.status] ?? '已记录'}</p>
      {record.brief && onLearning && <button className="button button--quiet" type="button" onClick={() => { for (const key of ['record', 'verification', 'discussion']) setReviewLocation(key, null); onLearning({ ...record.brief!, history_only: true }); }}>查看原学习对话</button>}
      <div className="record-verification-list">{record.verifications.map((v, i) => <button type="button" className="button button--quiet" key={v.id} aria-pressed={verificationId === v.id} onClick={() => { setVerificationId(v.id); setReviewLocation('verification', v.id); }}>验证 {record.verifications.length - i} · {v.mode === 'ai_challenge' ? 'AI 出题' : '提交材料'} · {v.purged_at ? '内容已删除' : labels[v.status] ?? '已保存'}</button>)}</div>
      {!record.verifications.length && <p>尚未发起验证；原学习记录仍保留。</p>}
    </section>}
    {verificationId && <VerificationReview id={verificationId} onDiscuss={id => discuss(id)} />}
  </section>;
}
