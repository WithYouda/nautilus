import { ArrowUpRight, Bot, MessageSquareText, SlidersHorizontal } from "lucide-react";
import type { AiProvider, PlanDetail, PlanSummary, TodayDashboard } from "./api";

type CompanionContext =
  | { scope: "global"; plans: PlanSummary[]; dashboard: TodayDashboard | null }
  | { scope: "plan"; plan: PlanDetail };

export default function AiCompanionPanel({
  context,
  provider,
  onOpenLearning,
  onOpenProvider,
}: {
  context: CompanionContext;
  provider: AiProvider | null;
  onOpenLearning: () => void;
  onOpenProvider: () => void;
}) {
  const ready = Boolean(provider?.enabled && provider.has_api_key);
  const isPlan = context.scope === "plan";
  const title = isPlan ? context.plan.title : "全局学习工作区";
  const route = isPlan
    ? `${context.plan.summary.subject_count} 个科目 / ${context.plan.summary.task_count} 项任务`
    : `${context.plans.length} 个活动计划 / 今日 ${context.dashboard?.summary.total ?? 0} 项任务`;
  const firstMetric = isPlan
    ? { label: "计划进度", value: `${context.plan.summary.progress}%` }
    : { label: "今日完成", value: `${context.dashboard?.summary.completed ?? 0} / ${context.dashboard?.summary.total ?? 0}` };
  const secondMetric = isPlan
    ? { label: "学习量", value: `${context.plan.summary.estimate_minutes} 分钟` }
    : { label: "计划任务", value: String(context.plans.reduce((sum, plan) => sum + plan.task_count, 0)) };

  return (
    <aside className="v6-companion" aria-label="AI 学习伙伴">
      <header className="v6-companion-header">
        <div><span>{isPlan ? "CONTEXT / PLAN" : "CONTEXT / GLOBAL"}</span><h2>AI 学习伙伴</h2></div>
        <Bot size={18} aria-hidden="true" />
      </header>

      <section className="v6-companion-context">
        <span>{isPlan ? "计划级上下文" : "全局上下文"}</span>
        <strong>{title}</strong>
        <p>{route}</p>
        <dl><div><dt>{firstMetric.label}</dt><dd>{firstMetric.value}</dd></div><div><dt>{secondMetric.label}</dt><dd>{secondMetric.value}</dd></div></dl>
      </section>

      <section className="v6-companion-note">
        <span>NAUTILUS</span>
        <p>{ready
          ? isPlan
            ? "我会围绕这个计划的科目、任务、排期和进度协助分析，不会因你点击某个任务而自动改变范围。"
            : "我会综合多个计划、今日任务、逾期项和近期截止项，协助安排整体学习节奏。"
          : "先配置一个 OpenAI 兼容提供方，再开始真实的流式学习对话。"}</p>
      </section>

      <div className="v6-companion-spacer" />

      <section className="v6-companion-compose">
        <div className="v6-companion-placeholder"><MessageSquareText size={16} /><span>{isPlan ? "围绕当前计划继续提问" : "从全局视角开始规划"}</span></div>
        <div className="v6-companion-actions">
          <button className="v6-link-button" type="button" onClick={onOpenProvider}><SlidersHorizontal size={14} />提供方设置</button>
          <button className="button button--accent button--with-icon" type="button" onClick={onOpenLearning}>进入学习室<ArrowUpRight size={15} /></button>
        </div>
      </section>
    </aside>
  );
}
