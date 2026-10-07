import { useEffect, useRef, useState } from 'react';
import { changePersona, exportPersona, getPersonas, personaKey, previewPersona, type PersonaPreview, type PersonaState, type PersonaStyle, type PersonaVersion } from './persona-api';
import './PersonaSettings.css';

const labels = { neutral: '平和', warm: '温和支持', direct: '直接明确', plain: '自然简洁', lively: '生动有趣', formal: '严谨正式', concise: '简短', balanced: '适中', detailed: '充分说明', gentle: '温和提醒' };
function PersonaSummary({ style }: { style: PersonaStyle }) {
  return <div className="persona-style">{style.character_name && <p>角色自称：{style.character_name}</p>}{style.identity && <p>{style.identity}</p>}<p>称呼用户：{style.address || '不特别称呼'} · 语气：{labels[style.tone]}</p><p>措辞：{labels[style.phrasing]} · 详略：{labels[style.detail]} · 提醒：{labels[style.reminders]}</p>{style.traits.length > 0 && <ul>{style.traits.map((item, index) => <li key={index}>{item}</li>)}</ul>}{Boolean(style.scenario_rules?.length) && <><p>不同场景</p><ul>{style.scenario_rules!.map((item, index) => <li key={index}>{item}</li>)}</ul></>}</div>;
}

export default function PersonaSettings() {
  const [state, setState] = useState<PersonaState | null>(null), [selected, setSelected] = useState('');
  const [editing, setEditing] = useState(false), [editingId, setEditingId] = useState<string | undefined>(), [name, setName] = useState(''), [description, setDescription] = useState('');
  const [preview, setPreview] = useState<PersonaPreview | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const live = useRef(false), fileInput = useRef<HTMLInputElement>(null);
  const pending = useRef<Parameters<typeof changePersona>[0] | null>(null);
  useEffect(() => { let active = true; live.current = true; void getPersonas().then(value => { if (active) { setState(value); setSelected(value.active_id ?? value.profiles[0]?.id ?? ''); } }).catch(reason => { if (active) setError(reason.message); }); return () => { active = false; live.current = false; }; }, []);
  const profile = state?.profiles.find(item => item.id === selected), current = profile?.versions.at(-1);
  const active = state?.profiles.find(item => item.id === state.active_id)?.versions.at(-1);
  function edit(version?: PersonaVersion) { setEditing(true); setEditingId(version ? selected : undefined); setName(version?.name ?? ''); setDescription(version?.description ?? ''); setPreview(null); setNotice(''); setError(''); }
  async function generate() {
    setBusy(true); setError(''); setPreview(null);
    try { const result = await previewPersona({ name, description, profile_id: editingId, request_key: personaKey() }); if (live.current) setPreview(result); }
    catch (reason) { if (live.current) setError(reason instanceof Error ? reason.message : '无法生成预览，描述已保留。'); }
    finally { if (live.current) setBusy(false); }
  }
  async function importFile(file?: File) {
    if (!file) return;
    setError(''); setNotice('');
    if (file.size > 64 * 1024) { setError('人格文件不能超过64KB。'); return; }
    setBusy(true);
    try {
      const content: unknown = JSON.parse(await file.text());
      const result = await previewPersona({ package: content, request_key: personaKey() });
      if (live.current) { setEditing(true); setEditingId(undefined); setName(result.package.name); setDescription(result.package.description); setPreview(result); }
    } catch (reason) { if (live.current) setError(reason instanceof SyntaxError ? '请选择有效的人格JSON文件。' : reason instanceof Error ? reason.message : '人格文件无法读取。'); }
    finally { if (live.current) setBusy(false); }
  }
  async function change(action: Parameters<typeof changePersona>[0]['action'], extra: Partial<Parameters<typeof changePersona>[0]> = {}) {
    if (!state) return;
    pending.current ??= { action, expected_revision: state.revision, request_key: personaKey(), ...extra };
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await changePersona(pending.current);
      if (!live.current) return;
      setState(result); setSelected(result.active_id ?? selected); pending.current = null;
      setEditing(false); setPreview(null);
      setNotice(action === 'disable' ? '人格已停用。' : '人格已启用，作为全局默认。');
      window.dispatchEvent(new Event('nautilus:learning-state-changed'));
    } catch (reason) { if (live.current) { setError(reason instanceof Error ? reason.message : '保存未成功，请重试。'); pending.current = null; } }
    finally { if (live.current) setBusy(false); }
  }
  async function reload() {
    setBusy(true); setError('');
    try { const value = await getPersonas(); if (live.current) setState(value); }
    catch (reason) { if (live.current) setError(reason instanceof Error ? reason.message : '读取失败。'); }
    finally { if (live.current) setBusy(false); }
  }
  async function download() {
    if (!profile) return;
    setBusy(true); setError('');
    try { const value = await exportPersona(profile.id); if (!live.current) return; const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' })); const link = document.createElement('a'); link.href = url; link.download = `${value.name.replace(/[\\/:*?"<>|]/g, '_')}.persona.json`; link.click(); URL.revokeObjectURL(url); }
    catch (reason) { if (live.current) setError(reason instanceof Error ? reason.message : '导出失败。'); }
    finally { if (live.current) setBusy(false); }
  }
  return <section className="persona-settings" id="persona-settings" aria-label="人格设置">
    <h3>人格</h3><p>在这里设置全局默认人格，计划、任务和对话可单独选择。</p>
    {!state && !error && <p role="status">正在读取人格…</p>}
    {state && <>
      <p className="persona-current">全局默认：<strong>{active?.name ?? '未启用人格'}</strong>{active && <button className="text-button" type="button" disabled={busy} onClick={() => void change('disable')}>停用</button>}</p>
      {state.profiles.length > 0 && <div className="persona-choice"><label className="field"><span>已保存的人格</span><select aria-label="已保存的人格" value={selected} disabled={busy} onChange={event => { setSelected(event.target.value); setEditing(false); setPreview(null); setNotice(''); }}><option value="" disabled>选择人格</option>{state.profiles.map(item => <option key={item.id} value={item.id}>{item.versions.at(-1)?.name}</option>)}</select></label>{profile && state.active_id !== profile.id && <button className="button button--quiet button--compact" type="button" disabled={busy} onClick={() => void change('activate', { profile_id: profile.id })}>启用此人格</button>}</div>}
      <div className="persona-actions"><button className="button button--quiet button--compact" type="button" disabled={busy} onClick={() => edit()}>新建人格</button><button className="text-button" type="button" disabled={busy} onClick={() => fileInput.current?.click()}>导入人格</button>{current && <button className="text-button" type="button" disabled={busy} onClick={() => edit(current)}>编辑</button>}</div>
      <input className="persona-file" ref={fileInput} type="file" accept=".json,application/json" aria-label="导入人格文件" disabled={busy} onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; void importFile(file); }} />
      {editing && <div className="persona-editor">
        <label className="field"><span>人格名称</span><small className="form-hint" id="persona-name-hint">用于保存和选择，可以与角色自称不同。</small><input aria-label="人格名称" aria-describedby="persona-name-hint" value={name} maxLength={60} disabled={busy} onChange={event => { setName(event.target.value); setPreview(null); }} /></label>
        <label className="field"><span>人格描述</span><textarea rows={4} value={description} disabled={busy} placeholder="严格而不羞辱人，讲话直接，发现拖延时指出问题，再给一个能开始的小步骤。" onChange={event => { setDescription(event.target.value); setPreview(null); }} /></label>
        <div className="persona-actions"><button className="button button--quiet button--compact" type="button" disabled={busy || !name.trim() || !description.trim()} onClick={() => void generate()}>{busy ? '处理中…' : '生成人格预览'}</button><button className="text-button" type="button" disabled={busy} onClick={() => { setEditing(false); setPreview(null); }}>取消编辑</button></div>
        {preview && <div className="persona-preview" aria-label="人格预览"><h4>{preview.package.name}</h4><PersonaSummary style={preview.package.style} />{preview.sample_reply && <blockquote><span>说话示例</span><p>{preview.sample_reply}</p></blockquote>}{preview.issues.length > 0 && <div role="alert"><p>请先修改这些要求：</p><ul>{preview.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul></div>}<button className="button button--dark button--compact" type="button" disabled={busy || !preview.can_confirm} onClick={() => void change('confirm', { preview_id: preview.preview_id })}>确认并启用</button></div>}
      </div>}
      {current && !editing && <details><summary>人格详情与历史</summary><PersonaSummary style={current.style} /><details><summary>原始描述</summary><p className="persona-description">{current.description}</p></details><button className="text-button" type="button" disabled={busy} onClick={() => void download()}>导出当前人格</button>
        {[...profile!.versions].reverse().map(version => <details key={version.version} className="persona-version"><summary>第{version.version}版 · {new Date(version.created_at).toLocaleString()}</summary><p>{version.name}</p><PersonaSummary style={version.style} />{version.version !== current.version && <button className="text-button" type="button" disabled={busy} onClick={() => void change('restore', { profile_id: profile!.id, version: version.version })}>恢复并启用此版</button>}</details>)}
      </details>}
    </>}
    {notice && <p role="status">{notice}</p>}{error && <p className="form-error" role="alert">{error}<button className="text-button" type="button" disabled={busy} onClick={() => void reload()}>读取最新人格</button></p>}
  </section>;
}
