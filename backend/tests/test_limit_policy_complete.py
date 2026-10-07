"""Owner-approved complete content with protocol, scope and run-budget safeguards."""
import json
import httpx
import pytest

from app.providers import ProviderConfig, ProviderError, build_provider
from app.native_providers import GoogleProvider
from app.teaching_json import JsonTeachingDecoder
from app.search_runtime import _add_results, _tool_result
from app.knowledge import KnowledgeRun
from test_model_control import RecordingProvider, make_client, authorize, configure_provider, make_scope, send
from test_knowledge_scope import setup as knowledge_setup
from test_background_coach import coach, end, check, finish  # noqa: F401
from test_learning_paths import seed, draft, confirm, path


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_entire_authorized_history_reaches_next_turn(tmp_path, kind):
    provider = RecordingProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        identifier, _, _ = make_scope(client, provider, kind)
        for index in range(13):
            send(client, kind, identifier, f'full-history-{index}', content=f'SYNTHETIC-HISTORY-{index}')
        actual = [p for p in provider.payloads if p.get('stream')][-1]['messages']
        for index in range(13):
            assert any(m.get('role') == 'user' and m.get('content') == f'SYNTHETIC-HISTORY-{index}' for m in actual)


@pytest.mark.parametrize('kind,size', [('conversation', 1_010_000), ('discussion', 33_000)])
def test_full_reply_is_persisted_beyond_old_character_limit(tmp_path, kind, size):
    answer = 'x' * size + 'END-OF-ANSWER'
    class LongProvider(RecordingProvider):
        def __call__(self, request):
            payload = json.loads(request.content)
            if payload.get('stream'):
                event = {'choices':[{'delta':{'content':answer}, 'finish_reason':'stop'}]}
                return httpx.Response(200, text='data: ' + json.dumps(event) + '\n\ndata: [DONE]\n\n')
            return super().__call__(request)
    provider = LongProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        identifier, _, _ = make_scope(client, provider, kind)
        result = send(client, kind, identifier, 'long-reply')
        field = 'content' if kind == 'conversation' else 'assistant_content'
        assert result[field] == answer


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai_compatible','openai_responses','google','anthropic'])
async def test_actual_context_window_error_is_explicit_and_private(kind):
    provider = build_provider(ProviderConfig(base_url='https://synthetic.example/v1', model='synthetic', api_key='synthetic',
        provider_kind=kind, max_output_tokens=64000), httpx.MockTransport(lambda request: httpx.Response(400,
        json={'error':{'code':'context_length_exceeded','message':'SYNTHETIC_PRIVATE_ECHO'}})))
    with pytest.raises(ProviderError) as result:
        await provider.generate_text([{'role':'user','content':'synthetic input'}])
    assert result.value.kind == 'context_limit'
    assert 'SYNTHETIC_PRIVATE_ECHO' not in str(result.value)
    assert '未静默截断' in str(result.value)


@pytest.mark.asyncio
async def test_large_native_json_response_is_complete():
    text = 'x' * (2 * 1024 * 1024 + 9) + 'END'
    provider = GoogleProvider(ProviderConfig(base_url='https://synthetic.example/v1', model='synthetic', api_key='synthetic', provider_kind='google'),
        httpx.MockTransport(lambda request: httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':text}]}}]})))
    assert await provider.generate_text([{'role':'user','content':'synthetic'}]) == text


def test_large_metadata_before_reply_does_not_hide_public_text():
    private = '仅用于校验的辅助字段' * 4000
    wire = json.dumps({'teaching':{'synthetic':private},'reply':'完整公开回答🙂','token':'token'}, ensure_ascii=False)
    decoder = JsonTeachingDecoder('token')
    public = ''.join(decoder.feed(wire[i:i+71]) for i in range(0,len(wire),71))
    decoder.finish()
    assert public == '完整公开回答🙂' and private not in public
    assert decoder.proposal() == {'synthetic':private}


def test_search_read_and_saved_trace_keep_all_returned_content():
    text = '完整网页原文' * 14000 + 'END'
    result = {'retrieved_at':'2026-10-07T00:00:00Z', 'urls':[
        {'url':f'https://example.test/{i}', 'content':text,'metadata':{'title':str(i)}} for i in range(22)]}
    trace = {'items':[]}; _add_results(trace,result,True)
    body = json.loads(_tool_result(result,True))
    assert len(body['pages']) == len(trace['items']) == 22
    assert body['pages'][-1]['content'] == trace['items'][-1]['text'] == text
    assert not trace['items'][-1]['content_truncated']


def test_configurable_budgets_are_finite_and_frozen_for_accepted_knowledge_run(client, tmp_path):
    _, _, chat, identity, selection, _ = knowledge_setup(client,tmp_path)
    service = client.app.state.search
    settings = service.get(identity['id'])
    services = [{**item,'secret_updates':{}} for item in settings['services']]
    saved = service.save(identity['id'], {**settings,'services':services,'max_requests':12,'knowledge_max_requests':9})
    assert saved['max_requests'] == 12 and saved['knowledge_max_requests'] == 9
    material = client.app.state.materials
    frozen = material.freeze(identity,'conversation',chat,selection)
    run = KnowledgeRun(material,identity,'conversation',chat,frozen,active=lambda:True,register=lambda *_:None)
    service.save(identity['id'], {**saved,'services':services,'max_requests':18,'knowledge_max_requests':15})
    assert run.budget == 9 and '9' in run.policy
    for bad in [0,-1,True,None]:
        from app.search_adapters import SearchError
        with pytest.raises(SearchError):
            service.save(identity['id'], {**service.get(identity['id']),'services':services,'knowledge_max_requests':bad})


def test_large_route_keeps_edges_and_rejects_cycle(client):
    _, plan_id, first, second = seed(client)
    nodes = [{'id':f'n{i}','title':f'Stage {i}','action_ids':[first['action_id']] if i == 0 else [],'outcome_ids':[]} for i in range(102)]
    edges = [{'source':f'n{i}','target':f'n{i+1}'} for i in range(101)]
    value, body = draft(client,plan_id,first,second,nodes=nodes,edges=edges,entry_node_id='n0',current_node_id='n0')
    confirm(client,plan_id,value)
    assert len(path(client,plan_id)['versions'][0]['nodes']) == 102
    body['edges'] = edges + [{'source':'n101','target':'n0'}]
    response = client.post(f'/api/learning/plans/{plan_id}/path/drafts',json=body)
    assert response.status_code == 422


def test_authorized_coach_reads_all_long_artifacts_and_revocation_still_blocks(coach):
    ctx = coach
    from app.core.commands import StartSession, SaveTextArtifact, EndSession
    from app.learning_domain import Principal
    principal=Principal.user(ctx['identity']['id']);core=ctx['service'].learning.core;action=ctx['item']['action_id']
    for index in range(5):
        version=lambda:ctx['db'].fetchone('SELECT version FROM learning_action WHERE id=?',(action,))[0]
        session=core.execute(principal,StartSession(delegation_id=ctx['item']['delegation_id'],expected_version=version()),f'long-start-{index}')['id']
        core.execute(principal,SaveTextArtifact(session_id=session,content=f'START-{index}'+('合成原始作品' * 1200)+f'END-{index}',expected_version=version()),f'long-art-{index}')
        core.execute(principal,EndSession(session_id=session,disposition='interrupted',expected_version=version()),f'long-end-{index}')
    ctx['target_kind']='permission_review'
    candidate=finish(ctx,check(ctx,'request-long')['run']['id'])['candidates'][0]
    fields=candidate['target']['permission_request'];client=ctx['client']
    permission=client.post('/api/learning/agent/permission-requests',json={k:fields[k] for k in ('purpose','target_id','content_granularity','ttl_seconds','request_key')}).json()
    request_id=permission['id']
    assert client.post(f'/api/learning/agent/permission-requests/{request_id}/approve').status_code == 200
    result=finish(ctx,check(ctx,'read-long',permission_candidate_id=candidate['id'],permission_request_id=request_id)['run']['id'])
    assert result['run']['status'] == 'succeeded'
    authorization=result['inputs']['authorization']
    assert len(authorization['artifacts']) == 5 and not authorization['limited']
    assert all(len(a['content'])>4000 and a['content'].endswith('END-'+a['content'].split('START-')[1][0]) for a in authorization['artifacts'])
    assert client.post(f'/api/learning/agent/permission-requests/{request_id}/revoke',json={'reason':'Synthetic revocation'}).status_code == 200
    denied=client.post('/api/learning/coach/checks',json={'scope':'global','trigger':'manual','request_key':'after-revoke','permission_candidate_id':candidate['id'],'permission_request_id':request_id})
    assert denied.status_code == 403


def test_stage_can_add_a_task_after_thirty_associations(client):
    from test_plan_organization import task, get
    from test_learning_paths import path_task_body
    _, plan_id, first, second = seed(client)
    linked = [task(client,get(client,plan_id),f'linked-{i}')['action_id'] for i in range(31)]
    value, _ = draft(client,plan_id,first,second,
        nodes=[{'id':'entry','title':'Many tasks','action_ids':linked,'outcome_ids':[]}],
        edges=[],entry_node_id='entry',current_node_id='entry')
    confirm(client,plan_id,value)
    body = path_task_body(path(client,plan_id),node_id='entry',request_key='after-thirty')
    response = client.post(f'/api/learning/plans/{plan_id}/path/tasks',json=body)
    assert response.status_code == 201, response.text
    result = response.json()
    current = next(v for v in result['path']['versions'] if v['id'] == result['path']['adopted_version_id'])
    assert current['nodes'][0]['action_ids'] == linked + [result['action_id']]


def test_graph_suggestions_accept_more_than_thirty_selected_outcomes(client):
    from test_outcome_graph import node, configure, wait_run, BASE
    from test_evidence_claims import authorize as authorize_graph
    authorize_graph(client); configure(client)
    ids = [node(client,f'Synthetic outcome {i}') for i in range(31)]
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"candidates":[]}'},'finish_reason':'stop'}]})
    client.app.state.outcome_graph.transport = httpx.MockTransport(handler)
    response = client.post(BASE+'/suggestions',json={'outcome_ids':ids,'request_key':'large-selection'})
    assert response.status_code == 201, response.text
    run = wait_run(client,response.json()['id'])
    assert run['status'] == 'succeeded', run
    assert run['outcome_ids'] == ids
    assert len(requests) == 1 and 'max_tokens' not in requests[0]
