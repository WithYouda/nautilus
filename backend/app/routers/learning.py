from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from ..conversations import ConversationError
from ..dependencies import (
    agent_runtime,
    current_identity,
    evidence_event_service,
    evidence_provider_service,
    evidence_service,
    measurement_service,
    learning_service,
    learning_setup_service,
    review_service,
    state_derivation_service,
    verification_service,
)
from ..learning_domain import DomainError
from ..learning_room import LearningRoomService
from ..schemas import (
    AgentPermissionDenyRequest,
    EvidenceAnalysisRequest,
    EvidenceHumanReviewRequest,
    EvidenceSupplementalVerificationRequest,
    EvidenceProviderSelectionRequest,
    EvidenceClaimReviewRequest,
    EvidenceBatchReviewRequest,
    DerivedStateRecalculateRequest,
    AgentPermissionRequestCreate,
    AgentPermissionRevokeRequest,
    ArtifactLifecycleRequest,
    ArtifactPurgeRequest,
    LearningActionCreateRequest,
    LearningArtifactCorrectRequest,
    LearningArtifactSaveRequest,
    LearningDelegationCreateRequest,
    LearningOutcomeCreateRequest,
    LearningSetupConfirmRequest,
    LearningSetupDraftRequest,
    LearningSessionEndRequest,
    LearningSessionStartRequest,
    LearningVerificationStartRequest,
    LearningVerificationSubmitRequest,
    LearningVerificationEvaluateRequest,
    LearningVerificationConfirmRequest,
    LearningVerificationPurgeRequest,
    LearningRoomConversationRequest,
)

router = APIRouter(prefix="/api/learning")


def _raise_learning_error(error: DomainError) -> None:
    messages = {
        "permission_denied": "当前身份无权访问或修改这条学习事实",
        "permission_request_not_pending": "权限申请已过期或已处理",
        "not_found": "学习事实不存在",
        "version_conflict": "学习事实已更新，请刷新后重试",
        "session_not_running": "学习会话不在进行中",
        "session_already_running": "已有进行中的学习会话",
        "event_integrity_failed": "事实事件校验失败",
        "event_chain_invalid": "事实事件链校验失败",
        "event_gap": "事实事件存在缺口",
        "event_version_unsupported": "事实事件版本不受支持",
        "projection_version_unsupported": "投影版本不受支持",
        "projection_rebuild_incomplete": "事实投影重建不完整",
        "artifact_source_missing": "缺少不可变原始产出",
        "artifact_not_eligible": "原始产出不可用于证据分析",
        "claim_not_candidate": "只有候选主张可以执行该复核动作",
        "claim_not_qualifying": "该主张不满足标准的证据配方",
        "claim_review_invalid_transition": "当前主张状态不支持该复核动作",
        "claim_review_conflict": "主张状态已变化，请刷新后重试",
        "replacement_claim_required": "替代主张必须指定替代关系",
        "replacement_claim_invalid": "替代主张必须属于同一标准和维度",
        "batch_claims_not_homogeneous": "批量采纳的主张必须属于同一标准",
        "artifact_not_visible": "产出当前不可见，不能执行该操作",
        "artifact_not_soft_deleted": "只有普通删除的产出可以恢复",
        "artifact_not_eligible": "产出当前不可撤回",
        "artifact_already_purged": "产出已彻底删除",
        "evidence_event_chain_invalid": "证据事件链校验失败",
        "evidence_event_version_unsupported": "证据事件版本不受支持",
        "evidence_event_integrity_failed": "证据事件完整性校验失败",
        "evidence_event_type_unsupported": "证据事件类型不受支持",
        "evidence_event_payload_invalid": "证据事件内容结构无效",
        "idempotency_conflict": "同一幂等键对应了不同请求",
        "invalid_idempotency_key": "幂等键不合法",
        "criterion_not_approved": "达成标准未通过审核",
        "criterion_out_of_scope": "达成标准不适用于当前成果",
        "criterion_unavailable": "达成标准已失效",
        "criterion_invalid_recipe": "达成标准配方不合法",
        "action_not_open": "学习行动不在待执行状态",
        "delegation_not_startable": "学习委托当前不能开始新的学习会话",
        "command_unsupported": "不支持的学习命令",
        "criterion_outcome_required": "选择达成标准时必须使用对应的标准成果",
        "criterion_outcome_mismatch": "所选成果与达成标准不匹配",
        "setup_provider_unavailable": "暂时无法使用 AI 初始化，请先配置可用的 AI 提供方",
        "setup_draft_invalid": "AI 初始化结果不完整，请重试或改为手动开始",
        "verification_provider_unavailable": "当前没有可用的 AI 验证提供方",
        "verification_generation_failed": "AI 验证题目生成失败，请稍后重试",
        "verification_evaluation_failed": "AI 验证评估失败，答案已保留，请稍后重试",
        "verification_invalid": "AI 返回的验证结构不完整，请重试",
        "verification_response_required": "请完成所有验证题目后再提交",
        "verification_material_required": "请先粘贴或上传本次验证材料",
        "verification_scope_invalid": "验证对象与学习任务不匹配",
        "verification_state_conflict": "验证状态已经被另一项提交更新，请刷新后重试",
        "verification_contract_changed": "本次验证的学习约定已变更，请按新约定重新开始验证",
        "verification_already_completed": "本次验证已完成，请先复核下一步学习安排",
        "verification_not_ready": "验证与停止条件尚未全部通过，暂时不能确认完成",
        "verification_learner_work_required": "请单独提交自己的过程、理解或项目结果；参考材料不作为能力证据",
        "verification_session_required": "缺少真实学习会话关联，当前记录不能接入证据链",
        "verification_submission_immutable": "验证提交不可更正，请在验证页提交新的作答",
        "verification_independent_evidence_required": "当前已审核标准要求独立作答；本次有资料或提示帮助的产出保留，但不作为独立能力证据",
    }
    raise HTTPException(
        status_code=error.status,
        detail={
            "kind": error.code,
            "message": messages.get(error.code, "学习事实操作失败"),
        },
    ) from error


@router.get("/state")
def learning_state(
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    return learning_service(request).overview(identity)


@router.post("/setup/draft")
async def learning_setup_draft(
    payload: LearningSetupDraftRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return await learning_setup_service(request).draft(identity, payload.intent)
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/setup/confirm", status_code=status.HTTP_201_CREATED)
def confirm_learning_setup(
    payload: LearningSetupConfirmRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return learning_setup_service(request).confirm(
            identity,
            payload.model_dump(exclude={"idempotency_key"}, mode="json"),
            payload.idempotency_key,
        )
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/actions", status_code=status.HTTP_201_CREATED)
def create_learning_action(
    payload: LearningActionCreateRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = learning_service(request)
    try:
        return service.create_action(
            identity,
            payload.model_dump(exclude={"idempotency_key"}, mode="json"),
            payload.idempotency_key,
        )
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/outcomes", status_code=status.HTTP_201_CREATED)
def create_learning_outcome(
    payload: LearningOutcomeCreateRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = learning_service(request)
    try:
        return service.create_outcome(
            identity,
            payload.model_dump(exclude={"idempotency_key"}, mode="json"),
            payload.idempotency_key,
        )
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/delegations", status_code=status.HTTP_201_CREATED)
def create_learning_delegation(
    payload: LearningDelegationCreateRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = learning_service(request)
    try:
        return service.create_delegation(
            identity,
            payload.model_dump(exclude={"idempotency_key"}, mode="json"),
            payload.idempotency_key,
        )
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def start_learning_session(
    payload: LearningSessionStartRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = learning_service(request)
    try:
        return service.start_session(
            identity,
            payload.model_dump(exclude={"idempotency_key"}, mode="json"),
            payload.idempotency_key,
        )
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/sessions/{session_id}/end")
def end_learning_session(
    session_id: str,
    payload: LearningSessionEndRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = learning_service(request)
    try:
        return service.end_session(
            identity,
            {
                "session_id": session_id,
                **payload.model_dump(exclude={"idempotency_key"}, mode="json"),
            },
            payload.idempotency_key,
        )
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/verifications", status_code=status.HTTP_201_CREATED)
async def start_learning_verification(
    payload: LearningVerificationStartRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return await verification_service(request).start(
            identity,
            payload.model_dump(exclude={"request_key"}, mode="json"),
            payload.request_key,
        )
    except DomainError as error:
        _raise_learning_error(error)


@router.get("/sessions/{session_id}/room")
def get_learning_room(session_id: str, request: Request, identity: dict[str, Any] = Depends(current_identity)):
    try:
        return LearningRoomService(learning_service(request), request.app.state.conversations).get(identity, session_id)
    except DomainError as error:
        _raise_learning_error(error)


@router.put("/sessions/{session_id}/room")
def select_learning_room_conversation(
    session_id: str, payload: LearningRoomConversationRequest, request: Request,
    identity: dict[str, Any] = Depends(current_identity),
):
    try:
        return LearningRoomService(learning_service(request), request.app.state.conversations).select(identity, session_id, payload.conversation_id)
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/verifications/{verification_id}/submit")
async def submit_learning_verification(
    verification_id: str,
    payload: LearningVerificationSubmitRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return await verification_service(request).submit(
            identity,
            verification_id,
            payload.model_dump(mode="json"),
        )
    except DomainError as error:
        _raise_learning_error(error)


@router.get("/verifications")
def list_learning_verifications(
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> list[dict[str, Any]]:
    return verification_service(request).list(identity)


@router.post("/verifications/{verification_id}/evaluate")
async def evaluate_learning_verification(
    verification_id: str, payload: LearningVerificationEvaluateRequest, request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return await verification_service(request).evaluate(identity, verification_id, payload.submission_id, payload.request_key)
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/verifications/{verification_id}/confirm")
def confirm_learning_verification(
    verification_id: str, payload: LearningVerificationConfirmRequest, request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return verification_service(request).confirm(identity, verification_id, payload.submission_id, payload.evaluation_id)
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/verifications/{verification_id}/evidence")
async def analyze_verification_evidence(verification_id: str, request: Request, identity: dict[str, Any] = Depends(current_identity)):
    try:
        return await verification_service(request).analyze_evidence(identity, verification_id)
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/verifications/{verification_id}/purge")
def purge_verification(verification_id: str, payload: LearningVerificationPurgeRequest, request: Request, identity: dict[str, Any] = Depends(current_identity)):
    try:
        result = verification_service(request).purge(identity, verification_id)
        return result
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/artifacts", status_code=status.HTTP_201_CREATED)
def save_learning_artifact(
    payload: LearningArtifactSaveRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = learning_service(request)
    try:
        return service.save_artifact(
            identity,
            payload.model_dump(exclude={"idempotency_key"}, mode="json"),
            payload.idempotency_key,
        )
    except DomainError as error:
        _raise_learning_error(error)


@router.get("/artifacts/{artifact_id}")
def get_learning_artifact(
    artifact_id: str,
    request: Request,
    content_version: int | None = Query(default=None, ge=1),
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = learning_service(request)
    try:
        return service.artifact(identity, artifact_id, content_version)
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/artifacts/{artifact_id}/corrections")
def correct_learning_artifact(
    artifact_id: str,
    payload: LearningArtifactCorrectRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = learning_service(request)
    try:
        result = service.correct_artifact(
            identity,
            {
                "artifact_id": artifact_id,
                **payload.model_dump(exclude={"idempotency_key"}, mode="json"),
            },
            payload.idempotency_key,
        )
        review_service(request).supersede_artifact_versions(identity, artifact_id)
        return result
    except DomainError as error:
        _raise_learning_error(error)


@router.get("/actions/{action_id}/events")
def get_learning_events(
    action_id: str,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> list[dict[str, Any]]:
    service = learning_service(request)
    try:
        return service.events(identity, action_id)
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/artifacts/{artifact_id}/soft-delete")
def soft_delete_learning_artifact(
    artifact_id: str,
    payload: ArtifactLifecycleRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = learning_service(request)
    try:
        result = service.soft_delete_artifact(
            identity,
            {"artifact_id": artifact_id, "expected_version": payload.expected_version},
            payload.idempotency_key,
        )
        state_derivation_service(request).recalculate(identity)
        return result
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/artifacts/{artifact_id}/restore")
def restore_learning_artifact(
    artifact_id: str,
    payload: ArtifactLifecycleRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = learning_service(request)
    try:
        result = service.restore_artifact(
            identity,
            {"artifact_id": artifact_id, "expected_version": payload.expected_version},
            payload.idempotency_key,
        )
        state_derivation_service(request).recalculate(identity)
        return result
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/artifacts/{artifact_id}/withdraw")
def withdraw_learning_artifact(
    artifact_id: str,
    payload: ArtifactLifecycleRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = learning_service(request)
    try:
        result = service.withdraw_artifact(
            identity,
            {"artifact_id": artifact_id, "expected_version": payload.expected_version},
            payload.idempotency_key,
        )
        state_derivation_service(request).recalculate(identity)
        return result
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/artifacts/{artifact_id}/purge")
def purge_learning_artifact(
    artifact_id: str,
    payload: ArtifactPurgeRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = learning_service(request)
    try:
        result = service.purge_artifact(
            identity,
            {
                "artifact_id": artifact_id,
                "expected_version": payload.expected_version,
                "confirmation": payload.confirmation,
            },
            payload.idempotency_key,
        )
        return result
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/artifacts/{artifact_id}/analysis")
async def analyze_learning_artifact(
    artifact_id: str,
    payload: EvidenceAnalysisRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = evidence_service(request)
    try:
        return await service.analyze(
            identity,
            artifact_id,
            payload.request_key,
            payload.content_version,
        )
    except DomainError as error:
        _raise_learning_error(error)


@router.get("/evidence-claims")
def list_learning_evidence_claims(
    request: Request,
    artifact_id: str | None = Query(default=None, min_length=1, max_length=100),
    identity: dict[str, Any] = Depends(current_identity),
) -> list[dict[str, Any]]:
    return evidence_service(request).claims(identity, artifact_id)


@router.post("/evidence-claims/{claim_id}/review", status_code=status.HTTP_201_CREATED)
def review_evidence_claim(
    claim_id: str,
    payload: EvidenceClaimReviewRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = review_service(request)
    try:
        return service.review(
            identity,
            claim_id,
            payload.action,
            payload.reason,
            payload.request_key,
            payload.replacement_claim_id,
        )
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/evidence-claims/batch-review", status_code=status.HTTP_201_CREATED)
def batch_review_evidence_claims(
    payload: EvidenceBatchReviewRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = review_service(request)
    try:
        return service.batch_review(
            identity,
            payload.claim_ids,
            payload.action,
            payload.reason,
            payload.request_key,
        )
    except DomainError as error:
        _raise_learning_error(error)


@router.get("/evidence-replacements")
def list_evidence_replacements(
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> list[dict[str, Any]]:
    return review_service(request).replacements(identity)


@router.get("/revisit-queue")
def list_revisit_queue(
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> list[dict[str, Any]]:
    return state_derivation_service(request).revisit_queue(identity)


@router.get("/derived-states")
def list_derived_states(
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> list[dict[str, Any]]:
    return state_derivation_service(request).states(identity)


@router.get("/derived-state-history")
def list_derived_state_history(
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> list[dict[str, Any]]:
    return state_derivation_service(request).history(identity)


@router.post("/derived-states/recalculate")
def recalculate_derived_states(
    payload: DerivedStateRecalculateRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> list[dict[str, Any]]:
    service = state_derivation_service(request)
    try:
        return service.recalculate(identity, payload.criterion_id)
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/evidence-claims/{claim_id}/human-review", status_code=status.HTTP_201_CREATED)
def request_evidence_human_review(
    claim_id: str,
    payload: EvidenceHumanReviewRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = evidence_service(request)
    try:
        return service.request_human_review(
            identity,
            claim_id,
            payload.request_key,
            payload.note,
        )
    except DomainError as error:
        _raise_learning_error(error)


@router.post(
    "/evidence-claims/{claim_id}/supplemental-verification",
    status_code=status.HTTP_201_CREATED,
)
def schedule_evidence_supplemental_verification(
    claim_id: str,
    payload: EvidenceSupplementalVerificationRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = evidence_service(request)
    try:
        due_at = payload.due_at.isoformat().replace("+00:00", "Z") if payload.due_at else None
        return service.schedule_supplemental_verification(
            identity,
            claim_id,
            payload.request_key,
            due_at,
            payload.note,
        )
    except DomainError as error:
        _raise_learning_error(error)


@router.get("/evidence-follow-ups")
def list_evidence_follow_ups(
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> list[dict[str, Any]]:
    return evidence_service(request).follow_ups(identity)


@router.get("/agent/permission-requests")
def list_agent_permission_requests(
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> list[dict[str, Any]]:
    return agent_runtime(request).list_permission_requests(identity)


@router.post("/agent/permission-requests", status_code=status.HTTP_201_CREATED)
def create_agent_permission_request(
    payload: AgentPermissionRequestCreate,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    runtime = agent_runtime(request)
    try:
        return runtime.create_permission_request(
            identity,
            {
                "purpose": payload.purpose,
                "scope": "learning_action",
                "target_id": payload.target_id,
                "content_granularity": payload.content_granularity,
                "ttl_seconds": payload.ttl_seconds,
            },
            payload.request_key,
        )
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/agent/permission-requests/{request_id}/deny")
def deny_agent_permission_request(
    request_id: str,
    payload: AgentPermissionDenyRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    runtime = agent_runtime(request)
    try:
        return runtime.deny_permission_request(identity, request_id, payload.reason)
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/agent/permission-requests/{request_id}/approve")
def approve_agent_permission_request(
    request_id: str,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    runtime = agent_runtime(request)
    try:
        return runtime.approve_permission_request(identity, request_id)
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/agent/permission-requests/{request_id}/revoke")
def revoke_agent_permission_grant(
    request_id: str,
    payload: AgentPermissionRevokeRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    runtime = agent_runtime(request)
    try:
        return runtime.revoke_permission_grant(identity, request_id, payload.reason)
    except DomainError as error:
        _raise_learning_error(error)


@router.get("/agent/context")
def get_agent_context(
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
    target_id: str | None = Query(default=None, min_length=1, max_length=100),
) -> dict[str, Any]:
    runtime = agent_runtime(request)
    try:
        return runtime.agent_context(identity, target_id)
    except DomainError as error:
        _raise_learning_error(error)


@router.get("/evidence-provider")
def get_evidence_provider(
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any] | None:
    return evidence_provider_service(request).selection(identity)


@router.put("/evidence-provider")
def set_evidence_provider(
    payload: EvidenceProviderSelectionRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return evidence_provider_service(request).set_selection(
            identity,
            payload.provider_profile_id,
            payload.provider_model_id,
        )
    except ConversationError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.delete("/evidence-provider", status_code=status.HTTP_204_NO_CONTENT)
def clear_evidence_provider(
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> Response:
    evidence_provider_service(request).clear_selection(identity)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/metrics")
def learning_metrics(
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    return measurement_service(request).report(identity).model_dump(mode="json")


@router.post("/evidence-replay")
def replay_evidence(
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    principal = learning_service(request).principal(identity)
    try:
        result = evidence_event_service(request).replay(principal.owner_id)
        state_derivation_service(request).refresh_revisit_queues(identity)
        return result
    except DomainError as error:
        _raise_learning_error(error)


@router.post("/replay")
def replay_learning(
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    service = learning_service(request)
    try:
        return service.replay(identity)
    except DomainError as error:
        _raise_learning_error(error)
