-- Native reasoning controls reuse the scoped model configuration and run snapshots.
ALTER TABLE learning_model_config ADD COLUMN reasoning_json TEXT
    CHECK(reasoning_json IS NULL OR json_valid(reasoning_json));

CREATE TABLE learning_model_defaults (
    owner_id TEXT PRIMARY KEY REFERENCES local_identity(id),
    reasoning_json TEXT CHECK(reasoning_json IS NULL OR json_valid(reasoning_json)),
    revision INTEGER NOT NULL CHECK(revision > 0),
    updated_at TEXT NOT NULL
);
