CREATE TABLE IF NOT EXISTS layout_config (
    identity_id TEXT PRIMARY KEY REFERENCES local_identity(id) ON DELETE CASCADE,
    modules_json TEXT NOT NULL,
    source_template_id TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS layout_template (
    id TEXT PRIMARY KEY,
    identity_id TEXT REFERENCES local_identity(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    modules_json TEXT NOT NULL,
    is_system INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (is_system = 1 AND identity_id IS NULL)
        OR (is_system = 0 AND identity_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_layout_template_identity
    ON layout_template(identity_id, created_at);

INSERT OR IGNORE INTO layout_template
    (id, identity_id, name, modules_json, is_system, created_at, updated_at)
VALUES
    (
        'system-today-cockpit',
        NULL,
        '今日学习驾驶舱',
        '[{"id":"summary","visible":true},{"id":"tasks","visible":true},{"id":"timer","visible":true},{"id":"context","visible":true}]',
        1,
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    (
        'system-focus',
        NULL,
        '专注执行',
        '[{"id":"tasks","visible":true},{"id":"timer","visible":true},{"id":"summary","visible":true},{"id":"context","visible":false}]',
        1,
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    ),
    (
        'system-review',
        NULL,
        '路线回顾',
        '[{"id":"summary","visible":true},{"id":"tasks","visible":true},{"id":"context","visible":true},{"id":"timer","visible":false}]',
        1,
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    );
