"""D2 organization API; reads and owner commands share the plan entry."""
from typing import Literal
from fastapi import APIRouter, Depends, Request, Response, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from ..dependencies import current_identity
from ..learning_domain import DomainError
from ..core.organization_commands import ModuleFields, ChildReference, TaskFields
from ..managed_purge import ManagedPurge


def private_response(response:Response):
    response.headers['Cache-Control']='no-store'

router = APIRouter(prefix='/api/learning/plans',dependencies=[Depends(private_response)])


def fail(error):
    messages = {'not_found':'计划、模块或任务当前不可查看。','permission_denied':'当前身份无权修改计划。',
        'version_conflict':'计划内容已更新，请刷新后重试。','idempotency_conflict':'这次保存请求已被其他内容使用，请刷新后重试。',
        'plan_not_active':'请先重新开启这个计划。','goal_not_active':'关联目标已暂停或结束，请先重新开启目标。',
        'organization_module_cycle':'模块不能放到自己或自己的子模块中。',
        'organization_members_changed':'同级模块或任务已变化，请刷新后重新排序。',
        'organization_order_invalid':'请提供完整且不重复的同级顺序。',
        'organization_title_required':'请输入名称。','organization_content_purged':'这个模块的说明已清除。',
        'organization_legacy_content_scope':'这项旧计划说明尚未进入本次清除范围。',
        'criterion_outcome_required':'请选择达成标准对应的成果。',
        'criterion_outcome_mismatch':'达成标准与所选成果不一致。',
        'composite_not_verifiable':'请为任务选择可验证成果。'}
    raise HTTPException(status_code=error.status,detail={'kind':error.code,'code':error.code,
        'message':messages.get(error.code,'操作未完成，请刷新后重试。')}) from error


class Key(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: str = Field(min_length=1,max_length=200)

class Create(Key):
    title: str = Field(min_length=1,max_length=200)
    description: str = Field(default='',max_length=1000)
    goal_id: str | None = Field(default=None,min_length=1,max_length=100)

class Revision(Key):
    expected_revision: int = Field(ge=0)

class Module(Revision,ModuleFields):
    pass

class Placement(Revision):
    module_id: str | None = Field(default=None,min_length=1,max_length=100)

class Order(Revision):
    parent_module_id: str | None = Field(default=None,min_length=1,max_length=100)
    children: list[ChildReference] = Field(max_length=10000)

class Task(TaskFields,Revision):
    pass

class Purge(Revision):
    confirmation: Literal['PURGE']


def values(payload):
    value = payload.model_dump(mode='json')
    key = value.pop('request_key')
    return value,key


def invoke(request, method, *args):
    try:
        return getattr(request.app.state.plan_organization,method)(*args)
    except DomainError as error:
        fail(error)

@router.post('',status_code=201)
def create(payload:Create,request:Request,identity=Depends(current_identity)):
    value,key = values(payload)
    return invoke(request,'create',identity,value,key)

@router.get('/{plan_id}/organization')
def organization(plan_id:str,request:Request,identity=Depends(current_identity)):
    return invoke(request,'organization',identity,plan_id)

@router.post('/{plan_id}/modules',status_code=201)
def create_module(plan_id:str,payload:Module,request:Request,identity=Depends(current_identity)):
    value,key = values(payload)
    return invoke(request,'create_module',identity,plan_id,value,key)

@router.post('/{plan_id}/modules/{module_id}/revise')
def revise_module(plan_id:str,module_id:str,payload:Module,request:Request,identity=Depends(current_identity)):
    value,key = values(payload)
    return invoke(request,'revise_module',identity,plan_id,module_id,value,key)

@router.post('/{plan_id}/tasks/{action_id}/placement')
def placement(plan_id:str,action_id:str,payload:Placement,request:Request,identity=Depends(current_identity)):
    value,key = values(payload)
    return invoke(request,'place_task',identity,plan_id,action_id,value,key)

@router.post('/{plan_id}/children-order')
def order(plan_id:str,payload:Order,request:Request,identity=Depends(current_identity)):
    value,key = values(payload)
    return invoke(request,'order_children',identity,plan_id,value,key)

@router.post('/{plan_id}/tasks',status_code=201)
def task(plan_id:str,payload:Task,request:Request,identity=Depends(current_identity)):
    value,key = values(payload)
    value.pop('plan_id',None)
    return invoke(request,'create_task',identity,plan_id,value,key)

@router.post('/{plan_id}/organization-content/purge')
def purge_plan(plan_id:str,payload:Purge,request:Request,identity=Depends(current_identity)):
    value,key = values(payload)
    return invoke(request,'purge_content',identity,plan_id,value,key)

@router.post('/{plan_id}/modules/{module_id}/content/purge')
def purge_module(plan_id:str,module_id:str,payload:Purge,request:Request,identity=Depends(current_identity)):
    value,key = values(payload)
    return invoke(request,'purge_content',identity,plan_id,value,key,module_id)

@router.get('/{plan_id}/organization-content/purge-status')
def plan_purge_status(plan_id:str,request:Request,identity=Depends(current_identity)):
    try:
        request.app.state.plan_organization.organization(identity,plan_id)
        return ManagedPurge(request.app.state.learning).status(identity,'plan_content',plan_id)
    except DomainError as error:
        fail(error)

@router.get('/{plan_id}/modules/{module_id}/content/purge-status')
def module_purge_status(plan_id:str,module_id:str,request:Request,identity=Depends(current_identity)):
    try:
        view = request.app.state.plan_organization.organization(identity,plan_id)
        if not any(module['id']==module_id for module in view['modules']):
            raise DomainError('not_found',404)
        return ManagedPurge(request.app.state.learning).status(identity,'module_content',module_id)
    except DomainError as error:
        fail(error)
