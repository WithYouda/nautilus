import json
import sqlite3
from contextlib import closing

import pytest

from app.discussion_branches import create_branch
from app.learning_domain import DomainError
from app.learning_production import create_learning_backup, restore_learning_backup, ProductionLearningDatabaseError
from app.managed_purge import ManagedPurge
from app.materials import MaterialService
from app.material_purge import erase_learning
from app.question_discussion import QuestionDiscussionService
from app.verification_help import submission_help_context
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY, response_transport
from test_verification_review import attempt


async def reply(service, did, text, key, **extra):
    service.verification.transport = response_transport(['{"history_query":null}', 'ANSWER-' + key])
    return await service.send(IDENTITY, did, text, key, **extra)


@pytest.mark.asyncio
async def test_selected_discussion_path_branch_keeps_source_and_help_facts(learning_database):
    verification, original = await attempt(learning_database)
    service = QuestionDiscussionService(verification)
    d = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'source')
    first = (await reply(service, d['id'], 'first', 'first', help_request='hint'))['turns'][0]
    alternate = (await reply(service, d['id'], 'first', 'alternative', regenerate_turn_id=first['id']))['turns'][-1]
    await reply(service, d['id'], 'later', 'later', parent_turn_id=first['id'])
    before = service.get(IDENTITY, d['id'])
    previous_help = submission_help_context(learning_database.connection, IDENTITY['id'], original['id'], 'independent', 'now')
    fork = create_branch(service, IDENTITY, d['id'], alternate['id'], 'fork')
    assert fork['source'] == before['source']
    assert fork['submission_id'] == before['submission_id'] and fork['evaluation_id'] == before['evaluation_id']
    assert len(fork['turns']) == 1
    assert fork['turns'][0]['assistant_content'] == alternate['assistant_content']
    assert fork['turns'][0]['parent_turn_id'] is None
    assert fork['turns'][0]['inherited_from'] == {'discussion_id':d['id'], 'turn_id':alternate['id']}
    assert fork['turns'][0]['help_record'] == alternate['help_record']
    service.record_help_display(IDENTITY, fork['id'], fork['turns'][0]['id'], 1)
    assert service.get(IDENTITY, d['id']) == before
    assert submission_help_context(learning_database.connection, IDENTITY['id'], original['id'], 'independent', 'now') == previous_help
    assert create_branch(service, IDENTITY, d['id'], alternate['id'], 'fork')['id'] == fork['id']
    with pytest.raises(DomainError, match='idempotency_conflict'):
        create_branch(service, IDENTITY, d['id'], first['id'], 'fork')
    with pytest.raises(DomainError, match='not_found'):
        create_branch(service, {**IDENTITY,'id':'owner-b'}, d['id'], first['id'], 'foreign')
    with pytest.raises(DomainError, match='not_found'):
        create_branch(service, IDENTITY, d['id'], fork['turns'][0]['id'], 'foreign-turn')
    continued = await reply(service, fork['id'], 'independent continuation', 'continued')
    assert continued['turns'][-1]['parent_turn_id'] == fork['turns'][0]['id']
    assert len(service.get(IDENTITY, d['id'])['turns']) == 3
    nested = create_branch(service, IDENTITY, fork['id'], continued['turns'][-1]['id'], 'nested')
    assert len(nested['turns']) == 2
    assert nested['turns'][1]['parent_turn_id'] == nested['turns'][0]['id']


@pytest.mark.asyncio
async def test_discussion_branches_follow_verification_purge_backups_and_restore(learning_database, tmp_path):
    verification, original = await attempt(learning_database)
    verification.confirm(IDENTITY, original['id'], original['latest_submission_id'], original['evaluation']['id'])
    service = QuestionDiscussionService(verification)
    d = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'source')
    first = (await reply(service, d['id'], 'PRIVATE-QUESTION', 'turn1'))['turns'][0]
    fork = create_branch(service, IDENTITY, d['id'], first['id'], 'fork')
    nested = create_branch(service, IDENTITY, fork['id'], fork['turns'][0]['id'], 'nested')
    backup, _, _ = create_learning_backup(learning_database.database_path, tmp_path/'backups', label='branches')
    unmanaged = tmp_path/'unmanaged.sqlite3'
    with closing(sqlite3.connect(unmanaged)) as c:
        learning_database.connection.backup(c)
    result = ManagedPurge(service.learning).run(IDENTITY, 'verification', original['id'], lambda: verification.purge(IDENTITY, original['id']))
    assert result['purge']['status'] == 'complete'
    for did in (d['id'],fork['id'],nested['id']):
        value = service.get(IDENTITY, did)
        assert value['purged'] and value['source'] is None
        assert all(t['assistant_content'] is None and t['user_content'] is None for t in value['turns'])
    with closing(sqlite3.connect(backup)) as c:
        dump = '\n'.join(c.iterdump())
        assert 'PRIVATE-' not in dump and 'ANSWER-turn1' not in dump
    with pytest.raises(ProductionLearningDatabaseError):
        restore_learning_backup(unmanaged, learning_database.database_path)
    with pytest.raises(DomainError, match='artifact_not_eligible'):
        create_branch(service, IDENTITY, fork['id'], fork['turns'][0]['id'], 'after-purge')


@pytest.mark.asyncio
async def test_discussion_branch_inherited_materials_and_selected_history_erasure(learning_database):
    verification, original = await attempt(learning_database)
    service = QuestionDiscussionService(verification)
    materials = MaterialService(service.learning, service.chats)
    service.chats.materials = materials
    d = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'source')
    material = materials.create(IDENTITY,'discussion',d['id'],title='v1',content='PRIVATE-MATERIAL')
    scope = {'mode':'reference','version_ids':[material['id']]}
    verification.transport = response_transport(['PRIVATE-REPLY'])
    first = (await service.send(IDENTITY,d['id'],'PRIVATE-QUESTION','first',source_scope=scope))['turns'][0]
    newer = materials.create(IDENTITY,'discussion',d['id'],title='v2',content='LATER-MATERIAL',material_id=material['material_id'])
    fork = create_branch(service, IDENTITY, d['id'], first['id'], 'fork')
    inherited = materials.list(IDENTITY,'discussion',fork['id'])['versions']
    assert len(inherited)==1 and inherited[0]['id']==material['id'] and inherited[0]['inherited']
    assert materials.freeze(IDENTITY,'discussion',fork['id'],scope)['materials'][0]['content']=='PRIVATE-MATERIAL'
    with pytest.raises(DomainError,match='material_not_found'):
        materials.freeze(IDENTITY,'discussion',fork['id'],{'mode':'reference','version_ids':[newer['id']]})
    # A new, different material keeps the inherited conversation context.
    other = materials.create(IDENTITY,'discussion',fork['id'],title='other',content='OTHER-MATERIAL')
    verification.transport=response_transport(['DERIVED-PRIVATE-REPLY'])
    await service.send(IDENTITY,fork['id'],'follow up','continued',source_scope={'mode':'reference','version_ids':[other['id']]})
    with learning_database.transaction() as c:
        erase_learning(c,IDENTITY['id'],material['material_id'],'now')
    assert all(t['status']=='purged' for t in service.get(IDENTITY,fork['id'])['turns'])
    assert next(v for v in materials.list(IDENTITY,'discussion',fork['id'])['versions'] if v['id']==other['id'])['content']=='OTHER-MATERIAL'


@pytest.mark.asyncio
async def test_later_source_material_does_not_erase_an_earlier_branch(learning_database):
    verification, original = await attempt(learning_database)
    service = QuestionDiscussionService(verification)
    materials = MaterialService(service.learning, service.chats)
    service.chats.materials = materials
    d = service.create(IDENTITY, original['id'], original['latest_submission_id'], 'q1', 'source')
    first = (await reply(service,d['id'],'early independent question','early'))['turns'][0]
    fork = create_branch(service,IDENTITY,d['id'],first['id'],'fork')
    material = materials.create(IDENTITY,'discussion',d['id'],title='later',content='LATER-PRIVATE')
    verification.transport = response_transport(['LATER-PRIVATE-REPLY'])
    await service.send(IDENTITY,d['id'],'later question','later',source_scope={'mode':'reference','version_ids':[material['id']]})
    with learning_database.transaction() as c:
        erase_learning(c,IDENTITY['id'],material['material_id'],'now')
    assert service.get(IDENTITY,fork['id'])['turns'][0]['assistant_content'] == first['assistant_content']
    assert service.get(IDENTITY,d['id'])['turns'][-1]['status']=='purged'
