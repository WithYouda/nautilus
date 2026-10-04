-- Explicit future promises are independent of actual sessions and outcomes.
CREATE TABLE learning_plan_commitment_state (
 owner_id TEXT NOT NULL, plan_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
 current_version_id TEXT, availability_revision INTEGER NOT NULL DEFAULT 0, last_event_id TEXT NOT NULL,
 PRIMARY KEY(owner_id,plan_id), FOREIGN KEY(owner_id,plan_id) REFERENCES learning_plan(owner_id,id)
);
CREATE TABLE learning_commitment_draft (
 id TEXT PRIMARY KEY NOT NULL, owner_id TEXT NOT NULL, plan_id TEXT NOT NULL, revision INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('draft','confirmed','purged')), route_version_id TEXT NOT NULL,
 base_version_id TEXT, input_hash TEXT NOT NULL, source TEXT NOT NULL CHECK(source IN ('manual','ai')),
 run_id TEXT, data_json TEXT NOT NULL CHECK(json_valid(data_json)), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 purged_at TEXT, UNIQUE(owner_id,id), FOREIGN KEY(owner_id,plan_id) REFERENCES learning_plan(owner_id,id)
);
CREATE TABLE learning_commitment_version (
 id TEXT PRIMARY KEY NOT NULL, owner_id TEXT NOT NULL, plan_id TEXT NOT NULL, route_version_id TEXT NOT NULL,
 draft_id TEXT NOT NULL, private_revision INTEGER NOT NULL, source TEXT NOT NULL,
 data_json TEXT NOT NULL CHECK(json_valid(data_json)), created_at TEXT NOT NULL, purged_at TEXT,
 UNIQUE(owner_id,id), FOREIGN KEY(owner_id,plan_id) REFERENCES learning_plan(owner_id,id)
);
CREATE TABLE learning_commitment_item (
 id TEXT PRIMARY KEY NOT NULL, owner_id TEXT NOT NULL, plan_id TEXT NOT NULL, first_version_id TEXT NOT NULL,
 route_version_id TEXT NOT NULL, node_id TEXT NOT NULL, action_id TEXT NOT NULL, delegation_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('planned','started','deferred','skipped')),
 future_due_at TEXT, future_timezone TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(owner_id,id), FOREIGN KEY(owner_id,plan_id) REFERENCES learning_plan(owner_id,id),
 FOREIGN KEY(owner_id,action_id) REFERENCES learning_action(owner_id,id),
 FOREIGN KEY(owner_id,delegation_id) REFERENCES learning_delegation(owner_id,id)
);
CREATE TABLE learning_commitment_execution (
 owner_id TEXT NOT NULL, item_id TEXT NOT NULL, session_id TEXT NOT NULL, version_id TEXT NOT NULL,
 estimate_min_minutes INTEGER, estimate_max_minutes INTEGER, due_at TEXT, availability_revision INTEGER NOT NULL,
 linked_at TEXT NOT NULL, PRIMARY KEY(owner_id,session_id),
 FOREIGN KEY(owner_id,item_id) REFERENCES learning_commitment_item(owner_id,id),
 FOREIGN KEY(owner_id,session_id) REFERENCES learning_session(owner_id,id)
);
CREATE TABLE learning_commitment_availability (
 owner_id TEXT NOT NULL, plan_id TEXT NOT NULL, revision INTEGER NOT NULL,
 data_json TEXT NOT NULL CHECK(json_valid(data_json)), PRIMARY KEY(owner_id,plan_id)
);
CREATE TABLE learning_commitment_run (
 id TEXT PRIMARY KEY NOT NULL, owner_id TEXT NOT NULL, plan_id TEXT NOT NULL, revision INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed','canceled','purged')),
 input_hash TEXT NOT NULL, base_revision INTEGER NOT NULL, provider_snapshot_json TEXT NOT NULL CHECK(json_valid(provider_snapshot_json)),
 draft_id TEXT, reason TEXT, created_at TEXT NOT NULL, finished_at TEXT, purged_at TEXT, UNIQUE(owner_id,id)
);
-- Retain private originals across replay. A purge never restores their bodies.
CREATE TABLE learning_commitment_private (
 owner_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('draft','run','feedback')),
 object_id TEXT NOT NULL, revision INTEGER NOT NULL, event_id TEXT NOT NULL REFERENCES learning_event(event_id),
 content_json TEXT CHECK(content_json IS NULL OR json_valid(content_json)), content_hash TEXT, purged_at TEXT,
 PRIMARY KEY(owner_id,kind,object_id,revision)
);
CREATE TABLE learning_commitment_private_tombstone (
 owner_id TEXT NOT NULL, kind TEXT NOT NULL, object_id TEXT NOT NULL, purged_at TEXT NOT NULL,
 PRIMARY KEY(owner_id,kind,object_id)
);
CREATE TABLE learning_commitment_source (
 owner_id TEXT NOT NULL, kind TEXT NOT NULL, object_id TEXT NOT NULL, revision INTEGER NOT NULL,
 source_kind TEXT NOT NULL, source_id TEXT NOT NULL, source_revision INTEGER NOT NULL,
 PRIMARY KEY(owner_id,kind,object_id,revision,source_kind,source_id,source_revision),
 FOREIGN KEY(owner_id,kind,object_id,revision) REFERENCES learning_commitment_private(owner_id,kind,object_id,revision)
);
CREATE INDEX learning_commitment_source_lookup ON learning_commitment_source(owner_id,source_kind,source_id);
CREATE INDEX learning_commitment_execution_item ON learning_commitment_execution(owner_id,item_id,linked_at);
CREATE INDEX learning_commitment_version_plan ON learning_commitment_version(owner_id,plan_id,created_at);
