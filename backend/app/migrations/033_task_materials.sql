-- Task materials are immutable content versions. Erasure only clears private columns.
CREATE TABLE learning_task_material (
    id TEXT PRIMARY KEY,
    material_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL CHECK(scope_kind IN ('conversation','discussion')),
    scope_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version > 0),
    title TEXT,
    content TEXT,
    url TEXT,
    content_kind TEXT NOT NULL CHECK(content_kind IN ('text','excerpt','page')),
    provenance_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(provenance_json)),
    created_at TEXT NOT NULL,
    purged_at TEXT,
    UNIQUE(owner_id, material_id, version)
);
CREATE INDEX learning_task_material_scope ON learning_task_material(owner_id,scope_kind,scope_id,material_id,version);
CREATE INDEX learning_task_material_group ON learning_task_material(owner_id,material_id);

CREATE TRIGGER learning_discussion_purge_materials AFTER UPDATE OF purged_at ON learning_question_discussion
WHEN NEW.purged_at IS NOT NULL BEGIN
    UPDATE learning_task_material SET title=NULL, content=NULL, url=NULL, provenance_json='{}', purged_at=NEW.purged_at
    WHERE owner_id=NEW.owner_id AND scope_kind='discussion' AND scope_id=NEW.id AND purged_at IS NULL;
END;
