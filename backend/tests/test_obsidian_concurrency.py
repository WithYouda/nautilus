"""Revocation ordering between vault reads, candidate publication and capture commits.

These tests stop a real operation at a controlled boundary with events, run the
revoking operation concurrently, and then assert on the database and candidate
state. They are not substitutes for the sequential token tests in
``test_obsidian_local.py``: those only prove that a token issued before a
revocation is refused afterwards.
"""
from __future__ import annotations

import os
import threading

import pytest

import app.obsidian as obsidian_module
from app.credentials import CredentialStore
from app.learning_domain import DomainError
from app.obsidian import ObsidianService, Vault
from test_obsidian_materials import build_vault
from test_task_materials import material_service  # noqa: F401

IDENTITY = {'id': 'owner'}
SCOPE = ('conversation', 'chat')
TIMEOUT = 10
CONFLICT_CODES = ('obsidian_selection_invalid', 'obsidian_connection_revision',
                  'obsidian_search_invalidated')


@pytest.fixture
def obsidian(material_service, tmp_path):  # noqa: F811 - shared fixture
    service = ObsidianService(CredentialStore(tmp_path / 'credentials'), material_service)
    material_service.obsidian = service
    vault, outside = build_vault(tmp_path)
    connection = service.connect('owner', str(vault), None)
    return service, material_service, vault, connection, outside


def page_for(service, connection, query='MATRIX'):
    return service.search(IDENTITY, *SCOPE, connection_id=connection['connection_id'],
                          connection_revision=connection['revision'], query=query, after=None)


def capture_for(service, token):
    return service.capture(IDENTITY, *SCOPE, selection_token=token)


def run_in_thread(target):
    outcome = {}

    def runner():
        try:
            outcome['value'] = target()
        except BaseException as error:  # noqa: BLE001 - surfaced to the test below
            outcome['error'] = error

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    return thread, outcome


def finish(thread):
    thread.join(TIMEOUT)
    assert not thread.is_alive(), 'background operation did not finish within the test timeout'


def test_disconnect_completed_first_rejects_inflight_capture(obsidian, monkeypatch):
    service, materials, _vault, connection, _outside = obsidian
    token = page_for(service, connection)['items'][0]['selection_token']
    entered, release = threading.Event(), threading.Event()
    original = Vault.read

    def paused(self, relative_path, guard=None):
        entered.set()
        assert release.wait(TIMEOUT), 'capture was never released'
        return original(self, relative_path, guard)

    monkeypatch.setattr(Vault, 'read', paused)
    thread, outcome = run_in_thread(lambda: capture_for(service, token))
    assert entered.wait(TIMEOUT), 'capture never reached the read'
    assert service.disconnect('owner', connection['revision'])['enabled'] is False
    release.set()
    finish(thread)
    error = outcome.get('error')
    assert isinstance(error, DomainError) and error.code in CONFLICT_CODES, outcome
    # Ordering B: the revocation completed before the commit, so nothing was written.
    assert materials.list(IDENTITY, *SCOPE)['versions'] == []
    assert materials.library(IDENTITY)['versions'] == []
    assert materials.db.fetchone('SELECT COUNT(*) AS n FROM learning_material_original')['n'] == 0
    assert materials.db.fetchone('SELECT COUNT(*) AS n FROM learning_material_link')['n'] == 0


def test_capture_commit_cannot_be_passed_by_disconnect(obsidian, monkeypatch):
    service, materials, _vault, connection, _outside = obsidian
    token = page_for(service, connection)['items'][0]['selection_token']
    entered, release = threading.Event(), threading.Event()
    original = materials.capture_obsidian

    def paused(*args, **kwargs):
        with materials.lock:  # the boundary a capture holds while committing
            entered.set()
            assert release.wait(TIMEOUT), 'commit was never released'
            return original(*args, **kwargs)

    monkeypatch.setattr(materials, 'capture_obsidian', paused)
    capture_thread, capture_outcome = run_in_thread(lambda: capture_for(service, token))
    assert entered.wait(TIMEOUT), 'capture never reached the commit boundary'
    attempted, done = threading.Event(), threading.Event()

    def disconnect():
        attempted.set()
        value = service.disconnect('owner', connection['revision'])
        done.set()
        return value

    disconnect_thread, disconnect_outcome = run_in_thread(disconnect)
    assert attempted.wait(TIMEOUT)
    # Bounded observation, not synchronization: a revocation cannot slip in after the
    # captured state was frozen, so it must still be waiting for the commit boundary.
    assert done.wait(0.5) is False, 'disconnect passed an in-flight commit'
    release.set()
    finish(capture_thread)
    finish(disconnect_thread)
    assert 'error' not in capture_outcome, capture_outcome
    assert 'error' not in disconnect_outcome, disconnect_outcome
    assert done.wait(TIMEOUT)
    # Ordering A: the commit finished first, so the snapshot stays valid and attached.
    versions = materials.list(IDENTITY, *SCOPE)['versions']
    assert len(versions) == 1 and versions[0]['content'].startswith('# Deep')
    assert materials.library(IDENTITY)['versions'][0]['id'] == versions[0]['id']
    assert materials.original(IDENTITY, *SCOPE, versions[0]['id'])['media_type'] == 'text/markdown'
    assert service.connection('owner')['enabled'] is False


def test_revocation_mid_scan_stops_further_reads(obsidian, monkeypatch):
    service, _materials, _vault, connection, _outside = obsidian
    reads = []
    entered, release = threading.Event(), threading.Event()
    original = Vault.read

    def paused(self, relative_path, guard=None):
        reads.append(relative_path)
        if len(reads) == 2:
            entered.set()
            assert release.wait(TIMEOUT), 'scan was never released'
        return original(self, relative_path, guard)

    monkeypatch.setattr(Vault, 'read', paused)
    thread, outcome = run_in_thread(lambda: page_for(service, connection, 'no-such-text-in-vault'))
    assert entered.wait(TIMEOUT), 'scan never reached the second file'
    service.disconnect('owner', connection['revision'])
    release.set()
    finish(thread)
    error = outcome.get('error')
    assert isinstance(error, DomainError) and error.code in CONFLICT_CODES, outcome
    assert len(reads) <= 2, reads  # no further source file was opened after revocation
    assert service._candidates == {}  # a revoked scan publishes no candidate page


def test_candidate_publication_cannot_be_inserted_by_invalidation(obsidian, monkeypatch):
    service, _materials, _vault, connection, _outside = obsidian
    entered, release = threading.Event(), threading.Event()
    original = service._release_expired

    def paused():
        entered.set()
        assert release.wait(TIMEOUT), 'publication was never released'
        original()

    monkeypatch.setattr(service, '_release_expired', paused)
    thread, outcome = run_in_thread(lambda: page_for(service, connection))
    assert entered.wait(TIMEOUT), 'search never reached the publication section'
    attempted, done = threading.Event(), threading.Event()

    def disconnect():
        attempted.set()
        value = service.disconnect('owner', connection['revision'])
        done.set()
        return value

    disconnect_thread, _disconnect_outcome = run_in_thread(disconnect)
    assert attempted.wait(TIMEOUT)
    assert done.wait(0.5) is False, 'invalidation entered the publication critical section'
    release.set()
    finish(thread)
    finish(disconnect_thread)
    assert done.wait(TIMEOUT)
    page = outcome.get('value')
    assert page is not None and page['items'], outcome
    # The search completed before the revocation; its page must not survive it.
    with pytest.raises(DomainError) as denied:
        capture_for(service, page['items'][0]['selection_token'])
    assert denied.value.code in CONFLICT_CODES + ('obsidian_disconnected',)
    assert service._candidates == {}


def test_purge_completed_first_rejects_inflight_capture(obsidian, monkeypatch):
    service, materials, _vault, connection, _outside = obsidian
    other = materials.create(IDENTITY, *SCOPE, title='Unrelated', content='UNRELATED_TEXT_7781')
    token = page_for(service, connection)['items'][0]['selection_token']
    entered, release = threading.Event(), threading.Event()
    original = Vault.read

    def paused(self, relative_path, guard=None):
        entered.set()
        assert release.wait(TIMEOUT), 'capture was never released'
        return original(self, relative_path, guard)

    monkeypatch.setattr(Vault, 'read', paused)
    thread, outcome = run_in_thread(lambda: capture_for(service, token))
    assert entered.wait(TIMEOUT), 'capture never reached the read'
    assert materials.purge(IDENTITY, other['material_id'])['purge']['status'] == 'complete'
    release.set()
    finish(thread)
    error = outcome.get('error')
    assert isinstance(error, DomainError) and error.code in CONFLICT_CODES, outcome
    assert materials.db.fetchone('SELECT COUNT(*) AS n FROM learning_task_material')['n'] == 1
    assert materials.library(IDENTITY)['versions'] == []


def test_source_status_revocation_is_not_published_as_success(obsidian, monkeypatch):
    service, _materials, _vault, connection, _outside = obsidian
    saved = capture_for(service, page_for(service, connection)['items'][0]['selection_token'])
    entered, release = threading.Event(), threading.Event()
    original = Vault.read

    def paused(self, relative_path, guard=None):
        entered.set()
        assert release.wait(TIMEOUT), 'status read was never released'
        return original(self, relative_path, guard)

    monkeypatch.setattr(Vault, 'read', paused)
    thread, outcome = run_in_thread(lambda: service.source_status(IDENTITY, *SCOPE, saved['id']))
    assert entered.wait(TIMEOUT), 'source status never reached the read'
    service.disconnect('owner', connection['revision'])
    release.set()
    finish(thread)
    assert 'value' not in outcome, outcome
    error = outcome.get('error')
    assert isinstance(error, DomainError) and error.code in CONFLICT_CODES, outcome


class PausedScan:
    """Iterate a real scandir result, running a hook after the first entry."""

    def __init__(self, iterator, hook):
        self.iterator = iterator
        self.hook = hook
        self.index = -1

    def __iter__(self):
        return self

    def __next__(self):
        entry = next(self.iterator)
        self.index += 1
        if self.index == 0:
            self.hook()
        return entry

    def __enter__(self):
        return self

    def __exit__(self, *_error):
        self.iterator.close()
        return False


def pausing_root_open(monkeypatch, entered, release):
    """Pause at the root-open boundary, before any descriptor is opened."""
    original = Vault.open.__func__

    def paused(cls, root_path, guard=None):
        entered.set()
        assert release.wait(TIMEOUT), 'root open was never released'
        return original(cls, root_path, guard)

    monkeypatch.setattr(Vault, 'open', classmethod(paused))


def count_root_opens(monkeypatch):
    """Count root descriptors actually obtained (a refused permission opens nothing)."""
    calls = []
    original = obsidian_module._open_root_descriptor

    def counted(path, guard=None):
        descriptor = original(path, guard)
        calls.append(str(path))
        return descriptor

    monkeypatch.setattr(obsidian_module, '_open_root_descriptor', counted)
    return calls


def count_reads(monkeypatch):
    calls = []
    original = Vault.read

    def counted(self, relative_path, guard=None):
        calls.append(relative_path)
        return original(self, relative_path, guard)

    monkeypatch.setattr(Vault, 'read', counted)
    return calls


def flatten_vault(tmp_path, count=5):
    root = tmp_path / 'Flat Vault'
    root.mkdir()
    for index in range(count):
        (root / f'note-{index}.md').write_text(f'flat note {index}\n', encoding='utf-8')
    return root


def test_revocation_before_root_open_rejects_the_operation(obsidian, monkeypatch):
    service, _materials, _vault, connection, _outside = obsidian
    entered, release = threading.Event(), threading.Event()
    root_opens = count_root_opens(monkeypatch)
    pausing_root_open(monkeypatch, entered, release)
    thread, outcome = run_in_thread(lambda: page_for(service, connection, 'no-such-text-in-vault'))
    assert entered.wait(TIMEOUT), 'search never reached the root-open boundary'
    service.disconnect('owner', connection['revision'])
    release.set()
    finish(thread)
    error = outcome.get('error')
    assert isinstance(error, DomainError) and error.code in CONFLICT_CODES, outcome
    assert root_opens == [], root_opens  # no root descriptor was opened, no scandir started
    assert service._candidates == {}


def test_revocation_after_first_entry_stops_flat_enumeration(obsidian, monkeypatch):
    service, _materials, _vault, connection, _outside = obsidian
    flat = flatten_vault(tmp_path=obsidian[2].parent)
    flat_connection = service.connect('owner', str(flat), connection['revision'])
    entered, release = threading.Event(), threading.Event()
    reads = count_reads(monkeypatch)
    real_scandir = os.scandir
    armed = {'wrapped': False}

    def pausing_scandir(*args, **kwargs):
        iterator = real_scandir(*args, **kwargs)
        if armed['wrapped']:
            return iterator
        armed['wrapped'] = True
        return PausedScan(iterator, lambda: (entered.set(), release.wait(TIMEOUT)))

    monkeypatch.setattr(os, 'scandir', pausing_scandir)
    thread, outcome = run_in_thread(lambda: page_for(service, flat_connection, 'no-such-text-in-vault'))
    assert entered.wait(TIMEOUT), 'enumeration never returned its first entry'
    assert reads == [], reads
    service.disconnect('owner', flat_connection['revision'])
    release.set()
    finish(thread)
    error = outcome.get('error')
    assert isinstance(error, DomainError) and error.code in CONFLICT_CODES, outcome
    assert reads == [], reads  # the remaining flat entries were never carried into file reads
    assert service._candidates == {}


def test_capture_after_revocation_never_opens_the_root(obsidian, monkeypatch):
    service, materials, _vault, connection, _outside = obsidian
    token = page_for(service, connection)['items'][0]['selection_token']
    entered, release = threading.Event(), threading.Event()
    root_opens = count_root_opens(monkeypatch)
    pausing_root_open(monkeypatch, entered, release)
    thread, outcome = run_in_thread(lambda: capture_for(service, token))
    assert entered.wait(TIMEOUT), 'capture never reached the root-open boundary'
    service.disconnect('owner', connection['revision'])
    release.set()
    finish(thread)
    error = outcome.get('error')
    assert isinstance(error, DomainError) and error.code in CONFLICT_CODES, outcome
    assert root_opens == []
    assert materials.list(IDENTITY, *SCOPE)['versions'] == []
    assert materials.db.fetchone('SELECT COUNT(*) AS n FROM learning_material_original')['n'] == 0
    assert materials.db.fetchone('SELECT COUNT(*) AS n FROM learning_material_link')['n'] == 0


def test_source_status_after_revocation_never_opens_the_root(obsidian, monkeypatch):
    service, _materials, _vault, connection, _outside = obsidian
    saved = capture_for(service, page_for(service, connection)['items'][0]['selection_token'])
    entered, release = threading.Event(), threading.Event()
    root_opens = count_root_opens(monkeypatch)
    pausing_root_open(monkeypatch, entered, release)
    thread, outcome = run_in_thread(lambda: service.source_status(IDENTITY, *SCOPE, saved['id']))
    assert entered.wait(TIMEOUT), 'source status never reached the root-open boundary'
    service.disconnect('owner', connection['revision'])
    release.set()
    finish(thread)
    assert 'value' not in outcome, outcome
    error = outcome.get('error')
    assert isinstance(error, DomainError) and error.code in CONFLICT_CODES, outcome
    assert root_opens == []
