-- Explicit library membership gives a material an independent lifecycle.
-- Relationships contain identifiers only; immutable versions remain authoritative.
CREATE TABLE learning_material_library (
    owner_id TEXT NOT NULL,
    material_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(owner_id, material_id)
);
CREATE TABLE learning_material_link (
    owner_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL CHECK(scope_kind IN ('conversation','discussion')),
    scope_id TEXT NOT NULL,
    version_id TEXT NOT NULL REFERENCES learning_task_material(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY(owner_id, scope_kind, scope_id, version_id)
);
DROP TRIGGER learning_discussion_purge_materials;
CREATE TRIGGER learning_discussion_purge_materials AFTER UPDATE OF purged_at ON learning_question_discussion
WHEN NEW.purged_at IS NOT NULL BEGIN
    UPDATE learning_task_material SET title=NULL, content=NULL, url=NULL, provenance_json='{}', purged_at=NEW.purged_at
    WHERE owner_id=NEW.owner_id AND scope_kind='discussion' AND scope_id=NEW.id AND purged_at IS NULL
      AND NOT EXISTS (SELECT 1 FROM learning_material_library l
                      WHERE l.owner_id=learning_task_material.owner_id AND l.material_id=learning_task_material.material_id);
END;
