from __future__ import annotations

from .conversations import ConversationError
from .core.learning import utc_timestamp
from .learning_domain import DomainError, LearningRepository


class LearningRoomService:
    """Resolve a real learning session and its owned teaching conversations."""

    def __init__(self, learning, conversations):
        self.learning = learning
        self.conversations = conversations

    def get(self, identity, session_id):
        principal = self.learning.principal(identity)
        repository = LearningRepository(self.learning.database, principal)
        session = repository.session(session_id)
        delegation = repository.delegation(session["delegation_id"])
        action = repository.action(delegation["action_id"])
        row = self.learning.database.fetchone(
            """SELECT c.boundaries, c.stop_conditions, o.object_description, o.behavior,
                      g.title AS goal_title, p.title AS plan_title
               FROM learning_contract_version c
               JOIN learning_outcome o ON o.owner_id=c.owner_id AND o.id=?
               LEFT JOIN learning_action_link l ON l.owner_id=c.owner_id AND l.action_id=?
               LEFT JOIN learning_plan p ON p.owner_id=l.owner_id AND p.id=l.plan_id
               LEFT JOIN learning_goal g ON g.owner_id=p.owner_id AND g.id=p.goal_id
               WHERE c.owner_id=? AND c.delegation_id=? AND c.version=?""",
            (delegation["outcome_id"], action["id"], principal.owner_id, delegation["id"], session["contract_version"]),
        )
        if row is None:
            raise DomainError("not_found", 404)
        conversations = []
        for link in self.learning.database.fetchall(
            "SELECT conversation_id FROM learning_room_conversation WHERE owner_id=? AND session_id=? ORDER BY selected_at DESC, conversation_id",
            (principal.owner_id, session_id),
        ):
            try:
                self.conversations.owned_conversation(principal.owner_id, link["conversation_id"])
                conversations.append(link["conversation_id"])
            except ConversationError:
                # Deleting a chat does not delete or invent a learning session.
                continue
        return {
            "brief": {
                "action_id": action["id"], "delegation_id": delegation["id"], "session_id": session_id,
                "criterion_id": delegation["criterion_id"], "action_title": action["title"],
                "goal_title": row["goal_title"] or "", "plan_title": row["plan_title"] or "",
                "outcome_object": row["object_description"], "outcome_behavior": row["behavior"],
                "boundaries": row["boundaries"], "stop_conditions": row["stop_conditions"],
            },
            "conversation_id": conversations[0] if conversations else None,
            "conversation_ids": conversations,
        }

    def select(self, identity, session_id, conversation_id):
        principal = self.learning.principal(identity)
        LearningRepository(self.learning.database, principal).session(session_id)
        try:
            conversation = self.conversations.owned_conversation(principal.owner_id, conversation_id)
        except ConversationError as exc:
            raise DomainError("not_found", 404) from exc
        if conversation["context_scope"] != "independent":
            raise DomainError("verification_scope_invalid")
        with self.learning.database.transaction(immediate=True) as connection:
            existing = connection.execute(
                "SELECT session_id FROM learning_room_conversation WHERE owner_id=? AND conversation_id=?",
                (principal.owner_id, conversation_id),
            ).fetchone()
            if existing and existing["session_id"] != session_id:
                raise DomainError("verification_scope_invalid")
            connection.execute(
                """INSERT INTO learning_room_conversation VALUES (?, ?, ?, ?)
                   ON CONFLICT(owner_id, conversation_id) DO UPDATE SET selected_at=excluded.selected_at""",
                (principal.owner_id, session_id, conversation_id, utc_timestamp()),
            )
        return self.get(identity, session_id)
