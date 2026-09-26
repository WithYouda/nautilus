# Nautilus 联网搜索接入

2026-09-26：作者授权选择服务，要求参考 RikkaHub 完整覆盖搜索类型及各服务设置。此规格替代 FOLLOWUP-SEARCH-001 先选单一供应商的临时范围；实现和验证事实见[开发状态](../../progress/nautilus-development-status.md)。

## 参考与范围

参考 [RikkaHub 固定版本](https://github.com/rikkahub/rikkahub/tree/8b696c0cfc301754689c0bb04e965fe60af6277c) 的 SearchService、设置页、SearchPicker、SearchTools，以及 ChatMessageCot / ChainOfThought / ChatMessageReasoning / ChatMessageTools。该项目为 AGPL-3.0；本项目独立实现 Python/React 适配与界面，使用公开协议与功能事实，不移植 Kotlin 代码、原提示词或 Android 运行时。

普通学习室及题目讨论支持关闭、外部搜索服务、模型内置搜索。新进入会话默认关闭，启用后按当前选择发送；自动学习提示、标题生成、验证出题/评分不因此自动联网。09-26按作者纠正：搜索按钮融入输入框工具栏，点击打开桌面浮层/手机底部面板；选择后自动收起，点击外部、再点图标、关闭按钮或Esc均可关闭。普通对话不再放置手动查询输入框；高级筛选保留在面板内折叠区。启用仅授予工具，AI结合完整对话先判断是否需要搜索、解析追问指代并生成关键词，不先自动搜索整条消息；不自动把历史对话、原验证材料或整份学习记录发送给新搜索服务。原生搜索由当前模型厂商在既有对话请求中执行。

全局可设置结果数量（默认10，1–50）、单次外部请求超时（默认30秒，5–120）、每轮外部检索次数（默认3，1–5）。支持同类型多个实例、命名、修改、删除、排序、稳定ID选择、能力标识、未保存配置的查询测试和网页读取测试。高级工具参数也在界面中提供，不能只有后端支持。

## 思考、工具与回答的呈现（09-26再次纠正）

普通学习室与题目讨论共用按原始事件顺序渲染的回答组件。相邻思考/工具组成步骤组，正文保留在其实际位置；移除回答下方固定的搜索响应卡片。超过两步时默认只显示最近两步，其余可展开；思考流式预览有高度限制，完成后折叠。搜索步骤显示实际搜索词、服务、来源数量和域名，点击可看查询、日期、摘要与原始URL；Google要求的搜索建议继续单独安全展示。

每段思考显示服务端实际观测的流式耗时：从该段开始到正文/工具边界，使用单调时钟，工具等待时间另计；这不是模型内部GPU耗时。客户端只在运行时补计显示，完成、取消、失败、刷新或重启后使用保存值，不能把停机时间算进思考。旧记录没有的阶段边界或时间不补造；无显式思考的模型只显示实际工具/正文。

## 外部服务覆盖

API密钥均按实例配置；多个密钥可按逗号或换行分隔，在运行开始时轮换选一个。失败不换密钥重试、不跨服务降级。下表“网页读取”为该服务自身的内容接口。

| 服务 | 实例设置 | 额外工具参数 | 网页读取 |
| --- | --- | --- | --- |
| Bing | 无需密钥，公开搜索页面；首选语言（默认zh-CN，可留空） | 无 | 否 |
| RikkaHub | 服务账户API密钥、standard/deep深度 | 无 | 否 |
| 智谱 | API密钥 | 无 | 否 |
| 豆包 | API密钥、custom/global模式 | 无 | 否 |
| Tavily | API密钥、basic/advanced深度 | topic：general/news/finance | 是 |
| Exa | API密钥 | fast/auto/deep、起止发布日期、包含/排除域名、maxAgeHours（-1–720）；读取也支持maxAgeHours | 是 |
| SearXNG | 实例地址、engines、language、用户名、密码 | 无 | 否 |
| LinkUp | API密钥、standard/deep深度 | 无 | 是 |
| Brave | API密钥 | 无 | 否 |
| 秘塔 | API密钥 | 无 | 否 |
| Ollama | ollama.com云端API密钥 | 无；不是本地daemon搜索 | 是 |
| Perplexity | API密钥、可留空的max_tokens和max_tokens_per_page | 无 | 否 |
| Firecrawl | API密钥 | sources：web/news；categories：github/research；读取onlyMainContent | 是 |
| Jina | API密钥、搜索URL、阅读URL | 无 | 是 |
| 博查 | API密钥、summary开关 | 无 | 否 |
| Grok | API密钥、模型、Responses URL、系统提示词 | 使用web_search与x_search | 否 |
| Tinyfish | API密钥 | 无 | 是 |
| Serper | API密钥 | 无 | 否 |
| Custom JS | 名称、搜索脚本、可选网页读取脚本 | search(query,maxResults)、scrape(urls)、fetch | 配置读取脚本后可用 |

各服务API自己的数量、套餐和地区限制仍有效；“结果数量”是返回上限，不保证取得同样多的结果。Bing依赖公开HTML结构，不是已停用的传统Bing Search API。RikkaHub与Ollama服务需要各自云端账户，不能因为软件开源或本机已有Ollama就视为免密钥服务。

09-26进一步核查：作者确认RikkaHub在另一网络正常，切到与Nautilus相同网络后也出现偏日文/不相关结果；不是只有Nautilus出现该现象。相同WSL的Chromium测试又能取得相关资料，Python请求的结果也有变化，因此目前只确认结果受网络/客户端条件影响，尚未定位到具体出口、代理、DNS或服务端策略。不能把收到HTTP响应/解析出链接当作检索质量验收，也不能据此认定必须改用付费API。保留Bing与既有服务选择，首选语言只是请求偏好。

Bing公开网页请求对齐RikkaHub的必要重定向行为：只在已知Bing HTTPS域名间最多跟随3次跳转，单次链内保存Cookie，整条链共享超时与2MiB响应限制；其他携带密钥的搜索服务仍不跟随重定向。超时、连接失败、HTTP 403/429及跳转异常分别提示，不暴露响应正文或凭据。搜索设置新增实例在HTTP局域网地址下也须可用：UUID缺少randomUUID接口时以getRandomValues生成，不依赖localhost的安全上下文例外。


Custom JS默认空，不把虚构示例当成搜索成功。脚本用独立QuickJS子进程执行，64MB JS堆、256KB栈，具有墙钟/CPU限制；不提供文件、进程、环境变量访问。fetch只允许有界公开HTTP(S)，DNS校验并固定解析地址，禁止私网、重定向和环境代理。进程退出或取消时回收。服务端自定义接口由已认证用户明确配置，凭据只发往该接口；非本机接口要求HTTPS。

## 模型原生搜索

| 配置协议 | 实际工具 | 状态来源 |
| --- | --- | --- |
| OpenAI Responses | web_search | 实际web_search_call完成事件及URL引用 |
| Google Gemini | googleSearch | groundingMetadata中的查询、来源及搜索建议 |
| Anthropic Messages | web_search_20250305 | 实际web_search_tool_result及引用 |

旧OpenAI Chat Completions兼容协议保持可用，但不伪称具备原生搜索；可配外部搜索。协议选择本身不保证每个模型/中转站/账户都支持工具。原生工具由厂商决定是否调用，未调用记录not_used；仅返回文字或URL不能冒充执行成功。Google返回的搜索建议在无脚本、无同源权限的隔离iframe展示。协议依据：[OpenAI](https://developers.openai.com/api/docs/guides/tools-web-search)、[Google](https://ai.google.dev/api/generate-content)、[Google来源与搜索建议](https://ai.google.dev/gemini-api/docs/google-search)、[Anthropic](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)。

## 执行与保存

1. 发送前冻结本轮服务、参数及所选密钥。设置修改、排序或删除不影响已经开始的运行；失效选择不得静默退回Bing。
2. 外部服务以真实`search_web`和按能力开放的`scrape_web`函数工具提供给当前模型。先调用模型，只有收到完整工具调用才执行；结果按调用ID回填，模型可直接回答、改写关键词或读取已有结果/用户给定URL。Chat Completions（含DeepSeek）、Responses、Gemini、Anthropic分别保持原生工具结果和思考/签名；不用JSON决策模拟工具，不混用厂商内置搜索。无调用标记`not_used`；用户设置的筛选优先于模型参数。未知/重复/无效参数不会出站且占用有界尝试次数，超额调用收到工具错误，耗尽后禁用工具完成回答；截断或无法解析的协议响应失败，不执行残缺调用。模型不能选择服务、密钥或扩大权限。资料始终按不可信内容处理，并要求评估相关性、优先一手来源、区分发布日期和检索时间。
3. 每版回答单独保存搜索模式、实际查询、请求过程、来源URL/摘要、检索时间、执行结果。检索时间与发布日期分开，搜索成功不构成用户掌握证据。关闭时不执行外部检索；调用失败把工具错误交回模型，允许生成说明受限的回答，不虚构来源。
4. 搜索配置复用按owner隔离的加密CredentialStore，读回密钥仅有掩码；不进入SQLite、localStorage或错误正文。高级参数按服务目录校验。配置revision防止旧页面覆盖新设置。
5. API协议复用provider_model.overrides_json；搜索来源、generation_trace与私有model_turn复用ai_run.config_snapshot_json、题目讨论provider_snapshot_json，无数据库结构变更。generation_trace按顺序保存思考/工具/正文、单调时钟耗时及终态，SSE process与快照提供同一视图。model_turn仅存本轮生成的原生assistant/tool结果与最终输出，保留DeepSeek reasoning_content（含空字段）、Responses加密reasoning、Google/Anthropic签名，供后续外部工具请求续接；不把它作为公开运行字段返回。只回放当前选中版本路径及相同协议/端点/模型的完整轮次，最近优先且总回放预算256KiB，超额整轮回退文本，不拆断tool/result配对；不是完整token压缩器。历史回答切换保留各版来源/过程；取消和清除拒绝迟到写回，讨论快照随现有清除边界删除。
6. 原生搜索的内部请求数与收费由厂商控制；外部次数上限不是金额预算。Custom JS每次执行另有fetch次数限制。账户、付费套餐和真实使用费用由用户配置承担，本次不购买、不使用现有私密学习内容作供应商验收。

函数工具协议依据：[OpenAI函数调用](https://developers.openai.com/api/docs/guides/function-calling)、[DeepSeek工具调用](https://api-docs.deepseek.com/guides/tool_calls/)、[DeepSeek思考模式续轮](https://api-docs.deepseek.com/guides/thinking_mode/)、[Gemini函数调用](https://ai.google.dev/gemini-api/docs/function-calling)、[Anthropic工具调用](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)。

成熟Agent运行方式对照：[Codex agent loop](https://openai.com/index/unrolling-the-codex-agent-loop/)与[Claude Code工作原理](https://code.claude.com/docs/en/how-claude-code-works)都把工具结果回到模型上下文，持续观察后续行动。本轮据此修补协议续接与过程可观察性；DeepSeek依据其当前公开API文档，不声称读取闭源网页或厂商内部harness。未引入通用shell、文件执行、多Agent产品运行时或全站改版。

## 验收边界

设置目录、请求协议、脚本限制、错误脱敏、来源持久化、版本/取消/清除和浏览器路径用隔离合成数据验证；公开Bing用无私文查询做实际出站检查。当前DeepSeek已使用合成问题实测函数调用与公开Bing搜索，覆盖直接回答和自主补查；其他付费搜索服务及三家原生协议使用Mock验证，待实际账户逐个验收；不能把适配覆盖称为19家真实调用均已通过。

本次不实现远程手机接入、通用附件、外部成绩导入、完整彻底删除、后台自主浏览或完整Research Agent；这些事项保持各自已确认的后续任务。
