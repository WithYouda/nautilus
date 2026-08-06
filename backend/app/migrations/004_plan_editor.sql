ALTER TABLE learning_goal ADD COLUMN deleted_at TEXT;
ALTER TABLE subject ADD COLUMN deleted_at TEXT;
ALTER TABLE topic ADD COLUMN deleted_at TEXT;
ALTER TABLE task ADD COLUMN deleted_at TEXT;

CREATE INDEX IF NOT EXISTS idx_learning_goal_identity_active
    ON learning_goal(identity_id, deleted_at, status, created_at);

CREATE INDEX IF NOT EXISTS idx_subject_goal_active_position
    ON subject(goal_id, deleted_at, position);

CREATE INDEX IF NOT EXISTS idx_topic_subject_active_position
    ON topic(subject_id, deleted_at, position);

CREATE INDEX IF NOT EXISTS idx_task_topic_active_position
    ON task(topic_id, deleted_at, position);
