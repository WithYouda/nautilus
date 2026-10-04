import { useEffect, useRef, useState } from 'react';
import { getModelConfig, listAiProviders, setReasoningDefault, type AiProvider, type ModelConfig, type ReasoningChoice } from './api';
import { ReasoningFields, ReasoningModelDeclaration, reasoningIssue } from './ReasoningControl';

function ReasoningSettingsBody() {
  const [providers, setProviders] = useState<AiProvider[]>([]);
  const [global, setGlobal] = useState<ModelConfig | null>(null);
  const [choice, setChoice] = useState<ReasoningChoice | null>(null);
  const [model, setModel] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const epoch = useRef(0);
  useEffect(() => {
    let active = true;
    const load = () => {
      const current = ++epoch.current;
      void Promise.all([listAiProviders(), getModelConfig('global', 'default')]).then(([profiles, config]) => {
        if (active && epoch.current === current) { setProviders(profiles); setGlobal(config); setChoice(config.override.reasoning ?? null); }
      }).catch(reason => { if (active && epoch.current === current) setError(reason instanceof Error ? reason.message : '无法读取思考设置'); });
    };
    load(); window.addEventListener('nautilus:model-settings-changed', load);
    return () => { active = false; epoch.current++; window.removeEventListener('nautilus:model-settings-changed', load); };
  }, []);
  async function save() {
    if (!global || busy) return;
    const issue = reasoningIssue(choice, global.effective.reasoning_capability); if (issue) { setError(issue); return; }
    const current = ++epoch.current; setBusy(true); setError(''); setNotice('');
    try {
      const next = await setReasoningDefault(global.revision, choice);
      if (epoch.current !== current) return;
      setGlobal(next); setChoice(next.override.reasoning ?? null); setNotice('全局思考默认已保存。'); window.dispatchEvent(new Event('nautilus:model-settings-changed'));
    } catch (reason) { if (epoch.current === current) setError(reason instanceof Error ? reason.message : '保存失败'); }
    finally { setBusy(false); }
  }
  const [providerId, modelId] = model.split('::');
  return <div className="reasoning-settings-body">
    <section aria-label="全局思考默认"><h4>全局思考默认</h4>
      {global ? <><p>{global.effective.provider_display_name} · {global.effective.model_display_name ?? global.effective.model_id}</p>
        <ReasoningFields value={choice} capability={global.effective.reasoning_capability} onChange={value => { setChoice(value); setError(''); setNotice(''); }} disabled={busy} allowInherit={false} />
        <button type="button" className="button button--quiet" disabled={busy} onClick={() => void save()}>保存全局思考默认</button>
      </> : !error && <p role="status">正在读取思考设置…</p>}
    </section>
    <section aria-label="模型思考规格"><h4>模型思考规格</h4>
      <label><span>选择模型</span><select aria-label="思考规格模型" value={model} disabled={busy} onChange={event => setModel(event.target.value)}><option value="">选择要确认的模型</option>
        {providers.flatMap(provider => (provider.models ?? []).map(item => <option key={item.id} value={`${provider.id}::${item.id}`}>{provider.display_name} · {item.display_name}</option>))}
      </select></label>
      {providerId && modelId && <ReasoningModelDeclaration providerId={providerId} modelId={modelId} />}
    </section>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
  </div>;
}
export default function ReasoningSettings() {
  const [open, setOpen] = useState(false);
  return <details className="reasoning-settings" onToggle={event => setOpen(event.currentTarget.open)}><summary>思考设置</summary>{open && <ReasoningSettingsBody />}</details>;
}
