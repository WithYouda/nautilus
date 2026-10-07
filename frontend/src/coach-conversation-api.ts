import { learningRequest, type AiConversationDetail, type PurgeReport } from './api';
import { coachKey, type CoachTarget } from './background-coach-api';

export { coachKey };
export const COACH_SESSION_KEY = 'nautilus.ai.coach-room';
export type CoachConversationInfo = { conversation_id: string; role: 'coach'; role_version: number; created_at: string; updated_at: string; purged_at: string | null };
export type CoachAction = { id: string; label: string; target: CoachTarget; source_revision: string; available: boolean; reason: string | null };
export type CoachMessageContext = { role: 'coach'; schema_version: 1; source_revision: string; actions: CoachAction[]; unknowns: string[]; content_available: boolean };
export type CoachConversationDetail = AiConversationDetail & { coach: CoachConversationInfo; coach_context: { source_revision: string; summary: string; actions: CoachAction[] } };
export type CoachReminderSettings = { revision: number; enabled: boolean; timezone: string; browser_enabled: boolean; study_times: Array<{ id: string; weekdays: number[]; time: string }>; followup_enabled: boolean; followup_delay_minutes: number; max_per_day: number; quiet_enabled: boolean; quiet_start: string; quiet_end: string };
export type CoachReminderTarget = { kind: 'commitment_item' | 'coach' | 'commitment_review'; plan_id: string | null; action_id: string | null; delegation_id: string | null; item_id: string | null; href: string; label: string };
export type CoachReminder = { id: string; revision: number; occurrence_key: string; stage: 'initial' | 'followup' | 'quiet_digest'; status: 'pending' | 'dispatched' | 'suppressed' | 'unavailable'; title: string; body: string; target: CoachReminderTarget; scheduled_at: string; dispatched_at: string | null; source_revision: string; reason: string | null };
export type CoachReminderView = { settings: CoachReminderSettings; due: CoachReminder[]; recent: CoachReminder[]; learning_active: boolean; quiet_now: boolean; budget: { used_today: number; remaining_today: number; local_date: string }; next_due_at: string | null; revision: string };
export type CoachReminderDispatch = { reminder: CoachReminder | null; claimed: boolean; reason: string | null; view: CoachReminderView };
const base = '/api/learning/coach';
export const listCoachConversations = (signal?: AbortSignal) => learningRequest<{ items: CoachConversationInfo[] }>(`${base}/conversations`, { signal });
export const openCoachConversation = (request_key: string, new_conversation = false) => learningRequest<CoachConversationDetail>(`${base}/conversations`, { method: 'POST', body: JSON.stringify({ request_key, new_conversation }) });
export const getCoachConversation = (id: string, signal?: AbortSignal) => learningRequest<CoachConversationDetail>(`${base}/conversations/${encodeURIComponent(id)}`, { signal });
export const resolveCoachAction = (id: string, action: CoachAction) => learningRequest<{ target: CoachTarget }>(`${base}/conversations/${encodeURIComponent(id)}/actions/${encodeURIComponent(action.id)}/resolve`, { method: 'POST', body: JSON.stringify({ source_revision: action.source_revision }) });
export const purgeCoachConversation = (id: string, request_key: string) => learningRequest<{ coach: CoachConversationInfo; purge_report: PurgeReport }>(`${base}/conversations/${encodeURIComponent(id)}/purge`, { method: 'POST', body: JSON.stringify({ confirm: true, request_key }) });
export const getCoachConversationPurge = (id: string) => learningRequest<{ purge_report: PurgeReport; impact: { conversations: number; messages: number; runs: number } }>(`${base}/conversations/${encodeURIComponent(id)}/purge`);
export const getCoachReminderSettings = () => learningRequest<CoachReminderSettings>(`${base}/reminders/settings`);
export const saveCoachReminderSettings = (fields: Omit<CoachReminderSettings, 'revision'> & { expected_revision: number; request_key: string }) => learningRequest<{ settings: CoachReminderSettings }>(`${base}/reminders/settings`, { method: 'PUT', body: JSON.stringify(fields) });
export const getCoachReminders = (signal?: AbortSignal) => learningRequest<CoachReminderView>(`${base}/reminders`, { signal });
export const dispatchCoachReminder = (item: CoachReminder, request_key: string) => learningRequest<CoachReminderDispatch>(`${base}/reminders/${encodeURIComponent(item.id)}/dispatch`, { method: 'POST', body: JSON.stringify({ expected_revision: item.revision, request_key }) });
export const resolveCoachReminder = (item: CoachReminder) => learningRequest<{ target: CoachReminderTarget }>(`${base}/reminders/${encodeURIComponent(item.id)}/resolve`, { method: 'POST', body: JSON.stringify({ source_revision: item.source_revision }) });

export function browserNotificationState(): 'unsupported' | NotificationPermission {
  return !window.isSecureContext || !('Notification' in window) ? 'unsupported' : Notification.permission;
}

export const getCoachReminderHistory = (before?: number) => learningRequest<{ items: CoachReminder[]; next_before: number | null }>(`${base}/reminders/history${before === undefined ? "" : `?before=${before}`}`);
