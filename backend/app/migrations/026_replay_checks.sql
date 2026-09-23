-- Comparison metadata only; never copies projection text into telemetry.
CREATE TABLE learning_replay_check (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    kind TEXT NOT NULL CHECK(kind IN ('fact', 'evidence')),
    cutoff INTEGER NOT NULL,
    before_digest TEXT,
    after_digest TEXT,
    counts_json TEXT NOT NULL,
    constraints_ok INTEGER NOT NULL,
    matched INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
