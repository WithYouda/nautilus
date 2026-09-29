-- Hiding a library entry must not revoke the material's independent lifecycle.
ALTER TABLE learning_material_library ADD COLUMN removed_at TEXT;
