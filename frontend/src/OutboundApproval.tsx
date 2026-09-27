import { useEffect, useState } from 'react';
import { ApiError, decideOutboundRequest, getOutboundRequests, type OutboundRequest } from './api';
import './styles/outbound-approval.css';

type Props = { kind: 'conversation' | 'discussion'; scopeId: string | null; active: boolean };

function queryParameters(url: string) {
  try { return Array.from(new URL(url).searchParams.entries()).map(([key, value]) => `${key}: ${value}`).join('\n'); }
  catch { return ''; }
}


function readableBody(body: string): string {
  try { return JSON.stringify(JSON.parse(body), null, 2); }
  catch { return body; }
}

export default function OutboundApproval({ kind, scopeId, active }: Props) {
  const [items, setItems] = useState<OutboundRequest[]>([]);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    setItems([]);
    setError('');
    if (!scopeId || !active) return;
    let live = true;
    let loading = false;
    const load = async () => {
      if (loading) return;
      loading = true;
      try {
        const result = await getOutboundRequests(kind, scopeId);
        if (live) { setItems(result.items); setError(''); }
      } catch (reason) {
        if (live) setError(reason instanceof Error ? reason.message : '无法读取待确认的外发请求。');
      } finally { loading = false; }
    };
    void load();
    const timer = window.setInterval(() => void load(), 1000);
    return () => { live = false; window.clearInterval(timer); };
  }, [kind, scopeId, active, revision]);

  if (!scopeId || (!active && !items.length)) return null;

  const decide = async (item: OutboundRequest, decision: 'approve' | 'deny' | 'cancel') => {
    if (busyId) return;
    setBusyId(item.id);
    setError('');
    try {
      await decideOutboundRequest(item.id, item.digest, decision);
      setItems(previous => previous.filter(entry => entry.id !== item.id));
      setRevision(value => value + 1);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        setError('这次外发请求已失效，正在读取当前待确认内容。');
        setRevision(value => value + 1);
      } else setError(reason instanceof Error ? reason.message : '处理失败，请重试。');
    } finally { setBusyId(null); }
  };

  return <section className="outbound-approval" aria-label="外发确认">
    {error && <p role="alert" className="outbound-approval__error">{error}</p>}
    {items.map(item => <article key={item.id} className="outbound-approval__card">
      <h3>确认这次外发</h3>
      <p>教学模型已经可以使用当前学习内容；这里要确认的是向外部搜索服务发送信息。请核对实际接收方和完整请求。</p>
      {item.reason && <p>{item.reason}</p>}
      <dl><dt>接收服务</dt><dd>{item.service_name}</dd><dt>请求地址</dt><dd className="outbound-approval__literal">{item.method} {item.url}</dd></dl>
      {queryParameters(item.url) && <><strong>网址中的查询参数</strong><pre>{queryParameters(item.url)}</pre></>}
      <strong>本次发送内容</strong><pre>{item.body ? readableBody(item.body) : '（无请求正文；请核对上面的完整请求地址）'}</pre>
      <details><summary>查看完整请求头</summary>
        <pre>{Object.entries(item.headers).map(([name, value]) => `${name}: ${value}`).join('\n') || '（无请求头）'}</pre>
      </details>
      <p className="outbound-approval__meaning">允许只发送上面这一次请求；拒绝后 AI 会继续使用已有依据回答；取消会停止本轮回答。</p>
      <div className="outbound-approval__actions">
        <button className="button button--accent" type="button" disabled={Boolean(busyId)} onClick={() => void decide(item, 'approve')}>允许这次发送</button>
        <button className="button button--quiet" type="button" disabled={Boolean(busyId)} onClick={() => void decide(item, 'deny')}>拒绝这次发送</button>
        <button className="button button--danger" type="button" disabled={Boolean(busyId)} onClick={() => void decide(item, 'cancel')}>取消本轮回答</button>
      </div>
    </article>)}
  </section>;
}
