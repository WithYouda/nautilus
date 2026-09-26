# Codex Astra + Sol 多 Agent 额度消耗诊断与优化建议

> 日期：2026-09-26
>
> 文档性质：**工程工作流研究记录 / 诊断指南 / 非规范性建议（non-normative）**
>
> 本文用于解释和排查 Nautilus 开发过程中 Codex / Work 的额度消耗，并给出可选优化策略。它**不修改** `AGENTS.md` 中已经确认的委派原则，也不构成新的产品需求、开发任务或强制规范。
>
> 当前 `AGENTS.md` 已经要求：Astra 负责主导复杂判断；Sol 用于边界清晰的委派任务；默认从 1–2 个 worker 开始；只并行真正独立的工作；向 worker 提供最小充分上下文；worker 不应自行递归委派；最终由 lead 集成与验收。本文主要补充这些原则背后的**额度成本模型、异常排查方法和观测手段**。

## 1. 当前观测

当前常用开发方式：

- Lead：`gpt-6-astra`，reasoning effort = `high`
- Subagents：通常 2–3 个 `gpt-5.6-sol`，目标 reasoning effort = `medium`
- 使用方式：Lead 负责需求解释、架构、复杂诊断和集成；Sol worker 做代码检查、实现、验证等边界任务

2026-09-26 的一次实际观测：

- 大约从 16:xx 工作到 20:13；
- weekly allowance 从接近 100% 降到约 72%；
- 即约 4 小时墙钟时间消耗约 28% weekly allowance；
- 粗略等价于 **约 7% weekly allowance / wall-clock hour**。

这个数字只能作为当前工作流的基线，**不能直接解释为“每小时固定消耗 7%”**。模型、reasoning effort、上下文长度、缓存、并行 worker 数量、工具调用、测试循环和任务类型都会改变实际消耗。

## 2. 为什么 4 小时墙钟时间可能烧掉很多额度

### 2.1 墙钟时间不等于 agent 工作量

当一个 Astra lead 与 2–3 个 Sol worker 同时工作时，1 小时墙钟时间可能包含：

- 1 小时 Astra lead 活动；
- 2–3 小时累计 Sol worker 活动；
- Lead 对 worker 结果的重新阅读、集成和复核；
- worker 自己的多轮工具调用、测试、重读和修正。

因此 1 小时墙钟时间可能接近 3–4 个 agent-hours，而不是“只运行了 Astra 1 小时”。

社区已经有非常接近的多 Agent 遥测案例：一个 GPT-6 Astra High 主任务加 3 个 Astra High children，在约 4.5 小时内消耗了约 86% Prolite weekly allowance，并在本地记录约 198M raw tokens。这个案例比 Nautilus 当前配置更激进，但说明并行 children 可以迅速放大吞吐和额度消耗。

### 2.2 Astra High 本身属于高成本工作模式

OpenAI 官方明确说明：

- Work 与 Codex 共用计划内 allowance；
- allowance 同时可能受 5 小时窗口和 weekly window 约束；
- 更大的输入/输出、更高 reasoning effort、Fast mode 和多步骤任务都会提高用量；
- Pro 5x 的官方估算中，Astra 每 5 小时约 25–225 条 local messages，Sol 约 50–500 条；
- 这些不是固定消息数，实际消耗取决于任务、模型和设置。

因此 Astra High 适合真正需要深度推理的阶段，但把所有普通探索和局部实现也留给 Astra High，会直接压缩 weekly runway。

### 2.3 Subagent 不是“免费线程”

即使 child 使用 Sol Medium，它仍是独立模型执行线程，需要：

- 初始化任务上下文；
- 读取任务相关文件；
- 进行自己的推理和工具调用；
- 接收测试/命令输出；
- 多轮修正；
- 最后把结果交还 lead。

如果同时启动三个 worker，总消耗应理解为**多个并发模型工作流的总和**，而不是一个主任务只多一点开销。

## 3. 最值得优先排查的四个问题

### 3.1 Child 实际是否真的运行在 Sol Medium

这是第一优先级。

Codex 社区已有多个公开 issue 报告：请求的 subagent model / reasoning effort 与实际 child runtime 不一致。例如：

- 明确请求 `gpt-5.6-sol + medium`，实际 child rollout 中记录为 `high`；
- 某些 role/profile 组合会让 child 继承 parent 的 profile；
- 某些 spawn/role 路径可能丢失显式 model override。

这些 issue 并不能证明当前 Nautilus 会话一定受影响，但意味着**不能只相信提示词、AGENTS.md 或 spawn 请求里的目标配置**。

#### 排查方法

对每个新 child：

1. 记录 parent 请求的：
   - model
   - reasoning effort
   - task / role
   - fork mode
2. child 启动后检查其实际 runtime / rollout metadata；
3. 重点确认最新的 `turn_context` 或对应运行元数据中的：
   - 实际 `model`
   - 实际 `effort`
   - collaboration / role 设置
4. 如果请求是 Sol Medium，但实际出现：
   - Sol High：额度会明显高于预期；
   - Astra High：说明 worker 降级策略实际上没有生效，应立即停止继续扩张并发。

**建议：在确认当前 Codex 版本能够可靠执行 model/effort override 前，把“验证实际 child runtime”作为每次新版本/新环境的抽样检查，而不是永久人工检查每个 child。**

### 3.2 Child 是否继承了过多 parent history

这是第二优先级。

Codex 的 `fork_turns` 会影响 child 带入多少父线程历史。对于边界清晰的 worker，如果 child 不需要完整会话历史，却继承了长时间积累的 parent context，会产生显著的重复上下文成本。

一个公开的 MultiAgentV2 遥测案例记录了 74 个 subagents、约 5.39B 本地 raw tokens。作者按 `fork_turns` 分组后发现：

- 30 个携带 `all / 3 / 5` 历史的 agents 累积约 4.824B tokens；
- 44 个 `fork_turns="none"` agents 累积约 153M tokens。

这些 agents 做的任务不同，因此**不能把差距全部归因于 fork mode**；但它足以说明：长 parent history + history-carrying forks 是需要重点监控的高风险组合。

#### 建议

对于普通 bounded worker，优先：

```text
fork_turns = "none"
```

然后在 handoff 中明确提供最小充分上下文：

- 任务目标；
- 相关文件；
- 必需 specification section；
- 已确认接口；
- invariants；
- allowed edit scope；
- acceptance checks。

只有 child 的任务确实依赖最近几轮决策时，才显式携带有限 history。

### 3.3 是否发生重复探索、重复 review、重复测试

常见的隐藏浪费不是模型选得太强，而是三个 worker 在做高度重叠的事情。

高风险委派：

```text
Agent A：全面检查这个实现
Agent B：独立全面 review 一遍
Agent C：再从架构角度全面检查
```

这三个 agent 往往会重复：

- 读取同一批文件；
- grep 同一批符号；
- 重建同一份 mental model；
- 跑相似测试；
- 输出大量重叠发现。

更好的拆分：

```text
Agent A：只检查 DB schema / persistence contract
Agent B：只检查 retrieval / service behavior
Agent C：只检查 frontend state / interaction contract
```

要求 scopes 尽量互斥；最终跨模块一致性由 Astra lead 做一次集成判断。

### 3.4 是否发生 child → grandchild 递归委派

这是最危险的额度失控模式之一。

公开 issue 已记录过 child 继续创建 descendants，最终形成数十个 subagents、多个层级和大量重复 review/test loop 的案例。

Nautilus 当前 `AGENTS.md` 已经规定：

> Workers do not recursively delegate unless the lead explicitly assigns that responsibility.

建议继续保持这一条，并把它当成**额度安全边界**，而不仅是工程组织习惯。

## 4. 不要直接相信“本地 raw token 总和”

排查时要区分两个东西：

1. **Settings → Usage / server-reported allowance**：判断计划额度实际下降多少；
2. **本地 rollout token telemetry**：用于分析哪个 thread、fork、模型和阶段产生了大量活动。

有公开 issue 报告，在某些版本/路径里 subagent fork 会把祖先的 `token_count` bookkeeping 复制到 child rollout，从而让“把所有 rollout token_count 简单相加”产生重复统计。

因此：

- weekly meter 的前后 delta 用来判断**真实计划额度下降**；
- 本地日志用来找**结构性原因**；
- 不要把所有 rollout 的历史 token 数直接相加后当作计费量；
- 更可靠的是看每个 child 启动后的增量、运行时长、模型/effort、fork mode 和 server usage delta。

## 5. 推荐的低风险诊断实验

目标不是为了“测额度而烧额度”，而是用最小成本确定主要问题。

每次实验建议设置停止条件：

- 最长 20–30 分钟；或
- weekly allowance 再下降约 3–5%；
- 任一条件先到即停止。

尽量选择**规模相近但不重复修改同一代码**的真实任务，不要为了 benchmark 制造无价值工作。

### 实验 A：Astra High 单线程基线

配置：

- Astra High
- 禁止 subagent
- Fast mode 关闭
- 选择一个真实、边界明确的中等任务

记录：

- 开始/结束时间；
- weekly % 前后；
- 5-hour % 前后；
- parent context 大小（如果可见）；
- 工具/测试次数；
- 本地 token 增量（仅作辅助）。

得到“Lead 单独工作”的大致基线。

### 实验 B：Astra High + 1 个 Sol Medium fresh-context child

配置：

- Lead = Astra High
- 1 个 Sol Medium child
- `fork_turns="none"`
- child task scope 明确且独立
- child 禁止再委派

重点验证：

- child 实际 runtime 确认是 Sol Medium；
- child 是否只读取指定文件；
- quota/hour 相比实验 A 增加多少；
- Lead 是否因为 integration 又重复做了 child 已完成的探索。

### 实验 C：Astra High + 2 个 Sol Medium children

仅当有两个真正独立 workstreams 时运行。

要求：

- 两个 child scopes 不重叠；
- 都使用最小上下文；
- 都禁止 descendants；
- Lead 不重复执行同样的 repo-wide exploration。

对比 B 与 C，可以判断当前工作流的并发收益是否值得额外额度。

### 暂时不建议做的实验

不要一上来测试：

- Astra High + 3 children + full history；
- xHigh / Ultra；
- child recursive delegation；
- 多轮“全面 review → 全面 fix → 再全面 review”。

这些组合在没有基线时信息价值不高，只会更快消耗 weekly allowance。

## 6. 推荐的日常委派策略

### 6.1 Lead 自己完成的小任务

以下任务通常不值得创建 child：

- 单文件小修改；
- 已知位置的查找；
- 一个简单 test failure；
- 几分钟能完成的局部 review；
- 只需要读 1–2 个文件就能回答的问题。

原因：spawn、初始化上下文、handoff、回收结果和 lead review 本身都有固定开销。

### 6.2 一个 Sol Medium worker

适合：

- 范围清晰的模块检查；
- 已确认接口下的局部实现；
- 可复现 local bug；
- 指定文件范围内的 focused review；
- 明确 acceptance checks 的验证任务。

### 6.3 两个 Sol Medium workers

作为默认并发上限更合理。

适合两个真正独立 workstreams，例如：

- worker A：DB / persistence；
- worker B：UI / state；
- Astra lead：跨模块 contract、integration、final review。

### 6.4 三个 worker

只在确实存在三个互不依赖的 workstreams 时使用。

不要因为“可以并行”就默认开满三个。优化目标应是：

> 每个 worker 节省的 lead wall-clock / reasoning 成本 > handoff + context + review + rework 成本

而不是最大化 agent 数量。

## 7. Context 管理建议

### 7.1 不要把整个会话复制给 worker

handoff 只传：

- 当前问题；
- 必要事实；
- 相关文件；
- 相关 spec section；
- interface / invariant；
- 输出要求。

避免：

- 整个 PRD；
- 整段历史讨论；
- 全部 progress docs；
- 与 worker scope 无关的架构背景。

这与当前 `AGENTS.md` 的“delegated agents 不重复 baseline reading；使用最小充分 context”完全一致。

### 7.2 Lead 长线程达到阶段边界时做 compact handoff

不要机械地“每做一步就新开 session”；新线程也可能需要重新读取仓库并失去已有缓存。

更合理的触发条件是：

- parent 已积累大量与当前阶段无关的历史；
- 当前任务从 planning 明确切换到 implementation / review；
- 后续工作只需要少量已确认结论；
- worker 一再携带无关历史。

此时先生成短 handoff / checkpoint，再开启新的 focused session，只恢复：

- confirmed decisions；
- current code state；
- next task；
- 必需文件和 checks。

## 8. Review / Test 的额度控制

建议遵循：

1. Worker 先完成自己的 focused checks；
2. 返回“改了什么 + 实际运行了什么 + 结果 + unresolved concerns”；
3. Astra lead review diff 和证据；
4. 只有共享行为、数据生命周期或真实风险需要时，lead 再扩大测试范围；
5. 不因为“review 更安心”就让多个 workers 对同一 revision 重复跑完整 suite。

这也符合当前 `AGENTS.md` 的 proportional validation 原则。

## 9. 什么时候才应该怀疑 quota / metering 异常

在以下因素都已经排除后，再把“计量异常”提升为主要假设：

- Fast mode 已关闭；
- Astra / Sol 的实际 runtime model 已验证；
- child reasoning effort 已验证；
- 没有意外 Astra children；
- 没有 recursive delegation；
- `fork_turns="none"` 或 history 确实必要；
- 没有三个 agent 重复做同一探索；
- 没有持续重复 full test / review；
- parent context 没有异常膨胀；
- task 已停止后 quota 没有合理解释的继续下降。

如果仍然出现：

- 与基线相比 >2× 的异常 drain；
- idle 状态持续下降；
- 一个很小的 bounded task 消耗多个百分点；
- usage meter 与可解释的 thread activity 明显不一致；

则记录并提交支持材料：

- ChatGPT / Codex 版本；
- plan；
- 日期、时间、时区；
- Settings → Usage 前后截图；
- parent model / effort / Fast 设置；
- child 实际 model / effort；
- child 数量与 nesting depth；
- `fork_turns`；
- thread IDs；
- sanitized token delta / runtime metadata。

**不要上传完整 rollout JSONL 到公共 issue。**其中可能包含项目源代码、用户输入、工具输出或其他敏感信息。只提交脱敏后的元数据和最小复现证据。

## 10. 建议的观测字段

如果以后要做一次正式用量分析，建议只保留一个很小的表，而不是建立复杂 reporting 系统：

| 字段 | 用途 |
|---|---|
| Start / End | 墙钟时间 |
| Weekly % before / after | 真实 allowance delta |
| 5h % before / after | 短窗口 delta |
| Lead model / effort | 主线程基线 |
| Child count | 并发度 |
| Child actual model / effort | 验证 override |
| fork_turns | 上下文继承 |
| nesting depth | 检查递归委派 |
| scope overlap | 检查重复工作 |
| tests / reviews repeated | 检查 churn |
| outcome | 是否真正节省 lead 工作 |

连续记录 3–5 个代表性任务通常就足以判断趋势，不需要长期手工记账。

## 11. 当前建议优先级

按优先级排序：

### P0 — 先验证实际 runtime

确认 Sol Medium children 实际就是 Sol Medium，而不是 Sol High / Astra High。

### P0 — 控制上下文继承

bounded worker 默认 fresh / minimal context；不要无理由携带完整 parent history。

### P0 — 禁止递归委派

继续执行现有 `AGENTS.md` 规则：worker 不自行创建 descendants。

### P1 — 默认最多 1–2 个并行 workers

第三个 worker 只用于第三条真正独立 workstream。

### P1 — 去掉重复探索和重复 review

Astra lead 负责 integration，不再重新完成 worker 已验证的局部工作。

### P1 — 给长 lead session 做阶段性 checkpoint

只在历史已经明显失去相关性时重开 focused session，不机械清空。

### P2 — 建立 3 个小样本基线

用 A/B/C 三种配置测 3–5 个真实任务；以 server usage delta 为主，本地 telemetry 为辅。

### P2 — 若仍异常，再怀疑 metering

只有在模型、effort、fork、并发、递归和重复工作都排除后，再向 OpenAI Support 提交用量异常证据。

## 12. 对当前 Nautilus 工作流的结论

当前的总体结构：

```text
Astra High lead
├── Sol Medium worker
├── Sol Medium worker
└── optional third Sol Medium worker
```

**方向本身合理，不建议因为这次额度消耗就立即把 Astra High 全面降级。**

更值得先优化的是：

1. child 实际 runtime 是否符合配置；
2. child 是否携带不必要的 parent history；
3. 是否默认开了过多并发 worker；
4. 是否有 scope overlap；
5. 是否存在 recursive delegation；
6. 是否发生重复 repo-wide exploration / review / test。

如果这六点都控制良好，再评估是否把某些 Lead 阶段从 Astra High 下调到 Astra Medium / Low。

换言之，优先优化的是**编排效率**，其次才是简单降低模型能力。

---

## 参考资料

### 官方

1. OpenAI Help Center — *Managing usage with GPT-6 Astra in Work and Codex*  
   https://help.openai.com/en/articles/20001516-managing-usage-with-gpt-6-astra-in-work-and-codex

### OpenAI Codex GitHub issue / 社区遥测

2. #45085 — *GPT-6 Astra High: one multi-agent Work task consumed 86% of weekly Prolite quota in ~4.5h (~198M tokens, 97.4% cached input)*  
   https://github.com/openai/codex/issues/45085

3. #34370 — *Subagents ignore requested medium reasoning effort and run at high*  
   https://github.com/openai/codex/issues/34370

4. #13849 — *Sub-agent role top-level reasoning settings are overridden by inherited parent profile*  
   https://github.com/openai/codex/issues/13849

5. #22250 — *Cannot overwrite subagent's model when spawning via LLM*  
   https://github.com/openai/codex/issues/22250

6. #38989 — *MultiAgentV2 runaway delegation: 74 subagents, 3-level nesting, 5.39B recorded tokens*  
   https://github.com/openai/codex/issues/38989

7. #35463 — *Codex subagents drain full week quota overnight - usage counting broken*  
   https://github.com/openai/codex/issues/35463

8. #45940 — *GPT-6 Astra appears to consume Pro weekly allowance at 1.4× the published credit-equivalent rate*  
   https://github.com/openai/codex/issues/45940

> 注意：GitHub issues 是用户报告和社区遥测，不等同于 OpenAI 已确认的产品行为。本文将它们用于提出排查假设和观测方法，而不是作为“当前账户一定存在同样 bug”的证据。
