-- Derived learning state is an interpretation projection, never a fact source.
CREATE TABLE learning_derived_state (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    outcome_id TEXT NOT NULL,
    criterion_id TEXT NOT NULL,
    dimension_id TEXT NOT NULL CHECK(length(trim(dimension_id)) > 0),
    status TEXT NOT NULL CHECK(status IN (
        'awaiting_evidence',
        'pending_review',
        'insufficient_evidence',
        'partially_supported',
        'supported',
        'contradicted'
    )),
    reason_code TEXT NOT NULL CHECK(length(trim(reason_code)) > 0),
    standard_version INTEGER NOT NULL CHECK(standard_version > 0),
    calculation_version INTEGER NOT NULL CHECK(calculation_version > 0),
    participating_claim_ids_json TEXT NOT NULL CHECK(json_valid(participating_claim_ids_json) AND json_type(participating_claim_ids_json) = 'array'),
    excluded_claim_ids_json TEXT NOT NULL CHECK(json_valid(excluded_claim_ids_json) AND json_type(excluded_claim_ids_json) = 'array'),
    excluded_claim_reasons_json TEXT NOT NULL CHECK(json_valid(excluded_claim_reasons_json) AND json_type(excluded_claim_reasons_json) = 'array'),
    calculated_at TEXT NOT NULL,
    UNIQUE(owner_id, criterion_id, dimension_id),
    FOREIGN KEY(owner_id, criterion_id) REFERENCES learning_criterion_version(owner_id, id),
    FOREIGN KEY(owner_id, outcome_id) REFERENCES learning_outcome(owner_id, id)
);
CREATE INDEX learning_derived_state_owner
    ON learning_derived_state(owner_id, criterion_id, dimension_id);

CREATE TABLE learning_derived_state_history (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    outcome_id TEXT NOT NULL,
    criterion_id TEXT NOT NULL,
    dimension_id TEXT NOT NULL CHECK(length(trim(dimension_id)) > 0),
    status TEXT NOT NULL CHECK(status IN (
        'awaiting_evidence',
        'pending_review',
        'insufficient_evidence',
        'partially_supported',
        'supported',
        'contradicted'
    )),
    reason_code TEXT NOT NULL CHECK(length(trim(reason_code)) > 0),
    standard_version INTEGER NOT NULL CHECK(standard_version > 0),
    calculation_version INTEGER NOT NULL CHECK(calculation_version > 0),
    participating_claim_ids_json TEXT NOT NULL CHECK(json_valid(participating_claim_ids_json) AND json_type(participating_claim_ids_json) = 'array'),
    excluded_claim_ids_json TEXT NOT NULL CHECK(json_valid(excluded_claim_ids_json) AND json_type(excluded_claim_ids_json) = 'array'),
    excluded_claim_reasons_json TEXT NOT NULL CHECK(json_valid(excluded_claim_reasons_json) AND json_type(excluded_claim_reasons_json) = 'array'),
    calculated_at TEXT NOT NULL,
    UNIQUE(owner_id, criterion_id, dimension_id, calculation_version),
    FOREIGN KEY(owner_id, criterion_id) REFERENCES learning_criterion_version(owner_id, id),
    FOREIGN KEY(owner_id, outcome_id) REFERENCES learning_outcome(owner_id, id)
);
CREATE INDEX learning_derived_state_history_owner
    ON learning_derived_state_history(owner_id, criterion_id, dimension_id, calculation_version);

CREATE TABLE learning_review_action (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    claim_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('adopt', 'question', 'withdraw', 'supersede', 'defer')),
    from_status TEXT NOT NULL CHECK(from_status IN ('candidate', 'adopted', 'questioned', 'withdrawn', 'superseded')),
    to_status TEXT NOT NULL CHECK(to_status IN ('candidate', 'adopted', 'questioned', 'withdrawn', 'superseded')),
    reason TEXT,
    request_key TEXT NOT NULL CHECK(length(trim(request_key)) > 0),
    created_at TEXT NOT NULL,
    UNIQUE(owner_id, id),
    UNIQUE(owner_id, request_key),
    FOREIGN KEY(owner_id, claim_id) REFERENCES learning_evidence_claim(owner_id, id)
);
CREATE INDEX learning_review_action_owner_claim
    ON learning_review_action(owner_id, claim_id, created_at);
