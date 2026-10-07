"""Omitted output budgets must not silently become fixed adapter defaults."""
import json
from types import SimpleNamespace
import httpx
import pytest
from app.providers import OpenAICompatibleProvider, ProviderConfig, ProviderError
from app.native_providers import OpenAIResponsesProvider, GoogleProvider, AnthropicProvider
from test_native_providers import config


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,cls,body', [
    ('openai_compatible', OpenAICompatibleProvider, {'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}),
    ('openai_responses', OpenAIResponsesProvider, {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{"ok":true}'}]}]}),
    ('google', GoogleProvider, {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"ok":true}'}]}}]}),
])
async def test_none_omits_native_output_field(kind, cls, body):
    seen=[]
    def handler(request):
        payload=json.loads(request.content);seen.append(payload)
        return httpx.Response(200,json=body)
    provider=cls(config(kind),httpx.MockTransport(handler))
    assert await provider.generate_text([{'role':'user','content':'synthetic'}],max_tokens=None,json_mode=True)=='{"ok":true}'
    assert not {'max_tokens','max_completion_tokens','max_output_tokens'} & seen[0].keys()
    assert 'maxOutputTokens' not in seen[0].get('generationConfig',{})
    assert 'tools' not in seen[0]


@pytest.mark.asyncio
async def test_claude_uses_reported_model_maximum_including_thinking():
    seen=[]
    def handler(request):
        if request.method=='GET':
            assert request.url.path.endswith('/models/model-test')
            return httpx.Response(200,json={'id':'model-test','max_tokens':64000})
        payload=json.loads(request.content);seen.append(payload)
        return httpx.Response(200,json={'stop_reason':'end_turn','content':[{'type':'text','text':'{"ok":true}'}]})
    settings=config('anthropic');settings.reasoning_parameters_json=json.dumps({'thinking':{'type':'enabled','budget_tokens':2048}})
    provider=AnthropicProvider(settings,httpx.MockTransport(handler))
    await provider.generate_text([{'role':'user','content':'synthetic'}],max_tokens=None,json_mode=True)
    assert seen[0]['max_tokens']==64000 and seen[0]['thinking']['budget_tokens']==2048
    assert 'tools' not in seen[0]


@pytest.mark.asyncio
async def test_claude_missing_model_maximum_does_not_guess_a_replacement():
    seen=[]
    def handler(request):
        seen.append(request.method)
        return httpx.Response(200,json={'id':'model-test'})
    provider=AnthropicProvider(config('anthropic'),httpx.MockTransport(handler))
    with pytest.raises(ProviderError,match='未退回固定额度'):
        await provider.generate_text([{'role':'user','content':'synthetic'}],max_tokens=None)
    assert seen==['GET']


@pytest.mark.parametrize('stale_binding', [False, True])
def test_comparison_uses_only_bound_discovery_maximum_without_model_lookup(tmp_path, stale_binding):
    from app.reasoning_control import prepare_configuration, persist_configuration
    from test_ai_conversations import FAKE_API_KEY
    from test_branch_comparisons import ComparisonProvider, fork, draft
    from test_model_control import make_client, authorize, configure_provider, new_chat, send

    class ClaudeComparisonProvider(ComparisonProvider):
        def __init__(self):
            super().__init__()
            self.claude_requests = []

        def __call__(self, request):
            if 'x-api-key' not in request.headers:
                return super().__call__(request)
            self.claude_requests.append(request)
            if request.method == 'GET':
                return httpx.Response(200, json={'id': 'model-test', 'max_tokens': 96000})
            payload = json.loads(request.content)
            sources = json.loads(payload['messages'][-1]['content'])
            refs = [dict(side=side, id=items[-1]['id'], quote=items[-1]['text'][:80])
                    for side, items in sources.items()]
            result = {'cards': [dict(topic='Synthetic', relation='complement', conclusion='Synthetic comparison', references=refs)]}
            return httpx.Response(200, json={'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': json.dumps(result)}]})

    provider = ClaudeComparisonProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client)
        configure_provider(client)
        left = new_chat(client)
        first = send(client, 'conversation', left, 'first')
        right = fork(client, 'conversation', left, first)
        send(client, 'conversation', right, 'different', content='Synthetic alternative')
        chats = client.app.state.conversations
        owner = client.app.state.auth.ensure_local_identity()['id']
        profile = chats.create_provider(owner, display_name='Synthetic Claude',
            base_url='https://claude.example.test/v1', model='model-test', api_key=FAKE_API_KEY,
            api_protocol='anthropic', is_default=True)
        model = dict(chats.database.fetchone('SELECT * FROM provider_model WHERE provider_profile_id=?', (profile['id'],)))
        prepared, _ = prepare_configuration(profile, model, 'anthropic', metadata={'max_output_tokens': 64000})
        if stale_binding:
            caps = json.loads(prepared['capabilities_json'])
            caps['reasoning_discovery']['binding']['model'] = 'previous-model'
            prepared['capabilities_json'] = json.dumps(caps)
        persist_configuration(chats, owner, profile['id'], model['id'], prepared)
        _, config_value, snapshot = chats.model_control.runtime(owner, 'conversation', left)
        assert config_value.provider_kind == 'anthropic'
        assert snapshot['model']['capabilities']['max_output_tokens'] is None
        assert snapshot['model']['capabilities']['reasoning_discovery']['metadata']['max_output_tokens'] == 64000

        assert len(draft(client, 'conversation', left, right)['cards']) == 1
        methods = [request.method for request in provider.claude_requests]
        assert methods == (['GET', 'POST'] if stale_binding else ['POST'])
        posted = json.loads(provider.claude_requests[-1].content)
        assert posted['max_tokens'] == (96000 if stale_binding else 64000)
