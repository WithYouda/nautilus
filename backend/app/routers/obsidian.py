from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from ..credentials import CredentialError
from ..dependencies import current_identity
from ..learning_domain import DomainError

router = APIRouter(prefix='/api/obsidian')
ScopeKind = Literal['conversation', 'discussion']


class ConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    root_path: str = Field(min_length=1, max_length=4096)
    expected_revision: int | None = None


class DisconnectRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    connection_id: str = Field(min_length=1, max_length=64)
    connection_revision: int
    query: str = Field(default='', max_length=500)
    after: str | None = Field(default=None, max_length=4096)


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    selection_token: str = Field(min_length=1, max_length=200)


def no_store(response: Response) -> None:
    response.headers['Cache-Control'] = 'no-store'


def fail(error) -> None:
    if isinstance(error, CredentialError):
        error = DomainError('obsidian_connection_unreadable', 503)
    raise HTTPException(status_code=error.status, detail=error.code) from error


@router.get('/connection')
def get_connection(request: Request, identity=Depends(current_identity),
                   _store: None = Depends(no_store)):
    try:
        return {'connection': request.app.state.obsidian.connection(identity['id'])}
    except (DomainError, CredentialError) as error:
        fail(error)


@router.put('/connection')
async def save_connection(payload: ConnectionUpdate, request: Request, identity=Depends(current_identity),
                          _store: None = Depends(no_store)):
    try:
        service = request.app.state.obsidian
        connection = await run_in_threadpool(service.connect, identity['id'], payload.root_path,
                                            payload.expected_revision)
        return {'connection': connection}
    except (DomainError, CredentialError) as error:
        fail(error)


@router.post('/connection/disconnect')
async def disconnect(payload: DisconnectRequest, request: Request, identity=Depends(current_identity),
                     _store: None = Depends(no_store)):
    try:
        service = request.app.state.obsidian
        connection = await run_in_threadpool(service.disconnect, identity['id'], payload.expected_revision)
        return {'connection': connection}
    except (DomainError, CredentialError) as error:
        fail(error)


@router.post('/{kind}/{scope_id}/search')
async def search(kind: ScopeKind, scope_id: str, payload: SearchRequest, request: Request,
                 identity=Depends(current_identity), _store: None = Depends(no_store)):
    try:
        service = request.app.state.obsidian
        return await run_in_threadpool(
            service.search, identity, kind, scope_id, connection_id=payload.connection_id,
            connection_revision=payload.connection_revision, query=payload.query, after=payload.after)
    except (DomainError, CredentialError) as error:
        fail(error)


@router.post('/{kind}/{scope_id}/capture', status_code=201)
async def capture(kind: ScopeKind, scope_id: str, payload: CaptureRequest, request: Request,
                  identity=Depends(current_identity), _store: None = Depends(no_store)):
    try:
        service = request.app.state.obsidian
        return await run_in_threadpool(service.capture, identity, kind, scope_id,
                                       selection_token=payload.selection_token)
    except (DomainError, CredentialError) as error:
        fail(error)


@router.get('/{kind}/{scope_id}/versions/{version_id}/source-status')
async def source_status(kind: ScopeKind, scope_id: str, version_id: str, request: Request,
                        identity=Depends(current_identity), _store: None = Depends(no_store)):
    try:
        service = request.app.state.obsidian
        return await run_in_threadpool(service.source_status, identity, kind, scope_id, version_id)
    except (DomainError, CredentialError) as error:
        fail(error)
