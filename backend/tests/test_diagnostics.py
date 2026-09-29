"""The opt-in diagnostic record stays local, bounded, and free of request content."""

import logging
import stat

from fastapi.testclient import TestClient

from app.diagnostics import DiagnosticService
from app.main import create_app
from conftest import build_settings


def authorize(client):
    token = client.app.state.settings.runtime_token_path.read_text(encoding='utf-8')
    response = client.post('/api/auth/authorize', json={'access_token': token})
    assert response.status_code == 200
    return response.json()['identity']['id']


def test_diagnostics_default_off_and_authorized(client):
    for method, path, payload in [('get', '/api/diagnostics/settings', None),
                                  ('get', '/api/diagnostics', None),
                                  ('put', '/api/diagnostics/settings', {'enabled': True}),
                                  ('delete', '/api/diagnostics', None)]:
        response = getattr(client, method)(path, json=payload) if payload else getattr(client, method)(path)
        assert response.status_code == 401

    owner = authorize(client)
    status = client.get('/api/diagnostics/settings').json()
    assert status['enabled'] is False
    assert status['storage_error'] is False
    assert client.get('/api/diagnostics').json()['entries'] == []
    assert not client.app.state.diagnostics.directory(owner).exists()
    assert client.get('/api/plans/private-id?private_query=hidden').status_code in (404, 422)
    assert client.get('/api/diagnostics').json()['entries'] == []


def test_enabled_requests_use_route_templates_and_hide_private_content(client):
    authorize(client)
    assert client.put('/api/diagnostics/settings', json={'enabled': True}).json()['enabled'] is True
    private_query = 'private-query-marker'
    private_body = 'private-body-marker'
    response = client.get(f'/api/plans/private-path-marker?note={private_query}')
    assert response.status_code in (404, 422)
    post = client.post('/api/learning/actions', json={'title': private_body})
    assert post.status_code in (400, 422)
    try:
        raise ValueError('private-exception-marker')
    except ValueError:
        logging.getLogger('nautilus').error('private-log-message-marker', exc_info=True)

    result = client.get('/api/diagnostics').json()
    requests = [row for row in result['entries'] if row['event'] == 'request.finished']
    assert len(requests) == 2
    assert requests[0]['route'] == '/api/plans/{goal_id}'
    assert requests[0]['status'] == response.status_code
    assert requests[0]['request_id'] == response.headers['X-Nautilus-Request-ID']
    assert requests[1]['route'] == '/api/learning/actions'
    assert requests[1]['status'] == post.status_code
    assert {row['method'] for row in requests} == {'GET', 'POST'}
    runtime = [row for row in result['entries'] if row['event'] == 'runtime.error']
    assert runtime and runtime[-1]['code'] == 'ValueError'
    serialized = str(result)
    for secret in (private_query, private_body, 'private-path-marker', 'private-exception-marker', 'private-log-message-marker'):
        assert secret not in serialized
    assert all('body' not in row and 'query' not in row for row in result['entries'])


def test_settings_and_entries_survive_restart_then_disable_and_clear(tmp_path):
    settings = build_settings(tmp_path)
    with TestClient(create_app(settings)) as first:
        authorize(first)
        assert first.put('/api/diagnostics/settings', json={'enabled': True}).status_code == 200
        first.get('/api/plans/restart-marker')
        assert any(row['event'] == 'request.finished' for row in first.get('/api/diagnostics').json()['entries'])

    with TestClient(create_app(settings)) as second:
        authorize(second)
        assert second.get('/api/diagnostics/settings').json()['enabled'] is True
        before = second.get('/api/diagnostics').json()['entries']
        assert any(row['event'] == 'request.finished' for row in before)
        assert second.put('/api/diagnostics/settings', json={'enabled': False}).json()['enabled'] is False
        frozen = second.get('/api/diagnostics').json()['entries']
        second.get('/api/plans/disabled-marker')
        assert second.get('/api/diagnostics').json()['entries'] == frozen
        assert second.delete('/api/diagnostics').json() == {'cleared': True}
        cleared = second.get('/api/diagnostics').json()
        assert cleared['entries'] == []
        assert cleared['enabled'] is False
        assert second.get('/api/diagnostics/settings').json()['enabled'] is False


def test_rotation_stays_bounded_with_private_permissions(tmp_path, monkeypatch):
    import app.diagnostics as diagnostics

    monkeypatch.setattr(diagnostics, 'MAX_BYTES', 512)
    service = DiagnosticService(tmp_path / 'diagnostics')
    service.configure('local-owner', True)
    for _ in range(40):
        service.record('local-owner', module='system', event='request.finished', method='GET', route='/api/plans/{goal_id}', status=200)
    service.close()
    directory = service.directory('local-owner')
    event_files = sorted(directory.glob('events.jsonl*'))
    assert 1 < len(event_files) <= diagnostics.BACKUP_COUNT + 1
    assert all(path.stat().st_size <= diagnostics.MAX_BYTES for path in event_files)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in event_files)
    assert stat.S_IMODE((directory / 'settings.json').stat().st_mode) == 0o600
    assert service.read('local-owner')['entries']


def test_storage_write_failure_does_not_break_request_and_is_visible(client, monkeypatch):
    import app.diagnostics as diagnostics

    authorize(client)
    assert client.put('/api/diagnostics/settings', json={'enabled': True}).status_code == 200

    def fail_writer(*args, **kwargs):
        raise OSError('synthetic storage failure')

    monkeypatch.setattr(diagnostics, 'RotatingFileHandler', fail_writer)
    response = client.get('/api/plans')
    assert response.status_code == 200
    assert client.get('/api/diagnostics/settings').json()['storage_error'] is True
    assert client.get('/api/diagnostics').json()['entries'] == []
