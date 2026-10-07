# Nautilus 上限与截断清单（2026-10-07）

作者已确认三组具体修改并统一启用原trial049。以下先列本次处理结果，再保留最初盘点作为历史证据；旧表数值不代表当前仍生效。[当前开发状态](nautilus-development-status.md)记录验证与保留项。

范围：当前工作树的backend/app、frontend/src、frontend/native、native和日常scripts/start.sh，起始提交bb55f0f。通过全目录关键词扫描、调用处阅读与Pydantic字段AST核对整理；gpt-6.1-sol/xhigh负责非token清单，主Agent补输出token表并复核整合。条目区分拒绝、截断、仅显示及可配置行为；不会把仅分页/折叠误报为删除内容。

没有读取真实学习正文或调用真实Provider；未核验已安装原生包与第三方库/厂商/系统全部固有限制。不包括纯内部ID宽度、CSS尺寸、锁文件、依赖、历史迁移。这里是已发现且核实的限制，不宣称穷尽所有协议与第三方实现。

下文“字/字符”指Python Unicode字符；Web maxLength按UTF-16计数，部分emoji计数会不同。KiB/MiB按1024进制；token不是字数。

## 本次处理结果（已启用，以下旧数值表为历史盘点）

| 范围 | 处理结果 |
|---|---|
| A01–A15、A17 输出额度 | 取消应用固定token与默认48，包括标题/连接测试；Claude用真实模型最大值，其他协议不传应用预算。模型或服务商自身默认值/上限仍存在。A16真实思考规格校验保持。 |
| B01–B05、B11–B14 正文与合并 | 输入、作品、正文、反馈/引用、合并卡片数量与单卡正文门槛已取消；来源、类型、非空和短名称校验保持。长度不足内存时明确拒绝，不截原文。 |
| B06–B09、B19、B25 历史/上下文 | 当前允许路径完整历史、相关匹配原文及协议块不再按固定条数/字节丢弃；来源范围、清除和协议兼容性仍决定哪些内容可进入。B10自动标题继续使用简短摘录生成短名称。 |
| B15–B24 传输与教学记录 | 工具参数/结果/轮次和事件数量不再有旧固定额度；保留调用标识/格式校验、每轮明确工具预算、总期限和可用内存检查。大响应临时缓冲后解析，缓冲阈值不等于正文上限；生产教学JSON不再16KiB截断。 |
| B26–B32 教练 | 完整扫描积压来源、每批24项逐批消费；取消32KiB及附加计划/任务/拓扑裁剪。授权作品完整读取，摘要不扩大原始内容权限；结构化动作/未知事项不再因超过3/5项整组丢弃。 |
| B33、B35–B36 路线/建议 | 取消计划100任务、路线60节点/100边、每节点30关联、建议30成果/60候选等门槛，补齐UI/路由/Core三层。AI安排仍遵守真实校准、本人时间预算和日期有效性。 |
| B40–B46、C09–C10 内容 | 反馈、材料、补练、人格正文和网页结果保留完整实际内容；旧截断不补造。名称等短字段及有意义的语义/权限校验保持。 |
| C02–C03、C18–C20 检索 | 外部/知识库次数可设正整数，移除原5次/固定4次的配置障碍，接受时冻结；保留有限循环、分页/继续读取、授权和取消。 |
| C04、C13 外部返回 | 取消普通服务2MiB响应门槛和Exa固定maxCharacters；保留DNS/URL、重定向、超时和实际内存检查。服务商可能返回摘录，保存的是实际取得内容，不声称总能取得网页全文。 |
| E11–E12、E15–E16 查看 | 教练处理及提醒历史可翻页；日历更多项可展开；周指标从完整列表计算。 |
| 继续保留的必要控制 | 单会话状态、并发/取消/超时/有限重试；日志与缓存；脚本沙箱及其网络/IPC资源界限；鉴权/来源/版本/撤销/清除；本人督学频率/免打扰、正式验证标准；格式枚举、内部标识及短名称。 |
| 未取消的额外字段 | 权限申请说明500/1000字、督学信号短引用500字、批量证据100项、组织排序10000项等原操作字段门槛保留。自动审批对额外移除明确拒绝，认为超出具体授权且削弱操作/资源保护；本轮未绕过，也不将它们标记为已取消。 |

本轮没有修改真实历史内容、标准或资料归属。实际检查、已知基线失败及启用记录见开发状态；供应商返回的真实容量错误会明确显示，应用不自行换模型或缩减原文。

## A. 模型输出token限制

| 编号与功能 | 当前值与影响 | 代码位置 |
|---|---|---|
| A00 分支合并（本轮已取消） | 原min(8192,已知模型cap)改为显式None；Chat/Responses/Google省略输出预算字段，不回落适配器48。Claude协议强制参数，取已知能力（模型发现元数据须绑定当前协议/模型/端点）或Models API返回的模型最大值；缺失时报错，不另造固定值。仍有B12–B14输入/卡片约束及B21协议响应体限制 | [backend/app/branch_comparisons.py:125](/home/kingdom/ai_learning/backend/app/branch_comparisons.py:125); [backend/app/providers.py:307](/home/kingdom/ai_learning/backend/app/providers.py:307); [backend/app/native_providers.py:540](/home/kingdom/ai_learning/backend/app/native_providers.py:540) |
| A01 人格生成/预览 | 8192，已知模型上限更低时取较低值 | [backend/app/personas.py:244](/home/kingdom/ai_learning/backend/app/personas.py:244) |
| A02 后台教练复盘 | 8192，已知模型上限更低时取较低值 | [backend/app/background_coach.py:19](/home/kingdom/ai_learning/backend/app/background_coach.py:19), `:216` |
| A03 学习初始化安排 | 8192 | [backend/app/learning_setup.py:19](/home/kingdom/ai_learning/backend/app/learning_setup.py:19), `:125` |
| A04 验证出题与评估 | 每次8192 | [backend/app/verification.py:187](/home/kingdom/ai_learning/backend/app/verification.py:187), `:535` |
| A05 补练生成/提示/反馈等 | 共用请求每次8192 | [backend/app/practice.py:197](/home/kingdom/ai_learning/backend/app/practice.py:197) |
| A06 外部完成材料审查 | 8192 | [backend/app/completion.py:203](/home/kingdom/ai_learning/backend/app/completion.py:203) |
| A07 图片/PDF OCR | 每页8192 | [backend/app/material_ocr.py:173](/home/kingdom/ai_learning/backend/app/material_ocr.py:173) |
| A08 学习位置整理 | 4096 | [backend/app/learning_position.py:103](/home/kingdom/ai_learning/backend/app/learning_position.py:103) |
| A09 成果关系建议 | 最多32768，已知模型上限更低时取较低值 | [backend/app/outcome_graph.py:25](/home/kingdom/ai_learning/backend/app/outcome_graph.py:25), `:226` |
| A10 近期学习安排 | min(32768,4096+2048×校准允许的次数)，再与已知较低模型上限取min | [backend/app/commitments.py:235](/home/kingdom/ai_learning/backend/app/commitments.py:235) |
| A11 作品语义证据分析 | 800 | [backend/app/evidence.py:152](/home/kingdom/ai_learning/backend/app/evidence.py:152) |
| A12 自动会话标题 | 512 | [backend/app/ai_runtime.py:30](/home/kingdom/ai_learning/backend/app/ai_runtime.py:30), `:418` |
| A13 Claude普通流式对话 | 适配器默认4096；显式thinking预算会加到max_tokens，自适应thinking与正文仍共用输出总额度 | [backend/app/native_providers.py:452](/home/kingdom/ai_learning/backend/app/native_providers.py:452), `:474`; [backend/app/reasoning_wire.py:103](/home/kingdom/ai_learning/backend/app/reasoning_wire.py:103) |
| A14 非流式通用适配器默认值 | 未显式传参时默认48；业务调用一般显式传入上表数值。本轮分支明确None，不触发默认值 | [backend/app/providers.py:311](/home/kingdom/ai_learning/backend/app/providers.py:311); [backend/app/native_providers.py:307](/home/kingdom/ai_learning/backend/app/native_providers.py:307), `:425`, `:565` |
| A15 提供方连接测试 | Chat兼容1；Responses/Google/Claude 32；仅ping，不是正常回答 | [backend/app/providers.py:507](/home/kingdom/ai_learning/backend/app/providers.py:507); [backend/app/native_providers.py:196](/home/kingdom/ai_learning/backend/app/native_providers.py:196) |
| A16 思考预算设置 | Claude explicit最小1024、无代码固定最大；Gemini已登记规格最大32768或24576；Qwen最小1且无固定最大。这是思考配置/型号规格校验，不能与回答字数混为一谈 | [backend/app/reasoning_control.py:49](/home/kingdom/ai_learning/backend/app/reasoning_control.py:49), `:57`, `:59`, `:61`, `:70`, `:332` |
| A17 题目讨论历史检索决策 | 单次2048；决定是否检索历史及关键词，并非讨论正文 | [backend/app/question_discussion.py:617](/home/kingdom/ai_learning/backend/app/question_discussion.py:617) |

除A00外均保留。不同协议对thinking token的计算不同：Claude显式thinking会在调用者正文额度上加预算；不能把8192等数字一律解释成8192个汉字或所有厂商完全相同的计费额度。其他协议普通流式对话未发现统一应用max_tokens，但有下表字符/协议边界。

Claude的max_tokens为必填：[Messages API](https://platform.claude.com/docs/en/api/messages/create)；模型最大值字段见[Models API](https://platform.claude.com/docs/en/api/python/models/retrieve)。省略可选参数也不代表取消服务商默认值或模型自身能力限制；本轮未改服务商规则。

## 0. 与已取消资料限制的关系

确认记录：[docs/progress/nautilus-product-design-decisions.md:1913](/home/kingdom/ai_learning/docs/progress/nautilus-product-design-decisions.md:1913)、`:1915` 明确取消上传文件 bytes、DOCX XML bytes、对话资料正文/提取正文长度、单轮参考总长、保存与选择份数；`:34` 对 Obsidian 也明确不重加正文/资料数/文件大小限额、不静默截断。

当前原始资料路径确实没有应用自定义总长/数量/页数上限：`routers/materials.py:121`–`:128` 全量收取请求流；`MaterialCreate.content` 无 max_length（`:22`）；`material_files.py:150`–`:153` 遍历所有 PDF 页、`:184`–`:203` 全量 DOCX 文本；`routers/material_ocr.py:22`、`:27` 的人工 OCR 页文字/页列表无上限；`material_images.py:57`–`:77` 遍历所选图片及全部指定页；`obsidian.py:247`–`:258` 的 1 MiB 是读取 chunk、不是文件总限额；已配对原生同步 [native/sync/src/lib.rs:223](/home/kingdom/ai_learning/native/sync/src/lib.rs:223)–`:231` 使用 `usize::MAX`。

但以下相邻链路仍有大小/数量限制，用户可能希望一起核对：外部完成材料 30,000 字；正式作答/作品 1,000,000 字；分支比较输入 192 KiB；从网页保存的资料只有已取得的 12,000 字截断正文；本地知识库每轮 4 调用与 80 行；工具结果 2,000,000 bytes/轮次 continuation 4,000,000 bytes。它们不等于重新给“原始上传/保存资料”设置全局上限，却会让大资料的后续使用在某些旅程受限。

## 1. 会影响输入、输出或模型实际上下文的硬限制/截断

| 项目 | 值、单位与实际行为 | 代码位置 |
|---|---|---|
| B01 普通学习室/教练单次用户消息 | 1–8,000 字；后端 schema 拒绝超长，Web 输入限制相同 | [backend/app/schemas.py:329](/home/kingdom/ai_learning/backend/app/schemas.py:329); [frontend/src/AiLearningRoom.tsx](/home/kingdom/ai_learning/frontend/src/AiLearningRoom.tsx) 通过 `LearningComposer` 默认值；[frontend/src/CoachConversation.tsx:13](/home/kingdom/ai_learning/frontend/src/CoachConversation.tsx:13); `AiCompanionPanel.tsx:15`; `LearningRoomLayout.tsx:141` |
| B02 题目讨论用户消息/编辑 | 1–12,000 字；后端拒绝，前端禁入更多 | [backend/app/schemas.py:678](/home/kingdom/ai_learning/backend/app/schemas.py:678); [frontend/src/QuestionDiscussion.tsx:254](/home/kingdom/ai_learning/frontend/src/QuestionDiscussion.tsx:254), `:288` |
| B03 普通学习室流式回复总量 | 正文与思考共 1,000,000 字；最后 chunk 截取剩余长度后抛 `output_limit`，已收到内容留存 | [backend/app/ai_runtime.py:27](/home/kingdom/ai_learning/backend/app/ai_runtime.py:27), `:275`–`:294` |
| B04 题目讨论回复 | 正文 >32,000 字或思考 >128,000 字即抛错、运行失败；以前持久化的部分留存；不是模型 token 限制 | [backend/app/question_discussion.py:748](/home/kingdom/ai_learning/backend/app/question_discussion.py:748) |
| B05 回复过程片段 | 1,024 个正文/思考/工具过程片段；超过抛 `output_limit`，会使生成失败，并非仅丢日志 | [backend/app/generation_trace.py:41](/home/kingdom/ai_learning/backend/app/generation_trace.py:41)–`:47` |
| B06 普通对话历史 | 模型只收到当前允许路径最后 20 条非空 complete 消息（通常约10组问答）；旧消息仍保存在库中 | [backend/app/conversations.py:20](/home/kingdom/ai_learning/backend/app/conversations.py:20), `:1967`–`:1972` |
| B07 题目讨论历史 | 模型只收到当前历史最后 8 turns（16条问答）；旧记录留存 | [backend/app/question_discussion.py:635](/home/kingdom/ai_learning/backend/app/question_discussion.py:635)–`:652` |
| B08 题目讨论检索历史 | 检索词最多80字；直接 `search()` 还静默截为80；普通对话最多4命中、其他讨论2命中，共最多6；每条摘录1,600字 | [backend/app/question_discussion.py:122](/home/kingdom/ai_learning/backend/app/question_discussion.py:122)–`:156`, `:619` |
| B09 普通计划/全局上下文 | 计划最多40项活跃任务；全局最多12个计划/20任务；包含 total/included/truncated 元数据；不删除任务 | [backend/app/conversations.py:26](/home/kingdom/ai_learning/backend/app/conversations.py:26)–`:28`, `:1161`, `:1230`–`:1231` |
| B10 自动标题输入 | 最后4条可用消息，每条前500字，总前2,000字；自动/备用标题最多32字 | [backend/app/conversations.py:22](/home/kingdom/ai_learning/backend/app/conversations.py:22)–`:25`, `:70`, `:82`, `:2277`–`:2291`; [frontend/src/AiLearningRoom.tsx:204](/home/kingdom/ai_learning/frontend/src/AiLearningRoom.tsx:204) |
| B11 学习位置自动整理输入 | 最近12条路径消息、每条前2,000字；生成 current/next 各500字，后端校验拒绝超长 | [backend/app/learning_position.py:19](/home/kingdom/ai_learning/backend/app/learning_position.py:19)–`:20`, `:88`–`:104` |
| B12 分支比较总输入 | 比较两路径的 JSON UTF-8 <=192 KiB；超长 HTTP422，不截原文 | [backend/app/branch_comparisons.py:115](/home/kingdom/ai_learning/backend/app/branch_comparisons.py:115)–`:114` |
| B13 分支比较卡片结构 | <=24卡；topic1–120字；conclusion1–4,000字；每卡1–8引用、每引用1–1,200字；超限整个输出无效 | [backend/app/branch_comparisons.py:82](/home/kingdom/ai_learning/backend/app/branch_comparisons.py:82)–`:92` |
| B14 分支比较采用 | 合并 title1–60字、selected1–24卡、每结论1–4,000字；超限422/前端限输入 | [backend/app/routers/branch_comparisons.py:25](/home/kingdom/ai_learning/backend/app/routers/branch_comparisons.py:25), `:30`–`:31`; `branch_comparisons.py:169`–`:166`; [frontend/src/BranchComparison.tsx:61](/home/kingdom/ai_learning/frontend/src/BranchComparison.tsx:61), `:64` |
| B15 工具调用数 | 每个模型 turn <=8 calls，声明 <=8 tools；超限 `protocol_error/config_error`；不等于每轮总搜索次数 | [backend/app/function_tools.py:20](/home/kingdom/ai_learning/backend/app/function_tools.py:20), `:67`, `:170` |
| B16 工具参数与名字 | JSON arguments <=20,000 UTF-8 bytes；工具 name <=128字；超限协议失败（纯 call ID 限制略） | [backend/app/function_tools.py:21](/home/kingdom/ai_learning/backend/app/function_tools.py:21)–`:22`, `:47`, `:61`, `:323` |
| B17 工具结果 | 单个 tool result <=2,000,000 UTF-8 bytes；超限 `protocol_error` | [backend/app/function_tools.py:23](/home/kingdom/ai_learning/backend/app/function_tools.py:23), `:209` |
| B18 工具 continuation | Provider轮次响应/生成记录序列化 <=4,000,000 UTF-8 bytes（某些流式分支逐步计数）；超限协议失败；不是原始图片输入总限额 | [backend/app/function_tools.py:24](/home/kingdom/ai_learning/backend/app/function_tools.py:24), `:153`–`:158`, `:187`, `:302`, `:455`, `:521` |
| B19 私有协议历史重放 | 从最近向前择取完整 `_model_turn`，合计<=256 KiB；超出跳过其协议块，用普通公开回复历史；保存的原块保留 | [backend/app/function_tools.py:25](/home/kingdom/ai_learning/backend/app/function_tools.py:25), `:91`–`:117` |
| B20 Responses/Google/Anthropic 流协议 | 单 SSE event <=512 KiB、事件数<=10,000；超限协议错误。这里 NativeProvider 是服务端协议适配器，非 Rust原生客户端 | [backend/app/native_providers.py:24](/home/kingdom/ai_learning/backend/app/native_providers.py:24)–`:25`, `:130`–`:148` |
| B21 服务端原生协议非流响应 | <=2 MiB，超过拒绝 `protocol_error`，也用于模型列表 | [backend/app/native_providers.py:26](/home/kingdom/ai_learning/backend/app/native_providers.py:26), `:200`–`:208` |
| B22 教学/教练 JSON元数据 | metadata/framing <=16,384 Unicode字；超大会标记envelope_oversized/不应用教学推进或动作，JSON decoder此后停止解码，若reply在超大metadata后也不会再展示；此前已解码正文保留。公开reply本身无此decoder长度限制（仍受外层回复限制） | [backend/app/teaching_runtime.py:26](/home/kingdom/ai_learning/backend/app/teaching_runtime.py:26), `:376`, `:399`, `:478`; `teaching_json.py:112`–`:145`, `:158`–`:167`; `coach_conversation.py:211`–`:212` 使用同一 decoder |
| B23 教学事件字段 | step引用<=240字；attempt/practice question/feedback/project goal/instruction/feedback引用<=4,000字；mode/help/change/persistence/adaptation来源引用<=1,200字；适应理由<=240字；超限教学 proposal无效 | [backend/app/teaching_runtime.py:608](/home/kingdom/ai_learning/backend/app/teaching_runtime.py:608), `:636`, `:694`, `:714`, `:777`–`:806`, `:838`, `:866`–`:868`, `:902`–`:943` |
| B24 教学学习观察产出 | <=4条 observations、<=12 used 引用；topic<=120字，原作答quote/feedback各<=1,200字；超限 proposal无效 | [backend/app/learning_observations.py:45](/home/kingdom/ai_learning/backend/app/learning_observations.py:45), `:61`–`:67` |
| B25 教学传给模型的观察上下文 | 最近12个点，每点最近3条观察，每观察最近3帮助记录；教学选择上下文只保留最后20条；正式历史未删除 | [backend/app/learning_observations.py:93](/home/kingdom/ai_learning/backend/app/learning_observations.py:93)–`:97`; `teaching_runtime.py:232` |
| B26 后台教练输入 | <=24 source refs/32 KiB JSON UTF-8；选最多4计划/32任务/64委托；先删非选定源的附加任务，再从ref末尾缩批；仍超限拒绝 | [backend/app/coach_sources.py:11](/home/kingdom/ai_learning/backend/app/coach_sources.py:11)–`:15`, `:161`–`:170`, `:232`–`:236`, `:299`–`:303`; `background_coach.py:210`–`:212`; `core/background_coach.py:120` |
| B27 后台教练路径/安排上下文 | 每路径最多12节点，每节点action/outcome各12，路径edges24；每计划arrangements8；topology_limited标记节点/边遗漏 | [backend/app/coach_sources.py:200](/home/kingdom/ai_learning/backend/app/coach_sources.py:200)–`:207` |
| B28 后台教练信号候选扫描 | 按源类型在48/72/96/120/144 refs时停止该扫描，最后仍只选24且最多4计划；更多源未删除 | [backend/app/coach_sources.py:265](/home/kingdom/ai_learning/backend/app/coach_sources.py:265), `:276`, `:279`, `:282`, `:285`, `:300`–`:303` |
| B29 后台教练生成候选 | <=8候选；title<=160字、explanation<=1,200字、unknowns<=8、source_refs1–64；超限模型输出无效 | [backend/app/background_coach.py:25](/home/kingdom/ai_learning/backend/app/background_coach.py:25)–`:34`; `core/coach_commands.py:52` |
| B30 获“full_text”许可的教练读作品 | 实际最多3份、每份先4,000字、合计12,000 UTF-8 bytes；截断设partial/limited；会读取范围内作品的开头，未发送完整大作品 | [backend/app/coach_permissions.py:60](/home/kingdom/ai_learning/backend/app/coach_permissions.py:60)–`:74` |
| B31 持续教练当前摘要 | 初选最多32计划/64任务/24安排/1运行session，每task只取1个可起学委托；JSON<=30 KiB（32KiB预留2KiB）；超过逐项缩减，无法继续缩减时失败 | [backend/app/coach_conversation.py:94](/home/kingdom/ai_learning/backend/app/coach_conversation.py:94)–`:149` |
| B32 持续教练动作输出 | 最多3动作；AI返回>3则整组置空；plain取前3。unknown字符串<=500字，否则整组置空；最后unknowns最多5条 | [backend/app/coach_conversation.py:171](/home/kingdom/ai_learning/backend/app/coach_conversation.py:171)–`:178` |
| B33 AI安排输入范围 | 当前计划任务>100则 `commitment_input_scope_too_large` HTTP422 | [backend/app/core/commitments.py:201](/home/kingdom/ai_learning/backend/app/core/commitments.py:201) |
| B34 AI安排长度/日期 | 依据校准通常最多3/5/7次，dated最多min(7或14天,未来slot数,slot容量,预算容量)；AI source超 `max_sessions` 拒绝；日期必须落在有效horizon/时段/每次上限/周预算，无重叠 | [backend/app/commitment_calibration.py:215](/home/kingdom/ai_learning/backend/app/commitment_calibration.py:215)–`:236`, `:263`–`:267`; `core/commitments.py:143`–`:176` |
| B35 路线图结构 | <=60节点、<=100边，每节点<=30 action_ids及<=30 outcome_ids；各title<=200字、reason<=2,000字；后端拒绝，Web按钮/勾选同步限制 | [backend/app/core/path_commands.py:13](/home/kingdom/ai_learning/backend/app/core/path_commands.py:13)–`:31`; [frontend/src/LearningPaths.tsx:183](/home/kingdom/ai_learning/frontend/src/LearningPaths.tsx:183), `:299`–`:305` |
| B36 成果关系建议 | 一批2–30 outcomes、返回候选<=60；每关系source_refs<=30；context<=200字、rationale<=2,000、uncertainty<=1,000；后端拒绝，Web最多选30 | [backend/app/core/graph_commands.py:29](/home/kingdom/ai_learning/backend/app/core/graph_commands.py:29)–`:32`, `:58`, `:68`; `outcome_graph.py:22`; [frontend/src/OutcomeSuggestions.tsx:48](/home/kingdom/ai_learning/frontend/src/OutcomeSuggestions.tsx:48), `:82`–`:83` |
| B37 组织排序 | 一次 children <=10,000；后端拒绝 | [backend/app/routers/plan_organization.py:53](/home/kingdom/ai_learning/backend/app/routers/plan_organization.py:53); `core/organization_commands.py:55` |
| B38 证据批量复核 | 一次claim_ids1–100，超限API拒绝 | [backend/app/schemas.py:619](/home/kingdom/ai_learning/backend/app/schemas.py:619) |
| B39 验证题目生成 | questions必须1–3题，超限输出无效；每题来源URL只保存前5 | [backend/app/verification.py:195](/home/kingdom/ai_learning/backend/app/verification.py:195), `:223` |
| B40 验证评估文本 | 总feedback静默截为4,000字、next_step1,000字；每题feedback/reference_answer各<=6,000字；follow_up_questions/unmet_requirements各<=5项且每项<=1,000字，超限评估失败 | [backend/app/verification.py:542](/home/kingdom/ai_learning/backend/app/verification.py:542), `:557`, `:562` |
| B41 外部完成/完成记录材料 | 文本1–30,000字；frontend本地文本文件>30,000字直接拒绝。材料label<=200字；method<=300/result<=2,000；说明/回应<=4,000 | [backend/app/completion.py:21](/home/kingdom/ai_learning/backend/app/completion.py:21)–`:36`, `:59`; [frontend/src/LearningCompletion.tsx:54](/home/kingdom/ai_learning/frontend/src/LearningCompletion.tsx:54)–`:55`, `:137`–`:149` |
| B42 外部完成材料AI审查产出 | summary/limitations<=3,000字，next_step<=2,000字，findings1–20条、quote<=2,000/comment<=3,000字；超限输出无效 | [backend/app/completion.py:65](/home/kingdom/ai_learning/backend/app/completion.py:65)–`:74` |
| B43 补练用户输入 | backend answer<=16,000字，Web更低<=12,000；objection<=4,000；超限拒绝/禁入 | [backend/app/practice.py:27](/home/kingdom/ai_learning/backend/app/practice.py:27), `:38`; [frontend/src/Practice.tsx:95](/home/kingdom/ai_learning/frontend/src/Practice.tsx:95), `:167` |
| B44 补练AI产出 | source/exercise reason/summary<=3,000字、basis1–8且每quote<=3,000；question/guidance<=8,000；hint<=4,000；feedback<=4,000、answer_quote<=3,000、remaining<=12、next_step<=2,000 | [backend/app/practice.py:51](/home/kingdom/ai_learning/backend/app/practice.py:51)–`:83` |
| B45 人格配置/预览 | name<=60字、description<=6,000；identity<=320、称呼<=40、自称<=60；trait<=4且每条<=160；场景<=6且每条<=240；sample<=500；issues<=8、每message<=400、1–2引用每quote<=400；超限拒绝、某些invalid issue项直接忽略 | [backend/app/personas.py:25](/home/kingdom/ai_learning/backend/app/personas.py:25)–`:41`, `:51`–`:74`, `:220`, `:254`; [frontend/src/PersonaSettings.tsx:74](/home/kingdom/ai_learning/frontend/src/PersonaSettings.tsx:74)–`:75` |
| B46 人格请求/导入body | <=64 KiB，超限HTTP413 | [backend/app/routers/personas.py:31](/home/kingdom/ai_learning/backend/app/routers/personas.py:31)–`:36` |
| B47 学习偏好body / 联网选择JSON | 请求<=32 KiB，外部selection JSON<=20,000字符；超限拒绝 | [backend/app/routers/preferences.py:27](/home/kingdom/ai_learning/backend/app/routers/preferences.py:27); `preferences.py:72`; `search_service.py:200` |
| B48 新旧功能文字/分钟输入 | 多种title/description/boundary/reason/note仍有限值；全部逐字段见后附表（是拒绝输入或结构化AI输出，并非仅提示词） | 见附录 |

## 2. 搜索/知识库：请求数量、截断、脚本资源边界

| 项目 | 值、单位与行为 | 代码位置 |
|---|---|---|
| C01 外部服务配置个数 | <=50实例，超限配置拒绝 | [backend/app/search_service.py:154](/home/kingdom/ai_learning/backend/app/search_service.py:154)–`:155` |
| C02 外部搜索结果数/次数/超时 | 可调 result_size1–50，timeout5–120秒，max_requests1–5。backend空配置默认10/30秒/3次；Web未加载占位default为1次；下层adapter接受>0–120秒，Custom JS accepts0.1–120秒 | [backend/app/search_service.py:78](/home/kingdom/ai_learning/backend/app/search_service.py:78)–`:80`, `:167`–`:169`; `search_adapters.py:41`, `:51`; `search_scripts.py:114`–`:116`; [frontend/src/SearchSettings.tsx:7](/home/kingdom/ai_learning/frontend/src/SearchSettings.tsx:7)–`:8` |
| C03 外部工具执行轮数 | 每run执行<=配置 max_requests次search/scrape；知识库另有4次；总round最多合计budget+1，最终禁工具。无效/重复请求也消费总attempt budget，用完回填error或失败 | [backend/app/search_runtime.py:136](/home/kingdom/ai_learning/backend/app/search_runtime.py:136)–`:138`, `:173`, `:215`–`:218`, `:240`–`:261` |
| C04 实际外部服务 HTTP返回 | 单响应<=2 MiB；超限SearchError；配置超时作用于请求，DNS核查3秒 | [backend/app/search_adapters.py:22](/home/kingdom/ai_learning/backend/app/search_adapters.py:22), `:92`, `:130`, `:193` |
| C05 Bing redirects | 最多follow3次（4轮请求）；更多拒绝，普通其他JSON服务不follow_redirects | [backend/app/search_adapters.py:115](/home/kingdom/ai_learning/backend/app/search_adapters.py:115), `:159`–`:177` |
| C06 搜索词/参数 | query/任意string parameter<=2,000字；array<=50项（每字符串仍2,000字）；selection JSON<=20,000字符；URL<=2,048字；Bing语言<=35字 | [backend/app/search_service.py:196](/home/kingdom/ai_learning/backend/app/search_service.py:196)–`:201`, `:227`–`:237`, `:274`; `search_adapters.py:57`, `:355` |
| C07 搜索配置body/字段 | body<=512 KiB；名称<=80字，text/options<=2,000、textarea<=65,536字、credentials<=16,000；number未指定max时上限1,000,000 | [backend/app/routers/search.py:20](/home/kingdom/ai_learning/backend/app/routers/search.py:20); `search_service.py:106`, `:123`, `:130`, `:141` |
| C08 API返回结果选择 | `_items`只保留有效条目前result_size，<=50；传给各上游的size可能还更低 | [backend/app/search_adapters.py:253](/home/kingdom/ai_learning/backend/app/search_adapters.py:253)–`:256` |
| C09 模型看到工具数据 | <=20项，每项text/content<=12,000字、正文合计<=60,000字（answer另<=12,000）；每title<=300、date<=100，highlights<=5且每<=2,000；images<=20；这些静默截断 | [backend/app/search_runtime.py:77](/home/kingdom/ai_learning/backend/app/search_runtime.py:77)–`:100` |
| C10 保存的外部搜索证据/可另存资料 | trace.answer前12,000字；每item.text前12,000、content_truncated标记；最多50 URL条目；images前20；网页保存素材使用这份已截断的trace | [backend/app/search_runtime.py:53](/home/kingdom/ai_learning/backend/app/search_runtime.py:53)–`:74`; `materials.py:208`–`:231` |
| C11 服务端模型内置搜索来源 | NativeProvider先最多100 sources；落入search trace最多50；title前300/url前4,096；suggestionsHTML>65,536 UTF-8 bytes整项不收；不是正文模型输入裁剪 | [backend/app/native_providers.py:27](/home/kingdom/ai_learning/backend/app/native_providers.py:27), `:59`, `:303`, `:421`, `:536`; `search_runtime.py:29`–`:40` |
| C12 豆包全网搜索 | 上游DocCount<=20，MaxSnippetLength300、MaxImageCountPerDoc1；定制count<=50 | [backend/app/search_adapters.py:424](/home/kingdom/ai_learning/backend/app/search_adapters.py:424) |
| C13 Exa内容请求 | 搜索带日期/域名/缓存条件时text.maxCharacters8,000/highlights1,200；read content固定maxCharacters8,000 | [backend/app/search_adapters.py:452](/home/kingdom/ai_learning/backend/app/search_adapters.py:452), `:644` |
| C14 Ollama云搜索 | 上游max_results clamp至5–10，最终又按result_size保留 | [backend/app/search_adapters.py:466](/home/kingdom/ai_learning/backend/app/search_adapters.py:466), `:256` |
| C15 Perplexity检索 token设置 | 用户可选max_tokens/max_tokens_per_page，>0，保存时默认max<=1,000,000；不是Provider回答max_tokens | [backend/app/search_catalog.py:45](/home/kingdom/ai_learning/backend/app/search_catalog.py:45); `search_service.py:123`; `search_adapters.py:470`–`:473` |
| C16 页面缓存年龄 | Exa可选maxAgeHours -1–720小时，超限拒绝；Firecrawl读取固定maxAge172,800,000毫秒=48小时 | [backend/app/search_catalog.py:24](/home/kingdom/ai_learning/backend/app/search_catalog.py:24); `search_adapters.py:529`, `:655` |
| C17 网页读取数量 | 内置adapter scrape一次只传1 URL（目录注释如此）；Custom JS1–20URLs；SearchService.test先静默取前5 URLs，其内置适配器仍只读url首项 | [backend/app/search_catalog.py:61](/home/kingdom/ai_learning/backend/app/search_catalog.py:61)–`:65`; `search_scripts.py:125`; `search_service.py:271`; `search_adapters.py:635` |
| C18 本地知识库调用 | 每run4次，由外部工具循环实际执行；非用户可配置 | [backend/app/knowledge.py:22](/home/kingdom/ai_learning/backend/app/knowledge.py:22); `search_runtime.py:137`, `:240`–`:242` |
| C19 本地知识库搜索页 | 每call最多5条匹配，has_more/next_after可继续；每结果命中位置周围最多7行（1based hit-2到hit+4，经边界clamp）；保存全文快照但只发送该行摘录 | [backend/app/knowledge.py:17](/home/kingdom/ai_learning/backend/app/knowledge.py:17), `:153`–`:158`, `:166`–`:176` |
| C20 本地知识库read | 一次1–80行，超范围请求拒绝；末页clip至文件末行；query<=500字，path/cursor<=4,096 | [backend/app/knowledge.py:18](/home/kingdom/ai_learning/backend/app/knowledge.py:18), `:127`, `:184`–`:195`; `obsidian.py:72` |
| C21 Obsidian选择搜索（人的界面） | query<=500、cursor<=4,096字；路径root<=4,096；每页50、可继续翻页；展示标题前300/单行摘要前200字，抓取全文无总bytes/字数上限 | [backend/app/obsidian.py:26](/home/kingdom/ai_learning/backend/app/obsidian.py:26)–`:31`, `:46`, `:68`, `:288`–`:291`, `:426`–`:428`, `:469`–`:473`; `routers/obsidian.py:19` |
| C22 Custom JS源代码 | UTF-8<=128 KiB；另有search settings textarea65,536字上限（双层）；超限拒绝 | [backend/app/search_scripts.py:20](/home/kingdom/ai_learning/backend/app/search_scripts.py:20), `:121`; `search_service.py:130` |
| C23 Custom JS输入/输出IPC | payload<=300,000 bytes；父stdout每line<=1,600,000，结果line<=1,000,000；worker原JSON返回<=900,000、最终输出<=1,000,000 bytes；超限脚本失败 | [backend/app/search_scripts.py:134](/home/kingdom/ai_learning/backend/app/search_scripts.py:134)–`:150`, `:168`; `search_script_worker.py:150`, `:157`–`:158`, `:176` |
| C24 Custom JS执行资源 | QuickJS memory64 MiB/stack256 KiB、pending job<=100,000；CPU软ceil(timeout)秒至少1/硬ceil(timeout)+1秒至少2；父stdout等待timeout+1、结束wait1秒 | [backend/app/search_script_worker.py:103](/home/kingdom/ai_learning/backend/app/search_script_worker.py:103)–`:107`, `:145`; `search_scripts.py:146`, `:167` |
| C25 Custom JS网络调用 | 每script共用common.max_requests次数（正常UI1–5，底层允许0–20）；每fetch<=min(10秒,script timeout)；headers<=32，key<=100/value<=4,096字，URL<=2,048字，request body/response各<=1MiB；超限失败 | [backend/app/search_scripts.py:116](/home/kingdom/ai_learning/backend/app/search_scripts.py:116); `search_script_worker.py:23`, `:39`–`:50`, `:89`, `:108`–`:117` |
| C26 Custom JS直接入口参数 | 下层query<=8,000字，但正常SearchService路径先<=2,000；scrape URLs1–20 | [backend/app/search_scripts.py:125](/home/kingdom/ai_learning/backend/app/search_scripts.py:125)–`:129`; `search_service.py:227` |
| C27 Custom JS normalized search | 原始items<=1,000（超限拒），只保留前result_size；answer/text每<=20,000字、title<=300、date<=100、highlights<=20且每<=1,000；images原数组<=100但只保留前20 | [backend/app/search_scripts.py:67](/home/kingdom/ai_learning/backend/app/search_scripts.py:67)–`:88` |
| C28 Custom JS normalized scrape | 返回urls<=50、每content<=100,000字、metadata各<=500字；超限拒；之后模型仍受上表工具裁剪 | [backend/app/search_scripts.py:92](/home/kingdom/ai_learning/backend/app/search_scripts.py:92)–`:106` |

Claude内置搜索另有每轮最多5次max_uses（[backend/app/native_providers.py:462](/home/kingdom/ai_learning/backend/app/native_providers.py:462)），不受外部服务max_requests设置替代；此项记为C29。

## 3. 可配置频率、并发、超时、重试与生命周期

| 项目 | 值/行为 | 代码位置 |
|---|---|---|
| D01 Provider超时设置 | 默认60秒，可调5–600秒；global/default和one-run可保存，one-run不能短于default；绝大多数生成总期限用配置；HTTP connect固定10秒 | [backend/app/schemas.py:192](/home/kingdom/ai_learning/backend/app/schemas.py:192), `:278`; `model_control.py:26`; [frontend/src/ModelControl.tsx:141](/home/kingdom/ai_learning/frontend/src/ModelControl.tsx:141), `:161`; `providers.py:230`; `native_providers.py:79`; `ai_runtime.py:220`; `question_discussion.py:610` |
| D02 Provider API密钥长度 | <=512字（保存/未保存测试模型配置均检查），超限拒绝、不回显凭据；不是UUID形状限制 | [backend/app/conversations.py:862](/home/kingdom/ai_learning/backend/app/conversations.py:862), `:1043`, `:1085` |
| D03 Provider自动重试 | 最多3尝试，延迟0.5/1秒；只ConnectError/ConnectTimeout且不TLS；read/write/HTTP返回不自动重放；不可在UI配置 | [backend/app/provider_network.py:19](/home/kingdom/ai_learning/backend/app/provider_network.py:19), `:155`–`:183` |
| D04 服务端Provider并发 | 主运行 semaphore4，persona/branch comparison/graph/commitments/background coach共用该slots；等待外发批准释放slot。这不是全服务所有Provider调用的全局4并发保证；OCR未共用该semaphore且每job逐页生成 | [backend/app/ai_runtime.py:28](/home/kingdom/ai_learning/backend/app/ai_runtime.py:28), `:89`; `main.py:163`, `:167`, `:178`, `:182`, `:184`;`outbound.py:55`; `material_ocr.py:164`–`:173` |
| D05 同范围活跃运行 | 普通会话/题目讨论已有run拒绝新run；后台教练同owner只能1queued/running；这些是实际并发门槛。未发现成果图服务同范围1-run限制 | [backend/app/conversations.py:1910](/home/kingdom/ai_learning/backend/app/conversations.py:1910)–`:1922`; `question_discussion.py:442`–`:443`; `core/background_coach.py:128`; `core/outcome_graph.py:181`–`:190` |
| D06 后台自动复盘频率 | 默认每session1、每天3、cooldown30分钟；可设置session1–20、daily1–100、cooldown30–10,080分钟；自动超限gated，manual跳过这些frequency门槛；仍受1active运行 | [backend/app/core/background_coach.py:23](/home/kingdom/ai_learning/backend/app/core/background_coach.py:23)–`:24`, `:137`–`:142`; `core/coach_commands.py:15`–`:17` |
| D07 督学提醒配置 | study_times<=14、每time weekdays1–7且去重；追加默认30分钟可1–1,440；daily默认2可1–100；quiet默认22:00–08:00可调；超daily/quiet/learning_active不派发 | [backend/app/coach_reminders.py:22](/home/kingdom/ai_learning/backend/app/coach_reminders.py:22), `:26`, `:40`–`:45`, `:265`; [frontend/src/CoachReminderSettings.tsx:67](/home/kingdom/ai_learning/frontend/src/CoachReminderSettings.tsx:67), `:71`–`:72` |
| D08 督学提醒派发合并 | 每次view最多1due，dispatch后其他已到期pending合并抑制；只生成昨天/今天/明天固定时点与<=now+1day的已安排时间；不是保留完整旧通知队列 | [backend/app/coach_reminders.py:185](/home/kingdom/ai_learning/backend/app/coach_reminders.py:185)–`:186`, `:246`, `:270`–`:271` |
| D09 督学核对频率 | Web每15秒刷新，后台boundary事件每1秒检查；不是生成输出大小限制 | [frontend/src/CoachReminderHost.tsx:60](/home/kingdom/ai_learning/frontend/src/CoachReminderHost.tsx:60); [backend/app/background_coach.py:330](/home/kingdom/ai_learning/backend/app/background_coach.py:330) |
| D10 OCR运行 | 同源已有running会返回已有job；每页最多配置Provider超时，顺序页处理；PDFium渲染Lock=1；无全job页数/正文/次数上限 | [backend/app/material_ocr.py:133](/home/kingdom/ai_learning/backend/app/material_ocr.py:133)–`:135`, `:164`–`:173`; `material_files.py:31`, `:98` |
| D11 外发授权有效期 | 一般许可default300秒、可60–3,600；教练生成full_text请求固定300秒且过期不读取 | [backend/app/schemas.py:536](/home/kingdom/ai_learning/backend/app/schemas.py:536); `coach_permissions.py:31`, `:52` |
| D12 延迟回访最小间隔 | 已批准regex题库实际min86,400秒=24小时，suggested259,200秒=3天仅建议；安排早于初次提交+min会422；初始/回访各8题，answers字典<=8 | [backend/app/standards/python_regex_match_followup_v1.approved.json:10](/home/kingdom/ai_learning/backend/app/standards/python_regex_match_followup_v1.approved.json:10)–`:11`; `delayed_follow_up.py:29`, `:363`–`:365` |
| D13 校准反馈时间参数 | 预计投入1–10,080分钟、实际投入0–10,080；周预算1–10,080、block1–1,440；可用slots<=60、preferred_days只7/14；后端拒绝且前端有对应range | [backend/app/core/commitment_commands.py:42](/home/kingdom/ai_learning/backend/app/core/commitment_commands.py:42)–`:43`, `:123`–`:126`, `:172`–`:173`; [frontend/src/LearningCommitments.tsx:132](/home/kingdom/ai_learning/frontend/src/LearningCommitments.tsx:132), `:159`; `SessionFeedback.tsx:43` |
| D14 旧任务/计时/改期参数 | 任务estimate1–1,440分钟、focus1–240、rest0–120；改期days -365–365；拒绝超范围、Web表单范围同步 | [backend/app/schemas.py:34](/home/kingdom/ai_learning/backend/app/schemas.py:34)–`:37`, `:97`–`:100`, `:142`, `:158`–`:159`; [frontend/src/PlanEditor.tsx:207](/home/kingdom/ai_learning/frontend/src/PlanEditor.tsx:207), `:220`–`:221`; `TaskListView.tsx:155` |
| D15 指标观察窗 | 恢复学习完成观察只计创建review后7天内完成，超过窗处理未完成；影响指标归因，不是保存内容上限 | [backend/app/measurements.py:13](/home/kingdom/ai_learning/backend/app/measurements.py:13), `:232`–`:239` |
| D16 普通流恢复 | 初始订阅失败后最多3次重连，等待0.5/1/2秒；重连现有run，不重新模型生成 | [frontend/src/AiLearningRoom.tsx:74](/home/kingdom/ai_learning/frontend/src/AiLearningRoom.tsx:74), `:617`–`:624` |
| D17 题目讨论流恢复 | 总共3次订阅尝试，失败间等待0.5/1/1.5秒；最终提示显式恢复 | [frontend/src/QuestionDiscussion.tsx:117](/home/kingdom/ai_learning/frontend/src/QuestionDiscussion.tsx:117)–`:140` |
| D18 标题轮询 | <=25次读取，间隔800ms，pending-awaitqueue仅前5attempt；到限只停止UI轮询，不停止后台生成 | [frontend/src/AiLearningRoom.tsx:487](/home/kingdom/ai_learning/frontend/src/AiLearningRoom.tsx:487)–`:498` |
| D19 其他过程刷新/轮询 | OCR1.5秒；成果建议0.5/0.75秒；后台教练初始0.7后1秒、错误2.5秒；安排初始0.8后1秒、错误2.5秒；诊断2秒；外发批准1秒 | [frontend/src/AttachmentReview.tsx:109](/home/kingdom/ai_learning/frontend/src/AttachmentReview.tsx:109)–`:111`; `OutcomeSuggestions.tsx:32`–`:36`; `BackgroundCoach.tsx:141`–`:144`; `LearningCommitments.tsx:45`–`:48`; `Diagnostics.tsx:201`; `OutboundApproval.tsx:41` |
| D20 本地DB busy wait | 通常5,000ms；purge副本1,000ms后失败；非内容长度上限 | [backend/app/db.py:93](/home/kingdom/ai_learning/backend/app/db.py:93); `managed_purge.py:56` |
| D21 启动脚本准备等待 | token最多50×0.1秒，front HTML最多50×0.1秒（HTTP请求耗时另算）；超时退出 | [scripts/start.sh:56](/home/kingdom/ai_learning/scripts/start.sh:56)–`:67`, `:71`–`:83` |
| D22 Cookie/会话 | cookie默认315,360,000秒=约10年，可env改；config.session_ttl默认28,800秒但数据库lookup按revoked_at，不实际8小时自动失效；timestamp至少10年仅schema兼容 | [backend/app/config.py:54](/home/kingdom/ai_learning/backend/app/config.py:54)–`:56`; `auth.py:13`, `:74`–`:77`; `routers/auth.py:35` |

## 4. 展示、分页、缓存限制（区别于数据/模型约束）

| 项目 | 值/行为 | 代码位置 |
|---|---|---|
| E01 人格预览缓存 | 每owner只留最近20份未确认内存preview；旧preview丢失后需重做，已保存版本不删除 | [backend/app/personas.py:263](/home/kingdom/ai_learning/backend/app/personas.py:263)–`:265` |
| E02 分支比较预览缓存 | 每owner最近20份未确认preview元数据；旧preview失效；实际资料/已合并记录保留 | [backend/app/branch_comparisons.py:158](/home/kingdom/ai_learning/backend/app/branch_comparisons.py:158)–`:153` |
| E03 活跃/完成AI内存缓存 | 目标64runs，超时只淘汰finished；活动未结束可暂超64；超出改DB重放，不删除正式数据 | [backend/app/ai_runtime.py:25](/home/kingdom/ai_learning/backend/app/ai_runtime.py:25), `:185`–`:191`, `:598`–`:604` |
| E04 SSE订阅队列 | 每subscriber最多256events；慢客户端溢出断流并提示重连，模型生成和持久化仍继续 | [backend/app/ai_runtime.py:29](/home/kingdom/ai_learning/backend/app/ai_runtime.py:29), `:606`, `:635`–`:643`; `ai_runtime.py:533`–`:537` |
| E05 SSE心跳 | 普通15秒等待无新event就keep-alive；题目讨论10秒，持久化snapshot每50ms读取；不会主动停止生成 | [backend/app/ai_runtime.py:26](/home/kingdom/ai_learning/backend/app/ai_runtime.py:26), `:629`–`:632`; `question_discussion.py:548`, `:554` |
| E06 Provider模型发现缓存 | TTL600秒，可force刷新；不删手动保存的模型 | [backend/app/model_discovery.py:12](/home/kingdom/ai_learning/backend/app/model_discovery.py:12), `:62`, `:71` |
| E07 模型发现结果 | OpenAI-compatible返回最多500有效model，名称>120字忽略；模型body只读前512KiB，可能随后JSON失败；NativeProvider只看values前500项、名称<=120 | [backend/app/providers.py:24](/home/kingdom/ai_learning/backend/app/providers.py:24)–`:25`, `:457`, `:477`–`:479`, `:490`–`:496`; `native_providers.py:187`–`:191` |
| E08 Provider错误正文 | Compatible错误body只取前64KiB，最终详情前300字；不是回复内容裁剪 | [backend/app/providers.py:22](/home/kingdom/ai_learning/backend/app/providers.py:22)–`:23`, `:167`, `:485`–`:497` |
| E09 诊断日志 | 单文件1MiB、3轮转备份（合计约4MiB）；API返回最新500entry；旧轮转删除；UI2秒刷新 | [backend/app/diagnostics.py:16](/home/kingdom/ai_learning/backend/app/diagnostics.py:16)–`:17`, `:73`, `:103`; [frontend/src/Diagnostics.tsx:201](/home/kingdom/ai_learning/frontend/src/Diagnostics.tsx:201) |
| E10 Obsidian人的检索 | 一页50（显式next_after），摘录200/标题300；候选selection token10分钟有效；过期必须重新检索；全文快照不丢 | [backend/app/obsidian.py:26](/home/kingdom/ai_learning/backend/app/obsidian.py:26)–`:31`, `:469`–`:473`, `:515`–`:531` |
| E11 后台复盘界面history | backend最多100runs和100已处理candidate记录；无history分页返回；默认前端只显示1pending，有“展开”可全部显示已返回候选 | [backend/app/background_coach.py:143](/home/kingdom/ai_learning/backend/app/background_coach.py:143), `:151`; [frontend/src/BackgroundCoach.tsx:197](/home/kingdom/ai_learning/frontend/src/BackgroundCoach.tsx:197)–`:198` |
| E12 督学历史 | backend最近10已派发；Web只显示其中前5，无更早列表入口 | [backend/app/coach_reminders.py:245](/home/kingdom/ai_learning/backend/app/coach_reminders.py:245); [frontend/src/CoachReminderSettings.tsx:48](/home/kingdom/ai_learning/frontend/src/CoachReminderSettings.tsx:48) |
| E13 持续教练动作默认展示 | 当前动作只显示3，明确“更多入口”展开；输出动作本身另有3的硬限制（见第1表） | [frontend/src/CoachConversation.tsx:34](/home/kingdom/ai_learning/frontend/src/CoachConversation.tsx:34)–`:35` |
| E14 返回学习摘要 | supported只前4、evidence_details只前12；正式证据未删，该返回payload不含其余项 | [backend/app/continuity.py:146](/home/kingdom/ai_learning/backend/app/continuity.py:146), `:152` |
| E15 计划概览近期任务 | 只前6priority任务，其他在schedule/structure；本周待完成指标也从这6条计算，属于受裁剪影响的数值 | [frontend/src/PlanOverview.tsx:20](/home/kingdom/ai_learning/frontend/src/PlanOverview.tsx:20)–`:27` |
| E16 日历格任务 | 每日只显示前3按钮，超出显示“+N项”，该+N是span非展开按钮；其余在任务/计划列表 | [frontend/src/CalendarView.tsx:54](/home/kingdom/ai_learning/frontend/src/CalendarView.tsx:54)–`:55` |
| E17 搜索正文默认折叠 | <500字全显，否则前460+展开全文；展开仍只能看到backend已保存12,000字内容。suggestionsHTML最多65,536个UTF-16单位 | [frontend/src/SearchResults.tsx:20](/home/kingdom/ai_learning/frontend/src/SearchResults.tsx:20)–`:26` |
| E18 回复过程默认折叠 | parts>2只显示最后2，有展开；summary最多3domain名；全部已返回parts可展开 | [frontend/src/AssistantResponse.tsx:61](/home/kingdom/ai_learning/frontend/src/AssistantResponse.tsx:61), `:102`–`:103` |
| E19 学习位置来源预览 | 前240字，但有完整消息details；教学practice/instruction短text字段前240字同时保留start/end用于解析全文 | [frontend/src/LearningPosition.tsx:33](/home/kingdom/ai_learning/frontend/src/LearningPosition.tsx:33)–`:34`; [backend/app/teaching_runtime.py:616](/home/kingdom/ai_learning/backend/app/teaching_runtime.py:616), `:701`, `:795` |
| E20 资料界面短预览 | 网页候选snippet前200字后ellipsis，但已保存版本/来源面板可查看剩余已取得正文；TaskMaterials title输入<=200而backend<=300（前端更低是输入限制） | [frontend/src/TaskMaterials.tsx:374](/home/kingdom/ai_learning/frontend/src/TaskMaterials.tsx:374), `:379`; [backend/app/routers/materials.py:21](/home/kingdom/ai_learning/backend/app/routers/materials.py:21) |
| E21 分支名称/来源摘录 | branch title和source_excerpt用60字_clip，原消息仍可打开；comparison.last_question前160字是显示元数据不进入compare body | [backend/app/branch_maps.py:8](/home/kingdom/ai_learning/backend/app/branch_maps.py:8)–`:9`, `:104`; `conversations.py:58`–`:60`; `branch_comparisons.py:64` |

## 5. 独立 Rust/原生客户端差异

这些是当前源码路径的事实；未核验已安装二进制或历史交付包是否与此源码一致。

| 项目 | 值/行为 | 代码位置 |
|---|---|---|
| F01 原生用户消息/回答/资料 | frontend/native字段无maxLength，store保存/追加答案无自定义字数/file/count cap；与Web的8k/12k/1m/32k边界不同 | [frontend/native/main.tsx:615](/home/kingdom/ai_learning/frontend/native/main.tsx:615)–`:647`; [native/core/src/store.rs:636](/home/kingdom/ai_learning/native/core/src/store.rs:636)–`:754`, `:763`–`:771` |
| F02 原生历史 | 把相同资料范围的complete祖先一直遍历到scope变化/非complete；没有last20/last8条数裁剪；原资料逐个全量拼入当前message | [native/core/src/store.rs:1558](/home/kingdom/ai_learning/native/core/src/store.rs:1558)–`:1579`, `:1809`–`:1829` |
| F03 原生Provider请求 | 仅OpenAI-compatible chat/completions；没有应用max_tokens、SSE bytes/event count/总文本cap、没有显式应用总request timeout或retry；返回tool_calls拒绝，数组只取first choice | [native/core/src/provider.rs:46](/home/kingdom/ai_learning/native/core/src/provider.rs:46)–`:53`, `:63`–`:123` |
| F04 原生生成并发 | 一个app state最多1生成（setup与回答共用cancel状态），本机pending turn也只能1；拒绝第二条 | [native/src-tauri/src/lib.rs:195](/home/kingdom/ai_learning/native/src-tauri/src/lib.rs:195)–`:203`, `:539`–`:541`; [native/core/src/store.rs:685](/home/kingdom/ai_learning/native/core/src/store.rs:685)–`:689` |
| F05 原生安排预算 | time_budget_minutes1–1,440或null，超过校验拒绝；文本仅非空无字符上限 | [native/core/src/types.rs:56](/home/kingdom/ai_learning/native/core/src/types.rs:56)–`:78`; [frontend/native/main.tsx:67](/home/kingdom/ai_learning/frontend/native/main.tsx:67) |
| F06 已配对同步 | 请求/应答read_to_end usize::MAX，素材/回答无人工总bytes/count cap；不是64KiB | [native/sync/src/lib.rs:223](/home/kingdom/ai_learning/native/sync/src/lib.rs:223)–`:231`, `:611` |
| F07 未配对同步/配对 | 未鉴权 envelope<=64KiB且读取10秒，配对码有效600秒；sync tick间隔3秒或wake；connect期限5秒 | [native/sync/src/lib.rs:25](/home/kingdom/ai_learning/native/sync/src/lib.rs:25), `:225`–`:231`, `:256`, `:593` |
| F08 Android系统兼容 | minSdk24；API37+局域网permission gating；不是内容/数量限额 | [native/src-tauri/tauri.conf.json:12](/home/kingdom/ai_learning/native/src-tauri/tauri.conf.json:12); [native/android/MainActivity.kt:16](/home/kingdom/ai_learning/native/android/MainActivity.kt:16)–`:17` |

## 6. 仅提示词建议 / 第三方固有未知

- Prompt的“只建议一个下一步”（`learning_position.py:93`）是文本语义要求，代码只验证current/next字符串<=500，不数正文中的行动。
- 标题“最多32字”既有prompt要求也有实际normalize裁剪（`conversations.py:82`），所以已列硬边界。
- 分支“最多24卡”既有prompt（`branch_comparisons.py:121`）也有actual validator（`:81`），是硬限制。
- 教练候选/安排/观察/知识库次数同样有代码执行，不能仅按prompt看待。
- 延迟回访suggested3天仅默认建议，actual最小24小时是数据包与服务的硬校验。
- Pillow保留库自身图片解码/DecompressionBomb保障（`material_files.py:118`–`:131`），应用未覆盖像素阈值。没有读取已安装Pillow配置，故不猜精确pixel数；第三方模型上下文/厂商输出上限、HTTP服务器/WebView/OS/SQLite的固有限制也没有当作Nautilus自设限额。它们的实时实际值此静态盘点未证明。
- 没有发现当前原资料上传/选用/OCR review/配对后同步再引入bytes/body/count总限额。上述assertion只针对已读的应用路径，静态搜索无法数学证明没有任何任意分支/第三方隐藏限制。

## 附录：普通表单/名称/说明字段按值分组

下表只补上主表以外或容易漏看的标题、名称、说明、备注等字段；这些大多是后端 `Field(max_length=...)` 拒绝输入/结构化输出，Web `maxLength` 也禁止继续输入。单位为Python字符，Web按UTF-16计算；模型输出Field超限时拒绝整份解析，非自动截断。分组行不表示全局所有字段使用同一个值。

| 上限 | 受影响字段与features | 精确源码证据 |
|---|---|---|
| G01 40字 | 人格称呼用户 | [backend/app/personas.py:28](/home/kingdom/ai_learning/backend/app/personas.py:28) |
| G02 60字 | 手工会话改名、分支改名/合并主题、人格名称及角色自称；生成会话标题另为32字 | [backend/app/schemas.py:304](/home/kingdom/ai_learning/backend/app/schemas.py:304); `personas.py:25`, `:40`; `routers/branch_comparisons.py:30`; [frontend/src/BranchMap.tsx:293](/home/kingdom/ai_learning/frontend/src/BranchMap.tsx:293); `AiLearningRoom.tsx:1210` |
| G03 80字 | 布局模板名称、Provider显示名称、搜索服务名称 | [backend/app/schemas.py:172](/home/kingdom/ai_learning/backend/app/schemas.py:172), `:185`, `:245`; `search_service.py:106`; [frontend/src/LayoutDialog.tsx:159](/home/kingdom/ai_learning/frontend/src/LayoutDialog.tsx:159); `SearchSettings.tsx:104` |
| G04 100字 | 后台教练/延迟回访timezone文字（仍需合法ZoneInfo）；非ID | [backend/app/core/coach_commands.py:14](/home/kingdom/ai_learning/backend/app/core/coach_commands.py:14); `delayed_follow_up.py:40` |
| G05 120字 | 旧计划goal/科目/主题名称、新会话创建传入title、学习观察topic、Provider配置/test模型名；旧任务查询query120字 | [backend/app/schemas.py:21](/home/kingdom/ai_learning/backend/app/schemas.py:21), `:25`, `:26`, `:47`, `:65`, `:187`, `:223`, `:247`, `:285`, `:357`; `routers/plans.py:73`; [frontend/src/PlanDialog.tsx:129](/home/kingdom/ai_learning/frontend/src/PlanDialog.tsx:129), `:151`, `:155`; `PlanEditor.tsx:65`, `:119`; `AiProviderDialog.tsx:268`, `:316` |
| G06 160字 | 后台复盘候选title；人格每条trait（trait数量4） | [backend/app/background_coach.py:25](/home/kingdom/ai_learning/backend/app/background_coach.py:25); `personas.py:51` |
| G07 200字 | 旧任务名称；新版goal/plan/module/path/node/迁入计划标题；context_key/成果适用情境；标准包title、reviewed_by及outcome.source；外部材料label；手动模型model_id/display_name（这个model_id是实际提供方模型名称，不是内部UUID） | [backend/app/schemas.py:27](/home/kingdom/ai_learning/backend/app/schemas.py:27), `:90`, `:118`, `:263`–`:264`, `:366`, `:387`, `:389`, `:392`, `:396`, `:425`; `core/organization_commands.py:12`, `:24`; `core/path_commands.py:13`, `:26`, `:137`; `standards.py:22`–`:23`, `:29`, `:31`, `:34`; `completion.py:28` |
| G08 Web更低的200字 | 资料title前端200、后端允许300；本地完成导入文件名静默截前200 | [frontend/src/TaskMaterials.tsx:374](/home/kingdom/ai_learning/frontend/src/TaskMaterials.tsx:374); `LearningCompletion.tsx:55`; [backend/app/routers/materials.py:21](/home/kingdom/ai_learning/backend/app/routers/materials.py:21) |
| G09 240字 | 人格每条场景规则；教学/adaptation理由；教学step引用 | [backend/app/personas.py:53](/home/kingdom/ai_learning/backend/app/personas.py:53); `teaching_runtime.py:838`, `:866`, `:930` |
| G10 300字 | 学习action/任务title；资料title与上传basename；完成验证method；Provider Base URL配置字段（URL使用场景，另有安全检查） | [backend/app/schemas.py:186](/home/kingdom/ai_learning/backend/app/schemas.py:186), `:206`, `:222`, `:246`, `:365`, `:391`; `core/organization_commands.py:60`; `routers/materials.py:21`; `material_files.py:42`, `:165`; `completion.py:21`; [frontend/src/FactWorkspace.tsx:1338](/home/kingdom/ai_learning/frontend/src/FactWorkspace.tsx:1338); `LearningPlanOrganization.tsx:340` |
| G11 320字 | 人格identity | [backend/app/personas.py:26](/home/kingdom/ai_learning/backend/app/personas.py:26) |
| G12 400字 | 人格预览issue.message/单quote（2quote上限），不合法issue项忽略；并非用户所有消息限制 | [backend/app/personas.py:69](/home/kingdom/ai_learning/backend/app/personas.py:69)–`:71` |
| G13 500字 | 成果对象/行为，学习位置current/next，AI证据观察scope，标准成果定义object/behavior，持续教练unknown项、标准包source | [backend/app/schemas.py:394](/home/kingdom/ai_learning/backend/app/schemas.py:394)–`:395`, `:423`–`:424`, `:495`–`:496`; `evidence.py:33`; `standards.py:20`–`:21`, `:32`; `coach_conversation.py:175`; [frontend/src/OutcomeGraphForms.tsx:65](/home/kingdom/ai_learning/frontend/src/OutcomeGraphForms.tsx:65)–`:66`; `LearningPosition.tsx:139`, `:142` |
| G14 600字 | 学习观察人工note | [backend/app/schemas.py:359](/home/kingdom/ai_learning/backend/app/schemas.py:359); `learning_observations.py:135`; [frontend/src/LearningObservations.tsx:87](/home/kingdom/ai_learning/frontend/src/LearningObservations.tsx:87) |
| G15 1,000字 | 旧计划/goal及新版goal/plan/module/迁入计划description；创建学习AI说明rationale；agent拒绝/撤销reason、证据review note/reason；关系uncertainty；standard包source500而standard成果source200（500字行另列） | [backend/app/schemas.py:22](/home/kingdom/ai_learning/backend/app/schemas.py:22), `:48`, `:388`, `:390`, `:549`, `:560`, `:577`, `:590`, `:602`, `:621`; `core/organization_commands.py:13`, `:25`; `core/path_commands.py:138`; `learning_setup.py:55`; `core/graph_commands.py:31`; [frontend/src/PlanEditor.tsx:66](/home/kingdom/ai_learning/frontend/src/PlanEditor.tsx:66); `LearningPlanOrganization.tsx:177`, `:253`; `LearningPaths.tsx:296` |
| G16 1,000字 | agent读取purpose（教练请求会先截至1000） | [backend/app/schemas.py:533](/home/kingdom/ai_learning/backend/app/schemas.py:533); `coach_permissions.py:30` |
| G17 1,200字 | 后台教练explanation；若干教学/分支原文quote（数量主表） | [backend/app/background_coach.py:26](/home/kingdom/ai_learning/backend/app/background_coach.py:26); `branch_comparisons.py:91`; `learning_observations.py:64`, `:67` |
| G18 2,000字 | 委托boundary/stop_condition；路线/安排reason、安排run explanation；学习反馈notes；关系rationale与URL source；external completion report.result；各下阶段模型结果next_step（主表详述） | [backend/app/schemas.py:398](/home/kingdom/ai_learning/backend/app/schemas.py:398)–`:399`, `:441`–`:442`; `core/path_commands.py:31`; `core/commitment_commands.py:46`, `:71`, `:153`, `:184`; `core/graph_commands.py:12`, `:30`; `completion.py:22`; [frontend/src/LearningPaths.tsx:305](/home/kingdom/ai_learning/frontend/src/LearningPaths.tsx:305); `SessionFeedback.tsx:46` |
| G19 3,000字 | completion AI审查summary/comment/limitations；补练SourceReview.summary/Exercise.reason/quotes等（主表） | [backend/app/completion.py:66](/home/kingdom/ai_learning/backend/app/completion.py:66), `:71`, `:73`; `practice.py:51`, `:56`, `:63` |
| G20 4,000字 | 开始学习intent/original_intent；AI证据observation.statement；completion说明/回应；补练objection；分支合并结论 | [backend/app/schemas.py:371](/home/kingdom/ai_learning/backend/app/schemas.py:371), `:386`; `core/commands.py:32`; `evidence.py:32`; `completion.py:36`, `:59`; `practice.py:27`; `routers/branch_comparisons.py:25`; [frontend/src/FactWorkspace.tsx:1098](/home/kingdom/ai_learning/frontend/src/FactWorkspace.tsx:1098) |
| G21 6,000字 | 人格description；验证每题解释/参考答案（主表） | [backend/app/personas.py:41](/home/kingdom/ai_learning/backend/app/personas.py:41); `verification.py:557`; [frontend/src/PersonaSettings.tsx:75](/home/kingdom/ai_learning/frontend/src/PersonaSettings.tsx:75) |
| G22 8,000/12,000/16,000字 | 普通聊天输入8k；题目讨论12k；补练Web12k/backend16k；详见主表 | [backend/app/schemas.py:329](/home/kingdom/ai_learning/backend/app/schemas.py:329), `:678`; `practice.py:38`; [frontend/src/LearningRoomLayout.tsx:141](/home/kingdom/ai_learning/frontend/src/LearningRoomLayout.tsx:141); `Practice.tsx:167` |
| G23 30,000字 | external completion材料文字，含前端本地文本文件入口；不是通用资料上传 | [backend/app/completion.py:29](/home/kingdom/ai_learning/backend/app/completion.py:29); [frontend/src/LearningCompletion.tsx:54](/home/kingdom/ai_learning/frontend/src/LearningCompletion.tsx:54), `:148` |
| G24 1,000,000字 | 正式artifact保存/更正、verification提交material和learner_work；后端拒绝超长，frontend对应长文本未另设较低maxLength | [backend/app/schemas.py:464](/home/kingdom/ai_learning/backend/app/schemas.py:464), `:502`–`:503`, `:527`; `core/commands.py:72`, `:86` |
| G25 数量4个 | 旧布局modules必须正好4，不是只设max4 | [backend/app/schemas.py:168](/home/kingdom/ai_learning/backend/app/schemas.py:168) |
| G26 数量20/100 | CriterionRecipe dimensions最多20，每dimension requirements最多20；EvidenceRequirement.minimum1–100 | [backend/app/learning_domain.py:40](/home/kingdom/ai_learning/backend/app/learning_domain.py:40), `:47`, `:52` |
| G27 日期字符串64字 | delayed_followup due_at、standard.reviewed_at（之后仍检查日期格式） | [backend/app/delayed_follow_up.py:39](/home/kingdom/ai_learning/backend/app/delayed_follow_up.py:39); `standards.py:35` |
