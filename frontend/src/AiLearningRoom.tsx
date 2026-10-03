import useConversationState, { isStateConflict, isStateRejected } from './useConversationState';
import ConversationStateNotice from './ConversationStateNotice';
import BranchMap from './BranchMap';
import useReplyHistory from "./useReplyHistory";
import { LearningChatPanel, LearningComposer, LearningMessage, LearningUserMessage, LearningReplyActions } from "./LearningRoomLayout";
import QuestionDiscussion from "./QuestionDiscussion";
import { setReviewLocation } from "./LearningRecords";
import { FormEvent, KeyboardEvent, useCallback, useEffect, useRef, useState, type ChangeEvent, type RefObject, type ReactNode } from "react";
import { ArrowLeft, Bot, Check, CircleAlert, History, ListChecks, MapPin, Pencil, Plus, RefreshCw, RotateCcw, ShieldCheck, Sparkles, Square, SlidersHorizontal, Trash2, X } from "lucide-react";
import LearningMarkdown from "./LearningMarkdown";
import SearchControls, { type SearchSelection } from "./SearchControls";
import OutboundApproval from './OutboundApproval';
import type { SearchTrace } from "./SearchResults";
import AssistantResponse, { type GenerationTrace } from "./AssistantResponse";
import HelpControls from "./HelpControls";
import HelpRecord, { HelpRecordFacts } from "./HelpRecord";
import ComposerAttachments from './ComposerAttachments';
import MessageAttachments from './MessageAttachments';
import { attachmentError } from './AttachmentSupport';
import TaskMaterials, { MaterialUse, emptySourceScope, webMaterialCandidates } from './TaskMaterials';
import {
  ApiError,
  recordLearningRoomEntry,
  recordAiHelpDisplay,
  cancelAiRun,
  branchAiConversation,
  clearAiConversationConfig,
  createAiConversation,
  deleteAiConversation,
  getAiConversation,
  getAiConversationConfig,
  getAiContextPreview,
  getLearningRoom,
  getReturnReview,
  chooseReturnReview,
  selectLearningRoomConversation,
  regenerateAiConversationTitle,
  listAiProviders,
  listAiConversations,
  renameAiConversation,
  setAiConversationConfig,
  sendAiMessage,
  streamAiRun,
  type AiConversation,
  type AiConversationDetail,
  type AiMessage,
  type HelpRequestKind,
  type TeachingSelection,
  type TeachingAction,
  type AiProvider,
  type AiProviderModel,
  type AiConversationConfig,
  type AiContextScope,
  type AiLearningContext,
  type AiRun,
  type AiStreamEvent,
  type SourceScope,
  type MaterialVersion,
  type LearningRoomBrief,
  type Task,
} from "./api";
import DialogPortal from "./DialogPortal";
import useDismissibleLayer from "./useDismissibleLayer";
import LearningVerification from "./LearningVerification";
import LearningPosition from "./LearningPosition";
import TeachingState, { conversationTeachingEntries } from './TeachingState';
import LearningCompletion from "./LearningCompletion";

const SESSION_KEY = "nautilus.ai.learning-room";
const MAX_RECONNECT_ATTEMPTS = 3;
const LEARNING_PROMPT_ID_PREFIX = "learning-start:";

type RoomStatus = "loading" | "idle" | "submitting" | "streaming" | "reconnecting" | "succeeded" | "failed" | "canceled";

type PendingSubmission = {
  taskId: string | null;
  contextScope: AiContextScope;
  targetId: string | null;
  conversationId: string | null;
  clientMessageId: string;
  search?: SearchSelection;
  publicQuery?: string;
  sourceScope?: SourceScope;
  attachmentVersionIds?: string[];
  helpRequest?: HelpRequestKind | null;
  teachingMode?: TeachingSelection | null;
  teachingAction?: TeachingAction | null;
  regenerateMessageId?: string;
  editMessageId?: string;
  parentMessageId?: string;
};

type DraftConfig = {
  providerProfileId: string;
  providerModelId: string;
};

type RoomSession = {
  taskId: string | null;
  contextScope: AiContextScope;
  targetId: string | null;
  conversationId: string | null;
  runId: string | null;
  initialDraft?: string | null;
  open?: boolean;
  pending?: PendingSubmission;
  draftConfig?: DraftConfig | null;
  learningBrief?: LearningRoomBrief;
};

function readSession(): RoomSession | null {
  try {
    const raw = window.sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<RoomSession>;
    const legacyTaskId = typeof parsed.taskId === "string" ? parsed.taskId : null;
    const contextScope = isContextScope(parsed.contextScope)
      ? parsed.contextScope
      : legacyTaskId ? "task" : "independent";
    const targetId = typeof parsed.targetId === "string" ? parsed.targetId : legacyTaskId;
    return {
      taskId: legacyTaskId,
      contextScope,
      targetId,
      conversationId: typeof parsed.conversationId === "string" ? parsed.conversationId : null,
      runId: typeof parsed.runId === "string" ? parsed.runId : null,
      initialDraft: typeof parsed.initialDraft === "string" ? parsed.initialDraft : null,
      open: parsed.open === true,
      pending: parsed.pending && typeof parsed.pending === "object"
        ? {
            taskId: typeof parsed.pending.taskId === "string" ? parsed.pending.taskId : null,
            contextScope: isContextScope(parsed.pending.contextScope)
              ? parsed.pending.contextScope
              : typeof parsed.pending.taskId === "string" ? "task" : "independent",
            targetId: typeof parsed.pending.targetId === "string"
              ? parsed.pending.targetId
              : typeof parsed.pending.taskId === "string" ? parsed.pending.taskId : null,
            conversationId: typeof parsed.pending.conversationId === "string" ? parsed.pending.conversationId : null,
            regenerateMessageId: parsed.pending.regenerateMessageId,
            editMessageId: parsed.pending.editMessageId,
            parentMessageId: parsed.pending.parentMessageId,
            clientMessageId: typeof parsed.pending.clientMessageId === "string" ? parsed.pending.clientMessageId : "",
            search: parsed.pending.search && typeof parsed.pending.search === "object" && ["off", "external", "native"].includes(parsed.pending.search.mode) ? parsed.pending.search : undefined,
            attachmentVersionIds: Array.isArray(parsed.pending.attachmentVersionIds) ? parsed.pending.attachmentVersionIds.filter((value): value is string => typeof value === 'string') : [],
            sourceScope: parsed.pending.sourceScope && ['unspecified', 'reference', 'only'].includes(parsed.pending.sourceScope.mode) && Array.isArray(parsed.pending.sourceScope.version_ids) ? parsed.pending.sourceScope : undefined,
            helpRequest: ["hint", "explain_step", "example", "try_first"].includes(parsed.pending.helpRequest ?? "") ? parsed.pending.helpRequest : null,
            teachingMode: ['stepwise', 'socratic', 'feynman', 'default'].includes(parsed.pending.teachingMode ?? '') ? parsed.pending.teachingMode : null,
            teachingAction: ['practice', 'retell', 'continue'].includes(parsed.pending.teachingAction ?? '') ? parsed.pending.teachingAction : null,
          }
        : undefined,
      learningBrief: parsed.learningBrief,
      draftConfig: parsed.draftConfig && typeof parsed.draftConfig === "object"
        && typeof parsed.draftConfig.providerProfileId === "string"
        && typeof parsed.draftConfig.providerModelId === "string"
        ? {
            providerProfileId: parsed.draftConfig.providerProfileId,
            providerModelId: parsed.draftConfig.providerModelId,
          }
        : null,
    };
  } catch {
    return null;
  }
}

function isContextScope(value: unknown): value is AiContextScope {
  return value === "independent" || value === "global" || value === "plan" || value === "task";
}

function writeSession(session: RoomSession | null) {
  try {
    if (!session) window.sessionStorage.removeItem(SESSION_KEY);
    else window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({
      ...session,
      pending: session.pending ? {
        ...session.pending,
        publicQuery: undefined,
      } : undefined,
    }));
  } catch {
    // Storage may be unavailable in private browsing; in-memory state still works.
  }
}

function makeClientMessageId() {
  return typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

function fallbackConversationTitle(content: string) {
  const cleaned = content
    .replace(/^\s*(?:#{1,6}\s*|[-*+]\s+|\d+[.)、]\s*)/, "")
    .replace(/[`*_~]+/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^[，。！？!?：:；;、—\-"'“”‘’\s]+|[，。！？!?：:；;、—\-"'“”‘’\s]+$/g, "");
  return cleaned.slice(0, 32) || "新的学习对话";
}

function upsertAssistantMessage(
  messages: AiMessage[],
  messageId: string | null,
  content: string,
  status: AiMessage["status"],
  reasoningContent?: string,
  searchTrace?: SearchTrace | null,
  generationTrace?: GenerationTrace | null,
): AiMessage[] {
  if (!messageId) return messages;
  let found = false;
  const next = messages.map((message) => {
    if (message.id !== messageId) return message;
    found = true;
    return {
      ...message,
      content,
      reasoning_content: reasoningContent ?? message.reasoning_content,
      search_trace: searchTrace === undefined ? message.search_trace : searchTrace,
      generation_trace: generationTrace === undefined ? message.generation_trace : generationTrace,
      status,
      updated_at: new Date().toISOString(),
    };
  });
  return found ? next : messages;
}

function conversationListItem(detail: AiConversationDetail): AiConversation {
  const targetId = detail.context?.scope_kind === "task"
    ? detail.context.task_id
    : detail.context?.scope_kind === "plan" ? detail.context.goal_id : null;
  return {
    ...detail.conversation,
    link_type: detail.context?.scope_kind === "task" ? "task" : detail.context?.scope_kind === "plan" ? "goal" : null,
    link_target_id: targetId,
  };
}

function upsertConversation(items: AiConversation[], item: AiConversation, moveToFront = false) {
  const remaining = items.filter((candidate) => candidate.id !== item.id);
  if (moveToFront) return [item, ...remaining];
  const index = items.findIndex((candidate) => candidate.id === item.id);
  if (index < 0) return [item, ...items];
  const next = [...items];
  next[index] = item;
  return next;
}

function conversationMatchesEntry(item: AiConversation, scope: AiContextScope, targetId: string | null) {
  if (item.context_scope !== scope) return false;
  if (scope === "task") return item.link_type === "task" && item.link_target_id === targetId;
  if (scope === "plan") return item.link_type === "goal" && item.link_target_id === targetId;
  return item.link_target_id == null;
}

function conversationContext(detail: AiConversationDetail): { scope: AiContextScope; targetId: string | null } {
  const { conversation, context } = detail;
  return {
    scope: conversation.context_scope,
    targetId: conversation.context_scope === "task"
      ? conversation.link_target_id ?? (context?.scope_kind === "task" ? context.task_id : null)
      : conversation.context_scope === "plan"
        ? conversation.link_target_id ?? (context?.scope_kind === "plan" ? context.goal_id : null)
        : null,
  };
}

function scopeLabel(item: AiConversation, entryScope: AiContextScope, entryTargetId: string | null) {
  const current = conversationMatchesEntry(item, entryScope, entryTargetId);
  if (item.context_scope === "task") return current ? "当前任务" : "任务对话";
  if (item.context_scope === "plan") return current ? "当前计划" : "计划对话";
  if (item.context_scope === "global") return "全局 AI";
  return "独立对话";
}

export default function AiLearningRoom({
  task,
  contextScope,
  targetId,
  initialDraft,
  learningBrief,
  provider,
  onBack,
  onProviderOpen,
}: {
  task: Task | null;
  contextScope?: AiContextScope;
  targetId?: string | null;
  initialDraft?: string;
  learningBrief?: LearningRoomBrief;
  provider: AiProvider | null;
  onBack: () => void;
  onProviderOpen: () => void;
}) {
  const effectiveScope: AiContextScope = contextScope ?? (task ? "task" : "independent");
  const effectiveTargetId = targetId ?? (effectiveScope === "task" ? task?.id ?? null : null);
  const [detail, setDetail] = useState<AiConversationDetail | null>(null);
  const [context, setContext] = useState<AiLearningContext | null>(null);
  const [status, setStatus] = useState<RoomStatus>("loading");
  const [entryReady, setEntryReady] = useState(false);
  const [completionOpen, setCompletionOpen] = useState(false);
  const [helpHistoryOpen, setHelpHistoryOpen] = useState(false);
  const [failedHelpDisplays, setFailedHelpDisplays] = useState<Record<string, number>>({});
  const helpHistoryTriggerRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { setCompletionOpen(false); }, [learningBrief?.delegation_id]);
  const [draft, setDraft] = useState("");
  const [publicQuery, setPublicQuery] = useState('');
  const [error, setError] = useState("");
  const [providers, setProviders] = useState<AiProvider[]>([]);
  const [conversations, setConversations] = useState<AiConversation[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [historyActionError, setHistoryActionError] = useState("");
  const [historyActionBusy, setHistoryActionBusy] = useState<string | null>(null);
  const [editingConversationId, setEditingConversationId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<AiConversation | null>(null);
  const [historyDismissSuspended, setHistoryDismissSuspended] = useState(false);
  const [conversationConfig, setConversationConfig] = useState<AiConversationConfig | null>(null);
  const [draftConfig, setDraftConfig] = useState<DraftConfig | null>(readSession()?.draftConfig ?? null);
  const [configBusy, setConfigBusy] = useState(false);
  const [openLayer, setOpenLayer] = useState<"history" | "config" | "context" | null>(null);
  const [verificationOpen, setVerificationOpen] = useState(learningBrief?.open_verification === true);
  const [verificationCompleted, setVerificationCompleted] = useState(false);
  const [discussionId, setDiscussionId] = useState<string | null>(() => new URLSearchParams(window.location.search).get("discussion"));
  const [discussionReviewVersion, setDiscussionReviewVersion] = useState(0);
  const [titleBusy, setTitleBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const titlePollTimerRef = useRef<number | null>(null);
  const runIdRef = useRef<string | null>(null);
  const conversationIdRef = useRef<string | null>(null);
  const creationEpoch = useRef(0);
  const [attachmentContext, setAttachmentContext] = useState(0);
  const creatingConversation = useRef<Promise<AiConversationDetail> | null>(null);
  const currentRunRef = useRef<AiRun | null>(null);
  const subscribeRef = useRef<(run: AiRun, attempt?: number) => Promise<void>>(async () => undefined);
  const cancelRequestedRef = useRef(false);
  const mountedRef = useRef(true);
  const conversationContextRef = useRef<{ scope: AiContextScope; targetId: string | null } | null>(null);
  const configLayerRef = useRef<HTMLDivElement | null>(null);
  const historyLayerRef = useRef<HTMLDivElement | null>(null);
  const contextLayerRef = useRef<HTMLDivElement | null>(null);
  const deleteDialogRef = useRef<HTMLElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  // Only identifiers survive a refresh. Keep the question itself in memory
  // long enough to restore the controlled input after an ambiguous failure.
  const pendingSubmissionRef = useRef<PendingSubmission | null>(readSession()?.pending ?? null);
  const pendingContentRef = useRef<string | null>(null);
  const initialDraftSentRef = useRef<string | null>(null);
  const sendingRef = useRef(false);
  const conversationDrafts = useRef(new Map<string, string>());
  const previousConversationId = useRef<string | null>(null);
  const [mapLocation, setMapLocation] = useState<{ id: string; source: string } | null>(null);
  const branchKeysRef = useRef<Record<string, string>>({});
  const branchBusyRef = useRef(false);
  const [branchBusy, setBranchBusy] = useState(false);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [materialVersions, setMaterialVersions] = useState<MaterialVersion[]>([]);
  const [attachmentDraftIds, setAttachmentDraftIds] = useState<string[]>([]);
  const [attachmentClearSignal, setAttachmentClearSignal] = useState(0);
  const [attachmentBusy, setAttachmentBusy] = useState(false);
  const [selectedTeachingMode, setSelectedTeachingMode] = useState<TeachingSelection | null>(null);

  const dismissLayer = useCallback(() => setOpenLayer(null), []);
  const closeHelpHistory = useCallback(() => setHelpHistoryOpen(false), []);
  useDismissibleLayer(openLayer === "config", [configLayerRef], dismissLayer);
  useDismissibleLayer(openLayer === "history" && !historyDismissSuspended, [historyLayerRef, deleteDialogRef], dismissLayer);
  useDismissibleLayer(openLayer === "context", [contextLayerRef], dismissLayer);

  useEffect(() => {
    creationEpoch.current++; creatingConversation.current = null;
  }, [effectiveScope, effectiveTargetId]);
  useEffect(() => {
    const update = () => { void listAiProviders().then(setProviders).catch(() => {}); };
    window.addEventListener('nautilus:image-settings-changed', update);
    return () => window.removeEventListener('nautilus:image-settings-changed', update);
  }, []);
  const currentRun = detail?.active_run ?? null;
  const conversationId = detail?.conversation.id ?? null;
  const sharedState = useConversationState('conversation', detail?.conversation.identity_id ?? null, conversationId, async () => {
    if (!conversationId) return;
    const next = await getAiConversation(conversationId);
    if (conversationIdRef.current === conversationId) setDetail(next);
  });
  const sourceScope = sharedState.sourceScope;
  const setSourceScope = (value: SourceScope) => sharedState.save({ source_scope: value });
  const searchChoice = sharedState.search;
  const searchSelection = searchChoice.value;
  const replyHistory = useReplyHistory(conversationId ?? '', (detail?.messages ?? []).map(message => ({ id: message.id, parentId: message.parent_message_id ?? null })), currentRun?.response_message_id, { leaf: sharedState.snapshot.leaf_id, paths: sharedState.snapshot.paths, ready: sharedState.ready, select: (leaf_id, paths) => sharedState.save({ leaf_id, paths }) });
  const visibleMessages = replyHistory.path.map(id => detail!.messages.find(message => message.id === id)!);
  const teachingPath = replyHistory.path.join(':');
  useEffect(() => { setSelectedTeachingMode(null); }, [conversationId, teachingPath]);
  useEffect(() => {
    if (!mapLocation || conversationId !== mapLocation.id || !detail?.messages.some(item => item.id === mapLocation.source)) return;
    if (!sharedState.ready) return;
    if (replyHistory.leaf !== mapLocation.source) {
      const source = mapLocation.source; setMapLocation(null);
      void Promise.resolve(replyHistory.locate(source)).then(saved => { if (saved) requestAnimationFrame(() => document.getElementById(`answer-${source}`)?.scrollIntoView({ block: 'center' })); });
      return;
    }
    const frame = requestAnimationFrame(() => {
      document.getElementById(`answer-${mapLocation.source}`)?.scrollIntoView({ block: 'center' });
      setMapLocation(null);
    });
    return () => cancelAnimationFrame(frame);
  }, [mapLocation, conversationId, detail, replyHistory.leaf, sharedState.ready]);


  useEffect(() => {
    if (previousConversationId.current && previousConversationId.current !== conversationId) setPublicQuery('');
    previousConversationId.current = conversationId;
    setEditingMessageId(null); setMaterialVersions([]); setHelpHistoryOpen(false); setFailedHelpDisplays({});
  }, [conversationId]);

  conversationIdRef.current = conversationId;
  currentRunRef.current = currentRun;

  function sessionContext() {
    return conversationContextRef.current ?? { scope: effectiveScope, targetId: effectiveTargetId };
  }

  function persistSession(extra: Partial<RoomSession> = {}) {
    if (!mountedRef.current) return;
    const current = sessionContext();
    const previous = readSession();
    writeSession({
      taskId: current.scope === "task" ? current.targetId : null,
      contextScope: current.scope,
      targetId: current.targetId,
      conversationId: conversationIdRef.current ?? previous?.conversationId ?? null,
      runId: currentRunRef.current?.id ?? runIdRef.current ?? previous?.runId ?? null,
      initialDraft: previous?.initialDraft ?? null,
      open: true,
      draftConfig: previous?.draftConfig ?? null,
      learningBrief,
      ...extra,
    });
  }

  const saveCurrentSession = useCallback((extra: Partial<RoomSession> = {}) => {
    persistSession(extra);
  }, [effectiveScope, effectiveTargetId]);

  const pollTitle = useCallback(async (id: string, attempt = 0) => {
    if (!mountedRef.current || attempt >= 25) return;
    const next = await getAiConversation(id);
    if (!mountedRef.current || conversationIdRef.current !== id) return;
    setDetail(next);
    setConversations((items) => upsertConversation(items, conversationListItem(next)));
    const pending = ["queued", "running"].includes(next.conversation.title_generation_status);
    const awaitingQueue = next.conversation.title_generation_status === "pending"
      && ["placeholder", "fallback"].includes(next.conversation.title_source)
      && attempt < 5;
    setTitleBusy(pending);
    if (pending || awaitingQueue) {
      titlePollTimerRef.current = window.setTimeout(() => void pollTitle(id, attempt + 1), 800);
    }
  }, []);

  const reconcile = useCallback(async (id: string) => {
    const next = await getAiConversation(id);
    if (!mountedRef.current || conversationIdRef.current !== id) return next;
    setDetail(next);
    setConversations((items) => upsertConversation(items, conversationListItem(next), true));
    if (next.active_run) {
      runIdRef.current = next.active_run.id;
      saveCurrentSession({ conversationId: id, runId: next.active_run.id });
    } else {
      runIdRef.current = null;
      const previous = readSession();
      persistSession(previous?.pending
        ? { conversationId: id, runId: null, pending: previous.pending }
        : { conversationId: id, runId: null });
    }
    return next;
  }, [effectiveScope, effectiveTargetId, saveCurrentSession]);

  const subscribe = useCallback(async (run: AiRun, attempt = 0) => {
    if (!mountedRef.current) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    runIdRef.current = run.id;
    cancelRequestedRef.current = false;
    setStatus(attempt ? "reconnecting" : "streaming");
    saveCurrentSession({ runId: run.id });
    let terminal = false;
    try {
      await streamAiRun(run.id, (event: AiStreamEvent) => {
        if (!mountedRef.current || runIdRef.current !== run.id) return;
        if (event.type === "start") {
          terminal = false;
          setDetail((previous) => previous ? {
            ...previous,
            active_run: { ...(previous.active_run ?? run), status: event.data.status },
            messages: upsertAssistantMessage(
              previous.messages,
              event.data.message_id,
              event.data.content,
              "streaming",
              event.data.reasoning_content,
              event.data.search_trace,
              event.data.generation_trace,
            ),
          } : previous);
          return;
        }
        if (event.type === "search") {
          if (event.data.run_id !== run.id) return;
          setDetail(previous => previous ? { ...previous, messages: previous.messages.map(message => message.id === event.data.message_id ? { ...message, search_trace: event.data.trace } : message) } : previous);
          return;
        }
        if (event.type === "process") {
          if (event.data.run_id !== run.id) return;
          setDetail(previous => previous ? { ...previous, messages: previous.messages.map(message => message.id === event.data.message_id ? { ...message, generation_trace: event.data.trace } : message) } : previous);
          return;
        }
        if (event.type === "delta") {
          setDetail((previous) => {
            if (!previous) return previous;
            const assistantId = previous.active_run?.response_message_id ?? run.response_message_id;
            const message = previous.messages.find((item) => item.id === assistantId);
            const current = message?.content ?? "";
            const reasoning = message?.reasoning_content ?? "";
            return {
              ...previous,
              messages: upsertAssistantMessage(
                previous.messages,
                assistantId,
                event.data.kind === "content" ? current + event.data.text : current,
                "streaming",
                event.data.kind === "reasoning" ? reasoning + event.data.text : reasoning,
              ),
            };
          });
          return;
        }
        terminal = true;
        if (event.type === "done") {
          setStatus(event.data.status === "canceled" ? "canceled" : "succeeded");
        } else {
          setError(event.data.message || "AI 运行失败");
          setStatus("failed");
        }
        setDetail((previous) => previous ? {
          ...previous,
          active_run: null,
          messages: upsertAssistantMessage(
            previous.messages,
            event.data.message_id,
            event.data.content,
            event.type === "done" && event.data.status === "succeeded" ? "complete" : event.type === "done" ? "canceled" : "failed",
            event.data.reasoning_content,
            event.data.search_trace,
            event.data.generation_trace,
          ),
        } : previous);
        persistSession({ conversationId: run.conversation_id, runId: null });
      }, controller.signal);
      if (!terminal && !controller.signal.aborted && !cancelRequestedRef.current) {
        throw new Error("流式连接提前结束");
      }
      if (terminal && mountedRef.current) {
        const next = await reconcile(run.conversation_id);
        if (["pending", "queued", "running"].includes(next.conversation.title_generation_status)
          && ["placeholder", "fallback"].includes(next.conversation.title_source)) {
          setTitleBusy(["queued", "running"].includes(next.conversation.title_generation_status));
          void pollTitle(run.conversation_id);
        }
      }
    } catch (reason: unknown) {
      if (controller.signal.aborted || cancelRequestedRef.current || !mountedRef.current) return;
      if (attempt < MAX_RECONNECT_ATTEMPTS) {
        setStatus("reconnecting");
        reconnectTimerRef.current = window.setTimeout(() => {
          void subscribeRef.current(run, attempt + 1);
        }, 500 * 2 ** attempt);
      } else {
        setStatus("failed");
        setError(reason instanceof Error ? reason.message : "流式连接失败，请重试");
      }
    }
  }, [effectiveScope, effectiveTargetId, pollTitle, reconcile, saveCurrentSession]);

  subscribeRef.current = subscribe;

  const activateConversation = useCallback(async (id: string) => {
    if (learningBrief?.session_id) await selectLearningRoomConversation(learningBrief.session_id, id);
    const [next, currentConfig] = await Promise.all([
      getAiConversation(id),
      getAiConversationConfig(id).catch(reason => {
        if (mountedRef.current) setError(reason instanceof Error ? reason.message : "模型配置暂时无法读取");
        return { config: null };
      }),
    ]);
    if (!mountedRef.current) return;
    conversationIdRef.current = id;
    setDetail(next);
    conversationContextRef.current = conversationContext(next);
    setConversationConfig(currentConfig.config);
    setDraftConfig(null);
    setConversations((items) => upsertConversation(items, conversationListItem(next)));
    const titlePending = ["queued", "running"].includes(next.conversation.title_generation_status);
    setTitleBusy(titlePending);
    if (titlePending) void pollTitle(id);
    if (next.active_run) {
      runIdRef.current = next.active_run.id;
      persistSession({ conversationId: id, runId: next.active_run.id });
      void subscribeRef.current(next.active_run);
    } else {
      runIdRef.current = null;
      persistSession({ conversationId: id, runId: null });
      setStatus("idle");
    }
  }, [effectiveScope, effectiveTargetId, pollTitle, learningBrief?.session_id]);

  const loadRoom = useCallback(async () => {
    setEntryReady(false);
    setStatus("loading");
    setError("");
    setHistoryLoading(true);
    setHistoryError("");
    setHistoryActionError("");
    const saved = readSession();
    const savedForEntry = saved?.contextScope === effectiveScope && saved.targetId === effectiveTargetId
      && saved.learningBrief?.session_id === learningBrief?.session_id ? saved : null;
    try {
      const [entryContext, conversationItems, providerList, room] = await Promise.all([
        getAiContextPreview(effectiveScope, effectiveTargetId),
        listAiConversations().catch((reason: unknown) => {
          setHistoryError(reason instanceof Error ? reason.message : "对话历史加载失败");
          return [] as AiConversation[];
        }),
        listAiProviders(),
        learningBrief?.session_id ? getLearningRoom(learningBrief.session_id) : Promise.resolve(null),
      ]);
      if (!mountedRef.current) return;
      if (room && (room.brief.delegation_id !== learningBrief?.delegation_id || room.brief.action_id !== learningBrief?.action_id)) {
        throw new Error('学习室与当前任务不一致，已停止恢复，请返回后重新进入。');
      }
      if (room && learningBrief?.session_id && !learningBrief.history_only) await recordLearningRoomEntry(learningBrief.session_id);
      if (room && learningBrief?.continuity_review_id && learningBrief.session_id && !learningBrief.history_only) {
        await chooseReturnReview(learningBrief.continuity_review_id, "entered", `entered:${learningBrief.continuity_review_id}:${learningBrief.session_id}`, undefined, learningBrief.session_id);
      }
      setContext(entryContext);
      setProviders(providerList);
      setConversations(room ? conversationItems.filter((item) => room.conversation_ids.includes(item.id)) : conversationItems);
      setHistoryLoading(false);
      setDraftConfig(savedForEntry?.draftConfig ?? null);
      const savedConversation = savedForEntry?.conversationId
        ? conversationItems.find((item) => item.id === savedForEntry.conversationId)
        : null;
      let candidate = !initialDraft && savedConversation && conversationMatchesEntry(savedConversation, effectiveScope, effectiveTargetId)
        ? savedConversation.id
        : null;
      if (room) candidate = room.conversation_id;
      if (!room && !candidate && !initialDraft) {
        candidate = conversationItems.find((item) => conversationMatchesEntry(item, effectiveScope, effectiveTargetId))?.id ?? null;
      }
      if (candidate) {
        try {
          await activateConversation(candidate);
          if (savedForEntry?.pending) {
            pendingSubmissionRef.current = null;
            pendingContentRef.current = null;
          }
        } catch {
          pendingSubmissionRef.current = null;
          pendingContentRef.current = null;
          conversationContextRef.current = null;
          persistSession({ conversationId: null, runId: null });
          setStatus("idle");
        }
      } else {
        setDetail(null);
        setConversationConfig(null);
        setDraft("");
        setStatus("idle");
      }
      if (mountedRef.current) setEntryReady(true);
    } catch (reason: unknown) {
      if (!mountedRef.current) return;
      setHistoryLoading(false);
      setStatus("failed");
      setError(reason instanceof Error ? reason.message : "学习室加载失败");
    }
  }, [activateConversation, effectiveScope, effectiveTargetId, initialDraft, learningBrief?.session_id]);

  useEffect(() => {
    mountedRef.current = true;
    void loadRoom();
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
      if (reconnectTimerRef.current !== null) window.clearTimeout(reconnectTimerRef.current);
      if (titlePollTimerRef.current !== null) window.clearTimeout(titlePollTimerRef.current);
    };
  }, [loadRoom]);

  useEffect(() => {
    const content = initialDraft?.trim();
    if (!searchChoice.ready || !content || status !== "idle" || detail?.messages.some((message) => message.role === "user") || initialDraftSentRef.current === content) return;
    const timer = window.setTimeout(() => {
      if (mountedRef.current) void submitMessage(content);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [detail, initialDraft, provider, providers, status, searchChoice.ready]);


  useEffect(() => {
    if (openLayer === "history") return;
    setEditingConversationId(null);
    setEditingTitle("");
  }, [openLayer]);

  async function ensureConversation(): Promise<AiConversationDetail> {
    if (detail) return detail;
    if (creatingConversation.current) return creatingConversation.current;
    const current = creationEpoch.current;
    const stillCurrent = () => mountedRef.current && creationEpoch.current === current;
    const create = async () => {
      let created = await createAiConversation(effectiveScope, effectiveTargetId);
      if (!stillCurrent()) throw new Error('对话已切换，请在当前对话重新上传。');
      if (learningBrief?.session_id) await selectLearningRoomConversation(learningBrief.session_id, created.conversation.id);
      if (draftConfig) {
        await setAiConversationConfig(created.conversation.id, {
          provider_profile_id: draftConfig.providerProfileId,
          provider_model_id: draftConfig.providerModelId,
        });
        created = await getAiConversation(created.conversation.id);
        setDraftConfig(null);
        saveCurrentSession({ conversationId: created.conversation.id, draftConfig: null });
      }
      if (!stillCurrent()) throw new Error('对话已切换，请在当前对话重新上传。');
      await sharedState.initializeNew(created.conversation.id);
      if (!stillCurrent()) throw new Error('对话已切换，请在当前对话重新上传。');
      if (stillCurrent()) {
        setDetail(created);
        conversationContextRef.current = conversationContext(created);
        conversationIdRef.current = created.conversation.id;
        setConversations((items) => upsertConversation(items, conversationListItem(created), true));
        saveCurrentSession({ conversationId: created.conversation.id, runId: null });
        const currentConfig = await getAiConversationConfig(created.conversation.id);
        if (!stillCurrent()) throw new Error('对话已切换，请在当前对话重新上传。');
        setConversationConfig(currentConfig.config);
      }
      return created;
    };
    const pending = create(); creatingConversation.current = pending;
    try { return await pending; }
    finally { if (creatingConversation.current === pending) creatingConversation.current = null; }
  }

  async function handleConfigChange(event: ChangeEvent<HTMLSelectElement>) {
    const [providerId, modelId] = event.target.value.split("::");
    if (configBusy) return;
    if (!providerId || !modelId) {
      if (conversationId) await handleRestoreDefault();
      else {
        setDraftConfig(null);
        saveCurrentSession({ draftConfig: null });
      }
      return;
    }
    if (!conversationId) {
      const nextDraft = { providerProfileId: providerId, providerModelId: modelId };
      setDraftConfig(nextDraft);
      saveCurrentSession({ draftConfig: nextDraft });
      return;
    }
    setConfigBusy(true);
    setError("");
    try {
      const result = await setAiConversationConfig(conversationId, {
        provider_profile_id: providerId,
        provider_model_id: modelId,
      });
      setConversationConfig(result.config);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "切换提供方或模型失败");
    } finally {
      setConfigBusy(false);
    }
  }

  async function handleRestoreDefault() {
    if (!conversationId || configBusy) return;
    setConfigBusy(true);
    setError("");
    try {
      await clearAiConversationConfig(conversationId);
      setConversationConfig(null);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "恢复默认配置失败");
    } finally {
      setConfigBusy(false);
    }
  }

  function handleRestoreSelection() {
    if (conversationId) {
      void handleRestoreDefault();
      return;
    }
    setDraftConfig(null);
    saveCurrentSession({ draftConfig: null });
  }

  async function handleRegenerateTitle() {
    if (!conversationId || titleBusy || !detail?.messages.some((message) => message.status === "complete")) return;
    setTitleBusy(true);
    setError("");
    try {
      await regenerateAiConversationTitle(conversationId);
      void pollTitle(conversationId);
    } catch (reason: unknown) {
      setTitleBusy(false);
      setError(reason instanceof Error ? reason.message : "重新生成标题失败");
    }
  }

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await submitMessage(draft.trim());
  }

  async function submitMessage(content: string, preserveDraft = false, regenerateMessageId?: string, editMessageId?: string, requestedHelp?: HelpRequestKind | null, requestedAction?: TeachingAction | null): Promise<boolean> {
    if (attachmentBusy || !entryReady || !content || branchBusyRef.current || sendingRef.current || status === "submitting" || status === "streaming" || status === "reconnecting") return false;
    if (sharedState.blocked) { setError("请先确认或修复当前学习状态，再发送消息。"); return false; }
    if (sourceScope.mode !== 'unspecified' && sourceScope.version_ids.length === 0 && !sourceScope.knowledge_base && !pendingSubmissionRef.current) { setError('请先选择至少一个资料版本或知识库，或改为未指定资料。'); return false; }
    const unresolved = pendingSubmissionRef.current;

    if (unresolved && (pendingContentRef.current !== content || unresolved.regenerateMessageId !== regenerateMessageId || unresolved.editMessageId !== editMessageId)) {
      setError("上次发送结果尚未确认。请先用原问题重试，或重新打开对话核对已保存的消息。");
      return false;
    }
    if (!activeProvider?.has_api_key || !activeProvider.enabled) {
      setError("请先配置并启用 AI 提供方");
      return false;
    }
    setError("");
    setStatus("submitting");
    sendingRef.current = true;
    const sendEpoch = creationEpoch.current;
    // Creating the first conversation changes the displayed path. Capture the
    // user's choice before that asynchronous change clears the unsent choice.
    const requestedTeachingMode = regenerateMessageId
      ? detail?.messages.find(message => message.id === regenerateMessageId)?.teaching?.requested_mode ?? null
      : selectedTeachingMode;
    const stillCurrent = () => mountedRef.current && creationEpoch.current === sendEpoch;
    let conversation: AiConversationDetail;
    try {
      conversation = await ensureConversation();
      if (!stillCurrent() || conversationIdRef.current !== conversation.conversation.id) return false;
      const savedPending = pendingSubmissionRef.current ?? readSession()?.pending;
      const canReusePending = Boolean(
        savedPending &&
        savedPending.contextScope === effectiveScope &&
        savedPending.targetId === effectiveTargetId &&
        savedPending.conversationId === conversation.conversation.id &&
        savedPending.regenerateMessageId === regenerateMessageId &&
        savedPending.editMessageId === editMessageId &&
        (!pendingContentRef.current || pendingContentRef.current === content),
      );
      const automatic = !regenerateMessageId && !editMessageId && Boolean(learningBrief && initialDraft?.trim() === content);
      const clientMessageId = canReusePending ? savedPending!.clientMessageId : `${automatic ? LEARNING_PROMPT_ID_PREFIX : ""}${makeClientMessageId()}`;
      const parentMessageId = canReusePending ? savedPending!.parentMessageId : (!regenerateMessageId && !editMessageId ? replyHistory.leaf ?? undefined : undefined);
      const frozenSearch = canReusePending ? savedPending!.search ?? { mode: "off" as const } : automatic ? { mode: "off" as const } : structuredClone(searchSelection);
      const frozenPublicQuery = canReusePending ? savedPending!.publicQuery ?? publicQuery.trim() : !automatic && !regenerateMessageId && !editMessageId && frozenSearch.mode === 'external' ? publicQuery.trim() : '';
      const frozenHelp = canReusePending ? savedPending!.helpRequest ?? null : requestedHelp !== undefined ? requestedHelp : regenerateMessageId ? detail?.messages.find(message => message.id === regenerateMessageId)?.help_record?.request?.kind ?? null : null;
      const frozenTeachingMode = canReusePending ? savedPending!.teachingMode ?? null : requestedTeachingMode;
      const frozenTeachingAction = canReusePending ? savedPending!.teachingAction ?? null : regenerateMessageId
        ? detail?.messages.find(message => message.id === regenerateMessageId)?.teaching?.requested_action ?? null : requestedAction ?? null;
      const frozenScope = canReusePending ? savedPending!.sourceScope ?? emptySourceScope() : sourceScope;
      const frozenAttachments = canReusePending ? savedPending!.attachmentVersionIds ?? [] : regenerateMessageId || editMessageId || automatic ? [] : attachmentDraftIds.filter(id => frozenScope.version_ids.includes(id));
      const pending: PendingSubmission = { attachmentVersionIds: frozenAttachments, search: frozenSearch, publicQuery: frozenPublicQuery, sourceScope: frozenScope, helpRequest: frozenHelp, teachingMode: frozenTeachingMode, teachingAction: frozenTeachingAction, regenerateMessageId, editMessageId, parentMessageId, taskId: effectiveScope === "task" ? effectiveTargetId : null, contextScope: effectiveScope, targetId: effectiveTargetId, conversationId: conversation.conversation.id, clientMessageId };
      pendingSubmissionRef.current = pending;
      pendingContentRef.current = content;
      persistSession({ conversationId: conversation.conversation.id, runId: null, pending });
      if (!preserveDraft) setDraft("");
      const result = await sendAiMessage(conversation.conversation.id, content, clientMessageId, { current_state_revision: sharedState.revisionFor(conversation.conversation.id), regenerate_message_id: regenerateMessageId, edit_message_id: editMessageId, parent_message_id: parentMessageId, help_request: frozenHelp, teaching_mode: frozenTeachingMode, teaching_action: frozenTeachingAction, source_scope: frozenScope, attachment_version_ids: frozenAttachments, ...(frozenSearch.mode !== "off" ? { search: frozenSearch } : {}), ...(frozenPublicQuery ? { public_search_query: frozenPublicQuery } : {}) });
      if (!stillCurrent() || conversationIdRef.current !== conversation.conversation.id) return false;
      if (!regenerateMessageId && !editMessageId && !automatic) setAttachmentClearSignal(value => value + 1);
      if (frozenPublicQuery) setPublicQuery(previous => previous.trim() === frozenPublicQuery ? '' : previous);
      if (initialDraft?.trim() === content) initialDraftSentRef.current = content;
      pendingSubmissionRef.current = null;
      pendingContentRef.current = null;
      const localTitle = fallbackConversationTitle(content);
      setDetail((previous) => {
        const current = previous ?? conversation;
        const shouldUseFallback = current.conversation.title_source === "placeholder"
          && current.conversation.title_generation_status === "pending";
        return {
          ...current,
          conversation: shouldUseFallback ? {
            ...current.conversation,
            title: localTitle,
            title_source: "fallback",
            title_revision: current.conversation.title_revision + 1,
          } : current.conversation,
          messages: result.messages.map(message => ({ ...message, search_trace: message.search_trace === undefined ? current.messages.find(old => old.id === message.id)?.search_trace : message.search_trace })),
          active_run: result.run,
        };
      });
      setConversations((items) => upsertConversation(items, {
        ...conversationListItem(conversation),
        title: conversation.conversation.title_source === "placeholder" ? localTitle : conversation.conversation.title,
        title_source: conversation.conversation.title_source === "placeholder" ? "fallback" : conversation.conversation.title_source,
        last_message_at: new Date().toISOString(),
      }, true));
      await sharedState.reload(false, conversation.conversation.id);
      if (!stillCurrent() || conversationIdRef.current !== conversation.conversation.id) return false;
      runIdRef.current = result.run.id;
      persistSession({ conversationId: conversation.conversation.id, runId: result.run.id, initialDraft: null, pending: undefined });
      void subscribe(result.run);
      return true;
    } catch (reason: unknown) {
      if (!stillCurrent()) return false;
      const stateRejected = isStateRejected(reason);
      if (stateRejected) await sharedState.reload(isStateConflict(reason));
      if (!stillCurrent()) return false;
      if (stateRejected || (reason instanceof ApiError && [400, 422].includes(reason.status ?? 0))) {
        pendingSubmissionRef.current = null;
        pendingContentRef.current = null;
        persistSession({ pending: undefined });
        if (!regenerateMessageId) setSelectedTeachingMode(requestedTeachingMode);
      }
      if (!preserveDraft) setDraft(content);
      setStatus("failed");
      setError(stateRejected ? "消息未发送，请核对最新状态后重新发送。" : attachmentError(reason));
      return false;
    } finally {
      if (creationEpoch.current === sendEpoch) sendingRef.current = false;
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.ctrlKey ||
      event.metaKey ||
      event.altKey ||
      event.nativeEvent.isComposing ||
      event.nativeEvent.keyCode === 229 ||
      !canSend ||
      !draft.trim()
    ) {
      return;
    }
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  async function handleCancel() {
    const run = detail?.active_run;
    if (!run) return;
    cancelRequestedRef.current = true;
    setStatus("canceled");
    abortRef.current?.abort();
    try {
      await cancelAiRun(run.id);
      await reconcile(run.conversation_id);
    } catch (reason: unknown) {
      if (mountedRef.current) setError(reason instanceof Error ? reason.message : "取消 AI 请求失败");
    }
  }

  async function handleRetry() {
    const answer = [...visibleMessages].reverse().find(message => message.role === 'assistant');
    const question = detail?.messages.find(message => message.id === answer?.parent_message_id);
    if (answer && question) await submitMessage(question.content, true, answer.id);
  }

  function handleNewConversation() {
    if (!entryReady || branchBusyRef.current) return;
    creationEpoch.current++; creatingConversation.current = null; sendingRef.current = false; setAttachmentContext(value => value + 1);
    abortRef.current?.abort();
    runIdRef.current = null;
    pendingSubmissionRef.current = null;
    pendingContentRef.current = null;
    setDetail(null);
    conversationContextRef.current = null;
    setConversationConfig(null);
    setDraftConfig(null);
    setOpenLayer(null);
    setEditingConversationId(null);
    setEditingTitle("");
    setHistoryActionError("");
    setTitleBusy(false);
    setError("");
    setDraft("");
    setPublicQuery('');
    setSelectedTeachingMode(null);
    setStatus("idle");
    persistSession({ conversationId: null, runId: null, draftConfig: null });
  }

  async function handleConversationSwitch(id: string) {
    if (branchBusyRef.current) return;
    if (id === conversationId) {
      setOpenLayer(null);
      return;
    }
    creationEpoch.current++; creatingConversation.current = null; sendingRef.current = false; setAttachmentContext(value => value + 1);
    abortRef.current?.abort();
    if (titlePollTimerRef.current !== null) window.clearTimeout(titlePollTimerRef.current);
    runIdRef.current = null;
    pendingSubmissionRef.current = null;
    pendingContentRef.current = null;
    setOpenLayer(null);
    setError("");
    setPublicQuery('');
    if (conversationId) conversationDrafts.current.set(conversationId, draft);
    setStatus("loading");
    try {
      await activateConversation(id);
      setDraft(conversationDrafts.current.get(id) ?? "");
    } catch (reason: unknown) {
      if (!mountedRef.current) return;
      setStatus("failed");
      setError(reason instanceof Error ? reason.message : "切换对话失败");
    }
  }

  async function handleBranch(messageId: string) {
    if (!conversationId || !detail || branchBusyRef.current || sendingRef.current || pendingSubmissionRef.current || currentRun || !entryReady || ['loading', 'submitting', 'streaming', 'reconnecting'].includes(status)) return;
    if (sharedState.blocked) return;
    const sourceId = conversationId;
    const key = `${sourceId}:${messageId}`;
    const requestKey = branchKeysRef.current[key] ?? makeClientMessageId();
    branchKeysRef.current[key] = requestKey;
    branchBusyRef.current = true; setBranchBusy(true); setError('');
    try {
      const created = await branchAiConversation(sourceId, messageId, requestKey);
      if (!mountedRef.current) return;
      const nextId = created.conversation.id;
      await sharedState.initializeNew(nextId, { leaf_id: created.messages.at(-1)?.id ?? null, source_scope: created.branch_source_scope ?? emptySourceScope(), search_override: searchSelection });
      conversationDrafts.current.set(sourceId, draft);
      conversationDrafts.current.set(nextId, draft);
      await activateConversation(nextId);
      delete branchKeysRef.current[key];
    } catch (reason) {
      if (mountedRef.current) setError(reason instanceof Error ? reason.message : '创建独立对话失败，请重试。');
    } finally {
      branchBusyRef.current = false; if (mountedRef.current) setBranchBusy(false);
    }
  }

  function handleStartRename(item: AiConversation) {
    setHistoryActionError("");
    setEditingConversationId(item.id);
    setEditingTitle(item.title);
  }

  function handleCancelRename() {
    if (historyActionBusy) return;
    setEditingConversationId(null);
    setEditingTitle("");
  }

  async function handleRenameConversation(item: AiConversation) {
    const title = editingTitle.trim();
    if (!title) {
      setHistoryActionError("对话标题不能为空");
      return;
    }
    if (title === item.title) {
      handleCancelRename();
      return;
    }
    setHistoryActionBusy(item.id);
    setHistoryActionError("");
    try {
      const next = await renameAiConversation(item.id, title);
      setConversations((items) => upsertConversation(items, conversationListItem(next)));
      if (item.id === conversationId) setDetail(next);
      setEditingConversationId(null);
      setEditingTitle("");
    } catch (reason: unknown) {
      setHistoryActionError(reason instanceof Error ? reason.message : "修改对话标题失败");
    } finally {
      setHistoryActionBusy(null);
    }
  }

  async function handleConfirmDelete() {
    const target = deleteTarget;
    if (!target || historyActionBusy) return;
    setHistoryActionBusy(target.id);
    setHistoryActionError("");
    try {
      await deleteAiConversation(target.id);
      const remaining = conversations.filter((item) => item.id !== target.id);
      setConversations(remaining);
      if (target.id === conversationId) {
        abortRef.current?.abort();
        if (titlePollTimerRef.current !== null) window.clearTimeout(titlePollTimerRef.current);
        runIdRef.current = null;
        pendingSubmissionRef.current = null;
        pendingContentRef.current = null;
        const replacement = remaining.find((item) => conversationMatchesEntry(item, effectiveScope, effectiveTargetId)) ?? null;
        if (replacement) {
          await activateConversation(replacement.id);
        } else {
          handleNewConversation();
        }
      }
    } catch (reason: unknown) {
      setHistoryActionError(reason instanceof Error ? reason.message : "删除对话失败");
    } finally {
      setHistoryActionBusy(null);
      closeDeleteDialog();
    }
  }

  function closeDeleteDialog() {
    setDeleteTarget(null);
    window.setTimeout(() => {
      if (mountedRef.current) setHistoryDismissSuspended(false);
    }, 0);
  }

  const displayContext = detail ? detail.context : context;
  const displayScope = detail?.conversation.context_scope ?? effectiveScope;
  const contextTitle = learningContextTitle(displayContext, displayScope);
  const selectedProviderId = conversationConfig?.provider_profile_id ?? draftConfig?.providerProfileId;
  const selectedModelId = conversationConfig?.provider_model_id ?? draftConfig?.providerModelId;
  const activeProvider = providers.find((item) => item.id === selectedProviderId) ?? providers.find(item => item.id === provider?.id) ?? provider;
  const activeModel = activeProvider?.models?.find((item) => item.id === (selectedModelId ?? activeProvider.default_model_id)) ?? activeProvider?.default_model ?? null;
  const selectedConfigValue = selectedProviderId && selectedModelId ? `${selectedProviderId}::${selectedModelId}` : "";
  const conversationTitle = detail?.conversation.title ?? "新的学习对话";
  const canSend = entryReady && !branchBusy && !sharedState.blocked && Boolean(
    activeProvider?.has_api_key && activeProvider.enabled && (!selectedModelId || (activeModel?.enabled && activeModel.discovery_status !== "unavailable")),
  ) && !["loading", "submitting", "streaming", "reconnecting"].includes(status);
  const teaching = <TeachingState
    key={conversationId ?? 'new'} kind="conversation" scopeId={conversationId ?? ''} pathKey={teachingPath}
    entries={conversationTeachingEntries(visibleMessages)} standalone={!learningBrief}
    defaultMode={sharedState.teachingDefault} selectedMode={pendingSubmissionRef.current ? pendingSubmissionRef.current.teachingMode ?? null : selectedTeachingMode} onModeChange={setSelectedTeachingMode}
    onAction={(action, label) => void submitMessage(label, true, undefined, undefined, undefined, action)}
    disabled={!entryReady || attachmentBusy || sharedState.blocked || branchBusy || Boolean(currentRun) || ['loading', 'submitting', 'streaming', 'reconnecting'].includes(status) || Boolean(editingMessageId) || Boolean(pendingSubmissionRef.current)}
    onUpdated={(answerId, record) => setDetail(previous => previous?.conversation.id === conversationId
      ? { ...previous, messages: previous.messages.map(message => message.id === answerId ? { ...message, teaching: record } : message) } : previous)} />;

  return (
    <>
      {learningBrief?.action_id && learningBrief.delegation_id && <div className="verification-scroll" hidden={!verificationOpen || Boolean(discussionId)}>
      <LearningVerification
        brief={learningBrief}
        reviewRefreshKey={String(discussionReviewVersion)}
        onBack={() => setVerificationOpen(false)}
        onDiscuss={id => { setDiscussionId(id); setReviewLocation("discussion", id); }}
        onCompleted={() => { setVerificationCompleted(true); onBack(); }}
      />
      </div>}
    {discussionId && <QuestionDiscussion id={discussionId} onNavigate={id => { setDiscussionId(id); setReviewLocation("discussion", id); }} onBack={() => { setDiscussionId(null); setReviewLocation("discussion", null); setDiscussionReviewVersion(value => value + 1); setVerificationOpen(true); }} />}
    {learningBrief?.delegation_id && !learningBrief.history_only && <div className="verification-scroll" hidden={!completionOpen || verificationOpen || Boolean(discussionId)}><div className="verification-page">
      <button className="button button--quiet" type="button" onClick={() => setCompletionOpen(false)}>返回学习室</button>
      <LearningCompletion key={learningBrief.delegation_id} delegationId={learningBrief.delegation_id} onCompleted={onBack} />
    </div></div>}
    <div className="ai-room" style={verificationOpen || completionOpen || discussionId ? { display: "none" } : undefined}>
      <header className="ai-room-header">
        <div className="ai-room-heading">
          <button className="button button--quiet button--compact button--with-icon" onClick={onBack} disabled={branchBusy} aria-label="返回工作区">
            <ArrowLeft size={15} /><span>返回工作区</span>
          </button>
          <div>
            <p className="eyebrow">LEARNING ROOM</p>
            <h1>AI 学习室</h1>
          </div>
        </div>
        <div className="ai-room-actions">
          <button ref={helpHistoryTriggerRef} className="ai-room-tool-trigger" type="button" aria-label="当前对话帮助记录" title="帮助记录" aria-haspopup="dialog" onClick={() => { setOpenLayer(null); setHelpHistoryOpen(true); }}>
            <ListChecks size={14} /><span>帮助记录</span>
          </button>
          <div className="ai-room-layer-anchor" ref={historyLayerRef}>
            <button
              className={`ai-room-tool-trigger${openLayer === "history" ? " is-open" : ""}`}
              type="button"
              aria-label="对话历史"
              title="对话历史"
              aria-expanded={openLayer === "history"}
              aria-controls="ai-conversation-history-panel"
              onClick={() => setOpenLayer((value) => value === "history" ? null : "history")}
            >
              <History size={14} /><span>对话历史</span>
            </button>
            {openLayer === "history" && <div id="ai-conversation-history-panel" className="ai-layer-panel ai-history-panel">
              <div className="ai-layer-heading"><div><small>HISTORY</small><strong>学习对话</strong></div><button className="icon-button" type="button" onClick={() => setOpenLayer(null)} aria-label="关闭对话历史"><X size={15} /></button></div>
              <button className="button button--quiet button--with-icon ai-history-new" type="button" disabled={branchBusy} onClick={handleNewConversation}><Plus size={13} />新建{scopeNoun(effectiveScope)}对话</button>
              {historyActionError && <p className="ai-history-action-error" role="alert">{historyActionError}</p>}
              <div className="ai-history-list" aria-label="对话列表">
                {historyLoading ? <p className="ai-history-state">正在加载对话…</p> : historyError ? <p className="ai-history-state is-error" role="alert">{historyError}</p> : conversations.length === 0 ? <p className="ai-history-state">还没有历史对话。</p> : conversations.map((item) => {
                  const scope = scopeLabel(item, effectiveScope, effectiveTargetId);
                  const editing = editingConversationId === item.id;
                  const busy = historyActionBusy === item.id;
                  return <div key={item.id} data-conversation-id={item.id} className={`ai-history-item${item.id === conversationId ? " is-current" : ""}`}>
                    {editing ? <form className="ai-history-edit" onSubmit={(event) => { event.preventDefault(); void handleRenameConversation(item); }}>
                      <input
                        autoFocus
                        aria-label="编辑对话标题"
                        value={editingTitle}
                        maxLength={60}
                        disabled={busy}
                        onChange={(event) => setEditingTitle(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Escape") {
                            event.preventDefault();
                            handleCancelRename();
                          }
                        }}
                      />
                      <button className="icon-button" type="submit" aria-label="保存对话标题" title="保存" disabled={busy || !editingTitle.trim()}><Check size={14} /></button>
                      <button className="icon-button" type="button" aria-label="取消修改标题" title="取消" disabled={busy} onClick={handleCancelRename}><X size={14} /></button>
                    </form> : <>
                      <button className="ai-history-select" type="button" disabled={branchBusy} aria-current={item.id === conversationId ? "true" : undefined} onClick={() => void handleConversationSwitch(item.id)}>
                        <span><strong>{item.title}</strong><small>{scope}</small></span>
                        {item.id === conversationId && <span className="ai-history-current">当前</span>}
                      </button>
                      <div className="ai-history-item-actions">
                        <button className="icon-button" type="button" aria-label={`编辑对话标题：${item.title}`} title="修改标题" disabled={Boolean(historyActionBusy)} onClick={() => handleStartRename(item)}><Pencil size={13} /></button>
                        <button
                          className="icon-button ai-history-delete"
                          type="button"
                          aria-label={`删除对话：${item.title}`}
                          title={item.id === conversationId && Boolean(detail?.active_run) ? "请先取消当前回答" : "删除对话"}
                          disabled={Boolean(historyActionBusy) || (item.id === conversationId && Boolean(detail?.active_run))}
                          onClick={() => { setHistoryActionError(""); setHistoryDismissSuspended(true); setDeleteTarget(item); }}
                        ><Trash2 size={13} /></button>
                      </div>
                    </>}
                  </div>;
                })}
              </div>
            </div>}
          </div>
          <div className="ai-room-layer-anchor" ref={contextLayerRef}>
            <button
              className={`ai-room-tool-trigger ai-context-trigger${openLayer === "context" ? " is-open" : ""}`}
              type="button"
              aria-label="当前对话信息"
              title="当前对话信息"
              aria-expanded={openLayer === "context"}
              aria-controls="ai-conversation-context-panel"
              onClick={() => setOpenLayer((value) => value === "context" ? null : "context")}
            >
              <MapPin size={14} /><span>{contextTitle}</span>
            </button>
            {openLayer === "context" && <div id="ai-conversation-context-panel" className="ai-layer-panel ai-context-panel">
              <div className="ai-layer-heading"><div><small>{displayScope.toUpperCase()} CONTEXT</small><strong>{contextTitle}</strong></div><button className="icon-button" type="button" onClick={() => setOpenLayer(null)} aria-label="关闭当前对话信息"><X size={15} /></button></div>
              <p className="ai-context-panel-route">{learningContextRoute(displayContext, displayScope)}</p>
              {displayContext ? <ContextFacts context={displayContext} /> : learningBrief ? <LearningRoomBriefDetails brief={learningBrief} /> : <p>本次对话不自动注入计划数据。</p>}
            </div>}
          </div>
          <div className="ai-room-layer-anchor" ref={configLayerRef}>
            <button
              className={`ai-config-trigger${openLayer === "config" ? " is-open" : ""}`}
              type="button"
              aria-expanded={openLayer === "config"}
              title="对话配置"
              aria-controls="ai-conversation-config-panel"
              onClick={() => setOpenLayer((value) => value === "config" ? null : "config")}
            >
              <SlidersHorizontal size={14} /><span>对话配置</span>
            </button>
            {openLayer === "config" && <div id="ai-conversation-config-panel" className="ai-layer-panel ai-config-panel">
              <div className="ai-layer-heading"><div><small>CONVERSATION</small><strong>本次对话配置</strong></div><button className="icon-button" type="button" onClick={() => setOpenLayer(null)} aria-label="关闭对话配置"><X size={15} /></button></div>
              <label className="ai-room-config-select">
                <span>提供方 / 模型</span>
                <select
                  aria-label="对话引擎选择"
                  value={selectedConfigValue}
                  onChange={(event) => void handleConfigChange(event)}
                  disabled={configBusy || !providers.length || Boolean(detail?.active_run)}
                >
                  <option value="">默认配置</option>
                  {providers.flatMap((item) => (item.models ?? []).map((model: AiProviderModel) => (
                    <option key={`${item.id}::${model.id}`} value={`${item.id}::${model.id}`} disabled={!item.enabled || !model.enabled || model.discovery_status === "unavailable"}>
                      {item.display_name} · {model.display_name}{model.discovery_status === "stale" ? "（过期）" : ""}
                    </option>
                  )))}
                </select>
              </label>
              <p className="ai-config-summary">{selectedConfigValue ? `${activeProvider?.display_name ?? "未知提供方"} · ${activeModel?.display_name ?? "未知模型"}` : "跟随默认提供方和模型"}</p>
              <p className="ai-capability-summary">当前已启用：文本输入、流式回答{activeModel?.capabilities.supports_reasoning ? "、推理内容" : ""}</p>
              {!activeProvider?.has_api_key && <div className="ai-provider-note" role="note">尚未配置可用提供方。<button className="text-button" onClick={onProviderOpen}>现在配置</button></div>}
              <div className="ai-config-actions">
                <button className="button button--quiet button--with-icon" type="button" disabled={!selectedConfigValue || configBusy} onClick={handleRestoreSelection}><RotateCcw size={13} />恢复默认</button>
                <button className="button button--quiet button--with-icon" type="button" disabled={!conversationId || titleBusy || !detail?.messages.some((message) => message.status === "complete")} onClick={() => void handleRegenerateTitle()}><Sparkles size={13} />重新生成标题</button>
              </div>
              <p className="ai-title-note">{detail?.conversation.title_generation_status === "failed" ? "上次标题生成失败，当前保留本地标题。" : "首轮回答成功后自动生成一次；也可在这里手动重生成。"}</p>
            </div>}
          </div>
          <button className="button button--quiet button--compact button--with-icon" onClick={onProviderOpen} disabled={branchBusy} aria-label="AI 提供方设置" title="AI 提供方设置">
            <SlidersHorizontal size={15} /><span>AI 提供方设置</span>
          </button>
              {learningBrief?.action_id && learningBrief.delegation_id && <button className="button button--accent button--compact button--with-icon" type="button" disabled={branchBusy} aria-label={verificationCompleted ? "查看验证结果" : "进入验证"} onClick={() => setVerificationOpen(true)}>
            <ShieldCheck size={15} /><span>{verificationCompleted ? "查看验证结果" : "进入验证"}</span>
          </button>}
          <button className="icon-button icon-button--bordered" onClick={handleNewConversation} disabled={!entryReady || branchBusy} title="新建对话" aria-label="新建对话"><Plus size={16} /></button>
        </div>
      </header>

    {learningBrief && <><LearningRoomBriefCard brief={learningBrief} conversationId={conversationId} visibleMessages={visibleMessages} teaching={teaching} chatBusy={Boolean(currentRun) || status === "submitting" || status === "streaming" || status === "reconnecting"} /><div className="return-room-actions">
        <button className="button button--quiet" disabled={branchBusy} onClick={async () => { try { const card = await getReturnReview(); if (card) await chooseReturnReview(card.id, "stop_for_now", `room-stop:${card.id}`); onBack(); } catch (reason) { setError(reason instanceof Error ? reason.message : "暂停未保存"); } }}>今天先停</button>
        {learningBrief.delegation_id && !learningBrief.history_only && <button className="button button--quiet" type="button" aria-expanded={completionOpen} onClick={() => setCompletionOpen(value => !value)}>记录本次完成</button>}
        {learningBrief.continuity_review_id && <button className="text-button" onClick={async () => { try { await chooseReturnReview(learningBrief.continuity_review_id!, "corrected", `corrected:${learningBrief.continuity_review_id}`); onBack(); } catch { setError("纠正未保存，请重试"); } }}>恢复错了，重新选择</button>}
      </div></>}
      {!learningBrief && teaching}

      <div className="ai-chat-with-map">
      <ConversationStateNotice state={sharedState} onSelectPath={() => { void sharedState.save({ leaf_id: detail?.messages.filter(message => !message.source_scope?.purged).at(-1)?.id ?? null, paths: {} }); }} />
      {conversationId && <BranchMap kind="conversation" id={conversationId} revision={`${detail?.conversation.title}:${detail?.messages.at(-1)?.status}:${detail?.messages.length}`} disabled={branchBusy || Boolean(currentRun) || !entryReady || ['loading', 'submitting', 'streaming', 'reconnecting'].includes(status) || Boolean(editingMessageId) || Boolean(pendingSubmissionRef.current)}
        onNavigate={async (id, source) => { await handleConversationSwitch(id); if (source) setMapLocation({ id, source }); }}
        onRenamed={async () => { const [next, list] = await Promise.all([getAiConversation(conversationId), listAiConversations()]); if (conversationIdRef.current === conversationId) { setDetail(next); setConversations(list); } }} />}
      <LearningChatPanel title={conversationTitle} autoFollow={!editingMessageId && (replyHistory.following || status === "submitting")} followToken={`${conversationId}:${detail?.messages.filter(message => message.role === "user").length ?? 0}`} notice={<>
          <OutboundApproval kind="conversation" scopeId={conversationId} active={Boolean(currentRun)} />
          {detail?.branch_origin && <p className="ai-branch-origin">从另一对话分出 · <button className="text-button" type="button" disabled={branchBusy} onClick={() => void handleConversationSwitch(detail.branch_origin!.conversation_id)}>返回原对话</button></p>}
          {searchChoice.error && <p role="status">{searchChoice.error}</p>}
          {error && <div className="ai-room-error" role="alert"><CircleAlert size={15} /><span>{error}</span></div>}
          {status === "failed" && pendingSubmissionRef.current?.helpRequest && pendingContentRef.current && <button className="button button--quiet ai-retry-button button--with-icon" type="button" onClick={() => void submitMessage(pendingContentRef.current!, true, undefined, undefined, pendingSubmissionRef.current!.helpRequest)}><RefreshCw size={15} />重试发送帮助请求</button>}
          {status === "failed" && pendingSubmissionRef.current?.teachingAction && pendingContentRef.current && <button className="button button--quiet ai-retry-button button--with-icon" type="button" onClick={() => void submitMessage(pendingContentRef.current!, true, undefined, undefined, undefined, pendingSubmissionRef.current!.teachingAction)}><RefreshCw size={15} />重试发送</button>}
          {status === "failed" && !pendingSubmissionRef.current && !editingMessageId && detail?.messages.some((message) => message.role === "user") && (
            <button className="button button--quiet ai-retry-button button--with-icon" onClick={() => void handleRetry()}><RefreshCw size={15} />重新生成</button>
          )}
      </>} composer={<LearningComposer id="ai-learning-question" textareaRef={composerRef}
        value={draft} onChange={setDraft} onSubmit={handleSend} onKeyDown={handleComposerKeyDown}
        placeholder={sharedState.blocked ? "请先确认或修复当前学习状态" : canSend ? `输入关于${scopeNoun(effectiveScope)}的问题` : "请先配置 AI 提供方"}
        attachments={<ComposerAttachments kind="conversation" id={conversationId} identity={detail?.conversation.identity_id ?? null} contextKey={`${effectiveScope}:${effectiveTargetId}:${attachmentContext}`} scope={sourceScope} versions={materialVersions} onChange={setSourceScope} onVersions={setMaterialVersions} onEnsure={async () => (await ensureConversation()).conversation.id} supportsImages={activeModel?.capabilities.supports_image_input} onDraftChange={setAttachmentDraftIds} clearSignal={attachmentClearSignal} onBusyChange={setAttachmentBusy} disabled={!sharedState.ready || Boolean(currentRun) || status === 'submitting' || Boolean(editingMessageId)} />}
        disabled={!canSend || Boolean(editingMessageId)} sendDisabled={attachmentBusy} suggestions={<HelpControls disabled={!canSend || attachmentBusy || Boolean(editingMessageId)} onChoose={(kind, label) => void submitMessage(label, true, undefined, undefined, kind)} />} tools={<><SearchControls value={searchSelection} onChange={searchChoice.change} onReset={searchChoice.reset} overridden={searchChoice.overridden} publicQuery={publicQuery} onPublicQueryChange={setPublicQuery} disabled={!sharedState.ready || branchBusy || Boolean(currentRun) || status === 'submitting' || Boolean(editingMessageId)} providerKind={typeof activeModel?.overrides.api_protocol === "string" ? activeModel.overrides.api_protocol : activeProvider?.api_protocol} /><TaskMaterials kind="conversation" id={conversationId} identity={detail?.conversation.identity_id ?? null} scope={sourceScope} onChange={setSourceScope} onVersions={setMaterialVersions} evidenceVersionIds={(detail?.messages ?? []).flatMap(message => message.source_scope?.version_ids ?? [])} disabled={!sharedState.ready || Boolean(currentRun) || status === 'submitting' || Boolean(editingMessageId)} onEnsure={async () => (await ensureConversation()).conversation.id} onPurged={async () => { if (conversationId) { const next = await getAiConversation(conversationId); if (conversationIdRef.current === conversationId) { setDetail(next); await sharedState.reload(); } } }} candidates={webMaterialCandidates((detail?.messages ?? []).filter(message => message.role === 'assistant').map(message => ({ runId: message.ai_run_id, trace: message.search_trace, complete: message.status === 'complete' })))} /></>} actions={detail?.active_run && <button className="button button--danger button--with-icon" type="button" onClick={() => void handleCancel()}><Square size={14} fill="currentColor" />取消生成</button>}
      />}>
            {visibleMessages.length ? visibleMessages.map((message, index) => {
              const versions = message.role === 'user'
                ? detail!.messages.filter(item => item.role === 'user' && (item.question_version_id ?? item.id) === (message.question_version_id ?? message.id))
                : detail!.messages.filter(item => item.role === 'assistant' && item.parent_message_id === message.parent_message_id);
              const versionIndex = versions.findIndex(item => item.id === message.id);
              return <MessageBubble key={message.id} message={message} materialVersions={materialVersions} retryDisabled={!canSend || Boolean(editingMessageId)} branchDisabled={message.status === 'streaming' || Boolean(message.source_scope?.purged) || branchBusy || sendingRef.current || Boolean(pendingSubmissionRef.current) || Boolean(currentRun) || !entryReady || ['loading', 'submitting', 'streaming', 'reconnecting'].includes(status) || Boolean(editingMessageId)} onBranch={message.role === 'assistant' ? () => void handleBranch(message.id) : undefined}
                onHelpDisplay={async characters => {
                  try {
                    const record = await recordAiHelpDisplay(message.conversation_id, message.id, characters);
                    setFailedHelpDisplays(previous => { const next = { ...previous }; delete next[message.id]; return next; });
                    setDetail(previous => previous?.conversation.id === message.conversation_id ? {
                      ...previous, messages: previous.messages.map(item => item.id === message.id ? { ...item, help_record: record } : item),
                    } : previous);
                    return record;
                  } catch (reason) {
                    if (conversationIdRef.current === message.conversation_id) setFailedHelpDisplays(previous => ({ ...previous, [message.id]: characters }));
                    throw reason;
                  }
                }}
                editing={editingMessageId === message.id}
                editDisabled={!entryReady || branchBusy || Boolean(currentRun) || status === "submitting" || (Boolean(editingMessageId) && editingMessageId !== message.id)}
                sendDisabled={!canSend}
                onStartEdit={() => setEditingMessageId(message.id)}
                onCancelEdit={() => {
                  setEditingMessageId(null);
                  if (pendingSubmissionRef.current?.editMessageId === message.id) {
                    pendingSubmissionRef.current = null; pendingContentRef.current = null;
                    persistSession({ pending: undefined }); setError("");
                    if (status === "failed") setStatus("idle");
                  }
                }}
                onSendEdit={text => submitMessage(text, true, undefined, message.id)}
                version={{ disabled: branchBusy || Boolean(currentRun) || status === "submitting" || Boolean(editingMessageId), index: versionIndex, count: versions.length,
                  onPrevious: () => replyHistory.switchVersion(versions[versionIndex - 1].id),
                  onNext: () => replyHistory.switchVersion(versions[versionIndex + 1].id) }}
                onRetry={message.role === 'assistant' ? () => {
                  const question = detail!.messages.find(item => item.id === message.parent_message_id);
                  if (question) void submitMessage(question.content, true, message.id);
                } : undefined}
                automatic={message.role === "user" && (Boolean(message.client_message_id?.startsWith(LEARNING_PROMPT_ID_PREFIX))
                  || Boolean(learningBrief && index === 0 && message.content.startsWith("我正在执行下面这次学习安排。当前阶段只做资料整理、教学和答疑，不进入验证。")
                    && ["学习目标：", "本次任务：", "希望形成的能力：", "学习边界：", "停止条件："].every(label => message.content.includes(label))))} />;
            }) : (
              <div className="ai-empty-chat">
                <Bot size={24} />
                <h2>从一个学习问题开始</h2>
                <p>{emptyRoomCopy(effectiveScope)}</p>
              </div>
            )}
      </LearningChatPanel>
      </div>
      {helpHistoryOpen && <ConversationHelpDialog key={conversationId ?? 'new'} messages={detail?.messages ?? []} title={conversationTitle} failedDisplays={failedHelpDisplays} triggerRef={helpHistoryTriggerRef} onRetryDisplay={async message => {
        const characters = failedHelpDisplays[message.id];
        if (!characters || message.conversation_id !== conversationIdRef.current) return;
        const record = await recordAiHelpDisplay(message.conversation_id, message.id, characters);
        setFailedHelpDisplays(previous => { const next = { ...previous }; delete next[message.id]; return next; });
        setDetail(previous => previous?.conversation.id === message.conversation_id ? {
          ...previous, messages: previous.messages.map(item => item.id === message.id ? { ...item, help_record: record } : item),
        } : previous);
      }} onClose={closeHelpHistory} />}
      {deleteTarget && <ConversationDeleteDialog
        conversation={deleteTarget}
        busy={historyActionBusy === deleteTarget.id}
        dialogRef={deleteDialogRef}
        onCancel={() => { if (!historyActionBusy) closeDeleteDialog(); }}
        onConfirm={() => void handleConfirmDelete()}
      />}
    </div>
    </>
  );
}

function scopeNoun(scope: AiContextScope) {
  return { independent: "独立", global: "全局", plan: "当前计划", task: "当前任务" }[scope];
}

function ConversationHelpDialog({ messages, title, failedDisplays, triggerRef, onRetryDisplay, onClose }: {
  messages: AiMessage[]; title: string; failedDisplays: Record<string, number>;
  triggerRef: RefObject<HTMLButtonElement | null>;
  onRetryDisplay: (message: AiMessage) => Promise<void>;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [retryErrorId, setRetryErrorId] = useState<string | null>(null);
  const entries = messages.filter(message => message.role === 'assistant' && message.help_record);
  useEffect(() => {
    dialogRef.current?.querySelector<HTMLButtonElement>('button')?.focus();
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
      if (event.key !== 'Tab' || !dialogRef.current) return;
      const buttons = Array.from(dialogRef.current.querySelectorAll<HTMLButtonElement>('button:not([disabled])'));
      const first = buttons[0], last = buttons.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => { document.removeEventListener('keydown', onKeyDown); triggerRef.current?.focus(); };
  }, [onClose, triggerRef]);

  return <DialogPortal><div className="dialog-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={dialogRef} tabIndex={-1} className="ai-help-dialog" role="dialog" aria-modal="true" aria-labelledby="ai-help-dialog-title">
      <header className="dialog-header"><div><p className="eyebrow">CURRENT CONVERSATION</p><h2 id="ai-help-dialog-title">帮助记录</h2><p className="ai-help-dialog-title">{title}</p></div><button className="icon-button" type="button" aria-label="关闭帮助记录" onClick={onClose}><X size={18} /></button></header>
      <div className="ai-help-dialog-body">
        {entries.length === 0 ? <p>当前对话还没有帮助记录。无记录不证明独立完成。</p> : entries.map(message => {
          const question = messages.find(item => item.id === message.parent_message_id);
          const questionVersions = question ? messages.filter(item => item.role === 'user' && (item.question_version_id ?? item.id) === (question.question_version_id ?? question.id)) : [];
          const questionIndex = questionVersions.findIndex(item => item.id === question?.id) + 1;
          const answerVersions = messages.filter(item => item.role === 'assistant' && item.parent_message_id === message.parent_message_id);
          const answerIndex = answerVersions.findIndex(item => item.id === message.id) + 1;
          return <article key={message.id} className="ai-help-dialog-entry">
            <h3>问题版本 {questionIndex || '?'} / {questionVersions.length || '?'} · 回答版本 {answerIndex} / {answerVersions.length}</h3>
            {message.inherited_from && <p>原对话记录</p>}
            <p className="ai-help-dialog-question">{question?.content ?? '原问题不可用'}</p>
            <HelpRecordFacts record={message.help_record!} />
            {!message.inherited_from && failedDisplays[message.id] && !message.help_record?.display && <p role="alert">页面呈现记录未保存。
              <button className="text-button" type="button" disabled={retryingId === message.id} onClick={async () => {
                setRetryingId(message.id); setRetryErrorId(null);
                try { await onRetryDisplay(message); } catch { setRetryErrorId(message.id); }
                finally { setRetryingId(null); }
              }}>{retryingId === message.id ? '重试中' : '重试保存'}</button>
              {retryErrorId === message.id && ' 重试失败，请稍后再试。'}
            </p>}
          </article>;
        })}
      </div>
    </section>
  </div></DialogPortal>;
}

function learningContextTitle(context: AiLearningContext | null, scope: AiContextScope) {
  if (context?.scope_kind === "task") return context.task_title;
  if (context?.scope_kind === "plan") return context.goal_title;
  if (context?.scope_kind === "global") return "全局学习工作区";
  return scope === "global" ? "全局学习工作区" : scope === "plan" ? "当前计划" : scope === "task" ? "当前任务" : "独立对话";
}

function learningContextRoute(context: AiLearningContext | null, scope: AiContextScope) {
  if (context?.scope_kind === "task") return context.route;
  if (context?.scope_kind === "plan") return `${context.goal_title} / ${context.subject_count} 个科目 / ${context.task_count} 项任务`;
  if (context?.scope_kind === "global") return `全部活动计划 / ${context.plan_counts.total} 个计划 / ${context.task_counts.total} 项待执行任务`;
  return scope === "independent" ? "未关联计划或任务" : "上下文正在加载";
}

function ContextFacts({ context }: { context: AiLearningContext }) {
  if (context.scope_kind === "task") return <dl><div><dt>状态</dt><dd>{context.status}</dd></div><div><dt>截止</dt><dd>{context.due_date}</dd></div><div><dt>进度</dt><dd>{context.progress}%</dd></div></dl>;
  if (context.scope_kind === "plan") return <dl><div><dt>状态</dt><dd>{context.status}</dd></div><div><dt>任务</dt><dd>{context.completed_task_count} / {context.task_count}</dd></div><div><dt>进度</dt><dd>{context.progress}%</dd></div></dl>;
  return <dl><div><dt>计划</dt><dd>{context.plan_counts.total}</dd></div><div><dt>待执行</dt><dd>{context.task_counts.total}</dd></div><div><dt>逾期</dt><dd>{context.task_counts.overdue}</dd></div></dl>;
}

function LearningRoomBriefCard({ brief, conversationId, visibleMessages, chatBusy, teaching }: { brief: LearningRoomBrief; conversationId: string | null; visibleMessages: AiMessage[]; chatBusy: boolean; teaching: ReactNode }) {
  return (
    <section className="ai-room-brief" aria-label="本次学习安排">
      <details>
        <summary>学习安排 · {brief.action_title}</summary>
        <div className="ai-room-brief__route">{brief.goal_title} / {brief.plan_title}</div>
        <div className="ai-room-brief__items">
          <span><b>成果</b>{brief.outcome_object}；{brief.outcome_behavior}</span>
          {brief.boundaries && <span><b>边界</b>{brief.boundaries}</span>}
          <span><b>停止</b>{brief.stop_conditions}</span>
        </div>
        {teaching}
        {/* Learning position remains a separate, revisable note. */}
        {brief.session_id && <LearningPosition key={`${brief.session_id}:${conversationId}`} sessionId={brief.session_id} conversationId={conversationId} visibleMessages={visibleMessages} chatBusy={chatBusy} />}
      </details>
    </section>
  );
}

function LearningRoomBriefDetails({ brief }: { brief: LearningRoomBrief }) {
  return (
    <dl>
      <div><dt>目标</dt><dd>{brief.goal_title}</dd></div>
      <div><dt>任务</dt><dd>{brief.action_title}</dd></div>
      <div><dt>成果</dt><dd>{brief.outcome_object}；{brief.outcome_behavior}</dd></div>
      {brief.boundaries && <div><dt>边界</dt><dd>{brief.boundaries}</dd></div>}
      <div><dt>停止</dt><dd>{brief.stop_conditions}</dd></div>
    </dl>
  );
}

function emptyRoomCopy(scope: AiContextScope) {
  return {
    global: "我会综合多个计划、今日任务和近期截止项，帮助你规划整体学习节奏。",
    plan: "我会围绕当前计划的科目、主题、任务、排期和进度回答。",
    task: "我会结合当前任务及其完整学习路径，帮助你拆解概念、练习和复习。",
    independent: "这个对话不自动注入计划数据，适合自由探索一个学习问题。",
  }[scope];
}

function ConversationDeleteDialog({
  conversation,
  busy,
  dialogRef,
  onCancel,
  onConfirm,
}: {
  conversation: AiConversation;
  busy: boolean;
  dialogRef: RefObject<HTMLElement | null>;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  useEffect(() => {
    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape" && !busy) onCancel();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [busy, onCancel]);

  return (
    <DialogPortal>
      <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onCancel(); }}>
        <section ref={dialogRef} className="confirm-dialog ai-conversation-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="ai-conversation-delete-title" onMouseDown={(event) => event.stopPropagation()}>
          <div className="confirm-icon"><Trash2 size={20} /></div>
          <h2 id="ai-conversation-delete-title">删除“{conversation.title}”？</h2>
          <p>删除后，这个对话将从历史记录中移除，当前无法恢复。确定继续吗？</p>
          <div className="confirm-actions">
            <button className="button button--quiet" type="button" disabled={busy} onClick={onCancel}>取消</button>
            <button className="button button--danger" type="button" disabled={busy} onClick={onConfirm}>{busy ? "删除中" : "确认删除"}</button>
          </div>
        </section>
      </div>
    </DialogPortal>
  );
}

function MessageBubble({ message, automatic = false, onRetry, retryDisabled, onBranch, branchDisabled, version, editing, editDisabled, sendDisabled, onStartEdit, onCancelEdit, onSendEdit, onHelpDisplay, materialVersions }: {
  message: AiMessage; automatic?: boolean; onRetry?: () => void; retryDisabled?: boolean; onBranch?: () => void; branchDisabled?: boolean; materialVersions: MaterialVersion[];
  onHelpDisplay: (characters: number) => Promise<NonNullable<AiMessage['help_record']>>;
  version?: { disabled?: boolean; index: number; count: number; onPrevious: () => void; onNext: () => void };
  editing: boolean; editDisabled: boolean; sendDisabled: boolean; onStartEdit: () => void; onCancelEdit: () => void; onSendEdit: (text: string) => Promise<boolean>;
}) {
  const isUser = message.role === "user";
  if (isUser) return <LearningUserMessage content={message.content} automatic={automatic} version={version}
    editing={editing} editDisabled={editDisabled} sendDisabled={sendDisabled}
    onStartEdit={onStartEdit} onCancelEdit={onCancelEdit} onSendEdit={onSendEdit}
    attachments={<MessageAttachments kind="conversation" id={message.conversation_id} versionIds={message.attachment_version_ids ?? []} versions={materialVersions} />} />;
  return (
    <LearningMessage id={`answer-${message.id}`} role="assistant" state={message.status !== "complete" ? message.status : undefined} status={message.status !== "complete" ? (message.status === "streaming" ? "生成中" : message.status === "failed" ? "失败" : "已取消") : undefined}>
      {message.inherited_from && <small className="ai-inherited-answer">继承的历史回答</small>}
      <AssistantResponse key={message.id} trace={message.generation_trace} content={message.content} reasoningContent={message.reasoning_content} searchTrace={message.search_trace} streaming={message.status === "streaming"} />
      {!message.inherited_from && <HelpRecord key={`help:${message.id}`} record={message.help_record} body={message.content} terminal={message.status !== 'streaming'} showDetails={false} onDisplay={onHelpDisplay} />}
      <LearningReplyActions version={version} content={message.content} onRetry={onRetry} retryDisabled={retryDisabled || message.status === 'streaming'} onBranch={onBranch} branchDisabled={branchDisabled} more={<MaterialUse scope={message.source_scope} versions={materialVersions} kind="conversation" scopeId={message.conversation_id} />} />
    </LearningMessage>
  );
}
