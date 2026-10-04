"""Learning-records graph routes. Every mutation remains an owner decision."""
from typing import Literal
from fastapi import APIRouter, Depends, Request, Response, Query, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from ..dependencies import current_identity
from ..core.graph_commands import RelationFields
from ..core.commands import CreateOutcome
from ..learning_domain import DomainError
from ..managed_purge import ManagedPurge


def private_response(response:Response):
    response.headers['Cache-Control']='no-store'

router=APIRouter(prefix='/api/learning/outcome-graph',dependencies=[Depends(private_response)])


def fail(error):
    messages={'not_found':'成果或引用当前不可查看。','version_conflict':'内容已更新，请刷新后重试。',
        'idempotency_conflict':'这次保存请求已被其他内容使用，请刷新后重试。',
        'graph_duplicate_relation':'这项关系已经存在。','graph_relation_cycle':'这项关系会形成循环，请调整两个成果。',
        'graph_relation_conflict':'这两个成果已有互相矛盾的关系，请先调整已有关系。',
        'graph_contains_requires_composite':'包含关系须从综合成果连接到组成成果。',
        'graph_self_relation':'请选择两个不同的成果。','graph_provider_unavailable':'请先配置可用的AI模型。',
        'graph_run_inactive':'这次建议已结束，请刷新查看结果。','graph_candidate_inactive':'这项建议已处理或清除，请刷新。',
        'graph_relation_inactive':'这项关系已撤销或清除，请刷新。',
        'graph_input_changed':'建议依据已变化或清除，请重新选择成果。',
        'graph_candidate_out_of_scope':'建议只能采用本次选定的成果。',
        'composite_not_verifiable':'请为学习委托选择可验证成果。'}
    raise HTTPException(status_code=error.status,detail={'kind':error.code,'code':error.code,'message':messages.get(error.code,'操作未完成，请刷新后重试。')}) from error


class Key(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_key:str=Field(min_length=1,max_length=200)

class OutcomeCreate(CreateOutcome,Key):
    pass

class RelationCreate(RelationFields,Key):
    pass

class RelationRevise(RelationCreate):
    expected_revision:int=Field(ge=1)

class Revision(Key):
    expected_revision:int=Field(ge=1)

class Purge(Revision):
    confirmation:Literal['PURGE']

class Suggest(Key):
    outcome_ids:list[str]=Field(min_length=2,max_length=30)

class CandidateReview(Revision):
    decision:Literal['accept','reject']
    relation:RelationFields|None=None


def without_key(payload):
    value=payload.model_dump(mode='json')
    key=value.pop('request_key')
    return value,key

@router.get('')
@router.get('/')
def graph(request:Request,plan_id:str|None=Query(default=None),identity=Depends(current_identity)):
    try:
        return request.app.state.outcome_graph.graph(identity,plan_id)
    except DomainError as error:
        fail(error)

@router.post('/outcomes',status_code=201)
def outcome(payload:OutcomeCreate,request:Request,identity=Depends(current_identity)):
    try:
        value,key=without_key(payload)
        return request.app.state.outcome_graph.create_outcome(identity,value,key)
    except DomainError as error:
        fail(error)

@router.post('/relations',status_code=201)
def create_relation(payload:RelationCreate,request:Request,identity=Depends(current_identity)):
    try:
        value,key=without_key(payload)
        return request.app.state.outcome_graph.create_relation(identity,value,key)
    except DomainError as error:
        fail(error)

@router.get('/relations/{relation_id}')
def relation(relation_id:str,request:Request,identity=Depends(current_identity)):
    try:
        return request.app.state.outcome_graph.relation(identity,relation_id)
    except DomainError as error:
        fail(error)

@router.post('/relations/{relation_id}/revise')
def revise_relation(relation_id:str,payload:RelationRevise,request:Request,identity=Depends(current_identity)):
    try:
        value,key=without_key(payload)
        return request.app.state.outcome_graph.revise_relation(identity,relation_id,value,key)
    except DomainError as error:
        fail(error)

@router.post('/relations/{relation_id}/revoke')
def revoke_relation(relation_id:str,payload:Revision,request:Request,identity=Depends(current_identity)):
    try:
        value,key=without_key(payload)
        return request.app.state.outcome_graph.revoke_relation(identity,relation_id,value,key)
    except DomainError as error:
        fail(error)

@router.post('/relations/{relation_id}/purge')
def purge_relation(relation_id:str,payload:Purge,request:Request,identity=Depends(current_identity)):
    try:
        value,key=without_key(payload)
        return request.app.state.outcome_graph.purge_relation(identity,relation_id,value,key)
    except DomainError as error:
        fail(error)

@router.get('/relations/{relation_id}/purge-status')
def relation_purge_status(relation_id:str,request:Request,identity=Depends(current_identity)):
    try:
        return ManagedPurge(request.app.state.learning).status(identity,'graph_relation',relation_id)
    except DomainError as error:
        fail(error)

@router.post('/suggestions',status_code=201)
async def suggest(payload:Suggest,request:Request,identity=Depends(current_identity)):
    try:
        return await request.app.state.outcome_graph.start(identity,payload.outcome_ids,payload.request_key)
    except DomainError as error:
        fail(error)

@router.get('/suggestions/{run_id}')
def run(run_id:str,request:Request,identity=Depends(current_identity)):
    try:
        return request.app.state.outcome_graph.run(identity,run_id)
    except DomainError as error:
        fail(error)

@router.post('/suggestions/{run_id}/cancel')
async def cancel(run_id:str,payload:Revision,request:Request,identity=Depends(current_identity)):
    try:
        value,key=without_key(payload)
        return await request.app.state.outcome_graph.cancel(identity,run_id,value,key)
    except DomainError as error:
        fail(error)

@router.post('/suggestions/{run_id}/candidates/{candidate_id}/review')
def candidate(run_id:str,candidate_id:str,payload:CandidateReview,request:Request,identity=Depends(current_identity)):
    try:
        value,key=without_key(payload)
        return request.app.state.outcome_graph.review(identity,run_id,candidate_id,value,key)
    except DomainError as error:
        fail(error)

@router.post('/suggestions/{run_id}/purge')
async def purge_run(run_id:str,payload:Purge,request:Request,identity=Depends(current_identity)):
    try:
        value,key=without_key(payload)
        return await request.app.state.outcome_graph.purge_run(identity,run_id,value,key)
    except DomainError as error:
        fail(error)

@router.get('/suggestions/{run_id}/purge-status')
def run_purge_status(run_id:str,request:Request,identity=Depends(current_identity)):
    try:
        return ManagedPurge(request.app.state.learning).status(identity,'graph_run',run_id)
    except DomainError as error:
        fail(error)
