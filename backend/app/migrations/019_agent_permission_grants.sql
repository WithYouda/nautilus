-- Task 10: approved Agent reads are explicit, scoped, expiring, and revocable.
CREATE TABLE learning_agent_permission_grant (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    request_id TEXT NOT NULL,
    agent_id TEXT NOT NULL CHECK(length(trim(agent_id)) > 0),
    scope TEXT NOT NULL CHECK(scope IN ('learning_action')),
    target_id TEXT NOT NULL,
    content_granularity TEXT NOT NULL CHECK(content_granularity IN ('metadata', 'full_text')),
    status TEXT NOT NULL CHECK(status IN ('active', 'revoked', 'expired')),
    granted_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    revoke_reason TEXT,
    UNIQUE(owner_id, request_id),
    FOREIGN KEY(owner_id, request_id) REFERENCES learning_agent_permission_request(owner_id, id),
    FOREIGN KEY(owner_id, target_id) REFERENCES learning_action(owner_id, id)
);
CREATE INDEX learning_agent_permission_grant_owner_target
    ON learning_agent_permission_grant(owner_id, target_id, status, expires_at);
CREATE UNIQUE INDEX learning_agent_permission_grant_one_active
    ON learning_agent_permission_grant(owner_id, agent_id, target_id)
    WHERE status = 'active';
