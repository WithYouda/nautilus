import json

import pytest

from app.core.commands import CreateOutcome, SaveTextArtifact, CorrectArtifact, SoftDeleteArtifact
from app.learning_domain import DomainError, Principal
from app.outcome_review import OutcomeReview
from app.review import ReviewService
from app.state_derivation import StateDerivationService
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY, OWNER, PASS, response_transport, create_context, verification_service
from test_verification_review import attempt
from test_verification_evidence import chain, REFERENCE


def outcome_id(service, current):
    return service.learning.database.fetchone(
        'SELECT outcome_id FROM learning_delegation WHERE id=?', (current['delegation_id'],))[0]


async def test_no_standard_review_keeps_versions_conditions_and_owner_boundary(learning_database):
    service, current = await attempt(learning_database)
    first_submission, first_evaluation = current['latest_submission_id'], current['evaluation']['id']
    newer = await service.submit(IDENTITY, current['id'], dict(
        responses={'q1': '另一份私密作答'}, request_key='second', evidence_condition='independent'))
    service.transport = response_transport([PASS])
    evaluated = await service.evaluate(IDENTITY, current['id'], newer['latest_submission_id'], 'evaluate-second')
    reader = OutcomeReview(service)
    oid = outcome_id(service, current)
    before_events = learning_database.fetchone('SELECT COUNT(*) FROM learning_event')[0]
    view = reader.get(IDENTITY, oid)
    assert view['standards'] == [] and view['claims'] == []
    assert view['artifacts'] == []  # A verification submission is not a second independent artifact.
    assert len(view['attempts']) == 2
    assert (view['attempts'][1]['submission_id'], view['attempts'][1]['evaluation_id']) == (first_submission, first_evaluation)
    assert view['attempts'][0]['evaluation_id'] == evaluated['evaluation']['id']
    assert view['attempts'][1]['condition'] == 'independent'
    assert view['attempts'][0]['condition'] == 'with_materials'
    assert view['attempts'][1]['condition_basis'] == 'submission_record'
    assert all(a['standard_version'] is None for a in view['attempts'])
    assert view['records'][0]['outcome_id'] == oid
    serialized = json.dumps(view, ensure_ascii=False)
    assert '另一份私密作答' not in serialized and '服务端评估依据' not in serialized
    assert learning_database.fetchone('SELECT COUNT(*) FROM learning_event')[0] == before_events
    assert learning_database.fetchone('SELECT COUNT(*) FROM learning_derived_state')[0] == 0
    with pytest.raises(DomainError, match='not_found'):
        reader.get({**IDENTITY, 'id': 'owner-b'}, oid)
    foreign = service.learning.core.execute(Principal.user('owner-b'), CreateOutcome(
        object_description='别人的成果', behavior='别人的行为', context_key='foreign'), 'foreign-outcome')
    with pytest.raises(DomainError, match='not_found'):
        reader.get(IDENTITY, foreign['id'])


async def test_core_evidence_questioning_standards_and_purge_are_not_reinterpreted(learning_database):
    service, evidence, events, saved = await chain(learning_database)
    await service.evaluate(IDENTITY, saved['id'], saved['latest_submission_id'], 'evaluate')
    await service.analyze_evidence(IDENTITY, saved['id'])
    claim = evidence.claims(IDENTITY)[0]
    states = StateDerivationService(service.learning, events)
    reviews = ReviewService(service.learning, states, events)
    evidence.schedule_supplemental_verification(IDENTITY, claim['id'], 'follow', note=REFERENCE)
    reviews.review(IDENTITY, claim['id'], 'adopt', '合成采纳理由', 'adopt')
    reader = OutcomeReview(service)
    oid = outcome_id(service, saved)
    supported = reader.get(IDENTITY, oid)
    dimension = next(d for d in supported['standards'][0]['dimensions'] if d['id'] == claim['dimension_id'])
    assert dimension['state']['status'] == 'supported'
    assert dimension['state']['participating_claim_ids'] == [claim['id']]
    assert supported['claims'][0]['condition_basis'] == 'user_self_report'
    reviews.review(IDENTITY, claim['id'], 'question', REFERENCE, 'question')
    questioned = reader.get(IDENTITY, oid)
    assert questioned['claims'][0]['reviews'][-1]['action'] == 'question'
    assert questioned['follow_ups'][0]['status'] == 'pending'
    assert len(questioned['attempts']) == 1  # Arranging a revisit creates no actual new answer.
    assert not any(d['state'] and d['state']['status'] == 'supported' for d in questioned['standards'][0]['dimensions'])
    with learning_database.transaction() as connection:
        connection.execute('''INSERT INTO learning_criterion_version
            SELECT id||':v2',owner_id,package_id,outcome_id,2,source,context_key,recipe_json,
                review_status,reviewed_by,reviewed_at,created_at FROM learning_criterion_version WHERE id=?''', (claim['criterion_id'],))
        connection.execute('INSERT INTO learning_criterion_availability VALUES (?,?,?,?)',
                           (IDENTITY['id'], claim['criterion_id'], 'retired', '2026-09-26T00:00:00Z'))
    versioned = reader.get(IDENTITY, oid)
    assert [s['version'] for s in versioned['standards']] == [1, 2]
    assert versioned['standards'][0]['availability'] == 'retired'
    assert all(d['state'] is None for d in versioned['standards'][1]['dimensions'])
    assert versioned['attempts'][0]['standard_version'] == 1
    service.purge(IDENTITY, saved['id'])
    purged = reader.get(IDENTITY, oid)
    assert not purged['attempts'][0]['available']
    assert purged['attempts'][0]['feedback'] is None
    assert purged['claims'][0]['statement'] is None
    assert not purged['claims'][0]['available']
    assert all(r['reason'] is None for r in purged['claims'][0]['reviews'])
    assert REFERENCE not in json.dumps(purged, ensure_ascii=False)


def test_raw_artifact_versions_remain_linked_but_hidden_content_is_unavailable(learning_database):
    context = create_context(learning_database)
    service = verification_service(learning_database, [])
    core = service.learning.core
    artifact = core.execute(OWNER, SaveTextArtifact(session_id=context['session_id'],
        content='合成产出第一版', expected_version=3), 'artifact')
    core.execute(OWNER, CorrectArtifact(artifact_id=artifact['id'],
        content='合成产出第二版', expected_version=4), 'correct')
    reader = OutcomeReview(service)
    oid = outcome_id(service, context)
    view = reader.get(IDENTITY, oid)
    assert [a['content_version'] for a in view['artifacts']] == [2, 1]
    assert all(a['available'] and a['delegation_id'] == context['delegation_id'] for a in view['artifacts'])
    assert core.artifact(OWNER, artifact['id'], 1)['content'] == '合成产出第一版'
    assert '合成产出第一版' not in json.dumps(view, ensure_ascii=False)
    core.execute(OWNER, SoftDeleteArtifact(artifact_id=artifact['id'], expected_version=5), 'hide')
    assert not any(a['available'] for a in reader.get(IDENTITY, oid)['artifacts'])
