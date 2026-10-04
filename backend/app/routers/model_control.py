from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..dependencies import current_identity
from ..conversations import ConversationConflict, ConversationError
from ..learning_domain import DomainError


def _private(response: Response):
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/api/model-config', dependencies=[Depends(_private)])
Kind = Literal['global', 'plan', 'task', 'conversation', 'discussion']


class Preview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    override: dict = Field(default_factory=dict)


class Save(Preview):
    expected_revision: str = Field(min_length=1, max_length=100)


class ReasoningDefault(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: str = Field(min_length=1, max_length=100)
    reasoning: dict | None


@router.put('/global/default/reasoning')
def save_reasoning_default(body: ReasoningDefault, request: Request, identity=Depends(current_identity)):
    return _call(request, identity, lambda service, owner: service.save_reasoning_default(owner, body.reasoning, body.expected_revision))


def _call(request, identity, function):
    owner = request.app.state.learning.principal(identity).owner_id
    try:
        return function(request.app.state.model_control, owner)
    except DomainError as error:
        raise HTTPException(error.status, error.code) from error
    except ConversationError as error:
        raise HTTPException(409 if isinstance(error, ConversationConflict) else 400, str(error)) from error


@router.get('/{kind}/{scope_id}')
def get(kind: Kind, scope_id: str, request: Request, identity=Depends(current_identity)):
    return _call(request, identity, lambda service, owner: service.get(owner, kind, scope_id))


@router.put('/{kind}/{scope_id}')
def save(kind: Kind, scope_id: str, body: Save, request: Request, identity=Depends(current_identity)):
    return _call(request, identity, lambda service, owner: service.save(owner, kind, scope_id, body.override, body.expected_revision))


@router.post('/{kind}/{scope_id}/preview')
def preview(kind: Kind, scope_id: str, body: Preview, request: Request, identity=Depends(current_identity)):
    return _call(request, identity, lambda service, owner: service.get(owner, kind, scope_id, body.override))
