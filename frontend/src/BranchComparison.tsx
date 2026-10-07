import { useEffect, useRef, useState } from 'react';
import { compareBranches, confirmBranchComparison, getComparisonSources, type BranchComparison as Preview, type BranchComparisonSource, type BranchMapNode } from './api';
import { ModelSummary } from './ModelControl';

const relations = { same: '相同点', different: '差异', complement: '互补', open: '待核实' };
export default function BranchComparison({ kind, nodes, onBack, onSaved, onBusy }: {
  kind: 'conversation' | 'discussion'; nodes: BranchMapNode[];
  onBack: () => void; onSaved: (id: string) => Promise<void>; onBusy: (busy: boolean) => void;
}) {
  const [left, setLeft] = useState(''), [right, setRight] = useState('');
  const [sources, setSources] = useState<BranchComparisonSource[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [selection, setSelection] = useState<Record<string, boolean>>({});
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [title, setTitle] = useState('');
  const [generating, setGenerating] = useState(false), [saving, setSaving] = useState(false);
  const [error, setError] = useState(''), [savedId, setSavedId] = useState('');
  const controller = useRef<AbortController | null>(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; controller.current?.abort(); }; }, []);
  useEffect(() => {
    let active = true;
    setPreview(null); setSources([]); setError(''); setSelection({}); setTexts({}); setSavedId('');
    if (left && right && left !== right) getComparisonSources(kind, left, right).then(value => { if (active) setSources(value); })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : '分支暂时无法读取'); });
    return () => { active = false; };
  }, [kind, left, right]);
  async function generate() {
    const abort = new AbortController(); controller.current = abort;
    setGenerating(true); setError(''); setPreview(null); setSelection({}); setSavedId('');
    try {
      const next = await compareBranches(kind, left, right, abort.signal);
      if (!alive.current || abort.signal.aborted) return;
      setPreview(next); setSources(next.sources); setTexts(Object.fromEntries(next.cards.map(card => [card.id, card.conclusion])));
    } catch (reason) { if (alive.current && !abort.signal.aborted) setError(reason instanceof Error ? reason.message : '比较失败，请重试'); }
    finally { if (alive.current) setGenerating(false); }
  }
  async function save() {
    if (!preview?.preview_id) return;
    setSaving(true); onBusy(true); setError('');
    try {
      const result = await confirmBranchComparison(preview.preview_id, title, preview.cards.filter(card => selection[card.id]).map(card => ({ id: card.id, text: texts[card.id] })));
      if (!alive.current) return;
      setSavedId(result.id); onBusy(false); await onSaved(result.id);
    } catch (reason) { if (alive.current) setError(reason instanceof Error ? reason.message : '保存失败，请重试'); }
    finally { if (alive.current) { setSaving(false); onBusy(false); } }
  }
  const blocked = generating || saving;
  return <section className="branch-comparison" aria-label="分支比较">
    <div className="branch-comparison-heading"><h3>合并对话</h3><button type="button" disabled={saving} onClick={onBack}>返回分支图</button></div>
    <div className="branch-comparison-paths">{(['left', 'right'] as const).map(side => <label key={side}>
      <span>{side === 'left' ? '来源一' : '来源二'}</span>
      <select aria-label={side === 'left' ? '来源一' : '来源二'} value={side === 'left' ? left : right} disabled={blocked} onChange={event => (side === 'left' ? setLeft : setRight)(event.target.value)}>
        <option value="" disabled>请选择一条对话</option>
        {nodes.filter(node => node.available).map(node => <option key={node.id} value={node.id} disabled={node.id === (side === 'left' ? right : left)}>{node.title}</option>)}
      </select>
      {sources[side === 'left' ? 0 : 1] && <small>当前选中路径：{sources[side === 'left' ? 0 : 1].last_question}</small>}
    </label>)}</div>
    <div className="branch-comparison-actions"><button type="button" disabled={blocked || sources.length !== 2} onClick={() => void generate()}>{preview ? '重新整理' : '整理合并内容'}</button>
      {generating && <><span role="status">正在比较…</span><button type="button" onClick={() => controller.current?.abort()}>取消比较</button></>}
    </div>
    {preview?.empty_reason && <p role="status">{preview.empty_reason}</p>}
    {preview?.preview_id && <><p className="branch-map-muted">勾选要保留的观点，可直接修改结论文字。</p>
      <div className="branch-comparison-cards">{preview.cards.map(card => <article className="branch-comparison-card" key={card.id}>
        <label className="branch-comparison-choice"><input type="checkbox" aria-label={`采用：${card.topic}`} checked={!!selection[card.id]} disabled={saving || !!savedId} onChange={event => setSelection(old => ({ ...old, [card.id]: event.target.checked }))} /><strong>{card.topic}</strong><span>{relations[card.relation]}</span></label>
        <textarea aria-label={`结论：${card.topic}`} value={texts[card.id] ?? ''} rows={3} maxLength={4000} disabled={saving || !!savedId} onChange={event => setTexts(old => ({ ...old, [card.id]: event.target.value }))} />
        <details><summary>查看原文依据</summary>{card.references.map((reference, index) => <blockquote key={index}><small>{reference.side === 'left' ? '来源一' : '来源二'}</small><p>{reference.quote}</p></blockquote>)}</details>
      </article>)}</div>
      <label className="branch-comparison-title"><span>合并后的主题</span><input aria-label="合并后的主题" value={title} placeholder="为合并后的主题命名" maxLength={60} disabled={saving || !!savedId} onChange={event => setTitle(event.target.value)} /></label>
      <div className="branch-comparison-actions">{savedId ? <button type="button" onClick={() => void onSaved(savedId)}>打开合并对话</button> : <button type="button" disabled={saving || !title.trim() || !preview.cards.some(card => selection[card.id]) || preview.cards.some(card => selection[card.id] && !texts[card.id]?.trim())} onClick={() => void save()}>{saving ? '正在保存…' : '创建合并对话'}</button>}</div>
      <details className="model-config-history"><summary>本次比较模型</summary>{preview.model_config && <ModelSummary value={preview.model_config} />}</details>
    </>}
    {error && <p className="branch-map-error" role="alert">{error}</p>}
  </section>;
}
