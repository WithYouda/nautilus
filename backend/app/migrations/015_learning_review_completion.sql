-- Task 6.1: batch review, explicit replacements, and revisit queue.
CREATE TABLE learning_batch_review_action (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    action TEXT NOT NULL CHECK(action IN ('adopt', 'question', 'withdraw', 'defer')),
    reason TEXT,
    request_key TEXT NOT NULL CHECK(length(trim(request_key)) > 0),
    claim_ids_json TEXT NOT NULL CHECK(json_valid(claim_ids_json) AND json_type(claim_ids_json) = 'array'),
    created_at TEXT NOT NULL,
    UNIQUE(owner_id, id),
    UNIQUE(owner_id, request_key)
);

CREATE TABLE learning_claim_replacement (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    superseded_claim_id TEXT NOT NULL,
    replacement_claim_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
    created_at TEXT NOT NULL,
    UNIQUE(owner_id, superseded_claim_id, replacement_claim_id),
    FOREIGN KEY(owner_id, superseded_claim_id)
        REFERENCES learning_evidence_claim(owner_id, id),
    FOREIGN KEY(owner_id, replacement_claim_id)
        REFERENCES learning_evidence_claim(owner_id, id)
);

CREATE TABLE learning_revisit_item (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    source_kind TEXT NOT NULL CHECK(source_kind IN (
        'questioned_claim',
        'insufficient_state',
        'supplemental_verification'
    )),
    source_id TEXT NOT NULL CHECK(length(trim(source_id)) > 0),
    claim_id TEXT,
    criterion_id TEXT NOT NULL,
    dimension_id TEXT,
    reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
    due_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'completed', 'cancelled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(owner_id, source_kind, source_id),
    FOREIGN KEY(owner_id, claim_id) REFERENCES learning_evidence_claim(owner_id, id),
    FOREIGN KEY(owner_id, criterion_id) REFERENCES learning_criterion_version(owner_id, id)
);
CREATE INDEX learning_revisit_item_owner_status
    ON learning_revisit_item(owner_id, status, due_at);
CREATE INDEX learning_revisit_item_criterion
    ON learning_revisit_item(owner_id, criterion_id, dimension_id);
ALTER TABLE learning_review_action
    ADD COLUMN replacement_claim_id TEXT;
