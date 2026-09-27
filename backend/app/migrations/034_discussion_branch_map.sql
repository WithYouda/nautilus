-- Keep lineage as identifiers even when private turn snapshots are erased.
ALTER TABLE learning_question_discussion ADD COLUMN title TEXT;
ALTER TABLE learning_question_discussion ADD COLUMN title_source TEXT NOT NULL DEFAULT 'source' CHECK(title_source IN ('source','question','manual'));
ALTER TABLE learning_question_discussion ADD COLUMN branch_parent_id TEXT REFERENCES learning_question_discussion(id);
ALTER TABLE learning_question_discussion ADD COLUMN branch_turn_id TEXT REFERENCES learning_discussion_turn(id);
UPDATE learning_question_discussion SET
 branch_parent_id=(SELECT json_extract(t.provider_snapshot_json,'$.branch_origin.discussion_id') FROM learning_discussion_turn t WHERE t.discussion_id=learning_question_discussion.id AND json_type(t.provider_snapshot_json,'$.branch_origin')='object' ORDER BY t.rowid DESC LIMIT 1),
 branch_turn_id=(SELECT json_extract(t.provider_snapshot_json,'$.branch_origin.turn_id') FROM learning_discussion_turn t WHERE t.discussion_id=learning_question_discussion.id AND json_type(t.provider_snapshot_json,'$.branch_origin')='object' ORDER BY t.rowid DESC LIMIT 1);
CREATE TRIGGER discussion_title_on_purge AFTER UPDATE OF purged_at ON learning_question_discussion
WHEN NEW.purged_at IS NOT NULL BEGIN
 UPDATE learning_question_discussion SET title=NULL,title_source='source' WHERE id=NEW.id;
END;
CREATE TRIGGER discussion_title_on_turn_purge AFTER UPDATE OF status ON learning_discussion_turn
WHEN NEW.status='purged' BEGIN
 UPDATE learning_question_discussion SET title=NULL,title_source='source' WHERE id=NEW.discussion_id;
END;
