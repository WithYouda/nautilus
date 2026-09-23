import LearningMarkdown from './LearningMarkdown';
import type { QuestionFeedback } from './api';

export default function QuestionFeedbackContent({ feedback, onReadSolution }: { feedback: QuestionFeedback; onReadSolution?: () => void }) {
  return <section className="question-feedback" aria-label="本题 AI 反馈">
    <h4>AI 反馈与建议</h4>
    <div className="ai-markdown"><LearningMarkdown>{feedback.feedback}</LearningMarkdown></div>
    {feedback.unmet_requirements.length > 0 && <div><strong>本题仍需补充</strong><ul>{feedback.unmet_requirements.map((value, i) => <li key={i}><LearningMarkdown>{value}</LearningMarkdown></li>)}</ul></div>}
    {feedback.reference_answer && <details onToggle={event => { if (event.currentTarget.open) onReadSolution?.(); }}>
      <summary>AI 参考解法（可继续质疑）</summary><div className="ai-markdown"><LearningMarkdown>{feedback.reference_answer}</LearningMarkdown></div>
    </details>}
    {feedback.follow_up_questions.length > 0 && <div><h4>可选拓展问题</h4><ul>{feedback.follow_up_questions.map((value, i) => <li key={i}><LearningMarkdown>{value}</LearningMarkdown></li>)}</ul><p className="form-hint">可在本题讨论中继续回答，不影响原验证结果。</p></div>}
  </section>;
}
