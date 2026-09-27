import asyncio

import httpx
import pytest

from app.outbound import ApprovalError, OutboundApprovals, OutboundDenied, ProviderLease, RunOutbound
from app.search_service import SearchRun


def run(kind='tavily', parameters=None):
    return SearchRun({'mode': 'external', 'parameters': parameters or {}}, {},
                     {'id': 'synthetic-service', 'kind': kind, 'name': 'Synthetic', 'options': {'api_key': 'fake-private-key'}})


def request(query='private', **kwargs):
    return httpx.Request('POST', 'https://api.example/search',
                         headers={'Authorization': 'Bearer fake-private-key'}, json={'query': query, **kwargs})


def context(registry, **kwargs):
    return RunOutbound(registry, owner='owner', kind='conversation', scope_id='chat', run_id='run',
                       active=lambda: True, **kwargs)


@pytest.mark.asyncio
async def test_unknown_request_bound_to_owner_digest_and_one_live_call():
    registry = OutboundApprovals()
    task = asyncio.create_task(context(registry).hook(run(), {'query': 'private'}, fetch=False, call_id='call')(request()))
    await asyncio.sleep(0)
    pending = registry.list('owner', 'conversation', 'chat')[0]
    assert registry.list('other', 'conversation', 'chat') == []
    assert pending['body'] == '{"query":"private"}'
    assert 'fake-private-key' not in str(pending)
    with pytest.raises(ApprovalError):
        registry.decide('other', pending['id'], pending['digest'], 'approve')
    with pytest.raises(ApprovalError):
        registry.decide('owner', pending['id'], 'changed', 'approve')
    assert not task.done()
    registry.decide('owner', pending['id'], pending['digest'], 'approve')
    with pytest.raises(ApprovalError):
        registry.decide('owner', pending['id'], pending['digest'], 'approve')
    await task
    assert not registry.pending
    other = asyncio.create_task(context(registry).hook(run(), {'query': 'private'}, fetch=False, call_id='next')(request()))
    await asyncio.sleep(0)
    assert registry.list('owner', 'conversation', 'chat')[0]['digest'] != pending['digest']
    other.cancel()
    with pytest.raises(asyncio.CancelledError):
        await other
    assert not registry.pending


@pytest.mark.asyncio
async def test_public_grant_exact_parameters_only_then_redirect_is_new_request():
    registry = OutboundApprovals()
    outbound = context(registry, public_query='public words')
    hook = outbound.hook(run(), {'query': 'public words'}, fetch=False, call_id='call')
    await hook(request('public words'))
    assert not registry.pending
    redirect = asyncio.create_task(hook(httpx.Request('GET', 'https://api.example/changed?private=data')))
    await asyncio.sleep(0)
    assert len(registry.pending) == 1
    redirect.cancel()
    with pytest.raises(asyncio.CancelledError):
        await redirect
    for parameters in ({'query': 'different'}, {'query': 'public words', 'includeDomains': ['private.example']}):
        task = asyncio.create_task(outbound.hook(run(), parameters, fetch=False, call_id='extra')(request()))
        await asyncio.sleep(0)
        assert len(registry.pending) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_returned_url_exact_only_and_custom_script_never_bypasses_gate():
    registry = OutboundApprovals()
    outbound = context(registry, public_query='public')
    await outbound.hook(run(), {'query': 'public'}, fetch=False, call_id='search')(request('public'))
    outbound.received({'items': [{'url': 'https://example.com/result'}]}, fetch=False, call_id='search')
    outbound.received({'items': [{'url': 'https://example.com/private'}]}, fetch=False, call_id='manually-approved')
    assert 'https://example.com/private' not in outbound.public_urls
    await outbound.hook(run(), {'url': 'https://example.com/result'}, fetch=True, call_id='read')(request())
    for r, params, fetch in [(run(), {'url': 'https://example.com/result?secret=x'}, True),
                             (run('custom_js'), {'query': 'public'}, False)]:
        task = asyncio.create_task(outbound.hook(r, params, fetch=fetch, call_id='not-public')(request()))
        await asyncio.sleep(0)
        pending = registry.list('owner', 'conversation', 'chat')[0]
        registry.decide('owner', pending['id'], pending['digest'], 'deny')
        with pytest.raises(OutboundDenied):
            await task


@pytest.mark.asyncio
async def test_wait_pauses_generation_deadline_and_releases_provider_slot():
    registry = OutboundApprovals()
    semaphore = asyncio.Semaphore(1)
    async def execute():
        async with ProviderLease(semaphore) as lease:
            async with asyncio.timeout(.05) as timeout:
                await context(registry, timeout=timeout, lease=lease).hook(
                    run(), {'query': 'private'}, fetch=False, call_id='call')(request())
    task = asyncio.create_task(execute())
    await asyncio.sleep(.10)
    assert not task.done() and not semaphore.locked()
    pending = registry.list('owner', 'conversation', 'chat')[0]
    registry.decide('owner', pending['id'], pending['digest'], 'approve')
    await task
    assert semaphore._value == 1 and not registry.pending


@pytest.mark.asyncio
async def test_cancel_wait_does_not_double_release_slot_or_reuse_approval():
    registry = OutboundApprovals()
    semaphore = asyncio.Semaphore(1)
    async def execute():
        async with ProviderLease(semaphore) as lease:
            async with asyncio.timeout(.05) as timeout:
                await context(registry, timeout=timeout, lease=lease).hook(
                    run(), {'query': 'private'}, fetch=False, call_id='call')(request())
    task = asyncio.create_task(execute())
    await asyncio.sleep(.01)
    pending = registry.list('owner', 'conversation', 'chat')[0]
    registry.decide('owner', pending['id'], pending['digest'], 'cancel')
    with pytest.raises(asyncio.CancelledError):
        await task
    assert semaphore._value == 1 and not registry.pending
