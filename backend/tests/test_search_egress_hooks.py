"""Outbound approval sees the request that is about to leave the process."""
import json
import socket

import httpx
import pytest

from app import search_adapters
from app.search_adapters import search, scrape
from app.search_script_worker import _fetch_request
from app import search_scripts


class Denied(Exception):
    pass


@pytest.mark.asyncio
async def test_adapter_denial_preserves_exception_and_blocks_send():
    sent = []
    seen = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json={"results": []})

    async def before_request(request):
        seen.append(request)
        raise Denied("wait for approval")

    with pytest.raises(Denied, match="wait for approval"):
        await search("tavily", {"query": "synthetic-private"}, {}, {"api_key": "fake"},
                     transport=httpx.MockTransport(handler), before_request=before_request)
    assert sent == []
    assert len(seen) == 1
    assert seen[0].url == "https://api.tavily.com/search"
    assert json.loads(seen[0].content)["query"] == "synthetic-private"


@pytest.mark.asyncio
async def test_bing_redirect_requires_second_exact_request_approval():
    sent = []
    seen = []

    def handler(request):
        sent.append(str(request.url))
        return httpx.Response(302, headers={"Location": "/search?q=changed"})

    async def before_request(request):
        seen.append(str(request.url))
        if len(seen) == 2:
            raise Denied("redirect changed request")

    with pytest.raises(Denied, match="redirect changed request"):
        await search("bing", {"query": "public"}, {}, {},
                     transport=httpx.MockTransport(handler), before_request=before_request)
    assert len(sent) == 1
    assert seen == ["https://www.bing.com/search?q=public", "https://www.bing.com/search?q=changed"]


@pytest.mark.asyncio
async def test_scrape_hook_sees_full_page_url_in_service_body():
    seen = []

    async def before_request(request):
        seen.append(request)
        raise Denied()

    with pytest.raises(Denied):
        await scrape("tavily", {"url": "https://example.com/page?private=synthetic"}, {},
                     {"api_key": "fake"}, transport=httpx.MockTransport(lambda _: pytest.fail("sent")),
                     before_request=before_request)
    assert json.loads(seen[0].content)["urls"] == ["https://example.com/page?private=synthetic"]


@pytest.mark.asyncio
async def test_scrape_denial_does_not_resolve_page_hostname(monkeypatch):
    def forbidden_resolver(*_args, **_kwargs):
        pytest.fail("page hostname was sent to DNS before approval")

    monkeypatch.setattr(search_adapters.socket, "getaddrinfo", forbidden_resolver)

    async def before_request(request):
        assert b"https://private-name.example/page" in request.content
        raise Denied()

    with pytest.raises(Denied):
        await scrape("tavily", {"url": "https://private-name.example/page"}, {},
                     {"api_key": "fake"}, before_request=before_request)


def test_custom_fetch_denial_precedes_dns_and_send():
    sent = []
    seen = []
    resolved = []

    def resolver(_host, port, **_kwargs):
        resolved.append(_host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", port))]

    def authorize(request):
        seen.append(request)
        assert resolved == []
        raise Denied()

    with pytest.raises(Denied):
        _fetch_request("https://example.com/path?private=synthetic",
                       {"method": "POST", "headers": {"X-Data": "synthetic"}, "body": "synthetic-body"},
                       resolver=resolver, authorize=authorize,
                       transport=httpx.MockTransport(lambda request: sent.append(request)))
    assert sent == []
    assert resolved == []
    assert str(seen[0].url) == "https://example.com/path?private=synthetic"
    assert seen[0].headers["host"] == "example.com"
    assert seen[0].content == b"synthetic-body"


def test_custom_fetch_allow_pins_transport_after_logical_approval():
    observed = []
    outbound = []

    def resolver(host, port, **_kwargs):
        assert observed and observed[0].url.host == host
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", port))]

    def handler(request):
        outbound.append(request)
        return httpx.Response(200, text="ok")

    result = _fetch_request("https://example.com/path?x=1", {"method": "POST", "body": "body"},
                            resolver=resolver, authorize=observed.append,
                            transport=httpx.MockTransport(handler))
    assert result["ok"] is True
    assert str(observed[0].url) == "https://example.com/path?x=1"
    assert str(outbound[0].url) == "https://93.184.215.14/path?x=1"
    assert outbound[0].headers["host"] == observed[0].headers["host"] == "example.com"
    assert outbound[0].content == observed[0].content == b"body"


@pytest.mark.asyncio
async def test_custom_parent_bridge_approves_each_frame_and_preserves_denial(tmp_path, monkeypatch):
    # The worker fixture emits two already built requests and only emits a result
    # after receiving approval for both. It cannot make a network request.
    worker = tmp_path / "worker.py"
    worker.write_text("""
import base64, hashlib, json, sys
sys.stdin.buffer.readline()
for host in ('one.example', 'two.example'):
    frame = {'type':'request','method':'POST','url':'https://'+host+'/path',
             'headers':[['host',host]], 'body':base64.b64encode(host.encode()).decode(),
             'sni_hostname':host}
    line = json.dumps(frame, separators=(',', ':')).encode()
    sys.stdout.buffer.write(line+b'\\n'); sys.stdout.buffer.flush()
    assert json.loads(sys.stdin.buffer.readline()) == {'allow':hashlib.sha256(line).hexdigest()}
sys.stdout.write(json.dumps({'type':'result','ok':True,'result':{'items':[]}})+'\\n')
""")
    monkeypatch.setattr(search_scripts, "WORKER", worker)
    seen = []

    async def allow(request):
        seen.append((request.headers["host"], request.content))

    result = await search_scripts.execute_script({"search_script": "async function search(){}"},
                                                 {"query": "synthetic"}, {}, before_request=allow)
    assert result["items"] == []
    assert seen == [("one.example", b"one.example"), ("two.example", b"two.example")]
    seen.clear()

    async def before_request(request):
        seen.append((request.headers["host"], request.content))
        if len(seen) == 2:
            raise Denied("second destination")

    with pytest.raises(Denied, match="second destination"):
        await search_scripts.execute_script({"search_script": "async function search(){}"},
                                            {"query": "synthetic"}, {}, before_request=before_request)
    assert seen == [("one.example", b"one.example"), ("two.example", b"two.example")]
