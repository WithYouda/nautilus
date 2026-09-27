import asyncio
import json

import httpx
import pytest

from app.credentials import CredentialStore
from app.question_discussion import QuestionDiscussionService
from app.search_service import SearchService
from app.outbound import ApprovalError
from test_learning_domain_schema import learning_database  # noqa: F401
from test_verification_review import IDENTITY, attempt
from test_search_runtime import chat_stream, search_call, answer_chunk


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['cancel', 'purge'])
async def test_discussion_wait_cannot_send_after_cancel_or_source_purge(learning_database, tmp_path, action):
    verification, original = await attempt(learning_database)
    sent = []
    def handler(request):
        if str(request.url) == 'https://api.tavily.com/search':
            sent.append(request)
            return httpx.Response(200, json={'results': []})
        payload = json.loads(request.content)
        if payload.get('stream'):
            return httpx.Response(200, text=chat_stream(search_call('synthetic private discussion')))
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"history_query":null}'}}]})
    verification.transport = httpx.MockTransport(handler)
    service = QuestionDiscussionService(verification)
    search = SearchService(CredentialStore(tmp_path / 'credentials'), transport=verification.transport)
    search.save(IDENTITY['id'], {**search.get(IDENTITY['id']), 'services': [dict(id='test', kind='tavily',
        name='Synthetic', options={}, secret_updates={'api_key': 'fake'})], 'selected_service_id': 'test', 'max_requests': 1})
    service.chats.search_service = search
    discussion = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'approval')
    current = service.start(IDENTITY, discussion['id'], '解释合成作答', 'question', search={'mode': 'external', 'service_id': 'test'})
    turn = current['turns'][-1]
    task = service.tasks[turn['id']]
    for _ in range(100):
        pending = service.outbound.list(IDENTITY['id'], 'discussion', discussion['id'])
        if pending:break
        await asyncio.sleep(.01)
    else:pytest.fail('No pending discussion approval')
    item = pending[0]
    assert not sent
    if action == 'purge':
        verification.purge(IDENTITY, original['id'])
        with pytest.raises(ApprovalError):
            service.outbound.decide(IDENTITY['id'], item['id'], item['digest'], 'approve')
        service.outbound.list(IDENTITY['id'], 'discussion', discussion['id'])
    else:
        service.outbound.decide(IDENTITY['id'], item['id'], item['digest'], 'cancel')
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not sent and not service.outbound.pending
    saved = service.get(IDENTITY, discussion['id'])
    if action == 'purge':
        assert saved['purged'] and saved['turns'][-1]['status'] == 'purged'
    else:
        assert saved['turns'][-1]['reason'] == 'cancelled'
