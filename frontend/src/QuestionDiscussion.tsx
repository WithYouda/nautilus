import useConversationSearch from './useConversationSearch';
import useReplyHistory from './useReplyHistory';
import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, Bot, Square } from 'lucide-react';
import { LearningChatPanel, LearningComposer, LearningMessage, LearningUserMessage, LearningReplyActions } from './LearningRoomLayout';
import DiscussionSources from './DiscussionSources';
import QuestionFeedbackContent from './QuestionFeedbackContent';
import LearningMarkdown from './LearningMarkdown';
import SearchControls, { type SearchSelection } from './SearchControls';
import AssistantResponse from './AssistantResponse';
import HelpControls from './HelpControls';
import HelpRecord from './HelpRecord';
import TaskMaterials, { MaterialUse, emptySourceScope, readSourceScope, webMaterialCandidates } from './TaskMaterials';
import { ApiError, getQuestionDiscussion, sendDiscussionMessage, streamDiscussionTurn, cancelDiscussionTurn, recordDiscussionHelpDisplay, recordReferenceHelpDisplay, type HelpRequestKind, type QuestionDiscussion as Discussion, type SourceScope, type MaterialVersion } from './api';

const requestId = (): string => crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
export default function QuestionDiscussion({ id, onBack }: { id: string; onBack: () => void }) {
  const [discussion, setDiscussion] = useState<Discussion | null>(null);
  const [content, setContent] = useState('');
  const searchChoice = useConversationSearch('discussion', discussion?.identity_id ?? null, id);
  const searchSelection = searchChoice.value;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pending, setPending] = useState<{ content: string; key: string; failed: boolean; helpRequest: HelpRequestKind | null; sourceScope: SourceScope } | null>(null);
  const [sourceScope, setSourceScope] = useState<SourceScope>(emptySourceScope);
  const [materialVersions, setMaterialVersions] = useState<MaterialVersion[]>([]);
  const [reconnect, setReconnect] = useState(0);
  const [connectionLost, setConnectionLost] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [editingTurnId, setEditingTurnId] = useState<string | null>(null);
  const editRequest = useRef<{ turnId: string; content: string; key: string } | null>(null);
  const key = useRef(requestId());
  const searchByRequestKey = useRef(new Map<string, { search: SearchSelection; content: string; helpRequest: HelpRequestKind | null; sourceScope: SourceScope }>());
  const sending = useRef(false);
  const generation = useRef(0);
  useEffect(() => {
    let active = true;
    generation.current += 1;
    setEditingTurnId(null); editRequest.current = null; searchByRequestKey.current.clear(); setDiscussion(null); setContent(''); setSourceScope(emptySourceScope()); setMaterialVersions([]); setError(''); setPending(null); setBusy(false); sending.current = false; key.current = requestId();
    getQuestionDiscussion(id).then(value => { if (active) { setDiscussion(value); setSourceScope(readSourceScope('discussion', value.identity_id ?? value.verification_id, id)); } }).catch(reason => { if (active) setError(String(reason.message ?? reason)); });
    return () => { active = false; generation.current += 1; };
  }, [id]);
  const runningTurn = discussion?.turns.find(turn => turn.status === 'running');
  const running = Boolean(runningTurn);
  const replyHistory = useReplyHistory(`discussion:${id}`, (discussion?.turns ?? []).map(turn => ({id:turn.id, parentId:turn.parent_turn_id, groupId:turn.question_id})), runningTurn?.id);
  const visibleTurns = replyHistory.path.map(turnId => discussion!.turns.find(turn => turn.id === turnId)!);

  useEffect(() => {
    if (!runningTurn) return;
    const controller = new AbortController();
    const turnId = runningTurn.id;
    setConnectionLost(false);
    void (async () => {
      for (let attempt = 0; attempt < 3 && !controller.signal.aborted; attempt++) {
        try {
          await streamDiscussionTurn(id, turnId, update => {
            if (controller.signal.aborted) return;
            setError('');
            setDiscussion(previous => previous && (update.purged
              ? { ...previous, purged: true, source: null, turns: [] }
              : { ...previous, turns: previous.turns.map(turn => turn.id === update.turn.id ? { ...update.turn, search_trace: update.turn.search_trace === undefined ? turn.search_trace : update.turn.search_trace, generation_trace: update.turn.generation_trace === undefined ? turn.generation_trace : update.turn.generation_trace } : turn) }));
          }, controller.signal);
          return;
        } catch {
          if (controller.signal.aborted) return;
          setError('连接已中断，正在恢复回复…');
          // Reading the saved state never resends a prompt or starts another model call.
          try {
            const saved = await getQuestionDiscussion(id);
            if (controller.signal.aborted) return;
            setDiscussion(saved);
            if (!saved.turns.some(turn => turn.id === turnId && turn.status === 'running')) { setError(''); return; }
          } catch { /* Reconnect the existing run below. */ }
          await new Promise(resolve => window.setTimeout(resolve, 500 * (attempt + 1)));
        }
      }
      if (!controller.signal.aborted) { setConnectionLost(true); setError('暂时无法接收回复，已保存的消息仍保留。'); }
    })();
    return () => controller.abort();
  }, [id, runningTurn?.id, reconnect]);

  async function send(text = content, requestKey = key.current, retry = false, preserveDraft = false, regenerateTurnId?: string, editTurnId?: string, requestedHelp?: HelpRequestKind | null): Promise<boolean> {
    if (!text.trim() || sending.current || running) return false;
    if (!searchChoice.ready) { setError("正在读取联网设置，请稍后发送。"); return false; }
    if (sourceScope.mode !== 'unspecified' && sourceScope.version_ids.length === 0 && !searchByRequestKey.current.has(requestKey)) { setError('请先选择至少一个资料版本，或改为未指定资料。'); return false; }
    if (searchByRequestKey.current.size && (!searchByRequestKey.current.has(requestKey) || searchByRequestKey.current.get(requestKey)?.content !== text)) {
      setError('上次发送结果尚未确认。请先重试原消息，或重新打开讨论核对已保存的内容。');
      return false;
    }
    const currentGeneration = generation.current;
    sending.current = true; setBusy(true); setError('');
    const frozenHelp = searchByRequestKey.current.has(requestKey) ? searchByRequestKey.current.get(requestKey)!.helpRequest : (requestedHelp !== undefined ? requestedHelp : regenerateTurnId ? discussion?.turns.find(turn => turn.id === regenerateTurnId)?.help_record?.request?.kind ?? null : null);
    const frozenScope = searchByRequestKey.current.get(requestKey)?.sourceScope ?? sourceScope;
    if (!retry && !regenerateTurnId && !editTurnId) { setPending({ content: text, key: requestKey, failed: false, helpRequest: frozenHelp, sourceScope: frozenScope }); if (!preserveDraft) setContent(''); }
    try {
      const frozenSearch = searchByRequestKey.current.get(requestKey)?.search ?? structuredClone(searchSelection);
      searchByRequestKey.current.set(requestKey, { search: frozenSearch, content: text, helpRequest: frozenHelp, sourceScope: frozenScope });
      const saved = await sendDiscussionMessage(id, text, requestKey, retry, { regenerate_turn_id: regenerateTurnId, edit_turn_id: editTurnId, parent_turn_id: regenerateTurnId || editTurnId ? undefined : replyHistory.leaf ?? undefined, help_request: frozenHelp, source_scope: frozenScope, ...(frozenSearch.mode !== 'off' ? { search: frozenSearch } : {}) });
      if (generation.current !== currentGeneration) return false;
      searchByRequestKey.current.delete(requestKey);
      setDiscussion(previous => ({ ...saved, turns: saved.turns.map(turn => ({ ...turn, search_trace: turn.search_trace === undefined ? previous?.turns.find(old => old.id === turn.id)?.search_trace : turn.search_trace, generation_trace: turn.generation_trace === undefined ? previous?.turns.find(old => old.id === turn.id)?.generation_trace : turn.generation_trace })) })); setPending(null); key.current = requestId();
      const sent = saved.turns.find(turn => turn.request_key === requestKey);
      if (sent) replyHistory.select(sent.id);
      return true;
    } catch (reason) {
      if (generation.current !== currentGeneration) return false;
      if (reason instanceof ApiError && [400, 422].includes(reason.status ?? 0)) {
        searchByRequestKey.current.delete(requestKey);
        if (editRequest.current?.key === requestKey) editRequest.current = null;
        if (key.current === requestKey) key.current = requestId();
        if (!retry && !regenerateTurnId && !editTurnId) { setPending(null); if (!preserveDraft) setContent(text); }
      } else if (!retry && !regenerateTurnId && !editTurnId) setPending({ content: text, key: requestKey, failed: true, helpRequest: frozenHelp, sourceScope: frozenScope });
      setError(reason instanceof Error ? reason.message : '消息发送未确认，请重试。');
      return false;
    } finally {
      if (generation.current === currentGeneration) { sending.current = false; setBusy(false); }
    }
  }
  async function cancel() {
    if (!runningTurn || cancelling) return;
    const currentGeneration = generation.current;
    setCancelling(true);
    try {
      const saved = await cancelDiscussionTurn(id, runningTurn.id);
      if (generation.current === currentGeneration) { setDiscussion(saved); setError(''); }
    } catch { if (generation.current === currentGeneration) setError('取消未确认，请重试。'); }
    finally { if (generation.current === currentGeneration) setCancelling(false); }
  }
  const feedback = discussion?.source?.feedback;
  return <section className="ai-room question-discussion" aria-label="题目学习室">
    <header className="ai-room-header">
      <div className="ai-room-heading">
        <button className="button button--quiet button--compact button--with-icon" type="button" onClick={onBack} aria-label="返回验证记录"><ArrowLeft size={15} /><span>返回验证记录</span></button>
        <h1>AI 学习室</h1>
      </div>
      <span className="question-discussion-context">题目讨论</span>
    </header>
    <LearningChatPanel title="讨论这道题" autoFollow={!editingTurnId && (replyHistory.following || busy) && Boolean(discussion?.turns.length || pending)} followToken={`${id}:${(discussion?.turns.length ?? 0) + (pending ? 1 : 0)}`}
      notice={<>{searchChoice.error && <p role="status">{searchChoice.error}</p>}{error && <p className="ai-room-error" role="alert">{error}</p>}{connectionLost && running && <button type="button" className="button button--quiet ai-retry-button" onClick={() => setReconnect(value => value + 1)}>重新连接回复</button>}</>}
      composer={discussion && !discussion.purged && <LearningComposer
        id="question-discussion-input" label="继续提问或回答拓展问题" value={content}
        onChange={value => { setContent(value); key.current = requestId(); }}
        onSubmit={event => { event.preventDefault(); void send(); }}
        placeholder="输入关于这道题的问题，或回答拓展问题" maxLength={12000}
        disabled={busy || running || Boolean(pending) || Boolean(editingTurnId)}
        suggestions={<HelpControls disabled={busy || running || Boolean(pending) || Boolean(editingTurnId)} onChoose={(kind, label) => void send(label, key.current, false, true, undefined, undefined, kind)} />} tools={<><SearchControls value={searchSelection} onChange={searchChoice.change} onReset={searchChoice.reset} overridden={searchChoice.overridden} disabled={busy || running || Boolean(pending) || Boolean(editingTurnId) || !searchChoice.ready} providerKind={discussion.provider_protocol ?? undefined} /><TaskMaterials kind="discussion" id={id} identity={discussion.identity_id ?? discussion.verification_id} scope={sourceScope} onChange={setSourceScope} onVersions={setMaterialVersions} disabled={busy || running || Boolean(pending) || Boolean(editingTurnId)} onPurged={async () => { const current = generation.current; const next = await getQuestionDiscussion(id); if (generation.current === current) setDiscussion(next); }} candidates={webMaterialCandidates(discussion.turns.map(turn => ({ runId: turn.id, trace: turn.search_trace, complete: turn.status === 'succeeded' })))} /></>}
        actions={running && <button className="button button--danger button--with-icon" type="button" disabled={cancelling} onClick={() => void cancel()}><Square size={14} fill="currentColor" />取消生成</button>}
      />}
    >
      {!discussion && !error && <p role="status">正在恢复题目讨论…</p>}
      {discussion?.purged ? <p>关联内容已彻底删除，讨论正文不可恢复。</p> : discussion && <>
        <details className="question-discussion-source" open={!discussion.turns.length && !pending}>
          <summary>题目、当时的回答与反馈</summary>
          <div className="question-discussion-source__body">
            <h3>题目</h3><div className="ai-markdown"><LearningMarkdown>{discussion.source?.question ?? ''}</LearningMarkdown></div>
            {discussion.source?.material && <details><summary>本次参考材料</summary><div className="ai-markdown"><LearningMarkdown>{discussion.source.material}</LearningMarkdown></div></details>}
            <h3>我当时的回答</h3><div className="ai-markdown review-answer"><LearningMarkdown>{discussion.source?.answer || '没有提交本人作答'}</LearningMarkdown></div>
            {feedback && 'question_id' in feedback ? <QuestionFeedbackContent key={`${id}:${discussion.evaluation_id}:${feedback.question_id}`} feedback={feedback} helpDisplay={discussion.help_displays?.[feedback.question_id]} onRecordDisplay={discussion.evaluation_id ? async () => {
              const value = await recordReferenceHelpDisplay(discussion.verification_id, discussion.evaluation_id!, feedback.question_id);
              setDiscussion(previous => previous?.id === id && previous.evaluation_id === discussion.evaluation_id ? { ...previous, help_displays: { ...previous.help_displays, [feedback.question_id]: value } } : previous);
              return value;
            } : undefined} /> : <>
              <p className="form-hint">这次记录未保存逐题反馈，可在讨论中请 AI 重新讲解。</p>
              {feedback?.feedback && <><h3>当时的整体验证总结</h3><div className="ai-markdown"><LearningMarkdown>{feedback.feedback}</LearningMarkdown>{'next_step' in feedback && <LearningMarkdown>{feedback.next_step}</LearningMarkdown>}</div></>}
            </>}
          </div>
        </details>
        {!discussion.turns.length && !pending && <div className="ai-empty-chat"><Bot size={24} /><h2>还有哪里没弄明白？</h2><p>可以追问反馈、比较解法，或回答拓展问题。原验证结果保持不变。</p></div>}
        {visibleTurns.map(turn => {
          const questionVersions = [...new Map(discussion.turns.filter(item => (item.question_version_id ?? item.question_id) === (turn.question_version_id ?? turn.question_id)).map(item => [item.question_id, item])).values()];
          const questionIndex = questionVersions.findIndex(item => item.question_id === turn.question_id);
          return <div key={turn.id} className="discussion-turn">
          {turn.status === 'purged' ? <p>这轮讨论内容已删除。</p> : <>
            <LearningUserMessage content={turn.user_content ?? ''} maxLength={12000}
              editing={editingTurnId === turn.id} editDisabled={busy || running || Boolean(pending) || (Boolean(editingTurnId) && editingTurnId !== turn.id)} sendDisabled={busy || running || Boolean(pending)}
              onStartEdit={() => setEditingTurnId(turn.id)}
              onCancelEdit={() => { setEditingTurnId(null); editRequest.current = null; setError(''); }}
              onSendEdit={text => {
                if (editRequest.current?.turnId !== turn.id || editRequest.current.content !== text) editRequest.current = {turnId: turn.id, content: text, key: requestId()};
                return send(text, editRequest.current.key, false, true, undefined, turn.id);
              }}
              version={{ disabled: busy || running || Boolean(pending) || Boolean(editingTurnId), index: questionIndex, count: questionVersions.length,
                onPrevious: () => { const target = questionVersions[questionIndex - 1]; replyHistory.switchVersion(replyHistory.preferredVersion(target.question_id, target.id)); },
                onNext: () => { const target = questionVersions[questionIndex + 1]; replyHistory.switchVersion(replyHistory.preferredVersion(target.question_id, target.id)); } }} />
            <LearningMessage role="assistant" state={turn.status === 'running' ? 'streaming' : turn.status === 'failed' ? (turn.reason === 'cancelled' ? 'canceled' : 'failed') : undefined} status={turn.status === 'running' ? '生成中' : turn.status === 'failed' ? (turn.reason === 'cancelled' ? '已取消' : '失败') : undefined}>
              <AssistantResponse key={turn.id} trace={turn.generation_trace} content={turn.assistant_content ?? ''} reasoningContent={turn.reasoning_content} searchTrace={turn.search_trace} streaming={turn.status === 'running'} />
              <MaterialUse scope={turn.source_scope} versions={materialVersions} />
              <HelpRecord key={`help:${turn.id}`} record={turn.help_record} body={turn.assistant_content ?? ''} terminal={turn.status !== 'running'} onDisplay={characters => recordDiscussionHelpDisplay(id, turn.id, characters)} />
              {turn.status === 'failed' && <div role="status"><p>{turn.reason === 'cancelled' ? '已取消生成，已收到的内容保留。' : '这次回复未完成，问题和已收到的内容已保存。'}</p></div>}
              {turn.status === 'succeeded' && turn.sources.length === 0 && <p className="form-hint">{turn.history_searched ? '本轮检索没有找到匹配的历史记录。' : '本轮依据这道题和当前讨论回答，未检索其他历史。'}</p>}
              {turn.sources.length > 0 && <DiscussionSources sources={turn.sources} />}
              <LearningReplyActions content={turn.assistant_content ?? ''} retryDisabled={busy || running || Boolean(pending) || Boolean(editingTurnId) || !turn.user_content}
                onRetry={() => void send(turn.user_content ?? '', requestId(), false, true, turn.id)}
                version={{ disabled: busy || running || Boolean(pending) || Boolean(editingTurnId), index: discussion.turns.filter(item => item.question_id === turn.question_id).findIndex(item => item.id === turn.id), count: discussion.turns.filter(item => item.question_id === turn.question_id).length,
                  onPrevious: () => { const versions = discussion.turns.filter(item => item.question_id === turn.question_id); replyHistory.switchVersion(versions[versions.findIndex(item => item.id === turn.id) - 1].id); },
                  onNext: () => { const versions = discussion.turns.filter(item => item.question_id === turn.question_id); replyHistory.switchVersion(versions[versions.findIndex(item => item.id === turn.id) + 1].id); } }} />
            </LearningMessage>
          </>}
        </div>; })}
        {pending && <>
          <LearningMessage role="user" state={pending.failed ? 'failed' : undefined} status={pending.failed ? '发送未确认' : '发送中'}><div className="ai-message-content">{pending.content}</div></LearningMessage>
          {pending.failed ? <button className="button button--quiet ai-retry-button" type="button" onClick={() => void send(pending.content, pending.key, false, true, undefined, undefined, pending.helpRequest)}>重试发送</button> : <LearningMessage role="assistant" status="生成中"><div className="ai-message-content">…</div></LearningMessage>}
        </>}
      </>}
    </LearningChatPanel>
  </section>;
}
