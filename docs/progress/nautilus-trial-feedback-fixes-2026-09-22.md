# 2026-09-22 作者试用反馈修复

用户反馈入口混乱、联网能力不明、数学公式未渲染、AI 出题失败；并确认使用 DeepSeek 官方 API。这是实际使用的定性反馈，不是已经核验过的结构化 Task 13B 基线。未读取试用原文、Provider 配置或凭据，不能从旧的通用错误反推出那一次请求的唯一根因。

## 改动与边界

- 开始学习默认只显示返回卡或目标输入，移除并列的“旧计划管理入口 / 我想从学习目标开始”及重复“按计划开始”。已有历史任务时显示次要链接；原计划页标为历史计划，说明新学习在开始学习中继续。目标、当前任务、停止条件仍分开；未做旧新领域同步、迁移或数据删除。
- 学习室、验证题目和评估反馈共用 `LearningMarkdown`，支持美元与 LaTeX 括号分隔符；代码保持原样。KaTeX 的渲染器与样式使用相同版本，关闭可信 HTML 指令，长公式局部滚动。修复验证反馈原有全局 span 样式对公式的干扰、窄屏验证按钮缺少可访问名称。
- 出题和评估启用 JSON 输出模式，提供合法类型示例及转义说明，输出预算由 1800/1000 调至 8192，区分最终文本和推理前缀，识别输出截断、拒绝及仅推理响应。上限提高不能保证每次成功；不自动重试收费请求、不把残缺 JSON 补成通过结果。
- 验证沿用同一委托学习室已选择的对话 Provider/模型及超时设置；显式配置失效时不偷偷回退默认。无学习室关联时仍使用默认配置。生成/评估增加总超时，返回固定安全错误分类，不向页面转发上游错误正文、答案或隐藏推理。评估失败保留作答并允许重试。
- 联网能力纠正：当前 Chat Completions 调用没有真正的搜索工具。提示词与设置说明明确该限制，不允许声称已搜索/核验网页。DeepSeek 官方 API 的 Function Calling 不等于附带搜索执行器；尚未新增搜索服务，也没有取得用户对某个新增服务/费用的选择。

官方核对来源：

- [DeepSeek JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)：需要显式 response_format、JSON 指令与足够输出预算。
- [DeepSeek Responses 接口](https://api-docs.deepseek.com/api/create-response/)：tools 中内置工具类型被忽略，Function Calling 需应用提供工具。
- [OpenAI 搜索工具](https://developers.openai.com/api/docs/guides/tools-web-search)：需要显式接口集成，不能由提示词冒充。

## 文件与迁移

本轮未新增迁移，未修改旧迁移，未升级或读取 `data/`。试用环境只进行服务重启，不运行测试、不重建、不清空数据。所有自动化使用临时合成库和 Mock Provider。

- 后端：`providers.py`、`verification.py`、`routers/learning.py`、`conversations.py`。
- 前端：`FactWorkspace.tsx`、`Workspace.tsx`、`PlanWorkspace.tsx`、`AiLearningRoom.tsx`、`LearningVerification.tsx`、`AiProviderDialog.tsx`、`api.ts`、`styles/fact-workspace.css`；新增 `LearningMarkdown.tsx`；`package.json`/lock 增加 remark-math、rehype-katex、KaTeX。
- 测试：新增 `test_verification_provider_contract.py`、`learning-feedback.spec.ts`；调整 `test_learning_verifications.py`、`ai-learning.spec.ts`、`direct-learning.spec.ts`、`plan-workspace.spec.ts`；扩展合成 Mock Provider。
- 治理：本记录、PRD 顶部澄清、产品决策记录、开发状态。

## 验证

最终命令与结果见开发状态顶部；中间过程：后端全量 353 passed（随后补充保护 JSON 内字面 think 标签的定向回归），第一轮相关浏览器 20 passed。新增移动端旅程第一次因测试直接写入配置后未刷新客户端而失败，修复测试初始化后通过；该失败不是公式渲染结论。后续视觉检查还修复了 KaTeX 依赖版本不一致与反馈 span 样式问题。

没有调用真实 DeepSeek API、没有读取真实错误响应；实际那一次出题失败的原因尚待用户复试后的安全错误分类确认。未完成全套前端自动化、真实手机键盘验收、联网服务集成、真实结构化使用基线。

唯一下一项：作者在现有试用环境复试 DeepSeek 出题与完成返回，反馈是否成功或新的安全错误类别。搜索服务选择继续待决，不自动进入通用 Research Agent 或工具平台。


## 同日补修：恢复已有验证后仍可选择方式

- 用户报告进入验证只剩提交材料。代码原因是方式选择位于 `!verification` 分支，自动恢复已有未提交尝试后整个选择区被隐藏；无需读取真实数据库即可确认。
- 将方式选择放在未完成验证的常驻区域。按当前行动/委托/会话恢复两种方式各自的已有尝试，切换不删除已保存提交；未提交草稿仅在当前页面内按尝试保留，不写入浏览器持久存储。彻底删除会清理对应内存草稿；确认完成规则没有变化。
- 修改 `frontend/src/LearningVerification.tsx` 与 `frontend/e2e/learning-feedback.spec.ts`，同步实施计划、决策与开发状态；本次无后端或迁移改动。
- 命令：`npm --prefix frontend run build` 通过（既有包体提示）；frontend 中 `./node_modules/.bin/playwright test e2e/learning-feedback.spec.ts` 为 1 passed，`./node_modules/.bin/playwright test e2e/learning-continuity.spec.ts` 为 2 passed；`git diff --check` 通过。测试使用隔离合成库及 Mock，覆盖刷新后选择、失败后切回、草稿与已保存记录保留，以及完成/中断返回。没有重跑后端和全套前端，没有验证真实 DeepSeek。
- 新构建已由既有试用预览提供；HTTP 页面与健康接口正常。没有读取或变更试用正文、凭据、数据库，没有清理数据。
- 用户要求的额外搜索配置已正式进入 `FOLLOWUP-SEARCH-001`，未实现、未开通。下一项为用户刷新页面复试验证方式切换及 DeepSeek 出题；搜索供应商、预算、出站范围在后续实施前确定。


## 同日补修：AI 答题界面无法上下滚动

- 根因：外层学习室使用固定高度 grid 与 overflow:hidden，验证包装 div 没有可用高度内的滚动区域。新增 `.verification-scroll` 的 min-height:0、min-width:0 与纵向 overflow:auto，仍通过 hidden 保留教学/验证之间的页内草稿。
- 改动：`AiLearningRoom.tsx`、`styles/fact-workspace.css`、`e2e/learning-feedback.spec.ts` 与开发状态/本记录。无后端、迁移、真实数据读取或变更。
- 回归：旧构建中实际滚轮滚动失败，scrollTop 一直为 0；中途两次测试因未重建仍使用旧 dist，不算修复后结果。`npm --prefix frontend run build` 成功（既有包大小提示）后，frontend 中 `./node_modules/.bin/playwright test e2e/learning-feedback.spec.ts` 为 1 passed。新增 390×844、1024×640、1440×1000 滚到底部提交按钮并返回顶部，以及 390px Chromium touchStart/touchMove 滑动检查；不再依赖 Playwright 点击时自动滚入视野。`git diff --check` 通过。
- 未重跑后端和全部前端套件；触摸模拟不代表真机软键盘验收，未调用真实 DeepSeek。现有试用预览已提供新 JS/CSS，页面和健康接口正常，无需重启后端。
- 唯一下一项：作者保留当前未提交答案后刷新页面，复试 AI 答题页滚动与提交。搜索待办 FOLLOWUP-SEARCH-001 未丢弃、未在本轮实现。
