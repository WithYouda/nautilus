import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { coachHref, navigateCoach } from './background-coach-api';
import { browserNotificationState, coachKey, dispatchCoachReminder, getCoachReminders, resolveCoachReminder, type CoachReminder, type CoachReminderView } from './coach-conversation-api';
import './styles/coach-conversation.css';

export default function CoachReminderHost() {
  const [shown, setShown] = useState<CoachReminder[]>([]), [error, setError] = useState(''), [opening, setOpening] = useState<string | null>(null);
  const [channelNotice, setChannelNotice] = useState('');
  const notifications = useRef(new Map<string, Notification>()), closed = useRef(new Set<string>()), claimKeys = useRef(new Map<string, string>());
  const refreshRef = useRef<() => void>(() => {}), alive = useRef(true);
  async function open(item: CoachReminder) {
    setOpening(item.id); setError('');
    try {
      const { target } = await resolveCoachReminder(item);
      if (!alive.current) return;
      if (target.kind === 'coach') window.dispatchEvent(new Event('nautilus:open-coach-room'));
      else { const href = coachHref(target.href); if (!href) throw new Error('当前安排入口暂时不可用。'); navigateCoach(href); }
    } catch (reason) { if (alive.current) setError(reason instanceof Error ? reason.message : '当前安排已变化，请重新查看。'); }
    finally { if (alive.current) { setOpening(null); refreshRef.current(); } }
  }
  useEffect(() => {
    alive.current = true;
    let running = false, repeat = false, active = true;
    const controller = new AbortController();
    function clean(view: CoachReminderView) {
      const current = new Map([...view.due, ...view.recent].map(item => [item.id, item]));
      const valid = new Set([...current.values()].filter(item => item.status === 'pending' || item.status === 'dispatched').map(item => item.id));
      if (!view.settings.enabled || view.learning_active || view.quiet_now) valid.clear();
      setShown(previous => previous.filter(item => valid.has(item.id) && current.get(item.id)?.source_revision === item.source_revision));
      for (const [id, notification] of notifications.current) if (!valid.has(id)) { notification.close(); notifications.current.delete(id); }
    }
    async function refresh() {
      if (running) { repeat = true; return; }
      running = true;
      try {
        let view = await getCoachReminders(controller.signal);
        if (!active) return;
        clean(view);
        if (!view.settings.enabled || view.learning_active || view.quiet_now) return;
        for (const item of view.due) {
          if (item.status !== 'pending') continue;
          const key = claimKeys.current.get(item.id) ?? coachKey(); claimKeys.current.set(item.id, key);
          const result = await dispatchCoachReminder(item, key);
          if (!active) return;
          view = result.view; clean(view);
          if (!result.claimed || !result.reminder || result.reminder.status !== 'dispatched' || !view.settings.enabled || view.learning_active || view.quiet_now) continue;
          const reminder = result.reminder;
          if (!closed.current.has(reminder.id)) setShown(previous => previous.some(value => value.id === reminder.id) ? previous : [...previous, reminder]);
          if (view.settings.browser_enabled && browserNotificationState() === 'granted') {
            try { const notification = new Notification(reminder.title, { body: reminder.body, tag: `nautilus-reminder:${reminder.id}` }); setChannelNotice(''); notifications.current.set(reminder.id, notification); notification.onclick = () => { notification.close(); window.focus(); void open(reminder); }; notification.onclose = () => notifications.current.delete(reminder.id); }
            catch { setChannelNotice('浏览器通知未能显示，应用内提醒仍可用。'); }
          }
        }
      } catch { /* Reconnect on the next poll or explicit state refresh. */ }
      finally { running = false; if (repeat && active) { repeat = false; void refresh(); } }
    }
    refreshRef.current = () => void refresh();
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    const visible = () => { if (document.visibilityState === 'visible') void refresh(); };
    const changed = () => void refresh();
    document.addEventListener('visibilitychange', visible);
    window.addEventListener('focus', changed); window.addEventListener('nautilus:coach-reminder-settings-changed', changed); window.addEventListener('nautilus:learning-state-changed', changed); window.addEventListener('popstate', changed);
    return () => { active = false; alive.current = false; controller.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', visible); window.removeEventListener('focus', changed); window.removeEventListener('nautilus:coach-reminder-settings-changed', changed); window.removeEventListener('nautilus:learning-state-changed', changed); window.removeEventListener('popstate', changed); for (const notification of notifications.current.values()) notification.close(); notifications.current.clear(); };
  }, []);
  if (!shown.length) return null;
  return <aside className="coach-reminder-host" aria-label="学习提醒" aria-live="polite">{shown.map(item => <article className="coach-reminder" key={item.id} data-coach-reminder={item.id}>
    <button className="icon-button" type="button" aria-label="关闭当前提示" title="关闭当前提示" onClick={() => { closed.current.add(item.id); setShown(previous => previous.filter(value => value.id !== item.id)); notifications.current.get(item.id)?.close(); notifications.current.delete(item.id); }}><X size={15} /></button>
    <h2>{item.title}</h2><p>{item.body}</p><div className="coach-reminder__actions"><button className="button button--quiet button--compact" type="button" disabled={Boolean(opening)} onClick={() => void open(item)}>{opening === item.id ? '正在核对…' : item.target.label}</button><button className="text-button" type="button" onClick={() => window.dispatchEvent(new Event('nautilus:open-coach-reminder-settings'))}>提醒设置</button></div>
  </article>)}{channelNotice && <p className="coach-reminder-channel" role="status">{channelNotice}</p>}{error && <p className="form-error" role="alert">{error}</p>}</aside>;
}
