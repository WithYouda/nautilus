-- A verification attempt keeps the assessment prompt separate from teaching chat.
-- Answer keys and submitted material are private server-side data.
CREATE TABLE learning_verification (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    action_id TEXT NOT NULL,
    delegation_id TEXT NOT NULL,
    session_id TEXT,
    mode TEXT NOT NULL CHECK(mode IN ('ai_challenge', 'user_material')),
    request_key TEXT NOT NULL CHECK(length(trim(request_key)) > 0),
    request_fingerprint TEXT NOT NULL CHECK(length(trim(request_fingerprint)) > 0),
    status TEXT NOT NULL CHECK(status IN ('ready', 'submitted', 'passed', 'failed')),
    challenge_json TEXT NOT NULL CHECK(json_valid(challenge_json) AND json_type(challenge_json) = 'object'),
    answer_key_json TEXT NOT NULL CHECK(json_valid(answer_key_json) AND json_type(answer_key_json) = 'object'),
    submission_json TEXT CHECK(submission_json IS NULL OR (json_valid(submission_json) AND json_type(submission_json) = 'object')),
    result_json TEXT CHECK(result_json IS NULL OR (json_valid(result_json) AND json_type(result_json) = 'object')),
    stop_condition_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(stop_condition_confirmed IN (0, 1)),
    stop_condition_met INTEGER CHECK(stop_condition_met IS NULL OR stop_condition_met IN (0, 1)),
    created_at TEXT NOT NULL,
    submitted_at TEXT,
    UNIQUE(owner_id, id),
    UNIQUE(owner_id, request_key),
    FOREIGN KEY(owner_id, action_id) REFERENCES learning_action(owner_id, id),
    FOREIGN KEY(owner_id, delegation_id) REFERENCES learning_delegation(owner_id, id),
    FOREIGN KEY(owner_id, session_id) REFERENCES learning_session(owner_id, id)
);

CREATE INDEX learning_verification_owner_action
    ON learning_verification(owner_id, action_id, created_at DESC);
