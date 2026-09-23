import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, Bot, Square } from 'lucide-react';
import { LearningChatPanel, LearningComposer, LearningMessage, ReasoningBlock } from './LearningRoomLayout';
import DiscussionSources from './DiscussionSources';
import QuestionFeedbackContent from './QuestionFeedbackContent';
import LearningMarkdown from './LearningMarkdown';
import { getQuestionDiscussion, sendDiscussionMessage, streamDiscussionTurn, cancelDiscussionTurn, type QuestionDiscussion as Discussion } from './api';

const requestId = (): string => crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
export default function QuestionDiscussion({ id, onBack }: { id: string; onBack: () => void }) {
  const [discussion, setDiscussion] = useState<Discussion | null>(null);
  const [content, setContent] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pending, setPending] = useState<{ content: string; key: string; failed: boolean } | null>(null);
  const [reconnect, setReconnect] = useState(0);
  const [connectionLost, setConnectionLost] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const key = useRef(requestId());
  const sending = useRef(false);
  const generation = useRef(0);
  useEffect(() => {
    let active = true;
    generation.current += 1;
    setDiscussion(null); setContent(''); setError(''); setPending(null); setBusy(false); sending.current = false; key.current = requestId();
    getQuestionDiscussion(id).then(value => { if (active) setDiscussion(value); }).catch(reason => { if (active) setError(String(reason.message ?? reason)); });
    return () => { active = false; generation.current += 1; };
  }, [id]);
  const runningTurn = discussion?.turns.find(turn => turn.status === 'running');
  const running = Boolean(runningTurn);
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
              : { ...previous, turns: previous.turns.map(turn => turn.id === update.turn.id ? update.turn : turn) }));
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

  async function send(text = content, requestKey = key.current, retry = false) {
    if (!text.trim() || sending.current || running) return;
    const currentGeneration = generation.current;
    sending.current = true; setBusy(true); setError('');
    if (!retry) { setPending({ content: text, key: requestKey, failed: false }); setContent(''); }
    try {
      const saved = await sendDiscussionMessage(id, text, requestKey, retry);
      if (generation.current !== currentGeneration) return;
      setDiscussion(saved); setPending(null); key.current = requestId();
    } catch (reason) {
      if (generation.current !== currentGeneration) return;
      if (!retry) setPending({ content: text, key: requestKey, failed: true });
      setError(reason instanceof Error ? reason.message : '消息发送未确认，请重试。');
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
    <LearningChatPanel title="讨论这道题" autoFollow={Boolean(discussion?.turns.length || pending)} followToken={`${id}:${(discussion?.turns.length ?? 0) + (pending ? 1 : 0)}`}
      notice={<>{error && <p className="ai-room-error" role="alert">{error}</p>}{connectionLost && running && <button type="button" className="button button--quiet ai-retry-button" onClick={() => setReconnect(value => value + 1)}>重新连接回复</button>}</>}
      composer={discussion && !discussion.purged && <LearningComposer
        id="question-discussion-input" label="继续提问或回答拓展问题" value={content}
        onChange={value => { setContent(value); key.current = requestId(); }}
        onSubmit={event => { event.preventDefault(); void send(); }}
        placeholder="输入关于这道题的问题，或回答拓展问题" maxLength={12000}
        disabled={busy || running || Boolean(pending)}
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
            {feedback && 'question_id' in feedback ? <QuestionFeedbackContent feedback={feedback} /> : <>
              <p className="form-hint">这次记录未保存逐题反馈，可在讨论中请 AI 重新讲解。</p>
              {feedback?.feedback && <><h3>当时的整体验证总结</h3><div className="ai-markdown"><LearningMarkdown>{feedback.feedback}</LearningMarkdown>{'next_step' in feedback && <LearningMarkdown>{feedback.next_step}</LearningMarkdown>}</div></>}
            </>}
          </div>
        </details>
        {!discussion.turns.length && !pending && <div className="ai-empty-chat"><Bot size={24} /><h2>还有哪里没弄明白？</h2><p>可以追问反馈、比较解法，或回答拓展问题。原验证结果保持不变。</p></div>}
        {discussion.turns.map(turn => <div key={turn.id} className="discussion-turn">
          {turn.status === 'purged' ? <p>这轮讨论内容已删除。</p> : <>
            <LearningMessage role="user"><div className="ai-message-content">{turn.user_content ?? ''}</div></LearningMessage>
            <LearningMessage role="assistant" state={turn.status === 'running' ? 'streaming' : turn.status === 'failed' ? (turn.reason === 'cancelled' ? 'canceled' : 'failed') : undefined} status={turn.status === 'running' ? '生成中' : turn.status === 'failed' ? (turn.reason === 'cancelled' ? '已取消' : '失败') : undefined}>
              {turn.reasoning_content && <ReasoningBlock content={turn.reasoning_content} streaming={turn.status === 'running'} />}
              {turn.assistant_content && <div className="ai-message-content ai-markdown"><LearningMarkdown>{turn.assistant_content}</LearningMarkdown></div>}
              {turn.status === 'failed' && <div role="status"><p>{turn.reason === 'cancelled' ? '已取消生成，已收到的内容保留。' : '这次回复未完成，问题和已收到的内容已保存。'}</p><button className="button button--quiet" type="button" disabled={busy || running} onClick={() => void send(turn.user_content ?? '', turn.request_key, true)}>重试这条问题</button></div>}
              {turn.status === 'running' && !turn.assistant_content && <p className="ai-message-content" role="status">…</p>}
              {turn.status === 'succeeded' && turn.sources.length === 0 && <p className="form-hint">{turn.history_searched ? '本轮检索没有找到匹配的历史记录。' : '本轮依据这道题和当前讨论回答，未检索其他历史。'}</p>}
              {turn.sources.length > 0 && <DiscussionSources sources={turn.sources} />}
            </LearningMessage>
          </>}
        </div>)}
        {pending && <>
          <LearningMessage role="user" state={pending.failed ? 'failed' : undefined} status={pending.failed ? '发送未确认' : '发送中'}><div className="ai-message-content">{pending.content}</div></LearningMessage>
          {pending.failed ? <button className="button button--quiet ai-retry-button" type="button" onClick={() => void send(pending.content, pending.key)}>重试发送</button> : <LearningMessage role="assistant" status="生成中"><div className="ai-message-content">…</div></LearningMessage>}
        </>}
      </>}
    </LearningChatPanel>
  </section>;
}
