import { useRef, useState, type FormEvent } from 'react';
import { ApiError, createGraphOutcome, createOutcomeRelation, getLearningArtifact, getOutcomeRelation, reviseOutcomeRelation, type OutcomeGraphNode, type OutcomeRelationFields, type OutcomeRelationReadFields, type OutcomeRelationType } from './api';
import { AttachmentDialog } from './AttachmentReview';
import LearningMarkdown from './LearningMarkdown';

export const relationLabels: Record<OutcomeRelationType, string> = { contains: '包含', prerequisite: '是前置', equivalent: '等价', overlap: '重叠' };
export const stateLabels: Record<string, string> = { awaiting_evidence: '尚无依据', pending_review: '等待复核', insufficient_evidence: '依据不足', partially_supported: '部分支持', supported: '已有支持', contradicted: '不同表现' };
export const requestKey = () => crypto.randomUUID?.() ?? `graph-${Date.now()}-${Math.random()}`;
export const graphTime = (value: string) => new Date(value).toLocaleString();
export function graphError(reason: unknown): string {
  if (reason instanceof ApiError && reason.status === 409) {
    const labels: Record<string, string> = { version_conflict: '这项关系已在其他页面更新。请重新读取后再保存。', duplicate_relation: '这两个成果已有相同关系，请查看已有关系。', relation_cycle: '这项关系会形成循环，请调整两个成果或关系方向。', idempotency_conflict: '这次保存的内容发生了变化，请重新尝试。', relation_conflict: '这两个成果已有不相容的关系，请先调整已有关系。' };
    return labels[reason.kind] ?? reason.message;
  }
  const labels: Record<string, string> = { contains_requires_composite: '包含关系的起点需要是综合成果。', self_relation: '请选择两个不同的成果。', source_unavailable: '引用的来源当前不可查看，请重新选择依据。', provider_not_configured: '请先在设置中配置可用的 AI。', no_provider: '请先在设置中配置可用的 AI。', generation_failed: 'AI 暂时无法生成关系建议，请重试或手动关联。', interrupted: '上次分析被中断，请重新分析。', user_canceled: '这次分析已取消。' };
  return reason instanceof Error ? labels[reason.message] ?? reason.message : '暂时无法完成，请重试。';
}
export function OutcomeCreateDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => Promise<void> }) {
  const [kind, setKind] = useState<'composite' | 'atomic'>('composite');
  const [object, setObject] = useState(''), [behavior, setBehavior] = useState(''), [context, setContext] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const attempt = useRef<{ body: string; key: string } | null>(null);
  async function save(event: FormEvent) {
    event.preventDefault(); if (busy) return;
    const payload = { kind, object_description: object.trim(), behavior: behavior.trim(), context_key: context.trim() || '个人学习' };
    const body = JSON.stringify(payload);
    if (attempt.current?.body !== body) attempt.current = { body, key: requestKey() };
    setBusy(true); setError('');
    try { const result = await createGraphOutcome({ ...payload, request_key: attempt.current.key }); await onCreated(result.id); }
    catch (reason) { setError(graphError(reason)); }
    finally { setBusy(false); }
  }
  return <AttachmentDialog title="新建成果" className="outcome-graph__dialog" closeLabel="关闭新建成果" onClose={() => { if (!busy) onClose(); }}>
    <form onSubmit={event => void save(event)}>
      <label>成果类型<select value={kind} onChange={event => setKind(event.target.value as typeof kind)} disabled={busy}><option value="composite">综合成果</option><option value="atomic">可验证成果</option></select></label>
      <label>关于什么<input value={object} onChange={event => setObject(event.target.value)} maxLength={500} required disabled={busy} placeholder="例如：独立完成一个数据分析项目" /></label>
      <label>希望能够做什么<textarea value={behavior} onChange={event => setBehavior(event.target.value)} maxLength={500} required disabled={busy} placeholder={kind === 'composite' ? '描述整体结果，之后可以关联组成成果' : '写出可以单独观察的行为'} /></label>
      <details><summary>适用情境</summary><label>在哪些情况下<input value={context} onChange={event => setContext(event.target.value)} maxLength={200} disabled={busy} placeholder="例如：使用 Python 分析公开数据" /></label></details>
      {error && <p role="alert">{error}</p>}
      <div className="outcome-graph__actions"><button className="button button--quiet" type="button" onClick={onClose} disabled={busy}>取消</button><button className="button button--accent" type="submit" disabled={busy || !object.trim() || !behavior.trim()}>{busy ? '正在保存…' : '创建成果'}</button></div>
    </form>
  </AttachmentDialog>;
}

export function RelationDialog({ nodes, currentPlanId, initial, initialSource, onClose, onSaved, onAdopt }: {
  nodes: OutcomeGraphNode[]; currentPlanId: string | null; initial?: OutcomeRelationReadFields & { id?: string; revision?: number }; initialSource?: string;
  onClose: () => void; onSaved: () => Promise<void>; onAdopt?: (fields: OutcomeRelationFields, key: string) => Promise<void>;
}) {
  const [source, setSource] = useState(initial?.source_outcome_id ?? initialSource ?? '');
  const [target, setTarget] = useState(initial?.target_outcome_id ?? '');
  const [kind, setKind] = useState<OutcomeRelationType>(initial?.relation_type ?? (nodes.find(node => node.id === initialSource)?.kind === 'atomic' ? 'prerequisite' : 'contains'));
  const [context, setContext] = useState(initial?.context_key ?? ''), [rationale, setRationale] = useState(initial?.rationale ?? ''), [uncertainty, setUncertainty] = useState(initial?.uncertainty ?? '');
  const [crossPlan, setCrossPlan] = useState(!currentPlanId || Boolean(initial)), [search, setSearch] = useState(''), [url, setUrl] = useState('');
  const [supplement, setSupplement] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [stale, setStale] = useState(false);
  const [revision, setRevision] = useState(initial?.revision);
  const [sourceRefs, setSourceRefs] = useState(initial?.source_refs ?? []);
  const attempt = useRef<{ body: string; key: string } | null>(null);
  const choices = nodes.filter(node => (crossPlan || node.plan_ids.includes(currentPlanId!) || node.id === source || node.id === target) && (!search || `${node.object_description} ${node.behavior}`.toLowerCase().includes(search.toLowerCase())));
  const sourceOptions = choices.filter(node => kind !== 'contains' || node.kind === 'composite');
  const selectedNodes = nodes.filter(node => node.id === source || node.id === target);
  const supplements = selectedNodes.flatMap(node => [
    ...node.coverage.standards.map(standard => ({ key: `criterion:${standard.id}`, label: `${node.object_description} · ${standard.package_title ?? '达成标准'} v${standard.version}`, ref: { kind: 'criterion' as const, id: standard.id, version: standard.version } })),
    ...node.evidence_links.filter(link => link.available).map(link => ({ key: `artifact:${link.artifact_id}:${link.content_version}`, label: `${node.object_description} · 原始依据 v${link.content_version}`, ref: { kind: 'artifact' as const, id: link.artifact_id, version: link.content_version } })),
  ]).filter((item, index, all) => all.findIndex(other => other.key === item.key) === index);
  async function save(event: FormEvent) {
    event.preventDefault(); if (busy || stale) return;
    const extra = supplements.find(item => item.key === supplement)?.ref;
    const fields: OutcomeRelationFields = { source_outcome_id: source, target_outcome_id: target, relation_type: kind, context_key: context.trim() || '个人学习', rationale: rationale.trim(), uncertainty: uncertainty.trim(), source_refs: [{ kind: 'outcome', id: source }, { kind: 'outcome', id: target }, ...sourceRefs.filter(ref => ref.kind !== 'outcome'), ...(extra ? [extra] : []), ...(url.trim() ? [{ kind: 'external' as const, url: url.trim() }] : [])] };
    const body = JSON.stringify({ ...fields, revision });
    if (attempt.current?.body !== body) attempt.current = { body, key: requestKey() };
    setBusy(true); setError('');
    try {
      if (onAdopt) await onAdopt(fields, attempt.current.key);
      else if (initial?.id && revision !== undefined) await reviseOutcomeRelation(initial.id, { ...fields, expected_revision: revision, request_key: attempt.current.key });
      else await createOutcomeRelation({ ...fields, request_key: attempt.current.key });
      await onSaved();
    } catch (reason) { setError(graphError(reason)); if (reason instanceof ApiError && reason.status === 409 && reason.kind === 'version_conflict') setStale(true); }
    finally { setBusy(false); }
  }
  async function reread() {
    if (!initial?.id) return;
    setBusy(true);
    try { const latest = await getOutcomeRelation(initial.id); if (latest.status !== 'active') { setError('这项关系已撤销或清除，请关闭后查看历史。'); return; } setRevision(latest.revision); setSource(latest.source_outcome_id); setTarget(latest.target_outcome_id); setKind(latest.relation_type); setContext(latest.context_key ?? ''); setRationale(latest.rationale ?? ''); setUncertainty(latest.uncertainty ?? ''); setSourceRefs(latest.source_refs); setStale(false); setError(''); attempt.current = null; }
    catch (reason) { setError(graphError(reason)); } finally { setBusy(false); }
  }
  return <AttachmentDialog title={onAdopt ? '调整并采用建议' : initial?.id ? '调整关系' : '添加关系'} className="outcome-graph__dialog" closeLabel="关闭关系编辑" onClose={() => { if (!busy) onClose(); }}>
    <form onSubmit={event => void save(event)}>
      <label>关系<select value={kind} onChange={event => { setKind(event.target.value as OutcomeRelationType); if (event.target.value === 'contains' && nodes.find(node => node.id === source)?.kind !== 'composite') setSource(''); }} disabled={busy}>{Object.entries(relationLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>查找成果<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索名称或能力描述" disabled={busy} /></label>
      {currentPlanId && <label className="outcome-graph__cross-plan"><input type="checkbox" checked={crossPlan} onChange={event => setCrossPlan(event.target.checked)} disabled={busy} />包含其他计划的成果</label>}
      <label>{kind === 'contains' ? '综合成果' : kind === 'prerequisite' ? '前置成果' : '第一个成果'}<select value={source} onChange={event => setSource(event.target.value)} required disabled={busy}><option value="">请选择成果</option>{sourceOptions.map(node => <option key={node.id} value={node.id}>{node.object_description}</option>)}</select></label>
      <label>{kind === 'contains' ? '组成成果' : kind === 'prerequisite' ? '后续成果' : '第二个成果'}<select value={target} onChange={event => setTarget(event.target.value)} required disabled={busy}><option value="">请选择成果</option>{choices.filter(node => node.id !== source).map(node => <option key={node.id} value={node.id}>{node.object_description}</option>)}</select></label>
      {kind === 'prerequisite' && <p className="outcome-graph__muted">用于说明你的学习组织，不会改变任务顺序。</p>}
      <details open={Boolean(initial?.rationale || initial?.context_key)}><summary>情境、说明与来源</summary>
        <label>适用情境<input value={context} onChange={event => setContext(event.target.value)} maxLength={200} disabled={busy} /></label>
        <label>为什么关联<textarea value={rationale} onChange={event => setRationale(event.target.value)} disabled={busy} /></label>
        <label>仍有哪些不确定<textarea value={uncertainty} onChange={event => setUncertainty(event.target.value)} disabled={busy} /></label>
        {!!supplements.length && <label>补充依据<select value={supplement} onChange={event => setSupplement(event.target.value)} disabled={busy}><option value="">只引用所选成果声明</option>{supplements.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>}
        <label>外部来源链接<input type="url" value={url} onChange={event => setUrl(event.target.value)} disabled={busy} placeholder="可选，保存你提供的链接" /></label>
      </details>
      {error && <p role="alert">{error}</p>}{stale && <button className="button" type="button" onClick={() => void reread()} disabled={busy}>重新读取关系</button>}
      <div className="outcome-graph__actions"><button className="button button--quiet" type="button" onClick={onClose} disabled={busy}>取消</button><button className="button button--accent" type="submit" disabled={busy || stale || !source || !target || source === target}>{busy ? '正在保存…' : onAdopt ? '确认采用' : '保存关系'}</button></div>
    </form>
  </AttachmentDialog>;
}

export function RelationSources({ relation, nodes, onEvidence }: { relation: OutcomeRelationReadFields; nodes: OutcomeGraphNode[]; onEvidence: (id: string) => void }) {
  const [artifact, setArtifact] = useState<{ id: string; version: number; content: string | null } | null>(null), [error, setError] = useState(''), [loading, setLoading] = useState(false);
  async function readArtifact(id: string, version: number) {
    setLoading(true); setError(''); setArtifact(null);
    try { const value = await getLearningArtifact(id, version); setArtifact({ id, version, content: value.purged_at ? null : value.content }); }
    catch (reason) { setError(graphError(reason)); } finally { setLoading(false); }
  }
  return <>{relation.source_refs.map((ref, index) => {
    const standardNode = ref.kind === 'criterion' ? nodes.find(node => node.coverage.standards.some(standard => standard.id === ref.id)) : null;
    return <p key={index}>{ref.available === false ? '来源当前不可查看' : ref.kind === 'external' ? <a href={ref.url} target="_blank" rel="noreferrer">{ref.url}</a> : ref.kind === 'outcome' ? <button type="button" className="text-button" onClick={() => { if (ref.id) onEvidence(ref.id); }}>{nodes.find(node => node.id === ref.id)?.object_description ?? '关联成果'} · 成果声明</button> : ref.kind === 'artifact' && ref.id && ref.version ? <button className="text-button" type="button" onClick={() => void readArtifact(ref.id!, ref.version!)}>查看原始依据 · v{ref.version}</button> : standardNode ? <button className="text-button" type="button" onClick={() => onEvidence(standardNode.id)}>{standardNode.object_description} · 达成标准{ref.version ? ` v${ref.version}` : ''}</button> : <span>达成标准当前不可查看</span>}</p>;
  })}{loading && <p role="status">正在读取原始依据…</p>}{error && <p role="alert">{error}</p>}{artifact && <div className="outcome-graph__source-content"><button className="text-button" type="button" onClick={() => setArtifact(null)}>收起原始依据</button>{artifact.content === null ? <p>这个版本当前不可查看。</p> : <div className="ai-markdown"><LearningMarkdown>{artifact.content}</LearningMarkdown></div>}</div>}</>;
}
