import { useEffect, useMemo, useRef, useState } from 'react';
import { getOutcomeGraph, getOutcomeRelation, getReturnReview, revokeOutcomeRelation, type OutcomeGraphData, type OutcomeGraphNode, type OutcomeRelation, type OutcomeRelationDetail } from './api';
import LearningPageHeader from './LearningPageHeader';
import OutcomeGraphCanvas, { type GraphNodeDisplay } from './OutcomeGraphCanvas';
import { graphError, graphTime, OutcomeCreateDialog, relationLabels, RelationDialog, RelationSources, requestKey, stateLabels } from './OutcomeGraphForms';
import OutcomeSuggestions from './OutcomeSuggestions';
import OutcomeGraphPurge from './OutcomeGraphPurge';
import './styles/outcome-graph.css';

function location(key: string, value: string | null) {
  const url = new URL(window.location.href); if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
  window.history.replaceState(null, '', url);
}
function nodeLabels(node: OutcomeGraphNode): GraphNodeDisplay['labels'] {
  if (node.kind === 'composite') return [{ text: '整体实践仍待验证', tone: 'unknown' }];
  if (node.coverage.status === 'no_standard') return [{ text: '没有合格标准', tone: 'unknown' }];
  const dimensions = node.coverage.standards.filter(standard => standard.review_status === 'approved' && !standard.availability).flatMap(standard => standard.dimensions);
  const labels: GraphNodeDisplay['labels'] = [];
  if (dimensions.some(dimension => ['supported', 'partially_supported'].includes(dimension.state?.status ?? ''))) labels.push({ text: '已有支持', tone: 'supported' });
  if (dimensions.some(dimension => dimension.state?.status === 'contradicted')) labels.push({ text: '不同表现', tone: 'different' });
  if (dimensions.some(dimension => !dimension.state || ['awaiting_evidence', 'pending_review', 'insufficient_evidence'].includes(dimension.state.status))) labels.push({ text: '仍待判断', tone: 'unknown' });
  return labels.length ? labels : [{ text: '仍待判断', tone: 'unknown' }];
}

export default function OutcomeGraph({ onBack, onEvidence }: { onBack: () => void; onEvidence: (id: string) => void }) {
  const query = new URLSearchParams(window.location.search);
  const [data, setData] = useState<OutcomeGraphData | null>(null), [allData, setAllData] = useState<OutcomeGraphData | null>(null);
  const [plan, setPlan] = useState<string | null>(query.get('graph_plan'));
  const [currentPlan, setCurrentPlan] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(query.get('graph_node'));
  const [search, setSearch] = useState(''), [error, setError] = useState(''), [loading, setLoading] = useState(true);
  const [create, setCreate] = useState(false), [relation, setRelation] = useState<OutcomeRelation | 'new' | null>(null), [suggest, setSuggest] = useState(false);
  const [relationId, setRelationId] = useState<string | null>(null), [detail, setDetail] = useState<OutcomeRelationDetail | null>(null), [relationError, setRelationError] = useState('');
  const [revoke, setRevoke] = useState(false), [busy, setBusy] = useState(false);
  const revokeKey = useRef<string | null>(null);
  const requestSerial = useRef(0);
  const inspectorElement = useRef<HTMLElement>(null);
  useEffect(() => {
    let active = true;
    Promise.all([getOutcomeGraph(), getReturnReview().catch(() => null)]).then(async ([all, position]) => {
      const defaultPlan = position?.position.plan_id ?? null;
      const chosen = query.has('graph_plan') ? query.get('graph_plan') : defaultPlan;
      const filtered = chosen && chosen !== 'all' ? await getOutcomeGraph(chosen) : all;
      if (!active) return;
      setCurrentPlan(defaultPlan); setAllData(all); setPlan(chosen ?? 'all'); setData(filtered); setLoading(false);
      location('graph_plan', chosen ?? 'all');
    }).catch(reason => { if (active) { setError(graphError(reason)); setLoading(false); } });
    return () => { active = false; requestSerial.current += 1; };
  }, []);
  async function refresh(chosen = plan, select?: string) {
    const serial = ++requestSerial.current;
    setError('');
    const all = await getOutcomeGraph();
    const filtered = chosen && chosen !== 'all' ? await getOutcomeGraph(chosen) : all;
    if (serial !== requestSerial.current) return;
    setAllData(all); setData(filtered); setLoading(false);
    if (select) { setSelectedId(select); location('graph_node', select); }
  }
  async function filter(value: string) {
    setPlan(value); location('graph_plan', value); setLoading(true); setRelationId(null); setDetail(null);
    try { await refresh(value); } catch (reason) { setError(graphError(reason)); setLoading(false); }
  }
  useEffect(() => {
    if (!relationId) { setDetail(null); return; }
    let active = true; setDetail(null); setRelationError(''); setRevoke(false); revokeKey.current = null;
    getOutcomeRelation(relationId).then(value => { if (active) setDetail(value); }).catch(reason => { if (active) setRelationError(graphError(reason)); });
    return () => { active = false; };
  }, [relationId]);
  const nodes = useMemo(() => (data?.nodes ?? []).filter(node => !search || `${node.object_description} ${node.behavior}`.toLowerCase().includes(search.toLowerCase())), [data, search]);
  const visibleIds = new Set(nodes.map(node => node.id));
  const activeRelations = (data?.relations ?? []).filter(item => item.status === 'active');
  const edges = activeRelations.filter(item => visibleIds.has(item.source_outcome_id) && visibleIds.has(item.target_outcome_id));
  const selected = nodes.find(node => node.id === selectedId);
  const allNodes = allData?.nodes ?? [];
  const nodeTitle = (id: string) => allNodes.find(node => node.id === id)?.object_description ?? '成果当前不可查看';
  function focusDetails() { if (window.matchMedia('(max-width: 1050px)').matches) requestAnimationFrame(() => inspectorElement.current?.scrollIntoView({ block: 'start' })); }
  function select(id: string) { setSelectedId(id); location('graph_node', id); setRelationId(null); focusDetails(); }
  async function revokeRelation() {
    if (!detail || busy) return;
    if (!revokeKey.current) revokeKey.current = requestKey();
    setBusy(true); setRelationError('');
    try { await revokeOutcomeRelation(detail.id, detail.revision, revokeKey.current); setDetail(await getOutcomeRelation(detail.id)); setRevoke(false); await refresh(); }
    catch (reason) { setRelationError(graphError(reason)); }
    finally { setBusy(false); }
  }
  return <section className="learning-page outcome-graph" aria-label="成果图">
    <LearningPageHeader title="成果图" description="组织希望形成的能力，查看各项成果的依据。"><button className="button button--quiet" type="button" onClick={onBack}>返回学习记录</button></LearningPageHeader>
    <div className="outcome-graph__toolbar">
      <label>计划范围<select value={plan ?? 'all'} onChange={event => void filter(event.target.value)} disabled={loading}><option value="all">全部成果</option>{allData?.plans.map(item => <option key={item.id} value={item.id}>{item.title}{item.id === currentPlan ? ' · 当前计划' : ''}</option>)}</select></label>
      <label>查找成果<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索名称或能力描述" /></label>
      <div className="outcome-graph__actions"><button className="button" type="button" onClick={() => setCreate(true)} disabled={!allData}>新建成果</button><button className="button button--quiet" type="button" onClick={() => setSuggest(true)} disabled={allNodes.length < 2}>AI 关系建议</button></div>
    </div>
    {error && <div role="alert"><p>{error}</p><button className="text-button" type="button" onClick={() => { setLoading(true); void refresh().catch(reason => { setError(graphError(reason)); setLoading(false); }); }}>重新读取成果图</button></div>}
    {loading && <p role="status">正在读取成果图…</p>}
    {!loading && !error && <div className="outcome-graph__layout">
      {nodes.length ? <OutcomeGraphCanvas nodes={nodes.map(node => ({ id: node.id, title: node.object_description, behavior: node.behavior, kind: node.kind, labels: nodeLabels(node) }))} edges={edges.map(edge => ({ id: edge.id, source: edge.source_outcome_id, target: edge.target_outcome_id, kind: edge.relation_type, label: relationLabels[edge.relation_type] }))} selected={selectedId} onSelect={select} onRelation={id => { setRelationId(id); focusDetails(); }} /> : <div className="outcome-graph__empty"><h3>{search ? '没有找到匹配的成果' : '这个范围还没有成果'}</h3><p className="outcome-graph__muted">{search ? '试试其他名称，或清空搜索。' : '可以新建综合成果，再关联已有成果。'}</p>{plan !== 'all' && <button className="button button--quiet" type="button" onClick={() => void filter('all')}>查看全部成果</button>}</div>}
      <aside ref={inspectorElement} className="outcome-graph__inspector" aria-label={relationId ? '关系详情' : '成果详情'}>
        {relationId ? <>
          <button className="text-button" type="button" onClick={() => setRelationId(null)}>返回成果详情</button>
          {relationError && <div role="alert"><p>{relationError}</p><button className="text-button" type="button" onClick={() => void getOutcomeRelation(relationId).then(value => { setDetail(value); setRelationError(''); setRevoke(false); revokeKey.current = null; }).catch(reason => setRelationError(graphError(reason)))}>重新读取关系</button></div>}
          {!detail && !relationError && <p role="status">正在读取关系…</p>}
          {detail && <>
            <h3>{nodeTitle(detail.source_outcome_id)} {relationLabels[detail.relation_type]} {nodeTitle(detail.target_outcome_id)}</h3>
            <p className="outcome-graph__muted">{detail.status === 'active' ? '当前关系' : detail.status === 'revoked' ? '已撤销' : '说明已清除'} · {detail.source_kind === 'ai_accepted' ? 'AI 建议 · 本人采用' : '本人添加'}</p>
            {!detail.available ? <p>来源或说明当前不可查看。</p> : <>{detail.rationale && <p>{detail.rationale}</p>}{detail.context_key && <p>情境：{detail.context_key}</p>}<details><summary>来源与不确定处</summary>{detail.uncertainty && <p>{detail.uncertainty}</p>}<RelationSources relation={detail} nodes={allNodes} onEvidence={onEvidence} /></details></>}
            {detail.status === 'active' && <div className="outcome-graph__actions"><button className="button" type="button" disabled={busy} onClick={() => setRelation(detail)}>调整关系</button><button className="text-button" type="button" disabled={busy} onClick={() => setRevoke(true)}>撤销关系</button></div>}
            {revoke && <div className="outcome-graph__relations"><p>撤销这项关系后，成果和原始依据仍保留。</p><div className="outcome-graph__actions"><button className="button" type="button" disabled={busy} onClick={() => void revokeRelation()}>{busy ? '正在撤销…' : '确认撤销'}</button><button className="text-button" type="button" disabled={busy} onClick={() => setRevoke(false)}>取消</button></div></div>}
            <details><summary>关系历史（{detail.history.length}）</summary><div className="outcome-graph__history">{detail.history.map((item, index) => <article key={item.revision ?? index}><small>{graphTime(item.updated_at ?? item.created_at)} · {item.status === 'active' ? '保存关系' : item.status === 'revoked' ? '撤销关系' : '清除说明'}</small><p>{nodeTitle(item.source_outcome_id)} {relationLabels[item.relation_type]} {nodeTitle(item.target_outcome_id)}</p>{item.available ? <>{item.context_key && <p>情境：{item.context_key}</p>}{item.rationale && <p>{item.rationale}</p>}{item.uncertainty && <p>{item.uncertainty}</p>}<RelationSources relation={item} nodes={allNodes} onEvidence={onEvidence} /></> : <p>内容当前不可查看。</p>}</article>)}</div></details>
            <details><summary>更多操作</summary><OutcomeGraphPurge key={detail.id} kind="relation" id={detail.id} revision={detail.revision} purged={detail.status === 'purged'} onPurged={async () => { setDetail(await getOutcomeRelation(detail.id)); await refresh(); }} /></details>
          </>}
        </> : selected ? <>
          <small>{selected.kind === 'composite' ? '综合成果' : '可验证成果'}</small><h2>{selected.object_description}</h2><p>{selected.behavior}</p>
          {selected.context_key && <p className="outcome-graph__muted">情境：{selected.context_key}</p>}
          {selected.kind === 'composite' && <p>整体实践仍待验证。组成成果的依据分别展示。</p>}
          <div className="outcome-graph__actions"><button className="button" type="button" onClick={() => onEvidence(selected.id)}>查看原始依据</button><button className="button button--quiet" type="button" onClick={() => setRelation('new')}>添加关系</button></div>
          {(selected.kind !== 'composite' || selected.coverage.standards.length > 0) && <section className="outcome-graph__standards" aria-label="按标准查看依据"><h3>依据覆盖</h3>
            {selected.coverage.status === 'no_standard' && <p>没有合格标准。已有记录和反馈可在原始依据中查看。</p>}
            {selected.coverage.standards.filter(standard => standard.review_status === 'approved' && !standard.availability).map(standard => <article key={standard.id}><strong>{standard.package_title ?? '达成标准'} · v{standard.version}</strong>{standard.context_key && <small>{standard.context_key}</small>}<ul>{standard.dimensions.map(dimension => <li key={dimension.id}>{dimension.label} · {dimension.state ? stateLabels[dimension.state.status] ?? '仍待判断' : '尚无依据'}</li>)}</ul><details><summary>标准来源与范围</summary><p>已批准{standard.package_title ? ` · ${standard.package_title}` : ''}{standard.package_version !== null ? ` · v${standard.package_version}` : ''}</p>{standard.sources.map((source, index) => <p key={index}>{source}</p>)}{standard.scope && <p>适用范围：{standard.scope}</p>}{standard.limitations.map((limitation, index) => <p key={index}>{limitation}</p>)}</details></article>)}
            {selected.kind !== 'composite' && selected.coverage.status === 'unknown' && <p>已有合格标准，尚无足够依据。</p>}
            {!!selected.coverage.standards.filter(standard => standard.review_status !== 'approved' || standard.availability).length && <details><summary>其他标准版本</summary>{selected.coverage.standards.filter(standard => standard.review_status !== 'approved' || standard.availability).map(standard => <p key={standard.id}>{standard.package_title ?? '达成标准'} · v{standard.version} · {standard.review_status === 'approved' ? '已批准' : '候选'}{standard.availability ? ` · ${standard.availability === 'retired' ? '已停用' : '已失效'}` : ''}</p>)}</details>}
          </section>}
          <section className="outcome-graph__relations" aria-label="这个成果的关系"><h3>关联成果</h3>{(allData?.relations ?? []).filter(item => item.source_outcome_id === selected.id || item.target_outcome_id === selected.id).map(item => <article key={item.id}><button className="text-button" type="button" onClick={() => setRelationId(item.id)}>{nodeTitle(item.source_outcome_id)} {relationLabels[item.relation_type]} {nodeTitle(item.target_outcome_id)}{item.status === 'active' ? '' : item.status === 'revoked' ? ' · 已撤销' : ' · 说明已清除'}</button></article>)}</section>
          {!!selected.task_links.length && <details><summary>关联任务（{selected.task_links.length}）</summary>{selected.task_links.map(item => <p key={`${item.action_id}:${item.plan_id}`}>{item.action_title}</p>)}</details>}
          {!!selected.evidence_links.length && <details><summary>已有证据引用（{selected.evidence_links.length}）</summary><p>这些依据仍属于原来的成果和标准。</p><button className="text-button" type="button" onClick={() => onEvidence(selected.id)}>查看作答、产出与证据判断</button></details>}
        </> : <><h3>选一个成果</h3><p className="outcome-graph__muted">点开节点查看依据和关联；点开关系查看说明与历史。</p></>}
      </aside>
    </div>}
    {create && <OutcomeCreateDialog onClose={() => setCreate(false)} onCreated={async id => { setPlan('all'); location('graph_plan', 'all'); await refresh('all', id); setRelationId(null); setCreate(false); }} />}
    {relation && <RelationDialog nodes={allNodes} currentPlanId={currentPlan} initial={relation === 'new' ? undefined : relation} initialSource={selectedId ?? undefined} onClose={() => setRelation(null)} onSaved={async () => { await refresh(); if (detail && relation !== 'new') setDetail(await getOutcomeRelation(detail.id)); setRelation(null); }} />}
    {suggest && <OutcomeSuggestions nodes={allNodes} runs={allData?.runs ?? []} currentPlanId={plan === 'all' ? null : plan} onClose={() => setSuggest(false)} onUpdated={() => refresh()} onEvidence={id => { setSuggest(false); onEvidence(id); }} />}
  </section>;
}
