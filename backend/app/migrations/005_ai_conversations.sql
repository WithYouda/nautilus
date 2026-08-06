-- AI 学习最小纵切片：提供方配置、普通线性对话、消息、上下文快照和 AI 运行记录。
-- 安全边界：provider_profile 只保存非秘密配置，API 密钥由本地加密 CredentialStore 保存，
-- 不进入本数据库、日志、备份包或对话内容。

CREATE TABLE IF NOT EXISTS provider_profile (
    id TEXT PRIMARY KEY,
    identity_id TEXT NOT NULL REFERENCES local_identity(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    provider_kind TEXT NOT NULL CHECK (provider_kind IN ('openai_compatible')),
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    credential_key TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    config_version INTEGER NOT NULL DEFAULT 1 CHECK (config_version > 0),
    request_timeout_seconds INTEGER NOT NULL DEFAULT 60 CHECK (request_timeout_seconds BETWEEN 5 AND 600),
    last_test_status TEXT CHECK (last_test_status IN ('succeeded', 'failed')),
    last_test_error TEXT,
    last_tested_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_provider_profile_identity
    ON provider_profile(identity_id, enabled)
    WHERE deleted_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_profile_one_default
    ON provider_profile(identity_id)
    WHERE is_default = 1 AND deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS conversation (
    id TEXT PRIMARY KEY,
    identity_id TEXT NOT NULL REFERENCES local_identity(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    conversation_kind TEXT NOT NULL DEFAULT 'linear' CHECK (conversation_kind IN ('linear')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    last_message_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_conversation_identity_recent
    ON conversation(identity_id, last_message_at DESC)
    WHERE deleted_at IS NULL;

-- 对话与计划节点的关联。primary 关联决定默认上下文与归档位置，reference 关联用于检索。
CREATE TABLE IF NOT EXISTS conversation_link (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    link_role TEXT NOT NULL DEFAULT 'primary' CHECK (link_role IN ('primary', 'reference')),
    target_type TEXT NOT NULL CHECK (target_type IN ('task', 'topic', 'subject', 'goal')),
    target_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversation_link_conversation
    ON conversation_link(conversation_id, link_role);

CREATE INDEX IF NOT EXISTS idx_conversation_link_target
    ON conversation_link(target_type, target_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_link_one_primary
    ON conversation_link(conversation_id)
    WHERE link_role = 'primary';

-- 消息采用追加式记录，不做原地重写。client_message_id 用于抵挡刷新和重复提交。
CREATE TABLE IF NOT EXISTS message (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL DEFAULT '',
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    status TEXT NOT NULL DEFAULT 'complete'
        CHECK (status IN ('complete', 'streaming', 'failed', 'canceled')),
    client_message_id TEXT,
    ai_run_id TEXT REFERENCES ai_run(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_message_conversation_sequence
    ON message(conversation_id, sequence);

CREATE UNIQUE INDEX IF NOT EXISTS idx_message_client_id
    ON message(conversation_id, client_message_id)
    WHERE client_message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_message_run
    ON message(ai_run_id)
    WHERE ai_run_id IS NOT NULL;

-- 记录本次请求实际使用了哪些任务/计划上下文，便于追溯 AI 看到过什么。
CREATE TABLE IF NOT EXISTS context_snapshot (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL DEFAULT 'task_plan' CHECK (source_kind IN ('task_plan', 'none')),
    task_id TEXT,
    goal_id TEXT,
    summary TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_context_snapshot_conversation
    ON context_snapshot(conversation_id, created_at);

-- AI 运行记录：区分 queued/running/succeeded/failed/canceled，记录提供方与模型，不记录密钥。
CREATE TABLE IF NOT EXISTS ai_run (
    id TEXT PRIMARY KEY,
    identity_id TEXT NOT NULL REFERENCES local_identity(id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    workflow TEXT NOT NULL DEFAULT 'tutor_chat' CHECK (workflow IN ('tutor_chat')),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'canceled')),
    provider_profile_id TEXT REFERENCES provider_profile(id) ON DELETE SET NULL,
    provider_kind TEXT,
    model TEXT,
    config_version INTEGER,
    context_snapshot_id TEXT REFERENCES context_snapshot(id) ON DELETE SET NULL,
    request_message_id TEXT REFERENCES message(id) ON DELETE SET NULL,
    response_message_id TEXT REFERENCES message(id) ON DELETE SET NULL,
    error_kind TEXT,
    error_message TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_run_conversation
    ON ai_run(conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_run_identity_status
    ON ai_run(identity_id, status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_run_request_message
    ON ai_run(request_message_id)
    WHERE request_message_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_run_response_message
    ON ai_run(response_message_id)
    WHERE response_message_id IS NOT NULL;

-- 一个线性对话同一时间只能有一个排队或运行中的回复；终态后自动释放槽位。
CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_run_one_active_conversation
    ON ai_run(conversation_id)
    WHERE status IN ('queued', 'running');
