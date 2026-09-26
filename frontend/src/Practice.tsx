import { useEffect, useRef, useState } from 'react';
import LearningMarkdown from './LearningMarkdown';
import PurgeStatus from './PurgeStatus';
import {
  choosePractice, createPractice, getPractice, listPractices, purgePractice,
  recordPracticeDisplay, runPractice, savePracticeAttempt,
  type Practice, type PracticeKind,
} from './api';

const requestKey = () => crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
const when = (value: string | null) => value ? new Date(value).toLocaleString() : '未记录';
const kindName = (kind: PracticeKind) => kind === 'redo' ? '原题重做' : '新情境';
const statusName: Record<Practice['status'], string> = { running: '处理中', ready: '可开始', reviewed: '已复核', started: '练习中', skipped: '暂不练', failed: '未完成', purged: '内容已删除' };
const sourceName = { question: '原题', answer: '当时作答', feedback: '当时反馈' };

function Basis({ items }: { items: Array<{ source: 'question' | 'answer' | 'feedback'; quote: string }> }) {
  return items.length > 0 && <details><summary>依据（{items.length}）</summary><ul>{items.map((item, index) => <li key={index}>{sourceName[item.source]}：<span>{item.quote}</span></li>)}</ul></details>;
}

export function PracticePanel({ verificationId, submissionId, evaluationId, questionId }: {
  verificationId: string; submissionId: string; evaluationId: string; questionId: string;
}) {
  const [items, setItems] = useState<Practice[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [kind, setKind] = useState<PracticeKind>('new_situation');
  const [objection, setObjection] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const pendingCreate = useRef<{ key: string; operation: 'exercise' | 'recheck'; kind: PracticeKind; objection?: string; recheckId?: string; previousId?: string } | null>(null);
  const scope = `${verificationId}:${submissionId}:${evaluationId}:${questionId}`;
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  useEffect(() => {
    let active = true;
    setItems([]); setSelectedId(null); setError(''); pendingCreate.current = null;
    listPractices(verificationId, submissionId, evaluationId, questionId)
      .then(value => { if (active) { setItems(value); setSelectedId(value[0]?.id ?? null); } })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : '补练记录暂时无法读取'); });
    return () => { active = false; };
  }, [scope]);
  useEffect(() => {
    if (!items.some(item => item.status === 'running')) return;
    let active = true;
    const timer = window.setTimeout(() => {
      void listPractices(verificationId, submissionId, evaluationId, questionId).then(value => { if (active && scopeRef.current === scope) setItems(value); }).catch(() => undefined);
    }, 2500);
    return () => { active = false; window.clearTimeout(timer); };
  }, [items, scope]);
  async function refresh() {
    const target = scope;
    setError('');
    try {
      const value = await listPractices(verificationId, submissionId, evaluationId, questionId);
      if (scopeRef.current !== target) return;
      setItems(value);
      setSelectedId(current => current && value.some(item => item.id === current) ? current : value[0]?.id ?? null);
      if (value.some(item => item.request?.request_key === pendingCreate.current?.key)) pendingCreate.current = null;
    } catch (reason) { if (scopeRef.current === target) setError(reason instanceof Error ? reason.message : '补练记录暂时无法读取'); }
  }
  async function create(operation: 'exercise' | 'recheck', recheckId?: string, previousId?: string, kindOverride?: PracticeKind) {
    if (busyRef.current) return;
    if (operation === 'recheck' && !objection.trim()) return;
    if (operation === 'exercise' && objection.trim()) { setError('你已写下对反馈的质疑。请先复核反馈，或清空质疑后再出练习。'); return; }
    const previous = pendingCreate.current;
    if (previous && (previous.operation !== operation || previous.recheckId !== recheckId || previous.previousId !== previousId)) {
      setError('上次请求结果尚未确认。请重试原请求，或刷新记录核对。'); return;
    }
    const request = previous ?? { key: requestKey(), operation, kind: kindOverride ?? kind, objection: operation === 'recheck' ? objection.trim() : undefined, recheckId, previousId };
    pendingCreate.current = request;
    busyRef.current = true; setBusy(true); setError('');
    const target = scope;
    try {
      const value = await createPractice(verificationId, {
        submission_id: submissionId, evaluation_id: evaluationId, question_id: questionId,
        request_key: request.key, operation: request.operation, requested_kind: request.kind,
        ...(request.objection ? { objection: request.objection } : {}), ...(request.recheckId ? { recheck_id: request.recheckId } : {}), ...(request.previousId ? { previous_id: request.previousId } : {}),
      });
      if (scopeRef.current !== target) return;
      setItems(current => [value, ...current.filter(item => item.id !== value.id)]);
      setSelectedId(value.id); pendingCreate.current = null;
      if (operation === 'recheck') setObjection('');
    } catch (reason) { if (scopeRef.current === target) setError(reason instanceof Error ? reason.message : '请求未确认，请重试或刷新记录'); }
    finally { busyRef.current = false; setBusy(false); }
  }
  const selected = items.find(item => item.id === selectedId);
  return <div className="practice-panel" aria-label="针对性补练">
    <p className="form-hint">补练是另一次练习与 AI 反馈，不改写本次验证结果，也不自动作为正式能力通过记录。</p>
    {error && <p role="alert">{error}</p>}
    <div className="practice-panel__controls">
      <label>练习方式 <select value={kind} onChange={event => setKind(event.target.value as PracticeKind)} disabled={busy || Boolean(pendingCreate.current)}><option value="new_situation">换个情境</option><option value="redo">原题重做</option></select></label>
      <button className="button button--quiet" type="button" disabled={busy || Boolean(pendingCreate.current) || Boolean(objection.trim())} onClick={() => void create('exercise')}>建议一个练习</button>
      <button className="button button--quiet" type="button" onClick={() => void refresh()}>刷新补练记录</button>
    </div>
    <label className="field"><span>对原反馈有疑问？先说出要复核的具体判断</span><textarea value={objection} onChange={event => setObjection(event.target.value)} maxLength={4000} disabled={busy || Boolean(pendingCreate.current)} /></label>
    {objection.trim() && <p className="form-hint">已写下质疑。先复核反馈，或清空质疑后再建议练习。</p>}
    <button className="button button--quiet" type="button" disabled={busy || !objection.trim() || Boolean(pendingCreate.current)} onClick={() => void create('recheck')}>先复核反馈</button>
    {pendingCreate.current && <button className="button button--quiet" type="button" disabled={busy} onClick={() => void create(pendingCreate.current!.operation, pendingCreate.current!.recheckId, pendingCreate.current!.previousId)}>重试上次请求</button>}
    {items.length > 0 && <div className="practice-panel__versions"><strong>已保存的候选与练习</strong>{items.map((item, index) => <button key={item.id} className="text-button" type="button" aria-pressed={selectedId === item.id} onClick={() => setSelectedId(item.id)}>第 {items.length - index} 个 · {item.operation === 'recheck' ? '反馈复核' : kindName(item.requested_kind)} · {statusName[item.status]} · {when(item.created_at)}</button>)}</div>}
    {selected && <PracticeDetail key={selected.id} id={selected.id} initial={selected} onChange={value => setItems(current => current.map(item => item.id === value.id ? value : item))} onAnother={() => { if (selected.requested_kind === 'redo') setKind('new_situation'); void create('exercise', undefined, selected.id, selected.requested_kind === 'redo' ? 'new_situation' : undefined); }} onPracticeFromReview={reviewId => void create('exercise', reviewId)} />}
  </div>;
}

export function PracticeDetail({ id, initial, readOnly = false, onChange, onAnother, onPracticeFromReview }: {
  id: string; initial?: Practice; readOnly?: boolean; onChange?: (value: Practice) => void;
  onAnother?: () => void; onPracticeFromReview?: (reviewId: string) => void;
}) {
  const [practice, setPractice] = useState<Practice | null>(initial ?? null);
  const [answer, setAnswer] = useState('');
  const [independent, setIndependent] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const pending = useRef<{ label: string; key: string; action: () => Promise<Practice> } | null>(null);
  const [retryLabel, setRetryLabel] = useState('');
  const idRef = useRef(id);
  idRef.current = id;
  useEffect(() => {
    let active = true;
    setPractice(initial ?? null); setError(''); pending.current = null; setRetryLabel('');
    getPractice(id).then(value => { if (active) setPractice(value); })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : '补练记录暂时无法读取'); });
    return () => { active = false; };
  }, [id]);
  useEffect(() => {
    if (practice?.status !== 'running' && !practice?.runs.some(run => run.status === 'running')) return;
    let active = true;
    const timer = window.setTimeout(() => {
      void getPractice(id).then(value => { if (active && idRef.current === id) { setPractice(value); onChange?.(value); } }).catch(() => undefined);
    }, 2500);
    return () => { active = false; window.clearTimeout(timer); };
  }, [id, practice]);
  function apply(value: Practice) { setPractice(value); onChange?.(value); }
  async function refresh() {
    setError('');
    try { const value = await getPractice(id); if (idRef.current === id) apply(value); }
    catch (reason) { if (idRef.current === id) setError(reason instanceof Error ? reason.message : '补练记录暂时无法读取'); }
  }
  async function act(label: string, make: (key: string) => () => Promise<Practice>) {
    if (busyRef.current) return;
    if (pending.current && pending.current.label !== label) { setError('上次请求结果尚未确认。请重试或刷新后核对。'); return; }
    const key = pending.current?.key ?? requestKey();
    const operation = pending.current ?? { label, key, action: make(key) };
    pending.current = operation;
    busyRef.current = true; setBusy(true); setError(''); setRetryLabel('');
    try { const value = await operation.action(); if (idRef.current === id) { apply(value); pending.current = null; if (label === '保存作答') { setAnswer(''); setIndependent(false); } } }
    catch (reason) { if (idRef.current === id) { setRetryLabel(label); setError(reason instanceof Error ? reason.message : `${label}未确认`); } }
    finally { busyRef.current = false; setBusy(false); }
  }
  if (!practice) return <div role="status">{error || '正在读取补练…'}</div>;
  const exercise = practice.content?.exercise;
  const review = practice.content?.review;
  const attemptNumbers = new Map(practice.attempts.map((attempt, index) => [attempt.id, practice.attempts.length - index]));
  return <article className="practice-detail" aria-label="补练详情">
    <div className="review-question-heading"><h4>{practice.operation === 'recheck' ? 'AI 反馈复核' : `${kindName(practice.requested_kind)} · 补练`}</h4><button className="text-button" type="button" onClick={() => void refresh()}>刷新状态</button></div>
    <p className="form-hint">创建于 {when(practice.created_at)} · 状态：{statusName[practice.status]}{practice.reason ? ` · ${practice.reason}` : ''}</p>
    {practice.available === false && !practice.purged_at && <p role="status">原题、作答或关联复核内容当前不可用，不能继续生成或提交补练；可查看已保存的状态。</p>}
    {error && <p role="alert">{error}</p>}
    {retryLabel && <button className="button button--quiet" type="button" disabled={busy || (practice.available === false && retryLabel !== '删除补练')} onClick={() => void act(retryLabel, () => pending.current!.action)}>重试上次操作</button>}
    {practice.status === 'running' && <p role="status">AI 正在处理；已保存请求，可稍后刷新恢复。</p>}
    {practice.operation === 'recheck' && practice.request?.objection && <p>你的质疑：{practice.request.objection}</p>}
    {review && <section aria-label="原反馈复核"><strong>复核：{review.status === 'supported' ? '原反馈有依据' : review.status === 'corrected' ? '原反馈需要修正' : '依据不足'}</strong><p>{review.summary}</p><Basis items={review.basis} /><p className="form-hint">这次复核另存记录，不改写原评估。</p></section>}
    {practice.operation === 'recheck' && review && review.status !== 'insufficient' && !readOnly && <button className="button button--quiet" type="button" disabled={busy || practice.available === false} onClick={() => onPracticeFromReview?.(practice.id)}>按复核结果出练习</button>}
    {exercise && <section aria-label="补练题目"><strong>{exercise.focus === 'required_gap' ? '原要求缺口' : '可选拓展'} · {kindName(exercise.kind)}</strong><p>{exercise.reason}</p><Basis items={exercise.basis} /><div className="ai-markdown"><LearningMarkdown>{exercise.prompt}</LearningMarkdown></div></section>}
    {exercise && (practice.status === 'ready' || practice.status === 'skipped') && !readOnly && <div className="practice-panel__controls"><button className="button button--accent" type="button" disabled={busy || Boolean(pending.current) || practice.available === false} onClick={() => void act('开始练习', () => () => choosePractice(id, 'start'))}>{practice.status === 'skipped' ? '现在开始' : '开始'}</button><button className="button button--quiet" type="button" disabled={busy || Boolean(pending.current) || practice.available === false} onClick={onAnother}>换一个</button>{practice.status === 'ready' && <button className="button button--quiet" type="button" disabled={busy || Boolean(pending.current) || practice.available === false} onClick={() => void act('暂不练', () => () => choosePractice(id, 'skip'))}>暂不练</button>}</div>}
    {practice.status === 'started' && !readOnly && practice.available !== false && <section aria-label="补练作答">
      <label className="field"><span>我的作答</span><textarea value={answer} onChange={event => setAnswer(event.target.value)} maxLength={12000} disabled={busy || Boolean(pending.current)} /></label>
      <label className="verification-stop-check"><input type="checkbox" checked={independent} onChange={event => setIndependent(event.target.checked)} disabled={busy || Boolean(pending.current)} />这次作答由我独立完成，未查看资料、解法或提示（仅本人自报）</label>
      <div className="practice-panel__controls"><button className="button button--quiet" type="button" disabled={busy || Boolean(pending.current) || practice.runs.some(run => run.status === 'running')} onClick={() => void act('获取提示', key => () => runPractice(id, { kind: 'hint', request_key: key }))}>给个提示</button><button className="button button--accent" type="button" disabled={busy || Boolean(pending.current) || !answer.trim()} onClick={() => {
        const text = answer.trim(); const condition = independent ? 'independent' : 'with_materials';
        void act('保存作答', key => () => savePracticeAttempt(id, { answer: text, evidence_condition: condition, request_key: key }));
      }}>保存作答</button></div>
    </section>}
    {practice.attempts.length > 0 && <section aria-label="补练作答版本"><h5>作答版本</h5>{practice.attempts.map((attempt, index) => <article key={attempt.id}><strong>第 {practice.attempts.length - index} 次作答 · {when(attempt.created_at)}</strong><p>本人自报：{attempt.condition?.user_report === 'independent' ? '独立完成' : attempt.condition?.user_report === 'with_materials' ? '借助资料或帮助' : '未记录'}；保存时条件：{attempt.condition?.evidence_condition === 'independent' ? '按自报独立记录，未独立核实' : attempt.condition?.evidence_condition === 'with_materials' ? '有资料或帮助记录' : '未记录'} · {attempt.condition?.attempt_kind === 'same_question_retry' ? '同题再试' : kindName(attempt.condition?.attempt_kind === 'redo' ? 'redo' : 'new_situation')}</p><div className="ai-markdown"><LearningMarkdown>{attempt.answer ?? '内容已删除'}</LearningMarkdown></div><p className="form-hint">保存时帮助记录 {attempt.condition?.records.length ?? 0} 条；无记录不证明独立完成，后来查看提示不改写此版本。</p>{attempt.condition?.records.map(record => <p key={record.run_id} className="form-hint">{({ hint: '提示', evaluation: '补练评估', source_feedback: '原题反馈', reference_answer: '原题参考解法', discussion_reply: '原题讨论回复' } as Record<string, string>)[record.kind] ?? '帮助'}：已生成 {when(record.provided_at)}；页面呈现 {when(record.displayed_at)}</p>)}{!readOnly && practice.available !== false && !attempt.purged_at && !practice.runs.some(run => run.status === 'running') && !practice.runs.some(run => run.kind === 'evaluation' && run.attempt_id === attempt.id && run.status === 'succeeded') && <button className="button button--quiet" type="button" disabled={busy || Boolean(pending.current)} onClick={() => void act('评估作答', key => () => runPractice(id, { kind: 'evaluation', attempt_id: attempt.id, request_key: key }))}>评估这次作答{practice.runs.some(run => run.kind === 'evaluation' && run.attempt_id === attempt.id && run.status === 'failed') ? '（重试）' : ''}</button>}</article>)}</section>}
    {practice.runs.length > 0 && <section aria-label="补练 AI 结果"><h5>提示与评估记录</h5>{practice.runs.map(run => <PracticeRun key={run.id} practiceId={id} run={run} attemptNumber={run.attempt_id ? attemptNumbers.get(run.attempt_id) ?? null : null} onChange={apply} />)}</section>}
    {practice.purged_at ? <PurgeStatus kind="practice" objectId={id} onRetry={async () => { apply(await purgePractice(id)); }} busy={busy} /> : !readOnly && <details><summary>删除补练内容</summary><p>将清除这项补练及由它的复核或换题结果衍生的后续补练的题目、作答、提示、评估与受管理副本，无法恢复；原验证记录保留。</p><button className="button button--danger" type="button" disabled={busy || Boolean(pending.current)} onClick={() => { if (window.confirm('彻底删除这项补练及其衍生补练内容？原验证仍保留。')) void act('删除补练', () => () => purgePractice(id)); }}>彻底删除这项补练</button></details>}
  </article>;
}

function PracticeRun({ practiceId, run, attemptNumber, onChange }: { practiceId: string; run: Practice['runs'][number]; attemptNumber: number | null; onChange: (value: Practice) => void }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  async function display() {
    if (inFlight.current || run.displayed_at || run.status !== 'succeeded' || !run.result || !(run.result.text || run.result.feedback || run.result.assessment || run.result.answer_quote || run.result.next_step || run.result.remaining?.length)) return;
    inFlight.current = true; setBusy(true); setError('');
    try { onChange(await recordPracticeDisplay(practiceId, run.id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '展示记录未保存'); }
    finally { inFlight.current = false; setBusy(false); }
  }
  return <details onToggle={event => { if (event.currentTarget.open) void display(); }}><summary>{run.kind === 'hint' ? '提示' : `第 ${attemptNumber ?? '?'} 次作答的 AI 评估`} · {run.status === 'succeeded' ? '已完成' : run.status === 'failed' ? '失败' : '处理中'} · {when(run.created_at)}</summary>
    {run.reason && <p>{run.reason}</p>}
    {run.result && <div className="ai-markdown"><LearningMarkdown>{run.result.text ?? run.result.feedback ?? ''}</LearningMarkdown>{run.result.assessment && <p>AI 判断：{run.result.assessment === 'meets' ? '达到本次练习要求' : run.result.assessment === 'needs_work' ? '仍需补强' : '暂不能判断'}</p>}{run.result.answer_quote && <p>所引作答：{run.result.answer_quote}</p>}{Boolean(run.result.remaining?.length) && <ul>{run.result.remaining?.map((value, index) => <li key={index}>{value}</li>)}</ul>}{run.result.next_step && <p>下一步：{run.result.next_step}</p>}</div>}
    <p className="form-hint">正文生成：{when(run.finished_at)}；页面呈现记录：{when(run.displayed_at)}。呈现不代表已阅读或理解。</p>
    {error && <p role="alert">{error}</p>}{error && <button className="text-button" type="button" disabled={busy} onClick={() => void display()}>重试保存展示记录</button>}
  </details>;
}
