-- D1 preserves existing outcome identities and immutable standard/evidence versions.
CREATE TABLE learning_outcome_kind (
    owner_id TEXT NOT NULL,
    outcome_id TEXT PRIMARY KEY NOT NULL,
    kind TEXT NOT NULL CHECK(kind='composite'),
    FOREIGN KEY(owner_id,outcome_id) REFERENCES learning_outcome(owner_id,id)
);
CREATE TABLE learning_outcome_relation (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    source_outcome_id TEXT NOT NULL,
    target_outcome_id TEXT NOT NULL,
    relation_type TEXT NOT NULL CHECK(relation_type IN ('contains','prerequisite','equivalent','overlap')),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('manual','ai_accepted')),
    candidate_id TEXT,
    revision INTEGER NOT NULL CHECK(revision>0),
    status TEXT NOT NULL CHECK(status IN ('active','revoked','purged')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    purged_at TEXT,
    UNIQUE(owner_id,id),
    CHECK(source_outcome_id<>target_outcome_id),
    FOREIGN KEY(owner_id,source_outcome_id) REFERENCES learning_outcome(owner_id,id),
    FOREIGN KEY(owner_id,target_outcome_id) REFERENCES learning_outcome(owner_id,id)
);
CREATE TABLE learning_outcome_relation_history (
    owner_id TEXT NOT NULL,
    relation_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    source_outcome_id TEXT NOT NULL,
    target_outcome_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    candidate_id TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    event_id TEXT NOT NULL REFERENCES learning_event(event_id),
    PRIMARY KEY(owner_id,relation_id,revision)
);
CREATE TABLE learning_graph_run (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    revision INTEGER NOT NULL CHECK(revision>0),
    status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed','canceled','purged')),
    reason TEXT,
    outcome_ids_json TEXT NOT NULL CHECK(json_valid(outcome_ids_json)),
    provider_snapshot_json TEXT NOT NULL CHECK(json_valid(provider_snapshot_json)),
    created_at TEXT NOT NULL,
    finished_at TEXT,
    purged_at TEXT,
    UNIQUE(owner_id,id)
);
CREATE TABLE learning_graph_candidate (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision>0),
    status TEXT NOT NULL CHECK(status IN ('pending','accepted','rejected','purged')),
    source_outcome_id TEXT NOT NULL,
    target_outcome_id TEXT NOT NULL,
    relation_type TEXT NOT NULL CHECK(relation_type IN ('contains','prerequisite','equivalent','overlap')),
    relation_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    purged_at TEXT,
    UNIQUE(owner_id,id),
    FOREIGN KEY(owner_id,run_id) REFERENCES learning_graph_run(owner_id,id),
    FOREIGN KEY(owner_id,source_outcome_id) REFERENCES learning_outcome(owner_id,id),
    FOREIGN KEY(owner_id,target_outcome_id) REFERENCES learning_outcome(owner_id,id)
);
-- Immutable original private payloads survive projection rebuilding; only erasure changes them.
CREATE TABLE learning_graph_private (
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    kind TEXT NOT NULL CHECK(kind IN ('relation','run','candidate')),
    object_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    content_json TEXT CHECK(content_json IS NULL OR json_valid(content_json)),
    content_hash TEXT,
    purged_at TEXT,
    PRIMARY KEY(owner_id,kind,object_id,revision)
);
CREATE TABLE learning_graph_source (
    owner_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    object_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    source_kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_version INTEGER NOT NULL,
    PRIMARY KEY(owner_id,kind,object_id,revision,source_kind,source_id,source_version),
    FOREIGN KEY(owner_id,kind,object_id,revision) REFERENCES learning_graph_private(owner_id,kind,object_id,revision)
);
CREATE INDEX learning_graph_source_lookup ON learning_graph_source(owner_id,source_kind,source_id);
