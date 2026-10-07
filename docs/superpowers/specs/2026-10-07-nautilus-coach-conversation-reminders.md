# Nautilus D3 补齐：教练持续对话与督学

日期：2026-10-07。状态：**本契约工程已完成独立审查与相关检查，并在同一原trial049启用；真实教练质量和督学体验仍待本人试用。人格加载与关闭应用后的推送不在本次交付。**

代码勘查基线：`a4a7bd8`。本轮两名 `gpt-6.1-sol/xhigh` 分别实现后端与前端，另一名同模型/强度独立审查，主 Agent 负责契约、整合、产品决定和启用。沿用 PRD V2 7.4 / 8.4、产品决定 9 / 10 / 12 及 10-05 后台教练契约；048受控复盘继续可用。

## 1. 本人确认的范围

- 本轮先补齐教练持续对话及督学，人格紧接着单独实施。本轮不以系统 Prompt 冒充人格加载。
- 教练可围绕今天时间、精力、拖延与中断恢复持续交谈，并提供现有任务、近期安排及原调整入口的可执行导航。
- 督学采用应用内提醒；浏览器支持且本人明确授权时也可通知。关闭应用后的推送留待后续，本轮不承诺。
- 提醒开关独立于自动复盘，默认关闭。本人选择固定学习时间，也跟随当前有效近期安排的具体时点。
- 未开始后追加一次的初值为30分钟；全局每天至多2次；免打扰初值22:00–08:00。固定时间、追加间隔、日上限和免打扰均可调整，不能把初值写死成不可改行为。
- 督学实时核对当前安排及真实学习状态，开始不等于完成；完成、暂停、改期、跳过和目标状态变化都影响后续提醒。
- 正式任务、委托、路线、安排、证据与长期状态仍走原确认流程。打开教练、发送消息、接受导航或收到提醒均不代替正式操作。

## 2. 现有复用边界

| 能力 | 代码事实 | 本轮规则 |
| --- | --- | --- |
| 普通会话 | `conversations.py:1348` 已支持global；`1205` 的global_context仍读取旧计划域 | 复用conversation/message/ai_run/context_snapshot，不读取旧域作为新教练上下文 |
| 新学习室归属 | `learning_room.py:59` 只允许independent会话绑定真实session | global教练不绑定learning_room_conversation，不制造教学session |
| 消息运行 | `/api/ai/conversations/{id}/messages`、`/api/ai/runs/{id}/stream`、cancel；AiRunManager共享Provider槽位 | 所有教练消息走同一接受、冻结、流式、取消、重试与恢复链 |
| D3摘要和动作 | `coach_sources.py:155` 按实际refs限制计划/任务；target/校验已有 | 复用白名单与target校验；补一个可在没有新复盘信号时读取的当前导航摘要，不能用空refs冒充全局状态 |
| D2时间 | due_at为带UTC偏移的具体时刻，timezone为IANA时区；UI为datetime-local；有效改期在item.future_due_at | 读取当前有效item和window，不能使用旧版本里的due_at作为当前提醒时间 |
| D2真实执行 | `core/commitments.py:100` 按action/delegation派生完成；`423` 起学写execution→session | 合并item、action、delegation及session状态；未开始、已开始、暂停与完成分别表达 |
| 现有后台检查 | `background_coach.py:323` 仅监控用户正常session.ended；前端返回触发return复盘 | 定时督学是确定性服务；不复用自动复盘开关、预算或模型运行 |
| 清除 | 普通DELETE仅soft-delete；ManagedPurge现有coach_run只擦新学习库；material_purge已有跨DB擦除和后代闭包 | 教练专属清除需沿受管理跨DB机制扩展，不得声称soft-delete即彻底清除 |

## 3. 会话身份、上下文与事实隔离

### 3.1 身份

建议新增学习库迁移 `049_coach_conversation_reminders.sql`，只新增教练会话映射、提醒设置、提醒发生记录及清除屏障；不修改001–010，不给普通库增加新迁移，不新增另一套消息或AI运行表。

`learning_coach_conversation` 保存owner、普通conversation_id、创建/更新时间、角色版本、purged_at。普通会话保持context_scope=global；只有被本人新建并登记映射的会话采用本契约。旧global会话不能自动转成教练，旧independent教学会话不能自动扩大范围。普通会话的所有权与映射owner都必须一致。

首页“学习教练”打开最近仍有效的已登记会话；没有时仅本人打开入口明确创建一条。历史继续读原conversation/message，支持另开一次教练对话及历史返回，不按组件挂载隐式创建。双请求/多页打开以服务端request_key和原子映射领取去重；跨DB创建失败留下的未登记普通会话不能当教练读写，应清理或显示可恢复的失败，不重复产生运行。

### 3.2 默认可见内容

- 本人当前教练会话所选路径的消息；本人在这里主动提供的时间、精力和说明仅属本次对话上下文。
- 新学习域当前计划/目标ID、最小标题、状态；现存任务/委托的ID、标题、版本和可执行状态；当前路径位置引用；当前有效近期安排、时刻、预计范围及真实执行状态；已有证据/回访的ID和状态引用。
- 不默认读取任务会话、作答、产出正文、反馈notes、资料/附件、旧计划域、路径私文或完整历史批次。旧grant不得自动流入本会话。
- 本轮教练对话不新增任务原文授权读取。需要私文时说明当前范围，提供原048权限复盘入口或请本人自行概述；打开本人产出回看不等于授权教练读取。
- 每次发送冻结角色、白名单摘要、来源ID/版本、允许targets与实际Provider/model/timeout/reasoning。发送前和保存结构动作前重核资格；来源已变则动作不可执行，正文历史不改成新事实。

不得把今天“我很累”“我拖延”等消息自动写入反馈、偏好、完成或掌握记录；不调用StartSession、EndSession、ConfirmCommitments或证据命令。教练角色不用任务教学活动/assignment_signal回写，不因全局教学默认模式强制出题。人格与长期偏好仍属后续。

### 3.3 对话与动作

同次回答可给简短解释及0–3个动作，目标只允许来自本轮冻结targets。可建议继续现有任务、查看/核对当前安排、调整路线或进入单独安排入口；提供具体原入口。用户点击仅导航，不自动起学、不移动焦点、不确认正式草案。

结构输出沿现有能力检查和同次流式协议扩展；不为补动作再起模型调用。能力不足时普通对话仍可用，并展示服务端当前可用入口。结构部分不合法只丢弃动作，保留合法正文；不能把模型任意链接/对象ID当导航。动作展示前与点击resolve时都要核对真实owner、版本及可执行状态。正文中自称已修改或已开始没有领域效力。

应用内首页保留048建议卡，新增明显而简短的教练入口；对话复用现有消息/运行呈现，称“学习教练”，不能把教学session或旧“全局AI”直接改名后宣称功能完成。

## 4. 督学的确定性语义

### 4.1 时点与设置

提醒设置与048设置分开。未设置具体学习时间时不替本人猜一个时刻。启用需有至少一个本人固定时点或当前有效带时刻安排；没有可用时点返回明确可操作的设置错误。

固定时点按设置中的IANA timezone、星期与当地HH:MM解释；D2安排按item.future_due_at的UTC时刻，原future_timezone仅用于解释。免打扰按提醒设置时区划日，跨午夜时段支持。日限额、追加间隔、免打扰开始/结束均由本人调整；不存在隐藏第二份时间配置。

### 4.2 当前资格

发出、追加、免打扰结束合并、打开目标前，都重新计算资格：

- owner一致；目标/计划仍开放；action未移除/完成/关闭；delegation仍可执行；当前path未暂停、当前有效安排/来源仍存在。
- item不是completed、skipped、失效或被新window移出的旧项。改期以当前future_due_at重新计算，旧occurrence失效，旧提醒不能继续按旧时点追加。
- 通过learning_commitment_execution和learning_session核对该项是否真实开始。开始立即抑制该次“未开始”追加；普通task入口启动同委托也算开始，不因未写item execution伪称未开始。
- 本人的任何真实学习session正在running时，不弹普通催促。会话结束/暂停不等于任务完成；已开始本次不自动重设为未开始，剩余内容按本人当前安排继续。
- 已开始但结束/暂停且未完成的当前有效安排，在下一次本人固定学习时间提供“继续上次的学习”及真实入口。该固定恢复提醒仅发首提醒，不追加“未开始”；原安排的未开始追加继续停止。完成或来源失效后撤下旧提示，不自动写完成。
- 目标暂停/完成/停止追踪、路线暂停、skip、行政移除等立即取消待发提醒；恢复后依当前有效安排重新计算，不重放历史提醒。
- 没有可执行安排时，固定学习时点可以提供“安排学习/打开教练”入口；不伪造任务、逾期或完成情况。

### 4.3 首提醒、追加和合并

每个当前学习发生项有稳定occurrence_key，由owner、当地日、固定时点/有效item身份与当前时点组成；同一时刻的固定时间和安排合并为一条。提醒先选择现有顺序中的可执行安排，不新增隐含优先级算法。

首提醒发出后仍未实际开始，可在可调追加间隔后最多再发一次；追加也占同一owner的全局日限额。无安排的固定恢复入口只发首提醒，不声称具体工作未开始。不因本人没点“已读”而再次追加。

免打扰期内不弹通知；结束后至多合并一条当下仍有效的提醒，逐个历史时点不补发。running学习抑制期间同样不累计待补发队列。应用断连/重启只恢复确定性发生记录，不产生模型调用，也不把历史所有到期项集中通知。

设置关闭或改动后重核所有未发送资格。已发生历史可保留最小身份/时间/状态，不能把旧通知当现有学习事实。全局每日上限跨计划、网页、浏览器tab和重启共用，按持久时区划日；启用/关闭不能清零当日已发送次数。

### 4.4 通知领取与浏览器

服务端计算并持久化提醒发生项；GET仅列状态，弹出资格由显式POST dispatch原子领取。每个occurrence与阶段只允许一次成功领取；同一领取同时承载应用内和已授权浏览器通知，计数一次。多tab、刷新、网络重试返回同一领取结果，不使其他页面再弹。

前端在已登录且应用打开期间轮询提醒状态；只对本次成功新领取显示应用内提醒及可选浏览器Notification。重连前已有领取仅保留应用内历史，不再次弹通知。领取成功而页面立即关闭时允许留下已发送/未确认记录，不重新广播，从而保持不重复；该有限交付不保证系统通知确实被人看到。

浏览器是否支持、secure context、permission均由真实环境读取。只有本人明确点按钮才requestPermission；denied/default不影响应用内功能。请求权限失败、HTTP环境不支持或系统拦截时如实显示应用内仍可用。通知只写最小任务标题/短提醒，不带对话私文；点击通过服务端当前target导航。关闭应用后推送不属于此接口承诺。

## 5. 前后端冻结DTO草案

以下新增字段供前端直接使用，原AiConversationDetail / AiSendResult / AiRun及SSE保持兼容。

```typescript
type CoachConversationInfo = {
  conversation_id: string; role: 'coach'; role_version: number;
  created_at: string; updated_at: string; purged_at: string | null;
};
type CoachAction = {
  id: string; label: string; target: CoachTarget;
  source_revision: string; available: boolean; reason: string | null;
}; // CoachTarget沿048；id由服务端产生，不能接受任意href
type CoachMessageContext = {
  role: 'coach'; schema_version: 1; source_revision: string;
  actions: CoachAction[]; unknowns: string[]; content_available: boolean;
};
type CoachConversationDetail = AiConversationDetail & {
  coach: CoachConversationInfo;
  coach_context: { source_revision: string; summary: string; actions: CoachAction[] };
};
// AiMessage新增可选coach: CoachMessageContext；历史回答只回自己的冻结动作。
// 动作与最终正文一起在原done/start重放中的coach字段返回；AiSendResult.messages也含同字段。
type CoachReminderSettings = {
  revision: number; enabled: boolean; timezone: string;
  browser_enabled: boolean;
  followup_enabled: boolean; quiet_enabled: boolean;
  study_times: Array<{ id: string; weekdays: number[]; time: string }>;
  followup_delay_minutes: number; max_per_day: number;
  quiet_start: string; quiet_end: string;
}; // weekdays:1=周一…7=周日；time/quiet为HH:MM；全部时间字段可编辑
type CoachReminderTarget = {
  kind: 'commitment_item' | 'coach' | 'commitment_review';
  plan_id: string | null; action_id: string | null;
  delegation_id: string | null; item_id: string | null;
  href: string; label: string;
};
type CoachReminder = {
  id: string; revision: number; occurrence_key: string;
  stage: 'initial' | 'followup' | 'quiet_digest';
  status: 'pending' | 'dispatched' | 'suppressed' | 'unavailable';
  title: string; body: string; target: CoachReminderTarget;
  scheduled_at: string; dispatched_at: string | null;
  source_revision: string; reason: string | null;
};
type CoachReminderView = {
  settings: CoachReminderSettings;
  due: CoachReminder[]; recent: CoachReminder[];
  learning_active: boolean; quiet_now: boolean;
  budget: { used_today: number; remaining_today: number; local_date: string };
  next_due_at: string | null; revision: string;
};
type CoachReminderDispatch = {
  reminder: CoachReminder | null; claimed: boolean;
  reason: string | null; view: CoachReminderView;
}; // claimed=false绝不能再次弹；重放同request_key也不能要求前端再弹
```

| 方法和路径 | 请求 | 结果 |
| --- | --- | --- |
| GET `/api/learning/coach/conversations` | 无 | `{items: CoachConversationInfo[]}`；只本人、只已登记仍可查看的会话 |
| POST `/api/learning/coach/conversations` | `{request_key, new_conversation?: boolean}`；默认false | `CoachConversationDetail`；返回最近或原子建立；true为本人明确新建 |
| GET `/api/learning/coach/conversations/{id}` | 无 | `CoachConversationDetail`；映射+普通会话双检查 |
| 原POST `/api/ai/conversations/{id}/messages` | 原AiMessageSendRequest | 原AiSendResult；服务端识别coach角色，无新增消息运行协议 |
| 原GET `/api/ai/runs/{id}/stream`、cancel | 原请求 | 原SSE/Run；最终及重放带可选coach字段 |
| POST `/api/learning/coach/conversations/{id}/actions/{action_id}/resolve` | `{source_revision}` | `{target: CoachTarget}`；来源资格重核，只导航 |
| POST `/api/learning/coach/conversations/{id}/purge` | `{confirm: true, request_key}` | `{coach: CoachConversationInfo, purge_report}`；不可恢复的教练私文清除、失败可重试 |
| GET `/api/learning/coach/conversations/{id}/purge` | 无 | `{purge_report}`；清除后映射仍可取得无私文进度 |
| GET `/api/learning/coach/reminders/settings` | 无 | `CoachReminderSettings` |
| PUT `/api/learning/coach/reminders/settings` | 设置全字段+`expected_revision`+`request_key`，不传revision | `{settings: CoachReminderSettings}`；先完整校验再原子保存 |
| GET `/api/learning/coach/reminders` | 无 | `CoachReminderView`；不调模型、不消费弹出预算 |
| POST `/api/learning/coach/reminders/{id}/dispatch` | `{expected_revision, request_key}` | `CoachReminderDispatch`；当前资格+预算+同发生项领取原子化 |
| POST `/api/learning/coach/reminders/{id}/resolve` | `{source_revision}` | `{target: CoachReminderTarget}`；重核当前来源后导航 |

设置校验：时区为有效IANA；study_times最多14个，星期数组非空、唯一、1–7，时点同日不得重复；追加间隔为整数1–1440分钟；日上限为整数1–100；免打扰HH:MM合法，quiet_enabled=true时开始≠结束。默认study_times=[]、browser_enabled=false、followup_enabled=true、quiet_enabled=true，不默认硬塞学习时刻。本人可以关闭追加或免打扰。browser_enabled只保存本人是否选浏览器渠道，不能冒充系统permission。初值限额只是本人试用设置，不是最优频率主张。

教练消息在此切片不开放search/material/attachment/teaching工具；原API收到非off搜索、非unspecified资料范围、非空附件或任务教学动作要明确拒绝，前端不呈现对应任务控件。Provider/model/reasoning仍沿现有全局→会话→本次运行控制，接受后冻结。用户明确消息运行不占048自动复盘预算；提醒dispatch永远不调模型。

## 6. 跨DB私文、清除与恢复责任

原会话DELETE继续只代表隐藏/soft-delete，不能冒充教练内容彻底清除。教练purge必须先持久化无私文receipt，再在共享锁内停止/取消活跃回答和标题运行，擦普通DB消息、思考、context_snapshot摘要/payload、运行config_snapshot里的私文/模型turn/trace、标题及所有从该教练来源产生的复制分支和后代回答。学习DB擦当前会话状态的私文设置及教练相关私文副本，保留owner、conversation/run/source ID、清除时间和最小状态屏障。未来源关联的其他教学记录、正式事实和独立共享资料不随此删除。

复用 `material_purge` 的双DB路径登记、来源闭包、普通消息/上下文擦除、备份清单、receipt、secure_delete/VACUUM/日志处理和失败重试约定，扩展明确kind=`coach_conversation`。不能把教练本人输入错误归为material或artifact来绕过所有权检查；不复制原文进Core事件或receipt。清除前列出会话/分支影响，用户明确确认。

新增mapping及tombstone登记到COACH_PURGE_TABLES / PURGE_BARRIERS / PRIVATE_COLUMNS及恢复检查；普通DB对应擦除与启动时receipt核对也必须纳入。同一receipt覆盖两个DB和已登记备份，任何一侧失败为partial，不宣称complete。恢复只接受已经符合清除屏障的候选；先于049的旧备份缺映射/屏障时不得恢复被清除原文。普通DB单独被旧文件替换时，启动在提供会话读取或AI发送前执行receipt屏障核对/擦除，不能因学习DB已清除而重新可见。

purge、取消或来源清除后的晚到回答不能复写正文/动作；提醒关闭只阻止未发提醒，不取消本人正在进行的教练对话或048设置独立控制的复盘。跨DB停机途中保留可重试receipt。对话默认未读取任务原文，后续若扩原文授权，需另冻结授权生命周期及源清除→所有派生回答闭包，不能把本草案当该读取已授权。

## 7. 验收及交付边界

- 后端：同一owner连续会话/历史、重复创建及重复发送幂等、global/教学session隔离、新域/旧域隔离、来源冻结、动作越界拒绝、来源变动resolve失败、正文保存与正式学习事实不增加、Provider失败/取消/重启、双DB清除与晚到拒绝、备份擦除及恢复屏障。
- 督学：可注入clock，不真实等待；具体安排时点、固定时点合并、未开始追加、全局日上限、时区跨日、免打扰/合并、running抑制、开始不当完成、结束/暂停、改期/skip/目标状态/移除、设置关闭、多tab原子领取、同key重放与重启不重复；全部无需真实Provider。
- 浏览器：今天时间/精力/拖延讨论可显示真实可执行入口；消息取消/刷新/历史；点击只定位原流程；提醒设置所有时间可改；应用内+mock真实浏览器能力/授权分支；导航及时失效；桌面及手机宽度检查。关闭应用后不承诺推送。
- 独立Sol审查确认权限、数据生命周期、重复通知和领域事实隔离后，主 Agent 完成必要整合检查、状态/决定更新、本地明确路径提交及按既有常设授权升级原trial。工程检查与本人实际对话/督学体验分别记录。

## 8. 已冻结的补充决定

1. 主 Agent 已确认上述数值范围；提醒本轮不新增snooze/dismiss服务端语义，界面可关闭当前提示或在设置中暂停。
2. 免打扰结束后的合并按首提醒处理，仍占日次数，后续追加受全局上限；不逐个补发历史时点。
3. 本轮教练不开放跨会话复制分支，UI隐藏fork入口，后端所有fork/clone出口明确拒绝coach；同会话编辑、重试和选路径保持。清除覆盖完整本教练会话，不重做普通chat删除产品。本接口不扩任意资料/任务原文读取。

后端检查点：18项新增教练/提醒检查及244项相关既有检查，共262个不同检查通过，全部使用`/tmp`隔离数据及模拟Provider。覆盖实际D2确认/改期/开始/结束/本人完成、固定时点恢复、原子领取、跨时区预算、权限与教学隔离、双库/备份/源依赖清除、main启动时普通库单独回滚屏障，以及原教学JSON/普通会话/048复盘与升级恢复定向回归。重复修复运行不累计为更多检查；此证据不代替浏览器整合、真实教练质量和本人试用。

最终整合：新浏览器9项同组、7项既有兼容、TSC/受测构建及1280/390/320页面审阅通过；独立审查无剩余阻塞。原trial048→049采用正式工具自动前后备份，旧数据和88原备份文件保持，63项静态资源/健康/鉴权检查通过。启用时5新表为空，提醒默认关闭，无真实模型调用或业务种样。详细证据与下一项见开发状态；只本地提交，不推送云端。
