import { useEffect, useRef, useState } from 'react';
import {
  ApiError, changeAdaptiveLearning, getAdaptiveLearning,
  type AdaptiveLearningChange, type AdaptiveLearningConfiguration, type AdaptiveLearningProfile,
  type AdaptiveLearningRule, type AdaptiveLearningSource,
} from './api';
import './AdaptiveLearningSettings.css';

const scenarios = { general: '一般学习', concepts: '理解概念', problem_solving: '解题', coding: '写代码', project: '做项目' };
const methods = { stepwise: '分步讲解', socratic: '提问引导', feynman: '费曼复述', practice_first: '练习优先', project: '项目实践', direct_answer: '直接给答案', full_explanation: '完整讲解' };
const starts = { auto: '按任务安排', example_first: '先看例子', try_first: '先自己试', explain_first: '先听讲解' };
const helps = { auto: '按情况帮助', one_hint: '先给一个提示', explain_when_stuck: '卡住时再讲解' };
const fields = [
  { key: 'scenario', label: '适用情境', options: scenarios },
  { key: 'method', label: '学习方式', options: methods },
  { key: 'start', label: '如何开始', options: starts },
  { key: 'help', label: '需要帮助时', options: helps },
] as const;
type ChangeAction = AdaptiveLearningChange extends infer T ? T extends AdaptiveLearningChange ? Omit<T, 'expected_revision' | 'request_key'> : never : never;

function summary(configuration: AdaptiveLearningConfiguration) {
  return [scenarios[configuration.scenario], methods[configuration.method],
    configuration.start !== 'auto' ? starts[configuration.start] : null,
    configuration.help !== 'auto' ? helps[configuration.help] : null].filter(Boolean).join(' · ');
}

function allowedStart(method: AdaptiveLearningConfiguration['method'], start: string) {
  if (method === 'practice_first' || method === 'feynman') return start === 'auto' || start === 'try_first';
  if (method === 'direct_answer' || method === 'full_explanation') return start !== 'try_first';
  return true;
}

function SourceDetails({ source, original, reason }: { source: AdaptiveLearningSource | null; original: string | null; reason?: string }) {
  return <details className="adaptive-learning__source"><summary>原话与依据</summary>
    {source && <p>来源：{source.kind === 'conversation' ? '学习对话' : '题目讨论'}中的反馈</p>}
    {original ? <blockquote>{original}</blockquote> : <p className="form-hint">来源原话已不可用。</p>}
    {reason && <p>{reason}</p>}
  </details>;
}

function RuleEditor({ rule, disabled, onSave }: {
  rule: AdaptiveLearningRule; disabled: boolean;
  onSave: (configuration: AdaptiveLearningConfiguration, enabled: boolean) => void;
}) {
  const [configuration, setConfiguration] = useState(rule.configuration);
  const [enabled, setEnabled] = useState(rule.enabled);
  const changed = enabled !== rule.enabled || JSON.stringify(configuration) !== JSON.stringify(rule.configuration);
  const unavailable = !rule.source && !rule.enabled;
  return <details className="adaptive-learning__editor"><summary>编辑偏好</summary>
    <div className="adaptive-learning__fields">{fields.map(field => <label className="field" key={field.key}><span>{field.label}</span>
      <select value={configuration[field.key]} disabled={disabled} onChange={event => setConfiguration(current => {
        const next = { ...current, [field.key]: event.target.value } as AdaptiveLearningConfiguration;
        return allowedStart(next.method, next.start) ? next : { ...next, start: 'auto' };
      })}>
        {Object.entries(field.options).filter(([value]) => field.key !== 'start' || allowedStart(configuration.method, value)).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
    </label>)}</div>
    <label className="adaptive-learning__enabled"><input type="checkbox" checked={enabled} disabled={disabled || unavailable} onChange={event => setEnabled(event.target.checked)} />启用这条偏好</label>
    {unavailable && <p className="form-hint">来源原话已不可用，这条偏好保持停用。</p>}
    <button className="button button--quiet button--compact" type="button" disabled={disabled || !changed} onClick={() => onSave(configuration, enabled)}>保存偏好</button>
  </details>;
}

/** Changes here save independently of the surrounding default-settings form. */
export default function AdaptiveLearningSettings() {
  const [profile, setProfile] = useState<AdaptiveLearningProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [retryPayload, setRetryPayload] = useState<AdaptiveLearningChange | null>(null);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const request = useRef<AbortController | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    void refresh();
    return () => { alive.current = false; request.current?.abort(); request.current = null; };
  }, []);

  async function refresh() {
    if (request.current) return;
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError('');
    try {
      const value = await getAdaptiveLearning(controller.signal);
      if (!alive.current || controller.signal.aborted) return;
      setProfile(value); setRetryPayload(null); setNeedsRefresh(false);
    } catch {
      if (alive.current && !controller.signal.aborted) setError('无法读取个人学习偏好，请重试。');
    } finally {
      if (alive.current && !controller.signal.aborted) setBusy(false);
      if (request.current === controller) request.current = null;
    }
  }

  async function save(action: ChangeAction | null) {
    if (!profile || request.current || needsRefresh) return;
    const payload = action ? { ...action, expected_revision: profile.revision,
      request_key: crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}` } as AdaptiveLearningChange : retryPayload;
    if (!payload) return;
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError(''); setNotice('');
    try {
      const value = await changeAdaptiveLearning(payload, controller.signal);
      if (!alive.current || controller.signal.aborted) return;
      setProfile(value); setRetryPayload(null);
      setNotice(payload.action === 'accept' ? '已采纳，之后的自适应学习会参考这条偏好。'
        : payload.action === 'dismiss' ? '已忽略这条建议。'
          : payload.action === 'reconsider' ? '这条建议已回到待确认。'
          : payload.action === 'restore' ? '已恢复所选历史偏好。' : '个人学习偏好已保存。');
    } catch (reason) {
      if (!alive.current || controller.signal.aborted) return;
      if (reason instanceof ApiError && reason.status === 409) {
        setRetryPayload(null);
        try {
          const value = await getAdaptiveLearning(controller.signal);
          if (!alive.current || controller.signal.aborted) return;
          setProfile(value); setNeedsRefresh(false);
          setError('偏好已变化或适用情境已有其他偏好。已读取最新内容，请核对后再操作。');
        } catch {
          if (alive.current && !controller.signal.aborted) {
            setNeedsRefresh(true); setError('偏好已变化，暂时无法读取最新内容。请重新读取后再操作。');
          }
        }
      } else if (reason instanceof ApiError && reason.status !== null && reason.status >= 400 && reason.status < 500) {
        setRetryPayload(null);
        setError('这次偏好修改未保存，请检查适用情境和来源后再操作。');
      } else {
        setRetryPayload(payload);
        setError('保存结果尚未确认，请重试这次保存或重新读取偏好。');
      }
    } finally {
      if (alive.current && !controller.signal.aborted) setBusy(false);
      if (request.current === controller) request.current = null;
    }
  }

  const disabled = busy || Boolean(retryPayload) || needsRefresh;
  return <details className="adaptive-learning-settings">
    <summary>个人学习偏好{Boolean(profile?.drafts.length) && <span> · {profile!.drafts.length} 条待确认</span>}</summary>
    {!profile && !error && <p role="status">正在读取偏好…</p>}
    {profile && <>
      <div className="adaptive-learning__rules">
        {profile.rules.length === 0 && <p className="form-hint">还没有已确认偏好。</p>}
        {profile.rules.map(rule => <article className="adaptive-learning__rule" aria-label="已确认偏好" key={`${profile.revision}:${rule.id}`}>
          <p className="adaptive-learning__summary">{summary(rule.configuration)}{!rule.enabled && <span> · 已停用</span>}</p>
          <SourceDetails source={rule.source} original={rule.original_text} />
          <RuleEditor rule={rule} disabled={disabled} onSave={(configuration, enabled) => void save({ action: 'edit', rule_id: rule.id, configuration, enabled })} />
          <button className="button button--quiet button--compact" type="button" disabled={disabled} onClick={() => void save({ action: 'remove', rule_id: rule.id })}>删除偏好</button>
        </article>)}
      </div>
      {profile.drafts.length > 0 && <div className="adaptive-learning__drafts"><h4>待确认建议</h4>
        {profile.drafts.map(draft => <article className="adaptive-learning__draft" aria-label="待确认偏好" key={draft.id}>
          <p className="adaptive-learning__summary">{summary(draft.configuration)}</p>
          <SourceDetails source={draft.source} original={draft.original_text} reason={draft.reason} />
          {profile.rules.some(rule => rule.configuration.scenario === draft.configuration.scenario) && <p className="form-hint">采纳后会替换这个情境的现有偏好。</p>}
          <div className="adaptive-learning__actions">
            <button className="button button--quiet button--compact" type="button" disabled={disabled} onClick={() => void save({ action: 'accept', candidate_id: draft.id })}>采纳</button>
            <button className="button button--quiet button--compact" type="button" disabled={disabled} onClick={() => void save({ action: 'dismiss', candidate_id: draft.id })}>忽略</button>
          </div>
        </article>)}
      </div>}
      {profile.ignored?.length > 0 && <details className="adaptive-learning__ignored"><summary>已忽略建议</summary>
        {profile.ignored.map(draft => <article className="adaptive-learning__draft" aria-label="已忽略偏好" key={draft.id}>
          <p className="adaptive-learning__summary">{summary(draft.configuration)}</p>
          <SourceDetails source={draft.source} original={draft.original_text} reason={draft.reason} />
          <button className="button button--quiet button--compact" type="button" disabled={disabled} onClick={() => void save({ action: 'reconsider', candidate_id: draft.id })}>重新考虑</button>
        </article>)}
      </details>}
      {profile.history.length > 0 && <details className="adaptive-learning__history"><summary>偏好历史</summary>
        {profile.history.map(version => <article key={version.revision}>
          <p>{version.revision === 0 ? '初始状态' : <time dateTime={version.created_at}>{new Date(version.created_at).toLocaleString('zh-CN')}</time>}</p>
          {version.rules.length ? <ul>{version.rules.map(rule => <li key={rule.id}>{summary(rule.configuration)}{!rule.enabled && ' · 已停用'}</li>)}</ul> : <p>尚无个人偏好</p>}
          <button className="button button--quiet button--compact" type="button" disabled={disabled || version.revision === profile.revision} onClick={() => void save({ action: 'restore', version: version.revision })}>恢复这份偏好</button>
        </article>)}
      </details>}
    </>}
    {notice && <p role="status">{notice}</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {(retryPayload || needsRefresh || !profile && error) && <div className="adaptive-learning__actions">
      {retryPayload && <button type="button" className="button button--quiet button--compact" disabled={busy} onClick={() => void save(null)}>重试保存</button>}
      <button type="button" className="button button--quiet button--compact" disabled={busy} onClick={() => void refresh()}>重新读取偏好</button>
    </div>}
  </details>;
}
