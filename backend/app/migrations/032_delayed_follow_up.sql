-- A bounded, approved fixed-item follow-up; separate from old ability evidence.
CREATE TABLE learning_delayed_follow_up (
 id TEXT PRIMARY KEY NOT NULL,
 owner_id TEXT NOT NULL,
 outcome_id TEXT NOT NULL,
 delegation_id TEXT NOT NULL,
 source_artifact_id TEXT NOT NULL,
 source_content_version INTEGER NOT NULL,
 source_criterion_id TEXT,
 standard_id TEXT NOT NULL,
 standard_snapshot_json TEXT,
 request_key TEXT NOT NULL,
 request_fingerprint TEXT,
 status TEXT NOT NULL CHECK(status IN ('initial','scheduled','started','completed','skipped','purged')),
 due_at TEXT,
 timezone TEXT,
 arranged_at TEXT,
 started_at TEXT,
 history_json TEXT,
 created_at TEXT NOT NULL,
 purged_at TEXT,
 UNIQUE(owner_id,id),
 UNIQUE(owner_id,request_key),
 UNIQUE(owner_id,outcome_id,standard_id),
 FOREIGN KEY(owner_id,outcome_id) REFERENCES learning_outcome(owner_id,id),
 FOREIGN KEY(owner_id,delegation_id) REFERENCES learning_delegation(owner_id,id),
 FOREIGN KEY(owner_id,source_artifact_id) REFERENCES learning_artifact(owner_id,id)
);
CREATE TABLE learning_delayed_attempt (
 id TEXT PRIMARY KEY NOT NULL,
 owner_id TEXT NOT NULL,
 follow_up_id TEXT NOT NULL,
 phase TEXT NOT NULL CHECK(phase IN ('initial','followup')),
 revision INTEGER NOT NULL DEFAULT 0,
 answers_json TEXT,
 user_report TEXT,
 condition_json TEXT,
 submitted_at TEXT,
 submit_key TEXT,
 submit_fingerprint TEXT,
 check_status TEXT NOT NULL DEFAULT 'not_checked' CHECK(check_status IN ('not_checked','succeeded','failed')),
 result_json TEXT,
 checked_at TEXT,
 created_at TEXT NOT NULL,
 purged_at TEXT,
 UNIQUE(owner_id,id),
 UNIQUE(owner_id,follow_up_id,phase),
 FOREIGN KEY(owner_id,follow_up_id) REFERENCES learning_delayed_follow_up(owner_id,id)
);
CREATE TABLE learning_delayed_view (
 id TEXT PRIMARY KEY NOT NULL,
 owner_id TEXT NOT NULL,
 follow_up_id TEXT NOT NULL,
 attempt_id TEXT NOT NULL,
 provided_at TEXT,
 displayed_at TEXT,
 after_arranging INTEGER DEFAULT 0 CHECK(after_arranging IN (0,1)),
 purged_at TEXT,
 UNIQUE(owner_id,id),
 FOREIGN KEY(owner_id,follow_up_id) REFERENCES learning_delayed_follow_up(owner_id,id),
 FOREIGN KEY(owner_id,attempt_id) REFERENCES learning_delayed_attempt(owner_id,id)
);
CREATE INDEX learning_delayed_due ON learning_delayed_follow_up(owner_id,status,due_at);
CREATE TRIGGER learning_delayed_source_erased AFTER UPDATE OF purged_at ON learning_raw_artifact
WHEN NEW.purged_at IS NOT NULL
BEGIN
 UPDATE learning_delayed_follow_up SET purged_at=NEW.purged_at
 WHERE owner_id=NEW.owner_id AND source_artifact_id=NEW.artifact_id;
END;
CREATE TRIGGER learning_delayed_erased AFTER UPDATE OF purged_at ON learning_delayed_follow_up
WHEN NEW.purged_at IS NOT NULL
BEGIN
 UPDATE learning_delayed_follow_up SET status='purged',standard_snapshot_json=NULL,request_fingerprint=NULL,
 history_json=NULL,due_at=NULL,timezone=NULL,arranged_at=NULL,started_at=NULL WHERE id=NEW.id;
 UPDATE learning_delayed_attempt SET answers_json=NULL,user_report=NULL,condition_json=NULL,submit_fingerprint=NULL,
 result_json=NULL,check_status='not_checked',purged_at=NEW.purged_at WHERE owner_id=NEW.owner_id AND follow_up_id=NEW.id;
 UPDATE learning_delayed_view SET provided_at=NULL,displayed_at=NULL,after_arranging=NULL,purged_at=NEW.purged_at
 WHERE owner_id=NEW.owner_id AND follow_up_id=NEW.id;
END;
