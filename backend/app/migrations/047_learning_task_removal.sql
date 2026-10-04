-- Administrative removal keeps execution facts and their stable references.
CREATE TABLE learning_action_removal (
    owner_id TEXT NOT NULL REFERENCES local_identity(id),
    action_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    previous_status TEXT NOT NULL CHECK(previous_status IN ('open','completed','cancelled')),
    event_id TEXT NOT NULL REFERENCES learning_event(event_id),
    removed_at TEXT NOT NULL,
    PRIMARY KEY(owner_id,action_id),
    FOREIGN KEY(owner_id,action_id) REFERENCES learning_action(owner_id,id),
    FOREIGN KEY(owner_id,action_id) REFERENCES learning_action_link(owner_id,action_id),
    FOREIGN KEY(owner_id,plan_id) REFERENCES learning_plan(owner_id,id)
);
CREATE INDEX learning_action_removal_plan ON learning_action_removal(owner_id,plan_id);
