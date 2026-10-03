from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ..dependencies import current_identity
from ..learning_domain import DomainError

router = APIRouter(prefix='/api/material-ocr')
Kind = Literal['conversation', 'discussion']


class OCRSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider_profile_id: str | None
    provider_model_id: str | None


class ReviewedPage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    number: int = Field(ge=1)
    text: str


class Review(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pages: list[ReviewedPage]
    acknowledge_incomplete: StrictBool = False


def fail(error):
    raise HTTPException(error.status, detail=error.code) from error


@router.get('/settings')
def settings(request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.material_ocr.settings(identity['id'])
    except DomainError as error:
        fail(error)


@router.put('/settings')
def save_settings(payload: OCRSettings, request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.material_ocr.save_settings(identity['id'], payload.provider_profile_id, payload.provider_model_id)
    except DomainError as error:
        fail(error)


@router.get('/{kind}/{scope_id}/versions/{version_id}')
def get_ocr(kind: Kind, scope_id: str, version_id: str, request: Request, job_id: str | None = None, identity=Depends(current_identity)):
    try:
        return request.app.state.material_ocr.get(identity, kind, scope_id, version_id, job_id)
    except DomainError as error:
        fail(error)


@router.post('/{kind}/{scope_id}/versions/{version_id}')
async def start_ocr(kind: Kind, scope_id: str, version_id: str, request: Request, identity=Depends(current_identity)):
    try:
        return await request.app.state.material_ocr.start(identity, kind, scope_id, version_id)
    except DomainError as error:
        fail(error)


@router.post('/{kind}/{scope_id}/versions/{version_id}/{job_id}/cancel')
def cancel_ocr(kind: Kind, scope_id: str, version_id: str, job_id: str, request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.material_ocr.cancel(identity, kind, scope_id, version_id, job_id)
    except DomainError as error:
        fail(error)


@router.post('/{kind}/{scope_id}/versions/{version_id}/{job_id}/confirm')
def confirm_ocr(kind: Kind, scope_id: str, version_id: str, job_id: str, payload: Review,
                request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.material_ocr.confirm(identity, kind, scope_id, version_id, job_id,
            [page.model_dump() for page in payload.pages], payload.acknowledge_incomplete)
    except DomainError as error:
        fail(error)
