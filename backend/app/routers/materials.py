from typing import Literal
import json
from urllib.parse import unquote, quote
from pathlib import PurePath

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..dependencies import current_identity
from ..learning_domain import DomainError
from ..purge_storage import receipt_path
from ..managed_purge import EXTERNAL_LIMITS
from ..material_files import extract_material_text

router = APIRouter(prefix='/api/materials')
ScopeKind = Literal['conversation', 'discussion']


class MaterialCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str | None = None
    material_id: str | None = None
    web_run_id: str | None = None
    web_item_index: int | None = Field(default=None, ge=0)


def fail(error):
    raise HTTPException(status_code=error.status, detail=error.code) from error


class LibraryChoice(BaseModel):
    version_id: str


@router.get('/library')
def library(request: Request, identity=Depends(current_identity)):
    return request.app.state.materials.library(identity)


def finish_purge(request, identity, material_id):
    result = request.app.state.materials.purge(identity, material_id)
    report = result['purge']
    request.app.state.diagnostics.record(identity['id'], module='materials', event='material.purge',
        level='info' if report['status'] == 'complete' else 'warning',
        request_id=request.state.diagnostic_id, result=report['status'],
        cleared_count=sum(item['status'] == 'cleared' for item in report['files']),
        failed_count=sum(item['status'] == 'failed' for item in report['files']))
    request.app.state.ai_runs.forget_material_runs(result['affected_run_ids'])
    request.app.state.discussions.forget_purged_turns()
    return result


@router.post('/library/{material_id}/remove')
def remove_from_library(material_id: str, request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.materials.remove_from_library(identity, material_id)
    except DomainError as error:
        fail(error)


@router.post('/library/{material_id}/purge')
async def purge_library_material(material_id: str, request: Request, identity=Depends(current_identity)):
    try:
        service = request.app.state.materials
        with service.lock:
            owner = service.learning.principal(identity).owner_id
            if not service.in_library(owner, material_id):
                raise DomainError('material_not_found', 404)
            return finish_purge(request, identity, material_id)
    except DomainError as error:
        fail(error)


@router.post('/{scope_kind}/{scope_id}/{material_id}/library')
def store_in_library(scope_kind: ScopeKind, scope_id: str, material_id: str,
                     request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.materials.store_in_library(identity, scope_kind, scope_id, material_id)
    except DomainError as error:
        fail(error)


@router.post('/{scope_kind}/{scope_id}/library-use')
def use_library(scope_kind: ScopeKind, scope_id: str, payload: LibraryChoice,
                request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.materials.use_library(identity, scope_kind, scope_id, payload.version_id)
    except DomainError as error:
        fail(error)


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


@router.post('/{scope_kind}/{scope_id}/upload', status_code=201)
async def upload_material(scope_kind: ScopeKind, scope_id: str, request: Request,
                          material_id: str | None = None, identity=Depends(current_identity)):
    try:
        service = request.app.state.materials
        # Resolve ownership before reading or parsing untrusted bytes.
        with service.lock:
            service.owned_scope(identity, scope_kind, scope_id)
        name = PurePath(unquote(request.headers.get('x-filename', '')).replace('\\', '/')).name
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
        content = await run_in_threadpool(extract_material_text, name, bytes(raw))
        media_type = ('application/pdf' if name.lower().endswith('.pdf') else
                      'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                      if name.lower().endswith('.docx') else 'text/plain')
        return await run_in_threadpool(service.create, identity, scope_kind, scope_id,
                                      title=name, content=content, material_id=material_id,
                                      original=(bytes(raw), name, media_type))
    except DomainError as error:
        fail(error)


@router.get('/{scope_kind}/{scope_id}/versions/{version_id}/original')
def material_original(scope_kind: ScopeKind, scope_id: str, version_id: str,
                      request: Request, identity=Depends(current_identity)):
    try:
        service = request.app.state.materials
        with service.lock:
            original = service.original(identity, scope_kind, scope_id, version_id)
            return Response(original['content'], media_type='application/octet-stream', headers={
                'Content-Disposition': "attachment; filename*=UTF-8''" + quote(original['filename'], safe=''),
                'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            })
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
            return finish_purge(request, identity, material_id)
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
