import { useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { BookOpen, Bot, ChevronLeft, ChevronRight, Compass, History, LogOut, Menu, MessageSquareText, Settings2, X } from "lucide-react";
import { getAiProvider, type Health, type AiProvider, type AiContextScope, type Identity, type LearningRoomBrief } from "./api";
import AiLearningRoom from "./AiLearningRoom";
import AiCompanionPanel from "./AiCompanionPanel";
import AiProviderDialog from "./AiProviderDialog";
import DialogPortal from "./DialogPortal";
import FactWorkspace from "./FactWorkspace";
import LearningPlans from "./LearningPlans";
import LearningRecords from "./LearningRecords";

type WorkspaceView = "home" | "plans" | "records";
type AiRoomEntry = { scope: AiContextScope; targetId: string | null; initialDraft?: string; learningBrief?: LearningRoomBrief };
const navigation = [
  { id: "home", label: "学习首页", icon: Compass },
  { id: "plans", label: "学习计划", icon: BookOpen },
  { id: "records", label: "学习记录", icon: History },
] as const;

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
      contextScope?: unknown; open?: unknown; initialDraft?: unknown; learningBrief?: unknown;
    };
    if (parsed.open !== true || parsed.contextScope !== "independent") return null;
    const learningBrief = parsed.learningBrief && typeof parsed.learningBrief === "object"
      ? parsed.learningBrief as LearningRoomBrief
      : undefined;
    const initialDraft = typeof parsed.initialDraft === "string" ? parsed.initialDraft : undefined;
    return { scope: "independent", targetId: null, initialDraft, learningBrief };
  } catch {
    return null;
  }
}


export default function Workspace({ health, identity, onLogout }: {
  health: Health | null; identity: Identity | null; onLogout: () => Promise<void>;
}) {
  const [view, setView] = useState<WorkspaceView>(restoredWorkspaceView);
  const [mode, setMode] = useState<"manage" | "ai">(() => restoredAiEntry() ? "ai" : "manage");
  const [aiEntry, setAiEntry] = useState<AiRoomEntry>(() => restoredAiEntry() ?? { scope: "independent", targetId: null });
  const [aiProvider, setAiProvider] = useState<AiProvider | null>(null);
  const [providerDialogOpen, setProviderDialogOpen] = useState(false);
  const [companionDrawerOpen, setCompanionDrawerOpen] = useState(false);
  const [companionExpanded, setCompanionExpanded] = useState(false);
  const [error, setError] = useState("");
  const [pageKey, setPageKey] = useState(0);
  const [creation, setCreation] = useState<{ planId?: string } | null>(null);
  const [v6Layout, setV6Layout] = useState<V6Layout>(restoredV6Layout);
  const v6LayoutRef = useRef(v6Layout);
  useEffect(() => { v6LayoutRef.current = v6Layout; }, [v6Layout]);
  useEffect(() => { getAiProvider().then(result => setAiProvider(result.provider)).catch(reason => setError(reason.message)); }, []);
  useEffect(() => {
    const pop = () => { closeStoredRoom(); setView(restoredWorkspaceView()); setMode("manage"); setCreation(null); setPageKey(key => key + 1); };
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  useEffect(() => {
    if (!companionDrawerOpen) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setCompanionDrawerOpen(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [companionDrawerOpen]);
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


  function chooseView(next: WorkspaceView, params: Record<string, string> = {}) {
    closeStoredRoom();
    setView(next); setMode("manage"); setCreation(null); setPageKey(key => key + 1);
    if (window.matchMedia("(max-width: 760px)").matches) persistV6Layout({ ...v6Layout, collapsed: false });
    const url = new URL(window.location.href);
    url.search = new URLSearchParams({ view: next, ...params }).toString();
    window.history.pushState({}, "", url);
  }
  function create(planId?: string) { chooseView("home"); setCreation({ planId }); }
  function openRecord(id: string, verificationId?: string | null) {
    chooseView("records", { record: id, ...(verificationId ? { verification: verificationId } : {}) });
  }
  function openRoom(initialDraft: string, learningBrief?: LearningRoomBrief) {
    openAiEntry({ scope: "independent", targetId: null, initialDraft, learningBrief });
  }
  function openAiEntry(entry: AiRoomEntry) {
    try {
      const raw = window.sessionStorage.getItem(AI_ROOM_SESSION_KEY);
      const previous = raw ? JSON.parse(raw) as Record<string, unknown> : {};
      const sameEntry = previous.contextScope === entry.scope && previous.targetId === entry.targetId && (previous.learningBrief as LearningRoomBrief | undefined)?.delegation_id === entry.learningBrief?.delegation_id;
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


  function closeAiLearning() { closeStoredRoom(); setMode("manage"); setCreation(null); setPageKey(key => key + 1); }
  const workspaceStyle = { "--v6-rail-width": `${v6Layout.collapsed ? 58 : v6Layout.rail}px`, "--v6-companion-width": `${v6Layout.companion}px` } as CSSProperties;
  return <main className={`app-shell v6-workspace${v6Layout.collapsed ? " is-rail-collapsed" : ""}${!companionExpanded ? " is-companion-collapsed" : ""}${mode === "ai" ? " is-ai-mode" : ""}`} style={workspaceStyle}>
    {mode === "manage" && <>
      <aside className="v6-rail">
        <button className="v6-rail-toggle" type="button" onClick={() => persistV6Layout({ ...v6Layout, collapsed: !v6Layout.collapsed })} aria-label={v6Layout.collapsed ? "展开导航" : "收起导航"}>{v6Layout.collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}</button>
        <div className="v6-brand"><span className="v6-brand-mark">N</span><div className="v6-rail-copy"><strong>学海无涯</strong><small>NAUTILUS / LOCAL</small></div></div>
        <nav className="v6-rail-nav" aria-label="工作区视图">
          {navigation.map(({ id, label, icon: Icon }, index) => <button key={id} aria-label={label} aria-current={view === id ? "page" : undefined} title={label} className={view === id ? "is-active" : ""} onClick={() => chooseView(id)}><Icon size={16} /><span>{label}</span><small>0{index + 1}</small></button>)}
        </nav>
        <div className="v6-rail-local"><span className="status-dot" /><div className="v6-rail-copy"><strong>{identity?.display_name ?? "本地学习者"}</strong><small>{health?.status === "ok" ? "本地服务在线" : "正在检查服务"}</small></div></div>
      </aside>
      <div className="v6-resizer v6-resizer--rail" role="separator" aria-label="调整左栏宽度" onPointerDown={event => resizeColumn("rail", event)} />
    </>}
    <section className="v6-main-column">
      <header className="app-header">
        <div className="brand-lockup">
          {mode === "manage" && <button className="v6-mobile-nav-toggle" type="button" onClick={() => persistV6Layout({ ...v6Layout, collapsed: !v6Layout.collapsed })} aria-label={v6Layout.collapsed ? "关闭导航" : "打开导航"}><Menu size={17} /></button>}
          <span className="v6-coordinate">{mode === "ai" ? "学习室" : navigation.find(item => item.id === view)?.label}</span>
        </div>
        <div className="workspace-actions">
          {mode === "manage" && <>
            <button className="icon-button" type="button" onClick={() => openRoom("")} aria-label="学习室" title="学习室"><MessageSquareText size={17} /></button>
            <button className="icon-button v6-companion-toggle" type="button" onClick={() => setCompanionExpanded(!companionExpanded)} aria-expanded={companionExpanded} aria-label={companionExpanded ? "收起 AI 学习伙伴" : "打开 AI 学习伙伴"}><Bot size={17} /></button>
            <button className="icon-button v6-compact-companion-trigger" type="button" onClick={() => setCompanionDrawerOpen(true)} aria-label="打开 AI 学习伙伴"><Bot size={17} /></button>
          </>}
          <button className="icon-button" onClick={() => setProviderDialogOpen(true)} title="提供方设置" aria-label="提供方设置"><Settings2 size={18} /></button>
          <button className="icon-button" onClick={onLogout} title="退出会话" aria-label="退出会话"><LogOut size={18} /></button>
        </div>
      </header>
      {error && <div className="workspace-alert" role="alert">{error}</div>}
      {mode === "ai" ? <AiLearningRoom task={null} contextScope={aiEntry.scope} targetId={aiEntry.targetId} initialDraft={aiEntry.initialDraft} learningBrief={aiEntry.learningBrief} provider={aiProvider} onBack={closeAiLearning} onProviderOpen={() => setProviderDialogOpen(true)} />
        : view === "home" ? <FactWorkspace key={pageKey} creation={creation} onOpenPlans={id => chooseView("plans", id ? { plan: id } : {})} onOpenRecord={openRecord} onOpenLearningRoom={openRoom} />
        : view === "plans" ? <LearningPlans key={pageKey} onCreate={create} onOpenRecord={openRecord} onLearning={brief => openRoom("", brief)} />
        : <LearningRecords key={pageKey} onClose={() => chooseView("home")} onLearning={brief => openRoom("", brief)} />}
      <AiProviderDialog open={providerDialogOpen} provider={aiProvider} onClose={() => setProviderDialogOpen(false)} onChanged={setAiProvider} />
    </section>
    {mode === "manage" && <>
      <div className="v6-resizer v6-resizer--companion" role="separator" aria-label="调整 AI 伙伴栏宽度" onPointerDown={event => resizeColumn("companion", event)} />
      <AiCompanionPanel provider={aiProvider} onOpenLearning={() => openRoom("")} onOpenProvider={() => setProviderDialogOpen(true)} />
    </>}
    {mode === "manage" && companionDrawerOpen && <DialogPortal><div className="v6-companion-drawer-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setCompanionDrawerOpen(false); }}><section className="v6-companion-drawer" role="dialog" aria-modal="true" aria-label="AI 学习伙伴抽屉"><button className="icon-button v6-companion-drawer-close" type="button" onClick={() => setCompanionDrawerOpen(false)} aria-label="关闭 AI 学习伙伴"><X size={17} /></button><AiCompanionPanel provider={aiProvider} onOpenLearning={() => { setCompanionDrawerOpen(false); openRoom(""); }} onOpenProvider={() => { setCompanionDrawerOpen(false); setProviderDialogOpen(true); }} /></section></div></DialogPortal>}
  </main>;
}
function restoredWorkspaceView(): WorkspaceView {
  const params = new URLSearchParams(window.location.search);
  if (params.has("record")) return "records";
  const value = params.get("view");
  return value === "plans" || value === "records" ? value : "home";
}
function closeStoredRoom() {
  try {
    const raw = window.sessionStorage.getItem(AI_ROOM_SESSION_KEY);
    if (raw) window.sessionStorage.setItem(AI_ROOM_SESSION_KEY, JSON.stringify({ ...JSON.parse(raw), open: false }));
  } catch { /* Navigation remains usable without browser storage. */ }
}
