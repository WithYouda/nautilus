"""Remaining approved limits preserve full text and existing permission boundaries."""
import json
import httpx
from app.coach_signals import adopt
from test_background_coach import coach, end, check, finish  # noqa: F401


def test_long_permission_purpose_survives_candidate_request_and_grant(coach):
    ctx = coach
    purpose = '核对这次作品中的具体依据。' * 120 + '目的末尾'
    alternative = '拒绝后可在原任务自行核对。' * 80 + '替代末尾'

    async def respond(request):
        inputs = json.loads(json.loads(request.content)['messages'][-1]['content'])
        target = next(t for t in inputs['targets'] if t['kind'] == 'permission_review')
        proposal = {'candidates': [dict(title='核对作品', explanation='合成依据', unknowns=[],
            source_refs=inputs['refs'][:1],
            target={k: target[k] for k in ('kind','plan_id','action_id','delegation_id','object_id')},
            access_request={'purpose': purpose, 'alternative': alternative})]}
        return httpx.Response(200, json={'choices':[{'message':{'content':json.dumps(proposal)},'finish_reason':'stop'}]})

    ctx['service'].transport = httpx.MockTransport(respond)
    end(ctx)
    run = finish(ctx, check(ctx)['run']['id'])
    assert run['run']['status'] == 'succeeded', run
    candidate = run['candidates'][0]
    fields = candidate['target']['permission_request']
    assert fields['purpose'].endswith(purpose)
    assert fields['alternative'] == alternative
    client = ctx['client']
    created = client.post('/api/learning/agent/permission-requests', json={
        k: fields[k] for k in ('purpose','target_id','content_granularity','ttl_seconds','request_key')})
    assert created.status_code == 201, created.text
    identifier = created.json()['id']
    assert ctx['db'].fetchone('SELECT purpose FROM learning_agent_permission_request WHERE id=?', (identifier,))[0] == fields['purpose']
    assert ctx['db'].fetchone('SELECT COUNT(*) FROM learning_agent_permission_grant WHERE request_id=?', (identifier,))[0] == 0
    assert client.post('/api/learning/agent/permission-requests/'+identifier+'/approve').status_code == 200
    assert client.post('/api/learning/agent/permission-requests/'+identifier+'/revoke', json={'reason':'合成撤回'}).status_code == 200


def test_long_signal_quote_still_requires_exact_current_user_source():
    quote = '需要单独安排这项学习。' * 80
    def frozen():
        return {'coach_context': {'action_id':'synthetic'}, 'output': {'format':'json'},
                'origin': {'kind':'conversation'}, 'message_id':'synthetic'}
    proposal = {'assignment_signal': {'kind':'separate_work_requested', 'quote':quote}}
    accepted = frozen()
    adopt(accepted, proposal, '开头'+quote+'结尾', {})
    assert accepted['assignment_signal']['start'] == 2
    assert accepted['assignment_signal']['end'] == 2 + len(quote)
    rejected = frozen()
    adopt(rejected, proposal, quote[:-1], {})
    assert 'assignment_signal' not in rejected
