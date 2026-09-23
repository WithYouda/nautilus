import { useEffect, useState } from 'react';
import { chooseReturnReview, getLearningRoom, getLearningState, getReturnReview, type LearningRoomBrief, type LearningState } from './api';
import LearningPageHeader from './LearningPageHeader';

export default function LearningPlans({ onCreate, onOpenRecord, onLearning }: {
  onCreate: (planId?: string) => void; onOpenRecord: (delegationId: string) => void; onLearning: (brief: LearningRoomBrief) => void;
}) {
  const [state, setState] = useState<LearningState | null>(null);
  const [planId, setPlanId] = useState<string | null>(() => new URLSearchParams(window.location.search).get('plan'));
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { getLearningState().then(setState).catch(reason => setError(reason.message)); }, []);
  const plans = state?.plans ?? [];
  const selected = plans.find(plan => plan.id === planId) ?? (planId ? null : plans[0]);
  const goal = state?.goals.find(item => item.id === selected?.goal_id);
  const taskIds = new Set(state?.action_links.filter(link => link.plan_id === selected?.id).map(link => link.action_id));
  const tasks = state?.actions.filter(action => taskIds.has(action.id)).sort((a, b) => a.created_at.localeCompare(b.created_at)) ?? [];
  async function continueTask(delegationId: string) {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const card = await getReturnReview();
      if (!card) throw new Error('任务状态已改变，请刷新页面。');
      const result = await chooseReturnReview(card.id, 'choose_other', `${card.id}:plan:${delegationId}`, delegationId);
      if (!result.session_id) throw new Error('暂时无法打开这项任务，请刷新后重试。');
      const room = await getLearningRoom(result.session_id);
      onLearning({ ...room.brief, continuity_review_id: card.id });
    } catch (reason) { setError(reason instanceof Error ? reason.message : '无法继续学习'); }
    finally { setBusy(false); }
  }
  function select(id: string) {
    setPlanId(id);
    const url = new URL(window.location.href); url.searchParams.set('plan', id); window.history.replaceState(null, '', url);
  }
  return <section className="learning-plans learning-page" aria-label="学习计划">
    <LearningPageHeader title="学习计划" description="目标是你想学会什么，计划把它拆成可以逐步完成的任务。">
      <button className="button button--accent" onClick={() => onCreate()}>创建</button>
    </LearningPageHeader>
    {error && <p className="workspace-alert" role="alert">{error}</p>}
    {!state && !error && <p role="status">正在加载计划…</p>}
    {state && !plans.length && <div className="learning-empty"><h2>从一个目标开始</h2><p>确认第一项学习任务后，目标、计划和后续记录都会显示在这里。</p><button className="button button--quiet" onClick={() => onCreate()}>创建学习计划</button></div>}
    {!!plans.length && <div className="learning-plans__layout">
      <nav className="learning-plans__list" aria-label="计划列表">{plans.map(plan => {
        const ids = new Set(state!.action_links.filter(link => link.plan_id === plan.id).map(link => link.action_id));
        const actions = state!.actions.filter(action => ids.has(action.id));
        return <button key={plan.id} aria-pressed={selected?.id === plan.id} onClick={() => select(plan.id)}><strong>{plan.title}</strong><span>{state!.goals.find(item => item.id === plan.goal_id)?.title}</span><small>{actions.filter(action => action.status === 'completed').length} / {actions.length} 项任务已完成</small></button>;
      })}</nav>
      {selected ? <section className="learning-plan-detail" aria-label="计划详情">
        <header><p className="eyebrow">学习目标</p><h2>{goal?.title || selected.title}</h2>{goal?.description && <p>{goal.description}</p>}<p className="learning-plan-detail__route">{selected.title}</p></header>
        <div className="learning-plan-detail__heading"><h3>学习任务</h3>{selected.status === 'active' && <button className="button button--accent" onClick={() => onCreate(selected.id)}>添加下一步</button>}</div>
        {tasks.map((task, index) => {
          const delegations = state!.delegations.filter(item => item.action_id === task.id);
          return <article className="learning-plan-task" key={task.id}><div className="learning-plan-task__title"><span className="learning-plan-task__number">{String(index + 1).padStart(2, '0')}</span><h4>{task.title}</h4><span className="learning-state-label">{task.status === 'completed' ? '已完成' : delegations.some(item => item.status === 'active') ? '正在学习' : '已保存'}</span></div>
            {delegations.map(delegation => <div className="learning-plan-task__body" key={delegation.id}><p>{delegation.behavior}</p><div className="learning-action-row">{task.status === 'open' && ['ready', 'active'].includes(delegation.status) && <button className="button button--quiet" disabled={busy} onClick={() => void continueTask(delegation.id)}>{delegation.status === 'ready' ? '开始学习' : '继续学习'}</button>}<button className="text-button" onClick={() => onOpenRecord(delegation.id)}>查看记录</button></div></div>)}
          </article>;
        })}
        {!tasks.length && <p>还没有任务，添加下一步开始学习。</p>}
      </section> : <p>这个计划不存在或当前不可查看，请从左侧重新选择。</p>}
    </div>}
  </section>;
}
