"""Owner-reviewed drafts and real task entry for a plan route."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from ..dependencies import current_identity
from ..core.path_commands import PathFields, TransferFields, PathTaskFields
from ..learning_domain import DomainError
from ..managed_purge import ManagedPurge

def no_cache(response:Response):
    response.headers['Cache-Control']='no-store'

router=APIRouter(prefix='/api/learning/plans',dependencies=[Depends(no_cache)])

class Key(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_key:str=Field(min_length=1,max_length=200)

class Draft(PathFields,Key):
    expected_revision:int=Field(ge=0)
    expected_organization_revision:int=Field(ge=0)
    intent:Literal['create','change_entry','change_scope','change_direction','restore','undo']='create'
    draft_id:str|None=None
    expected_draft_revision:int|None=Field(default=None,ge=1)
    source_version_id:str|None=None
    restore_version_id:str|None=None

class DraftReference(BaseModel):
    model_config=ConfigDict(extra='forbid')
    draft_id:str

class Confirm(Key):
    draft_id:str
    expected_draft_revision:int=Field(ge=1)
    expected_revision:int=Field(ge=0)
    review_key:str=Field(min_length=1,max_length=100)

class Position(Key):
    version_id:str
    node_id:str
    expected_revision:int=Field(ge=1)

class Start(Position):
    delegation_id:str
    expected_action_version:int=Field(ge=1)
    use_checkpoint:bool=True

class Task(PathTaskFields,Key):
    pass

class Restore(Key):
    version_id:str
    node_id:str|None=None
    intent:Literal['restore','undo']='restore'
    expected_revision:int=Field(ge=0)
    expected_organization_revision:int=Field(ge=0)
    reason:str=Field(default='',max_length=2000)

class Purge(Key):
    expected_revision:int=Field(ge=1)
    confirmation:Literal['PURGE']

class Transfer(TransferFields,Key):
    review_key:str=Field(min_length=1,max_length=100)

def fail(error):
    messages={
        'not_found':'这条路线或关联记录当前不可查看。',
        'version_conflict':'计划或路线已更新。输入已保留，请读取最新状态后核对。',
        'path_reference_scope':'请选择这个计划中的任务及可访问的成果。',
        'path_transfer_tasks':'新计划可引用已有成果；原任务保留在原计划，请明确添加新任务。',
        'path_paused':'原方向已暂停，请先预览恢复，再开始节点任务。',
        'path_plan_inactive':'这个计划已暂停或结束，请先重新开启。',
        'goal_not_active':'目标已暂停或结束，请先在计划中重新开启。',
        'path_input_changed':'路线位置、任务或来源已变化，请重新保存并核对草案。',
        'path_review_changed':'预览依据已变化，请重新查看影响后确认。',
        'path_draft_inactive':'这份草案已处理或清除，请读取当前路线。',
        'path_not_current':'这条路线已不是当前主线，请先预览恢复。',
        'path_generation_running':'当前回答还在生成，请等待完成或取消后再核对切换。',
        'path_anchor_unavailable':'原对话位置已不可读取。可查看记录，或明确从当前可用任务开始。',
        'path_content_unavailable':'这份路线说明已清除，请重新建立可用草案。',
        'path_already_exists':'计划已有主线，请通过调整方向建立新草案。',
        'path_not_adopted':'请先建立并确认一条路径。',
        'path_restore_changed':'原路线结构已变化，请重新选择历史位置。',
        'path_restore_required':'请选择要恢复的历史路线。',
        'path_node_missing':'这个路线节点不存在，请重新选择。',
        'path_node_task_limit':'这个阶段的关联已满，请先调整阶段再添加任务。',
        'delegation_not_startable':'这项任务已经结束，请查看记录或明确添加新练习。',
        'idempotency_conflict':'请求内容已改变，请核对后重新保存。'}
    raise HTTPException(status_code=error.status,detail=dict(kind=error.code,code=error.code,
        message=messages.get(error.code,'操作未完成，请读取最新状态后重试。'))) from error

def call(request,identity,method,*args):
    try:
        return getattr(request.app.state.learning_paths,method)(identity,*args)
    except DomainError as error:
        fail(error)

def values(payload):
    data=payload.model_dump(mode='json')
    return data,data.pop('request_key')

@router.get('/{plan_id}/path')
def path(plan_id:str,request:Request,identity=Depends(current_identity)):
    return call(request,identity,'data',plan_id)

@router.post('/{plan_id}/path/drafts')
def draft(plan_id:str,payload:Draft,request:Request,identity=Depends(current_identity)):
    data,key=values(payload)
    return call(request,identity,'save',plan_id,data,key)

@router.post('/{plan_id}/path/previews')
def preview(plan_id:str,payload:DraftReference,request:Request,identity=Depends(current_identity)):
    return call(request,identity,'preview',plan_id,payload.draft_id)

@router.post('/{plan_id}/path/decisions')
def confirm(plan_id:str,payload:Confirm,request:Request,identity=Depends(current_identity)):
    data,key=values(payload)
    return call(request,identity,'confirm',plan_id,data,key)

@router.post('/{plan_id}/path/position')
def position(plan_id:str,payload:Position,request:Request,identity=Depends(current_identity)):
    data,key=values(payload)
    return call(request,identity,'position',plan_id,data,key)

@router.post('/{plan_id}/path/transfer-preview')
def transfer_preview(plan_id:str,payload:TransferFields,request:Request,identity=Depends(current_identity)):
    return call(request,identity,'transfer_preview',plan_id,payload.model_dump(mode='json'))

@router.post('/{plan_id}/path/transfer')
def transfer(plan_id:str,payload:Transfer,request:Request,identity=Depends(current_identity)):
    data,key=values(payload)
    return call(request,identity,'transfer',plan_id,data,key)

@router.post('/{plan_id}/path/start')
def start(plan_id:str,payload:Start,request:Request,identity=Depends(current_identity)):
    data,key=values(payload)
    return call(request,identity,'start',plan_id,data,key)

@router.post('/{plan_id}/path/tasks',status_code=201)
def task(plan_id:str,payload:Task,request:Request,identity=Depends(current_identity)):
    data,key=values(payload)
    return call(request,identity,'create_task',plan_id,data,key)

@router.post('/{plan_id}/path/restore-draft')
def restore(plan_id:str,payload:Restore,request:Request,identity=Depends(current_identity)):
    data,key=values(payload)
    return call(request,identity,'restore_draft',plan_id,data,key)

@router.post('/{plan_id}/path/versions/{version_id}/purge')
def purge(plan_id:str,version_id:str,payload:Purge,request:Request,identity=Depends(current_identity)):
    data,key=values(payload)
    return call(request,identity,'purge',plan_id,version_id,data,key)

@router.get('/{plan_id}/path/versions/{version_id}/purge-status')
def purge_status(plan_id:str,version_id:str,request:Request,identity=Depends(current_identity)):
    try:
        principal=request.app.state.learning.principal(identity)
        if not request.app.state.learning.database.fetchone('SELECT 1 FROM learning_path_version WHERE owner_id=? AND id=? AND plan_id=?',
                (principal.owner_id,version_id,plan_id)):
            raise DomainError('not_found',404)
        return ManagedPurge(request.app.state.learning).status(identity,'path_content',version_id)
    except DomainError as error:
        fail(error)
