"""A library material survives its source discussion, but explicit erasure wins."""
import sqlite3
from contextlib import closing

import pytest

from app.learning_production import (
    ProductionLearningDatabaseError,
    create_learning_backup,
    restore_learning_backup,
)
from app.managed_purge import ManagedPurge
from app.materials import MaterialService
from app.question_discussion import QuestionDiscussionService
from app.purge_content import erase
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import (
    CHALLENGE, IDENTITY, PASS, create_context, verification_service,
)
from test_task_materials import material_service  # noqa: F401
from test_verification_review import attempt


def _version(path, version_id):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute('''SELECT m.title,m.content,m.purged_at,o.content,o.purged_at
            FROM learning_task_material m JOIN learning_material_original o ON o.version_id=m.id
            WHERE m.id=?''', (version_id,)).fetchone()


@pytest.mark.asyncio
async def test_verification_purge_preserves_library_material_in_live_and_backup(learning_database, tmp_path):
    verification, source = await attempt(learning_database)
    discussions = QuestionDiscussionService(verification)
    materials = MaterialService(discussions.learning, discussions.chats)
    discussion = discussions.create(IDENTITY, source['id'], source['latest_submission_id'], 'q1', 'source')
    saved = materials.create(IDENTITY, 'discussion', discussion['id'], title='Shared title',
                             content='SHARED_TEXT_9841', original=(b'SHARED_BYTES_9841', 'shared.txt', 'text/plain'))
    local = materials.create(IDENTITY, 'discussion', discussion['id'], title='Local title',
                             content='LOCAL_TEXT_9841', original=(b'LOCAL_BYTES_9841', 'local.txt', 'text/plain'))
    other_context = create_context(learning_database, key='other-discussion', start=False)
    other_verification = verification_service(learning_database, [CHALLENGE, PASS])
    other = await other_verification.start(IDENTITY, {**other_context, 'mode': 'ai_challenge'}, 'other-start')
    other = await other_verification.submit(IDENTITY, other['id'], dict(
        responses={'q1': '另一题作答'}, request_key='other-answer', evidence_condition='independent'))
    other = await other_verification.evaluate(IDENTITY, other['id'], other['latest_submission_id'], 'other-eval')
    other_discussion = QuestionDiscussionService(other_verification).create(
        IDENTITY, other['id'], other['latest_submission_id'], 'q1', 'other-source')
    assert materials.store_in_library(IDENTITY, 'discussion', discussion['id'], saved['material_id']) == {'stored': True}
    assert materials.use_library(IDENTITY, 'discussion', other_discussion['id'], saved['id'])['id'] == saved['id']
    selection = {'mode': 'only', 'version_ids': [saved['id']]}
    frozen = materials.freeze(IDENTITY, 'discussion', other_discussion['id'], selection)
    assert frozen['materials'][0]['content'] == 'SHARED_TEXT_9841'
    with learning_database.transaction() as connection:
        connection.execute('''INSERT INTO learning_discussion_turn
            (id,discussion_id,request_key,user_content,assistant_content,status,sources_json,
             provider_snapshot_json,created_at) VALUES
            ('other-answer-turn',?,'other-turn','Other question','OTHER_ANSWER_9841','succeeded','[]',?,'now')''',
            (other_discussion['id'], '{}'))
    backup, _, _ = create_learning_backup(learning_database.database_path, tmp_path / 'backups', label='before')
    result = ManagedPurge(discussions.learning).run(
        IDENTITY, 'verification', source['id'], lambda: verification.purge(IDENTITY, source['id']))
    assert result['purge']['status'] == 'complete', result
    for path in (learning_database.database_path, backup):
        assert _version(path, saved['id']) == ('Shared title', 'SHARED_TEXT_9841', None,
                                               b'SHARED_BYTES_9841', None)
        local_row = _version(path, local['id'])
        assert local_row[:2] == (None, None) and local_row[2]
        assert local_row[3] is None and local_row[4]
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute('SELECT purged_at FROM learning_question_discussion WHERE id=?',
                                      (discussion['id'],)).fetchone()[0]
            assert connection.execute('''SELECT purged_at FROM learning_question_discussion WHERE id=?''',
                                      (other_discussion['id'],)).fetchone()[0] is None
            assert connection.execute('''SELECT assistant_content FROM learning_discussion_turn WHERE id=?''',
                                      ('other-answer-turn',)).fetchone()[0] == 'OTHER_ANSWER_9841'
    assert any(row['id'] == saved['id'] for row in
               materials.list(IDENTITY, 'discussion', other_discussion['id'])['versions'])
    assert materials.freeze(IDENTITY, 'discussion', other_discussion['id'], selection)['version_ids'] == [saved['id']]
    assert materials.original(IDENTITY, 'discussion', other_discussion['id'], saved['id'])['content'] == b'SHARED_BYTES_9841'
    edited = materials.create(IDENTITY, 'discussion', other_discussion['id'], material_id=saved['material_id'],
                              title='Updated from another discussion', content='NEW_SHARED_TEXT_9841')
    assert edited['version'] == 2
    assert materials.freeze(IDENTITY, 'discussion', other_discussion['id'],
                            {'mode': 'only', 'version_ids': [edited['id']]})['materials'][0]['content'] == 'NEW_SHARED_TEXT_9841'
    # Restoring a post-purge snapshot must accept the intact, independent material.
    post_purge, _, _ = create_learning_backup(learning_database.database_path,
                                               tmp_path / 'backups', label='after')
    restore_learning_backup(post_purge, learning_database.database_path)
    assert _version(learning_database.database_path, saved['id'])[3] == b'SHARED_BYTES_9841'


@pytest.mark.asyncio
async def test_legacy_snapshot_without_library_table_erases_discussion_material(learning_database, tmp_path):
    verification, source = await attempt(learning_database)
    discussions = QuestionDiscussionService(verification)
    materials = MaterialService(discussions.learning, discussions.chats)
    discussion = discussions.create(IDENTITY, source['id'], source['latest_submission_id'], 'q1', 'source')
    version = materials.create(IDENTITY, 'discussion', discussion['id'], title='Legacy', content='private',
                               original=(b'LEGACY_BYTES_1137', 'legacy.txt', 'text/plain'))
    # A disposable snapshot emulates the old schema's absence of library membership.
    snapshot = tmp_path / 'legacy.sqlite3'
    with closing(sqlite3.connect(snapshot)) as target:
        learning_database.connection.backup(target)
    with closing(sqlite3.connect(snapshot)) as connection:
        connection.execute('DROP TRIGGER learning_discussion_purge_materials')
        connection.execute('DROP TABLE learning_material_link')
        connection.execute('DROP TABLE learning_material_library')
        connection.commit()
        connection.row_factory = sqlite3.Row
        erase(connection, IDENTITY['id'], 'verification', source['id'], 'now')
        connection.commit()
    assert _version(snapshot, version['id'])[3] is None


def test_explicit_library_material_purge_scrubs_original_and_rejects_stale_restore(material_service, tmp_path):
    service = material_service
    version = service.create({'id': 'owner'}, 'conversation', 'chat', title='Shared', content='secret',
                             original=(b'EXPLICIT_BYTES_4272', 'shared.txt', 'text/plain'))
    with service.db.transaction() as connection:
        connection.execute('''INSERT INTO learning_material_library(owner_id,material_id,created_at)
            VALUES ('owner',?,'now')''', (version['material_id'],))
    managed, _, _ = create_learning_backup(service.db.database_path, tmp_path / 'backups', label='before')
    stale = tmp_path / 'stale.sqlite3'
    with closing(sqlite3.connect(stale)) as target:
        service.db.connection.backup(target)
    assert service.purge({'id': 'owner'}, version['material_id'])['purge']['status'] == 'complete'
    for path in (service.db.database_path, managed):
        row = _version(path, version['id'])
        assert row[:2] == (None, None) and row[2]
        assert row[3] is None and row[4]
    with pytest.raises(ProductionLearningDatabaseError):
        restore_learning_backup(stale, service.db.database_path)
