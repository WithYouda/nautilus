from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, status

from .auth import AuthService
from .ai_runtime import AiRunManager
from .conversations import ConversationService
from .layouts import LayoutService
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
