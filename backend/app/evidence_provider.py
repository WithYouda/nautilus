from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .conversations import ConversationError, ConversationService
from .learning_service import LearningService


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


ANALYSIS_PROMPT_SCHEMA_VERSION = 1


class EvidenceProviderService:
    """Explicit, per-owner provider selection for evidence analysis."""

    def __init__(self, learning: LearningService, conversations: ConversationService) -> None:
        self.learning = learning
        self.conversations = conversations
        self.database = learning.database

    def _selection_for_owner(self, owner_id: str) -> dict[str, Any] | None:
        row = self.database.fetchone(
            """SELECT provider_profile_id, provider_model_id, updated_at
               FROM learning_evidence_provider WHERE owner_id=?""",
            (owner_id,),
        )
        return dict(row) if row is not None else None

    def selection(self, identity: dict[str, Any]) -> dict[str, Any] | None:
        principal = self.learning.principal(identity)
        return self._selection_for_owner(principal.owner_id)

    def set_selection(
        self,
        identity: dict[str, Any],
        provider_profile_id: str,
        provider_model_id: str,
    ) -> dict[str, Any]:
        principal = self.learning.principal(identity)
        # Validate before persisting. This also proves the key is available.
        self.conversations.provider_runtime_for(
            principal.owner_id,
            provider_profile_id,
            provider_model_id,
        )
        now = utc_timestamp()
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO learning_evidence_provider
                   (owner_id, provider_profile_id, provider_model_id, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(owner_id) DO UPDATE SET
                       provider_profile_id=excluded.provider_profile_id,
                       provider_model_id=excluded.provider_model_id,
                       updated_at=excluded.updated_at""",
                (principal.owner_id, provider_profile_id, provider_model_id, now),
            )
        return {
            "provider_profile_id": provider_profile_id,
            "provider_model_id": provider_model_id,
            "updated_at": now,
        }

    def _model_id(self, provider_profile_id: str, model: str) -> str | None:
        row = self.conversations.database.fetchone(
            """SELECT id FROM provider_model
               WHERE provider_profile_id=? AND model_id=?""",
            (provider_profile_id, model),
        )
        return row["id"] if row is not None else None

    def runtime_details(self, owner_id: str) -> tuple[dict[str, Any], Any, dict[str, Any]]:
        """Return the runtime plus a non-secret snapshot for analysis audit."""
        selection = self._selection_for_owner(owner_id)
        if selection is None:
            profile, config = self.conversations.provider_runtime(owner_id)
            selection_source = "default"
            provider_model_id = self._model_id(profile["id"], config.model)
        else:
            # An explicit selection must fail closed if it becomes disabled,
            # deleted, or missing its credential. Falling back to the chat default
            # could send a learner artifact to a provider the user did not select.
            profile, config = self.conversations.provider_runtime_for(
                owner_id,
                selection["provider_profile_id"],
                selection["provider_model_id"],
            )
            selection_source = "explicit"
            provider_model_id = selection["provider_model_id"]
        snapshot = {
            "selection_source": selection_source,
            "provider_profile_id": profile["id"],
            "provider_model_id": provider_model_id,
            "model": config.model,
            "provider_kind": config.provider_kind,
            "provider_config_version": profile["config_version"],
            "timeout_seconds": config.timeout_seconds,
            "analysis_prompt_schema_version": ANALYSIS_PROMPT_SCHEMA_VERSION,
        }
        return profile, config, snapshot

    def clear_selection(self, identity: dict[str, Any]) -> None:
        principal = self.learning.principal(identity)
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "DELETE FROM learning_evidence_provider WHERE owner_id=?",
                (principal.owner_id,),
            )

    def provider_runtime(self, owner_id: str):
        """Resolve the evidence-specific runtime for a learning-domain owner."""
        profile, config, _snapshot = self.runtime_details(owner_id)
        return profile, config
