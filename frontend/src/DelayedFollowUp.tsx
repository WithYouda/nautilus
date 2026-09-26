import { useEffect, useRef, useState } from 'react';
import { checkDelayed, chooseDelayed, createDelayed, displayDelayed, getDelayed, listHomeDelayed, listOutcomeDelayed, purgeDelayed, revealDelayed, saveDelayedDraft, scheduleDelayed, submitDelayed, type DelayedAnswers, type DelayedAttempt, type DelayedDetail, type DelayedReport, type DelayedReveal, type DelayedSource, type DelayedStandard } from './api';
import PurgeStatus from './PurgeStatus';
import './styles/delayed-follow-up.css';

const key = () => crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
const when = (value: string | null, timezone?: string | null) => value ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: timezone || undefined }).format(new Date(value)) : '尚未安排';
const reportText: Record<DelayedReport, string> = { none: '未使用帮助（用户报告，未独立核实）', used: '使用了帮助', unknown: '不确定' };
const statusText: Record<DelayedDetail['status'], string> = { initial: '初次记录', scheduled: '等待回访', started: '回访作答中', completed: '回访已提交', skipped: '已跳过', purged: '内容已删除' };
const localInput = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}T${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
const errorText = (reason: unknown) => reason instanceof Error ? reason.message : '操作失败，请重试';
type Retry = { operation: string; id: string; requestKey: string } | null;

function SavedAnswers({ value, displayFailed, onRetryDisplay }: { value: DelayedReveal; displayFailed: boolean; onRetryDisplay: () => void }) {
  return <div className="delayed-detail__reveal">
    <p>{value.result ? `${value.result.correct}/${value.result.total} 项正确 · ${value.result.description}` : '答案已保存，检查结果尚不可用。'}</p>
    <ul>{value.items.map(question => {
      const checked = value.result?.items.find(result => result.id === question.id);
      return <li key={question.id}><code>{question.pattern}</code> 对 <code>{question.text}</code>：作答 {value.answers[question.id] ? '是' : '否'}{checked && ` · 标准结果 ${checked.expected ? '是' : '否'} · ${checked.correct ? '正确' : '不同'}`}</li>;
    })}</ul>
    {displayFailed && <button className="button button--quiet" type="button" onClick={onRetryDisplay}>重试记录这次显示</button>}
  </div>;
}

export function DelayedOutcomePanel({ outcomeId, refreshKey }: { outcomeId: string; refreshKey?: number }) {
  const [standard, setStandard] = useState<DelayedStandard | null>(null);
  const [sources, setSources] = useState<DelayedSource[]>([]);
  const [items, setItems] = useState<DelayedDetail[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [sourceIndex, setSourceIndex] = useState(0);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const retry = useRef<Retry>(null);
  const generation = useRef(0);
  async function load() {
    const current = ++generation.current;
    setLoading(true); setError(''); setItems([]); setSources([]); setStandard(null); setSelected(null);
    try {
      const value = await listOutcomeDelayed(outcomeId);
      if (generation.current !== current) return;
      setStandard(value.standard); setSources(value.sources); setItems(value.items);
      setSelected(value.items[0]?.id ?? null);
    } catch (reason) { if (generation.current === current) setError(errorText(reason)); }
    finally { if (generation.current === current) setLoading(false); }
  }
  useEffect(() => { void load(); return () => { generation.current++; }; }, [outcomeId, refreshKey]);
  async function create() {
    const source = sources[sourceIndex];
    if (!source || busy) return;
    const id = `${source.artifact_id}:${source.content_version}`;
    if (retry.current?.operation !== 'create' || retry.current.id !== id) retry.current = { operation: 'create', id, requestKey: key() };
    setBusy(true); setError('');
    try {
      const detail = await createDelayed(outcomeId, source, retry.current.requestKey);
      retry.current = null;
      setItems(previous => [detail, ...previous.filter(item => item.id !== detail.id)]);
      setSelected(detail.id);
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }
  return <section className="delayed-panel" aria-label="窄领域延迟回访">
    <h4>正则匹配判断 · 延迟回访</h4>
    <p className="form-hint">固定两组各 8 项，只判断 Python re.fullmatch 对短字符串是否整体匹配。它只比较同范围表现，不代表迁移或稳定掌握。</p>
    {loading && <p role="status">正在读取回访…</p>}
    {error && <p role="alert">{error} <button className="text-button" type="button" onClick={() => void load()}>重试读取</button></p>}
    {!loading && standard && <p className="form-hint">{standard.title} · v{standard.version} · {standard.review_status === 'approved' ? '已批准' : standard.review_status}</p>}
    {!loading && sources.length > 0 && items.length === 0 && <div className="delayed-panel__create">
      <label>关联的正则成果 <select aria-label="关联的正则成果" value={sourceIndex} onChange={event => setSourceIndex(Number(event.target.value))}>{sources.map((source, index) => <option value={index} key={`${source.artifact_id}:${source.content_version}`}>{source.action_title} · 产出 v{source.content_version}</option>)}</select></label>
      <button className="button" type="button" disabled={busy} onClick={() => void create()}>开始初次记录</button>
    </div>}
    {!loading && !sources.length && !items.length && !error && <p>这个成果目前没有符合条件的正则来源。</p>}
    {!!items.length && <div className="delayed-panel__list">{items.map(item => <button className="button button--quiet" type="button" key={item.id} onClick={() => setSelected(item.id)}>{statusText[item.status]} · {when(item.created_at)}</button>)}</div>}
    {!loading && selected && <DelayedDetailPanel key={`${selected}:${refreshKey ?? ''}`} id={selected} onChanged={detail => setItems(previous => [detail, ...previous.filter(item => item.id !== detail.id)])} />}
  </section>;
}

export function DelayedHomePanel() {
  const [items, setItems] = useState<DelayedDetail[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const generation = useRef(0);
  async function load() {
    const current = ++generation.current;
    setLoading(true); setError(''); setItems([]); setSelected(null);
    try { const value = await listHomeDelayed(); if (generation.current === current) setItems(value.items); }
    catch (reason) { if (generation.current === current) setError(errorText(reason)); }
    finally { if (generation.current === current) setLoading(false); }
  }
  useEffect(() => { void load(); return () => { generation.current++; }; }, []);
  if (!loading && !error && !items.length && !selected) return null;
  return <section className="delayed-panel delayed-panel--home" aria-label="到期回访">
    <div className="delayed-panel__heading"><h3>正则匹配判断回访</h3><button className="text-button" type="button" onClick={() => void load()}>刷新</button></div>
    {loading && <p role="status">正在读取回访安排…</p>}
    {error && <p role="alert">回访安排暂时无法读取：{error} <button className="text-button" type="button" onClick={() => void load()}>重试</button></p>}
    {!loading && !error && !items.length && <p>暂无待处理的正则匹配判断回访。</p>}
    {!!items.length && <div className="delayed-panel__list">{items.map(item => <button className="button button--quiet" key={item.id} type="button" onClick={() => setSelected(item.id)}>{item.is_due ? '已到期' : statusText[item.status]} · {when(item.due_at, item.timezone)}（{item.timezone ?? '本机时区'}）</button>)}</div>}
    {!loading && selected && <DelayedDetailPanel key={selected} id={selected} onChanged={detail => setItems(previous => detail.status === 'scheduled' || detail.status === 'started' ? [detail, ...previous.filter(item => item.id !== detail.id)] : previous.filter(item => item.id !== detail.id))} />}
  </section>;
}

export function DelayedDetailPanel({ id, onChanged }: { id: string; onChanged?: (detail: DelayedDetail) => void }) {
  const [detail, setDetail] = useState<DelayedDetail | null>(null);
  const [answers, setAnswers] = useState<DelayedAnswers>({});
  const [report, setReport] = useState<DelayedReport>('unknown');
  const [date, setDate] = useState('');
  const [reveals, setReveals] = useState<Record<string, DelayedReveal>>({});
  const [displayErrors, setDisplayErrors] = useState<Record<string, boolean>>({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const retry = useRef<Retry>(null);
  const generation = useRef(0);
  const edit = useRef(false);
  const displayed = useRef(new Set<string>());
  const attempt = detail?.attempts.find(item => item.id === detail.active_attempt_id) ?? null;
  function accept(value: DelayedDetail, preserveDraft = false) {
    if (detail && (value.status !== detail.status || value.arranged_at !== detail.arranged_at || value.started_at !== detail.started_at)) { setReveals({}); setDisplayErrors({}); }
    setDetail(value); onChanged?.(value);
    const active = value.attempts.find(item => item.id === value.active_attempt_id);
    if (!preserveDraft || !edit.current) {
      setAnswers(active?.answers ?? {}); setReport(active?.user_report ?? 'unknown'); edit.current = false;
    }
    if (value.due_at) setDate(localInput(new Date(value.due_at)));
    else if (value.attempts[0]?.submitted_at) {
      const suggested = Math.max(new Date(value.attempts[0].submitted_at).getTime() + (value.standard?.suggested_interval_seconds ?? 259200) * 1000, Date.now() + 259200000);
      setDate(localInput(new Date(suggested)));
    }
    if (!value.available || value.status === 'purged') { setReveals({}); setDisplayErrors({}); setAnswers({}); edit.current = false; }
  }
  async function load() {
    const current = ++generation.current;
    setLoading(true); setError(''); setDetail(null); setAnswers({}); setReveals({}); setDisplayErrors({}); displayed.current.clear(); edit.current = false;
    try { const value = await getDelayed(id); if (current === generation.current) accept(value); }
    catch (reason) { if (current === generation.current) setError(errorText(reason)); }
    finally { if (current === generation.current) setLoading(false); }
  }
  useEffect(() => { void load(); return () => { generation.current++; }; }, [id]);
  useEffect(() => {
    if (!detail?.available) return;
    for (const value of Object.values(reveals)) {
      if (displayed.current.has(value.view_id)) continue;
      displayed.current.add(value.view_id);
      void displayDelayed(detail.id, value.view_id).then(() => setDisplayErrors(previous => ({ ...previous, [value.view_id]: false }))).catch(reason => {
        displayed.current.delete(value.view_id);
        setDisplayErrors(previous => ({ ...previous, [value.view_id]: true }));
        setError(`答案已显示，但显示记录失败：${errorText(reason)}`);
      });
    }
  }, [detail, reveals]);
  async function mutate(operation: string, target: string, action: (requestKey: string) => Promise<DelayedDetail>, preserveDraft = false) {
    if (busy) return;
    if (retry.current?.operation !== operation || retry.current.id !== target) retry.current = { operation, id: target, requestKey: key() };
    const requestKey = retry.current.requestKey;
    setBusy(true); setError('');
    try { accept(await action(requestKey), preserveDraft); retry.current = null; }
    catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }
  async function saveDraft() {
    if (!attempt || !detail) return;
    await mutate('draft', attempt.id, () => saveDelayedDraft(detail.id, attempt.id, attempt.revision, answers, report));
  }
  async function submit() {
    if (!attempt || !detail || detail.items.some(item => answers[item.id] === null || answers[item.id] === undefined)) return;
    const complete = Object.fromEntries(detail.items.map(item => [item.id, answers[item.id] as boolean]));
    await mutate('submit', attempt.id, requestKey => submitDelayed(detail.id, attempt.id, attempt.revision, complete, report, requestKey));
  }
  async function reveal(target: DelayedAttempt) {
    if (!detail || busy) return;
    if (target.phase === 'initial' && (detail.status === 'scheduled' || detail.status === 'started') && !detail.attempts.some(item => item.phase === 'followup' && item.submitted_at)) {
      if (!window.confirm('查看初次答案和反馈会被记录为回访前的帮助条件。仍要查看吗？')) return;
    }
    setBusy(true); setError('');
    try {
      const value = await revealDelayed(detail.id, target.id);
      setReveals(previous => ({ ...previous, [target.id]: value }));
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }
  const initial = detail?.attempts.find(item => item.phase === 'initial');
  const maySchedule = detail && initial?.submitted_at && initial.check_status === 'succeeded' && ['initial', 'scheduled', 'skipped', 'started'].includes(detail.status) && !detail.attempts.some(item => item.phase === 'followup' && item.submitted_at);
  return <div className="delayed-detail" aria-label="延迟回访详情">
    {loading && <p role="status">正在读取回访详情…</p>}
    {error && <p role="alert">{error} {!detail && <button className="text-button" type="button" onClick={() => void load()}>重试读取</button>}</p>}
    {detail && <>
      <div className="delayed-panel__heading"><strong>{statusText[detail.status]}</strong><button className="text-button" type="button" disabled={busy} onClick={() => void load()}>刷新状态</button></div>
      {!detail.available || detail.status === 'purged' ? <><p>这项回访的内容当前不可查看。</p>{detail.status === 'purged' ? <PurgeStatus kind="delayed" objectId={detail.id} onRetry={async () => { accept(await purgeDelayed(detail.id)); }} /> : <button className="text-button delayed-detail__purge" type="button" disabled={busy} onClick={() => { if (window.confirm('确认清除这项回访的作答与安排内容？原成果不会因此删除，此操作不可撤销。')) void mutate('purge', detail.id, () => purgeDelayed(detail.id)); }}>清除这项回访</button>}</> : <>
        {detail.due_at && <p>计划时间：{when(detail.due_at, detail.timezone)} · 保存时区：{detail.timezone} {detail.is_due ? '· 已到期' : ''}</p>}
        {detail.attempts.map(item => <article className="delayed-detail__attempt" key={item.id}>
          <h5>{item.phase === 'initial' ? '初次记录 A' : '延迟回访 B'}</h5>
          <p>{item.submitted_at ? `提交于 ${when(item.submitted_at)}（本机时间）` : '尚未提交'} · {item.check_status === 'succeeded' ? '检查已完成' : item.check_status === 'failed' ? '检查失败，可重试' : '尚未检查'}</p>
          {item.submitted_at && <>
            {item.user_report && <p>提交时自报：{reportText[item.user_report]}</p>}
            {item.condition && <><p>产品内已记录查看 {item.condition.observed_views.length} 次；外部资料及间隔内学习未知，独立性未核实。</p>{!!item.condition.observed_views.length && <details><summary>查看帮助条件记录</summary><ul>{item.condition.observed_views.map((view, index) => <li key={`${view.attempt_id}:${view.provided_at}:${index}`}>{view.after_arranging ? '安排后' : '安排前'} · 提供于 {when(view.provided_at)}（本机时间） · 页面显示于 {view.displayed_at ? `${when(view.displayed_at)}（本机时间）` : '未记录'}</li>)}</ul></details>}</>}
            {item.check_status !== 'succeeded' && <button className="button" type="button" disabled={busy} onClick={() => void mutate('check', item.id, () => checkDelayed(detail.id, item.id))}>运行确定性检查</button>}
            <button className="button button--quiet" type="button" disabled={busy} onClick={() => void reveal(item)}>查看已保存答案{item.check_status === 'succeeded' ? '与检查结果' : ''}</button>
            {reveals[item.id] && <SavedAnswers value={reveals[item.id]} displayFailed={!!displayErrors[reveals[item.id].view_id]} onRetryDisplay={() => setReveals(previous => ({ ...previous }))} />}
          </>}
        </article>)}
        {attempt && !attempt.submitted_at && (detail.status === 'initial' || detail.status === 'started') && <section className="delayed-detail__form" aria-label={attempt.phase === 'initial' ? '初次作答' : '回访作答'}>
          <p>逐项判断 <code>re.fullmatch(pattern, text)</code> 是否匹配整个字符串。未作答的项目可以保留在草稿中。</p>
          {detail.items.map(item => <fieldset key={item.id} disabled={busy}><legend><code>{item.pattern}</code> 对 <code>{item.text}</code></legend><label><input type="radio" name={`delayed-${item.id}`} checked={answers[item.id] === true} onChange={() => { setAnswers(previous => ({ ...previous, [item.id]: true })); edit.current = true; }} /> 是</label><label><input type="radio" name={`delayed-${item.id}`} checked={answers[item.id] === false} onChange={() => { setAnswers(previous => ({ ...previous, [item.id]: false })); edit.current = true; }} /> 否</label></fieldset>)}
          <label>本次作答使用帮助了吗？ <select disabled={busy} value={report} onChange={event => { setReport(event.target.value as DelayedReport); edit.current = true; }}><option value="unknown">不确定</option><option value="none">未使用帮助</option><option value="used">使用了帮助</option></select></label>
          <div className="delayed-panel__actions"><button className="button button--quiet" type="button" disabled={busy} onClick={() => void saveDraft()}>保存草稿</button><button className="button" type="button" disabled={busy || detail.items.some(item => answers[item.id] === null || answers[item.id] === undefined)} onClick={() => void submit()}>提交全部 8 项</button></div>
        </section>}
        {maySchedule && <section className="delayed-detail__schedule"><h5>{detail.due_at ? '调整回访时间' : '安排回访时间'}</h5><p>至少在初次提交 24 小时后；建议 3 天后。实际比较间隔以两次提交时间为准。</p><label>本机日期时间 <input type="datetime-local" disabled={busy} value={date} onChange={event => setDate(event.target.value)} /></label><p>本机时区：{Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'}{detail.due_at && detail.timezone !== (Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC') ? ` · 原安排时区 ${detail.timezone}` : ''}</p><button className="button" type="button" disabled={busy || !date || Number.isNaN(new Date(date).getTime())} onClick={() => { const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; void mutate('schedule', `${date}:${zone}`, requestKey => scheduleDelayed(detail.id, new Date(date).toISOString(), zone, requestKey)); }}>{detail.due_at ? '保存改期' : '安排回访'}</button></section>}
        {detail.status === 'scheduled' && <div className="delayed-panel__actions">{detail.is_due && <button className="button" type="button" disabled={busy} onClick={() => void mutate('start', detail.id, requestKey => chooseDelayed(detail.id, 'start', requestKey))}>开始回访</button>}<button className="button button--quiet" type="button" disabled={busy} onClick={() => void mutate('skip', detail.id, requestKey => chooseDelayed(detail.id, 'skip', requestKey))}>跳过这次回访</button></div>}
        {detail.status === 'started' && <button className="button button--quiet" type="button" disabled={busy} onClick={() => void mutate('skip', detail.id, requestKey => chooseDelayed(detail.id, 'skip', requestKey))}>跳过这次回访</button>}
        {detail.comparison && <section><h5>两次记录比较</h5><p>{detail.comparison.description}</p><p>实际提交间隔：{(detail.comparison.interval_seconds / 3600).toFixed(1)} 小时 · 初次 {detail.comparison.initial_correct}/8 · 回访 {detail.comparison.followup_correct}/8 · {detail.comparison.interval_met ? '达到最小间隔' : '不足 24 小时'}</p><p>这只是固定题组的同范围再测；独立性、间隔内学习和迁移能力未由产品核实。</p></section>}
        {!!detail.history.length && <details><summary>安排变更记录</summary><ul>{detail.history.map((entry, index) => <li key={index}>{entry.operation} · {when(entry.at)}（本机时间）{entry.due_at ? ` · ${when(entry.due_at, entry.timezone)}（${entry.timezone ?? '本机时区'}）` : ''}</li>)}</ul></details>}
        <button className="text-button delayed-detail__purge" type="button" disabled={busy} onClick={() => { if (window.confirm('确认清除这项回访的作答与安排内容？原成果不会因此删除，此操作不可撤销。')) void mutate('purge', detail.id, () => purgeDelayed(detail.id)); }}>清除这项回访</button>
      </>}
    </>}
  </div>;
}
