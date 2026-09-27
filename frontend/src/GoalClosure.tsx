import { useEffect, useRef, useState } from 'react';
import DialogPortal from './DialogPortal';
import { ApiError, changeGoalStatus, getGoalReview, type GoalReview, type GoalStatus } from './api';

const labels: Record<GoalStatus, string> = {
  hypothesis: '进行中', active: '进行中', paused: '已暂停', completed: '已达成', archived: '已停止追踪',
};

export function goalIsClosed(status: GoalStatus): boolean {
  return status === 'paused' || status === 'completed' || status === 'archived';
}

export function goalStatusLabel(status: GoalStatus): string { return labels[status]; }

export default function GoalClosure({ goalId, onClose, onChanged, onOpenRecord }: {
  goalId: string; onClose: () => void; onChanged: () => Promise<void>; onOpenRecord: (delegationId: string) => void;
}) {
  const [review, setReview] = useState<GoalReview | null>(null);
  const [choice, setChoice] = useState<GoalStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [error, setError] = useState('');
  const attempt = useRef<{ status: GoalStatus; key: string } | null>(null);
  const loadSequence = useRef(0);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; loadSequence.current += 1; }; }, []);
  async function load() {
    const sequence = ++loadSequence.current;
    setLoading(true); setError('');
    try {
      const next = await getGoalReview(goalId);
      if (sequence !== loadSequence.current) return;
      setReview(next); setChoice(null); setStale(false); attempt.current = null;
    } catch (reason) { if (sequence === loadSequence.current) setError(reason instanceof Error ? reason.message : '无法读取目标状态，请重试。'); }
    finally { if (sequence === loadSequence.current) setLoading(false); }
  }
  useEffect(() => { void load(); }, [goalId]);
  async function confirm() {
    if (!review || !choice || busy || stale) return;
    setBusy(true); setError('');
    if (attempt.current?.status !== choice) attempt.current = { status: choice, key: crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}` };
    try {
      await changeGoalStatus(goalId, choice, review.goal.version, review.review_key, attempt.current.key);
      if (!mounted.current) return;
      await onChanged();
      if (!mounted.current) return;
      attempt.current = null;
      onClose();
    } catch (reason) {
      if (!mounted.current) return;
      if (reason instanceof ApiError && reason.status === 409) {
        setStale(true);
        setError('目标或关联任务已变化。请刷新目标信息后重新选择。');
      } else setError(reason instanceof Error ? reason.message : '状态未确认，请用同一操作重试。');
    } finally { setBusy(false); }
  }
  const closed = review ? goalIsClosed(review.goal.status) : false;
  const choices: Array<{ status: GoalStatus; label: string; detail: string }> = closed
    ? [{ status: 'active', label: '重新开启', detail: '恢复这个目标，后续可继续添加任务或开始学习。现有任务不会自动开始。' }]
    : [
      { status: 'completed', label: '由我确认目标已达成', detail: '确认你已达到目标；未完成的任务仍保留原状态。' },
      { status: 'paused', label: '暂停目标', detail: '暂停这个目标，之后可以重新开启。' },
      { status: 'archived', label: '停止追踪', detail: '不再围绕这个目标安排学习。记录保留，之后仍可重新开启。' },
    ];
  return <DialogPortal><div className="dialog-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <section className="goal-closure-dialog" role="dialog" aria-modal="true" aria-labelledby="goal-closure-title">
      <header className="dialog-header"><div><p className="eyebrow">目标检查</p><h2 id="goal-closure-title">调整目标状态</h2></div><button className="text-button" onClick={onClose} disabled={busy} aria-label="关闭">关闭</button></header>
      <div className="goal-closure-dialog__body">
        {loading && <p role="status">正在检查关联计划和任务…</p>}
        {error && <p className="workspace-alert" role="alert">{error}</p>}
        {(!review || stale) && !loading && <button className="button button--quiet" onClick={() => void load()} disabled={busy}>刷新目标信息</button>}
        {review && !stale && <>
          <p><strong>{review.goal.title}</strong> <span className="learning-state-label">{labels[review.goal.status]}</span></p>
          <p>{review.plans.length} 个关联计划 · {review.counts.total_tasks} 项任务，其中 {review.counts.completed_tasks} 项已完成、{review.counts.open_tasks} 项未完成。</p>
          {review.counts.running_sessions > 0 && !closed && <p className="workspace-alert">当前有 {review.counts.running_sessions} 个学习会话正在运行。确认已达成、暂停或停止追踪后，当前学习会话会结束，已保存记录仍可查看。</p>}
          <details><summary>查看关联计划和任务</summary>
            {review.plans.map(plan => <div key={plan.id} className="goal-closure-dialog__plan"><strong>{plan.title}</strong><ul>{review.tasks.filter(task => task.plan_id === plan.id).map(task => <li key={task.id}>{task.title} · {task.status === 'completed' ? '已完成' : '未完成'}{task.delegations.length > 0 && <button className="text-button" onClick={() => { onClose(); onOpenRecord(task.delegations[0].id); }}>查看记录</button>}</li>)}</ul></div>)}
          </details>
          <p>改变目标状态不会把未完成任务标成完成，也不会删除已有记录和复习安排。确认目标已达成，表示你认为达到自己的要求，不代表系统已证明你掌握了。重新开启前，这个目标不再安排新的学习，也不再出现在首页的继续学习建议中。</p>
          <fieldset className="goal-closure-dialog__choices"><legend>{closed ? '是否继续学习这个目标？' : '你想怎样安排这个目标？'}</legend>{choices.map(option => <label key={option.status}><input type="radio" name="goal-closure-choice" checked={choice === option.status} onChange={() => { setChoice(option.status); attempt.current = null; }} disabled={busy} /><span><strong>{option.label}</strong><small>{option.detail}</small></span></label>)}</fieldset>
          {review.history.length > 0 && <details><summary>查看状态历史</summary><ol>{review.history.map(item => <li key={item.id}>{new Date(item.occurred_at).toLocaleString()} · {labels[item.previous_status]} → {labels[item.status]}</li>)}</ol></details>}
        </>}
      </div>
      <div className="dialog-actions goal-closure-dialog__actions"><button className="button button--quiet" onClick={onClose} disabled={busy}>取消</button><button className="button button--accent" onClick={() => void confirm()} disabled={!choice || loading || busy || stale}>{busy ? '正在保存…' : choice === 'active' ? '确认重新开启' : '确认修改'}</button></div>
    </section>
  </div></DialogPortal>;
}
