import { useEffect, useRef, useState } from 'react';
import { previewProviderReasoning, type ReasoningChoice, type ReasoningPreview, type ReasoningPreviewInput } from './api';
import { ReasoningBudget, reasoningChoices, reasoningIssue, reasoningKey, reasoningLabel } from './ReasoningControl';

type Target = Omit<ReasoningPreviewInput, 'profile_id' | 'default_choice'>;
export function useProviderReasoningDraft(target: Target, active: boolean) {
  const [preview, setPreview] = useState<ReasoningPreview | null>(null);
  const [profileId, setProfileId] = useState<string | null>(null);
  const [defaultChoice, setDefaultChoice] = useState<ReasoningChoice | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const epoch = useRef(0);
  const currentTarget = useRef(target); currentTarget.current = target;
  const currentSettings = useRef({ profile_id: profileId, default_choice: defaultChoice }); currentSettings.current = { profile_id: profileId, default_choice: defaultChoice };
  useEffect(() => {
    const current = ++epoch.current; setPreview(null); setProfileId(null); setDefaultChoice(null); setError('');
    if (!active || !target.base_url || !target.model) { setLoading(false); return; }
    setLoading(true);
    previewProviderReasoning(target).then(next => {
      if (epoch.current === current && currentTarget.current === target) { setPreview(next); setProfileId(next.configured_profile_id); setDefaultChoice(next.configured_default); }
    }).catch(reason => { if (epoch.current === current) setError(reason instanceof Error ? reason.message : '无法读取模型思考设置'); })
      .finally(() => { if (epoch.current === current) setLoading(false); });
    return () => { epoch.current++; };
  }, [target, active]);
  async function refresh(settings = currentSettings.current) {
    if (!active || !target.base_url || !target.model) return;
    const current = ++epoch.current; setLoading(true); setError('');
    try {
      const next = await previewProviderReasoning({ ...target, ...settings });
      if (epoch.current === current && currentTarget.current === target) setPreview(next);
    } catch (reason) { if (epoch.current === current) setError(reason instanceof Error ? reason.message : '无法读取模型思考设置'); }
    finally { if (epoch.current === current) setLoading(false); }
  }
  function changeProfile(value: string | null) {
    const settings = { ...currentSettings.current, profile_id: value };
    setProfileId(value); currentSettings.current = settings; void refresh(settings);
  }
  function changeDefault(value: ReasoningChoice | null) {
    const settings = { ...currentSettings.current, default_choice: value };
    setDefaultChoice(value); currentSettings.current = settings;
    setError('');
  }
  const actualChoice = defaultChoice ?? preview?.default_choice ?? null;
  const issue = reasoningIssue(actualChoice, preview?.capability);
  const missing = Boolean(preview?.default_required && !defaultChoice);
  return { preview, profileId, defaultChoice, actualChoice, loading, error, issue, missing,
    blocked: loading || !preview || Boolean(error || issue) || missing,
    settings: { profile_id: profileId, default_choice: defaultChoice }, changeProfile, changeDefault, refresh };
}
export type ProviderReasoningDraft = ReturnType<typeof useProviderReasoningDraft>;
export default function ReasoningSettings({ draft, disabled = false }: { draft: ProviderReasoningDraft; disabled?: boolean }) {
  const preview = draft.preview;
  const choices = reasoningChoices(preview?.capability);
  const selected = reasoningKey(draft.actualChoice);
  const blocked = disabled || draft.loading;
  return <section className="provider-reasoning" aria-label="模型思考配置">
    {draft.loading && !preview ? <p role="status">正在读取模型思考设置…</p> : preview && <>
      {choices.length > 0 && <label><span>默认思考强度</span><select aria-label="默认思考强度" value={selected} disabled={blocked} onChange={event => {
        const option = choices.find(item => item.key === event.target.value); if (option) draft.changeDefault(option.value);
      }}>
        {!selected && <option value="" disabled>选择这个模型的默认设置</option>}
        {selected && !choices.some(item => item.key === selected) && <option value={selected}>{reasoningLabel(draft.actualChoice)}（当前规格不支持）</option>}
        {choices.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}
      </select></label>}
      {draft.actualChoice?.mode === 'budget' && <ReasoningBudget value={draft.actualChoice} capability={preview.capability} onChange={draft.changeDefault} disabled={blocked} />}
      {draft.missing && <p className="form-hint">这个模型没有高档，请选择默认设置后保存。</p>}
      <details><summary>思考规格</summary><label><span>模型思考规格</span><select aria-label="模型思考规格" value={draft.profileId ?? ''} disabled={blocked} onChange={event => draft.changeProfile(event.target.value || null)}>
        <option value="">根据模型信息识别</option><option value="unsupported">不提供思考控制</option>
        {draft.profileId && draft.profileId !== 'unsupported' && !preview.profiles.some(item => item.id === draft.profileId) && <option value={draft.profileId}>当前规格（接口已变化）</option>}
        {preview.profiles.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>{preview.capability.state === 'unknown' && <p className="form-hint">未知别名可按模型文档选择对应规格。</p>}</details>
    </>}
    {(draft.error || draft.issue) && <p className="form-error" role="alert">{draft.error || draft.issue}</p>}
  </section>;
}
