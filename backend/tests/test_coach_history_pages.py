from datetime import timedelta
from uuid import uuid4

from test_background_coach import coach, end, check, finish  # noqa: F401
from test_coach_reminders import reminder, arranged, settings, state, dispatch  # noqa: F401


def copies(db, table, sample, count):
    with db.transaction() as c:
        for _ in range(count):
            row = dict(sample); row['id'] = str(uuid4())
            if 'occurrence_key' in row:
                row['occurrence_key'] = 'synthetic-' + row['id']
            columns = ','.join(row)
            c.execute(f'INSERT INTO {table} ({columns}) VALUES ({",".join("?" for _ in row)})', tuple(row.values()))


def pages(client, url):
    result = []; before = None
    while True:
        response = client.get(url + ('&' if '?' in url else '?') + (f'before={before}' if before else ''))
        assert response.status_code == 200, response.text
        assert response.headers['cache-control'] == 'no-store'
        value = response.json(); result.extend(value['items']); before = value['next_before']
        if before is None:
            break
    assert len({item['id'] for item in result}) == len(result)
    return result


def test_coach_history_beyond_first_hundred_remains_accessible_and_scoped(coach, monkeypatch):
    ctx = coach; end(ctx)
    run = finish(ctx, check(ctx)['run']['id']); candidate = run['candidates'][0]
    assert ctx['client'].post('/api/learning/coach/candidates/' + candidate['id'] + '/decisions', json={
        'operation':'ignore', 'expected_revision':1, 'request_key':'history-ignore'}).status_code == 200
    sample = ctx['db'].fetchone('SELECT * FROM learning_coach_candidate WHERE id=?', (candidate['id'],))
    copies(ctx['db'], 'learning_coach_candidate', sample, 105)
    assert len(pages(ctx['client'], '/api/learning/coach/history')) == 106
    assert len(pages(ctx['client'], '/api/learning/coach/history?scope=plan&plan_id=' + ctx['plan_id'])) == 106
    assert ctx['client'].get('/api/learning/coach/history?scope=plan&plan_id=not-owned').status_code == 404
    # Exercise the query's owner boundary without initializing another copy of
    # the single-owner demonstration standards package.
    monkeypatch.setattr(ctx['service'], '_owner', lambda identity: identity['id'])
    assert ctx['service'].history({'id':'another-owner'})['items'] == []


def test_reminder_history_beyond_ten_has_no_gaps(reminder):
    ctx = reminder; settings(ctx, enabled=True, quiet_enabled=False)
    ctx['now'] += timedelta(minutes=1)
    row = state(ctx)['due'][0]; dispatch(ctx, row)
    sample = ctx['db'].fetchone('SELECT * FROM learning_coach_reminder WHERE id=?', (row['id'],))
    copies(ctx['db'], 'learning_coach_reminder', sample, 55)
    assert len(pages(ctx['client'], '/api/learning/coach/reminders/history')) == 56
    assert ctx['client'].get('/api/learning/coach/reminders/history?before=-1').status_code == 422
