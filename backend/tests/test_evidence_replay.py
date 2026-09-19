from __future__ import annotations

import sqlite3

import pytest

from app.learning_domain import DomainError
from test_evidence_claims import authorize, create_standard_chain


def remove_evidence_event_guards(database):
    database.connection.executescript(
        "DROP TRIGGER IF EXISTS learning_evidence_event_no_update; "
        "DROP TRIGGER IF EXISTS learning_evidence_event_no_delete;"
    )


def test_evidence_replay_rebuilds_claims_reviews_states_and_follow_ups(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    analysis = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
        json={"request_key": "evidence-replay-analysis"},
    )
    assert analysis.status_code == 200
    claim_id = analysis.json()["claims"][0]["id"]

    follow_up = client.post(
        f"/api/learning/evidence-claims/{claim_id}/human-review",
        json={"request_key": "replay-review", "note": "回放前复核请求"},
    )
    assert follow_up.status_code == 201
    review = client.post(
        f"/api/learning/evidence-claims/{claim_id}/review",
        json={"action": "adopt", "reason": "回放前采纳", "request_key": "replay-adopt"},
    )
    assert review.status_code == 201

    before_claims = client.get("/api/learning/evidence-claims").json()
    before_states = client.get("/api/learning/derived-states").json()
    before_follow_ups = client.get("/api/learning/evidence-follow-ups").json()

    replay = client.post("/api/learning/evidence-replay")
    assert replay.status_code == 200
    assert replay.json()["status"] == "succeeded"
    assert replay.json()["event_count"] > 0
    assert replay.json()["aggregate_count"] > 0
    assert all(
        row["schema_version"] == 1
        for row in client.app.state.learning.database.fetchall(
            "SELECT schema_version FROM learning_evidence_event"
        )
    )

    after_claims = client.get("/api/learning/evidence-claims").json()
    after_states = client.get("/api/learning/derived-states").json()
    after_follow_ups = client.get("/api/learning/evidence-follow-ups").json()

    assert after_claims == before_claims
    assert after_states == before_states
    assert after_follow_ups == before_follow_ups
    assert after_claims[0]["status"] == "adopted"
    assert after_states
    assert after_follow_ups[0]["kind"] == "human_review"


def test_evidence_replay_rejects_a_broken_event_chain(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    analysis = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
        json={"request_key": "broken-chain-analysis"},
    )
    assert analysis.status_code == 200
    from app.evidence_events import _event_hash

    database = client.app.state.learning.database
    remove_evidence_event_guards(database)
    row = dict(database.fetchone("SELECT * FROM learning_evidence_event ORDER BY created_at LIMIT 1"))
    row["previous_hash"] = "0" * 64
    with database.transaction() as connection:
        connection.execute(
            "UPDATE learning_evidence_event SET previous_hash=?, event_hash=? WHERE id=?",
            (row["previous_hash"], _event_hash(row), row["id"]),
        )

    response = client.post("/api/learning/evidence-replay")
    assert response.status_code == 409
    assert response.json()["detail"]["kind"] == "evidence_event_chain_invalid"


def test_evidence_replay_rejects_unsupported_schema_version_and_preserves_projection(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    analysis = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
        json={"request_key": "unsupported-schema-analysis"},
    )
    assert analysis.status_code == 200
    before = client.get("/api/learning/evidence-claims").json()

    database = client.app.state.learning.database
    remove_evidence_event_guards(database)
    event = database.fetchone(
        "SELECT id FROM learning_evidence_event ORDER BY created_at LIMIT 1"
    )
    with database.transaction() as connection:
        connection.execute(
            "UPDATE learning_evidence_event SET schema_version=999 WHERE id=?",
            (event["id"],),
        )

    response = client.post("/api/learning/evidence-replay")
    assert response.status_code == 409
    assert response.json()["detail"]["kind"] == "evidence_event_version_unsupported"
    assert client.get("/api/learning/evidence-claims").json() == before
    audit = client.app.state.learning.database.fetchone(
        """SELECT operation, result, reason_code FROM learning_audit
           WHERE operation='EvidenceReplay' ORDER BY rowid DESC LIMIT 1"""
    )
    assert tuple(audit) == ("EvidenceReplay", "rejected", "evidence_event_version_unsupported")


def test_evidence_replay_rejects_tampered_hash_and_preserves_projection(client):
    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    analysis = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
        json={"request_key": "tampered-hash-analysis"},
    )
    assert analysis.status_code == 200
    before = client.get("/api/learning/evidence-claims").json()

    database = client.app.state.learning.database
    remove_evidence_event_guards(database)
    event = database.fetchone(
        "SELECT id FROM learning_evidence_event ORDER BY created_at LIMIT 1"
    )
    with database.transaction() as connection:
        connection.execute(
            "UPDATE learning_evidence_event SET event_hash=? WHERE id=?",
            ("0" * 64, event["id"]),
        )

    response = client.post("/api/learning/evidence-replay")
    assert response.status_code == 409
    assert response.json()["detail"]["kind"] == "evidence_event_integrity_failed"
    assert client.get("/api/learning/evidence-claims").json() == before


def test_evidence_replay_rejects_unknown_event_type_after_rehash(client):
    from app.evidence_events import _event_hash

    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    analysis = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
        json={"request_key": "unknown-type-analysis"},
    )
    assert analysis.status_code == 200
    before = client.get("/api/learning/evidence-claims").json()

    database = client.app.state.learning.database
    remove_evidence_event_guards(database)
    row = dict(
        database.fetchone(
            "SELECT * FROM learning_evidence_event ORDER BY created_at LIMIT 1"
        )
    )
    row["event_type"] = "claim.unknown_future_type"
    with database.transaction() as connection:
        connection.execute(
            "UPDATE learning_evidence_event SET event_type=?, event_hash=? WHERE id=?",
            (row["event_type"], _event_hash(row), row["id"]),
        )

    response = client.post("/api/learning/evidence-replay")
    assert response.status_code == 409
    assert response.json()["detail"]["kind"] == "evidence_event_type_unsupported"
    assert client.get("/api/learning/evidence-claims").json() == before


def test_evidence_event_append_rejects_unknown_event_type(client):
    authorize(client)
    assert client.get("/api/learning/state").status_code == 200
    service = client.app.state.evidence_events
    owner_id = client.app.state.learning.database.fetchone(
        "SELECT id FROM local_identity LIMIT 1"
    )["id"]
    with pytest.raises(DomainError, match="evidence_event_type_unsupported"):
        service.append(
            owner_id,
            "claim",
            "unsupported-type-claim",
            "claim.unknown_future_type",
            {"id": "unsupported-type-claim"},
        )
    assert client.app.state.learning.database.fetchone(
        "SELECT 1 FROM learning_evidence_event WHERE aggregate_id='unsupported-type-claim'"
    ) is None


def test_evidence_event_table_is_append_only(client):
    authorize(client)
    assert client.get("/api/learning/state").status_code == 200
    database = client.app.state.learning.database
    owner_id = database.fetchone("SELECT id FROM local_identity LIMIT 1")["id"]
    event = client.app.state.evidence_events.append(
        owner_id,
        "claim",
        "append-only-claim",
        "claim.created",
        {
            "id": "append-only-claim",
            "artifact_id": "append-only-artifact",
            "content_version": 1,
            "fact_event_id": "append-only-fact-event",
            "criterion_id": "append-only-criterion",
            "dimension_id": "append-only-dimension",
            "stance": "supports",
            "status": "candidate",
            "source": "ai_analysis",
            "statement": "append-only test",
            "verification_method": "semantic_review",
            "evidence_condition": "independent",
            "scope": "append-only-test",
            "analysis_run_id": "append-only-run",
            "created_at": "2026-09-10T00:00:00Z",
        },
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with database.transaction() as connection:
            connection.execute(
                "UPDATE learning_evidence_event SET schema_version=999 WHERE id=?",
                (event["id"],),
            )


def test_evidence_replay_rejects_invalid_payload_after_rehash_and_preserves_projection(client):
    from app.evidence_events import _event_hash

    authorize(client)
    created = create_standard_chain(client)
    client.app.state.evidence.semantic_analyzer = None
    analysis = client.post(
        f"/api/learning/artifacts/{created['artifact']['id']}/analysis",
        json={"request_key": "invalid-payload-analysis"},
    )
    assert analysis.status_code == 200
    before = client.get("/api/learning/evidence-claims").json()

    database = client.app.state.learning.database
    remove_evidence_event_guards(database)
    row = dict(database.fetchone("SELECT * FROM learning_evidence_event ORDER BY created_at LIMIT 1"))
    row["payload_json"] = '{"id":"missing-required-fields"}'
    with database.transaction() as connection:
        connection.execute(
            "UPDATE learning_evidence_event SET payload_json=?, event_hash=? WHERE id=?",
            (row["payload_json"], _event_hash(row), row["id"]),
        )

    response = client.post("/api/learning/evidence-replay")
    assert response.status_code == 409
    assert response.json()["detail"]["kind"] == "evidence_event_payload_invalid"
    assert client.get("/api/learning/evidence-claims").json() == before
    audit = client.app.state.learning.database.fetchone(
        """SELECT operation, result, reason_code FROM learning_audit
           WHERE operation='EvidenceReplay' ORDER BY rowid DESC LIMIT 1"""
    )
    assert tuple(audit) == ("EvidenceReplay", "rejected", "evidence_event_payload_invalid")
