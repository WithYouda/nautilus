import { useState } from 'react';
import type { SearchResult } from './searchApi';

type SearchRequestTrace = { action: 'search' | 'scrape'; query?: string; url?: string; status: string; retrieved_at?: string; message?: string };
export type SearchTrace = {
  mode: 'off' | 'external' | 'native';
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'not_used' | 'off';
  service_name?: string; query?: string; retrieved_at?: string; message?: string;
  items?: SearchResult['items']; answer?: string | null; images?: SearchResult['images'];
  content?: string; url?: string; scraped_urls?: SearchResult['urls'];
  requests?: SearchRequestTrace[];
  search_suggestions_html?: string | null;
};
const safeUrl = (value: string) => {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; }
  catch { return null; }
};
function Excerpt({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  if (text.length < 500) return <p className="search-result-text">{text}</p>;
  return <div><p className="search-result-text">{open ? text : `${text.slice(0, 460)}…`}</p><button className="search-text-toggle" type="button" onClick={() => setOpen(!open)}>{open ? '收起' : '展开全文'}</button></div>;
}
const requestStatus = (status: string) => ({ queued: '等待中', running: '进行中', succeeded: '成功', failed: '失败', not_used: '未执行' }[status] ?? '未知状态');
const time = (value?: string) => { const date = value ? new Date(value) : null; return date && !Number.isNaN(date.valueOf()) ? date.toLocaleString() : null; };
export default function SearchResults({ trace }: { trace: SearchTrace | null | undefined }) {
  if (!trace || trace.mode === 'off' || trace.status === 'off') return null;
  const labels: Record<SearchTrace['status'], string> = { queued: '等待搜索', running: '正在搜索', succeeded: '已取得搜索响应', failed: '搜索失败', not_used: '本轮未执行搜索', off: '搜索已关闭' };
  const items = trace.items ?? [];
  const images = trace.images ?? [];
  const suggestions = trace.search_suggestions_html?.slice(0, 65_536);
  const suggestionDoc = suggestions ? `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data: https://www.gstatic.com; base-uri 'none'; form-action 'none'"><base target="_blank">${suggestions}` : undefined;
  return <div className="search-result-block"><details className="search-results" aria-label="联网搜索结果">
    <summary><strong>{labels[trace.status]}</strong>{trace.service_name && <span> · {trace.service_name}</span>}<span> · {items.length} 条来源</span></summary>
    <div className="search-results-body">
      {trace.retrieved_at && time(trace.retrieved_at) && <time dateTime={trace.retrieved_at}>检索于 {time(trace.retrieved_at)}</time>}
      {trace.query && <p className="search-results-query">查询：{trace.query}</p>}
      {trace.message && <p className={trace.status === 'failed' ? 'form-error' : 'form-hint'}>{trace.message}</p>}
      {!!trace.requests?.length && <details className="search-request-history"><summary>检索过程 · {trace.requests.length} 次请求</summary><ol>{trace.requests.map((request, index) => <li key={index}><strong>{request.action === 'search' ? '搜索' : '抓取'} · {requestStatus(request.status)}</strong>{request.query && <p>查询：{request.query}</p>}{request.url && <p>网址：{safeUrl(request.url) ? <a href={safeUrl(request.url)!} target="_blank" rel="noopener noreferrer">{request.url}</a> : request.url}</p>}{request.retrieved_at && time(request.retrieved_at) && <time dateTime={request.retrieved_at}>{time(request.retrieved_at)}</time>}{request.message && <p>{request.message}</p>}</li>)}</ol></details>}
      {trace.status === 'succeeded' && <>
        {trace.answer && <div className="search-result-answer"><strong>服务返回的摘要</strong><Excerpt text={trace.answer} /></div>}
        {trace.content && <div className="search-result-answer"><strong>抓取内容</strong><Excerpt text={trace.content} /></div>}
        {trace.scraped_urls?.map((page, index) => <div className="search-result-answer" key={`${page.url}-${index}`}><strong>抓取页面 {index + 1}</strong> {safeUrl(page.url) && <a href={safeUrl(page.url)!} target="_blank" rel="noopener noreferrer">{page.url}</a>}<Excerpt text={page.content || '服务未返回页面内容。'} /></div>)}
        {trace.url && safeUrl(trace.url) && <a href={safeUrl(trace.url)!} target="_blank" rel="noopener noreferrer">查看抓取页面</a>}
        {items.length > 0 && <ol className="search-result-items">{items.map((item, index) => <li key={`${item.url}-${index}`}>
          {safeUrl(item.url) ? <a href={safeUrl(item.url)!} target="_blank" rel="noopener noreferrer">{item.title || item.url}</a> : <strong>{item.title || '无效来源链接'}</strong>}
          {item.published_date && <small>发布于 {item.published_date}</small>}{item.text && <Excerpt text={item.text} />}
        </li>)}</ol>}
        {images.length > 0 && <div className="search-result-images">{images.map((image, index) => { const url = typeof image === 'string' ? image : image.url; return safeUrl(url) && <a key={`${url}-${index}`} href={safeUrl(url)!} target="_blank" rel="noopener noreferrer">{typeof image === 'string' ? `图片 ${index + 1}` : image.title || `图片 ${index + 1}`}</a>; })}</div>}
        {!trace.answer && !trace.content && !trace.url && !trace.scraped_urls?.length && items.length === 0 && images.length === 0 && <p className="form-hint">服务已响应，但没有返回可展示的结果。</p>}
        <p className="form-hint">检索时间不等于发布日期。</p>
      </>}
    </div>
  </details>{suggestionDoc && <div className="search-suggestions"><strong>Google 搜索建议</strong><iframe title="Google 搜索建议" className="search-suggestions-frame" sandbox="allow-popups allow-popups-to-escape-sandbox" referrerPolicy="no-referrer" srcDoc={suggestionDoc} /></div>}</div>;
}
