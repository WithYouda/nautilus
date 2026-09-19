import pytest

from app.conversations import ConversationError
from app.core.commands import EndSession, StartSession
from app.core.learning import LearningCore
from app.learning_domain import DomainError
from app.learning_room import LearningRoomService
from app.learning_service import LearningService
from test_learning_verifications import IDENTITY, OWNER, create_context
from test_learning_domain_schema import learning_database  # noqa: F401


class Chats:
    def __init__(self):
        self.items = {"chat-1": "owner-a", "chat-2": "owner-a", "foreign": "owner-b"}

    def owned_conversation(self, owner, conversation):
        if self.items.get(conversation) != owner:
            raise ConversationError("not found")
        return {"context_scope": "independent"}


def test_room_restores_owned_conversation_and_survives_fact_replay(learning_database):
    context = create_context(learning_database)
    chats = Chats()
    room = LearningRoomService(LearningService(learning_database), chats)
    initial = room.get(IDENTITY, context["session_id"])
    assert initial["conversation_id"] is None
    assert initial["brief"]["action_id"] == context["action_id"]
    assert initial["brief"]["stop_conditions"] == "完成一次独立说明"
    room.select(IDENTITY, context["session_id"], "chat-1")
    room.select(IDENTITY, context["session_id"], "chat-2")
    assert room.get(IDENTITY, context["session_id"])["conversation_id"] == "chat-2"
    LearningCore(learning_database).replay(OWNER)
    assert room.get(IDENTITY, context["session_id"])["conversation_ids"] == ["chat-2", "chat-1"]
    del chats.items["chat-2"]
    assert room.get(IDENTITY, context["session_id"])["conversation_id"] == "chat-1"
    assert learning_database.fetchall("PRAGMA foreign_key_check") == []


def test_room_refuses_foreign_objects_and_cross_session_reassignment(learning_database):
    context = create_context(learning_database)
    room = LearningRoomService(LearningService(learning_database), Chats())
    with pytest.raises(DomainError, match="not_found"):
        room.select(IDENTITY, context["session_id"], "foreign")
    with pytest.raises(DomainError, match="not_found"):
        room.get({**IDENTITY, "id": "owner-b", "device_id": "owner-b-device"}, context["session_id"])
    room.select(IDENTITY, context["session_id"], "chat-1")
    core = LearningCore(learning_database)
    core.execute(OWNER, EndSession(session_id=context["session_id"], disposition="interrupted", expected_version=3), "end")
    another = core.execute(OWNER, StartSession(delegation_id=context["delegation_id"], expected_version=4), "restart")
    with pytest.raises(DomainError, match="verification_scope_invalid"):
        room.select(IDENTITY, another["id"], "chat-1")
    assert room.get(IDENTITY, another["id"])["conversation_id"] is None
