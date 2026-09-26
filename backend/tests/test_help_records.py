import json

import pytest

from app.learning_domain import DomainError
from app.learning_records import LearningRecords
from app.verification_help import record_solution_display
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY
from test_verification_review import attempt


@pytest.mark.asyncio
async def test_solution_display_is_versioned_idempotent_and_does_not_rewrite_answer(learning_database):
    service, current = await attempt(learning_database)
    records = LearningRecords(service)
    original = records.detail(IDENTITY, current['id'])
    eid = original['selected_evaluation_id']
    first = record_solution_display(service, IDENTITY, current['id'], eid, 'q1')
    assert record_solution_display(service, IDENTITY, current['id'], eid, 'q1') == first
    shown = records.detail(IDENTITY, current['id'])
    assert shown['content'] == original['content']
    assert shown['content']['help_context']['records'] == []
    assert shown['help_displays']['q1'] == first
    payload = dict(responses={'q1': '另一次合成作答'}, request_key='after-help', evidence_condition='independent')
    await service.submit(IDENTITY, current['id'], payload)
    later = records.detail(IDENTITY, current['id'])
    assert later['help_displays'] == {}
    assert later['content']['evidence_condition'] == 'with_materials'
    assert later['content']['help_context']['user_report'] == 'independent'
    assert later['content']['help_context']['records'] == [dict(kind='reference_answer',
        evaluation_id=eid, question_id='q1', displayed_at=first['at'])]
    # Retrying the original request uses its original fingerprint and snapshot.
    await service.submit(IDENTITY, current['id'], payload)
    assert records.detail(IDENTITY, current['id'])['content'] == later['content']
    for identity, evaluation, question in [({**IDENTITY, 'id': 'other-owner'}, eid, 'q1'),
                                          (IDENTITY, 'other-evaluation', 'q1'), (IDENTITY, eid, 'q2')]:
        with pytest.raises(DomainError):
            record_solution_display(service, identity, current['id'], evaluation, question)
    service.purge(IDENTITY, current['id'])
    with pytest.raises(DomainError):
        record_solution_display(service, IDENTITY, current['id'], eid, 'q1')
    assert records.detail(IDENTITY, current['id'])['help_displays'] == {}
    assert learning_database.fetchone('SELECT provider_snapshot_json FROM learning_verification_evaluation WHERE id=?', (eid,))[0] is None


@pytest.mark.asyncio
async def test_discussion_help_snapshot_keeps_partial_body_but_not_empty_failure(learning_database):
    from app.question_discussion import QuestionDiscussionService
    from test_learning_verifications import response_transport
    service, current = await attempt(learning_database)
    discussions = QuestionDiscussionService(service)
    discussion = discussions.create(IDENTITY, current['id'], current['latest_submission_id'], 'q1', 'help-discussion')
    service.transport = response_transport(['{"history_query":null}', '合成提示正文'])
    answer = await discussions.send(IDENTITY, discussion['id'], '给个提示', 'hint-1', help_request='hint')
    turn = answer['turns'][0]
    assert turn['help_record']['request']['kind'] == 'hint'
    assert turn['help_record']['provided']['characters'] > 0
    record = discussions.record_help_display(IDENTITY, discussion['id'], turn['id'], len(turn['assistant_content']))
    assert record['display']['basis'] == 'client_report'
    assert discussions.record_help_display(IDENTITY, discussion['id'], turn['id'], len(turn['assistant_content'])) == record
    with learning_database.transaction() as connection:
        connection.execute("UPDATE learning_discussion_turn SET status='failed',reason='cancelled' WHERE id=?", (turn['id'],))
    service.transport = response_transport(['{"history_query":null}', ''])
    empty = await discussions.send(IDENTITY, discussion['id'], '换个例子', 'example-1', help_request='example')
    assert empty['turns'][-1]['help_record']['provided'] is None
    payload = dict(responses={'q1': '使用提示后的答案'}, request_key='after-partial', evidence_condition='independent')
    await service.submit(IDENTITY, current['id'], payload)
    saved = LearningRecords(service).detail(IDENTITY, current['id'])['content']['help_context']
    assert len(saved['records']) == 1
    assert saved['records'][0]['turn_id'] == turn['id']
    assert saved['records'][0]['partial'] is True
    assert saved['records'][0]['displayed_at'] == record['display']['at']
    assert '合成提示正文' not in json.dumps(saved, ensure_ascii=False)
