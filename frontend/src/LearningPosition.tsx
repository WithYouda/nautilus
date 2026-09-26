import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  generateLearningPosition,
  getLearningPosition,
  saveLearningPosition,
  type AiMessage,
  type LearningPosition as LearningPositionRecord,
  type PositionRevision,
} from "./api";
import "./styles/learning-position.css";

type Props = {
  sessionId: string;
  conversationId: string | null;
  visibleMessages: AiMessage[];
  chatBusy: boolean;
};

function errorMessage(reason: unknown, fallback: string) {
  if (reason instanceof ApiError && reason.status === 409) return "位置记录已变化，请重新载入后再试。";
  return reason instanceof Error ? reason.message : fallback;
}

function SourceExcerpt({ revision, messages }: { revision: PositionRevision; messages: AiMessage[] }) {
  if (!revision.basis_message_ids.length) return null;
  const sources = revision.basis_message_ids.map(id => messages.find(message => message.id === id));
  return <details className="learning-position__sources">
    <summary>查看依据对话</summary>
    {sources.map((message, index) => message
      ? <div className="learning-position__excerpt" key={message.id}>
          <b>{message.role === "assistant" ? "AI" : "我"}</b>
          <p>{message.content.slice(0, 240)}{message.content.length > 240 ? "…" : ""}</p>
          {message.content.length > 240 && <details><summary>展开完整消息</summary><p>{message.content}</p></details>}
        </div>
      : <p className="learning-position__missing" key={`${revision.basis_message_ids[index]}:${index}`}>这条依据不在当前对话路径中。</p>)}
  </details>;
}

export default function LearningPosition({ sessionId, conversationId, visibleMessages, chatBusy }: Props) {
  const anchor = [...visibleMessages].reverse().find(message => message.role === "assistant" && message.status === "complete");
  const anchorId = anchor?.id ?? null;
  const [record, setRecord] = useState<LearningPositionRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<"generate" | "save" | null>(null);
  const [editing, setEditing] = useState(false);
  const [currentDraft, setCurrentDraft] = useState("");
  const [nextDraft, setNextDraft] = useState("");
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const operationRef = useRef<AbortController | null>(null);

  useEffect(() => {
    operationRef.current?.abort();
    operationRef.current = null;
    setRecord(null);
    setBusy(null);
    setEditing(false);
    setError("");
    if (!conversationId || !anchorId) { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    getLearningPosition(sessionId, conversationId, anchorId, controller.signal)
      .then(setRecord)
      .catch(reason => { if (!controller.signal.aborted) setError(errorMessage(reason, "位置记录读取失败")); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); operationRef.current?.abort(); };
  }, [sessionId, conversationId, anchorId, reload]);

  const revisions = record?.message_id === anchorId ? record.revisions : [];
  const latest = revisions.at(-1);

  function startEdit() {
    setCurrentDraft(latest?.current ?? "");
    setNextDraft(latest?.next ?? "");
    setEditing(true);
    setError("");
  }

  async function save() {
    if (!conversationId || !anchorId || busy || !currentDraft.trim()) return;
    const controller = new AbortController();
    operationRef.current = controller;
    setBusy("save");
    setError("");
    try {
      const updated = await saveLearningPosition(sessionId, {
        conversation_id: conversationId,
        message_id: anchorId,
        expected_revision: revisions.length,
        current: currentDraft.trim(),
        next: nextDraft.trim(),
      }, controller.signal);
      if (!controller.signal.aborted) { setRecord(updated); setEditing(false); }
    } catch (reason) {
      if (!controller.signal.aborted) setError(errorMessage(reason, "保存失败"));
    } finally {
      if (!controller.signal.aborted) setBusy(null);
      if (operationRef.current === controller) operationRef.current = null;
    }
  }

  async function generate() {
    if (!conversationId || !anchorId || busy || chatBusy) return;
    const controller = new AbortController();
    operationRef.current = controller;
    setBusy("generate");
    setError("");
    try {
      const updated = await generateLearningPosition(sessionId, {
        conversation_id: conversationId,
        message_id: anchorId,
        expected_revision: revisions.length,
      }, controller.signal);
      if (!controller.signal.aborted) { setRecord(updated); setEditing(false); }
    } catch (reason) {
      if (!controller.signal.aborted) setError(errorMessage(reason, "AI整理失败"));
    } finally {
      if (!controller.signal.aborted) setBusy(null);
      if (operationRef.current === controller) operationRef.current = null;
    }
  }

  function cancelGeneration() {
    operationRef.current?.abort();
    operationRef.current = null;
    setBusy(null);
  }

  if (!conversationId || !anchorId) return <div className="learning-position" aria-label="学习位置"><p className="learning-position__empty">尚无可整理的对话。完成一轮回答后可记录当前位置。</p></div>;

  return <div className="learning-position" aria-label="学习位置">
    <div className="learning-position__top">
      <b>学习位置</b>
      <span>跟随当前选中的回答版本</span>
    </div>
    {loading ? <p className="learning-position__empty" role="status">正在读取位置记录…</p> : editing ? <div className="learning-position__editor">
      <label>当前讨论
        <textarea value={currentDraft} onChange={event => setCurrentDraft(event.target.value)} maxLength={500} rows={2} placeholder="目前讨论到哪里？" />
      </label>
      <label>建议下一步
        <textarea value={nextDraft} onChange={event => setNextDraft(event.target.value)} maxLength={500} rows={2} placeholder="可以留空，稍后再决定" />
      </label>
      <div className="learning-position__actions">
        <button className="button button--accent button--compact" type="button" disabled={busy !== null || !currentDraft.trim()} onClick={() => void save()}>{busy === "save" ? "保存中…" : "保存记录"}</button>
        <button className="button button--quiet button--compact" type="button" disabled={busy !== null} onClick={() => { setEditing(false); setError(""); }}>取消</button>
      </div>
    </div> : <>
      <div className="learning-position__columns">
        <div><span className="learning-position__label">当前讨论</span><p>{latest?.current || "未记录，请整理或自己填写。"}</p></div>
        <div><span className="learning-position__label">建议下一步</span><p>{latest ? latest.next || "暂未确定下一步。" : "尚无建议。"}</p></div>
      </div>
      {latest && <div className="learning-position__meta"><span>{latest.source === "ai" ? "AI概括" : "我的记录"}</span><time dateTime={latest.created_at}>{new Date(latest.created_at).toLocaleString("zh-CN")}</time></div>}
      {latest && <SourceExcerpt revision={latest} messages={visibleMessages} />}
      <div className="learning-position__actions">
        <button className="button button--quiet button--compact" type="button" disabled={busy !== null} onClick={startEdit}>{latest ? "修改记录" : "自己填写"}</button>
        {busy === "generate"
          ? <button className="button button--quiet button--compact" type="button" onClick={cancelGeneration}>取消整理</button>
          : <button className="button button--quiet button--compact" type="button" disabled={chatBusy || busy !== null} onClick={() => void generate()}>{latest ? "重新整理" : "AI整理"}</button>}
      </div>
      {revisions.length > 1 && <details className="learning-position__history"><summary>查看修订记录（{revisions.length - 1}）</summary>
        {revisions.slice(0, -1).reverse().map((revision, index) => <div key={`${revision.created_at}:${index}`} className="learning-position__history-item">
          <span>{revision.source === "ai" ? "AI概括" : "我的记录"} · {new Date(revision.created_at).toLocaleString("zh-CN")}</span>
          <p>当前讨论：{revision.current}</p><p>建议下一步：{revision.next || "暂未确定"}</p>
          <SourceExcerpt revision={revision} messages={visibleMessages} />
        </div>)}
      </details>}
    </>}
    {error && <div className="learning-position__error" role="alert">{error} <button className="text-button" type="button" onClick={() => setReload(value => value + 1)}>重新载入</button></div>}
  </div>;
}
