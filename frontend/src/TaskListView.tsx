import { useMemo, useState } from "react";
import { CalendarClock, Check, Circle, Search, SearchX } from "lucide-react";
import type { ScheduleMode, Task, TaskType } from "./api";

const taskTypeLabels: Record<TaskType, string> = {
  study: "学习",
  practice: "练习",
  review: "复习",
  output: "知识产出",
};
const statusLabels: Record<Task["status"], string> = {
  pending: "待开始",
  in_progress: "进行中",
  completed: "已完成",
  canceled: "已取消",
};
const scheduleLabels: Record<ScheduleMode, string> = {
  fixed: "固定日程",
  flexible: "灵活进度",
};

export default function TaskListView({
  tasks,
  busy,
  onSelectTask,
  onComplete,
  onReschedule,
}: {
  tasks: Task[];
  busy: boolean;
  onSelectTask: (taskId: string) => void;
  onComplete: (taskId: string) => void;
  onReschedule: (taskId: string, days: number) => void;
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<Task["status"] | "">("");
  const [taskType, setTaskType] = useState<TaskType | "">("");
  const [scheduleMode, setScheduleMode] = useState<ScheduleMode | "">("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const visibleTasks = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return tasks.filter((task) => {
      const haystack = [task.title, task.goal_title, task.subject_title, task.topic_title]
        .join(" ")
        .toLowerCase();
      return (
        (!normalized || haystack.includes(normalized)) &&
        (!status || task.status === status) &&
        (!taskType || task.task_type === taskType) &&
        (!scheduleMode || task.schedule_mode === scheduleMode) &&
        (!startDate || task.due_date >= startDate) &&
        (!endDate || task.start_date <= endDate)
      );
    });
  }, [endDate, query, scheduleMode, startDate, status, taskType, tasks]);

  return (
    <div className="workspace-content task-list-page">
      <section className="page-heading">
        <div>
          <p className="eyebrow">执行清单</p>
          <h1>独立任务列表</h1>
          <p>按状态、类型和排期快速定位下一项任务。</p>
        </div>
        <span className="page-count">{visibleTasks.length} / {tasks.length} 项</span>
      </section>
      <section className="task-filters tool-panel" aria-label="任务筛选">
        <label className="task-search">
          <Search size={16} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索任务、目标、科目或主题"
          />
        </label>
        <select value={status} onChange={(event) => setStatus(event.target.value as Task["status"] | "")} aria-label="任务状态">
          <option value="">全部状态</option>
          {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <select value={taskType} onChange={(event) => setTaskType(event.target.value as TaskType | "")} aria-label="任务类型">
          <option value="">全部类型</option>
          {Object.entries(taskTypeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <select value={scheduleMode} onChange={(event) => setScheduleMode(event.target.value as ScheduleMode | "")} aria-label="排期方式">
          <option value="">全部排期</option>
          {Object.entries(scheduleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} aria-label="最早截止日期" />
        <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} aria-label="最晚开始日期" />
      </section>
      <section className="tool-panel task-table-panel">
        <header className="tool-heading">
          <div><p className="eyebrow">任务队列</p><h2>全部任务</h2></div>
          <span>{visibleTasks.length} 项</span>
        </header>
        {visibleTasks.length ? (
          <div className="task-table">
            {visibleTasks.map((task) => (
              <TaskTableRow
                key={task.id}
                task={task}
                busy={busy}
                onSelect={onSelectTask}
                onComplete={onComplete}
                onReschedule={onReschedule}
              />
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <SearchX size={28} />
            <h3>没有匹配任务</h3>
            <p>调整筛选条件，或先回到计划视图创建可执行任务。</p>
          </div>
        )}
      </section>
    </div>
  );
}

function TaskTableRow({
  task,
  busy,
  onSelect,
  onComplete,
  onReschedule,
}: {
  task: Task;
  busy: boolean;
  onSelect: (id: string) => void;
  onComplete: (id: string) => void;
  onReschedule: (id: string, days: number) => void;
}) {
  const [days, setDays] = useState(1);
  const CompleteIcon = task.status === "completed" ? Check : Circle;
  return (
    <article className={`task-table-row${task.status === "completed" ? " is-complete" : ""}`}>
      <button className="task-table-main" onClick={() => onSelect(task.id)}>
        <span className={`task-type task-type--${task.task_type}`}>{taskTypeLabels[task.task_type]}</span>
        <span className="task-table-copy">
          <strong>{task.title}</strong>
          <small>{task.goal_title} · {task.subject_title} · {task.topic_title}</small>
        </span>
        <span className="task-table-date">{formatRange(task.start_date, task.due_date)}</span>
      </button>
      <div className="task-table-meta">
        <span className={`status-chip status-chip--${task.status}`}>{statusLabels[task.status]}</span>
        <span>{task.estimate_minutes} 分钟</span>
        {task.overdue && <span className="overdue-label">逾期</span>}
      </div>
      <div className="task-table-actions">
        <div className="reschedule-control">
          <CalendarClock size={15} />
          <input type="number" min="-365" max="365" value={days} onChange={(event) => setDays(Number(event.target.value))} aria-label={`调整 ${task.title} 的天数`} />
          <span>天</span>
          <button className="button button--quiet button--compact" disabled={busy || task.status === "completed" || !days} onClick={() => onReschedule(task.id, days)}>重排</button>
        </div>
        <button className="icon-button icon-button--bordered" disabled={busy || task.status === "canceled"} onClick={() => onComplete(task.id)} aria-label={task.status === "completed" ? `撤销完成：${task.title}` : `完成任务：${task.title}`} title={task.status === "completed" ? "标记为未完成" : "完成任务"}>
          <CompleteIcon size={17} />
        </button>
      </div>
    </article>
  );
}

function formatRange(start: string, end: string) {
  return start === end ? formatDate(start) : `${formatDate(start)} – ${formatDate(end)}`;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric" }).format(new Date(`${value}T00:00:00`));
}
