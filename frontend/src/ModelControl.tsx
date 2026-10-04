import { useCallback, useEffect, useRef, useState } from 'react';
import { SlidersHorizontal } from 'lucide-react';
import { getModelConfig, listAiProviders, previewModelConfig, putModelConfig, type AiProvider, type ModelConfig, type ModelOverride, type ModelRunConfig, type ModelScopeKind, type ModelSource } from './api';
import './ModelControl.css';

const emptyOverride = (): ModelOverride => ({ model: null, timeout_seconds: null });
const scopeNames: Record<ModelScopeKind | 'run', string> = { global: '全局默认', plan: '计划', task: '任务', conversation: '当前对话', discussion: '当前对话', run: '仅本次' };
const sourceName = (source?: ModelSource | null) => source ? scopeNames[source.kind] : null;
const errorText = (reason: unknown) => reason instanceof Error ? reason.message : '模型配置暂时无法读取';

export function useModelControl(kind: ModelScopeKind, id: string) {
  const [saved, setSaved] = useState<ModelConfig | null>(null);
  const [preview, setPreview] = useState<ModelConfig | null>(null);
  const [runOverride, setRunOverride] = useState<ModelOverride | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef(0);
  const scope = `${kind}:${id}`;
  const currentScope = useRef(scope); currentScope.current = scope;
  const load = useCallback(async () => {
    const epoch = ++request.current;
    setBusy(true); setError('');
    try {
      const next = await getModelConfig(kind, id);
      const run = runOverride ? await previewModelConfig(kind, id, runOverride) : null;
      if (request.current === epoch && currentScope.current === scope) { setSaved(next); setPreview(run); }
      return next;
    } catch (reason) {
      if (request.current === epoch) setError(errorText(reason));
      throw reason;
    } finally { if (request.current === epoch) setBusy(false); }
  }, [kind, id, scope, runOverride]);
  useEffect(() => {
    const epoch = ++request.current;
    setSaved(null); setPreview(null); setRunOverride(null); setBusy(true); setError('');
    getModelConfig(kind, id).then(next => { if (request.current === epoch) setSaved(next); })
      .catch(reason => { if (request.current === epoch) setError(errorText(reason)); })
      .finally(() => { if (request.current === epoch) setBusy(false); });
    return () => { request.current++; };
  }, [kind, id]);
  useEffect(() => {
    const update = () => { void load().catch(() => {}); };
    window.addEventListener('nautilus:model-settings-changed', update);
    window.addEventListener('nautilus:image-settings-changed', update);
    return () => {
      window.removeEventListener('nautilus:model-settings-changed', update);
      window.removeEventListener('nautilus:image-settings-changed', update);
    };
  }, [load]);
  const config = saved?.scope_kind === kind && saved.scope_id === id ? preview ?? saved : null;
  async function save(override: ModelOverride, once: boolean) {
    if (!saved || busy) return;
    const epoch = ++request.current;
    setBusy(true); setError('');
    try {
      if (once) {
        const next = await previewModelConfig(kind, id, override);
        if (request.current === epoch) { setRunOverride(override); setPreview(next); }
      } else {
        const next = await putModelConfig(kind, id, saved.revision, override);
        if (request.current === epoch) setSaved(next);
        const run = runOverride ? await previewModelConfig(kind, id, runOverride) : null;
        if (request.current === epoch) { setSaved(next); setPreview(run); }
      }
    } catch (reason) { if (request.current === epoch) setError(errorText(reason)); throw reason; }
    finally { if (request.current === epoch) setBusy(false); }
  }
  function clearOnce() { setRunOverride(null); setPreview(null); }
  async function forSend(targetKind: ModelScopeKind = kind, targetId = id) {
    if (targetKind === kind && targetId === id) {
      if (!config || busy) throw new Error('模型配置正在读取，请稍后发送。');
      return { model_override: runOverride, model_config_token: config.token };
    }
    const next = await getModelConfig(targetKind, targetId);
    return { model_override: null, model_config_token: next.token };
  }
  return { config, saved, runOverride, busy, error, save, clearOnce, forSend, reload: load };
}
export type ModelControlState = ReturnType<typeof useModelControl>;

export function ModelControlNotice({ control, onOpen }: { control: ModelControlState; onOpen: () => void }) {
  if (!control.error && (!control.config || control.config.effective.available)) return null;
  return <p className="ai-room-error" role="alert">{control.error || control.config?.issues[0] || '当前模型配置不可用。'} <button type="button" className="text-button" onClick={onOpen}>模型配置</button></p>;
}

export function ModelSummary({ value }: { value: ModelRunConfig }) {
  const model = value.model_display_name ?? value.model_id;
  const timeoutSource = value.timeout_policy === 'provider_default' ? '提供方默认' : sourceName(value.sources?.timeout);
  return <div className="model-control__summary">
    <p>{[value.provider_display_name, model].filter(Boolean).join(' · ') || '尚未配置模型'}{sourceName(value.sources?.model) && <small>来自{sourceName(value.sources?.model)}</small>}</p>
    {value.timeout_seconds != null && <p>超时 {value.timeout_seconds} 秒{timeoutSource && <small>来自{timeoutSource}</small>}</p>}
  </div>;
}
export function ModelConfigHistory({ config }: { config?: ModelRunConfig | null }) {
  if (!config) return null;
  return <details className="model-config-history"><summary>本次模型配置</summary><ModelSummary value={config} /></details>;
}
export function ModelControlEditor({ control, allowOnce = false, disabled = false }: { control: ModelControlState; allowOnce?: boolean; disabled?: boolean }) {
  const [providers, setProviders] = useState<AiProvider[]>([]);
  const [once, setOnce] = useState(false);
  const [model, setModel] = useState('');
  const [timeout, setTimeout] = useState('');
  const [message, setMessage] = useState('');
  const previousScope = useRef('');
  const config = control.config;
  const global = config?.scope_kind === 'global';
  const scope = config ? `${config.scope_kind}:${config.scope_id}` : '';
  useEffect(() => {
    const update = () => { void listAiProviders().then(setProviders).catch(reason => setMessage(errorText(reason))); };
    update();
    window.addEventListener('nautilus:model-settings-changed', update);
    return () => window.removeEventListener('nautilus:model-settings-changed', update);
  }, []);
  useEffect(() => {
    if (scope !== previousScope.current) { previousScope.current = scope; setOnce(false); }
  }, [scope]);
  const override = once ? control.runOverride : control.saved?.override;
  useEffect(() => {
    setModel(override?.model ? `${override.model.provider_profile_id}::${override.model.provider_model_id}` : '');
    setTimeout((once || global) && override?.timeout_seconds != null ? String(override.timeout_seconds) : '');
    setMessage('');
  }, [override, once, global]);
  const selectedProviderId = model ? model.split('::')[0] : control.saved?.effective.provider_profile_id;
  const defaultTimeout = providers.find(provider => provider.id === selectedProviderId)?.request_timeout_seconds ?? control.saved?.effective.timeout_seconds ?? 5;
  async function apply(reset = false) {
    const value = (once || global) && timeout.trim() ? Number(timeout) : null;
    if (!reset && value !== null && (!Number.isInteger(value) || value < 5 || value > 600)) { setMessage('超时请填写 5–600 秒。'); return; }
    if (!reset && once && value !== null && value < defaultTimeout) { setMessage(`仅本次超时不能少于提供方默认的 ${defaultTimeout} 秒。`); return; }
    const [provider_profile_id, provider_model_id] = model.split('::');
    try {
      await control.save(reset ? emptyOverride() : { model: model ? { provider_profile_id, provider_model_id } : null, timeout_seconds: value }, once);
      setMessage(once ? '已用于本次发送' : '已保存');
    } catch { /* The hook keeps the server error visible and the draft intact. */ }
  }
  const blocked = disabled || control.busy || !config;
  return <section className="model-control" aria-label="模型配置">
    {allowOnce && <div className="model-control__scope" role="group" aria-label="模型覆盖范围">
      <button type="button" aria-pressed={!once} onClick={() => setOnce(false)} disabled={disabled}>当前对话</button>
      <button type="button" aria-pressed={once} onClick={() => setOnce(true)} disabled={disabled}>仅本次</button>
    </div>}
    {config && <ModelSummary value={{ ...config.effective, sources: config.sources }} />}
    {control.busy && !config && <p role="status">正在读取模型配置…</p>}
    <label><span>提供方 / 模型</span><select aria-label="模型配置选择" value={model} onChange={event => { setModel(event.target.value); setMessage(''); }} disabled={blocked}>
      <option value="">继承上级</option>
      {model && !providers.some(provider => provider.models?.some(item => `${provider.id}::${item.id}` === model)) && <option value={model}>当前模型（不可用）</option>}
      {providers.flatMap(provider => (provider.models ?? []).map(item => <option key={item.id} value={`${provider.id}::${item.id}`} disabled={!provider.enabled || !item.enabled || item.discovery_status === 'unavailable'}>{provider.display_name} · {item.display_name}</option>))}
    </select></label>
    {(once || global) && <label><span>{once ? '仅本次延长（秒）' : '提供方默认超时（秒）'}</span><input aria-label="模型配置超时" type="number" min={once ? defaultTimeout : 5} max={600} step={1} placeholder={`提供方默认（${defaultTimeout} 秒）`} value={timeout} onChange={event => { setTimeout(event.target.value); setMessage(''); }} disabled={blocked} /></label>}
    <div className="model-control__actions">
      <button type="button" className="button button--quiet" disabled={blocked} onClick={() => void apply()}>{once ? '用于本次' : '保存配置'}</button>
      <button type="button" className="text-button" disabled={blocked} onClick={() => { if (once) { control.clearOnce(); setMessage(''); } else void apply(true); }}>{once ? '取消本次覆盖' : '恢复继承'}</button>
    </div>
    {control.runOverride && <p className="model-control__once" role="status">仅本次覆盖已准备</p>}
    {(control.error || config?.issues.length) ? <p role="alert">{control.error || config?.issues.join('；')} <button type="button" className="text-button" disabled={control.busy} onClick={() => void control.reload().catch(() => {})}>刷新配置</button></p> : message && <p role="status">{message}</p>}
  </section>;
}
function ScopedModelPanel({ kind, id }: { kind: 'plan' | 'task'; id: string }) {
  const control = useModelControl(kind, id);
  return <ModelControlEditor control={control} />;
}
export default function ScopedModelControl({ kind, id }: { kind: 'plan' | 'task'; id: string }) {
  const [open, setOpen] = useState(false);
  return <details className="model-control-entry" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary><SlidersHorizontal size={14} />模型配置</summary>{open && <ScopedModelPanel kind={kind} id={id} />}
  </details>;
}
