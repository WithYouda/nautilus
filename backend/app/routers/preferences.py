from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..credentials import CredentialError
from ..dependencies import current_identity
from ..preferences import PreferencesError
from ..search_adapters import SearchError

router = APIRouter(prefix="/api/preferences")


@router.get("")
def get_preferences(request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.preferences.get(identity["id"])
    except (PreferencesError, SearchError, CredentialError):
        raise HTTPException(400, "学习设置无法读取") from None


@router.put("")
async def save_preferences(request: Request, identity=Depends(current_identity)):
    # Size cap and generic parse errors avoid echoing any submitted search data.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 32 * 1024:
            raise HTTPException(413, "学习设置超过大小限制")
    try:
        import json
        payload = json.loads(body)
        return request.app.state.preferences.save(identity["id"], payload)
    except (ValueError, TypeError, SearchError):
        raise HTTPException(422, "学习设置格式或选项不正确") from None
    except CredentialError:
        raise HTTPException(503, "学习设置暂时无法保存") from None
