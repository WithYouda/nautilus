from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request

from ..credentials import CredentialError
from ..dependencies import current_identity
from ..search_adapters import SearchError
from ..search_service import SearchConflict

router = APIRouter(prefix="/api/search")


async def _payload(request):
    # Do not let schema validation echo credentials or scripts in a 422 response.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 512 * 1024:
            raise HTTPException(413, "搜索设置超过大小限制")
    try:
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise ValueError()
        return parsed
    except (ValueError, TypeError, UnicodeDecodeError):
        raise HTTPException(422, "搜索请求格式不正确") from None


def _error(error):
    raise HTTPException(409 if isinstance(error, SearchConflict) else 400,
                        str(error) if isinstance(error, SearchError) else "搜索凭据存储不可用") from None


@router.get("/catalog")
def catalog(request: Request, identity=Depends(current_identity)):
    return request.app.state.search.catalog()


@router.get("/settings")
def settings(request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.search.get(identity["id"])
    except (SearchError, CredentialError) as error:
        _error(error)


@router.put("/settings")
async def save_settings(request: Request, identity=Depends(current_identity)):
    payload = await _payload(request)
    try:
        return request.app.state.search.save(identity["id"], payload)
    except (SearchError, CredentialError) as error:
        _error(error)


async def _test(request, identity, fetch=False):
    payload = await _payload(request)
    try:
        result = await request.app.state.search.test(identity["id"], payload, fetch=fetch)
        return {"ok": True, "result": result}
    except (SearchError, CredentialError) as error:
        return {"ok": False, "kind": getattr(error, "kind", "credential_error"),
                "message": str(error) if isinstance(error, SearchError) else "搜索凭据存储不可用"}


@router.post("/test")
async def test_search(request: Request, identity=Depends(current_identity)):
    return await _test(request, identity)


@router.post("/scrape")
async def test_scrape(request: Request, identity=Depends(current_identity)):
    return await _test(request, identity, True)
