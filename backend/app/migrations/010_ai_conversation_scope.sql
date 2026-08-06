ALTER TABLE conversation ADD COLUMN context_scope TEXT NOT NULL DEFAULT 'independent'
    CHECK (context_scope IN ('independent', 'global', 'plan', 'task'));

UPDATE conversation
SET context_scope = CASE
    WHEN EXISTS (
        SELECT 1 FROM conversation_link AS link
        WHERE link.conversation_id = conversation.id
          AND link.link_role = 'primary'
          AND link.target_type = 'task'
    ) THEN 'task'
    WHEN EXISTS (
        SELECT 1 FROM conversation_link AS link
        WHERE link.conversation_id = conversation.id
          AND link.link_role = 'primary'
          AND link.target_type = 'goal'
    ) THEN 'plan'
    ELSE 'independent'
END;

CREATE INDEX IF NOT EXISTS idx_conversation_identity_scope_recent
    ON conversation(identity_id, context_scope, last_message_at DESC)
    WHERE deleted_at IS NULL;

ALTER TABLE context_snapshot ADD COLUMN scope_kind TEXT NOT NULL DEFAULT 'independent'
    CHECK (scope_kind IN ('independent', 'global', 'plan', 'task'));

UPDATE context_snapshot
SET scope_kind = CASE
    WHEN task_id IS NOT NULL THEN 'task'
    WHEN goal_id IS NOT NULL THEN 'plan'
    ELSE 'independent'
END;

CREATE INDEX IF NOT EXISTS idx_context_snapshot_scope
    ON context_snapshot(conversation_id, scope_kind, created_at);
