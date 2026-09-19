-- Evidence-gate follow-ups. They arrange review or verification; they do not
-- mutate the candidate claim until a later explicit review command.
CREATE TABLE learning_evidence_follow_up (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    claim_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('human_review', 'supplemental_verification')),
    status TEXT NOT NULL CHECK(status IN ('pending', 'completed', 'cancelled')),
    request_key TEXT NOT NULL CHECK(length(trim(request_key)) > 0),
    note TEXT,
    due_at TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    UNIQUE(owner_id, id),
    UNIQUE(owner_id, request_key),
    FOREIGN KEY(owner_id, claim_id) REFERENCES learning_evidence_claim(owner_id, id)
);
CREATE INDEX learning_evidence_follow_up_owner_status
    ON learning_evidence_follow_up(owner_id, status, kind, created_at);
CREATE INDEX learning_evidence_follow_up_claim
    ON learning_evidence_follow_up(owner_id, claim_id, kind, status);
