# Nautilus D3 后台教练契约

日期：2026-10-05。状态：**产品选择与实现接口已冻结；后端/前端及独立工程验收完成，原trial048已启用。实际检查与启用证据见开发状态，真实建议质量待本人体验。**

作者已试用 D2 并反馈无问题，授权开始 D3，指定 6.1 Sol 实现、另一名 6.1 Sol 独立审查，主 Agent 统领范围、契约与最终验收。代码基线 `3d4bc7f`，已有 D1/D2 和图内任务修正保持；当前工程与启用证据另见开发状态，不宣称长期学习效果已验收。

## 1. 已确认目标与边界

依据：[当前路线 D3](../plans/2026-09-27-nautilus-product-roadmap.md)、[PRD V2 7 / 8.4 / 9.1](2026-09-02-nautilus-prd-v2.md)、[产品决定 6.3.2 / 10 / 12](../../progress/nautilus-product-design-decisions.md)。

- Core 持续记录低成本结构化信号；不对每条消息、计时更新或细小事件另调模型。
- 复用正在进行的任务 Agent 同次输出，可附带 `assignment_signal`；模型不能借此直接创建正式委托或修改计划。
- 自然停顿、暂停/结束会话、任务切换、阶段产出与计划返回时，对尚未处理的有效信号去重、批量分析。正常返回或计划复盘也可处理重复阻塞、未处理候选和到期回访。
- 只有用户明确要求、不能继续或高影响决定才即时提示；普通建议不在学习中频繁弹窗。
- 全局教练只读取最小摘要、状态及证据引用。原始消息、资料、产出与自由文本反馈不因打开教练获得读取授权。
- 存在用户开关、会话/日级调用限额和冷却。相同批次不按候选逐个调用模型；没有新增有效信号不调用。
- 建议可接受、拒绝、忽略、撤销，处理有审计。正式计划、路线、委托、承诺、长期设置或能力状态变化仍需既有用户确认。
- 浏览器异常关闭或运行中断只留下待复盘状态，不能因此立即产生模型费用；拒绝建议或读取许可后原学习流程正常。
- D3 必须包含真实的受控 AI 分析与提案，不能仅把规则提醒命名为后台教练。

## 2. 作者已确认的开关、限额和呈现

作者已接受主 Agent 提交的两项推荐；决定已同步到产品决定 12.1.1。

1. 自动复盘默认关闭，由本人在设置中开启。初始可调限额为每会话 1 次、每天 3 次、30 分钟冷却；这些数字是试用限额，不是实测最佳值。没有会话归属的计划/全局批次仍受日限额和冷却约束，不通过丢弃会话归属绕过限制。手动复盘在开关关闭时仍可由本人明确发起。
2. 首页与对应计划使用简短卡片；默认显示一张和总数，其余本人展开/收起，沿现有顺序不新增优先级判断，也不触发模型或决定。普通建议不弹窗，依据按需查看，提供接受、拒绝、暂不处理、撤销。正式变化沿已有预览确认。

主 Agent 同时冻结两个技术边界：同次信号仅使用现有已启用且能力检查通过的结构回传组合；首片 coach 不生成完整 D2 安排/路线草案。接受只记录建议处理并打开对应原入口，正式变化及实际执行仍由既有流程明确确认；撤销只撤销建议处理，不回滚已单独确认的事实/计划。页面明确说明此效果。

已冻结：自动预算按真正发起 HTTP 分析计数；先原子预留，等待槽位时不算已用，未发取消释放；发出后失败/取消仍占次数。owner 跨 global/plan 共用日限额、冷却及真实会话计数，合并批次内每个会话均占一次，无会话批次只占日限额/冷却。自动冷却可调但至少 30 分钟。按持久用户时区划日；未设置时明确 UTC，首次开启由界面显示并保存浏览器时区，不接受单次请求临时换时区。

手动复盘在自动关闭时仍可本人明确发起，不占自动限额/冷却；同 owner 最多一个实际活动运行。没有有效新来源不重复付费；失败/取消批次只本人明确 retry 可增加 attempt，保留历史，不自动重试。关闭阻止未发自动运行及晚到自动候选，不回滚已有学习/决定。

## 3. 当前可复用文件地图

| 能力 | 当前准确接口/文件 | D3 的复用与限制 |
| --- | --- | --- |
| 领域账本与命令 | `backend/app/core/learning.py` 的 `execute` / `execute_in_transaction`；`core/events.py` 的 `append_event` / `apply_event` | 稳定事件 ID、owner、command、幂等和同事务投影；新增 coach 事件沿原链，不另建教学历史账本 |
| 正常边界 | `session.ended`、`action.completed`、`delegation.completed`、`artifact.created` / `verification.artifact_recorded`，以及 `feedback.*` / `commitment.*` / `path.*` | 只提取明确允许的结构字段；不能把整个 `payload_json` 当作模型摘要；`session.ended` 还可能由转向/暂停内部命令产生，须归并一次 |
| 当前运行同次结构回传 | `teaching_runtime.py` 的 `freeze` / `add_prompt` / `TeachingStream` / `evaluate` / `adopt`；`teaching_json.py`；`conversations.py` 的 `complete_run`；`question_discussion.py` 的 `_generate` 成功结果保存 | 扩展可选信号并保持普通正文及原教学记录。当前 `teaching-v9`，结构输出有能力检查与 plain 回退；没有能力时不能隐含追加检测调用 |
| 权限摘要与申请 | `agent_runtime.py` 的 `agent_context(identity, target_id=None)`、`create_permission_request`、approve/deny/revoke；`routers/learning.py` 的 `/agent/context` 和 `/agent/permission-requests` | 默认 global 仅 action 摘要和证据引用；task 元数据、grant 与原文读取独立。D3 必须主动白名单，不能直接调用带旧 full_text grant 的上下文再把整对象送模型 |
| 返回连续性 | `continuity.py` 的 `get` / `decide` / `record_usage`；`GET /api/learning/return-review`、`POST /return-review/{id}/choice`；`ReturnReviewCard.tsx` / `FactWorkspace.tsx` | 确定性返回卡、保存位置、单运行会话、切换与幂等保持；它不是 coach 的运行/预算/候选表，不应承担第二套 AI 状态 |
| 依据候选与回访 | `review.py` / `evidence.py`、`state_derivation.py` 的 `revisit_queue`；`delayed_follow_up.py` 的 `due_list` / `get` / `choose`；`DelayedFollowUp.tsx` | 只引用原候选/回访 ID、版本和到期状态；实际复核、开始/跳过回访仍走原入口。`due_list` 包含尚未到期的 scheduled 项，D3 必须检查 `is_due`；不能读取其含题目/作答的完整 public 对象后当全局摘要 |
| 模型归属与冻结 | `model_control.py` 的 `runtime(owner, kind, scope_id)`，支持 global/default 与 plan | global coach 用 global/default；plan 复盘用明确 plan ID 及其继承模型。历史模型、思考、超时/配置版本与输入在接受运行时冻结；不采用最后打开的对话 |
| 受控后台运行 | `ai_runtime.py` 的共享 `_provider_slots`、`commitments.py` 的 `suggest` / `_generate` / `cancel` / `recover` / `shutdown`、`main.py` 的 lifespan | 沿已用 Provider/config/diagnostics/异步 task 与生命周期约定；不用另一种 Agent 环境。新增轻量确定性门控服务，不自动开网络搜索/知识库/工具 |
| D2 路线与安排 | `learning_paths.py` / `core/path_commands.py` 的 `SavePathDraft`、`preview`、`ConfirmPathDecision`；`commitments.py` / `core/commitment_commands.py` 的 `save` / `preview` / `confirm` / `item_preview` / `change` | 提案只导向候选或可编辑草案，不能静默确认、开始或移动当前焦点。既有 AI 安排草案严格绑定 commitment run / input hash，不能把教练产物冒充 manual 来源 |
| 清除与恢复 | `managed_purge.py`、`purge_content.py`、`learning_production.py`、`commitment_integrations.py` 的注册/来源失效方式；`core/learning.py` 的 `PROJECTION_TABLES` 和 replay | 新私文统一清除、注册备份擦除、恢复屏障、晚到结果拒绝、Core 回放；复用源引用，不复制对话或学习情况原文 |
| 页面与设置 | `Workspace.tsx` 首页；`FactWorkspace.tsx` 当前卡/权限；`LearningPlans.tsx` / `LearningPaths.tsx` / `LearningCommitments.tsx`；`Settings.tsx` | 新卡保持短内容与具体动作，依据/历史/调用信息按需；统一设置加入开关与成本控制，不重做全站 |

## 4. 已冻结的最小完整切片

### 4.1 同次信号

为当前已启用的结构回传加入可选 `assignment_signal`，一次正常回答至多一条建议性信号；普通提问、临时插曲、一次小错误默认 null。

建议有限类型：`separate_work_requested`、`repeated_blocker`、`scope_conflict`、`cannot_continue`、`permission_or_cost_change`。信号不是正式结论。来源必须是当前实际用户请求/真实尝试、现存任务/契约或本轮输出；Core 检查 source ID、版本、owner、实际字符区间和允许枚举。不接受模型造出的任务 ID、费用或权限事实。

存储只保留类型、来源定位、当前任务/会话/路径/回答身份、结构状态、纠正排除状态及版本；展示原话时实时通过本人原入口解析，不把原话复制进全局摘要或公开账本。用户可以排除误判、恢复；当前尝试/学习情况被纠正或排除时，依赖它的阻塞信号也失效。分支只按既有复制身份引用，不能把不同复制回答当作独立重复失败。

信号只在成功且来源仍有效的回答完成时保存。失败、取消、仅部分输出、来源已清除或提案校验失败不制造有效信号。普通 plain 回答保持原行为，不为缺失 sidechannel 另起调用。解析信号失败应只丢弃该信号，不连带毁掉合法正文/原教学记录。

模型可提出 `repeated_blocker`，但跨会话门控最低为至少两个不同真实 session，各自具有有效真实尝试/阻塞引用；重试、复制和编辑/修订不能凑次数。新请求捕获该委托当前实际 running session，不沿历史 room relation/verification session 猜测当前会话。该最低语义不是通用学习稳定阈值；unknown、普通提问不算阻塞。

### 4.2 事件门控与批次

新增 coach 引用/批次投影，来源来自已有领域/证据事件、同次信号、原回访 ID、D2 确认项及反馈 revision。批次有稳定输入指纹和源引用集合，不重新保存全部历史。来源变化之后可形成新批次，旧批次与处理历史保留。

触发只分：明确正常会话边界、返回首页/打开计划、有新有效信号的复盘、用户手动要求。门控服务先计算待处理和到期状态，然后检查开关、实际新信号、当前批次幂等、预算、冷却和并发；全部满足才发起一次模型分析。自动领取以稳定 event ID/source revision 和 batch 指纹在同一事务中完成，预算预留与批次领取一起写入；不能以组件挂载次数或前端随机 request_key 作为自动去重依据。会话切换造成的多条内部暂停事件合并成一批，同一来源不会因首页/计划重复打开而重新计费。用户正在学习时普通候选只入队，不抢焦点。

浏览器断连、AI 取消/失败与进程恢复不作为立即付费触发；恢复时把未完成运行置为 interrupted/failed、信号保留待复盘，无自动重试。需要明确区分正常业务边界与异常恢复记录，不能只看 status=interrupted 就判断必须自动调用。

存在已待确认的候选只提示原候选；不得因为用户没处理而对同一输入反复调用。每日/每会话限制和冷却仅控制发起次数，不能当成事实质量、学习节奏或稳定掌握依据。失败和取消的实际模型发起照常占次数；槽位等待中未发送的任务关闭后不发起。关闭增加设置版本/运行屏障，已发送结果也不得晚到写入新候选；取消和重启不重发。

### 4.3 分析输入与模型输出

- global 输入：所属计划 ID、任务最小标题/状态、委托/会话身份与状态、成果/证据 ID 及状态、明确事件枚举、反馈结构轴与未知、路线 ID/版本/拓扑/位置、安排 ID/日期/预计范围、回访 ID/到期状态、候选状态。
- plan 输入：同一白名单，限定到明确 plan ID；不能把 D2 `input_context`、路径 private 原件、反馈 notes、证据 statement 或全部模型历史整体作为默认教练摘要。
- 最小摘要不足时，提案绑定具体 action/本判断目的/必要粒度/300 秒/拒绝替代，进入原权限申请。仅本人明确 `manual + permission_candidate_id + permission_request_id` 才进行本次有限授权复盘；历史 full_text grant 不自动转入新运行，也不转交其他 Agent。
- 分析不用工具，不扩联网权限。输出有限候选类型、简短理由、允许的 source refs、仍未知内容和具体建议动作；外部 ID/枚举/引用必须来自本次冻结白名单。可以不提出任何候选，不能为了填满卡片造建议。
- 接受前与完成前均检查输入/权限/源版本仍有效；变化后旧结果不可用于正式应用，也不能把新输入自动追加模型调用。

候选建议类型与实际动作：

| 候选 | 接受的实际结果 | 正式变化的再次确认 |
| --- | --- | --- |
| 继续某开放任务 | 定位该任务的原计划/任务入口，展示原开始或继续动作；检查 task/delegation 绑定并保留原位置 | 用户再在原流程明确开始/继续，才调用 continuity / StartSession；接受建议不自动执行 |
| 复核已有依据 | 实际 claim/revisit object_id 定位首页原高级处理区；纯记录回看明确标为“查看依据”。无 claim 的只读 revisit 标为“查看这项回访”，不虚构执行命令 | 采用/质疑仍由原 review 命令确认，不把打开视图当采用 |
| 已到期回访 | 定位原 follow_up 或 revisit 引用，进入其现有回访入口 | 开始/跳过沿原按钮；不因接受导航自动作答或认证掌握 |
| 调整当前路线/近期安排 | 展示具体调整意图与现存任务引用，定位对应 D2 原编辑/预览入口，保留 coach 原运行/依据可回看；本人也可明确触发原 AI 建议 | coach 不自动写 D2 草案、不冒充 manual/ai 来源；原草案/正式确认沿既有流程 |
| 单独安排一项工作 | 展示具体目的/范围建议，定位已有新任务/学习设置入口，保留原任务和当前焦点 | 本人核对契约与任务字段后才创建正式任务/委托，默认待开始 |
| 需要进一步任务产出读取 | 绑定真实任务/判断目的/full_text/300秒/替代，进入原申请；批准后本人另点“用本次授权继续复盘” | 本次授权只读有限原任务产出，不扩大工具/搜索/正式写入；拒绝可补本人摘要或继续原任务。费用/工具即时例外沿当前任务原决定入口 |

接受导航类建议也记录具体目标和结果，不能仅把数据库状态改成 accepted 而按钮无实际作用。首次接受成功后的重复请求返回同一导航目标；不创建学习会话/正式草案或切换焦点。对过期源返回可操作的重新核对提示，不静默换成另一个任务。回访改期、跳过、完成或源失效后，旧到期提案不可仍按原到期状态接受。

### 4.4 候选处理与撤销

建议候选状态 `pending` / `accepted` / `rejected` / `ignored` / `unavailable`，决策保持追加历史和版本比较。

- 接受：执行上表已说明的动作；涉及正式变化时记录 draft/preview 目标，后续正式确认仍是独立事实。以明确实际结果说明接受完成程度。
- 拒绝：结束本候选并抑制同一源指纹再次呈现，不关闭委托、不暂停学习、不改来源事实。
- 忽略：暂收起，来源未变时不重跑；本人可从历史重新考虑。若要采用“稍后自动再提醒”，其次数/间隔是新产品选择，本草稿不默认加入。
- 撤销接受/拒绝/忽略：撤销教练决策、在源仍有效时恢复待处理；不抹掉学习记录或暗中回退已确认的 D2 路线/安排。对已正式应用的变化提供既有 D2 撤销/恢复影响预览入口。
- 来源更正、排除、清除、软删或权限撤回：当前候选不可继续接受；保留无私文的审计理由和 ID，既有完成/正式决定不能被模型改写。
- 资格按 target kind 区分：完成/暂停/关闭目标仍可原依据回看、讨论和复核；执行/新任务/路线/安排检查冻结版本及可执行状态。清除、来源失效或本次权限无效一律拒绝，不静默换目标。

## 5. 已冻结接口与持久化

- `GET /api/learning/coach`：待处理卡、最小历史/依据入口、当前运行与安全限额概况，可按 plan ID 限定；不在 GET 中隐含发起模型费用。
- `GET/PUT /api/learning/coach/settings`：开关、限额/冷却、时区、expected_revision；无效设置不写入。
- `POST /api/learning/coach/checks`：scope(global/plan)、plan_id、trigger(manual/return/boundary)、request_key；服务端重新核验实际边界和新信号，客户端不能任意声明已经有费用授权/绕过限额。
- `GET /api/learning/coach/checks/{id}` 与 cancel/purge：复用当前异步生成、重开查看、取消、失败分类和私文清除约定。
- `POST /api/learning/coach/candidates/{id}/decisions`：operation、expected_revision、request_key；返回具体 action/target/draft/session 与应用阶段。
- `POST /api/learning/coach/signals/{id}/corrections`：exclude/restore、expected_revision、request_key；必要原话由原来源按本人权限实时解析。

建议新增迁移 `048_background_coach.sql`，只新增 coach settings、signal/source references、run/batch、candidate/decision 和 private originals/tombstone 的必要投影。优先把可重算/追加历史放入原 Core 事件账本；不得创建第二套会话/产出/教学快照。批次耗费和稳定去重必须持久化，不依赖进程内队列。

需要维护：`core/learning.py` 的命令分发/投影回放表，`core/events.py` 的有限 coach 事件；新增 bounded coach commands/application service/routers；`main.py` 生命周期与共享 slots；两类回答的同次结构接入；私文清除/备份擦除/恢复屏障；首页/计划卡和统一设置。实现者只改冻结范围，主 Agent 负责进度/产品决定/路线与提交。

### 5.1 前后端 DTO

以下为已冻结接口；前端无需读取后台实现猜字段。

```typescript
type CoachScope = 'global' | 'plan';
type CoachSettings = {
  revision: number; enabled: boolean; timezone: string;
  max_calls_per_session: number; max_calls_per_day: number; cooldown_minutes: number;
};
type CoachSource = {
  kind: 'event' | 'answer' | 'feedback' | 'claim' | 'revisit' | 'delayed_follow_up'
      | 'commitment_item' | 'path_version' | 'action' | 'permission' | 'artifact';
  id: string; revision: number | null; label: string; available: boolean;
  href: string | null; // 只由服务端绑定真实对象后生成站内入口
};
type CoachTarget = {
  kind: 'task' | 'evidence_review' | 'delayed_follow_up' | 'path_review'
      | 'commitment_review' | 'new_task' | 'permission_review';
  plan_id: string | null; action_id: string | null; delegation_id: string | null;
  object_id: string | null; href: string; label: string;
  permission_request?: { purpose: string; scope: 'learning_action'; target_id: string;
    content_granularity: 'full_text'; ttl_seconds: 300; alternative: string; request_key: string };
};
type CoachCandidate = {
  id: string; run_id: string; revision: number; scope: CoachScope; plan_id: string | null;
  status: 'pending' | 'accepted' | 'rejected' | 'ignored' | 'unavailable';
  title: string | null; explanation: string | null; unknowns: string[];
  target: CoachTarget | null; sources: CoachSource[];
  content_available: boolean; created_at: string; decided_at: string | null;
};
type CoachRun = {
  id: string; revision: number; scope: CoachScope; plan_id: string | null;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled' | 'purged';
  reason: string | null; created_at: string; finished_at: string | null;
  provider_snapshot: Record<string, unknown> | null; content_available: boolean;
  permission_candidate_id?: string | null; permission_request_id?: string | null;
};
type CoachView = {
  settings: CoachSettings; candidates: CoachCandidate[]; history: CoachCandidate[];
  active_run: CoachRun | null; latest_run: CoachRun | null;
  pending_signals: number; budget: { used_today: number; remaining_today: number; next_allowed_at: string | null };
};
```

- GET overview 默认返回当前 scope 的 `CoachView`。模型配置/时区/限额/历史按需，不把内部 enum 直接当产品文案。
- PUT settings 的请求为 settings 字段（去掉 revision）加 `expected_revision` / `request_key`，返回 `CoachSettings`。初始 disabled/1/3/30/UTC；首次开启保存本人界面显示的时区。
- POST check 请求 `{scope, plan_id?, trigger, request_key, retry_run_id?, permission_candidate_id?, permission_request_id?}`；返回 `{view: CoachView, run: CoachRun|null, reason: string|null}`。permission 两字段成对且仅 manual，沿原候选运行的 scope/model 归属。无新信号、限额、冷却、自动关闭不是生成失败；queued/running 只读轮询。API 不接受客户端提供模型输入/批次或来源正文。
- POST decisions 请求 `{operation:'accept'|'reject'|'ignore'|'undo', expected_revision, request_key}`，返回 `{candidate: CoachCandidate, navigation: CoachTarget|null}`；只有成功 accept 返回导航，其他操作不跳转。target 永远是站内结构化入口，不执行任意模型 URL。
- `GET /coach/candidates/{id}` 返回同一 owner 的单条 `CoachCandidate`，供接受后来源条，不放宽跨用户范围。首页与对应计划展示同一 candidate ID，包括 global 生成且 target 指向该 plan 的提案；owner active run 在各 scope 可发现，不重复生成候选。
- GET run 返回 `CoachRun` 和本运行 candidates / 仅已授权白名单输入的展开详情。cancel/purge 请求 `expected_revision` / `request_key`，purge 另加 `confirmation:'PURGE'`；清除含原结果/派生候选私文，保留无正文审计与来源屏障。
- source/候选原话纠正展开需补 `GET /coach/signals` 和单条 corrections，返回身份/类别/有效性/修订、可回看来源链接；默认卡片不展开全体信号。返回 source labels 为确定性类型文案，不从原文摘录生成全局“摘要”。
- target href 复用 `?view=plans&plan=…&plan_view=tasks|path|commitments`、`?view=records&record=…` 等现存入口；需要前端补齐 `coach_candidate` 的来源条/对应目标定位、`follow_up` 的指定回访展开、新任务/权限指定入口。接受记录与导航失败分开，重开可再次打开同一已接受目标，不把加载失败当作已执行正式变化。

建议文件所有权：后台实现负责 `backend/app/{background_coach.py,coach_integrations.py,routers/background_coach.py,core/coach_commands.py,core/background_coach.py,migrations/048_background_coach.sql}` 和必需的后台接缝、聚焦后端验证；前端独立实现负责 `frontend/src/{background-coach-api.ts,BackgroundCoach.tsx,BackgroundCoachSettings.tsx,styles/background-coach.css}` 以及 `Workspace.tsx` / `FactWorkspace.tsx` / `LearningPlans.tsx` / `Settings.tsx` / `DelayedFollowUp.tsx` 中相应接缝与聚焦浏览器验证。D2 的现有事实命令与教法 UI 不由前端 worker另改契约。新规格由后台实现者维护，进度/路线/产品决定仅主 Agent 修改。

## 6. 已冻结的实施接缝与成本边界

1. **同次 sidechannel 和普通聊天能力边界：** 当前结构教学输出只在已检查且本人启用的模型有效。建议仅在该通路附加信号，plain 保持；不得为了 D3 强迫 unknown 模型用结构输出或增加隐含检测调用。协议加字段要保持旧回答/分支/幂等只读兼容，信号失效不破坏原教法。
2. **D2 AI 草案来源：** 现有 AI 安排必须属于 `learning_commitment_run` 且由冻结 `input_hash`/source refs 验证。建议首片 coach 输出具体调整意图，打开对应 D2 的预填编辑/预览并保留 coach provenance；如冻结为直接产生完整 D2 草案，须新增明确的 coach-run→D2-draft 来源关联与约束，而不是 source=manual 绕过原 AI 校验。路径草案同样保留 coach run/source 引用。
3. **跨库成功与同次信号：** 普通聊天结果在主库、learning 信号在学习库。不能让信号写入失败回滚已保存正文；建议以不可变成功回答 ID/version 幂等导入，边界复盘时只补齐成功且有效的信号，不能为了补齐重调模型。
4. **正常暂停与异常中断：** Core 的 `session.ended(disposition=interrupted)` 被本人暂停、切换、转向等多条正常路径复用。以稳定 command/event 来源归并正常边界；异常恢复另记待复盘，不按同一个状态枚举自动计费。
5. **真正重复阻塞：** 按 4.1 的不同真实 session/尝试最小语义及既有教法纠正；不以错误次数推导完成或掌握。
6. **撤销语义：** 本切片建议撤销 coach 决策与正式 D2 撤销分开，页面必须说明已生效的正式变化需要原影响预览。不得接受“撤销”按钮暗中销毁正式任务/旧证据。

7. **有限输入：** 一个模型批次最多24个有效来源、4个计划、32个任务/64个委托；路线最多12节点/24边，保留完整拓扑指纹并标明 limited；安排最多每计划8项。同一 compact UTF-8 序列化口径总输入最多32768字节；必要时减少未引用的额外任务或本次源集合，未纳入来源保留待处理、不领取/标已分析。自动先排除额度已满的 session 再做 cap/优先级选择，旧待处理不能阻塞新会话；手动仍可处理原来源。旧事件按允许类型和未消费身份筛选，不被最近 coach 事件挤掉。

8. **本次明确授权：** 原 API 仍只申请 learning_action/full_text/300秒，候选私文绑定任务真实标题、目的和拒绝替代。server key 为 `coach-permission:<candidate>:<ordinal>`，pending/active 返回同 key；拒绝/撤销/过期只提供新未授权 attempt，创建和批准均本人操作，不续期。Core 核对候选→该 namespace 实际 request→owner/action/purpose/granularity/TTL→active grant/时效。`AgentRuntime.agent_context` 提供授权读取；本次选最多3份可见原任务产出，每份最多4000字符且原文合计最多12000 UTF-8字节，准确记录 artifact/version/start/end/hash 和未纳入标志，仍受全输入 cap。HTTP前、结束前复核本 grant/源版本，自动运行永不使用本 grant。消费按 request ID 独立一次逻辑批次：重复点击复用当前 attempt；明确 retry 继承原 candidate/request、仅在仍有效时增加新 attempt，不自动重试。

9. **清除闭环：** 授权原文/模型输入与结果仅入本 run 私文；源 artifact 清除同时擦除相关 run/后续派生 run 与注册备份/恢复屏障。coach说明复制到原权限 request.purpose 的副本也按 candidate 全 namespace 清除并撤销许可，保留无正文 ID/范围/时效/审计。回放使用既有 tombstone 固定清除时间，不能在重建时恢复已清内容或改写实际清除时间。

## 7. 聚焦验收

- 开关、日/会话限额、冷却、时区日界线、并发预留、跨浏览器/刷新幂等与重启不重复付费；没有有效新信号时零 Provider 调用；一个批次多个候选仅一次调用。
- 两类对话同次信号、source 真实绑定、plain 回退、取消/失败/部分输出/恶意未知枚举与旧协议；纠正、排除/恢复、复制分支、源删除/清除不制造重复阻塞。
- global 与 plan 使用正确 C3 归属和接受时快照；修改配置不改已接受运行；默认输入无原话/资料/反馈 notes/statement/私有路径标题/旧 full_text grant。拒绝/撤销/过期不泄漏，也不妨碍本人学习。
- 真正 AI 生成的多种候选：有来源、有未知、无越界 ID；接受打开真实对应对象或受控草案，正式确认仍经原预览；拒绝/忽略/撤销、晚到结果、范围变化、请求冲突和重复操作有实际正确效果。
- coach 私文及由其引用导出的副本，在本库/注册备份/受控恢复路径一起清除；Core 事件回放当前投影一致，原学习/证据/路线/完成身份与记录保持。
- 桌面与 390px：卡片短、普通学习无频繁弹窗、依据按需、现有入口准确、键盘/取消/焦点可用，失败后可继续原学习。工程检查与作者真实建议质量/体验验收分别报告。

本契约已完成对应实现与独立工程验收，原trial048已由主Agent使用正式工具升级启用。检查使用隔离合成数据和本地模拟模型；真实建议质量、节奏及长期效果由本人试用继续核对。实际文件、检查、备份/数据保全、运行资源与本地提交见开发状态。
