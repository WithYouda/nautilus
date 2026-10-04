import { learningRequest, type PurgeReport } from './api';

export type CommitmentSource = { kind: 'feedback' | 'artifact' | 'submission' | 'delayed_attempt' | 'completion' | 'path_version' | 'action' | 'outcome' | 'plan_content'; id: string; revision: number };
export type CommitmentItemInput = {
  id: string | null; node_id: string; action_id: string; delegation_id: string;
  estimate_min_minutes: number | null; estimate_max_minutes: number | null;
  due_at: string | null; timezone: string | null; reason: string; source_refs: CommitmentSource[];
};
export type CommitmentItem = Omit<CommitmentItemInput, 'id' | 'reason'> & {
  id: string; reason: string | null; status: 'planned' | 'started' | 'deferred' | 'skipped' | 'completed';
  route_version_id?: string; execution_session_ids: string[]; completion_ids: string[]; source: 'manual' | 'ai';
};
export type CommitmentVersion = { id: string; route_version_id: string; created_at: string; source: 'manual' | 'ai'; items: CommitmentItem[]; reason: string | null; content_available: boolean; can_purge_content: boolean; draft_id: string };
export type CommitmentDraft = Omit<CommitmentVersion, 'draft_id'> & { revision: number; status: 'draft' | 'confirmed' | 'purged'; run_id: string | null };
export type CommitmentCalibration = {
  range: 'short' | 'extended' | 'dated'; min_sessions: number; max_sessions: number; recommended_sessions: number; horizon_days: number | null;
  scope: 'new' | 'same' | 'covered'; reason_codes: string[]; unknowns: string[];
  axes: Array<{ name: 'execution' | 'performance' | 'effort' | 'experience' | 'rhythm'; state: 'covered' | 'partial' | 'unknown' | 'conflict'; source_refs: CommitmentSource[]; unknowns: string[] }>;
  sources: CommitmentSource[]; excluded_sources: Array<CommitmentSource & { reason: string }>; older_sources: Array<{ block_id: string; reason: string; source_refs: CommitmentSource[] }>;
};
export type CommitmentAvailability = { timezone: string; slots: Array<{ start_at: string; end_at: string }>; weekly_budget_minutes: number | null; block_max_minutes: number | null; preferred_days: 7 | 14 };
export type CommitmentView = { plan_id: string; route_status: 'active' | 'paused'; current_node_id: string | null; revision: number; current_version: CommitmentVersion | null; versions: CommitmentVersion[]; drafts: CommitmentDraft[]; calibration: CommitmentCalibration; availability: (CommitmentAvailability & { revision: number }) | null; purge_retry_ids?: string[]; runs?: CommitmentRunSummary[] };
export type CommitmentDraftInput = { route_version_id: string; items: CommitmentItemInput[]; reason: string; draft_id: string | null; expected_draft_revision?: number; expected_revision: number; request_key: string };
export type CommitmentPreview = { review_key: string; revision: number; draft_revision: number; changes: Array<{ kind: 'replace' | 'keep' | 'defer'; item_id: string; executed: boolean; reason_code?: string }>; calibration: CommitmentCalibration; unknowns: string[] };
export type CommitmentItemPreview = { review_key: string; revision: number; operation: 'defer' | 'skip'; item_id: string; affected_sessions: Array<{ id: string; action_id: string }>; due_at: string | null; timezone: string | null };
export type CommitmentRun = { id: string; plan_id: string; revision: number; status: 'running' | 'succeeded' | 'failed' | 'canceled' | 'purged'; reason: string | null; draft_id: string | null; created_at: string; finished_at: string | null; provider_snapshot: Record<string, unknown>; calibration: CommitmentCalibration | null; content_available: boolean; can_purge_content?: boolean; purge_retry_needed?: boolean };
export type CommitmentRunSummary = Pick<CommitmentRun, 'id' | 'plan_id' | 'revision' | 'status' | 'reason' | 'draft_id' | 'created_at' | 'finished_at' | 'can_purge_content' | 'purge_retry_needed'>;
export type SessionFeedbackInput = {
  actual_min_minutes: number | null; actual_max_minutes: number | null; purpose: 'real' | 'test' | 'unknown';
  grain: 'ok' | 'too_large' | 'too_small' | 'unknown'; pace: 'ok' | 'too_tight' | 'want_more' | 'unknown';
  method_feedback: 'ok' | 'unsuitable' | 'unknown'; progress: 'progress' | 'difficulty' | 'uncertain'; activity: 'learning' | 'recall' | 'variation' | 'transfer';
  artifact_id: string | null; artifact_version: number | null; submission_id: string | null; delayed_attempt_id: string | null; notes: string;
};
export type SessionFeedbackRecord = Omit<SessionFeedbackInput, 'notes'> & { revision: number; notes: string | null; created_at: string; content_available: boolean; association_label?: string; source_refs?: CommitmentSource[]; origin_basis?: string; known_origin?: string | null };
export type SessionFeedbackView = {
  session_id: string; known_origin: string | null; origin_basis: string; revision: number; current: SessionFeedbackRecord | null;
  history: SessionFeedbackRecord[]; session_span_minutes: number | null; span_source: 'session_clock'; purged: boolean; can_purge_content?: boolean; purge_retry_needed?: boolean;
  source_choices?: { artifacts: Array<{ id: string; content_version: number; created_at: string }>; submissions: Array<{ id: string; created_at: string }>; delayed_attempts: Array<{ id: string; revision: number; submitted_at: string; phase: string; association_label: string }> };
};

const plan = (id: string) => `/api/learning/plans/${encodeURIComponent(id)}/commitments`;
const feedback = (id: string) => `/api/learning/sessions/${encodeURIComponent(id)}/feedback`;
const post = <T>(path: string, payload: unknown) => learningRequest<T>(path, { method: 'POST', body: JSON.stringify(payload) });
export function getLearningCommitments(planId: string): Promise<CommitmentView> { return learningRequest(plan(planId), { cache: 'no-store' }); }
export function saveCommitmentDraft(planId: string, payload: CommitmentDraftInput): Promise<CommitmentView & { draft_id: string }> { return post(`${plan(planId)}/drafts`, payload); }
export function previewCommitmentDraft(planId: string, draftId: string): Promise<CommitmentPreview> { return post(`${plan(planId)}/previews`, { draft_id: draftId }); }
export function confirmCommitmentDraft(planId: string, payload: { draft_id: string; expected_draft_revision: number; expected_revision: number; review_key: string; request_key: string }): Promise<CommitmentView> { return post(`${plan(planId)}/confirm`, payload); }
export function startCommitmentItem(planId: string, itemId: string, payload: { expected_action_version: number; expected_revision: number; use_checkpoint: boolean; request_key: string }, continuing = false): Promise<{ session_id: string; revision: number; path_anchor?: Record<string, unknown> }> { return post(`${plan(planId)}/items/${encodeURIComponent(itemId)}/${continuing ? 'continue' : 'start'}`, payload); }
export function previewCommitmentItemChange(planId: string, itemId: string, operation: 'defer' | 'skip', dueAt: string | null, timezone: string | null): Promise<CommitmentItemPreview> { return post(`${plan(planId)}/items/${encodeURIComponent(itemId)}/preview`, { operation, due_at: dueAt, timezone }); }
export function changeCommitmentItem(planId: string, itemId: string, operation: 'defer' | 'skip', payload: { due_at: string | null; timezone: string | null; expected_revision: number; review_key: string; request_key: string }): Promise<CommitmentView> { return post(`${plan(planId)}/items/${encodeURIComponent(itemId)}/${operation}`, payload); }
export function saveCommitmentAvailability(planId: string, payload: CommitmentAvailability & { expected_revision: number; request_key: string }): Promise<CommitmentView> { return post(`${plan(planId)}/availability`, payload); }
export function startCommitmentSuggestion(planId: string, revision: number, key: string): Promise<CommitmentRun> { return post(`${plan(planId)}/suggestions`, { expected_revision: revision, request_key: key }); }
export function getCommitmentSuggestion(planId: string, runId: string): Promise<CommitmentRun> { return learningRequest(`${plan(planId)}/suggestions/${encodeURIComponent(runId)}`, { cache: 'no-store' }); }
export function cancelCommitmentSuggestion(planId: string, runId: string, revision: number, key: string): Promise<CommitmentRun> { return post(`${plan(planId)}/suggestions/${encodeURIComponent(runId)}/cancel`, { expected_revision: revision, request_key: key }); }
export function purgeCommitmentContent(planId: string, draftId: string, revision: number, key: string): Promise<CommitmentView & { purge_report: PurgeReport }> { return post(`${plan(planId)}/drafts/${encodeURIComponent(draftId)}/purge`, { expected_revision: revision, request_key: key, confirmation: 'PURGE' }); }
export function getCommitmentContentPurge(planId: string, draftId: string): Promise<PurgeReport> { return learningRequest(`${plan(planId)}/drafts/${encodeURIComponent(draftId)}/purge-status`, { cache: 'no-store' }); }
export function purgeCommitmentSuggestion(planId: string, runId: string, revision: number, key: string): Promise<CommitmentRun & { purge_report: PurgeReport }> { return post(`${plan(planId)}/suggestions/${encodeURIComponent(runId)}/purge`, { expected_revision: revision, request_key: key, confirmation: 'PURGE' }); }
export function getCommitmentSuggestionPurge(planId: string, runId: string): Promise<PurgeReport> { return learningRequest(`${plan(planId)}/suggestions/${encodeURIComponent(runId)}/purge-status`, { cache: 'no-store' }); }
export function getSessionFeedback(sessionId: string): Promise<SessionFeedbackView> { return learningRequest(feedback(sessionId), { cache: 'no-store' }); }
export function recordSessionFeedback(sessionId: string, payload: SessionFeedbackInput & { expected_revision: number; request_key: string }): Promise<SessionFeedbackView> { return post(feedback(sessionId), payload); }
export function purgeSessionFeedback(sessionId: string, revision: number, key: string): Promise<SessionFeedbackView & { purge_report: PurgeReport }> { return post(`${feedback(sessionId)}/purge`, { expected_revision: revision, request_key: key, confirmation: 'PURGE' }); }
export function getSessionFeedbackPurge(sessionId: string): Promise<PurgeReport> { return learningRequest(`${feedback(sessionId)}/purge-status`, { cache: 'no-store' }); }
