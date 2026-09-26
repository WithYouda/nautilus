import type { SearchSelection } from './SearchControls';

export type ConflictPolicy = 'ask' | 'balanced' | 'materials';
export type UserPreferences = { conflict_policy: ConflictPolicy; search: Pick<SearchSelection, 'mode' | 'service_id' | 'parameters'> };

async function preferencesRequest(init?: RequestInit): Promise<UserPreferences> {
  let response: Response;
  try {
    response = await fetch('/api/preferences', {
      ...init,
      credentials: 'include',
      headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
    });
  } catch {
    throw new Error('无法连接本地服务，请检查服务状态。');
  }
  const body = await response.json().catch(() => null) as { detail?: string } | UserPreferences | null;
  if (!response.ok) throw new Error(body && 'detail' in body && typeof body.detail === 'string' ? body.detail : `学习设置请求失败（${response.status}）。`);
  if (!body || !('conflict_policy' in body) || !('search' in body)) throw new Error('学习设置返回了无法读取的结果。');
  return body as UserPreferences;
}

export const getPreferences = () => preferencesRequest();
export async function savePreferences(value: UserPreferences): Promise<UserPreferences> {
  const saved = await preferencesRequest({ method: 'PUT', body: JSON.stringify(value) });
  window.dispatchEvent(new CustomEvent<UserPreferences>('nautilus:preferences-changed', { detail: saved }));
  return saved;
}
