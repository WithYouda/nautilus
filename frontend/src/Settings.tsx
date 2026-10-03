import { useEffect, useState, type FormEvent } from 'react';
import type { AiProvider } from './api';
import DialogPortal from './DialogPortal';
import SearchControls from './SearchControls';
import { getPreferences, savePreferences, type ConflictPolicy, type UserPreferences } from './preferences';
import './styles/settings.css';
import { DiagnosticSettings } from './Diagnostics';
import ObsidianSettings from './ObsidianSettings';
import ImageModelSettings from './ImageModelSettings';

export type SettingsSection = 'general' | 'search' | 'provider';
const initial: UserPreferences = { conflict_policy: 'ask', search: { mode: 'off' } };

export default function Settings({ open, section, provider, onClose, onOpenSearchSettings, onOpenProviderSettings }: {
  open: boolean; section: SettingsSection; provider: AiProvider | null; onClose: () => void;
  onOpenSearchSettings: () => void; onOpenProviderSettings: () => void;
}) {
  const [draft, setDraft] = useState<UserPreferences>(initial);
  const [baseline, setBaseline] = useState<UserPreferences>(initial);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true); setLoaded(false); setError('');
    void getPreferences().then(value => { if (active) { setDraft(value); setBaseline(value); setLoaded(true); } })
      .catch(cause => { if (active) setError(cause instanceof Error ? cause.message : '无法读取学习设置。'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open]);
  if (!open) return null;
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);
  const close = () => { if (!dirty || window.confirm('有未保存的设置，确定放弃修改吗？')) onClose(); };
  const save = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setError('');
    try { const value = await savePreferences(draft); setDraft(value); setBaseline(value); }
    catch (cause) { setError(cause instanceof Error ? cause.message : '保存失败。'); }
    finally { setSaving(false); }
  };
  return <DialogPortal><div className="dialog-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) close(); }}>
    <section className="unified-settings-dialog" role="dialog" aria-modal="true" aria-labelledby="unified-settings-title">
      <header className="dialog-header"><div><p className="eyebrow">NAUTILUS SETTINGS</p><h2 id="unified-settings-title">设置</h2></div><button className="icon-button" type="button" onClick={close} aria-label="关闭设置">×</button></header>
      {loading ? <p className="unified-settings-loading">正在加载设置…</p> : !loaded ? <p className="form-error unified-settings-error" role="alert">{error || '无法读取学习设置。'}请关闭后重试。</p> : <form onSubmit={event => void save(event)}>
        <div className="unified-settings-body">
          <section className={section === 'general' ? 'is-target' : ''}><h3>资料与回答</h3><p>新上传且读取成功的资料会成为当前对话可参考来源。遇到影响答案的实质冲突时，默认怎样处理？</p>
            <label className="field"><span>资料冲突默认方式</span><select value={draft.conflict_policy} onChange={event => setDraft(current => ({ ...current, conflict_policy: event.target.value as ConflictPolicy }))}>
              <option value="ask">询问我（推荐）</option><option value="balanced">由 AI 综合判断</option><option value="materials">以所选资料为准</option>
            </select></label><small className="form-hint">对话中的选择可覆盖此默认值。资料优先表示本次学习口径，并不代表资料一定正确。</small>
          </section>
          <section className={section === 'search' ? 'is-target' : ''}><h3>联网搜索</h3><p>上传或选用资料不会自动关闭联网。这里设置未单独调整的对话所用默认模式；对话中仍可单独调整。</p>
            <div className="unified-search-choice"><span>默认模式</span><SearchControls value={draft.search} onChange={search => setDraft(current => ({ ...current, search }))} providerKind={provider?.api_protocol} onOpenSettings={onOpenSearchSettings} /></div>
            <button className="button button--quiet" type="button" onClick={onOpenSearchSettings}>管理搜索服务与高级设置</button>
          </section>
          <section className={section === 'provider' ? 'is-target' : ''}><h3>AI 提供方</h3><p>配置模型、协议与凭据。</p><button className="button button--quiet" type="button" onClick={onOpenProviderSettings}>打开提供方设置</button></section>
          <section><DiagnosticSettings onOpen={() => { if (!dirty || window.confirm('有未保存的设置，确定放弃修改吗？')) { onClose(); window.dispatchEvent(new Event('nautilus:open-diagnostics')); } }} /></section>
          <ImageModelSettings />
          <ObsidianSettings />
        </div>
        {error && <p className="form-error unified-settings-error" role="alert">{error}</p>}
        <footer className="dialog-actions unified-settings-actions"><span>{dirty ? '有未保存的修改' : '设置已保存'}</span><button className="button button--quiet" type="button" onClick={close}>关闭</button><button className="button button--dark" type="submit" disabled={saving || !dirty}>{saving ? '保存中…' : '保存默认设置'}</button></footer>
      </form>}
    </section></div></DialogPortal>;
}
