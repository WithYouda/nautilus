import pytest
from app.core.commands import CorrectArtifact, PurgeArtifact
from app.learning_domain import DomainError
from test_learning_fact_hardening import core, running, save, USER
from test_learning_domain_schema import learning_database  # noqa: F401


def test_three_versions_purge_is_idempotent_and_survives_replay(core, running):
    artifact = save(core, running)
    for version in (4, 5):
        core.execute(USER, CorrectArtifact(artifact_id=artifact['id'], content=f'Synthetic correction {version}', expected_version=version), f'correct-{version}')
    result = core.execute(USER, PurgeArtifact(artifact_id=artifact['id'], expected_version=6, confirmation='PURGE'), 'purge')
    before = core.database.fetchone('SELECT COUNT(*) FROM learning_event')[0]
    again = core.execute(USER, PurgeArtifact(artifact_id=artifact['id'], expected_version=7, confirmation='PURGE'), 'purge-again')
    assert again == result
    assert core.database.fetchone('SELECT COUNT(*) FROM learning_event')[0] == before
    core.replay(USER)
    rows = core.database.fetchall('SELECT content, content_hash FROM learning_raw_artifact WHERE artifact_id=?', (artifact['id'],))
    assert len(rows) == 3 and all(tuple(row) == (None, None) for row in rows)
    assert tuple(core.database.fetchone('SELECT visibility, evidence_status FROM learning_artifact')) == ('purged', 'invalidated')
    with pytest.raises(DomainError, match='artifact_not_eligible'):
        core.execute(USER, CorrectArtifact(artifact_id=artifact['id'], content='Cannot revive', expected_version=7), 'revive')

from app.core.commands import SaveTextArtifact
from app.evidence import EvidenceClaimDraft
from app.review import ReviewService
from app.state_derivation import StateDerivationService
from test_verification_evidence import chain, WORK
from test_learning_verifications import IDENTITY

@pytest.mark.asyncio
async def test_ordinary_artifact_private_copies_are_erased_after_both_replays(learning_database):
    service, evidence, events, saved = await chain(learning_database)
    secret = 'SYNTHETIC_ORDINARY_PRIVATE_EXCERPT'
    version = learning_database.fetchone('SELECT version FROM learning_action')[0]
    artifact = service.learning.core.execute(USER, SaveTextArtifact(session_id=saved['session_id'], content=WORK+'\n'+secret, expected_version=version), 'ordinary')
    evidence.semantic_analyzer = lambda _: [EvidenceClaimDraft(dimension_id='syntax_semantics', stance='supports', statement=secret, scope=secret, source='ai_analysis', verification_method='semantic_analysis', evidence_condition='independent')]
    await evidence.analyze(IDENTITY, artifact['id'], 'ordinary-analysis')
    claims = evidence.claims(IDENTITY, artifact['id'])
    state = StateDerivationService(service.learning, events)
    review = ReviewService(service.learning, state, events)
    for claim in claims:
        evidence.request_human_review(IDENTITY, claim['id'], 'follow-'+claim['id'], secret)
    review.batch_review(IDENTITY, [c['id'] for c in claims], 'adopt', secret, 'batch')
    ledger = [tuple(row) for row in learning_database.fetchall('SELECT * FROM learning_evidence_event')]
    assert secret not in str(ledger)
    service.learning.purge_artifact(IDENTITY, dict(artifact_id=artifact['id'], expected_version=artifact['version'], confirmation='PURGE'), 'purge-ordinary')
    for replay in (False, True):
        if replay:
            service.learning.replay(IDENTITY)
            events.replay(USER.owner_id)
        for table in ('learning_raw_artifact', 'learning_evidence_claim', 'learning_review_action', 'learning_batch_review_action', 'learning_evidence_follow_up', 'learning_revisit_item', 'learning_evidence_event', 'learning_evidence_private_content', 'learning_analysis_run'):
            assert secret not in str([tuple(row) for row in learning_database.fetchall('SELECT * FROM '+table)]), table
        assert all(c['status']=='invalidated' for c in evidence.claims(IDENTITY, artifact['id']))
        assert all(s['status']!='supported' for s in state.states(IDENTITY))

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from app.learning_storage import open_learning_database
from app.core.learning import LearningCore
from app.core.commands import CreateLearningAction


def test_fact_replay_locks_before_snapshot_and_preserves_waiting_writer(core, running, monkeypatch):
    save(core, running)
    writer = open_learning_database(core.database.database_path, migrate=False)
    snapshot, release, attempted = Event(), Event(), Event()
    validate = core._validate_event_stream
    def paused(rows):
        snapshot.set()
        assert release.wait(3)
        return validate(rows)
    monkeypatch.setattr(core, '_validate_event_stream', paused)
    def write():
        attempted.set()
        return LearningCore(writer).execute(USER, CreateLearningAction(title='Concurrent synthetic action', context_key='synthetic'), 'concurrent')
    try:
        with ThreadPoolExecutor(2) as pool:
            replay = pool.submit(core.replay, USER)
            assert snapshot.wait(3)
            pending = pool.submit(write)
            assert attempted.wait(3)
            assert not pending.done()
            release.set()
            result = replay.result(3)
            created = pending.result(3)
        assert result['comparison']['matched']
        assert core.database.fetchone('SELECT id FROM learning_action WHERE id=?', (created['id'],))
        assert core.database.fetchone('SELECT COUNT(*) FROM learning_action')[0] == 2
    finally:
        release.set()
        writer.close()

@pytest.mark.asyncio
async def test_evidence_replay_serializes_claim_review_state_writes(learning_database, monkeypatch):
    import asyncio
    from app.evidence_events import EvidenceEventService
    from app.learning_service import LearningService
    service, evidence, events, saved = await chain(learning_database)
    await service.evaluate(IDENTITY, saved['id'], saved['latest_submission_id'], 'evaluate')
    await service.analyze_evidence(IDENTITY, saved['id'])
    claim = evidence.claims(IDENTITY)[0]
    writer = open_learning_database(learning_database.database_path, migrate=False)
    learning = LearningService(writer)
    writer_events = EvidenceEventService(writer)
    review = ReviewService(learning, StateDerivationService(learning, writer_events), writer_events)
    snapshot, release, attempted = Event(), Event(), Event()
    validate = events._validate_chain
    def paused(owner):
        snapshot.set()
        assert release.wait(3)
        return validate(owner)
    monkeypatch.setattr(events, '_validate_chain', paused)
    def write():
        attempted.set()
        return review.review(IDENTITY, claim['id'], 'adopt', None, 'concurrent-review')
    try:
        with ThreadPoolExecutor(2) as pool:
            replay = pool.submit(events.replay, USER.owner_id)
            assert snapshot.wait(3)
            pending = pool.submit(write)
            assert attempted.wait(3)
            assert not pending.done()
            release.set()
            assert replay.result(3)['comparison']['matched']
            pending.result(3)
        assert evidence.claims(IDENTITY)[0]['status'] == 'adopted'
        assert learning_database.fetchone('SELECT COUNT(*) FROM learning_derived_state')[0] == 3
        assert learning_database.fetchone('SELECT COUNT(*) FROM learning_review_action')[0] == 1
    finally:
        release.set()
        writer.close()

@pytest.mark.asyncio
async def test_ordinary_backup_cannot_restore_deleted_projection_quotes(learning_database, tmp_path):
    import sqlite3
    from contextlib import closing
    from app.learning_production import restore_learning_backup, ProductionLearningDatabaseError
    service, evidence, events, saved=await chain(learning_database)
    version=learning_database.fetchone('SELECT version FROM learning_action')[0]
    artifact=service.learning.core.execute(USER,SaveTextArtifact(session_id=saved['session_id'],content=WORK,expected_version=version),'ordinary')
    await evidence.analyze(IDENTITY,artifact['id'],'analyze')
    service.learning.purge_artifact(IDENTITY,dict(artifact_id=artifact['id'],expected_version=artifact['version'],confirmation='PURGE'),'purge')
    backup, target = tmp_path/'backup.sqlite3', tmp_path/'target.sqlite3'
    for path in (backup,target):
        with closing(sqlite3.connect(path)) as output:
            learning_database.connection.backup(output)
    assert restore_learning_backup(backup,target)['up_to_date']
    with closing(sqlite3.connect(backup)) as c:
        c.execute("UPDATE learning_evidence_claim SET statement='synthetic old quote' WHERE artifact_id=?",(artifact['id'],))
        c.commit()
    with pytest.raises(ProductionLearningDatabaseError):
        restore_learning_backup(backup,target)
