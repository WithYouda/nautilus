import { Bot, CalendarClock, Check, Circle, Clock3 } from "lucide-react";
import type { PlanDetail, PlanScheduleItem, Task } from "./api";
import { statusLabel, taskTypeLabel } from "./PlanEditor";

export default function PlanOverview({
  plan,
  schedule,
  busyTaskId,
  onOpenTask,
  onToggleCompletion,
  onOpenTaskAi,
}: {
  plan: PlanDetail;
  schedule: PlanScheduleItem[];
  busyTaskId: string | null;
  onOpenTask: (taskId: string) => void;
  onToggleCompletion: (task: Task) => void;
  onOpenTaskAi: (taskId: string) => void;
}) {
  const recent = schedule
    .filter((task) => task.status !== "canceled")
    .sort(taskPriority)
    .slice(0, 6);
  const upcomingThisWeek = recent.filter((task) => {
    const days = Math.ceil((new Date(`${task.due_date}T23:59:59`).getTime() - Date.now()) / 86_400_000);
    return task.status !== "completed" && days >= 0 && days <= 7;
  }).length;

  return (
    <div className="plan-overview" aria-label="计划概览">
      <section className="plan-metric-strip" aria-label="计划指标">
        <Metric label="总体完成" value={`${plan.summary.progress}%`} detail={`${plan.summary.completed_task_count} / ${plan.summary.task_count} 项任务`} />
        <Metric label="本周待完成" value={String(upcomingThisWeek)} detail="按当前截止日期" />
        <Metric label="计划学习量" value={formatMinutes(plan.summary.estimate_minutes)} detail={`已记录 ${formatMinutes(plan.summary.actual_minutes)}`} />
      </section>

      <section className="plan-section-band">
        <header><div><span className="eyebrow">SUBJECT PROGRESS</span><h3>科目进度</h3></div><small>{plan.subjects.length} 个科目</small></header>
        {plan.subjects.length ? <div className="subject-progress-list">
          {plan.subjects.map((subject) => <article className="subject-progress-row" key={subject.id}>
            <div className="subject-progress-copy"><strong>{subject.title}</strong><span>{subject.completed_task_count ?? 0} / {subject.task_count ?? 0} 项任务</span></div>
            <div className="subject-progress-track" aria-label={`${subject.title}进度 ${subject.progress ?? 0}%`}><span style={{ width: `${subject.progress ?? 0}%` }} /></div>
            <b>{subject.progress ?? 0}%</b>
          </article>)}
        </div> : <EmptyState text="这个计划还没有科目。" />}
      </section>

      <section className="plan-section-band plan-recent-section">
        <header><div><span className="eyebrow">UPCOMING TASKS</span><h3>近期任务</h3></div><small>科目进度下方独立排列</small></header>
        {recent.length ? <div className="plan-task-list">
          {recent.map((task) => <PlanTaskRow key={task.id} task={task} busy={busyTaskId === task.id} onOpenTask={onOpenTask} onToggleCompletion={onToggleCompletion} onOpenTaskAi={onOpenTaskAi} />)}
        </div> : <EmptyState text="暂无可显示的任务。" />}
      </section>
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="plan-metric"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>;
}

export function PlanTaskRow({ task, busy, onOpenTask, onToggleCompletion, onOpenTaskAi, extraActions }: { task: PlanScheduleItem | Task; busy: boolean; onOpenTask: (taskId: string) => void; onToggleCompletion: (task: Task) => void; onOpenTaskAi: (taskId: string) => void; extraActions?: React.ReactNode }) {
  const complete = task.status === "completed";
  const CompleteIcon = complete ? Check : Circle;
  return <article className={`plan-task-row${complete ? " is-complete" : ""}`}>
    <button className="plan-task-check" type="button" disabled={busy || task.status === "canceled"} onClick={() => onToggleCompletion(task)} aria-label={complete ? `撤销完成：${task.title}` : `完成任务：${task.title}`} title={complete ? "标记为未完成" : "标记完成"}><CompleteIcon size={17} /></button>
    <button className="plan-task-main" type="button" onClick={() => onOpenTask(task.id)}>
      <strong>{task.title}</strong>
      <span>{[task.subject_title, task.topic_title, taskTypeLabel(task.task_type)].filter(Boolean).join(" / ")}</span>
    </button>
    <div className="plan-task-meta"><span><CalendarClock size={13} />{formatDate(task.due_date)}</span><span><Clock3 size={13} />{task.estimate_minutes} 分钟</span><small>{statusLabel(task.status)}</small></div>
    <div className="plan-task-actions">{extraActions}<button className="icon-button icon-button--small" type="button" onClick={() => onOpenTaskAi(task.id)} aria-label={`任务 AI：${task.title}`} title="任务 AI"><Bot size={15} /></button></div>
  </article>;
}

function EmptyState({ text }: { text: string }) {
  return <div className="plan-inline-empty"><p>{text}</p></div>;
}

function taskPriority(first: PlanScheduleItem, second: PlanScheduleItem) {
  const state = (task: PlanScheduleItem) => task.status === "in_progress" ? 0 : task.status === "pending" ? 1 : 2;
  return state(first) - state(second) || first.due_date.localeCompare(second.due_date) || first.title.localeCompare(second.title);
}

function formatMinutes(minutes: number) {
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours} 小时 ${remainder} 分` : `${hours} 小时`;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(new Date(`${value}T00:00:00`));
}
