from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..dependencies import current_identity, layout_service
from ..layouts import LayoutError
from ..schemas import LayoutUpdateRequest, TemplateNameRequest

router = APIRouter(prefix="/api")


def _raise_layout_error(error: LayoutError, not_found: bool = False) -> None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND if not_found else status.HTTP_400_BAD_REQUEST,
        detail=str(error),
    ) from error


@router.get("/layout")
def get_layout(request: Request, identity: dict[str, Any] = Depends(current_identity)) -> dict[str, Any]:
    return layout_service(request).get_layout(identity["id"])


@router.put("/layout")
def update_layout(
    payload: LayoutUpdateRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return layout_service(request).update_layout(identity["id"], payload.model_dump(mode="json")["modules"])
    except LayoutError as error:
        _raise_layout_error(error)


@router.get("/layout/templates")
def list_layout_templates(request: Request, identity: dict[str, Any] = Depends(current_identity)) -> list[dict[str, Any]]:
    return layout_service(request).list_templates(identity["id"])


@router.post("/layout/templates", status_code=status.HTTP_201_CREATED)
def save_layout_template(
    payload: TemplateNameRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    return layout_service(request).save_personal_template(identity["id"], payload.name)


@router.post("/layout/templates/{template_id}/apply")
def apply_layout_template(template_id: str, request: Request, identity: dict[str, Any] = Depends(current_identity)) -> dict[str, Any]:
    try:
        return layout_service(request).apply_template(identity["id"], template_id)
    except LayoutError as error:
        _raise_layout_error(error, not_found=True)


@router.patch("/layout/templates/{template_id}")
def rename_layout_template(
    template_id: str,
    payload: TemplateNameRequest,
    request: Request,
    identity: dict[str, Any] = Depends(current_identity),
) -> dict[str, Any]:
    try:
        return layout_service(request).rename_template(identity["id"], template_id, payload.name)
    except LayoutError as error:
        _raise_layout_error(error)


@router.delete("/layout/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_layout_template(template_id: str, request: Request, identity: dict[str, Any] = Depends(current_identity)) -> Response:
    try:
        layout_service(request).delete_template(identity["id"], template_id)
    except LayoutError as error:
        _raise_layout_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
