import { useEffect, useRef, useState } from 'react';
import {
  ApiError, correctAiTeachingAttempt, correctDiscussionTeachingAttempt, correctAiLearningObservation, correctDiscussionLearningObservation,
  getAiConversation, getQuestionDiscussion, type AiMessage, type QuestionDiscussion, type HelpRecord,
  type TeachingAction, type TeachingMethod, type TeachingMode, type TeachingRecord, type TeachingSelection, type TeachingPracticeObservation, type LearningObservation,
} from './api';
import LearningObservations from './LearningObservations';
import './TeachingState.css';

type TeachingEntry = { id: string; teaching: TeachingRecord | null; userContent: string | null; answerContent: string | null; helpRecord: HelpRecord | null };
const modeLabels: Record<TeachingMode | 'adaptive', string> = { stepwise: '分步讲解', socratic: '提问引导', feynman: '费曼复述', practice_first: '练习优先', project: '项目实践', direct_answer: '直接给答案', full_explanation: '完整讲解', adaptive: '个人自适应' };
const helpLabels = { hint: '给个提示', explain_step: '只解释这一步', example: '换个例子', try_first: '让我先试试' };
const guidanceLabels = ['开放提问', '相关概念', '缩小范围', '局部示例', '直接解释'];
const progressLabel = (needsHelp: boolean | null | undefined) => needsHelp === true ? '仍需帮助' : needsHelp === false ? '已推进' : '未判断';

function referencedText(content: string | null, start: number, end: number): string | null {
  if (content === null || !Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start) return null;
  const points = Array.from(content);
  return end <= points.length ? points.slice(start, end).join('') : null;
}

export function conversationTeachingEntries(messages: AiMessage[]): TeachingEntry[] {
  return messages.filter(message => message.role === 'assistant').map(message => ({
    id: message.id,
    teaching: message.teaching ?? null,
    answerContent: message.content,
    helpRecord: message.help_record ?? null,
    userContent: messages.find(source => source.role === 'user' && source.id === (message.teaching?.project_observation?.message_id ?? message.teaching?.exercise_observation?.message_id ?? message.teaching?.retelling_observation?.message_id ?? message.teaching?.practice_observation?.message_id ?? message.teaching?.attempt?.message_id ?? message.teaching?.project_step?.step.change_request?.message_id))?.content ?? null,
  }));
}

export function discussionTeachingEntries(turns: QuestionDiscussion['turns']): TeachingEntry[] {
  return turns.map(turn => ({
    id: turn.id,
    teaching: turn.status === 'purged' ? null : turn.teaching ?? null,
    answerContent: turn.status === 'purged' ? null : turn.assistant_content,
    helpRecord: turn.status === 'purged' ? null : turn.help_record ?? null,
    userContent: turns.find(source => source.status !== 'purged' && source.id === (turn.teaching?.project_observation?.message_id ?? turn.teaching?.exercise_observation?.message_id ?? turn.teaching?.retelling_observation?.message_id ?? turn.teaching?.practice_observation?.message_id ?? turn.teaching?.attempt?.message_id ?? turn.teaching?.project_step?.step.change_request?.message_id))?.user_content ?? null,
  }));
}

export default function TeachingState({ kind, scopeId, pathKey, entries, disabled, onUpdated, defaultMode, selectedMode, onModeChange, onAction, standalone = false }: {
  kind: 'conversation' | 'discussion'; scopeId: string; pathKey: string; entries: TeachingEntry[];
  disabled: boolean; onUpdated: (answerId: string, teaching: TeachingRecord | null) => void; standalone?: boolean;
  defaultMode: TeachingMethod; selectedMode: TeachingSelection | null; onModeChange: (mode: TeachingSelection) => void;
  onAction: (action: TeachingAction, content: string) => void;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ id: string; text: string } | null>(null);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const request = useRef<AbortController | null>(null);
  const identity = `${kind}:${scopeId}:${pathKey}`;
  const currentIdentity = useRef(identity);
  currentIdentity.current = identity;
  const disabledRef = useRef(disabled);
  disabledRef.current = disabled;
  useEffect(() => {
    setBusyId(null); setNotice(null); setNeedsRefresh(false);
    return () => { request.current?.abort(); request.current = null; };
  }, [identity]);

  // The final selected answer owns this position. Legacy answers remain unknown;
  // cancellation and incomplete runs use their own saved pre-generation state.
  const last = entries.at(-1)?.teaching;
  const recordingUnavailable = last?.status === 'unavailable' || last?.recording?.available === false;
  const recordingNotice = last?.recording?.reason === 'not_checked'
    ? '当前模型尚未检查教学记录支持。可在设置中检查，普通对话可继续。'
    : last?.recording?.reason === 'native_search_unverified'
      ? '当前联网方式尚不能记录教学状态，普通对话可继续。'
      : '当前模型暂不能记录教学状态，普通对话可继续。';
  const checkpoint = last?.status === 'applied' ? last.current : last?.before;
  const attempts = entries.filter(entry => entry.teaching?.attempt && !entry.teaching.practice_observation && !entry.teaching.retelling_observation && !entry.teaching.exercise_observation && !entry.teaching.project_observation);
  const practices = entries.filter(entry => entry.teaching?.status === 'applied' && entry.teaching.practice_question);
  const practiceRecords = entries.filter(entry => entry.teaching?.status === 'applied' && (entry.teaching.exercise_question || entry.teaching.practice_question && entry.teaching.practice_question.kind !== 'retelling'));
  const retellings = practices.filter(entry => entry.teaching!.practice_question!.kind === 'retelling');
  const continuousRetellings = entries.filter(entry => entry.teaching?.status === 'applied' && entry.teaching.retelling_observation);
  const projectSteps = entries.filter(entry => entry.teaching?.status === 'applied' && entry.teaching.project_step);
  const currentMode = checkpoint?.mode ?? 'stepwise';
  const followsDefault = !checkpoint || checkpoint.mode_source === 'default';
  const method = selectedMode ?? (followsDefault ? 'default' : checkpoint?.policy === 'adaptive' ? 'adaptive' : currentMode === 'stepwise' || currentMode === 'socratic' || currentMode === 'feynman' || currentMode === 'practice_first' || currentMode === 'project' ? currentMode : '');
  const nextMode = method === 'default' ? defaultMode : method;
  const adaptive = nextMode === 'adaptive' || checkpoint?.policy === 'adaptive';
  const guidance = last?.status === 'applied' ? last.guidance ?? checkpoint?.guidance : checkpoint?.guidance;
  const continuousExercise = checkpoint?.exercise && !checkpoint.practice ? checkpoint.exercise : null;
  const project = checkpoint?.project;
  const continuousProject = project && !checkpoint?.practice && !checkpoint?.retelling ? project : null;

  async function correct(entry: TeachingEntry, change: { is_attempt: boolean; needs_help?: boolean | null }) {
    const attempt = entry.teaching?.attempt;
    if (!attempt || disabledRef.current || request.current || needsRefresh) return;
    const controller = new AbortController();
    request.current = controller;
    setBusyId(entry.id); setNotice(null);
    const active = () => !controller.signal.aborted && currentIdentity.current === identity && !disabledRef.current;
    try {
      const payload = {
        expected_revision: attempt.revision, ...change,
        request_key: crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`,
      };
      const saved = await (kind === 'conversation'
        ? correctAiTeachingAttempt(scopeId, entry.id, payload, controller.signal)
        : correctDiscussionTeachingAttempt(scopeId, entry.id, payload, controller.signal));
      if (active()) onUpdated(entry.id, saved);
    } catch (reason) {
      if (!active()) return;
      if (reason instanceof ApiError && reason.status === 409) {
        try {
          const latest = kind === 'conversation'
            ? (await getAiConversation(scopeId, controller.signal)).messages.find(message => message.id === entry.id)?.teaching
            : (await getQuestionDiscussion(scopeId, controller.signal)).turns.find(turn => turn.id === entry.id)?.teaching;
          if (!active()) return;
          onUpdated(entry.id, latest ?? null);
          setNotice({ id: entry.id, text: '识别记录已更新。已读取最新记录，请核对后再操作。' });
        } catch {
          if (active()) {
            setNeedsRefresh(true);
            setNotice({ id: entry.id, text: '识别记录已更新，暂时无法读取最新记录。请刷新后再操作。' });
          }
        }
      } else {
        setNotice({ id: entry.id, text: '纠正未确认，请刷新核对识别记录后再操作。' });
        setNeedsRefresh(true);
      }
    } finally {
      if (currentIdentity.current === identity && !controller.signal.aborted) setBusyId(null);
      if (request.current === controller) request.current = null;
    }
  }

  async function correctLearning(answerId: string, observation: LearningObservation, change: Pick<LearningObservation, 'topic' | 'state' | 'note' | 'excluded'>): Promise<boolean> {
    if (disabledRef.current || request.current || needsRefresh) return false;
    const controller = new AbortController();
    request.current = controller;
    setBusyId(observation.id); setNotice(null);
    const active = () => !controller.signal.aborted && currentIdentity.current === identity && !disabledRef.current;
    try {
      const payload = {
        observation_id: observation.id, expected_revision: observation.revision, ...change,
        request_key: crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`,
      };
      const saved = await (kind === 'conversation'
        ? correctAiLearningObservation(scopeId, answerId, payload, controller.signal)
        : correctDiscussionLearningObservation(scopeId, answerId, payload, controller.signal));
      if (!active()) return false;
      onUpdated(answerId, saved);
      return true;
    } catch (reason) {
      if (!active()) return false;
      if (reason instanceof ApiError && reason.status === 409) {
        try {
          const latest = kind === 'conversation'
            ? (await getAiConversation(scopeId, controller.signal)).messages.find(message => message.id === answerId)?.teaching
            : (await getQuestionDiscussion(scopeId, controller.signal)).turns.find(turn => turn.id === answerId)?.teaching;
          if (!active()) return false;
          onUpdated(answerId, latest ?? null);
          setNotice({ id: observation.id, text: '观察记录已更新。已读取最新记录，请核对后再操作。' });
        } catch {
          if (active()) {
            setNeedsRefresh(true);
            setNotice({ id: observation.id, text: '暂时无法读取最新观察，请刷新后再操作。' });
          }
        }
      } else {
        setNotice({ id: observation.id, text: '纠正未确认，请刷新核对观察记录后再操作。' });
        setNeedsRefresh(true);
      }
      return false;
    } finally {
      if (currentIdentity.current === identity && !controller.signal.aborted) setBusyId(null);
      if (request.current === controller) request.current = null;
    }
  }

  function correctionControls(entry: TeachingEntry, excerpt: string | null) {
    const attempt = entry.teaching?.attempt;
    if (!attempt) return null;
    return <>
      {attempt.is_attempt && <label className="teaching-attempt__progress">尝试进展
        <select aria-label="尝试进展" value={attempt.needs_help === true ? 'stuck' : attempt.needs_help === false ? 'progressed' : 'unknown'} disabled={disabled || Boolean(busyId) || needsRefresh || !excerpt}
          onChange={event => void correct(entry, { is_attempt: true, needs_help: event.target.value === 'stuck' ? true : event.target.value === 'progressed' ? false : null })}>
          <option value="unknown">未判断</option><option value="stuck">仍需帮助</option><option value="progressed">已推进</option>
        </select>
      </label>}
      <button type="button" className="button button--quiet button--compact" disabled={disabled || Boolean(busyId) || needsRefresh || !excerpt} onClick={() => void correct(entry, { is_attempt: !attempt.is_attempt })}>
        {busyId === entry.id ? '正在保存…' : attempt.is_attempt ? '这不是一次尝试' : '恢复为尝试'}
      </button>
      {notice?.id === entry.id && <p className="teaching-attempt__notice" role="alert">{notice.text}</p>}
      {attempt.corrections.length > 0 && <details className="teaching-attempt__history"><summary>纠正历史</summary>
        <ul>{attempt.corrections.map((correction, index) => <li key={correction.revision}>
          <time dateTime={correction.at}>{new Date(correction.at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</time>
          <span>{!correction.is_attempt ? '改为非尝试' : index > 0 && !attempt.corrections[index - 1].is_attempt ? '恢复为尝试' : 'needs_help' in correction ? `尝试 · ${progressLabel(correction.needs_help)}` : '恢复为尝试'}</span>
        </li>)}</ul>
      </details>}
    </>;
  }

  const answerExcerpt = (answerId: string, start: number, end: number) =>
    referencedText(entries.find(entry => entry.id === answerId)?.answerContent ?? null, start, end);

  function observationView(entry: TeachingEntry, observation: TeachingPracticeObservation, retelling: boolean, projectWork = false) {
    const attempt = entry.teaching!.attempt;
    const excerpt = referencedText(entry.userContent, observation.start, observation.end);
    const feedback = answerExcerpt(observation.answer_id, observation.feedback_start, observation.feedback_end);
    return <article className="teaching-practice__observation" aria-label={projectWork ? '实践内容' : retelling ? '复述作答' : '练习作答'} key={entry.id}>
      <p className="teaching-attempt__label">{projectWork ? '实践内容（AI识别）' : retelling ? '复述（AI识别）' : '作答（AI识别）'}{!observation.eligible && <span> · 已改为非尝试</span>}</p>
      {excerpt ? <blockquote>{excerpt}</blockquote> : <p className="form-hint">对应作答原文已不可用。</p>}
      {entry.userContent && entry.userContent !== excerpt && <details className="teaching-attempt__original"><summary>完整原文</summary><blockquote>{entry.userContent}</blockquote></details>}
      <p className="teaching-attempt__label">AI反馈</p>
      {feedback ? <blockquote>{feedback}</blockquote> : <p className="form-hint">对应反馈原文已不可用。</p>}
      {correctionControls(entry, attempt ? referencedText(entry.userContent, attempt.start, attempt.end) : null)}
    </article>;
  }

  function practiceView(entry: TeachingEntry, retelling: boolean) {
    const practice = entry.teaching!.practice_question!;
    const point = practice.basis_step;
    const pointText = point ? answerExcerpt(point.source_answer_id, point.start, point.end) : null;
    const question = answerExcerpt(practice.question.answer_id, practice.question.start, practice.question.end);
    const observations = entries.filter(item => item.teaching?.practice_observation?.question_id === practice.id);
    return <article className="teaching-practice" aria-label={retelling ? '单次复述' : '变式练习'} key={practice.id}>
      <p className="teaching-attempt__step"><b>原小点</b>{pointText || '对应原文已不可用。'}</p>
      <p className="teaching-attempt__label">{retelling ? '复述邀请' : '题目'}</p>
      {question ? <blockquote>{question}</blockquote> : <p className="form-hint">对应{retelling ? '邀请' : '题目'}原文已不可用。</p>}
      {observations.map(item => observationView(item, item.teaching!.practice_observation!, retelling))}
    </article>;
  }

  function exerciseView(entry: TeachingEntry) {
    const exercise = entry.teaching!.exercise_question!;
    const question = answerExcerpt(exercise.question.answer_id, exercise.question.start, exercise.question.end);
    const observations = entries.filter(item => item.teaching?.exercise_observation?.question_id === exercise.id);
    return <article className="teaching-practice" aria-label="持续练习" key={exercise.id}>
      <p className="teaching-attempt__label">题目</p>
      {question ? <blockquote>{question}</blockquote> : <p className="form-hint">对应题目原文已不可用。</p>}
      {observations.map(item => observationView(item, item.teaching!.exercise_observation!, false))}
    </article>;
  }

  function projectView(entry: TeachingEntry) {
    const project = entry.teaching!.project_step!;
    const step = project.step;
    const goal = answerExcerpt(project.goal.answer_id, project.goal.start, project.goal.end);
    const instruction = answerExcerpt(step.instruction.answer_id, step.instruction.start, step.instruction.end);
    const changeRequest = step.change_request && referencedText(entry.userContent, step.change_request.start, step.change_request.end);
    const history = entries.filter(item => item.teaching && (
      item.teaching.status === 'applied' && item.teaching.project_observation?.project_id === project.id && item.teaching.project_observation.question_id === step.id
      || item.teaching.before.project?.id === project.id && item.teaching.before.project.step.id === step.id
        && !item.teaching.project_observation && !item.teaching.project_step && !item.teaching.before.practice && !item.teaching.before.retelling
        && (item.helpRecord?.request && item.helpRecord.provided || item.teaching.status === 'applied' && (item.teaching.effective_mode === 'direct_answer' || item.teaching.effective_mode === 'full_explanation'))
    ));
    return <article className="teaching-practice" aria-label="实践步骤" key={step.id}>
      <p className="teaching-attempt__label">{step.change === 'revision' ? '调整要求后' : step.change === 'next' ? '下一步' : '开始实践'}</p>
      {step.change_request && <>
        <p className="teaching-attempt__label">调整要求</p>
        {changeRequest ? <blockquote>{changeRequest}</blockquote> : <p className="form-hint">对应要求原文已不可用。</p>}
      </>}
      <p className="teaching-attempt__step"><b>目标</b>{goal || '对应目标原文已不可用。'}</p>
      <p className="teaching-attempt__label">这一步</p>
      {instruction ? <blockquote>{instruction}</blockquote> : <p className="form-hint">对应步骤原文已不可用。</p>}
      {history.map(item => item.teaching!.project_observation
        ? observationView(item, item.teaching!.project_observation!, false, true)
        : <article className="teaching-practice__observation" aria-label="实践帮助" key={item.id}>
          <p className="teaching-attempt__label">{item.helpRecord?.request ? helpLabels[item.helpRecord.request.kind]
            : item.teaching!.effective_mode === 'direct_answer' || item.teaching!.effective_mode === 'full_explanation' ? modeLabels[item.teaching!.effective_mode!] : '帮助'}{item.helpRecord?.provided?.partial && ' · 部分内容'}</p>
          {item.answerContent ? <blockquote>{item.answerContent}</blockquote> : <p className="form-hint">对应帮助原文已不可用。</p>}
        </article>)}
    </article>;
  }

  const body = <div className="teaching-state" aria-label="当前教学安排">
    {recordingUnavailable && <p className="form-hint" role="status">{recordingNotice}</p>}
    <label className="teaching-state__choice">讲解方式
      <select aria-label="讲解方式" value={method} disabled={disabled || Boolean(busyId)} onChange={event => onModeChange(event.target.value as TeachingSelection)}>
        {!method && <option value="" disabled>选择方式</option>}
        <option value="default">沿用设置（{modeLabels[defaultMode]}）</option>
        <option value="stepwise">分步讲解</option><option value="socratic">提问引导</option>
        {method === 'feynman' && <option value="feynman" disabled>费曼复述（当前方式）</option>}
        {method === 'practice_first' && <option value="practice_first" disabled>练习优先（当前方式）</option>}
        {method === 'project' && <option value="project" disabled>项目实践（当前方式）</option>}
        {method === 'adaptive' && <option value="adaptive" disabled>个人自适应（当前方式）</option>}
      </select>
    </label>
    {selectedMode && <p className="form-hint" role="status">下次发送时使用{modeLabels[selectedMode === 'default' ? defaultMode : selectedMode]}。</p>}
    {!selectedMode && followsDefault && last && currentMode !== nextMode && <p className="teaching-state__mode">当前方式 · {modeLabels[currentMode]}{nextMode !== 'adaptive' && <> · 下次使用{modeLabels[defaultMode]}</>}</p>}
    {last?.status === 'applied' && last.mode_request?.scope === 'turn' && last.effective_mode && last.effective_mode !== checkpoint?.mode
      ? <p className="teaching-state__mode">本轮：{modeLabels[last.effective_mode]} · 下轮：{checkpoint?.mode ? modeLabels[checkpoint.mode] : '原方式'}</p>
      : (adaptive || currentMode !== 'stepwise' && currentMode !== 'socratic') && !(followsDefault && last && currentMode !== nextMode) && last && <p className="teaching-state__mode">当前方式 · {modeLabels[currentMode]}</p>}
    {last?.status === 'applied' && last.adaptation?.reason && <details className="teaching-attempt__original"><summary>选择原因</summary><p className="form-hint">{last.adaptation.reason}</p></details>}
    {(last?.effective_mode ?? checkpoint?.mode) === 'socratic' && guidance && <p className="teaching-state__mode">提示安排 · {guidanceLabels[guidance.level]}</p>}
    {project && <div className="teaching-state__step teaching-state__project">
      <b>当前目标</b><p>{answerExcerpt(project.goal.answer_id, project.goal.start, project.goal.end) || '对应目标原文已不可用。'}</p>
      <b>当前这一步</b><p>{answerExcerpt(project.step.instruction.answer_id, project.step.instruction.start, project.step.instruction.end) || '对应步骤原文已不可用。'}</p>
    </div>}
    {continuousExercise
      ? <div className="teaching-state__step"><b>当前题目</b><p>{answerExcerpt(continuousExercise.question.answer_id, continuousExercise.question.start, continuousExercise.question.end) || '对应题目原文已不可用。'}</p></div>
      : !continuousProject && checkpoint?.step && <div className="teaching-state__step"><b>当前小点</b><p>{checkpoint.step.text}</p></div>}
    {checkpoint?.step?.text.trim() && <div className="teaching-state__practice-actions">
      {!continuousExercise && !continuousProject && <button type="button" className="button button--quiet button--compact" disabled={disabled || Boolean(busyId) || needsRefresh || recordingUnavailable}
        onClick={() => onAction('practice', '换一道试试。')}>换一道试试</button>}
      <button type="button" className="button button--quiet button--compact" disabled={disabled || Boolean(busyId) || needsRefresh || recordingUnavailable}
        onClick={() => onAction('retell', '用自己的话说说。')}>用自己的话说说</button>
      {continuousExercise && (nextMode === 'practice_first' || nextMode === 'adaptive' && currentMode === 'practice_first') && <>
        <span className="teaching-state__practice-phase">{continuousExercise.phase === 'awaiting_attempt' ? '等待作答' : '已有反馈'}</span>
        <button type="button" className="button button--quiet button--compact" disabled={disabled || Boolean(busyId) || needsRefresh || recordingUnavailable}
          onClick={() => onAction('next_question', '下一题。')}>下一题</button>
      </>}
      {(checkpoint.practice || checkpoint.retelling) && <>
        <span className="teaching-state__practice-phase">{checkpoint.practice
          ? checkpoint.practice.phase === 'awaiting_attempt' ? checkpoint.practice.kind === 'retelling' ? '等待复述' : '等待作答' : '已有反馈'
          : checkpoint.retelling?.phase === 'awaiting_retelling' ? '等待复述' : '已有反馈'}</span>
        <button type="button" className="button button--quiet button--compact" disabled={disabled || Boolean(busyId) || needsRefresh || recordingUnavailable}
          onClick={() => onAction('continue', checkpoint.practice && checkpoint.practice.kind !== 'retelling' ? '这道先不练了，继续学习。' : '继续学习。')}>继续学习</button>
      </>}
    </div>}
    {continuousProject && (nextMode === 'project' || nextMode === 'adaptive' && currentMode === 'project') && <div className="teaching-state__practice-actions">
      <span className="teaching-state__practice-phase">{continuousProject.step.phase === 'awaiting_work' ? '等待实践内容' : '已有反馈'}</span>
      <button type="button" className="button button--quiet button--compact" disabled={disabled || Boolean(busyId) || needsRefresh || recordingUnavailable}
        onClick={() => onAction('next_step', '下一步。')}>下一步</button>
    </div>}
    {projectSteps.length > 0 && <details className="teaching-state__projects">
      <summary>实践记录</summary>
      {projectSteps.map(projectView)}
    </details>}
    {practiceRecords.length > 0 && <details className="teaching-state__practices">
      <summary>练习记录</summary>
      {practiceRecords.map(entry => entry.teaching!.exercise_question ? exerciseView(entry) : practiceView(entry, false))}
    </details>}
    {(retellings.length > 0 || continuousRetellings.length > 0) && <details className="teaching-state__retellings">
      <summary>复述记录</summary>
      {retellings.map(entry => practiceView(entry, true))}
      {continuousRetellings.map(entry => {
        const observation = entry.teaching!.retelling_observation!;
        const point = entry.teaching!.before.step;
        const pointText = point?.id === observation.question_id ? answerExcerpt(point.source_answer_id, point.start, point.end) : null;
        return <article className="teaching-practice" aria-label="持续复述" key={entry.id}>
          <p className="teaching-attempt__step"><b>原小点</b>{pointText || '对应原文已不可用。'}</p>
          {observationView(entry, observation, true)}
        </article>;
      })}
    </details>}
    {last?.status === 'running' && <p className="form-hint" role="status">正在回复，教学位置暂不更新。</p>}
    {last?.status === 'not_updated' && <p className="form-hint">{currentMode === 'feynman' || checkpoint?.practice?.kind === 'retelling' || last.requested_action === 'retell'
      ? '本轮复述记录未更新，对话内容已保留。' : '本轮未更新教学位置。'}</p>}
    {attempts.length > 0 && <details className="teaching-state__attempts">
      <summary>尝试识别</summary>
      {attempts.map(entry => {
        const attempt = entry.teaching!.attempt!;
        const step = entry.teaching!.before.step;
        // Offsets from the server refer to Unicode code points, as in Python.
        const excerpt = referencedText(entry.userContent, attempt.start, attempt.end);
        return <article className="teaching-attempt" key={entry.id} aria-label="AI识别的尝试">
          <p className="teaching-attempt__label">AI识别{!attempt.is_attempt && <span> · 已改为非尝试</span>}</p>
          {excerpt ? <blockquote>{excerpt}</blockquote> : <p className="form-hint">对应原文已不可用。</p>}
          {entry.userContent && entry.userContent !== excerpt && <details className="teaching-attempt__original"><summary>完整原文</summary><blockquote>{entry.userContent}</blockquote></details>}
          {step?.id === attempt.step_id && <p className="teaching-attempt__step"><b>当时的小点</b>{step.text}</p>}
          {correctionControls(entry, excerpt)}
        </article>;
      })}
    </details>}
    <LearningObservations entries={entries} identity={identity} disabled={disabled || needsRefresh} busyId={busyId} notice={notice} onCorrect={correctLearning} />
  </div>;
  return standalone ? <section className="ai-room-brief teaching-arrangement" aria-label="本次学习安排"><details><summary>学习安排</summary>{body}</details></section> : body;
}
