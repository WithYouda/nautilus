from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..dependencies import auth_service, current_identity
from ..schemas import AuthorizationRequest

router = APIRouter(prefix="/api")


@router.get("/auth/challenge")
def auth_challenge(request: Request, response: Response) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return {"code": auth_service(request).authorization_challenge()}


@router.get("/auth/status")
def auth_status(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    session = request.cookies.get(settings.cookie_name)
    identity = auth_service(request).identity_for_session(session)
    return {"authenticated": identity is not None, "identity": identity}


@router.post("/auth/authorize")
def authorize(payload: AuthorizationRequest, response: Response, request: Request) -> dict[str, object]:
    result = auth_service(request).authorize(payload.access_token)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="访问令牌无效或已过期",
        )
    session_token, identity = result
    settings = request.app.state.settings
    response.set_cookie(
        key=settings.cookie_name,
        value=session_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.session_cookie_max_age_seconds,
        path="/",
    )
    return {"authenticated": True, "identity": identity}


@router.post("/auth/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    settings = request.app.state.settings
    session = request.cookies.get(settings.cookie_name)
    auth_service(request).revoke_session(session)
    response.delete_cookie(key=settings.cookie_name, path="/")
    return {"authenticated": False}


@router.get("/me")
def me(identity: dict[str, object] = Depends(current_identity)) -> dict[str, object]:
    return identity
