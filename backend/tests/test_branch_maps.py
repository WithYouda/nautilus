import json
import sqlite3

import pytest

from app.branch_maps import discussion_map, rename_discussion
from app.discussion_branches import create_branch
from app.question_discussion import QuestionDiscussionService
from app.learning_domain import DomainError
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY
from test_verification_review import attempt
from test_discussion_branches import reply
from test_conversation_branches import branch, new_chat, send
from test_material_runtime import make_client, authorize, configure_provider, body_response


def test_ordinary_family_naming_manual_and_deleted_source(tmp_path):
    with make_client(tmp_path, lambda _: body_response('ANSWER')) as client:
        authorize(client); configure_provider(client)
        cid = new_chat(client)
        unrelated = new_chat(client)
        mid = send(client, cid, 'Which regex matches digits?')
        bid = branch(client, cid, mid).json()['conversation']['id']
        assert client.get(f'/api/ai/conversations/{bid}').json()['conversation']['title'] == 'Which regex matches digits?'
        with client.app.state.database.transaction() as c:
            c.execute("UPDATE conversation SET title='分支对话',title_source='manual',title_revision=0 WHERE id IN (?,?)", (bid, unrelated))
        assert client.get(f'/api/ai/conversations/{bid}').json()['conversation']['title'] == 'Which regex matches digits?'
        assert client.get(f'/api/ai/conversations/{unrelated}').json()['conversation']['title'] == '分支对话'

        send(client, bid, 'How do capture groups work?')
        assert client.get(f'/api/ai/conversations/{bid}').json()['conversation']['title'] == 'How do capture groups work?'
        send(client, bid, 'Another question')
        assert client.get(f'/api/ai/conversations/{bid}').json()['conversation']['title'] == 'How do capture groups work?'
        client.patch(f'/api/ai/conversations/{bid}', json={'title': 'My own title'})
        send(client, bid, 'Must not overwrite manual name')
        graph = client.get(f'/api/ai/conversations/{bid}/branch-map').json()
        assert {n['id'] for n in graph['nodes']} == {cid, bid}
        node = next(n for n in graph['nodes'] if n['id'] == bid)
        assert node['title'] == 'My own title'
        assert node['source_id'] == mid and node['source_excerpt'] == 'Which regex matches digits?'
        assert node['parent_id'] == cid and unrelated not in str(graph)
        client.delete(f'/api/ai/conversations/{cid}')
        graph = client.get(f'/api/ai/conversations/{bid}/branch-map').json()
        parent = next(n for n in graph['nodes'] if n['id'] == cid)
        child = next(n for n in graph['nodes'] if n['id'] == bid)
        assert parent['title'] == '对话已删除' and not parent['available']
        assert child['parent_id'] == cid and child['source_excerpt'] is None and child['source_id'] is None


@pytest.mark.asyncio
async def test_discussion_family_title_and_purge(learning_database):
    verification, original = await attempt(learning_database)
    service = QuestionDiscussionService(verification)
    d = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'source')
    service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'unrelated')
    first = (await reply(service, d['id'], 'Source question', 'first'))['turns'][0]
    fork = create_branch(service, IDENTITY, d['id'], first['id'], 'fork')
    assert fork['title'] == 'Source question'
    continued = await reply(service, fork['id'], 'New direction', 'second')
    assert continued['title'] == 'New direction'
    await reply(service, fork['id'], 'Later question', 'third')
    assert service.get(IDENTITY, fork['id'])['title'] == 'New direction'
    rename_discussion(service, IDENTITY, fork['id'], 'Manual title')
    await reply(service, fork['id'], 'Another new direction', 'fourth')
    graph = discussion_map(service, IDENTITY, fork['id'])
    assert {node['id'] for node in graph['nodes']} == {d['id'], fork['id']}
    node = next(n for n in graph['nodes'] if n['id'] == fork['id'])
    assert node['title'] == 'Manual title' and node['source_id'] == first['id']
    with pytest.raises(DomainError, match='not_found'):
        discussion_map(service, {**IDENTITY, 'id': 'owner-b'}, fork['id'])
    with pytest.raises(DomainError, match='not_found'):
        rename_discussion(service, {**IDENTITY, 'id': 'owner-b'}, fork['id'], 'x')
    # Whole source deletion keeps graph identifiers, never private titles or excerpts.
    verification.purge(IDENTITY, original['id'])
    graph = discussion_map(service, IDENTITY, fork['id'])
    assert len(graph['nodes']) == 2
    assert all(n['title'] == '内容已清除' and not n['available'] and n['source_excerpt'] is None for n in graph['nodes'])
    assert next(n for n in graph['nodes'] if n['id'] == fork['id'])['parent_id'] == d['id']
    assert learning_database.fetchone('SELECT title FROM learning_question_discussion WHERE id=?', (fork['id'],))[0] is None
    with pytest.raises(DomainError, match='artifact_not_eligible'):
        rename_discussion(service, IDENTITY, fork['id'], 'No resurrection')


@pytest.mark.asyncio
async def test_033_upgrade_preserves_all_existing_business_columns(learning_database, tmp_path):
    from contextlib import closing
    from app.learning_production import upgrade_learning_database
    verification, original = await attempt(learning_database)
    service = QuestionDiscussionService(verification)
    d = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'source')
    turn = (await reply(service, d['id'], 'Synthetic migration question', 'first'))['turns'][0]
    fork = create_branch(service, IDENTITY, d['id'], turn['id'], 'fork')
    # Match an initialized trial: the upgrade tool also reconciles existing identities.
    for identity in learning_database.fetchall('SELECT * FROM local_identity'):
        verification.link_legacy_submissions(dict(identity))
    legacy_path = tmp_path/'legacy-033.sqlite3'
    with closing(sqlite3.connect(legacy_path)) as c:
        learning_database.connection.backup(c)
        c.execute('DROP TRIGGER learning_discussion_purge_model_config')
        c.execute('DROP TABLE learning_model_config')
        c.execute('DROP TRIGGER learning_material_purge_ocr')
        c.execute('DROP TABLE learning_material_ocr')
        c.execute('DROP TRIGGER learning_material_purge_original')
        c.execute('DROP TABLE learning_material_original')
        c.execute('DROP TRIGGER learning_discussion_purge_materials')
        c.execute('DROP TABLE learning_material_link')
        c.execute('DROP TABLE learning_material_library')
        c.executescript('''CREATE TRIGGER learning_discussion_purge_materials
            AFTER UPDATE OF purged_at ON learning_question_discussion
            WHEN NEW.purged_at IS NOT NULL BEGIN
                UPDATE learning_task_material SET title=NULL,content=NULL,url=NULL,provenance_json='{}',purged_at=NEW.purged_at
                WHERE owner_id=NEW.owner_id AND scope_kind='discussion' AND scope_id=NEW.id AND purged_at IS NULL;
            END;''')
        c.execute('DROP TRIGGER learning_discussion_purge_current_state')
        c.execute('DROP TABLE learning_conversation_current_state')
        c.execute('DROP TRIGGER discussion_title_on_purge')
        c.execute('DROP TRIGGER discussion_title_on_turn_purge')
        for column in ('title', 'title_source', 'branch_parent_id', 'branch_turn_id'):
            c.execute(f'ALTER TABLE learning_question_discussion DROP COLUMN {column}')
        c.execute("DELETE FROM schema_migrations WHERE version >= '034'")
        c.commit()
        tables = [row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('schema_migrations','sqlite_sequence')")]
        columns = {t: [row[1] for row in c.execute(f'PRAGMA table_info("{t}")')] for t in tables}
        before = {t: c.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall() for t in tables}
    result = upgrade_learning_database(legacy_path, tmp_path/'backups', authorized=True)
    assert result['status'] == 'upgraded'
    assert result['preflight']['applied_migrations'][-1] == '033_task_materials'
    with closing(sqlite3.connect(legacy_path)) as c:
        for table, fields in columns.items():
            selection = ','.join('"'+field+'"' for field in fields)
            assert c.execute(f'SELECT {selection} FROM "{table}" ORDER BY rowid').fetchall() == before[table]
        assert c.execute('SELECT title,branch_parent_id,branch_turn_id FROM learning_question_discussion WHERE id=?', (fork['id'],)).fetchone() == (None,d['id'],turn['id'])
        assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []


@pytest.mark.asyncio
async def test_material_restore_rejects_title_only_resurrection(learning_database, tmp_path):
    from contextlib import closing
    from app.materials import MaterialService
    from app.material_purge import erase_learning
    from app.learning_production import restore_learning_backup, ProductionLearningDatabaseError
    from app.purge_storage import receipt_path, write_json
    from test_learning_verifications import response_transport
    verification, original = await attempt(learning_database)
    service = QuestionDiscussionService(verification)
    materials = MaterialService(service.learning, service.chats)
    service.chats.materials = materials
    d = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'source')
    material = materials.create(IDENTITY,'discussion',d['id'],title='Synthetic',content='private material')
    verification.transport = response_transport(['ANSWER'])
    turn = (await service.send(IDENTITY,d['id'],'private title','first',source_scope={'mode':'reference','version_ids':[material['id']]}))['turns'][0]
    with learning_database.transaction() as c:
        erase_learning(c, IDENTITY['id'], material['material_id'], 'now')
    write_json(receipt_path(learning_database.database_path, IDENTITY['id'], 'material', material['material_id']),
        dict(status='complete', kind='material', owner=IDENTITY['id'], object_id=material['material_id'],
             source_turn_ids=[turn['id']], updated_at='now'))
    backup = tmp_path/'title-only.sqlite3'
    with closing(sqlite3.connect(backup)) as c:
        learning_database.connection.backup(c)
        c.execute('UPDATE learning_question_discussion SET title=? WHERE id=?', ('private title', d['id']))
        c.commit()
    with pytest.raises(ProductionLearningDatabaseError, match='purged private content'):
        restore_learning_backup(backup, learning_database.database_path)
    assert learning_database.fetchone('SELECT title FROM learning_question_discussion WHERE id=?', (d['id'],))[0] is None
