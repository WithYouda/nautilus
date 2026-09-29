-- Original uploads belong to immutable material versions, not to a mutable filename.
-- Keeping originals in the learning database makes existing SQLite backups atomic.
CREATE TABLE learning_material_original (
    version_id TEXT PRIMARY KEY REFERENCES learning_task_material(id),
    filename TEXT,
    media_type TEXT,
    content BLOB,
    sha256 TEXT,
    purged_at TEXT
);

CREATE TRIGGER learning_material_purge_original AFTER UPDATE OF purged_at ON learning_task_material
WHEN NEW.purged_at IS NOT NULL BEGIN
    UPDATE learning_material_original SET filename=NULL,media_type=NULL,content=NULL,sha256=NULL,
        purged_at=NEW.purged_at WHERE version_id=NEW.id;
END;
