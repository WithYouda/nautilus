"""面向设置界面的搜索服务目录；此处不保存凭据。"""
from __future__ import annotations


def field(key, label, type="text", default="", **extra):
    return {"key": key, "label": label, "type": type, "default": default, **extra}


def choice(key, label, default, values):
    return field(key, label, "select", default, options=[{"value": v, "label": n} for v, n in values])


def entry(kind, label, homepage, description, scrape=False, fields=(), search_extra=None, scrape_extra=None):
    search_schema = {"type": "object", "properties": {"query": {"type": "string", "title": "搜索词", "description": "输入要查找的主题或问题。"}, **(search_extra or {})}, "required": ["query"]}
    scrape_schema = {"type": "object", "properties": {"url": {"type": "string", "title": "网页地址", "description": "输入要读取的公开网页地址。"}, **(scrape_extra or {})}, "required": ["url"]} if scrape else None
    return {"kind": kind, "label": label, "homepage": homepage, "description": description,
            "supports_scrape": scrape, "fields": list(fields), "search_parameters": search_schema,
            "scrape_parameters": scrape_schema}


KEY = lambda: field("api_key", "API 密钥", "secret", "", required=True)
DEPTH_LABELS = {"basic": "基础", "advanced": "深入", "standard": "标准", "deep": "深入"}
DEPTH = lambda default, values: choice("depth", "搜索深度", default, [(v, DEPTH_LABELS[v]) for v in values])
AGE = {"type": "integer", "title": "内容缓存时效（小时）", "description": "可选；-1 表示由服务决定，最多 720 小时。", "minimum": -1, "maximum": 720}

SEARCH_CATALOG: list[dict] = [
    entry("bing", "Bing", "https://www.bing.com/", "通过 Bing 公开搜索页面获取结果，不使用官方搜索 API；地区、反机器人策略及页面结构变化可能影响结果。", fields=[field("language", "首选语言", default="zh-CN", description="例如 zh-CN、en-US、ja-JP；表示语言偏好，不保证所有结果使用该语言。")]),
    entry("rikkahub", "RikkaHub", "https://rikka-ai.com/", "通过 RikkaHub 服务获取带来源的回答。", fields=[KEY(), DEPTH("standard", ["standard", "deep"])]),
    entry("zhipu", "智谱", "https://bigmodel.cn/", "通过智谱接口搜索网页。", fields=[KEY()]),
    entry("doubao", "豆包", "https://www.volcengine.com/", "通过豆包搜索接口获取网页结果。", fields=[KEY(), choice("mode", "搜索模式", "custom", [("custom", "定制搜索"), ("global", "全网搜索")])]),
    entry("tavily", "Tavily", "https://tavily.com/", "搜索网页、获取回答并提取网页正文。", True, [KEY(), DEPTH("advanced", ["basic", "advanced"])],
          {"topic": {"type": "string", "title": "搜索主题", "description": "可选：通用、新闻或财经。", "enum": ["general", "news", "finance"]}}),
    entry("exa", "Exa", "https://exa.ai/", "搜索网页，可限制日期、域名和内容缓存时效。", True, [KEY()],
          {"type": {"type": "string", "title": "搜索类型", "description": "快速、自动或深入；默认自动。", "enum": ["fast", "auto", "deep"]},
           "startPublishedDate": {"type": "string", "title": "最早发布日期", "description": "可选，ISO 8601 日期或时间；只查此时间之后发布的内容。"},
           "endPublishedDate": {"type": "string", "title": "最晚发布日期", "description": "可选，ISO 8601 日期或时间；只查此时间之前发布的内容。"},
           "includeDomains": {"type": "array", "title": "包含的域名", "description": "可选，只搜索这些域名。", "items": {"type": "string"}},
           "excludeDomains": {"type": "array", "title": "排除的域名", "description": "可选，不搜索这些域名。", "items": {"type": "string"}},
           "maxAgeHours": AGE}, {"maxAgeHours": AGE}),
    entry("searxng", "SearXNG", "https://docs.searxng.org/", "使用你配置的 SearXNG 实例搜索。", fields=[field("url", "实例地址", required=True), field("engines", "搜索引擎", description="多个引擎按实例要求填写。"), field("language", "语言"), field("username", "用户名"), field("password", "密码", "secret")]),
    entry("linkup", "LinkUp", "https://www.linkup.so/", "获取带来源的回答，并可读取网页。", True, [KEY(), DEPTH("standard", ["standard", "deep"])]),
    entry("brave", "Brave", "https://api.search.brave.com/", "通过 Brave Search 接口搜索网页。", fields=[KEY()]),
    entry("metaso", "秘塔", "https://metaso.cn/", "通过秘塔接口搜索网页。", fields=[KEY()]),
    entry("ollama", "Ollama", "https://ollama.com/", "使用 Ollama 云端搜索与网页读取接口，需要云端 API 密钥。", True, [KEY()]),
    entry("perplexity", "Perplexity", "https://www.perplexity.ai/", "搜索网页，可限制返回内容的 token 数。", fields=[KEY(), field("max_tokens", "最大 token 数", "number", None, min=1), field("max_tokens_per_page", "每页最大 token 数", "number", None, min=1)]),
    entry("firecrawl", "Firecrawl", "https://www.firecrawl.dev/", "搜索网页并提取网页正文。", True, [KEY()],
          {"sources": {"type": "array", "title": "搜索来源", "description": "可选：网页或新闻；默认网页。", "items": {"type": "string", "enum": ["web", "news"]}},
           "categories": {"type": "array", "title": "搜索分类", "description": "可选：GitHub 或研究资料；留空不按分类过滤。", "items": {"type": "string", "enum": ["github", "research"]}}},
          {"onlyMainContent": {"type": "boolean", "title": "只读取主要内容", "description": "默认开启；关闭后服务可能返回导航等附加内容。"}}),
    entry("jina", "Jina", "https://jina.ai/", "通过 Jina 搜索与阅读接口获取网页内容。", True, [KEY(), field("search_url", "搜索接口地址", default="https://s.jina.ai/"), field("scrape_url", "阅读接口地址", default="https://r.jina.ai/")]),
    entry("bocha", "博查", "https://open.bochaai.com/", "搜索网页，可选择生成结果摘要。", fields=[KEY(), field("summary", "返回摘要", "boolean", True)]),
    entry("grok", "Grok", "https://x.ai/", "通过 xAI Responses 接口获取带引用的搜索回答。", fields=[KEY(), field("model", "模型", default="grok-4-1-fast-non-reasoning"), field("custom_url", "Responses 接口地址", default="https://api.x.ai/v1/responses"), field("system_prompt", "系统提示词", "textarea", "查找可靠的近期资料，给出有来源的回答。")]),
    entry("tinyfish", "Tinyfish", "https://www.tinyfish.ai/", "搜索网页并读取网页内容。", True, [KEY()]),
    entry("serper", "Serper", "https://serper.dev/", "通过 Serper 获取 Google 搜索结果。", fields=[KEY()]),
    entry("custom_js", "Custom JS", "", "自行编写搜索脚本：async search(query, maxResults) 返回含 items 的对象；可选 async scrape(urls) 返回含 urls 的对象。可使用 fetch 请求已配置的真实服务。脚本默认留空，填写并通过测试后才能搜索。", True,
          [field("name", "名称"),
           field("search_script", "搜索脚本", "textarea", description="实现 async search(query, maxResults)，返回 {items:[{title,url,text}]}。将示例中的报错替换为真实搜索请求与解析逻辑。", example="async function search(query, maxResults) {\n  throw new Error('请先接入真实搜索服务');\n}"),
           field("scrape_script", "网页读取脚本", "textarea", description="可选。实现 async scrape(urls)，返回 {urls:[{url,content}]}；fetch(url) 可请求公开网页。", example="async function scrape(urls) {\n  throw new Error('请先实现网页读取');\n}")]),
]

# 自定义脚本一次可以接收多个网页地址；其他服务按单页读取。
SEARCH_CATALOG[-1]["scrape_parameters"] = {
    "type": "object",
    "properties": {"urls": {"type": "array", "title": "网页地址", "description": "要读取的公开网页地址列表。", "items": {"type": "string"}}},
    "required": ["urls"],
}
