-- Evidence-gate baseline. Claims are interpretations, not facts.
CREATE TABLE learning_evidence_claim (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    artifact_id TEXT NOT NULL,
    content_version INTEGER NOT NULL,
    fact_event_id TEXT NOT NULL,
    criterion_id TEXT NOT NULL,
    dimension_id TEXT NOT NULL CHECK(length(trim(dimension_id)) > 0),
    stance TEXT NOT NULL CHECK(stance IN ('supports', 'refutes', 'insufficient')),
    status TEXT NOT NULL CHECK(status IN ('candidate', 'adopted', 'questioned', 'withdrawn', 'superseded', 'invalidated')),
    source TEXT NOT NULL CHECK(source IN ('ai_analysis', 'human_review', 'deterministic_check')),
    statement TEXT NOT NULL CHECK(length(trim(statement)) > 0),
    verification_method TEXT NOT NULL CHECK(length(trim(verification_method)) > 0),
    evidence_condition TEXT NOT NULL CHECK(evidence_condition IN ('independent', 'with_materials', 'with_hints')),
    scope TEXT NOT NULL CHECK(length(trim(scope)) > 0),
    analysis_run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(owner_id, id),
    UNIQUE(owner_id, analysis_run_id, dimension_id),
    FOREIGN KEY(owner_id, artifact_id, content_version, fact_event_id)
        REFERENCES learning_raw_artifact(owner_id, artifact_id, content_version, fact_event_id),
    FOREIGN KEY(owner_id, criterion_id) REFERENCES learning_criterion_version(owner_id, id),
    FOREIGN KEY(owner_id, analysis_run_id) REFERENCES learning_analysis_run(owner_id, id)
);
CREATE INDEX learning_evidence_claim_artifact
    ON learning_evidence_claim(owner_id, artifact_id, content_version, status);
CREATE INDEX learning_evidence_claim_criterion_dimension
    ON learning_evidence_claim(owner_id, criterion_id, dimension_id, status);
