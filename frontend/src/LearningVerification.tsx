import LearningMarkdown from "./LearningMarkdown";
import VerificationReview from "./VerificationReview";
import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { ArrowLeft, Send, ShieldCheck } from "lucide-react";
import {
  startLearningVerification,
  submitLearningVerification,
  listLearningVerifications,
  evaluateLearningVerification,
  confirmLearningVerification,
  analyzeVerificationEvidence,
  purgeVerification,
  getVerificationReview,
  type LearningRoomBrief,
  type LearningVerification,
} from "./api";

type VerificationMode = "ai_challenge" | "user_material";
type VerificationDraft = {
  responses: Record<string, string>;
  material: string;
  learnerWork: string;
  independent: boolean;
  editing: boolean;
};

function requestId() {
  return typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

export default function LearningVerification({
  brief,
  onBack,
  onCompleted,
  onDiscuss,
}: {
  brief: LearningRoomBrief;
  onBack: () => void;
  onCompleted?: () => void;
  onDiscuss: (id: string) => void;
}) {
  const [mode, setMode] = useState<VerificationMode>("ai_challenge");
  const [verification, setVerification] = useState<LearningVerification | null>(null);
  const [attempts, setAttempts] = useState<LearningVerification[]>([]);
  const drafts = useRef(new Map<string, VerificationDraft>());
  const [responses, setResponses] = useState<Record<string, string>>({});
  const [material, setMaterial] = useState("");
  const [learnerWork, setLearnerWork] = useState("");
  const [independent, setIndependent] = useState(false);
  const [stopConfirmed, setStopConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const submissionKey = useRef(requestId());
  const startKey = useRef(requestId());

  useEffect(() => {
    let active = true;
    setLoading(true);
    listLearningVerifications().then((items) => {
      if (!active) return;
      const related = items.filter((item) => item.action_id === brief.action_id && item.delegation_id === brief.delegation_id
        && item.session_id === (brief.session_id ?? null));
      setAttempts(related);
      drafts.current.clear();
      setResponses({}); setMaterial(""); setLearnerWork(""); setIndependent(false); setEditing(false); setStopConfirmed(false);
      const current = related[0];
      setVerification(current ?? null);
      if (current) setMode(current.mode);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "验证恢复失败，请重新进入");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [brief.action_id, brief.delegation_id, brief.session_id]);

  function changed() {
    submissionKey.current = requestId();
    setStopConfirmed(false);
  }

  function updateVerification(next: LearningVerification) {
    setVerification(next);
    setAttempts((current) => [next, ...current.filter((item) => item.id !== next.id)]);
  }

  function changeMode(nextMode: VerificationMode) {
    if (busy || nextMode === mode || attempts.some((item) => item.status === "passed")) return;
    if (verification && !verification.content_purged) {
      drafts.current.set(verification.id, { responses, material, learnerWork, independent, editing });
    }
    const next = attempts.find((item) => item.mode === nextMode && !item.content_purged) ?? null;
    if (!next && attempts.some((item) => item.mode === nextMode)) startKey.current = requestId();
    const draft = next ? drafts.current.get(next.id) : undefined;
    setMode(nextMode);
    setVerification(next);
    setResponses(draft?.responses ?? {});
    setMaterial(draft?.material ?? "");
    setLearnerWork(draft?.learnerWork ?? "");
    setIndependent(draft?.independent ?? false);
    setEditing(draft?.editing ?? false);
    setError("");
    changed();
  }

  async function begin() {
    if (!brief.action_id || !brief.delegation_id) {
      setError("当前学习安排缺少验证关联，暂时不能开始验证");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const next = await startLearningVerification({
        action_id: brief.action_id,
        delegation_id: brief.delegation_id,
        session_id: brief.session_id ?? null,
        mode,
        request_key: `verification:${brief.delegation_id}:${brief.session_id ?? "none"}:${mode}:${startKey.current}`,
      });
      updateVerification(next);
      setResponses({});
      setMaterial("");
      setLearnerWork("");
      setIndependent(false);
      setStopConfirmed(false);
      setEditing(true);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "验证启动失败");
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!verification || busy) return;
    setBusy(true);
    setError("");
    try {
      const saved = await submitLearningVerification(verification.id, {
        responses,
        material,
        learner_work: learnerWork,
        evidence_condition: independent ? "independent" : "with_materials",
        request_key: submissionKey.current,
      });
      updateVerification(saved);
      setEditing(false);
      const next = await evaluateLearningVerification(saved.id, saved.latest_submission_id!, requestId());
      updateVerification(next);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "验证提交失败");
    } finally {
      setBusy(false);
    }
  }

  async function retryEvaluation() {
    if (!verification?.latest_submission_id || busy) return;
    setBusy(true);
    setError("");
    try {
      updateVerification(await evaluateLearningVerification(verification.id, verification.latest_submission_id, requestId()));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "评估重试失败，作答已保存");
    } finally { setBusy(false); }
  }

  async function confirm() {
    if (!verification?.latest_submission_id || !verification.evaluation || !stopConfirmed || busy) return;
    setBusy(true);
    setError("");
    try {
      const next = await confirmLearningVerification(verification.id, verification.latest_submission_id, verification.evaluation.id);
      updateVerification(next);
      if (next.status === "passed") onCompleted?.();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "完成确认失败，评估结果已保留");
    } finally { setBusy(false); }
  }

  async function readMaterial(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      setMaterial(await file.text());
      changed();
      setError("");
    } catch {
      setError("这个文件暂时无法读取，请直接粘贴文本");
    }
  }

  async function collectEvidence() {
    if (!verification || busy) return;
    setBusy(true);
    setError("");
    try { updateVerification(await analyzeVerificationEvidence(verification.id)); }
    catch (reason: unknown) { setError(reason instanceof Error ? reason.message : "证据分析失败，作答仍保留"); }
    finally { setBusy(false); }
  }

  async function removeMaterial() {
    if (!verification || busy) return;
    setBusy(true);
    try {
      const detail = await getVerificationReview(verification.id);
      if (!window.confirm(`彻底删除本次验证的全部提交、题目及评估？另有 ${detail.purge_discussion_count} 段关联或引用它的题目讨论正文会一并清除。依赖证据失效，完成记录保留，内容不可恢复。`)) return;
      updateVerification(await purgeVerification(verification.id));
      drafts.current.delete(verification.id);
      setResponses({}); setMaterial(""); setLearnerWork(""); setEditing(false);
    } catch (reason: unknown) { setError(reason instanceof Error ? reason.message : "删除失败"); }
    finally { setBusy(false); }
  }

  const questions = verification?.challenge.questions ?? [];
  const completed = verification?.status === "passed";
  const answering = !verification?.latest_submission_id || editing;
  const canConfirm = !answering && verification?.result?.passed && verification.stop_condition_met === true;

  return (
    <section className="verification-page" aria-label="学习验证">
      <header className="verification-page__header">
        <button className="icon-button" type="button" onClick={onBack} aria-label="返回学习室" title="返回学习室">
          <ArrowLeft size={18} />
        </button>
        <div>
          <p className="eyebrow">ASSESSMENT</p>
          <h1>验证本次学习</h1>
          <p>{brief.action_title}</p>
        </div>
      </header>

      {!loading && !completed && <section className="verification-mode-picker" aria-label="选择验证方式">
          <div className="verification-options" role="group" aria-label="验证方式">
            <button type="button" className={mode === "ai_challenge" ? "is-active" : ""} aria-pressed={mode === "ai_challenge"} disabled={busy} onClick={() => changeMode("ai_challenge")}>
              <strong>AI 出题验证</strong>
              <span>按本次成果设计场景题、项目题、简答题或判断题</span>
            </button>
            <button type="button" className={mode === "user_material" ? "is-active" : ""} aria-pressed={mode === "user_material"} disabled={busy} onClick={() => changeMode("user_material")}>
              <strong>提交我的材料</strong>
              <span>粘贴题目、标准答案、项目结果或自己的理解，由 AI 评估</span>
            </button>
          </div>
        <p className="form-hint">可随时切换方式；已保存的记录会保留，未提交输入仅在当前页面内保留。</p>
      </section>}

      {error && <div className="workspace-alert" role="alert">{error}</div>}

      {loading ? <p role="status">正在恢复验证记录…</p> : !verification ? (
        <section className="verification-panel">
          <div className="verification-panel__intro">
            <ShieldCheck size={20} />
            <div>
              <strong>现在单独验证本次学习</strong>
              <p>使用当前学习室所选模型出题和评估。提交后再查看结果和下一步建议。</p>
            </div>
          </div>
          <button className="button button--accent" type="button" onClick={() => void begin()} disabled={busy}>
            {busy ? "正在准备验证" : "开始验证"}
          </button>
        </section>
      ) : verification.content_purged ? (
        <section className="verification-panel">
          <p>{verification.verification_purged ? "验证内容已彻底删除" : "本次作答已彻底删除，题目及其他提交可能仍有保留"}，相关证据已失效。已有行动完成记录保留。</p>
          {!verification.verification_purged && <button className="button button--quiet" type="button" onClick={() => void removeMaterial()} disabled={busy}>彻底删除本次验证的剩余内容</button>}
          {!completed && <button className="button button--quiet" type="button" onClick={() => { startKey.current = requestId(); setVerification(null); }} disabled={busy}>重新准备验证</button>}
          <button className="button button--quiet" type="button" onClick={onBack}>返回学习室</button>
        </section>
      ) : (
        <form className="verification-panel verification-panel--exam" onSubmit={submit}>
          <div className="verification-panel__exam-head">
            <div>
              <span>{completed ? "本次委托已完成" : answering ? "验证进行中" : "验证记录"}</span>
              <strong>{questions.length ? `${questions.length} 道验证任务` : "材料评估"}</strong>
            </div>
            <span className="verification-private-note">{answering ? "先独立作答，提交后可查看反馈" : "作答与反馈已保存"}</span>
          </div>

          {verification.challenge.instructions && <p className="verification-instructions">{verification.challenge.instructions}</p>}
          {answering && questions.map((question, index) => (
            <fieldset className="verification-question" key={question.id}>
              <legend>{index + 1}. {question.type === "project" ? "项目任务" : question.type === "scenario" ? "场景任务" : question.type === "true_false" ? "判断题" : "简答题"}</legend>
              <div className="ai-markdown"><LearningMarkdown>{question.prompt}</LearningMarkdown></div>
              {question.source_urls.length > 0 && (
                <div className="verification-sources">
                  <small>Provider 提供的来源，系统未独立核验</small>
                  {question.source_urls.map((url) => <a key={url} href={url} target="_blank" rel="noreferrer">参考来源</a>)}
                </div>
              )}
              {answering && <textarea
                value={responses[question.id] ?? ""}
                onChange={(event) => { changed(); setResponses((current) => ({ ...current, [question.id]: event.target.value })); }}
                rows={5}
                placeholder="写出你的判断、过程或结果"
                disabled={completed || busy}
              />}
            </fieldset>
          ))}

          {verification.mode === "user_material" && answering && (<>
            <label className="field verification-material">
              <span>题目、参考资料或标准答案（可选，不作为能力证据）</span>
              <input type="file" accept=".txt,.md,.json,.py,.js,.ts" onChange={(event) => void readMaterial(event)} disabled={completed || busy} />
              <textarea value={material} onChange={(event) => { changed(); setMaterial(event.target.value); }} rows={5} placeholder="粘贴题目或参考材料" disabled={completed || busy} />
            </label>
            <label className="field"><span>我的过程、理解或项目结果</span><textarea value={learnerWork} onChange={(event) => { changed(); setLearnerWork(event.target.value); }} rows={8} placeholder="说明你自己做了什么、如何判断，以及实际结果" disabled={completed || busy} /></label>
          </>)}

          {!answering && verification.latest_submission_id && <VerificationReview
            id={verification.id} refreshKey={`${verification.latest_submission_id}:${verification.evaluation?.id}:${verification.evaluation?.status}`}
            onDiscuss={onDiscuss} onPurged={value => { drafts.current.delete(value.id); setResponses({}); setMaterial(""); setLearnerWork(""); updateVerification(value); }} onReadSolution={() => setIndependent(false)}
          />}
          {completed && <p>{verification.action_completed ? "停止条件已确认，学习行动已完成。" : "本次委托已完成；其他委托仍开放，学习行动可以继续。"}</p>}

          {!answering && verification.latest_submission_id && !completed && <p role="status">作答已保存。{verification.evaluation?.status === "failed" ? (verification.evaluation.message ?? "AI 评估未完成，可重试已保存的作答。") : verification.evaluation?.status === "running" ? "评估尚未返回；如请求已中断，可手动重试。" : ""}</p>}
          {!completed && canConfirm && <>
            <label className="verification-stop-check">
              <input type="checkbox" checked={stopConfirmed} onChange={(event) => setStopConfirmed(event.target.checked)} disabled={busy} />
              <span>我已核对结果，并确认满足停止条件：{verification.stop_conditions}</span>
            </label>
            <button className="button button--accent" type="button" onClick={() => void confirm()} disabled={busy || !stopConfirmed}>确认完成本次委托</button>
          </>}
          {!completed && answering && <button className="button button--accent" type="submit" disabled={busy}><Send size={16} />{busy ? "正在保存或评估" : "保存作答并验证"}</button>}
          {!completed && answering && <label className="verification-stop-check"><input type="checkbox" checked={independent} onChange={(event) => { changed(); setIndependent(event.target.checked); }} disabled={busy} /><span>本次作答由我独立完成，未查阅答案、资料或接受提示。未勾选仍可保存并评估；看过本次反馈后的补答按有帮助记录。</span></label>}
          {!completed && !answering && <>
            {verification.evaluation?.status !== "succeeded" && <button className="button button--accent" type="button" onClick={() => void retryEvaluation()} disabled={busy}>重试已保存的作答</button>}
            <button className="button button--quiet" type="button" onClick={() => { changed(); setIndependent(false); setEditing(true); }} disabled={busy}>提交新的作答</button>
            <button className="button button--quiet" type="button" onClick={() => { startKey.current = requestId(); setVerification(null); }} disabled={busy}>重新准备验证</button>
          </>}
          {completed && <button className="button button--quiet" type="button" onClick={onBack}><ArrowLeft size={16} />返回学习室</button>}
          {!answering && verification.evaluation?.status === "succeeded" && <div>
            <p>验证结果与成果证据分别处理。{brief.criterion_id ? "按已审核标准分析后，候选证据需在记录与复核工具中审阅。" : "当前未绑定合格标准，只保存产出和反馈，不派生成果状态。"}</p>
            {brief.criterion_id && <button className="button button--quiet" type="button" onClick={() => void collectEvidence()} disabled={busy || verification.evidence?.status === "succeeded"}>按已审核标准分析证据</button>}
            {verification.evidence && <p role="status">{verification.evidence.status === "succeeded" ? "候选证据已生成，等待复核；这不代表已经掌握。" : "证据分析未完成，作答已保留，可以重试。"}</p>}
          </div>}
          {answering && <details className="review-actions"><summary>更多操作</summary><p>仅在不想保留这些内容时使用，删除不可恢复。</p><button className="button button--danger" type="button" onClick={() => void removeMaterial()} disabled={busy}>彻底删除本次验证内容</button></details>}
        </form>
      )}
    </section>
  );
}
