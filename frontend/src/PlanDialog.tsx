import { FormEvent, useState } from "react";
import { X } from "lucide-react";
import {
  createManualPlan,
  type ManualPlanInput,
  type Plan,
  type ScheduleMode,
  type TaskType,
  type TimerMode,
} from "./api";
import DialogPortal from "./DialogPortal";

type Props = {
  open: boolean;
  onClose: () => void;
  onCreated: (plan: Plan) => void;
};

function localDate(offsetDays = 0) {
  const value = new Date();
  value.setDate(value.getDate() + offsetDays);
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

const timerPresets: Record<TimerMode, { work: number; rest: number }> = {
  pomodoro_25_5: { work: 25, rest: 5 },
  pomodoro_50_10: { work: 50, rest: 10 },
  custom: { work: 40, rest: 10 },
  count_up: { work: 60, rest: 0 },
};

export default function PlanDialog({ open, onClose, onCreated }: Props) {
  const [goalTitle, setGoalTitle] = useState("");
  const [description, setDescription] = useState("");
  const [startDate, setStartDate] = useState(localDate());
  const [endDate, setEndDate] = useState(localDate(30));
  const [subjectTitle, setSubjectTitle] = useState("");
  const [topicTitle, setTopicTitle] = useState("");
  const [taskTitle, setTaskTitle] = useState("");
  const [taskType, setTaskType] = useState<TaskType>("study");
  const [scheduleMode, setScheduleMode] = useState<ScheduleMode>("flexible");
  const [taskStartDate, setTaskStartDate] = useState(localDate());
  const [taskDueDate, setTaskDueDate] = useState(localDate());
  const [plannedStart, setPlannedStart] = useState("");
  const [plannedEnd, setPlannedEnd] = useState("");
  const [estimateMinutes, setEstimateMinutes] = useState(50);
  const [timerMode, setTimerMode] = useState<TimerMode>("pomodoro_50_10");
  const [workMinutes, setWorkMinutes] = useState(50);
  const [breakMinutes, setBreakMinutes] = useState(10);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!open) return null;

  function selectTimerMode(mode: TimerMode) {
    setTimerMode(mode);
    setWorkMinutes(timerPresets[mode].work);
    setBreakMinutes(timerPresets[mode].rest);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    const payload: ManualPlanInput = {
      goal_title: goalTitle.trim(),
      description: description.trim(),
      start_date: startDate,
      end_date: endDate,
      subject_title: subjectTitle.trim(),
      topic_title: topicTitle.trim(),
      task_title: taskTitle.trim(),
      task_type: taskType,
      schedule_mode: scheduleMode,
      task_start_date: taskStartDate,
      task_due_date: taskDueDate,
      planned_start:
        scheduleMode === "fixed" && plannedStart
          ? new Date(plannedStart).toISOString()
          : null,
      planned_end:
        scheduleMode === "fixed" && plannedEnd
          ? new Date(plannedEnd).toISOString()
          : null,
      estimate_minutes: estimateMinutes,
      timer_mode: timerMode,
      work_minutes: workMinutes,
      break_minutes: breakMinutes,
    };
    try {
      const plan = await createManualPlan(payload);
      onCreated(plan);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "计划创建失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <DialogPortal>
      <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
        <section
        className="plan-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="plan-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="dialog-header">
          <div>
            <p className="eyebrow">手动创建</p>
            <h2 id="plan-dialog-title">建立一条可执行学习路线</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} title="关闭" aria-label="关闭">
            <X size={18} />
          </button>
        </header>

        <form className="plan-form" onSubmit={handleSubmit}>
          <fieldset>
            <legend>学习目标</legend>
            <div className="field-grid field-grid--two">
              <label className="field field--wide">
                <span>目标名称</span>
                <input value={goalTitle} onChange={(event) => setGoalTitle(event.target.value)} required maxLength={120} />
              </label>
              <label className="field field--wide">
                <span>目标说明</span>
                <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={2} maxLength={1000} />
              </label>
              <label className="field">
                <span>开始日期</span>
                <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} required />
              </label>
              <label className="field">
                <span>结束日期</span>
                <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} required />
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend>科目与主题</legend>
            <div className="field-grid field-grid--two">
              <label className="field">
                <span>科目 / 领域</span>
                <input value={subjectTitle} onChange={(event) => setSubjectTitle(event.target.value)} required maxLength={120} />
              </label>
              <label className="field">
                <span>章节 / 主题</span>
                <input value={topicTitle} onChange={(event) => setTopicTitle(event.target.value)} required maxLength={120} />
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend>首个可执行任务</legend>
            <div className="field-grid field-grid--two">
              <label className="field field--wide">
                <span>任务名称</span>
                <input value={taskTitle} onChange={(event) => setTaskTitle(event.target.value)} required maxLength={200} />
              </label>
              <label className="field">
                <span>任务类型</span>
                <select value={taskType} onChange={(event) => setTaskType(event.target.value as TaskType)}>
                  <option value="study">学习</option>
                  <option value="practice">练习</option>
                  <option value="review">复习</option>
                  <option value="output">知识产出</option>
                </select>
              </label>
              <label className="field">
                <span>排期方式</span>
                <select value={scheduleMode} onChange={(event) => setScheduleMode(event.target.value as ScheduleMode)}>
                  <option value="flexible">灵活进度</option>
                  <option value="fixed">固定日程</option>
                </select>
              </label>
              <label className="field">
                <span>任务开始日期</span>
                <input type="date" value={taskStartDate} onChange={(event) => setTaskStartDate(event.target.value)} required />
              </label>
              <label className="field">
                <span>任务截止日期</span>
                <input type="date" value={taskDueDate} onChange={(event) => setTaskDueDate(event.target.value)} required />
              </label>
              {scheduleMode === "fixed" && (
                <>
                  <label className="field">
                    <span>具体开始时间</span>
                    <input type="datetime-local" value={plannedStart} onChange={(event) => setPlannedStart(event.target.value)} required />
                  </label>
                  <label className="field">
                    <span>具体结束时间</span>
                    <input type="datetime-local" value={plannedEnd} onChange={(event) => setPlannedEnd(event.target.value)} required />
                  </label>
                </>
              )}
              <label className="field">
                <span>预计学习时长（分钟）</span>
                <input type="number" min="1" max="1440" value={estimateMinutes} onChange={(event) => setEstimateMinutes(Number(event.target.value))} required />
              </label>
              <label className="field">
                <span>默认计时方式</span>
                <select value={timerMode} onChange={(event) => selectTimerMode(event.target.value as TimerMode)}>
                  <option value="pomodoro_25_5">25 / 5</option>
                  <option value="pomodoro_50_10">50 / 10</option>
                  <option value="custom">自定义番茄钟</option>
                  <option value="count_up">普通计时</option>
                </select>
              </label>
              {timerMode === "custom" && (
                <>
                  <label className="field">
                    <span>专注分钟</span>
                    <input type="number" min="1" max="240" value={workMinutes} onChange={(event) => setWorkMinutes(Number(event.target.value))} required />
                  </label>
                  <label className="field">
                    <span>休息分钟</span>
                    <input type="number" min="0" max="120" value={breakMinutes} onChange={(event) => setBreakMinutes(Number(event.target.value))} required />
                  </label>
                </>
              )}
            </div>
          </fieldset>

          {error && <p className="form-error dialog-error" role="alert">{error}</p>}
          <footer className="dialog-actions">
            <button className="button button--quiet" type="button" onClick={onClose}>取消</button>
            <button className="button button--dark" disabled={submitting}>
              {submitting ? "正在创建" : "创建计划"}
            </button>
          </footer>
        </form>
        </section>
      </div>
    </DialogPortal>
  );
}
