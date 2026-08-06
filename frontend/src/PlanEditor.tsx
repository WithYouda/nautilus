import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { BookOpen, CheckSquare2, Layers3, Save, Target, Trash2 } from "lucide-react";
import type { Plan, Task, TaskEditorInput } from "./api";
import DialogPortal from "./DialogPortal";

export type EditorFormHandle = {
  isDirty: () => boolean;
  save: () => Promise<boolean>;
  discard: () => void;
};

export const GoalEditorForm = forwardRef<EditorFormHandle, {
  plan: Plan;
  busy: boolean;
  onSave: (payload: Pick<Plan, "title" | "description" | "start_date" | "end_date" | "status">) => Promise<void>;
  onDelete?: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}>(function GoalEditorForm({ plan, busy, onSave, onDelete, onDirtyChange }, ref) {
  type Values = Pick<Plan, "title" | "description" | "start_date" | "end_date" | "status">;
  const initial = useMemo<Values>(() => ({
    title: plan.title,
    description: plan.description,
    start_date: plan.start_date,
    end_date: plan.end_date,
    status: plan.status,
  }), [plan.description, plan.end_date, plan.id, plan.start_date, plan.status, plan.title]);
  const initialRef = useRef(initial);
  const [values, setValues] = useState(initial);
  const dirty = JSON.stringify(values) !== JSON.stringify(initialRef.current);

  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  async function save() {
    if (!values.title.trim()) return false;
    try {
      const payload = { ...values, title: values.title.trim() };
      await onSave(payload);
      initialRef.current = payload;
      setValues(payload);
      return true;
    } catch {
      return false;
    }
  }

  useImperativeHandle(ref, () => ({
    isDirty: () => dirty,
    save,
    discard: () => setValues(initialRef.current),
  }), [dirty, values]);

  return (
    <form className="editor-form editor-form--inline" onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <EditorHeading icon={<Target size={19} />} eyebrow="计划设置" title="编辑计划" description="调整计划范围、说明和当前状态。" />
      <div className="editor-form-body">
        <label className="field field--wide"><span>计划名称</span><input value={values.title} onChange={(event) => setValues((current) => ({ ...current, title: event.target.value }))} required maxLength={120} /></label>
        <label className="field field--wide"><span>计划说明</span><textarea value={values.description} onChange={(event) => setValues((current) => ({ ...current, description: event.target.value }))} maxLength={1000} rows={4} /></label>
        <div className="field-grid field-grid--two">
          <label className="field"><span>开始日期</span><input type="date" value={values.start_date} onChange={(event) => setValues((current) => ({ ...current, start_date: event.target.value }))} required /></label>
          <label className="field"><span>结束日期</span><input type="date" value={values.end_date} onChange={(event) => setValues((current) => ({ ...current, end_date: event.target.value }))} required /></label>
        </div>
        <label className="field"><span>状态</span><select value={values.status} onChange={(event) => setValues((current) => ({ ...current, status: event.target.value as Plan["status"] }))}><option value="draft">草稿</option><option value="active">进行中</option><option value="completed">已完成</option><option value="archived">已归档</option></select></label>
      </div>
      <EditorActions busy={busy} dirty={dirty} onDelete={onDelete} />
    </form>
  );
});

export const NodeEditorForm = forwardRef<EditorFormHandle, {
  kind: "subject" | "topic";
  title: string;
  busy: boolean;
  creating?: boolean;
  onSave: (title: string) => Promise<void>;
  onDelete?: () => void;
  onCancel?: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}>(function NodeEditorForm({ kind, title: initialTitle, busy, creating = false, onSave, onDelete, onCancel, onDirtyChange }, ref) {
  const initialRef = useRef(initialTitle);
  const [title, setTitle] = useState(initialTitle);
  const dirty = title !== initialRef.current;
  const label = kind === "subject" ? "科目" : "主题";
  const Icon = kind === "subject" ? BookOpen : Layers3;

  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  async function save() {
    const normalized = title.trim();
    if (!normalized) return false;
    try {
      await onSave(normalized);
      initialRef.current = normalized;
      setTitle(normalized);
      return true;
    } catch {
      return false;
    }
  }

  useImperativeHandle(ref, () => ({
    isDirty: () => dirty,
    save,
    discard: () => setTitle(initialRef.current),
  }), [dirty, title]);

  return (
    <form className="editor-form editor-form--inline" onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <EditorHeading icon={<Icon size={19} />} eyebrow={label} title={creating ? `新建${label}` : `编辑${label}`} description={kind === "subject" ? "科目组织一组相互关联的主题。" : "主题承载一组可直接执行的任务。"} />
      <div className="editor-form-body editor-form-body--compact">
        <label className="field field--wide"><span>{label}名称</span><input value={title} onChange={(event) => setTitle(event.target.value)} required maxLength={120} autoFocus /></label>
      </div>
      <EditorActions busy={busy} dirty={dirty || creating} creating={creating} onDelete={onDelete} onCancel={onCancel} />
    </form>
  );
});

export const TaskEditorForm = forwardRef<EditorFormHandle, {
  plan: Plan;
  task: Task | null;
  busy: boolean;
  onSave: (payload: TaskEditorInput) => Promise<void>;
  onDelete?: () => void;
  onCancel?: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}>(function TaskEditorForm({ plan, task, busy, onSave, onDelete, onCancel, onDirtyChange }, ref) {
  const defaultDate = clampDate(todayString(), plan.start_date, plan.end_date);
  const initial = useMemo(() => taskValues(task, defaultDate), [defaultDate, task]);
  const initialRef = useRef(initial);
  const [values, setValues] = useState(initial);
  const dirty = JSON.stringify(values) !== JSON.stringify(initialRef.current);

  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  function payload(): TaskEditorInput {
    return {
      title: values.title.trim(),
      task_type: values.task_type,
      schedule_mode: values.schedule_mode,
      start_date: values.start_date,
      due_date: values.due_date,
      planned_start: values.planned_start ? new Date(values.planned_start).toISOString() : null,
      planned_end: values.planned_end ? new Date(values.planned_end).toISOString() : null,
      estimate_minutes: values.estimate_minutes,
      timer_mode: values.timer_mode,
      work_minutes: values.work_minutes,
      break_minutes: values.break_minutes,
    };
  }

  async function save() {
    const next = payload();
    if (!next.title) return false;
    try {
      await onSave(next);
      const normalized = { ...values, title: next.title };
      initialRef.current = normalized;
      setValues(normalized);
      return true;
    } catch {
      return false;
    }
  }

  useImperativeHandle(ref, () => ({
    isDirty: () => dirty,
    save,
    discard: () => setValues(initialRef.current),
  }), [dirty, values]);

  function chooseTimer(next: Task["timer_mode"]) {
    setValues((current) => ({
      ...current,
      timer_mode: next,
      ...(next === "pomodoro_25_5" ? { work_minutes: 25, break_minutes: 5 } : {}),
      ...(next === "pomodoro_50_10" ? { work_minutes: 50, break_minutes: 10 } : {}),
      ...(next === "count_up" ? { work_minutes: 60, break_minutes: 0 } : {}),
    }));
  }

  return (
    <form className="editor-form editor-form--inline" onSubmit={(event: FormEvent) => { event.preventDefault(); void save(); }}>
      <EditorHeading
        icon={<CheckSquare2 size={19} />}
        eyebrow="任务"
        title={task ? `编辑任务：${task.title}` : "新建任务"}
        description={task ? `${statusLabel(task.status)} · 当前进度 ${task.progress}%` : "添加一项可直接执行、计时和撤销完成的学习任务。"}
      />
      <div className="editor-form-body">
        <label className="field field--wide"><span>任务名称</span><input value={values.title} onChange={(event) => setValues((current) => ({ ...current, title: event.target.value }))} required maxLength={200} autoFocus={!task} /></label>
        <div className="editor-section">
          <div className="editor-section-title"><strong>任务类型</strong></div>
          <div className="choice-grid choice-grid--four">
            {(["study", "practice", "review", "output"] as Task["task_type"][]).map((item) => <button type="button" className={values.task_type === item ? "is-active" : ""} onClick={() => setValues((current) => ({ ...current, task_type: item }))} key={item}>{taskTypeLabel(item)}</button>)}
          </div>
        </div>
        <div className="field-grid field-grid--two">
          <label className="field"><span>排期方式</span><select value={values.schedule_mode} onChange={(event) => setValues((current) => ({ ...current, schedule_mode: event.target.value as Task["schedule_mode"] }))}><option value="flexible">灵活进度</option><option value="fixed">固定日程</option></select></label>
          <label className="field"><span>预计时长（分钟）</span><input type="number" min="1" max="1440" value={values.estimate_minutes} onChange={(event) => setValues((current) => ({ ...current, estimate_minutes: Number(event.target.value) }))} required /></label>
          <label className="field"><span>开始日期</span><input type="date" min={plan.start_date} max={plan.end_date} value={values.start_date} onChange={(event) => setValues((current) => ({ ...current, start_date: event.target.value }))} required /></label>
          <label className="field"><span>截止日期</span><input type="date" min={plan.start_date} max={plan.end_date} value={values.due_date} onChange={(event) => setValues((current) => ({ ...current, due_date: event.target.value }))} required /></label>
          <label className="field"><span>具体开始（可选）</span><input type="datetime-local" value={values.planned_start} onChange={(event) => setValues((current) => ({ ...current, planned_start: event.target.value }))} /></label>
          <label className="field"><span>具体结束（可选）</span><input type="datetime-local" value={values.planned_end} onChange={(event) => setValues((current) => ({ ...current, planned_end: event.target.value }))} /></label>
        </div>
        <div className="editor-section">
          <div className="editor-section-title"><strong>计时方式</strong></div>
          <div className="choice-grid choice-grid--four">
            {(["pomodoro_25_5", "pomodoro_50_10", "custom", "count_up"] as Task["timer_mode"][]).map((item) => <button type="button" className={values.timer_mode === item ? "is-active" : ""} onClick={() => chooseTimer(item)} key={item}>{timerModeLabel(item)}</button>)}
          </div>
        </div>
        {values.timer_mode === "custom" && <div className="field-grid field-grid--two">
          <label className="field"><span>专注分钟</span><input type="number" min="1" max="240" value={values.work_minutes} onChange={(event) => setValues((current) => ({ ...current, work_minutes: Number(event.target.value) }))} /></label>
          <label className="field"><span>休息分钟</span><input type="number" min="0" max="120" value={values.break_minutes} onChange={(event) => setValues((current) => ({ ...current, break_minutes: Number(event.target.value) }))} /></label>
        </div>}
      </div>
      <EditorActions busy={busy} dirty={dirty || !task} creating={!task} onDelete={onDelete} onCancel={onCancel} />
    </form>
  );
});

function EditorHeading({ icon, eyebrow, title, description }: { icon: ReactNode; eyebrow: string; title: string; description: string }) {
  return <header className="editor-heading"><div className="editor-heading-icon">{icon}</div><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2><p>{description}</p></div></header>;
}

function EditorActions({ busy, dirty, creating = false, onDelete, onCancel }: { busy: boolean; dirty: boolean; creating?: boolean; onDelete?: () => void; onCancel?: () => void }) {
  return <footer className="editor-actions"><div>{onDelete && <button type="button" className="button button--danger button--with-icon" disabled={busy} onClick={onDelete}><Trash2 size={15} />删除</button>}</div><div>{onCancel && <button type="button" className="button button--quiet" disabled={busy} onClick={onCancel}>取消</button>}<button className="button button--accent button--with-icon" disabled={busy || (!creating && !dirty)}><Save size={15} />{busy ? "保存中" : creating ? "创建" : "保存更改"}</button></div></footer>;
}

export function ConfirmDialog({ title, description, busy, onCancel, onConfirm }: { title: string; description: string; busy: boolean; onCancel: () => void; onConfirm: () => void }) {
  return <DialogPortal><div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onCancel(); }}><section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title"><div className="confirm-icon"><Trash2 size={20} /></div><h2 id="confirm-title">{title}</h2><p>{description}</p><div className="confirm-actions"><button className="button button--quiet" disabled={busy} onClick={onCancel}>取消</button><button className="button button--danger" disabled={busy} onClick={onConfirm}>{busy ? "处理中" : "确认删除"}</button></div></section></div></DialogPortal>;
}

function taskValues(task: Task | null, defaultDate: string) {
  return {
    title: task?.title ?? "",
    task_type: task?.task_type ?? "study" as Task["task_type"],
    schedule_mode: task?.schedule_mode ?? "flexible" as Task["schedule_mode"],
    start_date: task?.start_date ?? defaultDate,
    due_date: task?.due_date ?? defaultDate,
    planned_start: toLocalDateTime(task?.planned_start),
    planned_end: toLocalDateTime(task?.planned_end),
    estimate_minutes: task?.estimate_minutes ?? 50,
    timer_mode: task?.timer_mode ?? "pomodoro_50_10" as Task["timer_mode"],
    work_minutes: task?.work_minutes ?? 50,
    break_minutes: task?.break_minutes ?? 10,
  };
}

export function taskTypeLabel(value: Task["task_type"]) {
  return { study: "学习", practice: "练习", review: "复习", output: "知识产出" }[value];
}

export function statusLabel(value: Plan["status"] | Task["status"]) {
  return { draft: "草稿", active: "进行中", completed: "已完成", archived: "已归档", pending: "待开始", in_progress: "进行中", canceled: "已取消" }[value];
}

function timerModeLabel(value: Task["timer_mode"]) {
  return { pomodoro_25_5: "25 / 5", pomodoro_50_10: "50 / 10", custom: "自定义", count_up: "普通计时" }[value];
}

function todayString() {
  const today = new Date();
  const offset = today.getTimezoneOffset();
  return new Date(today.getTime() - offset * 60_000).toISOString().slice(0, 10);
}

function clampDate(value: string, min: string, max: string) {
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

function toLocalDateTime(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 16);
  const offset = date.getTimezoneOffset();
  return new Date(date.getTime() - offset * 60_000).toISOString().slice(0, 16);
}
