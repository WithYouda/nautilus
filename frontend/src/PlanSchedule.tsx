import { ArrowLeft, ArrowRight, CalendarDays } from "lucide-react";
import type { PlanScheduleItem, Task } from "./api";
import { PlanTaskRow } from "./PlanOverview";

export default function PlanSchedule({
  tasks,
  busyTaskId,
  onOpenTask,
  onToggleCompletion,
  onOpenTaskAi,
  onReschedule,
  onOpenCalendar,
}: {
  tasks: PlanScheduleItem[];
  busyTaskId: string | null;
  onOpenTask: (taskId: string) => void;
  onToggleCompletion: (task: Task) => void;
  onOpenTaskAi: (taskId: string) => void;
  onReschedule: (taskId: string, days: number) => void;
  onOpenCalendar: () => void;
}) {
  const groups = groupByDate(tasks);
  return <div className="plan-schedule" aria-label="计划排期">
    <div className="plan-schedule-toolbar"><div><span className="eyebrow">PLAN SCHEDULE</span><h3>计划排期</h3></div><button className="button button--quiet button--with-icon" type="button" onClick={onOpenCalendar}><CalendarDays size={15} />在学习日历中查看</button></div>
    {groups.length ? <div className="schedule-groups">
      {groups.map(([date, items]) => <section className="schedule-day" key={date}>
        <header><time dateTime={date}>{formatDateHeading(date)}</time><span>{items.length} 项</span></header>
        <div className="plan-task-list">
          {items.map((task) => <PlanTaskRow
            key={task.id}
            task={task}
            busy={busyTaskId === task.id}
            onOpenTask={onOpenTask}
            onToggleCompletion={onToggleCompletion}
            onOpenTaskAi={onOpenTaskAi}
            extraActions={<>
              <button className="icon-button icon-button--small" type="button" disabled={busyTaskId === task.id || task.status === "completed" || task.status === "canceled"} onClick={() => onReschedule(task.id, -1)} aria-label={`提前一天：${task.title}`} title="提前一天"><ArrowLeft size={14} /></button>
              <button className="icon-button icon-button--small" type="button" disabled={busyTaskId === task.id || task.status === "completed" || task.status === "canceled"} onClick={() => onReschedule(task.id, 1)} aria-label={`延期一天：${task.title}`} title="延期一天"><ArrowRight size={14} /></button>
            </>}
          />)}
        </div>
      </section>)}
    </div> : <div className="plan-inline-empty"><p>这个计划还没有任务排期。</p></div>}
  </div>;
}

function groupByDate(tasks: PlanScheduleItem[]) {
  const groups = new Map<string, PlanScheduleItem[]>();
  for (const task of tasks) {
    const key = task.start_date;
    groups.set(key, [...(groups.get(key) ?? []), task]);
  }
  return [...groups.entries()].sort(([first], [second]) => first.localeCompare(second));
}

function formatDateHeading(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "short" }).format(new Date(`${value}T00:00:00`));
}
