"""Small, isolated HTTP adapters for configured search services.

This module never chooses another service when the requested one fails.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from datetime import datetime, timezone
from html.parser import HTMLParser
import ipaddress
import json
import re
import socket
from urllib.parse import parse_qs, urlsplit

import httpx

from app.search_catalog import SEARCH_CATALOG

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
KINDS = {item["kind"]: item for item in SEARCH_CATALOG}


class SearchError(Exception):
    def __init__(self, message: str, kind: str = "search_error"):
        self.kind = kind
        super().__init__(message)


def _stamp():
    return datetime.now(timezone.utc).isoformat()


def _size(common):
    try:
        value = int(common.get("result_size", 10))
    except (TypeError, ValueError):
        raise SearchError("结果数量格式不正确。", "invalid_config") from None
    if not 1 <= value <= 50:
        raise SearchError("结果数量须为 1 至 50。", "invalid_config")
    return value


def _timeout(common):
    try:
        value = float(common.get("timeout_seconds", 30))
    except (TypeError, ValueError):
        raise SearchError("超时时间格式不正确。", "invalid_config") from None
    if not 0 < value <= 120:
        raise SearchError("超时时间须大于 0 且不超过 120 秒。", "invalid_config")
    return value


def _url(value, *, endpoint=False):
    if not isinstance(value, str) or not value or len(value) > 2048 or any(ord(c) < 33 for c in value):
        raise SearchError("地址格式不正确。", "invalid_url")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
    except ValueError:
        raise SearchError("地址格式不正确。", "invalid_url") from None
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password or port == 0:
        raise SearchError("地址格式不正确。", "invalid_url")
    loopback = host == "localhost" or host.endswith(".localhost")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None:
        loopback = addr.is_loopback
    if endpoint:
        if parsed.scheme != "https" and not loopback:
            raise SearchError("服务地址须使用 HTTPS；本机地址可使用 HTTP。", "invalid_url")
    elif parsed.scheme not in {"http", "https"} or loopback or host.endswith((".local", ".internal")) or (addr is not None and not addr.is_global):
        raise SearchError("网页地址须指向公开网络。", "invalid_url")
    return value


async def _public_page(value, *, resolve=True):
    value = _url(value)
    host = urlsplit(value).hostname
    try:
        ipaddress.ip_address(host)
        return value
    except ValueError:
        pass
    if resolve:
        try:
            addresses = await asyncio.wait_for(asyncio.to_thread(socket.getaddrinfo, host, None), 3)
        except (OSError, asyncio.TimeoutError):
            raise SearchError("无法核查网页地址。", "invalid_url") from None
        if not addresses or any(not ipaddress.ip_address(info[4][0]).is_global for info in addresses):
            raise SearchError("网页地址须指向公开网络。", "invalid_url")
    return value


def _key(options):
    key = options.get("api_key")
    if not isinstance(key, str) or not key.strip():
        raise SearchError("请先配置 API 密钥。", "unconfigured")
    return key


def _configured_endpoint(value, default):
    return _url(value or default, endpoint=True)


async def _request(method, url, *, common, transport=None, headers=None, body=None, params=None, before_request=None):
    timeout = _timeout(common)
    approval_error = None
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=False, trust_env=False) as client:
            request = client.build_request(method, url, headers=headers, json=body, params=params)
            if before_request is not None:
                try:
                    await before_request(request)
                except Exception as error:
                    approval_error = error
                    raise
            response = await client.send(request, stream=True)
            try:
                if response.status_code < 200 or response.status_code >= 300:
                    raise SearchError("搜索服务请求失败。", "service_failure")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise SearchError("搜索服务返回的数据超过大小限制。", "response_too_large")
                return bytes(content)
            finally:
                await response.aclose()
    except SearchError:
        raise
    except (httpx.HTTPError, ValueError, UnicodeError):
        if approval_error is not None:
            raise approval_error
        raise SearchError("无法连接搜索服务。", "service_failure") from None


async def _bing_request(query, *, common, transport=None, headers=None, before_request=None):
    """Bing's public page may redirect; keyed service requests must not follow it.

    Keep cookies within this one request chain, and allow only known Bing HTTPS
    hosts. The configured timeout covers the whole chain, not each redirect.
    """
    timeout = _timeout(common)
    allowed_hosts = {"www.bing.com", "cn.bing.com", "bing.com"}
    headers = dict(headers or {})
    headers.pop("Cookie", None)
    approval_error = None
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=False, trust_env=False) as client:
                client.cookies.set("SRCHHPGUSR", "ULSR=1", domain=".bing.com", path="/")
                target = httpx.URL("https://www.bing.com/search", params={"q": query})
                for redirect_count in range(4):
                    request = client.build_request("GET", target, headers=headers)
                    if before_request is not None:
                        try:
                            await before_request(request)
                        except Exception as error:
                            approval_error = error
                            raise
                    response = await client.send(request, stream=True)
                    try:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            if redirect_count == 3:
                                raise SearchError("Bing 搜索重定向次数过多。", "redirect_limit")
                            location = response.headers.get("location")
                            if not location:
                                raise SearchError("Bing 搜索重定向缺少目标地址。", "invalid_redirect")
                            try:
                                redirected = target.join(location)
                            except httpx.InvalidURL:
                                raise SearchError("Bing 搜索重定向地址格式不正确。", "invalid_redirect") from None
                            if (redirected.scheme != "https" or redirected.host not in allowed_hosts
                                    or redirected.port not in {None, 443} or redirected.userinfo):
                                raise SearchError("Bing 搜索重定向到了不受支持的地址。", "invalid_redirect")
                            target = redirected
                            continue
                        if response.status_code == 429:
                            raise SearchError("Bing 请求过于频繁（HTTP 429），请稍后重试。", "rate_limited")
                        if response.status_code == 403:
                            raise SearchError("Bing 拒绝了搜索请求（HTTP 403）。", "service_blocked")
                        if not 200 <= response.status_code < 300:
                            raise SearchError(f"Bing 搜索请求失败（HTTP {response.status_code}）。", "service_failure")
                        content = bytearray()
                        async for chunk in response.aiter_bytes():
                            content.extend(chunk)
                            if len(content) > MAX_RESPONSE_BYTES:
                                raise SearchError("搜索服务返回的数据超过大小限制。", "response_too_large")
                        return bytes(content)
                    finally:
                        await response.aclose()
    except SearchError:
        raise
    except (TimeoutError, httpx.TimeoutException):
        if approval_error is not None:
            raise approval_error
        raise SearchError("Bing 搜索请求超时，请稍后重试。", "timeout") from None
    except httpx.ConnectError:
        if approval_error is not None:
            raise approval_error
        raise SearchError("无法建立到 Bing 的连接，请检查服务端网络。", "connection_failure") from None
    except (httpx.HTTPError, ValueError, UnicodeError):
        if approval_error is not None:
            raise approval_error
        raise SearchError("Bing 搜索响应传输失败。", "service_failure") from None


async def _json(method, url, *, common, transport=None, headers=None, body=None, params=None, before_request=None):
    raw = await _request(method, url, common=common, transport=transport, headers=headers, body=body, params=params, before_request=before_request)
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeError):
        raise SearchError("搜索服务返回的数据格式不正确。", "invalid_response") from None
    if not isinstance(parsed, dict):
        raise SearchError("搜索服务返回的数据格式不正确。", "invalid_response")
    if parsed.get("success") is False or parsed.get("error"):
        raise SearchError("搜索服务报告请求失败。", "service_failure")
    return parsed


def _get(data, *path, default=None):
    for part in path:
        if not isinstance(data, dict):
            return default
        data = data.get(part)
    return default if data is None else data


def _item(value, *, title="title", url="url", text="text", date="publishedDate"):
    if not isinstance(value, dict):
        return None
    link = value.get(url)
    if not isinstance(link, str):
        return None
    try:
        _url(link)
    except SearchError:
        return None
    heading = value.get(title) or link
    passage = value.get(text) or ""
    highlights = value.get("highlights")
    return {"title": str(heading), "url": link, "text": str(passage),
            "published_date": str(value[date]) if value.get(date) else None,
            "highlights": [str(x) for x in highlights if isinstance(x, str)] if isinstance(highlights, list) else []}


def _items(values, *, size, **mapping):
    if not isinstance(values, list):
        raise SearchError("搜索服务返回的数据格式不正确。", "invalid_response")
    return [item for value in values if (item := _item(value, **mapping)) is not None][:size]


def _result(items, answer=None, images=None):
    return {"answer": str(answer) if answer is not None else None, "items": items,
            "images": [x for x in (images or []) if isinstance(x, str) and _valid_result_url(x)],
            "retrieved_at": _stamp()}


def _valid_result_url(value):
    try:
        _url(value)
        return True
    except SearchError:
        return False


def _scraped(url, content, metadata=None):
    _url(url)
    return {"url": url, "content": str(content or ""), "metadata": metadata if isinstance(metadata, dict) else {}}


def _scrape_result(urls):
    return {"urls": urls, "retrieved_at": _stamp()}


def _headers(key, *, header="Authorization", bearer=True):
    return {header: f"Bearer {key}" if bearer else key, "Accept": "application/json"}


class _BingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.in_title = False
        self.in_snippet = False
        self.current = None
        self.items = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = set(a.get("class", "").split())
        if tag == "li" and "b_algo" in classes and self.depth == 0:
            self.depth = 1
            self.current = {"title": "", "url": "", "text": ""}
            return
        if not self.depth:
            return
        if tag == "li":
            self.depth += 1
        if tag == "h2":
            self.in_title = True
        elif tag == "a" and self.in_title and self.current:
            self.current["url"] = a.get("href", "")
        elif tag == "p":
            self.in_snippet = True

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag == "h2":
            self.in_title = False
        elif tag == "p":
            self.in_snippet = False
        elif tag == "li":
            self.depth -= 1
            if self.depth == 0 and self.current:
                self.items.append(self.current)
                self.current = None

    def handle_data(self, data):
        if self.current:
            if self.in_title:
                self.current["title"] += data
            elif self.in_snippet:
                self.current["text"] += data


def _bing_target(link):
    """Resolve Bing's encoded outbound target without fetching the redirect."""
    try:
        parsed = urlsplit(link)
        if parsed.hostname not in {"bing.com", "www.bing.com"} or parsed.path != "/ck/a":
            return link
        values = parse_qs(parsed.query, keep_blank_values=True).get("u", [])
        if len(values) != 1 or not values[0].startswith("a1"):
            return link
        encoded = values[0][2:]
        if not encoded or len(encoded) > 4096:
            return link
        target = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True).decode("utf-8")
        _url(target)
        return target
    except (SearchError, ValueError, UnicodeError, binascii.Error):
        return link


def _bing_language(options):
    language = options.get("language", "zh-CN")
    if not isinstance(language, str) or len(language) > 35 or (language and not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", language)):
        raise SearchError("Bing 首选语言格式不正确。", "invalid_config")
    if not language:
        return None
    primary = language.split("-", 1)[0]
    return language if language.lower() == primary.lower() else f"{language},{primary};q=0.9"


async def search(kind: str, params: dict, common: dict, options: dict, *, transport: httpx.AsyncBaseTransport | None = None, before_request=None) -> dict:
    if kind not in KINDS:
        raise SearchError("不支持该搜索服务。", "unknown_service")
    if kind == "custom_js":
        raise SearchError("自定义脚本执行功能尚未接入。", "unsupported")
    query = params.get("query") if isinstance(params, dict) else None
    if not isinstance(query, str) or not query.strip():
        raise SearchError("请填写搜索词。", "invalid_query")
    common, options = common or {}, options or {}
    size = _size(common)
    headers = None
    method = "POST"
    body = {}
    url = ""
    request_params = None
    if kind == "bing":
        language = _bing_language(options)
        bing_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Charset": "utf-8",
            "Referer": "https://www.bing.com/",
            "Cookie": "SRCHHPGUSR=ULSR=1",
        }
        if language:
            bing_headers["Accept-Language"] = language
        raw = await _bing_request(query, common=common, transport=transport, headers=bing_headers, before_request=before_request)
        parser = _BingParser()
        parser.feed(raw.decode("utf-8", "replace"))
        for item in parser.items:
            item["url"] = _bing_target(item["url"])
        items = _items(parser.items, size=size)
        if not items:
            raise SearchError("Bing 未返回可用结果。", "no_results")
        return _result(items)
    if kind == "searxng":
        url = _configured_endpoint(options.get("url"), "")
        url = url.rstrip("/") + "/search"
        method = "GET"
        request_params = {"q": query, "format": "json"}
        for key in ("engines", "language"):
            if options.get(key):
                request_params[key] = options[key]
        if options.get("username") and options.get("password"):
            import base64
            token = base64.b64encode(f'{options["username"]}:{options["password"]}'.encode()).decode()
            headers = {"Authorization": f"Basic {token}"}
    else:
        key = _key(options)
        headers = _headers(key)
        if kind == "rikkahub":
            url = "https://api.rikka-ai.com/v1/search"
            body = {"q": query, "depth": options.get("depth", "standard"), "outputType": "sourcedAnswer", "includeImages": "false"}
        elif kind == "zhipu":
            url = "https://open.bigmodel.cn/api/paas/v4/web_search"
            body = {"search_query": query, "search_engine": "search_std", "count": size}
        elif kind == "doubao":
            mode = options.get("mode", "custom")
            if mode not in {"custom", "global"}:
                raise SearchError("搜索模式不正确。", "invalid_config")
            url = "https://open.feedcoopapi.com/search_api/" + ("web_search" if mode == "custom" else "global_search")
            body = {"Query": query, "SearchType": "web", "Count": min(size, 50), "QueryControl": {"QueryRewrite": False}} if mode == "custom" else {"Query": query, "DocCount": min(size, 20), "MaxSnippetLength": 300, "MaxImageCountPerDoc": 1}
        elif kind == "tavily":
            url = "https://api.tavily.com/search"
            topic = params.get("topic", "general")
            if topic not in {"general", "news", "finance"}:
                raise SearchError("搜索主题不正确。", "invalid_query")
            body = {"query": query, "max_results": size, "search_depth": options.get("depth", "advanced"), "topic": topic, "include_answer": "advanced", "include_images": True}
        elif kind == "exa":
            url = "https://api.exa.ai/search"
            search_type = params.get("type", "auto")
            if search_type not in {"fast", "auto", "deep"}:
                raise SearchError("Exa 搜索类型不正确。", "invalid_query")
            body = {"query": query, "numResults": size, "type": search_type, "contents": {"text": True}}
            evidence = False
            for name in ("startPublishedDate", "endPublishedDate"):
                if name in params:
                    if not isinstance(params[name], str):
                        raise SearchError("发布日期格式不正确。", "invalid_query")
                    body[name] = params[name]
                    evidence = True
            for name in ("includeDomains", "excludeDomains"):
                if name in params:
                    body[name] = _string_list(params[name])
                    evidence = True
            if "maxAgeHours" in params:
                body["contents"]["maxAgeHours"] = _age(params["maxAgeHours"])
                evidence = True
            if evidence:
                body["contents"].update({"text": {"maxCharacters": 8000}, "highlights": {"maxCharacters": 1200}})
        elif kind == "linkup":
            url = "https://api.linkup.so/v1/search"
            body = {"q": query, "depth": options.get("depth", "standard"), "outputType": "sourcedAnswer"}
        elif kind == "brave":
            url = "https://api.search.brave.com/res/v1/web/search"
            method = "GET"
            request_params = {"q": query, "count": size}
            headers = _headers(key, header="X-Subscription-Token", bearer=False)
        elif kind == "metaso":
            url = "https://metaso.cn/api/v1/search"
            body = {"q": query, "scope": "webpage", "size": size}
        elif kind == "ollama":
            url = "https://ollama.com/api/web_search"
            body = {"query": query, "max_results": max(5, min(size, 10))}
        elif kind == "perplexity":
            url = "https://api.perplexity.ai/search"
            body = {"query": query, "max_results": size}
            for source, target in (("max_tokens", "max_tokens"), ("max_tokens_per_page", "max_tokens_per_page")):
                if options.get(source) is not None:
                    value = _positive_int(options[source])
                    body[target] = value
        elif kind == "firecrawl":
            url = "https://api.firecrawl.dev/v2/search"
            body = {"query": query, "limit": size}
            for name in ("sources", "categories"):
                if name in params:
                    values = _string_list(params[name])
                    allowed = {"web", "news"} if name == "sources" else {"github", "research"}
                    if any(value not in allowed for value in values):
                        raise SearchError("搜索筛选条件不正确。", "invalid_query")
                    if values:
                        body[name] = values
        elif kind == "jina":
            url = _configured_endpoint(options.get("search_url"), "https://s.jina.ai/")
            body = {"q": query}
        elif kind == "bocha":
            url = "https://api.bochaai.com/v1/web-search"
            body = {"query": query, "summary": bool(options.get("summary", True)), "count": size}
        elif kind == "grok":
            url = _configured_endpoint(options.get("custom_url"), "https://api.x.ai/v1/responses")
            body = {"model": options.get("model") or "grok-4-1-fast-non-reasoning",
                    "input": [{"role": "system", "content": options.get("system_prompt") or "查找可靠的近期资料，给出有来源的回答。"}, {"role": "user", "content": query}],
                    "tools": [{"type": "web_search"}, {"type": "x_search"}], "store": False}
        elif kind == "tinyfish":
            url = "https://api.search.tinyfish.ai"
            method = "GET"
            request_params = {"query": query}
            headers = _headers(key, header="X-API-Key", bearer=False)
        elif kind == "serper":
            url = "https://google.serper.dev/search"
            body = {"q": query, "num": size}
            headers = _headers(key, header="X-API-KEY", bearer=False)
    data = await _json(method, url, common=common, transport=transport, headers=headers, body=body if method == "POST" else None, params=request_params, before_request=before_request)
    try:
        return _parse_search(kind, data, size, options)
    except SearchError:
        raise
    except (TypeError, ValueError, KeyError, AttributeError):
        raise SearchError("搜索服务返回的数据格式不正确。", "invalid_response") from None


def _positive_int(value):
    try:
        number = int(value)
    except (ValueError, TypeError):
        raise SearchError("数值须为正整数。", "invalid_config") from None
    if number <= 0:
        raise SearchError("数值须为正整数。", "invalid_config")
    return number


def _age(value):
    try:
        value = int(value)
    except (ValueError, TypeError):
        raise SearchError("内容缓存时效不正确。", "invalid_query") from None
    if not -1 <= value <= 720:
        raise SearchError("内容缓存时效不正确。", "invalid_query")
    return value


def _string_list(value):
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise SearchError("搜索筛选条件不正确。", "invalid_query")
    return [x.strip() for x in value if x.strip()]


def _parse_search(kind, data, size, options):
    answer = data.get("answer")
    images = data.get("images") or []
    mapping = {}
    if kind in {"rikkahub", "linkup"}:
        values = data.get("sources", [])
        mapping = {"title": "name", "text": "snippet"}
    elif kind == "zhipu":
        values = data.get("search_result", [])
        mapping = {"url": "link", "text": "content"}
    elif kind == "doubao":
        if _get(data, "ResponseMetadata", "Error"):
            raise SearchError("搜索服务报告请求失败。", "service_failure")
        result = data.get("Result") or {}
        if options.get("mode", "custom") == "global":
            if result.get("ErrorCode") not in (None, 0):
                raise SearchError("搜索服务报告请求失败。", "service_failure")
            values = result.get("Documents", [])
            mapping = {"title": "Title", "url": "Url", "text": "Snippet"}
            images = [s.get("Image", {}).get("ImageUrl") for v in values if isinstance(v, dict) for s in v.get("Snippet", []) if isinstance(s, dict) and isinstance(s.get("Image"), dict)]
            values = [dict(v, Snippet="\n".join(s.get("Text", "") for s in v.get("Snippet", []) if isinstance(s, dict))) for v in values if isinstance(v, dict)]
        else:
            values = result.get("WebResults", [])
            mapping = {"title": "Title", "url": "Url", "text": "Summary"}
            values = [dict(v, Summary=v.get("Summary") or v.get("Snippet", "")) for v in values if isinstance(v, dict)]
    elif kind == "tavily":
        values = data.get("results", [])
        mapping = {"text": "content"}
    elif kind == "exa":
        values = data.get("results", [])
        answer = _get(data, "output", "content")
        images = [x.get("image") for x in values if isinstance(x, dict)]
    elif kind == "searxng":
        values = data.get("results", [])
        mapping = {"text": "content"}
    elif kind == "brave":
        values = _get(data, "web", "results", default=[])
        mapping = {"text": "description"}
    elif kind == "metaso":
        values = data.get("webpages", [])
        mapping = {"url": "link", "text": "snippet", "date": "date"}
    elif kind == "ollama":
        values = data.get("results", [])
        mapping = {"text": "content"}
    elif kind == "perplexity":
        values = [dict(v, snippet=v.get("snippet") or v.get("text", "")) for v in data.get("results", []) if isinstance(v, dict)]
        mapping = {"text": "snippet"}
    elif kind == "firecrawl":
        raw = data.get("data", {})
        if isinstance(raw, dict):
            values = [*(raw.get("web") or [])]
            values.extend(dict(v, description=v.get("snippet") or v.get("description", ""), publishedDate=v.get("date")) for v in (raw.get("news") or []) if isinstance(v, dict))
        else:
            values = raw
        mapping = {"text": "description"}
    elif kind == "jina":
        values = data.get("data", [])
        mapping = {"text": "description"}
    elif kind == "bocha":
        values = _get(data, "data", "webPages", "value", default=[])
        values = [dict(v, snippet=v.get("summary") or v.get("snippet", "")) for v in values if isinstance(v, dict)]
        mapping = {"title": "name", "text": "snippet"}
    elif kind == "grok":
        messages = [x for x in data.get("output", []) if isinstance(x, dict) and x.get("type") == "message" and x.get("role") == "assistant"]
        contents = messages[0].get("content", []) if messages else []
        content = next((x for x in contents if isinstance(x, dict) and x.get("type") == "output_text"), {})
        answer = content.get("text")
        values = [{"url": x["url"], "title": x["url"], "text": ""} for x in content.get("annotations", []) if isinstance(x, dict) and x.get("type") == "url_citation" and x.get("url")]
    elif kind == "tinyfish":
        values = data.get("results", [])
        mapping = {"text": "snippet"}
    elif kind == "serper":
        values = data.get("organic", [])
        mapping = {"title": "title", "url": "link", "text": "snippet"}
        answer = _get(data, "answerBox", "answer") or _get(data, "answerBox", "snippet") or _get(data, "knowledgeGraph", "description")
    else:
        raise SearchError("不支持该搜索服务。", "unknown_service")
    return _result(_items(values, size=size, **mapping), answer, images)


async def scrape(kind: str, params: dict, common: dict, options: dict, *, transport: httpx.AsyncBaseTransport | None = None, before_request=None) -> dict:
    if kind not in KINDS:
        raise SearchError("不支持该搜索服务。", "unknown_service")
    if kind == "custom_js":
        raise SearchError("自定义脚本执行功能尚未接入。", "unsupported")
    if not KINDS[kind]["supports_scrape"]:
        raise SearchError("该服务不支持读取网页。", "unsupported")
    common, options = common or {}, options or {}
    _size(common)
    if not isinstance(params, dict):
        raise SearchError("请填写网页地址。", "invalid_url")
    # Parsing is local; resolving a hostname before approval would itself
    # disclose a private URL to DNS. Resolve only after the request is approved.
    page = await _public_page(params.get("url"), resolve=False)
    key = _key(options)
    headers = _headers(key)
    body = {}
    if kind == "tavily":
        endpoint = "https://api.tavily.com/extract"
        body = {"urls": [page]}
    elif kind == "exa":
        endpoint = "https://api.exa.ai/contents"
        body = {"urls": [page], "text": {"maxCharacters": 8000}}
        if "maxAgeHours" in params:
            body["maxAgeHours"] = _age(params["maxAgeHours"])
    elif kind == "linkup":
        endpoint = "https://api.linkup.so/v1/fetch"
        body = {"url": page}
    elif kind == "ollama":
        endpoint = "https://ollama.com/api/web_fetch"
        body = {"url": page}
    elif kind == "firecrawl":
        endpoint = "https://api.firecrawl.dev/v2/scrape"
        body = {"url": page, "onlyMainContent": bool(params.get("onlyMainContent", True)), "maxAge": 172800000, "parsers": [], "formats": ["markdown"]}
    elif kind == "jina":
        endpoint = _configured_endpoint(options.get("scrape_url"), "https://r.jina.ai/")
        body = {"url": page}
        headers["X-Return-Format"] = "markdown"
    elif kind == "tinyfish":
        endpoint = "https://api.fetch.tinyfish.ai"
        body = {"urls": [page], "format": "markdown"}
        headers = _headers(key, header="X-API-Key", bearer=False)
    async def before_scrape_request(request):
        if before_request is not None:
            await before_request(request)
        if transport is None:
            await _public_page(page, resolve=True)

    data = await _json("POST", endpoint, common=common, transport=transport, headers=headers, body=body, before_request=before_scrape_request)
    try:
        return _parse_scrape(kind, data, page)
    except SearchError:
        raise
    except (TypeError, ValueError, KeyError, AttributeError):
        raise SearchError("搜索服务返回的数据格式不正确。", "invalid_response") from None


def _parse_scrape(kind, data, page):
    if kind in {"tavily", "exa"}:
        values = data.get("results", [])
        if not isinstance(values, list):
            raise SearchError("搜索服务返回的数据格式不正确。", "invalid_response")
        urls = [_scraped(v.get("url", page), v.get("raw_content") if kind == "tavily" else v.get("text"),
                         {"title": v.get("title"), "published_date": v.get("publishedDate")} if kind == "exa" else {})
                for v in values if isinstance(v, dict)]
    elif kind == "linkup":
        urls = [_scraped(page, data.get("markdown"))]
    elif kind == "ollama":
        urls = [_scraped(page, data.get("content"), {"title": data.get("title")})]
    elif kind == "firecrawl":
        if data.get("success") is not True:
            raise SearchError("搜索服务返回的数据格式不正确。", "invalid_response")
        values = data.get("data", {})
        urls = [_scraped(page, values.get("markdown") if isinstance(values, dict) else "")]
    elif kind == "jina":
        values = data.get("data", {})
        urls = [_scraped(values.get("url", page), values.get("content"), {"title": values.get("title"), "description": values.get("description")})] if isinstance(values, dict) else []
    elif kind == "tinyfish":
        values = data.get("results", [])
        urls = [_scraped(v.get("url", page), v.get("text"), {k: v.get(k) for k in ("title", "description", "language")}) for v in values if isinstance(v, dict)]
    return _scrape_result(urls)
