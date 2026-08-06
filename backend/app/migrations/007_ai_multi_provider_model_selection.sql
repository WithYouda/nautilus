-- 多提供方、多模型、对话级选择与运行配置快照。
-- 不修改 001-006；旧 provider_profile.model 保留为兼容影子字段。

CREATE TABLE IF NOT EXISTS provider_model (
    id TEXT PRIMARY KEY,
    provider_profile_id TEXT NOT NULL REFERENCES provider_profile(id) ON DELETE CASCADE,
    model_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('discovered', 'manual')),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    discovery_status TEXT NOT NULL DEFAULT 'fresh'
        CHECK (discovery_status IN ('fresh', 'stale', 'unavailable')),
    last_discovered_at TEXT,
    capabilities_json TEXT NOT NULL DEFAULT '{"input_modalities":["text"],"output_modalities":["text"],"supports_streaming":true,"supports_reasoning":null,"supports_web_search":null,"supports_image_input":null,"supports_file_input":null,"max_context_tokens":null,"max_output_tokens":null}',
    capability_source TEXT NOT NULL DEFAULT 'inferred_registry'
        CHECK (capability_source IN ('provider', 'manual_override', 'inferred_registry')),
    overrides_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider_profile_id, model_id)
);

CREATE INDEX IF NOT EXISTS idx_provider_model_provider
    ON provider_model(provider_profile_id, enabled, display_name);

ALTER TABLE provider_profile ADD COLUMN default_model_id TEXT;
ALTER TABLE provider_profile ADD COLUMN credential_version INTEGER NOT NULL DEFAULT 1
    CHECK (credential_version > 0);

INSERT INTO provider_model (
    id, provider_profile_id, model_id, display_name, source, enabled,
    discovery_status, capability_source, created_at, updated_at
)
SELECT
    lower(hex(randomblob(16))),
    p.id,
    p.model,
    p.model,
    'manual',
    p.enabled,
    'fresh',
    'inferred_registry',
    p.created_at,
    p.updated_at
FROM provider_profile AS p
WHERE p.deleted_at IS NULL
  AND p.model <> ''
  AND NOT EXISTS (
      SELECT 1 FROM provider_model AS m
      WHERE m.provider_profile_id = p.id AND m.model_id = p.model
  );

UPDATE provider_profile
SET default_model_id = (
    SELECT m.id FROM provider_model AS m
    WHERE m.provider_profile_id = provider_profile.id
      AND m.model_id = provider_profile.model
    ORDER BY m.created_at
    LIMIT 1
)
WHERE default_model_id IS NULL;

CREATE TABLE IF NOT EXISTS conversation_config (
    conversation_id TEXT PRIMARY KEY REFERENCES conversation(id) ON DELETE CASCADE,
    provider_profile_id TEXT NOT NULL REFERENCES provider_profile(id) ON DELETE RESTRICT,
    provider_model_id TEXT NOT NULL REFERENCES provider_model(id) ON DELETE RESTRICT,
    timeout_override_seconds INTEGER CHECK (timeout_override_seconds BETWEEN 5 AND 600),
    config_version INTEGER NOT NULL DEFAULT 1 CHECK (config_version > 0),
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversation_config_provider
    ON conversation_config(provider_profile_id, provider_model_id);

ALTER TABLE ai_run ADD COLUMN provider_model_id TEXT REFERENCES provider_model(id) ON DELETE SET NULL;
ALTER TABLE ai_run ADD COLUMN snapshot_schema_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ai_run ADD COLUMN config_snapshot_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE ai_run ADD COLUMN credential_version INTEGER;
