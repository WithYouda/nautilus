from typing import Literal
from fastapi import APIRouter,Depends,Request,Response,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from ..dependencies import current_identity
from ..learning_domain import DomainError
from ..conversations import ConversationError
from ..providers import ProviderError

MESSAGES={'python_disabled':'请先启用 Python 代码。','python_unavailable':'Python 运行环境尚未就绪。',
 'python_busy':'已有代码正在运行，请等待或先取消。','python_source_unavailable':'原回答已变化或不可查看，请重新打开。',
 'version_conflict':'设置已变化，请重新打开后再保存。','idempotency_conflict':'这次运行内容已变化，请重新运行。',
 'not_found':'运行记录不存在或当前不可查看。'}
def private(response:Response):response.headers['Cache-Control']='no-store'
router=APIRouter(prefix='/api/plugins/python',dependencies=[Depends(private)])
class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class Config(Strict):
 enabled:bool
 timeout_seconds:int=Field(ge=1,le=300)
 memory_mb:Literal[128,256,512,1024]=512
 revision:int=Field(ge=0)
class Origin(Strict):
 kind:Literal['conversation','discussion']
 id:str=Field(min_length=1,max_length=100)
 answer_id:str=Field(min_length=1,max_length=100)
class Run(Strict):
 origin:Origin
 code:str=Field(min_length=1)
 stdin:str=''
 request_key:str=Field(min_length=1,max_length=200)
class Cancel(Strict):origin:Origin

def fail(exc):
 if isinstance(exc,DomainError):raise HTTPException(exc.status,{'kind':exc.code,'message':MESSAGES.get(exc.code,'操作未完成。')}) from None
 if isinstance(exc,ProviderError):raise HTTPException(413,str(exc)) from None
 raise HTTPException(404,MESSAGES['not_found']) from None

@router.get('')
async def info(request:Request,identity=Depends(current_identity)):
 return await request.app.state.python_execution.info(identity['id'])
@router.put('')
async def configure(payload:Config,request:Request,identity=Depends(current_identity)):
 try:return await request.app.state.python_execution.configure(identity['id'],payload.model_dump())
 except (DomainError,ConversationError,ProviderError) as exc:fail(exc)
@router.get('/runs')
def history(request:Request,kind:Literal['conversation','discussion'],id:str,answer_id:str,identity=Depends(current_identity)):
 try:return request.app.state.python_execution.history(identity['id'],dict(kind=kind,id=id,answer_id=answer_id))
 except (DomainError,ConversationError,ProviderError) as exc:fail(exc)
@router.post('/runs',status_code=201)
async def run(payload:Run,request:Request,identity=Depends(current_identity)):
 try:return await request.app.state.python_execution.start(identity['id'],payload.origin.model_dump(),payload.model_dump(exclude={'origin'}))
 except (DomainError,ConversationError,ProviderError) as exc:fail(exc)
@router.post('/runs/{identifier}/cancel')
async def cancel(identifier:str,payload:Cancel,request:Request,identity=Depends(current_identity)):
 try:return await request.app.state.python_execution.cancel(identity['id'],payload.origin.model_dump(),identifier)
 except (DomainError,ConversationError,ProviderError) as exc:fail(exc)
