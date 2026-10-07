-- Operational identities and notification receipts, never learning facts.
CREATE TABLE learning_coach_conversation (
 owner_id TEXT NOT NULL REFERENCES local_identity(id), conversation_id TEXT NOT NULL,
 role_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, purged_at TEXT, PRIMARY KEY(owner_id,conversation_id)
);
CREATE TABLE learning_coach_request (
 owner_id TEXT NOT NULL, scope TEXT NOT NULL, request_key TEXT NOT NULL,
 fingerprint TEXT NOT NULL, result_id TEXT, created_at TEXT NOT NULL,
 PRIMARY KEY(owner_id,scope,request_key)
);
CREATE TABLE learning_coach_reminder_settings (
 owner_id TEXT PRIMARY KEY REFERENCES local_identity(id), revision INTEGER NOT NULL,
 settings_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE learning_coach_reminder (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES local_identity(id),
 occurrence_key TEXT NOT NULL, stage TEXT NOT NULL, revision INTEGER NOT NULL,
 status TEXT NOT NULL, scheduled_at TEXT NOT NULL, dispatched_at TEXT,
 source_json TEXT NOT NULL, source_revision TEXT NOT NULL,
 settings_revision INTEGER NOT NULL, reason TEXT, created_at TEXT NOT NULL,
 UNIQUE(owner_id,occurrence_key,stage)
);
CREATE INDEX learning_coach_reminder_owner ON learning_coach_reminder(owner_id,scheduled_at);
CREATE TABLE learning_coach_reminder_budget (
 owner_id TEXT PRIMARY KEY, window_start TEXT NOT NULL, window_end TEXT NOT NULL,
 used_count INTEGER NOT NULL
);
