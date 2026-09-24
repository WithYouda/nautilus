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
  parent_message_id?: string | null;
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
  versions: { regenerate_message_id?: string; parent_message_id?: string } = {},
): Promise<AiSendResult> {
  return request<AiSendResult>(`/api/ai/conversations/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content, client_message_id: clientMessageId, ...versions }),
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

  await readStreamFrames(response, frame => {
    const parsed = parseAiStreamFrame(frame);
    if (parsed) onEvent(parsed);
  });
}

async function readStreamFrames(response: Response, onFrame: (frame: string) => void): Promise<void> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      // Normalize after concatenation, including CRLF split across network chunks.
      buffer = buffer.replace(/\r\n/g, '\n');
      let boundary = buffer.indexOf('\n\n');
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        onFrame(frame);
        boundary = buffer.indexOf('\n\n');
      }
      if (done) break;
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
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

export type LearningCommandResult = {
  id: string;
  aggregate_id: string;
  version: number;
  event_id: string;
};

export type LearningAction = {
  id: string;
  title: string;
  context_key: string;
  status: "open" | "completed" | "cancelled";
  version: number;
  created_at: string;
  aggregate_version: number;
};

export type LearningOutcome = {
  id: string;
  object_description: string;
  behavior: string;
  context_key: string;
  source: string;
  created_at: string;
};

export type LearningStandard = {
  id: string;
  outcome_id: string;
  package_id: string;
  version: number;
  context_key: string;
  review_status: "candidate" | "approved";
  package_title: string;
  object_description: string;
  behavior: string;
};

export type LearningDelegation = {
  id: string;
  action_id: string;
  outcome_id: string;
  criterion_id: string | null;
  contract_version: number;
  status: "ready" | "active" | "paused" | "completed" | "cancelled";
  version: number;
  created_at: string;
  action_title: string;
  object_description: string;
  behavior: string;
  criterion_status: string | null;
  criterion_package_title: string | null;
};

export type LearningSession = {
  id: string;
  delegation_id: string;
  contract_version: number;
  status: "running" | "ended" | "interrupted";
  started_at: string;
  ended_at: string | null;
  version: number;
  action_id: string;
  action_title: string;
};

export type LearningArtifact = {
  id: string;
  content_version: number;
  visibility: "visible" | "soft_deleted" | "purged";
  evidence_status: "eligible" | "withdrawn" | "invalidated";
  version: number;
  session_id: string;
  content: string | null;
  content_hash: string | null;
  privacy: string;
  purged_at: string | null;
  created_at: string;
  delegation_id: string;
  action_title: string;
};

export type LearningAnalysisRun = {
  id: string;
  artifact_id: string;
  content_version: number;
  fact_event_id: string;
  criterion_id: string | null;
  request_key: string;
  attempt: number;
  status:
    | "queued"
    | "running"
    | "succeeded"
    | "failed"
    | "timeout"
    | "cancelled"
    | "invalid_output"
    | "permission_denied"
    | "blocked_no_criterion";
  reason: string | null;
  provider_selection_source: "default" | "explicit" | null;
  provider_profile_id: string | null;
  provider_model_id: string | null;
  provider_model: string | null;
  provider_kind: string | null;
  provider_config_version: number | null;
  provider_timeout_seconds: number | null;
  analysis_prompt_schema_version: number | null;
  created_at: string;
  finished_at: string | null;
};

export type LearningEvent = {
  event_id: string;
  aggregate_type: string;
  aggregate_id: string;
  aggregate_version: number;
  event_type: string;
  occurred_at: string;
  payload_json: string;
};

export type LearningEvidenceClaim = {
  id: string;
  artifact_id: string;
  content_version: number;
  fact_event_id: string;
  criterion_id: string;
  dimension_id: string;
  stance: "supports" | "refutes" | "insufficient";
  status: "candidate" | "adopted" | "questioned" | "withdrawn" | "superseded";
  source: "ai_analysis" | "human_review" | "deterministic_check";
  source_trusted?: boolean;
  statement: string;
  verification_method: string;
  evidence_condition: "independent" | "with_materials" | "with_hints";
  scope: string;
  analysis_run_id: string;
  created_at: string;
};

export type LearningEvidenceFollowUp = {
  id: string;
  claim_id: string;
  kind: "human_review" | "supplemental_verification";
  status: "pending" | "completed" | "cancelled";
  request_key: string;
  note: string | null;
  due_at: string | null;
  created_at: string;
  decided_at: string | null;
};

export type LearningDerivedState = {
  id: string;
  outcome_id: string;
  criterion_id: string;
  dimension_id: string;
  status:
    | "awaiting_evidence"
    | "pending_review"
    | "insufficient_evidence"
    | "partially_supported"
    | "supported"
    | "contradicted";
  reason_code: string;
  standard_version: number;
  calculation_version: number;
  participating_claim_ids: string[];
  excluded_claim_ids: string[];
  excluded_claim_reasons: Array<{ claim_id: string; reason: string }>;
  calculated_at: string;
};

export type LearningReviewAction = {
  id: string;
  claim_id: string;
  action: "adopt" | "question" | "withdraw" | "supersede" | "defer";
  from_status: "candidate" | "adopted" | "questioned" | "withdrawn" | "superseded";
  to_status: "candidate" | "adopted" | "questioned" | "withdrawn" | "superseded";
  reason: string | null;
  request_key: string;
  created_at: string;
};

export type LearningEvidenceReplacement = {
  id: string;
  superseded_claim_id: string;
  replacement_claim_id: string;
  reason: string;
  created_at: string;
};

export type LearningRevisitItem = {
  id: string;
  source_kind: "questioned_claim" | "insufficient_state" | "supplemental_verification";
  source_id: string;
  claim_id: string | null;
  criterion_id: string;
  dimension_id: string | null;
  reason: string;
  due_at: string;
  status: "pending" | "completed" | "cancelled";
  created_at: string;
  updated_at: string;
};

export type LearningMetricResult = {
  numerator: number;
  denominator: number;
  value: number | null;
  sample_count: number;
  status: "pass" | "fail" | "no_sample" | "observed";
  unit: "ratio" | "count";
  notes: string[];
  excluded: Record<string, number>;
};

export type LearningMeasurementReport = {
  metric_version: string;
  generated_at: string;
  window: string;
  product_metrics: Record<string, LearningMetricResult>;
  hard_guards: Record<string, LearningMetricResult>;
};

export type LearningState = {
  goals: LearningGoal[];
  plans: LearningPlan[];
  modules: LearningModule[];
  action_links: LearningActionLink[];
  setups: LearningSetup[];
  actions: LearningAction[];
  outcomes: LearningOutcome[];
  standards: LearningStandard[];
  delegations: LearningDelegation[];
  sessions: LearningSession[];
  artifacts: LearningArtifact[];
  analysis_runs: LearningAnalysisRun[];
  evidence_claims: LearningEvidenceClaim[];
  evidence_follow_ups: LearningEvidenceFollowUp[];
  derived_states: LearningDerivedState[];
  review_actions: LearningReviewAction[];
  evidence_replacements: LearningEvidenceReplacement[];
  revisit_queue: LearningRevisitItem[];
};

export type LearningGoal = {
  id: string;
  original_intent: string;
  title: string;
  description: string;
  status: "hypothesis" | "active" | "paused" | "completed" | "archived";
  version: number;
  created_at: string;
  updated_at: string;
};

export type LearningPlan = {
  id: string;
  goal_id: string | null;
  title: string;
  description: string;
  status: "active" | "paused" | "completed" | "archived";
  version: number;
  created_at: string;
  updated_at: string;
};

export type LearningModule = {
  id: string;
  plan_id: string;
  parent_module_id: string | null;
  title: string;
  description: string;
  position: number;
  status: "active" | "paused" | "archived";
  created_at: string;
  updated_at: string;
};

export type LearningActionLink = {
  owner_id: string;
  action_id: string;
  plan_id: string;
  module_id: string | null;
  created_at: string;
};

export type LearningSetup = {
  id: string;
  goal_id: string;
  plan_id: string;
  action_id: string;
  outcome_id: string;
  delegation_id: string;
  original_intent: string;
  status: "confirmed";
  version: number;
  created_at: string;
};

export type LearningSetupDraft = {
  draft_id?: string;
  goal_title: string;
  goal_description: string;
  plan_title: string;
  plan_description: string;
  action_title: string;
  context_key: string;
  outcome_object: string;
  outcome_behavior: string;
  outcome_context_key: string;
  boundaries: string;
  stop_conditions: string;
  time_budget_minutes: number;
  recommended_criterion_id: string | null;
  rationale: string;
};

export type LearningRoomBrief = {
  history_only?: boolean;
  continuity_review_id?: string;
  open_verification?: boolean;
  action_id?: string;
  delegation_id?: string;
  session_id?: string;
  criterion_id?: string | null;
  goal_title: string;
  plan_title: string;
  action_title: string;
  outcome_object: string;
  outcome_behavior: string;
  boundaries: string;
  stop_conditions: string;
};

export type LearningVerificationQuestion = {
  id: string;
  type: "scenario" | "project" | "short_response" | "true_false";
  prompt: string;
  source_urls: string[];
};

export type LearningVerification = {
  id: string;
  action_id: string;
  delegation_id: string;
  session_id: string | null;
  mode: "ai_challenge" | "user_material";
  status: "ready" | "submitted" | "passed" | "failed";
  challenge: {
    questions?: LearningVerificationQuestion[];
    instructions?: string;
    stop_condition?: string;
  };
  result: {
    passed: boolean;
    stop_condition_met: boolean;
    feedback: string;
    next_step: string;
  } | null;
  stop_condition_confirmed: boolean;
  stop_condition_met: boolean | null;
  created_at: string;
  submitted_at: string | null;
  latest_submission_id: string | null;
  evaluation: { id: string; status: "running" | "succeeded" | "failed"; reason: string | null; message?: string | null } | null;
  action_completed: boolean;
  stop_conditions: string;
  artifact_id: string | null;
  content_purged: boolean;
  verification_purged: boolean;
  evidence: { id: string; status: string; reason: string | null } | null;
};

export type LearningReplayResult = {
  status: string;
  event_count: number;
  aggregate_count: number;
  projection_digest: string;
};

export function getLearningMetrics(): Promise<LearningMeasurementReport> {
  return request<LearningMeasurementReport>("/api/learning/metrics");
}

export function getLearningState(): Promise<LearningState> {
  return request<LearningState>("/api/learning/state");
}

export function createLearningSetupDraft(intent: string): Promise<LearningSetupDraft> {
  return request<LearningSetupDraft>("/api/learning/setup/draft", {
    method: "POST",
    body: JSON.stringify({ intent }),
  });
}

export function confirmLearningSetup(payload: {
  plan_id?: string;
  review_id?: string;
  draft_id?: string;
  original_intent: string;
  goal_title: string;
  goal_description: string;
  plan_title: string;
  plan_description: string;
  action_title: string;
  context_key: string;
  outcome_id: string | null;
  object_description: string;
  behavior: string;
  outcome_context_key: string;
  criterion_id: string | null;
  boundaries: string;
  stop_conditions: string;
  time_budget_minutes: number | null;
  idempotency_key: string;
}): Promise<{
  id: string;
  setup_id: string;
  goal_id: string;
  plan_id: string;
  action_id: string;
  outcome_id: string;
  delegation_id: string;
  version: number;
  event_id: string;
}> {
  return request("/api/learning/setup/confirm", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createLearningAction(payload: {
  title: string;
  context_key: string;
  idempotency_key: string;
}): Promise<LearningCommandResult> {
  return request<LearningCommandResult>("/api/learning/actions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createLearningOutcome(payload: {
  object_description: string;
  behavior: string;
  context_key: string;
  idempotency_key: string;
}): Promise<LearningCommandResult> {
  return request<LearningCommandResult>("/api/learning/outcomes", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createLearningDelegation(payload: {
  action_id: string;
  outcome_id: string;
  criterion_id: string | null;
  boundaries: string;
  stop_conditions: string;
  time_budget_minutes: number | null;
  expected_version: number;
  idempotency_key: string;
}): Promise<LearningCommandResult> {
  return request<LearningCommandResult>("/api/learning/delegations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function startLearningSession(payload: {
  delegation_id: string;
  expected_version: number;
  idempotency_key: string;
}): Promise<LearningCommandResult> {
  return request<LearningCommandResult>("/api/learning/sessions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function saveLearningArtifact(payload: {
  session_id: string;
  content: string;
  expected_version: number;
  idempotency_key: string;
}): Promise<LearningCommandResult> {
  return request<LearningCommandResult>("/api/learning/artifacts", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function endLearningSession(
  sessionId: string,
  payload: { disposition: "ended" | "interrupted"; expected_version: number; idempotency_key: string },
): Promise<LearningCommandResult> {
  return request<LearningCommandResult>(`/api/learning/sessions/${sessionId}/end`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function startLearningVerification(payload: {
  action_id: string;
  delegation_id: string;
  session_id?: string | null;
  mode: "ai_challenge" | "user_material";
  request_key: string;
}): Promise<LearningVerification> {
  return request<LearningVerification>("/api/learning/verifications", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function submitLearningVerification(
  verificationId: string,
  payload: {
    responses?: Record<string, string>;
    material?: string;
    learner_work?: string;
    evidence_condition?: "independent" | "with_materials" | "with_hints";
    request_key: string;
  },
): Promise<LearningVerification> {
  return request<LearningVerification>(`/api/learning/verifications/${verificationId}/submit`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listLearningVerifications(): Promise<LearningVerification[]> {
  return request<LearningVerification[]>("/api/learning/verifications");
}

export function analyzeVerificationEvidence(id: string): Promise<LearningVerification> {
  return request<LearningVerification>(`/api/learning/verifications/${id}/evidence`, { method: "POST" });
}

export function purgeVerification(id: string): Promise<LearningVerification> {
  return request<LearningVerification>(`/api/learning/verifications/${id}/purge`, {
    method: "POST", body: JSON.stringify({ confirmation: "PURGE" }),
  });
}

export type LearningRoomState = { brief: LearningRoomBrief; conversation_id: string | null; conversation_ids: string[] };

export function getLearningRoom(sessionId: string): Promise<LearningRoomState> {
  return request<LearningRoomState>(`/api/learning/sessions/${sessionId}/room`);
}

export function recordLearningRoomEntry(sessionId: string): Promise<{ recorded: boolean }> {
  return request(`/api/learning/sessions/${sessionId}/room/entered`, { method: 'POST' });
}

export function selectLearningRoomConversation(sessionId: string, conversationId: string): Promise<LearningRoomState> {
  return request<LearningRoomState>(`/api/learning/sessions/${sessionId}/room`, {
    method: "PUT", body: JSON.stringify({ conversation_id: conversationId }),
  });
}

export function evaluateLearningVerification(id: string, submissionId: string, requestKey: string): Promise<LearningVerification> {
  return request<LearningVerification>(`/api/learning/verifications/${id}/evaluate`, {
    method: "POST", body: JSON.stringify({ submission_id: submissionId, request_key: requestKey }),
  });
}

export function confirmLearningVerification(id: string, submissionId: string, evaluationId: string): Promise<LearningVerification> {
  return request<LearningVerification>(`/api/learning/verifications/${id}/confirm`, {
    method: "POST", body: JSON.stringify({ submission_id: submissionId, evaluation_id: evaluationId, stop_condition_confirmed: true }),
  });
}

export function getLearningArtifact(artifactId: string, contentVersion?: number): Promise<LearningArtifact> {
  const params = new URLSearchParams();
  if (contentVersion) params.set("content_version", String(contentVersion));
  const query = params.toString();
  return request<LearningArtifact>(`/api/learning/artifacts/${artifactId}${query ? `?${query}` : ""}`);
}

export function correctLearningArtifact(
  artifactId: string,
  payload: { content: string; expected_version: number; idempotency_key: string },
): Promise<LearningCommandResult> {
  return request<LearningCommandResult>(`/api/learning/artifacts/${artifactId}/corrections`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getLearningEvents(actionId: string): Promise<LearningEvent[]> {
  return request<LearningEvent[]>(`/api/learning/actions/${actionId}/events`);
}

export function analyzeLearningArtifact(
  artifactId: string,
  payload: { content_version?: number | null; request_key: string },
): Promise<{ run: LearningAnalysisRun; claims: LearningEvidenceClaim[]; created: boolean }> {
  return request<{ run: LearningAnalysisRun; claims: LearningEvidenceClaim[]; created: boolean }>(
    `/api/learning/artifacts/${artifactId}/analysis`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function requestEvidenceHumanReview(
  claimId: string,
  payload: { request_key: string; note?: string | null },
): Promise<LearningEvidenceFollowUp> {
  return request<LearningEvidenceFollowUp>(`/api/learning/evidence-claims/${claimId}/human-review`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function scheduleEvidenceSupplementalVerification(
  claimId: string,
  payload: { request_key: string; note?: string | null },
): Promise<LearningEvidenceFollowUp> {
  return request<LearningEvidenceFollowUp>(
    `/api/learning/evidence-claims/${claimId}/supplemental-verification`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function batchReviewEvidenceClaims(
  claimIds: string[],
  payload: {
    action: "adopt" | "question" | "withdraw" | "defer";
    reason?: string | null;
    request_key: string;
  },
): Promise<{ id: string; action: string; claim_ids: string[]; review_ids: string[] }> {
  return request<{ id: string; action: string; claim_ids: string[]; review_ids: string[] }>(
    "/api/learning/evidence-claims/batch-review",
    {
      method: "POST",
      body: JSON.stringify({
        claim_ids: claimIds,
        action: payload.action,
        reason: payload.reason ?? null,
        request_key: payload.request_key,
      }),
    },
  );
}

export function reviewEvidenceClaim(
  claimId: string,
  payload: {
    action: "adopt" | "question" | "withdraw" | "supersede" | "defer";
    reason?: string | null;
    request_key: string;
  },
): Promise<LearningReviewAction> {
  return request<LearningReviewAction>(`/api/learning/evidence-claims/${claimId}/review`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function recalculateDerivedStates(criterionId?: string | null): Promise<LearningDerivedState[]> {
  return request<LearningDerivedState[]>("/api/learning/derived-states/recalculate", {
    method: "POST",
    body: JSON.stringify({ criterion_id: criterionId ?? null }),
  });
}

export function getLearningDerivedStateHistory(): Promise<LearningDerivedState[]> {
  return request<LearningDerivedState[]>("/api/learning/derived-state-history");
}

export function getLearningEvidenceFollowUps(): Promise<LearningEvidenceFollowUp[]> {
  return request<LearningEvidenceFollowUp[]>("/api/learning/evidence-follow-ups");
}

export function getLearningEvidenceClaims(artifactId?: string): Promise<LearningEvidenceClaim[]> {
  const params = new URLSearchParams();
  if (artifactId) params.set("artifact_id", artifactId);
  const query = params.toString();
  return request<LearningEvidenceClaim[]>(`/api/learning/evidence-claims${query ? `?${query}` : ""}`);
}

export function softDeleteLearningArtifact(
  artifactId: string,
  payload: { expected_version: number; idempotency_key: string },
): Promise<LearningCommandResult> {
  return request<LearningCommandResult>(`/api/learning/artifacts/${artifactId}/soft-delete`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function restoreLearningArtifact(
  artifactId: string,
  payload: { expected_version: number; idempotency_key: string },
): Promise<LearningCommandResult> {
  return request<LearningCommandResult>(`/api/learning/artifacts/${artifactId}/restore`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function withdrawLearningArtifact(
  artifactId: string,
  payload: { expected_version: number; idempotency_key: string },
): Promise<LearningCommandResult> {
  return request<LearningCommandResult>(`/api/learning/artifacts/${artifactId}/withdraw`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function purgeLearningArtifact(
  artifactId: string,
  payload: { expected_version: number; idempotency_key: string; confirmation: "PURGE" },
): Promise<LearningCommandResult> {
  return request<LearningCommandResult>(`/api/learning/artifacts/${artifactId}/purge`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function replayEvidence(): Promise<LearningReplayResult> {
  return request<LearningReplayResult>("/api/learning/evidence-replay", { method: "POST" });
}

export function replayLearning(): Promise<LearningReplayResult> {
  return request<LearningReplayResult>("/api/learning/replay", { method: "POST" });
}

export type LearningEvidenceProviderSelection = {
  provider_profile_id: string;
  provider_model_id: string;
  updated_at: string;
};

export function getLearningEvidenceProvider(): Promise<LearningEvidenceProviderSelection | null> {
  return request<LearningEvidenceProviderSelection | null>("/api/learning/evidence-provider");
}

export function setLearningEvidenceProvider(payload: {
  provider_profile_id: string;
  provider_model_id: string;
}): Promise<LearningEvidenceProviderSelection> {
  return request<LearningEvidenceProviderSelection>("/api/learning/evidence-provider", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function clearLearningEvidenceProvider(): Promise<void> {
  return request<void>("/api/learning/evidence-provider", { method: "DELETE" });
}

export type AgentPermissionRequest = {
  id: string;
  owner_id: string;
  agent_id: string;
  request_key: string;
  purpose: string;
  scope: "learning_action";
  target_id: string;
  content_granularity: "metadata" | "full_text";
  ttl_seconds: number;
  expires_at: string;
  status: "pending" | "approved" | "denied" | "expired" | "revoked";
  created_at: string;
  decided_at: string | null;
  decision_reason: string | null;
  grant_status?: "active" | "revoked" | "expired";
  granted_at?: string | null;
  revoked_at?: string | null;
  revoke_reason?: string | null;
};

export type AgentContext = {
  agent_id: string;
  scope: "global" | "learning_action";
  authorization: {
    status: "default" | "pending" | "denied" | "expired" | "approved" | "revoked";
    content_granularity: "metadata" | "full_text";
    request_id: string | null;
  };
  analysis: {
    status: "available" | "incomplete";
    reason: string;
    available: string[];
    unavailable: string[];
  };
  context: {
    actions?: Array<{
      id: string;
      title: string;
      status: string;
      created_at: string;
      delegation_count: number;
      evidence_reference_count: number;
    }>;
    action?: {
      id: string;
      title: string;
      status: string;
      created_at: string;
      delegation_count: number;
      evidence_reference_count: number;
    };
    delegations?: Array<{ id: string; status: string }>;
    sessions?: Array<{ id: string; status: string }>;
    evidence_references?: Array<{ id: string; status: string; stance: string }>;
    artifacts?: Array<{
      id: string;
      content_version: number;
      visibility: string;
      evidence_status: string;
      content?: string;
    }>;
  };
};

export function listAgentPermissionRequests(): Promise<AgentPermissionRequest[]> {
  return request<AgentPermissionRequest[]>("/api/learning/agent/permission-requests");
}

export function createAgentPermissionRequest(payload: {
  purpose: string;
  target_id: string;
  content_granularity: "metadata" | "full_text";
  ttl_seconds: number;
  request_key: string;
}): Promise<AgentPermissionRequest> {
  return request<AgentPermissionRequest>("/api/learning/agent/permission-requests", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function denyAgentPermissionRequest(
  requestId: string,
  reason?: string | null,
): Promise<AgentPermissionRequest> {
  return request<AgentPermissionRequest>(`/api/learning/agent/permission-requests/${requestId}/deny`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  });
}


export function approveAgentPermissionRequest(requestId: string): Promise<AgentPermissionRequest> {
  return request<AgentPermissionRequest>(`/api/learning/agent/permission-requests/${requestId}/approve`, {
    method: "POST",
  });
}

export function revokeAgentPermissionGrant(
  requestId: string,
  reason?: string | null,
): Promise<AgentPermissionRequest> {
  return request<AgentPermissionRequest>(`/api/learning/agent/permission-requests/${requestId}/revoke`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  });
}

export function getAgentContext(targetId?: string): Promise<AgentContext> {
  const query = targetId ? `?target_id=${encodeURIComponent(targetId)}` : "";
  return request<AgentContext>(`/api/learning/agent/context${query}`);
}

export type ReturnReview = {
  id: string;
  position: { goal: string; plan: string; plan_id: string | null; action: string; action_id: string; delegation_id: string; last_session: string | null; last_activity_at: string | null };
  what_happened: { summary: string; action_status: string; delegation_status: string; verification_status: string | null; verification_id: string | null; has_saved_answer: boolean; session_status: string | null };
  supported: Array<{ claim_id: string; label: string; basis_kind: string; scope: string; user_facing_explanation: string }>;
  unknowns: Array<{ reason_code: string; label: string }>;
  recommendation: { kind: string; action_id: string | null; delegation_id: string | null; label: string; reason_code: string; explanation: string; verification_id: string | null };
  choices: string[];
  alternatives: Array<{ action_id: string; delegation_id: string; label: string }>;
  evidence_details: Array<{ id: string; status: string; statement: string; source: string; source_trusted: boolean; scope: string }>;
};
export function getReturnReview(): Promise<ReturnReview | null> {
  return request('/api/learning/return-review');
}
export function chooseReturnReview(id: string, kind: 'review_card_shown' | 'continue' | 'choose_other' | 'choose_new' | 'stop_for_now' | 'evidence_viewed' | 'corrected' | 'entered', requestKey: string, delegationId?: string, sessionId?: string): Promise<{ destination: string; session_id?: string; review_id?: string }> {
  return request(`/api/learning/return-review/${id}/choice`, { method: 'POST', body: JSON.stringify({ kind, request_key: requestKey, delegation_id: delegationId, session_id: sessionId }) });
}

export type QuestionFeedback = { question_id: string; feedback: string; reference_answer: string; follow_up_questions: string[]; unmet_requirements: string[] };
export type VerificationReview = {
  verification: LearningVerification;
  submissions: Array<{ id: string; created_at: string; purged_at: string | null }>;
  selected_submission_id: string | null;
  content: { responses?: Record<string, string>; material?: string; learner_work?: string; evidence_condition?: string } | null;
  evaluations: Array<{ id: string; status: string; reason: string | null; created_at: string; result: (NonNullable<LearningVerification['result']> & { question_feedback?: QuestionFeedback[] }) | null }>;
  selected_evaluation_id: string | null;
  result: (NonNullable<LearningVerification['result']> & { question_feedback?: QuestionFeedback[] }) | null;
  discussions: Array<{ id: string; question_id: string; submission_id: string; created_at: string; purged_at: string | null }>;
  purge_discussion_count: number;
};
export type QuestionDiscussion = {
  id: string; verification_id: string; submission_id: string; question_id: string; purged: boolean;
  source: { question: string; answer: string; material: string; feedback: QuestionFeedback | { feedback: string; next_step: string; legacy: boolean } } | null;
  turns: Array<{ question_id: string; parent_turn_id: string | null; id: string; request_key: string; user_content: string | null; assistant_content: string | null; reasoning_content: string | null; status: string; reason: string | null; created_at: string; history_searched: boolean; sources: Array<{ kind: string; excerpt: string }> }>;
};
export type LearningRecord = { id: string; status: string; action_id: string; title: string; goal_title: string; plan_title: string; created_at: string; session_id: string | null; verification_count: number };
export type LearningRecordDetail = { record: LearningRecord; brief: LearningRoomBrief | null; verifications: Array<{ id: string; mode: string; status: string; session_id: string | null; created_at: string; submitted_at: string | null; purged_at: string | null }> };
export function getVerificationReview(id: string, submissionId?: string, evaluationId?: string): Promise<VerificationReview> {
  const query = new URLSearchParams();
  if (submissionId) query.set('submission_id', submissionId);
  if (evaluationId) query.set('evaluation_id', evaluationId);
  return request(`/api/learning/verifications/${id}?${query}`);
}
export function listLearningRecords(): Promise<LearningRecord[]> { return request('/api/learning/records'); }
export function getLearningRecord(id: string): Promise<LearningRecordDetail> { return request(`/api/learning/records/${id}`); }
export function createQuestionDiscussion(id: string, submissionId: string, questionId: string, requestKey: string, evaluationId?: string | null): Promise<QuestionDiscussion> {
  return request(`/api/learning/verifications/${id}/discussions`, { method: 'POST', body: JSON.stringify({ submission_id: submissionId, question_id: questionId, request_key: requestKey, evaluation_id: evaluationId }) });
}
export function getQuestionDiscussion(id: string): Promise<QuestionDiscussion> { return request(`/api/learning/discussions/${id}`); }
export function sendDiscussionMessage(id: string, content: string, requestKey: string, retry = false, versions: { regenerate_turn_id?: string; parent_turn_id?: string } = {}): Promise<QuestionDiscussion> {
  return request(`/api/learning/discussions/${id}/messages`, { method: 'POST', body: JSON.stringify({ content, request_key: requestKey, retry, ...versions }) });
}


export type DiscussionStreamUpdate = { turn: QuestionDiscussion['turns'][number]; purged: boolean };
export function cancelDiscussionTurn(id: string, turnId: string): Promise<QuestionDiscussion> {
  return request(`/api/learning/discussions/${id}/turns/${turnId}/cancel`, { method: 'POST' });
}
export async function streamDiscussionTurn(id: string, turnId: string, onUpdate: (value: DiscussionStreamUpdate) => void, signal: AbortSignal): Promise<void> {
  const response = await fetch(`/api/learning/discussions/${id}/turns/${turnId}/stream`, {
    credentials: 'include', headers: { Accept: 'text/event-stream' }, signal,
  });
  if (!response.ok || !response.body) throw new Error('暂时无法接收回复，请重新连接。');
  let complete = false;
  await readStreamFrames(response, frame => {
    const lines = frame.split('\n');
    const event = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
    const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
    if (event === 'turn' && data) onUpdate(JSON.parse(data) as DiscussionStreamUpdate);
    if (event === 'done') complete = true;
  });
  if (!complete && !signal.aborted) throw new Error('连接已中断，正在恢复回复。');
}
