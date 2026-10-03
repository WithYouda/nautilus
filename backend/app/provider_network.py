"""Bounded connection-only retry and content-free Provider diagnostics.

Use the standard HTTPX client/environment/transport unchanged. Only connection
establishment errors can retry: no HTTP response, write or read failure is replayed.
"""
from __future__ import annotations

import asyncio
import errno
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx

RETRY_DELAYS = (0.5, 1.0)
ERROR_TYPES = frozenset({
    'ConnectError', 'ConnectTimeout', 'ReadError', 'ReadTimeout', 'WriteError', 'WriteTimeout',
    'PoolTimeout', 'ProxyError', 'RemoteProtocolError', 'LocalProtocolError', 'ProtocolError',
    'TimeoutError', 'CancelledError', 'gaierror', 'SSLError', 'SSLCertVerificationError',
    'OSError', 'ConnectionRefusedError', 'ConnectionResetError', 'BrokenPipeError',
    'ProviderError', 'DomainError', 'ValueError', 'RuntimeError',
})


def error_details(error: BaseException) -> dict:
    """Classify the causal chain; never return exception messages or arguments."""
    chain, seen = [], set()
    pending = [error]
    while pending and len(chain) < 8:
        item = pending.pop(0)
        if id(item) in seen:
            continue
        seen.add(id(item))
        chain.append(item)
        pending.extend(value for value in (item.__cause__, item.__context__)
                       if isinstance(value, BaseException))
    def known(item):
        name = type(item).__name__
        return name if name in ERROR_TYPES else 'OtherError'
    result = {'error_type': known(error), 'cause_type': known(chain[-1])}
    number = next((item.errno for item in reversed(chain)
                   if isinstance(item, OSError) and isinstance(item.errno, int)), None)
    # HTTP core sometimes preserves only the OS error text, not its cause.
    # Recognize fixed phrases/codes internally, without copying any text to logs.
    text = ' '.join(str(item)[:2000].lower() for item in chain)
    if number is None:
        match = re.search(r'\[errno (-?\d{1,5})\]', text)
        number = int(match[1]) if match else None
    if number is not None:
        result['errno'] = number
    if isinstance(error, asyncio.CancelledError):
        code, stage = 'canceled', 'canceled'
    elif isinstance(error, TimeoutError):
        code, stage = 'timeout', 'overall'
    elif isinstance(error, (httpx.ReadError, httpx.ReadTimeout)):
        code, stage = ('read_timeout' if isinstance(error, httpx.ReadTimeout) else 'read_error'), 'read'
    elif isinstance(error, (httpx.WriteError, httpx.WriteTimeout)):
        code, stage = ('write_timeout' if isinstance(error, httpx.WriteTimeout) else 'write_error'), 'write'
    elif any(isinstance(item, socket.gaierror) for item in chain) or 'name resolution' in text or 'name or service not known' in text:
        code, stage = ('dns_temporary' if number == socket.EAI_AGAIN or 'temporary failure' in text else 'dns_not_found'), 'dns'
    elif any(isinstance(item, ssl.SSLCertVerificationError) for item in chain) or 'certificate_verify_failed' in text:
        code, stage = 'tls_certificate', 'tls'
    elif any(isinstance(item, ssl.SSLError) for item in chain) or '[ssl:' in text:
        code, stage = 'tls_error', 'tls'
    elif isinstance(error, httpx.ConnectTimeout):
        code, stage = 'connect_timeout', 'connect'
    elif isinstance(error, httpx.ConnectError):
        code = {errno.ECONNREFUSED: 'connection_refused', errno.ECONNRESET: 'connection_reset',
                errno.ENETUNREACH: 'network_unreachable', errno.EHOSTUNREACH: 'network_unreachable'}.get(number, 'connect_error')
        stage = 'connect'
    elif isinstance(error, httpx.ProxyError):
        code, stage = 'proxy_error', 'proxy'
    elif isinstance(error, httpx.PoolTimeout):
        code, stage = 'pool_timeout', 'pool'
    elif isinstance(error, httpx.ProtocolError):
        code, stage = 'protocol_error', 'protocol'
    else:
        code, stage = 'unknown_error', 'unknown'
    return {**result, 'code': code, 'error_stage': stage}


@dataclass
class ProviderDiagnostics:
    service: object
    owner: str
    run_id: str
    scope_kind: str
    provider_kind: str
    phase: str = 'initial_response'
    check: Callable[[], None] | None = None
    request_seq: int = 0
    last_request: dict = field(default_factory=dict)
    last_error: dict = field(default_factory=dict)

    def record(self, event, *, level='info', **fields):
        if self.service is not None:
            self.service.record(self.owner, module='ai', event=event, level=level,
                                run_id=self.run_id, scope_kind=self.scope_kind,
                                provider_kind=self.provider_kind, phase=self.phase, **fields)

    def finish(self, result, error=None, code=None):
        details = error_details(error) if error is not None else {}
        # Preserve a low-level cause when a ProviderError merely wraps it.
        if error is not None and details.get('code') == 'unknown_error':
            cause = error.__cause__
            if cause is not None:
                details = error_details(cause)
        if self.last_error and (isinstance(error, httpx.HTTPError) or isinstance(getattr(error, '__cause__', None), httpx.HTTPError)):
            details = dict(self.last_error)
        if code and details.get('code', 'unknown_error') == 'unknown_error':
            details['code'] = code
            details['error_stage'] = ('protocol' if code in {'protocol_error', 'invalid_response', 'output_truncated', 'reasoning_only'}
                                      else 'http' if code in {'auth_error', 'rate_limited', 'endpoint_not_found', 'upstream_error', 'request_error'}
                                      else 'unknown')
        self.record('ai.run_finished', level='error' if result == 'failed' else 'info',
                    **{**self.last_request, **details, 'result': result})


class _ObservedStream(httpx.AsyncByteStream):
    def __init__(self, stream, context, metadata, started):
        self.stream, self.context, self.metadata, self.started = stream, context, metadata, started

    async def __aiter__(self):
        try:
            async for chunk in self.stream:
                yield chunk
        except httpx.HTTPError as error:
            if self.context:
                details = error_details(error)
                # Headers have arrived. Even a misclassified transport exception
                # here is a response-read failure and must never cause a replay.
                if details['error_stage'] in {'connect', 'dns', 'tls'}:
                    details.update(code='read_error', error_stage='read')
                self.context.last_error = details
                self.context.record('provider.failed', level='error', **self.metadata, **details,
                                    duration_ms=round((time.monotonic() - self.started) * 1000))
            raise

    async def aclose(self):
        await self.stream.aclose()


class ProviderHTTPClient(httpx.AsyncClient):
    def __init__(self, *args, diagnostics: ProviderDiagnostics | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.diagnostics = diagnostics

    async def send(self, request, **kwargs):
        stream = kwargs.pop('stream', False)
        context = self.diagnostics
        maximum = len(RETRY_DELAYS) + 1
        if context:
            context.request_seq += 1
            context.last_error = {}
        started = time.monotonic()
        for attempt in range(1, maximum + 1):
            metadata = {'request_seq': context.request_seq if context else 1,
                        'attempt': attempt, 'max_attempts': maximum,
                        'target_host': request.url.host}
            if context:
                context.last_request = metadata
                if context.check:
                    context.check()
            try:
                response = await super().send(request, stream=True, **kwargs)
            except httpx.HTTPError as error:
                details = error_details(error)
                retry = (isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout))
                         and details['error_stage'] not in {'tls'} and attempt < maximum)
                if context:
                    context.last_error = details
                    context.record('provider.retry' if retry else 'provider.failed',
                                   level='warning' if retry else 'error',
                                   **metadata, **details,
                                   duration_ms=round((time.monotonic() - started) * 1000),
                                   **({'retry_delay_ms': round(RETRY_DELAYS[attempt - 1] * 1000)} if retry else {}))
                if not retry:
                    raise
                await asyncio.sleep(RETRY_DELAYS[attempt - 1])
                continue
            if context:
                context.last_request = {**metadata, 'status': response.status_code}
                context.last_error = {}
                if response.is_error:
                    status = response.status_code
                    code = 'http_auth' if status in (401, 403) else 'http_rate_limited' if status == 429 else 'http_server_error' if status >= 500 else 'http_client_error'
                    context.last_error = {'code': code, 'error_stage': 'http'}
                    context.record('provider.failed', level='error', **metadata,
                                   code=code, error_stage='http', status=status,
                                   duration_ms=round((time.monotonic() - started) * 1000))
                elif attempt > 1:
                    context.record('provider.recovered', **metadata, result='connected',
                                   status=response.status_code,
                                   duration_ms=round((time.monotonic() - started) * 1000))
            response.stream = _ObservedStream(response.stream, context, metadata, started)
            if not stream:
                try:
                    await response.aread()
                except BaseException:
                    await response.aclose()
                    raise
            return response
