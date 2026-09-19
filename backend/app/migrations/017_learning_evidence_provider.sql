-- Task 9: explicit provider selection for evidence analysis.
CREATE TABLE learning_evidence_provider (
    owner_id TEXT PRIMARY KEY REFERENCES local_identity(id),
    provider_profile_id TEXT NOT NULL,
    provider_model_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
