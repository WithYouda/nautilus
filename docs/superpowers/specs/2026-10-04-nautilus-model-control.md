# C3 模型与超时的五级控制

日期：2026-10-04。状态：作者已选择先完成本切片，相关检查通过并在原trial040启用；不包含思考强度或“节省／平衡／深度”策略预设。依据PRD V2 7.5、产品决定9.6–9.7及当前路线C3。实际检查与启用见开发状态。

## 用户行为与边界

- 全局 → 计划 → 任务 → 对话 → 仅本次。模型选择与超时分别继承；Provider和其模型作为一组选择，避免继承出不属于该Provider的模型。
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

任一字段为null/省略表示继承；超时沿现有5–600秒限制。全局必须给出模型组合与超时。

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
