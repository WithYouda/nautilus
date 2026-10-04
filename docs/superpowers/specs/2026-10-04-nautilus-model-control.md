# C3 模型与原生思考控制

日期：2026-10-04。状态：模型首片、超时简化及最新每模型默认/当前对话滑块修订均已通过相关检查并启用原trial041。“节省／平衡／深度”等模型策略预设仍待具体方案答复。依据PRD V2 7.5、产品决定9.6–9.7及当前路线C3。实际检查与启用见开发状态。

## 后续方向修订（2026-10-04，已实施并启用）

作者接受超时简化：平时使用实际所选Provider的默认超时，需要时仅本次延长；模型五级继承保持，计划/任务级超时例外待明确使用场景再决定。此调整已启用原trial040，无迁移。非全局持久接口拒绝非空超时；旧列保留、不再参与新运行，旧回答快照保持原样。仅本次值须不小于最终Provider默认值，接受后原配置仍可幂等重放。下文为首片历史契约，涉及超时五级的描述由本段覆盖。随后原生思考强度与输入区右侧快选已按下述增量启用，调研与当前进度见开发状态。

## 用户行为与边界

### 原生思考控制增量（2026-10-04）

作者最新确认：思考采用“每模型默认＋当前对话选择”，取代此前五级思考继承与仅本次。两处输入区右侧、发送按钮旁使用同一刻度滑块，拖动预览、松开保存；不提供作用域切换、恢复继承或“模型默认”伪档位。生成中修改只影响下一次发送。普通学习室尚无对话时先建立真实对话，不能误写全局或任务设置。

供应商配置中为所选模型保存默认思考设置。未配置且实际支持high时默认high；没有high的模型必须明确选一个真实支持的默认值，不把等级映射成猜测的Token预算。未知或明确不支持的模型不伪造high。当前对话选择绑定实际所选Provider/model，包括临时模型；切换到其他模型时使用该模型默认，不套用旧模型强度。仅保存模型/超时不会抹掉已有思考选择；思考快选不会把临时模型/超时变为持久配置。一段对话保存最近一次明确思考选择及其模型绑定，不建立逐模型选择历史。

“关闭思考”是独立真实选项，位于最左；右侧才从最低实际思考等级开始。不能关闭的模型不显示虚假的关闭选项，low/minimal不能冒充关闭。仅预算模型直接使用实际预算/明确支持的动态预算，开关模型使用真实开关；不假造统一等级。RikkaHub AUTO通常省略effort或请求自适应，不等于用户配置默认，不增加统一AUTO等级。

能力识别依次为有效的手动兼容规格、模型列表返回的可用字段、已核查具体模型ID的官方规格。DeepSeek列表读取effort.supported_levels，Claude读取effort/thinking能力，Gemini读取thinking布尔；OpenAI标准列表未提供等级。缺失、false及空列表不混淆，不靠未知名称猜测。模型列表请求沿原列表获取动作一并读取能力；预览只读取本地配置/缓存，不触发生成。配置与发现事实绑定模型ID、协议和地址指纹，变化后不能沿用旧绑定。手动选择表示用户声明兼容性，不冒充真实账户探测。

模型默认保存在既有provider_model.overrides_json，能力及发现事实保存在capabilities_json；当前对话在041已有reasoning_json保存{choice,model}。本修订无新迁移，旧全局/计划/任务思考设置保留但不参与新运行。旧对话裸choice仍可读取；旧已接受仅本次请求按原快照幂等重放，不允许新发送携带仅本次思考。运行token绑定实际能力、选择和配置，快照保存实际原生参数；历史不补造，分支复制创建时的对话设置与绑定。

接口：GET/PUT /api/ai/providers/{provider_id}/models/{model_id}/reasoning-support，PUT接受expected_revision、profile_id及可选default_choice；模型配置保存也支持reasoning_settings并在写凭据/连接前校验。POST /api/ai/provider/reasoning-preview返回capability、default_choice、configured_default、default_required与兼容规格。旧全局思考写入接口明确拒绝并指向模型配置。当前对话沿既有模型配置PUT保存reasoning及reasoning_model；省略reasoning时保留当前选择及绑定。所有入口保持owner校验与版本冲突保护。

互斥选择为off、on、effort（原生effort字符串）、budget（实际budget_tokens，仅明确支持预算内effort的模型可附effort）。旧mode:default只用于兼容清除/快照解析，不在新UI中作为档位。新配置或选择不支持时明确拒绝，不自动删字段或降档。四种协议的普通请求及每个工具续轮复用已验证原生编译路径。

思考强度是原生控制信号，不保证固定Token量或质量。旧Claude预算请求保留既有回答额度并增加明确预算；自适应Claude仍受现有输出上限约束。模型策略预设仍待作者具体方案答复，本增量不自动选择模型。官方及参考项目依据见[调研](../../research/2026-10-04-nautilus-reasoning-controls.md)。

### 模型控制既有行为

- 全局 → 计划 → 任务 → 对话 → 仅本次。模型选择沿五级继承，超时按上述简化规则；Provider和其模型作为一组选择，避免继承出不属于该Provider的模型。
- 全局继续使用现有默认Provider、其默认模型与超时。下层未设置的字段向上继承，恢复继承不复制当时上级值。
- 计划/任务在现有计划页提供折叠入口；两处对话沿现有配置入口提供当前对话与仅本次选择，显示实际值及来源。全局沿现有设置维护。
- 保存持久覆盖不调用模型；仅本次为发送草稿的一部分，接受成功后清除，不改变持久设置。请求结果未知时保留相同请求编号和覆盖，重试不得重复调用。刷新不承诺保留未发草稿。
- 新生成和重新生成使用接受时的当前模型条件；同一请求编号的重放继续对应原运行。运行中修改只影响以后接受的请求，旧回答显示当时实际配置，缺少的旧来源不补造。
- 题目讨论作为独立对话继承其实际任务/计划，不再动态跟随同委托最近打开的其他学习室；原正式验证继续沿已确认的学习室模型选择规则，不由讨论覆盖反向修改。
- 普通分支保留原任务归属和创建分支时的对话覆盖，分支之间随后独立修改；题目分支保留原验证归属并复制讨论覆盖。复制的历史运行仍保留原快照，模型设置不改变资料/工具权限。
- 显式模型失效或凭据不可用时明确失败，不换Provider、不退回默认、不改资料和联网选择。联网选择独立保存，原生搜索能力在新发送时按最终模型检查（含仅本次模型），不因持久默认不支持而阻挡兼容的仅本次选择；私文原生搜索限制保持。当前页面设置过期时拒绝发送并要求刷新；已接受请求的幂等重放不受后来配置变化阻断。

## 现有基础与增量

普通对话已有`conversation_config`与`ai_run.config_snapshot_json`，讨论已有`learning_discussion_turn.provider_snapshot_json`及单次冻结。复用现有执行器、搜索冻结、帮助/教学状态、版本与清除，不建立第二套运行历史。

新学习域新增040模型覆盖表，按owner、scope kind/id保存稀疏覆盖与revision；不保存凭据或私文。全局继续用普通库Provider表。旧普通对话配置在尚无新覆盖记录时可读；新写入后新记录为唯一有效来源，空覆盖行表示明确恢复继承，不能重新拾起旧配置。旧表与旧迁移不改写。

普通学习室归属沿`learning_room_conversation → learning_session → learning_delegation → learning_action_link → learning_plan`解析，独立聊天只有全局和对话级。讨论沿原verification的action/delegation解析。旧规划域的`conversation_link`不作为新领域继承依据。

模型设置与资料/路径当前态分开保存，避免整对象更新互相覆盖。修改使用revision检查；新发送可带生效链token核对预览是否过期。Provider/模型引用跨库按owner校验，不以ID存在替代归属。

## 接口契约

路径为`/api/model-config/{kind}/{scope_id}`；kind为`global|plan|task|conversation|discussion`，global的scope_id固定`default`。

覆盖对象`ModelOverride`：

```json
{"model": {"provider_profile_id": "...", "provider_model_id": "..."}, "timeout_seconds": 60}
```

model为null/省略表示继承；超时沿现有5–600秒限制并按简化规则使用。全局必须给出模型组合与超时。思考的省略、绑定及兼容字段按上述最新增量处理。

- GET返回`scope_kind, scope_id, revision, token, override, effective, sources, layers, issues`。
- PUT接受`{expected_revision: string, override: ModelOverride}`并返回新GET结构。
- POST `.../preview`接受`{override: ModelOverride}`，只计算仅本次结果，token绑定持久配置链、该覆盖及最终选中模型的配置/能力；预览不写入持久覆盖。
- `effective`含Provider/模型ID及名称、协议、超时、图片/思考内容能力、可用性和密钥存在标志，不返回密钥、凭据引用或完整地址。
- `sources.model`与`sources.timeout`均为`{kind,id}`，kind含五级中的`run`；layers只含持久层级、revision和稀疏覆盖。
- 两类发送增加可选`model_override: ModelOverride`与`model_config_token: string`。幂等比较覆盖本身，不以后来token变化改变已接受请求。
- 两类回答增加只读`model_config`，从该回答快照输出当时Provider/模型名称、协议、超时、配置版本、字段来源；旧记录仅展示实际已有字段。

## 检查与启用计划

聚焦两字段独立继承、清除覆盖、两种对话/分支隔离、旧配置兼容、身份校验、模型失效拒绝、旧页面冲突、仅本次消耗/重试、接受后冻结与历史回看；检查资料/搜索/教学和正式验证未被模型选择改变。

前端检查两处发送/刷新/恢复继承、计划/任务入口及手机宽度；复用未变的教学检查。040已在隔离库演练，并按原trial常设授权使用正式升级工具、自动前后备份及旧表完整性/数据保存检查启用；不操作默认data或另一个环境，不push。
