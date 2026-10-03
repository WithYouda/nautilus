import { useEffect, useRef, useState } from 'react';
import { ApiError, getConversationState, putConversationState, type ConversationState, type ConversationStateValues, type MaterialKind } from './api';
import { getPreferences } from './preferences';
import type { SearchSelection } from './SearchControls';

const blank = (): ConversationStateValues => ({ leaf_id: null, paths: {}, source_scope: { mode: 'unspecified', version_ids: [] }, search_override: null });
type LegacyState = ConversationStateValues & { unreadable?: boolean };
const conflictMessage = '另一页面或设备已更新这段对话。已读取最新状态，草稿保留，请检查后重新操作。';
export const isStateConflict = (error: unknown) => error instanceof ApiError && error.status === 409 && (error.kind === 'conversation_state_conflict' || error.message.includes('conversation_state_conflict'));
export const isStateRejected = (error: unknown) => isStateConflict(error) || error instanceof ApiError && error.status === 409 && (error.kind === 'conversation_state_invalid' || error.message.includes('conversation_state_invalid'));

function legacy(kind: MaterialKind, identity: string, id: string, fallback: ConversationStateValues): LegacyState | null {
  const pathKey = `nautilus.reply-selection.v1:${kind === 'discussion' ? `discussion:${id}` : id}`;
  const materialKey = `nautilus.material-selection:${identity}:${kind}:${id}`;
  const searchKey = `nautilus.search-selection:${identity}:${kind}:${id}`;
  try {
    const leaf = localStorage.getItem(pathKey);
    const paths = localStorage.getItem(`${pathKey}:paths`);
    const source = localStorage.getItem(materialKey);
    const search = localStorage.getItem(searchKey);
    if (leaf === null && paths === null && source === null && search === null) return null;
    const value = { ...fallback, leaf_id: leaf ?? fallback.leaf_id, paths: paths ? JSON.parse(paths) : fallback.paths,
      source_scope: source ? JSON.parse(source) : fallback.source_scope, search_override: search ? JSON.parse(search) : fallback.search_override };
    if (!value.paths || typeof value.paths !== 'object' || Array.isArray(value.paths) || !Object.values(value.paths).every(item => typeof item === 'string') ||
        !value.source_scope || !['unspecified', 'reference', 'only'].includes(value.source_scope.mode) || !Array.isArray(value.source_scope.version_ids) || !value.source_scope.version_ids.every((item: unknown) => typeof item === 'string') ||
        value.search_override && !['off', 'external', 'native'].includes(value.search_override.mode)) return { ...fallback, unreadable: true };
    // Legacy query text is not part of a saved search choice.
    if (value.search_override) { const { mode, service_id, parameters } = value.search_override; value.search_override = { mode, ...(service_id ? { service_id } : {}), ...(parameters ? { parameters } : {}) }; }
    return value;
  } catch { return { ...fallback, unreadable: true }; }
}

export default function useConversationState(kind: MaterialKind, identity: string | null, id: string | null, onRefreshContent: () => Promise<void>) {
  const key = id && identity ? `${kind}:${identity}:${id}` : null;
  const [snapshot, setSnapshot] = useState<ConversationState>({ ...blank(), initialized: false, revision: 0, issues: [] });
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [migration, setMigration] = useState<LegacyState | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [defaults, setDefaults] = useState<SearchSelection>({ mode: 'off' });
  const [defaultsReady, setDefaultsReady] = useState(false);
  const stateRef = useRef(snapshot);
  const keyRef = useRef(key); keyRef.current = key;
  const loadedRef = useRef<string | null>(null);
  const refreshContent = useRef(onRefreshContent); refreshContent.current = onRefreshContent;
  const saving = useRef(false);
  const newStates = useRef(new Map<string, ConversationState>());
  const apply = (value: ConversationState, expectedKey: string | null) => {
    if (keyRef.current !== expectedKey) return;
    if (loadedRef.current === expectedKey && stateRef.current.revision > value.revision) return;
    stateRef.current = value; loadedRef.current = expectedKey; setSnapshot(value); setLoadedKey(expectedKey);
    // React holds the cache. Once server state exists, retire this browser's
    // migration sources so deleted settings cannot be offered for import again.
    if (expectedKey && value.initialized && id && identity) try {
      const pathKey = `nautilus.reply-selection.v1:${kind === 'discussion' ? `discussion:${id}` : id}`;
      for (const obsolete of [pathKey, `${pathKey}:paths`, `nautilus.material-selection:${identity}:${kind}:${id}`, `nautilus.search-selection:${identity}:${kind}:${id}`]) localStorage.removeItem(obsolete);
    } catch { /* Server remains authoritative; unavailable browser storage is never a fallback. */ }
  };
  useEffect(() => {
    let active = true;
    const load = async () => {
      try { const value = await getPreferences(); if (active) { setDefaults(value.search); setDefaultsReady(true); } }
      catch { if (active) { setDefaultsReady(false); setError('默认设置无法读取，请重试；暂不发送消息。'); } }
    };
    void load(); window.addEventListener('nautilus:preferences-changed', load);
    return () => { active = false; window.removeEventListener('nautilus:preferences-changed', load); };
  }, [identity]);

  useEffect(() => {
    let active = true;
    setMigration(null); setError(''); setNotice(''); setBusy(false); saving.current = false;
    loadedRef.current = null; setLoadedKey(null);
    if (!key || !id || !identity) {
      const value = { ...blank(), initialized: false, revision: 0, issues: [] };
      stateRef.current = value; setSnapshot(value);
      return;
    }
    const load = async () => {
      try {
        let value = await getConversationState(kind, id);
        if (!active) return;
        if (!value.initialized) {
          const old = legacy(kind, identity, id, value);
          if (old) { apply(value, key); setMigration(old); return; }
          try { value = await putConversationState(kind, id, value, 0); }
          catch (reason) { if (!isStateConflict(reason)) throw reason; value = await getConversationState(kind, id); }
        }
        if (active) apply(value, key);
      } catch (reason) { if (active) setError(reason instanceof Error ? reason.message : '当前学习状态无法读取，请重试。'); }
    };
    void load();
    return () => { active = false; };
  }, [key, kind, id, identity]);

  async function reload(conflict = false, targetId = id) {
    const target = keyRef.current;
    if (!targetId || !target || !target.endsWith(`:${targetId}`)) return;
    try {
      const value = await getConversationState(kind, targetId);
      if (keyRef.current !== target) return;
      apply(value, target); setMigration(null); setError('');
      await refreshContent.current();
      if (keyRef.current === target && conflict) setNotice(conflictMessage);
    } catch { if (keyRef.current === target) { loadedRef.current = null; setLoadedKey(null); setError('最新学习状态暂时无法读取，请重试；草稿保留。'); } }
  }
  async function save(patch: Partial<ConversationStateValues>, initial = false) {
    if (patch.source_scope) {
      const { image_version_ids, ...scope } = patch.source_scope;
      const selectedImages = image_version_ids?.filter(version => scope.version_ids.includes(version));
      patch = { ...patch, source_scope: { ...scope, ...(selectedImages?.length ? { image_version_ids: [...new Set(selectedImages)] } : {}) } };
    }
    if (!id || !key) {
      const value = { ...stateRef.current, ...patch }; stateRef.current = value; setSnapshot(value); return true;
    }
    if (saving.current || loadedRef.current !== key) return false;
    const target = key;
    saving.current = true; setBusy(true); setError(''); setNotice('');
    try {
      const value = await putConversationState(kind, id, { ...stateRef.current, ...patch }, initial ? 0 : stateRef.current.revision);
      if (keyRef.current === target) { apply(value, target); setMigration(null); }
      return true;
    } catch (reason) {
      if (keyRef.current !== target) return false;
      if (isStateConflict(reason)) await reload(true);
      else setError(reason instanceof Error ? `状态未保存：${reason.message}` : '状态未保存，请重试。');
      return false;
    } finally { if (keyRef.current === target) { saving.current = false; setBusy(false); } }
  }
  // Called only for a newly created conversation, before it is activated.
  async function initializeNew(targetId: string, values?: Partial<ConversationStateValues>) {
    const existing = await getConversationState(kind, targetId);
    const value = existing.initialized ? existing : await putConversationState(kind, targetId, { ...blank(), source_scope: stateRef.current.source_scope,
      search_override: stateRef.current.search_override, ...values }, 0);
    newStates.current.set(targetId, value);
    return value;
  }
  function revisionFor(targetId: string) {
    if (id === targetId && loadedRef.current === key && stateRef.current.initialized) return stateRef.current.revision;
    const fresh = newStates.current.get(targetId);
    if (fresh) return fresh.revision;
    throw new Error('正在读取当前学习状态，请稍后重新发送。');
  }
  async function retryLoad() {
    try { const value = await getPreferences(); setDefaults(value.search); setDefaultsReady(true); } catch { setError('默认设置无法读取，请重试。'); return; }
    if (id && key && identity && !stateRef.current.initialized) {
      try {
        let value = await getConversationState(kind, id);
        if (keyRef.current !== key) return;
        if (!value.initialized) {
          const old = legacy(kind, identity, id, value);
          if (old) { apply(value, key); setMigration(old); setError(''); return; }
          try { value = await putConversationState(kind, id, value, 0); }
          catch (reason) { if (!isStateConflict(reason)) throw reason; value = await getConversationState(kind, id); }
        }
        apply(value, key); setError('');
      } catch { setError('当前学习状态无法读取，请重试；草稿保留。'); }
      return;
    }
    await reload();
  }
  const ready = defaultsReady && (!key || (loadedKey === key && snapshot.initialized && !migration)) && !busy;
  const preview = migration ? { ...snapshot, ...migration } : snapshot;
  return { snapshot: preview, sourceScope: preview.source_scope, ready, busy, migration, error, notice,
    blocked: !ready || snapshot.issues.length > 0,
    search: { value: preview.search_override ?? defaults, overridden: preview.search_override !== null, ready,
      change: (value: SearchSelection) => { void save({ search_override: value }); }, reset: () => { void save({ search_override: null }); }, error: '' },
    save, reload, retryLoad, initializeNew, revisionFor,
    confirmMigration: () => migration && !migration.unreadable && void save(migration, true),
    discardMigration: () => void save({ ...blank(), leaf_id: snapshot.leaf_id }, true),
  };
}
