from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, status

from .auth import AuthService
from .agent_runtime import AgentRuntime
from .ai_runtime import AiRunManager
from .conversations import ConversationService
from .evidence import EvidenceService
from .evidence_provider import EvidenceProviderService
from .evidence_events import EvidenceEventService
from .layouts import LayoutService
from .learning_service import LearningService
from .learning_setup import LearningSetupService
from .measurements import MeasurementService
from .review import ReviewService
from .state_derivation import StateDerivationService
from .verification import VerificationService
from .plan_editor import PlanEditorService
from .plans import PlanService


def auth_service(request: Request) -> AuthService:
    return request.app.state.auth


def conversation_service(request: Request) -> ConversationService:
    return request.app.state.conversations


def ai_run_manager(request: Request) -> AiRunManager:
    return request.app.state.ai_runs


def plan_service(request: Request) -> PlanService:
    return request.app.state.plans


def plan_editor_service(request: Request) -> PlanEditorService:
    return request.app.state.plan_editor


def layout_service(request: Request) -> LayoutService:
    return request.app.state.layouts


def learning_service(request: Request) -> LearningService:
    return request.app.state.learning


def learning_setup_service(request: Request) -> LearningSetupService:
    return request.app.state.learning_setup


def agent_runtime(request: Request) -> AgentRuntime:
    return request.app.state.agent_runtime


def evidence_service(request: Request) -> EvidenceService:
    return request.app.state.evidence


def state_derivation_service(request: Request) -> StateDerivationService:
    return request.app.state.state_derivation


def evidence_event_service(request: Request) -> EvidenceEventService:
    return request.app.state.evidence_events


def evidence_provider_service(request: Request) -> EvidenceProviderService:
    return request.app.state.evidence_provider


def measurement_service(request: Request) -> MeasurementService:
    return request.app.state.measurements


def verification_service(request: Request) -> VerificationService:
    return request.app.state.verification


def review_service(request: Request) -> ReviewService:
    return request.app.state.review


def current_identity(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    session = request.cookies.get(settings.cookie_name)
    identity = auth_service(request).identity_for_session(session)
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要先完成本地授权",
        )
    return identity
