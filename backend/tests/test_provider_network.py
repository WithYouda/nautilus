"""Connection retries cannot replay delivered data, ignore cancellation or leak content."""
import asyncio
import errno
import json
import socket
import ssl
import time

import httpx
import pytest

from app.diagnostics import DiagnosticService
from app.provider_network import ProviderDiagnostics, ProviderHTTPClient, error_details
from app.providers import ProviderConfig, build_provider
from app.credentials import CredentialStore
from app.materials import MaterialService
from app.obsidian import ObsidianService
from app.question_discussion import QuestionDiscussionService
from test_ai_conversations import authorize, configure_provider, create_task, make_client, read_sse, start_conversation, streaming_handler
from test_knowledge_runtime import knowledge_handler, knowledge_selection
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY
from test_verification_review import attempt as verification_attempt


@pytest.fixture(autouse=True)
def immediate_backoff(monkeypatch):
    monkeypatch.setattr('app.provider_network.RETRY_DELAYS', (0, 0))


def context(tmp_path):
    service = DiagnosticService(tmp_path / 'diagnostics')
    service.configure('owner', True)
    return ProviderDiagnostics(service, 'owner', 'synthetic-run', 'conversation', 'openai_compatible')


@pytest.mark.parametrize('kind', ['openai_compatible', 'openai_responses', 'google', 'anthropic'])
async def test_retry_recovery_in_all_provider_clients_has_safe_correlated_logs(tmp_path, kind):
    calls = []
    def handler(request):
        calls.append(request.content)
        if len(calls) == 1:
            raise httpx.ConnectError('private-exception-marker') from socket.gaierror(socket.EAI_AGAIN, 'private-dns-marker')
        return httpx.Response(200, json={'ok': True})
    cfg = ProviderConfig(base_url='https://provider.example/private-url?key=private-query-marker',
                         model='test', api_key='sk-private-marker', provider_kind=kind)
    provider = build_provider(cfg, transport=httpx.MockTransport(handler))
    diagnostic = context(tmp_path)
    provider.diagnostics = diagnostic
    async with provider._client() as client:
        response = await client.post(cfg.base_url, headers=provider._headers(), json={'note': 'private-note-marker'})
    assert response.status_code == 200 and len(calls) == 2 and calls[0] == calls[1]
    rows = diagnostic.service.read('owner')['entries']
    assert [r['event'] for r in rows] == ['provider.retry', 'provider.recovered']
    assert rows[0]['code'] == 'dns_temporary' and rows[0]['errno'] == socket.EAI_AGAIN
    assert rows[0]['target_host'] == 'provider.example' and rows[0]['run_id'] == 'synthetic-run'
    assert rows[0]['attempt'] == 1 and rows[1]['attempt'] == 2 and rows[0]['max_attempts'] == 3
    assert rows[1]['result'] == 'connected'
    serialized = json.dumps(rows)
    for secret in ('private-exception-marker', 'private-dns-marker', 'private-url', 'private-query-marker', 'sk-private-marker', 'private-note-marker'):
        assert secret not in serialized
    diagnostic.service.close()


async def test_exhaustion_and_deterministic_tls_failure_are_logged_without_extra_requests(tmp_path):
    for tls, expected in ((False, 3), (True, 1)):
        calls = []
        def handler(request):
            calls.append(request)
            cause = ssl.SSLCertVerificationError(1, 'private cert') if tls else ConnectionRefusedError(errno.ECONNREFUSED, 'private host')
            raise httpx.ConnectError('private wrapper') from cause
        diagnostic = context(tmp_path)
        async with ProviderHTTPClient(transport=httpx.MockTransport(handler), diagnostics=diagnostic) as client:
            with pytest.raises(httpx.ConnectError):
                await client.post('https://provider.example', json={'private': True})
        assert len(calls) == expected
        rows = diagnostic.service.read('owner')['entries']
        assert rows[-1]['event'] == 'provider.failed' and rows[-1]['attempt'] == expected
        assert rows[-1]['code'] == ('tls_certificate' if tls else 'connection_refused')
        diagnostic.service.clear('owner')
        diagnostic.service.close()


@pytest.mark.parametrize('failure', [httpx.ReadTimeout, httpx.WriteError, httpx.RemoteProtocolError])
async def test_non_connect_failure_is_not_retried(tmp_path, failure):
    calls = []
    def handler(request):
        calls.append(request)
        raise failure('private exception')
    diagnostic = context(tmp_path)
    async with ProviderHTTPClient(transport=httpx.MockTransport(handler), diagnostics=diagnostic) as client:
        with pytest.raises(failure):
            await client.post('https://provider.example')
    assert len(calls) == 1
    assert [r['event'] for r in diagnostic.service.read('owner')['entries']] == ['provider.failed']
    diagnostic.service.close()


async def test_http_rejection_is_not_retried_or_logged_as_recovery(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectTimeout('private timeout')
        return httpx.Response(401, json={'error': 'private server response'})
    diagnostic = context(tmp_path)
    async with ProviderHTTPClient(transport=httpx.MockTransport(handler), diagnostics=diagnostic) as client:
        response = await client.post('https://provider.example')
    assert response.status_code == 401 and len(calls) == 2
    rows = diagnostic.service.read('owner')['entries']
    assert [r['event'] for r in rows] == ['provider.retry', 'provider.failed']
    assert rows[-1]['code'] == 'http_auth' and rows[-1]['status'] == 401
    assert 'private server response' not in json.dumps(rows)
    diagnostic.service.close()


@pytest.mark.parametrize('stream', [True, False])
async def test_failure_after_response_headers_never_replays_even_if_misclassified_connect_error(tmp_path, stream):
    calls = []
    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'private partial body'
            raise httpx.ConnectError('misclassified body error')
    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=Broken())
    diagnostic = context(tmp_path)
    async with ProviderHTTPClient(transport=httpx.MockTransport(handler), diagnostics=diagnostic) as client:
        with pytest.raises(httpx.ConnectError) as caught:
            if stream:
                async with client.stream('POST', 'https://provider.example') as response:
                    async for _ in response.aiter_bytes():
                        pass
            else:
                await client.post('https://provider.example')
    assert len(calls) == 1
    diagnostic.finish('failed', caught.value, 'network_error')
    rows = diagnostic.service.read('owner')['entries']
    assert rows[-1]['code'] == 'read_error' and rows[-1]['error_stage'] == 'read'
    diagnostic.service.close()


async def test_cancel_and_deadline_interrupt_backoff(monkeypatch, tmp_path):
    monkeypatch.setattr('app.provider_network.RETRY_DELAYS', (30, 30))
    for mode in ('cancel', 'deadline'):
        entered, calls = asyncio.Event(), []
        def handler(request):
            calls.append(request)
            entered.set()
            raise httpx.ConnectError('temporary') from socket.gaierror(socket.EAI_AGAIN, 'private DNS')
        diagnostic = context(tmp_path)
        async with ProviderHTTPClient(transport=httpx.MockTransport(handler), diagnostics=diagnostic) as client:
            if mode == 'cancel':
                task = asyncio.create_task(client.post('https://provider.example'))
                await entered.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError) as caught:
                    await task
            else:
                with pytest.raises(TimeoutError) as caught:
                    async with asyncio.timeout(.03):
                        await client.post('https://provider.example')
        assert len(calls) == 1
        diagnostic.finish('canceled' if mode == 'cancel' else 'failed', caught.value)
        final = diagnostic.service.read('owner')['entries'][-1]
        assert final['code'] == ('canceled' if mode == 'cancel' else 'timeout')
        assert final['error_stage'] == ('canceled' if mode == 'cancel' else 'overall')
        diagnostic.service.close()


async def test_grant_is_checked_again_before_retry(tmp_path):
    calls, valid = [], [True]
    def guard():
        if not valid[0]:
            raise asyncio.CancelledError()
    def handler(request):
        calls.append(request)
        valid[0] = False
        raise httpx.ConnectTimeout('synthetic')
    diagnostic = context(tmp_path)
    diagnostic.check = guard
    async with ProviderHTTPClient(transport=httpx.MockTransport(handler), diagnostics=diagnostic) as client:
        with pytest.raises(asyncio.CancelledError):
            await client.post('https://provider.example')
    assert len(calls) == 1
    diagnostic.service.close()


def test_conversation_continuation_retries_without_reexecuting_local_tool_and_logs_final_success(tmp_path):
    payloads, failures = [], []
    base = knowledge_handler(payloads)
    def handler(request):
        data = json.loads(request.content)
        if data.get('stream') and any(m.get('role') == 'tool' for m in data['messages']) and not failures:
            failures.append(True)
            raise httpx.ConnectError('private failure body') from socket.gaierror(socket.EAI_AGAIN, 'private DNS')
        return base(request)
    with make_client(tmp_path, handler) as client:
        authorize(client)
        configure_provider(client)
        client.put('/api/diagnostics/settings', json={'enabled': True})
        root = tmp_path / 'vault'
        root.mkdir()
        (root / 'matrix.md').write_text('matrix\nprivate evidence marker\n')
        connection = client.put('/api/obsidian/connection', json={'root_path': str(root), 'expected_revision': None}).json()['connection']
        chat = start_conversation(client, create_task(client))
        response = client.post(f'/api/ai/conversations/{chat}/messages', json={
            'content': 'Explain matrix', 'client_message_id': 'retry',
            'source_scope': knowledge_selection(connection), 'search': {'mode': 'off'}})
        assert response.status_code == 202, response.text
        run = response.json()['run']
        read_sse(client, run['id'])
        row = client.app.state.database.fetchone('SELECT status,config_snapshot_json FROM ai_run WHERE id=?', (run['id'],))
        assert row['status'] == 'succeeded'
        snap = json.loads(row['config_snapshot_json'])
        assert len(snap['source_scope']['knowledge_references']) == 1
        assert len([p for p in snap['generation_trace']['parts'] if p['type'] == 'tool']) == 1
        logs = [r for r in client.get('/api/diagnostics').json()['entries'] if r.get('run_id') == run['id']]
        assert [r['event'] for r in logs] == ['provider.retry', 'provider.recovered', 'ai.run_finished']
        assert logs[0]['phase'] == 'tool_continuation' and logs[0]['request_seq'] == 2
        assert logs[-1]['result'] == 'succeeded'
        assert 'private evidence marker' not in json.dumps(logs) and 'private failure body' not in json.dumps(logs)


async def test_discussion_final_failure_keeps_stage_and_reason_in_diagnostics(learning_database, tmp_path):
    verification, original = await verification_attempt(learning_database)
    service = QuestionDiscussionService(verification)
    materials = MaterialService(service.learning, service.chats)
    service.chats.materials = materials
    logs = DiagnosticService(tmp_path / 'diagnostics')
    logs.configure(IDENTITY['id'], True)
    service.chats.diagnostics = logs
    obsidian = ObsidianService(CredentialStore(tmp_path / 'credentials'), materials)
    materials.obsidian = obsidian
    root = tmp_path / 'vault'
    root.mkdir()
    (root / 'matrix.md').write_text('matrix\nprivate discussion evidence\n')
    connection = obsidian.connect(IDENTITY['id'], str(root), None)
    discussion = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'retry-log')
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ConnectTimeout('private timeout')
    verification.transport = httpx.MockTransport(handler)
    result = await service.send(IDENTITY, discussion['id'], 'Explain matrix', 'first',
                                source_scope=knowledge_selection(connection), search={'mode': 'off'})
    assert result['turns'][0]['status'] == 'failed' and len(calls) == 3
    rows = logs.read(IDENTITY['id'])['entries']
    assert [r['event'] for r in rows] == ['provider.retry', 'provider.retry', 'provider.failed', 'ai.run_finished']
    assert rows[-1]['phase'] == 'initial_response' and rows[-1]['error_stage'] == 'connect'
    assert rows[-1]['code'] == 'connect_timeout' and rows[-1]['attempt'] == 3
    assert rows[-1]['result'] == 'failed' and rows[-1]['scope_kind'] == 'discussion'
    logs.close()


def test_title_retry_and_final_outcome_are_logged_separately_from_answer(tmp_path):
    attempts = []
    def handler(request):
        if json.loads(request.content).get('stream') is False:
            attempts.append(True)
            if len(attempts) == 1:
                raise httpx.ConnectError('private title error')
            return httpx.Response(200, json={'choices': [{'message': {'content': 'Synthetic title'}}]})
        return streaming_handler(request)
    with make_client(tmp_path, handler) as client:
        authorize(client)
        configure_provider(client)
        client.put('/api/diagnostics/settings', json={'enabled': True})
        chat = start_conversation(client, create_task(client))
        run = client.post(f'/api/ai/conversations/{chat}/messages', json={
            'content': 'Private title inputs', 'client_message_id': 'title-log'}).json()['run']
        read_sse(client, run['id'])
        for _ in range(40):
            rows = client.get('/api/diagnostics').json()['entries']
            title = [r for r in rows if r.get('phase') == 'title']
            if title and title[-1]['event'] == 'ai.run_finished':
                break
            time.sleep(.01)
        assert len(attempts) == 2
        assert [r['event'] for r in title] == ['provider.retry', 'provider.recovered', 'ai.run_finished']
        assert title[-1]['result'] == 'succeeded' and title[-1]['run_id'] != run['id']
        assert 'Private title inputs' not in json.dumps(rows) and 'private title error' not in json.dumps(rows)
