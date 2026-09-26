export type SearchField = {
  key: string; label: string; type: 'text' | 'secret' | 'number' | 'select' | 'textarea' | 'boolean';
  default?: unknown; required?: boolean; options?: Array<{ value: string; label: string }>;
  min?: number; max?: number;
  description?: string; example?: string;
};
export type SearchParameterSchema = {
  type?: string; properties?: Record<string, SearchParameterSchema>;
  required?: string[]; description?: string; title?: string;
  enum?: Array<string | number | boolean>; default?: unknown;
  items?: SearchParameterSchema; minimum?: number; maximum?: number;
};
export type SearchCatalogItem = {
  kind: string; label: string; homepage: string; description: string; supports_scrape: boolean;
  fields: SearchField[]; search_parameters?: SearchParameterSchema | null;
  scrape_parameters?: SearchParameterSchema | null;
};
export type SearchService = {
  id: string; kind: string; name: string; options: Record<string, unknown>;
  has_secrets: Record<string, boolean>; masked_secrets: Record<string, string>;
};
export type SearchServiceDraft = SearchService & { secret_updates?: Record<string, string | null> };
export type SearchSettingsData = {
  revision: number; services: SearchService[]; selected_service_id: string | null;
  result_size: number; timeout_seconds: number; max_requests: number;
};
export type SearchSettingsDraft = Omit<SearchSettingsData, 'services'> & { services: SearchServiceDraft[] };
export type SearchResult = {
  answer?: string | null;
  items?: Array<{ title: string; url: string; text?: string | null; published_date?: string | null }>;
  images?: Array<string | { url: string; title?: string }>;
  url?: string; content?: string; metadata?: Record<string, unknown>;
  urls?: Array<{ url: string; content: string; metadata?: Record<string, unknown> }>; retrieved_at?: string;
};
export type SearchTestResponse = { ok: boolean; result?: SearchResult; kind?: string; message?: string };
export class SearchApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}
async function searchRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      credentials: 'include',
      headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
    });
  } catch {
    throw new SearchApiError('无法连接搜索服务，请检查本地服务状态。', 0);
  }
  if (!response.ok) {
    const message = response.status === 401 ? '请先完成本地授权。'
      : response.status === 409 ? '搜索设置已在其他页面更新。请保留当前编辑并刷新后重试。'
      : response.status === 400 || response.status === 422 ? '搜索设置无效，请检查必填字段和数值范围。'
      : response.status === 429 ? '搜索请求过于频繁，请稍后重试。'
      : `搜索服务请求失败（${response.status}）。`;
    throw new SearchApiError(message, response.status);
  }
  try { return await response.json() as T; }
  catch { throw new SearchApiError('搜索服务返回了无法读取的结果。', response.status); }
}
export const getSearchCatalog = () => searchRequest<SearchCatalogItem[]>('/api/search/catalog');
export const getSearchSettings = () => searchRequest<SearchSettingsData>('/api/search/settings');
export const putSearchSettings = (draft: SearchSettingsDraft) => searchRequest<SearchSettingsData>('/api/search/settings', { method: 'PUT', body: JSON.stringify(draft) });
export const testSearchService = (service: SearchServiceDraft, query: string, parameters?: Record<string, unknown>) =>
  searchRequest<SearchTestResponse>('/api/search/test', { method: 'POST', body: JSON.stringify({ service, query, parameters }) });
export const testSearchScrape = (service: SearchServiceDraft, urls: string[], parameters?: Record<string, unknown>) =>
  searchRequest<SearchTestResponse>('/api/search/scrape', { method: 'POST', body: JSON.stringify({ service, urls, parameters }) });
