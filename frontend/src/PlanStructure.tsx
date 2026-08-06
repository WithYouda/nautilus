import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ArrowDown,
  ArrowUp,
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  Circle,
  MoreHorizontal,
  Plus,
  Trash2,
} from "lucide-react";
import {
  createSubject,
  createTask,
  createTopic,
  deleteSubject,
  deleteTask,
  deleteTopic,
  reorderSubjects,
  reorderTasks,
  reorderTopics,
  setTaskCompletion,
  updateSubject,
  updateTask,
  updateTopic,
  type PlanDetail,
  type Subject,
  type Task,
  type Topic,
} from "./api";
import {
  ConfirmDialog,
  NodeEditorForm,
  TaskEditorForm,
  statusLabel,
  taskTypeLabel,
  type EditorFormHandle,
} from "./PlanEditor";
import useDismissibleLayer from "./useDismissibleLayer";

type Selection =
  | { kind: "subject"; id: string }
  | { kind: "topic"; id: string }
  | { kind: "task"; id: string }
  | { kind: "new-subject"; parentId: string }
  | { kind: "new-topic"; parentId: string }
  | { kind: "new-task"; parentId: string };

type DeleteTarget = { kind: "subject" | "topic" | "task"; id: string; label: string };

export type PlanStructureHandle = {
  isDirty: () => boolean;
  save: () => Promise<boolean>;
  discard: () => void;
};

const EXPANSION_KEY = "nautilus.plan-structure.expansion";

const PlanStructure = forwardRef<PlanStructureHandle, {
  plan: PlanDetail;
  targetTaskId: string | null;
  addSubjectRequest: number;
  runGuarded: (action: () => void) => void;
  onRefresh: () => Promise<void>;
  onOpenTaskAi: (taskId: string) => void;
}>(function PlanStructure({ plan, targetTaskId, addSubjectRequest, runGuarded, onRefresh, onOpenTaskAi }, ref) {
  const [expandedSubjects, setExpandedSubjects] = useState<Set<string>>(new Set());
  const [expandedTopics, setExpandedTopics] = useState<Set<string>>(new Set());
  const [selection, setSelection] = useState<Selection | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);
  const editorRef = useRef<EditorFormHandle>(null);
  const lastAddRequest = useRef(addSubjectRequest);

  useImperativeHandle(ref, () => ({
    isDirty: () => editorRef.current?.isDirty() ?? dirty,
    save: () => editorRef.current?.save() ?? Promise.resolve(true),
    discard: () => editorRef.current?.discard(),
  }), [dirty]);

  useEffect(() => {
    const restored = restoreExpansion(plan.id);
    if (restored) {
      setExpandedSubjects(new Set(restored.subjects.filter((id) => plan.subjects.some((subject) => subject.id === id))));
      setExpandedTopics(new Set(restored.topics.filter((id) => findTopic(plan, id))));
      return;
    }
    const focusId = targetTaskId ?? plan.summary.next_task?.id ?? null;
    const path = focusId ? findTaskPath(plan, focusId) : null;
    setExpandedSubjects(new Set(path ? [path.subject.id] : []));
    setExpandedTopics(new Set(path ? [path.topic.id] : []));
  }, [plan.id]);

  useEffect(() => {
    persistExpansion(plan.id, expandedSubjects, expandedTopics);
  }, [expandedSubjects, expandedTopics, plan.id]);

  useEffect(() => {
    if (!targetTaskId) return;
    const path = findTaskPath(plan, targetTaskId);
    if (!path) return;
    setExpandedSubjects((current) => new Set(current).add(path.subject.id));
    setExpandedTopics((current) => new Set(current).add(path.topic.id));
    requestAnimationFrame(() => document.querySelector(`[data-task-id="${CSS.escape(targetTaskId)}"]`)?.scrollIntoView({ block: "center" }));
  }, [plan, targetTaskId]);

  useEffect(() => {
    if (addSubjectRequest === lastAddRequest.current) return;
    lastAddRequest.current = addSubjectRequest;
    requestSelection({ kind: "new-subject", parentId: plan.id });
  }, [addSubjectRequest, plan.id]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const requestSelection = useCallback((next: Selection | null) => {
    runGuarded(() => {
      setSelection(next);
      setDirty(false);
      setError("");
    });
  }, [runGuarded]);

  async function mutate(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
      await onRefresh();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "计划更新失败");
      throw reason;
    } finally {
      setBusy(false);
    }
  }

  async function createMutation<T>(action: () => Promise<T>): Promise<T> {
    setBusy(true);
    setError("");
    try {
      const result = await action();
      await onRefresh();
      return result;
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "节点创建失败");
      throw reason;
    } finally {
      setBusy(false);
    }
  }

  function toggleSubject(subjectId: string) {
    setExpandedSubjects((current) => toggledSet(current, subjectId));
  }

  function toggleTopic(topicId: string) {
    setExpandedTopics((current) => toggledSet(current, topicId));
  }

  function openExisting(next: Selection) {
    const same = selection?.kind === next.kind && "id" in selection && "id" in next && selection.id === next.id;
    requestSelection(same ? null : next);
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    const target = deleteTarget;
    try {
      await mutate(async () => {
        if (target.kind === "subject") await deleteSubject(target.id);
        if (target.kind === "topic") await deleteTopic(target.id);
        if (target.kind === "task") await deleteTask(target.id);
      });
      setDeleteTarget(null);
      setSelection(null);
      setDirty(false);
    } catch {
      // The inline error remains visible.
    }
  }

  function editorFor(next: Selection): ReactNode {
    if (next.kind === "new-subject") return <NodeEditorForm key="new-subject" ref={editorRef} kind="subject" title="" busy={busy} creating onDirtyChange={setDirty} onCancel={() => requestSelection(null)} onSave={async (title) => {
      const created = await createMutation(() => createSubject(plan.id, title));
      setSelection({ kind: "subject", id: created.id });
    }} />;
    if (next.kind === "new-topic") return <NodeEditorForm key={`new-topic-${next.parentId}`} ref={editorRef} kind="topic" title="" busy={busy} creating onDirtyChange={setDirty} onCancel={() => requestSelection(null)} onSave={async (title) => {
      const created = await createMutation(() => createTopic(next.parentId, title));
      setExpandedSubjects((current) => new Set(current).add(next.parentId));
      setSelection({ kind: "topic", id: created.id });
    }} />;
    if (next.kind === "new-task") return <TaskEditorForm key={`new-task-${next.parentId}`} ref={editorRef} plan={plan} task={null} busy={busy} onDirtyChange={setDirty} onCancel={() => requestSelection(null)} onSave={async (payload) => {
      const created = await createMutation(() => createTask(next.parentId, payload));
      setExpandedTopics((current) => new Set(current).add(next.parentId));
      setSelection({ kind: "task", id: created.id });
    }} />;
    if (next.kind === "subject") {
      const subject = plan.subjects.find((item) => item.id === next.id);
      if (!subject) return null;
      return <NodeEditorForm key={subject.id} ref={editorRef} kind="subject" title={subject.title} busy={busy} onDirtyChange={setDirty} onDelete={() => setDeleteTarget({ kind: "subject", id: subject.id, label: subject.title })} onSave={(title) => mutate(() => updateSubject(subject.id, title))} />;
    }
    if (next.kind === "topic") {
      const topic = findTopic(plan, next.id);
      if (!topic) return null;
      return <NodeEditorForm key={topic.id} ref={editorRef} kind="topic" title={topic.title} busy={busy} onDirtyChange={setDirty} onDelete={() => setDeleteTarget({ kind: "topic", id: topic.id, label: topic.title })} onSave={(title) => mutate(() => updateTopic(topic.id, title))} />;
    }
    const task = findTask(plan, next.id);
    if (!task) return null;
    return <TaskEditorForm key={task.id} ref={editorRef} plan={plan} task={task} busy={busy} onDirtyChange={setDirty} onDelete={() => setDeleteTarget({ kind: "task", id: task.id, label: task.title })} onSave={(payload) => mutate(() => updateTask(task.id, payload))} />;
  }

  return <div className="plan-structure" aria-label="计划结构">
    <div className="plan-structure-toolbar">
      <div><span className="eyebrow">DOCUMENT OUTLINE</span><h3>计划结构</h3></div>
      <div><button className="button button--quiet button--compact" type="button" onClick={() => { setExpandedSubjects(new Set()); setExpandedTopics(new Set()); }}>收起全部</button><button className="button button--quiet button--compact" type="button" onClick={() => { setExpandedSubjects(new Set(plan.subjects.map((subject) => subject.id))); setExpandedTopics(new Set()); }}>展开到主题</button></div>
    </div>
    {error && <div className="workspace-alert plan-editor-alert" role="alert">{error}</div>}
    {selection?.kind === "new-subject" && <div className="outline-editor outline-editor--root">{editorFor(selection)}</div>}
    {plan.subjects.length ? <div className="document-outline">
      {plan.subjects.map((subject, subjectIndex) => {
        const subjectOpen = expandedSubjects.has(subject.id);
        return <section className="outline-subject" key={subject.id}>
          <div className={`outline-node-row outline-node-row--subject${selection?.kind === "subject" && selection.id === subject.id ? " is-selected" : ""}`}>
            <button className="outline-chevron" type="button" onClick={() => toggleSubject(subject.id)} aria-expanded={subjectOpen} aria-label={`${subjectOpen ? "收起" : "展开"}科目：${subject.title}`}>{subjectOpen ? <ChevronDown size={17} /> : <ChevronRight size={17} />}</button>
            <button className="outline-node-main" type="button" onClick={() => openExisting({ kind: "subject", id: subject.id })}><strong>{subject.title}</strong><span>{subject.completed_task_count ?? 0} / {subject.task_count ?? 0} 项任务 · {subject.progress ?? 0}%</span></button>
            <button className="icon-button icon-button--small" type="button" onClick={() => requestSelection({ kind: "new-topic", parentId: subject.id })} aria-label={`在${subject.title}下添加主题`} title="添加主题"><Plus size={15} /></button>
            <OutlineMenu busy={busy} canMoveUp={subjectIndex > 0} canMoveDown={subjectIndex < plan.subjects.length - 1} onMoveUp={() => void mutate(() => reorderSubjects(plan.id, swapIds(plan.subjects, subjectIndex, subjectIndex - 1)))} onMoveDown={() => void mutate(() => reorderSubjects(plan.id, swapIds(plan.subjects, subjectIndex, subjectIndex + 1)))} onDelete={() => setDeleteTarget({ kind: "subject", id: subject.id, label: subject.title })} label={subject.title} />
          </div>
          {selection?.kind === "subject" && selection.id === subject.id && <div className="outline-editor outline-editor--subject">{editorFor(selection)}</div>}
          {selection?.kind === "new-topic" && selection.parentId === subject.id && <div className="outline-editor outline-editor--subject">{editorFor(selection)}</div>}
          {subjectOpen && <div className="outline-topic-list">
            {subject.topics.map((topic, topicIndex) => {
              const topicOpen = expandedTopics.has(topic.id);
              return <div className="outline-topic" key={topic.id}>
                <div className={`outline-node-row outline-node-row--topic${selection?.kind === "topic" && selection.id === topic.id ? " is-selected" : ""}`}>
                  <button className="outline-chevron" type="button" onClick={() => toggleTopic(topic.id)} aria-expanded={topicOpen} aria-label={`${topicOpen ? "收起" : "展开"}主题：${topic.title}`}>{topicOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}</button>
                  <button className="outline-node-main" type="button" onClick={() => openExisting({ kind: "topic", id: topic.id })}><strong>{topic.title}</strong><span>{topic.completed_task_count ?? 0} / {topic.task_count ?? 0} 项任务 · {topic.progress ?? 0}%</span></button>
                  <button className="icon-button icon-button--small" type="button" onClick={() => requestSelection({ kind: "new-task", parentId: topic.id })} aria-label={`在${topic.title}下添加任务`} title="添加任务"><Plus size={15} /></button>
                  <OutlineMenu busy={busy} canMoveUp={topicIndex > 0} canMoveDown={topicIndex < subject.topics.length - 1} onMoveUp={() => void mutate(() => reorderTopics(subject.id, swapIds(subject.topics, topicIndex, topicIndex - 1)))} onMoveDown={() => void mutate(() => reorderTopics(subject.id, swapIds(subject.topics, topicIndex, topicIndex + 1)))} onDelete={() => setDeleteTarget({ kind: "topic", id: topic.id, label: topic.title })} label={topic.title} />
                </div>
                {selection?.kind === "topic" && selection.id === topic.id && <div className="outline-editor outline-editor--topic">{editorFor(selection)}</div>}
                {selection?.kind === "new-task" && selection.parentId === topic.id && <div className="outline-editor outline-editor--task">{editorFor(selection)}</div>}
                {topicOpen && <div className="outline-task-list">
                  {topic.tasks.map((task, taskIndex) => {
                    const selected = selection?.kind === "task" && selection.id === task.id;
                    const complete = task.status === "completed";
                    const CompleteIcon = complete ? Check : Circle;
                    return <div className="outline-task" key={task.id} data-task-id={task.id}>
                      <div className={`outline-node-row outline-node-row--task${selected ? " is-selected" : ""}${complete ? " is-complete" : ""}`}>
                        <span className="outline-task-spacer" />
                        <button className="outline-task-check" type="button" disabled={busy || task.status === "canceled"} onClick={() => void mutate(() => setTaskCompletion(task.id, !complete))} aria-label={complete ? `撤销完成：${task.title}` : `完成任务：${task.title}`} title={complete ? "标记为未完成" : "标记完成"}><CompleteIcon size={17} /></button>
                        <button className="outline-node-main outline-node-main--task" type="button" onClick={() => openExisting({ kind: "task", id: task.id })}><strong>{task.title}</strong><span>{taskTypeLabel(task.task_type)} · {task.estimate_minutes} 分钟 · {statusLabel(task.status)}</span></button>
                        <button className="icon-button icon-button--small" type="button" onClick={() => runGuarded(() => onOpenTaskAi(task.id))} aria-label={`任务 AI：${task.title}`} title="任务 AI"><Bot size={15} /></button>
                        <OutlineMenu busy={busy} canMoveUp={taskIndex > 0} canMoveDown={taskIndex < topic.tasks.length - 1} onMoveUp={() => void mutate(() => reorderTasks(topic.id, swapIds(topic.tasks, taskIndex, taskIndex - 1)))} onMoveDown={() => void mutate(() => reorderTasks(topic.id, swapIds(topic.tasks, taskIndex, taskIndex + 1)))} onDelete={() => setDeleteTarget({ kind: "task", id: task.id, label: task.title })} label={task.title} />
                      </div>
                      {selected && <div className="outline-editor outline-editor--task">{editorFor(selection)}</div>}
                    </div>;
                  })}
                </div>}
              </div>;
            })}
          </div>}
        </section>;
      })}
    </div> : <div className="plan-inline-empty"><p>这个计划还没有科目。使用计划标题右侧的“科目”按钮开始建立结构。</p></div>}
    {deleteTarget && <ConfirmDialog title={`删除“${deleteTarget.label}”？`} description="该节点会从当前计划中隐藏，数据仍保留在本地数据库中。" busy={busy} onCancel={() => setDeleteTarget(null)} onConfirm={() => void confirmDelete()} />}
  </div>;
});

export default PlanStructure;

function OutlineMenu({ busy, canMoveUp, canMoveDown, onMoveUp, onMoveDown, onDelete, label }: { busy: boolean; canMoveUp: boolean; canMoveDown: boolean; onMoveUp: () => void; onMoveDown: () => void; onDelete: () => void; label: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useDismissibleLayer(open, [ref], () => setOpen(false));
  return <div className="outline-more" ref={ref}><button className="icon-button icon-button--small" type="button" onClick={() => setOpen((current) => !current)} aria-label={`更多操作：${label}`} aria-expanded={open}><MoreHorizontal size={16} /></button>{open && <div className="outline-more-menu" role="menu"><button type="button" role="menuitem" disabled={busy || !canMoveUp} onClick={() => { setOpen(false); onMoveUp(); }}><ArrowUp size={14} />上移</button><button type="button" role="menuitem" disabled={busy || !canMoveDown} onClick={() => { setOpen(false); onMoveDown(); }}><ArrowDown size={14} />下移</button><button type="button" role="menuitem" disabled={busy} onClick={() => { setOpen(false); onDelete(); }}><Trash2 size={14} />删除</button></div>}</div>;
}

function findTopic(plan: PlanDetail, id: string): Topic | null {
  return plan.subjects.flatMap((subject) => subject.topics).find((topic) => topic.id === id) ?? null;
}

function findTask(plan: PlanDetail, id: string): Task | null {
  return plan.subjects.flatMap((subject) => subject.topics.flatMap((topic) => topic.tasks)).find((task) => task.id === id) ?? null;
}

function findTaskPath(plan: PlanDetail, id: string): { subject: Subject; topic: Topic; task: Task } | null {
  for (const subject of plan.subjects) for (const topic of subject.topics) {
    const task = topic.tasks.find((item) => item.id === id);
    if (task) return { subject, topic, task };
  }
  return null;
}

function toggledSet(current: Set<string>, id: string) {
  const next = new Set(current);
  if (next.has(id)) next.delete(id); else next.add(id);
  return next;
}

function swapIds(items: { id: string }[], from: number, to: number) {
  const ids = items.map((item) => item.id);
  [ids[from], ids[to]] = [ids[to], ids[from]];
  return ids;
}

function restoreExpansion(planId: string): { subjects: string[]; topics: string[] } | null {
  try {
    const all = JSON.parse(sessionStorage.getItem(EXPANSION_KEY) ?? "{}") as Record<string, { subjects?: string[]; topics?: string[] }>;
    const value = all[planId];
    return value ? { subjects: value.subjects ?? [], topics: value.topics ?? [] } : null;
  } catch {
    return null;
  }
}

function persistExpansion(planId: string, subjects: Set<string>, topics: Set<string>) {
  try {
    const all = JSON.parse(sessionStorage.getItem(EXPANSION_KEY) ?? "{}") as Record<string, unknown>;
    all[planId] = { subjects: [...subjects], topics: [...topics] };
    sessionStorage.setItem(EXPANSION_KEY, JSON.stringify(all));
  } catch {
    // The outline remains usable without session storage.
  }
}
