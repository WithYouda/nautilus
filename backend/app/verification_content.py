"""Shared verification content boundary for analysis, deletion and replay."""
from __future__ import annotations

import json

from .learning_domain import DomainError


def submission_content(connection, owner_id, submission):
    if submission["purged_at"]:
        raise DomainError("artifact_not_eligible", 409)
    if submission["artifact_id"]:
        raw = connection.execute(
            "SELECT content, purged_at FROM learning_raw_artifact WHERE owner_id=? AND artifact_id=? AND content_version=1",
            (owner_id, submission["artifact_id"]),
        ).fetchone()
        if raw is None or raw["purged_at"] or raw["content"] is None:
            raise DomainError("artifact_not_eligible", 409)
        return json.loads(raw["content"])
    return json.loads(submission["content_json"])


def learner_content(content):
    """Reference material never enters an evidence analyzer."""
    if isinstance(content.get("responses"), dict):
        return "\n\n".join(content["responses"].values())
    return content.get("learner_work", "").strip()


def purge_artifact_copies(connection, owner_id, artifact_id, now):
    submission = connection.execute(
        "SELECT id, verification_id FROM learning_verification_submission WHERE owner_id=? AND artifact_id=?",
        (owner_id, artifact_id),
    ).fetchone()
    if submission is None:
        scrub_evidence_copies(connection, owner_id, artifact_id)
        return
    connection.execute(
        "UPDATE learning_verification_submission SET content_json='{}', purged_at=? WHERE owner_id=? AND id=?",
        (now, owner_id, submission["id"]),
    )
    connection.execute(
        """UPDATE learning_verification_evaluation SET result_json=NULL,
           status=CASE WHEN status='running' THEN 'failed' ELSE status END,
           reason='content_purged', finished_at=COALESCE(finished_at, ?)
           WHERE owner_id=? AND submission_id=?""", (now, owner_id, submission["id"]),
    )
    connection.execute(
        """UPDATE learning_verification SET result_json=NULL, submission_json=NULL
           WHERE owner_id=? AND latest_submission_id=?""", (owner_id, submission["id"]),
    )
    scrub_evidence_copies(connection, owner_id, artifact_id)


def scrub_evidence_copies(connection, owner_id, artifact_id):
    """Erase private quotations while leaving the immutable event chain intact."""
    claim_ids = {row[0] for row in connection.execute(
        "SELECT id FROM learning_evidence_claim WHERE owner_id=? AND artifact_id=?", (owner_id, artifact_id),
    )}
    if not claim_ids:
        return
    for claim_id in claim_ids:
        connection.execute(
            "UPDATE learning_evidence_claim SET statement='内容已彻底删除', scope='artifact', verification_method='redacted', status='invalidated' WHERE owner_id=? AND id=?",
            (owner_id, claim_id),
        )
        connection.execute("UPDATE learning_review_action SET reason=NULL WHERE owner_id=? AND claim_id=?", (owner_id, claim_id))
        connection.execute("UPDATE learning_evidence_follow_up SET note=NULL, status='cancelled' WHERE owner_id=? AND claim_id=?", (owner_id, claim_id))
        connection.execute("UPDATE learning_revisit_item SET status='cancelled' WHERE owner_id=? AND claim_id=?", (owner_id, claim_id))
        connection.execute("UPDATE learning_claim_replacement SET reason='内容已彻底删除' WHERE owner_id=? AND (superseded_claim_id=? OR replacement_claim_id=?)", (owner_id, claim_id, claim_id))
    for row in connection.execute("SELECT id, claim_ids_json FROM learning_batch_review_action WHERE owner_id=?", (owner_id,)).fetchall():
        if claim_ids.intersection(json.loads(row["claim_ids_json"])):
            connection.execute("UPDATE learning_batch_review_action SET reason=NULL WHERE id=?", (row["id"],))
    for row in connection.execute(
        "SELECT event_id, claim_ids_json, purged_at FROM learning_evidence_private_content WHERE owner_id=?",
        (owner_id,),
    ).fetchall():
        if claim_ids.intersection(json.loads(row["claim_ids_json"])):
            # A batch reason is copied to every per-claim review, including claims
            # for other artifacts. Erase those shared copies as well.
            connection.execute(
                """UPDATE learning_review_action SET reason=NULL WHERE owner_id=? AND id IN
                   (SELECT aggregate_id FROM learning_evidence_event WHERE owner_id=? AND id=?)""",
                (owner_id, owner_id, row["event_id"]),
            )
            if row["purged_at"] is None:
                connection.execute(
                    "UPDATE learning_evidence_private_content SET content_json=NULL, purged_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE event_id=?",
                    (row["event_id"],),
                )
