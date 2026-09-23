import json
import pytest
from app.evidence import ProviderSemanticAnalyzer, AnalysisError
from test_learning_verifications import FakeConversations, response_transport

@pytest.mark.asyncio
@pytest.mark.parametrize('forgery', [
    {'source': 'human_review'}, {'source': 'deterministic_check'},
    {'verification_method': 'independent_review'}, {'evidence_condition': 'independent'},
])
async def test_provider_cannot_assign_execution_provenance(forgery):
    observation = dict(dimension_id='syntax_semantics', stance='supports', statement='Synthetic observation', scope='artifact')
    observation.update(forgery)
    analyzer = ProviderSemanticAnalyzer(FakeConversations(), response_transport([json.dumps(observation)]))
    with pytest.raises(AnalysisError, match='结构不合格'):
        await analyzer({'identity_id': 'owner-a', 'recipe': {}, 'content': 'Synthetic text'})

from test_learning_domain_schema import learning_database  # noqa: F401
from test_verification_evidence import chain
from test_learning_verifications import IDENTITY
from app.evidence import EvidenceClaimDraft
from app.state_derivation import StateDerivationService
from app.review import ReviewService

@pytest.mark.asyncio
async def test_runtime_binds_condition_and_ai_cannot_supply_human_support(learning_database):
    service, evidence, events, saved = await chain(learning_database)
    evidence.semantic_analyzer = lambda _: [EvidenceClaimDraft(dimension_id='syntax_semantics', stance='supports', statement='Synthetic observation', scope='artifact', source='human_review', verification_method='independent_review', evidence_condition='with_hints')]
    await service.evaluate(IDENTITY, saved['id'], saved['latest_submission_id'], 'evaluate')
    await service.analyze_evidence(IDENTITY, saved['id'])
    claim = next(c for c in evidence.claims(IDENTITY) if c['dimension_id'] == 'syntax_semantics')
    assert (claim['source'], claim['verification_method']) == ('ai_analysis', 'semantic_analysis')
    assert json.loads(claim['provenance_json'])['condition_basis'] == 'user_self_report'
    follow = evidence.request_human_review(IDENTITY, claim['id'], 'request', None)
    assert follow['status'] == 'pending'
    state = StateDerivationService(service.learning, events)
    ReviewService(service.learning, state, events).review(IDENTITY, claim['id'], 'adopt', None, 'adopt')
    assert next(s for s in state.states(IDENTITY) if s['dimension_id'] == 'syntax_semantics')['status'] == 'partially_supported'
    with learning_database.transaction() as connection:
        connection.execute("UPDATE learning_evidence_claim SET provenance_json=NULL WHERE id=?", (claim['id'],))
    state.recalculate(IDENTITY)
    assert all(s['status'] != 'supported' for s in state.states(IDENTITY))

@pytest.mark.asyncio
async def test_legacy_cached_support_cannot_return_through_reads_or_replay(learning_database, monkeypatch):
    from test_verification_evidence import chain
    from app.review import ReviewService
    from app.state_derivation import StateDerivationService
    from test_learning_verifications import IDENTITY
    service, evidence, events, saved = await chain(learning_database)
    append = events.append
    def legacy_shape(owner, aggregate_type, aggregate_id, event_type, payload, **kwargs):
        if event_type=='claim.created':
            payload={key:value for key,value in payload.items() if key!='provenance_json'}
        return append(owner,aggregate_type,aggregate_id,event_type,payload,**kwargs)
    monkeypatch.setattr(events,'append',legacy_shape)
    await evidence.analyze(IDENTITY,saved['artifact_id'],'legacy-shaped')
    state=StateDerivationService(service.learning,events)
    review=ReviewService(service.learning,state,events)
    claim=evidence.claims(IDENTITY)[0]
    review.review(IDENTITY,claim['id'],'adopt',None,'adopt')
    assert any(s['status']=='supported' for s in state.states(IDENTITY))
    with learning_database.transaction() as c:
        c.execute('UPDATE learning_evidence_claim SET provenance_json=NULL')
    assert not any(s['status']=='supported' for s in state.states(IDENTITY))
    overview = service.learning.overview(IDENTITY)
    assert not any(s['status']=='supported' for s in overview['derived_states'])
    assert all(not c['source_trusted'] for c in overview['evidence_claims'])
    events.replay(IDENTITY['id'])
    assert not any(s['status']=='supported' for s in state.states(IDENTITY))
    assert learning_database.fetchone("SELECT COUNT(*) FROM learning_derived_state WHERE status='supported'")[0]==0
