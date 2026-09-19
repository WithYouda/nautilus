import asyncio
import json
import sqlite3
from contextlib import closing

import httpx
import pytest

from app.core.commands import CreateLearningAction, CreateDelegation, StartSession, PurgeArtifact, CorrectArtifact
from app.core.learning import LearningCore
from app.evidence import EvidenceService, EvidenceClaimDraft
from app.evidence_events import EvidenceEventService
from app.learning_domain import DomainError
from app.learning_service import LearningService
from app.learning_production import restore_learning_backup, upgrade_learning_database, ProductionLearningDatabaseError
from app.review import ReviewService
from app.state_derivation import StateDerivationService
from app.verification import VerificationService
from test_learning_domain_schema import learning_database  # noqa: F401
from test_learning_verifications import IDENTITY, OWNER, PASS, CHALLENGE, create_context, FakeConversations, response_transport

WORK = "regex: ^Nautilus[0-9]+$\nsample: Nautilus42\nI used anchors to restrict the match."
REFERENCE = "PRIVATE_REFERENCE_SHOULD_NOT_BECOME_EVIDENCE"


async def chain(database, *, standard=True, material=None, work=WORK, responses=None):
    learning = LearningService(database)
    principal = learning.principal(IDENTITY)
    if standard:
        criterion = database.fetchone("SELECT id, outcome_id FROM learning_criterion_version WHERE owner_id=?", (principal.owner_id,))
        core = learning.core
        action = core.execute(principal, CreateLearningAction(title="Regex", context_key="python-regex-basics"), "action")
        delegation = core.execute(principal, CreateDelegation(action_id=action["id"], outcome_id=criterion["outcome_id"], criterion_id=criterion["id"], boundaries="Regex only", stop_conditions="Explain and demonstrate", expected_version=1), "delegation")
        session = core.execute(principal, StartSession(delegation_id=delegation["id"], expected_version=2), "session")
        context = {"action_id": action["id"], "delegation_id": delegation["id"], "session_id": session["id"]}
    else:
        context = create_context(database)
    events = EvidenceEventService(database)
    evidence = EvidenceService(learning, evidence_events=events)
    service = VerificationService(learning, FakeConversations(), response_transport(responses or [PASS]), evidence=evidence)
    verification = await service.start(IDENTITY, {**context, "mode": "user_material"}, "verify")
    saved = await service.submit(IDENTITY, verification["id"], {"material": material or REFERENCE, "learner_work": work, "evidence_condition": "independent", "request_key": "answer"})
    return service, evidence, events, saved


@pytest.mark.asyncio
async def test_submission_is_atomic_fact_and_private_reference_is_not_analyzed(learning_database):
    service, evidence, events, saved = await chain(learning_database)
    assert saved["artifact_id"]
    raw = service.learning.artifact(IDENTITY, saved["artifact_id"])
    assert json.loads(raw["content"])["material"] == REFERENCE
    assert learning_database.fetchone("SELECT content_json FROM learning_verification_submission")[0] == '{}'
    assert REFERENCE not in learning_database.fetchone("SELECT payload_json FROM learning_event WHERE event_type='verification.artifact_recorded'")[0]
    observed = []
    def semantic(request):
        observed.append(request["content"])
        return [EvidenceClaimDraft(dimension_id="syntax_semantics", stance="supports", source="ai_analysis", statement="Synthetic explanation", verification_method="semantic_analysis", evidence_condition="independent", scope="artifact")]
    evidence.semantic_analyzer = semantic
    evaluated = await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate")
    assert evaluated["status"] == "submitted"
    result = await service.analyze_evidence(IDENTITY, saved["id"])
    assert result["evidence"]["status"] == "succeeded"
    assert observed == [WORK]
    claims = evidence.claims(IDENTITY)
    assert len(claims) == 2
    assert all(c["artifact_id"] == raw["artifact_id"] and c["fact_event_id"] == raw["fact_event_id"] and c["status"] == "candidate" for c in claims)
    await service.analyze_evidence(IDENTITY, saved["id"])
    assert len(evidence.claims(IDENTITY)) == 2
    assert observed == [WORK]
    assert learning_database.fetchone("SELECT status FROM learning_action")[0] == "open"
    service.learning.replay(IDENTITY)
    events.replay(OWNER.owner_id)
    assert learning_database.fetchall("PRAGMA foreign_key_check") == []
    assert service.learning.artifact(IDENTITY, saved["artifact_id"])["content"] == raw["content"]


@pytest.mark.asyncio
async def test_reference_only_cannot_pass_or_generate_evidence(learning_database):
    service, evidence, _, saved = await chain(learning_database, work="", material=WORK)
    evaluated = await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate")
    assert evaluated["result"]["passed"] is False
    with pytest.raises(DomainError, match="verification_learner_work_required"):
        await service.analyze_evidence(IDENTITY, saved["id"])
    with pytest.raises(DomainError, match="verification_learner_work_required"):
        await evidence.analyze(IDENTITY, saved["artifact_id"], "bypass")
    assert evidence.claims(IDENTITY) == []


@pytest.mark.asyncio
async def test_no_standard_saves_fact_without_claim_or_derived_state(learning_database):
    service, evidence, _, saved = await chain(learning_database, standard=False)
    await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate")
    result = await service.analyze_evidence(IDENTITY, saved["id"])
    assert result["evidence"]["status"] == "blocked_no_criterion"
    assert evidence.claims(IDENTITY) == []
    assert learning_database.fetchone("SELECT COUNT(*) FROM learning_derived_state")[0] == 0


@pytest.mark.asyncio
async def test_purge_invalidates_claims_scrubs_copies_and_replay_cannot_restore(learning_database, tmp_path):
    service, evidence, events, saved = await chain(learning_database)
    evidence.semantic_analyzer = lambda request: [EvidenceClaimDraft(dimension_id="syntax_semantics", stance="supports", source="ai_analysis", statement=REFERENCE, verification_method="semantic_analysis", evidence_condition="independent", scope="artifact")]
    await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate")
    await service.analyze_evidence(IDENTITY, saved["id"])
    state = StateDerivationService(service.learning, events)
    review = ReviewService(service.learning, state, events)
    # Adopt through the same review boundary used by the workspace.
    for claim in evidence.claims(IDENTITY):
        evidence.request_human_review(IDENTITY, claim["id"], "follow-" + claim["id"], REFERENCE)
        review.review(IDENTITY, claim["id"], "adopt", REFERENCE, "adopt-" + claim["id"])
    ledger_before = {row["id"]: row["event_hash"] for row in learning_database.fetchall("SELECT id, event_hash FROM learning_evidence_event")}
    result = service.list(IDENTITY)[0]
    service.confirm(IDENTITY, saved["id"], saved["latest_submission_id"], result["evaluation"]["id"])
    before_backup = tmp_path / "before.sqlite3"
    with closing(sqlite3.connect(before_backup)) as destination:
        learning_database.connection.backup(destination)
    purged = service.purge(IDENTITY, saved["id"])
    assert purged["content_purged"] is True
    assert purged["action_completed"] is True
    assert purged["result"] is None
    assert service.learning.artifact(IDENTITY, saved["artifact_id"])["content"] is None
    assert all(c["status"] == "invalidated" for c in evidence.claims(IDENTITY))
    assert all(s["status"] != "supported" for s in state.states(IDENTITY))
    for table in ("learning_verification", "learning_verification_submission", "learning_verification_evaluation", "learning_evidence_claim", "learning_evidence_event", "learning_evidence_private_content", "learning_review_action", "learning_evidence_follow_up"):
        assert REFERENCE not in str([tuple(row) for row in learning_database.fetchall("SELECT * FROM " + table)])
    assert {row["id"]: row["event_hash"] for row in learning_database.fetchall("SELECT id, event_hash FROM learning_evidence_event") if row["id"] in ledger_before} == ledger_before
    service.learning.replay(IDENTITY)
    events.replay(OWNER.owner_id)
    assert all(c["status"] == "invalidated" and REFERENCE not in c["statement"] for c in evidence.claims(IDENTITY))
    assert all(s["status"] != "supported" for s in state.states(IDENTITY))
    assert all(f["status"] == "cancelled" and f["note"] is None for f in evidence.follow_ups(IDENTITY))
    with pytest.raises(DomainError, match="artifact_not_eligible"):
        review.review(IDENTITY, evidence.claims(IDENTITY)[0]["id"], "question", REFERENCE, "question-after-purge")
    assert service.purge(IDENTITY, saved["id"])["content_purged"] is True
    with pytest.raises(ProductionLearningDatabaseError, match="purged"):
        restore_learning_backup(before_backup, learning_database.database_path)


@pytest.mark.asyncio
async def test_purge_during_evaluation_discards_late_result(learning_database):
    service, _, _, saved = await chain(learning_database)
    started, release = asyncio.Event(), asyncio.Event()
    async def handler(request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": PASS}}]})
    service.transport = httpx.MockTransport(handler)
    task = asyncio.create_task(service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate"))
    await asyncio.wait_for(started.wait(), 2)
    service.purge(IDENTITY, saved["id"])
    release.set()
    result = await task
    assert result["result"] is None
    assert result["content_purged"]


@pytest.mark.asyncio
async def test_purge_during_evidence_analysis_cannot_recreate_claim(learning_database):
    service, evidence, _, saved = await chain(learning_database)
    await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate")
    started, release = asyncio.Event(), asyncio.Event()
    async def semantic(request):
        started.set()
        await release.wait()
        return [EvidenceClaimDraft(dimension_id="syntax_semantics", stance="supports", source="ai_analysis", statement=REFERENCE, verification_method="semantic_analysis", evidence_condition="independent", scope="artifact")]
    evidence.semantic_analyzer = semantic
    task = asyncio.create_task(service.analyze_evidence(IDENTITY, saved["id"]))
    await asyncio.wait_for(started.wait(), 2)
    service.purge(IDENTITY, saved["id"])
    release.set()
    with pytest.raises(DomainError, match="artifact_not_eligible"):
        await task
    assert evidence.claims(IDENTITY) == []


@pytest.mark.asyncio
async def test_submission_fact_failure_rolls_back_content_and_rejects_other_owner(learning_database):
    service, _, _, saved = await chain(learning_database)
    learning_database.connection.execute("""CREATE TRIGGER reject_record BEFORE INSERT ON learning_raw_artifact
        BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END""")
    with pytest.raises(DomainError, match="storage_failure"):
        await service.submit(IDENTITY, saved["id"], {"learner_work": "New", "request_key": "new"})
    assert learning_database.fetchone("SELECT COUNT(*) FROM learning_verification_submission")[0] == 1
    with pytest.raises(DomainError, match="not_found"):
        service.purge({**IDENTITY, "id": "owner-b", "device_id": "owner-b-device"}, saved["id"])


@pytest.mark.asyncio
async def test_assisted_submission_cannot_become_independent_evidence(learning_database):
    service, evidence, _, saved = await chain(learning_database)
    newer = await service.submit(IDENTITY, saved["id"], {"learner_work": WORK, "request_key": "assisted"})
    await service.evaluate(IDENTITY, saved["id"], newer["latest_submission_id"], "evaluate")
    with pytest.raises(DomainError, match="verification_independent_evidence_required"):
        await service.analyze_evidence(IDENTITY, saved["id"])
    with pytest.raises(DomainError, match="verification_independent_evidence_required"):
        await evidence.analyze(IDENTITY, newer["artifact_id"], "bypass")
    assert evidence.claims(IDENTITY) == []


@pytest.mark.asyncio
async def test_ai_challenge_evidence_uses_only_saved_response(learning_database):
    service, evidence, _, first = await chain(learning_database)
    service.transport = response_transport([CHALLENGE, PASS])
    started = await service.start(IDENTITY, {
        "action_id": first["action_id"], "delegation_id": first["delegation_id"],
        "session_id": first["session_id"], "mode": "ai_challenge",
    }, "ai-challenge")
    saved = await service.submit(IDENTITY, started["id"], {
        "responses": {"q1": WORK}, "evidence_condition": "independent", "request_key": "ai-response",
    })
    seen = []
    def semantic(request):
        seen.append(request["content"])
        return []
    evidence.semantic_analyzer = semantic
    await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate")
    result = await service.analyze_evidence(IDENTITY, saved["id"])
    assert result["evidence"]["status"] == "succeeded"
    assert seen == [WORK]
    assert evidence.claims(IDENTITY)[0]["artifact_id"] == saved["artifact_id"]
    service.purge(IDENTITY, saved["id"])
    original = next(item for item in service.list(IDENTITY) if item["id"] == first["id"])
    assert not original["content_purged"]


@pytest.mark.asyncio
async def test_mixed_batch_reason_is_erased_without_invalidating_other_artifact(learning_database):
    from app.core.commands import SaveTextArtifact
    service, evidence, events, saved = await chain(learning_database)
    await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate")
    await service.analyze_evidence(IDENTITY, saved["id"])
    version = learning_database.fetchone("SELECT version FROM learning_action")[0]
    other = service.learning.core.execute(OWNER, SaveTextArtifact(session_id=saved["session_id"], content=WORK, expected_version=version), "ordinary-work")
    await evidence.analyze(IDENTITY, other["id"], "ordinary-evidence")
    state = StateDerivationService(service.learning, events)
    review = ReviewService(service.learning, state, events)
    review.batch_review(IDENTITY, [claim["id"] for claim in evidence.claims(IDENTITY)], "adopt", REFERENCE, "mixed-batch")
    service.purge(IDENTITY, saved["id"])
    for replay in (False, True):
        if replay:
            events.replay(OWNER.owner_id)
        assert all(REFERENCE not in str(row) for row in review.actions(IDENTITY))
        assert REFERENCE not in str(events.events(OWNER.owner_id))
        assert evidence.claims(IDENTITY, other["id"])[0]["status"] == "adopted"
        assert next(s for s in state.states(IDENTITY) if s["dimension_id"] == "application")["status"] == "supported"


@pytest.mark.asyncio
async def test_direct_artifact_purge_blocks_old_evaluation_and_preserves_other_attempts(learning_database, tmp_path):
    service, evidence, events, saved = await chain(learning_database)
    await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate")
    await service.analyze_evidence(IDENTITY, saved["id"])
    version = learning_database.fetchone("SELECT version FROM learning_action")[0]
    with pytest.raises(DomainError, match="verification_submission_immutable"):
        service.learning.core.execute(OWNER, CorrectArtifact(artifact_id=saved["artifact_id"], content="Changed", expected_version=version), "correct")
    service.learning.purge_artifact(IDENTITY, {"artifact_id": saved["artifact_id"], "expected_version": version, "confirmation": "PURGE"}, "purge-one")
    state = StateDerivationService(service.learning, events)
    assert all(s["status"] != "supported" for s in state.states(IDENTITY))
    current = service.list(IDENTITY)[0]
    assert current["content_purged"] and not current["verification_purged"]
    for key in ("evaluate", "retry"):
        with pytest.raises(DomainError, match="artifact_not_eligible"):
            await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], key)
    with pytest.raises(DomainError, match="artifact_not_eligible"):
        service.confirm(IDENTITY, saved["id"], saved["latest_submission_id"], current["evaluation"]["id"])
    with pytest.raises(DomainError, match="artifact_not_eligible"):
        await service.analyze_evidence(IDENTITY, saved["id"])
    newer = await service.submit(IDENTITY, saved["id"], {"learner_work": WORK, "request_key": "new"})
    assert newer["artifact_id"] != saved["artifact_id"] and not newer["content_purged"]
    service.transport = response_transport([PASS])
    await service.evaluate(IDENTITY, saved["id"], newer["latest_submission_id"], "new-evaluation")
    post_backup, restore_target = tmp_path / "post.sqlite3", tmp_path / "restore.sqlite3"
    for path in (post_backup, restore_target):
        with closing(sqlite3.connect(path)) as destination:
            learning_database.connection.backup(destination)
    assert restore_learning_backup(post_backup, restore_target)["up_to_date"]
    service.purge(IDENTITY, saved["id"])
    assert learning_database.fetchone("SELECT COUNT(*) FROM learning_raw_artifact WHERE content IS NOT NULL")[0] == 0


@pytest.mark.asyncio
async def test_purge_and_state_recalculation_roll_back_together(learning_database, monkeypatch):
    service, evidence, _, saved = await chain(learning_database)
    await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate")
    await service.analyze_evidence(IDENTITY, saved["id"])
    def fail(*args, **kwargs):
        raise DomainError("synthetic_recalculation_failure")
    monkeypatch.setattr(StateDerivationService, "derive", fail)
    with pytest.raises(DomainError, match="synthetic_recalculation_failure"):
        service.purge(IDENTITY, saved["id"])
    assert not service.list(IDENTITY)[0]["content_purged"]
    assert service.learning.artifact(IDENTITY, saved["artifact_id"])["content"] is not None
    assert all(c["status"] == "candidate" for c in evidence.claims(IDENTITY))
    assert learning_database.fetchone("SELECT COUNT(*) FROM learning_event WHERE event_type='artifact.purged'")[0] == 0
    version = learning_database.fetchone("SELECT version FROM learning_action")[0]
    with pytest.raises(DomainError, match="synthetic_recalculation_failure"):
        service.learning.purge_artifact(IDENTITY, {"artifact_id": saved["artifact_id"], "expected_version": version, "confirmation": "PURGE"}, "purge-one")
    assert not service.list(IDENTITY)[0]["content_purged"]


@pytest.mark.asyncio
async def test_private_evidence_is_immutable_and_restore_checks_erased_copies(learning_database, tmp_path):
    service, _, events, saved = await chain(learning_database)
    await service.evaluate(IDENTITY, saved["id"], saved["latest_submission_id"], "evaluate")
    await service.analyze_evidence(IDENTITY, saved["id"])
    private = learning_database.fetchone("SELECT * FROM learning_evidence_private_content")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with learning_database.transaction() as connection:
            connection.execute("UPDATE learning_evidence_private_content SET content_json='{}'")
    with pytest.raises(sqlite3.IntegrityError, match="must be purged"):
        with learning_database.transaction() as connection:
            connection.execute("DELETE FROM learning_evidence_private_content")
    service.purge(IDENTITY, saved["id"])
    post_backup = tmp_path / "post.sqlite3"
    target_path = tmp_path / "restore-target.sqlite3"
    for path in (post_backup, target_path):
        with closing(sqlite3.connect(path)) as destination:
            learning_database.connection.backup(destination)
    assert restore_learning_backup(post_backup, target_path)["up_to_date"]
    # Simulate a backup retaining a private evidence copy despite erased raw content.
    with closing(sqlite3.connect(post_backup)) as backup:
        backup.execute("DROP TRIGGER learning_evidence_private_immutable")
        backup.execute("UPDATE learning_evidence_private_content SET content_json=?, purged_at=NULL WHERE event_id=?", (private["content_json"], private["event_id"]))
        backup.commit()
    with pytest.raises(ProductionLearningDatabaseError, match="purged"):
        restore_learning_backup(post_backup, target_path)
    # Corruption is detected before replay can replace current projections.
    learning_database.connection.execute("DROP TRIGGER learning_evidence_private_immutable")
    with learning_database.transaction() as connection:
        connection.execute("UPDATE learning_evidence_private_content SET content_json='{}', purged_at=NULL WHERE event_id=?", (private["event_id"],))
    with pytest.raises(DomainError, match="evidence_event_integrity_failed"):
        events.replay(OWNER.owner_id)


@pytest.mark.asyncio
async def test_purge_http_requires_literal_confirmation_and_owner(learning_database):
    from fastapi import FastAPI
    from app.dependencies import current_identity
    from app.routers.learning import router
    service, _, _, saved = await chain(learning_database)
    app = FastAPI()
    app.include_router(router)
    app.state.verification = service
    app.dependency_overrides[current_identity] = lambda: IDENTITY
    path = f"/api/learning/verifications/{saved['id']}/purge"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://isolated") as client:
        assert (await client.post(path, json={})).status_code == 422
        assert (await client.post(path, json={"confirmation": True})).status_code == 422
        app.dependency_overrides[current_identity] = lambda: {**IDENTITY, "id": "owner-b", "device_id": "owner-b-device"}
        assert (await client.post(path, json={"confirmation": "PURGE"})).status_code == 404
        assert (await client.post(f"/api/learning/verifications/{saved['id']}/evidence", json={})).status_code == 404
        app.dependency_overrides[current_identity] = lambda: IDENTITY
        result = await client.post(path, json={"confirmation": "PURGE"})
        assert result.status_code == 200 and result.json()["verification_purged"]
        assert REFERENCE not in result.text and WORK not in result.text


def test_023_upgrade_retries_import_without_inventing_sessions_or_past_work(tmp_path, monkeypatch):
    from pathlib import Path
    from app.db import Database
    from app.learning_storage import open_learning_database
    from app.core.commands import EndSession
    path = tmp_path / "legacy.sqlite3"
    database = Database(path, Path(__file__).parents[1] / "app" / "migrations", migration_floor=11, migration_ceiling=23)
    with database.transaction() as connection:
        connection.execute("INSERT INTO local_identity VALUES ('owner-a', 'owner-a-device', 'Synthetic', 'UTC', '2026-09-01', '2026-09-01')")
    context = create_context(database)
    version = database.fetchone("SELECT version FROM learning_action")[0]
    LearningCore(database).execute(OWNER, EndSession(session_id=context["session_id"], disposition="ended", expected_version=version), "end")
    contract = {"version": 1, "stop_conditions": "Synthetic condition"}
    with database.transaction() as connection:
        for verification_id, session_id in (("linked", context["session_id"]), ("unlinked", None)):
            connection.execute(
                """INSERT INTO learning_verification
                   (id, owner_id, action_id, delegation_id, session_id, mode, request_key, request_fingerprint,
                    status, challenge_json, answer_key_json, submission_json, result_json, created_at, submitted_at,
                    contract_snapshot_json, latest_submission_id)
                   VALUES (?, 'owner-a', ?, ?, ?, 'user_material', ?, 'fingerprint', 'submitted', '{}', '{}', ?, ?,
                           '2026-09-01', '2026-09-02', ?, ?)""",
                (verification_id, context["action_id"], context["delegation_id"], session_id, verification_id,
                 json.dumps({"material": REFERENCE}), PASS, json.dumps(contract), verification_id),
            )
            connection.execute("INSERT INTO learning_verification_submission VALUES (?, 'owner-a', ?, 'legacy', 'fingerprint', ?, '2026-09-02')", (verification_id, verification_id, json.dumps({"material": REFERENCE})))
            connection.execute("INSERT INTO learning_verification_evaluation VALUES (?, 'owner-a', ?, 'legacy', 'succeeded', ?, NULL, NULL, '2026-09-02', '2026-09-02')", (verification_id, verification_id, PASS))
    database.close()
    original = VerificationService.link_legacy_submissions
    def interrupted(*args):
        raise RuntimeError("synthetic import interruption")
    monkeypatch.setattr(VerificationService, "link_legacy_submissions", interrupted)
    with pytest.raises(RuntimeError, match="synthetic import interruption"):
        upgrade_learning_database(path, tmp_path / "backups", authorized=True)
    monkeypatch.setattr(VerificationService, "link_legacy_submissions", original)
    assert upgrade_learning_database(path, tmp_path / "backups", authorized=True)["status"] == "upgraded"
    assert upgrade_learning_database(path, tmp_path / "backups", authorized=True)["status"] == "already_up_to_date"
    database = open_learning_database(path, migrate=False)
    try:
        linked = database.fetchone("SELECT * FROM learning_verification_submission WHERE id='linked'")
        assert linked["artifact_id"] and linked["content_json"] == '{}'
        assert database.fetchone("SELECT artifact_id FROM learning_verification_submission WHERE id='unlinked'")[0] is None
        event = database.fetchone("SELECT payload_json, occurred_at FROM learning_event WHERE event_type='verification.artifact_recorded'")
        assert json.loads(event["payload_json"])["submitted_at"] == "2026-09-02"
        assert event["occurred_at"] != "2026-09-02"
        assert database.fetchone("SELECT COUNT(*) FROM learning_event WHERE event_type='verification.artifact_recorded'")[0] == 1
        assert database.fetchone("SELECT COUNT(*) FROM learning_session")[0] == 1
        service = VerificationService(LearningService(database), None)
        with pytest.raises(DomainError, match="verification_learner_work_required"):
            service.confirm(IDENTITY, "linked", "linked", "linked")
        service.purge(IDENTITY, "unlinked")
        assert database.fetchone("SELECT content_json FROM learning_verification_submission WHERE id='unlinked'")[0] == '{}'
        assert database.fetchall("PRAGMA foreign_key_check") == []
    finally:
        database.close()
