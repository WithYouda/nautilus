import asyncio
import json
import httpx
import pytest
from test_ai_conversations import make_client,authorize,configure_provider,create_task,start_conversation,read_sse,identity_id

@pytest.mark.parametrize('reasoning',[True,False])
def test_progress_is_real_and_first_response_timings_are_content_free(tmp_path,reasoning):
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(.05)
            if reasoning:
                yield b'data: {"choices":[{"delta":{"reasoning_content":"PRIVATE-SYNTHETIC-THOUGHT"}}]}\n\n'
                await asyncio.sleep(.03)
            yield b'data: {"choices":[{"delta":{"content":"PRIVATE-SYNTHETIC-ANSWER"},"finish_reason":"stop"}]}\n\n'
            yield b'data: [DONE]\n\n'
    def handler(request):
        if json.loads(request.content).get('stream'):return httpx.Response(200,stream=Stream())
        return httpx.Response(200,json={'choices':[{'message':{'content':'Synthetic title'}}]})
    with make_client(tmp_path,handler) as client:
        authorize(client);configure_provider(client)
        owner=identity_id(client);diagnostics=client.app.state.diagnostics;diagnostics.configure(owner,True)
        cid=start_conversation(client,create_task(client))
        result=client.post('/api/ai/conversations/'+cid+'/messages',json={'content':'PRIVATE-SYNTHETIC-QUESTION','client_message_id':'timing'})
        assert result.status_code==202
        run_id=result.json()['run']['id'];frames=read_sse(client,run_id)
        progress=[data['progress'] for event,data in frames if event=='progress' or event=='start' and data.get('progress')]
        phases=[p['phase'] for p in progress]
        assert 'waiting' in phases and 'content' in phases
        assert ('reasoning' in phases)==reasoning
        assert phases.index('waiting')<phases.index('content')
        timings=progress[-1]['timings']
        assert 0<=timings['generation_started']<=timings['provider_requested']<=timings['provider_first_chunk']<=timings['first_content']
        if reasoning:assert timings['provider_first_chunk']<=timings['first_reasoning']<=timings['first_content']
        assert client.post('/api/ai/runs/'+run_id+'/display-timing',json={'phase':'content','elapsed_ms':120,'accepted_ms':20,'subscription_delay_ms':2}).status_code==200
        assert client.post('/api/ai/runs/'+run_id+'/display-timing',json={'phase':'content','elapsed_ms':-1,'accepted_ms':20,'subscription_delay_ms':2}).status_code==422
        entries=diagnostics.read(owner)['entries'];wire=json.dumps(entries)
        assert all(x not in wire for x in ('PRIVATE-SYNTHETIC-THOUGHT','PRIVATE-SYNTHETIC-ANSWER','PRIVATE-SYNTHETIC-QUESTION'))
        assert any(row['event']=='stream.first_visible' and row['duration_ms']==120 for row in entries)
