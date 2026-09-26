import { useEffect, useRef, useState } from 'react';
import type { HelpRecord as HelpRecordValue } from './api';

const labels = { hint: '给个提示', explain_step: '只解释这一步', example: '换个例子', try_first: '让我先试试' };

export function HelpRecordFacts({ record, display }: { record: HelpRecordValue; display?: HelpRecordValue['display'] }) {
  const shown = display === undefined ? record.display : display;
  return <>
    <p>请求：{record.request ? `${labels[record.request.kind]} · ${new Date(record.request.at).toLocaleString()}` : '无记录'}</p>
    <p>已生成正文：{record.provided ? `${record.provided.characters} 字符${record.provided.partial ? ' · 部分输出' : ''}${record.provided.at ? ` · ${new Date(record.provided.at).toLocaleString()}` : ''}` : '无记录'}</p>
    <p>页面呈现正文（客户端记录）：{shown ? `${shown.characters} 字符 · ${new Date(shown.at).toLocaleString()}` : '无记录'}</p>
    <p className="form-hint">字符数是正文长度，不代表逐字可见；展示不代表已阅读或理解；无记录不证明独立完成。</p>
  </>;
}

export default function HelpRecord({ record, body, terminal, onDisplay, showDetails = true }: {
  record?: HelpRecordValue | null; body: string; terminal: boolean;
  onDisplay: (characters: number) => Promise<HelpRecordValue>;
  showDetails?: boolean;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const busy = useRef(false);
  const [display, setDisplay] = useState(record?.display ?? null);
  const [visible, setVisible] = useState(false);
  const [error, setError] = useState(false);
  useEffect(() => { if (record?.display) { setDisplay(record.display); setError(false); } }, [record?.display]);
  useEffect(() => {
    if (!terminal || !body || !record?.provided || display || !bodyRef.current) return;
    const bodyNodes = bodyRef.current.closest('.ai-message--assistant')?.querySelectorAll('.ai-assistant-response .ai-message-content');
    if (!bodyNodes?.length) return;
    const observer = new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting && entry.target.getClientRects().length)) setVisible(true); }, { threshold: 0 });
    bodyNodes.forEach(node => observer.observe(node));
    return () => observer.disconnect();
  }, [terminal, body, record?.provided, display]);
  useEffect(() => {
    if (!visible || !terminal || !body || !record?.provided || display || error || busy.current) return;
    busy.current = true;
    void onDisplay(Array.from(body).length).then(value => { setDisplay(value.display); setError(false); })
      .catch(() => setError(true)).finally(() => { busy.current = false; });
  }, [visible, terminal, body, record?.provided, display, error, onDisplay]);
  if (!record) return null;
  return <div className={showDetails ? 'help-record' : 'help-record-observer'} ref={bodyRef}>
    {showDetails && <details><summary>帮助记录</summary><HelpRecordFacts record={record} display={display} /></details>}
    {error && showDetails && <button type="button" className="text-button" onClick={() => { setError(false); setVisible(true); }}>展示记录未保存，重试</button>}
  </div>;
}
