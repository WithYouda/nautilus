import type { SearchSelection } from "./SearchControls";
import type { SearchTrace } from "./SearchResults";
import type { GenerationTrace } from "./AssistantResponse";
import type { CoachAssignmentSignal } from './background-coach-api';
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

export type AiApiProtocol = "openai_compatible" | "openai_responses" | "google" | "anthropic";

export type AiProvider = {
  id: string;
  display_name: string;
  provider_kind: "openai_compatible";
  api_protocol?: AiApiProtocol;
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

export type ModelScopeKind = 'global' | 'plan' | 'task' | 'conversation' | 'discussion';
export type ReasoningChoice = { mode: 'default' | 'off' | 'on' } | { mode: 'effort'; effort: string } | { mode: 'budget'; budget_tokens: number; effort?: string };
export type ReasoningCapability = {
  state: 'available' | 'unknown' | 'unsupported'; source: 'official' | 'manual' | 'unknown' | 'api';
  profile_id: string | null; label: string | null; style: string | null; version: number; stale?: boolean;
  efforts: string[]; supports_off: boolean; supports_on: boolean;
  budget: { min: number; max: number | null; dynamic: boolean; efforts: string[] } | null;
  reference_urls: string[];
};
export type ReasoningPreview = {
  capability: ReasoningCapability; default_choice: ReasoningChoice | null; configured_default: ReasoningChoice | null;
  default_required: boolean; configured_profile_id: string | null; profiles: Array<{ id: string; label: string }>;
};
export type ReasoningSupport = ReasoningPreview & { provider_id: string; model_id: string; protocol: AiApiProtocol; revision: string };
export type ModelOverride = { model?: { provider_profile_id: string; provider_model_id: string } | null; timeout_seconds?: number | null; reasoning?: ReasoningChoice | null; reasoning_model?: { provider_profile_id: string; provider_model_id: string } | null };
export type ModelSource = { kind: ModelScopeKind | 'run' | 'model'; id: string };
export type ModelSources = { model: ModelSource | null; timeout: ModelSource | null; reasoning?: ModelSource | null };
export type ModelEffective = {
  provider_profile_id: string | null; provider_model_id: string | null;
  provider_display_name: string | null; model_id: string | null; model_display_name: string | null;
  provider_kind: string | null; timeout_seconds: number | null; provider_config_version: number | null;
  timeout_policy?: 'provider_default' | 'run_extension';
  reasoning?: ReasoningChoice; reasoning_capability?: ReasoningCapability;
  reasoning_parameters?: Record<string, unknown> | null;
  supports_image_input: boolean | null; supports_reasoning: boolean | null; has_api_key: boolean; available: boolean;
};
export type ModelConfig = {
  scope_kind: ModelScopeKind; scope_id: string; revision: string; token: string; override: ModelOverride;
  effective: ModelEffective; sources: ModelSources;
  layers: Array<{ kind: ModelScopeKind; id: string; revision: string; override: ModelOverride }>; issues: string[];
};
export type ModelRunConfig = Partial<ModelEffective> & { sources?: ModelSources | null };
const modelConfigPath = (kind: ModelScopeKind, id: string) => `/api/model-config/${kind}/${encodeURIComponent(id)}`;
export function getModelConfig(kind: ModelScopeKind, id: string): Promise<ModelConfig> { return request(modelConfigPath(kind, id)); }
export function putModelConfig(kind: ModelScopeKind, id: string, expected_revision: string, override: ModelOverride): Promise<ModelConfig> {
  return request(modelConfigPath(kind, id), { method: 'PUT', body: JSON.stringify({ expected_revision, override }) });
}
export function previewModelConfig(kind: ModelScopeKind, id: string, override: ModelOverride): Promise<ModelConfig> {
  return request(`${modelConfigPath(kind, id)}/preview`, { method: 'POST', body: JSON.stringify({ override }) });
}
export function getReasoningSupport(providerId: string, modelId: string): Promise<ReasoningSupport> {
  return request(`/api/ai/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(modelId)}/reasoning-support`);
}
export function saveReasoningSupport(providerId: string, modelId: string, expected_revision: string, profile_id: string | null, default_choice?: ReasoningChoice | null): Promise<ReasoningSupport> {
  return request(`/api/ai/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(modelId)}/reasoning-support`, {
    method: 'PUT', body: JSON.stringify({ expected_revision, profile_id, ...(default_choice !== undefined ? { default_choice } : {}) }),
  });
}
export type ReasoningPreviewInput = {
  provider_id?: string; base_url: string; api_protocol: AiApiProtocol; model: string; api_key?: string;
  profile_id?: string | null; default_choice?: ReasoningChoice | null;
};
export function previewProviderReasoning(value: ReasoningPreviewInput): Promise<ReasoningPreview> {
  return request('/api/ai/provider/reasoning-preview', { method: 'POST', body: JSON.stringify(value) });
}

export type AiProviderInput = {
  display_name: string;
  base_url: string;
  model: string;
  api_protocol?: AiApiProtocol;
  api_key?: string;
  enabled: boolean;
  request_timeout_seconds: number;
  reasoning_settings?: { profile_id: string | null; default_choice: ReasoningChoice | null };
};

export type AiProviderRuntimeInput = {
  api_protocol?: AiApiProtocol;
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
export type HelpRequestKind = 'hint' | 'explain_step' | 'example' | 'try_first';
export type HelpRecord = {
  request: { kind: HelpRequestKind; at: string } | null;
  provided: { kind: 'reply_body'; characters: number; at: string | null; partial: boolean } | null;
  display: { characters: number; at: string; basis: 'client_report' } | null;
};
export type ReferenceHelpDisplay = { kind: 'reference_answer'; at: string; basis: 'client_report' };

export type ConcreteTeachingMethod = 'stepwise' | 'socratic' | 'feynman' | 'practice_first' | 'project';
export type TeachingMethod = ConcreteTeachingMethod | 'adaptive';
export type TeachingSelection = TeachingMethod | 'default';
export type TeachingAction = 'practice' | 'retell' | 'continue' | 'next_question' | 'next_step';
export type TeachingMode = ConcreteTeachingMethod | 'direct_answer' | 'full_explanation';
export type TeachingCheckpoint = {
  mode: TeachingMode | null;
  policy?: 'adaptive';
  mode_source?: 'default' | 'conversation';
  retelling?: { step_id: string; phase: 'awaiting_retelling' | 'feedback_available'; last_observation_id: string | null } | null;
  step: { id: string; source_answer_id: string; text: string; start: number; end: number } | null;
  guidance?: { level: 0 | 1 | 2 | 3 | 4; stuck_count: number; reset_answer_id: string | null } | null;
  practice?: TeachingPractice | null;
  exercise?: TeachingExercise | null;
  project?: TeachingProject | null;
};
export type TeachingTextRef = { answer_id: string; start: number; end: number };
export type TeachingProject = {
  id: string;
  goal: TeachingTextRef;
  step: {
    id: string;
    instruction: TeachingTextRef;
    change: 'start' | 'next' | 'revision';
    previous_step_id: string | null;
    phase: 'awaiting_work' | 'feedback_available';
    last_observation_id: string | null;
    change_request: { message_id: string; start: number; end: number } | null;
  };
};
export type TeachingExercise = {
  id: string;
  question: { answer_id: string; start: number; end: number };
  phase: 'awaiting_attempt' | 'feedback_available';
  last_observation_id: string | null;
};
export type TeachingPractice = {
  id: string;
  kind?: 'variant' | 'retelling';
  basis_step: TeachingCheckpoint['step'];
  question: { answer_id: string; start: number; end: number };
  return_guidance: TeachingCheckpoint['guidance'] | null;
  phase: 'awaiting_attempt' | 'feedback_available';
  last_observation_id: string | null;
};
export type TeachingPracticeObservation = {
  question_id: string; message_id: string; start: number; end: number;
  answer_id: string; feedback_start: number; feedback_end: number;
  eligible: boolean; needs_help: boolean | null; help_context?: unknown[];
};
export type LearningObservationState = 'progress' | 'difficulty' | 'uncertain';
export type LearningObservation = {
  id: string; point_id: string; topic: string; state: LearningObservationState;
  source: { message_id: string; start: number; end: number };
  feedback: TeachingTextRef;
  at: string;
  help_context: Array<HelpRecord & { answer_id: string; method?: string | null }>;
  original: { topic: string; state: LearningObservationState };
  note: string; excluded: boolean; revision: number; eligible: boolean;
  corrections: Array<{ revision: number; topic: string; state: LearningObservationState; note: string; excluded: boolean; at: string }>;
};
export type LearningObservationCorrection = {
  observation_id: string; expected_revision: number; topic: string; state: LearningObservationState;
  note: string; excluded: boolean; request_key: string;
};
export type TeachingRecord = {
  assignment_signal?: CoachAssignmentSignal | null;
  status: 'running' | 'applied' | 'not_updated' | 'unavailable';
  recording?: { available: boolean; reason: 'not_checked' | 'not_supported' | 'native_search_unverified' | null };
  before: TeachingCheckpoint;
  after: TeachingCheckpoint | null;
  current: TeachingCheckpoint;
  effective_mode: TeachingMode | null;
  adaptation?: {
    method: TeachingMode; reason: string | null; rule_id: string | null; profile_revision: number;
    draft: { configuration: AdaptiveLearningConfiguration; source: { message_id: string; start: number; end: number }; reason: string } | null;
  } | null;
  requested_mode?: TeachingSelection | null;
  default_mode?: TeachingMethod;
  requested_action?: TeachingAction | null;
  practice_question?: TeachingPractice | null;
  practice_observation?: TeachingPracticeObservation | null;
  retelling_observation?: TeachingPracticeObservation | null;
  exercise_question?: TeachingExercise | null;
  exercise_observation?: TeachingPracticeObservation | null;
  project_step?: TeachingProject | null;
  project_observation?: (TeachingPracticeObservation & { project_id: string }) | null;
  learning_observations?: LearningObservation[];
  learning_used?: string[];
  guidance?: { level: 0 | 1 | 2 | 3 | 4; reason: string } | null;
  mode_request: { mode: TeachingMode | 'adaptive'; scope: 'turn' | 'conversation'; start: number; end: number } | null;
  attempt: {
    message_id: string; step_id: string; source: 'ai'; start: number; end: number;
    is_attempt: boolean; revision: number; needs_help?: boolean | null;
    corrections: Array<{ revision: number; is_attempt: boolean; needs_help?: boolean | null; at: string }>;
  } | null;
};
export type TeachingAttemptCorrection = { expected_revision: number; is_attempt: boolean; request_key: string; needs_help?: boolean | null };

export type AdaptiveLearningConfiguration = {
  scenario: 'general' | 'concepts' | 'problem_solving' | 'coding' | 'project';
  method: TeachingMode;
  start: 'auto' | 'example_first' | 'try_first' | 'explain_first';
  help: 'auto' | 'one_hint' | 'explain_when_stuck';
};
export type AdaptiveLearningSource = {
  kind: 'conversation' | 'discussion'; scope_id: string; answer_id: string;
  message_id: string; start: number; end: number;
};
export type AdaptiveLearningRule = {
  id: string; configuration: AdaptiveLearningConfiguration; enabled: boolean;
  source: AdaptiveLearningSource | null; original_text: string | null;
};
export type AdaptiveLearningDraft = {
  id: string; configuration: AdaptiveLearningConfiguration; reason: string;
  source: AdaptiveLearningSource; original_text: string | null;
};
export type AdaptiveLearningVersion = { revision: number; created_at: string; rules: AdaptiveLearningRule[] };
export type AdaptiveLearningProfile = {
  revision: number; rules: AdaptiveLearningRule[]; drafts: AdaptiveLearningDraft[]; ignored: AdaptiveLearningDraft[]; history: AdaptiveLearningVersion[];
};
export type AdaptiveLearningChange = { expected_revision: number; request_key: string } & (
  { action: 'accept' | 'dismiss' | 'reconsider'; candidate_id: string }
  | { action: 'edit'; rule_id: string; configuration: AdaptiveLearningConfiguration; enabled: boolean }
  | { action: 'remove'; rule_id: string }
  | { action: 'restore'; version: number }
);
export function getAdaptiveLearning(signal?: AbortSignal): Promise<AdaptiveLearningProfile> {
  return request('/api/adaptive-learning', { signal });
}
export function changeAdaptiveLearning(payload: AdaptiveLearningChange, signal?: AbortSignal): Promise<AdaptiveLearningProfile> {
  return request('/api/adaptive-learning/changes', { method: 'POST', body: JSON.stringify(payload), signal });
}

export type AiMessage = {
  model_config?: ModelRunConfig | null;
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
  question_version_id?: string;
  search_trace?: SearchTrace | null;
  generation_trace?: GenerationTrace | null;
  help_record?: HelpRecord | null;
  teaching?: TeachingRecord | null;
  source_scope?: AppliedSourceScope | null;
  attachment_version_ids?: string[];
  inherited_from?: { conversation_id: string; message_id: string } | null;
};
export type KnowledgeBaseSelection = { kind: 'obsidian_local'; connection_id: string; connection_revision: number };
export type KnowledgeReference = { version_id: string; material_id: string; start_line: number; end_line: number; sha256: string; retrieved_at: string; marker?: string };
export type SourceScope = { mode: 'unspecified' | 'reference' | 'only'; version_ids: string[]; image_version_ids?: string[]; conflict_policy?: 'ask' | 'balanced' | 'materials'; knowledge_base?: KnowledgeBaseSelection };
export type AppliedSourceScope = SourceScope & {
  material_ids: string[];
  materials: Array<{ id: string; material_id: string; version: number; title: string; url: string | null; content_kind: 'text' | 'excerpt' | 'page'; cited: boolean; input_mode?: 'image' | 'text'; page_numbers?: number[]; source_version_id?: string }>;
  fingerprint: string;
  knowledge_base_name?: string;
  selection_version_ids?: string[];
  knowledge_references?: KnowledgeReference[];
  purged?: boolean;
};
export type AttachmentPage = { number: number; text: string; status?: string; reviewed?: boolean; error_code?: string | null };
export type MaterialVersion = { id: string; material_id: string; version: number; title: string | null; content: string | null; url: string | null; content_kind: 'text' | 'excerpt' | 'page'; created_at: string; purged_at: string | null; library: boolean; inherited?: boolean; provenance?: Record<string, unknown>; provenance_json?: string | null; original?: { filename: string; media_type: string; bytes: number; sha256: string } | null; attachment?: { kind: 'image' | 'pdf' | 'text'; mode: 'image' | 'text'; source_version_id: string; page_count: number; origin: 'uploaded' | 'ocr'; pages: AttachmentPage[] } };
export type MaterialOcrSettings = { provider_profile_id: string | null; provider_model_id: string | null };
export type MaterialOcrJob = { id: string; source_version_id: string; status: 'running' | 'review' | 'failed' | 'canceled' | 'confirmed'; pages: AttachmentPage[]; model: { provider_profile_id: string; provider_model_id: string; model: string; protocol: string } | null; error_code: string | null; result_version_id: string | null; created_at: string; updated_at: string };
export function uploadMaterial(kind: MaterialKind, id: string, file: File, materialId?: string): Promise<MaterialVersion> {
  return request(`/api/materials/${kind}/${encodeURIComponent(id)}/upload${materialId ? `?material_id=${encodeURIComponent(materialId)}` : ''}`, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name) }, body: file });
}
export function materialPreviewUrl(kind: MaterialKind, id: string, versionId: string, page = 1): string {
  return `/api/materials/${kind}/${encodeURIComponent(id)}/versions/${encodeURIComponent(versionId)}/preview/${page}`;
}
export function getMaterialOcrSettings(): Promise<MaterialOcrSettings> { return request('/api/material-ocr/settings'); }
export function saveMaterialOcrSettings(settings: MaterialOcrSettings): Promise<MaterialOcrSettings> { return request('/api/material-ocr/settings', { method: 'PUT', body: JSON.stringify(settings) }); }
const ocrPath = (kind: MaterialKind, id: string, version: string) => `/api/material-ocr/${kind}/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}`;
export function getMaterialOcr(kind: MaterialKind, id: string, version: string, jobId?: string): Promise<{ job: MaterialOcrJob | null }> { return request(`${ocrPath(kind, id, version)}${jobId ? `?job_id=${encodeURIComponent(jobId)}` : ''}`); }
export function startMaterialOcr(kind: MaterialKind, id: string, version: string): Promise<{ job: MaterialOcrJob | null }> { return request(ocrPath(kind, id, version), { method: 'POST' }); }
export function cancelMaterialOcr(kind: MaterialKind, id: string, version: string, job: string): Promise<{ job: MaterialOcrJob | null }> { return request(`${ocrPath(kind, id, version)}/${encodeURIComponent(job)}/cancel`, { method: 'POST' }); }
export function confirmMaterialOcr(kind: MaterialKind, id: string, version: string, job: string, pages: Array<{ number: number; text: string }>, acknowledgeIncomplete: boolean): Promise<MaterialVersion> { return request(`${ocrPath(kind, id, version)}/${encodeURIComponent(job)}/confirm`, { method: 'POST', body: JSON.stringify({ pages, acknowledge_incomplete: acknowledgeIncomplete }) }); }
export function setModelImageCapability(provider: string, model: string, supports: boolean | null): Promise<{ model: AiProviderModel }> { return request(`/api/ai/providers/${encodeURIComponent(provider)}/models/${encodeURIComponent(model)}/image-capability`, { method: 'PUT', body: JSON.stringify({ supports_image_input: supports }) }); }
export type MaterialKind = 'conversation' | 'discussion';
export function getMaterials(kind: MaterialKind, id: string): Promise<{ versions: MaterialVersion[] }> {
  return request(`/api/materials/${kind}/${id}`);
}
export function getMaterialLibrary(): Promise<{ versions: MaterialVersion[]; purge_retry_ids?: string[] }> {
  return request('/api/materials/library');
}
export function removeMaterialFromLibrary(materialId: string): Promise<{ removed: boolean }> {
  return request(`/api/materials/library/${encodeURIComponent(materialId)}/remove`, { method: 'POST' });
}
export function purgeLibraryMaterial(materialId: string): Promise<{ purge: PurgeReport; affected_run_ids?: string[] }> {
  return request(`/api/materials/library/${encodeURIComponent(materialId)}/purge`, { method: 'POST' });
}
export function storeMaterialInLibrary(kind: MaterialKind, id: string, materialId: string): Promise<{ stored: boolean }> {
  return request(`/api/materials/${kind}/${id}/${materialId}/library`, { method: 'POST' });
}
export function useMaterialFromLibrary(kind: MaterialKind, id: string, versionId: string): Promise<MaterialVersion> {
  return request(`/api/materials/${kind}/${id}/library-use`, { method: 'POST', body: JSON.stringify({ version_id: versionId }) });
}
export function saveMaterial(kind: MaterialKind, id: string, payload: { title: string; content?: string; material_id?: string; web_run_id?: string; web_item_index?: number }): Promise<MaterialVersion> {
  return request(`/api/materials/${kind}/${id}`, { method: 'POST', body: JSON.stringify(payload) });
}
export function purgeMaterial(kind: MaterialKind, id: string, materialId: string): Promise<{ purge: PurgeReport; affected_run_ids?: string[] }> {
  return request(`/api/materials/${kind}/${id}/${materialId}/purge`, { method: 'POST', body: JSON.stringify({ confirmation: 'PURGE' }) });
}
export function getMaterialPurge(kind: MaterialKind, id: string, materialId: string): Promise<PurgeReport> {
  return request(`/api/materials/${kind}/${id}/${materialId}/purge`);
}

export type ObsidianConnection = { connection_id: string; revision: number; root_path: string; vault_name: string; enabled: boolean };
export type ObsidianSearchItem = { relative_path: string; title: string; excerpt: string; excerpt_start_line: number; excerpt_end_line: number; sha256: string; selection_token: string };
export type ObsidianSearchResult = { items: ObsidianSearchItem[]; next_after: string | null; has_more: boolean; complete: boolean; unreadable_count: number };
export type ObsidianSourceStatus = { status: 'same_as_snapshot' | 'changed' | 'missing' | 'unavailable' | 'disconnected' | 'not_applicable'; checked_at: string | null };
export function getObsidianConnection(): Promise<{ connection: ObsidianConnection | null }> {
  return request('/api/obsidian/connection');
}
export function saveObsidianConnection(rootPath: string, expectedRevision: number | null): Promise<{ connection: ObsidianConnection }> {
  return request('/api/obsidian/connection', { method: 'PUT', body: JSON.stringify({ root_path: rootPath, expected_revision: expectedRevision }) });
}
export function disconnectObsidianConnection(expectedRevision: number): Promise<{ connection: ObsidianConnection }> {
  return request('/api/obsidian/connection/disconnect', { method: 'POST', body: JSON.stringify({ expected_revision: expectedRevision }) });
}
export function searchObsidianNotes(kind: MaterialKind, id: string, payload: { connection_id: string; connection_revision: number; query: string; after?: string | null }): Promise<ObsidianSearchResult> {
  return request(`/api/obsidian/${kind}/${id}/search`, { method: 'POST', body: JSON.stringify({ ...payload, after: payload.after ?? null }) });
}
export function captureObsidianNote(kind: MaterialKind, id: string, selectionToken: string): Promise<MaterialVersion> {
  return request(`/api/obsidian/${kind}/${id}/capture`, { method: 'POST', body: JSON.stringify({ selection_token: selectionToken }) });
}
export function getObsidianSourceStatus(kind: MaterialKind, id: string, versionId: string): Promise<ObsidianSourceStatus> {
  return request(`/api/obsidian/${kind}/${id}/versions/${encodeURIComponent(versionId)}/source-status`);
}

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
  branch_origin?: { conversation_id: string; message_id: string } | null;
  branch_source_scope?: SourceScope | null;
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
  search_trace?: SearchTrace | null;
  generation_trace?: GenerationTrace | null;
};

export type AiStreamEvent =
  | { type: "start"; data: AiStreamStartPayload }
  | { type: "delta"; data: { kind: "content" | "reasoning"; text: string } }
  | { type: "search"; data: { run_id: string; message_id: string | null; trace: SearchTrace } }
  | { type: "process"; data: { run_id: string; message_id: string | null; trace: GenerationTrace } }
  | {
      type: "done";
      data: Pick<AiStreamStartPayload, "run_id" | "message_id" | "status" | "content" | "reasoning_content" | "search_trace" | "generation_trace">;
    }
  | {
      type: "error";
      data: Pick<AiStreamStartPayload, "run_id" | "message_id" | "status" | "content" | "reasoning_content" | "search_trace" | "generation_trace"> & {
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

const teachingRecordingUnavailableMessage = '当前模型暂不能记录教学状态。可在设置中检查支持，或继续普通对话。';

function parseErrorBody(body: unknown): { kind?: string; message?: string } {
  if (!body || typeof body !== "object") return {};
  const detail = "detail" in body ? (body as { detail?: unknown }).detail : body;
  if (typeof detail === "string") return { message: detail === 'teaching_recording_unavailable' ? teachingRecordingUnavailableMessage : detail };
  if (detail && typeof detail === "object") {
    const record = detail as { kind?: unknown; message?: unknown };
    return {
      kind: typeof record.kind === "string" ? record.kind : undefined,
      message: record.kind === 'teaching_recording_unavailable' ? teachingRecordingUnavailableMessage : typeof record.message === "string" ? record.message : undefined,
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

// New learning-domain modules share the existing authentication and error boundary.
export { request as learningRequest };

export function getHealth(): Promise<Health> {
  return request<Health>("/api/health");
}

export function getAuthStatus(): Promise<AuthStatus> {
  return request<AuthStatus>("/api/auth/status");
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

export type TeachingSupportState = 'supported' | 'unavailable' | 'unchecked';
export type TeachingSupport = { plain: TeachingSupportState; tools: TeachingSupportState; checked_at: string | null };
export type TeachingSupportCheck = { support: TeachingSupport; failures: Partial<Record<'plain' | 'tools', string>>; updated: boolean };
const teachingSupportPath = (provider: string, model: string) => `/api/ai/providers/${encodeURIComponent(provider)}/models/${encodeURIComponent(model)}/teaching-support`;
export function getTeachingSupport(provider: string, model: string, signal?: AbortSignal): Promise<TeachingSupport> {
  return request(teachingSupportPath(provider, model), { signal });
}
export function checkTeachingSupport(provider: string, model: string, signal?: AbortSignal): Promise<TeachingSupportCheck> {
  return request(`${teachingSupportPath(provider, model)}/check`, { method: 'POST', signal });
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
  payload: Omit<AiProviderRuntimeInput, "model"> & { force_refresh?: boolean; provider_id?: string },
): Promise<{ models: string[]; cached: boolean; ttl_seconds: number; reasoning_metadata?: Record<string, Record<string, unknown>> }> {
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

export function getAiConversation(conversationId: string, signal?: AbortSignal): Promise<AiConversationDetail> {
  return request<AiConversationDetail>(`/api/ai/conversations/${conversationId}`, { signal });
}

export function branchAiConversation(conversationId: string, messageId: string, requestKey: string): Promise<AiConversationDetail> {
  return request<AiConversationDetail>(`/api/ai/conversations/${conversationId}/branches`, {
    method: 'POST', body: JSON.stringify({ message_id: messageId, request_key: requestKey }),
  });
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
  versions: { model_override?: ModelOverride | null; model_config_token?: string | null; current_state_revision?: number; edit_message_id?: string; regenerate_message_id?: string; parent_message_id?: string; search?: SearchSelection; public_search_query?: string; help_request?: HelpRequestKind | null; teaching_mode?: TeachingSelection | null; teaching_action?: TeachingAction | null; source_scope?: SourceScope; attachment_version_ids?: string[] } = {},
): Promise<AiSendResult> {
  return request<AiSendResult>(`/api/ai/conversations/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content, client_message_id: clientMessageId, ...versions }),
  });
}

export type OutboundRequest = {
  id: string;
  digest: string;
  run_id: string;
  call_id: string;
  service_name: string;
  reason: string;
  method: string;
  url: string;
  headers: Record<string, string>;
  body: string;
};

export function getOutboundRequests(kind: 'conversation' | 'discussion', scopeId: string): Promise<{ items: OutboundRequest[] }> {
  const query = new URLSearchParams({ kind, scope_id: scopeId });
  return request(`/api/outbound/requests?${query}`, { cache: 'no-store' });
}

export function decideOutboundRequest(id: string, digest: string, decision: 'approve' | 'deny' | 'cancel'): Promise<{ status: string }> {
  return request(`/api/outbound/requests/${encodeURIComponent(id)}/decision`, { method: 'POST', body: JSON.stringify({ digest, decision }) });
}

export function recordAiHelpDisplay(conversationId: string, messageId: string, characters: number): Promise<HelpRecord> {
  return request(`/api/ai/conversations/${conversationId}/messages/${messageId}/help-display`, { method: 'POST', body: JSON.stringify({ characters }) });
}

export function correctAiTeachingAttempt(conversationId: string, answerId: string, payload: TeachingAttemptCorrection, signal?: AbortSignal): Promise<TeachingRecord> {
  return request(`/api/ai/conversations/${conversationId}/messages/${answerId}/teaching-attempt`, { method: 'POST', body: JSON.stringify(payload), signal });
}
export function correctAiLearningObservation(conversationId: string, answerId: string, payload: LearningObservationCorrection, signal?: AbortSignal): Promise<TeachingRecord> {
  return request(`/api/ai/conversations/${conversationId}/messages/${answerId}/learning-observation`, { method: 'POST', body: JSON.stringify(payload), signal });
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
  if (!dataLines.length || !["start", "delta", "search", "done", "error"].includes(eventName)) {
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
  deleted?: boolean;
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

export type GoalStatus = LearningGoal['status'];
export type GoalReview = {
  goal: LearningGoal;
  plans: Array<{ id: string; title: string; status: string }>;
  tasks: Array<{ id: string; title: string; status: string; plan_id: string; delegations: Array<{ id: string; status: string }>; running_session_ids: string[] }>;
  counts: { total_tasks: number; completed_tasks: number; open_tasks: number; running_sessions: number };
  review_key: string;
  history: Array<{ id: string; status: GoalStatus; previous_status: GoalStatus; occurred_at: string }>;
};

export function getGoalReview(goalId: string): Promise<GoalReview> {
  return request(`/api/learning/goals/${encodeURIComponent(goalId)}/review`);
}

export function changeGoalStatus(goalId: string, status: GoalStatus, expectedVersion: number, reviewKey: string, idempotencyKey: string): Promise<{ id: string; version: number; status: GoalStatus; interrupted_session_ids: string[] }> {
  return request(`/api/learning/goals/${encodeURIComponent(goalId)}/status`, { method: 'POST', body: JSON.stringify({ status, expected_version: expectedVersion, review_key: reviewKey, idempotency_key: idempotencyKey }) });
}

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
  path_anchor?: { kind?: string; conversation_id?: string; leaf_id?: string | null; paths?: Record<string,string>; state_revision?: number | null; annotation_revision?: number | null };
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

export type PositionRevision = {
  current: string;
  next: string;
  source: "ai" | "user";
  created_at: string;
  basis_message_ids: string[];
  provider_model?: string | null;
};

export type LearningPosition = { message_id: string; revisions: PositionRevision[] };

function positionPath(sessionId: string) {
  return `/api/learning/sessions/${encodeURIComponent(sessionId)}/room/position`;
}

export function getLearningPosition(sessionId: string, conversationId: string, messageId: string, signal?: AbortSignal): Promise<LearningPosition> {
  const query = new URLSearchParams({ conversation_id: conversationId, message_id: messageId });
  return request<LearningPosition>(`${positionPath(sessionId)}?${query}`, { signal });
}

export function saveLearningPosition(sessionId: string, payload: {
  conversation_id: string;
  message_id: string;
  expected_revision: number;
  current: string;
  next: string;
}, signal?: AbortSignal): Promise<LearningPosition> {
  return request<LearningPosition>(positionPath(sessionId), { method: "PUT", body: JSON.stringify(payload), signal });
}

export function generateLearningPosition(sessionId: string, payload: {
  conversation_id: string;
  message_id: string;
  expected_revision: number;
}, signal?: AbortSignal): Promise<LearningPosition> {
  return request<LearningPosition>(`${positionPath(sessionId)}/generate`, { method: "POST", body: JSON.stringify(payload), signal });
}

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

export type PurgeReport = {
  status: 'not_requested' | 'pending' | 'partial' | 'complete';
  updated_at?: string;
  files: Array<{ name: string; status: 'cleared' | 'failed'; reason?: string }>;
  external_limits: string[];
};

export function getLearningPurgeReport(kind: 'verification' | 'completion' | 'artifact' | 'practice' | 'delayed', objectId: string): Promise<PurgeReport> {
  return request<PurgeReport>(`/api/learning/purges/${kind}/${objectId}`);
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
  position: { goal: string; goal_id?: string | null; goal_status?: GoalStatus | null; plan: string; plan_id: string | null; action: string; action_id: string; delegation_id: string; last_session: string | null; last_activity_at: string | null };
  what_happened: { summary: string; action_status: string; delegation_status: string; verification_status: string | null; verification_id: string | null; has_saved_answer: boolean; session_status: string | null; completion?: CompletionFact | null };
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
export type HelpContext = { captured_at: string; user_report: string; coverage: 'same_verification'; records: Array<{ kind: 'reference_answer' | 'discussion_reply'; evaluation_id?: string; question_id?: string; turn_id?: string; discussion_id?: string; provided_at?: string | null; displayed_at?: string | null; characters?: number; partial?: boolean }>; independence: 'not_inferred' };
export type VerificationReview = {
  verification: LearningVerification;
  submissions: Array<{ id: string; created_at: string; purged_at: string | null }>;
  selected_submission_id: string | null;
  content: { responses?: Record<string, string>; material?: string; learner_work?: string; evidence_condition?: string; help_context?: HelpContext } | null;
  help_displays?: Record<string, ReferenceHelpDisplay>;
  evaluations: Array<{ id: string; status: string; reason: string | null; created_at: string; result: (NonNullable<LearningVerification['result']> & { question_feedback?: QuestionFeedback[] }) | null }>;
  selected_evaluation_id: string | null;
  result: (NonNullable<LearningVerification['result']> & { question_feedback?: QuestionFeedback[] }) | null;
  discussions: Array<{ title: string; id: string; question_id: string; submission_id: string; created_at: string; purged_at: string | null }>;
  purge_discussion_count: number;
};
export type QuestionDiscussion = {
  title: string;
  id: string; identity_id?: string; verification_id: string; submission_id: string; evaluation_id?: string | null; question_id: string; purged: boolean;
  branch_origin?: { discussion_id: string; turn_id: string } | null;
  branch_source_scope?: SourceScope | null;
  help_displays?: Record<string, ReferenceHelpDisplay>;
  source: { question: string; answer: string; material: string; feedback: QuestionFeedback | { feedback: string; next_step: string; legacy: boolean } } | null;
  provider_protocol?: AiApiProtocol | null;
  image_model?: { provider_profile_id: string; provider_model_id: string; model: string; supports_image_input: boolean | null } | null;
  turns: Array<{ model_config?: ModelRunConfig | null; teaching?: TeachingRecord | null; search_trace?: SearchTrace | null; generation_trace?: GenerationTrace | null; help_record?: HelpRecord | null; source_scope?: AppliedSourceScope | null; attachment_version_ids?: string[]; inherited_from?: { discussion_id: string; turn_id: string } | null; question_version_id?: string; question_id: string; parent_turn_id: string | null; id: string; request_key: string; user_content: string | null; assistant_content: string | null; reasoning_content: string | null; status: string; reason: string | null; created_at: string; history_searched: boolean; sources: Array<{ kind: string; excerpt: string }> }>;
};
export type LearningRecord = { id: string; outcome_id: string; status: string; action_id: string; title: string; goal_title: string; plan_title: string; created_at: string; session_id: string | null; verification_count: number };
export type LearningRecordDetail = { sessions?: Array<{id:string;status:string;started_at:string;ended_at:string|null}>; record: LearningRecord; brief: LearningRoomBrief | null; verifications: Array<{ id: string; mode: string; status: string; session_id: string | null; created_at: string; submitted_at: string | null; purged_at: string | null }> };
export type CompletionKind = 'unverified' | 'external_material' | 'external_report';
export type CompletionFact = { id: string; verification_kind: CompletionKind; created_at: string; purged_at: string | null; delegation_id?: string };
export type CompletionContent = { note: string; report: { method: string; result: string } | null; material: { kind: 'work' | 'result'; label: string; text: string } | null };
export type CompletionReview = { id: string; status: 'running' | 'succeeded' | 'failed'; reason: string | null; created_at: string; finished_at: string | null; provider_name: string | null; model: string | null; result: null | { summary: string; findings: Array<{ kind: 'issue' | 'question' | 'insufficient' | 'no_issue'; quote: string; comment: string }>; limitations: string; next_step: string }; user_response: string | null };
export type LearningCompletion = CompletionFact & { action_id: string; delegation_id: string; content: CompletionContent | null; contract: null | { version: number; criterion_id: string | null; stop_conditions: string; boundaries: string }; reviews: CompletionReview[] };
export type CreateLearningCompletion = CompletionContent & { request_key: string; verification_kind: CompletionKind };
export function getLearningCompletion(delegationId: string): Promise<LearningCompletion | null> { return request(`/api/learning/delegations/${delegationId}/completion`); }
export function createLearningCompletion(delegationId: string, payload: CreateLearningCompletion): Promise<LearningCompletion> { return request(`/api/learning/delegations/${delegationId}/completion`, { method: 'POST', body: JSON.stringify(payload) }); }
export function reviewLearningCompletion(id: string, requestKey: string): Promise<LearningCompletion> { return request(`/api/learning/completions/${id}/reviews`, { method: 'POST', body: JSON.stringify({ request_key: requestKey }) }); }
export function respondToCompletionReview(id: string, reviewId: string, value: string): Promise<LearningCompletion> { return request(`/api/learning/completions/${id}/reviews/${reviewId}/response`, { method: 'PUT', body: JSON.stringify({ text: value }) }); }
export function purgeLearningCompletion(id: string): Promise<LearningCompletion> { return request(`/api/learning/completions/${id}/purge`, { method: 'POST' }); }
export type OutcomeReview = {
  outcome: { id: string; object_description: string; behavior: string; context_key: string };
  records: LearningRecord[];
  completions?: CompletionFact[];
  standards: Array<{ id: string; title: string; version: number; review_status: string; availability: string | null; dimensions: Array<{ id: string; label: string; state: LearningDerivedState | null }> }>;
  attempts: Array<{ verification_id: string; submission_id: string | null; evaluation_id: string | null; delegation_id: string; action_title: string; mode: string; created_at: string; criterion_id: string | null; standard_version: number | null; contract_version: number | null; evaluation_status: string | null; condition: string | null; condition_basis: 'submission_record' | null; feedback: string | null; passed: boolean | null; available: boolean; unavailable_reason: 'purged' | 'hidden' | 'not_submitted' | null; artifact_id: string | null }>;
  practices?: Array<{ id: string; verification_id: string; submission_id: string; evaluation_id: string; question_id: string; created_at: string; status: string; available: boolean; purged_at: string | null; attempt_count: number; latest_feedback: string | null }>;
  artifacts: Array<{ artifact_id: string; content_version: number; created_at: string; delegation_id: string; action_title: string; criterion_id: string | null; visibility: string; evidence_status: string; available: boolean }>;
  claims: Array<{ id: string; criterion_id: string; dimension_id: string; status: string; stance: string; source: string; verification_method: string; evidence_condition: string; condition_basis: string | null; statement: string | null; created_at: string; artifact_id: string; content_version: number; available: boolean; reviews: Array<{ id: string; action: string; reason: string | null; created_at: string }> }>;
  follow_ups: Array<{ id: string; claim_id: string; kind: string; status: string; due_at: string | null; created_at: string; note: string | null }>;
};
export function getOutcomeReview(id: string): Promise<OutcomeReview> { return request(`/api/learning/outcomes/${id}/review`); }

export type OutcomeRelationType = 'contains' | 'prerequisite' | 'equivalent' | 'overlap';
export type OutcomeRelationSource = { kind: 'outcome' | 'artifact' | 'criterion' | 'external'; id?: string; version?: number; url?: string; available?: boolean; unavailable_reason?: string | null };
export type OutcomeRelationFields = { source_outcome_id: string; target_outcome_id: string; relation_type: OutcomeRelationType; context_key: string; rationale: string; uncertainty: string; source_refs: OutcomeRelationSource[] };
export type OutcomeRelationReadFields = Omit<OutcomeRelationFields, 'context_key' | 'rationale' | 'uncertainty'> & { context_key: string | null; rationale: string | null; uncertainty: string | null };
export type OutcomeRelation = OutcomeRelationReadFields & { id: string; source_kind: 'manual' | 'ai_accepted'; candidate_id: string | null; revision: number; status: 'active' | 'revoked' | 'purged'; created_at: string; updated_at: string; available: boolean };
export type OutcomeRelationDetail = OutcomeRelation & { history: OutcomeRelation[] };
export type OutcomeGraphStandard = { id: string; version: number; context_key: string; review_status: string; availability: string | null; package_id: string | null; package_title: string | null; package_version: number | null; sources: string[]; scope: string; limitations: string[]; dimensions: Array<{ id: string; label: string; state: LearningDerivedState | null }> };
export type OutcomeGraphNode = { id: string; kind: 'atomic' | 'composite'; object_description: string; behavior: string; context_key: string; source: string; created_at: string; plan_ids: string[]; task_links: Array<{ action_id: string; action_title: string; plan_id: string }>; evidence_links: Array<{ claim_id: string; artifact_id: string; content_version: number; fact_event_id: string; criterion_id: string; dimension_id: string; stance: string; available: boolean }>; coverage: { status: 'no_standard' | 'unknown' | 'insufficient' | 'provisional' | 'supported' | 'conflicting' | 'mixed'; standards: OutcomeGraphStandard[] }; overall_evidence_required: boolean };
export type OutcomeRelationCandidate = OutcomeRelationReadFields & { id: string; revision: number; status: 'pending' | 'accepted' | 'rejected' | 'purged'; relation_id: string | null; available: boolean };
export type OutcomeSuggestionRun = { id: string; revision: number; status: 'running' | 'succeeded' | 'failed' | 'canceled' | 'purged'; reason: string | null; outcome_ids: string[]; provider_snapshot: { [key: string]: unknown } | null; created_at: string; finished_at: string | null; candidates: OutcomeRelationCandidate[] };
export type OutcomeGraphData = { nodes: OutcomeGraphNode[]; relations: OutcomeRelation[]; plans: Array<{ id: string; title: string; status: string }>; runs: OutcomeSuggestionRun[] };
const outcomeGraphPath = '/api/learning/outcome-graph';
function writableOutcomeRelation(relation: OutcomeRelationFields): OutcomeRelationFields {
  return { ...relation, source_refs: relation.source_refs.map(ref => ({ kind: ref.kind, ...(ref.id ? { id: ref.id } : {}), ...(ref.version !== undefined ? { version: ref.version } : {}), ...(ref.url ? { url: ref.url } : {}) })) };
}
export function getOutcomeGraph(planId?: string): Promise<OutcomeGraphData> { return request(`${outcomeGraphPath}${planId ? `?plan_id=${encodeURIComponent(planId)}` : ''}`); }
export function createGraphOutcome(payload: { request_key: string; kind: OutcomeGraphNode['kind']; object_description: string; behavior: string; context_key: string }): Promise<{ id: string; event_id: string; aggregate_version: number }> { return request(`${outcomeGraphPath}/outcomes`, { method: 'POST', body: JSON.stringify(payload) }); }
export function createOutcomeRelation(payload: OutcomeRelationFields & { request_key: string }): Promise<{ id: string; aggregate_version: number }> { return request(`${outcomeGraphPath}/relations`, { method: 'POST', body: JSON.stringify(writableOutcomeRelation(payload)) }); }
export function getOutcomeRelation(id: string): Promise<OutcomeRelationDetail> { return request(`${outcomeGraphPath}/relations/${encodeURIComponent(id)}`); }
export function reviseOutcomeRelation(id: string, payload: OutcomeRelationFields & { request_key: string; expected_revision: number }): Promise<{ id: string; aggregate_version: number }> { return request(`${outcomeGraphPath}/relations/${encodeURIComponent(id)}/revise`, { method: 'POST', body: JSON.stringify(writableOutcomeRelation(payload)) }); }
export function revokeOutcomeRelation(id: string, revision: number, requestKey: string): Promise<{ id: string; aggregate_version: number }> { return request(`${outcomeGraphPath}/relations/${encodeURIComponent(id)}/revoke`, { method: 'POST', body: JSON.stringify({ request_key: requestKey, expected_revision: revision }) }); }
export function createOutcomeSuggestions(ids: string[], requestKey: string): Promise<OutcomeSuggestionRun> { return request(`${outcomeGraphPath}/suggestions`, { method: 'POST', body: JSON.stringify({ outcome_ids: ids, request_key: requestKey }) }); }
export function getOutcomeSuggestions(id: string): Promise<OutcomeSuggestionRun> { return request(`${outcomeGraphPath}/suggestions/${encodeURIComponent(id)}`); }
export function cancelOutcomeSuggestions(id: string, revision: number, requestKey: string): Promise<OutcomeSuggestionRun> { return request(`${outcomeGraphPath}/suggestions/${encodeURIComponent(id)}/cancel`, { method: 'POST', body: JSON.stringify({ expected_revision: revision, request_key: requestKey }) }); }
export function purgeGraphContent(kind: 'relation' | 'run', id: string, revision: number, requestKey: string): Promise<{ purge_report: PurgeReport }> { return request(`${outcomeGraphPath}/${kind === 'relation' ? 'relations' : 'suggestions'}/${encodeURIComponent(id)}/purge`, { method: 'POST', body: JSON.stringify({ expected_revision: revision, request_key: requestKey, confirmation: 'PURGE' }) }); }
export function getGraphPurgeReport(kind: 'relation' | 'run', id: string): Promise<PurgeReport> { return request(`${outcomeGraphPath}/${kind === 'relation' ? 'relations' : 'suggestions'}/${encodeURIComponent(id)}/purge-status`); }
export function reviewOutcomeSuggestion(runId: string, candidate: OutcomeRelationCandidate, decision: 'accept' | 'reject', requestKey: string, relation?: OutcomeRelationFields): Promise<{ candidate_id: string; revision: number; status: string; relation_id: string | null }> { return request(`${outcomeGraphPath}/suggestions/${encodeURIComponent(runId)}/candidates/${encodeURIComponent(candidate.id)}/review`, { method: 'POST', body: JSON.stringify({ request_key: requestKey, expected_revision: candidate.revision, decision, ...(relation ? { relation: writableOutcomeRelation(relation) } : {}) }) }); }
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
export function getQuestionDiscussion(id: string, signal?: AbortSignal): Promise<QuestionDiscussion> { return request(`/api/learning/discussions/${id}`, { signal }); }
export function branchQuestionDiscussion(id: string, turnId: string, requestKey: string): Promise<QuestionDiscussion> {
  return request(`/api/learning/discussions/${id}/branches`, { method: 'POST', body: JSON.stringify({ turn_id: turnId, request_key: requestKey }) });
}
export function sendDiscussionMessage(id: string, content: string, requestKey: string, retry = false, versions: { model_override?: ModelOverride | null; model_config_token?: string | null; current_state_revision?: number; edit_turn_id?: string; regenerate_turn_id?: string; parent_turn_id?: string; search?: SearchSelection; public_search_query?: string; help_request?: HelpRequestKind | null; teaching_mode?: TeachingSelection | null; teaching_action?: TeachingAction | null; source_scope?: SourceScope; attachment_version_ids?: string[] } = {}): Promise<QuestionDiscussion> {
  return request(`/api/learning/discussions/${id}/messages`, { method: 'POST', body: JSON.stringify({ content, request_key: requestKey, retry, ...versions }) });
}
export function recordDiscussionHelpDisplay(discussionId: string, turnId: string, characters: number): Promise<HelpRecord> {
  return request(`/api/learning/discussions/${discussionId}/turns/${turnId}/help-display`, { method: 'POST', body: JSON.stringify({ characters }) });
}
export function correctDiscussionTeachingAttempt(discussionId: string, turnId: string, payload: TeachingAttemptCorrection, signal?: AbortSignal): Promise<TeachingRecord> {
  return request(`/api/learning/discussions/${discussionId}/turns/${turnId}/teaching-attempt`, { method: 'POST', body: JSON.stringify(payload), signal });
}
export function correctDiscussionLearningObservation(discussionId: string, turnId: string, payload: LearningObservationCorrection, signal?: AbortSignal): Promise<TeachingRecord> {
  return request(`/api/learning/discussions/${discussionId}/turns/${turnId}/learning-observation`, { method: 'POST', body: JSON.stringify(payload), signal });
}
export function recordReferenceHelpDisplay(verificationId: string, evaluationId: string, questionId: string): Promise<ReferenceHelpDisplay> {
  return request(`/api/learning/verifications/${verificationId}/evaluations/${evaluationId}/questions/${questionId}/help-display`, { method: 'POST' });
}

export type PracticeKind = 'redo' | 'new_situation';
export type DelayedStandard = { id: string; version: number; title: string; source: string; review_status: 'approved'; reviewed_by: string; reviewed_at: string; minimum_interval_seconds: number; suggested_interval_seconds: number; executor_version: string; limitations: string; content_hash: string };
export type DelayedSource = { artifact_id: string; content_version: number; delegation_id: string; criterion_id: string; action_title: string; created_at: string };
export type DelayedItem = { id: string; pattern: string; text: string };
export type DelayedAnswers = Record<string, boolean | null>;
export type DelayedReport = 'none' | 'used' | 'unknown';
export type DelayedCondition = { user_report: DelayedReport; observed_views: Array<{ attempt_id: string; provided_at: string | null; displayed_at: string | null; after_arranging: boolean }>; independence: 'unverified' };
export type DelayedAttempt = { id: string; phase: 'initial' | 'followup'; revision: number; answers: DelayedAnswers | null; user_report: DelayedReport | null; condition: DelayedCondition | null; submitted_at: string | null; check_status: 'not_checked' | 'succeeded' | 'failed'; checked_at: string | null; purged_at: string | null };
export type DelayedDetail = { id: string; outcome_id: string; delegation_id: string; source_artifact_id: string; source_content_version: number; source_criterion_id: string; standard: DelayedStandard | null; status: 'initial' | 'scheduled' | 'started' | 'completed' | 'skipped' | 'purged'; available: boolean; created_at: string; due_at: string | null; timezone: string | null; arranged_at: string | null; started_at: string | null; purged_at: string | null; server_now: string; is_due: boolean; history: Array<{ operation: string; at: string; due_at?: string; timezone?: string }>; items: DelayedItem[]; active_attempt_id: string | null; attempts: DelayedAttempt[]; comparison: null | { interval_seconds: number; minimum_interval_seconds: number; interval_met: boolean; initial_correct: number; followup_correct: number; description: string }; purge?: PurgeReport };
export type DelayedReveal = { view_id: string; attempt_id: string; phase: 'initial' | 'followup'; items: DelayedItem[]; answers: Record<string, boolean>; result: null | { executor_version: string; standard_hash: string; python_version: string; correct: number; total: number; items: Array<{ id: string; pattern: string; text: string; answer: boolean; expected: boolean; correct: boolean }>; description: string }; condition: DelayedCondition | null; submitted_at: string };
const delayedPath = (id: string) => `/api/learning/delayed-follow-ups/${id}`;
export function listOutcomeDelayed(outcomeId: string): Promise<{ standard: DelayedStandard; sources: DelayedSource[]; items: DelayedDetail[] }> { return request(`/api/learning/outcomes/${outcomeId}/delayed-follow-ups`); }
export function listHomeDelayed(): Promise<{ items: DelayedDetail[]; server_now: string }> { return request('/api/learning/delayed-follow-ups'); }
export function createDelayed(outcomeId: string, source: DelayedSource, requestKey: string): Promise<DelayedDetail> { return request(`/api/learning/outcomes/${outcomeId}/delayed-follow-ups`, { method: 'POST', body: JSON.stringify({ source_artifact_id: source.artifact_id, source_content_version: source.content_version, request_key: requestKey }) }); }
export function getDelayed(id: string): Promise<DelayedDetail> { return request(delayedPath(id)); }
export function saveDelayedDraft(id: string, attemptId: string, revision: number, answers: DelayedAnswers, userReport: DelayedReport): Promise<DelayedDetail> { return request(`${delayedPath(id)}/attempts/${attemptId}/draft`, { method: 'PUT', body: JSON.stringify({ revision, answers, user_report: userReport }) }); }
export function submitDelayed(id: string, attemptId: string, revision: number, answers: Record<string, boolean>, userReport: DelayedReport, requestKey: string): Promise<DelayedDetail> { return request(`${delayedPath(id)}/attempts/${attemptId}/submit`, { method: 'POST', body: JSON.stringify({ revision, answers, user_report: userReport, request_key: requestKey }) }); }
export function checkDelayed(id: string, attemptId: string): Promise<DelayedDetail> { return request(`${delayedPath(id)}/attempts/${attemptId}/check`, { method: 'POST', body: '{}' }); }
export function revealDelayed(id: string, attemptId: string): Promise<DelayedReveal> { return request(`${delayedPath(id)}/attempts/${attemptId}/reveal`, { method: 'POST', body: '{}' }); }
export function displayDelayed(id: string, viewId: string): Promise<{ id: string; displayed_at: string }> { return request(`${delayedPath(id)}/views/${viewId}/display`, { method: 'POST', body: '{}' }); }
export function scheduleDelayed(id: string, dueAt: string, timezone: string, requestKey: string): Promise<DelayedDetail> { return request(`${delayedPath(id)}/schedule`, { method: 'POST', body: JSON.stringify({ due_at: dueAt, timezone, request_key: requestKey }) }); }
export function chooseDelayed(id: string, choice: 'start' | 'skip', requestKey: string): Promise<DelayedDetail> { return request(`${delayedPath(id)}/choice`, { method: 'POST', body: JSON.stringify({ choice, request_key: requestKey }) }); }
export function purgeDelayed(id: string): Promise<DelayedDetail> { return request(`${delayedPath(id)}/purge`, { method: 'POST', body: '{}' }); }
export type Practice = {
  id: string; verification_id: string; submission_id: string; evaluation_id: string; question_id: string;
  available?: boolean;
  operation: 'exercise' | 'recheck'; requested_kind: PracticeKind;
  status: 'running' | 'ready' | 'reviewed' | 'started' | 'skipped' | 'failed' | 'purged';
  reason: string | null; created_at: string; started_at: string | null; purged_at: string | null;
  request: { objection?: string; recheck_id?: string; previous_id?: string; [key: string]: unknown } | null;
  contract: { version: number; criterion_id: string | null; standard_version: number | null; [key: string]: unknown } | null;
  content: { review: { status: 'supported' | 'corrected' | 'insufficient'; summary: string; basis: Array<{ source: 'question' | 'answer' | 'feedback'; quote: string }> }; exercise: { kind: PracticeKind; focus: 'required_gap' | 'optional'; reason: string; basis: Array<{ source: 'question' | 'answer' | 'feedback'; quote: string }>; prompt: string } | null } | null;
  attempts: Array<{ id: string; answer: string | null; condition: { user_report: string; evidence_condition: 'independent' | 'with_materials'; attempt_kind: PracticeKind | 'same_question_retry'; captured_at: string; records: Array<{ run_id: string; kind: string; provided_at: string | null; displayed_at: string | null }> } | null; created_at: string; purged_at: string | null }>;
  runs: Array<{ id: string; kind: 'hint' | 'evaluation'; attempt_id: string | null; status: 'running' | 'succeeded' | 'failed'; result: { text?: string; assessment?: 'meets' | 'needs_work' | 'uncertain'; feedback?: string; answer_quote?: string; remaining?: string[]; next_step?: string } | null; reason: string | null; provider_name: string | null; model: string | null; created_at: string; finished_at: string | null; displayed_at: string | null; purged_at: string | null }>;
};
export function listPractices(verificationId: string, submissionId: string, evaluationId: string, questionId: string): Promise<Practice[]> {
  const query = new URLSearchParams({ submission_id: submissionId, evaluation_id: evaluationId, question_id: questionId });
  return request(`/api/learning/verifications/${verificationId}/practices?${query}`);
}
export function createPractice(verificationId: string, payload: { submission_id: string; evaluation_id: string; question_id: string; request_key: string; operation: 'exercise' | 'recheck'; requested_kind: PracticeKind; objection?: string; recheck_id?: string; previous_id?: string }): Promise<Practice> {
  return request(`/api/learning/verifications/${verificationId}/practices`, { method: 'POST', body: JSON.stringify(payload) });
}
export function getPractice(id: string): Promise<Practice> { return request(`/api/learning/practices/${id}`); }
export function choosePractice(id: string, choice: 'start' | 'skip'): Promise<Practice> { return request(`/api/learning/practices/${id}/choice`, { method: 'POST', body: JSON.stringify({ choice }) }); }
export function savePracticeAttempt(id: string, payload: { answer: string; evidence_condition: 'independent' | 'with_materials'; request_key: string }): Promise<Practice> {
  return request(`/api/learning/practices/${id}/attempts`, { method: 'POST', body: JSON.stringify(payload) });
}
export function runPractice(id: string, payload: { kind: 'hint' | 'evaluation'; attempt_id?: string; request_key: string }): Promise<Practice> {
  return request(`/api/learning/practices/${id}/runs`, { method: 'POST', body: JSON.stringify(payload) });
}
export function recordPracticeDisplay(id: string, runId: string): Promise<Practice> { return request(`/api/learning/practices/${id}/runs/${runId}/display`, { method: 'POST' }); }
export function purgePractice(id: string): Promise<Practice> { return request(`/api/learning/practices/${id}/purge`, { method: 'POST' }); }


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

export type BranchMapNode = {
  id: string; title: string; parent_id: string | null; source_id: string | null;
  source_excerpt: string | null; available: boolean; created_at: string;
};
export type BranchMapData = { current_id: string; nodes: BranchMapNode[] };
export function getBranchMap(kind: 'conversation' | 'discussion', id: string): Promise<BranchMapData> {
  return request(`${kind === 'conversation' ? '/api/ai/conversations' : '/api/learning/discussions'}/${id}/branch-map`);
}
export function renameBranchNode(kind: 'conversation' | 'discussion', id: string, title: string): Promise<unknown> {
  return request(`${kind === 'conversation' ? '/api/ai/conversations' : '/api/learning/discussions'}/${id}${kind === 'discussion' ? '/title' : ''}`, { method: 'PATCH', body: JSON.stringify({ title }) });
}

export type ConversationStateValues = {
  leaf_id: string | null;
  paths: Record<string, string>;
  source_scope: SourceScope;
  search_override: SearchSelection | null;
};
export type ConversationState = ConversationStateValues & { initialized: boolean; revision: number; issues: string[] };
export const getConversationState = (kind: MaterialKind, id: string) =>
  request<ConversationState>(`/api/conversation-state/${kind}/${encodeURIComponent(id)}`);
export const putConversationState = (kind: MaterialKind, id: string, value: ConversationStateValues, revision: number) =>
  request<ConversationState>(`/api/conversation-state/${kind}/${encodeURIComponent(id)}`, {
    method: 'PUT', body: JSON.stringify({ leaf_id: value.leaf_id, paths: value.paths, source_scope: value.source_scope, search_override: value.search_override, expected_revision: revision }),
  });
