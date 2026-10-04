import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { Brain, ChevronDown, Sparkles, X, Zap } from 'lucide-react';
import DialogPortal from './DialogPortal';
import type { ReasoningCapability, ReasoningChoice } from './api';
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
export const reasoningKey = (choice?: ReasoningChoice | null) => !choice ? '' : choice.mode === 'effort' ? `effort:${choice.effort}` : choice.mode;
export type ReasoningOption = { key: string; label: string; value: ReasoningChoice };
export function reasoningChoices(capability?: ReasoningCapability | null): ReasoningOption[] {
  if (capability?.state !== 'available') return [];
  const choices: ReasoningOption[] = [];
  if (capability.supports_off) choices.push({ key: 'off', label: '关闭', value: { mode: 'off' } });
  for (const effort of capability.efforts) choices.push({ key: `effort:${effort}`, label: effortLabel(effort), value: { mode: 'effort', effort } });
  if (!capability.efforts.length && capability.supports_on) choices.push({ key: 'on', label: capability.budget?.dynamic ? '动态预算' : '开启', value: { mode: 'on' } });
  if (capability.budget) choices.push({ key: 'budget', label: '自定义预算', value: { mode: 'budget', budget_tokens: capability.budget.min } });
  return choices;
}
export function reasoningIssue(choice: ReasoningChoice | null, capability?: ReasoningCapability | null): string | null {
  if (!choice || choice.mode === 'default') return null;
  if (capability?.state !== 'available') return '请先确认当前模型的思考规格。';
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
function ReasoningIcon({ choice, size = 15 }: { choice?: ReasoningChoice | null; size?: number }) {
  if (choice?.mode === 'off' || (choice?.mode === 'effort' && ['minimal', 'low'].includes(choice.effort))) return <Zap size={size} />;
  if (choice?.mode === 'effort' && ['xhigh', 'max'].includes(choice.effort)) return <Sparkles size={size} />;
  return <Brain size={size} />;
}
function description(choice?: ReasoningChoice | null) {
  if (choice?.mode === 'off') return '直接生成回答。';
  if (choice?.mode === 'effort') return ({ minimal: '使用最少的思考投入。', low: '使用较少的思考投入。', medium: '使用适中的思考投入。', high: '投入更多思考。', xhigh: '使用较高的思考投入。', max: '使用模型支持的最高投入。' } as Record<string, string>)[choice.effort] ?? '使用这个模型的思考等级。';
  if (choice?.mode === 'on') return '使用模型的动态思考方式。';
  return '使用这个模型的思考预算。';
}

export default function ReasoningControl({ control, disabled = false, contextKey, onPrepare }: {
  control: ModelControlState; disabled?: boolean; contextKey: string; onPrepare?: () => Promise<string>;
}) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState('');
  const [position, setPosition] = useState({ left: 12, top: 12 });
  const [previewIndex, setPreviewIndex] = useState(0);
  const [previewChanged, setPreviewChanged] = useState(false);
  const [budgetDraft, setBudgetDraft] = useState<ReasoningChoice | null>(null);
  const [error, setError] = useState('');
  const trigger = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLElement>(null);
  const range = useRef<HTMLInputElement>(null);
  const epoch = useRef(0);
  const id = useId();
  const config = control.config;
  const effective = config?.effective;
  const capability = effective?.reasoning_capability;
  const choices = reasoningChoices(capability);
  const savedIndex = choices.findIndex(item => item.key === reasoningKey(effective?.reasoning));
  const current = choices[previewIndex]?.value;
  const scope = config ? `${config.scope_kind}:${config.scope_id}` : '';
  const modelKey = `${effective?.provider_profile_id}:${effective?.provider_model_id}`;
  const ready = Boolean(config && target === scope && !control.busy && !disabled);
  const budget = Boolean(capability?.budget && !capability.efforts.length);
  useEffect(() => { setPreviewIndex(Math.max(0, savedIndex)); setPreviewChanged(false); setBudgetDraft(effective?.reasoning ?? null); setError(''); }, [modelKey, savedIndex, JSON.stringify(effective?.reasoning)]);
  function close(restoreFocus = true) {
    epoch.current++; setOpen(false);
    if (restoreFocus) window.requestAnimationFrame(() => trigger.current?.focus({ preventScroll: true }));
  }
  useEffect(() => { epoch.current++; setOpen(false); setTarget(''); setError(''); }, [contextKey]);
  useEffect(() => { return () => { epoch.current++; }; }, []);
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      if (!trigger.current || !popup.current) return;
      const button = trigger.current.getBoundingClientRect(); const menu = popup.current.getBoundingClientRect();
      const left = Math.max(12, Math.min(button.right - menu.width, innerWidth - menu.width - 12));
      const above = button.top - menu.height - 8;
      setPosition({ left, top: Math.max(12, above >= 12 ? above : Math.min(button.bottom + 8, innerHeight - menu.height - 12)) });
    };
    place(); window.addEventListener('resize', place); window.addEventListener('scroll', place, true);
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true); };
  }, [open, scope, modelKey, budget, ready, error, reasoningKey(budgetDraft)]);
  useEffect(() => {
    if (!open) return;
    window.requestAnimationFrame(() => (range.current ?? popup.current?.querySelector<HTMLElement>('select:not(:disabled), button:not(:disabled)'))?.focus());
    const outside = (event: PointerEvent) => { if (!popup.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) close(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); close(); } };
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [open, ready]);
  async function show() {
    if (disabled) return;
    if (open) { close(); return; }
    const currentEpoch = ++epoch.current; setOpen(true); setError(''); setPreviewIndex(Math.max(0, savedIndex)); setPreviewChanged(false); setBudgetDraft(effective?.reasoning ?? null);
    if (!onPrepare) { setTarget(scope); return; }
    setTarget('');
    try { const conversationId = await onPrepare(); if (epoch.current === currentEpoch) setTarget(`conversation:${conversationId}`); }
    catch (reason) { if (epoch.current === currentEpoch) setError(reason instanceof Error ? reason.message : '无法准备当前对话'); }
  }
  async function choose(choice: ReasoningChoice) {
    if (!ready) return;
    const issue = reasoningIssue(choice, capability); if (issue) { setError(issue); return; }
    const currentEpoch = epoch.current; setError('');
    try { await control.changeReasoning(choice); }
    catch (reason) {
      if (epoch.current !== currentEpoch) return;
      setPreviewIndex(Math.max(0, savedIndex)); setPreviewChanged(false); setBudgetDraft(effective?.reasoning ?? null);
      setError(reason instanceof Error ? reason.message : '思考设置未保存');
    }
  }
  function commit(index: number) {
    const option = choices[index]; if (option) { setPreviewIndex(index); setPreviewChanged(true); void choose(option.value); }
  }
  const triggerLabel = !effective?.reasoning || effective.reasoning.mode === 'default' ? capability?.state === 'unsupported' ? '不可调' : '未配置' : reasoningLabel(effective.reasoning);
  const shownChoice = savedIndex < 0 && !previewChanged ? effective?.reasoning : current;
  const shownLabel = savedIndex < 0 && !previewChanged && (!shownChoice || shownChoice.mode === 'default') ? '请选择强度' : reasoningLabel(shownChoice);
  return <>
    <button ref={trigger} type="button" className="reasoning-quick" aria-label="思考设置" aria-expanded={open} aria-controls={open ? id : undefined} disabled={disabled} onClick={() => void show()}><ReasoningIcon choice={effective?.reasoning} size={13} />思考：{triggerLabel}<ChevronDown size={11} /></button>
    {open && <DialogPortal><section id={id} ref={popup} role="dialog" aria-label="思考设置" className="reasoning-popover" style={position}>
      <header><strong>思考强度</strong><button type="button" className="icon-button" aria-label="关闭思考设置" onClick={() => close()}><X size={14} /></button></header>
      {!target || !config || target !== scope ? <p role="status">正在准备当前对话…</p> : !choices.length ? <p>{capability?.state === 'unsupported' ? '这个模型不提供思考调节。' : '请在提供方设置中确认这个模型的思考规格。'}</p> : budget ? <>
        <label className="reasoning-budget-mode"><span>预算方式</span><select aria-label="思考预算方式" value={choices.some(item => item.key === reasoningKey(budgetDraft)) ? reasoningKey(budgetDraft) : ''} disabled={!ready} onChange={event => {
          const option = choices.find(item => item.key === event.target.value); if (option) { setBudgetDraft(option.value); setError(''); }
        }}><option value="" disabled>选择预算方式</option>{choices.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
        {budgetDraft?.mode === 'budget' && <ReasoningBudget value={budgetDraft} capability={capability} onChange={setBudgetDraft} disabled={!ready} />}
        <button className="button button--quiet" type="button" disabled={!ready || !budgetDraft || !choices.some(item => item.key === reasoningKey(budgetDraft))} onClick={() => { if (budgetDraft) void choose(budgetDraft); }}>保存</button>
      </> : <>
        <div className="reasoning-slider-heading"><span>思考较少</span><span>思考更多</span></div>
        <div className="reasoning-slider" style={{ '--reasoning-progress': `${choices.length > 1 ? previewIndex / (choices.length - 1) * 100 : 0}%` } as CSSProperties}>
          <div className="reasoning-slider-track">{choices.map((item, index) => <i key={item.key} style={{ left: `${choices.length > 1 ? index / (choices.length - 1) * 100 : 0}%` }} />)}</div>
          <input ref={range} type="range" aria-label="思考强度" aria-valuetext={shownLabel} min={0} max={Math.max(0, choices.length - 1)} step={1} value={previewIndex} disabled={!ready || choices.length < 2}
            onChange={event => { setPreviewIndex(Number(event.target.value)); setPreviewChanged(true); setError(''); }}
            onPointerUp={event => commit(Number(event.currentTarget.value))}
            onPointerCancel={() => { setPreviewIndex(Math.max(0, savedIndex)); setPreviewChanged(false); }}
            onKeyUp={event => { if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) commit(Number(event.currentTarget.value)); }} />
        </div>
        <div className="reasoning-slider-labels">{choices.map((item, index) => <button key={item.key} type="button" aria-label={`设为${item.label}`} aria-pressed={(savedIndex >= 0 || previewChanged) && previewIndex === index} disabled={!ready} onClick={() => commit(index)}>{item.label}</button>)}</div>
        <div className="reasoning-current"><ReasoningIcon choice={shownChoice} size={17} /><p><strong>{shownLabel}</strong><span>{savedIndex < 0 && !previewChanged ? '选择一个实际支持的档位。' : description(shownChoice)}</span></p></div>
      </>}
      {(error || control.error) && <p className="reasoning-error" role="alert">{error || control.error}</p>}
    </section></DialogPortal>}
  </>;
}
