export type Health = {
  status: string;
  service: string;
  version: string;
  database: string;
};

export type Identity = {
  id: string;
  device_id: string;
  display_name: string;
  timezone: string;
  created_at: string;
};

export type AuthStatus = {
  authenticated: boolean;
  identity: Identity | null;
};

export type AuthChallenge = {
  code: string;
};

export type TaskType = "study" | "practice" | "review" | "output";
export type ScheduleMode = "fixed" | "flexible";
export type TimerMode =
  | "pomodoro_25_5"
  | "pomodoro_50_10"
  | "custom"
  | "count_up";

export type Task = {
  id: string;
  topic_id: string;
  title: string;
  task_type: TaskType;
  schedule_mode: ScheduleMode;
  start_date: string;
  due_date: string;
  planned_start: string | null;
  planned_end: string | null;
  estimate_minutes: number;
  actual_minutes: number;
  progress: number;
  status: "pending" | "in_progress" | "completed" | "canceled";
  timer_mode: TimerMode;
  work_minutes: number;
  break_minutes: number;
  overdue: boolean;
  goal_id?: string;
  goal_title?: string;
  subject_title?: string;
  topic_title?: string;
  completed_at?: string | null;
};

export type Topic = {
  id: string;
  title: string;
  position: number;
  tasks: Task[];
  task_count?: number;
  completed_task_count?: number;
  progress?: number;
};

export type Subject = {
  id: string;
  title: string;
  position: number;
  topics: Topic[];
  task_count?: number;
  completed_task_count?: number;
  progress?: number;
};

export type Plan = {
  id: string;
  title: string;
  description: string;
  start_date: string;
  end_date: string;
  status: "draft" | "active" | "completed" | "archived";
  subjects: Subject[];
};

export type PlanSummary = Omit<Plan, "subjects"> & {
  subject_count: number;
  topic_count: number;
  task_count: number;
  completed_task_count: number;
  progress: number;
  estimate_minutes: number;
  actual_minutes: number;
  next_task: Task | null;
};

export type PlanDetail = Plan & {
  summary: Pick<
    PlanSummary,
    | "subject_count"
    | "topic_count"
    | "task_count"
    | "completed_task_count"
    | "progress"
    | "estimate_minutes"
    | "actual_minutes"
    | "next_task"
  >;
};

export type PlanScheduleItem = Task & {
  goal_id: string;
  goal_title: string;
  subject_title: string;
  topic_title: string;
};

export type TimerSnapshot = {
  id: string;
  task_id: string;
  status: "running" | "paused";
  timer_mode: TimerMode;
  work_minutes: number;
  break_minutes: number;
  started_at: string;
  elapsed_seconds: number;
  remaining_seconds: number | null;
  phase: "focus" | "break";
};

export type TodayDashboard = {
  date: string;
  tasks: Task[];
  summary: {
    total: number;
    completed: number;
    planned_minutes: number;
    actual_minutes: number;
    progress: number;
  };
  active_timer: TimerSnapshot | null;
};

export type ManualPlanInput = {
  goal_title: string;
  description: string;
  start_date: string;
  end_date: string;
  subject_title: string;
  topic_title: string;
  task_title: string;
  task_type: TaskType;
  schedule_mode: ScheduleMode;
  task_start_date: string;
  task_due_date: string;
  planned_start?: string | null;
  planned_end?: string | null;
  estimate_minutes: number;
  timer_mode: TimerMode;
  work_minutes: number;
  break_minutes: number;
};

export type GoalUpdateInput = Partial<
  Pick<Plan, "title" | "description" | "start_date" | "end_date" | "status">
>;

export type TaskEditorInput = Pick<
  Task,
  | "title"
  | "task_type"
  | "schedule_mode"
  | "start_date"
  | "due_date"
  | "planned_start"
  | "planned_end"
  | "estimate_minutes"
  | "timer_mode"
  | "work_minutes"
  | "break_minutes"
>;

export type TaskUpdateInput = Partial<TaskEditorInput>;

export type LayoutModuleId = "summary" | "tasks" | "timer" | "context";

export type LayoutModule = {
  id: LayoutModuleId;
  visible: boolean;
};

export type LayoutConfig = {
  modules: LayoutModule[];
  source_template_id: string | null;
  updated_at: string | null;
};

export type LayoutTemplate = {
  id: string;
  name: string;
  modules: LayoutModule[];
  is_system: boolean;
  created_at: string;
  updated_at: string;
};

export type AiProvider = {
  id: string;
  display_name: string;
  provider_kind: "openai_compatible";
  base_url: string;
  model: string;
  enabled: boolean;
  config_version: number;
  request_timeout_seconds: number;
  has_api_key: boolean;
  api_key_masked: string;
  credential_error: string | null;
  last_test_status: "succeeded" | "failed" | null;
  last_test_error: string | null;
  last_tested_at: string | null;
  updated_at: string;
  default_model_id?: string | null;
  default_model?: AiProviderModel | null;
  is_default?: boolean;
  credential_version?: number;
  models?: AiProviderModel[];
};

export type AiProviderModel = {
  id: string;
  provider_profile_id: string;
  model_id: string;
  display_name: string;
  source: "discovered" | "manual";
  enabled: boolean;
  discovery_status: "fresh" | "stale" | "unavailable";
  last_discovered_at: string | null;
  capabilities: {
    input_modalities?: string[];
    output_modalities?: string[];
    supports_streaming?: boolean | null;
    supports_reasoning?: boolean | null;
    supports_web_search?: boolean | null;
    supports_image_input?: boolean | null;
    supports_file_input?: boolean | null;
    max_context_tokens?: number | null;
    max_output_tokens?: number | null;
  };
  capability_source: "provider" | "manual_override" | "inferred_registry";
  overrides: Record<string, unknown>;
};

export type AiConversationConfig = {
  conversation_id: string;
  provider_profile_id: string;
  provider_model_id: string;
  timeout_override_seconds: number | null;
  config_version: number;
  provider_display_name: string;
  model_id: string;
  model_display_name: string;
  updated_at: string;
};

export type AiProviderInput = {
  display_name: string;
  base_url: string;
  model: string;
  api_key?: string;
  enabled: boolean;
  request_timeout_seconds: number;
};

export type AiProviderRuntimeInput = {
  base_url?: string;
  model?: string;
  api_key?: string;
  request_timeout_seconds?: number;
};

export type AiTaskContext = {
  scope_kind: "task";
  task_id: string;
  task_title: string;
  task_type: TaskType;
  status: Task["status"];
  start_date: string;
  due_date: string;
  estimate_minutes: number;
  progress: number;
  overdue: boolean;
  goal_id: string;
  goal_title: string;
  subject_title: string;
  topic_title: string;
  route: string;
  summary: string;
  counts?: { total: number; included: number; truncated: boolean };
};

export type AiPlanContext = {
  scope_kind: "plan";
  goal_id: string;
  goal_title: string;
  description: string;
  status: Plan["status"];
  start_date: string;
  end_date: string;
  progress: number;
  subject_count: number;
  topic_count: number;
  task_count: number;
  completed_task_count: number;
  estimate_minutes: number;
  actual_minutes: number;
  summary: string;
  counts: { total: number; included: number; truncated: boolean };
};

export type AiGlobalContext = {
  scope_kind: "global";
  summary: string;
  plans: Array<Pick<PlanSummary, "id" | "title" | "status" | "progress" | "task_count" | "completed_task_count">>;
  tasks: Task[];
  plan_counts: { total: number; included: number; truncated: boolean };
  task_counts: { total: number; included: number; truncated: boolean; overdue: number };
};

export type AiContextScope = "independent" | "global" | "plan" | "task";
export type AiLearningContext = AiTaskContext | AiPlanContext | AiGlobalContext;

export type AiConversation = {
  id: string;
  identity_id: string;
  title: string;
  conversation_kind: "linear";
  status: "active" | "archived";
  title_source: "placeholder" | "fallback" | "ai" | "manual";
  title_generation_status: "pending" | "queued" | "running" | "succeeded" | "failed" | "idle";
  title_revision: number;
  title_generated_at: string | null;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  context_scope: AiContextScope;
  link_type?: "task" | "topic" | "subject" | "goal" | null;
  link_target_id?: string | null;
};

export type AiTitleRun = {
  id: string;
  identity_id: string;
  conversation_id: string;
  trigger_ai_run_id: string | null;
  status: "queued" | "running" | "succeeded" | "failed" | "superseded";
  forced: boolean;
  provider_profile_id: string | null;
  provider_model_id: string | null;
  provider_kind: "openai_compatible";
  model: string;
  snapshot_schema_version: number;
  credential_version: number | null;
  expected_title_revision: number;
  generated_title: string | null;
  error_kind: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
};

export type AiMessageStatus = "complete" | "streaming" | "failed" | "canceled";

export type AiMessage = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  reasoning_content: string;
  sequence: number;
  status: AiMessageStatus;
  client_message_id: string | null;
  ai_run_id: string | null;
  created_at: string;
  updated_at: string;
};

export type AiRunStatus = "queued" | "running" | "succeeded" | "failed" | "canceled";

export type AiRun = {
  id: string;
  identity_id: string;
  conversation_id: string;
  workflow: "tutor_chat";
  status: AiRunStatus;
  provider_profile_id: string | null;
  provider_kind: "openai_compatible" | null;
  model: string | null;
  config_version: number | null;
  context_snapshot_id: string | null;
  request_message_id: string | null;
  response_message_id: string | null;
  error_kind: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
};

export type AiConversationDetail = {
  conversation: AiConversation;
  context: AiLearningContext | null;
  messages: AiMessage[];
  active_run: AiRun | null;
};

export type AiSendResult = {
  run: AiRun;
  created: boolean;
  messages: AiMessage[];
};

export type AiStreamStartPayload = {
  run_id: string;
  conversation_id: string;
  message_id: string | null;
  status: AiRunStatus;
  content: string;
  reasoning_content: string;
};

export type AiStreamEvent =
  | { type: "start"; data: AiStreamStartPayload }
  | { type: "delta"; data: { kind: "content" | "reasoning"; text: string } }
  | {
      type: "done";
      data: Pick<AiStreamStartPayload, "run_id" | "message_id" | "status" | "content" | "reasoning_content">;
    }
  | {
      type: "error";
      data: Pick<AiStreamStartPayload, "run_id" | "message_id" | "status" | "content" | "reasoning_content"> & {
        kind: string | null;
        message: string;
      };
    };

export type ApiErrorKind =
  | "local_network_error"
  | "auth_error"
  | "endpoint_not_found"
  | "rate_limited"
  | "timeout"
  | "network_error"
  | "protocol_error"
  | "upstream_error"
  | "request_error"
  | string;

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;

  constructor(message: string, kind: ApiErrorKind = "request_error", status: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
  }
}

export function actionableProviderError(kind?: string | null, message?: string | null): string {
  if (message?.trim()) return message.trim();
  switch (kind) {
    case "auth_error":
      return "提供方拒绝了请求，请检查 API Key、账号权限或模型权限。";
    case "endpoint_not_found":
      return "提供方接口路径不存在，请核对 Base URL 是否需要 /v1。";
    case "rate_limited":
      return "提供方触发限流，请稍后重试或检查账号额度。";
    case "timeout":
      return "提供方响应超时，请检查网络、服务状态或适当增加超时时间。";
    case "network_error":
      return "Nautilus 无法连接 AI 提供方，请检查 Base URL、DNS、TLS 和本地网络。";
    case "protocol_error":
      return "AI 提供方返回了无法识别的响应格式，请确认它兼容 OpenAI Chat Completions。";
    case "upstream_error":
      return "AI 提供方返回错误，请检查提供方状态和请求配置。";
    default:
      return "AI 提供方连接测试失败，请检查 Base URL、模型和 API Key。";
  }
}

function parseErrorBody(body: unknown): { kind?: string; message?: string } {
  if (!body || typeof body !== "object") return {};
  const detail = "detail" in body ? (body as { detail?: unknown }).detail : body;
  if (typeof detail === "string") return { message: detail };
  if (detail && typeof detail === "object") {
    const record = detail as { kind?: unknown; message?: unknown };
    return {
      kind: typeof record.kind === "string" ? record.kind : undefined,
      message: typeof record.message === "string" ? record.message : undefined,
    };
  }
  return {};
}

function throwLocalNetworkError(reason: unknown): never {
  if (reason instanceof ApiError) throw reason;
  if (reason instanceof DOMException && reason.name === "AbortError") throw reason;
  throw new ApiError("无法连接 Nautilus 本地服务，请确认服务正在运行。", "local_network_error");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      ...init,
    });
  } catch (reason: unknown) {
    throwLocalNetworkError(reason);
  }
  const body = (await response.json().catch(() => null)) as
    | { detail?: unknown }
    | T
    | null;
  if (!response.ok) {
    const parsed = parseErrorBody(body);
    throw new ApiError(
      parsed.message ?? actionableProviderError(parsed.kind, null),
      parsed.kind ?? "request_error",
      response.status,
    );
  }
  return body as T;
}

export function getHealth(): Promise<Health> {
  return request<Health>("/api/health");
}

export function getAuthStatus(): Promise<AuthStatus> {
  return request<AuthStatus>("/api/auth/status");
}

export function getAuthChallenge(): Promise<AuthChallenge> {
  return request<AuthChallenge>("/api/auth/challenge");
}

export function authorize(accessToken: string): Promise<AuthStatus> {
  return request<AuthStatus>("/api/auth/authorize", {
    method: "POST",
    body: JSON.stringify({ access_token: accessToken }),
  });
}

export function logout(): Promise<{ authenticated: false }> {
  return request<{ authenticated: false }>("/api/auth/logout", {
    method: "POST",
  });
}

export function getTodayDashboard(): Promise<TodayDashboard> {
  return request<TodayDashboard>("/api/dashboard/today");
}

export type TaskListFilters = {
  query?: string;
  status?: Task["status"] | "";
  task_type?: TaskType | "";
  schedule_mode?: ScheduleMode | "";
  start_date?: string;
  end_date?: string;
};

export function getTasks(filters: TaskListFilters = {}): Promise<Task[]> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  const query = params.toString();
  return request<Task[]>(`/api/tasks${query ? `?${query}` : ""}`);
}

export function getPlans(): Promise<Plan[]> {
  return request<Plan[]>("/api/plans");
}

export function getPlanSummaries(): Promise<PlanSummary[]> {
  return request<PlanSummary[]>("/api/plans/summary");
}

export function getPlan(planId: string): Promise<PlanDetail> {
  return request<PlanDetail>(`/api/plans/${planId}`);
}

export function getPlanSchedule(planId: string): Promise<PlanScheduleItem[]> {
  return request<PlanScheduleItem[]>(`/api/plans/${planId}/schedule`);
}

export function createManualPlan(payload: ManualPlanInput): Promise<Plan> {
  return request<Plan>("/api/plans/manual", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updatePlan(planId: string, payload: GoalUpdateInput): Promise<Plan> {
  return request<Plan>(`/api/plans/${planId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deletePlan(planId: string): Promise<void> {
  return request<void>(`/api/plans/${planId}`, { method: "DELETE" });
}

export function createSubject(planId: string, title: string): Promise<Subject> {
  return request<Subject>(`/api/plans/${planId}/subjects`, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export function updateSubject(subjectId: string, title: string): Promise<Subject> {
  return request<Subject>(`/api/subjects/${subjectId}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export function deleteSubject(subjectId: string): Promise<void> {
  return request<void>(`/api/subjects/${subjectId}`, { method: "DELETE" });
}

export function reorderSubjects(planId: string, orderedIds: string[]): Promise<Plan> {
  return request<Plan>(`/api/plans/${planId}/subjects/order`, {
    method: "PUT",
    body: JSON.stringify({ ordered_ids: orderedIds }),
  });
}

export function createTopic(subjectId: string, title: string): Promise<Topic> {
  return request<Topic>(`/api/subjects/${subjectId}/topics`, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export function updateTopic(topicId: string, title: string): Promise<Topic> {
  return request<Topic>(`/api/topics/${topicId}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export function deleteTopic(topicId: string): Promise<void> {
  return request<void>(`/api/topics/${topicId}`, { method: "DELETE" });
}

export function reorderTopics(subjectId: string, orderedIds: string[]): Promise<Plan> {
  return request<Plan>(`/api/subjects/${subjectId}/topics/order`, {
    method: "PUT",
    body: JSON.stringify({ ordered_ids: orderedIds }),
  });
}

export function createTask(topicId: string, payload: TaskEditorInput): Promise<Task> {
  return request<Task>(`/api/topics/${topicId}/tasks`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateTask(taskId: string, payload: TaskUpdateInput): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function rescheduleTask(taskId: string, days: number): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}/reschedule`, {
    method: "POST",
    body: JSON.stringify({ days }),
  });
}

export function deleteTask(taskId: string): Promise<void> {
  return request<void>(`/api/tasks/${taskId}`, { method: "DELETE" });
}

export function reorderTasks(topicId: string, orderedIds: string[]): Promise<Plan> {
  return request<Plan>(`/api/topics/${topicId}/tasks/order`, {
    method: "PUT",
    body: JSON.stringify({ ordered_ids: orderedIds }),
  });
}

export function completeTask(taskId: string): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}/complete`, { method: "POST" });
}

export function setTaskCompletion(taskId: string, completed: boolean): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}/completion`, {
    method: "PUT",
    body: JSON.stringify({ completed }),
  });
}

export function updateTimer(
  taskId: string,
  action: "start" | "pause" | "resume" | "finish",
  config?: Pick<ManualPlanInput, "timer_mode" | "work_minutes" | "break_minutes">,
): Promise<TimerSnapshot | null> {
  return request<TimerSnapshot | null>(`/api/tasks/${taskId}/timer`, {
    method: "POST",
    body: JSON.stringify({ action, ...config }),
  });
}

export function timerSocket(taskId: string): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return new WebSocket(`${protocol}//${window.location.host}/api/ws/timers/${taskId}`);
}

export function getLayout(): Promise<LayoutConfig> {
  return request<LayoutConfig>("/api/layout");
}

export function updateLayout(modules: LayoutModule[]): Promise<LayoutConfig> {
  return request<LayoutConfig>("/api/layout", {
    method: "PUT",
    body: JSON.stringify({ modules }),
  });
}

export function getLayoutTemplates(): Promise<LayoutTemplate[]> {
  return request<LayoutTemplate[]>("/api/layout/templates");
}

export function saveLayoutTemplate(name: string): Promise<LayoutTemplate> {
  return request<LayoutTemplate>("/api/layout/templates", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function applyLayoutTemplate(templateId: string): Promise<LayoutConfig> {
  return request<LayoutConfig>(`/api/layout/templates/${templateId}/apply`, {
    method: "POST",
  });
}

export function renameLayoutTemplate(templateId: string, name: string): Promise<LayoutTemplate> {
  return request<LayoutTemplate>(`/api/layout/templates/${templateId}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

export function deleteLayoutTemplate(templateId: string): Promise<void> {
  return request<void>(`/api/layout/templates/${templateId}`, { method: "DELETE" });
}

export function getAiProvider(): Promise<{ provider: AiProvider | null }> {
  return request<{ provider: AiProvider | null }>("/api/ai/provider");
}

export function listAiProviders(): Promise<AiProvider[]> {
  return request<AiProvider[]>("/api/ai/providers");
}

export function createAiProvider(payload: AiProviderInput & { is_default?: boolean; provider_kind?: "openai_compatible" }): Promise<{ provider: AiProvider }> {
  return request<{ provider: AiProvider }>("/api/ai/providers", { method: "POST", body: JSON.stringify(payload) });
}

export function updateAiProvider(providerId: string, payload: Partial<AiProviderInput> & { is_default?: boolean }): Promise<{ provider: AiProvider }> {
  return request<{ provider: AiProvider }>(`/api/ai/providers/${providerId}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function setDefaultAiProvider(providerId: string): Promise<{ provider: AiProvider }> {
  return request<{ provider: AiProvider }>(`/api/ai/providers/${providerId}/default`, { method: "POST" });
}

export function testAiProviderProfile(providerId: string, payload?: AiProviderRuntimeInput): Promise<{
  ok: boolean;
  model?: string;
  latency_ms?: number;
  kind?: string;
  message?: string;
  provider: AiProvider;
}> {
  return request(`/api/ai/providers/${providerId}/test`, {
    method: "POST",
    body: payload ? JSON.stringify(payload) : undefined,
  });
}

export function listAiProviderModels(providerId: string): Promise<AiProviderModel[]> {
  return request<AiProviderModel[]>(`/api/ai/providers/${providerId}/models`);
}

export function discoverAiProviderModelsForProfile(providerId: string, payload: Omit<AiProviderRuntimeInput, "model"> & { force_refresh?: boolean }): Promise<{ models: AiProviderModel[]; cached: boolean; ttl_seconds: number }> {
  return request(`/api/ai/providers/${providerId}/models/discover`, { method: "POST", body: JSON.stringify(payload) });
}

export function addAiProviderModel(providerId: string, modelId: string, displayName?: string): Promise<{ model: AiProviderModel }> {
  return request<{ model: AiProviderModel }>(`/api/ai/providers/${providerId}/models/manual`, { method: "POST", body: JSON.stringify({ model_id: modelId, display_name: displayName }) });
}

export function saveAiProvider(payload: AiProviderInput): Promise<{ provider: AiProvider }> {
  return request<{ provider: AiProvider }>("/api/ai/provider", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function testAiProvider(payload?: AiProviderRuntimeInput): Promise<{
  ok: boolean;
  model?: string;
  latency_ms?: number;
  kind?: string;
  message?: string;
  provider: AiProvider | null;
}> {
  return request("/api/ai/provider/test", {
    method: "POST",
    body: payload ? JSON.stringify(payload) : undefined,
  });
}

export function discoverAiProviderModels(
  payload: Omit<AiProviderRuntimeInput, "model"> & { force_refresh?: boolean },
): Promise<{ models: string[]; cached: boolean; ttl_seconds: number }> {
  return request("/api/ai/provider/models", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getAiTaskContext(taskId: string): Promise<AiTaskContext> {
  return request<AiTaskContext>(`/api/ai/tasks/${taskId}/context`);
}

export function getAiContextPreview(scope: AiContextScope, targetId?: string | null): Promise<AiLearningContext | null> {
  const params = new URLSearchParams({ scope });
  if (targetId) params.set("target_id", targetId);
  return request<AiLearningContext | null>(`/api/ai/context?${params}`);
}

export function listAiConversations(): Promise<AiConversation[]> {
  return request<AiConversation[]>("/api/ai/conversations");
}

export function createAiConversation(
  contextScope: AiContextScope = "independent",
  targetId?: string | null,
): Promise<AiConversationDetail> {
  return request<AiConversationDetail>("/api/ai/conversations", {
    method: "POST",
    body: JSON.stringify({ context_scope: contextScope, ...(targetId ? { target_id: targetId } : {}) }),
  });
}

export function getAiConversation(conversationId: string): Promise<AiConversationDetail> {
  return request<AiConversationDetail>(`/api/ai/conversations/${conversationId}`);
}

export function renameAiConversation(conversationId: string, title: string): Promise<AiConversationDetail> {
  return request<AiConversationDetail>(`/api/ai/conversations/${conversationId}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export function deleteAiConversation(conversationId: string): Promise<void> {
  return request<void>(`/api/ai/conversations/${conversationId}`, { method: "DELETE" });
}

export function getAiConversationConfig(conversationId: string): Promise<{ config: AiConversationConfig | null }> {
  return request<{ config: AiConversationConfig | null }>(`/api/ai/conversations/${conversationId}/config`);
}

export function setAiConversationConfig(conversationId: string, payload: Pick<AiConversationConfig, "provider_profile_id" | "provider_model_id"> & { timeout_override_seconds?: number | null }): Promise<{ config: AiConversationConfig }> {
  return request<{ config: AiConversationConfig }>(`/api/ai/conversations/${conversationId}/config`, { method: "PUT", body: JSON.stringify(payload) });
}

export function clearAiConversationConfig(conversationId: string): Promise<void> {
  return request<void>(`/api/ai/conversations/${conversationId}/config`, { method: "DELETE" });
}

export function regenerateAiConversationTitle(conversationId: string): Promise<{ title_run: AiTitleRun }> {
  return request<{ title_run: AiTitleRun }>(`/api/ai/conversations/${conversationId}/title/regenerate`, { method: "POST" });
}

export function getAiConversationTitleRun(conversationId: string): Promise<{ title_run: AiTitleRun | null }> {
  return request<{ title_run: AiTitleRun | null }>(`/api/ai/conversations/${conversationId}/title-run`);
}

export function sendAiMessage(
  conversationId: string,
  content: string,
  clientMessageId: string,
): Promise<AiSendResult> {
  return request<AiSendResult>(`/api/ai/conversations/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content, client_message_id: clientMessageId }),
  });
}

export function cancelAiRun(runId: string): Promise<{ run: AiRun }> {
  return request<{ run: AiRun }>(`/api/ai/runs/${runId}/cancel`, { method: "POST" });
}

export async function streamAiRun(
  runId: string,
  onEvent: (event: AiStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api/ai/runs/${runId}/stream`, {
      credentials: "include",
      headers: { Accept: "text/event-stream" },
      signal,
    });
  } catch (reason: unknown) {
    throwLocalNetworkError(reason);
  }
  if (!response.ok || !response.body) {
    const body = (await response.json().catch(() => null)) as unknown;
    const parsed = parseErrorBody(body);
    throw new ApiError(
      parsed.message ?? "Nautilus AI 流式接口没有返回有效响应，请检查服务日志。",
      parsed.kind ?? "request_error",
      response.status,
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseAiStreamFrame(frame);
      if (parsed) onEvent(parsed);
      boundary = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
}

function parseAiStreamFrame(frame: string): AiStreamEvent | null {
  if (!frame || frame.startsWith(":")) return null;
  let eventName = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length || !["start", "delta", "done", "error"].includes(eventName)) {
    return null;
  }
  const data = JSON.parse(dataLines.join("\n")) as AiStreamEvent["data"];
  return { type: eventName, data } as AiStreamEvent;
}
