-- Task 12: separate evidence event sequence from semantic schema version.
-- Existing event_version remains the per-aggregate sequence introduced by 016.
ALTER TABLE learning_evidence_event
    ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 1
        CHECK(schema_version > 0);
CREATE INDEX learning_evidence_event_schema_version
    ON learning_evidence_event(owner_id, schema_version);
CREATE TRIGGER learning_evidence_event_no_update
BEFORE UPDATE ON learning_evidence_event
BEGIN
    SELECT RAISE(ABORT, 'learning_evidence_event is append-only');
END;
CREATE TRIGGER learning_evidence_event_no_delete
BEFORE DELETE ON learning_evidence_event
BEGIN
    SELECT RAISE(ABORT, 'learning_evidence_event is append-only');
END;
