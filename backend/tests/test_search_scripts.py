import asyncio
import json
import socket

import httpx
import pytest

from app.search_adapters import SearchError
from app.search_script_worker import _fetch_request
from app.search_scripts import execute_script


@pytest.mark.asyncio
async def test_async_search_and_scrape_normalize_results():
    search = await execute_script(
        {"search_script": "async function search(query,maxResults) { await Promise.resolve(); return {answer: query, items:[{title:'One',url:'https://example.com/a',text:'body',publishedDate:'2026-01-01'}]}; }"},
        {"query": "hello"}, {"result_size": 2},
    )
    assert search["answer"] == "hello"
    assert search["items"][0]["published_date"] == "2026-01-01"
    scraped = await execute_script(
        {"scrape_script": "async function scrape(urls) { return {urls:urls.map(url=>({url,content:'content',metadata:{publishedDate:'2026-01-02'}}))}; }"},
        {"urls": ["https://example.com/a"]}, {}, fetch=True,
    )
    assert scraped["urls"][0]["metadata"]["published_date"] == "2026-01-02"


@pytest.mark.asyncio
async def test_js_has_no_file_or_process_access():
    result = await execute_script(
        {"search_script": "function search(){ return {items:[{title:'Safe',url:'https://example.com',text:[typeof require,typeof process,typeof Deno,typeof XMLHttpRequest].join(',')}]}; }"},
        {"query": "q"}, {},
    )
    assert result["items"][0]["text"] == "undefined,undefined,undefined,undefined"


@pytest.mark.asyncio
@pytest.mark.parametrize("script", [
    "function search(){ return {items:[{title:'bad',url:'file:///etc/passwd',text:''}]}; }",
    "function search(){ return {items:[{title:'bad',url:'https://example.com',text:42}]}; }",
    "function search(){ return null; }",
])
async def test_invalid_script_results_are_rejected(script):
    with pytest.raises(SearchError):
        await execute_script({"search_script": script}, {"query": "q"}, {})


@pytest.mark.asyncio
async def test_infinite_loop_timeout_and_cancellation():
    with pytest.raises(SearchError) as error:
        await execute_script({"search_script": "function search(){ while(true){} }"}, {"query": "q"}, {"timeout_seconds": .2})
    assert error.value.kind in {"timeout", "script_failed"}  # wall limit or CPU limit can win
    task = asyncio.create_task(execute_script({"search_script": "function search(){ while(true){} }"}, {"query": "q"}, {"timeout_seconds": 5}))
    await asyncio.sleep(.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_localhost_fetch_is_rejected_without_network():
    script = "async function search(){ await fetch('http://127.0.0.1/secret'); return {items:[]}; }"
    with pytest.raises(SearchError) as error:
        await execute_script({"search_script": script}, {"query": "q"}, {})
    assert error.value.kind == "script_failed"


def test_fetch_pins_checked_dns_ip_and_preserves_host_and_sni():
    seen = {}

    def resolver(host, port, **kwargs):
        assert host == "example.com"
        assert port == 443
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", port))]

    def handler(request):
        seen["url"] = str(request.url)
        seen["host"] = request.headers["Host"]
        seen["sni"] = request.extensions["sni_hostname"]
        return httpx.Response(200, text='{"ok":true}')

    result = _fetch_request("https://example.com/path?q=1", {}, resolver=resolver, transport=httpx.MockTransport(handler))
    assert result["status"] == 200
    assert seen == {"url": "https://93.184.215.14/path?q=1", "host": "example.com", "sni": "example.com"}


@pytest.mark.parametrize("addresses", [
    ["127.0.0.1"],
    ["93.184.215.14", "10.0.0.1"],
    ["169.254.169.254"],
])
def test_fetch_rejects_any_nonpublic_dns_answer(addresses):
    def resolver(_host, port, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in addresses]
    with pytest.raises(ValueError, match="invalid_url"):
        _fetch_request("https://example.com/", {}, resolver=resolver, transport=httpx.MockTransport(lambda _: httpx.Response(200)))


def test_fetch_rejects_redirect_and_host_override():
    resolver = lambda _host, port, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", port))]
    with pytest.raises(ValueError, match="invalid_headers"):
        _fetch_request("https://example.com/", {"headers": {"Host": "evil.test"}}, resolver=resolver)
    with pytest.raises(ValueError, match="redirect_blocked"):
        _fetch_request("https://example.com/", {}, resolver=resolver,
                       transport=httpx.MockTransport(lambda _: httpx.Response(302, headers={"Location": "http://localhost/"})))
