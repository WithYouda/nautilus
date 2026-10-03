import { ApiError, type MaterialVersion } from './api';

export const imageFileAccept = '.png,.jpg,.jpeg,.webp';
export const materialFileAccept = '.txt,.md,.markdown,.json,.csv,.tsv,.py,.js,.ts,.tsx,.jsx,.html,.css,.xml,.yaml,.yml,.sql,.sh,.rs,.go,.java,.c,.cpp,.h,.docx,.pdf';
export function attachmentError(reason: unknown): string {
  const code = reason instanceof ApiError ? reason.kind : reason instanceof Error ? reason.message : String(reason);
  const messages: Record<string, string> = {
    material_file_encoding: '文本文件需要使用 UTF-8 编码。', material_file_unsupported: '暂不支持此文件格式。请使用 PNG、JPG、WebP、PDF、DOCX 或 UTF-8 文本。',
    material_file_no_text: '文件中没有读到可用文字。', material_file_unreadable: '文件无法读取，请检查是否损坏。', material_file_encrypted: '请先解密 PDF 后再上传。',
    material_file_no_pages: '文件没有可预览的页面。', material_file_page_not_found: '原件中没有这一页。', material_file_page_invalid: '页码无效，请重新选择。',
    material_original_unavailable: '此版本的原件当前不可用。', material_not_found: '资料已不可用，请重新打开资料列表。',
    image_model_unverified: '当前模型的图片能力未确认。请确认图片能力，并手动选择支持图片的对话模型，或主动使用 OCR。',
    image_model_unsupported: '当前模型不支持图片。请手动选择支持图片的对话模型，或主动使用 OCR。',
    ocr_model_required: '请先在“图片与 OCR 模型”中选择识别模型，再开始识别。', ocr_model_unavailable: '所选识别模型当前不可用，请检查提供方、凭据与图片能力。',
    ocr_source_unsupported: '此资料不能进行图片文字识别。', ocr_not_ready: '识别尚未完成，请等待后再核对。', ocr_review_invalid: '请核对全部页码并填写至少一页文字。',
    ocr_incomplete_confirmation_required: '仍有空白页，请补充文字，或明确确认文字不完整。', ocr_interrupted: '识别中断，已取得的草稿保留，可核对或重新识别。',
    ocr_pages_failed: '部分页面识别失败。请对照原件补充文字，再确认。', ocr_failed: '识别失败，可检查模型后重新识别。', ocr_canceled: '已取消识别，原件仍保留。',
  };
  return messages[code] ?? (reason instanceof Error ? messages[reason.message] : undefined) ?? (reason instanceof Error ? reason.message : '操作未完成，请重试。');
}
export const attachmentLabel = (version: MaterialVersion) => version.attachment?.origin === 'ocr' ? '已核对的 OCR 文字（派生版本）' : version.attachment?.mode === 'image' ? '原图参考' : '已读取文字';
export function attachmentChanged(kind: string, id: string) { window.dispatchEvent(new CustomEvent('nautilus:materials-changed', { detail: { kind, id } })); }
