-- Minimal guided setup for the independent learning domain.
CREATE TABLE learning_goal (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    original_intent TEXT NOT NULL CHECK(length(trim(original_intent)) > 0),
    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('hypothesis', 'active', 'paused', 'completed', 'archived')),
    version INTEGER NOT NULL CHECK(version > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(owner_id, id)
);

CREATE TABLE learning_plan (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    goal_id TEXT,
    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('active', 'paused', 'completed', 'archived')),
    version INTEGER NOT NULL CHECK(version > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(owner_id, id),
    FOREIGN KEY(owner_id, goal_id) REFERENCES learning_goal(owner_id, id)
);

CREATE TABLE learning_module (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    plan_id TEXT NOT NULL,
    parent_module_id TEXT,
    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
    description TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL CHECK(position >= 0),
    status TEXT NOT NULL CHECK(status IN ('active', 'paused', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(owner_id, id),
    FOREIGN KEY(owner_id, plan_id) REFERENCES learning_plan(owner_id, id),
    FOREIGN KEY(owner_id, parent_module_id) REFERENCES learning_module(owner_id, id),
    CHECK(parent_module_id IS NULL OR parent_module_id <> id)
);

CREATE TABLE learning_action_link (
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    action_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    module_id TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY(owner_id, action_id),
    FOREIGN KEY(owner_id, action_id) REFERENCES learning_action(owner_id, id),
    FOREIGN KEY(owner_id, plan_id) REFERENCES learning_plan(owner_id, id),
    FOREIGN KEY(owner_id, module_id) REFERENCES learning_module(owner_id, id)
);

CREATE TABLE learning_setup (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    goal_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    outcome_id TEXT NOT NULL,
    delegation_id TEXT NOT NULL,
    original_intent TEXT NOT NULL CHECK(length(trim(original_intent)) > 0),
    status TEXT NOT NULL CHECK(status = 'confirmed'),
    version INTEGER NOT NULL CHECK(version > 0),
    created_at TEXT NOT NULL,
    UNIQUE(owner_id, id),
    FOREIGN KEY(owner_id, goal_id) REFERENCES learning_goal(owner_id, id),
    FOREIGN KEY(owner_id, plan_id) REFERENCES learning_plan(owner_id, id),
    FOREIGN KEY(owner_id, action_id) REFERENCES learning_action(owner_id, id),
    FOREIGN KEY(owner_id, outcome_id) REFERENCES learning_outcome(owner_id, id),
    FOREIGN KEY(owner_id, delegation_id) REFERENCES learning_delegation(owner_id, id)
);

CREATE INDEX learning_plan_owner_status ON learning_plan(owner_id, status, created_at);
CREATE INDEX learning_action_link_plan ON learning_action_link(owner_id, plan_id, created_at);
