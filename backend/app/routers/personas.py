import json
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError
from ..dependencies import current_identity
from ..credentials import CredentialError
from ..conversations import ConversationError
from ..providers import ProviderError
from ..personas import PersonaError
from ..learning_domain import DomainError


def private(response: Response):
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/api/personas', dependencies=[Depends(private)])


def error(exc):
    if isinstance(exc, DomainError):
        raise HTTPException(exc.status, exc.code) from None
    if isinstance(exc, PersonaError):
        raise HTTPException(exc.status, str(exc)) from None
    if isinstance(exc, ValidationError):
        raise HTTPException(422, '人格文件或配置字段不正确。') from None
    if isinstance(exc, (ConversationError, ProviderError)):
        raise HTTPException(400, str(exc)) from None
    raise HTTPException(503, '人格配置暂时无法读取或保存。') from None


async def body(request):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 64 * 1024:
            raise HTTPException(413, '人格内容过大，请限制在64KB以内。')
    try:
        return json.loads(data)
    except ValueError:
        raise HTTPException(422, '人格格式不正确。') from None


@router.get('')
def get(request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.personas.get(identity['id'])
    except (PersonaError, CredentialError) as exc:
        error(exc)


@router.post('/previews')
async def preview(request: Request, identity=Depends(current_identity)):
    payload = await body(request)
    try:
        return await request.app.state.personas.preview(identity['id'], payload)
    except (PersonaError, CredentialError, ConversationError, ProviderError, ValidationError) as exc:
        error(exc)


@router.post('/changes')
async def change(request: Request, identity=Depends(current_identity)):
    payload = await body(request)
    try:
        return request.app.state.personas.change(identity['id'], payload)
    except (PersonaError, CredentialError, ValidationError) as exc:
        error(exc)


@router.get('/{identifier}/export')
def export(identifier: str, request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.personas.export(identity['id'], identifier)
    except (PersonaError, CredentialError, ValidationError) as exc:
        error(exc)


@router.get('/scopes/{kind}/{scope_id}')
def get_scope(kind: str, scope_id: str, request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.personas.get_scope(identity['id'], kind, scope_id)
    except (PersonaError, CredentialError, DomainError, ConversationError) as exc:
        error(exc)


@router.put('/scopes/{kind}/{scope_id}')
async def set_scope(kind: str, scope_id: str, request: Request, identity=Depends(current_identity)):
    payload = await body(request)
    try:
        return request.app.state.personas.set_scope(identity['id'], kind, scope_id, payload)
    except (PersonaError, CredentialError, DomainError, ConversationError) as exc:
        error(exc)
