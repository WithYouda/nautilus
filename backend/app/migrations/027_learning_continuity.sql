-- Stable review/recommendation linkage. No learning text or model output.
CREATE TABLE learning_return_review (
 id TEXT PRIMARY KEY NOT NULL,
 owner_id TEXT NOT NULL REFERENCES local_identity(id),
 context_key TEXT NOT NULL,
 position_session_id TEXT,
 action_id TEXT,
 delegation_id TEXT,
 verification_id TEXT,
 kind TEXT NOT NULL,
 reason_code TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(owner_id, context_key), UNIQUE(owner_id, id)
);
CREATE TABLE learning_usage_event (
 id TEXT PRIMARY KEY NOT NULL,
 owner_id TEXT NOT NULL REFERENCES local_identity(id),
 review_id TEXT,
 kind TEXT NOT NULL CHECK(kind IN ('review_card_shown','resume_candidate_presented','continue','choose_other','stop_for_now','evidence_viewed','started','entered','corrected','switched','completed','setup_ai','setup_manual','setup_modified','first_artifact')),
 action_id TEXT,
 delegation_id TEXT,
 session_id TEXT,
 request_key TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(owner_id, request_key),
 FOREIGN KEY(owner_id, review_id) REFERENCES learning_return_review(owner_id, id)
);
CREATE INDEX learning_usage_review ON learning_usage_event(owner_id, review_id, kind);
