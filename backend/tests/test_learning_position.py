import json

import httpx
import pytest

from app.config import Settings
from app.core.commands import EndSession
from app.core.learning import LearningCore
from app.conversations import ConversationService
from app.credentials import CredentialStore
from app.db import Database
from app.learning_domain import DomainError
from app.learning_position import LearningPositionService
from app.learning_service import LearningService
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY, OWNER, create_context


@pytest.fixture
def position_room(learning_database, tmp_path):
    db = Database(tmp_path / 'chat.sqlite3', Settings.from_env().migrations_dir)
    with db.transaction() as connection:
        connection.execute("INSERT INTO local_identity VALUES (?,?,?,?,?,?)",
                           ('owner-a', 'owner-a-device', 'Synthetic learner', 'UTC', '2026-09-26', '2026-09-26'))
    chats = ConversationService(db, None, CredentialStore(tmp_path / 'credentials'))
    chats.save_provider('owner-a', display_name='Synthetic', base_url='https://example.test/v1',
                        model='synthetic', api_key='synthetic-test-key')
    cid = chats.create_conversation('owner-a')['conversation']['id']
    context = create_context(learning_database)
    service = LearningPositionService(LearningService(learning_database), chats)
    service.room.select(IDENTITY, context['session_id'], cid)
    first = chats.prepare_run('owner-a', cid, content='如何定位编号？', client_message_id='first')['run']
    chats.finalize_run(first['id'], 'succeeded', content='先定位前缀，再检查数字。')
    yield service, context['session_id'], cid, first
    db.close()


def test_corrections_restore_per_answer_without_changing_learning_facts(position_room):
    service, session, cid, first = position_room
    args = (IDENTITY, session, cid, first['response_message_id'])
    before = [tuple(row) for row in service.room.learning.database.fetchall('SELECT * FROM learning_delegation')]
    original = service.chats.list_messages('owner-a', cid)
    assert service.get(*args)['revisions'] == []
    note = {'current': '正在比较前缀', 'next': '换一个输入试试'}
    service.save(*args, 0, note)
    service.save(*args, 1, {**note, 'current': '实际还在讨论数字范围'})
    assert service.get(*args)['revisions'][0]['current'] == note['current']
    assert service.get(*args)['revisions'][-1]['source'] == 'user'
    with pytest.raises(DomainError, match='position_changed'):
        service.save(*args, 1, note)
    second = service.chats.prepare_run('owner-a', cid, content='如何定位编号？',
        client_message_id='regenerate', regenerate_message_id=first['response_message_id'])['run']
    service.chats.finalize_run(second['id'], 'succeeded', content='另一种解释。')
    assert service.get(IDENTITY, session, cid, second['response_message_id'])['revisions'] == []
    assert len(service.get(*args)['revisions']) == 2
    assert service.chats.list_messages('owner-a', cid)[:2] == original
    assert [tuple(row) for row in service.room.learning.database.fetchall('SELECT * FROM learning_delegation')] == before


async def test_generation_uses_selected_path_and_cannot_overwrite_correction_or_deleted_chat(position_room):
    service, session, cid, first = position_room
    args = (IDENTITY, session, cid, first['response_message_id'])
    later = service.chats.prepare_run('owner-a', cid, content='不应进入旧路径概括的后续问题', client_message_id='later')['run']
    service.chats.finalize_run(later['id'], 'succeeded', content='后续答案')

    def reply(request):
        payload = json.loads(request.content)
        assert '不应进入旧路径概括' not in json.dumps(payload, ensure_ascii=False)
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"current":"讨论编号定位","next":"解释自己的判断"}'}}]})

    service.transport = httpx.MockTransport(reply)
    async def connected():
        return False
    saved = await service.generate(*args, 0, connected)
    assert saved['revisions'][0]['basis_message_ids'] == [first['request_message_id'], first['response_message_id']]
    assert saved['revisions'][0]['source'] == 'ai'

    def concurrent_edit(request):
        service.save(*args, 1, {'current': '用户纠正优先', 'next': ''})
        return reply(request)
    service.transport = httpx.MockTransport(concurrent_edit)
    with pytest.raises(DomainError, match='position_changed'):
        await service.generate(*args, 1, connected)
    assert service.get(*args)['revisions'][-1]['current'] == '用户纠正优先'

    def concurrent_delete(request):
        service.chats.delete_conversation('owner-a', cid)
        return reply(request)
    service.transport = httpx.MockTransport(concurrent_delete)
    with pytest.raises(DomainError, match='not_found'):
        await service.generate(*args, 2, connected)
    snapshot = service.chats.database.fetchone('SELECT config_snapshot_json FROM ai_run WHERE id=?', (first['id'],))[0]
    assert 'learning_position' not in json.loads(snapshot)


async def test_scope_failure_and_cancel_leave_existing_notes_unchanged(position_room):
    service, session, cid, first = position_room
    args = (IDENTITY, session, cid, first['response_message_id'])
    LearningCore(service.room.learning.database).execute(
        OWNER, EndSession(session_id=session, disposition='interrupted', expected_version=3), 'pause')
    other = create_context(service.room.learning.database, 'other')
    with pytest.raises(DomainError, match='not_found'):
        service.get(IDENTITY, other['session_id'], cid, first['response_message_id'])
    with pytest.raises(DomainError, match='not_found'):
        service.get({**IDENTITY, 'id': 'owner-b'}, session, cid, first['response_message_id'])
    note = {'current': '保留我的记录', 'next': ''}
    service.save(*args, 0, note)

    async def connected():
        return False
    service.transport = httpx.MockTransport(lambda request: httpx.Response(401, json={'error': {'message': 'synthetic error'}}))
    with pytest.raises(DomainError, match='position_generation_failed'):
        await service.generate(*args, 1, connected)
    service.transport = httpx.MockTransport(lambda request: httpx.Response(200, json={'choices': [{'message': {'content': '{"current":"新概括","next":""}'}}]}))
    async def disconnected():
        return True
    with pytest.raises(DomainError, match='position_canceled'):
        await service.generate(*args, 1, disconnected)
    assert service.get(*args)['revisions'][-1]['current'] == note['current']
    assert len(service.get(*args)['revisions']) == 1
