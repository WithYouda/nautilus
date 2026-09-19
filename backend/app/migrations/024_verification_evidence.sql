-- Verification content uses the existing raw artifact lifecycle once linked.
ALTER TABLE learning_verification_submission ADD COLUMN artifact_id TEXT;
ALTER TABLE learning_verification_submission ADD COLUMN purged_at TEXT;
ALTER TABLE learning_verification ADD COLUMN purged_at TEXT;
ALTER TABLE learning_verification_evaluation ADD COLUMN evidence_run_id TEXT;

CREATE UNIQUE INDEX verification_submission_artifact
    ON learning_verification_submission(owner_id, artifact_id) WHERE artifact_id IS NOT NULL;

CREATE TRIGGER verification_submission_content_immutable
BEFORE UPDATE OF content_json ON learning_verification_submission
WHEN NEW.content_json <> OLD.content_json AND NOT (
    NEW.content_json = '{}' AND (NEW.artifact_id IS NOT NULL OR NEW.purged_at IS NOT NULL)
)
BEGIN SELECT RAISE(ABORT, 'verification submission is immutable'); END;

CREATE TABLE learning_evidence_private_content (
    event_id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL,
    claim_ids_json TEXT NOT NULL CHECK(json_valid(claim_ids_json)),
    content_json TEXT CHECK(content_json IS NULL OR json_valid(content_json)),
    purged_at TEXT,
    CHECK((purged_at IS NULL AND content_json IS NOT NULL) OR (purged_at IS NOT NULL AND content_json IS NULL)),
    FOREIGN KEY(owner_id, event_id) REFERENCES learning_evidence_event(owner_id, id)
);
CREATE TRIGGER learning_evidence_private_immutable BEFORE UPDATE ON learning_evidence_private_content
WHEN NOT (OLD.purged_at IS NULL AND NEW.purged_at IS NOT NULL AND NEW.content_json IS NULL
          AND NEW.event_id=OLD.event_id AND NEW.owner_id=OLD.owner_id AND NEW.claim_ids_json=OLD.claim_ids_json)
BEGIN SELECT RAISE(ABORT, 'private evidence content is immutable'); END;
CREATE TRIGGER learning_evidence_private_no_delete BEFORE DELETE ON learning_evidence_private_content
BEGIN SELECT RAISE(ABORT, 'private evidence content must be purged'); END;
