import { FileText, X } from 'lucide-react';
import { materialPreviewUrl, type MaterialKind, type MaterialVersion } from './api';
import { attachmentName } from './AttachmentSupport';

export default function AttachmentCard({ kind, id, version, onOpen, onRemove, disabled, pending, onRetry }: {
  kind: MaterialKind; id: string; version: MaterialVersion; onOpen: () => void; onRemove?: () => void; disabled?: boolean; pending?: boolean; onRetry?: () => void;
}) {
  const name = attachmentName(version);
  const image = version.attachment?.kind === 'image' || version.original?.media_type.startsWith('image/');
  return <article className={`composer-attachment-card${image ? ' composer-attachment-card--image' : ''}${pending ? ' composer-attachment-card--pending' : ''}`}>
    <button className="attachment-card-open" type="button" aria-label={`查看附件：${name}`} title={name} onClick={onOpen}>
      {image ? <img src={materialPreviewUrl(kind, id, version.id)} alt={name} /> : <><FileText size={24} aria-hidden="true" /><span>{name}</span></>}
    </button>
    {onRemove && <button className="attachment-card-remove" type="button" aria-label={`移除附件：${name}`} title="移除附件" disabled={disabled} onClick={onRemove}><X size={13} /></button>}
    {pending && <div className="attachment-card-pending"><span>尚未加入本次附件</span><button className="text-button" type="button" disabled={disabled} onClick={onRetry}>重试添加</button></div>}
  </article>;
}
