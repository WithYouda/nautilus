"""Obsidian snapshots join the existing material version, original, library and purge chain."""
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.learning_domain import DomainError
from app.learning_production import ProductionLearningDatabaseError, create_learning_backup, restore_learning_backup
from test_ai_conversations import authorize, create_task, make_client, start_conversation
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY
from test_verification_review import attempt

NOTE = '# Deep\nMATRIX reference\n'


def build_vault(tmp_path, name='My Vault'):
    root = tmp_path / name
    (root / '子目录' / '空格 目录').mkdir(parents=True)
    for hidden in ('.obsidian', '.git', '.trash'):
        (root / hidden).mkdir()
    (root / '笔记 一.md').write_text('# 标题\n矩阵乘法的定义与例子\n', encoding='utf-8')
    (root / 'plain.md').write_text('普通笔记\n', encoding='utf-8')
    (root / 'blank.md').write_text('   \n\n', encoding='utf-8')
    (root / '坏.md').write_bytes(b'\xff\xfe\x00bad')
    (root / 'picture.png').write_bytes(b'\x89PNG')
    (root / '子目录' / '空格 目录' / 'Deep Note.MD').write_text(NOTE, encoding='utf-8')
    (root / '.obsidian' / 'hidden.md').write_text('OBSIDIAN_SECRET\n', encoding='utf-8')
    (root / '.git' / 'config.md').write_text('GIT_SECRET\n', encoding='utf-8')
    (root / '.trash' / 'gone.md').write_text('TRASH_SECRET\n', encoding='utf-8')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.md').write_text('OUTSIDE_SECRET\n', encoding='utf-8')
    os.symlink(outside / 'secret.md', root / 'link.md')
    os.symlink(outside, root / 'linked-dir')
    return root, {'secret': 'OUTSIDE_SECRET', 'path': outside}


def connect(client, root, expected=None):
    return client.put('/api/obsidian/connection',
                      json={'root_path': str(root), 'expected_revision': expected})


def body(connection, query='', after=None):
    return {'connection_id': connection['connection_id'],
            'connection_revision': connection['revision'], 'query': query, 'after': after}


def search(client, scope, connection, query='', after=None, kind='conversation'):
    return client.post(f'/api/obsidian/{kind}/{scope}/search', json=body(connection, query, after))


def capture(client, scope, token, kind='conversation'):
    return client.post(f'/api/obsidian/{kind}/{scope}/capture', json={'selection_token': token})


def open_page(client, scope, connection, query=''):
    page = search(client, scope, connection, query)
    assert page.status_code == 200, page.text
    return page.json()


def db_rows(client, sql, params=()):
    return client.app.state.learning.database.fetchall(sql, params)


def test_capture_persists_version_original_provenance_and_library(client, tmp_path):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    connection = connect(client, vault).json()['connection']
    chat = start_conversation(client, create_task(client))
    page = open_page(client, chat, connection, 'MATRIX')
    item = page['items'][0]
    assert item['relative_path'] == '子目录/空格 目录/Deep Note.MD'
    saved = capture(client, chat, item['selection_token'])
    assert saved.status_code == 201, saved.text
    version = saved.json()
    raw = (vault / '子目录' / '空格 目录' / 'Deep Note.MD').read_bytes()
    assert version['content'] == NOTE and version['title'] == 'Deep Note'
    assert version['content_kind'] == 'text' and version['url'] is None
    assert version['library'] is True and version['version'] == 1
    assert version['original'] == {'filename': 'Deep Note.MD', 'media_type': 'text/markdown',
                                   'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    provenance = json.loads(version['provenance_json'])
    assert provenance['kind'] == 'obsidian_local' and provenance['schema_version'] == 1
    assert provenance['connection_id'] == connection['connection_id']
    assert provenance['vault_name'] == vault.name
    assert provenance['relative_path'] == '子目录/空格 目录/Deep Note.MD'
    assert provenance['sha256'] == hashlib.sha256(raw).hexdigest()
    assert provenance['captured_at'] and provenance['locator'] == {'kind': 'whole_document',
                                                                  'start_line': 1, 'end_line': 2}
    assert str(vault) not in version['provenance_json']
    base = f'/api/materials/conversation/{chat}'
    listed = client.get(base).json()['versions'][0]
    assert listed['id'] == version['id'] and listed['library'] is True
    download = client.get(base + f"/versions/{version['id']}/original")
    assert download.status_code == 200 and download.content == raw
    assert download.headers['content-type'] == 'application/octet-stream'
    assert client.get('/api/materials/library').json()['versions'][0]['id'] == version['id']
    frozen = client.app.state.materials.freeze(IDENTITY_OF(client), 'conversation', chat,
                                               {'mode': 'only', 'version_ids': [version['id']]})
    assert 'MATRIX reference' in client.app.state.materials.prompt(frozen)
    assert db_rows(client, '''SELECT COUNT(*) FROM learning_material_link
        WHERE scope_kind='conversation' AND scope_id=? AND version_id=?''', (chat, version['id']))[0][0] == 1


def IDENTITY_OF(client):
    return {'id': client.get('/api/auth/status').json()['identity']['id']}


def test_repeat_capture_reuses_group_and_version_across_scopes(client, tmp_path):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    connection = connect(client, vault).json()['connection']
    first_chat = start_conversation(client, create_task(client))
    second_chat = start_conversation(client, create_task(client))
    token = open_page(client, first_chat, connection, 'MATRIX')['items'][0]['selection_token']
    first = capture(client, first_chat, token).json()
    again = capture(client, first_chat, token).json()
    assert (again['id'], again['material_id'], again['version']) == (first['id'], first['material_id'], 1)
    other_token = open_page(client, second_chat, connection, 'MATRIX')['items'][0]['selection_token']
    borrowed = capture(client, second_chat, other_token).json()
    assert (borrowed['id'], borrowed['material_id'], borrowed['version']) == (first['id'], first['material_id'], 1)
    assert db_rows(client, 'SELECT COUNT(*) FROM learning_task_material WHERE material_id=?',
                   (first['material_id'],))[0][0] == 1
    for chat in (first_chat, second_chat):
        assert client.app.state.materials.freeze(IDENTITY_OF(client), 'conversation', chat,
                                                 {'mode': 'reference', 'version_ids': [first['id']]})['materials'][0]['content'] == NOTE


def test_source_change_appends_version_and_keeps_old_basis(client, tmp_path):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    note = vault / '子目录' / '空格 目录' / 'Deep Note.MD'
    connection = connect(client, vault).json()['connection']
    chat = start_conversation(client, create_task(client))
    first = capture(client, chat, open_page(client, chat, connection, 'MATRIX')['items'][0]['selection_token']).json()
    original_basis = client.app.state.materials.freeze(IDENTITY_OF(client), 'conversation', chat,
                                                       {'mode': 'only', 'version_ids': [first['id']]})
    note.write_text('# Deep\nMATRIX rewritten\n', encoding='utf-8')
    second = capture(client, chat, open_page(client, chat, connection, 'MATRIX')['items'][0]['selection_token']).json()
    assert second['material_id'] == first['material_id'] and second['version'] == 2
    assert second['content'] == '# Deep\nMATRIX rewritten\n' and second['id'] != first['id']
    note.write_text(NOTE, encoding='utf-8')
    third = capture(client, chat, open_page(client, chat, connection, 'MATRIX')['items'][0]['selection_token']).json()
    assert (third['material_id'], third['version']) == (first['material_id'], 3)
    assert third['id'] not in (first['id'], second['id'])
    base = f'/api/materials/conversation/{chat}'
    assert client.get(base).json()['versions'][0]['content'] == NOTE
    assert client.get(base + f"/versions/{first['id']}/original").content == NOTE.encode()
    assert client.app.state.materials.prompt(client.app.state.materials.freeze(
        IDENTITY_OF(client), 'conversation', chat, original_basis)) == \
        client.app.state.materials.prompt(original_basis)


def test_manual_edit_forces_a_new_captured_version(client, tmp_path):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    connection = connect(client, vault).json()['connection']
    chat = start_conversation(client, create_task(client))
    first = capture(client, chat, open_page(client, chat, connection, 'MATRIX')['items'][0]['selection_token']).json()
    edited = client.post(f'/api/materials/conversation/{chat}',
                         json={'title': '我的改写', 'content': 'MY OWN NOTES', 'material_id': first['material_id']})
    assert edited.status_code == 201 and edited.json()['version'] == 2
    third = capture(client, chat, open_page(client, chat, connection, 'MATRIX')['items'][0]['selection_token']).json()
    assert third['version'] == 3 and third['content'] == NOTE
    assert client.get(f'/api/materials/conversation/{chat}').json()['versions'][1]['content'] == 'MY OWN NOTES'


def test_failed_capture_transaction_leaves_no_partial_rows(client, tmp_path, monkeypatch):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    connection = connect(client, vault).json()['connection']
    chat = start_conversation(client, create_task(client))
    first = capture(client, chat, open_page(client, chat, connection, 'MATRIX')['items'][0]['selection_token']).json()
    monkeypatch.setattr('app.materials.uuid4', lambda: first['id'])
    page = open_page(client, chat, connection, '普通笔记')
    with pytest.raises(sqlite3.IntegrityError):
        capture(client, chat, page['items'][0]['selection_token'])
    assert [item['id'] for item in client.get(f'/api/materials/conversation/{chat}').json()['versions']] == [first['id']]
    assert db_rows(client, 'SELECT COUNT(*) FROM learning_task_material')[0][0] == 1
    assert db_rows(client, 'SELECT COUNT(*) FROM learning_material_original')[0][0] == 1
    assert db_rows(client, 'SELECT COUNT(*) FROM learning_material_library')[0][0] == 1
    assert db_rows(client, '''SELECT COUNT(*) FROM learning_material_link
        WHERE version_id NOT IN (SELECT id FROM learning_task_material)''')[0][0] == 0
    assert client.get('/api/materials/library').json()['versions'][0]['title'] == 'Deep Note'


def test_source_status_reports_change_missing_and_disconnect(client, tmp_path):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    note = vault / '子目录' / '空格 目录' / 'Deep Note.MD'
    connection = connect(client, vault).json()['connection']
    chat = start_conversation(client, create_task(client))
    saved = capture(client, chat, open_page(client, chat, connection, 'MATRIX')['items'][0]['selection_token']).json()
    path = f"/api/obsidian/conversation/{chat}/versions/{saved['id']}/source-status"
    assert client.get(path).json()['status'] == 'same_as_snapshot'
    assert client.get(path).json()['checked_at']
    note.write_text('# Deep\nMATRIX changed again\n', encoding='utf-8')
    assert client.get(path).json()['status'] == 'changed'
    os.rename(note, vault / '子目录' / '空格 目录' / 'renamed.md')
    assert client.get(path).json()['status'] == 'missing'
    note.write_text(NOTE, encoding='utf-8')
    assert client.get(path).json()['status'] == 'same_as_snapshot'
    client.post('/api/obsidian/connection/disconnect', json={'expected_revision': connection['revision']})
    assert client.get(path).json() == {'status': 'disconnected', 'checked_at': None}
    typed = client.post(f'/api/materials/conversation/{chat}', json={'title': '手写', 'content': 'typed'}).json()
    assert client.get(f"/api/obsidian/conversation/{chat}/versions/{typed['id']}/source-status").json() == \
        {'status': 'not_applicable', 'checked_at': None}
    other = start_conversation(client, create_task(client))
    assert client.get(f"/api/obsidian/conversation/{other}/versions/{saved['id']}/source-status").status_code == 404


def test_purge_scrubs_snapshot_backup_and_blocks_restore(client, tmp_path):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    connection = connect(client, vault).json()['connection']
    chat = start_conversation(client, create_task(client))
    saved = capture(client, chat, open_page(client, chat, connection, 'MATRIX')['items'][0]['selection_token']).json()
    typed = client.post(f'/api/materials/conversation/{chat}', json={'title': 'Unrelated', 'content': 'UNRELATED_TEXT'}).json()
    learning_path = client.app.state.settings.learning_database_path
    backup, _, _ = create_learning_backup(learning_path, tmp_path / 'backups', label='before-obsidian-purge')
    # An unmanaged copy keeps the pre-purge private content; the managed backup must not.
    unmanaged = tmp_path / 'unmanaged.sqlite3'
    with closing(sqlite3.connect(unmanaged)) as target:
        client.app.state.learning.database.connection.backup(target)
    stale_token = open_page(client, chat, connection, 'MATRIX')['items'][0]['selection_token']
    purged = client.post(f'/api/materials/conversation/{chat}/{saved["material_id"]}/purge',
                         json={'confirmation': 'PURGE'})
    assert purged.status_code == 200 and purged.json()['purge']['status'] == 'complete', purged.text
    assert client.post(f'/api/obsidian/conversation/{chat}/capture',
                       json={'selection_token': stale_token}).status_code == 409
    for path in (learning_path, backup):
        with closing(sqlite3.connect(path)) as connection_to:
            rows = connection_to.execute('''SELECT m.title,m.content,m.provenance_json,o.content,o.sha256
                FROM learning_task_material m LEFT JOIN learning_material_original o ON o.version_id=m.id
                WHERE m.material_id=?''', (saved['material_id'],)).fetchall()
        assert rows and all(row == (None, None, '{}', None, None) for row in rows), (path, rows)
        assert b'MATRIX reference' not in path.read_bytes()
    listed = client.get(f'/api/materials/conversation/{chat}').json()['versions']
    assert [item['title'] for item in listed if not item['purged_at']] == ['Unrelated']
    assert client.get('/api/materials/library').json()['versions'] == []
    # Restoring a snapshot that still holds the purged content is refused: the
    # pre-purge copy cannot revive the snapshot, original or source metadata.
    current = tmp_path / 'current-copy.sqlite3'
    with closing(sqlite3.connect(current)) as target:
        client.app.state.learning.database.connection.backup(target)
    shutil.copytree(tmp_path / 'runtime' / f'purge-{learning_path.name}',
                    tmp_path / 'runtime' / f'purge-{current.name}')
    assert b'MATRIX reference' in unmanaged.read_bytes()
    with pytest.raises(ProductionLearningDatabaseError, match='purged content'):
        restore_learning_backup(unmanaged, current)
    with closing(sqlite3.connect(current)) as probe:
        assert probe.execute('SELECT COUNT(*) FROM learning_task_material WHERE purged_at IS NULL').fetchone()[0] == 1
    assert b'MATRIX reference' not in current.read_bytes()
    again = capture(client, chat, open_page(client, chat, connection, 'MATRIX')['items'][0]['selection_token']).json()
    assert again['material_id'] != saved['material_id'] and again['version'] == 1
    assert again['content'] == NOTE and typed['id'] not in (again['id'], saved['id'])


@pytest.mark.asyncio
async def test_discussion_scope_reuses_the_same_entry_and_stays_scoped(learning_database, tmp_path):  # noqa: F811
    import httpx
    from fastapi import FastAPI
    from app.credentials import CredentialStore
    from app.dependencies import current_identity
    from app.materials import MaterialService
    from app.obsidian import ObsidianService
    from app.question_discussion import QuestionDiscussionService
    from app.routers import obsidian as obsidian_router

    verification, source = await attempt(learning_database)
    discussions = QuestionDiscussionService(verification)
    discussion = discussions.create(IDENTITY, source['id'], source['latest_submission_id'], 'q1', 'source')
    materials = MaterialService(discussions.learning, discussions.chats)
    service = ObsidianService(CredentialStore(tmp_path / 'credentials'), materials)
    materials.obsidian = service
    vault, _ = build_vault(tmp_path)
    app = FastAPI()
    app.include_router(obsidian_router.router)
    app.state.obsidian = service
    app.dependency_overrides[current_identity] = lambda: IDENTITY
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://isolated') as http:
        created = await http.put('/api/obsidian/connection',
                                 json={'root_path': str(vault), 'expected_revision': None})
        connection = created.json()['connection']
        scope = f"/api/obsidian/discussion/{discussion['id']}"
        page = await http.post(scope + '/search', json=body(connection, 'MATRIX'))
        assert page.status_code == 200, page.text
        item = page.json()['items'][0]
        saved = await http.post(scope + '/capture', json={'selection_token': item['selection_token']})
        assert saved.status_code == 201, saved.text
        assert saved.json()['content'] == NOTE
        assert (await http.get(scope + f"/versions/{saved.json()['id']}/source-status")).json()['status'] == 'same_as_snapshot'
        missing = await http.post('/api/obsidian/discussion/not-a-discussion/search', json=body(connection))
        assert (missing.status_code, missing.json()['detail']) == (404, 'not_found')
    assert materials.library(IDENTITY)['versions'][0]['id'] == saved.json()['id']
    assert materials.original(IDENTITY, 'discussion', discussion['id'],
                              saved.json()['id'])['content'] == NOTE.encode()
    # A scope that never selected the snapshot cannot read it, and an unknown scope is 404.
    with pytest.raises(DomainError):
        materials.original(IDENTITY, 'discussion', 'not-a-discussion', saved.json()['id'])
    with pytest.raises(DomainError):
        materials.freeze(IDENTITY, 'discussion', 'not-a-discussion',
                         {'mode': 'only', 'version_ids': [saved.json()['id']]})


def test_obsidian_snapshot_reaches_model_input_and_keeps_outbound_gate(tmp_path):
    """A captured note is ordinary private material: it enters the prompt and stays behind A2."""
    from test_outbound_runtime import SEARCH_URL, _decide, _handler, _pending, _search_calls, _setup

    marker = 'OBSIDIAN_PRIVATE_MARKER_5162'
    handler, calls = _handler(query=marker)
    with make_client(tmp_path, handler) as client:
        conversation = _setup(client)
        vault = tmp_path / 'Boundary Vault'
        vault.mkdir()
        (vault / 'boundary.md').write_text(f'# Boundary\n{marker}\n', encoding='utf-8')
        connection = client.put('/api/obsidian/connection',
                                json={'root_path': str(vault), 'expected_revision': None}).json()['connection']
        page = client.post(f'/api/obsidian/conversation/{conversation}/search', json={
            'connection_id': connection['connection_id'], 'connection_revision': connection['revision'],
            'query': 'boundary', 'after': None}).json()
        saved = client.post(f'/api/obsidian/conversation/{conversation}/capture',
                            json={'selection_token': page['items'][0]['selection_token']}).json()
        sent = client.post(f'/api/ai/conversations/{conversation}/messages', json={
            'content': 'Explain the saved note briefly', 'client_message_id': 'obsidian-boundary',
            'source_scope': {'mode': 'reference', 'version_ids': [saved['id']]},
            'search': {'mode': 'external', 'service_id': 'tavily-test', 'query': 'general concepts'}})
        assert sent.status_code == 202, sent.text
        item = _pending(client, conversation)
        assert _search_calls(calls) == []
        model_payloads = [payload for url, payload in calls if url != SEARCH_URL and payload.get('stream')]
        assert model_payloads, calls
        assert marker in json.dumps(model_payloads[0], ensure_ascii=False)
        assert str(vault) not in json.dumps(calls, ensure_ascii=False)
        assert _decide(client, item, 'deny').status_code == 200
        assert _search_calls(calls) == []
