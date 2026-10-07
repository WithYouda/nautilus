"""Explicit coach identity and deterministic notification dispatch endpoints."""
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Request,Response,Query
from pydantic import BaseModel,ConfigDict,Field
from ..dependencies import current_identity
from ..conversations import ConversationError,ConversationConflict
from ..learning_domain import DomainError
from ..coach_reminders import ReminderSettings


def no_store(response:Response): response.headers['Cache-Control']='no-store'
router=APIRouter(prefix='/api/learning/coach',dependencies=[Depends(no_store)])

def invoke(request,service,method,*args):
    try: return getattr(getattr(request.app.state,service),method)(*args)
    except DomainError as error:
        messages={'coach_reminder_time_required':'请先选择学习时间，或确认一项带时间的近期安排。','version_conflict':'设置或提醒已更新，请读取最新状态。','coach_source_unavailable':'安排或学习状态已变化，请重新核对。'}
        raise HTTPException(error.status,detail={'kind':error.code,'code':error.code,'message':messages.get(error.code,'操作未完成，请重新核对。')}) from error
    except ConversationError as error:
        raise HTTPException(409 if isinstance(error,ConversationConflict) else 404,detail={'kind':'coach_conversation_unavailable','message':str(error)}) from error

class Key(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_key:str=Field(min_length=1,max_length=200)
class Open(Key): new_conversation:bool=False
class Source(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source_revision:str=Field(min_length=1,max_length=128)
class Purge(Key): confirm:Literal[True]
class Dispatch(Key): expected_revision:int=Field(ge=1)
class SaveReminderSettings(ReminderSettings):
    request_key:str=Field(min_length=1,max_length=200)
    expected_revision:int=Field(ge=0)

@router.get('/conversations')
def conversations(request:Request,identity=Depends(current_identity)):
    return invoke(request,'coach_conversations','list',identity)
@router.post('/conversations')
def open_conversation(payload:Open,request:Request,identity=Depends(current_identity)):
    return invoke(request,'coach_conversations','open',identity,payload.request_key,payload.new_conversation)
@router.get('/conversations/{identifier}')
def detail(identifier:str,request:Request,identity=Depends(current_identity)):
    return invoke(request,'coach_conversations','detail',identity,identifier)
@router.post('/conversations/{identifier}/actions/{action_id}/resolve')
def action(identifier:str,action_id:str,payload:Source,request:Request,identity=Depends(current_identity)):
    return invoke(request,'coach_conversations','resolve',identity,identifier,action_id,payload.source_revision)
@router.get('/conversations/{identifier}/purge')
def purge_status(identifier:str,request:Request,identity=Depends(current_identity)):
    return invoke(request,'coach_conversation_purge','status',identity,identifier)
@router.post('/conversations/{identifier}/purge')
async def purge(identifier:str,payload:Purge,request:Request,identity=Depends(current_identity)):
    try: return await request.app.state.coach_conversation_purge.purge(identity,identifier,payload.request_key)
    except ConversationError as error: raise HTTPException(404,detail={'kind':'coach_conversation_unavailable','message':str(error)}) from error
@router.get('/reminders/settings')
def reminder_settings(request:Request,identity=Depends(current_identity)):
    return invoke(request,'coach_reminders','settings',identity)
@router.get('/reminders/history')
def reminder_history(request:Request,before:int|None=Query(default=None,ge=1),identity=Depends(current_identity)):
    return invoke(request,'coach_reminders','history',identity,before)
@router.put('/reminders/settings')
def save_reminder_settings(payload:SaveReminderSettings,request:Request,identity=Depends(current_identity)):
    return invoke(request,'coach_reminders','save',identity,payload.model_dump(mode='json',exclude={'request_key','expected_revision'}),payload.expected_revision,payload.request_key)
@router.get('/reminders')
def reminders(request:Request,identity=Depends(current_identity)):
    return invoke(request,'coach_reminders','view',identity)
@router.post('/reminders/{identifier}/dispatch')
def dispatch(identifier:str,payload:Dispatch,request:Request,identity=Depends(current_identity)):
    return invoke(request,'coach_reminders','dispatch',identity,identifier,payload.expected_revision,payload.request_key)
@router.post('/reminders/{identifier}/resolve')
def reminder_target(identifier:str,payload:Source,request:Request,identity=Depends(current_identity)):
    return invoke(request,'coach_reminders','resolve',identity,identifier,payload.source_revision)
