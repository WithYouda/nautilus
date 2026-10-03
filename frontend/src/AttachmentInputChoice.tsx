import { useId } from 'react';
import type { MaterialVersion, SourceScope } from './api';

export default function AttachmentInputChoice({ version, scope, disabled, onChange }: { version: MaterialVersion; scope: SourceScope; disabled?: boolean; onChange: (scope: SourceScope) => Promise<boolean> | void }) {
  const label = useId();
  if (!version.original || !version.attachment?.page_count || version.attachment.mode !== 'text' || !scope.version_ids.includes(version.id)) return null;
  const original = scope.image_version_ids?.includes(version.id) ?? false;
  return <label className="attachment-input-choice" htmlFor={label}>本次参考方式：{version.title}<select id={label} value={original ? 'image' : 'text'} disabled={disabled} onChange={event => {
    const images = (scope.image_version_ids ?? []).filter(id => id !== version.id && scope.version_ids.includes(id));
    if (event.target.value === 'image') images.push(version.id);
    const { image_version_ids: _previous, ...rest } = scope;
    void onChange({ ...rest, ...(images.length ? { image_version_ids: images } : {}) });
  }}><option value="text">参考文字</option><option value="image">参考原页（需要支持图片的模型）</option></select></label>;
}
