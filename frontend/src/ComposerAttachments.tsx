import { useEffect, useRef, useState } from 'react';
import { Plus } from 'lucide-react';
import { getMaterials, materialPreviewUrl, uploadMaterial, type MaterialKind, type MaterialVersion, type SourceScope } from './api';
import { AttachmentDialog, AttachmentOcrReview, AttachmentPreview } from './AttachmentReview';
import ImageModelSettings from './ImageModelSettings';
import AttachmentInputChoice from './AttachmentInputChoice';
import { attachmentChanged, attachmentError, attachmentLabel, imageFileAccept, materialFileAccept } from './AttachmentSupport';
import './styles/composer-attachments.css';

export default function ComposerAttachments({ kind, id, identity, contextKey, scope, versions, onChange, onVersions, onEnsure, disabled, supportsImages, discussionModel }: {
  kind: MaterialKind; id: string | null; identity: string | null; contextKey?: string; scope: SourceScope; versions: MaterialVersion[];
  onChange: (scope: SourceScope) => Promise<boolean> | void; onVersions: (versions: MaterialVersion[]) => void;
  onEnsure?: () => Promise<string>; disabled?: boolean; supportsImages?: boolean | null; discussionModel?: boolean;
}) {
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState('');
  const [localVersions, setLocalVersions] = useState<MaterialVersion[]>([]);
  const [preview, setPreview] = useState<MaterialVersion | null>(null);
  const [review, setReview] = useState<MaterialVersion | null>(null);
  const [settings, setSettings] = useState(false);
  const [unselected, setUnselected] = useState<string[]>([]);
  const inputImage = useRef<HTMLInputElement>(null);
  const inputFile = useRef<HTMLInputElement>(null);
  const plus = useRef<HTMLButtonElement>(null);
  const picker = useRef<HTMLDivElement>(null);
  const generation = useRef(0);
  const creating = useRef(false);
  const operation = useRef(false);
  const live = useRef({ kind, id, identity, contextKey, scope, versions, onChange, onVersions });
  const previous = live.current;
  if (previous.kind !== kind || previous.contextKey !== contextKey || previous.id !== id && !(creating.current && previous.id === null) || previous.identity !== identity && !(creating.current && previous.identity === null)) generation.current++;
  live.current = { kind, id, identity, contextKey, scope, versions, onChange, onVersions };
  useEffect(() => {
    if (creating.current && id) return;
    setMenu(false); setBusy(false); setError(''); setUploading(''); setLocalVersions([]); setPreview(null); setReview(null); setSettings(false); setUnselected([]);
    operation.current = false;
  }, [kind, id, identity, contextKey]);
  useEffect(() => () => { generation.current++; }, []);
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
    setLocalVersions(previous => previous.filter(item => !purged.has(item.material_id)));
    setPreview(previous => previous && purged.has(previous.material_id) ? null : previous);
    setReview(previous => previous && purged.has(previous.material_id) ? null : previous);
    setUnselected(previous => previous.filter(versionId => !versions.some(item => item.id === versionId && item.purged_at)));
  }, [versions]);
  const all = [...new Map([...localVersions, ...versions].map(item => [item.id, item])).values()].filter(item => !item.purged_at && !purgedGroups.has(item.material_id));
  const groups = [...new Map(all.filter(item => item.attachment || item.original).sort((a, b) => a.version - b.version).map(item => [item.material_id, item])).values()];
  const cards = groups.map(group => all.find(item => item.material_id === group.material_id && unselected.includes(item.id)) ?? all.find(item => item.material_id === group.material_id && scope.version_ids.includes(item.id)) ?? group);
  async function reference(version: MaterialVersion, target = live.current.id, expected = generation.current): Promise<boolean> {
    if (!target || generation.current !== expected || live.current.id !== target) return false;
    const latest = live.current;
    const known = [...latest.versions, ...localVersions, version];
    const rest = latest.scope.version_ids.filter(versionId => !known.some(item => item.id === versionId && item.material_id === version.material_id));
    const applied = await latest.onChange({ ...latest.scope, mode: latest.scope.mode === 'unspecified' ? 'reference' : latest.scope.mode, version_ids: [...rest, version.id] });
    if (generation.current !== expected) return false;
    if (applied === false) { setUnselected(previous => [...new Set([...previous, version.id])]); setError('附件已保存，但当前参考未确认。请检查当前状态，再点击“参考此版本”重试。'); return false; }
    setUnselected(previous => previous.filter(value => value !== version.id)); setError(''); return true;
  }
  async function upload(files: FileList | null) {
    if (!files?.length || operation.current || disabled) return;
    const chosen = [...files]; const expected = generation.current;
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
          // Read the latest parent scope after both awaits; never restore an old selection.
          const applied = await reference(saved, target, expected);
          if (!applied && valid()) failures.push(`${file.name}：已保存，但当前参考未确认，可点击“参考此版本”重试。`);
        } catch (reason) { if (valid()) { if (savedResult) { setUnselected(previous => [...new Set([...previous, savedResult!.id])]); failures.push(`${file.name}：附件已保存，但列表或当前参考未确认，可稍后重试参考。${attachmentError(reason)}`); } else failures.push(`${file.name}：${attachmentError(reason)}`); } }
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
    return reference(version, live.current.id, current);
  }
  async function removeReference(version: MaterialVersion) {
    const expected = generation.current;
    const latest = live.current;
    const remaining = latest.scope.version_ids.filter(value => value !== version.id);
    const applied = await latest.onChange({ ...latest.scope, version_ids: remaining, mode: remaining.length || latest.scope.knowledge_base ? latest.scope.mode : 'unspecified' });
    if (generation.current === expected && applied === false) setError('取消参考未保存，请核对当前状态后重试。');
  }
  const imageSelected = cards.some(item => scope.version_ids.includes(item.id) && (item.attachment?.mode === 'image' || scope.image_version_ids?.includes(item.id)));
  return <div className="composer-attachments">
    <div className="attachment-picker" ref={picker} onKeyDown={event => {
      if (event.key === 'Escape' && menu) { event.preventDefault(); event.stopPropagation(); setMenu(false); plus.current?.focus(); }
    }}><button ref={plus} className="icon-button attachment-plus" type="button" aria-label="添加图片或文件" aria-expanded={menu} disabled={disabled || busy} onClick={() => setMenu(value => !value)}><Plus size={20} /></button>
      {menu && <div className="attachment-picker-menu" aria-label="上传附件"><button className="button button--quiet" type="button" onClick={() => inputImage.current?.click()}>上传图片</button><button className="button button--quiet" type="button" onClick={() => inputFile.current?.click()}>上传文件</button><small>图片：PNG、JPG、WebP；文件：PDF、DOCX、UTF-8 文本。</small></div>}
      <input ref={inputImage} type="file" aria-label="选择上传图片" accept={imageFileAccept} multiple hidden onChange={event => void upload(event.target.files)} />
      <input ref={inputFile} type="file" aria-label="选择上传文件" accept={materialFileAccept} multiple hidden onChange={event => void upload(event.target.files)} />
    </div>
    {(cards.length > 0 || busy || error) && <div className="composer-attachment-cards" aria-label="当前对话附件">
      {busy && <p role="status">正在保存附件：{uploading || '正在打开对话…'}</p>}
      {cards.map(version => <article className="composer-attachment-card" key={version.id}>
        {version.attachment && ['image', 'pdf'].includes(version.attachment.kind) && id && <button className="attachment-thumbnail" type="button" aria-label={`预览原件：${version.title}`} onClick={() => setPreview(version)}><img src={materialPreviewUrl(kind, id, version.id)} alt="" /></button>}
        <div><strong>{version.title || version.original?.filename || '附件'}</strong><small>第 {version.version} 版 · {scope.image_version_ids?.includes(version.id) ? '原页图片参考' : attachmentLabel(version)} · {scope.version_ids.includes(version.id) ? '当前参考' : unselected.includes(version.id) ? '已保存，参考未确认' : '已保存，未参考'}</small>
          <div className="attachment-card-actions">{version.attachment && ['image', 'pdf'].includes(version.attachment.kind) && <button className="text-button" type="button" onClick={() => setPreview(version)}>预览原件</button>}
            {version.attachment && ['image', 'pdf'].includes(version.attachment.kind) && (!version.inherited || version.library) && <button className="text-button" type="button" disabled={disabled || busy} onClick={() => setReview(version)}>{version.attachment.origin === 'ocr' ? '修改核对文字' : '识别与核对文字'}</button>}
            {scope.version_ids.includes(version.id) ? <button className="text-button" type="button" disabled={disabled || busy} onClick={() => void removeReference(version)}>取消参考</button> : <button className="text-button" type="button" disabled={disabled || busy} onClick={() => void reference(version)}>参考此版本</button>}
          </div><AttachmentInputChoice version={version} scope={scope} disabled={disabled || busy} onChange={onChange} /></div>
      </article>)}
      {imageSelected && <p className="attachment-model-hint">{supportsImages === true ? '当前模型支持图片，可直接发送问题看图。' : supportsImages === false ? '当前模型不支持图片，请手动选择支持图片的模型，或主动识别文字。' : '当前模型的图片能力未确认，请确认并选择支持图片的模型，或主动识别文字。'}{discussionModel && '问题讨论沿用学习室模型；请到学习室更换对话模型。'} <button className="text-button" type="button" onClick={() => setSettings(true)}>图片与 OCR 模型设置</button></p>}
      {error && <p className="form-error" role="alert">{error}</p>}
    </div>}
    {id && preview && <AttachmentPreview key={`${id}:${preview.id}`} kind={kind} id={id} version={preview} onClose={() => setPreview(null)} />}
    {id && review && <AttachmentOcrReview key={`${id}:${review.id}`} kind={kind} id={id} version={review} onConfirmed={confirmed} onClose={() => setReview(null)} />}
    {settings && <AttachmentDialog title="图片与 OCR 模型设置" onClose={() => setSettings(false)}><ImageModelSettings /></AttachmentDialog>}
  </div>;
}
