-- Missing provenance stays unknown; never certify legacy model declarations.
ALTER TABLE learning_evidence_claim ADD COLUMN provenance_json TEXT
    CHECK(provenance_json IS NULL OR json_valid(provenance_json));

-- Old cached conclusions cannot certify unrecorded execution provenance.
-- Preserve history and all immutable events; reassessment requires real execution.
UPDATE learning_derived_state SET status='insufficient_evidence',
    reason_code='execution_provenance_unverified'
WHERE status IN ('supported', 'partially_supported', 'contradicted');
