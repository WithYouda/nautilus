import { useEffect, useMemo, useState } from 'react';
import { getSearchCatalog, getSearchSettings, type SearchCatalogItem, type SearchParameterSchema, type SearchService } from './searchApi';

export type SearchSelection = { mode: 'off' | 'external' | 'native'; service_id?: string; query?: string; parameters?: Record<string, unknown> };
const nativeKinds = new Set(['google', 'openai_responses', 'anthropic']);
const label = (schema: SearchParameterSchema, key: string) => schema.title || key;
function Parameters({ schema, value, onChange, disabled }: { schema?: SearchParameterSchema | null; value: Record<string, unknown>; onChange: (value: Record<string, unknown>) => void; disabled?: boolean }) {
  const entries = Object.entries(schema?.properties ?? {}).filter(([key]) => !['query', 'url', 'urls'].includes(key));
  if (!entries.length) return <p className="form-hint">此服务没有额外搜索参数。</p>;
  return <div className="search-parameter-grid">{entries.map(([key, definition]) => {
    const raw = value[key] ?? definition.default;
    const update = (next: unknown) => { const copy = { ...value }; if (next === '' || next === undefined) delete copy[key]; else copy[key] = next; onChange(copy); };
    const type = Array.isArray(definition.type) ? definition.type.find((x) => x !== 'null') : definition.type;
    return <label className="field" key={key}><span>{label(definition, key)}{schema?.required?.includes(key) ? ' *' : ''}</span>
      {definition.enum ? <select disabled={disabled} value={String(raw ?? '')} onChange={(event) => update(event.target.value)}><option value="">使用默认值</option>{definition.enum.map((option) => <option key={String(option)} value={String(option)}>{String(option)}</option>)}</select>
        : type === 'boolean' ? <select disabled={disabled} value={raw === undefined ? '' : String(raw)} onChange={(event) => update(event.target.value === '' ? '' : event.target.value === 'true')}><option value="">使用默认值</option><option value="true">是</option><option value="false">否</option></select>
        : type === 'array' ? <textarea disabled={disabled} value={Array.isArray(raw) ? raw.join('\n') : ''} onChange={(event) => update(event.target.value.trim() ? event.target.value.split(/[\n,]/).map((x) => x.trim()).filter(Boolean) : '')} placeholder="每行一个值" rows={3} />
        : <input disabled={disabled} type={type === 'integer' || type === 'number' ? 'number' : 'text'} min={definition.minimum} max={definition.maximum} step={type === 'integer' ? 1 : 'any'} value={raw == null ? '' : String(raw)} onChange={(event) => update(event.target.value === '' ? '' : type === 'integer' || type === 'number' ? Number(event.target.value) : event.target.value)} />}
      {definition.description && <small className="form-hint">{definition.description}</small>}
    </label>;
  })}</div>;
}
export { Parameters as SearchParameters };
export default function SearchControls({ value, onChange, disabled, providerKind, onOpenSettings }: { value: SearchSelection; onChange: (value: SearchSelection) => void; disabled?: boolean; providerKind?: string; onOpenSettings?: () => void }) {
  const [services, setServices] = useState<SearchService[]>([]);
  const [catalog, setCatalog] = useState<SearchCatalogItem[]>([]);
  const [defaultId, setDefaultId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [externalDraft, setExternalDraft] = useState<Pick<SearchSelection, 'service_id' | 'query' | 'parameters'>>({});
  useEffect(() => {
    let active = true;
    const load = async () => {
      try { const [settings, kinds] = await Promise.all([getSearchSettings(), getSearchCatalog()]); if (active) { setServices(settings.services); setCatalog(kinds); setDefaultId(settings.selected_service_id); setError(''); } }
      catch { if (active) setError('无法读取搜索服务设置。'); }
    };
    void load(); window.addEventListener('nautilus:search-settings-changed', load);
    return () => { active = false; window.removeEventListener('nautilus:search-settings-changed', load); };
  }, []);
  const selectedId = value.service_id ?? defaultId ?? '';
  const service = services.find((entry) => entry.id === selectedId);
  const definition = useMemo(() => catalog.find((entry) => entry.kind === service?.kind), [catalog, service?.kind]);
  const nativeAllowed = nativeKinds.has(providerKind ?? '');
  useEffect(() => { if (value.mode === 'native' && !nativeAllowed) onChange({ mode: 'off' }); }, [nativeAllowed, value.mode]);
  const changeMode = (mode: SearchSelection['mode']) => {
    if (mode === value.mode) return;
    if (value.mode === 'external') setExternalDraft({ service_id: value.service_id, query: value.query, parameters: value.parameters });
    if (mode === 'off') onChange({ mode });
    if (mode === 'external') onChange({ mode, service_id: externalDraft.service_id ?? value.service_id ?? defaultId ?? undefined, query: externalDraft.query, parameters: externalDraft.parameters });
    if (mode === 'native') onChange({ mode });
  };
  return <div className="search-controls">
    <div className="search-controls-toolbar"><strong>联网搜索</strong>
    <div className="search-mode-options" role="group" aria-label="本轮搜索模式">
      <button type="button" className={value.mode === 'off' ? 'is-active' : ''} disabled={disabled} onClick={() => changeMode('off')}>关闭</button>
      <button type="button" className={value.mode === 'external' ? 'is-active' : ''} disabled={disabled} onClick={() => changeMode('external')}>外部服务</button>
      <button type="button" className={value.mode === 'native' ? 'is-active' : ''} disabled={disabled || !nativeAllowed} title={nativeAllowed ? '' : '当前模型提供方未接入内置搜索'} onClick={() => changeMode('native')}>模型内置</button>
    </div><button className="search-text-toggle" type="button" onClick={() => onOpenSettings ? onOpenSettings() : window.dispatchEvent(new Event('nautilus:open-search-settings'))}>搜索设置</button></div>
    {error && <p className="form-error" role="alert">{error}</p>}
    {value.mode === 'external' && <div className="search-controls-detail">
      <label className="field"><span>搜索服务</span><select disabled={disabled} value={selectedId} onChange={(event) => onChange({ ...value, service_id: event.target.value || undefined, parameters: event.target.value === selectedId ? value.parameters : undefined })}><option value="">选择搜索服务</option>{services.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      {services.length === 0 && <p className="form-hint">还没有配置搜索服务。请先打开搜索设置。</p>}
      {selectedId && !service && <p className="form-error">所选服务已不存在，请重新选择。</p>}
      <label className="field"><span>搜索查询</span><input disabled={disabled} value={value.query ?? ''} onChange={(event) => onChange({ ...value, query: event.target.value })} placeholder="留空则使用当前问题" /></label>
      <p className="form-hint">本轮查询会发送给所选搜索服务。留空时使用当前问题。</p>
      {definition && <><button className="search-text-toggle" type="button" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}>{advanced ? '收起高级参数' : '展开高级参数'}</button>{advanced && <Parameters schema={definition.search_parameters} value={value.parameters ?? {}} onChange={(parameters) => onChange({ ...value, parameters })} disabled={disabled} />}</>}
    </div>}
    {value.mode === 'native' && <p className="form-hint">由当前模型提供方执行内置搜索；是否实际调用会在回复中显示。</p>}
  </div>;
}
