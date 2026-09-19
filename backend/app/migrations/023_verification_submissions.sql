-- Submission content is append-only; model attempts and final confirmation are separate.
ALTER TABLE learning_verification ADD COLUMN contract_snapshot_json TEXT;
ALTER TABLE learning_verification ADD COLUMN latest_submission_id TEXT;

UPDATE learning_verification
SET contract_snapshot_json = (
    SELECT json_object('version', c.version, 'boundaries', c.boundaries,
                       'stop_conditions', c.stop_conditions, 'criterion_id', d.criterion_id)
    FROM learning_delegation d JOIN learning_contract_version c
      ON c.owner_id=d.owner_id AND c.delegation_id=d.id AND c.version=d.contract_version
    WHERE d.owner_id=learning_verification.owner_id AND d.id=learning_verification.delegation_id
);

CREATE TABLE learning_verification_submission (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL,
    verification_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    content_json TEXT NOT NULL CHECK(json_valid(content_json)),
    created_at TEXT NOT NULL,
    UNIQUE(owner_id, id),
    UNIQUE(owner_id, verification_id, request_key),
    FOREIGN KEY(owner_id, verification_id) REFERENCES learning_verification(owner_id, id)
);

CREATE TABLE learning_verification_evaluation (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'succeeded', 'failed')),
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    provider_snapshot_json TEXT CHECK(provider_snapshot_json IS NULL OR json_valid(provider_snapshot_json)),
    reason TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(owner_id, submission_id, request_key),
    FOREIGN KEY(owner_id, submission_id) REFERENCES learning_verification_submission(owner_id, id)
);

-- Preserve the last available 022 submission; overwritten historical answers cannot be recovered.
INSERT INTO learning_verification_submission
SELECT 'legacy:' || id, owner_id, id, 'legacy', request_fingerprint,
       submission_json, COALESCE(submitted_at, created_at)
FROM learning_verification WHERE submission_json IS NOT NULL;

UPDATE learning_verification SET latest_submission_id='legacy:' || id
WHERE submission_json IS NOT NULL;

INSERT INTO learning_verification_evaluation
SELECT 'legacy:' || id, owner_id, 'legacy:' || id, 'legacy', 'succeeded', result_json,
       NULL, NULL, COALESCE(submitted_at, created_at), COALESCE(submitted_at, created_at)
FROM learning_verification WHERE submission_json IS NOT NULL AND result_json IS NOT NULL;

-- Conversation identifiers refer to the separate chat database; ownership is checked by the service.
CREATE TABLE learning_room_conversation (
    owner_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    selected_at TEXT NOT NULL,
    PRIMARY KEY(owner_id, conversation_id),
    FOREIGN KEY(owner_id, session_id) REFERENCES learning_session(owner_id, id)
);
