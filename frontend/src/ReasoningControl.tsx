import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { ChevronDown, X } from 'lucide-react';
import DialogPortal from './DialogPortal';
import { getReasoningSupport, saveReasoningSupport, type ReasoningCapability, type ReasoningChoice, type ReasoningSupport } from './api';
import type { ModelControlState } from './ModelControl';
import './ReasoningControl.css';

const labels: Record<string, string> = { minimal: '极低', low: '低', medium: '中', high: '高', xhigh: '超高', max: '最高' };
export const effortLabel = (effort: string) => labels[effort] ?? effort;
export function reasoningLabel(choice?: ReasoningChoice | null): string {
  if (!choice || choice.mode === 'default') return '模型默认';
  if (choice.mode === 'effort') return effortLabel(choice.effort);
  if (choice.mode === 'budget') return `${choice.budget_tokens} Token${choice.effort ? ` · ${effortLabel(choice.effort)}` : ''}`;
  return choice.mode === 'off' ? '关闭' : '开启';
}
const choiceKey = (choice?: ReasoningChoice | null) => !choice ? '' : choice.mode === 'effort' ? `effort:${choice.effort}` : choice.mode;
const message = (error: unknown) => error instanceof Error ? error.message : '思考设置暂时无法读取';
export function reasoningChoices(capability?: ReasoningCapability | null): Array<{ key: string; label: string; value: ReasoningChoice | null }> {
  const choices: Array<{ key: string; label: string; value: ReasoningChoice | null }> = [
    { key: '', label: '恢复继承', value: null }, { key: 'default', label: '模型默认', value: { mode: 'default' } },
  ];
  if (capability?.state !== 'available') return choices;
  if (capability.supports_off) choices.push({ key: 'off', label: '关闭思考', value: { mode: 'off' } });
  if (capability.supports_on) choices.push({ key: 'on', label: capability.budget?.dynamic ? '动态预算' : '开启思考', value: { mode: 'on' } });
  for (const effort of capability.efforts) choices.push({ key: `effort:${effort}`, label: effortLabel(effort), value: { mode: 'effort', effort } });
  if (capability.budget) choices.push({ key: 'budget', label: '自定义思考预算', value: { mode: 'budget', budget_tokens: capability.budget.min } });
  return choices;
}
export function reasoningIssue(choice: ReasoningChoice | null, capability?: ReasoningCapability | null): string | null {
  if (!choice || choice.mode === 'default') return null;
  if (capability?.state !== 'available') return '请先确认当前模型的思考规格，或选择模型默认。';
  if ((choice.mode === 'off' && !capability.supports_off) || (choice.mode === 'on' && !capability.supports_on)
    || (choice.mode === 'effort' && !capability.efforts.includes(choice.effort))) return '当前模型不支持这个思考设置，请重新选择。';
  if (choice.mode === 'budget') {
    const budget = capability.budget;
    if (!budget || !Number.isInteger(choice.budget_tokens) || choice.budget_tokens < budget.min || (budget.max !== null && choice.budget_tokens > budget.max)) return '请填写当前模型支持的思考预算。';
    if (choice.effort && !budget.efforts.includes(choice.effort)) return '当前预算模式不支持这个响应投入等级。';
  }
  return null;
}

export function ReasoningBudget({ value, capability, onChange, disabled = false }: {
  value: Extract<ReasoningChoice, { mode: 'budget' }>; capability?: ReasoningCapability | null;
  onChange: (choice: ReasoningChoice) => void; disabled?: boolean;
}) {
  const budget = capability?.budget;
  return <div className="reasoning-budget">
    <label><span>思考预算（Token）</span><input aria-label="思考预算（Token）" type="number" min={budget?.min ?? 1} max={budget?.max ?? undefined} step={1} value={Number.isFinite(value.budget_tokens) && value.budget_tokens > 0 ? value.budget_tokens : ''} disabled={disabled} onChange={event => onChange({ ...value, budget_tokens: Number(event.target.value) })} /></label>
    {budget && <small>{budget.max === null ? `至少 ${budget.min} Token` : `${budget.min}–${budget.max} Token`}</small>}
    {Boolean(budget?.efforts.length) && <label><span>响应投入</span><select aria-label="预算模式响应投入" value={value.effort ?? ''} disabled={disabled} onChange={event => {
      const next = { ...value }; if (event.target.value) next.effort = event.target.value; else delete next.effort; onChange(next);
    }}><option value="">模型默认</option>{budget!.efforts.map(effort => <option key={effort} value={effort}>{effortLabel(effort)}</option>)}</select></label>}
  </div>;
}
export function ReasoningFields({ value, capability, onChange, disabled = false, label = '思考设置', allowInherit = true }: {
  value: ReasoningChoice | null; capability?: ReasoningCapability | null; onChange: (choice: ReasoningChoice | null) => void; disabled?: boolean; label?: string; allowInherit?: boolean;
}) {
  const choices = reasoningChoices(capability).filter(item => allowInherit || item.key !== '');
  const key = choiceKey(!allowInherit && !value ? { mode: 'default' } : value);
  return <div className="reasoning-fields">
    <label><span>{label}</span><select aria-label={label} value={key} disabled={disabled} onChange={event => onChange(choices.find(item => item.key === event.target.value)?.value ?? null)}>
      {key && !choices.some(item => item.key === key) && <option value={key}>{reasoningLabel(value)}（当前模型不支持）</option>}
      {choices.map(item => <option key={item.key} value={item.key}>{item.key === '' ? '继承上级' : item.label}</option>)}
    </select></label>
    {value?.mode === 'budget' && <ReasoningBudget value={value} capability={capability} onChange={onChange} disabled={disabled} />}
  </div>;
}

export function ReasoningModelDeclaration({ providerId, modelId, onSaved, autoFocus = false }: { providerId: string; modelId: string; onSaved?: () => void; autoFocus?: boolean }) {
  const [support, setSupport] = useState<ReasoningSupport | null>(null);
  const [profile, setProfile] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const epoch = useRef(0);
  useEffect(() => {
    const current = ++epoch.current; setSupport(null); setError(''); setNotice(''); setBusy(true);
    getReasoningSupport(providerId, modelId).then(next => { if (epoch.current === current) { setSupport(next); setProfile(next.configured_profile_id ?? ''); } })
      .catch(reason => { if (epoch.current === current) setError(message(reason)); })
      .finally(() => { if (epoch.current === current) setBusy(false); });
    return () => { epoch.current++; };
  }, [providerId, modelId]);
  async function save() {
    if (!support || busy) return;
    const current = ++epoch.current; setBusy(true); setError(''); setNotice('');
    try {
      const next = await saveReasoningSupport(providerId, modelId, support.revision, profile || null);
      if (epoch.current !== current) return;
      setSupport(next); setNotice('思考规格已保存。'); window.dispatchEvent(new Event('nautilus:model-settings-changed')); onSaved?.();
    } catch (reason) { if (epoch.current === current) setError(message(reason)); }
    finally { if (epoch.current === current) setBusy(false); }
  }
  return <div className="reasoning-model-declaration">
    <p>按模型文档选择规格。保存不会调用模型。</p>
    {support ? <>
      <label><span>模型思考规格</span><select aria-label="模型思考规格" value={profile} disabled={busy} autoFocus={autoFocus} onChange={event => { setProfile(event.target.value); setNotice(''); }}>
        <option value="">自动识别已登记型号</option><option value="unsupported">不提供思考控制</option>
        {profile && profile !== 'unsupported' && !support.profiles.some(item => item.id === profile) && <option value={profile}>当前规格（接口已变化）</option>}
        {support.profiles.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>
      {support.capability.stale && <p role="status">接口或模型已变化，请重新确认规格。</p>}
      <button className="button button--quiet" type="button" disabled={busy} onClick={() => void save()}>保存思考规格</button>
      {support.capability.reference_urls.map(url => <a key={url} href={url} target="_blank" rel="noreferrer">模型文档</a>)}
    </> : busy && <p role="status">正在读取模型规格…</p>}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
  </div>;
}

export default function ReasoningControl({ control, disabled = false, contextKey, onPrepare }: {
  control: ModelControlState; disabled?: boolean; contextKey: string; onPrepare?: () => Promise<string>;
}) {
  const [open, setOpen] = useState(false);
  const [once, setOnce] = useState(false);
  const [budgetChoice, setBudgetChoice] = useState<Extract<ReasoningChoice, { mode: 'budget' }> | null>(null);
  const [target, setTarget] = useState('');
  const [position, setPosition] = useState({ left: 12, top: 12 });
  const [error, setError] = useState('');
  const [configure, setConfigure] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLElement>(null);
  const modal = useRef<HTMLElement>(null);
  const epoch = useRef(0);
  const id = useId();
  const config = control.config;
  const scope = config ? `${config.scope_kind}:${config.scope_id}` : '';
  const ready = Boolean(config && target === scope && !control.busy && !disabled);
  const activeEffective = once ? config?.effective : control.saved?.effective;
  const capability = activeEffective?.reasoning_capability;
  const chosen = once ? control.runOverride?.reasoning ?? null : control.saved?.override.reasoning ?? null;
  const effectiveLabel = reasoningLabel(config?.effective.reasoning);
  const source = config?.sources.reasoning?.kind;
  const choices = reasoningChoices(capability);
  function close(restoreFocus = true) {
    epoch.current++; setOpen(false); setConfigure(false);
    if (restoreFocus) window.requestAnimationFrame(() => trigger.current?.focus({ preventScroll: true }));
  }
  useEffect(() => { epoch.current++; setOpen(false); setConfigure(false); setTarget(''); setError(''); }, [contextKey]);
  useEffect(() => { return () => { epoch.current++; }; }, []);
  useLayoutEffect(() => {
    if (!open || configure) return;
    const place = () => {
      if (!trigger.current || !popup.current) return;
      const button = trigger.current.getBoundingClientRect(); const menu = popup.current.getBoundingClientRect();
      const left = Math.max(12, Math.min(button.right - menu.width, innerWidth - menu.width - 12));
      const above = button.top - menu.height - 8;
      const top = Math.max(12, above >= 12 ? above : Math.min(button.bottom + 8, innerHeight - menu.height - 12));
      setPosition({ left, top });
    };
    place(); window.addEventListener('resize', place); window.addEventListener('scroll', place, true);
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true); };
  }, [open, configure, scope, capability, budgetChoice, ready, error]);
  useEffect(() => {
    if (!open) return;
    if (!configure) window.requestAnimationFrame(() => popup.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus());
    const outside = (event: PointerEvent) => { if (!configure && !popup.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) close(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); if (configure) setConfigure(false); else close(); } };
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [open, configure]);
  useEffect(() => {
    if (configure) window.requestAnimationFrame(() => modal.current?.querySelector<HTMLSelectElement>('select')?.focus());
  }, [configure]);
  async function show() {
    if (disabled) return;
    if (open) { close(); return; }
    const current = ++epoch.current; setOpen(true); setError(''); setBudgetChoice(null); setOnce(false);
    if (!onPrepare) { setTarget(scope); return; }
    setTarget('');
    try { const conversationId = await onPrepare(); if (epoch.current === current) setTarget(`conversation:${conversationId}`); }
    catch (reason) { if (epoch.current === current) setError(message(reason)); }
  }
  async function choose(value: ReasoningChoice | null) {
    if (!ready) return;
    const issue = reasoningIssue(value, capability); if (issue) { setError(issue); return; }
    const current = epoch.current; setError('');
    try { await control.changeReasoning(value, once); if (epoch.current === current) close(); }
    catch (reason) { if (epoch.current === current) setError(message(reason)); }
  }
  return <>
    <button ref={trigger} type="button" className="reasoning-quick" aria-label="思考设置" aria-expanded={open} aria-controls={open ? id : undefined} disabled={disabled} onClick={() => void show()}>思考：{effectiveLabel}{source === 'run' ? ' · 本次' : ''}<ChevronDown size={12} /></button>
    {open && !configure && <DialogPortal><section id={id} ref={popup} role="dialog" aria-label="思考设置" className="reasoning-popover" style={position} onKeyDown={event => {
      if (!['ArrowDown', 'ArrowUp'].includes(event.key) || event.target instanceof HTMLInputElement) return;
      const buttons = Array.from(popup.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? []);
      const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
      if (index !== -1) { event.preventDefault(); buttons[(index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length]?.focus(); }
    }}>
      <header><strong>思考设置</strong><button type="button" className="icon-button" aria-label="关闭思考设置" onClick={() => close()}><X size={14} /></button></header>
      <div className="model-control__scope" role="group" aria-label="思考作用范围"><button type="button" aria-pressed={!once} disabled={!ready} onClick={() => { setOnce(false); setBudgetChoice(null); setError(''); }}>当前对话</button><button type="button" aria-pressed={once} disabled={!ready} onClick={() => { setOnce(true); setBudgetChoice(null); setError(''); }}>仅本次</button></div>
      {!target || !config || target !== scope ? <p role="status">正在准备当前对话…</p> : <>
        <div className="reasoning-options" role="group" aria-label="思考选项">{choices.map(item => <button key={item.key} type="button" aria-pressed={choiceKey(chosen) === item.key} disabled={!ready} onClick={() => {
          if (item.value?.mode === 'budget') { setBudgetChoice(chosen?.mode === 'budget' ? chosen : item.value); setError(''); } else void choose(item.value);
        }}>{item.label}</button>)}</div>
        {budgetChoice && <><ReasoningBudget value={budgetChoice} capability={capability} onChange={value => { if (value.mode === 'budget') setBudgetChoice(value); setError(''); }} disabled={!ready} /><button className="button button--quiet" type="button" disabled={!ready} onClick={() => void choose(budgetChoice)}>使用这个预算</button></>}
        {capability?.state !== 'available' && <p>{capability?.state === 'unsupported' ? '当前规格不提供思考控制。' : '思考规格尚未确认，可先使用模型默认。'}</p>}
        {activeEffective?.provider_profile_id && activeEffective.provider_model_id && <button className="text-button" type="button" disabled={!ready} onClick={() => setConfigure(true)}>配置模型思考规格</button>}
      </>}
      {(error || control.error) && <p role="alert">{error || control.error}</p>}
    </section></DialogPortal>}
    {open && configure && activeEffective?.provider_profile_id && activeEffective.provider_model_id && <DialogPortal><div className="dialog-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setConfigure(false); }}>
      <section ref={modal} className="reasoning-spec-dialog" role="dialog" aria-modal="true" aria-label="模型思考规格" onKeyDown={event => {
        if (event.key !== 'Tab') return;
        const fields = Array.from(modal.current?.querySelectorAll<HTMLElement>('button:not(:disabled), select:not(:disabled), a[href]') ?? []);
        if (event.shiftKey && document.activeElement === fields[0]) { event.preventDefault(); fields.at(-1)?.focus(); }
        if (!event.shiftKey && document.activeElement === fields.at(-1)) { event.preventDefault(); fields[0]?.focus(); }
      }}><header><h3>模型思考规格</h3><button className="icon-button" type="button" aria-label="关闭模型思考规格" onClick={() => setConfigure(false)}><X size={16} /></button></header>
        <p>{activeEffective.provider_display_name} · {activeEffective.model_display_name ?? activeEffective.model_id}</p>
        <ReasoningModelDeclaration providerId={activeEffective.provider_profile_id} modelId={activeEffective.provider_model_id} autoFocus />
      </section></div></DialogPortal>}
  </>;
}
