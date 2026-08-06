ALTER TABLE task ADD COLUMN completion_restore_status TEXT
    CHECK (
        completion_restore_status IS NULL
        OR completion_restore_status IN ('pending', 'in_progress', 'completed', 'canceled')
    );

ALTER TABLE task ADD COLUMN completion_restore_progress INTEGER
    CHECK (
        completion_restore_progress IS NULL
        OR completion_restore_progress BETWEEN 0 AND 100
    );
