import { useEffect, useId, useRef, useState } from 'react';
import { Ellipsis } from 'lucide-react';
import type { AppliedSourceScope, MaterialKind, MaterialVersion } from './api';
import DialogPortal from './DialogPortal';
import { AttachmentDialog, AttachmentPreview } from './AttachmentReview';
import { obsidianSource, obsidianUri } from './ObsidianMaterials';
import './styles/task-materials.css';

export default function AnswerSources({ scope, versions = [], kind, scopeId }: {
  scope?: AppliedSourceScope | null; versions?: MaterialVersion[]; kind: MaterialKind; scopeId: string;
}) {
  const [menu, setMenu] = useState(false);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const trigger = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const menuItem = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  useEffect(() => {
    if (!menu) return;
    menuItem.current?.focus({ preventScroll: true });
    const dismiss = (event: PointerEvent) => {
      if (event.target instanceof Node && !popup.current?.contains(event.target) && !trigger.current?.contains(event.target)) setMenu(false);
    };
    const close = () => setMenu(false);
    const reposition = () => { if (trigger.current) setPosition(menuPosition(trigger.current)); };
    document.addEventListener('pointerdown', dismiss);
    window.addEventListener('resize', close);
    document.addEventListener('scroll', reposition, true);
    return () => { document.removeEventListener('pointerdown', dismiss); window.removeEventListener('resize', close); document.removeEventListener('scroll', reposition, true); };
  }, [menu]);
  const item = scope?.purged ? undefined : scope?.materials.find(value => value.id === selected);
  const saved = item && versions.find(value => value.id === item.id && !value.purged_at);
  useEffect(() => { if (selected && !saved) setSelected(null); }, [selected, saved]);
  if (!scope || scope.mode === 'unspecified' && !scope.purged) return null;
  function close() { setOpen(false); setSelected(null); trigger.current?.focus(); }
  function toggle() {
    setPosition(menuPosition(trigger.current!));
    setMenu(value => !value);
  }
  const paged = saved?.attachment && ['image', 'pdf'].includes(saved.attachment.kind);
  const references = scope.knowledge_references?.filter(value => value.version_id === selected) ?? [];
  const source = obsidianSource(saved || undefined);
  return <div className="task-material-use">
    <button ref={trigger} type="button" className="icon-button" aria-label="更多回答操作" title="更多" aria-haspopup="menu" aria-expanded={menu} aria-controls={menu ? menuId : undefined} onClick={toggle}><Ellipsis size={17} /></button>
    {menu && <DialogPortal><div ref={popup} id={menuId} role="menu" aria-label="更多回答操作" className="answer-sources-menu" style={position} onKeyDown={event => {
      if (event.key === 'Escape' || event.key === 'Tab') { setMenu(false); trigger.current?.focus(); if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); } }
    }}><button ref={menuItem} type="button" role="menuitem" onClick={() => { setMenu(false); setOpen(true); }}>回答资料范围</button></div></DialogPortal>}
    {open && !saved && <AttachmentDialog title="回答资料范围" className="answer-sources-dialog" closeLabel="关闭回答资料范围" onClose={close}>
      {scope.purged ? <p>资料已清除。</p> : <>
        <p className="answer-sources-summary">{scope.mode === 'only' ? '只依据所选资料' : '参考所选资料'}{scope.knowledge_base_name && ` · 知识库 ${scope.knowledge_base_name}`}</p>
        <ul className="answer-sources-list">{scope.materials.map((material, index) => {
          const version = versions.find(value => value.id === material.id && !value.purged_at);
          const url = sourceUrl(material.url);
          return <li key={material.id}><strong>【资料{index + 1}】{material.title}</strong><div className="answer-source-actions">
            {version ? <button type="button" className="text-button" onClick={() => setSelected(material.id)}>{material.input_mode === 'image' && version.attachment?.kind === 'image' ? '查看图片' : material.input_mode === 'image' ? '查看页面' : '查看内容'}</button> : <span>资料暂不可用</span>}
            {version?.original && <a href={`/api/materials/${kind}/${encodeURIComponent(scopeId)}/versions/${encodeURIComponent(version.id)}/original`} download={version.original.filename}>下载</a>}
            {url && <a href={url} target="_blank" rel="noopener noreferrer">来源网页</a>}
          </div></li>;
        })}</ul>
        {!scope.materials.length && <p>暂无资料。</p>}
      </>}
    </AttachmentDialog>}
    {open && saved && (paged ? <AttachmentPreview kind={kind} id={scopeId} version={saved} pageNumbers={item?.page_numbers} onClose={() => setSelected(null)} />
      : <AttachmentDialog title={item?.title ?? '资料内容'} className="answer-sources-dialog" closeLabel="返回回答资料范围" onClose={() => setSelected(null)}>
        <div className="answer-source-content">{references.length ? references.map((reference, index) => <section key={index}>
          <p>第 {reference.start_line}–{reference.end_line} 行</p>
          <pre>{saved.content?.split(/\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/).slice(reference.start_line - 1, reference.end_line).join('\n')}</pre>
        </section>) : <pre>{saved.content}</pre>}</div>
        {source && <a href={obsidianUri(source.vault_name, source.relative_path)}>在 Obsidian 打开</a>}
      </AttachmentDialog>)}
  </div>;
}

function sourceUrl(value: string | null) {
  try { const url = new URL(value ?? ''); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; }
  catch { return null; }
}

function menuPosition(button: HTMLButtonElement) {
  const rect = button.getBoundingClientRect();
  return { top: Math.max(12, Math.min(rect.bottom + 58 <= window.innerHeight ? rect.bottom + 6 : rect.top - 58, window.innerHeight - 64)),
    left: Math.max(12, Math.min(rect.left, window.innerWidth - 192)) };
}
