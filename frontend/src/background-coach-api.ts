import { learningRequest } from './api';

export type CoachScope = 'global' | 'plan';
export type CoachSettings = { revision: number; enabled: boolean; timezone: string; max_calls_per_session: number; max_calls_per_day: number; cooldown_minutes: number };
export type CoachSource = { kind: 'event' | 'answer' | 'feedback' | 'claim' | 'revisit' | 'delayed_follow_up' | 'commitment_item' | 'path_version' | 'action' | 'permission' | 'artifact'; id: string; revision: number | null; label: string; available: boolean; href: string | null };
export type CoachPermissionRequest = { purpose: string; scope: 'learning_action'; target_id: string; content_granularity: 'full_text'; ttl_seconds: 300; alternative: string; request_key: string };
export type CoachTarget = { kind: 'task' | 'evidence_review' | 'delayed_follow_up' | 'path_review' | 'commitment_review' | 'new_task' | 'permission_review'; plan_id: string | null; action_id: string | null; delegation_id: string | null; object_id: string | null; href: string; label: string; permission_request?: CoachPermissionRequest };
export type CoachCandidate = { id: string; run_id: string; revision: number; scope: CoachScope; plan_id: string | null; status: 'pending' | 'accepted' | 'rejected' | 'ignored' | 'unavailable'; title: string | null; explanation: string | null; unknowns: string[]; target: CoachTarget | null; sources: CoachSource[]; content_available: boolean; created_at: string; decided_at: string | null };
export type CoachRun = { id: string; revision: number; scope: CoachScope; plan_id: string | null; status: 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled' | 'purged'; reason: string | null; created_at: string; finished_at: string | null; provider_snapshot: Record<string, unknown> | null; content_available: boolean; permission_candidate_id?: string | null; permission_request_id?: string | null };
export type CoachView = { settings: CoachSettings; candidates: CoachCandidate[]; history: CoachCandidate[]; active_run: CoachRun | null; latest_run: CoachRun | null; pending_signals: number; budget: { used_today: number; remaining_today: number; next_allowed_at: string | null } };
export type CoachSignalKind = 'separate_work_requested' | 'repeated_blocker' | 'scope_conflict' | 'cannot_continue' | 'permission_or_cost_change';
export type CoachSignal = { id: string; revision: number; kind: CoachSignalKind; status: 'active' | 'excluded' | 'unavailable'; plan_id: string | null; action_id: string; delegation_id: string | null; session_id: string | null; immediate: boolean; source_available: boolean; source: CoachSource; target: CoachTarget | null; created_at: string };
export type CoachAssignmentSignal = Pick<CoachSignal, 'id' | 'kind' | 'immediate' | 'source' | 'target'>;
export type CoachRunDetail = { run: CoachRun; candidates: CoachCandidate[]; inputs: Record<string, unknown> | null; purge_report?: Record<string, unknown> };
export type CoachDecision = { operation: 'accept' | 'reject' | 'ignore' | 'undo'; expected_revision: number; request_key: string };
export { organizationRequestKey as coachKey } from './learning-organization-api';
const base = '/api/learning/coach';
const scoped = (scope: CoachScope, planId?: string | null) => new URLSearchParams({ scope, ...(scope === 'plan' && planId ? { plan_id: planId } : {}) }).toString();
export const getCoach = (scope: CoachScope, planId?: string | null, signal?: AbortSignal) => learningRequest<CoachView>(`${base}?${scoped(scope, planId)}`, { signal });
export const getCoachSettings = (signal?: AbortSignal) => learningRequest<CoachSettings>(`${base}/settings`, { signal });
export const saveCoachSettings = (value: Omit<CoachSettings, 'revision'> & { expected_revision: number; request_key: string }) => learningRequest<CoachSettings>(`${base}/settings`, { method: 'PUT', body: JSON.stringify(value) });
export const checkCoach = (value: { scope: CoachScope; plan_id?: string; trigger: 'manual' | 'return' | 'boundary'; request_key: string; retry_run_id?: string; permission_candidate_id?: string; permission_request_id?: string }) => learningRequest<{ view: CoachView; run: CoachRun | null; reason: string | null }>(`${base}/checks`, { method: 'POST', body: JSON.stringify(value) });
export const getCoachRun = (id: string, signal?: AbortSignal) => learningRequest<CoachRunDetail>(`${base}/checks/${encodeURIComponent(id)}`, { signal });
export const cancelCoachRun = (run: CoachRun, requestKey: string) => learningRequest<CoachRunDetail>(`${base}/checks/${encodeURIComponent(run.id)}/cancel`, { method: 'POST', body: JSON.stringify({ expected_revision: run.revision, request_key: requestKey }) });
export const purgeCoachRun = (run: CoachRun, requestKey: string) => learningRequest<CoachRunDetail>(`${base}/checks/${encodeURIComponent(run.id)}/purge`, { method: 'POST', body: JSON.stringify({ expected_revision: run.revision, request_key: requestKey, confirmation: 'PURGE' }) });
export const decideCoachCandidate = (id: string, value: CoachDecision) => learningRequest<{ candidate: CoachCandidate; navigation: CoachTarget | null }>(`${base}/candidates/${encodeURIComponent(id)}/decisions`, { method: 'POST', body: JSON.stringify(value) });
export const getCoachCandidate = (id: string, signal?: AbortSignal) => learningRequest<CoachCandidate>(`${base}/candidates/${encodeURIComponent(id)}`, { signal });
export const getCoachSignals = (scope: CoachScope, planId?: string | null, signal?: AbortSignal) => learningRequest<{ items: CoachSignal[] }>(`${base}/signals?${scoped(scope, planId)}`, { signal });
export const correctCoachSignal = (item: CoachSignal, operation: 'exclude' | 'restore', requestKey: string) => learningRequest<CoachSignal>(`${base}/signals/${encodeURIComponent(item.id)}/corrections`, { method: 'POST', body: JSON.stringify({ operation, expected_revision: item.revision, request_key: requestKey }) });

/** Only the existing workspace destinations are actionable, even if a response is malformed. */
export function coachHref(href: string | null | undefined, candidateId?: string): string | null {
  if (!href || !/^(\?|\/\?)/.test(href)) return null;
  const url = new URL(href, window.location.href);
  if (url.origin !== window.location.origin || url.pathname !== window.location.pathname) return null;
  if (!['home', 'plans', 'records'].includes(url.searchParams.get('view') ?? '')) return null;
  if (candidateId) url.searchParams.set('coach_candidate', candidateId);
  return `${url.pathname}${url.search}${url.hash}`;
}

export function navigateCoach(href: string): void {
  const target = coachHref(href);
  if (target) window.dispatchEvent(new CustomEvent('nautilus:coach-navigate', { detail: { href: target } }));
}
