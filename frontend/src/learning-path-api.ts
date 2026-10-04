import { learningRequest, type PurgeReport } from './api';

export type LearningPathNode = { id: string; title: string; action_ids: string[]; outcome_ids: string[] };
export type LearningPathEdge = { source: string; target: string };
export type PathIntent = 'create' | 'change_entry' | 'change_scope' | 'change_direction' | 'restore' | 'undo';
export type PathCheckpoint = {
  node_id: string;
  action_id: string | null;
  delegation_id: string | null;
  session_id: string | null;
  anchor?: Record<string, unknown> | null;
  available?: boolean;
  precision?: 'answer' | 'conversation' | 'task';
};
export type LearningPathVersion = {
  id: string;
  route_id: string;
  previous_version_id: string | null;
  parent_version_id: string | null;
  branch_node_id: string | null;
  title: string;
  nodes: LearningPathNode[];
  edges: LearningPathEdge[];
  entry_node_id: string;
  current_node_id: string;
  created_at: string;
  content_available: boolean;
  checkpoint?: PathCheckpoint | null;
};
export type LearningPathDraft = {
  id: string;
  revision: number;
  intent: PathIntent;
  title: string;
  nodes: LearningPathNode[];
  edges: LearningPathEdge[];
  entry_node_id: string;
  current_node_id: string;
  source_version_id: string | null;
  restore_version_id: string | null;
  parent_version_id?: string | null;
  branch_node_id?: string | null;
  reason?: string | null;
  stale: boolean;
  content_available: boolean;
};
export type LearningPathView = {
  plan_id: string;
  revision: number;
  organization_revision: number;
  adopted_version_id: string | null;
  current_node_id: string | null;
  status: 'active' | 'paused';
  versions: LearningPathVersion[];
  drafts: LearningPathDraft[];
  purge_retry_ids?: string[];
  transfers?: Array<{ source_plan_id: string; destination_plan_id: string; destination_version_id: string; version_id: string; node_id: string; pause_original: boolean; created_at: string; checkpoint: PathCheckpoint | null }>;
  decisions: Array<{ id: string; intent: PathIntent; version_id: string; previous_version_id: string | null; node_id: string; previous_node_id: string | null; reason: string | null; created_at: string }>;
};
export type LearningPathDraftInput = {
  title: string;
  nodes: LearningPathNode[];
  edges: LearningPathEdge[];
  entry_node_id: string;
  current_node_id: string;
  reason: string;
  expected_revision: number;
  expected_organization_revision: number;
  intent: Exclude<PathIntent, 'restore' | 'undo'>;
  draft_id?: string | null;
  expected_draft_revision?: number;
  source_version_id?: string | null;
  restore_version_id?: string | null;
  request_key: string;
};
export type LearningPathPreview = {
  review_key: string;
  revision: number;
  draft_revision: number;
  intent: PathIntent;
  affected_sessions: Array<{ id: string; action_id: string; action_title: string }>;
  checkpoint: PathCheckpoint | null;
  draft: LearningPathDraft;
  commitment_changes: PathCommitmentChange[];
};
export type PathCommitmentChange = { item_id: string; action_title: string; kind: 'keep' | 'defer'; executed: boolean; completed: boolean; skip_preserved: boolean; from_node_id: string | null; to_node_id: string | null; reason_code: string };
export type PathTransferInput = Pick<LearningPathDraftInput, 'title' | 'nodes' | 'edges' | 'entry_node_id' | 'current_node_id' | 'reason' | 'expected_revision' | 'expected_organization_revision'> & {
  destination_title: string;
  destination_description: string;
  pause_original: boolean;
};
export type PathTransferPreview = {
  review_key: string; revision: number; organization_revision: number;
  affected_sessions: LearningPathPreview['affected_sessions']; checkpoint: PathCheckpoint | null;
  destination_title: string; pause_original: boolean;
  commitment_changes?: PathCommitmentChange[];
};
export type PathTransferResult = { plan_id: string; source_path: LearningPathView; path: LearningPathView };

const path = (planId: string) => `/api/learning/plans/${encodeURIComponent(planId)}/path`;
const post = <T>(url: string, body: unknown) => learningRequest<T>(url, { method: 'POST', body: JSON.stringify(body) });
export function getLearningPath(planId: string): Promise<LearningPathView> {
  return learningRequest(path(planId), { cache: 'no-store' });
}
export function saveLearningPathDraft(planId: string, payload: LearningPathDraftInput): Promise<LearningPathView & { draft_id: string }> {
  return post(`${path(planId)}/drafts`, payload);
}
export function previewLearningPath(planId: string, draftId: string): Promise<LearningPathPreview> {
  return post(`${path(planId)}/previews`, { draft_id: draftId });
}
export function decideLearningPath(planId: string, payload: { draft_id: string; expected_draft_revision: number; expected_revision: number; review_key: string; request_key: string }): Promise<LearningPathView> {
  return post(`${path(planId)}/decisions`, payload);
}
export function restoreLearningPathDraft(planId: string, payload: { version_id: string; node_id?: string; intent: 'restore' | 'undo'; expected_revision: number; expected_organization_revision: number; reason: string; request_key: string }): Promise<LearningPathView & { draft_id: string }> {
  return post(`${path(planId)}/restore-draft`, payload);
}
export function startLearningPathTask(planId: string, payload: { version_id: string; node_id: string; delegation_id: string; expected_action_version: number; expected_revision: number; use_checkpoint: boolean; request_key: string }): Promise<{ session_id: string; revision: number; path_anchor?: Record<string, unknown> }> {
  return post(`${path(planId)}/start`, payload);
}
export function purgeLearningPathVersion(planId: string, versionId: string, revision: number, requestKey: string): Promise<{ path: LearningPathView; purge_report: PurgeReport }> {
  return post(`${path(planId)}/versions/${encodeURIComponent(versionId)}/purge`, { expected_revision: revision, confirmation: 'PURGE', request_key: requestKey });
}
export function getLearningPathPurgeStatus(planId: string, versionId: string): Promise<PurgeReport> {
  return learningRequest(`${path(planId)}/versions/${encodeURIComponent(versionId)}/purge-status`, { cache: 'no-store' });
}
export function previewPathTransfer(planId: string, payload: PathTransferInput): Promise<PathTransferPreview> {
  return post(`${path(planId)}/transfer-preview`, payload);
}
export function confirmPathTransfer(planId: string, payload: PathTransferInput & { review_key: string; request_key: string }): Promise<PathTransferResult> {
  return post(`${path(planId)}/transfer`, payload);
}
