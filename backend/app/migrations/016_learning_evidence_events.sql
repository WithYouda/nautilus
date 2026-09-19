-- Evidence event ledger for claim, review, state, follow-up, and lifecycle replay.
CREATE TABLE learning_evidence_event (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    aggregate_type TEXT NOT NULL CHECK(aggregate_type IN (
        'claim',
        'review',
        'state',
        'follow_up',
        'lifecycle'
    )),
    aggregate_id TEXT NOT NULL CHECK(length(trim(aggregate_id)) > 0),
    event_type TEXT NOT NULL CHECK(length(trim(event_type)) > 0),
    event_version INTEGER NOT NULL CHECK(event_version > 0),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json) AND json_type(payload_json) = 'object'),
    previous_hash TEXT,
    event_hash TEXT NOT NULL CHECK(length(event_hash) = 64),
    created_at TEXT NOT NULL,
    UNIQUE(owner_id, aggregate_type, aggregate_id, event_version),
    UNIQUE(owner_id, id)
);
CREATE INDEX learning_evidence_event_owner_aggregate
    ON learning_evidence_event(owner_id, aggregate_type, aggregate_id, event_version);
CREATE INDEX learning_evidence_event_owner_created
    ON learning_evidence_event(owner_id, created_at, id);
