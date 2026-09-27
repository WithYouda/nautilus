"""Single-use, run-bound approval of the HTTP request that will actually be sent.

Pending payloads live only in the running process. They never create a second
private-data archive; restart/cancellation invalidates them rather than resuming
an old authorization.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

import httpx

from .search_adapters import SearchError

NATIVE_PRIVATE_MESSAGE = '当前回答包含未明确允许公开的内容，无法核对模型内置搜索的外发请求。请手动选择外部搜索逐次确认，或关闭联网；本次未发送。'


class OutboundCanceled(asyncio.CancelledError):
    pass


class OutboundDenied(SearchError):
    def __init__(self):
        super().__init__('用户拒绝了这次外发；请使用现有资料回答，说明本次未检索，不要换词或换服务绕过拒绝。', 'outbound_denied')


class ApprovalError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def validate_public_query(value):
    if value is not None and not isinstance(value, str):
        raise SearchError('公开检索词格式不正确', 'invalid_query')
    return (value or '').strip()


def native_public_only(messages, public_query):
    """Only an explicitly public single user prompt, with no private context."""
    query = validate_public_query(public_query)
    users = [m for m in messages if m.get('role') != 'system']
    return bool(query and len(users) == 1 and users[0].get('role') == 'user'
                and users[0].get('content', '').strip() == query)


class ProviderLease:
    """An approval wait must not occupy one of the four active provider slots."""
    def __init__(self, semaphore):
        self.semaphore = semaphore
        self.held = False

    async def __aenter__(self):
        await self.semaphore.acquire()
        self.held = True
        return self

    async def __aexit__(self, *args):
        if self.held:
            self.semaphore.release()
            self.held = False

    def release(self):
        if self.held:
            self.semaphore.release()
            self.held = False

    async def reacquire(self):
        if not self.held:
            await self.semaphore.acquire()
            self.held = True


@dataclass
class Pending:
    owner: str
    kind: str
    scope_id: str
    view: dict
    future: asyncio.Future
    active: object


class OutboundApprovals:
    def __init__(self):
        self.pending: dict[str, Pending] = {}

    def list(self, owner, kind, scope_id):
        result = []
        for item in list(self.pending.values()):
            if (item.owner, item.kind, item.scope_id) != (owner, kind, scope_id):
                continue
            if not item.active():
                item.future.cancel()
            elif not item.future.done():
                result.append(copy.deepcopy(item.view))
        return result

    def decide(self, owner, request_id, digest, decision):
        item = self.pending.get(request_id)
        if item is None or item.owner != owner:
            raise ApprovalError('这次外发请求已失效，请读取最新状态。')
        if decision not in {'approve', 'deny', 'cancel'}:
            raise ApprovalError('外发决定不支持。', 422)
        if (item.future.done() or not item.active()
                or not isinstance(digest, str) or not hmac.compare_digest(item.view['digest'], digest)):
            raise ApprovalError('这次外发请求已变化或结束，请读取最新状态。')
        item.future.set_result(decision)
        return {'status': decision}

    async def wait(self, owner, kind, scope_id, view, active):
        if not active():
            raise asyncio.CancelledError()
        request_id = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = Pending(owner, kind, scope_id, {'id': request_id, **view}, future, active)
        try:
            decision = await future
            if not active():
                raise asyncio.CancelledError()
            if decision == 'cancel':
                raise OutboundCanceled()
            if decision == 'deny':
                raise OutboundDenied()
        finally:
            self.pending.pop(request_id, None)

    def close(self):
        for item in self.pending.values():
            item.future.cancel()
        self.pending.clear()


def _request_view(request, secrets):
    # Never display configured API credentials. All content-bearing headers,
    # full recipient URL and body remain reviewable, including Custom JS fetch.
    def clean(value):
        for secret in sorted((s for s in secrets if isinstance(s, str) and s), key=len, reverse=True):
            value = value.replace(secret, '[凭据已隐藏]')
        return value
    hidden = {'authorization', 'proxy-authorization', 'cookie', 'x-api-key', 'api-key', 'x-subscription-token'}
    headers = {key: '[凭据已隐藏]' if key.lower() in hidden else clean(value)
               for key, value in request.headers.items()}
    return dict(method=request.method, url=clean(str(request.url)), headers=headers,
                body=clean(request.content.decode('utf-8', errors='replace')))


class RunOutbound:
    def __init__(self, approvals, *, owner, kind, scope_id, run_id, active,
                 public_query=None, timeout=None, lease=None):
        self.approvals = approvals
        self.owner, self.kind, self.scope_id, self.run_id = owner, kind, scope_id, run_id
        self.active = active
        self.public_query = validate_public_query(public_query)
        self.timeout, self.lease = timeout, lease
        self.public_urls: set[str] = set()
        self.public_calls: set[str] = set()

    @asynccontextmanager
    async def waiting(self):
        remaining = None
        if self.timeout is not None and self.timeout.when() is not None:
            remaining = max(0, self.timeout.when() - asyncio.get_running_loop().time())
            self.timeout.reschedule(None)
        if self.lease:
            self.lease.release()
        try:
            yield
            if self.lease:
                await self.lease.reacquire()
        finally:
            if self.timeout is not None and remaining is not None:
                self.timeout.reschedule(asyncio.get_running_loop().time() + remaining)

    def hook(self, run, params, *, fetch, call_id):
        expected = dict(run.selection.get('parameters') or {}) if not fetch else {}
        expected['url' if fetch else 'query'] = params.get('url' if fetch else 'query')
        known = params == expected and (
            params.get('url') in self.public_urls if fetch else
            bool(self.public_query and params.get('query') == self.public_query))
        # Script requests and an extra model's configured prompt have additional
        # outbound content. Their actual HTTP requests always need review.
        auto = known and run.service['kind'] not in {'custom_js', 'grok'}
        calls = 0
        secrets = [value for key, value in run.service['options'].items()
                   if key in {'api_key', 'password'}]

        async def before_request(request: httpx.Request):
            nonlocal calls
            if not self.active():
                raise asyncio.CancelledError()
            calls += 1
            if auto and calls == 1:
                self.public_calls.add(call_id)
                return
            self.public_calls.discard(call_id)
            raw = json.dumps({'run_id': self.run_id, 'call_id': call_id,
                              'service_id': run.service['id'], 'method': request.method,
                              'url': str(request.url), 'headers': list(request.headers.multi_items()),
                              'body': request.content.hex(), 'sni_hostname': str(request.extensions.get('sni_hostname', ''))}, sort_keys=True, ensure_ascii=False)
            view = {**_request_view(request, secrets), 'digest': hashlib.sha256(raw.encode()).hexdigest(),
                    'run_id': self.run_id, 'call_id': call_id, 'service_name': run.service['name'],
                    'reason': '这次请求不在本轮明确公开的范围内。请核对实际接收方和拟发送内容。'}
            async with self.waiting():
                await self.approvals.wait(self.owner, self.kind, self.scope_id, view, self.active)
            if not self.active():
                raise asyncio.CancelledError()
        return before_request

    def received(self, result, *, fetch, call_id):
        # Exact URLs returned by this run's executed public-web tools may be read
        # without adding private parameters. Invented/modified URLs are not grants.
        if call_id not in self.public_calls:
            return
        self.public_urls.update(item['url'] for item in result.get('urls' if fetch else 'items', [])
                                if isinstance(item.get('url'), str))
