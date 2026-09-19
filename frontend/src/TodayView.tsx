import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { Bot, Check, Circle, Pause, Play, Square } from "lucide-react";
import {
  type Identity,
  type LayoutModule,
  type LayoutModuleId,
  type ManualPlanInput,
  type Task,
  type TimerMode,
  type TimerSnapshot,
  type TodayDashboard,
} from "./api";

const taskTypeLabels: Record<Task["task_type"], string> = {
  study: "学习",
  practice: "练习",
  review: "复习",
  output: "知识产出",
};

const timerLabels: Record<TimerMode, string> = {
  pomodoro_25_5: "25 / 5",
  pomodoro_50_10: "50 / 10",
  custom: "自定义",
  count_up: "普通计时",
};

export default function TodayView({
  dashboard,
  identity,
  selectedTask,
  selectedTaskId,
  timer,
  busy,
  onSelectTask,
  onComplete,
  onTimer,
  onOpenAi,
  onOpenFacts,
  layoutModules,
}: {
  dashboard: TodayDashboard | null;
  identity: Identity | null;
  selectedTask: Task | null;
  selectedTaskId: string | null;
  timer: TimerSnapshot | null;
  busy: boolean;
  onSelectTask: (taskId: string) => void;
  onComplete: (taskId: string) => void;
  onTimer: (
    action: "start" | "pause" | "resume" | "finish",
    config?: Pick<ManualPlanInput, "timer_mode" | "work_minutes" | "break_minutes">,
  ) => void;
  onOpenAi: (taskId: string) => void;
  onOpenFacts: () => void;
  layoutModules: LayoutModule[];
}) {
  const summary = dashboard?.summary;
  return (
    <div className="workspace-content">
      <section className="today-heading">
        <div>
          <p className="eyebrow">今日学习</p>
          <h1>{formatDashboardDate(dashboard?.date)}</h1>
          <p>{identity?.display_name ?? "本地学习者"}，从下一项可执行任务开始。</p>
        </div>
        <div
          className="progress-dial"
          style={{ "--progress": `${summary?.progress ?? 0}%` } as CSSProperties}
          aria-label={`今日完成 ${summary?.progress ?? 0}%`}
        >
          <strong>{summary?.progress ?? 0}%</strong>
          <span>完成</span>
        </div>
      </section>

      {selectedTask && (
        <section className="today-ai-entry" aria-label="当前任务 AI 学习入口">
          <div className="today-ai-entry-copy">
            <p className="eyebrow">当前任务</p>
            <strong>{selectedTask.title}</strong>
            <span>打开只读任务上下文，开始一条普通线性学习对话。</span>
          </div>
          <button
            className="button button--accent button--with-icon"
            onClick={() => onOpenAi(selectedTask.id)}
            aria-label={`当前任务 ${selectedTask.title}：与 AI 学习`}
          >
            <Bot size={16} />与 AI 学习
          </button>
        </section>
      )}

      {!dashboard?.tasks.length && (
        <section className="first-slice-entry" aria-label="首片体验入口">
          <div>
            <p className="eyebrow">FIRST SLICE</p>
            <h2>从一次可验证学习开始</h2>
            <p>创建任务、委托和会话，保存原始产出，并查看证据链与派生状态。</p>
          </div>
          <button className="button button--accent" type="button" onClick={onOpenFacts}>
            开始一次学习
          </button>
        </section>
      )}

      <DashboardModules
        modules={layoutModules}
        dashboard={dashboard}
        selectedTask={selectedTask}
        selectedTaskId={selectedTaskId}
        timer={timer}
        busy={busy}
        onSelectTask={onSelectTask}
        onComplete={onComplete}
        onTimer={onTimer}
        onOpenAi={onOpenAi}
      />
    </div>
  );
}

function DashboardModules({
  modules,
  dashboard,
  selectedTask,
  selectedTaskId,
  timer,
  busy,
  onSelectTask,
  onComplete,
  onTimer,
  onOpenAi,
}: {
  modules: LayoutModule[];
  dashboard: TodayDashboard | null;
  selectedTask: Task | null;
  selectedTaskId: string | null;
  timer: TimerSnapshot | null;
  busy: boolean;
  onSelectTask: (taskId: string) => void;
  onComplete: (taskId: string) => void;
  onTimer: (
    action: "start" | "pause" | "resume" | "finish",
    config?: Pick<ManualPlanInput, "timer_mode" | "work_minutes" | "break_minutes">,
  ) => void;
  onOpenAi: (taskId: string) => void;
}) {
  const visible = modules.filter((module) => module.visible).map((module) => module.id);
  const output: ReactNode[] = [];

  const taskPanel = (
    <TaskPanel
      dashboard={dashboard}
      selectedTaskId={selectedTaskId}
      busy={busy}
      onSelectTask={onSelectTask}
      onComplete={onComplete}
      onOpenAi={onOpenAi}
    />
  );
  const narrowModule = (id: LayoutModuleId) =>
    id === "timer" ? (
      <TimerPanel
        task={selectedTask}
        timer={timer?.task_id === selectedTask?.id ? timer : null}
        busy={busy}
        onAction={onTimer}
      />
    ) : (
      <ContextPanel task={selectedTask} />
    );

  for (let index = 0; index < visible.length; index += 1) {
    const id = visible[index];
    if (id === "summary") {
      output.push(<SummaryStrip key={`summary-${index}`} dashboard={dashboard} timer={timer} />);
      continue;
    }
    if (id === "tasks") {
      const side: LayoutModuleId[] = [];
      let cursor = index + 1;
      while (cursor < visible.length && (visible[cursor] === "timer" || visible[cursor] === "context")) {
        side.push(visible[cursor]);
        cursor += 1;
      }
      output.push(
        <div className={`dashboard-grid${side.length === 0 ? " dashboard-grid--single" : ""}`} key={`tasks-${index}`}>
          {taskPanel}
          {side.length > 0 && (
            <aside className="dashboard-side">
              {side.map((item) => <div className="module-slot" key={item}>{narrowModule(item)}</div>)}
            </aside>
          )}
        </div>,
      );
      index = cursor - 1;
      continue;
    }

    const side: LayoutModuleId[] = [id];
    let cursor = index + 1;
    while (cursor < visible.length && (visible[cursor] === "timer" || visible[cursor] === "context")) {
      side.push(visible[cursor]);
      cursor += 1;
    }
    if (visible[cursor] === "tasks") {
      output.push(
        <div className="dashboard-grid dashboard-grid--reverse" key={`side-${index}`}>
          <aside className="dashboard-side">
            {side.map((item) => <div className="module-slot" key={item}>{narrowModule(item)}</div>)}
          </aside>
          {taskPanel}
        </div>,
      );
      index = cursor;
    } else {
      output.push(
        <div className="narrow-module-grid" key={`side-${index}`}>
          {side.map((item) => <div className="module-slot" key={item}>{narrowModule(item)}</div>)}
        </div>,
      );
      index = cursor - 1;
    }
  }

  return output.length ? (
    <div className="dashboard-module-stream">{output}</div>
  ) : (
    <div className="all-modules-hidden">所有首页模块当前均已隐藏。可从顶部布局设置恢复。</div>
  );
}

function SummaryStrip({ dashboard, timer }: { dashboard: TodayDashboard | null; timer: TimerSnapshot | null }) {
  const summary = dashboard?.summary;
  return (
    <section className="metric-strip" aria-label="今日学习概览">
      <Metric label="任务" value={`${summary?.completed ?? 0} / ${summary?.total ?? 0}`} />
      <Metric label="计划时长" value={formatMinutes(summary?.planned_minutes ?? 0)} />
      <Metric label="已记录" value={formatMinutes(summary?.actual_minutes ?? 0)} />
      <Metric label="当前节奏" value={timer?.status === "running" ? "专注中" : timer?.status === "paused" ? "已暂停" : "待开始"} />
    </section>
  );
}

function TaskPanel({
  dashboard,
  selectedTaskId,
  busy,
  onSelectTask,
  onComplete,
  onOpenAi,
}: {
  dashboard: TodayDashboard | null;
  selectedTaskId: string | null;
  busy: boolean;
  onSelectTask: (taskId: string) => void;
  onComplete: (taskId: string) => void;
  onOpenAi: (taskId: string) => void;
}) {
  return (
    <section className="tool-panel task-panel">
      <header className="tool-heading">
        <div><p className="eyebrow">执行队列</p><h2>今日任务</h2></div>
        <span>{dashboard?.tasks.length ?? 0} 项</span>
      </header>
      {!dashboard?.tasks.length ? (
        <div className="empty-state">
          <h3>今天还没有安排任务</h3>
          <p>从开始学习进入已有计划，或让 AI 帮你整理第一步。</p>
        </div>
      ) : (
        <div className="task-list">
          {dashboard.tasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              selected={task.id === selectedTaskId}
              busy={busy}
              onSelect={() => onSelectTask(task.id)}
              onComplete={() => onComplete(task.id)}
              onOpenAi={() => onOpenAi(task.id)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function TaskRow({ task, selected, busy, onSelect, onComplete, onOpenAi }: { task: Task; selected: boolean; busy: boolean; onSelect: () => void; onComplete: () => void; onOpenAi: () => void }) {
  const time = task.planned_start
    ? new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(task.planned_start))
    : "灵活";
  const CompleteIcon = task.status === "completed" ? Check : Circle;
  return (
    <article className={`task-row${selected ? " is-selected" : ""}${task.status === "completed" ? " is-complete" : ""}`}>
      <button className="task-select" onClick={onSelect} aria-label={`选择任务：${task.title}`}>
        <span className="task-time">{time}</span>
        <span className={`task-type task-type--${task.task_type}`}>{taskTypeLabels[task.task_type]}</span>
        <span className="task-copy"><strong>{task.title}</strong><small>{task.subject_title} / {task.topic_title}</small></span>
        <span className="task-duration">{task.estimate_minutes} 分钟</span>
      </button>
      <div className="task-row-actions">
        <button className="task-ai-button" onClick={onOpenAi} title="与 AI 学习" aria-label={`与 AI 学习：${task.title}`}><Bot size={18} strokeWidth={1.8} /></button>
        <button
          className="complete-button"
          onClick={onComplete}
          disabled={busy || task.status === "canceled"}
          title={task.status === "completed" ? "标记为未完成" : "完成任务"}
          aria-label={task.status === "completed" ? `撤销完成：${task.title}` : `完成任务：${task.title}`}
        >
          <CompleteIcon size={20} strokeWidth={1.8} />
        </button>
      </div>
    </article>
  );
}

function TimerPanel({ task, timer, busy, onAction }: { task: Task | null; timer: TimerSnapshot | null; busy: boolean; onAction: (action: "start" | "pause" | "resume" | "finish", config?: Pick<ManualPlanInput, "timer_mode" | "work_minutes" | "break_minutes">) => void }) {
  const [mode, setMode] = useState<TimerMode>(task?.timer_mode ?? "pomodoro_50_10");
  const [workMinutes, setWorkMinutes] = useState(task?.work_minutes ?? 50);
  const [breakMinutes, setBreakMinutes] = useState(task?.break_minutes ?? 10);

  useEffect(() => {
    setMode(task?.timer_mode ?? "pomodoro_50_10");
    setWorkMinutes(task?.work_minutes ?? 50);
    setBreakMinutes(task?.break_minutes ?? 10);
  }, [task?.id, task?.timer_mode, task?.work_minutes, task?.break_minutes]);

  function chooseMode(next: TimerMode) {
    setMode(next);
    if (next === "pomodoro_25_5") { setWorkMinutes(25); setBreakMinutes(5); }
    if (next === "pomodoro_50_10") { setWorkMinutes(50); setBreakMinutes(10); }
    if (next === "count_up") { setWorkMinutes(60); setBreakMinutes(0); }
  }

  const seconds = timer ? timer.remaining_seconds ?? timer.elapsed_seconds : workMinutes * 60;
  return (
    <section className="tool-panel timer-panel">
      <header className="tool-heading">
        <div><p className="eyebrow">专注计时</p><h2>{task ? "当前任务" : "等待任务"}</h2></div>
        <span>{timer ? timerLabels[timer.timer_mode] : timerLabels[mode]}</span>
      </header>
      {task ? (
        <>
          <div className="timer-task"><span className={`task-type task-type--${task.task_type}`}>{taskTypeLabels[task.task_type]}</span><strong>{task.title}</strong></div>
          <div className={`timer-readout${timer?.status === "running" ? " is-running" : ""}${timer?.phase === "break" ? " is-break" : ""}`}>
            <span>{formatSeconds(seconds)}</span>
            <small>{timer?.remaining_seconds === null ? "累计专注" : timer?.phase === "break" ? "本轮休息剩余" : timer ? "本轮专注剩余" : "计划专注"}</small>
          </div>
          {!timer && (
            <>
              <div className="segmented-control" aria-label="计时方式">
                {(["pomodoro_25_5", "pomodoro_50_10", "custom", "count_up"] as TimerMode[]).map((item) => (
                  <button key={item} className={mode === item ? "is-active" : ""} onClick={() => chooseMode(item)}>{timerLabels[item]}</button>
                ))}
              </div>
              {mode === "custom" && (
                <div className="timer-custom">
                  <label><span>专注</span><input type="number" min="1" max="240" value={workMinutes} onChange={(event) => setWorkMinutes(Number(event.target.value))} /></label>
                  <label><span>休息</span><input type="number" min="0" max="120" value={breakMinutes} onChange={(event) => setBreakMinutes(Number(event.target.value))} /></label>
                </div>
              )}
            </>
          )}
          <div className="timer-actions">
            {!timer ? (
              <button className="button button--accent button--with-icon" disabled={busy || task.status === "completed"} onClick={() => onAction("start", { timer_mode: mode, work_minutes: workMinutes, break_minutes: breakMinutes })}>
                <Play size={16} fill="currentColor" />开始专注
              </button>
            ) : (
              <>
                <button className="button button--dark button--with-icon timer-primary" disabled={busy} onClick={() => onAction(timer.status === "running" ? "pause" : "resume")}>
                  {timer.status === "running" ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" />}
                  {timer.status === "running" ? "暂停" : "继续"}
                </button>
                <button className="icon-button icon-button--bordered" disabled={busy} onClick={() => onAction("finish")} title="结束计时" aria-label="结束计时">
                  <Square size={16} fill="currentColor" />
                </button>
              </>
            )}
          </div>
        </>
      ) : (
        <div className="compact-empty">从今日任务或计划编辑器中选择一项任务。</div>
      )}
    </section>
  );
}

function ContextPanel({ task }: { task: Task | null }) {
  return (
    <section className="tool-panel context-panel">
      <header className="tool-heading"><div><p className="eyebrow">学习路径</p><h2>任务位置</h2></div></header>
      {task ? (
        <ol className="context-route">
          <li><span>目标</span><strong>{task.goal_title}</strong></li>
          <li><span>科目</span><strong>{task.subject_title}</strong></li>
          <li><span>主题</span><strong>{task.topic_title}</strong></li>
          <li className="is-current"><span>任务</span><strong>{task.title}</strong></li>
        </ol>
      ) : <div className="compact-empty">暂无任务上下文。</div>}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

function formatDashboardDate(value?: string) {
  if (!value) return "今日学习";
  return new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "long" }).format(new Date(`${value}T00:00:00`));
}

function formatMinutes(value: number) {
  if (value < 60) return `${value} 分钟`;
  const hours = Math.floor(value / 60);
  const minutes = value % 60;
  return minutes ? `${hours} 小时 ${minutes} 分` : `${hours} 小时`;
}

function formatSeconds(value: number) {
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const seconds = value % 60;
  return hours > 0
    ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}
