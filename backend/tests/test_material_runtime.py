import asyncio
import json
import time

import httpx
import pytest

from app.materials import MaterialService
from app.question_discussion import QuestionDiscussionService
from test_ai_conversations import make_client, authorize, configure_provider, create_task, start_conversation, read_sse, SlowHandler
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY
from test_verification_review import attempt


def body_response(text):
    return httpx.Response(200, text='data: ' + json.dumps({'choices': [{'delta': {'content': text}}]}) + '\n\ndata: [DONE]\n\n')


def test_material_scope_versions_isolate_context_tools_and_replay(tmp_path):
    calls = []
    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        return body_response('合成回答【资料1】')
    with make_client(tmp_path, handler) as client:
        authorize(client)
        configure_provider(client)
        cid = start_conversation(client, create_task(client))
        base = f'/api/materials/conversation/{cid}'
        material = client.post(base, json={'title': '文本', 'content': 'PRIVATE-V1-苹果'}).json()
        selection = {'mode': 'only', 'version_ids': [material['id']]}
        def send(key, text, scope, **extra):
            response = client.post(f'/api/ai/conversations/{cid}/messages', json={
                'content': text, 'client_message_id': key, 'source_scope': scope, **extra})
            assert response.status_code == 202, response.text
            run = response.json()['run']
            read_sse(client, run['id'])
            return run
        # Prior conversational/private protocol content is not in the new scope.
        with client.app.state.database.transaction() as connection:
            connection.execute("UPDATE conversation SET title_generation_status='idle' WHERE id=?", (cid,))
        old = send('old', 'OUTSIDE-SCOPE-PRIVATE', {'mode': 'unspecified', 'version_ids': []})
        with client.app.state.database.transaction() as connection:
            connection.execute("UPDATE ai_run SET config_snapshot_json=json_set(config_snapshot_json,'$.model_turn',?) WHERE id=?",
                               ('OUTSIDE-PROTOCOL-PRIVATE', old['id']))
        first = send('m1', '依据资料说明', selection, search={'mode': 'native'})
        first_payload = json.dumps(calls[-1], ensure_ascii=False)
        assert 'PRIVATE-V1-苹果' in first_payload
        assert 'OUTSIDE-SCOPE-PRIVATE' not in first_payload and 'OUTSIDE-PROTOCOL-PRIVATE' not in first_payload
        assert '矩阵乘法' not in first_payload  # Task-plan context is outside this explicit scope.
        assert 'web_search_options' not in calls[-1] and 'tools' not in calls[-1]
        replay = client.post(f'/api/ai/conversations/{cid}/messages', json={
            'content': '依据资料说明', 'client_message_id': 'm1', 'source_scope': selection,
            'search': {'mode': 'native'}})
        assert replay.status_code == 202 and not replay.json()['created']
        changed = client.post(f'/api/ai/conversations/{cid}/messages', json={
            'content': '依据资料说明', 'client_message_id': 'm1',
            'source_scope': {'mode': 'reference', 'version_ids': [material['id']]},
            'search': {'mode': 'native'}})
        assert changed.status_code == 409
        second_material = client.post(base, json={'title': '文本修订', 'content': 'PRIVATE-V2-梨',
            'material_id': material['material_id']}).json()
        second = send('m2', '依据资料说明', {'mode': 'only', 'version_ids': [second_material['id']]},
                      regenerate_message_id=first['response_message_id'])
        assert 'PRIVATE-V1-苹果' not in json.dumps(calls[-1], ensure_ascii=False)
        assert 'PRIVATE-V2-梨' in json.dumps(calls[-1], ensure_ascii=False)
        detail = client.get(f'/api/ai/conversations/{cid}').json()
        replies = [m for m in detail['messages'] if m['role'] == 'assistant']
        assert replies[1]['source_scope']['version_ids'] == [material['id']]
        assert replies[2]['source_scope']['materials'][0]['cited'] is True
        independent = send('m3', '现在独立讨论', {'mode': 'unspecified', 'version_ids': []}, parent_message_id=second['response_message_id'])
        assert 'PRIVATE-V' not in json.dumps(calls[-1], ensure_ascii=False)
        result = client.post(base + '/' + material['material_id'] + '/purge')
        assert result.status_code == 200, result.text
        assert result.json()['purge']['status'] == 'complete'
        assert client.get(base + '/' + material['material_id'] + '/purge').json()['status'] == 'complete'
        replayed = json.dumps(read_sse(client, first['id']), ensure_ascii=False)
        assert '合成回答' not in replayed  # Purge also invalidates completed in-memory replay.
        detail = client.get(f'/api/ai/conversations/{cid}').json()
        assert next(m for m in detail['messages'] if m['id'] == first['response_message_id'])['content'] == ''
        assert next(m for m in detail['messages'] if m['id'] == independent['response_message_id'])['content']
        assert client.post(f'/api/ai/conversations/{cid}/messages', json={
            'content': '再次请求', 'client_message_id': 'm4', 'source_scope': selection}).status_code == 400


def test_material_purge_cancels_active_provider_and_stream_cache(tmp_path):
    with make_client(tmp_path, SlowHandler(chunks=200, delay=.01)) as client:
        authorize(client)
        configure_provider(client)
        cid = start_conversation(client, create_task(client))
        base = f'/api/materials/conversation/{cid}'
        material = client.post(base, json={'title': '资料', 'content': '合成私文'}).json()
        result = client.post(f'/api/ai/conversations/{cid}/messages', json={
            'content': '解释', 'client_message_id': 'active',
            'source_scope': {'mode': 'only', 'version_ids': [material['id']]}}).json()
        rid = result['run']['id']
        for _ in range(100):
            if client.app.state.ai_runs._runs[rid].text:
                break
            time.sleep(.005)
        assert client.app.state.ai_runs._runs[rid].text
        result = client.post(base + '/' + material['material_id'] + '/purge')
        assert result.json()['purge']['status'] == 'complete'
        assert '块' not in json.dumps(read_sse(client, rid), ensure_ascii=False)
        assert client.app.state.ai_runs._runs[rid].text == ''


@pytest.mark.asyncio
async def test_discussion_only_scope_skips_planner_original_feedback_and_old_protocol(learning_database):
    verification, original = await attempt(learning_database)
    service = QuestionDiscussionService(verification)
    material_service = MaterialService(service.learning, service.chats)
    service.chats.materials = material_service
    current = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'materials')
    material = material_service.create(IDENTITY, 'discussion', current['id'], title='资料', content='PRIVATE-DISCUSSION')
    calls = []
    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload.get('stream'), 'Selected materials must not invoke the history planner'
        return body_response('资料说明【资料1】')
    verification.transport = httpx.MockTransport(handler)
    result = await service.send(IDENTITY, current['id'], '本资料是什么意思', 'one',
        source_scope={'mode': 'only', 'version_ids': [material['id']]}, search={'mode': 'native'})
    assert result['turns'][-1]['status'] == 'succeeded'
    assert len(calls) == 1
    prompt = json.dumps(calls[0], ensure_ascii=False)
    assert 'PRIVATE-DISCUSSION' in prompt and '合成原始作答' not in prompt
    assert '参考解法' not in calls[0]['messages'][-1]['content']
    assert 'tools' not in calls[0] and 'web_search_options' not in calls[0]
    assert result['turns'][-1]['source_scope']['materials'][0]['cited'] is True
    verification.purge(IDENTITY, original['id'])
    assert learning_database.fetchone('SELECT content FROM learning_task_material WHERE id=?', (material['id'],))[0] is None
