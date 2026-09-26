from fastapi import APIRouter, Depends, Request, Response

from ..dependencies import current_identity, verification_service
from ..learning_domain import DomainError
from ..managed_purge import ManagedPurge
from ..practice import PracticeService, PracticeCreate, PracticeChoice, PracticeAnswer, PracticeRun
from .learning import _raise_learning_error


def private_response(response: Response):
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/api/learning', dependencies=[Depends(private_response)])


def service(request):
    return PracticeService(verification_service(request))


@router.get('/verifications/{verification_id}/practices')
def list_practices(verification_id: str, submission_id: str, evaluation_id: str, question_id: str,
                   request: Request, identity=Depends(current_identity)):
    try:
        return service(request).list(identity, verification_id, submission_id, evaluation_id, question_id)
    except DomainError as error:
        _raise_learning_error(error)


@router.post('/verifications/{verification_id}/practices')
async def create_practice(verification_id: str, payload: PracticeCreate, request: Request, identity=Depends(current_identity)):
    try:
        return await service(request).create(identity, verification_id, payload)
    except DomainError as error:
        _raise_learning_error(error)


@router.get('/practices/{practice_id}')
def get_practice(practice_id: str, request: Request, identity=Depends(current_identity)):
    try:
        return service(request).get(identity, practice_id)
    except DomainError as error:
        _raise_learning_error(error)


@router.post('/practices/{practice_id}/choice')
def choose_practice(practice_id: str, payload: PracticeChoice, request: Request, identity=Depends(current_identity)):
    try:
        return service(request).choose(identity, practice_id, payload.choice)
    except DomainError as error:
        _raise_learning_error(error)


@router.post('/practices/{practice_id}/attempts')
def save_practice_answer(practice_id: str, payload: PracticeAnswer, request: Request, identity=Depends(current_identity)):
    try:
        return service(request).submit(identity, practice_id, payload)
    except DomainError as error:
        _raise_learning_error(error)


@router.post('/practices/{practice_id}/runs')
async def run_practice(practice_id: str, payload: PracticeRun, request: Request, identity=Depends(current_identity)):
    try:
        return await service(request).run(identity, practice_id, payload)
    except DomainError as error:
        _raise_learning_error(error)


@router.post('/practices/{practice_id}/runs/{run_id}/display')
def display_practice(practice_id: str, run_id: str, request: Request, identity=Depends(current_identity)):
    try:
        return service(request).display(identity, practice_id, run_id)
    except DomainError as error:
        _raise_learning_error(error)


@router.post('/practices/{practice_id}/purge')
def purge_practice(practice_id: str, request: Request, identity=Depends(current_identity)):
    try:
        current = service(request)
        return ManagedPurge(current.learning).run(identity, 'practice', practice_id, lambda: current.purge(identity, practice_id))
    except DomainError as error:
        _raise_learning_error(error)
