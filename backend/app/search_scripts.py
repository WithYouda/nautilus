"""Validate custom JS input/output and supervise its isolated worker."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

from .search_adapters import SearchError

WORKER = Path(__file__).with_name("search_script_worker.py")
MAX_SCRIPT = 128 * 1024


def _number(value, *, default, low, high, name):
    if value is None:
        return default
    if isinstance(value, bool):
        raise SearchError(f"{name}格式不正确", "invalid_config")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise SearchError(f"{name}格式不正确", "invalid_config") from None
    if not low <= parsed <= high or parsed != parsed:
        raise SearchError(f"{name}格式不正确", "invalid_config")
    return parsed


def _url(value):
    if not isinstance(value, str) or not value or len(value) > 2048 or any(ord(c) < 33 for c in value):
        raise SearchError("自定义脚本返回了不支持的网页地址", "invalid_response")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").rstrip(".").lower()
    except ValueError:
        raise SearchError("自定义脚本返回了不支持的网页地址", "invalid_response") from None
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise SearchError("自定义脚本返回了不支持的网页地址", "invalid_response")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise SearchError("自定义脚本返回了不支持的网页地址", "invalid_response")
    return value


def _string(value, maximum):
    if not isinstance(value, str) or len(value) > maximum:
        raise SearchError("自定义脚本返回的数据格式不正确", "invalid_response")
    return value


def _stamp():
    return datetime.now(timezone.utc).isoformat()


def _normalize_search(result, size):
    if not isinstance(result, dict) or not isinstance(result.get("items"), list) or len(result["items"]) > 1000:
        raise SearchError("自定义脚本返回的搜索结果格式不正确", "invalid_response")
    answer = result.get("answer")
    if answer is not None:
        answer = _string(answer, 20000)
    items = []
    for item in result["items"][:size]:
        if not isinstance(item, dict):
            raise SearchError("自定义脚本返回的搜索结果格式不正确", "invalid_response")
        url = _url(item.get("url"))
        highlights = item.get("highlights", [])
        if not isinstance(highlights, list) or len(highlights) > 20:
            raise SearchError("自定义脚本返回的搜索结果格式不正确", "invalid_response")
        date = item.get("published_date", item.get("publishedDate"))
        items.append({"title": _string(item.get("title"), 300), "url": url,
                      "text": _string(item.get("text", ""), 20000),
                      "published_date": _string(date, 100) if date is not None else None,
                      "highlights": [_string(part, 1000) for part in highlights]})
    images = result.get("images", [])
    if not isinstance(images, list) or len(images) > 100:
        raise SearchError("自定义脚本返回的搜索结果格式不正确", "invalid_response")
    return {"answer": answer, "items": items, "images": [_url(image) for image in images[:20]], "retrieved_at": _stamp()}


def _normalize_scrape(result):
    if not isinstance(result, dict) or not isinstance(result.get("urls"), list) or len(result["urls"]) > 50:
        raise SearchError("自定义脚本返回的网页内容格式不正确", "invalid_response")
    urls = []
    for item in result["urls"]:
        if not isinstance(item, dict):
            raise SearchError("自定义脚本返回的网页内容格式不正确", "invalid_response")
        meta = item.get("metadata") or {}
        if not isinstance(meta, dict):
            raise SearchError("自定义脚本返回的网页内容格式不正确", "invalid_response")
        metadata = {}
        for key in ("title", "description", "language", "published_date", "publishedDate"):
            if meta.get(key) is not None:
                target = "published_date" if key == "publishedDate" else key
                metadata[target] = _string(meta[key], 500)
        urls.append({"url": _url(item.get("url")), "content": _string(item.get("content"), 100000), "metadata": metadata})
    return {"urls": urls, "retrieved_at": _stamp()}


async def execute_script(options: dict, params: dict, common: dict, fetch: bool = False) -> dict:
    """Execute search(query,maxResults) or scrape(urls) in a killable QuickJS worker."""
    if not isinstance(options, dict) or not isinstance(params, dict) or not isinstance(common, dict):
        raise SearchError("自定义脚本配置格式不正确", "invalid_config")
    size = int(_number(common.get("result_size"), default=10, low=1, high=50, name="结果数量"))
    timeout = _number(common.get("timeout_seconds"), default=30, low=0.1, high=120, name="超时时间")
    max_requests = int(_number(common.get("max_requests"), default=5, low=0, high=20, name="请求次数"))
    mode = "scrape" if fetch else "search"
    script = options.get("scrape_script" if fetch else "search_script")
    if not isinstance(script, str) or not script.strip():
        raise SearchError("请先配置自定义脚本", "unconfigured")
    if len(script.encode("utf-8")) > MAX_SCRIPT:
        raise SearchError("自定义脚本超过大小限制", "invalid_config")
    if fetch:
        argument = params.get("urls", [params.get("url")])
        if not isinstance(argument, list) or not 1 <= len(argument) <= 20 or any(not isinstance(url, str) for url in argument):
            raise SearchError("请填写要读取的网页地址", "invalid_url")
    else:
        argument = params.get("query")
        if not isinstance(argument, str) or not argument.strip() or len(argument) > 8000:
            raise SearchError("请填写搜索词", "invalid_query")
    payload = json.dumps({"script": script, "argument": argument, "mode": mode,
                          "result_size": size, "timeout": timeout, "max_requests": max_requests}, ensure_ascii=False).encode()
    if len(payload) > 300_000:
        raise SearchError("自定义脚本输入超过大小限制", "invalid_config")
    process = None
    try:
        process = await asyncio.create_subprocess_exec(sys.executable, "-I", str(WORKER),
                                                       stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.DEVNULL, limit=1_100_000,
                                                       env={"LANG": "C.UTF-8", "PATH": os.defpath})
        stdout, _ = await asyncio.wait_for(process.communicate(payload), timeout=timeout + 1)
        if process.returncode != 0 or len(stdout) > 1_000_000:
            raise SearchError("自定义脚本执行失败，请检查脚本和服务配置", "script_failed")
        response = json.loads(stdout)
        if not isinstance(response, dict) or response.get("ok") is not True:
            raise SearchError("自定义脚本执行失败，请检查脚本和服务配置", "script_failed")
        return _normalize_scrape(response.get("result")) if fetch else _normalize_search(response.get("result"), size)
    except asyncio.TimeoutError:
        raise SearchError("自定义脚本执行超时", "timeout") from None
    except SearchError:
        raise
    except Exception:
        raise SearchError("自定义脚本执行失败，请检查脚本和服务配置", "script_failed") from None
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
