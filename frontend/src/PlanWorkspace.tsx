import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowUpRight, Bot, CalendarRange, ListTree, Plus, Settings2 } from "lucide-react";
import {
  deletePlan,
  getPlan,
  getPlanSchedule,
  rescheduleTask,
  setTaskCompletion,
  updatePlan,
  type PlanDetail,
  type PlanScheduleItem,
  type PlanSummary,
  type Task,
} from "./api";
import DialogPortal from "./DialogPortal";
import { ConfirmDialog, GoalEditorForm, statusLabel, type EditorFormHandle } from "./PlanEditor";
import PlanOverview from "./PlanOverview";
import PlanSchedule from "./PlanSchedule";
import PlanStructure, { type PlanStructureHandle } from "./PlanStructure";
import UnsavedChangesDialog from "./UnsavedChangesDialog";

export type PlanTab = "overview" | "structure" | "schedule";

const LAST_TAB_KEY = "nautilus.plan-workspace.last-tab";

export default function PlanWorkspace({
  summaries,
  onRefreshSummaries,
  onOpenTaskAi,
  onOpenPlanAi,
  onOpenCalendar,
  onPlanContextChange,
}: {
  summaries: PlanSummary[];
  onRefreshSummaries: () => Promise<void>;
  onOpenTaskAi: (taskId: string) => void;
  onOpenPlanAi: (planId: string) => void;
  onOpenCalendar: (planId: string) => void;
  onPlanContextChange: (plan: PlanDetail | null) => void;
}) {
  const initial = readPlanLocation();
  const [planId, setPlanId] = useState<string | null>(initial.planId);
  const [tab, setTab] = useState<PlanTab>(initial.tab);
  const [targetTaskId, setTargetTaskId] = useState<string | null>(initial.node);
  const [plan, setPlan] = useState<PlanDetail | null>(null);
  const [schedule, setSchedule] = useState<PlanScheduleItem[]>([]);
  const [loading, setLoading] = useState(Boolean(initial.planId));
  const [error, setError] = useState("");
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null);
  const [addSubjectRequest, setAddSubjectRequest] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [settingsClosePending, setSettingsClosePending] = useState(false);
  const [deletePlanOpen, setDeletePlanOpen] = useState(false);
  const [mutationBusy, setMutationBusy] = useState(false);
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null);
  const [guardBusy, setGuardBusy] = useState(false);
  const structureRef = useRef<PlanStructureHandle>(null);
  const settingsRef = useRef<EditorFormHandle>(null);

  const loadPlan = useCallback(async (nextPlanId: string) => {
    setLoading(true);
    setError("");
    try {
      const [nextPlan, nextSchedule] = await Promise.all([getPlan(nextPlanId), getPlanSchedule(nextPlanId)]);
      setPlan(nextPlan);
      setSchedule(nextSchedule);
      onPlanContextChange(nextPlan);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "计划加载失败");
      setPlan(null);
      setSchedule([]);
      setPlanId(null);
      onPlanContextChange(null);
      writePlanLocation(null, "overview", null, true);
    } finally {
      setLoading(false);
    }
  }, [onPlanContextChange]);

  const refreshPlan = useCallback(async () => {
    if (!planId) return;
    await Promise.all([loadPlan(planId), onRefreshSummaries()]);
  }, [loadPlan, onRefreshSummaries, planId]);

  useEffect(() => {
    if (planId) void loadPlan(planId);
    else {
      setPlan(null);
      setSchedule([]);
      onPlanContextChange(null);
    }
  }, [loadPlan, onPlanContextChange, planId]);

  useEffect(() => {
    const onPopState = () => {
      const next = readPlanLocation();
      setPlanId(next.planId);
      setTab(next.tab);
      setTargetTaskId(next.node);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    if (!settingsOpen || deletePlanOpen || settingsClosePending) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") requestSettingsClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [deletePlanOpen, mutationBusy, settingsClosePending, settingsDirty, settingsOpen]);

  useEffect(() => {
    if (!settingsDirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [settingsDirty]);

  function runGuarded(action: () => void) {
    if (tab === "structure" && structureRef.current?.isDirty()) {
      setPendingAction(() => action);
      return;
    }
    action();
  }

  function openPlan(nextPlanId: string, nextTab?: PlanTab, node: string | null = null) {
    const resolvedTab = nextTab ?? restoreLastTab(nextPlanId) ?? "overview";
    runGuarded(() => {
      setPlanId(nextPlanId);
      setTab(resolvedTab);
      setTargetTaskId(node);
      writePlanLocation(nextPlanId, resolvedTab, node);
    });
  }

  function chooseTab(nextTab: PlanTab, node: string | null = null) {
    if (!planId || nextTab === tab && node === targetTaskId) return;
    runGuarded(() => {
      setTab(nextTab);
      setTargetTaskId(node);
      storeLastTab(planId, nextTab);
      writePlanLocation(planId, nextTab, node);
    });
  }

  function backToList() {
    runGuarded(() => {
      setPlanId(null);
      setPlan(null);
      setSchedule([]);
      setTargetTaskId(null);
      onPlanContextChange(null);
      writePlanLocation(null, "overview", null);
    });
  }

  function addSubject() {
    runGuarded(() => {
      if (tab !== "structure") {
        setTab("structure");
        if (planId) {
          storeLastTab(planId, "structure");
          writePlanLocation(planId, "structure", null);
        }
        window.setTimeout(() => setAddSubjectRequest((current) => current + 1), 0);
      } else {
        setAddSubjectRequest((current) => current + 1);
      }
      setTargetTaskId(null);
    });
  }

  async function toggleCompletion(task: Task) {
    setBusyTaskId(task.id);
    setError("");
    try {
      await setTaskCompletion(task.id, task.status !== "completed");
      await refreshPlan();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "任务状态更新失败");
    } finally {
      setBusyTaskId(null);
    }
  }

  async function shiftTask(taskId: string, days: number) {
    setBusyTaskId(taskId);
    setError("");
    try {
      await rescheduleTask(taskId, days);
      await refreshPlan();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "任务排期更新失败");
    } finally {
      setBusyTaskId(null);
    }
  }

  async function deleteCurrentPlan() {
    if (!plan) return;
    setMutationBusy(true);
    setError("");
    try {
      await deletePlan(plan.id);
      setDeletePlanOpen(false);
      setSettingsOpen(false);
      setSettingsDirty(false);
      setSettingsClosePending(false);
      setPlanId(null);
      setPlan(null);
      onPlanContextChange(null);
      writePlanLocation(null, "overview", null);
      await onRefreshSummaries();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "计划删除失败");
    } finally {
      setMutationBusy(false);
    }
  }

  async function savePendingAndContinue() {
    setGuardBusy(true);
    const saved = await structureRef.current?.save();
    setGuardBusy(false);
    if (!saved) return;
    const action = pendingAction;
    setPendingAction(null);
    action?.();
  }

  function requestSettingsClose() {
    if (mutationBusy) return;
    if (settingsRef.current?.isDirty()) {
      setSettingsClosePending(true);
      return;
    }
    setSettingsOpen(false);
    setSettingsDirty(false);
  }

  async function saveSettingsAndClose() {
    const saved = await settingsRef.current?.save();
    if (!saved) return;
    setSettingsClosePending(false);
    setSettingsOpen(false);
    setSettingsDirty(false);
  }

  function discardSettingsAndClose() {
    settingsRef.current?.discard();
    setSettingsClosePending(false);
    setSettingsOpen(false);
    setSettingsDirty(false);
  }

  if (!planId) {
    return <div className="workspace-content plans-page plan-list-page">
      <section className="page-heading page-heading--plans"><div><p className="eyebrow">LEARNING PLANS</p><h1>历史计划</h1><p>管理此前保存的计划和任务。新学习的安排与进展请在“开始学习”中继续查看。</p></div></section>
      {error && <div className="workspace-alert" role="alert">{error}</div>}
      <PlanPortfolioMetrics summaries={summaries} />
      {summaries.length ? <section className="plan-summary-list" aria-label="全部计划">
        {summaries.map((summary) => <article className="plan-summary-row" key={summary.id}>
          <button className="plan-summary-main" type="button" onClick={() => openPlan(summary.id)}>
            <div className="plan-summary-title"><span className={`status-chip status-chip--${summary.status}`}>{statusLabel(summary.status)}</span><h2>{summary.title}</h2><p>{summary.description || "暂无计划说明"}</p></div>
            <div className="plan-summary-progress"><strong>{summary.progress}%</strong><div><span style={{ width: `${summary.progress}%` }} /></div><small>{summary.completed_task_count} / {summary.task_count} 项任务</small></div>
            <dl><div><dt>结构</dt><dd>{summary.subject_count} 科目 · {summary.topic_count} 主题</dd></div><div><dt>周期</dt><dd>{formatDateRange(summary.start_date, summary.end_date)}</dd></div></dl>
          </button>
          <div className="plan-summary-next"><span>下一项</span>{summary.next_task ? <button type="button" onClick={() => openPlan(summary.id, "structure", summary.next_task!.id)}><strong>{summary.next_task.title}</strong><small>{[summary.next_task.subject_title, summary.next_task.topic_title].filter(Boolean).join(" / ")}</small></button> : <p>暂无待办</p>}<button className="button button--quiet button--compact button--with-icon" type="button" onClick={() => openPlan(summary.id)}>打开计划<ArrowUpRight size={14} /></button></div>
        </article>)}
      </section> : <section className="empty-state empty-state--plans"><ListTree size={28} strokeWidth={1.5} /><h3>没有历史计划</h3><p>你可以在“开始学习”中填写想学会的内容，或继续上次的学习。</p></section>}
    </div>;
  }

  if (loading || !plan) return <div className="workspace-loading plan-workspace-loading"><div className="signal-loader" /><span>正在打开计划</span></div>;

  return <div className="workspace-content plans-page plan-detail-page">
    <button className="plan-back-button" type="button" onClick={backToList}><ArrowLeft size={15} />返回全部计划</button>
    <section className="plan-detail-heading">
      <div className="plan-detail-title"><div><span className={`status-chip status-chip--${plan.status}`}>{statusLabel(plan.status)}</span><span className="eyebrow">PLAN / {plan.id.slice(0, 8).toUpperCase()}</span></div><h1>{plan.title}</h1><p>{plan.description || "暂无计划说明"}</p></div>
      <div className="plan-detail-actions"><button className="button button--quiet button--with-icon" type="button" onClick={() => runGuarded(() => onOpenPlanAi(plan.id))}><Bot size={15} />计划 AI</button><button className="icon-button icon-button--bordered" type="button" onClick={() => runGuarded(() => setSettingsOpen(true))} aria-label="计划设置" title="计划设置"><Settings2 size={17} /></button><button className="button button--accent button--with-icon" type="button" onClick={addSubject}><Plus size={15} />科目</button></div>
      <dl className="plan-detail-summary"><div><dt>周期</dt><dd>{formatDateRange(plan.start_date, plan.end_date)}</dd></div><div><dt>总体进度</dt><dd>{plan.summary.progress}%</dd></div><div><dt>结构</dt><dd>{plan.summary.subject_count} 科目 · {plan.summary.task_count} 任务</dd></div><div><dt>计划学习量</dt><dd>{formatMinutes(plan.summary.estimate_minutes)}</dd></div></dl>
    </section>
    {error && <div className="workspace-alert" role="alert">{error}</div>}
    <nav className="plan-detail-tabs" aria-label="计划详情视图"><button className={tab === "overview" ? "is-active" : ""} onClick={() => chooseTab("overview")}>概览</button><button className={tab === "structure" ? "is-active" : ""} onClick={() => chooseTab("structure")}>结构</button><button className={tab === "schedule" ? "is-active" : ""} onClick={() => chooseTab("schedule")}>排期</button></nav>
    <div className="plan-detail-content">
      {tab === "overview" ? <PlanOverview plan={plan} schedule={schedule} busyTaskId={busyTaskId} onOpenTask={(taskId) => chooseTab("structure", taskId)} onToggleCompletion={(task) => void toggleCompletion(task)} onOpenTaskAi={(taskId) => runGuarded(() => onOpenTaskAi(taskId))} /> : tab === "structure" ? <PlanStructure ref={structureRef} plan={plan} targetTaskId={targetTaskId} addSubjectRequest={addSubjectRequest} runGuarded={runGuarded} onRefresh={refreshPlan} onOpenTaskAi={onOpenTaskAi} /> : <PlanSchedule tasks={schedule} busyTaskId={busyTaskId} onOpenTask={(taskId) => chooseTab("structure", taskId)} onToggleCompletion={(task) => void toggleCompletion(task)} onOpenTaskAi={(taskId) => runGuarded(() => onOpenTaskAi(taskId))} onReschedule={(taskId, days) => void shiftTask(taskId, days)} onOpenCalendar={() => runGuarded(() => onOpenCalendar(plan.id))} />}
    </div>
    {settingsOpen && <DialogPortal><div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) requestSettingsClose(); }}><section className="plan-settings-dialog" role="dialog" aria-modal="true" aria-label="计划设置"><GoalEditorForm ref={settingsRef} plan={plan} busy={mutationBusy} onDirtyChange={setSettingsDirty} onDelete={() => setDeletePlanOpen(true)} onSave={async (payload) => { setMutationBusy(true); setError(""); try { await updatePlan(plan.id, payload); await refreshPlan(); } catch (reason: unknown) { setError(reason instanceof Error ? reason.message : "计划更新失败"); throw reason; } finally { setMutationBusy(false); } }} /><button className="plan-settings-close" type="button" onClick={requestSettingsClose} aria-label="关闭计划设置">关闭</button></section></div></DialogPortal>}
    {deletePlanOpen && <ConfirmDialog title={`删除计划“${plan.title}”？`} description="计划及其科目、主题和任务会从工作区隐藏，已有本地数据仍保留。" busy={mutationBusy} onCancel={() => setDeletePlanOpen(false)} onConfirm={() => void deleteCurrentPlan()} />}
    {settingsClosePending && <UnsavedChangesDialog busy={mutationBusy} onContinue={() => setSettingsClosePending(false)} onDiscard={discardSettingsAndClose} onSave={() => void saveSettingsAndClose()} />}
    {pendingAction && <UnsavedChangesDialog busy={guardBusy} onContinue={() => setPendingAction(null)} onDiscard={() => { structureRef.current?.discard(); const action = pendingAction; setPendingAction(null); action(); }} onSave={() => void savePendingAndContinue()} />}
  </div>;
}

function PlanPortfolioMetrics({ summaries }: { summaries: PlanSummary[] }) {
  const tasks = summaries.reduce((sum, plan) => sum + plan.task_count, 0);
  const completed = summaries.reduce((sum, plan) => sum + plan.completed_task_count, 0);
  const progress = tasks ? Math.round(completed / tasks * 100) : 0;
  return <section className="plan-portfolio-metrics" aria-label="计划总体指标"><div><span>活动计划</span><strong>{summaries.filter((plan) => plan.status === "active").length}</strong></div><div><span>全部任务</span><strong>{tasks}</strong></div><div><span>整体完成</span><strong>{progress}%</strong></div><div><span>预计学习量</span><strong>{formatMinutes(summaries.reduce((sum, plan) => sum + plan.estimate_minutes, 0))}</strong></div></section>;
}

function readPlanLocation(): { planId: string | null; tab: PlanTab; node: string | null } {
  const params = new URLSearchParams(window.location.search);
  const rawTab = params.get("tab");
  return { planId: params.get("plan"), tab: rawTab === "structure" || rawTab === "schedule" ? rawTab : "overview", node: params.get("node") };
}

function writePlanLocation(planId: string | null, tab: PlanTab, node: string | null, replace = false) {
  const url = new URL(window.location.href);
  url.searchParams.set("view", "plans");
  if (planId) {
    url.searchParams.set("plan", planId);
    url.searchParams.set("tab", tab);
  } else {
    url.searchParams.delete("plan");
    url.searchParams.delete("tab");
  }
  if (node) url.searchParams.set("node", node); else url.searchParams.delete("node");
  window.history[replace ? "replaceState" : "pushState"]({}, "", url);
}

function restoreLastTab(planId: string): PlanTab | null {
  try {
    const values = JSON.parse(sessionStorage.getItem(LAST_TAB_KEY) ?? "{}") as Record<string, PlanTab>;
    return values[planId] ?? null;
  } catch { return null; }
}

function storeLastTab(planId: string, tab: PlanTab) {
  try {
    const values = JSON.parse(sessionStorage.getItem(LAST_TAB_KEY) ?? "{}") as Record<string, PlanTab>;
    values[planId] = tab;
    sessionStorage.setItem(LAST_TAB_KEY, JSON.stringify(values));
  } catch { /* The default overview remains available. */ }
}

function formatDateRange(start: string, end: string) {
  const formatter = new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "numeric", day: "numeric" });
  return `${formatter.format(new Date(`${start}T00:00:00`))} - ${formatter.format(new Date(`${end}T00:00:00`))}`;
}

function formatMinutes(minutes: number) {
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours} 小时 ${remainder} 分` : `${hours} 小时`;
}
