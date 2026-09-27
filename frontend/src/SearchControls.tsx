import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, Globe2, Search, Settings2, Sparkles, X } from 'lucide-react';
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
export default function SearchControls({ value, onChange, disabled, providerKind, onOpenSettings, onReset, overridden, publicQuery = '', onPublicQueryChange }: { value: SearchSelection; onChange: (value: SearchSelection) => void; disabled?: boolean; providerKind?: string; onOpenSettings?: () => void; onReset?: () => void; overridden?: boolean; publicQuery?: string; onPublicQueryChange?: (value: string) => void }) {
  const [services, setServices] = useState<SearchService[]>([]);
  const [catalog, setCatalog] = useState<SearchCatalogItem[]>([]);
  const [defaultId, setDefaultId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ left: number; bottom: number } | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const lastExternalId = useRef<string | undefined>(undefined);
  const lastExternalParameters = useRef<Record<string, unknown> | undefined>(undefined);
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
  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);
  useEffect(() => {
    if (!open) return;
    const updatePosition = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (rect) setPosition({ left: Math.max(16, Math.min(rect.left, window.innerWidth - 376)), bottom: window.innerHeight - rect.top + 8 });
    };
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);
    return () => { window.removeEventListener('resize', updatePosition); window.removeEventListener('scroll', updatePosition, true); };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    panelRef.current?.focus();
    const onPointerDown = (event: PointerEvent) => {
      if (!panelRef.current?.contains(event.target as Node) && !triggerRef.current?.contains(event.target as Node)) {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setOpen(false); triggerRef.current?.focus(); }
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => { document.removeEventListener('pointerdown', onPointerDown); document.removeEventListener('keydown', onKeyDown); };
  }, [open]);
  const close = () => { setOpen(false); triggerRef.current?.focus(); };
  const toggle = () => {
    if (open) { close(); return; }
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) setPosition({ left: Math.max(16, Math.min(rect.left, window.innerWidth - 376)), bottom: window.innerHeight - rect.top + 8 });
    setOpen(true);
  };
  const changeMode = (mode: SearchSelection['mode']) => {
    if (value.mode === 'external') { lastExternalId.current = value.service_id; lastExternalParameters.current = value.parameters; }
    if (mode === 'off' || mode === 'native') { onChange({ mode }); close(); return; }
    const serviceId = value.mode === 'external' ? value.service_id : lastExternalId.current ?? defaultId ?? undefined;
    onChange({ mode: 'external', service_id: serviceId, parameters: serviceId === lastExternalId.current ? lastExternalParameters.current : undefined });
    if (serviceId && services.some((entry) => entry.id === serviceId)) close();
  };
  const chooseService = (id: string) => {
    onChange({ mode: 'external', service_id: id, parameters: id === value.service_id ? value.parameters : undefined });
    lastExternalId.current = id;
    lastExternalParameters.current = id === value.service_id ? value.parameters : undefined;
    setAdvanced(false);
    close();
  };
  const triggerLabel = value.mode === 'off' ? '联网搜索：关闭' : value.mode === 'native' ? '联网搜索：模型内置' : `联网搜索：${service?.name ?? '请选择服务'}`;
  return <div className="search-controls">
    <button ref={triggerRef} type="button" className={`search-picker-trigger ${value.mode !== 'off' ? 'is-active' : ''}`} aria-label={triggerLabel} title={triggerLabel} aria-haspopup="dialog" aria-expanded={open} disabled={disabled} onClick={toggle}>
      {value.mode === 'native' ? <Sparkles size={17} /> : value.mode === 'external' ? <Globe2 size={17} /> : <Search size={17} />}
    </button>
    {open && createPortal(<div className="search-picker-layer"><div ref={panelRef} className="search-picker-panel" style={window.innerWidth > 700 && position ? position : undefined} role="dialog" aria-label="联网搜索选择" tabIndex={-1}>
      <div className="search-picker-header"><strong>联网搜索</strong><div><button type="button" className="search-picker-icon-button" aria-label="搜索设置" onClick={() => { close(); onOpenSettings ? onOpenSettings() : window.dispatchEvent(new Event('nautilus:open-search-settings')); }}><Settings2 size={17} /></button><button type="button" className="search-picker-icon-button" aria-label="关闭搜索选择" onClick={close}><X size={18} /></button></div></div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {onReset && <p className="form-hint">{overridden ? '当前对话已单独设置' : '沿用设置页默认值'}{overridden && <button type="button" className="text-button" onClick={() => { onReset(); close(); }}>恢复默认</button>}</p>}
      {value.mode === 'native' && !nativeAllowed && <p className="form-error">当前模型不支持内置搜索，请选择其他联网方式或关闭。</p>}
      <div className="search-picker-options" role="group" aria-label="本轮搜索模式">
        <button type="button" className={value.mode === 'off' ? 'is-active' : ''} onClick={() => changeMode('off')}><Search size={17} /><span><strong>关闭</strong><small>不使用联网搜索</small></span>{value.mode === 'off' && <Check size={16} />}</button>
        <button type="button" className={value.mode === 'external' ? 'is-active' : ''} onClick={() => changeMode('external')}><Globe2 size={17} /><span><strong>外部服务</strong><small>{value.mode === 'external' ? service?.name ?? '请选择服务' : services.find((entry) => entry.id === (lastExternalId.current ?? defaultId))?.name ?? '选择已配置服务'}</small></span>{value.mode === 'external' && <Check size={16} />}</button>
        <button type="button" className={value.mode === 'native' ? 'is-active' : ''} disabled={!nativeAllowed} title={nativeAllowed ? '' : '当前模型提供方未接入内置搜索'} onClick={() => changeMode('native')}><Sparkles size={17} /><span><strong>模型内置</strong><small>{nativeAllowed ? '由当前模型决定是否调用' : '当前模型不可用'}</small></span>{value.mode === 'native' && <Check size={16} />}</button>
      </div>
      {value.mode === 'external' && onPublicQueryChange && <label className="field search-public-query"><span>公开检索词（可选，仅下一次发送）</span><textarea rows={2} value={publicQuery} disabled={disabled} onChange={event => onPublicQueryChange(event.target.value)} placeholder="输入可公开发送的准确检索词" /><small className="form-hint">这条检索词会发送给所选外部服务，并读取其返回的公开页面。AI 后续提出其他词或参数时，仍会请你确认。</small></label>}
      {(value.mode === 'external' || !services.length) && <div className="search-picker-services"><div className="search-picker-section-title"><strong>搜索服务</strong>{service && <span>当前：{service.name}</span>}</div>
        {value.mode === 'external' && value.service_id && !service && <p className="form-error">所选服务已不存在，请重新选择。</p>}
        {services.length ? <div className="search-picker-service-list">{services.map((item) => <button type="button" key={item.id} className={item.id === value.service_id ? 'is-active' : ''} onClick={() => chooseService(item.id)}>{item.name}{item.id === value.service_id && <Check size={15} />}</button>)}</div> : <p className="form-hint">还没有配置搜索服务。请打开搜索设置添加。</p>}
        {service && definition && <div className="search-picker-advanced"><button className="search-text-toggle" type="button" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}>{advanced ? '收起高级参数' : '展开高级参数'}</button>{advanced && <Parameters schema={definition.search_parameters} value={value.parameters ?? {}} onChange={(parameters) => { onChange({ ...value, parameters }); lastExternalParameters.current = parameters; }} disabled={disabled} />}</div>}
      </div>}
    </div></div>, document.body)}
  </div>;
}
