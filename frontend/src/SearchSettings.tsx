import { useEffect, useState, type FormEvent, type DragEvent } from 'react';
import DialogPortal from './DialogPortal';
import SearchResults, { type SearchTrace } from './SearchResults';
import { SearchParameters } from './SearchControls';
import { getSearchCatalog, getSearchSettings, putSearchSettings, testSearchService, testSearchScrape, type SearchCatalogItem, type SearchServiceDraft, type SearchSettingsDraft, type SearchField } from './searchApi';

const initial: SearchSettingsDraft = { revision: 0, services: [], selected_service_id: null, result_size: 10, timeout_seconds: 30, max_requests: 1 };
const limitFields = [{ key: 'result_size', label: '结果数', min: 1, max: 50 }, { key: 'timeout_seconds', label: '超时秒数', min: 5, max: 120 }, { key: 'max_requests', label: '每轮外部检索次数', min: 1, max: 5 }] as const;
function newServiceId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
const fresh = (item: SearchCatalogItem): SearchServiceDraft => ({ id: newServiceId(), kind: item.kind, name: item.label, options: Object.fromEntries(item.fields.filter(field => field.type !== 'secret').map(field => [field.key, field.default ?? (field.type === 'boolean' ? false : '')])), has_secrets: {}, masked_secrets: {}, secret_updates: {} });
export default function SearchSettings({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [catalog, setCatalog] = useState<SearchCatalogItem[]>([]);
  const [draft, setDraft] = useState<SearchSettingsDraft>(initial);
  const [baseline, setBaseline] = useState<SearchSettingsDraft>(initial);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [addKind, setAddKind] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [url, setUrl] = useState('');
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  const [scrapeParameters, setScrapeParameters] = useState<Record<string, unknown>>({});
  const [trace, setTrace] = useState<SearchTrace | null>(null);
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [dragId, setDragId] = useState<string | null>(null);
  const selected = draft.services.find(item => item.id === selectedId);
  const definition = catalog.find(item => item.kind === selected?.kind);
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);
  useEffect(() => { setParameters({}); setScrapeParameters({}); setTrace(null); }, [selectedId]);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true); setError('');
    void Promise.all([getSearchCatalog(), getSearchSettings()]).then(([items, settings]) => {
      if (!active) return;
      const next: SearchSettingsDraft = { ...settings, services: settings.services.map(service => ({ ...service, secret_updates: {} })) };
      setCatalog(items); setDraft(structuredClone(next)); setBaseline(structuredClone(next)); setSelectedId(next.services[0]?.id ?? null); setAddKind(items[0]?.kind ?? ''); setTrace(null);
    }).catch(cause => { if (active) setError(cause instanceof Error ? cause.message : '加载搜索设置失败。'); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open]);
  const update = (id: string, change: (service: SearchServiceDraft) => SearchServiceDraft) => setDraft(current => ({ ...current, services: current.services.map(service => service.id === id ? change(service) : service) }));
  const close = () => { if (saving || testing) return; if (dirty && !window.confirm('放弃尚未保存的搜索设置？')) return; setDraft(structuredClone(baseline)); setRevealed({}); setTrace(null); onClose(); };
  const add = () => { const item = catalog.find(entry => entry.kind === addKind); if (!item) return; const service = fresh(item); setDraft(current => ({ ...current, services: [service, ...current.services] })); setSelectedId(service.id); setTrace(null); };
  const remove = (id: string) => { setDraft(current => ({ ...current, services: current.services.filter(service => service.id !== id), selected_service_id: current.selected_service_id === id ? null : current.selected_service_id })); if (selectedId === id) setSelectedId(null); setTrace(null); };
  const move = (id: string, destination: number) => setDraft(current => { const services = [...current.services]; const source = services.findIndex(service => service.id === id); if (source < 0 || destination < 0 || destination >= services.length || source === destination) return current; const [service] = services.splice(source, 1); services.splice(destination, 0, service); return { ...current, services }; });
  const drop = (event: DragEvent, id: string) => { event.preventDefault(); if (dragId) move(dragId, draft.services.findIndex(service => service.id === id)); setDragId(null); };
  const save = async (event: FormEvent) => {
    event.preventDefault(); setError('');
    const invalid = limitFields.find(field => !Number.isInteger(draft[field.key]) || draft[field.key] < field.min || draft[field.key] > field.max);
    if (invalid) { setError(`${invalid.label}须在 ${invalid.min}–${invalid.max} 之间。`); return; }
    for (const service of draft.services) {
      const item = catalog.find(entry => entry.kind === service.kind);
      if (!service.name.trim()) { setSelectedId(service.id); setError(`${item?.label || '服务'}：请填写名称。`); return; }
    }
    setSaving(true);
    try {
      const result = await putSearchSettings(draft);
      const clean: SearchSettingsDraft = { ...result, services: result.services.map(service => ({ ...service, secret_updates: {} })) };
      setDraft(structuredClone(clean)); setBaseline(structuredClone(clean)); setRevealed({});
      window.dispatchEvent(new Event('nautilus:search-settings-changed')); onClose();
    } catch (cause) { setError(cause instanceof Error ? cause.message : '保存失败；当前编辑已保留。'); }
    finally { setSaving(false); }
  };
  const test = async (mode: 'search' | 'scrape') => {
    if (!selected) return;
    if (mode === 'search' && !query.trim()) { setError('请输入测试查询。'); return; }
    const urls = selected.kind === 'custom_js' ? url.split('\n').map(value => value.trim()).filter(Boolean) : [url.trim()];
    if (mode === 'scrape' && (!urls.length || urls.some(value => !/^https?:\/\//i.test(value)))) { setError('请输入 http(s) 网页地址。'); return; }
    setTesting(true); setError(''); setTrace({ mode: 'external', status: 'running', service_name: selected.name, query: mode === 'search' ? query : url });
    try {
      const response = mode === 'search' ? await testSearchService(selected, query.trim(), parameters) : await testSearchScrape(selected, urls, scrapeParameters);
      setTrace({ mode: 'external', status: response.ok ? 'succeeded' : 'failed', service_name: selected.name, query: mode === 'search' ? query : url, message: response.message, answer: response.result?.answer, items: response.result?.items, images: response.result?.images, content: response.result?.content, url: response.result?.url, scraped_urls: response.result?.urls, retrieved_at: response.result?.retrieved_at ?? (response.ok ? new Date().toISOString() : undefined) });
    } catch (cause) { setTrace({ mode: 'external', status: 'failed', service_name: selected.name, message: cause instanceof Error ? cause.message : '测试失败。' }); }
    finally { setTesting(false); }
  };
  const renderField = (field: SearchField, service: SearchServiceDraft) => {
    const value = service.options[field.key] == null ? '' : String(service.options[field.key]);
    const setOption = (next: unknown) => update(service.id, current => ({ ...current, options: { ...current.options, [field.key]: next } }));
    return <label className="field" key={field.key}><span>{field.label}{field.required ? ' *' : ''}</span>
      {field.type === 'secret' ? <><div className="search-secret-row"><input type={revealed[`${service.id}:${field.key}`] ? 'text' : 'password'} autoComplete="off" value={service.secret_updates?.[field.key] ?? ''} placeholder={service.has_secrets[field.key] ? `已保存 ${service.masked_secrets[field.key] ?? '密钥'}；留空保留` : '输入密钥'} onChange={event => update(service.id, current => ({ ...current, secret_updates: { ...current.secret_updates, [field.key]: event.target.value } }))} /><button className="button button--quiet" type="button" onClick={() => setRevealed(current => ({ ...current, [`${service.id}:${field.key}`]: !current[`${service.id}:${field.key}`] }))}>{revealed[`${service.id}:${field.key}`] ? '隐藏' : '显示'}</button>{(service.has_secrets[field.key] || service.secret_updates?.[field.key]) && <button className="button button--quiet" type="button" onClick={() => update(service.id, current => ({ ...current, secret_updates: { ...current.secret_updates, [field.key]: null } }))}>清除</button>}</div>{service.secret_updates?.[field.key] === null && <small className="form-hint">保存后删除密钥。</small>}</>
      : field.type === 'select' ? <select value={value} onChange={event => setOption(event.target.value)}>{field.options?.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
      : field.type === 'boolean' ? <select value={String(service.options[field.key] ?? field.default ?? false)} onChange={event => setOption(event.target.value === 'true')}><option value="true">是</option><option value="false">否</option></select>
      : field.type === 'textarea' ? <textarea rows={5} value={value} placeholder={field.example} onChange={event => setOption(event.target.value)} />
      : <input type={field.type === 'number' ? 'number' : 'text'} min={field.min} max={field.max} value={value} onChange={event => setOption(field.type === 'number' ? event.target.value === '' ? null : Number(event.target.value) : event.target.value)} />}{field.description && <small className="form-hint">{field.description}</small>}{field.key === 'api_key' && <small className="form-hint">可暂不填写；多个密钥用逗号分隔，每轮使用其中一个。</small>}</label>;
  };
  if (!open) return null;
  return <DialogPortal><div className="dialog-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) close(); }}><section className="search-settings-dialog" role="dialog" aria-modal="true" aria-labelledby="search-settings-title">
    <header className="dialog-header"><div><p className="eyebrow">WEB SEARCH</p><h2 id="search-settings-title">联网搜索设置</h2></div><button className="icon-button" type="button" onClick={close} aria-label="关闭搜索设置">×</button></header>
    {loading ? <p className="search-settings-loading">正在加载搜索服务…</p> : <form onSubmit={event => void save(event)}><div className="search-settings-body"><aside className="search-service-list">
      <div className="search-service-add"><select aria-label="新增服务类型" value={addKind} onChange={event => setAddKind(event.target.value)}>{catalog.map(item => <option key={item.kind} value={item.kind}>{item.label}</option>)}</select><button className="button button--quiet" type="button" disabled={!addKind} onClick={add}>新增</button></div>
      {draft.services.length === 0 && <p className="form-hint">还没有搜索服务。可添加任何目录中的服务，同类型可创建多个实例。</p>}
      {draft.services.map((service, index) => { const item = catalog.find(entry => entry.kind === service.kind); return <div key={service.id} className={`search-service-row ${selectedId === service.id ? 'is-selected' : ''}`} draggable onDragStart={() => setDragId(service.id)} onDragEnd={() => setDragId(null)} onDragOver={event => event.preventDefault()} onDrop={event => drop(event, service.id)}><button className="search-service-select" type="button" onClick={() => { setSelectedId(service.id); setTrace(null); }}><strong>{service.name || item?.label || service.kind}</strong><small>搜索{item?.supports_scrape ? ' · 抓取' : ''}{draft.selected_service_id === service.id ? ' · 默认' : ''}</small></button><div className="search-service-order"><button type="button" disabled={index === 0} onClick={() => move(service.id, index - 1)} aria-label={`上移${service.name}`}>↑</button><button type="button" disabled={index === draft.services.length - 1} onClick={() => move(service.id, index + 1)} aria-label={`下移${service.name}`}>↓</button></div></div>; })}
    </aside><div className="search-settings-detail"><section className="search-common-settings"><h3>通用设置</h3><div className="search-parameter-grid">{limitFields.map(field => <label className="field" key={field.key}><span>{field.label}</span><input type="number" required min={field.min} max={field.max} value={draft[field.key]} onChange={event => setDraft(current => ({ ...current, [field.key]: Number(event.target.value) }))} /></label>)}</div><p className="form-hint">仅限制外部搜索与网页读取的工具调用；模型内置搜索和自定义脚本每次联网的费用以服务商实际计费为准。</p></section>
      {selected && <><div className="search-service-title"><div><h3>{definition?.label ?? selected.kind}</h3><p>{definition?.description}</p><span className="search-capability">搜索</span>{definition?.supports_scrape && <span className="search-capability">网页抓取</span>}{definition?.homepage && /^https:\/\//.test(definition.homepage) && <a href={definition.homepage} target="_blank" rel="noopener noreferrer">官网 / 密钥入口 ↗</a>}</div><button className="button button--quiet" type="button" onClick={() => remove(selected.id)}>删除实例</button></div>
        <label className="field"><span>显示名称</span><input value={selected.name} maxLength={80} required onChange={event => update(selected.id, current => ({ ...current, name: event.target.value }))} /></label>
        <label className="search-default-choice"><input type="radio" name="search-default" checked={draft.selected_service_id === selected.id} onChange={() => setDraft(current => ({ ...current, selected_service_id: selected.id }))} />默认外部服务</label>{draft.selected_service_id === selected.id && <button className="search-text-toggle" type="button" onClick={() => setDraft(current => ({ ...current, selected_service_id: null }))}>清除默认选择</button>}
        <div className="search-fields">{definition?.fields.map(field => renderField(field, selected))}</div>
        <section className="search-test"><h3>真实连接测试</h3><p className="form-hint">测试会向服务发送查询或网址，使用当前未保存的配置，可能产生费用。</p><label className="field"><span>搜索测试查询</span><input value={query} onChange={event => setQuery(event.target.value)} placeholder="输入搜索内容" /></label><details><summary>搜索高级参数</summary><SearchParameters schema={definition?.search_parameters} value={parameters} onChange={setParameters} /></details><button className="button button--quiet" type="button" disabled={testing || !query.trim()} onClick={() => void test('search')}>{testing ? '测试中…' : '测试搜索'}</button>
          {definition?.supports_scrape && <div className="search-scrape-test"><label className="field"><span>抓取网页</span>{selected.kind === 'custom_js' ? <textarea value={url} onChange={event => setUrl(event.target.value)} placeholder="每行一个 http(s) 网页地址，最多5个" rows={3} /> : <input type="url" value={url} onChange={event => setUrl(event.target.value)} placeholder="https://example.com/page" />}</label><details><summary>抓取高级参数</summary><SearchParameters schema={definition.scrape_parameters} value={scrapeParameters} onChange={setScrapeParameters} /></details><button className="button button--quiet" type="button" disabled={testing || !url.trim()} onClick={() => void test('scrape')}>测试抓取</button></div>}{trace && <SearchResults trace={trace} />}</section>
      </>}
    </div></div>{error && <p className="form-error search-settings-error" role="alert">{error}</p>}<footer className="dialog-actions search-settings-actions"><span>{dirty ? '有未保存的修改' : '设置已保存'}</span><button className="button button--quiet" type="button" onClick={close}>取消</button><button className="button button--dark" disabled={saving || testing || !dirty}>{saving ? '保存中…' : '保存设置'}</button></footer></form>}
  </section></div></DialogPortal>;
}
