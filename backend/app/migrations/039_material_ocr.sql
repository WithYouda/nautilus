-- OCR drafts are separate from immutable, user-confirmed material versions.
CREATE TABLE learning_material_ocr (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL CHECK(scope_kind IN ('conversation','discussion')),
    scope_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL REFERENCES learning_task_material(id),
    status TEXT NOT NULL CHECK(status IN ('running','review','failed','canceled','confirmed','purged')),
    pages_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(pages_json)),
    model_json TEXT,
    error_code TEXT,
    result_version_id TEXT REFERENCES learning_task_material(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    purged_at TEXT
);
CREATE INDEX learning_material_ocr_source ON learning_material_ocr(owner_id,source_version_id,created_at);
CREATE UNIQUE INDEX learning_material_ocr_running ON learning_material_ocr(owner_id,source_version_id) WHERE status='running';
CREATE TRIGGER learning_material_purge_ocr AFTER UPDATE OF purged_at ON learning_task_material
WHEN NEW.purged_at IS NOT NULL BEGIN
    UPDATE learning_material_ocr SET pages_json='[]',model_json=NULL,error_code=NULL,
        status='purged',updated_at=NEW.purged_at,purged_at=NEW.purged_at
        WHERE source_version_id=NEW.id;
END;
