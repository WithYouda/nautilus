import asyncio
import json
import base64
from urllib.parse import quote

import httpx
import pytest

from app.search_adapters import SearchError, scrape, search
from app.search_catalog import SEARCH_CATALOG


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,payload,part", [
    ("bing", '<li class="b_algo"><h2><a href="https://example.com/a">A</a></h2><p>Snippet</p></li>', "/search"),
    ("rikkahub", {"answer": "A", "sources": [{"name": "A", "url": "https://example.com/a", "snippet": "T"}]}, "/v1/search"),
    ("zhipu", {"search_result": [{"title": "A", "link": "https://example.com/a", "content": "T"}]}, "/web_search"),
    ("doubao", {"Result": {"WebResults": [{"Title": "A", "Url": "https://example.com/a", "Summary": "T"}]}}, "/web_search"),
    ("tavily", {"answer": "A", "results": [{"title": "A", "url": "https://example.com/a", "content": "T"}]}, "/search"),
    ("exa", {"results": [{"title": "A", "url": "https://example.com/a", "text": "T"}]}, "/search"),
    ("searxng", {"results": [{"title": "A", "url": "https://example.com/a", "content": "T"}]}, "/search"),
    ("linkup", {"answer": "A", "sources": [{"name": "A", "url": "https://example.com/a", "snippet": "T"}]}, "/v1/search"),
    ("brave", {"web": {"results": [{"title": "A", "url": "https://example.com/a", "description": "T"}]}}, "/web/search"),
    ("metaso", {"webpages": [{"title": "A", "link": "https://example.com/a", "snippet": "T"}]}, "/search"),
    ("ollama", {"results": [{"title": "A", "url": "https://example.com/a", "content": "T"}]}, "/web_search"),
    ("perplexity", {"results": [{"title": "A", "url": "https://example.com/a", "snippet": "T"}]}, "/search"),
    ("firecrawl", {"data": {"web": [{"title": "A", "url": "https://example.com/a", "description": "T"}]}}, "/search"),
    ("jina", {"data": [{"title": "A", "url": "https://example.com/a", "description": "T"}]}, "/"),
    ("bocha", {"data": {"webPages": {"value": [{"name": "A", "url": "https://example.com/a", "snippet": "T"}]}}}, "/web-search"),
    ("grok", {"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "A", "annotations": [{"type": "url_citation", "url": "https://example.com/a"}]}]}]}, "/responses"),
    ("tinyfish", {"results": [{"title": "A", "url": "https://example.com/a", "snippet": "T"}]}, "/"),
    ("serper", {"organic": [{"title": "A", "link": "https://example.com/a", "snippet": "T"}]}, "/search"),
])
async def test_every_http_search(kind, payload, part):
    seen = []

    def handler(request):
        seen.append(request)
        assert part in request.url.path
        if kind == "bing":
            return httpx.Response(200, text=payload)
        return httpx.Response(200, json=payload)

    options = {"api_key": "secret-test", "url": "https://example.com", "mode": "custom"}
    result = await search(kind, {"query": "sample"}, {"result_size": 1}, options, transport=httpx.MockTransport(handler))
    assert len(seen) == 1
    assert result["items"][0]["url"] == "https://example.com/a"
    assert result["items"][0]["published_date"] is None
    assert result["retrieved_at"].endswith("+00:00")
    if kind not in {"bing", "searxng"}:
        header = "X-Subscription-Token" if kind == "brave" else "X-API-Key" if kind in {"tinyfish", "serper"} else "Authorization"
        assert "secret-test" in seen[0].headers[header]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,payload", [
    ("tavily", {"results": [{"url": "https://example.com/a", "raw_content": "T"}]}),
    ("exa", {"results": [{"url": "https://example.com/a", "text": "T"}]}),
    ("linkup", {"markdown": "T"}),
    ("ollama", {"content": "T", "title": "A"}),
    ("firecrawl", {"success": True, "data": {"markdown": "T"}}),
    ("jina", {"data": {"url": "https://example.com/a", "content": "T"}}),
    ("tinyfish", {"results": [{"url": "https://example.com/a", "text": "T"}]}),
])
async def test_every_http_scraper(kind, payload):
    def handler(request):
        body = json.loads(request.content)
        assert "https://example.com/a" in str(body)
        return httpx.Response(200, json=payload)

    result = await scrape(kind, {"url": "https://example.com/a"}, {}, {"api_key": "secret-test"}, transport=httpx.MockTransport(handler))
    assert result["urls"][0]["content"] == "T"
    assert result["retrieved_at"].endswith("+00:00")


def test_catalog_is_complete():
    assert len(SEARCH_CATALOG) == 19
    assert len({row["kind"] for row in SEARCH_CATALOG}) == 19
    for row in SEARCH_CATALOG:
        assert row["search_parameters"]["required"] == ["query"]
        assert all({"key", "label", "type", "default"} <= field.keys() for field in row["fields"])


@pytest.mark.asyncio
async def test_no_fallback_or_secret_leak():
    def handler(request):
        return httpx.Response(401, text="secret-test and private query")

    with pytest.raises(SearchError) as caught:
        await search("brave", {"query": "private query"}, {}, {"api_key": "secret-test"}, transport=httpx.MockTransport(handler))
    assert caught.value.kind == "service_failure"
    assert "secret-test" not in str(caught.value)
    assert "private query" not in str(caught.value)
    with pytest.raises(SearchError) as unknown:
        await search("not_a_service", {"query": "x"}, {}, {})
    assert unknown.value.kind == "unknown_service"


@pytest.mark.asyncio
async def test_bounds_and_blocked_pages():
    for url in ("http://127.0.0.1/a", "http://localhost/a", "file:///etc/passwd", "http://10.0.0.1/a", "https://user:pass@example.com/a"):
        with pytest.raises(SearchError) as caught:
            await scrape("tavily", {"url": url}, {}, {"api_key": "x"}, transport=httpx.MockTransport(lambda r: pytest.fail("unexpected request")))
        assert caught.value.kind == "invalid_url"
    with pytest.raises(SearchError):
        await search("bing", {"query": "x"}, {"result_size": 51}, {})
    with pytest.raises(SearchError):
        await search("bing", {"query": "x"}, {"timeout_seconds": 121}, {}, transport=httpx.MockTransport(lambda r: pytest.fail("unexpected request")))


@pytest.mark.asyncio
async def test_bing_empty_or_blocked_page_is_not_search_success():
    for page in ("", "captcha required", '<li class="b_algo"><h2><a href="javascript:evil">Bad</a></h2></li>'):
        with pytest.raises(SearchError) as caught:
            await search("bing", {"query": "x"}, {}, {}, transport=httpx.MockTransport(lambda r: httpx.Response(200, text=page)))
        assert caught.value.kind == "no_results"


@pytest.mark.asyncio
async def test_bing_preserves_full_query_and_sets_language_preference():
    query = "今日 中国 科技新闻 TOP companies"
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, text='<li class="b_algo"><h2><a href="https://example.com/a">A</a></h2><p>Snippet</p></li>')

    for options, expected in (({}, "zh-CN,zh;q=0.9"), ({"language": "en-US"}, "en-US,en;q=0.9"), ({"language": ""}, None)):
        await search("bing", {"query": query}, {}, options, transport=httpx.MockTransport(handler))
        request = seen[-1]
        assert request.url.params["q"] == query
        assert dict(request.url.params) == {"q": query}
        assert request.headers.get("Accept-Language") == expected
        assert "Windows NT 10.0" in request.headers["User-Agent"]
        assert "text/html" in request.headers["Accept"]
        assert request.headers["Accept-Charset"] == "utf-8"
        assert request.headers["Referer"] == "https://www.bing.com/"
        assert request.headers["Cookie"] == "SRCHHPGUSR=ULSR=1"


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["zh-CN\r\nX-Injected: yes", "zh_CN", "a" * 36, "-zh", 7, None])
async def test_bing_rejects_invalid_language_before_outbound(language):
    with pytest.raises(SearchError) as caught:
        await search("bing", {"query": "example"}, {}, {"language": language},
                     transport=httpx.MockTransport(lambda request: pytest.fail("unexpected request")))
    assert caught.value.kind == "invalid_config"


@pytest.mark.asyncio
async def test_bing_follows_scoped_redirects_and_keeps_response_cookies():
    requests = []
    query = "合成查询 multiple words"

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            assert request.url.params['q'] == query
            return httpx.Response(302, headers={
                'Location': '/search?stage=2&q=' + quote(query),
                'Set-Cookie': 'synthetic_bing_session=synthetic; Path=/; Secure',
            })
        if len(requests) == 2:
            assert request.url.params['q'] == query
            assert 'synthetic_bing_session=synthetic' in request.headers['Cookie']
            return httpx.Response(301, headers={'Location': 'https://cn.bing.com/search?q=' + quote(query)})
        assert request.url.host == 'cn.bing.com'
        assert request.url.params['q'] == query
        assert 'synthetic_bing_session' not in request.headers.get('Cookie', '')
        return httpx.Response(200, text='<li class="b_algo"><h2><a href="https://example.com/a">Relevant</a></h2><p>Summary</p></li>')

    result = await search('bing', {'query': query}, {}, {}, transport=httpx.MockTransport(handler))
    assert len(requests) == 3
    assert result['items'][0]['title'] == 'Relevant'


@pytest.mark.asyncio
@pytest.mark.parametrize('location', ['http://www.bing.com/search', 'https://other.example/search',
                                     'https://127.0.0.1/search', 'https://www.bing.com:444/search',
                                     'https://user:password@www.bing.com/search'])
async def test_bing_rejects_unscoped_redirect_before_second_request(location):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={'Location': location})
    with pytest.raises(SearchError) as caught:
        await search('bing', {'query': 'example'}, {}, {}, transport=httpx.MockTransport(handler))
    assert caught.value.kind == 'invalid_redirect'
    assert len(requests) == 1
    assert location not in str(caught.value)


@pytest.mark.asyncio
async def test_bing_redirect_chain_is_bounded():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={'Location': '/search?q=example'})
    with pytest.raises(SearchError) as caught:
        await search('bing', {'query': 'example'}, {}, {}, transport=httpx.MockTransport(handler))
    assert caught.value.kind == 'redirect_limit'
    assert len(requests) == 4


@pytest.mark.asyncio
async def test_bing_timeout_covers_whole_redirect_chain():
    async def handler(request):
        await asyncio.sleep(.02)
        return httpx.Response(302, headers={'Location': '/search?q=example'})
    with pytest.raises(SearchError) as caught:
        await search('bing', {'query': 'example'}, {'timeout_seconds': .035}, {}, transport=httpx.MockTransport(handler))
    assert caught.value.kind == 'timeout'


@pytest.mark.asyncio
async def test_bing_response_size_remains_bounded():
    with pytest.raises(SearchError) as caught:
        await search('bing', {'query': 'example'}, {}, {},
                     transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'x' * (2 * 1024 * 1024 + 1))))
    assert caught.value.kind == 'response_too_large'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,kind', [(403, 'service_blocked'), (429, 'rate_limited'), (500, 'service_failure')])
async def test_bing_http_errors_are_distinguishable_without_echoing_body(status, kind):
    with pytest.raises(SearchError) as caught:
        await search('bing', {'query': 'private-query'}, {}, {},
                     transport=httpx.MockTransport(lambda r: httpx.Response(status, text='private-response')))
    assert caught.value.kind == kind
    assert str(status) in str(caught.value)
    assert 'private' not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('error,kind', [(httpx.ConnectError('private detail'), 'connection_failure'),
                                     (httpx.ReadTimeout('private detail'), 'timeout')])
async def test_bing_network_errors_are_distinguishable_without_echoing_details(error, kind):
    def handler(request):
        raise error
    with pytest.raises(SearchError) as caught:
        await search('bing', {'query': 'example'}, {}, {}, transport=httpx.MockTransport(handler))
    assert caught.value.kind == kind
    assert 'private' not in str(caught.value)


@pytest.mark.asyncio
async def test_bing_decodes_safe_target_and_keeps_redirect_for_dangerous_targets():
    def redirect(target):
        encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
        return f"https://www.bing.com/ck/a?u={quote('a1' + encoded)}&ntb=1"

    safe = "https://example.com/article?q=1"
    unsafe = ["javascript:alert(1)", "https://user:password@example.com/private", "http://127.0.0.1/private"]
    links = [redirect(safe), *(redirect(target) for target in unsafe)]
    page = "".join(f'<li class="b_algo"><h2><a href="{link}">Result</a></h2><p>Excerpt</p></li>' for link in links)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, text=page)

    result = await search("bing", {"query": "example"}, {"result_size": 4}, {}, transport=httpx.MockTransport(handler))
    assert len(seen) == 1
    assert [item["url"] for item in result["items"]] == [safe, *links[1:]]


@pytest.mark.asyncio
async def test_no_redirect_with_key_and_bounded_body():
    with pytest.raises(SearchError):
        await search("brave", {"query": "x"}, {}, {"api_key": "secret-test"}, transport=httpx.MockTransport(lambda r: httpx.Response(302, headers={"Location": "https://other.example/"})))
    with pytest.raises(SearchError) as caught:
        await search("brave", {"query": "x"}, {}, {"api_key": "secret-test"}, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))))
    assert caught.value.kind == "response_too_large"

@pytest.mark.asyncio
async def test_exa_advanced_parameters_and_result_cap():
    def handler(request):
        body = json.loads(request.content)
        assert body["type"] == "deep"
        assert body["startPublishedDate"] == "2025-01-01T00:00:00Z"
        assert body["includeDomains"] == ["example.com"]
        assert body["contents"] == {"text": {"maxCharacters": 8000}, "highlights": {"maxCharacters": 1200}, "maxAgeHours": 24}
        return httpx.Response(200, json={"results": [
            {"title": "A", "url": "https://example.com/a", "text": "T", "highlights": ["H"], "publishedDate": "2025-01-02"},
            {"title": "B", "url": "https://example.com/b", "text": "U"},
        ]})

    result = await search("exa", {"query": "x", "type": "deep", "startPublishedDate": "2025-01-01T00:00:00Z", "includeDomains": ["example.com"], "maxAgeHours": 24}, {"result_size": 1}, {"api_key": "x"}, transport=httpx.MockTransport(handler))
    assert len(result["items"]) == 1
    assert result["items"][0]["highlights"] == ["H"]
    assert result["items"][0]["published_date"] == "2025-01-02"


@pytest.mark.asyncio
async def test_firecrawl_filters_and_fetch_options():
    def search_handler(request):
        assert json.loads(request.content) == {"query": "x", "limit": 2, "sources": ["news"], "categories": ["research"]}
        return httpx.Response(200, json={"data": {"news": [{"title": "A", "url": "https://example.com/a", "description": "T"}]}})

    await search("firecrawl", {"query": "x", "sources": ["news"], "categories": ["research"]}, {"result_size": 2}, {"api_key": "x"}, transport=httpx.MockTransport(search_handler))

    def scrape_handler(request):
        body = json.loads(request.content)
        assert body["onlyMainContent"] is False
        assert body["formats"] == ["markdown"]
        return httpx.Response(200, json={"success": True, "data": {"markdown": "T"}})

    await scrape("firecrawl", {"url": "https://example.com/a", "onlyMainContent": False}, {}, {"api_key": "x"}, transport=httpx.MockTransport(scrape_handler))


@pytest.mark.asyncio
async def test_custom_endpoint_policy_and_basic_auth():
    def handler(request):
        assert request.url.scheme == "http"
        assert request.url.host == "localhost"
        assert request.headers["Authorization"].startswith("Basic ")
        return httpx.Response(200, json={"results": []})

    await search("searxng", {"query": "x"}, {}, {"url": "http://localhost:8888", "username": "a", "password": "b"}, transport=httpx.MockTransport(handler))
    with pytest.raises(SearchError) as caught:
        await search("jina", {"query": "x"}, {}, {"api_key": "x", "search_url": "http://example.com/"}, transport=httpx.MockTransport(lambda r: pytest.fail("unexpected request")))
    assert caught.value.kind == "invalid_url"


@pytest.mark.asyncio
async def test_doubao_global_and_custom_js_placeholder():
    def handler(request):
        assert request.url.path.endswith("/global_search")
        assert json.loads(request.content)["DocCount"] == 20
        return httpx.Response(200, json={"Result": {"Documents": [{"Title": "A", "Url": "https://example.com/a", "Snippet": [{"Text": "T"}]}]}})

    result = await search("doubao", {"query": "x"}, {"result_size": 50}, {"api_key": "x", "mode": "global"}, transport=httpx.MockTransport(handler))
    assert result["items"][0]["text"] == "T"
    with pytest.raises(SearchError) as caught:
        await search("custom_js", {"query": "x"}, {}, {})
    assert caught.value.kind == "unsupported"
