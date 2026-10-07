import { useEffect, useRef, useState } from 'react';
import { getPersonaScope, putPersonaScope, type PersonaScope } from './persona-api';

const sources = { global: '全局', plan: '计划', task: '任务', conversation: '当前对话', discussion: '当前对话' };
export default function PersonaScopeControl({ kind, id, disabled = false }: { kind: string; id: string; disabled?: boolean }) {
  const [saved, setSaved] = useState<PersonaScope | null>(null);
  const [selection, setSelection] = useState('inherit');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const epoch = useRef(0);
  async function load() {
    const current = ++epoch.current;
    setBusy(true); setError(''); setMessage('');
    try {
      const next = await getPersonaScope(kind, id);
      if (current === epoch.current) { setSaved(next); setSelection(next.selection ?? 'none'); }
    } catch (reason) { if (current === epoch.current) setError(reason instanceof Error ? reason.message : '人格暂时无法读取'); }
    finally { if (current === epoch.current) setBusy(false); }
  }
  useEffect(() => {
    setSaved(null);
    void load();
    return () => { epoch.current++; };
  }, [kind, id]);
  async function save() {
    if (!saved) return;
    const current = ++epoch.current;
    setBusy(true); setError(''); setMessage('');
    try {
      const next = await putPersonaScope(kind, id, selection === 'none' ? null : selection, saved.revision);
      if (current === epoch.current) { setSaved(next); setMessage('人格已保存'); }
    } catch (reason) { if (current === epoch.current) setError(reason instanceof Error ? reason.message : '人格暂时无法保存'); }
    finally { if (current === epoch.current) setBusy(false); }
  }
  return <section className="model-control" aria-label="当前范围人格">
    <label><span>人格</span><select aria-label="人格选择" value={selection} disabled={disabled || busy || !saved} onChange={event => { setSelection(event.target.value); setMessage(''); }}>
      <option value="inherit">沿用上级</option><option value="none">不用人格</option>
      {saved?.profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
    </select></label>
    {saved && <p className="model-control__summary">当前：{saved.effective?.name ?? '不用人格'} · 来自{sources[saved.source]}</p>}
    <button type="button" className="button button--quiet" disabled={disabled || busy || !saved} onClick={() => void save()}>保存人格</button>
    {error ? <p role="alert">{error} <button type="button" className="text-button" disabled={busy} onClick={() => void load()}>刷新人格</button></p> : message && <p role="status">{message}</p>}
  </section>;
}
