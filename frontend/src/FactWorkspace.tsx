import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  analyzeLearningArtifact,
  confirmLearningSetup,
  approveAgentPermissionRequest,
  batchReviewEvidenceClaims,
  createAgentPermissionRequest,
  correctLearningArtifact,
  createLearningAction,
  createLearningDelegation,
  createLearningOutcome,
  createLearningSetupDraft,
  denyAgentPermissionRequest,
  endLearningSession,
  getAgentContext,
  getLearningEvents,
  getLearningEvidenceProvider,
  getLearningMetrics,
  getLearningState,
  getLearningRoom,
  listAgentPermissionRequests,
  listAiProviders,
  recalculateDerivedStates,
  replayEvidence,
  clearLearningEvidenceProvider,
  setLearningEvidenceProvider,
  replayLearning,
  requestEvidenceHumanReview,
  revokeAgentPermissionGrant,
  restoreLearningArtifact,
  purgeLearningArtifact,
  softDeleteLearningArtifact,
  withdrawLearningArtifact,
  reviewEvidenceClaim,
  saveLearningArtifact,
  scheduleEvidenceSupplementalVerification,
  startLearningSession,
  type LearningAction,
  type LearningArtifact,
  type LearningDelegation,
  type LearningEvent,
  type LearningOutcome,
  type LearningSession,
  type LearningSetupDraft,
  type LearningRoomBrief,
  type AgentPermissionRequest,
  type AiProvider,
  type LearningEvidenceProviderSelection,
  type LearningMeasurementReport,
  type AgentContext,
  type LearningState,
  type Task,
} from "./api";

type FactOperation =
  | "action"
  | "outcome"
  | "delegation"
  | "session"
  | "artifact"
  | "end"
  | "correction"
  | "replay"
  | "agent-request"
  | "analysis"
  | "human-review"
  | "supplemental-verification"
  | "review"
  | "batch-review"
  | "recalculate"
  | "artifact-lifecycle"
  | "evidence-replay"
  | "setup";

function operationKey(scope: FactOperation, signature: string): string {
  const storageKey = `nautilus.fact.${scope}`;
  try {
    const raw = window.sessionStorage.getItem(storageKey);
    const parsed = raw ? JSON.parse(raw) as { signature?: unknown; key?: unknown } : null;
    if (parsed?.signature === signature && typeof parsed.key === "string") return parsed.key;
  } catch {
    // Storage is optional; a fresh key is still safe.
  }
  const key = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  try {
    window.sessionStorage.setItem(storageKey, JSON.stringify({ signature, key }));
  } catch {
    // Refresh recovery is best-effort.
  }
  return key;
}

function clearOperationKey(scope: FactOperation): void {
  try {
    window.sessionStorage.removeItem(`nautilus.fact.${scope}`);
  } catch {
    // Ignore storage failures.
  }
}

function formatTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function formatAgentRequestStatus(request: AgentPermissionRequest): string {
  const scope = request.scope === "learning_action" ? "任务范围" : request.scope;
  const granularity = request.content_granularity === "metadata" ? "摘要" : "原文";
  const expiry = `${Math.round(request.ttl_seconds / 60)} 分钟 · 到 ${formatTime(request.expires_at)}`;
  if (request.grant_status === "active") return `已批准 · ${scope} · ${granularity} · ${expiry}`;
  if (request.grant_status === "revoked") return `授权已撤销 · ${scope} · ${granularity} · ${expiry}`;
  if (request.grant_status === "expired") return `授权已过期 · ${scope} · ${granularity} · ${expiry}`;
  if (request.status === "denied") return `已拒绝 · ${scope} · ${granularity} · ${expiry}`;
  if (request.status === "expired") return `申请已过期 · ${scope} · ${granularity} · ${expiry}`;
  return `等待处理 · ${scope} · ${granularity} · ${expiry}`;
}

function formatUnavailableContext(items: string[]): string {
  if (items.length === 0) return "授权范围内可读";
  const labels = items.map((item) => {
    if (item === "raw_text") return "原文";
    if (item === "authorized_artifact_metadata") return "授权产出元数据";
    return item;
  });
  return `不可用：${labels.join("、")}`;
}

function manualSetupDraft(intent: string): LearningSetupDraft {
  const subject = intent.trim().slice(0, 120);
  return {
    goal_title: subject,
    goal_description: intent.trim(),
    plan_title: `${subject}：第一步`,
    plan_description: "先完成一个可检查的小步骤，再根据真实产出调整路线。",
    action_title: "完成一次最小练习并说明自己的理解",
    context_key: "guided",
    outcome_object: "一份与学习目标相关的解释或练习产出",
    outcome_behavior: "能独立说明关键思路并完成一个最小示例",
    outcome_context_key: "guided",
    boundaries: "只处理第一步所需的核心概念和一个最小示例。",
    stop_conditions: "完成一份可检查的产出，并记录仍然不确定的地方。",
    time_budget_minutes: 30,
    recommended_criterion_id: null,
    rationale: "这是手动起步草案，完成一次后再根据真实表现调整。",
  };
}

type FactWorkspaceProps = {
  existingTasks?: Task[];
  onOpenTaskLearning?: (taskId: string) => void;
  onStartTaskTimer?: (taskId: string) => Promise<boolean>;
  onOpenLearningRoom?: (initialDraft: string, brief: LearningRoomBrief) => void;
};

type LearningEntryMode = "guided" | "direct";

export default function FactWorkspace({
  existingTasks = [],
  onOpenTaskLearning,
  onStartTaskTimer,
  onOpenLearningRoom,
}: FactWorkspaceProps) {
  const [state, setState] = useState<LearningState | null>(null);
  const [metrics, setMetrics] = useState<LearningMeasurementReport | null>(null);
  const [events, setEvents] = useState<LearningEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedActionId, setSelectedActionId] = useState<string | null>(null);
  const [selectedOutcomeId, setSelectedOutcomeId] = useState<string | null>(null);
  const [selectedDelegationId, setSelectedDelegationId] = useState<string | null>(null);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [agentRequests, setAgentRequests] = useState<AgentPermissionRequest[]>([]);
  const [agentContext, setAgentContext] = useState<AgentContext | null>(null);
  const [agentGranularity, setAgentGranularity] = useState<"metadata" | "full_text">("metadata");
  const [providers, setProviders] = useState<AiProvider[]>([]);
  const [providerSelection, setProviderSelection] = useState<LearningEvidenceProviderSelection | null>(null);
  const [providerDraft, setProviderDraft] = useState({ providerId: "", modelId: "" });
  const [providersLoading, setProvidersLoading] = useState(true);
  const [providerBusy, setProviderBusy] = useState(false);
  const [setupIntent, setSetupIntent] = useState("");
  const [setupDraft, setSetupDraft] = useState<LearningSetupDraft | null>(null);
  const [setupCriterionId, setSetupCriterionId] = useState("");
  const [setupConfirmed, setSetupConfirmed] = useState(false);
  const [entryMode, setEntryMode] = useState<LearningEntryMode>("guided");
  const [directTaskId, setDirectTaskId] = useState("");

  const [actionForm, setActionForm] = useState({ title: "", contextKey: "default" });
  const [outcomeForm, setOutcomeForm] = useState({
    objectDescription: "",
    behavior: "",
    contextKey: "default",
  });
  const [delegationForm, setDelegationForm] = useState({
    boundaries: "",
    stopConditions: "",
    timeBudgetMinutes: 30,
    criterionId: "",
  });
  const [artifactForm, setArtifactForm] = useState({ content: "" });
  const [correctionForm, setCorrectionForm] = useState({ content: "" });
  const [purgeConfirmation, setPurgeConfirmation] = useState("");

  const loadState = useCallback(async () => {
    try {
      const [nextState, nextMetrics] = await Promise.all([
        getLearningState(),
        getLearningMetrics(),
      ]);
      setState(nextState);
      setMetrics(nextMetrics);
      setError("");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "事实工作台加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadState();
  }, [loadState]);

  const loadProviderSettings = useCallback(async () => {
    setProvidersLoading(true);
    try {
      const [nextProviders, nextSelection] = await Promise.all([
        listAiProviders(),
        getLearningEvidenceProvider(),
      ]);
      setProviders(nextProviders);
      setProviderSelection(nextSelection);

      const fallbackProvider = nextProviders.find((item) => item.is_default) ?? nextProviders[0] ?? null;
      const explicitProvider = nextSelection
        ? nextProviders.find((item) => item.id === nextSelection.provider_profile_id) ?? null
        : null;
      const explicitModel = explicitProvider?.models?.find(
        (item) => item.id === nextSelection?.provider_model_id,
      ) ?? null;
      const explicitSelectionUnavailable = Boolean(
        nextSelection &&
        (!explicitProvider ||
          !explicitProvider.enabled ||
          !explicitProvider.has_api_key ||
          !explicitModel ||
          !explicitModel.enabled ||
          explicitModel.discovery_status === "unavailable"),
      );
      const draftProvider = explicitSelectionUnavailable ? fallbackProvider : explicitProvider ?? fallbackProvider;
      const draftModel = explicitSelectionUnavailable
        ? draftProvider?.default_model ?? draftProvider?.models?.find((item) => item.enabled) ?? null
        : explicitModel ?? draftProvider?.default_model ?? draftProvider?.models?.find((item) => item.enabled) ?? null;
      setProviderDraft({
        providerId: draftProvider?.id ?? "",
        modelId: draftModel?.id ?? "",
      });
      setError("");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "证据分析 Provider 设置加载失败");
    } finally {
      setProvidersLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProviderSettings();
  }, [loadProviderSettings]);

  useEffect(() => {
    setDirectTaskId((current) =>
      current && existingTasks.some((task) => task.id === current && task.status !== "canceled")
        ? current
        : existingTasks.find((task) => task.status !== "canceled")?.id ?? "",
    );
  }, [existingTasks]);

  useEffect(() => {
    const runningSession = state?.sessions.find((session) => session.status === "running");
    if (runningSession) setSelectedDelegationId(runningSession.delegation_id);
  }, [state]);

  const loadAgentRequests = useCallback(async () => {
    try {
      setAgentRequests(await listAgentPermissionRequests());
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Agent 权限申请加载失败");
    }
  }, []);

  useEffect(() => {
    void loadAgentRequests();
  }, [loadAgentRequests]);

  const loadAgentContext = useCallback(async (targetId?: string) => {
    try {
      setAgentContext(await getAgentContext(targetId));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Agent 上下文加载失败");
    }
  }, []);

  useEffect(() => {
    void loadAgentContext(selectedActionId ?? undefined);
  }, [loadAgentContext, selectedActionId]);

  async function clearProviderSelection() {
    if (providerBusy || providerSelection == null) return;
    setProviderBusy(true);
    setError("");
    setNotice("");
    try {
      await clearLearningEvidenceProvider();
      setProviderSelection(null);
      const fallbackProvider = providers.find((item) => item.is_default) ?? providers[0] ?? null;
      const fallbackModel = fallbackProvider?.default_model
        ?? fallbackProvider?.models?.find((item) => item.enabled)
        ?? null;
      setProviderDraft({
        providerId: fallbackProvider?.id ?? "",
        modelId: fallbackModel?.id ?? "",
      });
      setNotice("证据分析 Provider 已恢复默认");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "证据分析 Provider 恢复默认失败");
    } finally {
      setProviderBusy(false);
    }
  }

  async function submitProviderSelection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (providerBusy || !providerDraft.providerId || !providerDraft.modelId) {
      setError("请选择证据分析 Provider 和模型");
      return;
    }
    setProviderBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await setLearningEvidenceProvider({
        provider_profile_id: providerDraft.providerId,
        provider_model_id: providerDraft.modelId,
      });
      setProviderSelection(result);
      setNotice("证据分析 Provider 已保存");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "证据分析 Provider 保存失败");
    } finally {
      setProviderBusy(false);
    }
  }

  function handleProviderDraftChange(providerId: string) {
    const provider = providers.find((item) => item.id === providerId) ?? null;
    const model = provider?.default_model?.enabled && provider.default_model.discovery_status !== "unavailable"
      ? provider.default_model
      : provider?.models?.find((item) => item.enabled && item.discovery_status !== "unavailable") ?? null;
    setProviderDraft({ providerId, modelId: model?.id ?? "" });
  }

  const selectedAction = useMemo<LearningAction | null>(() => {
    if (!state) return null;
    return state.actions.find((action) => action.id === selectedActionId) ?? state.actions[0] ?? null;
  }, [state, selectedActionId]);

  const selectedOutcome = useMemo<LearningOutcome | null>(() => {
    if (!state) return null;
    return state.outcomes.find((outcome) => outcome.id === selectedOutcomeId) ?? state.outcomes[0] ?? null;
  }, [state, selectedOutcomeId]);

  const selectedDelegation = useMemo<LearningDelegation | null>(() => {
    if (!state) return null;
    return (
      state.delegations.find((delegation) => delegation.id === selectedDelegationId) ??
      state.delegations.find((delegation) => delegation.action_id === selectedAction?.id) ??
      state.delegations[0] ??
      null
    );
  }, [state, selectedDelegationId, selectedAction?.id]);

  const selectedSession = useMemo<LearningSession | null>(() => {
    if (!state || !selectedDelegation) return null;
    return (
      state.sessions.find((session) => session.delegation_id === selectedDelegation.id && session.status === "running") ??
      state.sessions.find((session) => session.delegation_id === selectedDelegation.id) ??
      null
    );
  }, [state, selectedDelegation]);

  const selectedArtifact = useMemo<LearningArtifact | null>(() => {
    if (!state) return null;
    return (
      state.artifacts.find((artifact) => artifact.id === selectedArtifactId) ??
      state.artifacts.find((artifact) => artifact.session_id === selectedSession?.id) ??
      state.artifacts[0] ??
      null
    );
  }, [state, selectedArtifactId, selectedSession?.id]);

  useEffect(() => {
    if (!selectedAction) {
      setEvents([]);
      return;
    }
    let cancelled = false;
    getLearningEvents(selectedAction.id)
      .then((nextEvents) => {
        if (!cancelled) setEvents(nextEvents);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "事实事件加载失败");
      });
    return () => {
      cancelled = true;
    };
  }, [selectedAction]);

  async function runOperation(
    operation: FactOperation,
    signature: string,
    action: () => Promise<void>,
    clearKey = true,
  ) {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      if (clearKey) clearOperationKey(operation);
      await loadState();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "学习事实操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function submitAction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const payload = {
      title: actionForm.title.trim(),
      context_key: actionForm.contextKey.trim() || "default",
    };
    if (!payload.title) {
      setError("任务标题不能为空");
      return;
    }
    await runOperation("action", JSON.stringify(payload), async () => {
      const result = await createLearningAction({
        ...payload,
        idempotency_key: operationKey("action", JSON.stringify(payload)),
      });
      setSelectedActionId(result.id);
      setActionForm({ title: "", contextKey: payload.context_key });
      setNotice("任务已保存");
    });
  }

  async function handleSetupDraft() {
    const intent = setupIntent.trim();
    if (!intent || busy) {
      if (!intent) setError("先说说你想学会什么");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const draft = await createLearningSetupDraft(intent);
      setSetupDraft(draft);
      setSetupCriterionId(draft.recommended_criterion_id ?? "");
      setSetupConfirmed(false);
      setNotice("AI 已整理出第一步学习安排，请确认或修改");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "AI 学习初始化失败");
    } finally {
      setBusy(false);
    }
  }

  function handleManualSetup() {
    const intent = setupIntent.trim();
    if (!intent) {
      setError("先说说你想学会什么");
      return;
    }
    setSetupDraft(manualSetupDraft(intent));
    setSetupCriterionId("");
    setSetupConfirmed(false);
    setError("");
    setNotice("已切换为手动起步，你仍可以修改这份安排");
  }

  async function handleConfirmSetup() {
    if (!setupDraft || busy) return;
    const standard = state?.standards.find((item) => item.id === setupCriterionId) ?? null;
    const payload = {
      original_intent: setupIntent.trim(),
      goal_title: setupDraft.goal_title.trim(),
      goal_description: setupDraft.goal_description.trim(),
      plan_title: setupDraft.plan_title.trim(),
      plan_description: setupDraft.plan_description.trim(),
      action_title: setupDraft.action_title.trim(),
      context_key: standard?.context_key ?? setupDraft.context_key.trim(),
      outcome_id: standard?.outcome_id ?? null,
      object_description: standard?.object_description ?? setupDraft.outcome_object.trim(),
      behavior: standard?.behavior ?? setupDraft.outcome_behavior.trim(),
      outcome_context_key: standard?.context_key ?? setupDraft.outcome_context_key.trim(),
      criterion_id: standard?.id ?? null,
      boundaries: setupDraft.boundaries.trim(),
      stop_conditions: setupDraft.stop_conditions.trim(),
      time_budget_minutes: setupDraft.time_budget_minutes || null,
    };
    if (!payload.original_intent || !payload.goal_title || !payload.plan_title || !payload.action_title) {
      setError("目标、计划和任务名称不能为空");
      return;
    }
    if (!payload.stop_conditions) {
      setError("请补充本次学习的停止条件");
      return;
    }
    await runOperation("setup", JSON.stringify(payload), async () => {
      const result = await confirmLearningSetup({
        ...payload,
        idempotency_key: operationKey("setup", JSON.stringify(payload)),
      });
      setSelectedActionId(result.action_id);
      setSelectedOutcomeId(result.outcome_id);
      setSelectedDelegationId(result.delegation_id);
      setSetupConfirmed(true);
      setNotice("学习安排已确认，下一步是开始这项任务");
    });
  }

  async function handleStartGuidedSession() {
    const session = await handleStartSession();
    if (!session) return;
    if (onOpenLearningRoom) {
      const draft = setupDraft
        ? [
            "我正在执行下面这次学习安排。当前阶段只做资料整理、教学和答疑，不进入验证。",
            "请先基于可核验的权威资料组织教学内容，给出用户可以打开的来源链接和阅读顺序；如果当前运行环境不能联网，请明确说明，不要编造来源或链接。",
            "可以根据这些资料直接为我讲解，但本轮不要出验证题、练习题、判断题、填空题或标准答案，等我明确点击“开始验证”后再进入验证阶段。",
            `学习目标：${setupIntent.trim()}`,
            `本次任务：${setupDraft.action_title.trim()}`,
            `希望形成的能力：${setupDraft.outcome_object.trim()}；${setupDraft.outcome_behavior.trim()}`,
            `学习边界：${setupDraft.boundaries.trim()}`,
            `停止条件：${setupDraft.stop_conditions.trim()}`,
          ].filter(Boolean).join("\n")
        : undefined;
      onOpenLearningRoom(draft ?? "", {
        action_id: selectedAction?.id,
        delegation_id: selectedDelegation?.id,
        session_id: session.id,
        criterion_id: selectedDelegation?.criterion_id,
        goal_title: setupDraft?.goal_title.trim() ?? setupIntent.trim(),
        plan_title: setupDraft?.plan_title.trim() ?? "本次学习安排",
        action_title: setupDraft?.action_title.trim() ?? selectedAction?.title ?? "当前学习任务",
        outcome_object: setupDraft?.outcome_object.trim() ?? selectedOutcome?.object_description ?? "",
        outcome_behavior: setupDraft?.outcome_behavior.trim() ?? selectedOutcome?.behavior ?? "",
        boundaries: setupDraft?.boundaries.trim() ?? "",
        stop_conditions: setupDraft?.stop_conditions.trim() ?? "",
      });
      return;
    }
    document.getElementById("learning-session-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function handleResumeLearningRoom() {
    if (!selectedSession || !onOpenLearningRoom) return;
    setBusy(true);
    try {
      const room = await getLearningRoom(selectedSession.id);
      onOpenLearningRoom("", room.brief);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "学习室恢复失败");
    } finally { setBusy(false); }
  }

  async function submitOutcome(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const payload = {
      object_description: outcomeForm.objectDescription.trim(),
      behavior: outcomeForm.behavior.trim(),
      context_key: outcomeForm.contextKey.trim() || "default",
    };
    if (!payload.object_description || !payload.behavior) {
      setError("可验证成果的对象和行为不能为空");
      return;
    }
    await runOperation("outcome", JSON.stringify(payload), async () => {
      const result = await createLearningOutcome({
        ...payload,
        idempotency_key: operationKey("outcome", JSON.stringify(payload)),
      });
      setSelectedOutcomeId(result.id);
      setOutcomeForm({ objectDescription: "", behavior: "", contextKey: payload.context_key });
      setNotice("可验证成果已保存");
    });
  }

  async function submitDelegation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedAction || !selectedOutcome) {
      setError("请先选择任务和可验证成果");
      return;
    }
    const payload = {
      action_id: selectedAction.id,
      outcome_id: selectedOutcome.id,
      criterion_id: delegationForm.criterionId || null,
      boundaries: delegationForm.boundaries.trim(),
      stop_conditions: delegationForm.stopConditions.trim(),
      time_budget_minutes: delegationForm.timeBudgetMinutes || null,
      expected_version: selectedAction.aggregate_version,
    };
    if (!payload.stop_conditions) {
      setError("停止条件不能为空");
      return;
    }
    await runOperation("delegation", JSON.stringify(payload), async () => {
      const result = await createLearningDelegation({
        ...payload,
        idempotency_key: operationKey("delegation", JSON.stringify(payload)),
      });
      setSelectedDelegationId(result.id);
      setDelegationForm({ boundaries: "", stopConditions: "", timeBudgetMinutes: 30, criterionId: "" });
      setNotice("学习委托已保存");
    });
  }

  async function handleStartSession(): Promise<{ id: string } | null> {
    if (!selectedDelegation || !selectedAction) return null;
    let started: { id: string } | null = null;
    const payload = {
      delegation_id: selectedDelegation.id,
      expected_version: selectedAction.aggregate_version,
    };
    await runOperation("session", JSON.stringify(payload), async () => {
      const result = await startLearningSession({
        ...payload,
        idempotency_key: operationKey("session", JSON.stringify(payload)),
      });
      started = result;
      setNotice("学习会话已开始");
    });
    return started;
  }

  async function handleDirectLearning(withTimer: boolean) {
    const task = existingTasks.find((item) => item.id === directTaskId && item.status !== "canceled");
    if (!task || !onOpenTaskLearning) {
      setError(existingTasks.some((item) => item.status !== "canceled") ? "请选择一个计划任务" : "还没有可进入学习室的计划任务");
      return;
    }
    if (withTimer && task.status === "completed") {
      setError("已完成任务可以进入学习室，但不能重新开始计时");
      return;
    }
    if (withTimer && onStartTaskTimer) {
      const started = await onStartTaskTimer(task.id);
      if (!started) return;
    }
    onOpenTaskLearning(task.id);
  }

  async function submitArtifact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedSession || !selectedAction) return;
    const payload = {
      session_id: selectedSession.id,
      content: artifactForm.content,
      expected_version: selectedAction.aggregate_version,
    };
    if (!payload.content.trim()) {
      setError("学习产出不能为空");
      return;
    }
    await runOperation("artifact", JSON.stringify(payload), async () => {
      const result = await saveLearningArtifact({
        ...payload,
        idempotency_key: operationKey("artifact", JSON.stringify(payload)),
      });
      setSelectedArtifactId(result.id);
      setArtifactForm({ content: "" });
      setNotice("学习产出已保存");
    });
  }

  async function handleEndSession(disposition: "ended" | "interrupted") {
    if (!selectedSession || !selectedAction) return;
    const payload = {
      disposition,
      expected_version: selectedAction.aggregate_version,
    };
    await runOperation("end", JSON.stringify({ ...payload, session_id: selectedSession.id }), async () => {
      await endLearningSession(selectedSession.id, {
        ...payload,
        idempotency_key: operationKey("end", JSON.stringify({ ...payload, session_id: selectedSession.id })),
      });
      setNotice(disposition === "ended" ? "学习会话已结束" : "学习会话已中断");
    });
  }

  async function submitCorrection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedArtifact || !selectedAction) return;
    const payload = {
      content: correctionForm.content,
      expected_version: selectedAction.aggregate_version,
    };
    if (!payload.content.trim()) {
      setError("更正内容不能为空");
      return;
    }
    await runOperation("correction", JSON.stringify({ ...payload, artifact_id: selectedArtifact.id }), async () => {
      await correctLearningArtifact(selectedArtifact.id, {
        ...payload,
        idempotency_key: operationKey("correction", JSON.stringify({ ...payload, artifact_id: selectedArtifact.id })),
      });
      setCorrectionForm({ content: "" });
      setNotice("学习产出已追加更正版本");
    });
  }

  async function handleAnalyzeArtifact() {
    if (!selectedArtifact) return;
    const payload = {
      artifact_id: selectedArtifact.id,
      content_version: selectedArtifact.content_version,
    };
    await runOperation("analysis", JSON.stringify(payload), async () => {
      const result = await analyzeLearningArtifact(selectedArtifact.id, {
        content_version: payload.content_version,
        request_key: operationKey("analysis", JSON.stringify(payload)),
      });
      if (result.run.status === "succeeded") {
        setNotice(`证据分析完成：生成 ${result.claims.length} 条候选主张`);
      } else if (result.run.status === "blocked_no_criterion") {
        setNotice("没有合格标准，产出已保存但不会生成证据主张");
      } else {
        setNotice(`证据分析未完成：${result.run.status}${result.run.reason ? ` · ${result.run.reason}` : ""}`);
      }
    }, false);
  }

  async function handleReplay() {
    await runOperation("replay", "replay", async () => {
      const result = await replayLearning();
      setNotice(`事实回放完成：${result.event_count} 个事件，${result.aggregate_count} 个聚合`);
    });
  }

  async function handleReviewClaim(
    claimId: string,
    action: "adopt" | "question" | "withdraw" | "defer",
  ) {
    const payload = { claim_id: claimId, action };
    await runOperation("review", JSON.stringify(payload), async () => {
      await reviewEvidenceClaim(claimId, {
        action,
        reason:
          action === "adopt"
            ? "符合标准配方"
            : action === "question"
              ? "需要进一步复核"
              : action === "withdraw"
                ? "撤出当前状态计算"
                : "暂不处理",
        request_key: operationKey("review", JSON.stringify(payload)),
      });
      setNotice(
        action === "adopt"
          ? "主张已采纳，状态已重新计算"
          : action === "question"
            ? "主张已质疑，状态已重新计算"
            : action === "withdraw"
              ? "主张已撤回，状态已重新计算"
              : "主张保持候选，暂不处理",
      );
    }, false);
  }

  async function handleArtifactLifecycle(
    action: "soft-delete" | "restore" | "withdraw" | "purge",
  ) {
    if (!selectedArtifact || !selectedAction) return;
    if (action === "purge" && purgeConfirmation !== "PURGE") {
      setError("请输入 PURGE 以确认彻底删除");
      return;
    }
    const payload = {
      artifact_id: selectedArtifact.id,
      action,
      expected_version: selectedAction.aggregate_version,
      confirmation: action === "purge" ? "PURGE" : undefined,
    };
    await runOperation("artifact-lifecycle", JSON.stringify(payload), async () => {
      if (action === "soft-delete") {
        await softDeleteLearningArtifact(selectedArtifact.id, {
          expected_version: payload.expected_version,
          idempotency_key: operationKey("artifact-lifecycle", JSON.stringify(payload)),
        });
      } else if (action === "restore") {
        await restoreLearningArtifact(selectedArtifact.id, {
          expected_version: payload.expected_version,
          idempotency_key: operationKey("artifact-lifecycle", JSON.stringify(payload)),
        });
      } else if (action === "withdraw") {
        await withdrawLearningArtifact(selectedArtifact.id, {
          expected_version: payload.expected_version,
          idempotency_key: operationKey("artifact-lifecycle", JSON.stringify(payload)),
        });
      } else {
        await purgeLearningArtifact(selectedArtifact.id, {
          expected_version: payload.expected_version,
          idempotency_key: operationKey("artifact-lifecycle", JSON.stringify(payload)),
          confirmation: "PURGE",
        });
        setPurgeConfirmation("");
      }
      setNotice(
        action === "soft-delete"
          ? "产出已普通删除，可恢复"
          : action === "restore"
            ? "产出已恢复"
            : action === "withdraw"
              ? "产出已撤出当前证据计算"
              : "产出已彻底删除，依赖主张已失效",
      );
    });
  }

  async function handleEvidenceReplay() {
    await runOperation("evidence-replay", "evidence", async () => {
      const result = await replayEvidence();
      setNotice(`证据回放完成：${result.event_count} 个事件，${result.aggregate_count} 个聚合`);
    });
  }

  async function handleBatchReview(action: "adopt" | "question") {
    if (!state) return;
    const claimIds = state.evidence_claims
      .filter((claim) => claim.status === "candidate")
      .map((claim) => claim.id);
    if (claimIds.length === 0) {
      setNotice("没有可批量处理的候选主张");
      return;
    }
    const payload = { action, claim_ids: claimIds };
    await runOperation("batch-review", JSON.stringify(payload), async () => {
      const result = await batchReviewEvidenceClaims(claimIds, {
        action,
        reason: action === "adopt" ? "批量采纳符合标准的候选主张" : "批量质疑候选主张",
        request_key: operationKey("batch-review", JSON.stringify(payload)),
      });
      setNotice(`批量${action === "adopt" ? "采纳" : "质疑"}完成：${result.review_ids.length} 条主张`);
    }, false);
  }

  async function handleRecalculateStates() {
    await runOperation("recalculate", "all", async () => {
      const states = await recalculateDerivedStates();
      setNotice(`状态重算完成：${states.length} 个维度`);
    });
  }

  async function handleHumanReview(claimId: string) {
    const payload = { claim_id: claimId };
    await runOperation("human-review", JSON.stringify(payload), async () => {
      await requestEvidenceHumanReview(claimId, {
        request_key: operationKey("human-review", JSON.stringify(payload)),
        note: "请人工复核该候选主张",
      });
      setNotice("已请求人工复核");
    });
  }

  async function handleSupplementalVerification(claimId: string) {
    const payload = { claim_id: claimId };
    await runOperation("supplemental-verification", JSON.stringify(payload), async () => {
      await scheduleEvidenceSupplementalVerification(claimId, {
        request_key: operationKey("supplemental-verification", JSON.stringify(payload)),
        note: "安排一次补充验证",
      });
      setNotice("已安排补充验证");
    });
  }

  async function handleCreateAgentRequest() {
    if (!selectedAction || busy) return;
    const payload = {
      purpose: "读取当前任务的事实摘要，用于恢复学习上下文。",
      target_id: selectedAction.id,
      content_granularity: agentGranularity,
      ttl_seconds: 300,
    };
    await runOperation("agent-request", JSON.stringify(payload), async () => {
      const request = await createAgentPermissionRequest({
        ...payload,
        request_key: operationKey("agent-request", JSON.stringify(payload)),
      });
      setAgentRequests((current) => [request, ...current.filter((item) => item.id !== request.id)]);
      setNotice("Agent 已发起最小范围读取申请");
      await loadAgentContext(selectedAction.id);
    });
  }

  async function handleDenyAgentRequest(request: AgentPermissionRequest) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const denied = await denyAgentPermissionRequest(request.id, "用户拒绝本次读取");
      setAgentRequests((current) =>
        current.map((item) => item.id === denied.id ? denied : item),
      );
      setNotice("已拒绝 Agent 读取申请，学习产出保存不受影响");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Agent 权限拒绝失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleApproveAgentRequest(request: AgentPermissionRequest) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const approved = await approveAgentPermissionRequest(request.id);
      setAgentRequests((current) =>
        current.map((item) => item.id === approved.id ? approved : item),
      );
      await loadAgentContext(request.target_id);
      setNotice("已批准本次最小范围读取，未扩大写入权限");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Agent 权限批准失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleRevokeAgentRequest(request: AgentPermissionRequest) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const revoked = await revokeAgentPermissionGrant(request.id, "用户撤销本次读取");
      setAgentRequests((current) =>
        current.map((item) => item.id === revoked.id ? revoked : item),
      );
      await loadAgentContext(request.target_id);
      setNotice("已撤销 Agent 读取授权");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Agent 权限撤销失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleReapplyAgentRequest() {
    clearOperationKey("agent-request");
    await handleCreateAgentRequest();
  }

  const fallbackProvider = providers.find((item) => item.is_default) ?? providers[0] ?? null;
  const explicitProvider = providerSelection
    ? providers.find((item) => item.id === providerSelection.provider_profile_id) ?? null
    : null;
  const explicitModel = explicitProvider?.models?.find(
    (item) => item.id === providerSelection?.provider_model_id,
  ) ?? null;
  const explicitSelectionUnavailable = Boolean(
    providerSelection &&
    (!explicitProvider ||
      !explicitProvider.enabled ||
      !explicitProvider.has_api_key ||
      !explicitModel ||
      !explicitModel.enabled ||
      explicitModel.discovery_status === "unavailable"),
  );
  const activeProvider = explicitProvider ?? fallbackProvider;
  const activeModel = explicitModel ?? activeProvider?.default_model ?? activeProvider?.models?.find((item) => item.enabled) ?? null;
  const noStandard = selectedDelegation?.criterion_id == null;
  const canStartSession = Boolean(selectedDelegation && selectedAction && selectedSession?.status !== "running");
  const canSaveArtifact = Boolean(selectedSession?.status === "running" && selectedAction);
  const canEndSession = Boolean(selectedSession?.status === "running" && selectedAction);
  const canAnalyzeArtifact = Boolean(selectedArtifact && selectedDelegation?.criterion_id != null);
  const selectedSetupStandard = state?.standards.find((item) => item.id === setupCriterionId) ?? null;
  const directTasks = existingTasks.filter((task) => task.status !== "canceled");
  const directTask = directTasks.find((task) => task.id === directTaskId) ?? null;

  return (
    <section className="fact-workspace" aria-label="开始学习">
      <header className="fact-header">
        <div>
          <p className="eyebrow">LEARNING START</p>
          <h1>开始学习</h1>
          <p className="lead">选择直接使用已有计划，或输入学习目标，让 AI 帮你整理一次可修改的起步安排。</p>
        </div>
        <div className="fact-header__actions">
          <button className="button button--quiet" type="button" onClick={() => void loadState()} disabled={busy || loading}>
            刷新状态
          </button>
          <button className="button button--dark" type="button" onClick={() => void handleReplay()} disabled={busy || loading}>
            回放事实
          </button>
        </div>
      </header>

      {error && <div className="workspace-alert" role="alert">{error}</div>}
      {notice && <div className="fact-notice" role="status">{notice}</div>}
      {loading && <div className="workspace-loading"><div className="signal-loader" /><span>正在加载学习事实</span></div>}

      {!loading && state && (
        <>
          {noStandard && selectedDelegation && (
            <div className="fact-warning" role="status">
              <strong>未绑定合格标准</strong>
              <span>学习产出和事实事件仍会保存，但不会生成证据主张或学习状态。</span>
            </div>
          )}

          <section className="fact-card learning-entry-choice" aria-label="选择学习方式">
            <div className="fact-card__header">
              <p className="eyebrow">START HERE</p>
              <h2>你准备怎么开始？</h2>
            </div>
            <div className="learning-entry-choice__options">
              <button
                className={`learning-entry-choice__option${entryMode === "direct" ? " is-active" : ""}`}
                type="button"
                aria-pressed={entryMode === "direct"}
                onClick={() => setEntryMode("direct")}
              >
                <strong>我已有学习计划</strong>
                <span>选择一个计划任务，直接进入学习室</span>
              </button>
              <button
                className={`learning-entry-choice__option${entryMode === "guided" ? " is-active" : ""}`}
                type="button"
                aria-pressed={entryMode === "guided"}
                onClick={() => setEntryMode("guided")}
              >
                <strong>我想从学习目标开始</strong>
                <span>输入目标，让 AI 整理一次可修改的起步安排</span>
              </button>
            </div>
          </section>

          {entryMode === "direct" ? (
            <section className="fact-card direct-learning" aria-label="按计划进入学习室">
              <div className="fact-card__header">
                <p className="eyebrow">USE MY PLAN</p>
                <h2>按计划开始</h2>
              </div>
              {directTasks.length === 0 ? (
                <p className="fact-empty">还没有可进入学习室的计划任务，请先在计划视图创建任务。</p>
              ) : (
                <>
                  <label className="field">
                    <span>选择计划任务</span>
                    <select value={directTaskId} onChange={(event) => setDirectTaskId(event.target.value)}>
                      {directTasks.map((task) => (
                        <option key={task.id} value={task.id}>
                          {task.title} · {task.goal_title ?? "当前计划"} · {task.status === "completed" ? "已完成" : "可继续"}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="guided-setup__actions">
                    <button className="button button--accent" type="button" onClick={() => void handleDirectLearning(false)}>
                      进入学习室
                    </button>
                    <button className="button button--dark" type="button" onClick={() => void handleDirectLearning(true)} disabled={directTask?.status === "completed"}>
                      开始专注并进入
                    </button>
                  </div>
                  <p className="guided-setup__rationale">学习室只负责答疑和记录；计划、任务完成状态与专注时长仍按现有工作区记录。</p>
                </>
              )}
            </section>
          ) : (
          <section className="fact-card guided-setup" aria-label="从学习意图开始">
            <div className="fact-card__header">
              <p className="eyebrow">START HERE</p>
              <h2>开始一次学习</h2>
            </div>
            <label className="field">
              <span>学习目标</span>
              <textarea
                value={setupIntent}
                onChange={(event) => setSetupIntent(event.target.value)}
                placeholder="例如：我想学会用 Python 正则处理日志，并能独立写出几个实际脚本。"
                maxLength={4000}
                rows={3}
                disabled={busy || Boolean(setupDraft)}
              />
            </label>
            <div className="guided-setup__actions">
              <button className="button button--accent" type="button" onClick={() => void handleSetupDraft()} disabled={busy || !setupIntent.trim()}>
                让 AI 帮我整理第一步
              </button>
              <button className="button button--quiet" type="button" onClick={handleManualSetup} disabled={busy || !setupIntent.trim()}>
                我想自己安排
              </button>
            </div>

            {setupDraft && (
              <div className="guided-setup__draft">
                <div className="guided-setup__draft-heading">
                  <div>
                    <p className="eyebrow">可修改草案</p>
                    <h3>先完成这一小步</h3>
                  </div>
                  <span>{setupConfirmed ? "已确认" : "等待确认"}</span>
                </div>
                <p className="guided-setup__rationale">{setupDraft.rationale}</p>
                <div className="field-grid field-grid--two">
                  <label className="field">
                    <span>目标</span>
                    <input value={setupDraft.goal_title} onChange={(event) => setSetupDraft({ ...setupDraft, goal_title: event.target.value })} disabled={setupConfirmed} />
                  </label>
                  <label className="field">
                    <span>计划</span>
                    <input value={setupDraft.plan_title} onChange={(event) => setSetupDraft({ ...setupDraft, plan_title: event.target.value })} disabled={setupConfirmed} />
                  </label>
                </div>
                <label className="field">
                  <span>这次任务</span>
                  <input value={setupDraft.action_title} onChange={(event) => setSetupDraft({ ...setupDraft, action_title: event.target.value })} disabled={setupConfirmed} />
                </label>
                <div className="guided-setup__outcome">
                  <strong>希望形成的能力</strong>
                  <label className="field">
                    <span>成果对象</span>
                    <input
                      value={setupDraft.outcome_object}
                      onChange={(event) => {
                        setSetupDraft({ ...setupDraft, outcome_object: event.target.value });
                        setSetupCriterionId("");
                      }}
                      disabled={setupConfirmed}
                    />
                  </label>
                  <label className="field">
                    <span>能够表现出的行为</span>
                    <input
                      value={setupDraft.outcome_behavior}
                      onChange={(event) => {
                        setSetupDraft({ ...setupDraft, outcome_behavior: event.target.value });
                        setSetupCriterionId("");
                      }}
                      disabled={setupConfirmed}
                    />
                  </label>
                  {selectedSetupStandard && <span>当前使用标准：{selectedSetupStandard.package_title} · v{selectedSetupStandard.version}。修改成果后会改为自定义成果。</span>}
                </div>
                <label className="field">
                  <span>本次学习边界</span>
                  <textarea value={setupDraft.boundaries} onChange={(event) => setSetupDraft({ ...setupDraft, boundaries: event.target.value })} disabled={setupConfirmed} rows={2} />
                </label>
                <label className="field">
                  <span>完成后停止</span>
                  <textarea value={setupDraft.stop_conditions} onChange={(event) => setSetupDraft({ ...setupDraft, stop_conditions: event.target.value })} disabled={setupConfirmed} rows={2} />
                </label>
                <label className="field">
                  <span>本次可用的验证标准（可选）</span>
                  <select value={setupCriterionId} onChange={(event) => setSetupCriterionId(event.target.value)} disabled={setupConfirmed}>
                    <option value="">暂不绑定标准，只保存学习事实</option>
                    {state.standards.map((standard) => (
                      <option key={standard.id} value={standard.id}>{standard.package_title} · v{standard.version}</option>
                    ))}
                  </select>
                </label>
                {!setupConfirmed ? (
                  <div className="guided-setup__actions">
                    <button className="button button--accent" type="button" onClick={() => void handleConfirmSetup()} disabled={busy}>
                      确认这份学习安排
                    </button>
                    <button className="button button--quiet" type="button" onClick={() => setSetupDraft(null)} disabled={busy}>
                      重新开始
                    </button>
                  </div>
                ) : (
                  <div className="guided-setup__next">
                    <span>安排已保存，学习目标、计划、任务和学习委托已经连在一起。</span>
                    <button className="button button--dark" type="button" onClick={() => void handleStartGuidedSession()} disabled={busy || !selectedDelegation}>
                      进入学习室并开始这项任务
                    </button>
                  </div>
                )}
              </div>
            )}
          </section>
          )}

          {entryMode === "guided" && !setupDraft && selectedSession?.status === "running" && (
            <section className="fact-card active-learning-session" aria-label="当前学习会话">
              <div className="fact-card__header">
                <p className="eyebrow">CURRENT SESSION</p>
                <h2>正在进行的学习</h2>
              </div>
              <p className="guided-setup__rationale">你可以回到学习室继续提问，也可以在这里结束本次学习记录。</p>
              <div className="fact-session">
                <strong>{selectedAction?.title ?? selectedDelegation?.action_title ?? "当前学习任务"}</strong>
                <span>状态：{selectedSession.status}</span>
                <button className="button button--accent" type="button" onClick={() => void handleResumeLearningRoom()} disabled={busy}>返回学习室</button>
                <button className="button button--quiet" type="button" onClick={() => void handleEndSession("ended")} disabled={busy}>
                  结束学习记录
                </button>
              </div>
            </section>
          )}

          {entryMode === "guided" && !setupDraft && (
          <details className="advanced-facts">
            <summary>高级：记录与复核工具</summary>
            <p className="advanced-facts__intro">这些工具用于查看事实、产出和证据状态，不是开始学习的必填步骤。</p>
          <section className="fact-card fact-card--provider" aria-label="证据分析 Provider 设置">
            <div className="fact-card__header">
              <p className="eyebrow">EVIDENCE PROVIDER</p>
              <h2>证据分析 Provider</h2>
            </div>
            {providersLoading ? (
              <p className="fact-empty">正在加载证据分析 Provider…</p>
            ) : providers.length === 0 ? (
              <p className="fact-empty">还没有可用 Provider。请先在 AI 提供方设置中配置。</p>
            ) : (
              <>
                <dl className="fact-meta fact-provider-summary">
                  <div>
                    <dt>当前分析</dt>
                    <dd>
                      {activeProvider?.display_name ?? "未知 Provider"} · {activeModel?.display_name ?? activeModel?.model_id ?? "未知模型"}
                    </dd>
                  </div>
                  <div>
                    <dt>配置状态</dt>
                    <dd>
                      {providerSelection == null
                        ? "跟随默认 Provider"
                        : explicitSelectionUnavailable
                          ? "所选配置不可用，分析将失败"
                          : "独立配置"}
                    </dd>
                  </div>
                  <div>
                    <dt>更新时间</dt>
                    <dd>{providerSelection ? formatTime(providerSelection.updated_at) : "—"}</dd>
                  </div>
                </dl>
                <form className="fact-form" onSubmit={submitProviderSelection}>
                  <div className="field-grid field-grid--two">
                    <label className="field">
                      <span>Provider</span>
                      <select
                        value={providerDraft.providerId}
                        onChange={(event) => handleProviderDraftChange(event.target.value)}
                        disabled={providerBusy}
                        required
                      >
                        <option value="">请选择 Provider</option>
                        {providers.map((provider) => (
                          <option
                            key={provider.id}
                            value={provider.id}
                            disabled={!provider.enabled || !provider.has_api_key}
                          >
                            {provider.display_name}{provider.is_default ? " · 默认" : ""}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field">
                      <span>分析模型</span>
                      <select
                        value={providerDraft.modelId}
                        onChange={(event) => setProviderDraft((current) => ({ ...current, modelId: event.target.value }))}
                        disabled={providerBusy || !providerDraft.providerId}
                        required
                      >
                        <option value="">请选择模型</option>
                        {(providers.find((item) => item.id === providerDraft.providerId)?.models ?? []).map((model) => (
                          <option
                            key={model.id}
                            value={model.id}
                            disabled={!model.enabled || model.discovery_status === "unavailable"}
                          >
                            {model.display_name}{model.discovery_status === "stale" ? "（过期）" : ""}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <div className="fact-provider-actions">
                    <button className="button button--accent" type="submit" disabled={providerBusy || !providerDraft.providerId || !providerDraft.modelId}>
                      保存证据分析 Provider
                    </button>
                    {providerSelection && (
                      <button className="button button--quiet" type="button" onClick={() => void clearProviderSelection()} disabled={providerBusy}>
                        恢复默认 Provider
                      </button>
                    )}
                  </div>
                </form>
                {explicitSelectionUnavailable && (
                  <p className="fact-empty">保存新的可用 Provider 后，将替换失效配置。</p>
                )}
              </>
            )}
          </section>

          <div className="fact-grid">
            {entryMode === "guided" && !setupConfirmed && (
              <>
            <section className="fact-card" aria-label="创建任务">
              <div className="fact-card__header">
                <p className="eyebrow">STEP 01</p>
              <h2>任务</h2>
              </div>
              <form className="fact-form" onSubmit={submitAction}>
                <label className="field">
                  <span>任务标题</span>
                  <input
                    value={actionForm.title}
                    onChange={(event) => setActionForm({ ...actionForm, title: event.target.value })}
                    placeholder="例如：完成一次概念讲解"
                    maxLength={300}
                    required
                  />
                </label>
                <label className="field">
                  <span>上下文</span>
                  <input
                    value={actionForm.contextKey}
                    onChange={(event) => setActionForm({ ...actionForm, contextKey: event.target.value })}
                    placeholder="default"
                    maxLength={200}
                    required
                  />
                </label>
                <button className="button button--accent" type="submit" disabled={busy}>
                  创建任务
                </button>
              </form>
              {state.actions.length > 0 && (
                <label className="field fact-select">
                  <span>当前任务</span>
                  <select
                    value={selectedAction?.id ?? ""}
                    onChange={(event) => setSelectedActionId(event.target.value)}
                  >
                    {state.actions.map((action) => (
                      <option key={action.id} value={action.id}>
                        {action.title} · v{action.aggregate_version}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </section>

            <section className="fact-card" aria-label="创建可验证成果">
              <div className="fact-card__header">
                <p className="eyebrow">STEP 02</p>
                <h2>可验证成果</h2>
              </div>
              <form className="fact-form" onSubmit={submitOutcome}>
                <label className="field">
                  <span>对象</span>
                  <input
                    value={outcomeForm.objectDescription}
                    onChange={(event) => setOutcomeForm({ ...outcomeForm, objectDescription: event.target.value })}
                    placeholder="例如：一套概念说明"
                    maxLength={500}
                    required
                  />
                </label>
                <label className="field">
                  <span>行为</span>
                  <input
                    value={outcomeForm.behavior}
                    onChange={(event) => setOutcomeForm({ ...outcomeForm, behavior: event.target.value })}
                    placeholder="例如：能独立讲清关键区别"
                    maxLength={500}
                    required
                  />
                </label>
                <label className="field">
                  <span>上下文</span>
                  <input
                    value={outcomeForm.contextKey}
                    onChange={(event) => setOutcomeForm({ ...outcomeForm, contextKey: event.target.value })}
                    placeholder="default"
                    maxLength={200}
                    required
                  />
                </label>
                <button className="button button--accent" type="submit" disabled={busy}>
                  创建可验证成果
                </button>
              </form>
              {state.outcomes.length > 0 && (
                <label className="field fact-select">
                  <span>当前成果</span>
                  <select
                    value={selectedOutcome?.id ?? ""}
                    onChange={(event) => setSelectedOutcomeId(event.target.value)}
                  >
                    {state.outcomes.map((outcome) => (
                      <option key={outcome.id} value={outcome.id}>
                        {outcome.object_description} / {outcome.behavior}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </section>

            <section className="fact-card" aria-label="创建学习委托">
              <div className="fact-card__header">
                <p className="eyebrow">STEP 03</p>
                <h2>学习委托</h2>
              </div>
              <form className="fact-form" onSubmit={submitDelegation}>
                <div className="field-grid field-grid--two">
                  <label className="field">
                    <span>任务</span>
                    <select
                      value={selectedAction?.id ?? ""}
                      onChange={(event) => setSelectedActionId(event.target.value)}
                    >
                      {state.actions.map((action) => (
                        <option key={action.id} value={action.id}>{action.title}</option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>可验证成果</span>
                    <select
                      value={selectedOutcome?.id ?? ""}
                      onChange={(event) => setSelectedOutcomeId(event.target.value)}
                    >
                      {state.outcomes.map((outcome) => (
                        <option key={outcome.id} value={outcome.id}>
                          {outcome.object_description} / {outcome.behavior}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <label className="field">
                  <span>达成标准</span>
                  <select
                    value={delegationForm.criterionId}
                    onChange={(event) => setDelegationForm({ ...delegationForm, criterionId: event.target.value })}
                  >
                    <option value="">不绑定标准（仅保存事实）</option>
                    {state.standards.map((standard) => (
                      <option key={standard.id} value={standard.id}>
                        {standard.package_title} · v{standard.version}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>边界</span>
                  <textarea
                    value={delegationForm.boundaries}
                    onChange={(event) => setDelegationForm({ ...delegationForm, boundaries: event.target.value })}
                    placeholder="本次学习的边界"
                    maxLength={2000}
                  />
                </label>
                <label className="field">
                  <span>停止条件</span>
                  <textarea
                    value={delegationForm.stopConditions}
                    onChange={(event) => setDelegationForm({ ...delegationForm, stopConditions: event.target.value })}
                    placeholder="完成后停止"
                    maxLength={2000}
                    required
                  />
                </label>
                <label className="field">
                  <span>时间预算（分钟）</span>
                  <input
                    type="number"
                    min={1}
                    max={1440}
                    value={delegationForm.timeBudgetMinutes}
                    onChange={(event) => setDelegationForm({ ...delegationForm, timeBudgetMinutes: Number(event.target.value) })}
                  />
                </label>
                <button className="button button--accent" type="submit" disabled={busy || !selectedAction || !selectedOutcome}>
                  创建学习委托
                </button>
              </form>
              {state.delegations.length > 0 && (
                <label className="field fact-select">
                  <span>当前委托</span>
                  <select
                    value={selectedDelegation?.id ?? ""}
                    onChange={(event) => setSelectedDelegationId(event.target.value)}
                  >
                    {state.delegations.map((delegation) => (
                      <option key={delegation.id} value={delegation.id}>
                        {delegation.action_title} · {delegation.status}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </section>
              </>
            )}

            <section className="fact-card" id="learning-session-card" aria-label="学习会话和原始产出">
              <div className="fact-card__header">
                <p className="eyebrow">STEP 04</p>
                <h2>学习会话与原始产出</h2>
              </div>
              <div className="fact-session">
                <button className="button button--dark" type="button" onClick={() => void handleStartSession()} disabled={!canStartSession || busy}>
                  开始学习会话
                </button>
                <button className="button button--quiet" type="button" onClick={() => void handleEndSession("ended")} disabled={!canEndSession || busy}>
                  结束会话
                </button>
                <button className="button button--danger" type="button" onClick={() => void handleEndSession("interrupted")} disabled={!canEndSession || busy}>
                  中断会话
                </button>
              </div>
              {selectedSession && (
                <dl className="fact-meta">
                  <div><dt>状态</dt><dd>{selectedSession.status}</dd></div>
                  <div><dt>开始时间</dt><dd>{formatTime(selectedSession.started_at)}</dd></div>
                  <div><dt>结束时间</dt><dd>{formatTime(selectedSession.ended_at)}</dd></div>
                </dl>
              )}
              <form className="fact-form" onSubmit={submitArtifact}>
                <label className="field">
                  <span>原始文本产出</span>
                  <textarea
                    value={artifactForm.content}
                    onChange={(event) => setArtifactForm({ ...artifactForm, content: event.target.value })}
                    placeholder="写下本次学习的真实产出"
                    required
                    disabled={!canSaveArtifact}
                  />
                </label>
                <button className="button button--accent" type="submit" disabled={!canSaveArtifact || busy}>
                  保存原始产出
                </button>
              </form>
            </section>

            <section className="fact-card" aria-label="已保存产出和更正">
              <div className="fact-card__header">
                <p className="eyebrow">STEP 05</p>
                <h2>已保存产出</h2>
              </div>
              <div className="fact-batch-actions">
                <button
                  className="button button--accent button--compact"
                  type="button"
                  onClick={() => void handleBatchReview("adopt")}
                  disabled={busy || state.evidence_claims.every((claim) => claim.status !== "candidate")}
                >
                  批量采纳候选主张
                </button>
                <button
                  className="button button--quiet button--compact"
                  type="button"
                  onClick={() => void handleBatchReview("question")}
                  disabled={busy || state.evidence_claims.every((claim) => claim.status !== "candidate")}
                >
                  批量质疑候选主张
                </button>
              </div>
              {state.artifacts.length === 0 ? (
                <p className="fact-empty">还没有原始产出。</p>
              ) : (
                <ul className="fact-list">
                  {state.artifacts.map((artifact) => (
                    <li key={artifact.id}>
                      <button
                        type="button"
                        className={artifact.id === selectedArtifact?.id ? "is-active" : ""}
                        onClick={() => setSelectedArtifactId(artifact.id)}
                      >
                        <strong>{artifact.action_title}</strong>
                        <span>v{artifact.content_version} · {formatTime(artifact.created_at)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {selectedArtifact && (
                <>
                  <article className="fact-artifact">
                    <header>
                      <strong>当前版本 v{selectedArtifact.content_version}</strong>
                      <span>{selectedArtifact.action_title}</span>
                    </header>
                    <pre>{selectedArtifact.content ?? "内容已删除"}</pre>
                  </article>
                  <div className="fact-lifecycle">
                    <button
                      className="button button--quiet button--compact"
                      type="button"
                      onClick={() => void handleArtifactLifecycle("soft-delete")}
                      disabled={busy || selectedArtifact.visibility !== "visible"}
                    >
                      普通删除
                    </button>
                    <button
                      className="button button--quiet button--compact"
                      type="button"
                      onClick={() => void handleArtifactLifecycle("restore")}
                      disabled={busy || selectedArtifact.visibility !== "soft_deleted"}
                    >
                      恢复
                    </button>
                    <button
                      className="button button--quiet button--compact"
                      type="button"
                      onClick={() => void handleArtifactLifecycle("withdraw")}
                      disabled={busy || selectedArtifact.evidence_status !== "eligible"}
                    >
                      撤回证据
                    </button>
                    <div className="fact-purge">
                      <input
                        value={purgeConfirmation}
                        onChange={(event) => setPurgeConfirmation(event.target.value)}
                        placeholder="输入 PURGE"
                        aria-label="彻底删除确认"
                      />
                      <button
                        className="button button--danger button--compact"
                        type="button"
                        onClick={() => void handleArtifactLifecycle("purge")}
                        disabled={busy || purgeConfirmation !== "PURGE" || selectedArtifact.visibility === "purged"}
                      >
                        彻底删除
                      </button>
                    </div>
                  </div>
                  <p className="fact-lifecycle__impact">
                    当前影响：
                    {state.evidence_claims.filter((claim) => claim.artifact_id === selectedArtifact.id).length} 条主张，
                    {state.derived_states.filter((stateItem) =>
                      stateItem.participating_claim_ids.some((claimId) =>
                        state.evidence_claims.some((claim) => claim.id === claimId && claim.artifact_id === selectedArtifact.id),
                      ),
                    ).length} 个派生状态，
                    {state.revisit_queue.filter((item) =>
                      item.claim_id && state.evidence_claims.some((claim) => claim.id === item.claim_id && claim.artifact_id === selectedArtifact.id),
                    ).length} 个回访项。
                  </p>
                  {state.analysis_runs
                    .filter((run) => run.artifact_id === selectedArtifact.id)
                    .map((run) => (
                      <div className="fact-analysis" key={run.id}>
                        <strong>尝试 {run.attempt} · {run.status}</strong>
                        <span>{run.reason ?? "未提供原因"}</span>
                        <span>
                          {run.provider_model
                            ? `Provider：${run.provider_model} · ${run.provider_selection_source === "explicit" ? "独立配置" : "默认配置"}`
                            : "Provider：未记录"}
                        </span>
                      </div>
                    ))}
                  <button
                    className="button button--dark"
                    type="button"
                    onClick={() => void handleAnalyzeArtifact()}
                    disabled={!canAnalyzeArtifact || busy}
                  >
                    分析产出
                  </button>
                  <div className="fact-review-visibility">
                    <strong>复核依据可见范围</strong>
                    <span>
                      用户：{selectedArtifact.visibility === "purged" || selectedArtifact.content == null
                        ? "原始产出不可见（已彻底删除）"
                        : "可查看原始产出"}
                    </span>
                    <span>
                      Agent：{agentContext?.authorization.status === "approved" && agentContext.authorization.content_granularity === "full_text"
                        ? "已获目标行动原文读取授权"
                        : "仅有摘要、状态和证据引用，无原文授权"}
                    </span>
                    <span>
                      依据引用：产出 {selectedArtifact.id} · v{selectedArtifact.content_version} · 事实事件 {events.find((event) => event.event_id === state.evidence_claims.find((claim) => claim.artifact_id === selectedArtifact.id)?.fact_event_id)?.event_id ?? "—"}
                    </span>
                    <span>
                      权限限制：Agent 缺少原文授权时分析保留限制；用户无需授权即可暂不处理、请求人工复核或安排补充验证。
                    </span>
                  </div>
                  {state.evidence_claims
                    .filter((claim) => claim.artifact_id === selectedArtifact.id)
                    .map((claim) => (
                      <article className="fact-claim" key={claim.id}>
                        <header>
                          <strong>{claim.dimension_id} · {claim.stance}</strong>
                          <span>{claim.status} · {claim.source}</span>
                        </header>
                        <p>{claim.statement}</p>
                        <footer>
                          <span>验证方式：{claim.verification_method}</span>
                          <span>独立条件：{claim.evidence_condition}</span>
                        </footer>
                        {state.evidence_replacements
                          .filter(
                            (replacement) =>
                              replacement.superseded_claim_id === claim.id ||
                              replacement.replacement_claim_id === claim.id,
                          )
                          .map((replacement) => (
                            <div className="fact-replacement" key={replacement.id}>
                              <strong>替代关系</strong>
                              <span>
                                {replacement.superseded_claim_id === claim.id
                                  ? `被 ${replacement.replacement_claim_id.slice(0, 8)} 替代`
                                  : `替代 ${replacement.superseded_claim_id.slice(0, 8)}`}
                              </span>
                            </div>
                          ))}
                        <div className="fact-claim__actions">
                          <button
                            className="button button--accent button--compact"
                            type="button"
                            onClick={() => void handleReviewClaim(claim.id, "adopt")}
                            disabled={busy || claim.status !== "candidate"}
                          >
                            采纳
                          </button>
                          <button
                            className="button button--quiet button--compact"
                            type="button"
                            onClick={() => void handleReviewClaim(claim.id, "question")}
                            disabled={busy || claim.status === "questioned"}
                          >
                            质疑
                          </button>
                          <button
                            className="button button--danger button--compact"
                            type="button"
                            onClick={() => void handleReviewClaim(claim.id, "withdraw")}
                            disabled={busy || claim.status === "withdrawn"}
                          >
                            撤回
                          </button>
                          <button
                            className="button button--quiet button--compact"
                            type="button"
                            onClick={() => void handleReviewClaim(claim.id, "defer")}
                            disabled={busy || claim.status !== "candidate"}
                          >
                            暂不处理
                          </button>
                          <button
                            className="button button--quiet button--compact"
                            type="button"
                            onClick={() => void handleHumanReview(claim.id)}
                            disabled={busy}
                          >
                            请求人工复核
                          </button>
                          <button
                            className="button button--quiet button--compact"
                            type="button"
                            onClick={() => void handleSupplementalVerification(claim.id)}
                            disabled={busy}
                          >
                            安排补充验证
                          </button>
                        </div>
                      </article>
                    ))}
                  {state.evidence_follow_ups.length > 0 && (
                    <div className="fact-follow-ups">
                      {state.evidence_follow_ups.map((followUp) => (
                        <div className="fact-follow-up" key={followUp.id}>
                          <strong>
                            {followUp.kind === "human_review" ? "人工复核" : "补充验证"}
                          </strong>
                          <span>{followUp.status}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  <form className="fact-form" onSubmit={submitCorrection}>
                    <label className="field">
                      <span>追加更正版本</span>
                      <textarea
                        value={correctionForm.content}
                        onChange={(event) => setCorrectionForm({ ...correctionForm, content: event.target.value })}
                        placeholder="写入更正后的完整内容"
                        required
                      />
                    </label>
                    <button className="button button--accent" type="submit" disabled={busy}>
                      追加更正
                    </button>
                  </form>
                </>
              )}
            </section>

            <section className="fact-card" aria-label="派生学习状态">
              <div className="fact-card__header">
                <p className="eyebrow">DERIVED STATE</p>
                <h2>派生学习状态</h2>
              </div>
              <div className="fact-state-actions">
                <button
                  className="button button--dark"
                  type="button"
                  onClick={() => void handleRecalculateStates()}
                  disabled={busy || loading}
                >
                  重算状态
                </button>
                <button
                  className="button button--quiet"
                  type="button"
                  onClick={() => void handleEvidenceReplay()}
                  disabled={busy || loading}
                >
                  回放证据
                </button>
              </div>
              {state.derived_states.length === 0 ? (
                <p className="fact-empty">还没有派生状态。</p>
              ) : (
                <ul className="fact-state-list">
                  {state.derived_states.map((stateItem) => (
                    <li key={stateItem.id}>
                      <div>
                        <strong>{stateItem.dimension_id}</strong>
                        <span>{stateItem.status}</span>
                      </div>
                      <dl>
                        <div><dt>原因</dt><dd>{stateItem.reason_code}</dd></div>
                        <div><dt>标准</dt><dd>v{stateItem.standard_version}</dd></div>
                        <div><dt>计算</dt><dd>v{stateItem.calculation_version}</dd></div>
                        <div><dt>参与</dt><dd>{stateItem.participating_claim_ids.length}</dd></div>
                        <div><dt>排除</dt><dd>{stateItem.excluded_claim_ids.length}</dd></div>
                        <div className="fact-state__reasons">
                          <dt>排除原因</dt>
                          <dd>
                            {stateItem.excluded_claim_reasons.length === 0
                              ? "无"
                              : stateItem.excluded_claim_reasons.map((item) => item.reason).join(", ")}
                          </dd>
                        </div>
                      </dl>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="fact-card" aria-label="首片指标">
              <div className="fact-card__header">
                <p className="eyebrow">METRICS</p>
                <h2>首片指标</h2>
              </div>
              {!metrics ? (
                <p className="fact-empty">指标尚未加载。</p>
              ) : (
                <div className="fact-metrics">
                  <div>
                    <strong>产品指标</strong>
                    <ul>
                      {Object.entries(metrics.product_metrics).map(([name, metric]) => (
                        <li key={name}>
                          <span>{name}</span>
                          <strong>{metric.status}</strong>
                          <span>
                            {metric.status === "no_sample"
                              ? "无样本"
                              : metric.unit === "count"
                                ? metric.numerator
                                : `${Math.round((metric.value ?? 0) * 100)}%`}
                          </span>
                          {Object.entries(metric.excluded ?? {}).some(([, count]) => count > 0) && (
                            <span className="fact-metrics__excluded">
                              单列：
                              {Object.entries(metric.excluded)
                                .filter(([, count]) => count > 0)
                                .map(([reason, count]) => `${reason} ${count}`)
                                .join(" · ")}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <strong>硬性护栏</strong>
                    <ul>
                      {Object.entries(metrics.hard_guards).map(([name, metric]) => (
                        <li key={name}>
                          <span>{name}</span>
                          <strong>{metric.status}</strong>
                          <span>
                            {metric.status === "no_sample"
                              ? "无样本"
                              : metric.unit === "count"
                                ? metric.numerator
                                : `${Math.round((metric.value ?? 0) * 100)}%`}
                          </span>
                          {Object.entries(metric.excluded ?? {}).some(([, count]) => count > 0) && (
                            <span className="fact-metrics__excluded">
                              单列：
                              {Object.entries(metric.excluded)
                                .filter(([, count]) => count > 0)
                                .map(([reason, count]) => `${reason} ${count}`)
                                .join(" · ")}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <p className="fact-metrics__window">{metrics.window}</p>
                </div>
              )}
            </section>

            <section className="fact-card" aria-label="回访队列">
              <div className="fact-card__header">
                <p className="eyebrow">REVISIT</p>
                <h2>回访队列</h2>
              </div>
              {state.revisit_queue.length === 0 ? (
                <p className="fact-empty">当前没有待回访项。</p>
              ) : (
                <ul className="fact-revisit-list">
                  {state.revisit_queue.map((item) => (
                    <li key={item.id}>
                      <div>
                        <strong>{item.source_kind}</strong>
                        <span>{item.dimension_id ?? "维度未指定"}</span>
                      </div>
                      <span>{item.reason}</span>
                      <span>{formatTime(item.due_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="fact-card" aria-label="事实事件和回放">
              <div className="fact-card__header">
                <p className="eyebrow">STEP 06</p>
                <h2>事实事件</h2>
              </div>
              {events.length === 0 ? (
                <p className="fact-empty">当前任务还没有事件。</p>
              ) : (
                <ol className="fact-events">
                  {events.map((event) => (
                    <li key={event.event_id}>
                      <strong>{event.event_type}</strong>
                      <span>v{event.aggregate_version} · {formatTime(event.occurred_at)}</span>
                    </li>
                  ))}
                </ol>
              )}
              <button className="button button--dark" type="button" onClick={() => void handleReplay()} disabled={busy || loading}>
                回放事实
              </button>
            </section>

            <section className="fact-card fact-card--agent" aria-label="Agent 权限">
              <div className="fact-card__header">
                <p className="eyebrow">PERMISSION</p>
                <h2>Agent 权限</h2>
              </div>
              <p>全局 Agent 默认只读取最小摘要、状态和证据引用；批准只扩大本次读取范围，不扩大写入权限。拒绝后仍可继续学习和保存产出，Agent 只能基于已授权摘要继续。</p>
              <div>
                <label className="fact-field">
                  <span>读取粒度</span>
                  <select
                    value={agentGranularity}
                    onChange={(event) => setAgentGranularity(event.target.value as "metadata" | "full_text")}
                    disabled={busy || !selectedAction}
                  >
                    <option value="metadata">摘要与引用</option>
                    <option value="full_text">原文</option>
                  </select>
                </label>
                <button
                  className="button button--quiet"
                  type="button"
                  onClick={() => void handleCreateAgentRequest()}
                  disabled={busy || !selectedAction}
                >
                  发起 Agent 权限申请
                </button>
              </div>
              {agentContext && (
                <div className="fact-agent__context">
                  <strong>
                    {agentContext.scope === "global"
                      ? "全局默认上下文"
                      : `当前行动上下文 · ${agentContext.authorization.status === "approved" ? "已授权" : "最小范围"}`}
                  </strong>
                  <span>
                    {agentContext.scope === "global"
                      ? `${agentContext.context.actions?.length ?? 0} 个行动摘要 · ${agentContext.context.evidence_references?.length ?? 0} 条证据引用`
                      : `${agentContext.context.evidence_references?.length ?? 0} 条证据引用 · ${agentContext.context.artifacts?.length ?? 0} 个授权产出 · ${formatUnavailableContext(agentContext.analysis.unavailable)}`}
                  </span>
                </div>
              )}
              {agentRequests.length === 0 ? (
                <p className="fact-empty">还没有权限申请。</p>
              ) : (
                <ul className="fact-agent-list">
                  {agentRequests.map((request) => (
                    <li key={request.id}>
                      <div>
                        <strong>{request.purpose}</strong>
                        <span>{formatAgentRequestStatus(request)}</span>
                      </div>
                      <div className="fact-agent-actions">
                        {request.status === "pending" && request.grant_status !== "active" && (
                          <>
                            <button
                              className="button button--quiet button--compact"
                              type="button"
                              onClick={() => void handleApproveAgentRequest(request)}
                              disabled={busy}
                            >
                              批准
                            </button>
                            <button
                              className="button button--danger button--compact"
                              type="button"
                              onClick={() => void handleDenyAgentRequest(request)}
                              disabled={busy}
                            >
                              拒绝
                            </button>
                          </>
                        )}
                        {request.grant_status === "active" && (
                          <button
                            className="button button--danger button--compact"
                            type="button"
                            onClick={() => void handleRevokeAgentRequest(request)}
                            disabled={busy}
                          >
                            撤销
                          </button>
                        )}
                        {(request.grant_status === "revoked" || request.grant_status === "expired") && (
                          <button
                            className="button button--quiet button--compact"
                            type="button"
                            onClick={() => void handleReapplyAgentRequest()}
                            disabled={busy || !selectedAction}
                          >
                            再次申请
                          </button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
          </details>
          )}
        </>
      )}
    </section>
  );
}
