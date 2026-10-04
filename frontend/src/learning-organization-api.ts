import { learningRequest, type PurgeReport } from './api';

export type PlanOrganizationChild = {
  kind: 'module' | 'task';
  id: string;
  parent_module_id: string | null;
  position: number;
};
export type PlanOrganizationModule = {
  id: string;
  title: string;
  description: string;
  parent_module_id: string | null;
  position: number;
  status: string;
  can_purge_content?: boolean;
  content_available?: boolean;
};
export type PlanOrganization = {
  plan: { id: string; title: string; description: string; goal_id: string | null; status: string; can_purge_content?: boolean; content_available?: boolean };
  revision: number;
  modules: PlanOrganizationModule[];
  children: PlanOrganizationChild[];
  tasks: Array<{ id: string; title: string; status: string }>;
};
export type OrganizationWriteResult = { organization: PlanOrganization; object_id: string };
export type OrganizationVersion = { expected_revision: number; request_key: string };
export type PlanModuleInput = OrganizationVersion & {
  title: string;
  description: string;
  parent_module_id: string | null;
};
export type PlanTaskInput = OrganizationVersion & {
  action_title: string;
  context_key: string;
  object_description: string;
  behavior: string;
  outcome_context_key: string;
  outcome_id: string | null;
  criterion_id: string | null;
  boundaries: string;
  stop_conditions: string;
  time_budget_minutes: number | null;
};

const planPath = (id: string) => `/api/learning/plans/${encodeURIComponent(id)}`;
const post = <T>(path: string, payload: unknown) => learningRequest<T>(path, { method: 'POST', body: JSON.stringify(payload) });

export function organizationRequestKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
export function getPlanOrganization(planId: string): Promise<PlanOrganization> {
  return learningRequest(`${planPath(planId)}/organization`, { cache: 'no-store' });
}
export function createLearningPlan(payload: { title: string; description: string; goal_id: string | null; request_key: string }): Promise<{ plan_id: string; organization: PlanOrganization }> {
  return post('/api/learning/plans', payload);
}
export function createPlanModule(planId: string, payload: PlanModuleInput): Promise<OrganizationWriteResult> {
  return post(`${planPath(planId)}/modules`, payload);
}
export function revisePlanModule(planId: string, moduleId: string, payload: PlanModuleInput): Promise<OrganizationWriteResult> {
  return post(`${planPath(planId)}/modules/${encodeURIComponent(moduleId)}/revise`, payload);
}
export function placePlanTask(planId: string, actionId: string, payload: OrganizationVersion & { module_id: string | null }): Promise<OrganizationWriteResult> {
  return post(`${planPath(planId)}/tasks/${encodeURIComponent(actionId)}/placement`, payload);
}
export function reorderPlanChildren(planId: string, payload: OrganizationVersion & { parent_module_id: string | null; children: Array<{ kind: 'module' | 'task'; id: string }> }): Promise<OrganizationWriteResult> {
  return post(`${planPath(planId)}/children-order`, payload);
}
export function createPlanTask(planId: string, payload: PlanTaskInput): Promise<{ plan_id: string; action_id: string; outcome_id: string; delegation_id: string; revision: number }> {
  return post(`${planPath(planId)}/tasks`, payload);
}
function contentPath(planId: string, moduleId: string | null) {
  return moduleId ? `${planPath(planId)}/modules/${encodeURIComponent(moduleId)}/content` : `${planPath(planId)}/organization-content`;
}
export function purgePlanOrganizationContent(planId: string, moduleId: string | null, payload: OrganizationVersion): Promise<OrganizationWriteResult & { purge_report: PurgeReport }> {
  return post(`${contentPath(planId, moduleId)}/purge`, { ...payload, confirmation: 'PURGE' });
}
export function getPlanOrganizationPurgeStatus(planId: string, moduleId: string | null): Promise<PurgeReport> {
  return learningRequest(`${contentPath(planId, moduleId)}/purge-status`, { cache: 'no-store' });
}
