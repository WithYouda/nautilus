from typing import Literal
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..dependencies import current_identity
from ..learning_domain import DomainError
from ..purge_storage import receipt_path
from ..managed_purge import EXTERNAL_LIMITS

router = APIRouter(prefix='/api/materials')
ScopeKind = Literal['conversation', 'discussion']


class MaterialCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str | None = Field(default=None, max_length=30000)
    material_id: str | None = None
    web_run_id: str | None = None
    web_item_index: int | None = Field(default=None, ge=0)


def fail(error):
    raise HTTPException(status_code=error.status, detail=error.code) from error


@router.get('/{scope_kind}/{scope_id}')
def list_materials(scope_kind: ScopeKind, scope_id: str, request: Request, identity=Depends(current_identity)):
    try:
        service = request.app.state.materials
        with service.lock:
            return service.list(identity, scope_kind, scope_id)
    except DomainError as error:
        fail(error)


@router.post('/{scope_kind}/{scope_id}', status_code=201)
def create_material(scope_kind: ScopeKind, scope_id: str, payload: MaterialCreate,
                    request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.materials.create(identity, scope_kind, scope_id, **payload.model_dump())
    except DomainError as error:
        fail(error)


@router.post('/{scope_kind}/{scope_id}/{material_id}/purge')
async def purge_material(scope_kind: ScopeKind, scope_id: str, material_id: str,
                         request: Request, identity=Depends(current_identity)):
    try:
        service = request.app.state.materials
        # Complete the DB barrier and cache invalidation before yielding to a
        # provider task or stream subscriber in this event loop.
        with service.lock:
            versions = service.list(identity, scope_kind, scope_id)['versions']
            if not any(item['material_id'] == material_id for item in versions):
                raise DomainError('not_found', 404)
            result = service.purge(identity, material_id)
            request.app.state.ai_runs.forget_material_runs(result['affected_run_ids'])
            request.app.state.discussions.forget_purged_turns()
            return result
    except DomainError as error:
        fail(error)


@router.get('/{scope_kind}/{scope_id}/{material_id}/purge')
def purge_status(scope_kind: ScopeKind, scope_id: str, material_id: str,
                 request: Request, identity=Depends(current_identity)):
    try:
        service = request.app.state.materials
        with service.lock:
            versions = service.list(identity, scope_kind, scope_id)['versions']
            if not any(item['material_id'] == material_id for item in versions):
                raise DomainError('not_found', 404)
            path = receipt_path(service.db.database_path, identity['id'], 'material', material_id)
            if not path.exists():
                return dict(status='not_requested', files=[], external_limits=EXTERNAL_LIMITS)
            report = json.loads(path.read_text())
            return {key: report[key] for key in ('status', 'files', 'external_limits', 'updated_at')}
    except DomainError as error:
        fail(error)
