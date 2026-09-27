CREATE TABLE learning_conversation_current_state (
    owner_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('conversation','discussion')),
    scope_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    leaf_id TEXT,
    paths_json TEXT NOT NULL CHECK(json_valid(paths_json)),
    source_scope_json TEXT NOT NULL CHECK(json_valid(source_scope_json)),
    search_override_json TEXT CHECK(search_override_json IS NULL OR json_valid(search_override_json)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(owner_id,kind,scope_id)
);

CREATE TRIGGER learning_discussion_purge_current_state
AFTER UPDATE OF purged_at ON learning_question_discussion
WHEN NEW.purged_at IS NOT NULL
BEGIN
    DELETE FROM learning_conversation_current_state
    WHERE owner_id=NEW.owner_id AND kind='discussion' AND scope_id=NEW.id;
END;
