from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from typing import Literal

from ..dependencies import current_identity
from ..outbound import ApprovalError

router = APIRouter(prefix='/api/outbound')


class Decision(BaseModel):
    digest: str
    decision: Literal['approve', 'deny', 'cancel']


@router.get('/requests')
async def pending(request: Request, response: Response, kind: Literal['conversation', 'discussion'],
            scope_id: str, identity=Depends(current_identity)):
    response.headers['Cache-Control'] = 'no-store'
    return {'items': request.app.state.outbound.list(identity['id'], kind, scope_id)}


@router.post('/requests/{request_id}/decision')
async def decide(request_id: str, payload: Decision, request: Request, response: Response,
           identity=Depends(current_identity)):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return request.app.state.outbound.decide(identity['id'], request_id, payload.digest, payload.decision)
    except ApprovalError as error:
        raise HTTPException(error.status, str(error)) from None
