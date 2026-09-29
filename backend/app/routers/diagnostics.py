from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, StrictBool
from ..dependencies import current_identity

router = APIRouter(prefix='/api/diagnostics')


class Configuration(BaseModel):
    enabled: StrictBool


@router.get('/settings')
def settings(request: Request, identity=Depends(current_identity)):
    return request.app.state.diagnostics.status(identity['id'])


@router.put('/settings')
def configure(payload: Configuration, request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.diagnostics.configure(identity['id'], payload.enabled)
    except OSError:
        raise HTTPException(503, '诊断日志设置未保存，请检查本机存储后重试。') from None


@router.get('')
def entries(request: Request, identity=Depends(current_identity)):
    return request.app.state.diagnostics.read(identity['id'])


@router.delete('')
def clear(request: Request, identity=Depends(current_identity)):
    try:
        request.app.state.diagnostics.clear(identity['id'])
        return {'cleared': True}
    except OSError:
        raise HTTPException(503, '日志未能全部清空，请重试。') from None
