"""Explicit message attachments do not replace continuing conversation references."""
import json

import pytest

from app.conversation_state import CurrentConversationState
from app.learning_domain import DomainError
from app.material_files import prepare_material_file
from app.materials import MaterialService
from app.question_discussion import QuestionDiscussionService
from app.routers.conversation_state import CurrentStatePut
from test_ai_conversations import make_client, read_sse
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY, response_transport
from test_material_image_runtime import setup, upload, capability
from test_material_file_inputs import image_bytes
from test_material_runtime import body_response
from test_verification_review import attempt


def test_explicit_attachments_persist_on_message_without_clearing_scope(tmp_path):
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return body_response('Synthetic image answer')
    with make_client(tmp_path, handler) as client:
        provider, cid, base = setup(client)
        saved = upload(client, base)
        scope = {'mode': 'reference', 'version_ids': [saved['id']]}
        state_url = f'/api/conversation-state/conversation/{cid}'
        state = client.put(state_url, json={'expected_revision': 0, 'source_scope': scope}).json()
        message_url = f'/api/ai/conversations/{cid}/messages'
        request = {'content': 'Look at this image', 'client_message_id': 'explicit-file',
                   'source_scope': scope, 'attachment_version_ids': [saved['id']],
                   'current_state_revision': state['revision']}
        # Capability rejection does not consume a message or change selection.
        assert client.post(message_url, json=request).status_code == 400
        assert client.get(state_url).json()['source_scope'] == scope
        assert client.get(f'/api/ai/conversations/{cid}').json()['messages'] == []
        capability(client, provider)
        sent = client.post(message_url, json=request)
        assert sent.status_code == 202, sent.text
        first = sent.json()
        assert all(message['attachment_version_ids'] == [saved['id']] for message in first['messages'])
        read_sse(client, first['run']['id'])
        assert client.get(state_url).json()['source_scope'] == scope
        replay = client.post(message_url, json=request)
        assert replay.status_code == 202 and replay.json()['created'] is False
        assert client.post(message_url, json={**request, 'attachment_version_ids': []}).status_code == 409

        state = client.get(state_url).json()
        followup = client.post(message_url, json={**request, 'content': 'Explain more',
            'client_message_id': 'followup', 'attachment_version_ids': [],
            'current_state_revision': state['revision'], 'parent_message_id': state['leaf_id']})
        assert followup.status_code == 202, followup.text
        read_sse(client, followup.json()['run']['id'])
        messages = client.get(f'/api/ai/conversations/{cid}').json()['messages']
        assert [item['attachment_version_ids'] for item in messages if item['role'] == 'user'] == [[saved['id']], []]
        # Continue using the original image as history, not a new attachment.
        assert calls[-1]['messages'][-1]['content'] == 'Explain more'
        assert calls[-1]['messages'][1]['content'][1]['type'] == 'image_url'
        assert client.get(state_url).json()['source_scope'] == scope

        newer = upload(client, base, image_bytes(color='blue'), 'new-image.png')
        state = client.get(state_url).json()
        scope = {'mode': 'reference', 'version_ids': [saved['id'], newer['id']]}
        updated = client.put(state_url, json={'expected_revision': state['revision'],
            'leaf_id': state['leaf_id'], 'paths': state['paths'], 'source_scope': scope})
        assert updated.status_code == 200
        state = updated.json()
        for key, ids in [('new-image-only', [newer['id']]), ('explicitly-select-both', [saved['id'], newer['id']])]:
            sent = client.post(message_url, json={'content': '解析图片', 'client_message_id': key,
                'source_scope': scope, 'attachment_version_ids': ids,
                'current_state_revision': state['revision'], 'parent_message_id': state['leaf_id']})
            assert sent.status_code == 202, sent.text
            read_sse(client, sent.json()['run']['id'])
            body = calls[-1]['messages']
            assert len([part for part in body[-1]['content'] if part['type'] == 'image_url']) == len(ids)
            assert all('_attachment_version_ids' not in message for message in body)
            if len(ids) == 1:
                assert body[-1]['content'][1]['image_url']['url'] != body[1]['content'][1]['image_url']['url']
                assert '默认只针对用户最新消息实际附上的图片' in body[0]['content']
            state = client.get(state_url).json()

        fork = client.post(f'/api/ai/conversations/{cid}/branches', json={
            'message_id': first['run']['response_message_id'], 'request_key': 'file-branch'})
        assert fork.status_code == 201, fork.text
        assert fork.json()['messages'][0]['attachment_version_ids'] == [saved['id']]
        assert client.get(f'{base}/versions/{saved["id"]}/original').status_code == 200
        cleared = client.post(f'{base}/{saved["material_id"]}/purge')
        assert cleared.status_code == 200
        assert all(item['attachment_version_ids'] == [] for item in client.get(f'/api/ai/conversations/{cid}').json()['messages'])


def test_attachment_metadata_rejects_unselected_duplicates_and_non_file_originals(tmp_path):
    with make_client(tmp_path, lambda request: body_response('Synthetic')) as client:
        _, cid, base = setup(client)
        uploaded = upload(client, base, b'Synthetic file', 'source.txt')
        other = upload(client, base, b'Another file', 'other.txt')
        note = client.post(base, json={'title': 'Pasted text', 'content': 'Synthetic pasted text'}).json()
        # A connected-note snapshot also has original bytes, but is not an upload.
        with client.app.state.learning.database.transaction() as c:
            c.execute("UPDATE learning_task_material SET provenance_json=? WHERE id=?",
                      (json.dumps({'kind': 'obsidian'}), other['id']))
        scope = {'mode': 'reference', 'version_ids': [uploaded['id'], note['id'], other['id']]}
        base_request = {'content': 'Question', 'source_scope': scope}
        for index, ids in enumerate(([uploaded['id'], uploaded['id']], [note['id']], [other['id']], ['not-selected'])):
            rejected = client.post(f'/api/ai/conversations/{cid}/messages', json={
                **base_request, 'client_message_id': f'bad-{index}', 'attachment_version_ids': ids})
            assert rejected.status_code == 400, rejected.text
        assert client.get(f'/api/ai/conversations/{cid}').json()['messages'] == []
        # Pre-B3 upload provenance remains an eligible historical upload.
        with client.app.state.learning.database.transaction() as c:
            c.execute("UPDATE learning_task_material SET provenance_json=? WHERE id=?",
                      ('{"kind":"user_text"}', uploaded['id']))
        sent = client.post(f'/api/ai/conversations/{cid}/messages', json={
            **base_request, 'client_message_id': 'legacy-file', 'attachment_version_ids': [uploaded['id']]})
        assert sent.status_code == 202, sent.text
        read_sse(client, sent.json()['run']['id'])
        assert sent.json()['messages'][0]['attachment_version_ids'] == [uploaded['id']]


@pytest.mark.asyncio
async def test_discussion_attachment_metadata_and_reference_continuity(learning_database):
    verification, original = await attempt(learning_database)
    service = QuestionDiscussionService(verification)
    materials = MaterialService(service.learning, service.chats)
    service.chats.materials = materials
    state = CurrentConversationState(materials, service.chats, service, None)
    service.current_state = state
    discussion = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'attachments')
    did = discussion['id']
    raw = b'Synthetic uploaded file'
    saved = materials.create(IDENTITY, 'discussion', did, title='input.txt', content=raw.decode(),
        original=(raw, 'input.txt', 'text/plain'), file_metadata=prepare_material_file('input.txt', raw))
    scope = {'mode': 'reference', 'version_ids': [saved['id']]}
    state.put(IDENTITY, 'discussion', did, CurrentStatePut(expected_revision=0, source_scope=scope))
    options = dict(source_scope=scope, attachment_version_ids=[saved['id']], current_state_revision=1)
    verification.transport = response_transport(['Synthetic answer'])
    sent = await service.send(IDENTITY, did, 'Question', 'first', **options)
    assert sent['turns'][0]['attachment_version_ids'] == [saved['id']]
    assert state.get(IDENTITY, 'discussion', did)['source_scope'] == scope
    assert len(service.start(IDENTITY, did, 'Question', 'first', **options)['turns']) == 1
    with pytest.raises(DomainError, match='idempotency_conflict'):
        service.start(IDENTITY, did, 'Question', 'first', **{**options, 'attachment_version_ids': []})
    current = state.get(IDENTITY, 'discussion', did)
    verification.transport = response_transport(['More synthetic explanation'])
    result = await service.send(IDENTITY, did, 'Explain more', 'second', source_scope=scope,
        current_state_revision=current['revision'], parent_turn_id=current['leaf_id'], attachment_version_ids=[])
    assert [turn['attachment_version_ids'] for turn in result['turns']] == [[saved['id']], []]
    assert state.get(IDENTITY, 'discussion', did)['source_scope'] == scope
