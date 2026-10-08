"""Burst delivery must resynchronize without losing content or failing a live run."""
import asyncio
import json
import httpx
import pytest
from app.ai_runtime import AiRunManager,RunState,sse_event
from app.provider_network import ProviderHTTPClient,ProviderIdleTimeout,ProviderTotalTimeout,ProviderDiagnostics

class Chats:
    def owned_run(self,*args):return {}

def payload(frame):
    return frame.splitlines()[0][7:], json.loads(frame.split('data: ',1)[1])

def manager_state():
    manager=AiRunManager(Chats());manager._coach_payload=lambda *_:{}
    state=RunState('run','chat','owner','answer',status='running')
    manager._runs['run']=state
    return manager,state

def burst(manager,state,text):
    for char in text:
        state.chunks.append(char)
        manager._broadcast(state,sse_event('delta',{'kind':'content','text':char}))

@pytest.mark.asyncio
async def test_repeated_bursts_replace_pending_deltas_and_continue_without_duplicates():
    manager,state=manager_state();stream=manager.stream('owner','run')
    assert payload(await anext(stream))[0]=='start'
    first='合成完整正文🙂'*80;burst(manager,state,first)
    event,data=payload(await anext(stream))
    assert event=='start' and data['status']=='running' and data['content']==first
    assert not state.finished
    burst(manager,state,'END')
    tail=[payload(await anext(stream))[1]['text'] for _ in range(3)]
    assert ''.join(tail)=='END'
    second='下一批'*100;burst(manager,state,second)
    event,data=payload(await anext(stream))
    assert event=='start' and data['content']==first+'END'+second
    state.finished=True;state.status='succeeded';manager._broadcast(state,None)
    event,data=payload(await anext(stream))
    assert event=='done' and data['content']==first+'END'+second
    await stream.aclose();assert not state.subscribers

@pytest.mark.asyncio
@pytest.mark.parametrize('status',['succeeded','failed','canceled'])
async def test_full_queue_does_not_lose_real_terminal_state(status):
    manager,state=manager_state();stream=manager.stream('owner','run')
    await anext(stream);burst(manager,state,'x'*600)
    state.finished=True;state.status=status;state.error_kind='synthetic_error';manager._broadcast(state,None)
    frames=[payload(frame) async for frame in stream]
    assert frames[-1][0]==('error' if status=='failed' else 'done')
    assert frames[-1][1]['status']==status and frames[-1][1]['content']=='x'*600
    assert all(data.get('kind')!='subscriber_lag' for _,data in frames)
    assert not state.subscribers

@pytest.mark.asyncio
async def test_continuous_data_can_outlive_idle_budget_without_repeating_request():
    calls=[]
    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(10):await asyncio.sleep(.01);yield b'x'
    def respond(request):calls.append(request);return httpx.Response(200,stream=Bytes())
    async with ProviderHTTPClient(timeout=.04,total_timeout=.5,transport=httpx.MockTransport(respond)) as client:
        result=await client.get('https://synthetic.example')
    assert result.content==b'x'*10 and len(calls)==1

@pytest.mark.asyncio
@pytest.mark.parametrize('stalled',[True,False])
async def test_idle_and_total_timeouts_remain_distinct(stalled):
    closed=[]
    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(.2 if stalled else .005)
                yield b'x'
        async def aclose(self):closed.append(True)
    diagnostic=ProviderDiagnostics(None,'synthetic','synthetic','conversation','openai_compatible')
    async with ProviderHTTPClient(timeout=.04,total_timeout=.09,diagnostics=diagnostic,transport=httpx.MockTransport(lambda request:httpx.Response(200,stream=Bytes()))) as client:
        with pytest.raises(ProviderIdleTimeout if stalled else ProviderTotalTimeout):
            await client.get('https://synthetic.example')
    assert closed
    assert diagnostic.last_error['code']==('idle_timeout' if stalled else 'timeout')
