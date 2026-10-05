-- Bounded coach proposals reference existing facts; they never become learning facts.
CREATE TABLE learning_coach_settings (
 owner_id TEXT PRIMARY KEY REFERENCES local_identity(id), revision INTEGER NOT NULL,
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), timezone TEXT NOT NULL,
 max_calls_per_session INTEGER NOT NULL, max_calls_per_day INTEGER NOT NULL,
 cooldown_minutes INTEGER NOT NULL CHECK(cooldown_minutes>=30), enabled_position INTEGER NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE learning_coach_signal (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, revision INTEGER NOT NULL,
 kind TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','excluded')),
 plan_id TEXT, action_id TEXT NOT NULL, delegation_id TEXT, session_id TEXT,
 answer_kind TEXT NOT NULL CHECK(answer_kind IN ('conversation','discussion')),
 answer_id TEXT NOT NULL, source_id TEXT NOT NULL, source_revision INTEGER NOT NULL,
 start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(owner_id,id),
 UNIQUE(owner_id,answer_kind,answer_id), FOREIGN KEY(owner_id,action_id) REFERENCES learning_action(owner_id,id)
);
CREATE TABLE learning_coach_run (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, revision INTEGER NOT NULL,
 scope TEXT NOT NULL CHECK(scope IN ('global','plan')), plan_id TEXT,
 trigger TEXT NOT NULL, automatic INTEGER NOT NULL CHECK(automatic IN (0,1)),
 status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','canceled','purged')),
 batch_key TEXT NOT NULL, input_hash TEXT NOT NULL, settings_revision INTEGER NOT NULL,
 provider_snapshot_json TEXT NOT NULL, session_ids_json TEXT NOT NULL,
 reserved_day TEXT NOT NULL, sent_at TEXT, retry_run_id TEXT, reason TEXT,
 created_at TEXT NOT NULL, finished_at TEXT, purged_at TEXT,
 permission_candidate_id TEXT, permission_request_id TEXT, UNIQUE(owner_id,id)
);
CREATE UNIQUE INDEX learning_coach_one_active ON learning_coach_run(owner_id) WHERE status IN ('queued','running');
CREATE TABLE learning_coach_consumed (
 owner_id TEXT NOT NULL, source_key TEXT NOT NULL, run_id TEXT NOT NULL,
 PRIMARY KEY(owner_id,source_key), FOREIGN KEY(owner_id,run_id) REFERENCES learning_coach_run(owner_id,id)
);
CREATE TABLE learning_coach_run_source (
 owner_id TEXT NOT NULL, run_id TEXT NOT NULL, source_key TEXT NOT NULL,
 source_kind TEXT NOT NULL, source_id TEXT NOT NULL, source_revision INTEGER,
 PRIMARY KEY(owner_id,run_id,source_key), FOREIGN KEY(owner_id,run_id) REFERENCES learning_coach_run(owner_id,id)
);
CREATE TABLE learning_coach_candidate (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, run_id TEXT NOT NULL, revision INTEGER NOT NULL,
 kind TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','accepted','rejected','ignored')),
 private_revision INTEGER NOT NULL, source_keys_json TEXT NOT NULL, target_json TEXT NOT NULL,
 created_at TEXT NOT NULL, decided_at TEXT, UNIQUE(owner_id,id),
 FOREIGN KEY(owner_id,run_id) REFERENCES learning_coach_run(owner_id,id)
);
CREATE TABLE learning_coach_decision (
 owner_id TEXT NOT NULL, candidate_id TEXT NOT NULL, revision INTEGER NOT NULL,
 operation TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(owner_id,candidate_id,revision), FOREIGN KEY(owner_id,candidate_id) REFERENCES learning_coach_candidate(owner_id,id)
);
CREATE TABLE learning_coach_private (
 owner_id TEXT NOT NULL, run_id TEXT NOT NULL, revision INTEGER NOT NULL, event_id TEXT NOT NULL,
 content_json TEXT, content_hash TEXT, purged_at TEXT,
 PRIMARY KEY(owner_id,run_id,revision)
);
CREATE TABLE learning_coach_tombstone (
 owner_id TEXT NOT NULL, run_id TEXT NOT NULL, purged_at TEXT NOT NULL,
 PRIMARY KEY(owner_id,run_id)
);
