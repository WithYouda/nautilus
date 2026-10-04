-- Long-term route decisions are independent of recent learning sessions.
CREATE TABLE learning_plan_path_state (
    owner_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision>0),
    adopted_version_id TEXT,
    current_node_id TEXT,
    last_decision_id TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused')),
    PRIMARY KEY(owner_id,plan_id),
    FOREIGN KEY(owner_id,plan_id) REFERENCES learning_plan(owner_id,id)
);
CREATE TABLE learning_path_draft (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision>0),
    status TEXT NOT NULL CHECK(status IN ('draft','confirmed','purged')),
    intent TEXT NOT NULL,
    base_version_id TEXT,
    base_node_id TEXT,
    organization_revision INTEGER NOT NULL,
    reference_hash TEXT NOT NULL,
    data_json TEXT NOT NULL CHECK(json_valid(data_json)),
    source_version_id TEXT,
    restore_version_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    purged_at TEXT,
    UNIQUE(owner_id,id),
    FOREIGN KEY(owner_id,plan_id) REFERENCES learning_plan(owner_id,id)
);
CREATE TABLE learning_path_private (
    owner_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    event_id TEXT NOT NULL REFERENCES learning_event(event_id),
    content_json TEXT CHECK(content_json IS NULL OR json_valid(content_json)),
    content_hash TEXT,
    purged_at TEXT,
    PRIMARY KEY(owner_id,object_id,revision)
);
CREATE TABLE learning_path_private_tombstone (
    owner_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    purged_at TEXT NOT NULL,
    PRIMARY KEY(owner_id,object_id)
);
CREATE TABLE learning_path_version (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    route_id TEXT NOT NULL,
    previous_version_id TEXT,
    parent_version_id TEXT,
    branch_node_id TEXT,
    data_json TEXT NOT NULL CHECK(json_valid(data_json)),
    private_object_id TEXT NOT NULL,
    private_revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    purged_at TEXT,
    UNIQUE(owner_id,id),
    FOREIGN KEY(owner_id,plan_id) REFERENCES learning_plan(owner_id,id),
    FOREIGN KEY(owner_id,private_object_id,private_revision)
        REFERENCES learning_path_private(owner_id,object_id,revision)
);
CREATE TABLE learning_path_decision (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    previous_version_id TEXT,
    previous_node_id TEXT,
    node_id TEXT NOT NULL,
    intent TEXT NOT NULL,
    draft_id TEXT NOT NULL,
    event_id TEXT NOT NULL REFERENCES learning_event(event_id),
    created_at TEXT NOT NULL,
    UNIQUE(owner_id,id),
    FOREIGN KEY(owner_id,plan_id) REFERENCES learning_plan(owner_id,id),
    FOREIGN KEY(owner_id,version_id) REFERENCES learning_path_version(owner_id,id)
);
CREATE TABLE learning_path_checkpoint (
    owner_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    action_id TEXT,
    delegation_id TEXT,
    session_id TEXT,
    anchor_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(anchor_json)),
    event_id TEXT NOT NULL REFERENCES learning_event(event_id),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(owner_id,plan_id,version_id),
    FOREIGN KEY(owner_id,version_id) REFERENCES learning_path_version(owner_id,id)
);
CREATE INDEX learning_path_version_plan ON learning_path_version(owner_id,plan_id,created_at);
CREATE INDEX learning_path_draft_plan ON learning_path_draft(owner_id,plan_id,status);
