"""Local Obsidian connection, path safety, read-only search and selection tokens."""
import hashlib
import json
import os
import threading
from pathlib import Path

import pytest

from app.learning_domain import DomainError
from app.main import create_app
from app.purge_storage import receipt_path, write_json
from conftest import build_settings
from test_ai_conversations import authorize, create_task, start_conversation
from test_obsidian_materials import build_vault, connect


def search_body(connection, query='', after=None):
    return {'connection_id': connection['connection_id'],
            'connection_revision': connection['revision'], 'query': query, 'after': after}


def search(client, scope, connection, query='', after=None):
    return client.post(f'/api/obsidian/conversation/{scope}/search',
                       json=search_body(connection, query, after))


def test_unauthenticated_requests_are_rejected(client):
    assert client.get('/api/obsidian/connection').status_code == 401
    assert client.put('/api/obsidian/connection', json={'root_path': '/tmp', 'expected_revision': None}).status_code == 401
    assert client.post('/api/obsidian/connection/disconnect', json={'expected_revision': 1}).status_code == 401
    assert client.post('/api/obsidian/conversation/chat/search', json={
        'connection_id': 'made-up', 'connection_revision': 1, 'query': '', 'after': None}).status_code == 401


def test_connection_lifecycle_revisions_and_owner_scope(client, tmp_path):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    other = tmp_path / 'Other Vault'
    other.mkdir()
    assert client.get('/api/obsidian/connection').json() == {'connection': None}
    invalid = connect(client, 'relative/vault')
    assert (invalid.status_code, invalid.json()['detail']) == (422, 'obsidian_path_invalid')
    assert connect(client, tmp_path / 'missing').status_code == 422
    (tmp_path / 'notes.md').write_text('not a vault\n', encoding='utf-8')
    assert connect(client, tmp_path / 'notes.md').status_code == 422
    assert client.put('/api/obsidian/connection',
                      json={'root_path': str(vault), 'expected_revision': None, 'extra': 1}).status_code == 422
    first = connect(client, vault).json()['connection']
    assert first['revision'] == 1 and first['enabled'] is True
    assert first['root_path'] == str(vault.resolve()) and first['vault_name'] == vault.name
    assert client.get('/api/obsidian/connection').json() == {'connection': first}
    assert client.get('/api/obsidian/connection').headers['cache-control'] == 'no-store'
    assert connect(client, vault).status_code == 409
    assert connect(client, vault, expected=7).status_code == 409
    again = connect(client, vault, expected=1).json()['connection']
    assert again['revision'] == 2 and again['connection_id'] == first['connection_id']
    moved = connect(client, other, expected=2).json()['connection']
    assert moved['revision'] == 3 and moved['connection_id'] != first['connection_id']
    assert client.post('/api/obsidian/connection/disconnect', json={'expected_revision': 99}).status_code == 409
    stopped = client.post('/api/obsidian/connection/disconnect', json={'expected_revision': 3}).json()['connection']
    assert stopped['enabled'] is False and stopped['revision'] == 4
    assert client.get('/api/obsidian/connection').json()['connection']['enabled'] is False
    resumed = connect(client, other, expected=4).json()['connection']
    assert resumed['enabled'] is True and resumed['revision'] == 5
    assert resumed['connection_id'] == stopped['connection_id']


def test_path_failure_preserves_previous_configuration(client, tmp_path):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    first = connect(client, vault).json()['connection']
    broken = connect(client, tmp_path / 'gone', expected=1)
    assert (broken.status_code, broken.json()['detail']) == (422, 'obsidian_path_invalid')
    assert client.get('/api/obsidian/connection').json()['connection'] == first


def test_disconnect_persists_across_restart_and_stops_reads(tmp_path):
    from fastapi.testclient import TestClient
    settings = build_settings(tmp_path)
    vault, _ = build_vault(tmp_path)
    with TestClient(create_app(settings)) as first_client:
        authorize(first_client)
        connection = connect(first_client, vault).json()['connection']
        chat = start_conversation(first_client, create_task(first_client))
        assert search(first_client, chat, connection).status_code == 200
        assert first_client.post('/api/obsidian/connection/disconnect',
                                 json={'expected_revision': 1}).json()['connection']['enabled'] is False
    with TestClient(create_app(settings)) as second_client:
        authorize(second_client)
        stored = second_client.get('/api/obsidian/connection').json()['connection']
        assert stored['enabled'] is False and stored['revision'] == 2
        denied = second_client.post(f'/api/obsidian/conversation/{chat}/search',
                                    json=search_body({**stored, 'revision': 2}))
        assert (denied.status_code, denied.json()['detail']) == (409, 'obsidian_disconnected')


def test_search_lists_supported_notes_and_reports_partial_reads(client, tmp_path):
    authorize(client)
    vault, outside = build_vault(tmp_path)
    connection = connect(client, vault).json()['connection']
    chat = start_conversation(client, create_task(client))
    result = search(client, chat, connection)
    assert result.status_code == 200
    assert result.headers['cache-control'] == 'no-store'
    payload = result.json()
    paths = [item['relative_path'] for item in payload['items']]
    assert paths == sorted(paths)
    assert '笔记 一.md' in paths and '子目录/空格 目录/Deep Note.MD' in paths
    assert not any(path.startswith(('.obsidian', '.git', '.trash')) for path in paths)
    assert 'link.md' not in paths and 'linked-dir/hidden.md' not in paths
    assert 'picture.png' not in paths and '坏.md' not in paths
    assert payload['unreadable_count'] == 1 and payload['complete'] is False
    assert payload['has_more'] is False and payload['next_after'] is None
    item = next(row for row in payload['items'] if row['relative_path'] == '笔记 一.md')
    assert item['title'] == '笔记 一'
    assert item['excerpt'].startswith('# 标题') and item['excerpt_start_line'] == 1
    assert item['sha256'] == hashlib.sha256((vault / '笔记 一.md').read_bytes()).hexdigest()
    assert item['selection_token'] and outside['secret'] not in json.dumps(payload, ensure_ascii=False)


def test_content_and_path_matches_with_encoding_and_casefold(client, tmp_path):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    connection = connect(client, vault).json()['connection']
    chat = start_conversation(client, create_task(client))
    content = search(client, chat, connection, 'MATRIX').json()
    paths = [item['relative_path'] for item in content['items']]
    assert '子目录/空格 目录/Deep Note.MD' in paths and '笔记 一.md' not in paths
    assert content['items'][0]['excerpt'] == 'MATRIX reference'
    assert content['items'][0]['excerpt_start_line'] == 2
    by_path = search(client, chat, connection, '空格 目录').json()
    assert [item['relative_path'] for item in by_path['items']] == ['子目录/空格 目录/Deep Note.MD']
    chinese = search(client, chat, connection, '矩阵乘法').json()
    assert [item['relative_path'] for item in chinese['items']] == ['笔记 一.md']
    assert chinese['items'][0]['excerpt'] == '矩阵乘法的定义与例子'
    none = search(client, chat, connection, '没有这段文字').json()
    assert none['items'] == [] and none['complete'] is False and none['unreadable_count'] == 1
    assert search(client, chat, connection, 'x' * 501).status_code == 422
    assert search(client, chat, connection, 'ok', after='/etc/passwd').status_code == 422


def test_search_pagination_uses_stable_relative_path_cursor(client, tmp_path):
    authorize(client)
    root = tmp_path / 'Paged Vault'
    root.mkdir()
    for index in range(57):
        (root / f'note-{index:03d}.md').write_text(f'正文 {index}\n', encoding='utf-8')
    connection = connect(client, root).json()['connection']
    chat = start_conversation(client, create_task(client))
    first = search(client, chat, connection).json()
    assert len(first['items']) == 50 and first['has_more'] is True
    assert first['next_after'] == first['items'][-1]['relative_path'] == 'note-049.md'
    second = search(client, chat, connection, after=first['next_after']).json()
    assert [item['relative_path'] for item in second['items']][:2] == ['note-050.md', 'note-051.md']
    assert len(second['items']) == 7 and second['has_more'] is False and second['next_after'] is None


def test_scope_and_connection_checks_happen_before_reading(client, tmp_path):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    connection = connect(client, vault).json()['connection']
    chat = start_conversation(client, create_task(client))
    unknown = client.post('/api/obsidian/conversation/does-not-exist/search', json=search_body(connection))
    assert (unknown.status_code, unknown.json()['detail']) == (404, 'not_found')
    stale = client.post(f'/api/obsidian/conversation/{chat}/search',
                        json={**search_body(connection),
                              'connection_revision': connection['revision'] + 1})
    assert (stale.status_code, stale.json()['detail']) == (409, 'obsidian_connection_revision')
    foreign = client.post(f'/api/obsidian/conversation/{chat}/search',
                          json={**search_body(connection), 'connection_id': 'made-up'})
    assert foreign.status_code == 409
    assert client.post(f'/api/obsidian/conversation/{chat}/capture',
                       json={'selection_token': 'forged'}).status_code == 409
    forged = client.post(f'/api/obsidian/conversation/{chat}/capture',
                         json={'selection_token': 'forged', 'content': 'FORGED_CONTENT',
                               'provenance_json': '{"kind":"obsidian_local"}'})
    assert forged.status_code == 422
    assert client.post(f'/api/obsidian/discussion/does-not-exist/capture',
                       json={'selection_token': 'forged'}).status_code == 404


def test_unavailable_vault_is_not_reported_as_empty(client, tmp_path):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    connection = connect(client, vault).json()['connection']
    chat = start_conversation(client, create_task(client))
    os.rename(vault, tmp_path / 'moved-away')
    result = search(client, chat, connection)
    assert (result.status_code, result.json()['detail']) == (503, 'obsidian_vault_unavailable')


def test_vault_bytes_and_tree_stay_untouched_by_search_and_capture(client, tmp_path):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    connection = connect(client, vault).json()['connection']
    chat = start_conversation(client, create_task(client))
    before = snapshot(vault)
    result = search(client, chat, connection, 'MATRIX').json()
    captured = client.post(f'/api/obsidian/conversation/{chat}/capture',
                           json={'selection_token': result['items'][0]['selection_token']})
    assert captured.status_code == 201
    assert snapshot(vault) == before


def snapshot(root: Path):
    return sorted((str(path.relative_to(root)), path.read_bytes() if path.is_file() else b'')
                  for path in root.rglob('*') if not path.is_dir())


def test_selection_token_binds_owner_scope_page_and_read_generation(client, tmp_path):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    connection = connect(client, vault).json()['connection']
    chat = start_conversation(client, create_task(client))
    other = start_conversation(client, create_task(client))
    page = search(client, chat, connection, 'MATRIX').json()
    token = page['items'][0]['selection_token']
    # A newer page for the same scope replaces the previous candidates.
    assert search(client, chat, connection).status_code == 200
    assert client.post(f'/api/obsidian/conversation/{chat}/capture',
                       json={'selection_token': token}).status_code == 409
    fresh = search(client, chat, connection, 'MATRIX').json()
    cross_scope = client.post(f'/api/obsidian/conversation/{other}/capture',
                              json={'selection_token': fresh['items'][0]['selection_token']})
    assert cross_scope.status_code == 409
    accepted = client.post(f'/api/obsidian/conversation/{chat}/capture',
                           json={'selection_token': fresh['items'][0]['selection_token']})
    assert accepted.status_code == 201
    assert accepted.json()['content'].startswith('# Deep')
    disconnected = client.post('/api/obsidian/connection/disconnect',
                               json={'expected_revision': connection['revision']}).json()['connection']
    assert disconnected['enabled'] is False
    assert client.post(f'/api/obsidian/conversation/{chat}/capture',
                       json={'selection_token': fresh['items'][0]['selection_token']}).status_code == 409


def test_source_change_and_blank_note_are_refused_without_saving(client, tmp_path):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    connection = connect(client, vault).json()['connection']
    chat = start_conversation(client, create_task(client))
    page = search(client, chat, connection, 'MATRIX').json()
    token = page['items'][0]['selection_token']
    (vault / '子目录' / '空格 目录' / 'Deep Note.MD').write_text('# Deep\nMATRIX changed\n', encoding='utf-8')
    changed = client.post(f'/api/obsidian/conversation/{chat}/capture', json={'selection_token': token})
    assert (changed.status_code, changed.json()['detail']) == (409, 'obsidian_source_changed')
    assert client.get(f'/api/materials/conversation/{chat}').json()['versions'] == []
    blank = search(client, chat, connection, 'blank').json()
    assert blank['items'] and blank['items'][0]['relative_path'] == 'blank.md'
    empty = client.post(f'/api/obsidian/conversation/{chat}/capture',
                        json={'selection_token': blank['items'][0]['selection_token']})
    assert (empty.status_code, empty.json()['detail']) == (422, 'obsidian_note_empty')
    assert client.get(f'/api/materials/conversation/{chat}').json()['versions'] == []


def test_pending_purge_receipt_blocks_new_capture(client, tmp_path):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    connection = connect(client, vault).json()['connection']
    chat = start_conversation(client, create_task(client))
    owner = client.get('/api/auth/status').json()['identity']['id']
    page = search(client, chat, connection, 'MATRIX').json()
    learning_path = client.app.state.settings.learning_database_path
    write_json(receipt_path(learning_path, owner, 'material', 'synthetic-group'),
               {'owner': owner, 'kind': 'material', 'object_id': 'synthetic-group', 'status': 'partial'})
    blocked = client.post(f'/api/obsidian/conversation/{chat}/capture',
                          json={'selection_token': page['items'][0]['selection_token']})
    assert (blocked.status_code, blocked.json()['detail']) == (409, 'obsidian_purge_pending')
    write_json(receipt_path(learning_path, owner, 'material', 'synthetic-group'),
               {'owner': owner, 'kind': 'material', 'object_id': 'synthetic-group', 'status': 'complete'})
    assert client.post(f'/api/obsidian/conversation/{chat}/capture',
                       json={'selection_token': page['items'][0]['selection_token']}).status_code == 201


def test_replaced_root_ancestor_cannot_be_read_outside_the_authorized_vault(client, tmp_path):
    authorize(client)
    parent = tmp_path / 'vault-parent'
    vault = parent / 'Authorized Vault'
    vault.mkdir(parents=True)
    (vault / 'note.md').write_text('AUTHORIZED_NOTE_4417\n', encoding='utf-8')
    connection = connect(client, vault).json()['connection']
    chat = start_conversation(client, create_task(client))
    assert [item['relative_path'] for item in search(client, chat, connection, 'AUTHORIZED').json()['items']] == ['note.md']
    # Replace an ancestor of the saved root with a link to an identically named vault.
    attacker = tmp_path / 'attacker'
    (attacker / 'Authorized Vault').mkdir(parents=True)
    (attacker / 'Authorized Vault' / 'note.md').write_text('OUTSIDE_MARKER_4417\n', encoding='utf-8')
    os.rename(parent, tmp_path / 'vault-parent-moved')
    os.symlink(attacker, parent)
    result = search(client, chat, connection)
    assert (result.status_code, result.json()['detail']) == (503, 'obsidian_vault_unavailable')
    assert 'OUTSIDE_MARKER_4417' not in result.text and 'AUTHORIZED_NOTE_4417' not in result.text


def test_note_replaced_by_fifo_is_rejected_without_blocking(client, tmp_path):
    authorize(client)
    vault, _ = build_vault(tmp_path)
    connection = connect(client, vault).json()['connection']
    chat = start_conversation(client, create_task(client))
    owner = {'id': client.get('/api/auth/status').json()['identity']['id']}
    service = client.app.state.obsidian
    page = search(client, chat, connection, 'MATRIX').json()
    saved = client.post(f'/api/obsidian/conversation/{chat}/capture',
                        json={'selection_token': page['items'][0]['selection_token']}).json()
    note = vault.joinpath(*page['items'][0]['relative_path'].split('/'))
    note.unlink()
    os.mkfifo(note)
    token = page['items'][0]['selection_token']
    outcome = {}

    def attempt():
        try:
            outcome['result'] = service.capture(owner, 'conversation', chat, selection_token=token)
        except BaseException as error:  # noqa: BLE001 - asserted below
            outcome['error'] = error

    capture = threading.Thread(target=attempt)
    capture.start()
    capture.join(10)
    assert not capture.is_alive(), 'capture blocked on a FIFO without a writer'
    error = outcome.get('error')
    assert isinstance(error, DomainError) and error.code == 'obsidian_note_unsupported', outcome
    status = {}

    def inspect():
        status['value'] = service.source_status(owner, 'conversation', chat, saved['id'])

    check = threading.Thread(target=inspect)
    check.start()
    check.join(10)
    assert not check.is_alive(), 'source status blocked on a FIFO without a writer'
    assert status['value']['status'] == 'unavailable' and status['value']['checked_at']
    # The FIFO is not a note any more, so it is not listed for a new search either.
    assert [item['relative_path'] for item in search(client, chat, connection, 'MATRIX').json()['items']] == []


def test_first_page_of_unreadable_notes_still_advances(client, tmp_path):
    authorize(client)
    root = tmp_path / 'Broken Vault'
    root.mkdir()
    for index in range(50):
        (root / f'broken-{index:02d}.md').write_bytes(b'\xff\xfe\x00bad')
    (root / 'zz-good.md').write_text('GOOD_NOTE_4113\n', encoding='utf-8')
    connection = connect(client, root).json()['connection']
    chat = start_conversation(client, create_task(client))
    first = search(client, chat, connection).json()
    assert first['items'] == [] and first['has_more'] is True
    assert first['next_after'] == 'broken-49.md' and first['unreadable_count'] == 50
    assert first['complete'] is False
    second = search(client, chat, connection, after=first['next_after']).json()
    assert [item['relative_path'] for item in second['items']] == ['zz-good.md']
    assert second['has_more'] is False and second['next_after'] is None and second['complete'] is True
    assert [item['relative_path'] for item in search(client, chat, connection).json()['items']] == []


def test_page_tail_unreadable_still_reaches_later_notes(client, tmp_path):
    authorize(client)
    root = tmp_path / 'Tail Vault'
    root.mkdir()
    for index in range(49):
        (root / f'good-{index:02d}.md').write_text(f'Normal note {index}\n', encoding='utf-8')
    (root / 'tail-broken.md').write_bytes(b'\xff\xfe\x00bad')
    (root / 'zz-later.md').write_text('LATER_NOTE_8823\n', encoding='utf-8')
    connection = connect(client, root).json()['connection']
    chat = start_conversation(client, create_task(client))
    first = search(client, chat, connection).json()
    assert len(first['items']) == 49 and first['unreadable_count'] == 1 and first['complete'] is False
    assert first['has_more'] is True and first['next_after'] == 'tail-broken.md'
    second = search(client, chat, connection, after=first['next_after']).json()
    assert [item['relative_path'] for item in second['items']] == ['zz-later.md']
    assert second['has_more'] is False and second['next_after'] is None
