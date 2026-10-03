"""Selected local knowledge uses the same model loop without private replay copies."""
import asyncio
import json

import httpx
import pytest

from app.outbound import OutboundApprovals, RunOutbound
from app.providers import OpenAICompatibleProvider
from app.credentials import CredentialStore
from app.materials import MaterialService
from app.obsidian import ObsidianService
from app.question_discussion import QuestionDiscussionService
from app.search_runtime import external_stream, merge_knowledge_reference
from app.search_service import SearchRun
from test_ai_conversations import authorize, configure_provider, create_task, make_client, read_sse, start_conversation
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY
from test_verification_review import attempt
from test_function_tools import cfg
from test_search_runtime import answer_chunk, chat_stream


PRIVATE = 'SYNTHETIC-KB-PRIVATE-LINE'


def local_call(name='search_knowledge_base', params=None, call_id='kb-1'):
    return {'delta': {'tool_calls': [{'index': 0, 'id': call_id, 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(params or {'query': 'matrix'})}}]},
        'finish_reason': 'tool_calls'}


class LocalKnowledge:
    tools = [{'name': 'search_knowledge_base', 'description': 'Read selected vault',
              'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}},
                             'required': ['query']}}]
    policy = '仅按需要读取明确选中的本地知识库。'
    budget = 4

    def __init__(self, *, revoke=False):
        self.used = False
        self.revoked = False
        self.revoke = revoke

    def check(self):
        if self.revoked:
            raise asyncio.CancelledError()

    async def invoke(self, name, params):
        self.used = True
        self.revoked = self.revoke
        return {'content': json.dumps({'text': PRIVATE}),
                'result': {'knowledge_references': [{'version_id': 'v1', 'start_line': 2,
                                                    'end_line': 2, 'material_id': 'm1'}]}}


class WebService:
    def __init__(self):
        self.sent = []

    def _catalog(self, kind):
        return {'search_parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}},
                                     'required': ['query']}, 'supports_scrape': False}

    async def invoke(self, run, params, *, fetch=False, before_request=None):
        assert before_request is not None, 'Actual web requests must keep the A2 hook'
        request = httpx.Request('POST', 'https://public.example/search', json=params)
        await before_request(request)
        self.sent.append(request)
        return {'retrieved_at': '2026-10-03T00:00:00Z',
                'items': [{'url': 'https://public.example/result', 'title': 'Public', 'text': 'public fact'}]}


def web_run():
    return SearchRun({'mode': 'external', 'parameters': {}}, {'max_requests': 1},
                     {'id': 'web', 'kind': 'bing', 'name': 'Public search', 'options': {}})


@pytest.mark.asyncio
async def test_web_off_local_loop_keeps_raw_results_only_in_live_provider_context():
    payloads, traces = [], []
    def handler(request):
        body = json.loads(request.content)
        payloads.append(body)
        event = local_call() if len(payloads) == 1 else answer_chunk('From local evidence【资料1】')
        return httpx.Response(200, text=chat_stream(event))
    provider = OpenAICompatibleProvider(cfg('openai_compatible'), httpx.MockTransport(handler))
    chunks = [chunk async for chunk in external_stream(None, None,
        [{'role': 'user', 'content': 'Explain matrix'}], provider, traces.append, knowledge=LocalKnowledge())]
    assert len(payloads) == 2
    assert [tool['function']['name'] for tool in payloads[0]['tools']] == ['search_knowledge_base']
    assert PRIVATE in json.dumps(payloads[1])
    assert PRIVATE not in json.dumps([chunk.text for chunk in chunks])
    assert not any(chunk.kind == 'model_turn' for chunk in chunks)
    assert all(trace['status'] == 'off' and not trace['items'] for trace in traces)


@pytest.mark.asyncio
async def test_same_loop_supports_local_and_public_web_with_independent_budgets():
    payloads, traces = [], []
    def handler(request):
        body = json.loads(request.content)
        payloads.append(body)
        events = [local_call(), local_call('search_web', {'query': 'public matrix'}, 'web-1'), answer_chunk()]
        return httpx.Response(200, text=chat_stream(events[len(payloads) - 1]))
    web = WebService()
    outbound = RunOutbound(OutboundApprovals(), owner='owner', kind='conversation', scope_id='scope',
        run_id='run', active=lambda: True, public_query='public matrix')
    provider = OpenAICompatibleProvider(cfg('openai_compatible'), httpx.MockTransport(handler))
    chunks = [chunk async for chunk in external_stream(web, web_run(),
        [{'role': 'user', 'content': 'Compare sources'}], provider, traces.append,
        knowledge=LocalKnowledge(), outbound=outbound)]
    assert len(web.sent) == 1 and PRIVATE not in web.sent[0].content.decode()
    assert len(payloads) == 3
    assert traces[-1]['status'] == 'succeeded'
    assert [entry['call_id'] for entry in traces[-1]['requests']] == ['web-1']
    assert not any(chunk.kind == 'model_turn' for chunk in chunks)


@pytest.mark.asyncio
async def test_strict_union_offers_local_evidence_and_explains_web_restriction():
    payloads, traces = [], []
    def handler(request):
        body = json.loads(request.content)
        payloads.append(body)
        return httpx.Response(200, text=chat_stream(local_call() if len(payloads) == 1 else answer_chunk()))
    web = WebService()
    provider = OpenAICompatibleProvider(cfg('openai_compatible'), httpx.MockTransport(handler))
    await consume(external_stream(web, web_run(), [{'role': 'system', 'content': 'SELECTED-MANUAL-NOTE'},
        {'role': 'user', 'content': 'Explain'}], provider, traces.append,
        knowledge=LocalKnowledge(), strict_only=True))
    assert not web.sent
    assert all([tool['function']['name'] for tool in body['tools']] == ['search_knowledge_base']
               for body in payloads)
    assert 'SELECTED-MANUAL-NOTE' in json.dumps(payloads[0])
    assert traces[-1]['status'] == 'not_used' and '未开放联网工具' in traces[-1]['message']


async def consume(stream):
    return [chunk async for chunk in stream]


@pytest.mark.asyncio
async def test_revocation_after_local_read_blocks_result_and_provider_continuation():
    payloads, emitted = [], []
    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, text=chat_stream(local_call()))
    provider = OpenAICompatibleProvider(cfg('openai_compatible'), httpx.MockTransport(handler))
    with pytest.raises(asyncio.CancelledError):
        async for chunk in external_stream(None, None, [{'role': 'user', 'content': 'Explain'}],
                provider, lambda _: None, knowledge=LocalKnowledge(revoke=True)):
            emitted.append(chunk)
    assert len(payloads) == 1
    assert not any(chunk.kind in ('tool_end', 'model_turn') for chunk in emitted)
    assert PRIVATE not in json.dumps([chunk.text for chunk in emitted])


def test_registration_keeps_manual_selection_and_all_excerpt_dependencies_without_bodies():
    scope = {'mode': 'only', 'version_ids': ['manual'], 'material_ids': ['manual-group'],
             'materials': [{'id': 'manual', 'material_id': 'manual-group'}]}
    version = {'id': 'v1', 'material_id': 'm1', 'content': PRIVATE, 'version': 1}
    reference = {'version_id': 'v1', 'material_id': 'm1', 'start_line': 2, 'end_line': 2,
                 'sha256': 'digest', 'retrieved_at': 'now'}
    registered = merge_knowledge_reference(scope, version, reference)
    registered = merge_knowledge_reference(registered, version, {**reference, 'start_line': 3, 'end_line': 3})
    assert registered['selection_version_ids'] == ['manual']
    assert registered['version_ids'] == ['manual', 'v1']
    assert registered['material_ids'] == ['manual-group', 'm1']
    assert [ref['marker'] for ref in registered['knowledge_references']] == ['【资料2】', '【资料2】']
    assert PRIVATE not in json.dumps(registered)
    assert scope['version_ids'] == ['manual']


def knowledge_selection(connection, *, mode='only', version_ids=None):
    return {'mode': mode, 'version_ids': version_ids or [], 'knowledge_base': {
        'kind': 'obsidian_local', 'connection_id': connection['connection_id'],
        'connection_revision': connection['revision']}}


def knowledge_handler(payloads, observe=None):
    def handler(request):
        body = json.loads(request.content)
        payloads.append(body)
        if not body.get('stream'):
            return httpx.Response(200, json={'choices': [{'message': {'content': 'Synthetic title'}}]})
        has_result = any(message.get('role') == 'tool' for message in body['messages'])
        if has_result and observe:
            observe(body)
        event = answer_chunk('Local answer【资料1】【资料2】') if has_result else local_call()
        return httpx.Response(200, text=chat_stream(event))
    return handler


def test_conversation_registers_immutable_evidence_before_provider_and_purge_scrubs_history(tmp_path):
    payloads = []
    holder = {}
    def observe(body):
        client = holder['client']
        row = client.app.state.database.fetchone("SELECT config_snapshot_json FROM ai_run WHERE status='running' LIMIT 1")
        scope = json.loads(row[0])['source_scope']
        assert scope['knowledge_references'] and len(scope['material_ids']) == 2
    with make_client(tmp_path, knowledge_handler(payloads, observe)) as client:
        holder['client'] = client
        authorize(client)
        configure_provider(client)
        cid = start_conversation(client, create_task(client))
        root = tmp_path / 'runtime-vault'
        root.mkdir()
        note = root / 'matrix.md'
        note.write_text('matrix\n' + PRIVATE + '\n', encoding='utf-8')
        connection = client.put('/api/obsidian/connection',
            json={'root_path': str(root), 'expected_revision': None}).json()['connection']
        material_url = f'/api/materials/conversation/{cid}'
        manual = client.post(material_url, json={'title': 'Manual', 'content': 'SYNTHETIC-MANUAL-ONLY'}).json()
        selection = knowledge_selection(connection, version_ids=[manual['id']])
        def send(key):
            response = client.post(f'/api/ai/conversations/{cid}/messages', json={
                'content': 'Explain matrix', 'client_message_id': key, 'source_scope': selection,
                'search': {'mode': 'off'}})
            assert response.status_code == 202, response.text
            run = response.json()['run']
            read_sse(client, run['id'])
            saved = client.app.state.database.fetchone('SELECT status,config_snapshot_json FROM ai_run WHERE id=?', (run['id'],))
            assert saved['status'] == 'succeeded', saved['config_snapshot_json']
            return run, json.loads(saved['config_snapshot_json'])
        first, snapshot = send('first-kb')
        scope = snapshot['source_scope']
        assert scope['selection_version_ids'] == [manual['id']]
        assert len(scope['version_ids']) == 2
        evidence = scope['knowledge_references'][0]
        assert evidence['marker'] == '【资料2】'
        assert evidence['material_id'] in scope['material_ids']
        assert str(root) not in json.dumps(snapshot)
        assert PRIVATE not in json.dumps(snapshot) and 'model_turn' not in snapshot
        assert client.get('/api/materials/library').json()['versions'] == []
        assert PRIVATE in json.dumps(payloads[-1])
        assert 'SYNTHETIC-MANUAL-ONLY' in json.dumps(payloads[0])
        fork = client.post(f'/api/ai/conversations/{cid}/branches',
            json={'message_id': first['response_message_id'], 'request_key': 'kb-fork'}).json()
        assert fork['branch_source_scope']['version_ids'] == [manual['id']]
        assert fork['branch_source_scope']['knowledge_base'] == selection['knowledge_base']
        inherited = client.get(f"/api/materials/conversation/{fork['conversation']['id']}").json()['versions']
        assert evidence['version_id'] in [version['id'] for version in inherited]
        note.write_text('matrix\nSYNTHETIC-KB-NEW-VERSION\n', encoding='utf-8')
        second, changed = send('second-kb')
        later = changed['source_scope']['knowledge_references'][0]
        assert later['material_id'] == evidence['material_id']
        assert later['version_id'] != evidence['version_id']
        assert PRIVATE not in json.dumps(payloads[-2])  # No old raw protocol tool replay.
        rows = client.app.state.learning.database.fetchall('SELECT id,content FROM learning_task_material WHERE material_id=?',
                                                           (evidence['material_id'],))
        assert len(rows) == 2 and any(PRIVATE in row['content'] for row in rows)
        purged = client.post(material_url + '/' + evidence['material_id'] + '/purge')
        assert purged.status_code == 200 and purged.json()['purge']['status'] == 'complete'
        for run in (first, second):
            saved = client.app.state.database.fetchone('SELECT config_snapshot_json FROM ai_run WHERE id=?', (run['id'],))[0]
            assert 'knowledge_references' not in saved and 'generation_trace' not in saved and 'model_turn' not in saved
            assert 'Local answer' not in json.dumps(read_sse(client, run['id']))


@pytest.mark.asyncio
async def test_discussion_web_off_registers_private_local_evidence_and_keeps_strict_union(learning_database, tmp_path):
    verification, original = await attempt(learning_database)
    service = QuestionDiscussionService(verification)
    materials = MaterialService(service.learning, service.chats)
    service.chats.materials = materials
    obsidian = ObsidianService(CredentialStore(tmp_path / 'runtime-credentials'), materials)
    materials.obsidian = obsidian
    root = tmp_path / 'discussion-vault'
    root.mkdir()
    (root / 'matrix.md').write_text('matrix\n' + PRIVATE + '\n', encoding='utf-8')
    connection = obsidian.connect(IDENTITY['id'], str(root), None)
    discussion = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'knowledge')
    manual = materials.create(IDENTITY, 'discussion', discussion['id'], title='Manual', content='DISCUSSION-MANUAL')
    payloads = []
    def observe(body):
        row = learning_database.fetchone("SELECT provider_snapshot_json FROM learning_discussion_turn WHERE status='running' LIMIT 1")
        scope = json.loads(row[0])['source_scope']
        assert scope['knowledge_references'] and len(scope['material_ids']) == 2
    verification.transport = httpx.MockTransport(knowledge_handler(payloads, observe))
    result = await service.send(IDENTITY, discussion['id'], 'Explain matrix', 'kb',
        source_scope=knowledge_selection(connection, version_ids=[manual['id']]), search={'mode': 'off'})
    turn = result['turns'][-1]
    assert turn['status'] == 'succeeded', turn
    assert len(payloads) == 2  # Strict union bypasses the unrelated history planner.
    scope = turn['source_scope']
    assert scope['selection_version_ids'] == [manual['id']] and len(scope['version_ids']) == 2
    assert scope['knowledge_references'][0]['marker'] == '【资料2】'
    assert PRIVATE in json.dumps(payloads[-1])
    assert '合成原始作答' not in json.dumps(payloads, ensure_ascii=False)
    stored = json.loads(learning_database.fetchone('SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?',
                                                   (turn['id'],))[0])
    assert 'model_turn' not in stored and PRIVATE not in json.dumps(stored)
    assert materials.library(IDENTITY)['versions'] == []
    from app.discussion_branches import create_branch
    fork = create_branch(service, IDENTITY, discussion['id'], turn['id'], 'kb-fork')
    assert fork['branch_source_scope']['version_ids'] == [manual['id']]
    assert fork['branch_source_scope']['knowledge_base'] == knowledge_selection(connection)['knowledge_base']
    assert scope['knowledge_references'][0]['version_id'] in materials.inherited_versions(IDENTITY['id'], 'discussion', fork['id'])


def test_disconnect_between_local_read_and_delivery_prevents_provider_continuation(tmp_path, monkeypatch):
    from app.knowledge import KnowledgeRun
    invoke = KnowledgeRun.invoke
    payloads = []
    async def disconnect_after_read(run, name, params):
        result = await invoke(run, name, params)
        run.service.disconnect(run.owner, run.selection['connection_revision'])
        return result
    monkeypatch.setattr(KnowledgeRun, 'invoke', disconnect_after_read)
    with make_client(tmp_path, knowledge_handler(payloads)) as client:
        authorize(client)
        configure_provider(client)
        cid = start_conversation(client, create_task(client))
        root = tmp_path / 'disconnect-vault'
        root.mkdir()
        (root / 'matrix.md').write_text('matrix\n' + PRIVATE, encoding='utf-8')
        connection = client.put('/api/obsidian/connection',
            json={'root_path': str(root), 'expected_revision': None}).json()['connection']
        response = client.post(f'/api/ai/conversations/{cid}/messages', json={
            'content': 'Explain matrix', 'client_message_id': 'disconnect',
            'source_scope': knowledge_selection(connection), 'search': {'mode': 'off'}})
        assert response.status_code == 202, response.text
        run = response.json()['run']
        read_sse(client, run['id'])
        saved = client.app.state.database.fetchone('SELECT status,config_snapshot_json FROM ai_run WHERE id=?', (run['id'],))
        assert saved['status'] == 'failed' and len(payloads) == 1
        assert PRIVATE not in saved['config_snapshot_json'] and 'model_turn' not in saved['config_snapshot_json']
        # Already committed evidence remains an honest saved snapshot on disconnect.
        assert json.loads(saved['config_snapshot_json'])['source_scope']['knowledge_references']
