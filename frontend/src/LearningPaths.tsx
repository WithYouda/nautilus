import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { ApiError, getLearningRoom, getLearningState, type LearningRoomBrief, type LearningState, type PurgeReport } from './api';
import { AttachmentDialog } from './AttachmentReview';
import { PlanTaskDialog } from './LearningPlanOrganization';
import LearningPathCanvas, { pathNodeKey, type PathCanvasGroup } from './LearningPathCanvas';
import { organizationRequestKey } from './learning-organization-api';
import {
  confirmPathTransfer, decideLearningPath, getLearningPath, getLearningPathPurgeStatus, previewLearningPath, previewPathTransfer, purgeLearningPathVersion,
  restoreLearningPathDraft, saveLearningPathDraft, startLearningPathTask,
  previewLearningPathTaskRemoval, removeLearningPathTask,
  type LearningPathDraft, type LearningPathDraftInput, type LearningPathEdge, type LearningPathNode,
  type LearningPathPreview, type LearningPathVersion, type LearningPathView, type PathIntent, type PathTransferInput, type PathTransferPreview, type PathTransferResult, type PathCommitmentChange,
  type PathTaskTarget, type PathTaskRemovalInput, type PathTaskRemovalPreview,
} from './learning-path-api';
import './styles/learning-path.css';

const intentLabels: Record<PathIntent, string> = { create: '建立路径', change_entry: '换个入口', change_scope: '调整范围', change_direction: '换个方向', restore: '恢复旧方向', undo: '撤销上次调整' };
const generationBusy = (reason: unknown) => reason instanceof ApiError && (reason.kind === 'path_generation_running' || reason.message === 'path_generation_running');
const failure = (reason: unknown) => {
  if (generationBusy(reason)) return '相关对话仍在生成。请先完成或取消当前回答，再重新核对。已有输出与帮助记录保留。';
  return reason instanceof Error ? reason.message : '操作未完成，请重试。';
};
const isConflict = (reason: unknown) => reason instanceof ApiError && reason.status === 409 && !generationBusy(reason);
type Attempt = { signature: string; key: string } | null;
function keyFor(attempt: { current: Attempt }, body: unknown) {
  const signature = JSON.stringify(body);
  if (attempt.current?.signature !== signature) attempt.current = { signature, key: organizationRequestKey() };
  return attempt.current.key;
}
const blankNode = (): LearningPathNode => ({ id: organizationRequestKey(), title: '', action_ids: [], outcome_ids: [] });
const sequentialEdges = (nodes: LearningPathNode[]): LearningPathEdge[] => nodes.slice(1).map((node, index) => ({ source: nodes[index].id, target: node.id }));
type PathEditorInitial = { intent: LearningPathDraftInput['intent']; source?: LearningPathVersion; draft?: LearningPathDraft; insertAfterNodeId?: string };
type TaskRemoval = { input: PathTaskRemovalInput; taskTitle: string; nodeTitle: string };
function CommitmentChanges({ changes }: { changes: PathCommitmentChange[] }) {
  if (!changes.length) return null;
  return <section><h4>近期安排变化</h4><ul className="learning-path-commitment-changes">{changes.map(change => <li key={change.item_id}><strong>{change.kind === 'keep' ? '保留' : '延期未执行部分'}</strong><span>{change.action_title}</span>{(change.completed || change.skip_preserved || change.executed) && <small>{change.completed ? '已完成记录保留' : change.skip_preserved ? '已跳过记录保留' : '已发生学习记录保留'}</small>}</li>)}</ul></section>;
}
function pathGroups(view: LearningPathView): PathCanvasGroup[] {
  const main = view.versions.find(version => version.id === view.adopted_version_id);
  const versions = main ? [main, ...view.versions.filter(version => version.id !== main.id)] : view.versions;
  return [
    ...versions.filter(version => version.content_available).map(version => ({
      id: `version:${version.id}`, kind: version.id === view.adopted_version_id && view.status === 'active' ? 'main' as const : 'history' as const,
      title: version.title, nodes: version.nodes, edges: version.edges, entryNodeId: version.entry_node_id,
      currentNodeId: version.id === view.adopted_version_id ? view.current_node_id : version.checkpoint?.node_id ?? version.current_node_id,
      parentId: version.parent_version_id ? `version:${version.parent_version_id}` : null, branchNodeId: version.branch_node_id,
    })),
    ...view.drafts.filter(draft => draft.content_available).map(draft => ({ id: `draft:${draft.id}`, kind: 'candidate' as const, title: draft.title, nodes: draft.nodes, edges: draft.edges, entryNodeId: draft.entry_node_id, currentNodeId: draft.current_node_id, parentId: draft.parent_version_id && draft.branch_node_id ? `version:${draft.parent_version_id}` : null, branchNodeId: draft.parent_version_id && draft.branch_node_id ? draft.branch_node_id : null })),
  ];
}

export default function LearningPaths({ planId, state, onLearning, onOpenRecord, onRefresh, onPlanCreated, closed }: {
  planId: string; state: LearningState; onLearning: (brief: LearningRoomBrief) => void; onOpenRecord: (delegationId: string) => void;
  onRefresh: () => Promise<void>; onPlanCreated?: (id: string) => void; closed: boolean;
}) {
  const [view, setView] = useState<LearningPathView | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState('');
  const [selection, setSelection] = useState<string | null>(null), [focusTarget, setFocusTarget] = useState<{ key: string; request: number } | null>(null);
  const [selectedTask, setSelectedTask] = useState<{ nodeKey: string; actionId: string } | null>(null);
  const [editor, setEditor] = useState<PathEditorInitial | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null), [purging, setPurging] = useState(false), [busy, setBusy] = useState(false);
  const [taskTarget, setTaskTarget] = useState<PathTaskTarget | null>(null);
  const [removal, setRemoval] = useState<TaskRemoval | null>(null);
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 760px)').matches);
  const serial = useRef(0), identity = useRef(planId), focusSerial = useRef(0), attempt = useRef<Attempt>(null); identity.current = planId;
  const nestedTrigger = useRef<HTMLElement | null>(null);
  function rememberTrigger() { nestedTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; }
  function returnFocus() { requestAnimationFrame(() => { if (nestedTrigger.current?.isConnected) nestedTrigger.current.focus({ preventScroll: true }); }); }
  function openEditor(value: NonNullable<typeof editor>) { rememberTrigger(); setEditor(value); }
  function openPreview(id: string) { rememberTrigger(); setPreviewId(id); }
  async function read() {
    const sequence = ++serial.current;
    const value = await getLearningPath(planId);
    if (identity.current === planId && sequence === serial.current) { setView(value); setError(''); setLoading(false); }
    return value;
  }
  async function readWithFacts() { const value = await read(); await onRefresh(); return value; }
  useEffect(() => {
    setView(null); setLoading(true); setError(''); setSelection(null); setSelectedTask(null); setEditor(null); setPreviewId(null); setTaskTarget(null); setRemoval(null);
    void read().then(value => {
      if (identity.current !== planId) return;
      const query = new URLSearchParams(window.location.search), versionId = query.get('path_version');
      if (!versionId) return;
      const version = value.versions.find(item => item.id === versionId);
      const nodeId = query.get('path_node') ?? version?.current_node_id;
      if (!version?.content_available || !version.nodes.some(node => node.id === nodeId)) { setError('原路线位置当前不可查看，请选择当前可用阶段或查看任务记录。'); return; }
      const key = pathNodeKey(`version:${version.id}`, nodeId!); setSelection(key); setFocusTarget({ key, request: ++focusSerial.current });
    }).catch(reason => { if (identity.current === planId) { setError(failure(reason)); setLoading(false); } });
    return () => { serial.current++; };
  }, [planId]);
  useEffect(() => { const media = window.matchMedia('(max-width: 760px)'); const change = () => setMobile(media.matches); media.addEventListener('change', change); return () => media.removeEventListener('change', change); }, []);
  async function changed(next: LearningPathView) { setView(next); await onRefresh(); }
  async function transferred(next: PathTransferResult) {
    setView(next.source_path); setEditor(null); setSelection(null);
    try { await onRefresh(); } catch (reason) { setError(`新计划已建立，更新列表失败：${failure(reason)}`); }
    if (onPlanCreated) onPlanCreated(next.plan_id);
    else window.location.assign(`?view=plans&plan=${encodeURIComponent(next.plan_id)}&plan_view=path`);
  }
  function select(key: string) { setSelection(key); setSelectedTask(null); setFocusTarget({ key, request: ++focusSerial.current }); }
  function selectTask(key: string, actionId: string) { setSelection(key); setSelectedTask({ nodeKey: key, actionId }); setFocusTarget({ key, request: ++focusSerial.current }); }
  function closeDetail() {
    const key = selection, task = selectedTask; setSelection(null); setSelectedTask(null);
    if (key) requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(task ? `[data-path-canvas-task="${CSS.escape(`${key}:${task.actionId}`)}"]` : `[data-path-node="${CSS.escape(key)}"]`)?.focus({ preventScroll: true }));
  }
  function addTask() {
    if (!view || !node) return;
    rememberTrigger();
    setTaskTarget({ node_id: node.id, node_title: node.title, expected_revision: view.revision,
      ...(selectedGroup?.kind === 'main' && selectedVersion ? { version_id: selectedVersion.id } : selectedDraft ? { draft_id: selectedDraft.id, expected_draft_revision: selectedDraft.revision } : {}) });
  }
  function addNextStage() {
    if (!view || !node) return;
    openEditor({ intent: selectedDraft ? selectedDraft.intent as LearningPathDraftInput['intent'] : 'change_scope', draft: selectedDraft,
      source: selectedDraft ? view.versions.find(version => version.id === selectedDraft.source_version_id) : selectedVersion,
      insertAfterNodeId: node.id });
  }
  function removeTask(actionId: string, mode: PathTaskRemovalInput['mode']) {
    const action = state.actions.find(item => item.id === actionId);
    if (!view || !node || !action || action.deleted || action.status === 'cancelled' || !canEditStage) return;
    rememberTrigger();
    setRemoval({ taskTitle: action.title, nodeTitle: node.title, input: {
      node_id: node.id, action_id: action.id, mode, expected_revision: view.revision,
      expected_organization_revision: view.organization_revision, expected_action_version: action.version,
      ...(selectedDraft ? { draft_id: selectedDraft.id, expected_draft_revision: selectedDraft.revision } : { version_id: selectedVersion!.id }),
    } });
  }
  const main = view?.versions.find(version => version.id === view.adopted_version_id);
  const groups = view ? pathGroups(view) : [];
  const selectedGroup = groups.find(group => group.nodes.some(node => pathNodeKey(group.id, node.id) === selection));
  const node = selectedGroup?.nodes.find(item => pathNodeKey(selectedGroup.id, item.id) === selection);
  const selectedVersion = selectedGroup ? view?.versions.find(version => `version:${version.id}` === selectedGroup.id) : undefined;
  const selectedDraft = selectedGroup ? view?.drafts.find(draft => `draft:${draft.id}` === selectedGroup.id) : undefined;
  const canEditStage = selectedGroup?.kind === 'main' || !!selectedDraft && !selectedDraft.stale && !['restore', 'undo'].includes(selectedDraft.intent);
  const currentKey = view?.adopted_version_id && view.current_node_id ? pathNodeKey(`version:${view.adopted_version_id}`, view.current_node_id) : null;
  const planTasks = new Set(state.action_links.filter(link => link.plan_id === planId).map(link => link.action_id));
  const running = state.sessions.find(session => session.status === 'running' && planTasks.has(session.action_id));
  const runningElsewhere = running && main && !main.nodes.find(node => node.id === view?.current_node_id)?.action_ids.includes(running.action_id);
  const runningNode = runningElsewhere ? main!.nodes.find(node => node.action_ids.includes(running!.action_id)) : undefined;
  const latestDecision = view?.decisions.find(decision => decision.version_id === view.adopted_version_id && decision.previous_version_id);
  const undoVersion = view?.versions.find(version => version.id === latestDecision?.previous_version_id && version.content_available);
  async function restore(version: LearningPathVersion, intent: 'restore' | 'undo', nodeId?: string) {
    if (!view || busy || closed || !version.content_available) return;
    rememberTrigger();
    const body = { version_id: version.id, ...(nodeId ? { node_id: nodeId } : {}), intent, expected_revision: view.revision, expected_organization_revision: view.organization_revision, reason: '' };
    setBusy(true); setError('');
    try { const result = await restoreLearningPathDraft(planId, { ...body, request_key: keyFor(attempt, body) }); attempt.current = null; setView(result); setPreviewId(result.draft_id); }
    catch (reason) { setError(isConflict(reason) ? '路线或任务已变化，请重新读取路径后核对。' : failure(reason)); }
    finally { setBusy(false); }
  }
  async function start(actionId: string, useCheckpoint = true) {
    if (!view || view.status !== 'active' || !node || !selectedVersion || selectedGroup?.kind !== 'main' || busy || closed) return;
    const action = state.actions.find(item => item.id === actionId);
    const delegation = state.delegations.find(item => item.action_id === actionId && ['active', 'ready'].includes(item.status));
    if (!action || action.deleted || action.status !== 'open' || !delegation) return;
    const body = { version_id: selectedVersion.id, node_id: node.id, delegation_id: delegation.id, expected_action_version: action.version, expected_revision: view.revision, use_checkpoint: useCheckpoint };
    setBusy(true); setError('');
    try {
      const result = await startLearningPathTask(planId, { ...body, request_key: keyFor(attempt, body) });
      const room = await getLearningRoom(result.session_id); attempt.current = null;
      const brief = Object.assign({}, room.brief, result.path_anchor ? { path_anchor: result.path_anchor } : {});
      onLearning(brief);
    } catch (reason) { setError(isConflict(reason) ? '任务或路径已变化，请重新读取路径后再选择。' : failure(reason)); }
    finally { setBusy(false); }
  }
  function detail(): ReactNode {
    if (!node || !selectedGroup || !view) return null;
    const checkpointMissing = selectedVersion?.checkpoint?.available === false;
    return <div className="learning-path-detail">
      {!mobile && <header><h3>{node.title}</h3><button className="icon-button" type="button" aria-label="关闭阶段详情" onClick={closeDetail}>×</button></header>}
      <p className="learning-path-detail__state">{selectedGroup.kind === 'candidate' ? '待采用' : selectedGroup.kind === 'history' ? node.id === selectedGroup.currentNodeId ? '上次位置 · 暂停方向' : '暂停方向' : node.id === view.current_node_id ? '当前位置' : '当前路线'} · {selectedGroup.title}</p>
      {checkpointMissing && <p className="workspace-alert">原学习位置当前不可读取。可查看原任务记录，或明确从当前可用任务开始。</p>}
      {selectedGroup.kind === 'history' && selectedVersion && <button className="button button--accent" type="button" disabled={busy || closed} onClick={() => void restore(selectedVersion, 'restore', node.id)}>从这里继续</button>}
      {selectedGroup.kind === 'candidate' && selectedDraft && <div className="learning-path-actions"><button className="button button--accent" type="button" disabled={busy || closed} onClick={() => openPreview(selectedDraft.id)}>查看采用方案</button>{!['restore', 'undo'].includes(selectedDraft.intent) && <button className="text-button" type="button" disabled={busy || closed} onClick={() => openEditor({ intent: selectedDraft.intent as LearningPathDraftInput['intent'], draft: selectedDraft, source: view.versions.find(version => version.id === selectedDraft.source_version_id) })}>编辑草案</button>}</div>}
      <section className="learning-path-task-links" aria-label="关联任务"><h4>{selectedTask?.nodeKey === selection ? '所选任务' : '阶段任务'}</h4>{node.action_ids.filter(id => selectedTask?.nodeKey !== selection || id === selectedTask.actionId).map(id => {
        const action = state.actions.find(item => item.id === id);
        const removed = action?.deleted || action?.status === 'cancelled';
        const delegations = state.delegations.filter(item => item.action_id === id);
        const available = delegations.find(item => ['active', 'ready'].includes(item.status));
        return <article key={id} className={selectedTask?.actionId === id ? 'is-selected' : ''}><strong>{action?.title ?? '任务当前不可查看'}</strong>{(removed || action?.status === 'completed') && <span className="learning-state-label">{removed ? '已删除' : '已完成'}</span>}
          <div className="learning-path-actions">{selectedGroup.kind === 'main' && !removed && action?.status === 'open' && available && <button className="button button--quiet" type="button" disabled={busy || closed} onClick={() => void start(id, !checkpointMissing)}>{checkpointMissing ? '从当前可用任务开始' : available.status === 'active' ? '继续学习' : '开始学习'}</button>}{delegations[0] && <button className="text-button" type="button" onClick={() => onOpenRecord(delegations[0].id)}>{action?.status === 'completed' ? '回看记录' : '查看记录'}</button>}
          {canEditStage && !removed && selectedTask?.actionId === id && <><button className="text-button" type="button" disabled={closed || busy} onClick={() => removeTask(id, 'detach')}>移出阶段</button><button className="text-button" type="button" disabled={closed || busy} onClick={() => removeTask(id, 'delete')}>删除任务</button></>}</div>
        </article>;
      })}</section>
      {canEditStage && <div className="learning-path-actions"><button className="button button--quiet" type="button" disabled={closed || busy} onClick={addTask}>添加任务</button><button className="text-button" type="button" disabled={closed || busy || selectedGroup.nodes.length >= 60} onClick={addNextStage}>添加下一阶段</button></div>}
      {!!node.outcome_ids.length && <details><summary>成果依据</summary><div className="learning-path-outcome-links">{node.outcome_ids.map(id => <a key={id} href={`?view=records&outcome=${encodeURIComponent(id)}`}>{state.outcomes.find(outcome => outcome.id === id)?.object_description ?? '关联成果'} · 查看依据</a>)}</div></details>}
      {selectedVersion && <details><summary>路线变更详情</summary>{view.decisions.filter(decision => decision.version_id === selectedVersion.id).map(decision => <div key={decision.id}><p>{intentLabels[decision.intent]} · {new Date(decision.created_at).toLocaleString()}</p>{decision.reason && <p>{decision.reason}</p>}</div>)}<PathContentPurge planId={planId} version={selectedVersion} revision={view.revision} closed={closed} retryNeeded={view.purge_retry_ids?.includes(selectedVersion.id)} onChanged={changed} onDialogChange={setPurging} /></details>}
    </div>;
  }
  return <section className="learning-paths" aria-label="计划路径">
    <div className="learning-path-toolbar"><div>{main?.content_available && <h3>{main.title}</h3>}</div><div className="learning-path-actions"><button className="button button--quiet" type="button" disabled={closed || busy || !view} onClick={() => openEditor({ intent: main?.content_available ? 'change_entry' : main ? 'change_direction' : 'create', source: main?.content_available ? main : undefined })}>{main?.content_available ? '调整方向' : '建立路径'}</button>{undoVersion && <button className="text-button" type="button" disabled={closed || busy} onClick={() => void restore(undoVersion, 'undo')}>撤销上次调整</button>}</div></div>
    {loading && <p role="status">正在读取路径…</p>}{error && <div role="alert"><p>{error}</p><button className="text-button" type="button" disabled={busy} onClick={() => void read().then(onRefresh).catch(reason => setError(failure(reason)))}>重新读取路径</button></div>}
    {runningElsewhere && <div className="learning-path-outside"><p>当前正在学习：{running.action_title}{!runningNode && '（未关联这条路线）'}</p>{runningNode && <button className="text-button" type="button" onClick={() => { const key = pathNodeKey(`version:${main!.id}`, runningNode.id); select(key); setFocusTarget({ key, request: ++focusSerial.current }); }}>查看关联阶段</button>}</div>}
    {view?.status === 'paused' && main?.content_available && <div className="learning-path-paused"><p>原方向已暂停，记录与上次位置保留。</p><button className="button button--quiet" type="button" disabled={busy || closed} onClick={() => void restore(main, 'restore')}>预览恢复原方向</button></div>}
    {view && !groups.length && <div className="learning-path-empty"><h3>{main ? '原路线内容已清除' : '从几个有意义的阶段开始'}</h3><p>明确关联已有任务或成果，确认后记录当前路线。</p></div>}
    {!!groups.length && <div className={`learning-path-layout ${node && !mobile ? 'has-detail' : ''}`}><LearningPathCanvas groups={groups} actions={state.actions} selected={selection} selectedTask={selectedTask} onSelect={select} onTaskSelect={selectTask} currentKey={currentKey} focusTarget={focusTarget} />{node && !mobile && <aside className="learning-path-inspector" aria-label="阶段详情">{detail()}</aside>}</div>}
    {view && !!view.purge_retry_ids?.length && <div className="learning-path-purge-retries" aria-label="尚未完成的路线清除"><p>部分路线副本尚未清除。</p>{view.purge_retry_ids.map(id => { const version = view.versions.find(item => item.id === id); return version ? <PathContentPurge key={id} planId={planId} version={version} revision={view.revision} closed={closed} retryNeeded onChanged={changed} onDialogChange={setPurging} /> : null; })}</div>}
    {view && !!view.transfers?.length && <details className="learning-path-transfer-links"><summary>转向来源与新计划</summary><div>{view.transfers.map((transfer, index) => {
      const incoming = transfer.destination_plan_id === planId, relatedPlan = incoming ? transfer.source_plan_id : transfer.destination_plan_id;
      const versionId = incoming ? transfer.version_id : transfer.destination_version_id;
      const title = state.plans.find(plan => plan.id === relatedPlan)?.title ?? (incoming ? '原计划' : '新计划');
      return <p key={index}><a href={`?view=plans&plan=${encodeURIComponent(relatedPlan)}&plan_view=path&path_version=${encodeURIComponent(versionId)}${incoming ? `&path_node=${encodeURIComponent(transfer.node_id)}` : ''}`}>{incoming ? '查看原路线' : '查看新计划'}：{title}</a>{transfer.pause_original && incoming && <small>原方向暂停，原任务与记录保留。</small>}</p>;
    })}</div></details>}
    {view && view.versions.length > 1 && <details className="learning-path-history"><summary>查看路线历史</summary><div>{view.versions.filter(version => version.id !== view.adopted_version_id).map(version => <article key={version.id}><strong>{version.content_available ? version.title : '路线内容已清除'}</strong>{version.content_available ? <button className="text-button" type="button" onClick={() => { const key = pathNodeKey(`version:${version.id}`, version.checkpoint?.node_id ?? version.current_node_id ?? version.entry_node_id); select(key); setFocusTarget({ key, request: ++focusSerial.current }); }}>查看旧方向</button> : <PathContentPurge planId={planId} version={version} revision={view.revision} closed={closed} retryNeeded={view.purge_retry_ids?.includes(version.id)} onChanged={changed} onDialogChange={setPurging} />}</article>)}</div></details>}
    {node && mobile && <AttachmentDialog title={node.title} closeLabel="关闭阶段详情" className="learning-path-drawer" onClose={closeDetail} suspended={Boolean(editor || previewId || purging || taskTarget || removal)}>{detail()}</AttachmentDialog>}
    {taskTarget && <PlanTaskDialog planId={planId} pathTarget={taskTarget} onClose={() => { setTaskTarget(null); returnFocus(); }} onCreated={async (next, actionId) => {
      if (!next) return;
      setView(next); setTaskTarget(null);
      const group = taskTarget.draft_id ? `draft:${taskTarget.draft_id}` : `version:${next.adopted_version_id}`;
      const key = pathNodeKey(group, taskTarget.node_id); setSelection(key); setFocusTarget({ key, request: ++focusSerial.current });
      setSelectedTask(actionId ? { nodeKey: key, actionId } : null);
      try { await onRefresh(); } catch (reason) { setError(`任务已保存，更新界面失败：${failure(reason)}`); }
      if (!mobile && actionId) requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(`[data-path-canvas-task="${CSS.escape(`${key}:${actionId}`)}"]`)?.focus({ preventScroll: true }));
    }} />}
    {editor && view && <PathEditor planId={planId} state={state} view={view} initial={editor} closed={closed} onClose={() => { setEditor(null); returnFocus(); }} onRead={readWithFacts} onTransferred={transferred} onSaved={async (next, draftId, focusNodeId) => { setView(next); setEditor(null); setSelectedTask(null); const key = pathNodeKey(`draft:${draftId}`, focusNodeId ?? next.drafts.find(draft => draft.id === draftId)!.current_node_id); setSelection(key); setFocusTarget({ key, request: ++focusSerial.current }); }} />}
    {removal && <PathTaskRemovalDialog planId={planId} value={removal} closed={closed} onRead={readWithFacts} onClose={() => { setRemoval(null); returnFocus(); }} onConfirmed={async next => {
      const key = pathNodeKey(removal.input.draft_id ? `draft:${removal.input.draft_id}` : `version:${next.adopted_version_id}`, removal.input.node_id);
      setView(next); setRemoval(null); setSelection(key); setSelectedTask(null); setFocusTarget({ key, request: ++focusSerial.current });
      try { await onRefresh(); } catch (reason) { setError(`任务变化已保存，更新界面失败：${failure(reason)}`); }
      requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(mobile ? '.learning-path-drawer [aria-label="关闭阶段详情"]' : `[data-path-node="${CSS.escape(key)}"]`)?.focus({ preventScroll: true }));
    }} />}
    {previewId && view && <PathPreview planId={planId} draftId={previewId} view={view} state={state} closed={closed} onClose={() => { setPreviewId(null); returnFocus(); }} onRead={readWithFacts} onConfirmed={async next => { setView(next); setPreviewId(null); setSelection(null); try { await onRefresh(); } catch (reason) { setError(`路线已保存，更新界面失败：${failure(reason)}`); } }} />}
  </section>;
}

function PathEditor({ planId, state, view, initial, closed, onClose, onRead, onSaved, onTransferred }: {
  planId: string; state: LearningState; view: LearningPathView;
  initial: PathEditorInitial; closed: boolean;
  onClose: () => void; onRead: () => Promise<LearningPathView>; onSaved: (view: LearningPathView, draftId: string, focusNodeId?: string) => Promise<void>;
  onTransferred: (result: PathTransferResult) => Promise<void>;
}) {
  const template = initial.draft ?? (initial.intent !== 'change_direction' ? initial.source : undefined);
  const inserted = useRef(initial.insertAfterNodeId ? blankNode() : null);
  const first = useRef(template?.nodes.map(node => ({ ...node, action_ids: [...node.action_ids], outcome_ids: [...node.outcome_ids] })) ?? [blankNode()]);
  if (inserted.current && !first.current.some(node => node.id === inserted.current!.id)) first.current.splice(first.current.findIndex(node => node.id === initial.insertAfterNodeId) + 1, 0, inserted.current);
  const [nodes, setNodes] = useState(first.current), [edges, setEdges] = useState(() => inserted.current ? [
    ...(template?.edges ?? []).filter(edge => edge.source !== initial.insertAfterNodeId),
    { source: initial.insertAfterNodeId!, target: inserted.current.id },
    ...(template?.edges ?? []).filter(edge => edge.source === initial.insertAfterNodeId).map(edge => ({ source: inserted.current!.id, target: edge.target })),
  ] : template?.edges ?? []);
  const [title, setTitle] = useState(template?.title ?? ''), [reason, setReason] = useState(initial.draft?.reason ?? ''), [intent, setIntent] = useState(initial.intent);
  const [sourceVersionId, setSourceVersionId] = useState(initial.draft?.source_version_id ?? (initial.source && initial.intent !== 'change_direction' ? initial.source.id : null));
  const [entry, setEntry] = useState(template?.entry_node_id ?? first.current[0].id), [current, setCurrent] = useState(initial.source?.id === view.adopted_version_id && !initial.draft ? view.current_node_id ?? template!.current_node_id : template?.current_node_id ?? first.current[0].id);
  const [base, setBase] = useState(view), [busy, setBusy] = useState(false), [error, setError] = useState(''), [stale, setStale] = useState<'stale' | 'review' | null>(null);
  const [destination, setDestination] = useState<'current' | 'new'>('new'), [destinationTitle, setDestinationTitle] = useState(''), [destinationDescription, setDestinationDescription] = useState(''), [pauseOriginal, setPauseOriginal] = useState(true);
  const [transfer, setTransfer] = useState<{ body: PathTransferInput; preview: PathTransferPreview } | null>(null);
  const attempt = useRef<Attempt>(null);
  const transferTrigger = useRef<HTMLElement | null>(null);
  const ids = new Set(state.action_links.filter(link => link.plan_id === planId).map(link => link.action_id));
  const actions = state.actions.filter(action => ids.has(action.id) && !action.deleted && action.status !== 'cancelled');
  const disabled = busy || closed || !!stale;
  const newPlan = intent === 'change_direction' && destination === 'new';
  function edit(id: string, values: Partial<LearningPathNode>) { setNodes(previous => previous.map(node => node.id === id ? { ...node, ...values } : node)); }
  function order(next: LearningPathNode[]) { setNodes(next); setEdges(sequentialEdges(next)); setEntry(next[0].id); }
  function chooseEntry(id: string) { const chosen = nodes.find(node => node.id === id); if (chosen) order([chosen, ...nodes.filter(node => node.id !== id)]); }
  function switchIntent(value: LearningPathDraftInput['intent']) {
    setIntent(value);
    if (value === 'change_direction') { const node = blankNode(); setTitle(''); setNodes([node]); setEdges([]); setEntry(node.id); setCurrent(node.id); setSourceVersionId(null); }
  }
  function changeDestination(value: 'current' | 'new') {
    if (value === 'new' && nodes.some(node => node.action_ids.length)) { setError('要新建计划，请先取消本草案中的原任务选择。原任务仍保留在当前计划。'); return; }
    setDestination(value); setError('');
  }
  async function readLatest() {
    setBusy(true); setError('');
    try { setBase(await onRead()); setStale('review'); attempt.current = null; }
    catch (reason) { setError(failure(reason)); }
    finally { setBusy(false); }
  }
  async function save(event: FormEvent) {
    event.preventDefault(); if (disabled || !title.trim() || nodes.some(node => !node.title.trim())) return;
    if (newPlan) {
      if (!destinationTitle.trim() || nodes.some(node => node.action_ids.length)) { setError('请填写新计划名称，并取消原任务选择；原任务留在当前计划。'); return; }
      const body: PathTransferInput = { title: title.trim(), nodes: nodes.map(node => ({ ...node, title: node.title.trim() })), edges, entry_node_id: entry, current_node_id: current, reason: reason.trim(), destination_title: destinationTitle.trim(), destination_description: destinationDescription.trim(), pause_original: pauseOriginal, expected_revision: base.revision, expected_organization_revision: base.organization_revision };
      transferTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setBusy(true); setError('');
      try { setTransfer({ body, preview: await previewPathTransfer(planId, body) }); }
      catch (reason) { if (isConflict(reason)) { setStale('stale'); setError('原计划或当前学习已变化，输入已保留。'); } else setError(failure(reason)); }
      finally { setBusy(false); }
      return;
    }
    const latestDraft = initial.draft ? base.drafts.find(draft => draft.id === initial.draft!.id) : null;
    if (initial.draft && !latestDraft) { setError('这份草案已不可编辑，输入仍保留。请关闭后重新核对路线。'); return; }
    const body: Omit<LearningPathDraftInput, 'request_key'> = {
      title: title.trim(), nodes: nodes.map(node => ({ ...node, title: node.title.trim() })), edges, entry_node_id: entry, current_node_id: current,
      reason: reason.trim(), intent, expected_revision: base.revision, expected_organization_revision: base.organization_revision,
      source_version_id: sourceVersionId,
      draft_id: initial.draft?.id ?? null, ...(latestDraft ? { expected_draft_revision: latestDraft.revision } : {}),
    };
    setBusy(true); setError('');
    try { const next = await saveLearningPathDraft(planId, { ...body, request_key: keyFor(attempt, body) }); await onSaved(next, next.draft_id, inserted.current?.id); }
    catch (reason) { if (isConflict(reason)) { setStale('stale'); setError('路线或任务已变化，输入已保留。'); } else setError(failure(reason)); }
    finally { setBusy(false); }
  }
  return <><AttachmentDialog title={initial.insertAfterNodeId ? '添加下一阶段' : intent === 'create' ? '建立路径' : '调整方向'} closeLabel="关闭路径编辑" className="learning-path-dialog" suspended={!!transfer} onClose={() => { if (!busy) onClose(); }}><form onSubmit={save}><div className="learning-path-dialog__body">
    {error && <p role="alert">{error}</p>}{stale && <div className="learning-path-conflict"><p>{stale === 'stale' ? '请读取最新状态再核对，你的阶段与关联仍保留。' : '已读取最新状态，请核对任务与路线后继续编辑。'}</p><button className="button button--quiet" type="button" disabled={busy} onClick={stale === 'stale' ? () => void readLatest() : () => setStale(null)}>{stale === 'stale' ? '读取最新状态' : '已核对，继续编辑'}</button></div>}
    {initial.intent !== 'create' && !initial.draft && !initial.insertAfterNodeId && <label className="field"><span>这次想调整什么</span><select aria-label="这次想调整什么" value={intent} disabled={disabled} onChange={event => switchIntent(event.target.value as LearningPathDraftInput['intent'])}><option value="change_entry">换个入口</option><option value="change_scope">调整范围</option><option value="change_direction">换个方向</option></select></label>}
    {intent === 'change_direction' && <div className="learning-path-destination"><label className="field"><span>这还是同一个学习目标吗？</span><select aria-label="这还是同一个学习目标吗？" value={destination} disabled={disabled} onChange={event => changeDestination(event.target.value as 'current' | 'new')}><option value="new">新建计划，独立管理（推荐）</option><option value="current">留在当前计划</option></select></label>{newPlan && <><label className="field"><span>新计划名称</span><input required maxLength={200} value={destinationTitle} disabled={disabled} onChange={event => setDestinationTitle(event.target.value)} /></label><p className="form-hint">暂不关联目标，已有成果可沿用。原任务留在当前计划。</p><label className="learning-path-check"><input type="checkbox" checked={pauseOriginal} disabled={disabled} onChange={event => setPauseOriginal(event.target.checked)} /><span>暂停原方向并保留现场</span></label><details><summary>新计划说明（可选）</summary><label className="field"><span>说明</span><textarea maxLength={1000} value={destinationDescription} disabled={disabled} onChange={event => setDestinationDescription(event.target.value)} /></label></details></>}</div>}
    <label className="field"><span>路线名称</span><input required maxLength={200} disabled={disabled} value={title} onChange={event => setTitle(event.target.value)} /></label>
    <div className="learning-path-stages">{nodes.map((node, index) => <fieldset key={node.id} className="learning-path-stage"><legend>阶段 {index + 1}</legend><label className="field"><span>阶段名称</span><input required maxLength={200} autoFocus={node.id === inserted.current?.id} value={node.title} disabled={disabled} onChange={event => edit(node.id, { title: event.target.value })} /></label>
      <details><summary>关联任务与成果{node.action_ids.length + node.outcome_ids.length > 0 ? `（${node.action_ids.length + node.outcome_ids.length}）` : ''}</summary><div className="learning-path-stage__links"><fieldset><legend>计划任务</legend>{newPlan && <p>原任务留在当前计划，新计划的任务以后明确创建。</p>}{actions.map(action => <label key={action.id}><input type="checkbox" data-path-task={action.id} disabled={disabled || newPlan || !node.action_ids.includes(action.id) && node.action_ids.length >= 30} checked={node.action_ids.includes(action.id)} onChange={event => edit(node.id, { action_ids: event.target.checked ? [...node.action_ids, action.id] : node.action_ids.filter(id => id !== action.id) })} /><span>{action.title}</span></label>)}{!actions.length && <p>这个计划还没有任务。</p>}</fieldset><fieldset><legend>已有成果（可选）</legend>{state.outcomes.map(outcome => <label key={outcome.id}><input type="checkbox" data-path-outcome={outcome.id} disabled={disabled || !node.outcome_ids.includes(outcome.id) && node.outcome_ids.length >= 30} checked={node.outcome_ids.includes(outcome.id)} onChange={event => edit(node.id, { outcome_ids: event.target.checked ? [...node.outcome_ids, outcome.id] : node.outcome_ids.filter(id => id !== outcome.id) })} /><span>{outcome.object_description}</span></label>)}</fieldset></div></details>
      <div className="learning-path-stage__order"><button className="text-button" type="button" disabled={disabled || index === 0} onClick={() => { const next = [...nodes]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; order(next); }}>向上移</button><button className="text-button" type="button" disabled={disabled || index === nodes.length - 1} onClick={() => { const next = [...nodes]; [next[index], next[index + 1]] = [next[index + 1], next[index]]; order(next); }}>向下移</button><button className="text-button" type="button" disabled={disabled || nodes.length === 1} onClick={() => { const next = nodes.filter(item => item.id !== node.id); order(next); if (entry === node.id) setEntry(next[0].id); if (current === node.id) setCurrent(next[0].id); }}>移除阶段</button></div>
    </fieldset>)}</div>
    <button className="button button--quiet" type="button" disabled={disabled || nodes.length >= 60} onClick={() => order([...nodes, blankNode()])}>添加阶段</button>
    <p className="form-hint">选择起点会将该阶段移到开头。调整顺序后，将按此顺序衔接，可在草案图中核对。</p>
    <div className="learning-path-position-fields"><label className="field"><span>起点</span><select aria-label="起点" value={entry} disabled={disabled} onChange={event => chooseEntry(event.target.value)}>{nodes.map((node, index) => <option key={node.id} value={node.id}>{node.title || `阶段 ${index + 1}`}</option>)}</select></label><label className="field"><span>当前位置</span><select aria-label="当前位置" value={current} disabled={disabled} onChange={event => setCurrent(event.target.value)}>{nodes.map((node, index) => <option key={node.id} value={node.id}>{node.title || `阶段 ${index + 1}`}</option>)}</select></label></div>
    <details className="learning-path-reason"><summary>调整原因（可选）</summary><label className="field"><span>原因</span><textarea maxLength={2000} value={reason} disabled={disabled} onChange={event => setReason(event.target.value)} /></label></details>
  </div><div className="learning-path-dialog__footer"><button className="button button--quiet" type="button" disabled={busy} onClick={onClose}>取消</button><button className="button button--accent" type="submit" disabled={disabled || !title.trim() || nodes.some(node => !node.title.trim()) || newPlan && !destinationTitle.trim()}>{busy ? newPlan ? '正在核对…' : '正在保存…' : newPlan ? '查看转向方案' : '保存草案'}</button></div></form></AttachmentDialog>
    {transfer && <PathTransferDialog planId={planId} sourceTitle={state.plans.find(plan => plan.id === planId)?.title ?? '原计划'} value={transfer} view={base} closed={closed} onClose={() => { setTransfer(null); requestAnimationFrame(() => { if (transferTrigger.current?.isConnected) transferTrigger.current.focus({ preventScroll: true }); }); }} onRead={async () => { const next = await onRead(); setBase(next); return next; }} onRechecked={setTransfer} onConfirmed={onTransferred} />}
  </>;
}

function PathTaskRemovalDialog({ planId, value, closed, onClose, onRead, onConfirmed }: {
  planId: string; value: TaskRemoval; closed: boolean; onClose: () => void;
  onRead: () => Promise<LearningPathView>; onConfirmed: (view: LearningPathView) => Promise<void>;
}) {
  const [input, setInput] = useState(value.input), [preview, setPreview] = useState<PathTaskRemovalPreview | null>(null);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [stale, setStale] = useState(false), [error, setError] = useState('');
  const alive = useRef(true), attempt = useRef<Attempt>(null);
  const deleting = input.mode === 'delete';
  async function review(refresh = false) {
    setLoading(true); setError(''); setPreview(null);
    try {
      let next = input;
      if (refresh) {
        const path = await onRead(), state = await getLearningState();
        const action = state.actions.find(item => item.id === input.action_id);
        const draft = input.draft_id ? path.drafts.find(item => item.id === input.draft_id && !item.stale && !['restore', 'undo'].includes(item.intent)) : undefined;
        const version = !input.draft_id && path.status === 'active' ? path.versions.find(item => item.id === path.adopted_version_id) : undefined;
        const node = (draft ?? version)?.nodes.find(item => item.id === input.node_id && item.action_ids.includes(input.action_id));
        if (!action || action.deleted || action.status === 'cancelled' || !node) throw new Error('所选任务或阶段已变化。请关闭后从当前路径重新选择。');
        next = { ...input, expected_revision: path.revision, expected_organization_revision: path.organization_revision, expected_action_version: action.version,
          ...(draft ? { expected_draft_revision: draft.revision } : { version_id: version!.id }) };
      }
      const result = await previewLearningPathTaskRemoval(planId, next);
      if (alive.current) { setInput(next); setPreview(result); setStale(false); attempt.current = null; }
    } catch (reason) { if (alive.current) { setError(failure(reason)); setStale(true); } }
    finally { if (alive.current) setLoading(false); }
  }
  useEffect(() => { alive.current = true; void review(); return () => { alive.current = false; }; }, []);
  async function confirm() {
    if (!preview || busy || loading || stale || closed) return;
    const body = { ...input, review_key: preview.review_key };
    setBusy(true); setError('');
    try { const next = await removeLearningPathTask(planId, { ...body, request_key: keyFor(attempt, body) }); await onConfirmed(next); }
    catch (reason) { if (alive.current) { setError(isConflict(reason) ? '任务、路线或当前学习已变化。请重新读取并核对影响。' : failure(reason)); if (isConflict(reason) || generationBusy(reason)) setStale(true); } }
    finally { if (alive.current) setBusy(false); }
  }
  return <AttachmentDialog title={deleting ? '删除任务' : '移出阶段'} closeLabel="关闭任务变化预览" className="learning-path-dialog learning-path-task-removal" onClose={() => { if (!busy) onClose(); }}><div className="learning-path-dialog__body">
    <h3 className="learning-path-task-removal__title">{value.taskTitle}</h3>
    <p>{deleting ? '从计划任务和当前路线中移除这项任务，已发生的学习记录与成果依据保留。' : `从“${value.nodeTitle}”移出这项任务，任务仍保留在计划中，其他阶段关联保留。`}</p>
    {input.draft_id && <p>{deleting ? '所选候选路线也会移除这项任务，候选仍待采用。' : '只修改所选候选路线，当前采用路线保持。'}</p>}
    {loading && <p role="status">正在核对影响…</p>}{error && <p role="alert">{error}</p>}
    {preview && <>{!!preview.affected_sessions.length && <section className="learning-path-preview__impact"><h4>确认后暂停当前学习</h4><ul>{preview.affected_sessions.map(session => <li key={session.id}>{session.action_title}</li>)}</ul><p>已有作答、产出和帮助记录保留。</p></section>}<CommitmentChanges changes={preview.commitment_changes} /></>}
    {stale && <button className="button button--quiet" type="button" disabled={busy || loading} onClick={() => void review(true)}>重新读取并核对</button>}
  </div><div className="learning-path-dialog__footer"><button className="button button--quiet" type="button" disabled={busy} onClick={onClose}>取消</button><button className={`button ${deleting ? 'button--danger' : 'button--accent'}`} type="button" disabled={busy || loading || closed || stale || !preview} onClick={() => void confirm()}>{busy ? '正在保存…' : deleting ? '确认删除任务' : '确认移出阶段'}</button></div></AttachmentDialog>;
}

function PathPreview({ planId, draftId, view, state, closed, onClose, onRead, onConfirmed }: {
  planId: string; draftId: string; view: LearningPathView; state: LearningState; closed: boolean;
  onClose: () => void; onRead: () => Promise<LearningPathView>; onConfirmed: (view: LearningPathView) => Promise<void>;
}) {
  const [preview, setPreview] = useState<LearningPathPreview | null>(null), [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [error, setError] = useState(''), [stale, setStale] = useState(false);
  const attempt = useRef<Attempt>(null), active = useRef(true);
  async function read(refresh = false) {
    setLoading(true); setError('');
    try { if (refresh) await onRead(); const value = await previewLearningPath(planId, draftId); if (active.current) { setPreview(value); setStale(false); attempt.current = null; } }
    catch (reason) { if (active.current) { setError(failure(reason)); setStale(true); } }
    finally { if (active.current) setLoading(false); }
  }
  useEffect(() => { active.current = true; void read(); return () => { active.current = false; }; }, [planId, draftId]);
  async function confirm() {
    if (!preview || busy || closed || stale) return;
    const body = { draft_id: draftId, expected_draft_revision: preview.draft_revision, expected_revision: preview.revision, review_key: preview.review_key };
    setBusy(true); setError('');
    try { const next = await decideLearningPath(planId, { ...body, request_key: keyFor(attempt, body) }); await onConfirmed(next); }
    catch (reason) { if (generationBusy(reason)) { setStale(true); setError(failure(reason)); } else if (isConflict(reason)) { setStale(true); setError('路线、任务或当前学习已变化。草案已保留，请重新读取并核对。'); } else setError(failure(reason)); }
    finally { setBusy(false); }
  }
  const original = view.versions.find(version => version.id === view.adopted_version_id);
  const restoredVersion = view.versions.find(version => version.id === preview?.draft.restore_version_id);
  const restoresDifferentNode = !!preview && ['restore', 'undo'].includes(preview.intent) && restoredVersion?.checkpoint?.node_id !== preview.draft.current_node_id;
  return <AttachmentDialog title={preview ? intentLabels[preview.intent] : '核对路线变化'} closeLabel="关闭路线预览" className="learning-path-dialog learning-path-preview" onClose={() => { if (!busy) onClose(); }}><div className="learning-path-dialog__body">
    {loading && <p role="status">正在核对路线与当前学习…</p>}{error && <p role="alert">{error}</p>}
    {preview && <><h3>{preview.draft.title}</h3><ol className="learning-path-preview__nodes">{preview.draft.nodes.map(node => <li key={node.id}><strong>{node.title}</strong>{node.id === preview.draft.current_node_id && <span>当前位置</span>}{!!node.action_ids.length && <p>{node.action_ids.map(id => { const action = state.actions.find(item => item.id === id); return `${action?.title ?? '关联任务当前不可查看'}${action?.deleted || action?.status === 'cancelled' ? '（已删除）' : ''}`; }).join('、')}</p>}</li>)}</ol>
      {preview.affected_sessions.length > 0 ? <section className="learning-path-preview__impact"><h4>确认后暂停当前学习</h4><ul>{preview.affected_sessions.map(session => <li key={session.id}>{session.action_title}</li>)}</ul><p>已有学习现场、作答和帮助记录保留。</p></section> : <p>现有任务和学习记录保留。</p>}
      <CommitmentChanges changes={preview.commitment_changes} />
      <details><summary>旧恢复位置与保留记录</summary><p>{preview.checkpoint ? original?.nodes.find(node => node.id === preview.checkpoint!.node_id)?.title ?? '原阶段位置已保存' : '没有需要保留的旧学习位置。'}</p>{preview.checkpoint?.available === false && <p>原学习位置当前不可读取，可查看原任务记录或另选可用位置。</p>}{preview.checkpoint?.delegation_id && <p>原任务和学习记录保留。</p>}</details>
      {restoresDifferentNode && <p>这个阶段没有精确的旧对话位置。恢复后请明确选择关联任务，从当前可用任务继续。</p>}
      <p className="form-hint">确认后保存路线，新学习由你点击开始。</p>
    </>}
    {(stale || !preview && !loading) && <button className="button button--quiet" type="button" disabled={busy || loading} onClick={() => void read(true)}>重新读取并核对</button>}
  </div><div className="learning-path-dialog__footer"><button className="button button--quiet" type="button" disabled={busy} onClick={onClose}>取消</button><button className="button button--accent" type="button" disabled={!preview || busy || loading || closed || stale} onClick={() => void confirm()}>{busy ? '正在确认…' : preview?.intent === 'restore' ? '确认恢复' : preview?.intent === 'undo' ? '确认撤销' : preview?.intent === 'create' ? '确认采用' : '确认调整'}</button></div></AttachmentDialog>;
}

function PathTransferDialog({ planId, sourceTitle, value, view, closed, onClose, onRead, onRechecked, onConfirmed }: {
  planId: string; sourceTitle: string; value: { body: PathTransferInput; preview: PathTransferPreview }; view: LearningPathView; closed: boolean;
  onClose: () => void; onRead: () => Promise<LearningPathView>; onRechecked: (value: { body: PathTransferInput; preview: PathTransferPreview }) => void;
  onConfirmed: (result: PathTransferResult) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [stale, setStale] = useState(false);
  const attempt = useRef<Attempt>(null);
  async function confirm() {
    if (closed || busy || stale) return;
    const body = { ...value.body, review_key: value.preview.review_key };
    setBusy(true); setError('');
    try { const result = await confirmPathTransfer(planId, { ...body, request_key: keyFor(attempt, body) }); await onConfirmed(result); }
    catch (reason) { if (generationBusy(reason)) { setStale(true); setError(failure(reason)); } else if (isConflict(reason)) { setStale(true); setError('原计划、任务或当前学习已变化。输入已保留，请重新读取并核对。'); } else setError(failure(reason)); }
    finally { setBusy(false); }
  }
  async function recheck() {
    setBusy(true); setError('');
    try {
      const latest = await onRead();
      const body = { ...value.body, expected_revision: latest.revision, expected_organization_revision: latest.organization_revision };
      const preview = await previewPathTransfer(planId, body); onRechecked({ body, preview }); setStale(false); attempt.current = null;
    } catch (reason) { setError(failure(reason)); }
    finally { setBusy(false); }
  }
  const original = view.versions.find(version => version.id === view.adopted_version_id);
  const point = value.preview.checkpoint;
  return <AttachmentDialog title="转到新计划" closeLabel="关闭转向预览" className="learning-path-dialog learning-path-transfer-preview" onClose={() => { if (!busy) onClose(); }}><div className="learning-path-dialog__body">
    <dl className="learning-path-transfer-summary"><div><dt>原计划</dt><dd>{sourceTitle}</dd></div><div><dt>新计划</dt><dd>{value.preview.destination_title}<small>暂不关联目标</small></dd></div><div><dt>新的路线</dt><dd>{value.body.title}</dd></div></dl>
    <p>原任务、委托、产出与成果依据留在原计划。新计划沿用你选择的成果身份。</p>
    <ol className="learning-path-preview__nodes">{value.body.nodes.map(node => <li key={node.id}><strong>{node.title}</strong>{node.id === value.body.current_node_id && <span>新计划当前位置</span>}</li>)}</ol>
    {value.preview.affected_sessions.length > 0 ? <section className="learning-path-preview__impact"><h4>确认后暂停原计划当前学习</h4><ul>{value.preview.affected_sessions.map(session => <li key={session.id}>{session.action_title}</li>)}</ul><p>已有作答与帮助记录保留。</p></section> : <p>{value.preview.pause_original ? '原方向将暂停，记录与恢复位置保留。' : '原方向及当前学习保持。'}</p>}
    <CommitmentChanges changes={value.preview.commitment_changes ?? []} />
    <details><summary>原恢复位置</summary><p>{point ? original?.nodes.find(node => node.id === point.node_id)?.title ?? '原路线位置已保存' : '没有已有的学习位置。'}</p>{point?.available === false && <p>原对话位置当前不可读取，原任务记录仍可查看。</p>}</details>
    <p className="form-hint">确认后创建新计划，新学习由你点击开始。</p>
    {error && <p role="alert">{error}</p>}{stale && <button className="button button--quiet" type="button" disabled={busy} onClick={() => void recheck()}>重新读取并核对</button>}
  </div><div className="learning-path-dialog__footer"><button className="button button--quiet" type="button" disabled={busy} onClick={onClose}>取消</button><button className="button button--accent" type="button" disabled={busy || closed || stale} onClick={() => void confirm()}>{busy ? '正在确认…' : '确认新建并转向'}</button></div></AttachmentDialog>;
}

function PathContentPurge({ planId, version, revision, closed, retryNeeded, onChanged, onDialogChange }: {
  planId: string; version: LearningPathVersion; revision: number; closed: boolean; retryNeeded?: boolean;
  onChanged: (view: LearningPathView) => Promise<void>; onDialogChange: (open: boolean) => void;
}) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [report, setReport] = useState<PurgeReport | null>(null), [stale, setStale] = useState(false);
  const attempt = useRef<Attempt>(null), trigger = useRef<HTMLElement | null>(null);
  useEffect(() => { setReport(null); setError(''); setStale(false); attempt.current = null; }, [version.id]);
  useEffect(() => { setStale(false); attempt.current = null; }, [revision]);
  function dialog(value: boolean) { if (value) trigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setOpen(value); onDialogChange(value); if (!value) requestAnimationFrame(() => { if (trigger.current?.isConnected) trigger.current.focus({ preventScroll: true }); }); }
  async function read() {
    setBusy(true); setError('');
    try { setReport(await getLearningPathPurgeStatus(planId, version.id)); }
    catch (reason) { setError(failure(reason)); }
    finally { setBusy(false); }
  }
  async function clear() {
    if (busy || stale) return;
    setBusy(true); setError('');
    try { const next = await purgeLearningPathVersion(planId, version.id, revision, keyFor(attempt, { revision })); setReport(next.purge_report); dialog(false); await onChanged(next.path); }
    catch (reason) { if (isConflict(reason)) { setStale(true); setError('路线已变化，请关闭确认框后重新读取路径。'); } else setError(failure(reason)); }
    finally { setBusy(false); }
  }
  const retryAllowed = version.content_available || retryNeeded && report?.status !== 'complete' || report?.status === 'partial' || report?.status === 'pending';
  return <div className="learning-path-purge">{retryAllowed && <button className="text-button" type="button" disabled={busy || stale} onClick={() => dialog(true)}>{version.content_available ? '彻底清除路线内容' : '重试清除路线副本'}</button>}<button className="text-button" type="button" disabled={busy} onClick={() => void read()}>查看清除结果</button>{report && <div aria-label="路线清除结果"><p role="status">{report.status === 'complete' ? '路线内容及受管理副本已清除。' : report.status === 'not_requested' ? '尚未请求清除。' : '清除尚未完成，可重新打开确认框重试。'}</p>{report.files.some(file => file.status === 'failed') && <details><summary>清除详情</summary>{report.files.filter(file => file.status === 'failed').map((file, index) => <p key={index}>{file.name}{file.reason && ` · ${file.reason}`}</p>)}</details>}</div>}{error && !open && <p role="alert">{error}</p>}
    {open && <AttachmentDialog title="彻底清除路线内容？" className="learning-path-dialog learning-path-confirm" closeLabel="取消清除路线内容" onClose={() => { if (!busy) dialog(false); }}><div className="learning-path-dialog__body"><p>永久清除这个路线版本的名称、阶段名称、原因及明确衍生草案正文，无法撤销。任务、学习事实与成果依据保留。</p>{error && <p role="alert">{error}</p>}</div><div className="learning-path-dialog__footer"><button className="button button--quiet" type="button" disabled={busy} onClick={() => dialog(false)}>取消</button><button className="button button--danger" type="button" disabled={busy || stale} onClick={() => void clear()}>{busy ? '正在清除…' : '确认清除'}</button></div></AttachmentDialog>}
  </div>;
}
