-- D2 organization is an independent stream; plan.version is not its CAS.
CREATE TABLE learning_plan_organization (
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    plan_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    baseline_position INTEGER NOT NULL CHECK(baseline_position >= 0),
    last_event_id TEXT NOT NULL REFERENCES learning_event(event_id),
    PRIMARY KEY(owner_id,plan_id),
    FOREIGN KEY(owner_id,plan_id) REFERENCES learning_plan(owner_id,id)
);
CREATE TABLE learning_plan_child (
    owner_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('module','task')),
    child_id TEXT NOT NULL,
    parent_module_id TEXT,
    position INTEGER NOT NULL CHECK(position >= 0),
    PRIMARY KEY(owner_id,plan_id,kind,child_id),
    FOREIGN KEY(owner_id,plan_id) REFERENCES learning_plan(owner_id,id),
    FOREIGN KEY(owner_id,parent_module_id) REFERENCES learning_module(owner_id,id)
);
CREATE INDEX learning_plan_child_parent ON learning_plan_child(owner_id,plan_id,parent_module_id,position);
-- Retained originals and tombstones are deliberately outside replay projections.
CREATE TABLE learning_plan_private (
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    kind TEXT NOT NULL CHECK(kind IN ('plan','module')),
    object_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    event_id TEXT NOT NULL REFERENCES learning_event(event_id),
    content_json TEXT CHECK(content_json IS NULL OR json_valid(content_json)),
    content_hash TEXT,
    purged_at TEXT,
    PRIMARY KEY(owner_id,kind,object_id,revision)
);
CREATE TABLE learning_plan_private_tombstone (
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    kind TEXT NOT NULL CHECK(kind IN ('plan','module')),
    object_id TEXT NOT NULL,
    purged_at TEXT NOT NULL,
    PRIMARY KEY(owner_id,kind,object_id)
);
