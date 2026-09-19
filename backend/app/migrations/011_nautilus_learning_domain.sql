-- Independent learning baseline. Authentication is infrastructure, not legacy learning data.
CREATE TABLE local_identity (
    id TEXT PRIMARY KEY NOT NULL,
    device_id TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE sessions (
    id TEXT PRIMARY KEY NOT NULL,
    identity_id TEXT NOT NULL REFERENCES local_identity(id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE TABLE learning_outcome (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    object_description TEXT NOT NULL CHECK(length(trim(object_description)) > 0),
    behavior TEXT NOT NULL CHECK(length(trim(behavior)) > 0),
    context_key TEXT NOT NULL CHECK(length(trim(context_key)) > 0),
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(owner_id, id)
);
CREATE TABLE learning_standard_package (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    title TEXT NOT NULL,
    source TEXT NOT NULL CHECK(length(trim(source)) > 0),
    context_key TEXT NOT NULL CHECK(length(trim(context_key)) > 0),
    UNIQUE(owner_id, id)
);
CREATE TABLE learning_criterion_version (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    package_id TEXT NOT NULL,
    outcome_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version > 0),
    source TEXT NOT NULL CHECK(length(trim(source)) > 0),
    context_key TEXT NOT NULL CHECK(length(trim(context_key)) > 0),
    recipe_json TEXT NOT NULL CHECK(json_valid(recipe_json) AND json_type(recipe_json) = 'object'),
    review_status TEXT NOT NULL CHECK(review_status IN ('candidate', 'approved')),
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    CHECK(review_status != 'approved' OR (length(trim(reviewed_by)) > 0 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL)),
    UNIQUE(owner_id, id),
    UNIQUE(owner_id, package_id, outcome_id, version),
    FOREIGN KEY(owner_id, package_id) REFERENCES learning_standard_package(owner_id, id),
    FOREIGN KEY(owner_id, outcome_id) REFERENCES learning_outcome(owner_id, id)
);
CREATE TRIGGER learning_criterion_immutable BEFORE UPDATE ON learning_criterion_version
BEGIN SELECT RAISE(ABORT, 'criterion version is immutable'); END;
CREATE TRIGGER learning_criterion_no_delete BEFORE DELETE ON learning_criterion_version
BEGIN SELECT RAISE(ABORT, 'criterion version is immutable'); END;
CREATE TABLE learning_criterion_availability (
    owner_id TEXT NOT NULL,
    criterion_id TEXT PRIMARY KEY NOT NULL,
    reason TEXT NOT NULL CHECK(reason IN ('retired', 'invalidated')),
    changed_at TEXT NOT NULL,
    FOREIGN KEY(owner_id, criterion_id) REFERENCES learning_criterion_version(owner_id, id)
);

CREATE TABLE learning_action (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 300),
    context_key TEXT NOT NULL CHECK(length(trim(context_key)) > 0),
    status TEXT NOT NULL CHECK(status IN ('open', 'completed', 'cancelled')),
    version INTEGER NOT NULL CHECK(version > 0),
    created_at TEXT NOT NULL,
    UNIQUE(owner_id, id)
);
CREATE TABLE learning_delegation (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    action_id TEXT NOT NULL,
    outcome_id TEXT NOT NULL,
    criterion_id TEXT,
    contract_version INTEGER NOT NULL CHECK(contract_version > 0),
    status TEXT NOT NULL CHECK(status IN ('ready', 'active', 'paused', 'completed', 'cancelled')),
    version INTEGER NOT NULL CHECK(version > 0),
    created_at TEXT NOT NULL,
    UNIQUE(owner_id, id),
    FOREIGN KEY(owner_id, action_id) REFERENCES learning_action(owner_id, id),
    FOREIGN KEY(owner_id, outcome_id) REFERENCES learning_outcome(owner_id, id),
    FOREIGN KEY(owner_id, criterion_id) REFERENCES learning_criterion_version(owner_id, id)
);
CREATE TABLE learning_contract_version (
    delegation_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version > 0),
    boundaries TEXT NOT NULL,
    stop_conditions TEXT NOT NULL CHECK(length(trim(stop_conditions)) > 0),
    time_budget_minutes INTEGER CHECK(time_budget_minutes > 0),
    criterion_id TEXT,
    bound_at TEXT NOT NULL,
    PRIMARY KEY(delegation_id, version),
    UNIQUE(owner_id, delegation_id, version),
    FOREIGN KEY(owner_id, delegation_id) REFERENCES learning_delegation(owner_id, id),
    FOREIGN KEY(owner_id, criterion_id) REFERENCES learning_criterion_version(owner_id, id)
);
CREATE TRIGGER learning_contract_immutable BEFORE UPDATE ON learning_contract_version
BEGIN SELECT RAISE(ABORT, 'contract version is immutable'); END;
CREATE TABLE learning_session (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    delegation_id TEXT NOT NULL,
    contract_version INTEGER NOT NULL CHECK(contract_version > 0),
    status TEXT NOT NULL CHECK(status IN ('running', 'ended', 'interrupted')),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    version INTEGER NOT NULL CHECK(version > 0),
    CHECK((status = 'running' AND ended_at IS NULL) OR (status != 'running' AND ended_at IS NOT NULL)),
    UNIQUE(owner_id, id),
    FOREIGN KEY(owner_id, delegation_id, contract_version) REFERENCES learning_contract_version(owner_id, delegation_id, version)
);
CREATE UNIQUE INDEX learning_one_running_session ON learning_session(owner_id) WHERE status = 'running';

CREATE TABLE learning_command (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    actor_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) BETWEEN 1 AND 200),
    command_type TEXT NOT NULL,
    request_hash TEXT NOT NULL CHECK(length(request_hash) = 64),
    result_json TEXT NOT NULL CHECK(json_valid(result_json)),
    recorded_at TEXT NOT NULL,
    UNIQUE(owner_id, actor_id, idempotency_key),
    UNIQUE(owner_id, id, actor_id, idempotency_key)
);
CREATE TABLE learning_event (
    position INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    aggregate_version INTEGER NOT NULL CHECK(aggregate_version > 0),
    event_type TEXT NOT NULL,
    event_version INTEGER NOT NULL CHECK(event_version > 0),
    command_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_kind TEXT NOT NULL CHECK(actor_kind IN ('user', 'agent', 'system')),
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json) AND json_type(payload_json) = 'object'),
    metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json) AND json_type(metadata_json) = 'object'),
    projection_version INTEGER NOT NULL CHECK(projection_version > 0),
    privacy TEXT NOT NULL CHECK(privacy IN ('metadata', 'private')),
    event_hash TEXT NOT NULL CHECK(length(event_hash) = 64),
    previous_hash TEXT,
    UNIQUE(owner_id, event_id),
    UNIQUE(owner_id, aggregate_type, aggregate_id, aggregate_version),
    FOREIGN KEY(owner_id, command_id, actor_id, idempotency_key)
        REFERENCES learning_command(owner_id, id, actor_id, idempotency_key)
);
CREATE TRIGGER learning_event_no_update BEFORE UPDATE ON learning_event
BEGIN SELECT RAISE(ABORT, 'event is append only'); END;
CREATE TRIGGER learning_event_no_delete BEFORE DELETE ON learning_event
BEGIN SELECT RAISE(ABORT, 'event is append only'); END;
CREATE TABLE learning_stream_head (
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_count INTEGER NOT NULL CHECK(event_count > 0),
    last_hash TEXT NOT NULL CHECK(length(last_hash) = 64),
    PRIMARY KEY(owner_id, aggregate_type, aggregate_id)
);
CREATE TABLE learning_projection_position (
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    aggregate_version INTEGER NOT NULL CHECK(aggregate_version > 0),
    projection_version INTEGER NOT NULL CHECK(projection_version > 0),
    last_event_id TEXT NOT NULL,
    PRIMARY KEY(owner_id, aggregate_type, aggregate_id),
    FOREIGN KEY(owner_id, last_event_id) REFERENCES learning_event(owner_id, event_id)
);

CREATE TABLE learning_raw_artifact (
    artifact_id TEXT NOT NULL,
    content_version INTEGER NOT NULL CHECK(content_version > 0),
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    session_id TEXT NOT NULL,
    fact_event_id TEXT NOT NULL,
    content TEXT,
    content_hash TEXT,
    privacy TEXT NOT NULL CHECK(privacy = 'private'),
    created_at TEXT NOT NULL,
    purged_at TEXT,
    PRIMARY KEY(artifact_id, content_version),
    UNIQUE(owner_id, artifact_id, content_version),
    UNIQUE(owner_id, artifact_id, content_version, fact_event_id),
    CHECK((purged_at IS NULL AND content IS NOT NULL AND length(content) > 0
           AND content_hash IS NOT NULL AND length(content_hash) = 64)
        OR (purged_at IS NOT NULL AND content IS NULL AND content_hash IS NULL)),
    FOREIGN KEY(owner_id, session_id) REFERENCES learning_session(owner_id, id),
    FOREIGN KEY(owner_id, fact_event_id) REFERENCES learning_event(owner_id, event_id)
);
-- Content erasure is the only permitted mutation; ordinary corrections append a version.
CREATE TRIGGER learning_raw_artifact_immutable BEFORE UPDATE ON learning_raw_artifact
WHEN NOT (
    OLD.purged_at IS NULL AND NEW.purged_at IS NOT NULL
    AND NEW.content IS NULL AND NEW.content_hash IS NULL
    AND NEW.artifact_id = OLD.artifact_id AND NEW.content_version = OLD.content_version
    AND NEW.owner_id = OLD.owner_id AND NEW.session_id = OLD.session_id
    AND NEW.fact_event_id = OLD.fact_event_id AND NEW.privacy = OLD.privacy AND NEW.created_at = OLD.created_at
)
BEGIN SELECT RAISE(ABORT, 'artifact content is immutable'); END;
CREATE TRIGGER learning_raw_artifact_no_delete BEFORE DELETE ON learning_raw_artifact
BEGIN SELECT RAISE(ABORT, 'artifact history cannot be deleted'); END;
CREATE TABLE learning_artifact (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    content_version INTEGER NOT NULL CHECK(content_version > 0),
    visibility TEXT NOT NULL CHECK(visibility IN ('visible', 'soft_deleted', 'purged')),
    evidence_status TEXT NOT NULL CHECK(evidence_status IN ('eligible', 'withdrawn', 'invalidated')),
    version INTEGER NOT NULL CHECK(version > 0),
    UNIQUE(owner_id, id),
    FOREIGN KEY(owner_id, id, content_version) REFERENCES learning_raw_artifact(owner_id, artifact_id, content_version)
);
CREATE TABLE learning_analysis_run (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    artifact_id TEXT NOT NULL,
    content_version INTEGER NOT NULL,
    fact_event_id TEXT NOT NULL,
    criterion_id TEXT,
    request_key TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK(attempt > 0),
    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'failed', 'timeout', 'cancelled', 'invalid_output', 'permission_denied', 'blocked_no_criterion')),
    reason TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(owner_id, id),
    UNIQUE(owner_id, request_key, attempt),
    CHECK(status = 'blocked_no_criterion' OR criterion_id IS NOT NULL),
    FOREIGN KEY(owner_id, artifact_id, content_version, fact_event_id)
        REFERENCES learning_raw_artifact(owner_id, artifact_id, content_version, fact_event_id),
    FOREIGN KEY(owner_id, criterion_id) REFERENCES learning_criterion_version(owner_id, id)
);
CREATE TABLE learning_audit (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    actor_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    result TEXT NOT NULL,
    reference_id TEXT,
    reason_code TEXT,
    recorded_at TEXT NOT NULL
);

CREATE TABLE learning_agent_permission_request (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    agent_id TEXT NOT NULL CHECK(length(trim(agent_id)) > 0),
    request_key TEXT NOT NULL CHECK(length(trim(request_key)) > 0),
    purpose TEXT NOT NULL CHECK(length(trim(purpose)) > 0),
    scope TEXT NOT NULL CHECK(scope IN ('learning_action')),
    target_id TEXT NOT NULL,
    content_granularity TEXT NOT NULL CHECK(content_granularity IN ('metadata', 'full_text')),
    ttl_seconds INTEGER NOT NULL CHECK(ttl_seconds BETWEEN 60 AND 3600),
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'denied', 'expired')),
    created_at TEXT NOT NULL,
    decided_at TEXT,
    decision_reason TEXT,
    UNIQUE(owner_id, id),
    UNIQUE(owner_id, request_key),
    FOREIGN KEY(owner_id, target_id) REFERENCES learning_action(owner_id, id)
);
CREATE INDEX learning_agent_permission_request_owner_status
    ON learning_agent_permission_request(owner_id, status, created_at);
