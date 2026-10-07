import asyncio
import httpx
import pytest

from app.content_resources import ensure_capacity
from app.provider_network import ProviderHTTPClient
from app.providers import ProviderError


def test_capacity_depends_on_available_memory_not_fixed_content_size(monkeypatch):
    monkeypatch.setattr('app.content_resources.available_memory', lambda: 1024 * 1024 * 1024)
    ensure_capacity(3 * 1024 * 1024)
    monkeypatch.setattr('app.content_resources.available_memory', lambda: 1024)
    with pytest.raises(ProviderError) as failure:
        ensure_capacity(129)
    assert failure.value.kind == 'resource_limit'


@pytest.mark.asyncio
async def test_continuous_small_chunks_cannot_evade_total_deadline():
    closed = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(.002)
                yield b'x'
        async def aclose(self):
            closed.append(True)
    async with ProviderHTTPClient(timeout=.03, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=Stream()))) as client:
        with pytest.raises(httpx.ReadTimeout):
            await client.get('https://synthetic.test')
    assert closed
