import { useEffect, useRef, useState } from 'react';
import { getPreferences } from './preferences';
import type { SearchSelection } from './SearchControls';

export function writeConversationSearch(kind: string, identity: string, id: string, selection: SearchSelection) {
  try { localStorage.setItem(`nautilus.search-selection:${identity}:${kind}:${id}`, JSON.stringify(selection)); } catch { /* Current selection remains usable. */ }
}

// Defaults are account settings; overrides belong to one conversation on this browser.
export default function useConversationSearch(kind: string, identity: string | null, id: string | null) {
  const key = identity && id ? `nautilus.search-selection:${identity}:${kind}:${id}` : null;
  const [value, setValue] = useState<SearchSelection>({ mode: 'off' });
  const [overridden, setOverridden] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const defaults = useRef<SearchSelection>({ mode: 'off' });
  const override = useRef<SearchSelection | null>(null);
  const previousKey = useRef<string | null>(null);
  useEffect(() => {
    let active = true;
    const pending = previousKey.current === null ? override.current : null;
    previousKey.current = key;
    let saved: SearchSelection | null = pending;
    if (key) {
      try {
        const raw = localStorage.getItem(key);
        const parsed = raw ? JSON.parse(raw) : null;
        if (parsed && ['off', 'external', 'native'].includes(parsed.mode)) saved = parsed;
        else if (pending) localStorage.setItem(key, JSON.stringify(pending));
      } catch { /* Current in-memory choice remains usable. */ }
    }
    override.current = saved;
    setOverridden(Boolean(saved)); setValue(saved ?? { mode: 'off' }); setReady(false);
    const load = async () => {
      try {
        const preferences = await getPreferences();
        if (!active) return;
        defaults.current = preferences.search;
        setValue(override.current ?? preferences.search); setError('');
      } catch { if (active) setError('默认设置暂时无法读取；当前联网保持关闭，可手动选择。'); }
      finally { if (active) setReady(true); }
    };
    void load(); window.addEventListener('nautilus:preferences-changed', load);
    return () => { active = false; window.removeEventListener('nautilus:preferences-changed', load); };
  }, [key]);
  const change = (selection: SearchSelection) => {
    override.current = selection; setValue(selection); setOverridden(true);
    if (key) try { localStorage.setItem(key, JSON.stringify(selection)); } catch { /* In-memory override remains. */ }
  };
  const reset = () => {
    override.current = null; setValue(defaults.current); setOverridden(false);
    if (key) try { localStorage.removeItem(key); } catch { /* In-memory default remains. */ }
  };
  return { value, change, reset, overridden, ready, error };
}
