import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from ..dependencies import current_identity
from ..branch_comparisons import ComparisonError
from ..conversations import ConversationError
from ..learning_domain import DomainError
from ..providers import ProviderError
from ..credentials import CredentialError


def private(response: Response):
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/api/branch-comparisons', dependencies=[Depends(private)])


class Compare(BaseModel):
    other_id: str = Field(min_length=1, max_length=200)


class Selection(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)


class Confirm(BaseModel):
    preview_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=60)
    selected: list[Selection] = Field(min_length=1)


def error(exc):
    if isinstance(exc, (ComparisonError, DomainError)):
        raise HTTPException(exc.status, str(exc)) from None
    if isinstance(exc, CredentialError):
        raise HTTPException(503, '模型配置暂时无法读取。') from None
    raise HTTPException(400, str(exc)) from None


@router.get('/{kind}/{identifier}/sources')
def sources(kind: str, identifier: str, other_id: str, request: Request, identity=Depends(current_identity)):
    try:
        result = request.app.state.branch_comparisons.sources(identity, kind, identifier, other_id)
        return [dict(id=s['id'], leaf_id=s['leaf_id'], last_question=s['last_question']) for s in result]
    except (ComparisonError, ConversationError, DomainError, CredentialError) as exc:
        error(exc)


@router.post('/{kind}/{identifier}/previews')
async def preview(kind: str, identifier: str, payload: Compare, request: Request, identity=Depends(current_identity)):
    async def disconnected():
        while True:
            if (await request.receive())['type'] == 'http.disconnect':
                return
    operation = asyncio.create_task(request.app.state.branch_comparisons.preview(identity, kind, identifier, payload.other_id))
    watcher = asyncio.create_task(disconnected())
    try:
        completed, _ = await asyncio.wait({operation, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if operation not in completed:
            raise HTTPException(499, '比较已取消。')
        return await operation
    except (ComparisonError, ConversationError, DomainError, CredentialError, ProviderError) as exc:
        error(exc)
    finally:
        for task in (operation, watcher):
            if not task.done():
                task.cancel()
        await asyncio.gather(operation, watcher, return_exceptions=True)


@router.post('/confirm')
def confirm(payload: Confirm, request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.branch_comparisons.confirm(identity, payload.preview_id, payload.title,
                                                            [item.model_dump() for item in payload.selected])
    except (ComparisonError, ConversationError, DomainError, CredentialError) as exc:
        error(exc)
