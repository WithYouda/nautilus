import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { ApiError, getLearningState, getOutcomeGraph, type LearningOutcome, type LearningStandard, type PurgeReport } from './api';
import { AttachmentDialog } from './AttachmentReview';
import {
  createLearningPlan, createPlanModule, createPlanTask, getPlanOrganization, getPlanOrganizationPurgeStatus,
  organizationRequestKey, placePlanTask, purgePlanOrganizationContent, reorderPlanChildren, revisePlanModule,
  type OrganizationWriteResult, type PlanOrganization, type PlanTaskInput,
} from './learning-organization-api';
import './styles/learning-plan-organization.css';

const message = (reason: unknown) => reason instanceof Error ? reason.message : '操作未完成，请重试。';
const conflict = (reason: unknown) => reason instanceof ApiError && reason.status === 409;
type Attempt = { signature: string; key: string } | null;
function attemptKey(attempt: { current: Attempt }, payload: unknown) {
  const signature = JSON.stringify(payload);
  if (attempt.current?.signature !== signature) attempt.current = { signature, key: organizationRequestKey() };
  return attempt.current.key;
}
function siblings(data: PlanOrganization, parent: string | null) {
  return data.children.filter(child => child.parent_module_id === parent).sort((a, b) => a.position - b.position || a.id.localeCompare(b.id));
}
function moduleLabel(data: PlanOrganization, id: string, seen = new Set<string>()): string {
  const item = data.modules.find(module => module.id === id);
  if (!item || seen.has(id)) return '模块';
  seen.add(id);
  return item.parent_module_id ? `${moduleLabel(data, item.parent_module_id, seen)} / ${item.title}` : item.title;
}
function descendantIds(data: PlanOrganization, id: string) {
  const result = new Set([id]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const module of data.modules) if (module.parent_module_id && result.has(module.parent_module_id) && !result.has(module.id)) { result.add(module.id); changed = true; }
  }
  return result;
}
function ModuleOptions({ data, exclude }: { data: PlanOrganization; exclude?: string }) {
  const excluded = exclude ? descendantIds(data, exclude) : new Set<string>();
  return <><option value="">直接放在计划中</option>{data.modules.filter(item => !excluded.has(item.id) && item.status !== 'archived').map(item => <option key={item.id} value={item.id}>{moduleLabel(data, item.id)}</option>)}</>;
}
function ConflictNotice({ state, busy, onRead, onReviewed }: { state: 'stale' | 'review' | null; busy: boolean; onRead: () => void; onReviewed: () => void }) {
  if (!state) return null;
  return <div className="learning-organization-conflict" role="alert"><p>{state === 'stale' ? '计划或任务已变化。你的输入已保留，请读取最新状态后重新核对。' : '已读取最新状态，输入仍保留。请核对当前归属和顺序，再保存。'}</p><button className="button button--quiet" type="button" disabled={busy} onClick={state === 'stale' ? onRead : onReviewed}>{state === 'stale' ? '读取最新状态' : '已核对，继续编辑'}</button></div>;
}

export default function LearningPlanOrganization({ planId, renderTask, onRefresh, closed }: {
  planId: string; renderTask: (actionId: string) => ReactNode; onRefresh: () => Promise<void> | void; closed: boolean;
}) {
  const [data, setData] = useState<PlanOrganization | null>(null), [error, setError] = useState(''), [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true), [purging, setPurging] = useState(false);
  const serial = useRef(0), identity = useRef(planId); identity.current = planId;
  async function read() {
    const request = ++serial.current;
    const value = await getPlanOrganization(planId);
    if (request === serial.current && identity.current === planId) { setData(value); setError(''); setLoading(false); }
    return value;
  }
  useEffect(() => {
    setData(null); setLoading(true); setError(''); setEditing(false);
    void read().catch(reason => { if (identity.current === planId) { setError(message(reason)); setLoading(false); } });
    return () => { serial.current++; };
  }, [planId]);
  async function written(result: OrganizationWriteResult) {
    if (identity.current !== planId) return;
    setData(result.organization);
    await read();
    await onRefresh();
  }
  function render(parent: string | null, ancestors = new Set<string>()): ReactNode {
    return siblings(data!, parent).map(child => {
      if (child.kind === 'task') return <div key={`task:${child.id}`} data-task-id={child.id}>{renderTask(child.id)}</div>;
      const module = data!.modules.find(item => item.id === child.id);
      if (!module || ancestors.has(module.id)) return null;
      const next = new Set(ancestors); next.add(module.id);
      return <section className="learning-organization-module" key={`module:${module.id}`} data-module-id={module.id} aria-label={module.title}>
        <header><h4>{module.title}</h4>{module.description && <p>{module.description}</p>}{closed && <OrganizationPurge planId={planId} moduleId={module.id} revision={data!.revision} disabled={false} canClear={module.can_purge_content === true} purged={module.content_available === false} onSaved={written} onDialogChange={setPurging} onConflict={() => setError('计划已变化，请重新读取任务后核对。')} />}</header>
        <div className="learning-organization-module__tasks">{render(module.id, next)}{!siblings(data!, module.id).length && <p className="form-hint">还没有任务。</p>}</div>
      </section>;
    });
  }
  return <div className="learning-plan-organization">
    <div className="learning-organization-toolbar"><button className="button button--quiet" type="button" disabled={!data || closed} onClick={() => setEditing(true)}>组织任务</button>
      {data && <OrganizationPurge planId={planId} moduleId={null} revision={data.revision} disabled={false} canClear={data.plan.can_purge_content === true} purged={data.plan.content_available === false} onSaved={written} onDialogChange={setPurging} onConflict={() => setError('计划已变化，请重新读取任务后核对。')} />}
    </div>
    {loading && <p role="status">正在读取任务…</p>}
    {error && <div role="alert"><p>{error}</p><button className="text-button" type="button" onClick={() => { setLoading(true); void read().catch(reason => { setError(message(reason)); setLoading(false); }); }}>重新读取任务</button></div>}
    {data && <div className="learning-organization-tree">{render(null)}{!data.tasks.length && !data.modules.length && <p>还没有任务。</p>}</div>}
    {editing && data && <OrganizationEditor data={data} closed={closed} onClose={() => setEditing(false)} onRead={read} onSaved={written} suspended={purging} />}
  </div>;
}

function OrganizationEditor({ data, closed, onClose, onRead, onSaved, suspended }: {
  data: PlanOrganization; closed: boolean; onClose: () => void; onRead: () => Promise<PlanOrganization>;
  onSaved: (result: OrganizationWriteResult) => Promise<void>; suspended: boolean;
}) {
  const [selection, setSelection] = useState<{ kind: 'module' | 'task' | 'new'; id: string } | null>(null);
  const [title, setTitle] = useState(''), [description, setDescription] = useState(''), [parent, setParent] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [stale, setStale] = useState<'stale' | 'review' | null>(null), [nested, setNested] = useState(false);
  const attempt = useRef<Attempt>(null);
  const selectedChild = data.children.find(child => child.id === selection?.id && child.kind === selection?.kind);
  const selectedModule = data.modules.find(module => module.id === selection?.id && selection.kind === 'module');
  const selectedTask = data.tasks.find(task => task.id === selection?.id && selection.kind === 'task');
  const modulePurged = selectedModule?.content_available === false;
  useEffect(() => { if (modulePurged && selectedModule) { setTitle(selectedModule.title); setDescription(''); } }, [modulePurged, selectedModule?.id]);
  const disabled = busy || closed || !!stale;
  function choose(kind: 'module' | 'task' | 'new', id = '') {
    setSelection({ kind, id }); setError(''); setNotice(''); attempt.current = null;
    const module = kind === 'module' ? data.modules.find(item => item.id === id) : null;
    setTitle(module?.title ?? ''); setDescription(module?.description ?? '');
    setParent(kind === 'task' ? data.children.find(item => item.kind === 'task' && item.id === id)?.parent_module_id ?? '' : module?.parent_module_id ?? '');
  }
  async function write(signature: unknown, operation: (key: string) => Promise<OrganizationWriteResult>) {
    if (disabled) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await operation(attemptKey(attempt, signature));
      attempt.current = null;
      if (selection?.kind === 'new') setSelection({ kind: 'module', id: result.object_id });
      try { await onSaved(result); setNotice('已保存组织。'); }
      catch (reason) { setError(`组织已保存，读取最新状态失败：${message(reason)}`); }
    } catch (reason) {
      if (conflict(reason)) { setStale('stale'); setError(''); }
      else setError(message(reason));
    } finally { setBusy(false); }
  }
  async function readLatest() {
    setBusy(true); setError('');
    try { await onRead(); setStale('review'); attempt.current = null; }
    catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }
  function save(event: FormEvent) {
    event.preventDefault();
    if (!selection) return;
    const version = { expected_revision: data.revision };
    if (selection.kind === 'task') {
      if (!selectedTask) return;
      const payload = { ...version, module_id: parent || null };
      void write({ operation: 'placement', id: selection.id, ...payload }, key => placePlanTask(data.plan.id, selection.id, { ...payload, request_key: key }));
    } else {
      if (!title.trim() || selection.kind === 'module' && !selectedModule) return;
      const payload = { ...version, title: modulePurged ? selectedModule!.title : title.trim(), description: modulePurged ? '' : description.trim(), parent_module_id: parent || null };
      void write({ operation: selection.kind, id: selection.id, ...payload }, key => selection.kind === 'new' ? createPlanModule(data.plan.id, { ...payload, request_key: key }) : revisePlanModule(data.plan.id, selection.id, { ...payload, request_key: key }));
    }
  }
  function move(direction: -1 | 1) {
    if (!selectedChild || disabled) return;
    const children = siblings(data, selectedChild.parent_module_id);
    const index = children.findIndex(item => item.id === selectedChild.id && item.kind === selectedChild.kind);
    if (index + direction < 0 || index + direction >= children.length) return;
    [children[index], children[index + direction]] = [children[index + direction], children[index]];
    const payload = { parent_module_id: selectedChild.parent_module_id, children: children.map(item => ({ kind: item.kind, id: item.id })), expected_revision: data.revision };
    void write({ operation: 'order', ...payload }, key => reorderPlanChildren(data.plan.id, { ...payload, request_key: key }));
  }
  function list(parentId: string | null, depth = 0, ancestors = new Set<string>()): ReactNode {
    return siblings(data, parentId).map(child => {
      const item = child.kind === 'module' ? data.modules.find(module => module.id === child.id) : data.tasks.find(task => task.id === child.id);
      if (!item || ancestors.has(child.id)) return null;
      const next = new Set(ancestors); next.add(child.id);
      return <div key={`${child.kind}:${child.id}`}><button className="learning-organization-item" type="button" aria-label={`${child.kind === 'module' ? '编辑模块' : '移动任务'}：${item.title}`} aria-pressed={selection?.kind === child.kind && selection.id === child.id} disabled={busy} onClick={() => choose(child.kind, child.id)} style={{ paddingInlineStart: `${12 + Math.min(depth, 4) * 14}px` }}><small>{child.kind === 'module' ? '模块' : '任务'}</small><span>{item.title}</span></button>{child.kind === 'module' && list(child.id, depth + 1, next)}</div>;
    });
  }
  const sameParent = selectedChild ? siblings(data, selectedChild.parent_module_id) : [];
  const selectedIndex = sameParent.findIndex(item => item.kind === selectedChild?.kind && item.id === selectedChild?.id);
  return <AttachmentDialog title="组织任务" closeLabel="关闭组织任务" className="learning-organization-dialog" onClose={() => { if (!busy) onClose(); }} suspended={suspended || nested}>
    <div className="learning-organization-dialog__body">
      <ConflictNotice state={stale} busy={busy} onRead={() => void readLatest()} onReviewed={() => { setStale(null); setError(''); }} />
      {error && <p role="alert" className="workspace-alert">{error}</p>}{notice && <p role="status">{notice}</p>}
      <div className="learning-organization-editor"><div className="learning-organization-picker"><button className="button button--quiet" type="button" disabled={disabled} onClick={() => choose('new')}>新建模块</button><div className="learning-organization-items">{list(null)}{!data.children.length && <p className="form-hint">任务可以直接放在计划中。</p>}</div></div>
        <div className="learning-organization-fields">{selection ? <form onSubmit={save}>
          {selection.kind === 'task' ? <><h3>{selectedTask?.title ?? '任务已不可用'}</h3><label className="field"><span>放入</span><select aria-label="放入" value={parent} disabled={disabled || !selectedTask} onChange={event => setParent(event.target.value)}><ModuleOptions data={data} /></select></label></> : <>
            <h3>{selection.kind === 'new' ? '新建模块' : '编辑模块'}</h3>
            {modulePurged && <p className="form-hint">名称和说明已清除，结构仍可调整。</p>}
            <label className="field"><span>模块名称</span><input required maxLength={200} value={modulePurged ? selectedModule!.title : title} disabled={disabled || modulePurged} onChange={event => setTitle(event.target.value)} /></label>
            <label className="field"><span>说明（可选）</span><textarea maxLength={1000} value={modulePurged ? '' : description} disabled={disabled || modulePurged} onChange={event => setDescription(event.target.value)} /></label>
            <label className="field"><span>父模块</span><select aria-label="父模块" value={parent} disabled={disabled} onChange={event => setParent(event.target.value)}><ModuleOptions data={data} exclude={selection.kind === 'module' ? selection.id : undefined} /></select></label>
          </>}
          {selection.kind !== 'new' && !selectedChild && <p role="alert">当前项目已不可编辑。输入已保留，可选择其他项目。</p>}
          <div className="learning-organization-actions"><button className="button button--accent" type="submit" disabled={disabled || selection.kind !== 'new' && !selectedChild}>{busy ? '正在保存…' : selection.kind === 'new' ? '创建模块' : '保存组织'}</button></div>
          {selectedChild && <div className="learning-organization-order"><span>当前同级顺序</span><div><button className="button button--quiet" type="button" disabled={disabled || selectedIndex <= 0} onClick={() => move(-1)}>向上移</button><button className="button button--quiet" type="button" disabled={disabled || selectedIndex >= sameParent.length - 1} onClick={() => move(1)}>向下移</button></div></div>}
          {selectedModule && <OrganizationPurge planId={data.plan.id} moduleId={selectedModule.id} revision={data.revision} disabled={disabled} canClear={selectedModule.can_purge_content === true} purged={modulePurged} onSaved={onSaved} onDialogChange={setNested} onConflict={() => setStale('stale')} />}
        </form> : <p className="form-hint">选择任务或模块，调整归属与顺序。</p>}</div>
      </div>
    </div>
    <div className="learning-organization-dialog__footer"><button className="button button--quiet" type="button" disabled={busy} onClick={onClose}>完成</button></div>
  </AttachmentDialog>;
}

function OrganizationPurge({ planId, moduleId, revision, disabled, canClear, purged, onSaved, onDialogChange, onConflict }: {
  planId: string; moduleId: string | null; revision: number; disabled: boolean; canClear: boolean; purged: boolean;
  onSaved: (result: OrganizationWriteResult) => Promise<void>; onDialogChange?: (open: boolean) => void; onConflict?: () => void;
}) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [report, setReport] = useState<PurgeReport | null>(null);
  const [stale, setStale] = useState(false);
  const attempt = useRef<Attempt>(null);
  const trigger = useRef<HTMLElement | null>(null);
  useEffect(() => { setReport(null); setError(''); setStale(false); attempt.current = null; }, [planId, moduleId]);
  useEffect(() => { setStale(false); attempt.current = null; }, [revision]);
  function dialog(value: boolean) {
    if (value) trigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setOpen(value); onDialogChange?.(value);
    if (!value) requestAnimationFrame(() => { if (trigger.current?.isConnected) trigger.current.focus({ preventScroll: true }); });
  }
  async function read() {
    setBusy(true); setError('');
    try { setReport(await getPlanOrganizationPurgeStatus(planId, moduleId)); }
    catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }
  async function clear() {
    if (busy || disabled || stale) return;
    setBusy(true); setError('');
    const payload = { expected_revision: revision };
    try {
      const result = await purgePlanOrganizationContent(planId, moduleId, { ...payload, request_key: attemptKey(attempt, payload) });
      attempt.current = null; setReport(result.purge_report);
      await onSaved(result); dialog(false);
    } catch (reason) {
      if (conflict(reason)) { setStale(true); setError('计划已变化。请关闭确认框，读取最新状态后重新核对。'); onConflict?.(); }
      else setError(message(reason));
    } finally { setBusy(false); }
  }
  if (!canClear && !report) return null;
  const target = moduleId ? '模块' : '计划';
  return <><details className="learning-organization-more" onToggle={event => { if (event.currentTarget.open && purged && !report && !busy) void read(); }}><summary>更多操作</summary><div>
    {(!purged || report?.status !== 'complete') && <button className="text-button" type="button" disabled={disabled || busy || stale} onClick={() => { setError(''); dialog(true); }}>{purged ? '重试清除剩余副本' : `彻底清除${target}名称与说明`}</button>}
    <button className="text-button" type="button" disabled={busy} onClick={() => void read()}>查看清除结果</button>
    {report && <div aria-label="内容清除结果"><p role="status">{report.status === 'complete' ? '名称、说明及受管理副本已清除。' : report.status === 'not_requested' ? '尚未请求清除。' : '清除尚未完成，可重新打开确认框重试。'}</p>{report.status !== 'complete' && report.files.some(file => file.status === 'failed') && <details><summary>清除详情</summary>{report.files.filter(file => file.status === 'failed').map((file, i) => <p key={i}>{file.name}{file.reason && ` · ${file.reason}`}</p>)}</details>}</div>}
    {error && !open && <p role="alert">{error}</p>}
  </div></details>
    {open && <AttachmentDialog title={`彻底清除${target}名称与说明？`} className="learning-organization-dialog learning-organization-confirm" closeLabel="取消清除" onClose={() => { if (!busy) dialog(false); }}><div className="learning-organization-dialog__body"><p>永久清除这个{target}的名称与说明及受管理副本，无法撤销。{moduleId ? '模块结构、任务及学习记录保留。' : '任务、目标及学习记录保留。'}</p>{error && <p role="alert">{error}</p>}</div><div className="learning-organization-dialog__footer"><button className="button button--quiet" type="button" disabled={busy} onClick={() => dialog(false)}>取消</button><button className="button button--danger" type="button" disabled={busy || disabled || stale} onClick={() => void clear()}>{busy ? '正在清除…' : '确认清除'}</button></div></AttachmentDialog>}
  </>;
}

export function PlanCreateDialog({ goals, onClose, onCreated, onCreateGoal }: {
  goals: Array<{ id: string; title: string; status: string }>; onClose: () => void; onCreated: (planId: string) => void; onCreateGoal: () => void;
}) {
  const [title, setTitle] = useState(''), [description, setDescription] = useState(''), [goalId, setGoalId] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const attempt = useRef<Attempt>(null);
  async function save(event: FormEvent) {
    event.preventDefault(); if (busy || !title.trim()) return;
    setBusy(true); setError('');
    const payload = { title: title.trim(), description: description.trim(), goal_id: goalId || null };
    try { const result = await createLearningPlan({ ...payload, request_key: attemptKey(attempt, payload) }); onCreated(result.plan_id); }
    catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }
  return <AttachmentDialog title="创建学习计划" closeLabel="关闭创建学习计划" className="learning-organization-dialog learning-plan-create-dialog" onClose={() => { if (!busy) onClose(); }}><form onSubmit={save}><div className="learning-organization-dialog__body">
    <label className="field"><span>计划名称</span><input required maxLength={200} value={title} disabled={busy} onChange={event => setTitle(event.target.value)} /></label>
    <label className="field"><span>说明（可选）</span><textarea maxLength={1000} value={description} disabled={busy} onChange={event => setDescription(event.target.value)} /></label>
    <label className="field"><span>关联目标（可选）</span><select aria-label="关联目标（可选）" value={goalId} disabled={busy} onChange={event => setGoalId(event.target.value)}><option value="">暂不关联目标</option>{goals.filter(goal => ['active', 'hypothesis'].includes(goal.status)).map(goal => <option key={goal.id} value={goal.id}>{goal.title}</option>)}</select></label>
    <button className="text-button" type="button" disabled={busy} onClick={onCreateGoal}>从目标开始</button>{error && <p role="alert" className="workspace-alert">{error}</p>}
  </div><div className="learning-organization-dialog__footer"><button className="button button--quiet" type="button" disabled={busy} onClick={onClose}>取消</button><button className="button button--accent" type="submit" disabled={busy || !title.trim()}>{busy ? '正在创建…' : '创建计划'}</button></div></form></AttachmentDialog>;
}

export function PlanTaskDialog({ planId, onClose, onCreated }: { planId: string; onClose: () => void; onCreated: () => void }) {
  const [data, setData] = useState<PlanOrganization | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [title, setTitle] = useState(''), [object, setObject] = useState(''), [behavior, setBehavior] = useState(''), [stop, setStop] = useState('');
  const [context, setContext] = useState('本次学习'), [boundaries, setBoundaries] = useState(''), [budget, setBudget] = useState('');
  const [outcomeId, setOutcomeId] = useState(''), [criterionId, setCriterionId] = useState('');
  const [outcomes, setOutcomes] = useState<LearningOutcome[]>([]), [standards, setStandards] = useState<LearningStandard[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(false), [sourceError, setSourceError] = useState('');
  const [stale, setStale] = useState<'stale' | 'review' | null>(null);
  const attempt = useRef<Attempt>(null), alive = useRef(true), sourcesRequested = useRef(false);
  useEffect(() => {
    alive.current = true;
    getPlanOrganization(planId).then(value => { if (alive.current) setData(value); }).catch(reason => { if (alive.current) setError(message(reason)); });
    return () => { alive.current = false; };
  }, [planId]);
  async function loadSources() {
    if (sourcesRequested.current || sourcesLoading) return;
    setSourcesLoading(true); setSourceError('');
    try {
      const [state, graph] = await Promise.all([getLearningState(), getOutcomeGraph()]);
      if (!alive.current) return;
      const atomic = new Set(graph.nodes.filter(node => node.kind === 'atomic').map(node => node.id));
      setOutcomes(state.outcomes.filter(item => atomic.has(item.id))); setStandards(state.standards.filter(item => atomic.has(item.outcome_id) && item.review_status === 'approved'));
      sourcesRequested.current = true;
    } catch (reason) { if (alive.current) setSourceError(message(reason)); }
    finally { if (alive.current) setSourcesLoading(false); }
  }
  function chooseOutcome(id: string) {
    setOutcomeId(id); setCriterionId('');
    const chosen = outcomes.find(item => item.id === id);
    if (chosen) { setObject(chosen.object_description); setBehavior(chosen.behavior); setContext(chosen.context_key); }
  }
  function chooseStandard(id: string) {
    setCriterionId(id);
    const chosen = standards.find(item => item.id === id);
    if (chosen) { setOutcomeId(chosen.outcome_id); setObject(chosen.object_description); setBehavior(chosen.behavior); setContext(chosen.context_key); }
  }
  async function readLatest() {
    setBusy(true); setError('');
    try { const value = await getPlanOrganization(planId); if (alive.current) { setData(value); setStale('review'); attempt.current = null; } }
    catch (reason) { if (alive.current) setError(message(reason)); }
    finally { if (alive.current) setBusy(false); }
  }
  async function save(event: FormEvent) {
    event.preventDefault(); if (!data || busy || stale) return;
    if (!title.trim() || !object.trim() || !behavior.trim() || !stop.trim() || !context.trim()) { setError('请补充任务、期望能力、停止条件与情境。'); return; }
    const minutes = budget ? Number(budget) : null;
    if (minutes !== null && (!Number.isInteger(minutes) || minutes < 1 || minutes > 1440)) { setError('时间预算请填 1–1440 分钟，或留空。'); return; }
    const selectedOutcome = outcomes.find(item => item.id === outcomeId);
    const payload: Omit<PlanTaskInput, 'request_key'> = {
      action_title: title.trim(), object_description: object.trim(), behavior: behavior.trim(), stop_conditions: stop.trim(),
      context_key: context.trim(), outcome_context_key: selectedOutcome?.context_key ?? context.trim(), outcome_id: outcomeId || null,
      criterion_id: criterionId || null, boundaries: boundaries.trim(), time_budget_minutes: minutes, expected_revision: data.revision,
    };
    setBusy(true); setError('');
    try { await createPlanTask(planId, { ...payload, request_key: attemptKey(attempt, payload) }); if (alive.current) onCreated(); }
    catch (reason) { if (alive.current) { if (conflict(reason)) { setStale('stale'); setError(''); } else setError(message(reason)); } }
    finally { if (alive.current) setBusy(false); }
  }
  const disabled = busy || !!stale;
  const chosenStandard = standards.find(item => item.id === criterionId);
  return <AttachmentDialog title="添加下一步" closeLabel="关闭添加下一步" className="learning-organization-dialog learning-plan-task-dialog" onClose={() => { if (!busy) onClose(); }}><form onSubmit={save}><div className="learning-organization-dialog__body">
    {!data && !error && <p role="status">正在读取计划…</p>}
    <ConflictNotice state={stale} busy={busy} onRead={() => void readLatest()} onReviewed={() => setStale(null)} />
    <label className="field"><span>任务名称</span><input required maxLength={300} disabled={disabled} value={title} onChange={event => setTitle(event.target.value)} /></label>
    <fieldset className="learning-organization-outcome"><legend>希望能够做什么</legend><label className="field"><span>学习对象</span><input required maxLength={500} disabled={disabled || !!outcomeId} value={object} onChange={event => setObject(event.target.value)} placeholder="例如：含空行的文本" /></label><label className="field"><span>希望具备的能力</span><textarea required maxLength={500} disabled={disabled || !!outcomeId} value={behavior} onChange={event => setBehavior(event.target.value)} placeholder="例如：独立拆分并清理文本" /></label></fieldset>
    <label className="field"><span>做到哪里可以停</span><textarea required maxLength={2000} disabled={disabled} value={stop} onChange={event => setStop(event.target.value)} /></label>
    <details className="learning-organization-advanced" onToggle={event => { if (event.currentTarget.open) void loadSources(); }}><summary>情境、时间与已有成果</summary><div>
      <label className="field"><span>情境</span><input maxLength={200} value={context} disabled={disabled || !!chosenStandard} onChange={event => setContext(event.target.value)} /></label>
      <label className="field"><span>时间预算（分钟，可留空）</span><input type="number" step="any" value={budget} disabled={disabled} onChange={event => setBudget(event.target.value)} placeholder="不确定" /></label>
      <label className="field"><span>范围说明（可选）</span><textarea maxLength={2000} disabled={disabled} value={boundaries} onChange={event => setBoundaries(event.target.value)} /></label>
      {sourcesLoading && <p role="status">正在读取已有成果…</p>}{sourceError && <div><p role="alert">{sourceError}</p><button className="text-button" type="button" disabled={sourcesLoading} onClick={() => void loadSources()}>重读已有成果</button></div>}
      <label className="field"><span>成果来源</span><select aria-label="成果来源" value={outcomeId} disabled={disabled || sourcesLoading} onChange={event => chooseOutcome(event.target.value)}><option value="">新建上述期望能力声明</option>{outcomes.map(item => <option key={item.id} value={item.id}>{item.object_description} · {item.behavior}</option>)}</select></label>
      <label className="field"><span>验证标准（可选）</span><select aria-label="验证标准（可选）" value={criterionId} disabled={disabled || sourcesLoading} onChange={event => chooseStandard(event.target.value)}><option value="">暂不选择标准</option>{standards.filter(item => !outcomeId || item.outcome_id === outcomeId).map(item => <option key={item.id} value={item.id}>{item.package_title} · {item.object_description}</option>)}</select></label>
    </div></details>
    {error && <p role="alert" className="workspace-alert">{error}</p>}{!data && error && <button className="text-button" type="button" onClick={() => void getPlanOrganization(planId).then(setData).catch(reason => setError(message(reason)))}>重新读取计划</button>}
  </div><div className="learning-organization-dialog__footer"><button className="button button--quiet" type="button" disabled={busy} onClick={onClose}>取消</button><button className="button button--accent" type="submit" disabled={disabled || !data || !title.trim() || !object.trim() || !behavior.trim() || !stop.trim()}>{busy ? '正在保存…' : '确认任务'}</button></div></form></AttachmentDialog>;
}
