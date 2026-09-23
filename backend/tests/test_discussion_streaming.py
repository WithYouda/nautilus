import asyncio
import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from app.learning_domain import DomainError
from app.question_discussion import QuestionDiscussionService
from app.learning_production import upgrade_learning_database
from app.learning_storage import open_learning_database
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY, response_transport
from test_verification_review import attempt


class HeldStream(httpx.AsyncByteStream):
    def __init__(self, release, *, fail=False):
        self.release = release
        self.fail = fail
        self.closed = False

    async def __aiter__(self):
        yield self.frame('合成思考第一步。', 'reasoning_content')
        yield self.frame('合成思考第二步。', 'reasoning_content')
        yield self.frame('合成第一段')
        await self.release.wait()
        if self.fail:
            raise httpx.ReadError('synthetic-private-error')
        yield self.frame('，合成第二段')
        yield b'data: [DONE]\n\n'

    @staticmethod
    def frame(text, kind='content'):
        return ('data: ' + json.dumps({'choices': [{'delta': {kind: text}}]}) + '\n\n').encode()

    async def aclose(self):
        self.closed = True


async def running_discussion(db, *, fail=False):
    verification, current = await attempt(db)
    service = QuestionDiscussionService(verification)
    discussion = service.create(IDENTITY, current['id'], current['latest_submission_id'], 'q1', 'thread')
    release = asyncio.Event()
    stream = HeldStream(release, fail=fail)
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if payload.get('stream'):
            return httpx.Response(200, stream=stream)
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"history_query":null}'}}]})

    verification.transport = httpx.MockTransport(handler)
    started = service.start(IDENTITY, discussion['id'], '合成问题', 'message')
    assert started['turns'][0]['status'] == 'running'
    assert started['turns'][0]['user_content'] == '合成问题'
    assert not calls  # Immediate acknowledgement, before any model request.
    for _ in range(100):
        snapshot = service.get(IDENTITY, discussion['id'])
        if snapshot['turns'][0]['assistant_content']:
            break
        await asyncio.sleep(.001)
    else:
        pytest.fail('first provider chunk was not persisted while generation was running')
    return service, verification, current, snapshot, release, stream, calls


@pytest.mark.asyncio
async def test_immediate_ack_stream_reconnect_dedup_and_completion(learning_database):
    service, _, _, current, release, stream, calls = await running_discussion(learning_database)
    turn = current['turns'][0]
    assert turn['status'] == 'running' and turn['assistant_content'] == '合成第一段'
    assert turn['reasoning_content'] == '合成思考第一步。合成思考第二步。'
    first = service.stream(IDENTITY, current['id'], turn['id'])
    assert '合成第一段' in await anext(first)
    await first.aclose()  # A browser disconnect must not cancel or re-run the model.
    duplicate = service.start(IDENTITY, current['id'], '合成问题', 'message')
    assert len(duplicate['turns']) == 1
    resumed = service.stream(IDENTITY, current['id'], turn['id'])
    resumed_frame = await anext(resumed)
    assert '合成第一段' in resumed_frame and '合成思考第一步。合成思考第二步。' in resumed_frame
    with pytest.raises(DomainError, match='not_found'):
        service.turn_snapshot({**IDENTITY, 'id': 'foreign'}, current['id'], turn['id'])
    with pytest.raises(DomainError, match='not_found'):
        service.turn_snapshot(IDENTITY, current['id'], 'foreign-turn')
    task = service.tasks[turn['id']]
    release.set()
    await task
    frames = [frame async for frame in resumed]
    assert '合成第一段，合成第二段' in ''.join(frames)
    assert frames[-1].startswith('event: done')
    assert len(calls) == 2 and stream.closed
    assert service.get(IDENTITY, current['id'])['turns'][0]['status'] == 'succeeded'


@pytest.mark.asyncio
async def test_cancel_keeps_partial_and_retry_reuses_saved_question(learning_database):
    service, verification, _, current, _, stream, _ = await running_discussion(learning_database)
    turn = current['turns'][0]
    cancelled = await service.cancel(IDENTITY, current['id'], turn['id'])
    assert cancelled['turns'][0]['reason'] == 'cancelled'
    assert cancelled['turns'][0]['assistant_content'] == '合成第一段'
    assert cancelled['turns'][0]['reasoning_content'] == turn['reasoning_content']
    assert stream.closed
    verification.transport = response_transport(['{"history_query":null}', '合成重试回复'])
    retried = await service.send(IDENTITY, current['id'], '合成问题', 'message', retry=True)
    assert len(retried['turns']) == 1
    assert retried['turns'][0]['id'] == turn['id']
    assert retried['turns'][0]['assistant_content'] == '合成重试回复'
    assert retried['turns'][0]['status'] == 'succeeded'
    assert retried['turns'][0]['reasoning_content'] is None


@pytest.mark.asyncio
async def test_purge_during_stream_clears_partial_and_cannot_be_replayed(learning_database):
    service, verification, original, current, release, _, _ = await running_discussion(learning_database)
    turn = current['turns'][0]
    events = service.stream(IDENTITY, current['id'], turn['id'])
    await anext(events)
    verification.purge(IDENTITY, original['id'])
    task = service.tasks[turn['id']]
    release.set()
    await task
    remaining = ''.join([event async for event in events])
    assert '合成第一段' not in remaining and '合成第二段' not in remaining
    assert '合成思考' not in remaining
    assert '"purged": true' in remaining
    reconnect = ''.join([event async for event in service.stream(IDENTITY, current['id'], turn['id'])])
    assert '合成问题' not in reconnect and '合成思考' not in reconnect
    assert service.get(IDENTITY, current['id'])['turns'][0]['reasoning_content'] is None
    assert service.get(IDENTITY, current['id'])['turns'][0]['assistant_content'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('shutdown', [False, True])
async def test_stream_failure_or_shutdown_keeps_partial_without_private_error(learning_database, shutdown):
    service, _, _, current, release, _, _ = await running_discussion(learning_database, fail=True)
    task = service.tasks[current['turns'][0]['id']]
    if shutdown:
        await service.shutdown()
    else:
        release.set()
        await task
    restored = service.get(IDENTITY, current['id'])
    assert restored['turns'][0]['status'] == 'failed'
    assert restored['turns'][0]['assistant_content'] == '合成第一段'
    assert restored['turns'][0]['reasoning_content'] == '合成思考第一步。合成思考第二步。'
    assert 'synthetic-private-error' not in json.dumps(restored)


@pytest.mark.asyncio
async def test_http_start_stream_cancel_and_owner_isolation(learning_database):
    from fastapi import FastAPI
    from app.dependencies import current_identity
    from app.routers.learning import router

    service, verification, _, current, _, _, _ = await running_discussion(learning_database)
    app = FastAPI()
    app.include_router(router)
    app.state.discussions = service
    app.state.verification = verification
    app.dependency_overrides[current_identity] = lambda: IDENTITY
    path = '/api/learning/discussions/' + current['id']
    turn_path = path + '/turns/' + current['turns'][0]['id']
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://isolated') as client:
        repeated = await client.post(path + '/messages', json={'content': '合成问题', 'request_key': 'message'})
        assert repeated.status_code == 200
        assert len(repeated.json()['turns']) == 1
        app.dependency_overrides[current_identity] = lambda: {**IDENTITY, 'id': 'foreign'}
        assert (await client.get(turn_path + '/stream')).status_code == 404
        assert (await client.post(turn_path + '/cancel')).status_code == 404
        assert (await client.post(path + '/messages', json={'content': 'foreign', 'request_key': 'foreign'})).status_code == 404
        app.dependency_overrides[current_identity] = lambda: IDENTITY
        cancelled = await client.post(turn_path + '/cancel')
        assert cancelled.json()['turns'][0]['reason'] == 'cancelled'
        response = await client.get(turn_path + '/stream')
        assert response.headers['content-type'].startswith('text/event-stream')
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-accel-buffering'] == 'no'
        assert '合成第一段' in response.text and 'event: done' in response.text


@pytest.mark.asyncio
async def test_upgrade_028_preserves_existing_turn_and_erases_new_reasoning(learning_database, tmp_path):
    service, _, _, current, release, _, _ = await running_discussion(learning_database)
    turn_id = current['turns'][0]['id']
    task = service.tasks[turn_id]
    release.set()
    await task
    legacy_path = tmp_path / 'legacy-028.sqlite3'
    with sqlite3.connect(legacy_path) as legacy:
        learning_database.connection.backup(legacy)
        legacy.execute('DROP TRIGGER learning_discussion_erase_turns')
        legacy.execute('ALTER TABLE learning_discussion_turn DROP COLUMN reasoning_content')
        old_migration = Path('backend/app/migrations/028_verification_discussions.sql').read_text()
        legacy.executescript('CREATE TRIGGER learning_discussion_erase_turns' + old_migration.split('CREATE TRIGGER learning_discussion_erase_turns', 1)[1])
        legacy.execute("DELETE FROM schema_migrations WHERE version='029_discussion_reasoning'")
    result = upgrade_learning_database(legacy_path, tmp_path / 'backups', authorized=True)
    assert result['status'] == 'upgraded'
    assert result['preflight']['applied_migrations'][-1] == '028_verification_discussions'
    assert result['post_upgrade_backup']['integrity_check'] == 'ok'
    upgraded = open_learning_database(legacy_path, migrate=False)
    try:
        row = upgraded.fetchone('SELECT * FROM learning_discussion_turn WHERE id=?', (turn_id,))
        assert row['user_content'] == '合成问题'
        assert row['assistant_content'] == '合成第一段，合成第二段'
        assert row['status'] == 'succeeded' and row['reasoning_content'] is None
        with upgraded.transaction() as c:
            c.execute("UPDATE learning_discussion_turn SET reasoning_content='合成新思考' WHERE id=?", (turn_id,))
            c.execute("UPDATE learning_question_discussion SET purged_at='2026-09-24T00:00:00Z' WHERE id=?", (current['id'],))
        row = upgraded.fetchone('SELECT * FROM learning_discussion_turn WHERE id=?', (turn_id,))
        assert row['assistant_content'] is None and row['reasoning_content'] is None
    finally:
        upgraded.close()
