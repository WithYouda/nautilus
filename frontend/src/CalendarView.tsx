import { ChevronLeft, ChevronRight, FilterX } from "lucide-react";
import { useMemo, useState } from "react";
import type { Task } from "./api";

export default function CalendarView({
  tasks,
  planFilterTitle,
  onClearPlanFilter,
  onSelectTask,
}: {
  tasks: Task[];
  planFilterTitle: string | null;
  onClearPlanFilter: () => void;
  onSelectTask: (taskId: string) => void;
}) {
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const cells = useMemo(() => buildCalendar(month), [month]);
  return (
    <div className="workspace-content calendar-page">
      <section className="page-heading">
        <div>
          <p className="eyebrow">节奏总览</p>
          <h1>月历视图</h1>
          <p>查看任务覆盖日期，点击任务可回到今日驾驶舱开始计时。</p>
        </div>
        <div className="calendar-heading-actions">
          {planFilterTitle && <div className="calendar-plan-filter"><span>计划：{planFilterTitle}</span><button className="icon-button icon-button--small" type="button" onClick={onClearPlanFilter} aria-label="清除计划筛选" title="清除计划筛选"><FilterX size={15} /></button></div>}
          <div className="calendar-controls">
            <button className="icon-button icon-button--bordered" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))} aria-label="上个月"><ChevronLeft size={17} /></button>
            <strong>{new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "long" }).format(month)}</strong>
            <button className="icon-button icon-button--bordered" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))} aria-label="下个月"><ChevronRight size={17} /></button>
          </div>
        </div>
      </section>
      <section className="calendar-grid tool-panel" aria-label="月历">
        <div className="calendar-weekdays">{["一", "二", "三", "四", "五", "六", "日"].map((day) => <span key={day}>{day}</span>)}</div>
        <div className="calendar-cells">
          {cells.map((cell) => <CalendarCell key={cell.date} cell={cell} tasks={tasks} onSelectTask={onSelectTask} />)}
        </div>
      </section>
    </div>
  );
}

type CalendarCellData = { date: string; day: number; currentMonth: boolean };

function CalendarCell({ cell, tasks, onSelectTask }: { cell: CalendarCellData; tasks: Task[]; onSelectTask: (taskId: string) => void }) {
  const dateTasks = tasks.filter((task) => task.start_date <= cell.date && task.due_date >= cell.date);
  const isToday = cell.date === localDateKey(new Date());
  return (
    <div className={`calendar-cell${cell.currentMonth ? "" : " is-muted"}${isToday ? " is-today" : ""}`}>
      <div className="calendar-date"><span>{cell.day}</span>{dateTasks.length > 0 && <small>{dateTasks.length}</small>}</div>
      <div className="calendar-tasks">
        {dateTasks.slice(0, 3).map((task) => <button key={task.id} className={`calendar-task calendar-task--${task.status}`} onClick={() => onSelectTask(task.id)} title={task.title}>{task.title}</button>)}
        {dateTasks.length > 3 && <span className="calendar-more">+{dateTasks.length - 3} 项</span>}
      </div>
    </div>
  );
}

function buildCalendar(month: Date): CalendarCellData[] {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const start = new Date(first);
  start.setDate(start.getDate() - ((first.getDay() + 6) % 7));
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return {
      date: localDateKey(date),
      day: date.getDate(),
      currentMonth: date.getMonth() === month.getMonth(),
    };
  });
}

function localDateKey(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}
