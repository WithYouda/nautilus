import { useEffect, useState } from 'react';
import type { AppliedSourceScope, MaterialKind, MaterialVersion } from './api';
import AttachmentCard from './AttachmentCard';
import { AttachmentPreview } from './AttachmentReview';
import { uploadedAttachments } from './AttachmentSupport';

export default function MessageAttachments({ kind, id, versionIds, scope, versions }: { kind: MaterialKind; id: string; versionIds: string[]; scope?: AppliedSourceScope | null; versions: MaterialVersion[] }) {
  const [preview, setPreview] = useState<MaterialVersion | null>(null);
  const files = scope?.purged ? [] : uploadedAttachments(versions).filter(item => versionIds.includes(item.id));
  useEffect(() => { setPreview(previous => previous && files.some(item => item.id === previous.id) ? previous : null); }, [versions, versionIds, scope, id]);
  if (!files.length) return null;
  return <div className="message-attachments" aria-label="这条消息的附件">
    {files.map(version => <AttachmentCard key={version.id} kind={kind} id={id} version={version} onOpen={() => setPreview(version)} />)}
    {preview && <AttachmentPreview key={`${id}:${preview.id}`} kind={kind} id={id} version={preview} pageNumbers={scope?.materials.find(item => item.id === preview.id)?.page_numbers} onClose={() => setPreview(null)} />}
  </div>;
}
