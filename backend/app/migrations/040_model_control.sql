-- Sparse configuration, independent of material grants and learning facts.
CREATE TABLE learning_model_config (
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    scope_kind TEXT NOT NULL CHECK(scope_kind IN ('plan','task','conversation','discussion')),
    scope_id TEXT NOT NULL,
    provider_profile_id TEXT,
    provider_model_id TEXT,
    timeout_seconds INTEGER CHECK(timeout_seconds IS NULL OR timeout_seconds BETWEEN 5 AND 600),
    revision INTEGER NOT NULL CHECK(revision > 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(owner_id, scope_kind, scope_id),
    CHECK((provider_profile_id IS NULL) = (provider_model_id IS NULL))
);

CREATE TRIGGER learning_discussion_purge_model_config
AFTER UPDATE OF purged_at ON learning_question_discussion
WHEN NEW.purged_at IS NOT NULL
BEGIN
    DELETE FROM learning_model_config
    WHERE owner_id=NEW.owner_id AND scope_kind='discussion' AND scope_id=NEW.id;
END;
