-- Optional practice is separate from verification, completion and ability state.
CREATE TABLE learning_practice (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL,
    verification_id TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    evaluation_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    operation TEXT NOT NULL CHECK(operation IN ('exercise','recheck')),
    requested_kind TEXT NOT NULL CHECK(requested_kind IN ('redo','new_situation')),
    request_key TEXT NOT NULL,
    request_fingerprint TEXT,
    request_json TEXT CHECK(request_json IS NULL OR json_valid(request_json)),
    contract_snapshot_json TEXT CHECK(contract_snapshot_json IS NULL OR json_valid(contract_snapshot_json)),
    content_json TEXT CHECK(content_json IS NULL OR json_valid(content_json)),
    status TEXT NOT NULL CHECK(status IN ('running','ready','reviewed','started','skipped','failed','purged')),
    reason TEXT,
    provider_name TEXT,
    model TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    started_at TEXT,
    purged_at TEXT,
    UNIQUE(owner_id,id),
    UNIQUE(owner_id,request_key),
    FOREIGN KEY(owner_id,verification_id) REFERENCES learning_verification(owner_id,id),
    FOREIGN KEY(owner_id,submission_id) REFERENCES learning_verification_submission(owner_id,id),
    FOREIGN KEY(evaluation_id) REFERENCES learning_verification_evaluation(id)
);
CREATE INDEX learning_practice_source ON learning_practice(owner_id,submission_id,evaluation_id,question_id);
CREATE TABLE learning_practice_attempt (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL,
    practice_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    request_fingerprint TEXT,
    answer TEXT,
    condition_json TEXT CHECK(condition_json IS NULL OR json_valid(condition_json)),
    created_at TEXT NOT NULL,
    purged_at TEXT,
    UNIQUE(owner_id,id),
    UNIQUE(owner_id,practice_id,request_key),
    FOREIGN KEY(owner_id,practice_id) REFERENCES learning_practice(owner_id,id)
);
CREATE TABLE learning_practice_run (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL,
    practice_id TEXT NOT NULL,
    attempt_id TEXT,
    request_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('hint','evaluation')),
    status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed')),
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    reason TEXT,
    provider_name TEXT,
    model TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    displayed_at TEXT,
    purged_at TEXT,
    UNIQUE(owner_id,practice_id,request_key),
    FOREIGN KEY(owner_id,practice_id) REFERENCES learning_practice(owner_id,id),
    FOREIGN KEY(owner_id,attempt_id) REFERENCES learning_practice_attempt(owner_id,id)
);
-- Source erasure wins over pending generation and clears all private derivatives.
CREATE TRIGGER learning_practice_source_erased AFTER UPDATE OF purged_at ON learning_verification_submission
WHEN NEW.purged_at IS NOT NULL
BEGIN
    UPDATE learning_practice SET purged_at=NEW.purged_at WHERE owner_id=NEW.owner_id AND submission_id=NEW.id;
END;
CREATE TRIGGER learning_practice_erased AFTER UPDATE OF purged_at ON learning_practice
WHEN NEW.purged_at IS NOT NULL
BEGIN
    UPDATE learning_practice SET request_json=NULL,request_fingerprint=NULL,contract_snapshot_json=NULL,
        content_json=NULL,provider_name=NULL,model=NULL,status='purged',reason='content_purged' WHERE id=NEW.id;
    UPDATE learning_practice_attempt SET answer=NULL,condition_json=NULL,request_fingerprint=NULL,purged_at=NEW.purged_at
        WHERE owner_id=NEW.owner_id AND practice_id=NEW.id;
    UPDATE learning_practice_run SET result_json=NULL,provider_name=NULL,model=NULL,displayed_at=NULL,
        status='failed',reason='content_purged',finished_at=COALESCE(finished_at,NEW.purged_at),purged_at=NEW.purged_at
        WHERE owner_id=NEW.owner_id AND practice_id=NEW.id;
END;
