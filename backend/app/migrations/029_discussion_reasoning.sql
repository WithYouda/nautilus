-- Provider-returned thinking is private content, separate from the final answer.
ALTER TABLE learning_discussion_turn ADD COLUMN reasoning_content TEXT;

DROP TRIGGER learning_discussion_erase_turns;
CREATE TRIGGER learning_discussion_erase_turns
AFTER UPDATE OF purged_at ON learning_question_discussion
WHEN NEW.purged_at IS NOT NULL
BEGIN
    UPDATE learning_discussion_turn
    SET user_content=NULL, assistant_content=NULL, reasoning_content=NULL,
        status='purged', reason='content_purged', sources_json='[]',
        provider_snapshot_json='{}', finished_at=NEW.purged_at
    WHERE discussion_id=NEW.id;
END;
