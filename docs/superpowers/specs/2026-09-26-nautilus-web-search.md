# Nautilus 联网搜索接入

2026-09-26：作者授权选择服务，要求参考 RikkaHub 完整覆盖搜索类型及各服务设置。此规格替代 FOLLOWUP-SEARCH-001 先选单一供应商的临时范围；实现和验证事实见[开发状态](../../progress/nautilus-development-status.md)。

## 参考与范围

参考 [RikkaHub 固定版本](https://github.com/rikkahub/rikkahub/tree/8b696c0cfc301754689c0bb04e965fe60af6277c) 的 SearchService、设置页、SearchPicker 与 SearchTools。该项目为 AGPL-3.0；本项目独立实现 Python/React 适配与界面，使用公开协议与功能事实，不移植 Kotlin 代码、原提示词或 Android 运行时。

普通学习室及题目讨论支持关闭、外部搜索服务、模型内置搜索。新进入会话默认关闭，启用后按当前选择发送；自动学习提示、标题生成、验证出题/评分不因此自动联网。外部搜索显示可编辑查询，留空使用当前问题；不自动把历史对话、原验证材料或整份学习记录发送给新搜索服务。原生搜索由当前模型厂商在既有对话请求中执行。

全局可设置结果数量（默认10，1–50）、单次外部请求超时（默认30秒，5–120）、每轮外部检索次数（默认3，1–5）。支持同类型多个实例、命名、修改、删除、排序、稳定ID选择、能力标识、未保存配置的查询测试和网页读取测试。高级工具参数也在界面中提供，不能只有后端支持。

## 外部服务覆盖

API密钥均按实例配置；多个密钥可按逗号或换行分隔，在运行开始时轮换选一个。失败不换密钥重试、不跨服务降级。下表“网页读取”为该服务自身的内容接口。

| 服务 | 实例设置 | 额外工具参数 | 网页读取 |
| --- | --- | --- | --- |
| Bing | 无需密钥，公开搜索页面 | 无 | 否 |
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
2. 外部搜索执行用户可见的首个查询，当前聊天模型可在预算内请求补充关键词或读取已有结果URL；不能由模型选择服务、密钥、扩大权限或直接提交任意工具。资料始终按不可信内容处理。
3. 每版回答单独保存搜索模式、实际查询、请求过程、来源URL/摘要、检索时间、执行结果。检索时间与发布日期分开，搜索成功不构成用户掌握证据。关闭时不执行外部检索；首个检索失败仍允许生成说明受限的回答，不虚构来源。
4. 搜索配置复用按owner隔离的加密CredentialStore，读回密钥仅有掩码；不进入SQLite、localStorage或错误正文。高级参数按服务目录校验。配置revision防止旧页面覆盖新设置。
5. API协议复用provider_model.overrides_json；运行轨迹复用ai_run.config_snapshot_json、题目讨论provider_snapshot_json，无数据库结构变更。历史回答切换保留各版来源，取消不允许迟到结果写回；讨论清除仍沿原级联屏障清空快照。
6. 原生搜索的内部请求数与收费由厂商控制；外部次数上限不是金额预算。Custom JS每次执行另有fetch次数限制。账户、付费套餐和真实使用费用由用户配置承担，本次不购买、不使用现有私密学习内容作供应商验收。

## 验收边界

设置目录、请求协议、脚本限制、错误脱敏、来源持久化、版本/取消/清除和浏览器路径用隔离合成数据验证；公开Bing用无私文查询做实际出站检查。付费服务及三家原生协议使用Mock验证，待用户配置账户后逐个完成真实账户验收；不能把适配覆盖称为19家真实调用均已通过。

本次不实现远程手机接入、通用附件、外部成绩导入、完整彻底删除、后台自主浏览或完整Research Agent；这些事项保持各自已确认的后续任务。
