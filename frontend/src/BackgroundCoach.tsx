import { useEffect, useId, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { ApiError, approveAgentPermissionRequest, createAgentPermissionRequest, denyAgentPermissionRequest, listAgentPermissionRequests, revokeAgentPermissionGrant, type AgentPermissionRequest } from './api';
import { AttachmentDialog } from './AttachmentReview';
import { cancelCoachRun, checkCoach, coachHref, coachKey, correctCoachSignal, decideCoachCandidate, getCoach, getCoachCandidate, getCoachRun, getCoachSignals, navigateCoach, purgeCoachRun, type CoachAssignmentSignal, type CoachCandidate, type CoachDecision, type CoachRun, type CoachRunDetail, type CoachScope, type CoachSignal, type CoachView } from './background-coach-api';
import './styles/background-coach.css';

const statusLabels = { pending: '待考虑', accepted: '已接受', rejected: '已拒绝', ignored: '暂不处理', unavailable: '来源已变化' };
const runLabels = { queued: '等待复盘', running: '正在复盘', succeeded: '复盘完成', failed: '复盘未完成', canceled: '已取消复盘', purged: '复盘内容已清除' };
const signalLabels = { separate_work_requested: '考虑单独安排这项工作', repeated_blocker: '回看多次阻塞的依据', scope_conflict: '核对当前任务范围', cannot_continue: '先核对继续学习的条件', permission_or_cost_change: '先核对权限或投入变化' };
const reasonLabels: Record<string, string> = { coach_disabled: '自动复盘已关闭。仍可手动复盘。', coach_no_new_signals: '没有新的有效记录需要复盘。', coach_batch_consumed: '这批记录已经复盘，可查看已有建议。失败的复盘需明确重试。', coach_day_limit: '今天已达到自动复盘次数，可手动复盘。', coach_session_limit: '本次会话已达到自动复盘次数，可手动复盘。', coach_cooldown: '自动复盘正在冷却，可手动复盘。', coach_active: '已有复盘正在进行。' };
const runReason = (reason: string | null) => reason ? ({ interrupted: '复盘已中断，请明确重试。', invalid_proposal: '模型返回的建议无法使用，请核对来源后重试。', generation_failed: '模型复盘未完成，请核对提供方设置后重试。', content_purged: '复盘内容已清除。', disabled: '自动复盘已关闭。', coach_input_changed: '来源已变化，请重新核对记录。', auth_error: '提供方未通过授权，请检查模型和凭据。' } as Record<string, string>)[reason] ?? (reason.includes('_') ? '复盘未完成，请核对模型和来源后明确重试。' : reason) : '请核对模型设置后重试。';
const errorText = (reason: unknown) => reason instanceof Error ? reason.message : '操作未完成，请重试。';
const ongoing = (run: CoachRun | null | undefined) => run?.status === 'queued' || run?.status === 'running';
function followCoachLink(event: ReactMouseEvent<HTMLAnchorElement>) { event.preventDefault(); navigateCoach(event.currentTarget.getAttribute('href') ?? ''); }

function CandidateContent({ candidate }: { candidate: CoachCandidate }) {
  return <>
    <h4>{candidate.title ?? '这条建议的内容已不可查看'}</h4>
    {candidate.explanation && <p>{candidate.explanation}</p>}
    <details className="background-coach__basis"><summary>依据与仍未知的内容</summary>
      {!!candidate.sources.length && <ul>{candidate.sources.map(source => { const href = source.available ? coachHref(source.href) : null, label = source.kind === 'permission' ? '本次读取授权' : source.kind === 'artifact' ? '关联的学习产出' : source.label; return <li key={`${source.kind}:${source.id}`}>{href ? <a href={href} onClick={followCoachLink}>{label}</a> : <span>{label}{!source.available && ' · 当前不可查看'}</span>}</li>; })}</ul>}
      {!!candidate.unknowns.length && <ul>{candidate.unknowns.map((item, index) => <li key={index}>{item}</li>)}</ul>}
      {!candidate.sources.length && !candidate.unknowns.length && <p>这条建议没有可展开的依据。</p>}
    </details>
  </>;
}

function RunDetail({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const [detail, setDetail] = useState<CoachRunDetail | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const requestKey = useRef<string | null>(null);
  const alive = useRef(true);
  async function load() { setError(''); try { const next = await getCoachRun(id); if (alive.current) setDetail(next); } catch (reason) { if (alive.current) setError(errorText(reason)); } }
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; }; }, [id]);
  async function purge() {
    if (!detail || busy || !window.confirm('清除这次复盘的说明、输入和建议内容？管理范围内副本也会清除，原学习记录保留。此操作不可撤销。')) return;
    requestKey.current ??= coachKey(); setBusy(true); setError('');
    try { setDetail(await purgeCoachRun(detail.run, requestKey.current)); requestKey.current = null; onChanged(); }
    catch (reason) { setError(errorText(reason)); if (reason instanceof ApiError && reason.status === 409) { requestKey.current = null; await load(); } }
    finally { setBusy(false); }
  }
  return <AttachmentDialog title="教练复盘详情" closeLabel="关闭教练详情" onClose={onClose} className="background-coach-dialog">
    <div className="background-coach-dialog__body">
      {error && <p role="alert">{error} <button className="text-button" type="button" onClick={() => void load()}>重新读取</button></p>}
      {!detail && !error && <p role="status">正在读取复盘…</p>}
      {detail && <><p>{runLabels[detail.run.status]} · {new Date(detail.run.created_at).toLocaleString()}</p>
        {detail.run.reason && <p>{runReason(detail.run.reason)}</p>}
        {detail.candidates.map(candidate => <article className="background-coach__card" key={candidate.id}><small>{statusLabels[candidate.status]}</small><CandidateContent candidate={candidate} /></article>)}
        {detail.run.status === 'succeeded' && !detail.candidates.length && <p>这次复盘没有需要提出的建议。</p>}
        <details><summary>调用信息与摘要范围</summary>
          {detail.run.provider_snapshot ? <pre>{JSON.stringify(detail.run.provider_snapshot, null, 2)}</pre> : <p>调用信息不可查看。</p>}
          {detail.inputs ? <pre>{JSON.stringify(detail.inputs, null, 2)}</pre> : <p>本次摘要已不可查看。</p>}
        </details>
        {detail.purge_report && <details><summary>内容清除进度</summary><pre>{JSON.stringify(detail.purge_report, null, 2)}</pre></details>}
        {!ongoing(detail.run) && (detail.run.content_available || detail.purge_report) && <button className="text-button" type="button" disabled={busy} onClick={() => void purge()}>{detail.run.status === 'purged' ? '重试内容清除' : '清除这次复盘内容'}</button>}
      </>}
    </div>
  </AttachmentDialog>;
}

function Signals({ scope, planId }: { scope: CoachScope; planId?: string }) {
  const [items, setItems] = useState<CoachSignal[]>([]), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const retry = useRef<{ id: string; operation: 'exclude' | 'restore'; key: string } | null>(null);
  async function load() { try { setItems((await getCoachSignals(scope, planId)).items); setError(''); } catch (reason) { setError(errorText(reason)); } }
  useEffect(() => { void load(); }, [scope, planId]);
  async function correct(item: CoachSignal) {
    if (busy) return;
    const operation = item.status === 'excluded' ? 'restore' : 'exclude';
    if (!retry.current || retry.current.id !== item.id || retry.current.operation !== operation) retry.current = { id: item.id, operation, key: coachKey() };
    setBusy(true); setError('');
    try { const next = await correctCoachSignal(item, operation, retry.current.key); retry.current = null; setItems(previous => previous.map(value => value.id === next.id ? next : value)); window.dispatchEvent(new Event('nautilus:coach-updated')); }
    catch (reason) { setError(errorText(reason)); if (reason instanceof ApiError && reason.status === 409) { retry.current = null; await load(); } }
    finally { setBusy(false); }
  }
  return <div className="background-coach__signals">
    {error && <p role="alert">{error} <button className="text-button" type="button" onClick={() => void load()}>重新读取信号</button></p>}
    {!items.length && !error && <p>暂无可核对的任务信号。</p>}
    {items.map(item => <article key={item.id}><p>{signalLabels[item.kind]}{item.status === 'excluded' && ' · 已排除'}{item.status === 'unavailable' && ' · 来源已变化'}</p>{item.source_available && coachHref(item.source.href) && <a href={coachHref(item.source.href)!} onClick={followCoachLink}>{item.source.label}</a>}<button className="text-button" type="button" disabled={busy || !item.source_available || item.status === 'unavailable'} onClick={() => void correct(item)}>{item.status === 'excluded' ? '恢复信号' : '排除误判'}</button></article>)}
  </div>;
}

export default function BackgroundCoach({ scope = 'global', planId }: { scope?: CoachScope; planId?: string }) {
  const [view, setView] = useState<CoachView | null>(null), [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false), [detailId, setDetailId] = useState<string | null>(null), [signalsOpen, setSignalsOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const listId = useId();
  const identity = `${scope}:${planId ?? ''}`, current = useRef(identity); current.current = identity;
  const alive = useRef(false), serial = useRef(0);
  const mutation = useRef(0);
  const attempt = useRef<{ kind: string; key: string; payload?: CoachDecision } | null>(null);
  const run = view?.active_run ?? view?.latest_run ?? null;
  const runRef = useRef(run); runRef.current = run;
  const here = () => alive.current && current.current === identity;
  async function read() {
    const sequence = ++serial.current, generation = mutation.current, next = await getCoach(scope, planId);
    if (here() && sequence === serial.current && generation === mutation.current) setView(next);
    return next;
  }
  async function check(trigger: 'manual' | 'return', retryRunId?: string) {
    if (busy) return;
    let generation = ++mutation.current;
    serial.current++;
    const kind = `check:${trigger}:${retryRunId ?? ''}`;
    if (attempt.current?.kind !== kind) attempt.current = { kind, key: coachKey() };
    setBusy(true); if (trigger === 'manual') { setError(''); setNotice(''); }
    try {
      const retryRun = retryRunId && run?.id === retryRunId ? run : null;
      const requestScope = retryRun?.scope ?? scope, requestPlan = retryRun ? retryRun.plan_id : planId;
      const result = await checkCoach({ scope: requestScope, ...(requestScope === 'plan' && requestPlan ? { plan_id: requestPlan } : {}), trigger, request_key: attempt.current.key, ...(retryRunId ? { retry_run_id: retryRunId } : {}), ...(retryRun?.permission_candidate_id && retryRun.permission_request_id ? { permission_candidate_id: retryRun.permission_candidate_id, permission_request_id: retryRun.permission_request_id } : {}) });
      if (!here() || generation !== mutation.current) return;
      generation = ++mutation.current;
      serial.current++;
      if (requestScope === scope && requestPlan === (planId ?? null)) setView(result.view); else await read();
      attempt.current = null;
      if (trigger === 'manual' && result.reason) setNotice(reasonLabels[result.reason] ?? '这次没有发起新复盘。请核对已有建议和来源。');
    } catch (reason) { if (here() && generation === mutation.current) { setError(errorText(reason)); if (reason instanceof ApiError && reason.status !== null) attempt.current = null; } }
    finally { if (here() && generation === mutation.current) setBusy(false); }
  }
  useEffect(() => {
    alive.current = true; setView(null); setError(''); setNotice(''); setExpanded(false); attempt.current = null;
    const generation = mutation.current;
    void read().then(value => { if (here() && generation === mutation.current && value.settings.enabled && !ongoing(value.active_run)) void check('return'); }).catch(reason => { if (here()) setError(errorText(reason)); });
    const refresh = () => { void read().catch(reason => { if (here()) setError(errorText(reason)); }); };
    window.addEventListener('nautilus:coach-updated', refresh); window.addEventListener('nautilus:coach-settings-changed', refresh);
    return () => { alive.current = false; serial.current++; mutation.current++; window.removeEventListener('nautilus:coach-updated', refresh); window.removeEventListener('nautilus:coach-settings-changed', refresh); };
  }, [identity]);
  useEffect(() => {
    if (!ongoing(run)) return;
    let active = true, timer: number | undefined;
    const sameRun = () => active && here() && runRef.current?.id === run!.id && ongoing(runRef.current);
    const poll = async () => {
      const generation = mutation.current;
      try {
        const next = await getCoachRun(run!.id);
        if (!sameRun()) return;
        if (generation === mutation.current && next.run.revision >= (runRef.current?.revision ?? 0)) {
          if (ongoing(next.run)) setView(previous => {
            const displayed = previous?.active_run ?? previous?.latest_run;
            return previous && here() && generation === mutation.current && displayed?.id === next.run.id && displayed.revision <= next.run.revision ? { ...previous, active_run: next.run, latest_run: next.run } : previous;
          });
          else await read();
        }
        if (sameRun()) timer = window.setTimeout(() => void poll(), 1000);
      } catch (reason) { if (sameRun()) { setError(`复盘状态暂时无法读取：${errorText(reason)}`); timer = window.setTimeout(() => void poll(), 2500); } }
    };
    timer = window.setTimeout(() => void poll(), 700);
    return () => { active = false; window.clearTimeout(timer); };
  }, [identity, run?.id, run?.status]);
  async function decision(candidate: CoachCandidate, operation: CoachDecision['operation']) {
    if (busy) return;
    let generation = ++mutation.current;
    serial.current++;
    const kind = `decision:${candidate.id}:${operation}`;
    if (attempt.current?.kind !== kind) attempt.current = { kind, key: coachKey(), payload: { operation, expected_revision: candidate.revision, request_key: coachKey() } };
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await decideCoachCandidate(candidate.id, attempt.current.payload!); attempt.current = null;
      if (!here() || generation !== mutation.current) return;
      generation = ++mutation.current; serial.current++;
      const href = result.navigation ? coachHref(result.navigation.href, candidate.id) : null;
      if (operation === 'accept') {
        setNotice('已接受建议。打开原入口后，再确认实际操作。');
        await read();
        if (!here() || generation !== mutation.current) return;
        if (href) navigateCoach(href); else setError('建议已记录为接受，但目标入口当前不可打开。请重新读取建议后核对来源。');
      } else { await read(); if (here() && generation === mutation.current) setNotice(operation === 'undo' ? '已撤销建议处理。已单独确认的任务、路线或安排需在原入口调整。' : operation === 'ignore' ? '已暂时收起，可在处理记录中重新考虑。' : '已拒绝这条建议。'); }
    } catch (reason) { if (here() && generation === mutation.current) { setError(errorText(reason)); if (reason instanceof ApiError && reason.status !== null) { attempt.current = null; if (reason.status === 409) await read().catch(() => undefined); } } }
    finally { if (here() && generation === mutation.current) setBusy(false); }
  }
  async function cancel() {
    if (!run || busy) return;
    let generation = ++mutation.current;
    serial.current++;
    const kind = `cancel:${run.id}`; if (attempt.current?.kind !== kind) attempt.current = { kind, key: coachKey() };
    setBusy(true); setError('');
    try { await cancelCoachRun(run, attempt.current.key); if (!here() || generation !== mutation.current) return; generation = ++mutation.current; serial.current++; attempt.current = null; await read(); if (here() && generation === mutation.current) setNotice('已取消复盘，原学习可继续。'); }
    catch (reason) { if (here() && generation === mutation.current) { setError(errorText(reason)); if (reason instanceof ApiError && reason.status === 409) { attempt.current = null; await read().catch(() => undefined); } } }
    finally { if (here() && generation === mutation.current) setBusy(false); }
  }
  function card(candidate: CoachCandidate, history = false) {
    const href = candidate.target ? coachHref(candidate.target.href, candidate.id) : null;
    return <article className="background-coach__card" key={candidate.id} data-coach-candidate={candidate.id}>
      {history && <small>{statusLabels[candidate.status]}</small>}<CandidateContent candidate={candidate} />
      <div className="background-coach__actions">
        {candidate.status === 'pending' && <><button className="button button--quiet button--compact" type="button" disabled={busy || !candidate.content_available || !href} onClick={() => void decision(candidate, 'accept')}>接受并查看</button><button className="text-button" type="button" disabled={busy} onClick={() => void decision(candidate, 'reject')}>拒绝</button><button className="text-button" type="button" disabled={busy} onClick={() => void decision(candidate, 'ignore')}>暂不处理</button></>}
        {candidate.status === 'accepted' && href && <a href={href} onClick={followCoachLink}>再次打开{candidate.target?.label}</a>}
        {['accepted', 'rejected', 'ignored'].includes(candidate.status) && <button className="text-button" type="button" disabled={busy} onClick={() => void decision(candidate, 'undo')}>撤销处理</button>}
        <button className="text-button" type="button" onClick={() => setDetailId(candidate.run_id)}>原复盘</button>
      </div>
    </article>;
  }
  return <section className={`background-coach${scope === 'global' ? ' background-coach--home' : ''}`} aria-label={scope === 'global' ? '后台教练' : '计划后台教练'}>
    <div className="background-coach__heading"><h3>后台教练</h3><div className="background-coach__actions"><button className="text-button" type="button" disabled={!view || busy || ongoing(run)} onClick={() => void check('manual')}>手动复盘</button><button className="text-button" type="button" disabled={busy} onClick={() => void read().then(() => setError('')).catch(reason => setError(errorText(reason)))}>刷新</button></div></div>
    {!view && !error && <p role="status">正在读取建议…</p>}
    {ongoing(run) && <div className="background-coach__run"><p role="status">{run?.status === 'queued' ? '等待模型复盘…' : '正在复盘这些记录…'}</p><button className="text-button" type="button" disabled={busy} onClick={() => void cancel()}>取消复盘</button></div>}
    {run && (run.status === 'failed' || run.status === 'canceled') && <div className="background-coach__run"><p role={run.status === 'failed' ? 'alert' : 'status'}>{run.status === 'failed' ? `这次复盘未完成：${runReason(run.reason)}` : '已取消这次复盘，原学习可继续。'}</p><button className="text-button" type="button" disabled={busy || ongoing(view?.active_run)} onClick={() => void check('manual', run.id)}>重试这次复盘</button></div>}
    {error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="background-coach__notice" role="status">{notice}</p>}
    {view && view.candidates.length > 0 && <p className="background-coach__count">{view.candidates.length} 条待处理建议</p>}
    <div id={listId} className="background-coach__list">{(expanded ? view?.candidates : view?.candidates.slice(0, 1))?.map(candidate => card(candidate))}</div>
    {view && view.candidates.length > 1 && <button className="text-button background-coach__expand" type="button" aria-expanded={expanded} aria-controls={listId} onClick={() => setExpanded(value => !value)}>{expanded ? '收起其余建议' : `查看其余建议（${view.candidates.length - 1}）`}</button>}
    {view && !view.candidates.length && !ongoing(run) && run?.status !== 'failed' && run?.status !== 'canceled' && <p className="background-coach__empty">暂无待处理建议。</p>}
    {view && <details className="background-coach__more"><summary>处理记录与复盘设置</summary>
      <p>接受建议会打开原入口；实际变化仍由本人在原流程确认。撤销处理只恢复建议。</p>
      {view.history.map(candidate => card(candidate, true))}
      <p>{view.settings.enabled ? '自动复盘已开启' : '自动复盘已关闭'} · 今天自动发起 {view.budget.used_today} 次 · 每天限额 {view.settings.max_calls_per_day} 次</p>
      <p>每会话最多 {view.settings.max_calls_per_session} 次，间隔至少 {view.settings.cooldown_minutes} 分钟 · 保存时区 {view.settings.timezone}</p>
      {view.budget.next_allowed_at && <p>下次自动复盘最早在 {new Date(view.budget.next_allowed_at).toLocaleString()}</p>}
      <div className="background-coach__actions"><button className="text-button" type="button" onClick={() => window.dispatchEvent(new Event('nautilus:open-coach-settings'))}>调整教练设置</button>{run && <button className="text-button" type="button" onClick={() => setDetailId(run.id)}>最近复盘详情</button>}</div>
      <details onToggle={event => setSignalsOpen(event.currentTarget.open)}><summary>核对任务信号</summary>{signalsOpen && <Signals scope={scope} planId={planId} />}</details>
    </details>}
    {detailId && <RunDetail id={detailId} onClose={() => setDetailId(null)} onChanged={() => { void read(); }} />}
  </section>;
}

export function CoachSourceBar() {
  const [id, setId] = useState<string | null>(() => new URLSearchParams(window.location.search).get('coach_candidate'));
  const [candidate, setCandidate] = useState<CoachCandidate | null>(null), [error, setError] = useState(''), [detail, setDetail] = useState(false);
  useEffect(() => { const changed = () => setId(new URLSearchParams(window.location.search).get('coach_candidate')); window.addEventListener('nautilus:coach-location-changed', changed); return () => window.removeEventListener('nautilus:coach-location-changed', changed); }, []);
  const refresh = () => { if (id) void getCoachCandidate(id).then(value => { setCandidate(value); setError(''); }).catch(reason => setError(errorText(reason))); };
  useEffect(() => { if (!id) return; const controller = new AbortController(); void getCoachCandidate(id, controller.signal).then(setCandidate).catch(reason => { if (!controller.signal.aborted) setError(errorText(reason)); }); return () => controller.abort(); }, [id]);
  if (!id) return null;
  return <aside className="background-coach__source-bar" id="coach-source" tabIndex={-1} aria-label="教练建议来源">{error ? <p role="alert">建议来源暂时无法读取：{error} <button className="text-button" type="button" onClick={refresh}>重新读取建议来源</button></p> : candidate ? <><p><span>来自教练建议</span> · {candidate.title ?? '内容已不可查看'}</p><p>这里仍需核对并确认实际操作。</p><button className="text-button" type="button" onClick={() => setDetail(true)}>回看原复盘与依据</button>{candidate.target?.kind === 'permission_review' && <CoachPermission candidate={candidate} onChanged={refresh} />}{detail && <RunDetail id={candidate.run_id} onClose={() => setDetail(false)} onChanged={() => { window.dispatchEvent(new Event('nautilus:coach-updated')); refresh(); }} />}</> : <p role="status">正在读取建议来源…</p>}</aside>;
}

function CoachPermission({ candidate, onChanged }: { candidate: CoachCandidate; onChanged: () => void }) {
  const proposed = candidate.target?.permission_request;
  const [request, setRequest] = useState<AgentPermissionRequest | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState(''), [run, setRun] = useState<CoachRun | null>(null), [detail, setDetail] = useState(false);
  const attempt = useRef<{ kind: string; key: string } | null>(null), alive = useRef(true);
  async function load(clearError = true) {
    if (!proposed) return;
    try {
      const items = await listAgentPermissionRequests(), prefix = `coach-permission:${candidate.id}`;
      const matching = items.filter(item => (item.request_key === proposed.request_key || item.request_key === prefix || item.request_key.startsWith(`${prefix}:`)) && item.target_id === proposed.target_id && item.purpose === proposed.purpose && item.content_granularity === proposed.content_granularity && item.ttl_seconds === proposed.ttl_seconds);
      if (alive.current) { setRequest(matching.find(item => item.request_key === proposed.request_key) ?? matching.sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null); if (clearError) setError(''); }
    }
    catch (reason) { if (alive.current) setError(errorText(reason)); }
  }
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; }; }, [candidate.id, proposed?.request_key]);
  const sourceValid = candidate.content_available && candidate.status === 'accepted' && candidate.sources.every(source => source.available);
  const currentRequest = Boolean(request && request.request_key === proposed?.request_key);
  const granted = currentRequest && request?.grant_status === 'active' && new Date(request.expires_at).getTime() > Date.now();
  const pendingApproval = currentRequest && request?.status === 'pending' && !request.grant_status;
  const requestStatus = request ? request.grant_status === 'revoked' || request.status === 'revoked' ? '已撤销' : request.grant_status === 'expired' || request.status === 'expired' || new Date(request.expires_at).getTime() <= Date.now() ? '已过期' : request.grant_status === 'active' ? '已批准' : request.status === 'denied' ? '已拒绝' : '待批准' : '';
  async function change(operation: 'create' | 'approve' | 'deny' | 'revoke') {
    if (!proposed || busy || (operation === 'create' || operation === 'approve') && !sourceValid) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const next = operation === 'create' ? await createAgentPermissionRequest({ purpose: proposed.purpose, target_id: proposed.target_id, content_granularity: proposed.content_granularity, ttl_seconds: proposed.ttl_seconds, request_key: proposed.request_key }) : !request ? null : operation === 'approve' ? await approveAgentPermissionRequest(request.id) : operation === 'deny' ? await denyAgentPermissionRequest(request.id, '本人拒绝这次教练读取') : await revokeAgentPermissionGrant(request.id, '本人撤销这次教练读取');
      if (next) setRequest(next);
      await load();
      setNotice(operation === 'create' ? '已发起本次读取申请，核对后再决定是否批准。' : operation === 'approve' ? '已批准这次有限读取。点击继续复盘后才会调用模型。' : operation === 'deny' ? '已拒绝本次读取，可继续原任务或补充摘要。' : '已撤销本次读取。');
      window.dispatchEvent(new Event('nautilus:coach-permission-changed')); onChanged();
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }
  async function usePermission(retryRunId?: string) {
    if (!request || !granted || busy || !sourceValid) return;
    const kind = `permission:${request.id}:${retryRunId ?? ''}`; if (attempt.current?.kind !== kind) attempt.current = { kind, key: coachKey() };
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await checkCoach({ scope: candidate.scope, ...(candidate.scope === 'plan' && candidate.plan_id ? { plan_id: candidate.plan_id } : {}), trigger: 'manual', request_key: attempt.current.key, permission_candidate_id: candidate.id, permission_request_id: request.id, ...(retryRunId ? { retry_run_id: retryRunId } : {}) });
      attempt.current = null; setRun(result.run);
      setNotice(result.run ? ongoing(result.run) ? '正在用这次授权复盘。' : '这次授权对应的复盘已保存，可查看结果。' : reasonLabels[result.reason ?? ''] ?? '这次没有发起新复盘，请核对来源和本次授权。');
      window.dispatchEvent(new Event('nautilus:coach-updated'));
    } catch (reason) { setError(errorText(reason)); if (reason instanceof ApiError && reason.status !== null) attempt.current = null; await load(false); onChanged(); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    if (!ongoing(run)) return;
    let active = true, timer: number | undefined;
    const poll = async () => { try { const next = await getCoachRun(run!.id); if (!active) return; setRun(next.run); if (ongoing(next.run)) timer = window.setTimeout(() => void poll(), 1000); else { setNotice(next.run.status === 'succeeded' ? '本次授权复盘已完成。' : runReason(next.run.reason)); window.dispatchEvent(new Event('nautilus:coach-updated')); } } catch (reason) { if (active) setError(errorText(reason)); } };
    timer = window.setTimeout(() => void poll(), 700);
    return () => { active = false; window.clearTimeout(timer); };
  }, [run?.id, run?.status]);
  const taskHref = candidate.target?.plan_id && candidate.target.action_id ? coachHref(`?view=plans&plan=${encodeURIComponent(candidate.target.plan_id)}&plan_view=tasks&action=${encodeURIComponent(candidate.target.action_id)}`) : null;
  return <section className="background-coach__permission" aria-label="本次教练读取申请">
    {!proposed ? <p>这条建议尚无可申请的具体读取范围，请先回看原复盘与依据。</p> : <>
      <p><strong>本次判断目的</strong> · {proposed.purpose}</p><p>范围：建议对应的这一项任务的可见学习产出；最多 3 份，每份最多 4000 字符。读取粒度：原文；有效期：5 分钟。</p>
      <p>只供这次本人发起的复盘使用。超出本次容量的内容不纳入，复盘详情会说明；自动复盘继续只读摘要。</p><p>换一种方式：{proposed.alternative}</p>
      {!sourceValid && <p role="alert">这条建议或来源已变化，当前不能继续申请或复盘。</p>}
      {request && <p>{currentRequest ? '本次申请' : '上一申请'}：{requestStatus} · 截止 {new Date(request.expires_at).toLocaleString()}</p>}
      <div className="background-coach__actions">
        {!currentRequest && <button className="button button--quiet button--compact" type="button" disabled={busy || !sourceValid} onClick={() => void change('create')}>{request ? '重新发起本次读取申请' : '发起本次读取申请'}</button>}
        {pendingApproval && <><button className="button button--quiet button--compact" type="button" disabled={busy || !sourceValid} onClick={() => void change('approve')}>批准本次读取</button><button className="text-button" type="button" disabled={busy} onClick={() => void change('deny')}>拒绝本次读取</button></>}
        {granted && <><button className="button button--quiet button--compact" type="button" disabled={busy || !sourceValid || ongoing(run)} onClick={() => void usePermission()}>用本次授权继续复盘</button><button className="text-button" type="button" disabled={busy} onClick={() => void change('revoke')}>撤销本次授权</button></>}
        {granted && run && ['failed', 'canceled'].includes(run.status) && <button className="text-button" type="button" disabled={busy} onClick={() => void usePermission(run.id)}>重试本次授权复盘</button>}
        {run && <button className="text-button" type="button" onClick={() => setDetail(true)}>查看本次授权复盘</button>}
        {taskHref && <a href={taskHref} onClick={followCoachLink}>回到原任务核对或补充摘要</a>}
        <button className="text-button" type="button" disabled={busy} onClick={() => { void load(); onChanged(); }}>刷新本次权限</button>
      </div>
    </>}{error && <p className="form-error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {detail && run && <RunDetail id={run.id} onClose={() => setDetail(false)} onChanged={() => { window.dispatchEvent(new Event('nautilus:coach-updated')); onChanged(); }} />}
  </section>;
}

/** An already-paid answer exposes only a deterministic entrance, without starting another run. */
export function CoachImmediateSignal({ signal }: { signal: CoachAssignmentSignal | null | undefined }) {
  const [latest, setLatest] = useState<CoachSignal | null>(null);
  useEffect(() => {
    setLatest(null);
    if (!signal?.immediate) return;
    const controller = new AbortController();
    const read = () => { void getCoachSignals('global', null, controller.signal).then(value => { if (!controller.signal.aborted) setLatest(value.items.find(item => item.id === signal.id) ?? null); }).catch(() => undefined); };
    read(); window.addEventListener('nautilus:coach-updated', read);
    return () => { controller.abort(); window.removeEventListener('nautilus:coach-updated', read); };
  }, [signal?.id]);
  if (!signal?.immediate || latest && (latest.status !== 'active' || !latest.source_available)) return null;
  const href = coachHref(signal.target?.href);
  return <aside className="background-coach__immediate" aria-label="当前学习需要核对的事项"><p>{signalLabels[signal.kind]}</p>{href ? <a href={href} onClick={followCoachLink}>{signal.target!.label}</a> : <p>请先核对当前任务范围，继续对话也可说明你的选择。</p>}</aside>;
}
