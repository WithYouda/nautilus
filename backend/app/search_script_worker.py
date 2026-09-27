"""Isolated QuickJS worker. The JS realm only receives the limited fetch bridge."""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import math
import resource
import socket
import sys
from urllib.parse import urlsplit, urlunsplit

import httpx
import quickjs

MAX_FETCH_BYTES = 1024 * 1024
FORBIDDEN_HEADERS = {"host", "connection", "content-length", "transfer-encoding", "cookie", "set-cookie", "upgrade", "te", "trailer", "keep-alive"}


def _fetch_request(url, options, *, resolver=socket.getaddrinfo, transport=None, timeout=10.0, authorize=None):
    """Validate every DNS answer and pin the connection to a checked IP."""
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url):
        raise ValueError("invalid_url")
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as error:
        raise ValueError("invalid_url") from error
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("invalid_url")
    if not isinstance(options, dict):
        raise ValueError("invalid_options")
    method = str(options.get("method", "GET")).upper()
    if method not in {"GET", "POST"}:
        raise ValueError("invalid_method")
    supplied = options.get("headers", {})
    if not isinstance(supplied, dict) or len(supplied) > 32:
        raise ValueError("invalid_headers")
    headers = {}
    for key, value in supplied.items():
        if not isinstance(key, str) or not isinstance(value, str) or len(key) > 100 or len(value) > 4096:
            raise ValueError("invalid_headers")
        name = key.lower()
        if name in FORBIDDEN_HEADERS or name.startswith("proxy-") or name.startswith(":") or "\r" in key + value or "\n" in key + value:
            raise ValueError("invalid_headers")
        headers[key] = value
    body = options.get("body")
    if body is not None and (not isinstance(body, str) or len(body.encode("utf-8")) > MAX_FETCH_BYTES):
        raise ValueError("invalid_body")
    approval_error = None
    try:
        with httpx.Client(transport=transport, trust_env=False, follow_redirects=False, timeout=timeout) as client:
            logical = client.build_request(method, url, headers=headers, content=body,
                                           extensions={"sni_hostname": host})
            if authorize is not None:
                try:
                    authorize(logical)
                except Exception as error:
                    approval_error = error
                    raise
            # DNS lookup happens only after approval. Check every answer, then
            # connect to one checked IP while retaining the approved Host/SNI.
            try:
                literal = ipaddress.ip_address(host)
                addresses = [literal]
            except ValueError:
                try:
                    records = resolver(host, port, type=socket.SOCK_STREAM)
                    addresses = [ipaddress.ip_address(record[4][0]) for record in records]
                except (OSError, ValueError) as error:
                    raise ValueError("invalid_url") from error
            if not addresses or any(not address.is_global for address in addresses):
                raise ValueError("invalid_url")
            address = addresses[0]
            ip_host = f"[{address}]" if address.version == 6 else str(address)
            authority = f"{ip_host}:{port}"
            pinned = urlunsplit((parsed.scheme, authority, parsed.path or "/", parsed.query, ""))
            request = client.build_request(method, pinned, headers=logical.headers, content=logical.content,
                                           extensions={"sni_hostname": host})
            response = client.send(request, stream=True)
            try:
                if 300 <= response.status_code < 400:
                    raise ValueError("redirect_blocked")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_FETCH_BYTES:
                        raise ValueError("response_too_large")
                return {"status": response.status_code, "ok": 200 <= response.status_code < 300,
                        "body": bytes(raw).decode("utf-8", "replace")}
            finally:
                response.close()
    except httpx.HTTPError as error:
        if approval_error is not None:
            raise approval_error
        raise ValueError("fetch_failed") from error


def _execute(request, authorize=None):
    timeout = float(request["timeout"])
    resource.setrlimit(resource.RLIMIT_CPU, (max(1, math.ceil(timeout)), max(2, math.ceil(timeout) + 1)))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    context = quickjs.Context()
    context.set_memory_limit(64 * 1024 * 1024)
    context.set_max_stack_size(256 * 1024)
    remaining = int(request["max_requests"])

    def fetch_bridge(url, options_json):
        nonlocal remaining
        if remaining <= 0:
            raise ValueError("request_limit")
        remaining -= 1
        try:
            options = json.loads(options_json)
            result = _fetch_request(url, options, timeout=min(10.0, timeout), authorize=authorize)
            return json.dumps(result)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise ValueError("fetch_failed") from error

    context.add_callable("__nautilus_fetch", fetch_bridge)
    context.eval("""
        globalThis.console = {log(){}, info(){}, warn(){}, error(){}, debug(){}};
        globalThis.fetch = async (url, options = {}) => {
          const response = JSON.parse(__nautilus_fetch(String(url), JSON.stringify(options)));
          return {status: response.status, ok: response.ok,
            text: async () => response.body,
            json: async () => JSON.parse(response.body)};
        };
    """)
    context.eval(request["script"])
    argument = json.dumps(request["argument"], ensure_ascii=False)
    if request["mode"] == "search":
        invocation = f"search({argument}, {int(request['result_size'])})"
    else:
        invocation = f"scrape({argument})"
    context.eval("globalThis.__nautilus_state = 0; globalThis.__nautilus_value = '';" )
    context.eval("Promise.resolve(" + invocation + ").then("
                 "v => { __nautilus_value = JSON.stringify(v); __nautilus_state = 1; },"
                 "e => { __nautilus_state = 2; });")
    jobs = 0
    while context.eval("__nautilus_state") == 0:
        jobs += 1
        if jobs > 100000 or not context.execute_pending_job():
            raise ValueError("script_failed")
    if context.eval("__nautilus_state") != 1:
        raise ValueError("script_failed")
    result = context.eval("__nautilus_value")
    if not isinstance(result, str) or len(result.encode("utf-8")) > 900_000:
        raise ValueError("invalid_result")
    return json.loads(result)


def main():
    try:
        raw = sys.stdin.buffer.readline(300_002)
        if len(raw) > 300_000:
            raise ValueError("request_too_large")
        request = json.loads(raw)
        def authorize(outbound):
            frame = {"type": "request", "method": outbound.method, "url": str(outbound.url),
                     "headers": list(outbound.headers.multi_items()),
                     "body": base64.b64encode(outbound.content).decode("ascii"),
                     "sni_hostname": outbound.extensions.get("sni_hostname")}
            encoded = json.dumps(frame, ensure_ascii=False, separators=(",", ":")).encode()
            digest = hashlib.sha256(encoded).hexdigest()
            sys.stdout.buffer.write(encoded + b"\n")
            sys.stdout.buffer.flush()
            answer = json.loads(sys.stdin.buffer.readline(4096))
            if answer != {"allow": digest}:
                raise ValueError("request_denied")

        result = _execute(request, authorize=authorize if request.get("approval_bridge") else None)
        output = json.dumps({"type": "result", "ok": True, "result": result}, ensure_ascii=False, separators=(",", ":"))
        if len(output.encode("utf-8")) > 1_000_000:
            raise ValueError("result_too_large")
    except BaseException:
        output = '{"type":"result","ok":false}'
    sys.stdout.write(output + "\n")


if __name__ == "__main__":
    main()
