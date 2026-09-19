import asyncio
import json

import httpx
import pytest

from app.core.commands import CreateDelegation
from app.core.learning import LearningCore
from app.learning_domain import DomainError
from app.schemas import LearningVerificationSubmitRequest, LearningVerificationConfirmRequest
from pydantic import ValidationError
from test_learning_verifications import (
    IDENTITY, OWNER, PASS, FAIL, CHALLENGE, create_context, verification_service,
)
from test_learning_domain_schema import learning_database  # noqa: F401


async def saved_attempt(database, results):
    context = create_context(database)
    service = verification_service(database, results)
    started = await service.start(IDENTITY, {**context, "mode": "user_material"}, "start")
    saved = await service.submit(IDENTITY, started["id"], {"learner_work": "Synthetic process", "request_key": "answer-1"})
    return context, service, saved


@pytest.mark.asyncio
async def test_save_survives_provider_failure_and_retry_does_not_duplicate_submission(learning_database):
    _, service, saved = await saved_attempt(learning_database, ["not json", PASS])
    assert saved["evaluation"] is None
    failed = await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate-1")
    assert failed["evaluation"]["status"] == "failed"
    assert failed["result"] is None
    assert json.loads(learning_database.fetchone("SELECT content FROM learning_raw_artifact")[0])["learner_work"] == "Synthetic process"
    repeated = await service.submit(IDENTITY, saved["id"], {"learner_work": "Synthetic process", "request_key": "answer-1"})
    assert repeated["latest_submission_id"] == saved["latest_submission_id"]
    passed = await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate-2")
    assert passed["status"] == "submitted"
    assert learning_database.fetchone("SELECT COUNT(*) FROM learning_verification_submission")[0] == 1
    assert learning_database.fetchone("SELECT COUNT(*) FROM learning_verification_evaluation")[0] == 2
    assert learning_database.fetchone("SELECT status FROM learning_action")[0] == "open"
    public = json.dumps(service.list(IDENTITY))
    assert "Synthetic process" not in public
    assert "provider_snapshot_json" not in public


@pytest.mark.asyncio
async def test_final_confirmation_is_idempotent_and_never_regrades(learning_database):
    _, service, saved = await saved_attempt(learning_database, [PASS])
    result = await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate")
    assert result["status"] == "submitted"
    confirmed = service.confirm(IDENTITY, result["id"], result["latest_submission_id"], result["evaluation"]["id"])
    assert confirmed["status"] == "passed"
    assert service.confirm(IDENTITY, result["id"], result["latest_submission_id"], result["evaluation"]["id"]) == confirmed
    assert await service.evaluate(IDENTITY, result["id"], result["latest_submission_id"], "another-key") == confirmed
    assert learning_database.fetchone("SELECT COUNT(*) FROM learning_event WHERE event_type='action.completed'")[0] == 1


@pytest.mark.asyncio
async def test_late_old_evaluation_cannot_overwrite_new_submission(learning_database):
    _, service, saved = await saved_attempt(learning_database, [])
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
            content = PASS
        else:
            content = FAIL
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    service.transport = httpx.MockTransport(handler)
    old = asyncio.create_task(service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "old"))
    await asyncio.wait_for(started.wait(), 2)
    newer = await service.submit(IDENTITY, saved["id"], {"material": "New synthetic process", "request_key": "answer-2"})
    await service.evaluate(IDENTITY, saved["id"], newer["latest_submission_id"], "new")
    release.set()
    await old
    current = service.list(IDENTITY)[0]
    assert current["latest_submission_id"] == newer["latest_submission_id"]
    assert current["result"]["passed"] is False
    assert learning_database.fetchone("SELECT COUNT(*) FROM learning_verification_submission")[0] == 2
    with pytest.raises(DomainError, match="verification_state_conflict"):
        service.confirm(IDENTITY, saved["id"], saved["latest_submission_id"], "old")


@pytest.mark.asyncio
async def test_multi_delegation_completion_and_replay_preserve_remaining_work(learning_database):
    from app.core.commands import EndSession, StartSession
    context, service, saved = await saved_attempt(learning_database, [PASS])
    version = learning_database.fetchone("SELECT version FROM learning_action")[0]
    outcome = learning_database.fetchone("SELECT outcome_id FROM learning_delegation")[0]
    other = LearningCore(learning_database).execute(OWNER, CreateDelegation(
        action_id=context["action_id"], outcome_id=outcome, boundaries="Other scope",
        stop_conditions="Other condition", expected_version=version,
    ), "other-delegation")
    LearningCore(learning_database).execute(OWNER, EndSession(
        session_id=context["session_id"], disposition="ended", expected_version=version + 1,
    ), "end-first-session")
    other_session = LearningCore(learning_database).execute(OWNER, StartSession(
        delegation_id=other["id"], expected_version=version + 2,
    ), "start-other-session")
    evaluated = await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate")
    completed = service.confirm(IDENTITY, saved["id"], saved["latest_submission_id"], evaluated["evaluation"]["id"])
    assert completed["status"] == "passed"
    assert completed["action_completed"] is False
    for replay in (False, True):
        if replay:
            LearningCore(learning_database).replay(OWNER)
        assert learning_database.fetchone("SELECT status FROM learning_action")[0] == "open"
        assert learning_database.fetchone("SELECT status FROM learning_delegation WHERE id=?", (other["id"],))[0] == "active"
        assert learning_database.fetchone("SELECT status FROM learning_session WHERE id=?", (other_session["id"],))[0] == "running"
        assert learning_database.fetchone("SELECT status FROM learning_delegation WHERE id=?", (context["delegation_id"],))[0] == "completed"
        assert learning_database.fetchall("PRAGMA foreign_key_check") == []


@pytest.mark.asyncio
async def test_confirmation_failure_rolls_back_action_and_session(learning_database):
    _, service, saved = await saved_attempt(learning_database, [PASS])
    evaluated = await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate")
    learning_database.connection.execute("""CREATE TRIGGER reject_confirmation BEFORE UPDATE ON learning_verification
        WHEN NEW.status='passed' BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END""")
    with pytest.raises(DomainError, match="storage_failure"):
        service.confirm(IDENTITY, saved["id"], saved["latest_submission_id"], evaluated["evaluation"]["id"])
    assert learning_database.fetchone("SELECT status FROM learning_action")[0] == "open"
    assert learning_database.fetchone("SELECT status FROM learning_session")[0] == "running"
    assert learning_database.fetchone("SELECT COUNT(*) FROM learning_event WHERE event_type='action.completed'")[0] == 0


@pytest.mark.asyncio
async def test_invalid_private_result_and_foreign_confirmation_are_rejected(learning_database):
    invalid = json.dumps({"passed": True, "stop_condition_met": True, "feedback": {"answer_key": "private"}, "next_step": "next"})
    _, service, saved = await saved_attempt(learning_database, [invalid])
    result = await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate")
    assert result["result"] is None
    assert result["evaluation"]["status"] == "failed"
    with pytest.raises(DomainError, match="not_found"):
        service.confirm({**IDENTITY, "id": "owner-b", "device_id": "owner-b-device"}, saved["id"], saved["latest_submission_id"], result["evaluation"]["id"])
    with pytest.raises(DomainError, match="idempotency_conflict"):
        await service.submit(IDENTITY, saved["id"], {"material": "Changed content", "request_key": "answer-1"})


def test_confirmation_cannot_be_bundled_with_submission():
    with pytest.raises(ValidationError):
        LearningVerificationSubmitRequest(material="Synthetic", request_key="save", stop_condition_confirmed=True)
    with pytest.raises(ValidationError):
        LearningVerificationConfirmRequest(submission_id="s", evaluation_id="e", stop_condition_confirmed=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["https://", "https://example.com/source", "https://docs.example.org/source"])
async def test_rejects_invalid_or_placeholder_sources(learning_database, url):
    context = create_context(learning_database)
    challenge = json.loads(CHALLENGE)
    challenge["questions"][0]["source_urls"] = [url]
    service = verification_service(learning_database, [json.dumps(challenge)])
    with pytest.raises(DomainError, match="verification_invalid"):
        await service.start(IDENTITY, {**context, "mode": "ai_challenge"}, "start")


@pytest.mark.asyncio
async def test_cancelled_evaluation_keeps_submission_and_can_retry(learning_database):
    _, service, saved = await saved_attempt(learning_database, [])
    started = asyncio.Event()

    async def handler(request):
        started.set()
        await asyncio.Future()

    service.transport = httpx.MockTransport(handler)
    pending = asyncio.create_task(service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "cancel"))
    await asyncio.wait_for(started.wait(), 2)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    current = service.list(IDENTITY)[0]
    assert current["latest_submission_id"] == saved["latest_submission_id"]
    assert current["evaluation"]["reason"] == "cancelled"
    assert learning_database.fetchone("SELECT content_json FROM learning_verification_submission")[0]


@pytest.mark.asyncio
async def test_confirmation_rejects_changed_contract(learning_database):
    _, service, saved = await saved_attempt(learning_database, [PASS])
    evaluated = await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate")
    with learning_database.transaction() as connection:
        connection.execute("""INSERT INTO learning_contract_version
            SELECT delegation_id, owner_id, version+1, boundaries, 'Changed stop condition', time_budget_minutes, criterion_id, bound_at
            FROM learning_contract_version""")
        connection.execute("UPDATE learning_delegation SET contract_version=contract_version+1")
    with pytest.raises(DomainError, match="verification_contract_changed"):
        service.confirm(IDENTITY, saved["id"], saved["latest_submission_id"], evaluated["evaluation"]["id"])
    assert learning_database.fetchone("SELECT status FROM learning_action")[0] == "open"


@pytest.mark.asyncio
async def test_verification_http_contract_separates_save_evaluate_confirm(learning_database):
    from fastapi import FastAPI
    from app.dependencies import current_identity
    from app.routers.learning import router
    from app.learning_service import LearningService
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_identity] = lambda: IDENTITY
    app.state.learning = LearningService(learning_database)
    app.state.verification = verification_service(learning_database, [PASS])
    context = create_context(learning_database)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://isolated") as client:
        started = await client.post("/api/learning/verifications", json={**context, "mode": "user_material", "request_key": "start"})
        assert started.status_code == 201
        path = "/api/learning/verifications/" + started.json()["id"]
        assert (await client.post(path + "/submit", json={"material": "Synthetic", "request_key": "save", "stop_condition_confirmed": True})).status_code == 422
        saved = await client.post(path + "/submit", json={"learner_work": "Synthetic private response", "request_key": "save"})
        assert saved.status_code == 200
        assert "Synthetic private response" not in saved.text
        sid = saved.json()["latest_submission_id"]
        evaluated = await client.post(path + "/evaluate", json={"submission_id": sid, "request_key": "evaluate"})
        assert evaluated.status_code == 200
        assert evaluated.json()["status"] == "submitted"
        confirm_payload = {"submission_id": sid, "evaluation_id": evaluated.json()["evaluation"]["id"], "stop_condition_confirmed": True}
        assert (await client.post(path + "/confirm", json=confirm_payload)).json()["status"] == "passed"
        app.dependency_overrides[current_identity] = lambda: {**IDENTITY, "id": "owner-b", "device_id": "owner-b-device"}
        assert (await client.post(path + "/confirm", json=confirm_payload)).status_code == 404


def test_upgrade_022_preserves_last_saved_submission_and_result(tmp_path):
    from pathlib import Path
    from app.db import Database
    from app.learning_storage import open_learning_database
    path = tmp_path / "old-learning.sqlite3"
    database = Database(path, Path(__file__).parents[1] / "app" / "migrations", migration_floor=11, migration_ceiling=22)
    with database.transaction() as connection:
        connection.execute("INSERT INTO local_identity VALUES ('owner-a', 'owner-a-device', 'Synthetic', 'UTC', '2026-09-16', '2026-09-16')")
    context = create_context(database)
    with database.transaction() as connection:
        connection.execute("""INSERT INTO learning_verification
            (id, owner_id, action_id, delegation_id, session_id, mode, request_key, request_fingerprint,
             status, challenge_json, answer_key_json, submission_json, result_json, created_at)
            VALUES ('legacy', 'owner-a', ?, ?, ?, 'user_material', 'legacy', 'fingerprint',
                    'submitted', '{}', '{}', ?, ?, '2026-09-16')""",
            (context["action_id"], context["delegation_id"], context["session_id"], json.dumps({"material": "Synthetic legacy content"}), PASS))
    database.close()
    upgraded = open_learning_database(path)
    try:
        assert upgraded.fetchone("SELECT latest_submission_id FROM learning_verification")[0] == "legacy:legacy"
        assert json.loads(upgraded.fetchone("SELECT content_json FROM learning_verification_submission")[0])["material"] == "Synthetic legacy content"
        assert json.loads(upgraded.fetchone("SELECT result_json FROM learning_verification_evaluation")[0])["passed"] is True
        assert upgraded.fetchone("SELECT provider_snapshot_json FROM learning_verification_evaluation")[0] is None
        assert upgraded.fetchall("PRAGMA foreign_key_check") == []
    finally:
        upgraded.close()


@pytest.mark.asyncio
async def test_retry_supersedes_interrupted_request_for_same_submission(learning_database):
    _, service, saved = await saved_attempt(learning_database, [])
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
            content = FAIL
        else:
            content = PASS
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    service.transport = httpx.MockTransport(handler)
    pending = asyncio.create_task(service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "first"))
    await asyncio.wait_for(started.wait(), 2)
    duplicate = await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "first")
    assert duplicate["evaluation"]["status"] == "running"
    assert calls == 1
    retry = await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "retry")
    release.set()
    await pending
    assert retry["result"]["passed"] is True
    assert service.list(IDENTITY)[0]["result"]["passed"] is True
    assert learning_database.fetchone("SELECT reason FROM learning_verification_evaluation WHERE request_key='first'")[0] == "superseded"
