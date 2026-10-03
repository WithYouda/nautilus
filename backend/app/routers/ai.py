from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, StrictBool

from ..ai_runtime import AiRunManager
from ..conversations import ConversationConflict, ConversationError
from ..dependencies import ai_run_manager, conversation_service, current_identity
from ..providers import ProviderError, build_provider
from ..schemas import (
    ConversationConfigRequest,
    ConversationCreateRequest,
    ConversationBranchRequest,
    ConversationUpdateRequest,
    ModelManualRequest,
    MessageSendRequest,
    HelpDisplayRequest,
    TeachingAttemptCorrectionRequest,
    LearningObservationCorrectionRequest,
    ProviderModelsRequest,
    ProviderCreateRequest,
    ProviderSaveRequest,
    ProviderTestRequest,
    ProviderUpdateRequest,
)

router = APIRouter(prefix="/api/ai")

# SSE 经过 vite preview 代理时必须禁用缓冲，否则增量会被攒着一次性吐出。
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _raise(error: ConversationError) -> None:
    detail = str(error)
    if isinstance(error, ConversationConflict):
        code = status.HTTP_409_CONFLICT
    elif detail.endswith("不存在"):
        code = status.HTTP_404_NOT_FOUND
    else:
        code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=code, detail=detail) from error


# ======================================================================
# 提供方配置：只进出非敏感信息，密钥仅由 CredentialStore 保存
# ======================================================================
@router.get("/provider")
def get_provider(
    request: Request, identity: dict[str, Any] = Depends(current_identity)
) -> dict[str, Any]:
    return {"provider": conversation_service(request).provider_public(identity["id"])}


@router.get("/providers")
def list_providers(request: Request, identity: dict[str, Any] = Depends(current_identity)) -> list[dict[str, Any]]:
    return conversation_service(request).list_providers(identity["id"])


@router.post("/providers", status_code=status.HTTP_201_CREATED)
def create_provider(
    payload: ProviderCreateRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        provider = conversation_service(request).create_provider(
            identity["id"], display_name=payload.display_name, base_url=payload.base_url,
            model=payload.model, api_key=payload.api_key, enabled=payload.enabled,
            is_default=payload.is_default, request_timeout_seconds=payload.request_timeout_seconds,
            api_protocol=payload.api_protocol,
        )
    except ConversationError as error:
        _raise(error)
    return {"provider": provider}


@router.patch("/providers/{provider_id}")
def update_provider(
    provider_id: str,
    payload: ProviderUpdateRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        provider = conversation_service(request).update_provider(
            identity["id"], provider_id, **payload.model_dump(exclude_unset=True)
        )
    except ConversationError as error:
        _raise(error)
    return {"provider": provider}


@router.post("/providers/{provider_id}/default")
def make_default_provider(
    provider_id: str,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return {"provider": conversation_service(request).set_default_provider(identity["id"], provider_id)}
    except ConversationError as error:
        _raise(error)


@router.post("/providers/{provider_id}/test")
async def test_provider_profile(
    provider_id: str,
    request: Request,
    payload: ProviderTestRequest | None = None,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = conversation_service(request)
    try:
        profile, config = service.provider_profile_form_runtime(
            identity["id"], provider_id,
            base_url=payload.base_url if payload else None,
            model=payload.model if payload else None,
            api_key=payload.api_key if payload else None,
            request_timeout_seconds=payload.request_timeout_seconds if payload else None,
            api_protocol=payload.api_protocol if payload else None,
        )
    except ConversationError as error:
        _raise(error)
    manager: AiRunManager = ai_run_manager(request)
    provider = build_provider(config, transport=manager.transport)
    record_result = bool(
        not (payload and payload.api_key)
        and profile["base_url"] == config.base_url
        and profile["model"] == config.model
        and service._protocol(profile, config.model) == config.provider_kind
        and int(profile["request_timeout_seconds"]) == config.timeout_seconds
    )
    try:
        result = await provider.test_connection()
    except ProviderError as error:
        if record_result:
            service.record_provider_test(profile["id"], "failed", str(error))
        return {"ok": False, "kind": error.kind, "message": str(error), "provider": service.provider_public_by_id(identity["id"], provider_id)}
    if record_result:
        service.record_provider_test(profile["id"], "succeeded", None)
    return {
        "ok": True,
        "model": result["model"],
        "latency_ms": result["latency_ms"],
        "provider": service.provider_public_by_id(identity["id"], provider_id),
    }


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider_by_id(
    provider_id: str,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> Response:
    try:
        conversation_service(request).delete_provider_by_id(identity["id"], provider_id)
    except ConversationError as error:
        _raise(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/providers/{provider_id}/models")
def list_provider_models(
    provider_id: str,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> list[dict[str, Any]]:
    try:
        return conversation_service(request).list_models(identity["id"], provider_id)
    except ConversationError as error:
        _raise(error)


class ImageCapabilityRequest(BaseModel):
    supports_image_input: StrictBool | None


@router.get('/providers/{provider_id}/models/{model_id}/teaching-support')
def teaching_support(provider_id: str, model_id: str, request: Request, identity=Depends(current_identity)):
    from ..teaching_capability import status as teaching_status
    try:
        return teaching_status(conversation_service(request), identity['id'], provider_id, model_id)
    except ConversationError as error:
        _raise(error)


@router.post('/providers/{provider_id}/models/{model_id}/teaching-support/check')
async def check_teaching_support(provider_id: str, model_id: str, request: Request, identity=Depends(current_identity)):
    from ..teaching_capability import check
    try:
        return await check(conversation_service(request), identity['id'], provider_id, model_id,
                           transport=ai_run_manager(request).transport)
    except ConversationError as error:
        _raise(error)


@router.put('/providers/{provider_id}/models/{model_id}/image-capability')
def set_image_capability(provider_id: str, model_id: str, payload: ImageCapabilityRequest,
                         request: Request, identity=Depends(current_identity)):
    try:
        return {'model': conversation_service(request).set_image_capability(
            identity['id'], provider_id, model_id, payload.supports_image_input)}
    except ConversationError as error:
        _raise(error)


@router.post("/providers/{provider_id}/models/manual", status_code=status.HTTP_201_CREATED)
def add_provider_model(
    provider_id: str,
    payload: ModelManualRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        model = conversation_service(request).add_manual_model(
            identity["id"], provider_id, model_id=payload.model_id, display_name=payload.display_name
        )
    except ConversationError as error:
        _raise(error)
    return {"model": model}


@router.put("/provider")
def save_provider(
    payload: ProviderSaveRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        provider = conversation_service(request).save_provider(
            identity["id"],
            display_name=payload.display_name,
            base_url=payload.base_url,
            model=payload.model,
            api_key=payload.api_key,
            enabled=payload.enabled,
            request_timeout_seconds=payload.request_timeout_seconds,
            api_protocol=payload.api_protocol,
        )
    except ConversationError as error:
        _raise(error)
    return {"provider": provider}


@router.delete("/provider", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(
    request: Request, identity: dict[str, Any] = Depends(current_identity)
) -> Response:
    try:
        conversation_service(request).delete_provider(identity["id"])
    except ConversationError as error:
        _raise(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/provider/test")
async def test_provider(
    request: Request,
    payload: ProviderTestRequest | None = None,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = conversation_service(request)
    try:
        if payload is None:
            profile, config = service.provider_runtime(identity["id"])
        else:
            profile, config = service.provider_form_runtime(
                identity["id"],
                base_url=payload.base_url,
                model=payload.model,
                api_key=payload.api_key,
                request_timeout_seconds=payload.request_timeout_seconds,
                api_protocol=payload.api_protocol,
            )
            if not config.model:
                raise ConversationError("模型名称不能为空")
    except ConversationError as error:
        _raise(error)
    manager: AiRunManager = ai_run_manager(request)
    provider = build_provider(config, transport=manager.transport)
    record_result = bool(
        profile
        and not (payload and payload.api_key)
        and profile["base_url"] == config.base_url
        and profile["model"] == config.model
        and service._protocol(profile, config.model) == config.provider_kind
        and int(profile["request_timeout_seconds"]) == config.timeout_seconds
    )
    try:
        result = await provider.test_connection()
    except ProviderError as error:
        if record_result:
            service.record_provider_test(profile["id"], "failed", str(error))
        return {
            "ok": False,
            "kind": error.kind,
            "message": str(error),
            "provider": service.provider_public(identity["id"]),
        }
    if record_result:
        service.record_provider_test(profile["id"], "succeeded", None)
    return {
        "ok": True,
        "model": result["model"],
        "latency_ms": result["latency_ms"],
        "provider": service.provider_public(identity["id"]),
    }


@router.post("/provider/models")
async def discover_provider_models(
    payload: ProviderModelsRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = conversation_service(request)
    try:
        _profile, config = service.provider_form_runtime(
            identity["id"],
            base_url=payload.base_url,
            api_key=payload.api_key,
            request_timeout_seconds=payload.request_timeout_seconds,
            api_protocol=payload.api_protocol,
        )
        models, cached = await request.app.state.model_discovery.discover(
            identity["id"], config, force_refresh=payload.force_refresh
        )
    except ConversationError as error:
        _raise(error)
    except ProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"kind": error.kind, "message": str(error)},
        ) from error
    return {"models": models, "cached": cached, "ttl_seconds": 600}


@router.post("/providers/{provider_id}/models/discover")
async def discover_provider_profile_models(
    provider_id: str,
    payload: ProviderModelsRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = conversation_service(request)
    try:
        profile, config = service.provider_profile_form_runtime(
            identity["id"], provider_id, base_url=payload.base_url,
            api_key=payload.api_key, request_timeout_seconds=payload.request_timeout_seconds,
            api_protocol=payload.api_protocol,
        )
        models, cached = await request.app.state.model_discovery.discover(
            identity["id"], config, force_refresh=payload.force_refresh
        )
        return {"models": service.discover_models(identity["id"], provider_id, models), "cached": cached, "ttl_seconds": 600}
    except ConversationError as error:
        _raise(error)
    except ProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"kind": error.kind, "message": str(error)},
        ) from error


# ======================================================================
# 对话
# ======================================================================
@router.get("/context")
def context_preview(
    request: Request,
    scope: str = Query(pattern="^(independent|global|plan|task)$"),
    target_id: str | None = Query(default=None, max_length=64),
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any] | None:
    try:
        return conversation_service(request).context_preview(
            identity["id"], scope, target_id
        )
    except ConversationError as error:
        _raise(error)


@router.get("/conversations")
def list_conversations(
    request: Request, identity: dict[str, Any] = Depends(current_identity)
) -> list[dict[str, Any]]:
    return conversation_service(request).list_conversations(identity["id"])


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreateRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return conversation_service(request).create_conversation(
            identity["id"],
            title=payload.title,
            task_id=payload.task_id,
            context_scope=payload.context_scope,
            target_id=payload.target_id,
        )
    except ConversationError as error:
        _raise(error)


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return conversation_service(request).conversation_detail(identity["id"], conversation_id)
    except ConversationError as error:
        _raise(error)


@router.patch("/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: str,
    payload: ConversationUpdateRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return conversation_service(request).rename_conversation(
            identity["id"], conversation_id, payload.title
        )
    except ConversationError as error:
        _raise(error)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> Response:
    try:
        conversation_service(request).delete_conversation(identity["id"], conversation_id)
        request.app.state.material_ocr.forget_purged()
    except ConversationError as error:
        _raise(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/conversations/{conversation_id}/config")
def get_conversation_config(
    conversation_id: str,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return {"config": conversation_service(request).conversation_config_public(identity["id"], conversation_id)}
    except ConversationError as error:
        _raise(error)


@router.put("/conversations/{conversation_id}/config")
def set_conversation_config(
    conversation_id: str,
    payload: ConversationConfigRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        config = conversation_service(request).set_conversation_config(
            identity["id"], conversation_id,
            provider_id=payload.provider_profile_id,
            model_id=payload.provider_model_id,
            timeout_override_seconds=payload.timeout_override_seconds,
        )
    except ConversationError as error:
        _raise(error)
    return {"config": config}


@router.delete("/conversations/{conversation_id}/config", status_code=status.HTTP_204_NO_CONTENT)
def clear_conversation_config(
    conversation_id: str,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> Response:
    try:
        conversation_service(request).clear_conversation_config(identity["id"], conversation_id)
    except ConversationError as error:
        _raise(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/conversations/{conversation_id}/title/regenerate",
    status_code=status.HTTP_202_ACCEPTED,
)
async def regenerate_conversation_title(
    conversation_id: str,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    manager: AiRunManager = ai_run_manager(request)
    try:
        title_run = await manager.start_title_regeneration(identity["id"], conversation_id)
    except ConversationError as error:
        _raise(error)
    return {"title_run": title_run}


@router.get("/conversations/{conversation_id}/title-run")
def get_conversation_title_run(
    conversation_id: str,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        title_run = conversation_service(request).latest_title_run(identity["id"], conversation_id)
    except ConversationError as error:
        _raise(error)
    return {"title_run": title_run}


@router.get("/tasks/{task_id}/context")
def task_context(
    task_id: str,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return conversation_service(request).task_context(identity["id"], task_id)
    except ConversationError as error:
        _raise(error)


# ======================================================================
# 发送、流式与取消
# ======================================================================
def _public_run(run):
    # Protocol continuations contain opaque reasoning/signatures for the provider,
    # not a public response field. Keep the existing run metadata contract.
    clean = dict(run)
    if clean.get('config_snapshot_json'):
        import json
        snapshot = json.loads(clean['config_snapshot_json'])
        snapshot.pop('model_turn', None)
        clean['config_snapshot_json'] = json.dumps(snapshot, ensure_ascii=False)
    return clean


@router.post("/conversations/{conversation_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_message(
    conversation_id: str,
    payload: MessageSendRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    """写入用户消息并在后台启动生成。重复的 client_message_id 只会命中已有运行。"""
    manager: AiRunManager = ai_run_manager(request)
    try:
        started = await manager.start(
            identity["id"],
            conversation_id,
            content=payload.content,
            client_message_id=payload.client_message_id,
            regenerate_message_id=payload.regenerate_message_id,
            parent_message_id=payload.parent_message_id,
            edit_message_id=payload.edit_message_id,
            search=payload.search,
            public_search_query=payload.public_search_query,
            help_request=payload.help_request,
            teaching_mode=payload.teaching_mode, teaching_action=payload.teaching_action,
            source_scope=payload.source_scope,
            attachment_version_ids=payload.attachment_version_ids,
            current_state_revision=payload.current_state_revision,
        )
    except ConversationError as error:
        _raise(error)
    service = conversation_service(request)
    return {
        "run": _public_run(started["run"]),
        "created": started["created"],
        "messages": service.list_messages(identity["id"], conversation_id),
    }


@router.post("/conversations/{conversation_id}/messages/{message_id}/help-display")
def record_help_display(
    conversation_id: str,
    message_id: str,
    payload: HelpDisplayRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return conversation_service(request).record_help_display(identity["id"], conversation_id, message_id, payload.characters)
    except ConversationError as error:
        _raise(error)


@router.post('/conversations/{conversation_id}/messages/{message_id}/teaching-attempt')
def correct_teaching_attempt(conversation_id: str, message_id: str,
                             payload: TeachingAttemptCorrectionRequest, request: Request,
                             identity: dict[str, Any] = Depends(current_identity)):
    try:
        return conversation_service(request).correct_teaching_attempt(
            identity['id'], conversation_id, message_id, **payload.model_dump(exclude_unset=True))
    except ConversationError as error:
        _raise(error)


@router.post('/conversations/{conversation_id}/messages/{message_id}/learning-observation')
def correct_learning_observation(conversation_id: str, message_id: str,
                                 payload: LearningObservationCorrectionRequest, request: Request,
                                 identity: dict[str, Any] = Depends(current_identity)):
    try:
        return conversation_service(request).correct_learning_observation(
            identity['id'], conversation_id, message_id, **payload.model_dump())
    except ConversationError as error:
        _raise(error)


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: str,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> StreamingResponse:
    """订阅一次生成。断开或刷新只是退订，后台生成继续跑完，重连可重放。"""
    manager: AiRunManager = ai_run_manager(request)
    try:
        manager.conversations.owned_run(identity["id"], run_id)
    except ConversationError as error:
        _raise(error)
    return StreamingResponse(
        manager.stream(identity["id"], run_id),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    manager: AiRunManager = ai_run_manager(request)
    try:
        run = await manager.cancel(identity["id"], run_id)
    except ConversationError as error:
        _raise(error)
    return {"run": _public_run(run)}


@router.post("/conversations/{conversation_id}/branches", status_code=201)
def branch_conversation(conversation_id: str, payload: ConversationBranchRequest, request: Request,
                        identity=Depends(current_identity)):
    from ..conversation_branches import create_branch
    try:
        return create_branch(conversation_service(request), identity['id'], conversation_id,
                             payload.message_id, payload.request_key)
    except ConversationError as error:
        _raise(error)


@router.get('/conversations/{conversation_id}/branch-map')
def get_conversation_branch_map(conversation_id: str, request: Request, identity=Depends(current_identity)):
    from ..branch_maps import conversation_map
    try:
        return conversation_map(conversation_service(request), identity['id'], conversation_id)
    except ConversationError as error:
        _raise(error)
