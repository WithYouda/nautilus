"""Owner-authenticated coach proposals; accepting never executes a formal change."""
from typing import Literal
from fastapi import APIRouter,Depends,Request,Response,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from ..dependencies import current_identity
from ..learning_domain import DomainError

def no_store(response:Response): response.headers['Cache-Control']='no-store'
router=APIRouter(prefix='/api/learning/coach',dependencies=[Depends(no_store)])

MESSAGES={'not_found':'这项建议或来源当前不可查看。','version_conflict':'建议或设置已更新，请读取最新状态后重新核对。',
    'idempotency_conflict':'本次请求内容已经变化，请核对后重试。','coach_provider_unavailable':'请先配置可用的AI模型。',
    'coach_source_unavailable':'相关来源已更正、隐藏或清除，请重新核对。','coach_input_changed':'复盘依据已变化，请重新核对。',
    'coach_retry_invalid':'这次复盘不能按原批次重试，请核对来源。','coach_run_inactive':'这次复盘已经结束，请读取最新记录。',
    'coach_decision_inactive':'这条建议已经处理，请读取最新状态。','coach_target_out_of_scope':'建议目标超出本次范围。'}
def fail(error):
    raise HTTPException(status_code=error.status,detail={'kind':error.code,'code':error.code,'message':MESSAGES.get(error.code,'操作未完成，请重新核对后重试。')}) from error
def invoke(request,method,*args):
    try: return getattr(request.app.state.background_coach,method)(*args)
    except DomainError as error: fail(error)
async def invoke_async(request,method,*args):
    try: return await getattr(request.app.state.background_coach,method)(*args)
    except DomainError as error: fail(error)
class Key(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_key:str=Field(min_length=1,max_length=200)
class Settings(Key):
    expected_revision:int=Field(ge=0)
    enabled:bool
    timezone:str=Field(min_length=1,max_length=100)
    max_calls_per_session:int=Field(ge=1,le=20)
    max_calls_per_day:int=Field(ge=1,le=100)
    cooldown_minutes:int=Field(ge=30,le=10080)
class Check(Key):
    scope:Literal['global','plan']='global'
    plan_id:str|None=None
    trigger:Literal['manual','return','boundary']='manual'
    retry_run_id:str|None=None
    permission_candidate_id:str|None=None
    permission_request_id:str|None=None
class Revision(Key): expected_revision:int=Field(ge=1)
class Decision(Revision): operation:Literal['accept','reject','ignore','undo']
class Correction(Revision): operation:Literal['exclude','restore']
class Purge(Revision): confirmation:Literal['PURGE']
def values(payload):
    result=payload.model_dump(mode='json');key=result.pop('request_key');return result,key
@router.get('')
def overview(request:Request,scope:Literal['global','plan']='global',plan_id:str|None=None,identity=Depends(current_identity)):
    return invoke(request,'view',identity,scope,plan_id)
@router.get('/settings')
def get_settings(request:Request,identity=Depends(current_identity)): return invoke(request,'get_settings',identity)
@router.put('/settings')
async def save_settings(payload:Settings,request:Request,identity=Depends(current_identity)):
    data,key=values(payload)
    # Core also validates timezone; API validation must precede any writes.
    from ..core.coach_commands import SaveCoachSettings
    from pydantic import ValidationError
    try: SaveCoachSettings(**data)
    except ValidationError as error: raise HTTPException(422,detail={'kind':'coach_settings_invalid','message':'请填写有效时区与复盘限额。'}) from error
    return await invoke_async(request,'save_settings',identity,data,key)
@router.post('/checks')
async def check(payload:Check,request:Request,identity=Depends(current_identity)):
    data,key=values(payload);return await invoke_async(request,'check',identity,data,key)
@router.get('/checks/{run_id}')
def run(run_id:str,request:Request,identity=Depends(current_identity)): return invoke(request,'run',identity,run_id)
@router.post('/checks/{run_id}/cancel')
async def cancel(run_id:str,payload:Revision,request:Request,identity=Depends(current_identity)):
    data,key=values(payload);return await invoke_async(request,'cancel',identity,run_id,data,key)
@router.post('/checks/{run_id}/purge')
async def purge(run_id:str,payload:Purge,request:Request,identity=Depends(current_identity)):
    data,key=values(payload);return await invoke_async(request,'purge',identity,run_id,data,key)
@router.get('/candidates/{candidate_id}')
def candidate(candidate_id:str,request:Request,identity=Depends(current_identity)): return invoke(request,'candidate',identity,candidate_id)
@router.post('/candidates/{candidate_id}/decisions')
def decide(candidate_id:str,payload:Decision,request:Request,identity=Depends(current_identity)):
    data,key=values(payload);return invoke(request,'decide',identity,candidate_id,data,key)
@router.get('/signals')
def signals(request:Request,scope:Literal['global','plan']='global',plan_id:str|None=None,identity=Depends(current_identity)):
    return invoke(request,'signals',identity,scope,plan_id)
@router.post('/signals/{signal_id}/corrections')
def correct(signal_id:str,payload:Correction,request:Request,identity=Depends(current_identity)):
    data,key=values(payload);return invoke(request,'correct_signal',identity,signal_id,data,key)
