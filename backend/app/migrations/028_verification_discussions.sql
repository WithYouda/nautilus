-- Private question discussions stay beside their verification in the learning DB.
CREATE TABLE learning_question_discussion (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    verification_id TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    evaluation_id TEXT REFERENCES learning_verification_evaluation(id),
    request_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    purged_at TEXT,
    UNIQUE(owner_id, id),
    UNIQUE(owner_id, request_key),
    FOREIGN KEY(owner_id, verification_id) REFERENCES learning_verification(owner_id, id),
    FOREIGN KEY(submission_id) REFERENCES learning_verification_submission(id)
);

CREATE TABLE learning_discussion_turn (
    id TEXT PRIMARY KEY,
    discussion_id TEXT NOT NULL REFERENCES learning_question_discussion(id),
    request_key TEXT NOT NULL,
    user_content TEXT,
    assistant_content TEXT,
    status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed','purged')),
    reason TEXT,
    sources_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(sources_json)),
    provider_snapshot_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(provider_snapshot_json)),
    created_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(discussion_id, request_key)
);
CREATE UNIQUE INDEX learning_discussion_one_running
    ON learning_discussion_turn(discussion_id) WHERE status='running';

-- Only source IDs are copied. A derived discussion follows its source's erasure.
CREATE TABLE learning_discussion_dependency (
    discussion_id TEXT NOT NULL REFERENCES learning_question_discussion(id),
    source_discussion_id TEXT NOT NULL REFERENCES learning_question_discussion(id),
    PRIMARY KEY(discussion_id, source_discussion_id)
);

CREATE TRIGGER learning_submission_purge_discussions
AFTER UPDATE OF purged_at ON learning_verification_submission
WHEN NEW.purged_at IS NOT NULL AND OLD.purged_at IS NULL
BEGIN
    UPDATE learning_question_discussion SET purged_at=NEW.purged_at
    WHERE purged_at IS NULL AND id IN (
        WITH RECURSIVE affected(id) AS (
            SELECT id FROM learning_question_discussion WHERE submission_id=NEW.id
            UNION
            SELECT d.discussion_id FROM learning_discussion_dependency d JOIN affected a ON d.source_discussion_id=a.id
        ) SELECT id FROM affected
    );
END;

CREATE TRIGGER learning_discussion_erase_turns
AFTER UPDATE OF purged_at ON learning_question_discussion
WHEN NEW.purged_at IS NOT NULL
BEGIN
    UPDATE learning_discussion_turn
    SET user_content=NULL, assistant_content=NULL, status='purged', reason='content_purged',
        sources_json='[]', provider_snapshot_json='{}', finished_at=NEW.purged_at
    WHERE discussion_id=NEW.id;
END;
