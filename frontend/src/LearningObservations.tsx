import { useEffect, useState } from 'react';
import type { LearningObservation, LearningObservationState, TeachingRecord } from './api';
import './LearningObservations.css';

type Entry = { id: string; teaching: TeachingRecord | null; userContent: string | null; answerContent: string | null };
type ObservationEntry = { entry: Entry; observation: LearningObservation };
type Change = Pick<LearningObservation, 'topic' | 'state' | 'note' | 'excluded'>;
const labels: Record<LearningObservationState, string> = { progress: '有进展', difficulty: '仍有困难', uncertain: '尚不明确' };
const helpLabels = { hint: '给个提示', explain_step: '只解释这一步', example: '换个例子', try_first: '让我先试试' };
const dateLabel = (at: string) => new Date(at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });

function excerpt(content: string | null, start: number, end: number) {
  if (content === null || !Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start) return null;
  const points = Array.from(content);
  return end <= points.length ? points.slice(start, end).join('') : null;
}

export default function LearningObservations({ entries, identity, disabled, busyId, notice, onCorrect }: {
  entries: Entry[]; identity: string; disabled: boolean; busyId: string | null;
  notice: { id: string; text: string } | null;
  onCorrect: (answerId: string, observation: LearningObservation, change: Change) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState<{ id: string; revision: number; value: Change } | null>(null);
  useEffect(() => { setEditing(null); }, [identity]);
  const all: ObservationEntry[] = entries.flatMap(entry => (entry.teaching?.learning_observations ?? []).map(observation => ({ entry, observation })));
  const groups = new Map<string, ObservationEntry[]>();
  for (const item of all) groups.set(item.observation.point_id, [...(groups.get(item.observation.point_id) ?? []), item]);
  const used = entries.at(-1)?.teaching?.learning_used ?? [];
  if (!all.length && !used.length) return null;
  const blocked = disabled || Boolean(busyId);

  function evidence({ entry, observation }: ObservationEntry) {
    const source = entry.teaching?.attempt?.message_id === observation.source.message_id
      ? excerpt(entry.userContent, observation.source.start, observation.source.end) : null;
    const feedback = excerpt(entries.find(item => item.id === observation.feedback.answer_id)?.answerContent ?? null, observation.feedback.start, observation.feedback.end);
    return <details className="learning-observation__evidence">
      <summary>查看依据</summary>
      <p className="learning-observation__label">你的原话</p>
      {source ? <blockquote>{source}</blockquote> : <p className="form-hint">对应原话已不可用。</p>}
      <p className="learning-observation__label">AI反馈</p>
      {feedback ? <blockquote>{feedback}</blockquote> : <p className="form-hint">对应反馈已不可用。</p>}
      <p className="learning-observation__label">AI原始观察 · {observation.original.topic} · {labels[observation.original.state]}</p>
      <p className="learning-observation__label">当时的帮助</p>
      {observation.help_context.length ? <ul className="learning-observation__help">{observation.help_context.map((help, index) => <li key={`${help.answer_id}:${index}`}>
        {help.request ? helpLabels[help.request.kind] : help.method === 'direct_answer' ? '直接给答案' : help.method === 'full_explanation' ? '完整讲解' : '帮助请求未记录'}
        {help.provided ? ` · 已提供回复${help.provided.partial ? '（部分内容）' : ''}` : ' · 是否提供未记录'}
        {help.display ? ' · 已显示' : ' · 是否显示未记录'}
      </li>)}</ul> : <p className="form-hint">当时的帮助情况未记录。</p>}
      <time className="learning-observation__time" dateTime={observation.at}>{dateLabel(observation.at)}</time>
    </details>;
  }

  function record(item: ObservationEntry, historical = false) {
    const { entry, observation } = item;
    const currentEdit = editing?.id === observation.id ? editing : null;
    const sourceAvailable = entry.teaching?.attempt?.message_id === observation.source.message_id
      && Boolean(excerpt(entry.userContent, observation.source.start, observation.source.end));
    const change = { topic: observation.topic, state: observation.state, note: observation.note, excluded: observation.excluded };
    return <article key={observation.id} data-observation-id={observation.id} className={`learning-observation${historical ? ' learning-observation--historical' : ''}`} aria-label={historical ? '此前观察' : `知识点：${observation.topic}`}>
      <div className="learning-observation__heading"><b>{observation.topic}</b><span className={`learning-observation__state learning-observation__state--${observation.state}`}>{labels[observation.state]}</span></div>
      <p className="learning-observation__label">{observation.corrections.length ? '你的纠正' : 'AI观察'}
        {!observation.eligible && <span> · {observation.excluded ? '已排除' : '对应内容已改为非尝试'}</span>}
      </p>
      {observation.note && <p className="learning-observation__note">{observation.note}</p>}
      {evidence(item)}
      <div className="learning-observation__actions">
        <button type="button" className="button button--quiet button--compact" disabled={blocked || !sourceAvailable}
          onClick={() => setEditing({ id: observation.id, revision: observation.revision, value: change })}>纠正</button>
        <button type="button" className="button button--quiet button--compact" disabled={blocked || !sourceAvailable}
          onClick={() => void onCorrect(entry.id, observation, { ...change, excluded: !observation.excluded })}>
          {busyId === observation.id ? '正在保存…' : observation.excluded ? '恢复使用' : '排除此观察'}
        </button>
      </div>
      {currentEdit && <form className="learning-observation__form" onSubmit={event => {
        event.preventDefault();
        if (currentEdit.revision !== observation.revision) return;
        void onCorrect(entry.id, observation, { ...currentEdit.value, topic: currentEdit.value.topic.trim(), note: currentEdit.value.note.trim() }).then(saved => {
          if (saved) setEditing(value => value?.id === observation.id ? null : value);
        });
      }}>
        <label>知识点<input aria-label="知识点" value={currentEdit.value.topic} maxLength={120} required disabled={blocked}
          onChange={event => setEditing({ ...currentEdit, value: { ...currentEdit.value, topic: event.target.value } })} /></label>
        <label>学习情况<select aria-label="学习情况" value={currentEdit.value.state} disabled={blocked}
          onChange={event => setEditing({ ...currentEdit, value: { ...currentEdit.value, state: event.target.value as LearningObservationState } })}>
          <option value="progress">有进展</option><option value="difficulty">仍有困难</option><option value="uncertain">尚不明确</option>
        </select></label>
        <label>补充说明（可选）<textarea aria-label="补充说明（可选）" value={currentEdit.value.note} maxLength={600} rows={2} disabled={blocked}
          onChange={event => setEditing({ ...currentEdit, value: { ...currentEdit.value, note: event.target.value } })} /></label>
        {currentEdit.revision !== observation.revision && <p className="form-hint">记录已更新，请取消后重新纠正。</p>}
        <div className="learning-observation__actions">
          <button type="submit" className="button button--quiet button--compact" disabled={blocked || !currentEdit.value.topic.trim() || currentEdit.revision !== observation.revision}>保存纠正</button>
          <button type="button" className="button button--quiet button--compact" disabled={Boolean(busyId)} onClick={() => setEditing(null)}>取消</button>
        </div>
      </form>}
      {notice?.id === observation.id && <p className="teaching-attempt__notice" role="alert">{notice.text}</p>}
      {observation.corrections.length > 0 && <details className="learning-observation__corrections"><summary>纠正历史</summary>
        <ul>{observation.corrections.map(correction => <li key={correction.revision}>
          <time dateTime={correction.at}>{dateLabel(correction.at)}</time>
          <span>你的纠正 · {correction.topic} · {labels[correction.state]}{correction.excluded ? ' · 已排除' : ' · 可使用'}</span>
          {correction.note && <p>{correction.note}</p>}
        </li>)}</ul>
      </details>}
    </article>;
  }

  return <details className="learning-observations">
    <summary>学习情况</summary>
    {[...groups.entries()].map(([pointId, records]) => {
      const current = [...records].reverse().find(item => item.observation.eligible) ?? records.at(-1)!;
      const history = records.filter(item => item !== current);
      return <div className="learning-observations__point" key={pointId}>
        {record(current)}
        {history.length > 0 && <details className="learning-observations__history"><summary>观察历史（{history.length}）</summary>{history.map(item => record(item, true))}</details>}
      </div>;
    })}
    {used.length > 0 && <details className="learning-observations__used"><summary>本轮参考</summary>
      <p className="form-hint">本轮回答当时参考的观察</p>
      <ul>{used.map(id => {
        const item = all.find(value => value.observation.id === id);
        return <li key={id}>{item ? <>{item.observation.topic}{item.observation.corrections.length > 0 && ' · 现有记录经过纠正'}{!item.observation.eligible && ' · 现已不再使用'}</> : '对应观察已不可用。'}</li>;
      })}</ul>
    </details>}
  </details>;
}
