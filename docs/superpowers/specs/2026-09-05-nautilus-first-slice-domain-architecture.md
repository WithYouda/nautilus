# 学海无涯（Nautilus）首个纵切片领域与架构规格

## 当前工程契约（2026-09-19，优先于下文历史实现描述）

### 来源信任边界

| 类型 | 创建边界 | 能证明什么 |
| --- | --- | --- |
| AI observation | Provider 只返回 dimension/stance/statement/scope；服务端固定 ai_analysis/semantic_analysis | 模型对所给产出的候选解释 |
| human review | 有身份、明确提交结果的人工执行链；当前仅 request_human_review，未实现 submit 结果 | 请求保持 pending，不能产生人工支持 |
| deterministic check | RegexDeterministicAnalyzer 代码赋值 deterministic_check/python_re_search | 当前 pattern 在当前 sample 匹配 |
| user self-report | 用户保存提交时的独立/资料/提示声明 | 自报条件，非系统证明独立 |
| delayed recall | 未来实际延迟任务、时间及作答记录 | 当前无执行链，不允许 AI 模拟 |
| transfer verification | 未来真实不同情境任务和观察 | 当前无执行链，不允许 AI 模拟 |

模型观察与执行 provenance 分离；source、verification_method、evidence_condition、executor_kind/version、observed_at 由系统组合。历史无可信执行标记的主张不能默认为高信任来源。单次 AI 不产生稳定支持，标准 v1 不原地改写；未来 v2 的多正例/反例/边界/不同输入/解释/变式待批准。

### 状态机与完成边界

| 对象 | 状态及边界 |
| --- | --- |
| Action | open → completed；库还保留 cancelled；最后开放委托完成才关闭行动 |
| Delegation | ready → active / paused → completed / cancelled；只有验证、停止条件与用户确认均通过才能完成本次委托 |
| Session | running → ended / interrupted；ended 不代表行动完成，恢复建立后续会话并关联原委托 |
| Verification | ready → submitted / failed → passed；submitted 是评估通过待用户确认，failed 可重试已保存提交 |
| Evidence Claim | candidate → adopted / questioned / withdrawn / superseded / invalidated；采纳不是新验证方法 |
| Derived State | awaiting_evidence / pending_review / insufficient_evidence / partially_supported / supported / contradicted（简称 awaiting/pending/insufficient/partial） |

对象之间没有 completed 的一一映射。supported 仅表示当前标准版本和实际范围内支持，不是通用掌握或长期保持。用户自报独立性与执行检测结果分别展示。

### 删除影响矩阵

“原文/摘录”表示可能包含；普通删除只隐藏/退出当前计算，撤回不删内容，彻底删除是授权入口的内容清除。此矩阵是系统执行边界，不扩大尚待决定的产品保证。

| 对象 | 原文 | 衍生摘录 | 普通删除 | 撤回 | 彻底删除 | 最小审计 | 恢复 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| learning_raw_artifact | 是 | 是 | 保留所有版本 | 保留 | 所有版本 content/hash=NULL | ID/时间/清除标记 | purge 后禁止 |
| learning_artifact | 否 | 否 | soft_deleted/withdrawn | withdrawn | purged/invalidated | 状态关系 | 仅普通删除 |
| learning_verification | 题目/旧材料 | 反馈 | 随关联失去证据资格 | 不删 | 整体验证入口清题目/答案/反馈；单产出入口只清其副本 | 完成事实 | 已清除部分禁止 |
| learning_verification_submission | 是 | 是 | 保留 | 保留 | 关联正文清空，purged 标记 | ID/关联 | 禁止 |
| learning_verification_evaluation | 可能 | 是 | 保留 | 保留 | 清结果，阻断迟到回写 | 非敏感运行元数据 | 禁止 |
| learning_evidence_claim | 可能 | 是 | 排除当前计算 | 排除 | 正文/范围摘录清除，invalidated | 引用/状态 | 禁止复活 |
| learning_review_action | 可能 | 是 | 保留 | 保留 | reason 清除 | 决定及关系 | 私文禁止 |
| learning_batch_review_action | 可能 | 是 | 保留 | 保留 | 任一关联清除即清共享 reason | ID/选择 | 私文禁止 |
| learning_evidence_follow_up | 可能 | 是 | 排除 | 排除 | note 清除、cancelled | 安排关系 | 私文禁止 |
| learning_revisit_item | 否（原因码） | 否 | 排除 | 排除 | 依赖项取消/重算 | 原因码 | 不恢复无效依据 |
| learning_evidence_event | schema v1 可能 | schema v1 可能 | 不改 | 不改 | 新写仅元数据/hash；不 UPDATE 历史账本 | 不可变事件 | v2 不能恢复私文；v1 见下文 |
| learning_evidence_private_content | 可能 | 是 | 保留 | 保留 | content_json=NULL，标记清除；混合共享引用连带清文 | hash/关系 | 禁止 |
| learning_question_discussion / learning_discussion_turn | 轮次包含 | AI 回复可能包含 | 暂无单独普通删除入口 | 不改变讨论正文 | 清除根提交关联及检索引用传播的讨论正文、来源/模型快照 | ID/状态/时间/依赖关系 | 禁止复活已清除正文 |
| learning_discussion_dependency | 否 | 否 | 保留关系 | 保留关系 | 保留用于禁止副本复活的来源 ID | 是 | 不允许借恢复复活私文 |
| 分析运行快照 | 不应 | 不应 | 保留 | 保留 | 只留模型/版本/状态，禁止存正文 | 是 | 可恢复非敏感元数据 |
| 普通备份 | 可能 | 可能 | 无自动清理 | 无自动清理 | 不回写已有备份；恢复入口检查清除标记 | 恢复检查 | 拒绝复活已清内容 |
| 恢复 | 可能 | 可能 | 不适用 | 不适用 | 必须与当前清除标记比较 | 是 | 缺少当前标记不可声称安全 |
| 外部 Provider | 可能 | 可能 | 系统不控制 | 系统不控制 | 本地删除不保证外部副本清除 | 无外部证明 | 系统不可控制 |

普通 artifact 的 schema v1 证据事件已经可能含私人文本，这是历史格式风险。新写入统一采用私密存储，事件仅保留关系、状态、ID、安全元数据及内容哈希。禁止直接改旧 append-only 事件。历史处理需单独设计：授权后盘点 v1、离线生成新账本/映射并校验、协调备份和切换；本轮不执行历史数据迁移，不读取真实库。手工导出和文件系统取证范围未承诺。

### 回放一致性契约

BEGIN IMMEDIATE → 确立事件截止位置 → 读取截止内事件 → 校验链/版本/引用 → 重建 → 校验实际投影、数量/状态/关系、外键和领域约束 → 提交。错误回滚保持原投影。事实和证据写入使用同一 SQLite 写锁；不能事务外读取旧 rows 再开始重建。应用内共享连接还受 Database RLock 保护，多连接由 SQLite 互斥。无需新基础设施。

一致性记录只存 cutoff、before/after digest、数量与约束结果，不存正文；成功审计不替代比较。损坏投影修复与正常重建一致性分别报告。证据版本纠正、清除覆盖及派生状态须保持相同截止点语义。

### 双数据库所有权

| 对象 | 所有库 | 校验/降级 |
| --- | --- | --- |
| Identity | 主库权威，学习库镜像 | LearningService 校验已认证身份并同步；不能由学习库授予认证 |
| Session/Auth | 主库 | 学习库历史 sessions 表不作为当前认证来源 |
| Provider Profile / Model | 主库 | 配置服务校验 owner、enabled、存在性；失效显式失败，不静默换 Provider |
| AI Conversation / AI Run | 主库 | ConversationService 校验 owner/删除状态 |
| Learning Goal / Plan / Action | 学习库 | Core 范围和事务约束 |
| Delegation / Learning Session | 学习库 | Core owner、契约版本、单一 running |
| Question Discussion / Turn / Dependency | 学习库 | QuestionDiscussionService 校验 owner/委托/提交/评估与来源有效性；清除触发器同事务执行 |
| Verification / Artifact | 学习库 | 服务与 Core 校验关联及清除状态 |
| Evidence / Derived State | 学习库 | 执行 provenance、引用、生命周期与状态规则 |
| learning_room_conversation | 学习库，引用主库 conversation | RoomService 检查双方 owner 和任务范围；不存在降级为无对话，保留学习事实 |
| learning_evidence_provider | 学习库，引用主库 profile/model | EvidenceProviderService 检查 owner/可用性；缺失报告不可用 |
| 身份同步 | 主库 → 学习库 | 请求边界同步；单库恢复不能暗中创建主库身份 |

没有跨库 FK。单库恢复后应进行只读悬空引用核对（身份、room conversation、evidence provider）再启用；当前没有协调双库恢复保证，不能将一库 integrity_check 当成跨库完整性。生产核对、恢复与历史迁移都需另行授权。

### 测量关联契约

返回卡持久化稳定推荐 ID 和结构化选择，关联 review_card_shown、resume_candidate_presented、resume_choice、resume_started、resume_corrected/switched 以及 action completion。不保存标题/聊天/正文。恢复按已明确尝试原委托且实际进入统计，纠正另记；主动切换和意图未知单列。下一行动按稳定推荐与实际正式完成匹配，观察窗口固定七天；session ended 不替代完成。值只作 observed/no_sample；硬护栏有对应契约。测试库和真实使用库分离，不导入自动化样本。


### 2026-09-19 已落实的接口与实现范围

- `GET /api/learning/return-review` 汇总位置、事实、支持、未知与单一规则推荐。推荐以稳定 context fingerprint 复用 ID；仅保存 ID、推荐类型/原因码和时间，不保存返回文案或原文。最近会话按已提交事件位置排序，避免时钟回拨选错委托。
- `POST /api/learning/return-review/{id}/choice` 接受展示、继续、换项、暂停、查看、实际进入、纠正；所有引用均按 owner 校验，开始使用 Core 既有命令和版本约束。界面只在用户点击后进入/暂停，不自动改正式计划。choose_next 的空 action 只有在用户确认新安排后才绑定，表示用户确认的下一行动；实际进入与正式 action completion 关联回原卡，允许跨中断会话延续，不把结束会话计为完成。`POST /api/learning/sessions/{id}/room/entered` 记录实际界面进入。
- 初始化保存 AI 草案的内容指纹、采纳来源和是否修改；首个非空自写产出才形成 first_artifact，单独参考材料不算。指纹不保存草案正文。指标 v3 的产品值为 observed/no_sample；时间只用于七天观察窗口，因果先后使用事件提交顺序。无推荐关联的历史会话不推测为成功。
- 回放比较涵盖事实投影及 claim/review/batch/replacement/follow-up/state/history/revisit 的数量、关系和状态；JSON 规范化。历史行的重建随机 ID，以及 revisit 的运行时 created/updated/due 时间不参与摘要，复核截止时间仍在 follow-up 投影中比较。外键和单一 running 约束另验。修复损坏投影的 digest 差异如实记 matched=false；校验拒绝不会伪记比较通过。不是任意数据库字节一致性证明。
- 同一委托恢复可选取其原有对话，保留最初会话关联；其他委托和其他 owner 不得重挂同一对话。单库丢失的主库对话降级为无对话。
- 025 增加执行 provenance，已有不明来源的当前支持缓存降为 insufficient；历史事件/历史状态保留。读 API 与回放再次核实参与主张，不能让旧来源声明重新成为当前支持。026 只存重建比较元数据。027 只存返回推荐与用户行为关联。既有迁移和 approved v1 均未修改。
- 普通产出与验证产出的新证据私文均进入可清除 store；恢复检查同时拒绝原文、私密 store 和当前证据摘录复活。既有普通备份不自动擦除，缺少当前 tombstone 或手工绕过恢复工具的情形没有防复活保证。

上述接口已实现，当前启用和验证事实见开发状态。历史 schema v1 私文的单独迁移、双库协调恢复仍未完成，新真实数据操作按确认范围执行；当前没有全系统副本彻底删除承诺。


| 项目 | 内容 |
| --- | --- |
| 产品 | 学海无涯（Nautilus） |
| 文档类型 | 首个纵切片工程领域/架构规格 |
| 日期 | 2026-09-05，Asia/Shanghai |
| 状态 | 基于已确认 PRD V2；计划内 Task 0-8 已完成并通过自动化验证，事实门通过，证据门工程链路与指标验收已实现，整体产品验收边界见[开发状态](../../progress/nautilus-development-status.md) |
| 产品基线 | `docs/superpowers/specs/2026-09-02-nautilus-prd-v2.md` |
| 实施计划 | `docs/superpowers/plans/2026-09-05-nautilus-first-slice-implementation.md` |

## 1. 范围与边界

本规格只定义 PRD V2 首个纵切片的工程边界，不把终局能力直接变成当前任务清单。

首片直接使用新领域模型独立验证。旧四层计划、旧任务入口、旧 API、旧字段语义不构成兼容要求；不新增旧模型映射、适配、双写或迁移兼容层。历史用户数据仍须遵守备份、校验、恢复和授权保护。

首片围绕一项可验证成果及一个预先审核、版本化的窄领域达成标准版本，按两个连续验收门交付：

1. **事实闭环门**：委托、标准绑定、学习会话、文本原始产出、事实事件、关系型当前态投影和可校验回放。
2. **证据闭环门**：候选证据主张、状态派生、复核、质疑、撤回、彻底删除后的失效和证据回放。

没有合格标准时，仍可保存会话、原始产出和事实事件，但不得生成证据主张或学习状态。AI 不可用、超时、取消或输出不合格时不阻塞保存；失败只形成可审计的分析运行结果，不能生成空主张、伪造主张或伪造状态。

首片不强制创建综合成果，不实现完整路径图、成果图、主动后台教练、云同步、社区市场或跨设备能力。

## 2. 领域对象

以下对象是首片所需的最小语义集合。具体表名、API 字段和代码命名可以在实现中调整，但不得改变对象边界。

| 对象 | 作用 | 不变量 |
| --- | --- | --- |
| 学习成果 `VerifiableOutcome` | 被验证的能力身份 | 有稳定身份、描述对象/行为/情境；不以任务完成代替成果达成 |
| 达成标准版本 `CriterionVersion` | 定义成果所需的证据组合和质量条件 | 必须来自已审核的窄领域标准包；版本不可变；记录来源、版本和适用范围 |
| 学习行动 `LearningAction` | 用户执行的具体工作节点，界面可称任务 | 独立于委托、会话和产出；旧任务模型不作为兼容边界 |
| 学习委托 `LearningDelegation` | 围绕一次行动的长期工作单 | 绑定行动、成果和标准版本；保存边界、停止条件、状态和版本历史 |
| 学习会话 `LearningSession` | 一次真实学习过程 | 有开始/结束或中断事实；可重复打开并关联多个产出 |
| 原始产出 `RawArtifact` | 用户提交的文本内容 | 内容不可覆盖；更正通过新版本或追加事件；拥有隐私范围和删除状态 |
| 事实事件 `DomainEvent` | 记录何时、由谁、通过什么动作发生了什么 | 追加式、唯一、排序、幂等；与当前态投影同事务提交 |
| 证据主张 `EvidenceClaim` | 说明产出对成果维度的支持、反驳或不足 | 必须引用具体产出和事实事件；候选、采纳、质疑、撤回、替代分开表达 |
| 派生学习状态 `DerivedLearningState` | Core 根据可用证据和标准计算的当前状态 | 只能由 Core 派生；不能作为事实事件来源；可从事件和有效主张重算 |
| 分析运行 `AnalysisRun` | 记录 AI 或人工分析尝试 | 幂等键唯一；保存成功、失败、取消、超时和不合格原因；失败不得产生占位主张 |
| 复核/删除审计 `ReviewAudit` | 记录采纳、质疑、撤回、普通删除、彻底删除等动作 | 审计元数据不包含被彻底删除的原始私人内容 |

事实层和解释层必须分开：`RawArtifact` 保存内容，`DomainEvent` 保存发生上下文；`EvidenceClaim` 和 `DerivedLearningState` 是解释/派生层，不能反向伪造事实。

## 3. 标准准入与降级

### 3.1 标准准入

- 只有预先审核并版本化的窄领域达成标准包可以绑定到委托并参与状态派生。
- 用户提供的可追溯标准在进入标准包前只能作为候选来源保存，不能参与正式状态计算。
- 每次委托必须记录标准包标识、标准版本、来源和绑定时间；标准版本发布后不可原地修改。
- 标准缺失、失效、超出适用范围或未完成审核时，Core 返回“不可分析”的明确原因。

### 3.2 无标准和标准不可用

无标准或标准不可用时：

1. 允许创建或继续学习委托。
2. 允许保存会话、文本原始产出和对应事实事件。
3. 创建 `AnalysisRun(status=blocked_no_criterion)`，记录原因和可恢复动作。
4. 不创建候选主张，不创建或覆盖学习状态。
5. 界面提供查看原因、继续产出、稍后重试绑定标准或请求人工复核的入口。

## 4. 命令与状态转换

Core 是唯一执行领域命令和写入正式状态的边界。Runtime/Agent 只能提交结构化命令、观察或分析结果，不能直接写表。

首片最小命令集：

| 命令 | 前置条件 | 结果 |
| --- | --- | --- |
| `CreateLearningAction` | 用户有权在当前范围创建行动 | 创建行动并记录事实事件 |
| `CreateDelegation` | 行动存在；成果和标准绑定合法 | 创建委托版本并绑定标准 |
| `StartSession` | 委托可执行；当前用户无冲突的运行会话 | 创建会话开始事实 |
| `SaveTextArtifact` | 会话属于当前用户；内容通过大小和隐私校验 | 保存不可变产出、关联事实事件和投影位置 |
| `EndSession` | 会话属于当前用户且未结束 | 追加结束事件，保留产出 |
| `RequestAnalysis` | 有产出；标准有效；调用方拥有分析权限 | 创建幂等分析运行 |
| `CompleteAnalysis` | 分析运行仍是当前版本 | 成功时写入候选主张；失败时只写失败结果 |
| `AdoptClaim` | 主张满足采纳条件且用户有权限 | 改变审查状态，触发状态重算，不直接设置状态 |
| `QuestionClaim` | 主张可见且尚未撤回/替代 | 主张退出当前状态计算，记录质疑理由 |
| `WithdrawArtifactEvidence` | 产出可见且用户有权限 | 使依赖主张退出当前计算，不删除内容 |
| `CorrectArtifact` | 原产出可见且用户有权限 | 创建新版本/更正事件，旧版本保留审计关系 |
| `SoftDeleteArtifact` | 用户明确执行普通删除 | 改变当前可见性，可恢复，不销毁内容 |
| `HardDeleteArtifact` | 用户明确确认影响范围且具备权限 | 不可逆清除或不可逆脱敏内容，失效依赖主张并重算状态 |
| `ReplayAggregate` | 维护权限；投影重建在隔离存储中进行 | 校验事件并原子替换投影，失败时保留旧投影 |

核心状态转换：

```text
委托：draft -> active -> paused/completed/cancelled
会话：planned -> running -> ended/interrupted
分析运行：queued -> running -> succeeded/failed/timeout/cancelled/invalid_output/blocked_no_criterion
主张：candidate -> adopted -> questioned/withdrawn/superseded
产出可见性：visible -> soft_deleted -> visible
产出证据适用性：eligible -> withdrawn/invalidated -> eligible（仅在明确恢复且条件仍满足时）
```

状态转换必须由命令和事件驱动，不能由前端直接修改数据库字段。重复命令返回同一业务结果或明确的幂等冲突，不产生重复事实。

## 5. 事件账本与投影

### 5.1 事件最小结构

每条事件至少包含：

- `event_id`：全局唯一不可变标识；
- `aggregate_type`、`aggregate_id`：所属聚合；
- `aggregate_version`：聚合内单调递增序号；
- `event_type`、`event_version`：事件语义和 schema 版本；
- `command_id`、`idempotency_key`：来源命令和重试去重键；
- `occurred_at`、`recorded_at`、`actor_id`、`tenant/user scope`；
- `payload`、`metadata`：结构化事件内容及非业务元数据；
- `projection_version` 或等价的投影位置；
- 隐私分类和保留/删除标记。

事件类型名称必须表达事实，例如 `artifact.created`、`session.started`、`claim.questioned`，不得把 `DerivedLearningState` 当成原始事实事件。

### 5.2 事务和幂等

一次领域命令必须在同一数据库事务内完成：校验前置条件、登记幂等键、追加事件、更新当前态投影和写入必要审计元数据。任一环节失败，事务整体回滚。

同一 `idempotency_key` 重试必须返回第一次成功结果，或返回可审计的冲突；不能追加第二条等价事实。事件唯一约束、聚合版本约束和幂等键约束必须由数据库和 Core 双重保护。

### 5.3 投影与回放

- 当前态是查询投影，不是唯一真相；事件账本和不可变原始产出共同构成历史依据。
- 每个聚合维护最后应用的 `aggregate_version`；发现缺口、重复或乱序必须停止应用并报告错误。
- 重建在隔离临时投影中进行，完成数量、顺序、版本和领域约束校验后才原子切换。
- 重建失败或校验不通过时保留原投影并暴露失败原因，不能清空有效当前态。
- 删除投影后可以从事件重建；派生状态还必须重新读取当前有效标准、主张和删除/撤回适用性。
- 回放必须校验事件数量、首尾版本、连续顺序、事件 schema 版本、关键外键/权限约束和结果摘要。

### 5.4 事件版本升级

事件 schema 变更必须选择一种显式策略：

1. 提供确定性升级器，将旧版本转换到新版本后再回放；或
2. 拒绝该版本的重建并将错误标记为不可回放。

禁止静默按新含义解释旧 payload。升级器必须有单元测试、版本范围声明和失败记录。

## 6. 证据、删除与重算

- 文本产出创建后，候选主张必须同时引用产出 ID、产出版本和对应事实事件 ID。
- AI 语义分析默认生成候选主张；机械事实或确定性验证是否可自动采纳由标准包和 Core 规则决定。
- 用户采纳只改变审查状态；状态贡献仍由 Core 按标准和证据配方计算。
- 质疑、撤回、事实更正和彻底删除会使相关主张退出当前状态计算，并触发成果状态及回访队列重算。
- 普通删除是正常可用的软删除，内容可恢复；撤回不删除内容，只改变证据适用性。
- 彻底删除必须显示受影响的主张、状态和回访安排并明确确认；内容不可恢复或不可逆脱敏，缓存、索引和普通备份不得继续提供内容，只保留最小审计元数据。
- 重算结果必须能追溯到标准版本、参与主张集合、排除原因和计算版本；重算失败不得用旧结果冒充新结果，需标记待重算并保留失败审计。

## 7. AI 失败与恢复

AI 调用分为保存链路和分析链路。保存链路不依赖 AI 成功；分析链路只能在标准有效且产出已成功保存后执行。

需要区分并记录：不可用、超时、取消、输出不合格、权限拒绝、标准缺失和内部错误。每类失败都保留可读原因、运行状态、幂等键、重试次数和下一步动作。

重试使用同一业务对象的新运行记录和稳定幂等键语义：同一请求不能重复产生主张；成功后再次重试应返回已存在的成功结果。用户可以继续保存、稍后重试、请求人工复核或安排补充验证。失败时不得创建空主张、伪造引用或学习状态。

## 8. 权限与隐私边界

- 所有命令按用户身份、对象归属、当前 Agent 数据范围和显式工具授权校验。
- 全局 Agent 默认只读最小范围；需要扩大范围时主动申请，拒绝后仍可继续不依赖该权限的学习和保存。
- 跨身份读取、未授权写入、越过计划/任务/委托范围的主张分析必须被拒绝并记录，不返回被保护内容。
- 复核卡只显示用户当前有权查看的依据；彻底删除后的审计记录不得包含原始私人文本、凭据或可恢复内容。
- Provider、凭据和运行参数与领域数据分离保存；日志、指标和回放输出不得写入访问令牌、Cookie、API Key 或用户原始内容。

## 9. 迁移、备份和恢复约束

- 本规格只允许未来迁移从 `011_*.sql` 开始，现有 `001` 至 `010` 不得修改。
- `011` 起的迁移应先在隔离数据库应用和校验，记录 schema 版本、备份标识、恢复演练结果和回滚/前滚策略。
- 自动化测试使用临时隔离数据库，不得使用默认 `data/`。
- 默认数据库迁移、数据转换或破坏性重构必须在验收后另行确认备份和恢复方案；本规格不授权执行。
- 备份恢复必须验证事件账本、原始产出、投影位置、权限边界和彻底删除语义，不得因为恢复而重新暴露已彻底删除内容。

## 10. 工程完成定义

首片进入实现验收的必要条件：

1. 事实门的 `CAP-FACT-001`、`CAP-FACT-002` 和适用的 `INV-001` 至 `INV-010` 有对应测试与结果。
2. 证据门只在事实门通过后实施，并覆盖 `CAP-EVID-001`、`CAP-EVID-002`。
3. 后端命令、事务、投影、回放和删除语义有集成测试；前端有失败、权限和恢复状态；Playwright 覆盖真实用户路径。
4. 隔离迁移、备份恢复、跨身份越权和回放失败均有可重复验证记录。
5. 成功指标按 `CAP-MEASURE-001` 的固定口径记录；无样本明确标为未测，不冒充通过。
6. `git diff --check` 通过，开发状态文档记录实际改动、测试、已知问题和下一任务。


## 验证回看与题目讨论契约（2026-09-24）

本人详情按submission/evaluation版本鉴权；新评估必须逐题完整反馈，包含可质疑的参考解法、可选追问和既定要求缺口，有必需缺口时不能通过。旧评估不补造字段，不公开隐藏评分依据。

题目讨论存于学习库，以验证/提交/题目/评估引用建立会话。轮次独立保存user_content、assistant_content、reasoning_content及运行状态，Provider快照只保存模型/版本/是否检索等非私文信息。使用现有Provider流适配器，HTTP先保存并确认问题，任务独立生成，SSE读取持久化快照；取消/失败保留部分内容，重试清空旧回复和思考，attempt_id防止旧尝试覆写。

本地检索限本人同委托可见教学对话与讨论：每轮最多一次、检索词最多80字符、最多6段且每段1600字符，当前讨论取最近8轮。仅保存实际来源ID，不把检索原文复制进运行快照，也不将验证私文复制到主库。没有开放联网、通用工具或全文索引。

迁移028建立discussion/turn/dependency与级联清除触发器；029增加reasoning_content并更新清除触发器。清除验证提交时在同一SQLite事务内清除其讨论和引用它的衍生讨论正文/思考，保留最小ID/状态，不改完成事实。每个迟到片段核对当前尝试和来源有效性；恢复工具检查私文残留且兼容旧备份无思考列。

前端共用LearningChatPanel、LearningMessage、LearningComposer、ReasoningBlock。Provider思考生成时展开、结束后折叠；刷新重连不重复调用。服务重启后运行轮次标记中断供重试，不承诺跨重启自动继续生成。独立异步任务不是新增常驻Agent或任务队列。

运行事实和当前限制见[开发状态](../../progress/nautilus-development-status.md)。外部Provider、导出与取证副本不属于当前库清除保证；真实新迁移仍遵循已确认授权边界。

### 原计划追加任务（2026-09-24）

`ConfirmLearningSetup` 接受可选 `plan_id`：未传时创建目标/计划，传入时校验本人活动计划并只追加任务、成果、委托与安排。`plan.step_added` 和普通事实事件在同一事务提交，回放保持父目标/计划及原始意图不变，步骤意图单独保留在setup。首页完成后的确认通过原会话锁定计划，不能用review关联另一计划；不新增schema迁移。未传plan_id的既有幂等哈希保持不变。前端计划页直接读取学习域，不读取旧规划或引入双写。
