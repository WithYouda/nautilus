"""Synthetic uploads -> current model / optional OCR -> history and erasure."""
import asyncio
import json
import sqlite3
import threading
import time
from contextlib import closing

import httpx
import pytest

from app.learning_production import create_learning_backup, restore_learning_backup, upgrade_learning_database, ProductionLearningDatabaseError
from app.materials import MaterialService
from app.material_files import prepare_material_file
from app.question_discussion import QuestionDiscussionService
from test_ai_conversations import authorize, configure_provider, create_task, make_client, read_sse, start_conversation
from test_material_file_inputs import image_bytes, pdf_bytes
from test_material_runtime import body_response
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY
from test_verification_review import attempt


def setup(client):
    authorize(client)
    provider = configure_provider(client)
    cid = start_conversation(client, create_task(client))
    with client.app.state.database.transaction() as c:
        c.execute("UPDATE conversation SET title_generation_status='idle' WHERE id=?", (cid,))
    return provider, cid, f'/api/materials/conversation/{cid}'


def capability(client, provider, support=True, model_id=None):
    response = client.put(f'/api/ai/providers/{provider["id"]}/models/{model_id or provider["default_model"]["id"]}/image-capability',
                          json={'supports_image_input': support})
    assert response.status_code == 200, response.text
    return response.json()['model']


def upload(client, base, raw=None, name='image.png'):
    response = client.post(base + '/upload', content=raw or image_bytes(), headers={'X-Filename': name, 'Content-Type': 'application/octet-stream'})
    assert response.status_code == 201, response.text
    return response.json()


def ocr_path(cid, version):
    return f'/api/material-ocr/conversation/{cid}/versions/{version["id"]}'


def choose_ocr(client, provider):
    response = client.post(f'/api/ai/providers/{provider["id"]}/models/manual', json={'model_id': 'synthetic-ocr'})
    assert response.status_code == 201, response.text
    model = response.json()['model']
    capability(client, provider, model_id=model['id'])
    saved = client.put('/api/material-ocr/settings', json={'provider_profile_id': provider['id'], 'provider_model_id': model['id']})
    assert saved.status_code == 200, saved.text
    return model


def wait_job(client, path):
    for _ in range(200):
        response = client.get(path)
        assert response.status_code == 200, response.text
        job = response.json()['job']
        if job and job['status'] != 'running':
            return job
        time.sleep(.01)
    raise AssertionError('OCR did not finish')


def ocr_response(text):
    return httpx.Response(200, json={'choices': [{'message': {'content': text}, 'finish_reason': 'stop'}]})


def test_upload_keeps_original_and_direct_image_requires_explicit_model_capability(tmp_path):
    calls = []
    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        return body_response('图中内容【资料1】')
    with make_client(tmp_path, handler) as client:
        provider, cid, base = setup(client)
        raw = image_bytes('JPEG', orientation=6)
        saved = upload(client, base, raw, 'photo.jpg')
        assert calls == []
        assert saved['content'] is None and saved['attachment']['mode'] == 'image'
        assert client.get(f'{base}/versions/{saved["id"]}/original').content == raw
        preview = client.get(f'{base}/versions/{saved["id"]}/preview/1')
        assert preview.status_code == 200 and preview.headers['content-type'] == 'image/png'
        assert preview.headers['cache-control'] == 'no-store'
        other = start_conversation(client, create_task(client))
        assert client.get(f'/api/materials/conversation/{other}/versions/{saved["id"]}/preview/1').status_code == 404
        selection = {'mode': 'only', 'version_ids': [saved['id']]}
        def send(key):
            return client.post(f'/api/ai/conversations/{cid}/messages', json={
                'content': '请解释图片', 'client_message_id': key, 'source_scope': selection, 'search': {'mode': 'off'}})
        assert send('unknown').status_code == 400
        capability(client, provider, False)
        assert send('unsupported').status_code == 400
        assert calls == []
        capability(client, provider)
        sent = send('direct')
        assert sent.status_code == 202, sent.text
        read_sse(client, sent.json()['run']['id'])
        content = calls[0]['messages'][-1]['content']
        assert content[0]['type'] == 'text' and '附图 1 对应【资料1】第 1 页' in content[0]['text']
        data_url = content[1]['image_url']['url']
        assert data_url.startswith('data:image/png;base64,')
        snapshot = client.app.state.database.fetchone('SELECT config_snapshot_json FROM ai_run WHERE id=?', (sent.json()['run']['id'],))[0]
        assert 'base64' not in snapshot and data_url.split(',')[1] not in snapshot
        source = json.loads(snapshot)['source_scope']['materials'][0]
        assert source['source_version_id'] == saved['id'] and source['page_numbers'] == [1]
        assert client.get(ocr_path(cid, saved)).json()['job'] is None  # No automatic OCR.


def test_ocr_uses_separate_model_and_only_reviewed_versions_supply_text(tmp_path):
    calls = []
    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        return body_response('依据核对文字【资料1】') if payload.get('stream') else ocr_response('原始识别[无法辨认]')
    with make_client(tmp_path, handler) as client:
        provider, cid, base = setup(client)
        raw = image_bytes()
        saved = upload(client, base, raw)
        path = ocr_path(cid, saved)
        assert client.post(path).json()['detail'] == 'ocr_model_required'
        choose_ocr(client, provider)
        assert client.post(path).status_code == 200
        job = wait_job(client, path)
        assert job['status'] == 'review' and job['model']['model'] == 'synthetic-ocr'
        assert len(client.get(base).json()['versions']) == 1
        assert client.get(base).json()['versions'][0]['content'] is None
        assert calls[0]['model'] == 'synthetic-ocr' and calls[0]['messages'][-1]['content'][1]['type'] == 'image_url'
        result = client.post(path + f'/{job["id"]}/confirm', json={'pages': [{'number': 1, 'text': '本人核对的文字'}]})
        assert result.status_code == 200, result.text
        derived = result.json()
        assert derived['material_id'] == saved['material_id'] and derived['version'] == 2
        assert derived['attachment']['origin'] == 'ocr' and derived['attachment']['mode'] == 'text'
        assert derived['attachment']['source_version_id'] == saved['id']
        assert client.get(f'{base}/versions/{derived["id"]}/original').content == raw
        assert client.post(path + f'/{job["id"]}/confirm', json={'pages': [{'number': 1, 'text': '本人核对的文字'}]}).json()['id'] == derived['id']
        revision = client.post(path + f'/{job["id"]}/confirm', json={'pages': [{'number': 1, 'text': '修订后的核对文字'}]}).json()
        assert revision['version'] == 3 and revision['id'] != derived['id']
        assert next(item for item in client.get(base).json()['versions'] if item['id'] == derived['id'])['content'] == '[第 1 页]\n本人核对的文字'
        assert client.get(ocr_path(cid, derived)).json()['job']['pages'][0]['text'] == '本人核对的文字'
        assert client.get(ocr_path(cid, derived) + f'?job_id={job["id"]}').json()['job']['pages'][0]['text'] == '修订后的核对文字'
        sent = client.post(f'/api/ai/conversations/{cid}/messages', json={'content': '按文字讲解', 'client_message_id': 'reviewed',
            'source_scope': {'mode': 'only', 'version_ids': [derived['id']]}, 'search': {'mode': 'off'}})
        assert sent.status_code == 202, sent.text
        read_sse(client, sent.json()['run']['id'])
        chat = next(call for call in calls if call.get('stream'))
        assert chat['model'] == provider['model'] and isinstance(chat['messages'][-1]['content'], str)
        assert '本人核对的文字' in chat['messages'][0]['content']
        assert '原始识别' not in json.dumps(chat, ensure_ascii=False) and 'base64' not in json.dumps(chat)
        # An unchanged confirmation from another linked scope returns a usable
        # immutable version rather than an inaccessible ID from the first chat.
        assert client.post(base + f'/{saved["material_id"]}/library').status_code == 200
        other = start_conversation(client, create_task(client))
        other_base = f'/api/materials/conversation/{other}'
        assert client.post(other_base + '/library-use', json={'version_id': saved['id']}).status_code == 200
        reused = client.post(ocr_path(other, saved) + f'/{job["id"]}/confirm', json={'pages': [{'number': 1, 'text': '修订后的核对文字'}]}).json()
        assert reused['id'] == revision['id']
        owner = client.app.state.auth.ensure_local_identity()
        client.app.state.materials.freeze(owner, 'conversation', other, {'mode': 'only', 'version_ids': [reused['id']]})


def test_readable_pdf_can_explicitly_use_original_pages_and_freezes_actual_mode(tmp_path):
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return body_response('原页图表【资料1】')
    with make_client(tmp_path, handler) as client:
        provider, cid, base = setup(client)
        capability(client, provider)
        saved = upload(client, base, pdf_bytes('captioned page'), 'figures.pdf')
        assert saved['attachment']['mode'] == 'text'
        selection = {'mode': 'only', 'version_ids': [saved['id']], 'image_version_ids': [saved['id']]}
        # Verify the same exact choice survives the server current-state boundary.
        current = client.app.state.conversation_state
        identity = client.app.state.auth.ensure_local_identity()
        state_path = f'/api/conversation-state/conversation/{cid}'
        state = client.put(state_path, json={'expected_revision': 0, 'source_scope': selection, 'search_override': {'mode': 'off'}})
        assert state.status_code == 200, state.text
        assert client.get(state_path).json()['source_scope'] == selection
        sent = client.post(f'/api/ai/conversations/{cid}/messages', json={'content': '解释原页图表', 'client_message_id': 'pdf-vision',
            'source_scope': selection, 'search': {'mode': 'off'}, 'current_state_revision': 1})
        assert sent.status_code == 202, sent.text
        read_sse(client, sent.json()['run']['id'])
        assert calls[0]['messages'][-1]['content'][1]['type'] == 'image_url'
        assert 'captioned page' not in calls[0]['messages'][0]['content']
        snapshot = client.app.state.database.fetchone('SELECT config_snapshot_json FROM ai_run WHERE id=?', (sent.json()['run']['id'],))[0]
        scope = json.loads(snapshot)['source_scope']
        assert scope['image_version_ids'] == [saved['id']] and scope['materials'][0]['input_mode'] == 'image'
        # A text source cannot be turned into an image by crafting scope data.
        plain = client.post(base, json={'title': 'plain', 'content': 'plain text'}).json()
        from app.learning_domain import DomainError
        with pytest.raises(DomainError, match='material_image_unavailable'):
            current._validate_scope(identity, 'conversation', cid, {'mode': 'only', 'version_ids': [plain['id']], 'image_version_ids': [plain['id']]})


def test_formal_038_to_039_preserves_all_old_rows_and_original_bytes(tmp_path):
    from app.config import Settings
    from app.db import Database
    from app.learning_service import LearningService
    from test_material_originals import _business_rows
    path = tmp_path / 'learning.sqlite3'
    db = Database(path, Settings.from_env().migrations_dir, migration_floor=11, migration_ceiling=38)
    LearningService(db).principal({'id': 'owner', 'device_id': 'synthetic', 'display_name': 'Synthetic', 'timezone': 'UTC', 'created_at': '2026-10-03T00:00:00Z'})
    with db.transaction() as c:
        c.execute('''INSERT INTO learning_task_material
            (id,material_id,owner_id,scope_kind,scope_id,version,title,content,content_kind,provenance_json,created_at)
            VALUES ('v1','group','owner','conversation','chat',1,'Old material','Original private text','text','{}','now')''')
        c.execute("INSERT INTO learning_material_original(version_id,filename,media_type,content,sha256) VALUES ('v1','old.txt','text/plain',?,'fingerprint')", (b'ORIGINAL_BYTES_038',))
        c.execute("INSERT INTO learning_material_library(owner_id,material_id,created_at) VALUES ('owner','group','now')")
        c.execute("INSERT INTO learning_material_link(owner_id,scope_kind,scope_id,version_id,created_at) VALUES ('owner','conversation','other','v1','now')")
    before = _business_rows(db.connection)
    db.close()
    result = upgrade_learning_database(path, tmp_path / 'backups', authorized=True)
    assert result['preflight']['applied_migrations'][-1] == '038_material_library_removal'
    assert result['post_upgrade_backup']['applied_migrations'][-1] == '039_material_ocr'
    with closing(sqlite3.connect(path)) as c:
        after = _business_rows(c)
        assert {table: after[table] for table in before} == before
        assert set(after) - set(before) == {'learning_material_ocr'}
        assert after['learning_material_ocr'] == []
        assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []


def test_cancel_during_pdf_preparation_does_not_render_more_pages_or_call_provider(tmp_path, monkeypatch):
    import app.material_images as module
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    renders, calls = [], []
    def render(raw, media_type, page):
        renders.append(page)
        entered.set()
        assert release.wait(3)
        exited.set()
        return image_bytes(), 'image/png'
    monkeypatch.setattr(module, 'render_material_page', render)
    with make_client(tmp_path, lambda request: calls.append(request) or body_response('unexpected')) as client:
        provider, cid, base = setup(client)
        capability(client, provider)
        saved = upload(client, base, pdf_bytes('one', 'two'), 'pages.pdf')
        sent = client.post(f'/api/ai/conversations/{cid}/messages', json={'content': '看原页', 'client_message_id': 'cancel-preparation',
            'source_scope': {'mode': 'only', 'version_ids': [saved['id']], 'image_version_ids': [saved['id']]}, 'search': {'mode': 'off'}})
        assert sent.status_code == 202, sent.text
        assert entered.wait(2)
        run = sent.json()['run']
        assert client.post(f'/api/ai/runs/{run["id"]}/cancel').status_code == 200
        release.set()
        assert exited.wait(2)
        read_sse(client, run['id'])
        time.sleep(.03)
        assert renders == [1] and calls == []


def test_mixed_pdf_keeps_every_page_and_partial_ocr_needs_explicit_review(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return ocr_response('Freshly recognized first page')
        return httpx.Response(400, json={'error': {'message': 'PRIVATE_UPSTREAM_ERROR'}})
    with make_client(tmp_path, handler) as client:
        provider, cid, base = setup(client)
        saved = upload(client, base, pdf_bytes('text layer', None), 'mixed.pdf')
        assert saved['content'] is None and saved['attachment']['page_count'] == 2
        assert client.get(f'{base}/versions/{saved["id"]}/preview/2').status_code == 200
        choose_ocr(client, provider)
        path = ocr_path(cid, saved)
        client.post(path)
        job = wait_job(client, path)
        assert job['status'] == 'review' and job['error_code'] == 'ocr_pages_failed'
        assert [page['status'] for page in job['pages']] == ['recognized', 'failed']
        assert job['pages'][0]['text'] == 'Freshly recognized first page' and len(calls) == 2
        assert 'PRIVATE_UPSTREAM_ERROR' not in json.dumps(job)
        review = {'pages': [{'number': 1, 'text': 'text layer'}, {'number': 2, 'text': ''}]}
        assert client.post(path + f'/{job["id"]}/confirm', json=review).json()['detail'] == 'ocr_incomplete_confirmation_required'
        review['acknowledge_incomplete'] = True
        result = client.post(path + f'/{job["id"]}/confirm', json=review)
        assert result.status_code == 200, result.text
        assert '[第 2 页]\n[本页没有确认文字' in result.json()['content']


@pytest.mark.parametrize('action', ['cancel', 'purge', 'delete_scope'])
def test_late_ocr_cannot_publish_after_cancel_purge_or_scope_deletion(tmp_path, action):
    arrived = threading.Event()
    async def handler(request):
        arrived.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass  # A late result must still fail the publication guard.
        return ocr_response('LATE_PRIVATE_OCR_772')
    with make_client(tmp_path, handler) as client:
        provider, cid, base = setup(client)
        choose_ocr(client, provider)
        saved = upload(client, base)
        path = ocr_path(cid, saved)
        started = client.post(path).json()['job']
        assert arrived.wait(2)
        if action == 'cancel':
            assert client.post(path + f'/{started["id"]}/cancel').status_code == 200
        elif action == 'purge':
            result = client.post(base + f'/{saved["material_id"]}/purge')
            assert result.status_code == 200 and result.json()['purge']['status'] == 'complete'
        else:
            assert client.delete(f'/api/ai/conversations/{cid}').status_code == 204
        for _ in range(100):
            if started['id'] not in client.app.state.material_ocr.tasks:
                break
            time.sleep(.01)
        assert started['id'] not in client.app.state.material_ocr.tasks
        row = client.app.state.learning.database.fetchone('SELECT * FROM learning_material_ocr WHERE id=?', (started['id'],))
        assert row['status'] in ('canceled', 'purged') and 'LATE_PRIVATE_OCR_772' not in row['pages_json']
        assert len(client.app.state.learning.database.fetchall('SELECT id FROM learning_task_material WHERE material_id=?', (saved['material_id'],))) == 1


def test_ocr_draft_and_reviewed_text_clear_from_managed_backups_and_cannot_restore(tmp_path):
    with make_client(tmp_path, lambda request: ocr_response('OCR_PRIVATE_CLEAR_901')) as client:
        provider, cid, base = setup(client)
        choose_ocr(client, provider)
        saved = upload(client, base)
        path = ocr_path(cid, saved)
        client.post(path)
        job = wait_job(client, path)
        result = client.post(path + f'/{job["id"]}/confirm', json={'pages': [{'number': 1, 'text': 'REVIEWED_PRIVATE_CLEAR_901'}]})
        assert result.status_code == 200
        db = client.app.state.learning.database
        backup, _, _ = create_learning_backup(db.database_path, tmp_path / 'backups', label='ocr')
        unmanaged = tmp_path / 'unmanaged.sqlite3'
        with closing(sqlite3.connect(unmanaged)) as target:
            db.connection.backup(target)
        cleared = client.post(base + f'/{saved["material_id"]}/purge')
        assert cleared.json()['purge']['status'] == 'complete'
        for location in (db.database_path, backup):
            assert b'OCR_PRIVATE_CLEAR_901' not in location.read_bytes()
            assert b'REVIEWED_PRIVATE_CLEAR_901' not in location.read_bytes()
        assert client.get(path).status_code == 404
        with pytest.raises(ProductionLearningDatabaseError):
            restore_learning_backup(unmanaged, db.database_path)
        stale = tmp_path / 'stale.sqlite3'
        with closing(sqlite3.connect(stale)) as target:
            db.connection.backup(target)
        with closing(sqlite3.connect(stale)) as c:
            c.execute("UPDATE learning_material_ocr SET pages_json='[{\"text\":\"STALE_DRAFT_PRIVATE\"}]' WHERE id=?", (job['id'],))
            c.commit()
        with pytest.raises(ProductionLearningDatabaseError, match='private content'):
            restore_learning_backup(stale, db.database_path)


@pytest.mark.asyncio
async def test_question_discussion_receives_real_image_and_snapshot_only_keeps_locator(learning_database):
    verification, original = await attempt(learning_database)
    service = QuestionDiscussionService(verification)
    materials = MaterialService(service.learning, service.chats)
    service.chats.materials = materials
    discussion = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'image-discussion')
    raw = image_bytes()
    saved = materials.create(IDENTITY, 'discussion', discussion['id'], title='diagram.png',
        original=(raw, 'diagram.png', 'image/png'), file_metadata=prepare_material_file('diagram.png', raw))
    calls = []
    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        return body_response('图中关系【资料1】')
    verification.transport = httpx.MockTransport(handler)
    # This fixture deliberately supplies a synthetic runtime, not a saved profile.
    # Inject the capability boundary while still checking the actual send path.
    from unittest.mock import patch
    with patch('app.question_discussion.require_image_capability') as capability_check:
        # Give the existing synthetic profile an ID for the new capability call.
        original_runtime = verification._runtime
        verification._runtime = lambda owner, session: ({**original_runtime(owner, session)[0], 'id': 'synthetic'}, original_runtime(owner, session)[1])
        result = await service.send(IDENTITY, discussion['id'], '请解释图中关系', 'image-question',
            source_scope={'mode': 'reference', 'version_ids': [saved['id']]},
            attachment_version_ids=[saved['id']], search={'mode': 'off'})
        capability_check.assert_called_once()
        newer_raw = image_bytes(color='blue')
        newer = materials.create(IDENTITY, 'discussion', discussion['id'], title='new.png',
            original=(newer_raw, 'new.png', 'image/png'), file_metadata=prepare_material_file('new.png', newer_raw))
        await service.send(IDENTITY, discussion['id'], '解析新图片', 'new-image-question',
            parent_turn_id=result['turns'][-1]['id'], attachment_version_ids=[newer['id']],
            source_scope={'mode': 'reference', 'version_ids': [saved['id'], newer['id']]}, search={'mode': 'off'})
        assert len([part for part in calls[-1]['messages'][-1]['content'] if part['type'] == 'image_url']) == 1
        earlier = next(message for message in calls[-1]['messages'][:-1]
                       if isinstance(message.get('content'), list))
        assert earlier['content'][1]['image_url']['url'] != calls[-1]['messages'][-1]['content'][1]['image_url']['url']
    assert result['turns'][-1]['status'] == 'succeeded'
    assert calls[0]['messages'][-1]['content'][1]['type'] == 'image_url'
    snapshot = learning_database.fetchone('SELECT provider_snapshot_json FROM learning_discussion_turn WHERE id=?', (result['turns'][-1]['id'],))[0]
    assert 'base64' not in snapshot
    assert result['turns'][-1]['source_scope']['materials'][0]['page_numbers'] == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize('shared', [False, True])
async def test_source_purge_clears_ocr_or_preserves_independent_library_group(learning_database, tmp_path, shared):
    from app.material_ocr import MaterialOCR
    from app.managed_purge import ManagedPurge
    verification, original = await attempt(learning_database)
    discussions = QuestionDiscussionService(verification)
    materials = MaterialService(discussions.learning, discussions.chats)
    discussion = discussions.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'ocr-source')
    raw = image_bytes()
    source = materials.create(IDENTITY, 'discussion', discussion['id'], title='source.png',
        original=(raw, 'source.png', 'image/png'), file_metadata=prepare_material_file('source.png', raw))
    with learning_database.transaction() as c:
        c.execute('''INSERT INTO learning_material_ocr
            (id,owner_id,scope_kind,scope_id,source_version_id,status,pages_json,model_json,created_at,updated_at)
            VALUES ('ocr-source',?,'discussion',?,?,'review',?,'{"model":"synthetic"}','now','now')''',
            (IDENTITY['id'], discussion['id'], source['id'], json.dumps([{'number': 1, 'text': 'SOURCE_OCR_PRIVATE_344', 'status': 'recognized'}])))
    ocr = MaterialOCR(materials, None)
    derived = ocr.confirm(IDENTITY, 'discussion', discussion['id'], source['id'], 'ocr-source', [{'number': 1, 'text': 'SOURCE_REVIEW_PRIVATE_344'}])
    if shared:
        materials.store_in_library(IDENTITY, 'discussion', discussion['id'], source['material_id'])
    backup, _, _ = create_learning_backup(learning_database.database_path, tmp_path / 'backups', label='source-ocr')
    result = ManagedPurge(verification.learning).run(IDENTITY, 'verification', original['id'], lambda: verification.purge(IDENTITY, original['id']))
    assert result['purge']['status'] == 'complete'
    for path in (learning_database.database_path, backup):
        with closing(sqlite3.connect(path)) as c:
            job = c.execute("SELECT status,pages_json,model_json,purged_at FROM learning_material_ocr WHERE id='ocr-source'").fetchone()
            content = c.execute('SELECT content FROM learning_task_material WHERE id=?', (derived['id'],)).fetchone()[0]
        if shared:
            assert job[0] == 'confirmed' and 'SOURCE_REVIEW_PRIVATE_344' in job[1]
            assert 'SOURCE_REVIEW_PRIVATE_344' in content
        else:
            assert job[0] == 'purged' and job[1:3] == ('[]', None) and job[3]
            assert content is None and b'SOURCE_REVIEW_PRIVATE_344' not in path.read_bytes()
    if shared:
        post, _, _ = create_learning_backup(learning_database.database_path, tmp_path / 'backups', label='after-source-purge')
        restore_learning_backup(post, learning_database.database_path)
