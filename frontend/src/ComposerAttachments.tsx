import { useEffect, useRef, useState } from 'react';
import { Plus, FileText } from 'lucide-react';
import { getMaterials, materialPreviewUrl, uploadMaterial, type MaterialKind, type MaterialVersion, type SourceScope } from './api';
import { AttachmentDialog, AttachmentOcrReview, AttachmentPreview } from './AttachmentReview';
import AttachmentCard from './AttachmentCard';
import ImageModelSettings from './ImageModelSettings';
import AttachmentInputChoice from './AttachmentInputChoice';
import { attachmentChanged, attachmentError, attachmentName, imageFileAccept, latestUploadedAttachments, materialFileAccept, uploadedAttachments } from './AttachmentSupport';
import './styles/composer-attachments.css';

export default function ComposerAttachments({ kind, id, identity, contextKey, scope, versions, onChange, onVersions, onEnsure, onDraftChange, onBusyChange, clearSignal = 0, disabled, supportsImages, discussionModel }: {
  kind: MaterialKind; id: string | null; identity: string | null; contextKey?: string; scope: SourceScope; versions: MaterialVersion[];
  onChange: (scope: SourceScope) => Promise<boolean> | void; onVersions: (versions: MaterialVersion[]) => void;
  onEnsure?: () => Promise<string>; onDraftChange?: (ids: string[]) => void; onBusyChange?: (busy: boolean) => void; clearSignal?: number; disabled?: boolean; supportsImages?: boolean | null; discussionModel?: boolean;
}) {
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState('');
  const [localVersions, setLocalVersions] = useState<MaterialVersion[]>([]);
  const [draftIds, setDraftIds] = useState<string[]>([]);
  const draft = useRef<string[]>([]);
  const [preview, setPreview] = useState<MaterialVersion | null>(null);
  const [review, setReview] = useState<MaterialVersion | null>(null);
  const [settings, setSettings] = useState(false);
  const [unselected, setUnselected] = useState<string[]>([]);
  const [history, setHistory] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [query, setQuery] = useState('');
  const [chosenIds, setChosenIds] = useState<string[]>([]);
  const inputImage = useRef<HTMLInputElement>(null);
  const inputFile = useRef<HTMLInputElement>(null);
  const plus = useRef<HTMLButtonElement>(null);
  const picker = useRef<HTMLDivElement>(null);
  const generation = useRef(0);
  const creating = useRef(false);
  const operation = useRef(false);
  const live = useRef({ kind, id, identity, contextKey, scope, versions, onChange, onVersions, onDraftChange, onBusyChange });
  const previous = live.current;
  if (previous.kind !== kind || previous.contextKey !== contextKey || previous.id !== id && !(creating.current && previous.id === null) || previous.identity !== identity && !(creating.current && previous.identity === null)) generation.current++;
  live.current = { kind, id, identity, contextKey, scope, versions, onChange, onVersions, onDraftChange, onBusyChange };
  function updateDraft(ids: string[]) { draft.current = ids; setDraftIds(ids); live.current.onDraftChange?.(ids); }
  useEffect(() => {
    if (creating.current && id) return;
    setMenu(false); setBusy(false); setError(''); setUploading(''); setLocalVersions([]); setPreview(null); setReview(null); setSettings(false); setUnselected([]); setHistory(false); setHistoryLoading(false); setChosenIds([]); setQuery('');
    updateDraft([]); operation.current = false;
  }, [kind, id, identity, contextKey]);
  useEffect(() => { updateDraft([]); setUnselected([]); }, [clearSignal]);
  useEffect(() => { live.current.onBusyChange?.(busy || unselected.some(versionId => !scope.version_ids.includes(versionId))); }, [busy, unselected, scope.version_ids]);
  useEffect(() => () => { generation.current++; live.current.onBusyChange?.(false); }, []);
  useEffect(() => {
    if (!menu) return;
    const dismiss = (event: MouseEvent) => { if (event.target instanceof Node && !picker.current?.contains(event.target)) setMenu(false); };
    document.addEventListener('mousedown', dismiss);
    return () => document.removeEventListener('mousedown', dismiss);
  }, [menu]);
  const purgedGroups = new Set(versions.filter(item => item.purged_at).map(item => item.material_id));
  useEffect(() => {
    const purged = new Set(versions.filter(item => item.purged_at).map(item => item.material_id));
    if (!purged.size) return;
    const retained = (versionId: string) => ![...versions, ...localVersions].some(item => item.id === versionId && purged.has(item.material_id));
    setLocalVersions(previous => previous.filter(item => !purged.has(item.material_id)));
    setPreview(previous => previous && purged.has(previous.material_id) ? null : previous);
    setReview(previous => previous && purged.has(previous.material_id) ? null : previous);
    setUnselected(previous => previous.filter(retained)); setChosenIds(previous => previous.filter(retained)); updateDraft(draft.current.filter(retained));
  }, [versions]);
  const all = [...new Map([...localVersions, ...versions].map(item => [item.id, item])).values()].filter(item => !item.purged_at && !purgedGroups.has(item.material_id));
  const files = uploadedAttachments(all);
  const groups = latestUploadedAttachments(all);
  const cards = files.filter(item => draftIds.includes(item.id) && scope.version_ids.includes(item.id) || unselected.includes(item.id));
  function scopeWith(selected: MaterialVersion[]): SourceScope {
    const latest = live.current.scope;
    const materialIds = new Set(selected.map(item => item.material_id));
    const known = [...live.current.versions, ...localVersions, ...selected];
    const rest = latest.version_ids.filter(versionId => !known.some(item => item.id === versionId && materialIds.has(item.material_id)));
    const ids = [...rest, ...selected.map(item => item.id)];
    const images = (latest.image_version_ids ?? []).filter(versionId => ids.includes(versionId));
    const { image_version_ids: _previous, ...base } = latest;
    return { ...base, mode: latest.mode === 'unspecified' ? 'reference' : latest.mode, version_ids: ids, ...(images.length ? { image_version_ids: images } : {}) };
  }
  async function reference(selected: MaterialVersion[], target = live.current.id, expected = generation.current): Promise<boolean> {
    if (!target || generation.current !== expected || live.current.id !== target) return false;
    const applied = await live.current.onChange(scopeWith(selected));
    if (generation.current !== expected) return false;
    if (applied === false) { setError('附件已保存，但尚未加入本次附件。请核对当前状态后重试。'); return false; }
    const materialIds = new Set(selected.map(item => item.material_id));
    const known = [...live.current.versions, ...localVersions, ...selected];
    updateDraft([...draft.current.filter(versionId => !known.some(item => item.id === versionId && materialIds.has(item.material_id))), ...selected.map(item => item.id)]);
    setUnselected(previous => previous.filter(value => !selected.some(item => item.id === value) && !known.some(item => item.id === value && materialIds.has(item.material_id)))); setError(''); return true;
  }
  async function upload(fileList: FileList | null) {
    if (!fileList?.length || operation.current || disabled) return;
    const chosen = [...fileList]; const expected = generation.current;
    operation.current = true; setBusy(true); setMenu(false); setError('');
    let target = id;
    const failures: string[] = [];
    const valid = () => generation.current === expected && (live.current.id === target || creating.current && live.current.id === null);
    try {
      if (!target) {
        if (!onEnsure) throw new Error('请先打开对话。');
        creating.current = true; target = await onEnsure();
        if (!valid()) return;
      }
      for (const file of chosen) {
        if (!valid()) break;
        setUploading(file.name);
        let savedResult: MaterialVersion | null = null;
        try {
          const saved = await uploadMaterial(kind, target, file); savedResult = saved;
          attachmentChanged(kind, target);
          if (!valid()) break;
          setLocalVersions(previous => [...previous.filter(item => item.id !== saved.id), saved]);
          const data = await getMaterials(kind, target);
          if (!valid()) break;
          live.current.onVersions(data.versions);
          // Use the latest parent scope after both awaits, never the selection at upload start.
          const applied = await reference([saved], target, expected);
          if (!applied && valid()) { setUnselected(previous => [...new Set([...previous, saved.id])]); failures.push(`${file.name}：已保存，尚未加入本次附件，可重试添加。`); }
        } catch (reason) { if (valid()) { if (savedResult) { setUnselected(previous => [...new Set([...previous, savedResult!.id])]); failures.push(`${file.name}：已保存，可重试添加。${attachmentError(reason)}`); } else failures.push(`${file.name}：${attachmentError(reason)}`); } }
      }
      if (valid() && failures.length) setError(failures.join('\n'));
    } catch (reason) { if (generation.current === expected) setError(attachmentError(reason)); }
    finally {
      creating.current = false;
      if (generation.current === expected) { operation.current = false; setBusy(false); setUploading(''); }
      if (inputFile.current) inputFile.current.value = ''; if (inputImage.current) inputImage.current.value = '';
    }
  }
  async function confirmed(version: MaterialVersion) {
    const current = generation.current;
    setLocalVersions(previous => [...previous.filter(item => item.id !== version.id), version]);
    setUnselected(previous => [...new Set([...previous, version.id])]);
    if (live.current.id) {
      const fresh = await getMaterials(kind, live.current.id);
      if (generation.current !== current) return false;
      live.current.onVersions(fresh.versions);
    }
    return reference([version], live.current.id, current);
  }
  async function removeReference(version: MaterialVersion) {
    if (unselected.includes(version.id) && !scope.version_ids.includes(version.id)) { setUnselected(previous => previous.filter(value => value !== version.id)); setError(''); return; }
    const expected = generation.current;
    const latest = live.current;
    const remaining = latest.scope.version_ids.filter(value => value !== version.id);
    const images = (latest.scope.image_version_ids ?? []).filter(value => remaining.includes(value));
    const { image_version_ids: _previous, ...base } = latest.scope;
    const applied = await latest.onChange({ ...base, version_ids: remaining, mode: remaining.length || latest.scope.knowledge_base ? latest.scope.mode : 'unspecified', ...(images.length ? { image_version_ids: images } : {}) });
    if (generation.current !== expected) return;
    if (applied === false) setError('移除未保存，请核对当前状态后重试。');
    else { updateDraft(draft.current.filter(value => value !== version.id)); setUnselected(previous => previous.filter(value => value !== version.id)); setError(''); }
  }
  async function openHistory() {
    setMenu(false); setHistory(true); setChosenIds([]); setQuery(''); setError('');
    if (!id) return;
    const expected = generation.current; const target = id; setHistoryLoading(true);
    try { const fresh = await getMaterials(kind, target); if (generation.current === expected && live.current.id === target) live.current.onVersions(fresh.versions); }
    catch (reason) { if (generation.current === expected) setError(attachmentError(reason)); }
    finally { if (generation.current === expected) setHistoryLoading(false); }
  }
  async function addHistory() {
    if (busy || !chosenIds.length) return;
    const expected = generation.current; setBusy(true);
    try { if (await reference(groups.filter(item => chosenIds.includes(item.id))) && generation.current === expected) setHistory(false); }
    catch (reason) { if (generation.current === expected) setError(attachmentError(reason)); }
    finally { if (generation.current === expected) setBusy(false); }
  }
  const imageSelected = files.some(item => scope.version_ids.includes(item.id) && (item.attachment?.mode === 'image' || scope.image_version_ids?.includes(item.id)));
  return <div className="composer-attachments">
    <div className="attachment-picker" ref={picker} onKeyDown={event => {
      if (event.key === 'Escape' && menu) { event.preventDefault(); event.stopPropagation(); setMenu(false); plus.current?.focus(); }
    }}><button ref={plus} className="icon-button attachment-plus" type="button" aria-label="添加图片或文件" aria-expanded={menu} disabled={disabled || busy} onClick={() => setMenu(value => !value)}><Plus size={20} /></button>
      {menu && <div className="attachment-picker-menu" aria-label="添加附件"><button className="button button--quiet" type="button" onClick={() => inputImage.current?.click()}>上传图片</button><button className="button button--quiet" type="button" onClick={() => inputFile.current?.click()}>上传文件</button><button className="button button--quiet" type="button" onClick={() => void openHistory()}>已上传的文件</button></div>}
      <input ref={inputImage} type="file" aria-label="选择上传图片" accept={imageFileAccept} multiple hidden onChange={event => void upload(event.target.files)} />
      <input ref={inputFile} type="file" aria-label="选择上传文件" accept={materialFileAccept} multiple hidden onChange={event => void upload(event.target.files)} />
    </div>
    {(cards.length > 0 || busy || error) && <div className="composer-attachment-cards" aria-label="待发送附件">
      {busy && !history && <p role="status">正在保存附件：{uploading || '正在打开对话…'}</p>}
      {id && cards.map(version => <AttachmentCard key={version.id} kind={kind} id={id} version={version} disabled={disabled || busy} pending={unselected.includes(version.id) && !scope.version_ids.includes(version.id)} onOpen={() => setPreview(version)} onRemove={() => void removeReference(version)} onRetry={() => void reference([version])} />)}
      {imageSelected && supportsImages !== true && <p className="attachment-model-hint">{supportsImages === false ? '当前模型不支持图片。' : '当前模型的图片能力未确认。'}{discussionModel ? '可到学习室更换模型，或识别文字。' : '可更换模型，或识别文字。'} <button className="text-button" type="button" onClick={() => setSettings(true)}>图片与 OCR 模型设置</button></p>}
      {error && !history && <p className="form-error" role="alert">{error}</p>}
    </div>}
    {history && <AttachmentDialog title="已上传的文件" onClose={() => setHistory(false)}>
      <div className="attachment-history"><label>搜索文件<input type="search" placeholder="搜索文件名" value={query} onChange={event => setQuery(event.target.value)} /></label>
        {historyLoading ? <p role="status">正在读取文件…</p> : <div className="attachment-history-list">{groups.filter(item => attachmentName(item).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).map(version => <label className="attachment-history-row" key={version.id}>
          <input type="checkbox" checked={chosenIds.includes(version.id)} disabled={busy} onChange={event => setChosenIds(previous => event.target.checked ? [...previous, version.id] : previous.filter(value => value !== version.id))} />
          {version.attachment?.kind === 'image' && id ? <img src={materialPreviewUrl(kind, id, version.id)} alt="" /> : <FileText size={22} aria-hidden="true" />}<span>{attachmentName(version)}</span>
        </label>)}{!groups.length && <p>还没有上传文件。可从“＋”上传图片或文件。</p>}{groups.length > 0 && !groups.some(item => attachmentName(item).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) && <p>没有找到匹配的文件。</p>}</div>}
        {error && <p className="form-error" role="alert">{error}</p>}
        <footer><span>已选择 {chosenIds.length} 个文件</span><button className="button button--accent" type="button" disabled={disabled || busy || historyLoading || !chosenIds.length} onClick={() => void addHistory()}>{busy ? '添加中…' : '参考'}</button></footer>
      </div>
    </AttachmentDialog>}
    {id && preview && <AttachmentPreview key={`${id}:${preview.id}`} kind={kind} id={id} version={preview} onClose={() => setPreview(null)}>
      <AttachmentInputChoice version={preview} scope={scope} disabled={disabled || busy} onChange={onChange} />
      {preview.attachment && ['image', 'pdf'].includes(preview.attachment.kind) && (!preview.inherited || preview.library) && <button className="button button--quiet" type="button" disabled={disabled || busy} onClick={() => { setPreview(null); setReview(preview); }}>{preview.attachment.origin === 'ocr' ? '修改核对文字' : '识别与核对文字'}</button>}
    </AttachmentPreview>}
    {id && review && <AttachmentOcrReview key={`${id}:${review.id}`} kind={kind} id={id} version={review} onConfirmed={confirmed} onClose={() => setReview(null)} />}
    {settings && <AttachmentDialog title="图片与 OCR 模型设置" onClose={() => setSettings(false)}><ImageModelSettings /></AttachmentDialog>}
  </div>;
}
