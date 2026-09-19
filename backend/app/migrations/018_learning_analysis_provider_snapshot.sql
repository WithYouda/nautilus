-- Task 9: persist a non-secret provider/model snapshot for each analysis run.
ALTER TABLE learning_analysis_run
    ADD COLUMN provider_selection_source TEXT
        CHECK(provider_selection_source IS NULL OR provider_selection_source IN ('default', 'explicit'));
ALTER TABLE learning_analysis_run
    ADD COLUMN provider_profile_id TEXT;
ALTER TABLE learning_analysis_run
    ADD COLUMN provider_model_id TEXT;
ALTER TABLE learning_analysis_run
    ADD COLUMN provider_model TEXT;
ALTER TABLE learning_analysis_run
    ADD COLUMN provider_kind TEXT;
ALTER TABLE learning_analysis_run
    ADD COLUMN provider_config_version INTEGER;
ALTER TABLE learning_analysis_run
    ADD COLUMN provider_timeout_seconds INTEGER;
ALTER TABLE learning_analysis_run
    ADD COLUMN analysis_prompt_schema_version INTEGER;
