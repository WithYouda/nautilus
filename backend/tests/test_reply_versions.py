import json

import httpx
import pytest

from app.learning_domain import DomainError
from app.question_discussion import QuestionDiscussionService
from test_ai_conversations import make_client, authorize, configure_provider, create_task, start_conversation, read_sse, streaming_handler
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY
from test_verification_review import attempt


def test_regeneration_keeps_one_question_and_freezes_only_selected_ancestry(tmp_path):
    captured = []
    def handler(request):
        payload = json.loads(request.content)
        if payload.get('stream'):
            captured.append(payload['messages'])
            return httpx.Response(200, text='data: '+json.dumps({'choices':[{'delta':{'content':f'answer-{len(captured)}'}}]})+'\n\ndata: [DONE]\n\n')
        return streaming_handler(request)
    with make_client(tmp_path, handler) as client:
        authorize(client)
        configure_provider(client)
        conversation = start_conversation(client, create_task(client))
        url = f'/api/ai/conversations/{conversation}/messages'
        def send(content, key, **versions):
            response = client.post(url, json=dict(content=content, client_message_id=key, **versions))
            assert response.status_code == 202, response.text
            result = response.json()
            read_sse(client, result['run']['id'])
            return result['run']['response_message_id']
        first = send('first question', 'first')
        second = send('old followup', 'second', parent_message_id=first)
        before = client.get(f'/api/ai/conversations/{conversation}').json()['messages']
        regenerated = send('first question', 'regen', regenerate_message_id=first)
        assert [m['content'] for m in captured[-1][1:]] == ['first question']
        after = client.get(f'/api/ai/conversations/{conversation}').json()['messages']
        assert after[:4] == before
        assert len(after) == 5 and sum(m['role']=='user' for m in after) == 2
        assert after[-1]['parent_message_id'] == before[0]['id']
        duplicate = client.post(url, json=dict(content='first question', client_message_id='regen', regenerate_message_id=first)).json()
        assert duplicate['created'] is False and duplicate['run']['response_message_id'] == regenerated
        send('new followup', 'third', parent_message_id=regenerated)
        assert [m['content'] for m in captured[-1][1:]] == ['first question', 'answer-3', 'new followup']
        send('continue old path', 'fourth', parent_message_id=second)
        assert [m['content'] for m in captured[-1][1:]] == ['first question','answer-1','old followup','answer-2','continue old path']
        other = start_conversation(client, create_task(client))
        rejected = client.post(f'/api/ai/conversations/{other}/messages', json=dict(content='first question', client_message_id='foreign', regenerate_message_id=first))
        assert rejected.status_code == 400
        assert client.get(f'/api/ai/conversations/{other}').json()['messages'] == []
        assert client.post(url,json=dict(content='first question',client_message_id='regen',regenerate_message_id=regenerated)).status_code == 409


@pytest.mark.asyncio
async def test_discussion_versions_preserve_reasoning_ancestry_and_purge_all_versions(learning_database):
    verification, saved = await attempt(learning_database)
    service = QuestionDiscussionService(verification)
    discussion = service.create(IDENTITY, saved['id'], saved['latest_submission_id'], 'q1', 'versions')
    captured = []
    def handler(request):
        body = json.loads(request.content)
        if not body.get('stream'):
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"history_query":null}'}}]})
        captured.append(body['messages'])
        n = len(captured)
        return httpx.Response(200,text='data: '+json.dumps({'choices':[{'delta':{'content':f'reply-{n}','reasoning_content':f'thinking-{n}'}}]})+'\n\ndata: [DONE]\n\n')
    verification.transport = httpx.MockTransport(handler)
    async def send(content, key, **versions):
        current = service.start(IDENTITY, discussion['id'], content, key, **versions)
        turn = next(t for t in current['turns'] if t['request_key']==key)
        task = service.tasks.get(turn['id'])
        if task: await task
        return service.get(IDENTITY, discussion['id'])['turns'][-1]
    first = await send('first question', 'first')
    second = await send('old followup', 'second', parent_turn_id=first['id'])
    regenerated = await send('first question', 'regen', regenerate_turn_id=first['id'])
    assert regenerated['question_id'] == first['question_id']
    assert regenerated['parent_turn_id'] is None
    assert [m['content'] for m in captured[-1][2:]] == ['first question']
    assert service.get(IDENTITY, discussion['id'])['turns'][:2] == [first, second]
    assert regenerated['reasoning_content'] == 'thinking-3'
    await send('new followup', 'third', parent_turn_id=regenerated['id'])
    assert [m['content'] for m in captured[-1][2:]] == ['first question','reply-3','new followup']
    await send('old path', 'fourth', parent_turn_id=second['id'])
    assert [m['content'] for m in captured[-1][2:]] == ['first question','reply-1','old followup','reply-2','old path']
    duplicate = service.start(IDENTITY, discussion['id'],'first question','regen',regenerate_turn_id=first['id'])
    assert len(duplicate['turns']) == 5 and len(captured) == 5
    with pytest.raises(DomainError, match='idempotency_conflict'):
        service.start(IDENTITY, discussion['id'],'first question','regen',regenerate_turn_id=regenerated['id'])
    with pytest.raises(DomainError, match='verification_scope_invalid'):
        service.start(IDENTITY, discussion['id'],'first question','foreign',regenerate_turn_id='foreign')
    verification.purge(IDENTITY, saved['id'])
    erased = service.get(IDENTITY, discussion['id'])
    assert erased['purged'] and all(t['assistant_content'] is None and t['reasoning_content'] is None and t['user_content'] is None for t in erased['turns'])
    with pytest.raises(DomainError, match='artifact_not_eligible|not_found'):
        service.start(IDENTITY, discussion['id'],'first question','after-purge',regenerate_turn_id=first['id'])
    await service.shutdown()
