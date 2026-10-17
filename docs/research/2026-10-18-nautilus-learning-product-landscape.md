# Nautilus 学习产品深度调研

开源与闭源机制、学习效果证据、Nautilus 后端现状与明确改进方向

研究截至 2026-10-18 北京时间（2026-10-17 UTC）。本报告完成 10 月 15 日起的持续调研，覆盖 27 个产品或产品族；不同产品按其相关性进行不同深度的核查，不以数量代替证据。资料以官方帮助、版本化源码、发布说明及原始论文为主。

## 1. 先给判断

**Nautilus 面临的竞争，已经超过“上传资料后能问答、出题、生成互动”。** RemNote 把阅读、题卡、引导学习与考试排程放在同一工作流；StudyFetch 已有接受计划、保存步骤和恢复会话；DeepTutor 已区分原始尝试、提示使用、受助表现与独立表现。把这些产品概括为聊天包装，会导致低估对手。[S09](#s09) [S10](#s10) [S28](#s28) [S29](#s29) [S55](#s55)

**Nautilus 已经具备有状态教学与可追溯学习证据的后端基础。** 原始尝试、帮助条件、教学检查点、可纠正观察、正式验证、历史回看、近期安排和持续教练都有实际实现。竞争判断应从“还缺不缺这些基础”转向“覆盖了什么知识、判断有多可靠、用户能否顺畅使用、成果能否带走”。生成式交互应扩展这个基础，不能另起一套学习系统。[S97](#s97) [S98](#s98) [S100](#s100) [S101](#s101) [S102](#s102) [S105](#s105) [S108](#s108)

**当前最明确的差距是可靠评价覆盖、长期复习调度、交互作品生命周期与成果出口。** 已批准的 F 整体 UI/UX 主线是合理的：把已有能力组织成连贯的学习过程，具有直接产品价值。这里没有依据要求替换 Agent Runtime 或重新建设计划、证据、教练；也不能把代码完整直接当作学习效果已经成立。[S103](#s103) [S104](#s104) [S109](#s109) [S110](#s110) [S113](#s113)

本次最值得带回的五项取舍：

- 复用已有尝试、帮助、反馈和下一步记录；未来交互作品补齐操作状态与版本关联，避免重复建设证据系统。
- 优先借鉴 RemNote 的流程衔接、DeepTutor 的证据分层、Brilliant 的共享交互状态、Anki 的历史与调度、Moodle 的证据与权限设计。
- “掌握”必须有具体含义。看过、提示后答对、首次独立答对、隔几天完成新题，是不同证据，不能由一个百分比代替。
- 主动性应体现为有依据、可拒绝的下一项行动。提醒、定时模型调用、自动诊断和有效干预是四种不同能力。
- 保留既有 Agent Runtime 和开发路线；对生成式 UI 继续采用隔离、小范围验证。先判断它是否改善学习过程和可回看产出，再决定扩大。

**本次修订采用明确的功能基线。** 用户已确认本地领先远端的改动仅涉及 UI 操作逻辑，后端功能一致。因此以远端固定提交 `7b5835527675481a7e43324b20530fabf56a6d66` 判断后端功能，不再把信息同步列为结论的前置条件。第 9 节已按实际代码重写；本地界面的操作体验不由远端推断。研究阶段仅作只读分析；本次按作者要求归档研究文档，未修改应用代码、运行 Nautilus 测试或访问真实 Vault、正式数据库、trial。[S96](#s96)

## 2. 怎样比较：把五种状态分清楚

| 比较对象 | 真正要问的问题 | 常见误判 |
|---|---|---|
| 内容状态 | 材料来自哪里，生成内容是否可修订，能否回到当时版本？ | 有引用链接就能复原历史上下文 |
| 活动状态 | 课程、题目、计划进行到哪里，中断后怎样继续？ | 有聊天历史就等于有学习计划状态 |
| 学习者表现 | 原始答案、操作、提示、重试、置信度是否可区分？ | 最终答对就代表独立掌握 |
| 能力判断 | 结论依据哪些任务，是否受帮助、时间和情境限制？ | 卡片记忆概率、课程完成率都是通用能力分数 |
| 后续行动 | 该复习什么、何时做、为何做，能否拒绝与纠正？ | 发出提醒就构成有效的主动教练 |

本报告使用四种证据：**代码证据**确认实现结构；**官方说明**确认公开功能与承诺；**效果研究**确认某种研究条件下的结果；**分析判断**说明对 Nautilus 的意义。官方可用、代码存在、实际体验良好和学习有效，是不同结论。“未证实”表示本次资料不足，不表示功能一定不存在。

## 3. 竞争全景：27 个产品族各自解决什么

### 通用 AI、个人资料与知识工作流

| 产品 | 类型与主要机制 | 值得比较的实质能力 | 边界 |
|---|---|---|---|
| ChatGPT Study Mode / Visualizations | 闭源通用助手；引导问答与可交互可视化 | 学习目标、材料、可选记忆进入对话；低门槛生成交互表达 | 交互快照不是自动持久同步的学习应用；学习模式也可能直接给答案。[S01](#s01) [S02](#s02) |
| Gemini Apps Study notebooks / Gemini Notebook | 闭源资料与学习产品族；后者由 NotebookLM 更名 | 诊断、小课、测验、来源与进度；来源内的闪卡测验可恢复，闪卡可 CSV 导出 | Apps 与独立 Notebook 的入口、权限和端能力不能混用；Study notebooks 目前有网页与活动记录条件。[S03](#s03) [S04](#s04) [S05](#s05) |
| Claude Artifacts | 闭源创作与运行平台 | 作品保存、版本、导出；应用可有个人或共享状态 | 作者仍须定义教学和测量规则；导出作品不等于迁走全部云能力。[S53](#s53) [S76](#s76) |
| RemNote | 闭源知识与学习工作台 | 资料阅读、制卡、引导学、测验、考试排程和复习衔接 | 卡片记忆与课程掌握的判断仍需区分；AI 有额度成本。[S09](#s09) [S10](#s10) [S11](#s11) |
| Heptabase | 闭源视觉知识工作台 | 从白板资料进入 AI Tutor；课程和 AI 产出回到白板；编辑可审阅 | 持续知识产物已有实质设计，公开资料不足以证明校准过的能力判断。[S19](#s19) [S20](#s20) |
| Readwise Reader | 闭源阅读与回顾系统 | 段落内问答、保存回答为笔记；高亮转主动回忆卡 | 阅读回顾不全是提取练习；Obsidian 导出以追加为主。[S15](#s15) [S17](#s17) [S18](#s18) |
| Obsidian | 闭源本体、插件生态、文件型知识库 | 用户直接持有 Markdown 文件；适合作为可读学习资产的承载处 | 插件具有较广权限；本地文件不等于所有 AI 处理都离线。[S73](#s73) [S74](#s74) |

### 开源系统与成熟的学习基础能力

| 产品 | 类型与主要机制 | 值得比较的实质能力 | 边界 |
|---|---|---|---|
| DeepTutor | 开源完整学习系统 | 原始作答、受助条件、复习、学习记忆与定时 tutor turn | 评分规则和模拟学生评估不能直接证明真实长期能力提升。[S27](#s27) [S29](#s29) [S31](#s31) |
| OpenMAIC | 开源生成课堂与项目学习系统 | 内容模板与个人学习状态分开；服务端生成恢复；课程导出 | 某些帮助页临时输入不持久；课堂导出不等于完整学习档案。[S32](#s32) [S33](#s33) [S78](#s78) |
| Open Notebook | 开源、自托管资料研究工作台 | 来源、笔记、insight、对话持久化；模型可替换 | 明确单用户优先；系统备份不等于完整个人学习包导出。[S35](#s35) [S36](#s36) [S80](#s80) |
| Anki / FSRS | 开源桌面与多端生态；间隔复习 | 复习历史、目标记忆率、调度、带历史导出和同步 | 回忆自评与迁移能力不同；各客户端与算法库许可不同。[S37](#s37) [S38](#s38) [S81](#s81) |
| Moodle | 开源机构学习平台 | 逐步作答、提示、能力证据、人工复核、角色权限 | 系统较重；证据框架依赖课程设计与评价劳动。[S40](#s40) [S41](#s41) [S82](#s82) |
| H5P | 开源交互内容组件生态 | 可复用教学活动，输出回答、完成等 xAPI 事件 | 事件须由宿主接收和持久化；不是自带学习者模型。[S42](#s42) [S43](#s43) |
| PhET | 教育模拟资源与商业授权产品 | 可信的学科模拟、参数操作与探索 | 普通当前 HTML 模拟为 CC BY-NC 4.0；可访问不等于可免费商用嵌入。[S44](#s44) [S45](#s45) |
| Exercism | 开源编程练习生态 | 测试执行、代码分析、解法归类与人工指导分工 | 测试通过不证明作者独立完成，也不覆盖所有代码质量。[S46](#s46) |

### 课程、考试与持续辅导

| 产品 | 类型与主要机制 | 值得比较的实质能力 | 边界 |
|---|---|---|---|
| Khan Academy / Khanmigo | 闭源辅导服务结合成熟课程平台 | 课程练习、导师、学校实施、独立测验与进度 | 整套学校干预效果不能归因于聊天功能本身。[S47](#s47) [S72](#s72) |
| Brilliant / Koji | 闭源交互课程与导师 | 导师读懂当前交互，并在同一场景操作、提示 | 个性化课程与真正长期迁移是不同问题。[S48](#s48) [S49](#s49) |
| Duolingo / Video Call / Roleplay | 闭源语言学习 | 课程之外增加真实口头或书面产出，短会话、回顾和后续记忆 | 关系记忆不等于能力模型；Video Call 已开始向 Super 扩展，不能仍称 Max 独占。[S50](#s50) [S83](#s83) |
| Learn Your Way | Google Labs 研究实验 | 同源内容多种表达，加 QuizMe 与反馈 | 不能等同普遍开放的成熟个人学习产品；视觉贡献未被单独识别。[S52](#s52) [S84](#s84) |
| Quizlet | 闭源题卡、练习与 AI 测试 | 从材料生成测试、保存结果、按词条表现定向练习 | Progress 的 mastered 是产品内标准；不同测试和端能力有区别。[S22](#s22) [S23](#s23) |
| Knowt / Kai | 闭源题卡、语音辅导与教师工具 | 语音作答历史、卡片调度；教师可查看任务会话并复核成绩 | 教师课堂功能不能泛化到所有个人会话；未证实完整状态可迁移。[S24](#s24) [S25](#s25) [S26](#s26) |
| StudyFetch / Sparky | 闭源材料学习与教练 | 计划接受、步骤状态、跨活动引导、复习、提醒、Mini Apps | 最终练习完成率不能代替首次独立表现；消费者与机构数据政策不同。[S55](#s55) [S56](#s56) [S57](#s57) [S58](#s58) [S59](#s59) |
| Sana Learn | 闭源企业学习 | 课程内导师、资料边界、管理员工作流和通知控制 | 面向组织培训，不能直接当个人深度学习体验的完整答案。[S60](#s60) |

### 中文市场：入口、错题与跨端回流

| 产品族 | 已确认机制 | 值得借鉴 | 边界 |
|---|---|---|---|
| 豆包 / 豆包爱学 | 拍题、分步讲解、历史讲解参考与错题练习建议；通用豆包另有桌面入口 | 问题就地进入，历史参考可控 | 没有证据证明通用豆包与爱学的全部记录自动组成同一学习档案。[S61](#s61) [S62](#s62) |
| 作业帮 | 主 App 的学练测；开启关联后错题、生词可进入配套 App 和账号下智能设备 | 给临时问题一个明确的回流去处 | 学习机“全局随时问”不能泛化为普通手机 App 能力。[S63](#s63) [S85](#s85) |
| 有道小P | 解释与追问、错题本、学情分析；商业 API 另有接口 | 眼前答疑与后续错题串联 | 当前政策对题目解析/答疑有成年实名要求；商店年龄分级不能替代资格。[S64](#s64) [S65](#s65) |
| 通义听悟 | 音视频转写、章节、PPT 与结构化结果 | 时间戳和句子定位支持回到原课、原材料 | “问答回顾”提取已有问答，不能当成学习者能力评估。[S66](#s66) [S67](#s67) |

## 4. 深拆最值得借鉴的机制

### 4.1 RemNote：把学习动作接起来，比增加入口更重要

其 Guided Learn 从上传或已有资料生成分节计划，把摘要、题卡和测验放入连续过程；用户熟悉度影响学习顺序。学习状态随活动更新，较长材料可逐步生成。AI Tutor 可在阅读和复习中调用相关笔记、保存聊天，并让用户选择是否采纳生成题卡。**这是真实的工作流竞争，不是孤立的出题按钮。**[S09](#s09) [S10](#s10)

考试排程将考试日期、材料范围和每天可投入时间转成复习工作量；长期记忆调度与考试截止目标是两个机制。当前 FSRS v6 属于可选 beta，不能写成所有用户默认已经采用 FSRS。[S11](#s11) [S12](#s12)

对 Nautilus 的启发是把“当前材料—一次练习—保存结果—下次行动”接成可继续的任务。需要避免的取舍是为所有资料自动制造大量题卡：生成内容越多，审阅、纠错和到期复习负担也越大。应核查用户能否拒绝低价值产物，以及计划超出可用时间时如何收缩。这是设计分析，不是断言 RemNote 没有相关控制。

### 4.2 Readwise 与 Heptabase：成果应回到工作的地方

Reader 的段落问答携带文档与阅读位置，回答可保存为文档笔记；其 Mastery 可把高亮改为问答或填空。Readwise 到 Obsidian 的官方同步以追加新高亮为主，避免覆盖手改内容，但不保证双向同步和无重复。[S15](#s15) [S17](#s17) [S18](#s18)

Heptabase 已有 AI Tutor、课程白板、AI 产物归位、AI 来源标识与编辑差异审阅；移动端导师也已列入已发布记录。这些能力使 AI 产出进入长期知识组织，而不只留在聊天中。[S19](#s19) [S21](#s21)

Nautilus 当前 Obsidian 服务已经实现只读搜索与快照捕获，尚未提供学习成果写回；应用内学习记录则已经存在。因此可借鉴的是把自己的解释、问题与后续任务形成可带走的成果，并尊重原笔记中的手工编辑。无需为了这一点新增白板或整套知识管理系统。[S109](#s109) [S102](#s102)

### 4.3 DeepTutor：证据结构已经进入直接竞争范围

当前 v1.6.14 的学习记录包含原始答案、目标、时间、是否独立、提示与尝试条件；共享 assessment 保留原始尝试，并处理幂等身份与作废记录。策略层区分受助练习、独立展示与仅被讲解；学生自称掌握与系统判断具有不同来源。[S28](#s28) [S29](#s29) [S30](#s30) [S77](#s77)

它的 quantitative gate 与 qualitative pass 是明确的产品规则，不能当作已经校准的通用能力认证。Practice 的 SM-2 风格规则与另一 Mastery 调度机制也不能统称 FSRS。当前论文使用画像驱动的模拟学生评价，不能改写为真实学生的纵向迁移收益。[S29](#s29) [S28](#s28) [S86](#s86)

定时机制同样已有真实实现：在任务所有者作用域执行正常 tutor turn，把提醒及回复写回原聊天。它证明“持久化任务可以触发辅导”，没有证明系统已经能独立选择最佳干预并校准效果。[S31](#s31)

Nautilus 已实现类似证据分层，而且会把纯 AI 分析保留为部分支持，把候选、旧版本、不符合标准的证据排除出正式推导；观察也可纠正和排除。DeepTutor 应作为可靠性、覆盖范围与使用体验的比较对象，不构成重写现有证据层的理由。“记录学习过程”本身已不是独有卖点。[S98](#s98) [S101](#s101)

### 4.4 OpenMAIC：课堂模板、个人状态与导出要分别处理

10 月 16 日发布的 1.2.0 已把课程、身份、生成与模型配置迁到服务器，并支持生成恢复；代价是 PostgreSQL 与常驻 Node 服务。它不是仍停在 RC 的功能，也不是可直接塞进 Vite 的轻量组件。[S32](#s32)

PBL 学习状态保存提交、评价、讨论等，导出设计模板时则去掉个人表现，这是可借鉴的分层。特定最近发展区验证同时坦承：使用合成答案并修正过页面；有些帮助页临时输入不跨刷新保存；看过答案后的满分仍不足以证明独立掌握。[S78](#s78) [S33](#s33)

相关 MAIC 正式论文确有超过 500 名学生、10 万条学习记录的初步实践，不能说没有真人研究；但这不证明当前版本的每个生成式功能均有长期效果。[S34](#s34)

对 Nautilus 的启发是给每种产物明确生命周期：教学模板、可执行界面、学习者状态、评分与导出各自保存什么。课件可导出，并不自动意味着互动能力、个人尝试和云端依赖都能一起迁走。

### 4.5 Brilliant、PhET、Exercism：可信任务环境仍有价值

Koji 能看到当前题目与交互元素，并在同一场景里高亮、绘制或调整内容。这种共享任务状态比让用户不断截图解释“我在这里卡住了”更直接。家长面板也把活动、测评表现和求助类别分开，且不提供聊天原文。[S48](#s48) [S49](#s49)

PhET 提供经过学科设计的模拟；Exercism 把测试执行、代码分析、解法归类与导师评论分工。它们提示一个工程取舍：**生成解释可以灵活，核心任务规则与判定不必每次由模型重写。**[S44](#s44) [S46](#s46)

对 Softmax 场景，滑动温度后得到的概率、数值稳定性和边界关系适合确定性计算。模型更适合选择教学顺序、解释误解与反馈表述；不要让每次拖动都触发推理，也不要仅凭自然语言评语判断公式正确。

### 4.6 Anki 与 Moodle：长期学习的难点早已有成熟解法

Anki 的价值不仅是卡片：复习历史可用于重算调度，目标记忆率与工作量存在显式取舍，导出可以包含调度与 review log。其普通复习多数依赖学习者自评；历史记录也不等于当时完整题面与提示的不可变快照。[S37](#s37) [S81](#s81) [S87](#s87)

Moodle 保存逐步作答和提示过程，并将能力证据与评级、复核者分开。5.3 的 AI 使用报告进一步把教师可见的使用摘要与发起者可见的提示正文分离。它表明“可审查学习过程”与“最小必要可见性”可以同时设计。[S40](#s40) [S41](#s41) [S82](#s82)

Nautilus 的历史、纠正和证据推导已有基础；更值得借鉴的是 Anki 在长期调度与工作量取舍上的积累，以及 Moodle 的评价标准治理。现有回访队列与正则固定题组回访还不是通用的个人记忆调度。也不应把所有知识都变成卡片：记忆定义、推导结论、设计系统需要不同任务。[S101](#s101) [S104](#s104)

### 4.7 StudyFetch、Quizlet、Knowt：完成度已经高，掌握语义仍需谨慎

StudyFetch 的 Guided Chat 让用户接受或修改计划，再进入阅读、题卡、测验等活动，保存步骤状态并逐步继续；这比一次生成计划文本更接近可执行学习会话。[S55](#s55)

其 QuizFetch 用连续正确推进题目掌握，统计页保留错误、准确率和逐题历史。最终显示完成或 100% 的页面，与第一次答题结果仍须分开理解。Spaced Learning Hub 记录自评按钮和下次到期；浏览器提醒则可分别控制材料完成、日历与学习提醒。[S57](#s57) [S56](#s56) [S58](#s58)

Quizlet 已有保存的 AI Practice Tests 和按词条进度定向练习；Knowt 的语音题卡记录正确、错误、跳过，教师任务还能查看会话并复核评分。这些反例说明，市场并不缺“记录”。仍需要核对的是这些记录的解释、跨任务一致性和可迁移性。[S22](#s22) [S23](#s23) [S24](#s24) [S25](#s25)

对 Nautilus，最小但有价值的体验可能是重新打开时清楚显示：“上次你在提示后完成了 A；今天用一个新例子确认 B。”无需让用户先理解复杂能力图谱，也不必重新生成一整套计划。

### 4.8 大厂与中文产品：便利入口正在成为基础要求

Google 已把材料、诊断、短课、练习与进度放入学习笔记；Gemini Notebook 的题卡和测验可恢复，来源也有同步与权限语义。9 月的新语音及学习概览功能分批推出，不能把发布宣布直接当成所有账户可用。[S04](#s04) [S05](#s05) [S06](#s06) [S07](#s07)

中文产品同样在推进连续学习：豆包爱学参考历史并给错题练习建议，作业帮有明确账号关联回流，有道小P已有错题本。相比之下，通义听悟主要解决课堂或讲座的输入与回源问题。[S61](#s61) [S63](#s63) [S64](#s64) [S66](#s66)

这些做法值得借鉴，但不能把一个品牌所有 App、硬件、API 的能力拼成虚构的完整产品。Nautilus 也需要清楚的产品边界：先服务什么人、什么材料、什么学习目标，再决定哪些入口值得接入。

## 5. 学习效果：哪些结论有证据，哪些还没有

**已有正向结果，不能据此跳到“所有 AI 导师有效”；也已有负向结果，不能据此断言“AI 必然损害学习”。** 研究中的任务、帮助方式、对照、使用强度、评价时点往往比模型名称更能解释产品取舍。

| 研究与证据性质 | 设计与结果 | 能支持什么 | 不能支持什么 |
|---|---|---|---|
| Bastani 等，PNAS 2025；同行评审现场实验 | 近千名土耳其高中生；普通 GPT 与有教学约束版本对比。普通版本提高受助表现，但撤去工具后的成绩相对对照低 17%；教学约束版本缓解负效应。[S69](#s69) | 受助完成与独立学习可以背离；帮助方式值得单独控制 | 不是所有当前模型或学科都会下降 17%；也不是下降 17 个百分点 |
| Kestin 等，Scientific Reports 2025；随机交叉研究 | 194 名大学物理学生，两节课；专门设计的自学 AI Tutor 在即时测验中优于相应主动课堂条件。[S70](#s70) | 受控内容、教学设计和个性化速度可以产生短期收益 | 不能证明任意聊天助手优于教师，也未证明跨学期保持与广泛迁移 |
| Learn Your Way，Frontiers 2026；同行评审小样本实验 | 60 名高中生，单主题、最多 40 分钟；3–7 天后约 78% 对 67%。实验组均使用文本与 QuizMe，对照未匹配测验反馈。[S52](#s52) | 多种表达与练习组成的整套体验有积极信号 | 无法单独归因于视觉、兴趣个性化或额外模态；数天保持不能叫长期精通 |
| Khanmigo，2026 工作论文；真实学校集群随机 | 18 校、53 个校内年级集群，两个学年；第二年 ITT 0.084 SD，第一年不显著，合并结果仅在 10% 水平显著。[S72](#s72) | 整套课程平台与学校实施可以带来小幅改善 | 未隔离聊天增量；按参与率放大的约 0.14 不是全体随机分配效果；暑假保持未定 |
| Tutor CoPilot，2025 年修订工作论文；真人导师辅助 | 超过 700 名导师、1000 名学生；主题掌握提高约 4 个百分点，较弱导师组约 9 个百分点。[S71](#s71) | 帮助导师采用更好策略，是一条值得认真看待的路线 | 不是完全自主 AI 替代导师的证据，也不是长期跨领域能力证明 |
| Duolingo Video Call，2025 厂商原始报告 | 分层随机后 30 天使用，标准化口语/听力测验报告小幅优势；通话组实际学习更久，分析样本排除/未完成不对称。[S51](#s51) | 口语实际产出有短期价值，证据强于满意度 | 时长调整不能替代等量随机练习；没有停用后的长期复测 |
| Duolingo Roleplay/解释功能，Frontiers 2025 | 385 人，一个月前后自我效能调查，没有无 AI 对照。[S88](#s88) | 对学习信心与主观准备度有积极信号 | 不能当成标准化技能提升或实际迁移的因果证据 |
| DeepTutor / MAIC 的公开研究与验证 | 前者有模拟学生评估；MAIC 有真人初步实践；特定 OpenMAIC ZPD 验证明确为合成答案和工程检查。[S86](#s86) [S34](#s34) [S33](#s33) | 研究与工程机制均值得审阅，不能当纯演示忽略 | 不同论文、产品版本、实验对象和功能不能互相替代效果证据 |

Duolingo PDF 直接获取被拒，本次依据官方 PDF 的可检索方法和限制段核对；Kestin 正文获取不完整，采用期刊官方索引与摘要可确认的设计，不补写未读到的细节。其他结论同样按实际取得材料的范围陈述。

对 Nautilus 最有用的评价顺序是：先确认数学与任务正确、过程可保存，再观察学习者是否产生有意义的尝试，最后才评估独立表现与延迟迁移。**可用性验证、技术可靠性验证与学习效果验证各自回答不同问题。** 一个能顺利完成的演示不必同时承担全部科研任务；也不能在只做了演示后宣称效果已获证明。

如果未来比较文字教学与交互教学，应尽量匹配材料、练习、反馈和时间，只改变需要研究的交互表达。否则测到的可能只是“一组有练习、另一组没有练习”。新题也需要检查是否与示例近乎重复，以及是否提前泄露了关键结论。

## 6. 成本与集成：不能用消费者价格推算自建系统

### 6.1 真正需要区分的五类成本

| 成本类型 | 市场实例与机制 | 对 Nautilus 的含义 |
|---|---|---|
| 材料准备 | OCR、转写、解析、分段、嵌入、重建索引；听悟 API 按时长与能力叠加计费 | 用户上传一次不代表只花一次模型费用；材料变化也可能触发重新处理。[S67](#s67) [S68](#s68) |
| 生成与修复 | 课程、题目、媒体、界面、校验和失败重试；OpenMAIC 有多类能力槽 | 统计整项学习任务的调用，不把多步骤流程误算为一次调用。[S32](#s32) |
| 交互推理 | 每轮问答、语音、诊断、批改；Claude AI 作品消耗使用者额度 | 产品订阅中的“无限/包含”不能当嵌入到 Nautilus 的免费 API。[S53](#s53) |
| 状态与运营 | 持久化、恢复、同步、权限、备份、版本兼容、删除 | 很多长期成本发生在界面生成之后；自托管也有维护成本。[S36](#s36) [S80](#s80) |
| 教学与注意力 | 题目审阅、错判纠正、计划选择、制卡、复习债务 | 内容越多未必价值越大；用户的时间也是成本。[S11](#s11) [S37](#s37) |

一个可核对的代码实例是 Open Notebook 的 Ask：先生成检索策略，再对有结果的分支生成答案，最后综合。正常成功路径是“有效分支数＋2”次生成调用，另有检索嵌入；这不代表所有模式或异常路径的固定上限。[S89](#s89)

建议未来观测“完成一项有效学习活动所花的时间、调用和修复次数”，并在效果研究中另看“每个获得独立验证的目标的成本”。现阶段没有实际调用、统一工作负载或定价配置，**不能诚实给出精确的竞品单次美元成本、延迟排名或性能优劣**。

### 6.2 三种借鉴方式的成本区别

| 方式 | 能得到什么 | 主要额外工作 | 本次判断 |
|---|---|---|---|
| 直接使用闭源产品 | 现成账号、课程、UI、托管模型和运行环境 | 平台限制、数据出口、账户、地区与订阅；通常没有等价嵌入接口 | 可作为体验标尺；不把消费产品视作可导入模块 |
| 整体部署开源系统 | 完整工作流、数据模型与管理能力 | 新运行时、身份、存储、迁移、依赖、运维和与既有系统的冲突 | 对当前 Nautilus 成本高，且可能违反保留 Runtime 的边界 |
| 复用具体库/协议 | 已实现的调度、组件或事件表达 | 版本、许可、适配、边界、异常与数据映射 | 适合小而明确的能力，不会自动带来教学设计 |
| 借鉴机制、独立实现 | 更容易接入已有任务、来源和学习记录 | 自己承担正确性、状态恢复、评估与维护 | 对少数核心机制更可控，但并非“抄一个页面”就完成 |

### 6.3 已核版本和许可，不混淆本体与子组件

| 对象 | 本次基线 | 许可与直接集成边界 |
|---|---|---|
| DeepTutor | v1.6.14；6cf793bd… | Apache-2.0；整体系统有自己的 Python/前端、资料处理、状态与模型依赖，根许可不能代表全部依赖。[S27](#s27) [S90](#s90) |
| OpenMAIC | v1.2.0；a9da60b3… | 当前 MIT；1.2 需要常驻 Node 与 PostgreSQL，旧版本架构和历史许可证不能套用当前。[S32](#s32) [S91](#s91) |
| Open Notebook | v1.15.0；315d5255… | MIT；Python、前端、SurrealDB、worker、SQLite checkpoint 等共同构成运行系统。[S35](#s35) [S36](#s36) [S92](#s92) |
| Anki Desktop / fsrs-rs | 26.09.3 / 实际锁定的 6.6.2 | Anki 为 AGPLv3+；实际 fsrs-rs 为 BSD-3-Clause。复用独立算法库与复制 Anki 本体是不同选择。[S38](#s38) [S39](#s39) |
| Moodle | 5.3 LTS；稳定分支 Build 20261013 | GPLv3+；完整 LMS 的身份、课程与插件运维明显重于借鉴 evidence/attempt 概念。[S79](#s79) [S82](#s82) |
| H5P | 官方许可与事件文档 | 以 MIT 为主但存在 GPL 相关组件；具体组件需逐项确认。xAPI 事件不是自带 LRS 或能力模型。[S42](#s42) [S43](#s43) |
| PhET | 当前官方许可页 | 普通 HTML 模拟 CC BY-NC 4.0，商用另有许可；PhET-iO 有独立授权。不能沿用旧 CC BY 印象。[S44](#s44) |

这里是源码与公开许可的技术边界核对，不是全部传递依赖或商业许可审计。直接选用组件前需要按实际版本再看其许可；本轮没有安装或引入任何依赖。

## 7. 持久化、跨端、导出与隐私：四个独立问题

### 7.1 不能只问“支持保存/手机/导出吗”

| 代表 | 已有能力 | 仍需分清的边界 |
|---|---|---|
| Gemini Notebook | 题卡/测验进度、CSV 题卡；资料更新与权限处理 | Study notebooks 的网页条件不能扩大到全部移动端；原资料同步不证明旧答案锁定了当时内容。[S04](#s04) [S05](#s05) [S07](#s07) |
| Claude Artifacts | 作品保存、文件导出、付费个人/共享应用状态 | 新旧作品存储规则不同；模型、连接器、账户与共享权限不随 HTML 自动迁走。[S53](#s53) [S76](#s76) |
| RemNote | 原生备份、Markdown/HTML/Anki 等出口 | 原生导出不含图片/PDF 本体，媒体需另行处理；不同格式保留的语义不等价。[S14](#s14) |
| Readwise | 问答存入笔记，高亮导出到 Obsidian | 追加同步保护手改，但改名/移动与更新存在限制，不能宣传全双向一致。[S18](#s18) |
| OpenMAIC | 服务端恢复；PPTX/离线 HTML 课堂导出 | PPTX 交互场景以在线入口承接；离线课件不是完整 AI/PBL 与个人状态迁移。[S32](#s32) |
| Open Notebook | 系统级备份恢复；资料/笔记/聊天持久化 | 多个持久层要一起处理；完整用户级学习包未获充分确认，且默认是单用户产品。[S36](#s36) [S80](#s80) |
| Anki | 包含调度/历史的导出；跨设备同步 | 媒体另有选项；结构性变更可能需要单向同步，不能当无冲突复制。[S81](#s81) [S93](#s93) |
| Moodle App | 部分资料与活动离线后同步 | 离线测验有条件，外部工具和插件不一定支持；同步时间可能不是实际学习发生时间。[S94](#s94) |
| 中文产品族 | 错题回流、历史记录或个人信息副本申请 | 个人信息副本权利不等于一键导出原答、提示、评分、来源版本和复习计划。[S61](#s61) [S63](#s63) [S65](#s65) |

**一个值得采用的出口分层：**第一层是离开产品仍可阅读的成果；第二层是能继续计算的结构化记录；第三层才是完整可运行应用。Nautilus 可以先保证前两层的关键内容，而不必把每个动态界面都变成跨平台软件包。这个选择需要与已有 Obsidian 方案对齐，不是要求立即引入新格式。

### 7.2 数据边界应具体到产品与动作

RemNote 的本地知识库不等于所有 AI 请求留在本机；Gemini Notebook 的默认训练承诺与用户提交反馈的例外不同，Workspace/Education 又有不同保护。StudyFetch 的消费者政策与机构/K-12 合同也不同，不能混成一句统一的“学生数据从不训练”。[S13](#s13) [S08](#s08) [S59](#s59) [S95](#s95)

豆包爱学的历史参考开关与训练数据撤回不是同一控制；有道小P题目答疑有明确资格要求。这里只陈述实际政策边界，不从一份隐私政策反推模型内部实现或断言产品违规。[S61](#s61) [S65](#s65)

对 Nautilus 最有用的产品表达是告诉用户：这次会把哪部分材料交给哪个处理环节、结果留在哪里、能否删除或带走。没有必要让每次练习都出现技术说明；在发生有意义的数据选择时给出清晰控制即可。

### 7.3 “有沙箱”还不能回答所有隔离问题

Claude Design 公布了独立内容域的 sandboxed iframe 与短时访问令牌；这是预览隔离。创作时的云代码执行和连接器访问属于其他层，不能互相替代。Obsidian 插件具有较广宿主权限，也说明“本地运行”与“细粒度隔离”不是同义词。[S54](#s54) [S73](#s73)

对生成式教学界面，应分别限制可用组件、网络/宿主能力和数据写入范围，并把高频操作留在确定性组件中。本轮没有进行安全攻击测试，也没有证据支持比较各闭源产品的实际漏洞率、统一 CPU/内存上限或完整隔离强度排名。

## 8. 市场仍处理不好的问题：有反例，也有未解决的张力

以下是跨样本反复出现的难题，**不是“所有产品都缺这些功能”**。

| 难题 | 已有较好做法/反例 | 仍然难在哪里 | Nautilus 值得验证的方向 |
|---|---|---|---|
| 把帮助后的成功解释为能力 | DeepTutor 区分受助；Moodle 保存步骤；OpenMAIC 验证明确指出满分不等于独立 | 系统看不到全部外部帮助；页面答案、重试和熟悉题会改变结果含义 | 记录可观察帮助，诚实标注无法确认的独立性 |
| 把“mastered”变成可信承诺 | FSRS 有明确定义的记忆预测；Brilliant 区分活动与评估 | 不同知识、任务与时间尺度不能共用随意百分比 | 用具体证据说明已验证到哪里，避免过度确定 |
| 生成题目出错后恢复信任 | DeepTutor 有作废记录；平台普遍有题目反馈 | 修正题目后历史分数、计划和能力判断可能已被影响 | 保留修订与作废原因，重新解释受影响记录 |
| 从一个场景迁移到新问题 | 部分研究有新任务或标准化测试 | 同义改写并非真正迁移；短期效果不保证长期保持 | 少量有代表性的新情境与延迟任务，清楚定义范围 |
| 自由材料与可靠课程结构兼得 | 资料型助手灵活；Brilliant 等课程系统更受控 | 用户材料可能残缺、过时、相互矛盾，缺少可用评价标准 | 先明确来源与目标，缺少依据时允许“尚不能判断” |
| 主动教练不过度打扰 | StudyFetch 计划接受/逐步继续；RemNote 截止日期排程 | 回访点击、连续签到与学习收益并不等价 | 提醒给出依据、耗时与延期选项，按帮助价值评估 |
| 内容越来越多，学习越来越重 | Readwise 就地记录；用户可选择是否采纳部分 AI 产物 | 自动制卡、摘要、地图可能形成内容和复习债务 | 生成前有目的，生成后可舍弃；先留下少而有用的成果 |
| 跨端与离线一致性 | Anki 有历史同步；Moodle 有受限离线；作业帮有账号回流 | 身份、冲突、媒体和活动时间语义不同；网页适配不等于原生/离线 | 先把一个核心流程在目标端做好，再逐步扩大承诺 |
| 数据可携带性 | Anki 可含历史导出；RemNote 多格式；课件/笔记可带走 | PDF、可读内容、结构化证据、运行能力是不同出口 | 导出自己的尝试与依据，别只导出模型答案 |
| 可审查与思考隐私并存 | Moodle 只向教师开放必要摘要；Brilliant 面板不展示聊天原文 | 学习者需要放心犯错，又可能需要老师/家长支持 | 角色与用途决定可见范围，不默认收集越多越好 |
| 推理成本和反馈速度可控 | Anki 调度、Exercism 测试和本地模拟不需逐次 LLM | 多媒体、上下文、重试与多代理会叠加费用和等待 | 让模型只承担其有增益的环节，按任务看成本 |
| 真实能力提升的商业证明 | 已有随机研究与厂商实验 | 很多研究无法隔离 AI/UI 增量，样本、期限、分母不同 | 对外承诺与取得的证据同尺度，先证明一个窄场景 |

这里最有价值的机会不是“记录更多字段”，而是把记录变成学习者能理解并采取行动的解释。例如“你已完成这节课”只能证明活动结束；“你能在无提示条件下解释温度上升为何使分布变平，但还未验证接近零时的行为”更能指导下一次学习。后者也需要真实任务支撑，不能由模型凭印象写出。

## 9. Nautilus 后端对照后的明确结论

本节以用户确认的“本地与远端后端功能一致”为前提，固定到提交 7b58355。判断依据是服务、请求结构、状态推导与路由实现，并参考当前路线；没有用旧状态文档中的历史限制覆盖后来已经交付的功能。[S96](#s96)

### 9.1 已经做好的基础：这些不应再列为待补功能

| 能力 | 代码确认的实际行为 | 对竞争判断的意义 |
|---|---|---|
| 有状态教学 | teaching_runtime 保存版本内检查点，支持分步、苏格拉底、费曼、练习优先、项目与自适应；校验用户原话，正常完成后才接受状态更新。[S97](#s97) | 已超出单纯切换提示词的教学模式；下一步比较教学质量与连续体验。 |
| 尝试、求助与展示分离 | help_records 区分请求、实际生成正文、客户端报告的展示；正式提交冻结同题帮助条件，不因没有帮助记录就推断独立。[S99](#s99) [S100](#s100) | 已经处理“答对是否受助”这个关键问题，不应建议从零补一套提示追踪。 |
| 观察可追溯、可纠正 | 观察绑定用户原文和反馈位置；保留原始状态、修订、排除标记；当前路径上下文使用有效记录。[S98](#s98) | 有防止误判持续污染后续教学的机制；还需关注识别与反馈本身是否准确。 |
| 正式证据有约束 | 已批准标准才参与推导；待审候选、旧产物版本与失效证据被排除；纯 AI 分析只得到部分支持；提交与评价保留版本。[S101](#s101) [S115](#s115) | 来源可靠、模型觉得正确、用户实际表现三者没有简单混成一个“掌握分”。这是已有的工程长处。 |
| 记录可以回看 | LearningRecords 可按提交、评价版本读取原始内容、帮助展示和关联讨论；学习路由已有产物、正式验证、回访与 replay 入口。[S102](#s102) [S114](#s114) | “保存后能回看”不是空白。交互回放仍是另一项契约，不能由现有 replay 名称推定已经具备。 |
| 近期安排与中断恢复 | commitments 已有草案、预览、确认、变更、开始及执行反馈；服务端保存对话选择状态，使用版本检查处理过期更新。[S108](#s108) [S119](#s119) | 不必为追齐 StudyFetch 另建计划状态系统；应检查已有安排是否在使用中减轻负担。 |
| 持续教练与提醒 | 教练会话持久化并复用已有聊天运行时；后台建议受来源、事件、会话/日预算和冷却限制；时钟提醒无需模型调用，有安静时段、每日限额和学习中抑制。[S105](#s105) [S106](#s106) [S107](#s107) | 已有受控主动性。后续问题是建议有用率、任务选择与打扰代价，不是有没有教练。 |
| 资料进入有边界 | Obsidian 服务只读检索、显式捕获快照，检查连接修订及文件内容哈希；不直接改写用户笔记。[S109](#s109) | 已有可追溯的资料入口，尚缺学习成果返回原工作环境的对应出口。 |

**整体判断：Nautilus 已经拥有值得保留的学习与证据架构。** 就公开实现的机制而言，它不应再被归入只会根据资料聊天、出题的薄层产品。这个判断不等于“功能全面领先竞品”：RemNote、StudyFetch、DeepTutor、Anki、Brilliant 分别在连续流程、覆盖、调度或教学内容上有实质积累。

### 9.2 真正需要改进的地方

| 明确差距或限制 | 依据与实际影响 | 改进应落在哪里 |
|---|---|---|
| 可靠评价的知识覆盖仍窄 | 默认已批准标准包固定为 Python 正则基础；通用 AI 出题/评价已有实现，但不等于各领域都有经审查的能力标准。证据架构可以通用，现有标准和判定内容尚不能支撑通用掌握承诺。[S103](#s103) [S115](#s115) | 优先把目标用户最常学的少数领域做实：好题、明确尺度、误判纠正、必要的人工审阅。主要瓶颈是教学与评价内容，不是再增加图谱对象。 |
| 长期复习尚未形成通用调度 | 已有不足证据/待复核/补充验证回访队列；延迟比较则固定为正则的两组各 8 题，建议间隔 3 天、最低比较间隔 24 小时，并明确不证明稳定掌握或迁移。[S101](#s101) [S104](#s104) [S116](#s116) | 从现有历史出发决定“该复习哪个薄弱点、用什么任务、多久后再看、如何限制负担”。Anki 的调度可借鉴，但无需把所有任务卡片化，也无需用 FSRS 替换现有教练。 |
| 结构化教学并非所有模型组合都可用 | teaching_capability 按供应商配置、凭据版本、协议与模型绑定结果；未检查或不支持的组合退回普通文本，原生搜索组合也退回 plain。[S112](#s112) | 把“能聊天”和“能生成可用教学记录”的支持范围说清楚。质量与覆盖是后端实际限制，本地 UI 改进可以改善呈现，但不能消除这一限制。 |
| 可持续交互作品尚无正式数据契约 | 现有学习产物请求主要是 session_id、content、expected_version、idempotency_key；teaching_wire 是回答与教学元数据，没有组件树、交互状态、操作事件和运行版本的作品协议。已有版本控制不自动等于交互作品恢复。[S110](#s110) [S111](#s111) [S120](#s120) | 隔离验证只补交互作品这一层，复用现有任务、来源、帮助和证据语义；不能让拖动次数或作品生成成功自动升级成能力证据。 |
| 可带走的学习成果出口未闭合 | 应用内可回看原答和评价，但现有学习记录/产物接口没有提供把原答、帮助、反馈、来源版本与后续任务组成便携学习包的完整出口；Obsidian 服务明确只读。原生验证包也明确未接入导出。[S102](#s102) [S109](#s109) [S114](#s114) [S117](#s117) | 借鉴 Readwise 的成果归位与 Anki 的历史导出。应讨论用户可读记录与必要结构化数据；不因此默认批准向真实 Vault 写入或建设双向同步。 |
| 跨端交付仍是局部能力 | Web 已有服务端恢复；独立原生 0.4.0 已有 Windows/Android 本机保存与局域网同步，但完整学习域、全部模型协议和四平台交付尚未统一。[S113](#s113) [S117](#s117) [S119](#s119) | 按既定 F 与客户端迁移方向收口，明确各端可以完成的整条学习旅程。不能把 Web 小屏可用或原生首片同步称为完整四端产品。 |
| 教练已有约束，但有效性还未被证明 | 当前教练是基于受限结构摘要的建议与导航，不会自动理解所有原始学习内容、创建整套正式计划或替用户开始学习；预算和冷却解决调用边界，不证明干预有效。[S105](#s105) [S107](#s107) | 观察建议之后是否真的完成有用行动、是否反复推荐被拒事项、是否增加负担。不要为“更主动”扩大无依据读取、调用频率或自动改计划。 |

还有一个可以直接作出的产品判断：**后端对象与状态已经足够丰富，继续横向增加同类功能的收益，很可能低于把已有能力组织成一条短而连贯的学习流程。** 这是根据架构成熟度和竞品机制得出的优先级判断，不是对用户最新本地 UI 的负面评测。首次操作是否冗长、入口是否难找，应由当前界面决定；不再用远端界面推断。

### 9.3 对现有进度与计划的判断

**继续当前 F 整体 UI/UX 主线，不因本次竞品调研重排路线。** 当前路线已经明确“已完成能力只作为基础，不重新开发”，并将客户端迁移和整体体验一并处理。这与调研结论一致。旧资料中“下一步建设教练”的建议已被实际实现和后来的路线覆盖，不应继续沿用。[S113](#s113)

需要改善的是验收重点：让用户在同一学习过程中看到当前任务、自己的尝试、收到的反馈、保存的成果和回来后的下一步；复杂证据细节在需要解释或纠错时可展开。教学覆盖、长期调度、成果出口和生成式交互属于明确的后续讨论项，不自动追加为 F 的完成条件。

## 10. 借鉴优先级与不值得追逐的目标

本节是研究后的评估顺序，不是新的开发排期。

先看各类产品真正拥有的优势，才能避免只跟着功能发布走。下表是基于前述机制的竞争分析，不是市场份额或商业收入排名。

| 竞争位置 | 用户主要为了什么而来 | 较难复制的积累 | Nautilus 应怎样比较 |
|---|---|---|---|
| 通用大模型助手 | 随时提问、处理材料、生成工具 | 通用能力、已有入口和账户使用习惯 | 证明专门学习流程在连续使用时减少了多少负担，而不只比较一次回答 |
| 课程与题库产品 | 学完一门课、应试、获得明确练习 | 课程设计、题目质量、内容覆盖和评价体系 | 不以任意生成内容替代经过检查的任务；先选自己能做扎实的知识范围 |
| 个人知识与阅读工具 | 留住资料、形成自己的知识组织 | 已积累材料、来源关系、编辑习惯与工作流 | 尊重用户原有材料组织，给出新增学习价值，避免强迫整体迁移 |
| 自托管开源学习系统 | 控制模型、数据和部署，按需修改 | 完整流程、社区修复与可检查实现 | 比较长期维护与数据语义；开源可见不代表整套接入成本低 |
| 学校/企业学习系统 | 管理课程、分配任务、监督与报告 | 身份、权限、课程治理、机构采购与服务 | 借鉴证据和权限机制，不把个人产品变成不必要的管理后台 |

Nautilus 目前的差异化假设应当落在用户已经拥有的材料与持续深度学习之间。是否值得付费，还取决于用户学习频率、现有工具组合、人工整理时间与结果可信度；本次没有用户访谈或收入数据，因此不声称已经验证商业需求。

| 顺序 | 现在值得关注的事项 | 复用基础与借鉴对象 | 范围判断 |
|---|---|---|---|
| 当前已批准主线 | 将进入、学习、反馈、保存和续学连成明确流程 | 复用现有状态与记录；借鉴 RemNote、StudyFetch 的衔接 | 继续 F UI/UX；不重建计划、证据和教练，不以竞品功能追加验收项 |
| 后续优先讨论 | 把少数高价值领域的评价做可靠 | 复用正式验证、标准与纠错；借鉴成熟课程和 Moodle 的评价治理 | 先明确适用知识与评价依据，再扩大覆盖，不宣称通用掌握 |
| 后续优先讨论 | 让历史支持长期复习与可带走成果 | 复用回访、帮助和版本记录；借鉴 Anki 调度、Readwise 归位 | 分别处理调度、可读导出与结构化记录，不能笼统称为“接入 Obsidian” |
| 专项保持隔离 | 受控交互组件服务具体理解障碍 | 复用现有学习语义；借鉴 json-render 与 Brilliant 共享任务状态 | P0/P1 仍需按原规划单独决定启动，不改变 F 排期 |
| 持续使用中观察 | 教练收益、提醒负担、跨端续学 | 利用已有预算、来源、接受/拒绝与任务状态 | 以有效行动和恢复成功为判断，不以调用次数、提醒数量为成绩 |

不建议把“会生成任意 App”“多代理数量多”“内容形式多”“仪表盘复杂”“所有知识都有掌握百分比”单独当作目标。也不建议因为发现一个开源系统更完整，就更换现有 Agent Runtime。完整系统的优势通常来自协同的任务、内容、状态和运营，照搬入口难以获得同样效果。

比较上述竞争位置后，我更看好一个需要验证的定位：**学习者用自己的资料，完成真正需要动手和解释的任务，得到可信、可继续、可带走的成果。** 这与 Nautilus 已认可的生成式交互学习方向一致，但是否构成付费价值或长期留存优势，仍需要目标用户与使用证据。

## 11. 与既有生成式 UI 专项的衔接：保留隔离验证

此前技术研究的候选方向仍然合理：以受控 React 组件目录验证最小教学单元，借鉴 json-render 的声明式渲染方式；A2UI 用于协议与跨端研究，Open Intelligent UI 用于自定义界面与隔离思路。这里没有重做三者的完整版本审计，也没有把先前建议提升为技术批准。

**仍遵守原规划：P0 是隔离技术验证；Softmax 温度滑块是 P1 候选。** 本报告只是说明，如果该候选以后被选中，应怎样避免验证目标退化成“生成了一个漂亮滑块”。不访问真实 Vault、数据库或 trial，不增加正式功能范围。

**与现有后端衔接时，新增对象应是交互学习作品，不是新的教学运行时。** 现有 TeachingRuntime 继续管理教学步骤，帮助记录继续区分请求、输出与展示，正式验证与证据审查继续负责能力结论。作品额外保留组件描述/版本、来源引用、关键状态与操作、学习者原答、反馈关联及回看所需信息。原有 expected_version 是状态并发检查的一部分，不能代替作品 schema 或组件运行版本。[S97](#s97) [S99](#s99) [S110](#s110) [S111](#s111) [S120](#s120)

P0 中这些接口只以合成样本或适配器契约表达，不调用生产写入接口；不为验证自行扩展正式数据库。这样才能检验作品是否未来接得上已有记录，同时维持专项规定的隔离边界。[S118](#s118)

### 一个可审查的候选学习单元

| 环节 | 学习者实际做什么 | 留下的证据 | 模型与程序的分工 |
|---|---|---|---|
| 预测 | 先判断温度升高后分布怎样变化，并说明理由 | 首次判断和原话 | 模型可设计问题；此时不展示答案 |
| 操作 | 改变温度，比较固定 logits 的概率分布 | 有教学意义的参数选择、比较点和提交；无需保存每个鼠标像素 | 概率与绘图由可信程序即时计算 |
| 解释 | 解释观察与预测为何一致或不一致 | 学习者自己的解释、使用过的提示 | 模型可追问；不把自己的解释写成用户回答 |
| 验证 | 换一组数据或条件，做新的无提示任务 | 新题原答、帮助状态、确定性结果或有依据的评价 | 能规则判定的部分用规则；开放解释保留判断依据和不确定性 |
| 回看 | 关闭后重新打开，查看变化和下一步 | 内容版本、尝试、反馈、尚待验证项 | 重开不重新生成整课；未来导出有可读表示 |

对于 Softmax，固定教学计算应采用数值稳定形式，明确 T＞0；验证概率归一化、温度改变时的预期行为，并避免将数学边界误讲成所有模型采样策略的完整行为。这个单元的成功也不等于学习者掌握了全部温度采样知识。

### 技术通过与学习通过分别判断

| 类别 | 可检验的候选成功标准 | 失败时说明什么 |
|---|---|---|
| 任务正确 | 核心数学和少数边界输入正确；未知组件/非法参数可明确拒绝 | 还不能用作教学内容，即使视觉正常 |
| 记录可信 | 首次尝试、提示后尝试、模型反馈可区分；错误题可标记作废 | 不能用最终得分推断掌握 |
| 可恢复 | 刷新/关闭重开后，能够读回同一活动与个人尝试，不依赖重新生成 | 只完成了一次性展示 |
| 可回看 | 学习者能说清上次预测、观察、误解与下一步，而不是只找到聊天长文 | 产物保存了但使用价值尚未成立 |
| 成本可控 | 拖动不调用模型；记录实际生成、反馈和修复调用，不设虚构省钱比例 | 需要重新分配确定性计算与推理职责 |
| 使用可达 | 目标浏览器内可完成，关键操作有键盘或等价输入；小屏可用性按实际目标单独确认 | 不能以桌面截图宣称跨端完成 |
| 教学增益 | 后续经匹配对照观察新的无提示任务与短期延迟表现，同时记录耗时和提示 | 技术可行但尚未证明值得扩大；小样本不宣称统计显著 |

最小验证只做与这些风险对应的检查，不追求庞大自动化测试矩阵。先把具体学习活动做成可审查结果，再决定是否需要正式效果研究；本次没有启动该验证。

## 12. 已确定的判断边界与后续观察

- **Nautilus 功能基线已确定：**用户确认本地与远端后端一致；第 9 节的功能与缺口结论不再等待本地同步。仅本地 UI 操作体验未据此评分，后端工程完整也不代表教学有效性已经得到实证。
- **真实体验：**未注册、购买、安装或上传竞品资料，不能给出语音自然度、实际故障率、跨端恢复成功率或用户偏好的实测排名。
- **闭源内部机制：**没有公开的模型编排、精确成本、统一隔离配额、完整学习状态出口时，均保留未知；宣传“自适应”不足以反推出算法。
- **效果外推：**多数研究集中在有限课程、群体和时间窗。Nautilus 所面向的个人资料、跨领域深度学习，需要自己的证据。
- **许可与数据：**只核对代表性本体与关键子组件，未完成全依赖审计；消费、学校与企业条款分开阅读。
- **名称与版本：**NotebookLM 已更名 Gemini Notebook；OpenMAIC 1.2.0 已正式发布；OpenNote 的同名 Rust 笔记项目未混入教育产品清单；功能发布宣布与全面可用已区分。

研究已足够支持当前取舍：保留现有学习后端与 Agent Runtime，继续既定 UI/UX 主线，把可靠评价覆盖、长期复习、成果出口列为后续重点，生成式交互保持隔离验证定位。下一次观察应围绕已有真实学习过程：什么帮助了用户独立完成新任务、什么提醒带来有效行动、哪些记录在几天后仍有用。无需为了得出这些结论继续扩充竞品名单，也无需现在启动大规模测试或正式开发。

## 13. 一手来源与版本索引

正文编号链接到下方原始资料。产品文档用于确认公开功能与限制，源码固定提交用于确认实现，论文单独说明研究性质。未完整读取的论文已在正文标明；没有用搜索排名、用户评论、星数或营销形容词作效果证明。

### S01

[ChatGPT：Study Mode 使用说明](https://help.openai.com/en/articles/11780217-using-study-mode-in-chatgpt)

官方帮助；学习机制、可选记忆与使用边界。

### S02

[ChatGPT：Visualizations](https://learn.chatgpt.com/docs/visualizations)

官方文档；交互表达、端与持久性边界。

### S03

[NotebookLM 更名 Gemini Notebook](https://blog.google/innovation-and-ai/products/gemini-notebook/notebooklm-gemini-notebook/)

2026-07-16 官方发布；更名及产品衔接。

### S04

[Gemini Apps：Study notebooks](https://support.google.com/gemini/answer/16972047?hl=en)

官方帮助；诊断、学习状态、活动记录与网页条件；续接前次已读取资料，本轮再次打开失败。

### S05

[Gemini Notebook：Flashcards and quizzes](https://support.google.com/gemininotebook/answer/16958963?hl=en)

官方帮助；进度恢复、重练、CSV 与授权内容限制。

### S06

[Gemini Notebook：2026 年 9 月学习工具更新](https://blog.google/innovation-and-ai/products/gemini-notebook/new-study-tools-september-2026/)

2026-09-15 官方宣布；分批推出，不等同全量可用。

### S07

[Gemini Notebook：来源类型与更新](https://support.google.com/gemininotebook/answer/16215270?hl=en)

官方帮助；来源副本/同步、权限和导入限制。

### S08

[Gemini Notebook：数据保护](https://support.google.com/gemininotebook/answer/17004255?hl=en)

官方帮助；消费者反馈例外与 Workspace/Education 边界。

### S09

[RemNote：AI Tutor Chat](https://help.remnote.com/en/articles/10103884-ai-tutor-chat)

2026-09-02 帮助；任务内辅导、笔记来源、产物采纳。

### S10

[RemNote：Guided Learn Mode](https://help.remnote.com/en/articles/15724936-guided-learn-mode)

2026-09-04 帮助；材料、计划、练习与状态衔接。

### S11

[RemNote：考试排程原理](https://help.remnote.com/en/articles/9102040-understanding-the-exam-scheduler)

官方帮助；考试目标与长期调度分工。

### S12

[RemNote：FSRS](https://help.remnote.com/en/articles/9124137-the-fsrs-spaced-repetition-algorithm)

2026-08-21；FSRS v6 beta，不能称默认全面启用。

### S13

[RemNote：笔记隐私](https://help.remnote.com/en/articles/7974260-privacy-of-your-notes)

官方帮助；本地库、云同步和 AI 处理边界。

### S14

[RemNote：导出与打印](https://help.remnote.com/en/articles/7898019-exporting-and-printing-notes)

官方帮助；不同出口内容与媒体限制。

### S15

[Readwise Reader：文档内 Ghostreader Chat](https://docs.readwise.io/reader/guides/ghostreader/chat)

官方文档；位置上下文、回答保存与端边界。

### S16

[Readwise Reader：全局 Ghostreader](https://docs.readwise.io/reader/guides/ghostreader/global)

补充：跨材料与聊天历史。

### S17

[Readwise：Mastery](https://docs.readwise.io/readwise/guides/mastery)

官方文档；高亮转问答/填空与回顾。

### S18

[Readwise：Obsidian 导出](https://docs.readwise.io/readwise/docs/exporting-highlights/obsidian)

官方文档；追加、手改保护与同步限制。

### S19

[Heptabase：Changelog](https://wiki.heptabase.com/changelog)

官方带日期发布记录；Tutor、AI 标识、白板归位与编辑审阅。

### S20

[Heptabase：Work with AI](https://wiki.heptabase.com/work-with-ai)

官方机制文档；资料作用域。

### S21

[Heptabase：Roadmap / 已发布功能](https://wiki.heptabase.com/roadmap)

用于核对移动端 Tutor 的已发布状态，不把未来规划当现状。

### S22

[Quizlet：Practice Tests](https://help.quizlet.com/hc/en-us/articles/25946589648013-Studying-with-Practice-Tests)

官方帮助；与普通 Test 区分，记录、资料与端限制。

### S23

[Quizlet：Progress](https://help.quizlet.com/hc/en-us/articles/360048803491-Using-Progress-for-targeted-studying)

官方帮助；词条进度及定向练习。

### S24

[Knowt：复核 Chat Tutor 会话](https://help.knowt.com/en/articles/16905157-how-to-review-chat-tutor-sessions)

教师课堂范围，不能泛化到全部个人聊天。

### S25

[Knowt：Call Kai](https://help.knowt.com/en/articles/16905162-how-do-i-use-call-kai)

官方帮助；语音题卡、通话历史和表现。

### S26

[Knowt：Spaced Repetition Mode](https://help.knowt.com/en/articles/10714645-how-do-i-use-spaced-repetition-mode)

官方帮助；按钮自评和间隔，不推断为 FSRS。

### S27

[DeepTutor：v1.6.14](https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.14)

2026-10-08 正式版；源码固定为 6cf793bd868ba5ecbe64722936d4be8fab5a01df。

### S28

[DeepTutor：Practice](https://github.com/HKUDS/DeepTutor/blob/6cf793bd868ba5ecbe64722936d4be8fab5a01df/docs-for-user/PRACTICE.md)

固定源码；原始答案、复习、客观判定与自评。

### S29

[DeepTutor：掌握策略](https://github.com/HKUDS/DeepTutor/blob/6cf793bd868ba5ecbe64722936d4be8fab5a01df/deeptutor/learning/policy.py)

固定源码；独立/受助、自述/系统来源与阈值。

### S30

[DeepTutor：学习数据模型](https://github.com/HKUDS/DeepTutor/blob/6cf793bd868ba5ecbe64722936d4be8fab5a01df/deeptutor/learning/models.py)

固定源码；QuizAttempt、LearningEvidence 等字段。

### S31

[DeepTutor：定时任务执行](https://github.com/HKUDS/DeepTutor/blob/6cf793bd868ba5ecbe64722936d4be8fab5a01df/deeptutor/services/cron/executor.py)

固定源码；用户作用域、Runtime 调用、回写原会话。

### S32

[OpenMAIC：1.2.0 Server-first release](https://github.com/THU-MAIC/OpenMAIC/releases/tag/v1.2.0)

2026-10-16 正式版；服务端、恢复、导出与部署变化。

### S33

[OpenMAIC：ZPD 本地验证记录](https://github.com/THU-MAIC/OpenMAIC/blob/a9da60b3b4adb429369c0da13d5637a904ead2b0/eval/zone-of-proximal-development/LOCAL_VALIDATION.md)

固定源码内的 2026-09-05 历史验证；合成答案与持久化限制，不是本次实测。

### S34

[From MOOC to MAIC，JCST 2026](https://jcst.ict.ac.cn/en/article/doi/10.1007/s11390-025-6000-0)

只采用正式论文摘要中的真人实践规模，不声称已复核因果设计。

### S35

[Open Notebook：持久化对象模型](https://github.com/lfnovo/open-notebook/blob/315d5255af2a5132aada41c94d5c3c5dc8e837aa/open_notebook/domain/notebook.py)

v1.15.0 固定源码；来源、笔记、insight 与对象关系。

### S36

[Open Notebook：配置与备份](https://github.com/lfnovo/open-notebook/blob/315d5255af2a5132aada41c94d5c3c5dc8e837aa/docs/5-CONFIGURATION/advanced.md)

固定源码；文件、数据库与恢复。

### S37

[Anki：Deck Options / FSRS](https://docs.ankiweb.net/manual/deck-options)

官方手册；记忆率、历史优化、自评与工作量。

### S38

[Anki Desktop：LICENSE](https://github.com/ankitects/anki/blob/29bb700b951e3f0c0cb69b77c0180fc1fe33e6ba/LICENSE)

26.09.3 固定源码；AGPLv3+ 与第三方例外。

### S39

[fsrs-rs：实际 6.6.2 上游许可](https://github.com/open-spaced-repetition/fsrs-rs/blob/6088949b99d44f46f5328fd7289d209b9a842b68/LICENSE)

BSD-3-Clause；版本由 Anki 固定提交的 Cargo.lock 核对。

### S40

[Moodle 5.3：AI usage report](https://docs.moodle.org/503/en/AI_usage_report)

课程摘要、本人 prompt/生成内容和角色范围。

### S41

[Moodle 5.3：Learning plans](https://docs.moodle.org/503/en/Learning_plans)

能力证据、计划与复核。

### S42

[H5P：xAPI](https://h5p.org/documentation/x-api)

事件与宿主接收/LRS 边界；不声称覆盖所有内容类型。

### S43

[H5P：Licensing](https://h5p.org/licensing)

官方许可说明；具体组件存在差异，未替代当前全依赖审计。

### S44

[PhET：当前许可](https://phet.colorado.edu/en/licensing/)

普通 HTML 模拟的 NC 条件、商用与 PhET-iO 区分。

### S45

[PhET：Offline access](https://phet.colorado.edu/en/offline-access)

离线模拟与客户端；不推出学习档案能力。

### S46

[Exercism：Track tooling](https://exercism.org/docs/building/tracks/new/implement-tooling)

Test Runner、Analyzer 与 Representer 分工。

### S47

[Khan Academy：近期 AI Tutor 产品实验](https://blog.khanacademy.org/how-khan-academy-is-building-a-better-ai-tutor-our-most-recent-learnings/)

官方在线实验说明；不等同独立长期效果研究。

### S48

[Brilliant：Koji 工作方式](https://brilliant.org/help/features/how-does-koji-work/)

2026-10-07 帮助；共享交互状态与提示。

### S49

[Brilliant：家长进度面板](https://brilliant.org/help/features/parent-progress-dashboards-on-brilliant/)

2026-10-07；活动、评估与求助分离，不显示聊天原文。

### S50

[Duolingo：AI 与 Video Call](https://blog.duolingo.com/ai-and-video-call/)

官方机制文章；会话结构与用户事实记忆。

### S51

[Duolingo Video Call，DRR-25-06](https://duolingo-papers.s3.amazonaws.com/reports/Duolingo_whitepaper_language_video_call_improves_speaking_2025.pdf)

厂商原始报告；直读 403，方法、结果与限制依据官方 PDF 搜索索引核查。

### S52

[Learn Your Way 效果论文，Frontiers 2026](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2026.1783117/full)

60 人实验；数天后测验与模态归因边界。

### S53

[Claude：Artifacts 核心说明](https://support.claude.com/en/articles/17153992-what-are-artifacts-and-how-do-i-use-them)

当前新旧版本、存储、连接器、导出与模型额度。

### S54

[Claude Design：管理与预览隔离](https://support.claude.com/en/articles/14604406-claude-design-admin-guide-for-team-and-enterprise-plans)

预览 iframe 与访问令牌；不外推所有模板资源限制。

### S55

[StudyFetch：Guided Chat](https://www.studyfetch.com/docs/docs/ai-chat/guided-chat)

已按当前可访问路径更新；计划接受、活动状态与逐步推进。

### S56

[StudyFetch：Spaced Learning Hub](https://sso.studyfetch.com/blog/meet-the-spaced-learning-hub)

官方发布；自评、到期和逐卡历史。

### S57

[StudyFetch：QuizFetch 结果与推荐](https://www.studyfetch.com/docs/docs/quizfetch/quizfetch-results-and-recommendations)

当前可访问路径；完成分数、原错误与逐题统计。

### S58

[StudyFetch：2026-09-28 Changelog](https://www.studyfetch.com/changelog/weekly-2026-09-28)

浏览器通知选择加入、日历和学习提醒分项设置。

### S59

[StudyFetch：消费者隐私](https://www.studyfetch.com/legal/privacy)

2026-08-13；消费与机构条款范围分开。

### S60

[Sana Learn：Changelog](https://sanalabs.com/sana-learn-changelog)

课程内 Tutor、管理员工作流与通知设置；代表性补充，非全产品审计。

### S61

[豆包爱学：隐私政策](https://lf9-cdn-tos.draftstatic.com/obj/ies-hotsoon-draft/turing/7a518dd9-d4bf-45dd-8fbd-8544dcf381cb.html)

2026-08-03；历史讲解、错题、分析、训练与导出请求。

### S62

[豆包桌面版官方入口](https://www.doubao.com/download/desktop?ug_utm_source=225)

动态页面，以官方可检索说明核对截图/划词入口；不推断与爱学统一档案。

### S63

[作业帮智能：隐私政策](https://smart.zuoyebang.com/agreement/privacy.html)

2026-07-31；账号关联、错题/生词回流与硬件配套。

### S64

[有道小P：中国 App Store 开发者页](https://apps.apple.com/cn/app/id6502383883)

只使用开发者描述与版本历史；错题本/学情已发布，更新较旧不等于停服。

### S65

[有道小P：隐私政策](https://c.youdao.com/dict/law/XIAOP_privacy.html)

2025-08-20；成人实名答疑资格与个人信息权利。

### S66

[通义听悟：API 功能规格](https://help.aliyun.com/zh/tingwu/features)

转写、问答回顾、摘要与 PPT 等边界。

### S67

[通义听悟：离线转写 API](https://help.aliyun.com/zh/tingwu/offline-transcribe-of-audio-and-video-files)

音视频输入与结构化结果；离线任务不代表本机离线处理。

### S68

[通义听悟：API 计费](https://help.aliyun.com/zh/tingwu/pricing-and-billing-rules)

按时长与能力叠加；不套用到消费端会员。

### S69

[Bastani 等：Generative AI without guardrails can harm learning](https://www.pnas.org/doi/10.1073/pnas.2422633122)

PNAS 2025；受助表现与独立学习的差异。

### S70

[Kestin 等：AI tutoring outperforms in-class active learning](https://www.nature.com/articles/s41598-025-97652-6)

Scientific Reports 2025；期刊摘要/官方索引，正文获取不完整。

### S71

[Tutor CoPilot：修订工作论文](https://edworkingpapers.com/ai24-1054)

采用 2025-11 修订摘要的样本和结果，不混用较早版本数字。

### S72

[One Click Away：Khanmigo 两年学校实验](https://edworkingpapers.com/sites/default/files/ai26-1551.pdf)

2026 工作论文；完整 PDF，随机单位、ITT 与参与率缩放分别解释。

### S73

[Obsidian：Plugin security](https://obsidian.md/help/plugin-security)

插件权限与 Restricted Mode，不以本地推断沙箱。

### S74

[Obsidian：数据存储](https://obsidian.md/help/data-storage)

官方帮助；本地 Markdown 文件与外部编辑。

### S75

[RemNote：AI Credits](https://help.remnote.com/en/articles/9416169-ai-credits)

补充：额度与输入/输出 token；不是单次实际成本测量。

### S76

[Claude：Share artifacts](https://support.claude.com/en/articles/9547008-share-artifacts)

当前分享、账号、连接权限与新旧版本边界。

### S77

[DeepTutor：共享 assessment](https://github.com/HKUDS/DeepTutor/blob/6cf793bd868ba5ecbe64722936d4be8fab5a01df/deeptutor/learning/assessment.py)

固定源码；attempt identity、原始记录和作废/重放处理。

### S78

[OpenMAIC：PBL learner-state](https://github.com/THU-MAIC/OpenMAIC/blob/a9da60b3b4adb429369c0da13d5637a904ead2b0/lib/pbl/v2/runtime/learner-state.ts)

固定源码；提交、评价、讨论与设计模板分离。

### S79

[Moodle：许可与稳定版本](https://github.com/moodle/moodle/blob/344c92d5bb70f37306829d7739e2710305a39c3e/public/version.php)

固定稳定 SHA；5.3+ Build20261013，GPLv3+。

### S80

[Open Notebook：single-user-first](https://github.com/lfnovo/open-notebook/blob/315d5255af2a5132aada41c94d5c3c5dc8e837aa/docs/7-DEVELOPMENT/decisions/PDR-001-single-user-first.md)

固定源码；单用户产品边界，不将共同密码视为多租户身份系统。

### S81

[Anki：含复习历史的导出实现](https://github.com/ankitects/anki/blob/29bb700b951e3f0c0cb69b77c0180fc1fe33e6ba/rslib/src/import_export/gather.rs)

固定源码；with_scheduling 时 gather_revlog。

### S82

[Moodle：稳定 schema](https://github.com/moodle/moodle/blob/344c92d5bb70f37306829d7739e2710305a39c3e/public/lib/db/install.xml)

固定源码；question attempt/step、能力与 evidence。

### S83

[Duolingo：2026 Q1 官方股东信](https://investors.duolingo.com/static-files/ac220d7c-e313-4049-b309-1095fd24a86f)

Video Call 开始向 Super 扩展；不推断所有账户即时可用。

### S84

[Google Learn Your Way：实验入口](https://learnyourway.withgoogle.com/)

公开示例/候补入口；不作为全面商用证据。

### S85

[作业帮：中国 App Store 开发者页](https://apps.apple.com/cn/app/id803781859)

只使用开发者描述；主 App 与硬件形态区分。

### S86

[DeepTutor：论文 v3](https://arxiv.org/abs/2604.26962v3)

2026-07-09；模拟学生与个性化评估，不外推真实长期效果。

### S87

[Anki：统计与 revlog](https://docs.ankiweb.net/manual/stats)

历史记录、题面可能已改与删除后的统计语义。

### S88

[Duolingo 自我效能研究，Frontiers 2025](https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2025.1499497/full)

385 人前后问卷，无无 AI 对照；与 Video Call 标准化测验分开。

### S89

[Open Notebook：Ask graph](https://github.com/lfnovo/open-notebook/blob/315d5255af2a5132aada41c94d5c3c5dc8e837aa/open_notebook/graphs/ask.py)

固定源码；检索策略、有效分支回答与综合的调用结构。

### S90

[DeepTutor：LICENSE](https://github.com/HKUDS/DeepTutor/blob/6cf793bd868ba5ecbe64722936d4be8fab5a01df/LICENSE)

固定提交 Apache-2.0；不代表全部依赖。

### S91

[OpenMAIC：LICENSE](https://github.com/THU-MAIC/OpenMAIC/blob/a9da60b3b4adb429369c0da13d5637a904ead2b0/LICENSE)

固定 1.2.0 提交 MIT；不套用历史旧版本。

### S92

[Open Notebook：LICENSE](https://github.com/lfnovo/open-notebook/blob/315d5255af2a5132aada41c94d5c3c5dc8e837aa/LICENSE)

固定 v1.15.0 提交 MIT。

### S93

[Anki：Syncing](https://docs.ankiweb.net/manual/syncing)

官方手册；多端、冲突与媒体同步。

### S94

[Moodle：App offline features](https://docs.moodle.org/503/en/Moodle_app_offline_features)

离线活动条件、日志时间与同步限制。

### S95

[Honen：NVIDIA K-12 Sponsored Terms](https://honen.com/nvidia-k12-sponsored-terms)

专用机构条款；学生数据训练限制与合同优先范围。

### S96

[Nautilus：本次后端核查固定提交](https://github.com/WithYouda/nautilus/commit/7b5835527675481a7e43324b20530fabf56a6d66)

固定提交 7b58355；7b5835527675481a7e43324b20530fabf56a6d66；通过 main 分支与完整仓库树确定基线。用户确认本地差异仅在 UI 操作逻辑。

### S97

[Nautilus：教学运行时](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/teaching_runtime.py)

固定提交 7b58355；版本内教学检查点、教学方式、原文校验、完成后采纳与尝试纠正。

### S98

[Nautilus：学习观察与纠正](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/learning_observations.py)

固定提交 7b58355；原答与反馈引用、当前路径上下文、修订、排除与可用状态。

### S99

[Nautilus：帮助请求、输出与展示](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/help_records.py)

固定提交 7b58355；区分请求、实际正文、部分生成和客户端报告的展示。

### S100

[Nautilus：正式提交的帮助条件](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/verification_help.py)

固定提交 7b58355；同题帮助快照；后续展示不改写提交条件；不从记录缺失推断独立。

### S101

[Nautilus：能力状态推导与回访队列](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/state_derivation.py)

固定提交 7b58355；已批准标准、采纳证据、版本有效性、AI-only 部分支持、重算与回访。

### S102

[Nautilus：学习记录回看](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/learning_records.py)

固定提交 7b58355；按提交与评价版本读取原答、评价、帮助展示及关联讨论。

### S103

[Nautilus：已批准标准包加载](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/standards.py)

固定提交 7b58355；默认加载 Python 正则基础标准包；正式标准对象的种子安装与检查。

### S104

[Nautilus：固定题组延迟回访](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/delayed_follow_up.py)

固定提交 7b58355；安排、作答、帮助条件、确定性检查与有界比较；不是通用记忆调度。

### S105

[Nautilus：持续教练会话](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/coach_conversation.py)

固定提交 7b58355；已有聊天运行时、持久化身份/历史、当前状态摘要与有界导航。

### S106

[Nautilus：时钟提醒](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/coach_reminders.py)

固定提交 7b58355；无需 AI 调用；安静时段、时区、每日预算、当前任务有效性与学习中抑制。

### S107

[Nautilus：后台教练](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/background_coach.py)

固定提交 7b58355；事件触发、结构摘要、来源与目标校验、预算/冷却、建议和运行管理。

### S108

[Nautilus：近期安排](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/commitments.py)

固定提交 7b58355；草案、预览、确认、执行变更、反馈与建议生命周期。

### S109

[Nautilus：Obsidian 只读接入](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/obsidian.py)

固定提交 7b58355；只读检索、选择令牌、哈希与连接修订检查、显式捕获；不写回 Vault。

### S110

[Nautilus：现有学习产物请求结构](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/schemas.py)

固定提交 7b58355；LearningArtifactSaveRequest 使用会话、文本、状态版本和幂等键；未定义交互作品契约。

### S111

[Nautilus：教学输出协议](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/teaching_wire.py)

固定提交 7b58355；reply/teaching/token 结构及受控教学元数据；没有交互组件树协议。

### S112

[Nautilus：结构化教学能力范围](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/teaching_capability.py)

固定提交 7b58355；按配置、凭据、协议和模型绑定；未支持/未检查及原生搜索组合的 plain 回退。

### S113

[Nautilus：当前产品路线](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/docs/superpowers/plans/2026-09-27-nautilus-product-roadmap.md)

固定提交 7b58355；10-09 确认 F 整体 UI/UX 主线；复用已交付能力，客户端迁移另按范围落实。

### S114

[Nautilus：学习域 API](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/routers/learning.py)

固定提交 7b58355；任务、会话、产物、验证、记录、回访与重放入口；不将状态重放等同交互作品回放。

### S115

[Nautilus：正式验证](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/verification.py)

固定提交 7b58355；先保存作答再评价；提交与评价版本、受助条件、确认与历史。

### S116

[Nautilus：正则延迟比较标准](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/standards/python_regex_match_followup_v1.approved.json)

固定提交 7b58355；两组各 8 题；建议 259200 秒、最低 86400 秒；明确不证明稳定掌握或迁移。

### S117

[Nautilus：原生独立运行验证说明](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/native/README.md)

固定提交 7b58355；0.4.0 Windows/Android 本机保存与局域网同步；完整学习域、其他平台与导出边界。

### S118

[Nautilus：生成式交互学习专项](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/docs/superpowers/plans/2026-10-10-nautilus-generative-learning-ui.md)

固定提交 7b58355；方向已认可；范围、排期、选型未批准；P0 隔离、P1 Softmax 候选与现有证据复用。

### S119

[Nautilus：服务端对话选择状态 API](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/routers/conversation_state.py)

固定提交 7b58355；读取、更新与期望修订校验；支持明确恢复当前选择，非完整云同步。

### S120

[Nautilus：学习域产物命令](https://github.com/WithYouda/nautilus/blob/7b5835527675481a7e43324b20530fabf56a6d66/backend/app/core/commands.py)

固定提交 7b58355；SaveTextArtifact、验证产物与修正命令；状态版本不等于交互作品 schema 版本。
