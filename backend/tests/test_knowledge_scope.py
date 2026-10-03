"""Real local reads: selection revocation, immutable locators and copy ownership."""
import asyncio
import hashlib
import json
import threading

import pytest

from app.knowledge import KnowledgeRun
from app.learning_domain import DomainError
from app.obsidian import Vault
from app.search_runtime import merge_knowledge_reference
from app.source_runtime import public_scope, scope_key
from test_ai_conversations import authorize, create_task, start_conversation
from test_obsidian_materials import connect


def setup(client, tmp_path, *, selected=True):
    authorize(client)
    root = tmp_path / 'Synthetic Vault'
    root.mkdir()
    content = '\n'.join(f'line {i}' for i in range(1, 101)) + '\n'
    content = content.replace('line 50\n', 'matrix evidence line 50\n')
    (root / 'note.md').write_text(content)
    conn = connect(client, root).json()['connection']
    chat = start_conversation(client, create_task(client))
    identity = client.get("/api/auth/status").json()["identity"]
    selection = {'mode': 'only', 'version_ids': [], 'knowledge_base': {
        'kind': 'obsidian_local', 'connection_id': conn['connection_id'],
        'connection_revision': conn['revision']}}
    if selected:
        response = client.put(f'/api/conversation-state/conversation/{chat}', json={
            'expected_revision': 0, 'source_scope': selection})
        assert response.status_code == 200, response.text
    return root, conn, chat, identity, selection, content


def run_for(client, chat, identity, selection, *, register=None):
    materials = client.app.state.materials
    frozen = materials.freeze(identity, 'conversation', chat, selection)
    scopes = [public_scope(frozen)]
    def save(version, ref):
        # Snapshot and original exist before the callback can expose a snippet.
        row = materials.db.fetchone('SELECT content FROM learning_task_material WHERE id=?', (version['id'],))
        assert row['content'] == version['content']
        assert materials.original(identity, 'conversation', chat, version['id'])['content']
        scopes.append(merge_knowledge_reference(scopes[-1], version, ref))
        return scopes[-1]
    run = KnowledgeRun(materials, identity, 'conversation', chat, frozen,
                       active=lambda: True, register=register or save)
    return run, scopes


def invoke(run, tool='search_knowledge_base', params=None):
    return asyncio.run(run.invoke(tool, params or {'query': 'matrix'}))


def test_immutable_line_evidence_and_strict_key_do_not_change_with_retrieval(client, tmp_path):
    root, conn, chat, identity, selection, content = setup(client, tmp_path)
    run, scopes = run_for(client, chat, identity, selection)
    result = invoke(run)
    item = json.loads(result['content'])['items'][0]
    assert (item['start_line'], item['end_line']) == (47, 53)
    assert item['text'] == '\n'.join(content.splitlines()[46:53])
    assert item['sha256'] == hashlib.sha256(content.encode()).hexdigest()
    assert item['marker'] == '【资料1】'
    assert 'matrix evidence' not in json.dumps(result['result'])
    assert '_knowledge' not in json.dumps(scopes[-1]) and str(root) not in json.dumps(scopes[-1])
    assert scopes[-1]['selection_version_ids'] == []
    assert scope_key(scopes[0]) == scope_key(scopes[-1]) == scope_key(selection)
    (root / 'note.md').write_text('matrix changed\n')
    read = invoke(run, 'read_knowledge_note', {'version_id': item['version_id'], 'start_line': 49, 'end_line': 51})
    assert json.loads(read['content'])['text'] == '\n'.join(content.splitlines()[48:51])
    assert client.get('/api/materials/library').json()['versions'] == []
    with pytest.raises(DomainError, match='invalid_knowledge_request'):
        invoke(run, 'read_knowledge_note', {'version_id': item['version_id'], 'start_line': 1, 'end_line': 100})
    with pytest.raises(DomainError, match='invalid_knowledge_request'):
        invoke(run, 'read_knowledge_note', {'version_id': 'not-retrieved', 'start_line': 1, 'end_line': 2})


@pytest.mark.parametrize('revoke', ['deselect_reselect', 'disconnect', 'purge'])
def test_revocation_before_first_read_stops_inflight_retrieval(client, tmp_path, monkeypatch, revoke):
    root, conn, chat, identity, selection, _ = setup(client, tmp_path)
    run, scopes = run_for(client, chat, identity, selection)
    materials = client.app.state.materials
    disposable = materials.create(identity, 'conversation', chat, title='Synthetic', content='temporary')
    entered, release = threading.Event(), threading.Event()
    original = Vault.read
    def paused(self, path, guard=None):
        entered.set()
        assert release.wait(10)
        return original(self, path, guard)
    monkeypatch.setattr(Vault, 'read', paused)
    outcome = []
    def target():
        try:
            outcome.append(invoke(run))
        except BaseException as error:
            outcome.append(error)
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    assert entered.wait(10)
    try:
        if revoke == 'deselect_reselect':
            url = f'/api/conversation-state/conversation/{chat}'
            assert client.put(url, json={'expected_revision': 1}).status_code == 200
            assert client.put(url, json={'expected_revision': 2, 'source_scope': selection}).status_code == 200
        elif revoke == 'disconnect':
            assert client.post('/api/obsidian/connection/disconnect', json={'expected_revision': conn['revision']}).status_code == 200
            assert 'material_unavailable' in client.get(f'/api/conversation-state/conversation/{chat}').json()['issues']
        else:
            materials.purge(identity, disposable['material_id'])
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive()
    assert isinstance(outcome[0], DomainError), outcome
    assert not run.used and len(scopes) == 1
    assert all(json.loads(v['provenance_json']).get('kind') != 'obsidian_local'
               for v in materials.list(identity, 'conversation', chat)['versions'])


def test_automatic_copies_scope_local_until_explicit_library_promotion(client, tmp_path):
    root, conn, chat, identity, selection, _ = setup(client, tmp_path, selected=False)
    second = start_conversation(client, create_task(client))
    first_run, _ = run_for(client, chat, identity, selection)
    second_run, _ = run_for(client, second, identity, selection)
    one = json.loads(invoke(first_run)['content'])['items'][0]
    two = json.loads(invoke(second_run)['content'])['items'][0]
    assert one['material_id'] != two['material_id']
    materials = client.app.state.materials
    materials.store_in_library(identity, 'conversation', chat, one['material_id'])
    third = start_conversation(client, create_task(client))
    third_run, _ = run_for(client, third, identity, selection)
    three = json.loads(invoke(third_run)['content'])['items'][0]
    assert three['version_id'] == one['version_id']
    assert len(materials.library(identity)['versions']) == 1
    materials.remove_from_library(identity, one['material_id'])
    fresh, _ = run_for(client, third, identity, selection)
    assert json.loads(invoke(fresh)['content'])['items'][0]['version_id'] == one['version_id']
    assert materials.library(identity)['versions'] == []


def test_pagination_and_read_failures_are_visible_without_extra_evidence(client, tmp_path):
    root, conn, chat, identity, selection, _ = setup(client, tmp_path)
    for i in range(7):
        (root / f'extra-{i}.md').write_text(f'matrix {i}\n')
    (root / 'bad.md').write_bytes(b'\xff')
    run, scopes = run_for(client, chat, identity, selection)
    first = json.loads(invoke(run)['content'])
    assert len(first['items']) == 5 and first['has_more']
    assert not first['complete'] and first['unreadable_count'] == 1
    second = json.loads(invoke(run, params={'query': 'matrix', 'after': first['next_after']})['content'])
    assert len(second['items']) == 3 and not second['has_more']
    assert len(scopes[-1]['version_ids']) == 8
    with pytest.raises(DomainError, match='obsidian_query_invalid'):
        invoke(run, params={'query': 'different', 'after': first['next_after']})
    with pytest.raises(DomainError):
        invoke(run, params={'query': 'matrix', 'after': '../outside.md'})


def test_failed_answer_registration_never_returns_private_snippets(client, tmp_path):
    root, conn, chat, identity, selection, _ = setup(client, tmp_path)
    def canceled(version, reference):
        raise asyncio.CancelledError()
    run, _ = run_for(client, chat, identity, selection, register=canceled)
    with pytest.raises(asyncio.CancelledError):
        invoke(run)
    assert not run.used
    assert client.get('/api/materials/library').json()['versions'] == []
