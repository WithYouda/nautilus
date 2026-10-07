"""Long valid content remains exact; relaxing size never relaxes provenance."""
from copy import deepcopy
import pytest

from app.branch_comparisons import BranchComparisons, ComparisonError
from app.completion import CompletionRequest, CompletionService
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY, create_context, verification_service
from test_branch_comparisons import ComparisonProvider, fork, draft
from test_model_control import make_client, authorize, configure_provider, make_scope, send


@pytest.mark.parametrize('kind', ['conversation', 'discussion'])
def test_large_selected_branch_content_reaches_comparison_without_clipping(tmp_path, kind):
    provider = ComparisonProvider()
    with make_client(tmp_path, provider) as client:
        authorize(client); configure_provider(client)
        left, _, _ = make_scope(client, provider, kind)
        content = 'Synthetic original 汉字🙂\n' * 5000 + 'END-OF-ORIGINAL'
        first = send(client, kind, left, 'large', content=content)
        right = fork(client, kind, left, first)
        send(client, kind, right, 'other', content='Synthetic alternative')
        assert draft(client, kind, left, right)['cards']
        assert any(content in item['text'] for item in provider.comparison_input['left'])
        assert any(content in item['text'] for item in provider.comparison_input['right'])


def test_long_completion_is_stored_exactly_and_does_not_create_evidence(learning_database):
    context = create_context(learning_database, start=False)
    service = CompletionService(verification_service(learning_database, []))
    text = '合成作品🙂\n' * 16000 + 'END'
    payload = CompletionRequest(request_key='long-work', verification_kind='unverified',
        material={'kind':'work', 'label':'Synthetic work', 'text':text})
    before = learning_database.fetchone('SELECT COUNT(*) FROM learning_evidence_claim')[0]
    result = service.create(IDENTITY, context['delegation_id'], payload)
    assert result['content']['material']['text'] == text
    assert service.get(IDENTITY, context['delegation_id'])['content']['material']['text'] == text
    assert learning_database.fetchone('SELECT COUNT(*) FROM learning_evidence_claim')[0] == before


def test_long_comparison_cards_keep_exact_quotes_and_reject_fabricated_sources():
    quote = '原文🙂' * 600
    sources = [{'messages':[{'id':'left', 'text':quote}]}, {'messages':[{'id':'right', 'text':quote}]}]
    card = {'topic':'Synthetic', 'relation':'complement', 'conclusion':'结论' * 3000,
            'references':[{'side':side, 'id':side, 'quote':quote} for side in ('left', 'right')]}
    raw = {'cards':[deepcopy(card) for _ in range(25)]}
    cards = BranchComparisons._validate_cards(None, raw, sources)
    assert len(cards) == 25 and cards[-1]['conclusion'] == card['conclusion']
    assert cards[-1]['references'][0]['quote'] == quote
    raw['cards'][0]['references'][0]['quote'] = 'not in the source'
    with pytest.raises(ComparisonError):
        BranchComparisons._validate_cards(None, raw, sources)
