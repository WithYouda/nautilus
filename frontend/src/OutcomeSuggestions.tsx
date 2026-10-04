import { useEffect, useRef, useState } from 'react';
import { cancelOutcomeSuggestions, createOutcomeSuggestions, getOutcomeSuggestions, reviewOutcomeSuggestion, type OutcomeGraphNode, type OutcomeRelationCandidate, type OutcomeRelationFields, type OutcomeSuggestionRun } from './api';
import { AttachmentDialog } from './AttachmentReview';
import { graphError, graphTime, relationLabels, RelationDialog, RelationSources, requestKey } from './OutcomeGraphForms';
import OutcomeGraphPurge from './OutcomeGraphPurge';

const runLabels = { running: '正在分析', succeeded: '建议已保存', failed: '分析失败', canceled: '已取消', purged: '内容已清除' };
const candidateLabels = { pending: '待确认', accepted: '已采用', rejected: '已拒绝', purged: '内容已清除' };
export default function OutcomeSuggestions({ nodes, runs, currentPlanId, onClose, onUpdated, onEvidence }: {
  nodes: OutcomeGraphNode[]; runs: OutcomeSuggestionRun[]; currentPlanId: string | null;
  onClose: () => void; onUpdated: () => Promise<void>; onEvidence: (id: string) => void;
}) {
  const [selected, setSelected] = useState<string[]>([]), [search, setSearch] = useState(''), [crossPlan, setCrossPlan] = useState(!currentPlanId);
  const [run, setRun] = useState<OutcomeSuggestionRun | null>(() => runs.find(item => item.status === 'running') ?? runs[0] ?? null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [editing, setEditing] = useState<OutcomeRelationCandidate | null>(null);
  const [reviewError, setReviewError] = useState<{ id: string; text: string } | null>(null);
  const [pollEpoch, setPollEpoch] = useState(0), [purgeOpen, setPurgeOpen] = useState(false);
  const startAttempt = useRef<{ ids: string; key: string } | null>(null);
  const reviewKeys = useRef(new Map<string, string>());
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    if (!run || run.status !== 'running') return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await getOutcomeSuggestions(run.id);
        if (disposed) return;
        setRun(value); setError('');
        if (value.status === 'running') timer = setTimeout(() => void poll(), 750);
        else await onUpdated();
      } catch (reason) { if (!disposed) setError(graphError(reason)); }
    };
    timer = setTimeout(() => void poll(), 500);
    return () => { disposed = true; clearTimeout(timer); };
  }, [run?.id, run?.status, pollEpoch]);
  const choices = nodes.filter(node => (crossPlan || node.plan_ids.includes(currentPlanId!)) && (!search || `${node.object_description} ${node.behavior}`.toLowerCase().includes(search.toLowerCase())));
  const frozenNodes = nodes.filter(node => run?.outcome_ids.includes(node.id));
  async function load(id: string) {
    setBusy(true); setError('');
    try { const value = await getOutcomeSuggestions(id); setRun(value); setSelected(value.outcome_ids); setPollEpoch(value => value + 1); }
    catch (reason) { setError(graphError(reason)); } finally { setBusy(false); }
  }
  async function start(retry = false) {
    const ids = retry && run ? run.outcome_ids : selected;
    if (busy || ids.length < 2 || ids.length > 30) return;
    const serialized = JSON.stringify(ids);
    if (retry || startAttempt.current?.ids !== serialized) startAttempt.current = { ids: serialized, key: requestKey() };
    setBusy(true); setError('');
    try { const value = await createOutcomeSuggestions(ids, startAttempt.current!.key); if (!alive.current) return; setRun(value); setSelected(ids); await onUpdated(); startAttempt.current = null; }
    catch (reason) { if (alive.current) setError(graphError(reason)); } finally { if (alive.current) setBusy(false); }
  }
  async function cancel() {
    if (!run || busy) return;
    setBusy(true); setError('');
    try { setRun(await cancelOutcomeSuggestions(run.id, run.revision, requestKey())); await onUpdated(); }
    catch (reason) { setError(graphError(reason)); } finally { setBusy(false); }
  }
  async function review(candidate: OutcomeRelationCandidate, decision: 'accept' | 'reject', relation?: OutcomeRelationFields, key?: string) {
    if (!run) return;
    const action = `${candidate.id}:${candidate.revision}:${decision}`;
    if (!reviewKeys.current.has(action)) reviewKeys.current.set(action, requestKey());
    await reviewOutcomeSuggestion(run.id, candidate, decision, key ?? reviewKeys.current.get(action)!, relation);
    setRun(await getOutcomeSuggestions(run.id)); await onUpdated(); setReviewError(null);
  }
  async function decide(candidate: OutcomeRelationCandidate, decision: 'accept' | 'reject') {
    if (busy) return;
    setBusy(true); setReviewError(null);
    try { await review(candidate, decision); }
    catch (reason) { setReviewError({ id: candidate.id, text: graphError(reason) }); }
    finally { setBusy(false); }
  }
  if (editing && run) return <RelationDialog nodes={frozenNodes} currentPlanId={null} initial={editing} onClose={() => setEditing(null)} onAdopt={(fields, key) => review(editing, 'accept', fields, key)} onSaved={async () => { setEditing(null); }} />;
  return <AttachmentDialog title="AI 关系建议" className="outcome-graph__dialog" closeLabel="关闭 AI 关系建议" suspended={purgeOpen} onClose={() => { if (!busy && !purgeOpen) onClose(); }}>
    <div className="outcome-graph__dialog-body">
      <p className="outcome-graph__muted">只分析你选中的成果声明；逐项确认后才加入成果图。</p>
      <details open={!run}><summary>选择要分析的成果{selected.length ? `（${selected.length}）` : ''}</summary>
        <label>查找成果<input type="search" value={search} onChange={event => setSearch(event.target.value)} /></label>
        {currentPlanId && <label className="outcome-graph__cross-plan"><input type="checkbox" checked={crossPlan} onChange={event => setCrossPlan(event.target.checked)} />包含其他计划的成果</label>}
        <div className="outcome-graph__picker">{choices.map(node => <label key={node.id}><input type="checkbox" checked={selected.includes(node.id)} disabled={busy || run?.status === 'running' || (!selected.includes(node.id) && selected.length >= 30)} onChange={event => setSelected(ids => event.target.checked ? [...ids, node.id] : ids.filter(id => id !== node.id))} /><span><strong>{node.object_description}</strong><small>{node.behavior}</small></span></label>)}</div>
        <button className="button button--accent" type="button" disabled={busy || run?.status === 'running' || selected.length < 2 || selected.length > 30} onClick={() => void start()}>{busy ? '正在提交…' : '分析选中成果'}</button>
      </details>
      {runs.length > 1 && <details><summary>先前的分析</summary><label>选择分析记录<select value={run?.id ?? ''} disabled={busy} onChange={event => void load(event.target.value)}>{runs.map(item => <option value={item.id} key={item.id}>{graphTime(item.created_at)} · {runLabels[item.status]}</option>)}</select></label></details>}
      {error && <div role="alert"><p>{error}</p>{run && <button className="text-button" type="button" disabled={busy} onClick={() => void load(run.id)}>重新读取分析</button>}</div>}
      {run && <section aria-label="关系建议结果" className="outcome-graph__candidates">
        <p role="status">{runLabels[run.status]} · {run.outcome_ids.length} 个成果</p>
        {run.status === 'running' && <button className="button button--quiet" type="button" disabled={busy} onClick={() => void cancel()}>取消分析</button>}
        {['failed', 'canceled'].includes(run.status) && <><p>{run.reason ? graphError(new Error(run.reason)) : '这次分析没有生成建议。'}</p><button className="button" type="button" disabled={busy} onClick={() => void start(true)}>重新分析这组成果</button></>}
        {run.status === 'succeeded' && !run.candidates.length && <p>这组成果暂时没有可采用的关系建议。你仍可以手动添加关系。</p>}
        {run.candidates.map(candidate => <article className="outcome-graph__candidate" key={candidate.id} aria-label={`建议：${nodes.find(node => node.id === candidate.source_outcome_id)?.object_description ?? '成果'} ${relationLabels[candidate.relation_type]}`}>
          <small>{candidateLabels[candidate.status]}</small><h3>{nodes.find(node => node.id === candidate.source_outcome_id)?.object_description ?? '来源成果'} {relationLabels[candidate.relation_type]} {nodes.find(node => node.id === candidate.target_outcome_id)?.object_description ?? '目标成果'}</h3>
          {!candidate.available ? <p>来源当前不可查看，无法采用这项建议。</p> : <>
            {candidate.rationale && <p>{candidate.rationale}</p>}
            <details><summary>情境、来源与不确定处</summary>{candidate.context_key && <p>情境：{candidate.context_key}</p>}{candidate.uncertainty && <p>{candidate.uncertainty}</p>}<RelationSources relation={candidate} nodes={nodes} onEvidence={onEvidence} /></details>
          </>}
          {candidate.status === 'pending' && <div className="outcome-graph__actions"><button className="button" type="button" disabled={busy || !candidate.available} onClick={() => void decide(candidate, 'accept')}>采用</button><button className="button button--quiet" type="button" disabled={busy || !candidate.available} onClick={() => setEditing(candidate)}>调整后采用</button><button className="text-button" type="button" disabled={busy} onClick={() => void decide(candidate, 'reject')}>拒绝</button></div>}
          {reviewError?.id === candidate.id && <div role="alert"><p>{reviewError.text}</p><button className="text-button" type="button" onClick={() => void load(run.id)}>重新读取建议</button></div>}
        </article>)}
        <details><summary>更多操作</summary><OutcomeGraphPurge key={run.id} kind="run" id={run.id} revision={run.revision} purged={run.status === 'purged'} onDialogChange={setPurgeOpen} onPurged={async () => { setRun(await getOutcomeSuggestions(run.id)); await onUpdated(); }} /></details>
      </section>}
    </div>
  </AttachmentDialog>;
}
