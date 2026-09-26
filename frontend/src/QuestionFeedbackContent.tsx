import LearningMarkdown from './LearningMarkdown';
import { useState } from 'react';
import type { QuestionFeedback, ReferenceHelpDisplay } from './api';

export default function QuestionFeedbackContent({ feedback, onReadSolution, helpDisplay, onRecordDisplay }: { feedback: QuestionFeedback; onReadSolution?: () => void; helpDisplay?: ReferenceHelpDisplay | null; onRecordDisplay?: () => Promise<ReferenceHelpDisplay> }) {
  const [recorded, setRecorded] = useState<ReferenceHelpDisplay | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const display = helpDisplay ?? recorded;
  async function record() {
    if (!onRecordDisplay || display || busy) return;
    setBusy(true); setError(false);
    try { setRecorded(await onRecordDisplay()); } catch { setError(true); } finally { setBusy(false); }
  }
  return <section className="question-feedback" aria-label="本题 AI 反馈">
    <h4>AI 反馈与建议</h4>
    <div className="ai-markdown"><LearningMarkdown>{feedback.feedback}</LearningMarkdown></div>
    {feedback.unmet_requirements.length > 0 && <div><strong>本题仍需补充</strong><ul>{feedback.unmet_requirements.map((value, i) => <li key={i}><LearningMarkdown>{value}</LearningMarkdown></li>)}</ul></div>}
    {feedback.reference_answer && <details onToggle={event => { if (event.currentTarget.open) { onReadSolution?.(); void record(); } }}>
      <summary>AI 参考解法（可继续质疑）</summary><div className="ai-markdown"><LearningMarkdown>{feedback.reference_answer}</LearningMarkdown></div>
      {onRecordDisplay && <p className="form-hint">页面展示记录：{display ? new Date(display.at).toLocaleString() : error ? '保存失败' : busy ? '保存中…' : '尚未记录'}。展示不代表已阅读或理解；无记录不证明独立完成。</p>}
      {error && <button className="text-button" type="button" onClick={() => void record()}>重试保存展示记录</button>}
    </details>}
    {feedback.follow_up_questions.length > 0 && <div><h4>可选拓展问题</h4><ul>{feedback.follow_up_questions.map((value, i) => <li key={i}><LearningMarkdown>{value}</LearningMarkdown></li>)}</ul><p className="form-hint">可在本题讨论中继续回答，不影响原验证结果。</p></div>}
  </section>;
}
