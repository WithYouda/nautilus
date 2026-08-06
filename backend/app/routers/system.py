from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from .. import __version__

router = APIRouter(prefix="/api")


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    database = request.app.state.database
    database.fetchone("SELECT 1")
    return {
        "status": "ok",
        "service": "nautilus",
        "version": __version__,
        "database": "ok",
    }
