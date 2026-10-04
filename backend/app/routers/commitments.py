"""D2 recent-arrangement routes. Confirmation never starts a session."""
from typing import Literal
from fastapi import APIRouter,Depends,Request,Response,HTTPException
from pydantic import BaseModel,ConfigDict,Field,model_validator
from ..dependencies import current_identity
from ..learning_domain import DomainError
from ..managed_purge import ManagedPurge
from ..core.commitment_commands import ItemFields,FeedbackFields,AvailabilityFields,utc,valid_zone


def no_store(response:Response):response.headers['Cache-Control']='no-store'
router=APIRouter(prefix='/api/learning/plans',dependencies=[Depends(no_store)])
feedback_router=APIRouter(prefix='/api/learning/sessions',dependencies=[Depends(no_store)])


def fail(error):
    messages={'not_found':'这项安排或引用当前不可查看。','version_conflict':'内容已更新，请刷新后重新核对。',
        'idempotency_conflict':'这次保存请求已被其他内容使用，请刷新后重试。',
        'goal_not_active':'关联目标已暂停或结束，请先重新开启目标。',
        'path_paused':'这条路径已暂停，请先恢复路径再安排学习。','commitment_route_required':'请先为计划建立路径。','commitment_route_changed':'采用的路径已变化，请重新核对安排。',
        'commitment_review_changed':'安排或受影响会话已变化，请重新核对预览。',
        'commitment_generation_running':'这个计划的安排建议正在更新，请读取当前更新，或取消后再更新。',
        'commitment_input_changed':'建议依据已变化，请重新更新安排。',
        'commitment_source_unavailable':'相关依据已更正、隐藏或清除，请重新核对安排。',
        'commitment_draft_inactive':'这份草案已经确认或清除，请刷新。',
        'commitment_item_completed':'这项任务已完成，可以回看记录或明确建立新的练习。',
        'commitment_item_identity_changed':'已有安排不能换成另一个任务或委托，请明确建立新安排。',
        'commitment_executed_item_changed':'已经执行的安排保留原预计，请只调整尚未执行部分。',
        'commitment_item_preview_required':'请通过改期预览调整这项已开始的安排。',
        'commitment_feedback_scope':'所选产出或作答与这次学习不一致。',
        'commitment_synthetic_origin_locked':'这条记录已明确用于演示或测试，不能记作实际学习。',
        'commitment_provider_unavailable':'请先为这个计划配置可用的AI模型。',
        'commitment_run_inactive':'这次建议已结束、取消或清除，请刷新。',
        'commitment_calibration_scope':'建议超出当前依据支持的范围。',
        'commitment_calendar_not_supported':'当前依据只支持任务顺序和范围，请暂不指定日期。',
        'commitment_capacity_exceeded':'这项建议超出了已给出的时段、区块或预算。',
        'commitment_effective_effort_unknown':'有效投入仍未知，请保留未知或预计范围。',
        'commitment_ai_source_out_of_scope':'建议引用了本次输入以外的依据。','commitment_ai_item_out_of_scope':'建议引用了本次输入以外的安排。',
        'path_generation_running':'请等当前回答结束或取消后，再重新核对安排。',
        'path_anchor_unavailable':'原学习位置当前不可查看，请明确选择新的位置。'}
    raise HTTPException(status_code=error.status,detail={'kind':error.code,'code':error.code,'message':messages.get(error.code,'操作未完成，请刷新后重试。')}) from error


class Key(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_key:str=Field(min_length=1,max_length=200)
class Revision(Key):
    expected_revision:int=Field(ge=0)
class Draft(Revision):
    route_version_id:str
    items:list[ItemFields]=Field(max_length=100)
    reason:str=Field(default='',max_length=2000)
    draft_id:str|None=None
    expected_draft_revision:int|None=Field(default=None,ge=1)
class DraftPreview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    draft_id:str
class Confirm(Revision):
    draft_id:str
    expected_draft_revision:int=Field(ge=1)
    review_key:str
class Start(Revision):
    expected_action_version:int=Field(ge=1)
    use_checkpoint:bool=True
class ItemPreview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    operation:Literal['defer','skip']
    due_at:str|None=None
    timezone:str|None=None
    @model_validator(mode='after')
    def date(self):
        if self.operation=='skip' and (self.due_at or self.timezone):raise ValueError('skip cannot set a date')
        if bool(self.due_at)!=bool(self.timezone):raise ValueError('a date needs a timezone')
        self.due_at=utc(self.due_at)
        if self.timezone:valid_zone(self.timezone)
        return self
class Change(Revision):
    review_key:str
    due_at:str|None=None
    timezone:str|None=None
class Availability(Revision,AvailabilityFields):pass
class Feedback(Revision,FeedbackFields):pass
class Purge(Revision):
    confirmation:Literal['PURGE']
class RunRevision(Key):
    expected_revision:int=Field(ge=1)
class RunPurge(RunRevision):
    confirmation:Literal['PURGE']


def values(payload):
    value=payload.model_dump(mode='json');key=value.pop('request_key');return value,key

def invoke(request,method,*args):
    try:return getattr(request.app.state.commitments,method)(*args)
    except DomainError as error:fail(error)

@router.get('/{plan_id}/commitments')
def data(plan_id:str,request:Request,identity=Depends(current_identity)):
    return invoke(request,'data',identity,plan_id)
@router.post('/{plan_id}/commitments/drafts',status_code=201)
def draft(plan_id:str,payload:Draft,request:Request,identity=Depends(current_identity)):
    value,key=values(payload);return invoke(request,'save',identity,plan_id,value,key)
@router.post('/{plan_id}/commitments/previews')
def preview(plan_id:str,payload:DraftPreview,request:Request,identity=Depends(current_identity)):
    return invoke(request,'preview',identity,plan_id,payload.draft_id)
@router.post('/{plan_id}/commitments/confirm')
def confirm(plan_id:str,payload:Confirm,request:Request,identity=Depends(current_identity)):
    value,key=values(payload);return invoke(request,'confirm',identity,plan_id,value,key)
@router.post('/{plan_id}/commitments/items/{item_id}/start')
@router.post('/{plan_id}/commitments/items/{item_id}/continue')
def start(plan_id:str,item_id:str,payload:Start,request:Request,identity=Depends(current_identity)):
    value,key=values(payload);return invoke(request,'start',identity,plan_id,item_id,value,key)
@router.post('/{plan_id}/commitments/items/{item_id}/preview')
def item_preview(plan_id:str,item_id:str,payload:ItemPreview,request:Request,identity=Depends(current_identity)):
    return invoke(request,'item_preview',identity,plan_id,item_id,payload.model_dump(mode='json'))
@router.post('/{plan_id}/commitments/items/{item_id}/defer')
def defer(plan_id:str,item_id:str,payload:Change,request:Request,identity=Depends(current_identity)):
    value,key=values(payload)
    try:value.update(ItemPreview(operation='defer',due_at=value.get('due_at'),timezone=value.get('timezone')).model_dump(exclude={'operation'}))
    except ValueError:raise HTTPException(422,detail={'kind':'invalid_date','message':'请输入有效日期与时区。'})
    return invoke(request,'change',identity,plan_id,item_id,'defer',value,key)
@router.post('/{plan_id}/commitments/items/{item_id}/skip')
def skip(plan_id:str,item_id:str,payload:Change,request:Request,identity=Depends(current_identity)):
    value,key=values(payload)
    if value['due_at'] or value['timezone']:raise HTTPException(422,detail={'kind':'invalid_date','message':'跳过安排不指定日期。'})
    return invoke(request,'change',identity,plan_id,item_id,'skip',value,key)
@router.post('/{plan_id}/commitments/availability')
def availability(plan_id:str,payload:Availability,request:Request,identity=Depends(current_identity)):
    value,key=values(payload);return invoke(request,'availability',identity,plan_id,value,key)
@router.post('/{plan_id}/commitments/drafts/{draft_id}/purge')
def purge_content(plan_id:str,draft_id:str,payload:Purge,request:Request,identity=Depends(current_identity)):
    value,key=values(payload);return invoke(request,'purge_content',identity,plan_id,draft_id,value,key)
@router.get('/{plan_id}/commitments/drafts/{draft_id}/purge-status')
def content_status(plan_id:str,draft_id:str,request:Request,identity=Depends(current_identity)):
    try:
        view=request.app.state.commitments.data(identity,plan_id)
        if not any(draft['id']==draft_id for draft in view['drafts']):raise DomainError('not_found',404)
        return ManagedPurge(request.app.state.learning).status(identity,'commitment_content',draft_id)
    except DomainError as error:fail(error)
@router.post('/{plan_id}/commitments/suggestions',status_code=201)
async def suggest(plan_id:str,payload:Revision,request:Request,identity=Depends(current_identity)):
    value,key=values(payload)
    try:return await request.app.state.commitments.suggest(identity,plan_id,value,key)
    except DomainError as error:fail(error)
@router.get('/{plan_id}/commitments/suggestions/{run_id}')
def run(plan_id:str,run_id:str,request:Request,identity=Depends(current_identity)):
    return invoke(request,'run',identity,plan_id,run_id)
@router.post('/{plan_id}/commitments/suggestions/{run_id}/cancel')
async def cancel(plan_id:str,run_id:str,payload:RunRevision,request:Request,identity=Depends(current_identity)):
    value,key=values(payload)
    try:return await request.app.state.commitments.cancel(identity,plan_id,run_id,value,key)
    except DomainError as error:fail(error)
@router.post('/{plan_id}/commitments/suggestions/{run_id}/purge')
async def purge_run(plan_id:str,run_id:str,payload:RunPurge,request:Request,identity=Depends(current_identity)):
    value,key=values(payload)
    try:return await request.app.state.commitments.purge_run(identity,plan_id,run_id,value,key)
    except DomainError as error:fail(error)
@router.get('/{plan_id}/commitments/suggestions/{run_id}/purge-status')
def run_status(plan_id:str,run_id:str,request:Request,identity=Depends(current_identity)):
    try:
        request.app.state.commitments.run(identity,plan_id,run_id)
        return ManagedPurge(request.app.state.learning).status(identity,'commitment_run',run_id)
    except DomainError as error:fail(error)
@feedback_router.get('/{session_id}/feedback')
def feedback(session_id:str,request:Request,identity=Depends(current_identity)):
    return invoke(request,'feedback',identity,session_id)
@feedback_router.post('/{session_id}/feedback')
def record(session_id:str,payload:Feedback,request:Request,identity=Depends(current_identity)):
    value,key=values(payload);return invoke(request,'record_feedback',identity,session_id,value,key)
@feedback_router.post('/{session_id}/feedback/purge')
def purge_feedback(session_id:str,payload:RunPurge,request:Request,identity=Depends(current_identity)):
    value,key=values(payload);return invoke(request,'purge_feedback',identity,session_id,value,key)
@feedback_router.get('/{session_id}/feedback/purge-status')
def feedback_status(session_id:str,request:Request,identity=Depends(current_identity)):
    try:
        request.app.state.commitments.feedback(identity,session_id)
        return ManagedPurge(request.app.state.learning).status(identity,'session_feedback',session_id)
    except DomainError as error:fail(error)
