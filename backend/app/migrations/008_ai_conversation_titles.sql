-- AI 学习室标题状态与独立标题运行。
-- 标题运行只保存非敏感配置快照和输入消息 ID，不保存密钥或额外复制消息正文。

ALTER TABLE conversation ADD COLUMN title_source TEXT NOT NULL DEFAULT 'placeholder'
    CHECK (title_source IN ('placeholder', 'fallback', 'ai', 'manual'));
ALTER TABLE conversation ADD COLUMN title_generation_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (title_generation_status IN ('pending', 'queued', 'running', 'succeeded', 'failed', 'idle'));
ALTER TABLE conversation ADD COLUMN title_revision INTEGER NOT NULL DEFAULT 0
    CHECK (title_revision >= 0);
ALTER TABLE conversation ADD COLUMN title_generated_at TEXT;

-- 旧的机械标题允许在第一次成功回复后生成 AI 标题；用户显式标题保持不动。
UPDATE conversation
SET title_source = CASE
        WHEN title = '新的学习对话' OR title LIKE '与 AI 学习：%' THEN 'placeholder'
        ELSE 'manual'
    END,
    title_generation_status = CASE
        WHEN title = '新的学习对话' OR title LIKE '与 AI 学习：%' THEN 'pending'
        ELSE 'idle'
    END;

CREATE TABLE IF NOT EXISTS conversation_title_run (
    id TEXT PRIMARY KEY,
    identity_id TEXT NOT NULL REFERENCES local_identity(id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    trigger_ai_run_id TEXT REFERENCES ai_run(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'superseded')),
    forced INTEGER NOT NULL DEFAULT 0 CHECK (forced IN (0, 1)),
    provider_profile_id TEXT REFERENCES provider_profile(id) ON DELETE SET NULL,
    provider_model_id TEXT REFERENCES provider_model(id) ON DELETE SET NULL,
    provider_kind TEXT NOT NULL,
    model TEXT NOT NULL,
    snapshot_schema_version INTEGER NOT NULL DEFAULT 1 CHECK (snapshot_schema_version > 0),
    config_snapshot_json TEXT NOT NULL DEFAULT '{}',
    credential_version INTEGER,
    expected_title_revision INTEGER NOT NULL CHECK (expected_title_revision >= 0),
    input_message_ids_json TEXT NOT NULL DEFAULT '[]',
    generated_title TEXT,
    error_kind TEXT,
    error_message TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (forced = 1 OR trigger_ai_run_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_conversation_title_run_conversation
    ON conversation_title_run(conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversation_title_run_identity_status
    ON conversation_title_run(identity_id, status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_title_run_one_active
    ON conversation_title_run(conversation_id)
    WHERE status IN ('queued', 'running');
