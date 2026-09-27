from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..dependencies import current_identity
from ..learning_domain import DomainError

def _private_response(response: Response):
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/api/conversation-state', dependencies=[Depends(_private_response)])


class CurrentStatePut(BaseModel):
    expected_revision: int = Field(ge=0)
    leaf_id: str | None = None
    paths: dict[str, str] = Field(default_factory=dict)
    source_scope: dict[str, Any] = Field(default_factory=lambda: {'mode': 'unspecified', 'version_ids': []})
    search_override: dict[str, Any] | None = None


def _error(error: DomainError):
    raise HTTPException(status_code=error.status, detail=error.code) from error


@router.get('/{kind}/{scope_id}')
def get_state(kind: Literal['conversation', 'discussion'], scope_id: str, request: Request,
              identity=Depends(current_identity)):
    try:
        return request.app.state.conversation_state.get(identity, kind, scope_id)
    except DomainError as error:
        _error(error)


@router.put('/{kind}/{scope_id}')
def put_state(kind: Literal['conversation', 'discussion'], scope_id: str, payload: CurrentStatePut,
              request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.conversation_state.put(identity, kind, scope_id, payload)
    except DomainError as error:
        _error(error)
