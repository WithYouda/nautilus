from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..adaptive_preferences import AdaptivePreferencesError
from ..credentials import CredentialError
from ..dependencies import current_identity


def _private_response(response: Response):
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/api/adaptive-learning', dependencies=[Depends(_private_response)])


def _error(error):
    messages = {404: '这项偏好或来源已不可用，请刷新后重试。',
                409: '偏好已变化或请求已使用，请刷新后重试。',
                422: '偏好设置格式或选项不正确。',
                503: '个人学习偏好暂时无法读取或保存。'}
    status = error.status_code if isinstance(error, AdaptivePreferencesError) else 503
    raise HTTPException(status, messages[status]) from None


@router.get('')
def get_preferences(request: Request, identity=Depends(current_identity)):
    try:
        return request.app.state.adaptive_preferences.get(identity['id'])
    except (AdaptivePreferencesError, CredentialError) as error:
        _error(error)


@router.post('/changes')
async def change_preferences(request: Request, identity=Depends(current_identity)):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 8 * 1024:
            raise HTTPException(413, '偏好设置超过大小限制。')
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        raise HTTPException(422, '偏好设置格式或选项不正确。') from None
    try:
        return request.app.state.adaptive_preferences.change(identity['id'], payload)
    except (AdaptivePreferencesError, CredentialError) as error:
        _error(error)
