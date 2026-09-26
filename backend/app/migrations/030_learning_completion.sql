-- User-confirmed execution and reported verification are independent facts.
-- Private material/report/review content stays outside the immutable event log.
CREATE TABLE learning_completion (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    action_id TEXT NOT NULL,
    delegation_id TEXT NOT NULL,
    verification_kind TEXT NOT NULL CHECK(verification_kind IN ('unverified','external_material','external_report')),
    request_key TEXT NOT NULL,
    request_fingerprint TEXT,
    content_json TEXT CHECK(content_json IS NULL OR json_valid(content_json)),
    contract_snapshot_json TEXT CHECK(contract_snapshot_json IS NULL OR json_valid(contract_snapshot_json)),
    created_at TEXT NOT NULL,
    purged_at TEXT,
    UNIQUE(owner_id,id),
    UNIQUE(owner_id,delegation_id),
    UNIQUE(owner_id,request_key),
    FOREIGN KEY(owner_id,action_id) REFERENCES learning_action(owner_id,id),
    FOREIGN KEY(owner_id,delegation_id) REFERENCES learning_delegation(owner_id,id)
);

CREATE TABLE learning_completion_review (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL,
    completion_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed')),
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    provider_name TEXT,
    model TEXT,
    reason TEXT,
    user_response TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(owner_id,id),
    UNIQUE(owner_id,completion_id,request_key),
    FOREIGN KEY(owner_id,completion_id) REFERENCES learning_completion(owner_id,id)
);
