-- Optional user-reported effective effort; never infer it from session spans.
CREATE TABLE learning_session_feedback (
 id TEXT PRIMARY KEY NOT NULL, owner_id TEXT NOT NULL, plan_id TEXT, session_id TEXT NOT NULL,
 revision INTEGER NOT NULL CHECK(revision>0), data_json TEXT NOT NULL CHECK(json_valid(data_json)),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, purged_at TEXT, UNIQUE(owner_id,id),
 FOREIGN KEY(owner_id,session_id) REFERENCES learning_session(owner_id,id)
);
CREATE TABLE learning_session_feedback_history (
 owner_id TEXT NOT NULL, session_id TEXT NOT NULL, revision INTEGER NOT NULL,
 data_json TEXT NOT NULL CHECK(json_valid(data_json)), event_id TEXT NOT NULL REFERENCES learning_event(event_id),
 created_at TEXT NOT NULL, PRIMARY KEY(owner_id,session_id,revision)
);
