import { useEffect, useRef, useState } from 'react';
import { ApiError } from './api';
import { coachHref, navigateCoach } from './background-coach-api';
import { browserNotificationState, coachKey, getCoachReminderHistory, getCoachReminderSettings, resolveCoachReminder, saveCoachReminderSettings, type CoachReminder, type CoachReminderSettings } from './coach-conversation-api';
import './styles/coach-conversation.css';

type Draft = Omit<CoachReminderSettings, 'revision'>;
type Save = Draft & { expected_revision: number; request_key: string };
const localTimezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
const days = ['一', '二', '三', '四', '五', '六', '日'];

export default function CoachReminderSettings() {
  const [settings, setSettings] = useState<CoachReminderSettings | null>(null), [draft, setDraft] = useState<Draft | null>(null), [busy, setBusy] = useState(false), [conflict, setConflict] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [permission, setPermission] = useState(browserNotificationState), [permissionBusy, setPermissionBusy] = useState(false);
  const [history, setHistory] = useState<CoachReminder[] | null>(null), [historyError, setHistoryError] = useState(''), [openingHistory, setOpeningHistory] = useState<string | null>(null);
  const historyGeneration = useRef(0);
  const [historyBefore, setHistoryBefore] = useState<number | null>(null), [historyBusy, setHistoryBusy] = useState(false);
  const alive = useRef(true), attempt = useRef<Save | null>(null);
  function accept(value: CoachReminderSettings) { const { revision: _revision, ...fields } = value; setSettings(value); setDraft(fields); attempt.current = null; setConflict(false); }
  async function load() {
    setBusy(true); setError('');
    try { const result = await getCoachReminderSettings(); if (alive.current) accept(result); }
    catch (reason) { if (alive.current) setError(reason instanceof Error ? reason.message : '无法读取学习提醒设置。'); }
    finally { if (alive.current) setBusy(false); }
  }
  useEffect(() => { alive.current = true; void load(); const refresh = () => setPermission(browserNotificationState()); window.addEventListener('focus', refresh); return () => { alive.current = false; historyGeneration.current++; window.removeEventListener('focus', refresh); }; }, []);
  const locked = busy || Boolean(attempt.current) || conflict;
  const dirty = Boolean(settings && draft && Object.entries(draft).some(([key, value]) => JSON.stringify(settings[key as keyof Draft]) !== JSON.stringify(value)));
  function edit(next: Partial<Draft>) { setDraft(previous => previous ? { ...previous, ...next } : previous); setNotice(''); }
  async function save() {
    if (!settings || !draft || locked && !attempt.current) return;
    if (draft.study_times.some(item => !item.time || !item.weekdays.length)) { setError('请为每个学习时间选择时刻和星期，或移除空白时间。'); return; }
    if (draft.quiet_enabled && draft.quiet_start === draft.quiet_end) { setError('免打扰的开始和结束时间需要不同。'); return; }
    attempt.current ??= { ...draft, expected_revision: settings.revision, request_key: coachKey() };
    setBusy(true); setError(''); setNotice('');
    try { const result = await saveCoachReminderSettings(attempt.current); if (!alive.current) return; accept(result.settings); setNotice(result.settings.enabled ? '学习提醒已保存。' : '学习提醒已暂停。'); window.dispatchEvent(new Event('nautilus:coach-reminder-settings-changed')); }
    catch (reason) { if (!alive.current) return; setError(reason instanceof Error ? reason.message : '保存结果尚未确认，请重试这次保存。'); if (reason instanceof ApiError && reason.status !== null) { attempt.current = null; if (reason.status === 409) { setConflict(true); setError('提醒设置已在其他页面变化。输入已保留，请读取最新设置后核对。'); } } }
    finally { if (alive.current) setBusy(false); }
  }
  async function authorizeBrowser() {
    if (permission === 'unsupported' || permissionBusy) return;
    setPermissionBusy(true); setError('');
    try { await Notification.requestPermission(); if (alive.current) setPermission(browserNotificationState()); }
    catch { if (alive.current) setError('浏览器通知授权未成功，应用内提醒仍可使用。'); }
    finally { if (alive.current) setPermissionBusy(false); }
  }
  async function loadHistory(more = false) {
    if (more && (historyBusy || historyBefore === null)) return;
    const generation = ++historyGeneration.current; if (!more) setHistory(null); setHistoryError(''); setHistoryBusy(true);
    try {
      const page = await getCoachReminderHistory(more ? historyBefore! : undefined);
      if (alive.current && historyGeneration.current === generation) { setHistory(previous => [...(more ? previous ?? [] : []), ...page.items]); setHistoryBefore(page.next_before); }
    } catch (reason) { if (alive.current && historyGeneration.current === generation) setHistoryError(reason instanceof Error ? reason.message : '无法读取提醒记录。'); }
    finally { if (alive.current && historyGeneration.current === generation) setHistoryBusy(false); }
  }
  async function openHistory(item: CoachReminder) {
    const generation = historyGeneration.current; setOpeningHistory(item.id); setHistoryError('');
    try { const { target } = await resolveCoachReminder(item); if (!alive.current || generation !== historyGeneration.current) return; if (target.kind === 'coach') window.dispatchEvent(new Event('nautilus:open-coach-room')); else { const href = coachHref(target.href); if (!href) throw new Error('当前入口暂时不可用。'); navigateCoach(href); } }
    catch (reason) { if (alive.current && generation === historyGeneration.current) setHistoryError(reason instanceof Error ? reason.message : '这个安排已变化，请重新查看。'); }
    finally { if (alive.current && generation === historyGeneration.current) setOpeningHistory(null); }
  }
  return <section className="coach-reminder-settings" id="coach-reminder-settings" aria-label="学习提醒设置">
    <h3>学习提醒</h3><p>按学习时间和当前安排提醒你。</p>
    {!draft && !error && <p role="status">正在读取提醒设置…</p>}
    {draft && <>
      <label className="background-coach-settings__switch"><input type="checkbox" checked={draft.enabled} disabled={locked} onChange={event => edit({ enabled: event.target.checked, ...(event.target.checked && settings?.revision === 0 ? { timezone: localTimezone() } : {}) })} />开启学习提醒</label>
      <div className="coach-reminder-settings__times">{draft.study_times.map((item, index) => <div className="coach-reminder-settings__time" key={item.id}>
        <label><span className="sr-only">学习时间 {index + 1}</span><input type="time" aria-label={`学习时间 ${index + 1}`} value={item.time} disabled={locked} onChange={event => edit({ study_times: draft.study_times.map(value => value.id === item.id ? { ...value, time: event.target.value } : value) })} /></label>
        <div className="coach-reminder-settings__days" aria-label={`学习时间 ${index + 1} 的星期`}>{days.map((day, i) => <button type="button" key={day} aria-label={`星期${day}`} aria-pressed={item.weekdays.includes(i + 1)} disabled={locked} onClick={() => edit({ study_times: draft.study_times.map(value => value.id === item.id ? { ...value, weekdays: value.weekdays.includes(i + 1) ? value.weekdays.filter(number => number !== i + 1) : [...value.weekdays, i + 1].sort((a, b) => a - b) } : value) })}>{day}</button>)}</div>
        <button className="text-button" type="button" disabled={locked} aria-label={`移除学习时间 ${index + 1}`} onClick={() => edit({ study_times: draft.study_times.filter(value => value.id !== item.id) })}>移除</button>
      </div>)}</div>
      <button className="text-button" type="button" disabled={locked || draft.study_times.length >= 14} onClick={() => edit({ study_times: [...draft.study_times, { id: coachKey(), weekdays: [1, 2, 3, 4, 5, 6, 7], time: '' }] })}>添加学习时间</button>
      {!draft.study_times.length && <p className="form-hint">未设固定时间时，跟随当前已确认的具体安排。</p>}
      <details><summary>提醒频率与免打扰</summary><div className="background-coach-settings__grid">
        <label className="background-coach-settings__switch"><input type="checkbox" checked={draft.followup_enabled} disabled={locked} onChange={event => edit({ followup_enabled: event.target.checked })} />未开始时追加一次</label>
        <label className="field"><span>追加间隔（分钟）</span><input type="number" min={1} max={1440} step={1} value={draft.followup_delay_minutes} disabled={locked || !draft.followup_enabled} onChange={event => edit({ followup_delay_minutes: Number(event.target.value) })} /></label>
        <label className="field"><span>每天最多提醒（次）</span><input type="number" min={1} max={100} step={1} value={draft.max_per_day} disabled={locked} onChange={event => edit({ max_per_day: Number(event.target.value) })} /></label>
        <label className="field"><span>提醒时区</span><input value={draft.timezone} disabled={locked} onChange={event => edit({ timezone: event.target.value })} /></label>
        <label className="background-coach-settings__switch"><input type="checkbox" checked={draft.quiet_enabled} disabled={locked} onChange={event => edit({ quiet_enabled: event.target.checked })} />免打扰</label>
        <div className="coach-reminder-settings__time"><label className="field"><span>从</span><input type="time" aria-label="免打扰开始" value={draft.quiet_start} disabled={locked || !draft.quiet_enabled} onChange={event => edit({ quiet_start: event.target.value })} /></label><label className="field"><span>到</span><input type="time" aria-label="免打扰结束" value={draft.quiet_end} disabled={locked || !draft.quiet_enabled} onChange={event => edit({ quiet_end: event.target.value })} /></label></div>
      </div><button className="text-button" type="button" disabled={locked} onClick={() => edit({ timezone: localTimezone() })}>使用本机时区（{localTimezone()}）</button></details>
      <div className="coach-reminder-settings__channel"><label className="background-coach-settings__switch"><input type="checkbox" checked={draft.browser_enabled} disabled={locked || permission === 'unsupported'} onChange={event => edit({ browser_enabled: event.target.checked })} />同时使用浏览器通知</label>
        <p className="form-hint">{permission === 'unsupported' ? '当前地址或浏览器不支持系统通知，应用内提醒仍可使用。' : permission === 'granted' ? '浏览器已授权。应用打开时可发送通知。' : permission === 'denied' ? '浏览器已拒绝通知，可在浏览器的站点设置中调整。应用内提醒仍可使用。' : '浏览器通知需要你的授权。'}</p>
        {permission === 'default' && <button className="button button--quiet button--compact" type="button" disabled={permissionBusy} onClick={() => void authorizeBrowser()}>{permissionBusy ? '等待浏览器授权…' : '授权浏览器通知'}</button>}
      </div>
      <div className="background-coach__actions"><button className="button button--quiet button--compact" type="button" disabled={busy || !dirty || conflict} onClick={() => void save()}>{busy ? '保存中…' : attempt.current ? '重试这次保存' : '保存提醒设置'}</button>{(conflict || error) && <button className="text-button" type="button" disabled={busy} onClick={() => void load()}>读取最新提醒设置</button>}</div>
      <details onToggle={event => { if (event.currentTarget.open) void loadHistory(); else historyGeneration.current++; }}><summary>提醒记录</summary>
        {!history && !historyError && <p role="status">正在读取提醒记录…</p>}
        {history?.length === 0 && <p className="form-hint">还没有提醒记录。</p>}
        {history?.map(item => <article className="coach-reminder-settings__history" key={item.id}><strong>{item.title}</strong><small>{new Date(item.dispatched_at ?? item.scheduled_at).toLocaleString('zh-CN', { timeZone: settings?.timezone, dateStyle: 'short', timeStyle: 'short' })} · {({ dispatched: '已提醒', pending: '等待提醒', suppressed: '已停止提醒', unavailable: '安排已变化' })[item.status]}</small><button className="text-button" type="button" disabled={Boolean(openingHistory) || item.status !== 'dispatched'} onClick={() => void openHistory(item)}>{openingHistory === item.id ? '正在核对…' : item.target.label}</button></article>)}
        {historyBefore !== null && <button className="text-button" type="button" disabled={historyBusy} onClick={() => void loadHistory(true)}>{historyBusy ? "正在读取…" : "查看更早提醒"}</button>}
        {historyError && <p className="form-error" role="alert">{historyError}<button className="text-button" type="button" onClick={() => void loadHistory()}>重读提醒记录</button></p>}
      </details>
    </>}
    {notice && <p role="status">{notice}</p>}{error && <p className="form-error" role="alert">{error}{!draft && <button className="text-button" type="button" onClick={() => void load()}>重试读取</button>}</p>}
  </section>;
}
