from __future__ import annotations

import asyncio
from typing import Any

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect, status

from ..plans import PlanError
from ..dependencies import current_identity, plan_editor_service, plan_service
from ..schemas import (
    GoalUpdateRequest,
    ManualPlanRequest,
    NodeTitleRequest,
    ReorderRequest,
    TaskCompletionRequest,
    TaskCreateRequest,
    TaskRescheduleRequest,
    TaskUpdateRequest,
    TimerActionRequest,
)

router = APIRouter(prefix="/api")


def _raise_plan_error(error: PlanError, not_found: bool = False) -> None:
    detail = str(error)
    code = status.HTTP_404_NOT_FOUND if not_found or detail.endswith("不存在") else status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=code, detail=detail) from error


@router.get("/plans")
def list_plans(request: Request, identity: dict[str, Any] = Depends(current_identity)) -> list[dict[str, Any]]:
    return plan_service(request).list_plans(identity["id"])


@router.get("/plans/summary")
def list_plan_summaries(
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> list[dict[str, Any]]:
    return plan_service(request).list_plan_summaries(identity["id"])


@router.get("/plans/{goal_id}")
def get_plan_detail(
    goal_id: str,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return plan_service(request).get_plan_detail(identity["id"], goal_id)
    except PlanError as error:
        _raise_plan_error(error, not_found=True)


@router.get("/plans/{goal_id}/schedule")
def get_plan_schedule(
    goal_id: str,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> list[dict[str, Any]]:
    try:
        return plan_service(request).plan_schedule(identity["id"], goal_id)
    except PlanError as error:
        _raise_plan_error(error, not_found=True)


@router.get("/tasks")
def list_tasks(
    request: Request,
    query: str | None = Query(default=None, max_length=120),
    task_status: str | None = Query(default=None, alias="status"),
    task_type: str | None = Query(default=None),
    schedule_mode: str | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    identity: dict[str, Any] = Depends(current_identity),
) -> list[dict[str, Any]]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="任务筛选开始日期不能晚于结束日期")
    if task_status and task_status not in {"pending", "in_progress", "completed", "canceled"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的任务状态筛选")
    if task_type and task_type not in {"study", "practice", "review", "output"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的任务类型筛选")
    if schedule_mode and schedule_mode not in {"fixed", "flexible"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的排期方式筛选")
    return plan_service(request).list_tasks(
        identity["id"], query, task_status, task_type, schedule_mode, start_date, end_date
    )


@router.post("/plans/manual", status_code=status.HTTP_201_CREATED)
def create_manual_plan(
    payload: ManualPlanRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return plan_service(request).create_manual_plan(identity["id"], payload.model_dump(mode="json"))
    except PlanError as error:
        _raise_plan_error(error)


@router.patch("/plans/{goal_id}")
def update_goal(
    goal_id: str,
    payload: GoalUpdateRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return plan_editor_service(request).update_goal(identity["id"], goal_id, payload.model_dump(exclude_unset=True, mode="json"))
    except PlanError as error:
        _raise_plan_error(error)


@router.delete("/plans/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(goal_id: str, request: Request, identity: dict[str, Any] = Depends(current_identity)) -> Response:
    try:
        plan_editor_service(request).delete_goal(identity["id"], goal_id)
    except PlanError as error:
        _raise_plan_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/plans/{goal_id}/subjects", status_code=status.HTTP_201_CREATED)
def create_subject(
    goal_id: str,
    payload: NodeTitleRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return plan_editor_service(request).create_subject(identity["id"], goal_id, payload.title)
    except PlanError as error:
        _raise_plan_error(error)


@router.put("/plans/{goal_id}/subjects/order")
def reorder_subjects(
    goal_id: str,
    payload: ReorderRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return plan_editor_service(request).reorder_subjects(identity["id"], goal_id, payload.ordered_ids)
    except PlanError as error:
        _raise_plan_error(error)


@router.patch("/subjects/{subject_id}")
def update_subject(
    subject_id: str,
    payload: NodeTitleRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return plan_editor_service(request).update_subject(identity["id"], subject_id, payload.title)
    except PlanError as error:
        _raise_plan_error(error)


@router.delete("/subjects/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subject(subject_id: str, request: Request, identity: dict[str, Any] = Depends(current_identity)) -> Response:
    try:
        plan_editor_service(request).delete_subject(identity["id"], subject_id)
    except PlanError as error:
        _raise_plan_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/subjects/{subject_id}/topics", status_code=status.HTTP_201_CREATED)
def create_topic(
    subject_id: str,
    payload: NodeTitleRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return plan_editor_service(request).create_topic(identity["id"], subject_id, payload.title)
    except PlanError as error:
        _raise_plan_error(error)


@router.put("/subjects/{subject_id}/topics/order")
def reorder_topics(
    subject_id: str,
    payload: ReorderRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return plan_editor_service(request).reorder_topics(identity["id"], subject_id, payload.ordered_ids)
    except PlanError as error:
        _raise_plan_error(error)


@router.patch("/topics/{topic_id}")
def update_topic(
    topic_id: str,
    payload: NodeTitleRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return plan_editor_service(request).update_topic(identity["id"], topic_id, payload.title)
    except PlanError as error:
        _raise_plan_error(error)


@router.delete("/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_topic(topic_id: str, request: Request, identity: dict[str, Any] = Depends(current_identity)) -> Response:
    try:
        plan_editor_service(request).delete_topic(identity["id"], topic_id)
    except PlanError as error:
        _raise_plan_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/topics/{topic_id}/tasks", status_code=status.HTTP_201_CREATED)
def create_task(
    topic_id: str,
    payload: TaskCreateRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return plan_editor_service(request).create_task(identity["id"], topic_id, payload.model_dump(mode="json"))
    except PlanError as error:
        _raise_plan_error(error)


@router.put("/topics/{topic_id}/tasks/order")
def reorder_tasks(
    topic_id: str,
    payload: ReorderRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return plan_editor_service(request).reorder_tasks(identity["id"], topic_id, payload.ordered_ids)
    except PlanError as error:
        _raise_plan_error(error)


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: str,
    payload: TaskUpdateRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return plan_editor_service(request).update_task(identity["id"], task_id, payload.model_dump(exclude_unset=True, mode="json"))
    except PlanError as error:
        _raise_plan_error(error)


@router.post("/tasks/{task_id}/reschedule")
def reschedule_task(
    task_id: str,
    payload: TaskRescheduleRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return plan_editor_service(request).reschedule_task(identity["id"], task_id, payload.days)
    except PlanError as error:
        _raise_plan_error(error)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: str, request: Request, identity: dict[str, Any] = Depends(current_identity)) -> Response:
    try:
        plan_editor_service(request).delete_task(identity["id"], task_id)
    except PlanError as error:
        _raise_plan_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/dashboard/today")
def today_dashboard(request: Request, identity: dict[str, Any] = Depends(current_identity)) -> dict[str, Any]:
    return plan_service(request).today_dashboard(identity["id"])


@router.post("/tasks/{task_id}/complete")
def complete_task(task_id: str, request: Request, identity: dict[str, Any] = Depends(current_identity)) -> dict[str, Any]:
    try:
        return plan_service(request).complete_task(identity["id"], task_id)
    except PlanError as error:
        _raise_plan_error(error, not_found=True)


@router.put("/tasks/{task_id}/completion")
def set_task_completion(
    task_id: str,
    payload: TaskCompletionRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return plan_service(request).set_task_completion(
            identity["id"], task_id, payload.completed
        )
    except PlanError as error:
        _raise_plan_error(error, not_found=True)


@router.post("/tasks/{task_id}/timer")
def timer_action(
    task_id: str,
    payload: TimerActionRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any] | None:
    try:
        return plan_service(request).timer_action(
            identity["id"],
            task_id,
            payload.action,
            payload.timer_mode,
            payload.work_minutes,
            payload.break_minutes,
        )
    except PlanError as error:
        _raise_plan_error(error)


@router.websocket("/ws/timers/{task_id}")
async def timer_updates(websocket: WebSocket, task_id: str) -> None:
    settings = websocket.app.state.settings
    session = websocket.cookies.get(settings.cookie_name)
    identity = websocket.app.state.auth.identity_for_session(session)
    if not identity:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        while True:
            snapshot = websocket.app.state.plans.timer_snapshot(identity["id"], task_id)
            await websocket.send_json(snapshot)
            if snapshot is None:
                return
            await asyncio.sleep(1)
    except PlanError:
        await websocket.close(code=4404)
    except WebSocketDisconnect:
        return
