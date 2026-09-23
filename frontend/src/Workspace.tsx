import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { BookOpen, Bot, ChevronLeft, ChevronRight, Compass, LogOut, Menu, MessageSquareText, Settings2, X } from "lucide-react";
import {
  getAiProvider,
  getLayout,
  getLayoutTemplates,
  getPlanSummaries,
  getTasks,
  getTodayDashboard,
  rescheduleTask,
  setTaskCompletion,
  timerSocket,
  updateTimer,
  type Health,
  type AiProvider,
  type AiContextScope,
  type Identity,
  type LearningRoomBrief,
  type LayoutConfig,
  type LayoutTemplate,
  type ManualPlanInput,
  type PlanDetail,
  type PlanSummary,
  type Task,
  type TimerSnapshot,
  type TodayDashboard,
} from "./api";
import AiLearningRoom from "./AiLearningRoom";
import AiCompanionPanel from "./AiCompanionPanel";
import AiProviderDialog from "./AiProviderDialog";
import FloatingTimer from "./FloatingTimer";
import LayoutDialog from "./LayoutDialog";
import PlanWorkspace from "./PlanWorkspace";
import TodayView from "./TodayView";
import TaskListView from "./TaskListView";
import CalendarView from "./CalendarView";
import DialogPortal from "./DialogPortal";
import FactWorkspace from "./FactWorkspace";

type WorkspaceView = "today" | "tasks" | "calendar" | "plans" | "facts";
type WorkspaceMode = "manage" | "ai";
type AiRoomEntry = {
  scope: AiContextScope;
  targetId: string | null;
  initialDraft?: string;
  learningBrief?: LearningRoomBrief;
};

const AI_ROOM_SESSION_KEY = "nautilus.ai.learning-room";
const V6_LAYOUT_KEY = "nautilus.v6.workspace-layout";

type V6Layout = { collapsed: boolean; rail: number; companion: number };
const defaultV6Layout: V6Layout = { collapsed: false, rail: 196, companion: 320 };

function restoredV6Layout(): V6Layout {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(V6_LAYOUT_KEY) ?? "null") as Partial<V6Layout> | null;
    return {
      collapsed: parsed?.collapsed === true,
      rail: typeof parsed?.rail === "number" ? Math.min(240, Math.max(144, parsed.rail)) : defaultV6Layout.rail,
      companion: typeof parsed?.companion === "number" ? Math.min(420, Math.max(260, parsed.companion)) : defaultV6Layout.companion,
    };
  } catch {
    return defaultV6Layout;
  }
}

function restoredAiEntry(): AiRoomEntry | null {
  try {
    const raw = window.sessionStorage.getItem(AI_ROOM_SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as {
      taskId?: unknown;
      contextScope?: unknown;
      targetId?: unknown;
      open?: unknown;
      initialDraft?: unknown;
      learningBrief?: unknown;
    };
    if (parsed.open !== true) return null;
    const legacyTask = typeof parsed.taskId === "string" ? parsed.taskId : null;
    const scope = parsed.contextScope === "global" || parsed.contextScope === "plan" || parsed.contextScope === "task" || parsed.contextScope === "independent"
      ? parsed.contextScope
      : legacyTask ? "task" : "independent";
    const targetId = typeof parsed.targetId === "string" ? parsed.targetId : legacyTask;
    if ((scope === "plan" || scope === "task") && !targetId) return null;
    const learningBrief = parsed.learningBrief && typeof parsed.learningBrief === "object"
      ? parsed.learningBrief as LearningRoomBrief
      : undefined;
    const initialDraft = typeof parsed.initialDraft === "string" ? parsed.initialDraft : undefined;
    return { scope, targetId, initialDraft, learningBrief };
  } catch {
    return null;
  }
}

const defaultLayout: LayoutConfig = {
  modules: [
    { id: "summary", visible: true },
    { id: "tasks", visible: true },
    { id: "timer", visible: true },
    { id: "context", visible: true },
  ],
  source_template_id: "system-today-cockpit",
  updated_at: null,
};

export default function Workspace({
  health,
  identity,
  onLogout,
}: {
  health: Health | null;
  identity: Identity | null;
  onLogout: () => Promise<void>;
}) {
  const [view, setView] = useState<WorkspaceView>(() => restoredWorkspaceView());
  const [mode, setMode] = useState<WorkspaceMode>(() => restoredAiEntry() ? "ai" : "manage");
  const [aiEntry, setAiEntry] = useState<AiRoomEntry>(() => restoredAiEntry() ?? { scope: "global", targetId: null });
  const [dashboard, setDashboard] = useState<TodayDashboard | null>(null);
  const [planSummaries, setPlanSummaries] = useState<PlanSummary[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [layout, setLayout] = useState<LayoutConfig>(defaultLayout);
  const [layoutTemplates, setLayoutTemplates] = useState<LayoutTemplate[]>([]);
  const [aiProvider, setAiProvider] = useState<AiProvider | null>(null);
  const [activePlanContext, setActivePlanContext] = useState<PlanDetail | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [timer, setTimer] = useState<TimerSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [layoutDialogOpen, setLayoutDialogOpen] = useState(false);
  const [providerDialogOpen, setProviderDialogOpen] = useState(false);
  const [companionDrawerOpen, setCompanionDrawerOpen] = useState(false);
  const [companionExpanded, setCompanionExpanded] = useState(false);
  const [calendarPlanId, setCalendarPlanId] = useState<string | null>(() => restoredCalendarPlanFilter());
  const [v6Layout, setV6Layout] = useState<V6Layout>(() => restoredV6Layout());
  const v6LayoutRef = useRef(v6Layout);
  const mainColumnRef = useRef<HTMLElement>(null);

  useEffect(() => {
    v6LayoutRef.current = v6Layout;
  }, [v6Layout]);

  useEffect(() => {
    if (!companionDrawerOpen) return;
    const close = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setCompanionDrawerOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [companionDrawerOpen]);

  useEffect(() => {
    const onPopState = () => {
      const nextView = restoredWorkspaceView();
      setView(nextView);
      setMode("manage");
      setCalendarPlanId(restoredCalendarPlanFilter());
      if (nextView !== "plans") setActivePlanContext(null);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const loadWorkspace = useCallback(async () => {
    try {
      const [nextDashboard, nextPlanSummaries, nextTasks, nextLayout, nextTemplates, providerResult] = await Promise.all([
        getTodayDashboard(),
        getPlanSummaries(),
        getTasks(),
        getLayout(),
        getLayoutTemplates(),
        getAiProvider(),
      ]);
      setDashboard(nextDashboard);
      setPlanSummaries(nextPlanSummaries);
      setTasks(nextTasks);
      setLayout(nextLayout);
      setLayoutTemplates(nextTemplates);
      setAiProvider(providerResult.provider);
      setTimer(nextDashboard.active_timer);
      setSelectedTaskId((current) => {
        const allIds = nextTasks.map((task) => task.id);
        if (current && allIds.includes(current)) return current;
        const restored = restoredAiEntry();
        if (restored?.scope === "task" && restored.targetId && allIds.includes(restored.targetId)) return restored.targetId;
        return nextDashboard.active_timer?.task_id ?? nextDashboard.tasks[0]?.id ?? allIds[0] ?? null;
      });
      setError("");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "工作区加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  useEffect(() => {
    if (!timer?.task_id) return;
    const socket = timerSocket(timer.task_id);
    socket.onmessage = (event) => {
      const next = JSON.parse(event.data) as TimerSnapshot | null;
      setTimer(next);
      if (!next) void loadWorkspace();
    };
    return () => socket.close();
  }, [timer?.task_id, loadWorkspace]);

  const allTasks = useMemo(() => tasks, [tasks]);
  const selectedTask =
    dashboard?.tasks.find((task) => task.id === selectedTaskId) ??
    allTasks.find((task) => task.id === selectedTaskId) ??
    null;
  const timerTask = timer ? allTasks.find((task) => task.id === timer.task_id) ?? selectedTask : null;
  const companionContext = activePlanContext
    ? { scope: "plan" as const, plan: activePlanContext }
    : { scope: "global" as const, plans: planSummaries, dashboard };

  function persistV6Layout(next: V6Layout) {
    setV6Layout(next);
    try { window.localStorage.setItem(V6_LAYOUT_KEY, JSON.stringify(next)); } catch { /* Layout remains usable without storage. */ }
  }

  function resizeColumn(kind: "rail" | "companion", event: ReactPointerEvent<HTMLDivElement>) {
    if (window.matchMedia("(max-width: 1180px)").matches) return;
    const root = event.currentTarget.closest(".v6-workspace") as HTMLElement | null;
    if (!root) return;
    const startX = event.clientX;
    const startValue = kind === "rail" ? v6Layout.rail : v6Layout.companion;
    event.currentTarget.setPointerCapture(event.pointerId);
    const target = event.currentTarget;
    const onMove = (moveEvent: PointerEvent) => {
      const delta = moveEvent.clientX - startX;
      const nextValue = kind === "rail"
        ? Math.min(240, Math.max(144, startValue + delta))
        : Math.min(420, Math.max(260, startValue - delta));
      setV6Layout((current) => ({ ...current, [kind]: nextValue }));
    };
    const onEnd = () => {
      target.removeEventListener("pointermove", onMove);
      target.removeEventListener("pointerup", onEnd);
      try { window.localStorage.setItem(V6_LAYOUT_KEY, JSON.stringify(v6LayoutRef.current)); } catch { /* Layout remains usable without storage. */ }
    };
    target.addEventListener("pointermove", onMove);
    target.addEventListener("pointerup", onEnd, { once: true });
  }

  function chooseView(next: WorkspaceView) {
    setView(next);
    setMode("manage");
    if (window.matchMedia("(max-width: 760px)").matches) {
      persistV6Layout({ ...v6Layout, collapsed: false });
    }
    setCalendarPlanId(null);
    const url = new URL(window.location.href);
    url.searchParams.set("view", next);
    url.searchParams.delete("plan_filter");
    if (next !== "plans") {
      url.searchParams.delete("plan");
      url.searchParams.delete("tab");
      url.searchParams.delete("node");
      setActivePlanContext(null);
    }
    window.history.pushState({}, "", url);
  }

  function openPlanCalendar(planId: string) {
    setView("calendar");
    setMode("manage");
    setCalendarPlanId(planId);
    setActivePlanContext(null);
    const url = new URL(window.location.href);
    url.searchParams.set("view", "calendar");
    url.searchParams.set("plan_filter", planId);
    url.searchParams.delete("plan");
    url.searchParams.delete("tab");
    url.searchParams.delete("node");
    window.history.pushState({}, "", url);
  }

  function clearCalendarPlanFilter() {
    setCalendarPlanId(null);
    const url = new URL(window.location.href);
    url.searchParams.delete("plan_filter");
    window.history.replaceState({}, "", url);
  }

  async function handleTimer(
    action: "start" | "pause" | "resume" | "finish",
    config?: Pick<ManualPlanInput, "timer_mode" | "work_minutes" | "break_minutes">,
  ) {
    if (!selectedTask) return;
    setBusy(true);
    setError("");
    try {
      const next = await updateTimer(selectedTask.id, action, config);
      setTimer(next);
      if (!next) await loadWorkspace();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "计时操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleTaskTimerStart(taskId: string): Promise<boolean> {
    const task = tasks.find((item) => item.id === taskId);
    if (!task) return false;
    setSelectedTaskId(taskId);
    setBusy(true);
    setError("");
    try {
      const next = await updateTimer(taskId, "start", {
        timer_mode: task.timer_mode,
        work_minutes: task.work_minutes,
        break_minutes: task.break_minutes,
      });
      setTimer(next);
      await loadWorkspace();
      return Boolean(next);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "计时操作失败");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function handleFloatingTimer(taskId: string, action: "pause" | "resume" | "finish") {
    setBusy(true);
    setError("");
    try {
      const next = await updateTimer(taskId, action);
      setTimer(next);
      if (!next) await loadWorkspace();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "计时操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleComplete(taskId: string) {
    setBusy(true);
    setError("");
    try {
      const task = dashboard?.tasks.find((item) => item.id === taskId) ?? tasks.find((item) => item.id === taskId);
      await setTaskCompletion(taskId, task?.status !== "completed");
      await loadWorkspace();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "任务更新失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleReschedule(taskId: string, days: number) {
    setBusy(true);
    setError("");
    try {
      await rescheduleTask(taskId, days);
      await loadWorkspace();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "任务排期更新失败");
    } finally {
      setBusy(false);
    }
  }

  function openAiLearning(taskId: string) {
    openAiEntry({ scope: "task", targetId: taskId });
    setSelectedTaskId(taskId);
  }

  function openAiEntry(entry: AiRoomEntry) {
    try {
      const raw = window.sessionStorage.getItem(AI_ROOM_SESSION_KEY);
      const previous = raw ? JSON.parse(raw) as Record<string, unknown> : {};
      const sameEntry = previous.contextScope === entry.scope && previous.targetId === entry.targetId;
      window.sessionStorage.setItem(AI_ROOM_SESSION_KEY, JSON.stringify({
        ...previous,
        taskId: entry.scope === "task" ? entry.targetId : null,
        contextScope: entry.scope,
        targetId: entry.targetId,
        initialDraft: entry.initialDraft,
        learningBrief: entry.learningBrief,
        conversationId: sameEntry && typeof previous.conversationId === "string" ? previous.conversationId : null,
        runId: sameEntry && typeof previous.runId === "string" ? previous.runId : null,
        pending: undefined,
        draftConfig: null,
        open: true,
      }));
    } catch {
      // Learning room remains usable without browser storage.
    }
    setAiEntry(entry);
    setMode("ai");
  }

  function closeAiLearning() {
    try {
      const raw = window.sessionStorage.getItem(AI_ROOM_SESSION_KEY);
      if (raw) {
        const previous = JSON.parse(raw) as Record<string, unknown>;
        window.sessionStorage.setItem(AI_ROOM_SESSION_KEY, JSON.stringify({ ...previous, open: false }));
      }
    } catch {
      // Learning room remains usable without browser storage.
    }
    setMode("manage");
    if (aiEntry.learningBrief) chooseView("facts");
  }

  const workspaceStyle = {
    "--v6-rail-width": `${v6Layout.collapsed ? 58 : v6Layout.rail}px`,
    "--v6-companion-width": `${v6Layout.companion}px`,
  } as CSSProperties;

  return (
    <main className={`app-shell v6-workspace${v6Layout.collapsed ? " is-rail-collapsed" : ""}${!companionExpanded ? " is-companion-collapsed" : ""}${mode === "ai" ? " is-ai-mode" : ""}${timer ? " has-active-timer" : ""}`} style={workspaceStyle}>
      {mode === "manage" && <aside className="v6-rail">
        <button
          className="v6-rail-toggle"
          type="button"
          onClick={() => persistV6Layout({ ...v6Layout, collapsed: !v6Layout.collapsed })}
          aria-label={v6Layout.collapsed ? "展开导航" : "收起导航"}
        >
          {v6Layout.collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
        </button>
        <div className="v6-brand">
          <span className="v6-brand-mark">N</span>
          <div className="v6-rail-copy"><strong>学海无涯</strong><small>NAUTILUS / LOCAL</small></div>
        </div>
        <span className="v6-rail-section">WORKSPACE</span>
        <nav className="v6-rail-nav" aria-label="工作区视图">
          <button className={view === "today" ? "is-active" : ""} onClick={() => chooseView("today")}><Compass size={16} /><span>今日</span><small>01</small></button>
          <button onClick={() => openAiEntry({ scope: "global", targetId: null })}><MessageSquareText size={16} /><span>学习室</span><small>02</small></button>
          <button className={view === "facts" ? "is-active" : ""} onClick={() => chooseView("facts")}><BookOpen size={16} /><span>开始学习</span><small>03</small></button>
        </nav>
        <span className="v6-rail-section">KNOWLEDGE</span>
        <button className="v6-rail-disabled" disabled title="知识库尚未实现"><BookOpen size={16} /><span>知识库（开发中）</span><small>04</small></button>
        <div className="v6-rail-local">
          <span className="status-dot" />
          <div className="v6-rail-copy"><strong>{identity?.display_name ?? "本地学习者"}</strong><small>{health?.status === "ok" ? "本地服务在线" : "正在检查服务"}</small></div>
        </div>
      </aside>}
      {mode === "manage" && <div className="v6-resizer v6-resizer--rail" role="separator" aria-label="调整左栏宽度" onPointerDown={(event) => resizeColumn("rail", event)} onDoubleClick={() => persistV6Layout({ ...v6Layout, rail: defaultV6Layout.rail })} />}

      <section className="v6-main-column" ref={mainColumnRef}>
      <header className="app-header">
        <div className="brand-lockup">
          <button
            className="v6-mobile-nav-toggle"
            type="button"
            onClick={() => persistV6Layout({ ...v6Layout, collapsed: !v6Layout.collapsed })}
            aria-label={v6Layout.collapsed ? "关闭导航" : "打开导航"}
          >
            <Menu size={17} />
          </button>
          <span className="v6-coordinate">{mode === "ai" ? "LEARNING SESSION" : `ROUTE / ${view.toUpperCase()}`} · {dashboard?.date ?? "LOCAL"}</span>
        </div>
        <div className="workspace-actions">
          {mode === "manage" && <span className="service-badge"><span className="status-dot" />{health?.status === "ok" ? "服务在线" : "检查中"}</span>}
          {mode === "manage" && <button className="icon-button v6-companion-toggle" type="button" onClick={() => setCompanionExpanded((expanded) => !expanded)} aria-expanded={companionExpanded} aria-label={companionExpanded ? "收起 AI 学习伙伴" : "打开 AI 学习伙伴"} title={companionExpanded ? "收起 AI 学习伙伴" : "打开 AI 学习伙伴"}><Bot size={17} /></button>}
          {mode === "manage" && <button className="icon-button v6-compact-companion-trigger" type="button" onClick={() => setCompanionDrawerOpen(true)} aria-label="打开 AI 学习伙伴" title="AI 学习伙伴"><Bot size={17} /></button>}
          {mode === "manage" && <button className="icon-button" onClick={() => setLayoutDialogOpen(true)} title="首页布局" aria-label="首页布局"><Settings2 size={18} /></button>}
          <button className="icon-button" onClick={onLogout} title="退出会话" aria-label="退出会话"><LogOut size={18} /></button>
        </div>
      </header>

      {error && <div className="workspace-alert" role="alert">{error}</div>}
      {loading ? (
        <div className="workspace-loading"><div className="signal-loader" /><span>正在整理学习路线</span></div>
      ) : mode === "ai" ? (
        <AiLearningRoom
          task={aiEntry.scope === "task" ? allTasks.find((task) => task.id === aiEntry.targetId) ?? selectedTask : null}
          contextScope={aiEntry.scope}
          targetId={aiEntry.targetId}
          initialDraft={aiEntry.initialDraft}
          learningBrief={aiEntry.learningBrief}
          provider={aiProvider}
          onBack={closeAiLearning}
          onProviderOpen={() => setProviderDialogOpen(true)}
        />
      ) : view === "facts" ? (
        <>
          <PerspectiveBar view={view} onChange={chooseView} />
          <FactWorkspace
            hasLegacyTasks={allTasks.length > 0}
            onOpenLegacyPlans={() => chooseView("plans")}
            onOpenLearningRoom={(initialDraft, learningBrief) => openAiEntry({ scope: "independent", targetId: null, initialDraft, learningBrief })}
          />
        </>
      ) : view === "today" ? (
        <>
          <PerspectiveBar view={view} onChange={chooseView} />
          <TodayView
            dashboard={dashboard}
            identity={identity}
            selectedTask={selectedTask}
            selectedTaskId={selectedTaskId}
            timer={timer}
            busy={busy}
            onSelectTask={setSelectedTaskId}
            onComplete={handleComplete}
            onTimer={handleTimer}
            onOpenAi={openAiLearning}
            onOpenFacts={() => chooseView("facts")}
            layoutModules={layout.modules}
          />
        </>
      ) : view === "tasks" ? (
        <>
          <PerspectiveBar view={view} onChange={chooseView} />
          <TaskListView
            tasks={tasks}
            busy={busy}
            onSelectTask={(taskId) => { setSelectedTaskId(taskId); chooseView("today"); }}
            onComplete={handleComplete}
            onReschedule={handleReschedule}
          />
        </>
      ) : view === "calendar" ? (
        <>
          <PerspectiveBar view={view} onChange={chooseView} />
          <CalendarView
            tasks={calendarPlanId ? tasks.filter((task) => task.goal_id === calendarPlanId) : tasks}
            planFilterTitle={calendarPlanId ? planSummaries.find((plan) => plan.id === calendarPlanId)?.title ?? "当前计划" : null}
            onClearPlanFilter={clearCalendarPlanFilter}
            onSelectTask={(taskId) => { setSelectedTaskId(taskId); chooseView("today"); }}
          />
        </>
      ) : (
        <>
          <PerspectiveBar view={view} onChange={chooseView} />
          <PlanWorkspace
            summaries={planSummaries}
            onRefreshSummaries={loadWorkspace}
            onOpenTaskAi={openAiLearning}
            onOpenPlanAi={(planId) => openAiEntry({ scope: "plan", targetId: planId })}
            onOpenCalendar={openPlanCalendar}
            onPlanContextChange={setActivePlanContext}
          />
        </>
      )}

      <LayoutDialog
        open={layoutDialogOpen}
        layout={layout}
        templates={layoutTemplates}
        onClose={() => setLayoutDialogOpen(false)}
        onChanged={(nextLayout, nextTemplates) => {
          setLayout(nextLayout);
          if (nextTemplates) setLayoutTemplates(nextTemplates);
        }}
      />
      <AiProviderDialog
        open={providerDialogOpen}
        provider={aiProvider}
        onClose={() => setProviderDialogOpen(false)}
        onChanged={setAiProvider}
      />
      <FloatingTimer
        timer={timer}
        task={timerTask}
        busy={busy}
        boundaryRef={mainColumnRef}
        onAction={(taskId, action) => void handleFloatingTimer(taskId, action)}
      />
      </section>

      {mode === "manage" && (
        <>
          <div className="v6-resizer v6-resizer--companion" role="separator" aria-label="调整 AI 伙伴栏宽度" onPointerDown={(event) => resizeColumn("companion", event)} onDoubleClick={() => persistV6Layout({ ...v6Layout, companion: defaultV6Layout.companion })} />
          <AiCompanionPanel
            context={companionContext}
            provider={aiProvider}
            onOpenLearning={() => openAiEntry(activePlanContext ? { scope: "plan", targetId: activePlanContext.id } : { scope: "global", targetId: null })}
            onOpenProvider={() => setProviderDialogOpen(true)}
          />
        </>
      )}
      {mode === "manage" && companionDrawerOpen && <DialogPortal><div className="v6-companion-drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setCompanionDrawerOpen(false); }}><section className="v6-companion-drawer" role="dialog" aria-modal="true" aria-label="AI 学习伙伴抽屉"><button className="icon-button v6-companion-drawer-close" type="button" onClick={() => setCompanionDrawerOpen(false)} aria-label="关闭 AI 学习伙伴"><X size={17} /></button><AiCompanionPanel context={companionContext} provider={aiProvider} onOpenLearning={() => { setCompanionDrawerOpen(false); openAiEntry(activePlanContext ? { scope: "plan", targetId: activePlanContext.id } : { scope: "global", targetId: null }); }} onOpenProvider={() => { setCompanionDrawerOpen(false); setProviderDialogOpen(true); }} /></section></div></DialogPortal>}
    </main>
  );
}

function restoredWorkspaceView(): WorkspaceView {
  const value = new URLSearchParams(window.location.search).get("view");
  return value === "tasks" || value === "calendar" || value === "plans" || value === "facts" ? value : "today";
}

function restoredCalendarPlanFilter(): string | null {
  const params = new URLSearchParams(window.location.search);
  return params.get("view") === "calendar" ? params.get("plan_filter") : null;
}

function PerspectiveBar({ view, onChange }: { view: WorkspaceView; onChange: (view: WorkspaceView) => void }) {
  return (
    <div className="workspace-perspective-bar">
      <span className="workspace-perspective-label">当前视角</span>
      <nav className="v6-perspective-tabs" aria-label="当前视角">
        <button className={view === "today" ? "is-active" : ""} onClick={() => onChange("today")}>今日</button>
        <button className={view === "tasks" ? "is-active" : ""} onClick={() => onChange("tasks")}>任务</button>
          <button className={view === "facts" ? "is-active" : ""} onClick={() => onChange("facts")}>开始学习</button>
        <button className={view === "plans" ? "is-active" : ""} onClick={() => onChange("plans")}>历史计划</button>
        <button className={view === "calendar" ? "is-active" : ""} onClick={() => onChange("calendar")}>日历</button>
        <button disabled title="甘特图开发中">甘特图</button>
      </nav>
    </div>
  );
}
