import { useEffect, useRef, useState } from 'react';
import { ApiError } from './api';
import { coachKey, getCoachSettings, saveCoachSettings, type CoachSettings } from './background-coach-api';
import './styles/background-coach.css';

const localTimezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
type Draft = Omit<CoachSettings, 'revision'>;
type Save = Draft & { expected_revision: number; request_key: string };

export default function BackgroundCoachSettings() {
  const [settings, setSettings] = useState<CoachSettings | null>(null), [draft, setDraft] = useState<Draft | null>(null), [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false), [conflict, setConflict] = useState(false);
  const attempt = useRef<Save | null>(null), alive = useRef(true);
  function accept(value: CoachSettings) { const { revision: _revision, ...fields } = value; setSettings(value); setDraft(fields); attempt.current = null; setConflict(false); }
  async function load() {
    setBusy(true); setError('');
    try { const value = await getCoachSettings(); if (alive.current) accept(value); }
    catch (reason) { if (alive.current) setError(reason instanceof Error ? reason.message : '无法读取教练设置。'); }
    finally { if (alive.current) setBusy(false); }
  }
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; }; }, []);
  async function save() {
    if (!settings || !draft || busy || conflict) return;
    attempt.current ??= { ...draft, expected_revision: settings.revision, request_key: coachKey() };
    setBusy(true); setError(''); setNotice('');
    try {
      const value = await saveCoachSettings(attempt.current);
      if (!alive.current) return;
      accept(value); setNotice(value.enabled ? '自动复盘设置已保存。' : '自动复盘已关闭，新自动调用已停止。');
      window.dispatchEvent(new Event('nautilus:coach-settings-changed'));
    } catch (reason) {
      if (!alive.current) return;
      setError(reason instanceof Error ? reason.message : '保存结果尚未确认，可重试这次保存。');
      if (reason instanceof ApiError && reason.status !== null) { attempt.current = null; if (reason.status === 409) { setConflict(true); setError('教练设置已在其他页面变化。你的输入已保留，请读取最新设置后核对。'); } }
    } finally { if (alive.current) setBusy(false); }
  }
  const changed = Boolean(settings && draft && Object.entries(draft).some(([key, value]) => settings[key as keyof Draft] !== value));
  return <section className="background-coach-settings" id="background-coach-settings" aria-label="后台教练设置">
    <h3>后台教练</h3><p>在停顿或返回时复盘有效记录，建议会出现在首页和对应计划。</p>
    {!draft && !error && <p role="status">正在读取教练设置…</p>}
    {draft && <><label className="background-coach-settings__switch"><input type="checkbox" checked={draft.enabled} disabled={busy || !!attempt.current || conflict} onChange={event => setDraft(previous => previous ? { ...previous, enabled: event.target.checked, ...(!settings?.enabled && event.target.checked && settings?.revision === 0 && previous.timezone === 'UTC' ? { timezone: localTimezone() } : {}) } : previous)} />自动复盘</label>
      <p className="form-hint">关闭时仍可手动复盘。普通建议不在学习中弹窗。</p>
      <details><summary>调用限额与时区</summary>
        <div className="background-coach-settings__grid">
          <label className="field"><span>每会话自动复盘最多（次）</span><input type="number" min="1" step="1" value={draft.max_calls_per_session} disabled={busy || !!attempt.current || conflict} onChange={event => setDraft(previous => previous ? { ...previous, max_calls_per_session: Number(event.target.value) } : previous)} /></label>
          <label className="field"><span>每天自动复盘最多（次）</span><input type="number" min="1" step="1" value={draft.max_calls_per_day} disabled={busy || !!attempt.current || conflict} onChange={event => setDraft(previous => previous ? { ...previous, max_calls_per_day: Number(event.target.value) } : previous)} /></label>
          <label className="field"><span>自动复盘间隔至少（分钟）</span><input type="number" min="30" step="1" value={draft.cooldown_minutes} disabled={busy || !!attempt.current || conflict} onChange={event => setDraft(previous => previous ? { ...previous, cooldown_minutes: Number(event.target.value) } : previous)} /></label>
          <label className="field"><span>每日计数时区</span><input value={draft.timezone} disabled={busy || !!attempt.current || conflict} onChange={event => setDraft(previous => previous ? { ...previous, timezone: event.target.value } : previous)} /></label>
        </div>
        <p className="form-hint">已发送的失败或取消调用也计次数。手动复盘不受自动频率限额约束。</p>
        <button className="text-button" type="button" disabled={busy || !!attempt.current || conflict} onClick={() => setDraft(previous => previous ? { ...previous, timezone: localTimezone() } : previous)}>使用本机时区（{localTimezone()}）</button>
      </details>
      <p className="form-hint">{changed ? '待保存时区' : '保存时区'}：{draft.timezone}</p>
      <div className="background-coach__actions"><button className="button button--quiet button--compact" type="button" disabled={busy || !changed || conflict} onClick={() => void save()}>{busy ? '保存中…' : attempt.current ? '重试这次保存' : '保存教练设置'}</button>{(conflict || error) && <button className="text-button" type="button" disabled={busy} onClick={() => void load()}>读取最新教练设置</button>}</div>
    </>}
    {notice && <p role="status">{notice}</p>}{error && <p className="form-error" role="alert">{error}{!draft && <button className="text-button" type="button" onClick={() => void load()}>重试读取</button>}</p>}
  </section>;
}
