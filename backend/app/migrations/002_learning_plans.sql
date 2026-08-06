CREATE TABLE IF NOT EXISTS learning_goal (
    id TEXT PRIMARY KEY,
    identity_id TEXT NOT NULL REFERENCES local_identity(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('draft', 'active', 'completed', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_learning_goal_identity_status
    ON learning_goal(identity_id, status);

CREATE TABLE IF NOT EXISTS subject (
    id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL REFERENCES learning_goal(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subject_goal_position
    ON subject(goal_id, position);

CREATE TABLE IF NOT EXISTS topic (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL REFERENCES subject(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_topic_subject_position
    ON topic(subject_id, position);

CREATE TABLE IF NOT EXISTS task (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topic(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    task_type TEXT NOT NULL CHECK (task_type IN ('study', 'practice', 'review', 'output')),
    schedule_mode TEXT NOT NULL DEFAULT 'flexible' CHECK (schedule_mode IN ('fixed', 'flexible')),
    start_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    planned_start TEXT,
    planned_end TEXT,
    estimate_minutes INTEGER NOT NULL CHECK (estimate_minutes > 0),
    actual_minutes INTEGER NOT NULL DEFAULT 0 CHECK (actual_minutes >= 0),
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'canceled')),
    timer_mode TEXT NOT NULL DEFAULT 'pomodoro_25_5' CHECK (timer_mode IN ('pomodoro_25_5', 'pomodoro_50_10', 'custom', 'count_up')),
    work_minutes INTEGER NOT NULL DEFAULT 25 CHECK (work_minutes > 0),
    break_minutes INTEGER NOT NULL DEFAULT 5 CHECK (break_minutes >= 0),
    position INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_topic_position
    ON task(topic_id, position);

CREATE INDEX IF NOT EXISTS idx_task_schedule_status
    ON task(start_date, due_date, status);

CREATE TABLE IF NOT EXISTS study_session (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    identity_id TEXT NOT NULL REFERENCES local_identity(id) ON DELETE CASCADE,
    timer_mode TEXT NOT NULL CHECK (timer_mode IN ('pomodoro_25_5', 'pomodoro_50_10', 'custom', 'count_up')),
    work_minutes INTEGER NOT NULL CHECK (work_minutes > 0),
    break_minutes INTEGER NOT NULL CHECK (break_minutes >= 0),
    status TEXT NOT NULL CHECK (status IN ('running', 'paused', 'completed', 'canceled')),
    started_at TEXT NOT NULL,
    resumed_at TEXT NOT NULL,
    paused_at TEXT,
    ended_at TEXT,
    accumulated_seconds INTEGER NOT NULL DEFAULT 0 CHECK (accumulated_seconds >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_study_session_one_active_task
    ON study_session(task_id)
    WHERE status IN ('running', 'paused');

CREATE UNIQUE INDEX IF NOT EXISTS idx_study_session_one_active_identity
    ON study_session(identity_id)
    WHERE status IN ('running', 'paused');

CREATE INDEX IF NOT EXISTS idx_study_session_identity_status
    ON study_session(identity_id, status);
