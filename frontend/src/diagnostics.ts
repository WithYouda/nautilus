export type DiagnosticStatus = { enabled: boolean; storage_error: boolean; retention_bytes: number };
export type DiagnosticEntry = {
  id: string;
  at: string;
  level: 'info' | 'warning' | 'error';
  module: string;
  event: string;
  request_id?: string;
  method?: string;
  route?: string;
  status?: number;
  duration_ms?: number;
  code?: string;
  result?: string;
  failed_count?: number;
  cleared_count?: number;
  source?: string;
  line?: number;
  run_id?: string;
  scope_kind?: 'conversation' | 'discussion';
  phase?: 'initial_response' | 'tool_continuation' | 'history_selection' | 'title' | 'provider_request';
  provider_kind?: string;
  target_host?: string;
  request_seq?: number;
  attempt?: number;
  max_attempts?: number;
  retry_delay_ms?: number;
  error_stage?: string;
  error_type?: string;
  cause_type?: string;
  errno?: number;
};
export type DiagnosticPage = DiagnosticStatus & { entries: DiagnosticEntry[] };
async function diagnosticRequest<T>(path = '', init?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(`/api/diagnostics${path}`, { ...init, credentials: 'include', cache: 'no-store', headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}) } }); }
  catch { throw new Error('诊断日志暂时无法连接，请重试。'); }
  if (!response.ok) throw new Error('诊断日志操作未完成，请重试。');
  return response.json();
}
export const getDiagnosticStatus = () => diagnosticRequest<DiagnosticStatus>('/settings');
export const getDiagnosticEntries = () => diagnosticRequest<DiagnosticPage>();
export async function setDiagnosticEnabled(enabled: boolean) {
  const value = await diagnosticRequest<DiagnosticStatus>('/settings', { method: 'PUT', body: JSON.stringify({ enabled }) });
  window.dispatchEvent(new CustomEvent('nautilus:diagnostics-changed', { detail: value }));
  return value;
}
export const clearDiagnostics = () => diagnosticRequest<{ cleared: boolean }>('', { method: 'DELETE' });
