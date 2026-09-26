from fastapi import APIRouter, Depends, Request

from ..dependencies import current_identity, learning_service
from ..delayed_follow_up import (
    DelayedFollowUpService, CreateFollowUp, DraftAnswer, SubmitAnswer,
    ScheduleFollowUp, ChooseFollowUp,
)
from ..learning_domain import DomainError
from ..managed_purge import ManagedPurge
from .learning import _raise_learning_error
from .practice import private_response


router = APIRouter(prefix='/api/learning', dependencies=[Depends(private_response)])


def service(request):
    return DelayedFollowUpService(learning_service(request))


def invoke(method, *args):
    try:
        return method(*args)
    except DomainError as error:
        _raise_learning_error(error)


@router.get('/outcomes/{outcome_id}/delayed-follow-ups')
def for_outcome(outcome_id: str, request: Request, identity=Depends(current_identity)):
    return invoke(service(request).for_outcome, identity, outcome_id)


@router.get('/delayed-follow-ups')
def due_list(request: Request, identity=Depends(current_identity)):
    return invoke(service(request).due_list, identity)


@router.post('/outcomes/{outcome_id}/delayed-follow-ups')
def create(outcome_id: str, payload: CreateFollowUp, request: Request, identity=Depends(current_identity)):
    return invoke(service(request).create, identity, outcome_id, payload)


@router.get('/delayed-follow-ups/{follow_up_id}')
def get(follow_up_id: str, request: Request, identity=Depends(current_identity)):
    return invoke(service(request).get, identity, follow_up_id)


@router.put('/delayed-follow-ups/{follow_up_id}/attempts/{attempt_id}/draft')
def draft(follow_up_id: str, attempt_id: str, payload: DraftAnswer, request: Request, identity=Depends(current_identity)):
    return invoke(service(request).draft, identity, follow_up_id, attempt_id, payload)


@router.post('/delayed-follow-ups/{follow_up_id}/attempts/{attempt_id}/submit')
def submit(follow_up_id: str, attempt_id: str, payload: SubmitAnswer, request: Request, identity=Depends(current_identity)):
    return invoke(service(request).submit, identity, follow_up_id, attempt_id, payload)


@router.post('/delayed-follow-ups/{follow_up_id}/attempts/{attempt_id}/check')
def check(follow_up_id: str, attempt_id: str, request: Request, identity=Depends(current_identity)):
    return invoke(service(request).check, identity, follow_up_id, attempt_id)


@router.post('/delayed-follow-ups/{follow_up_id}/attempts/{attempt_id}/reveal')
def reveal(follow_up_id: str, attempt_id: str, request: Request, identity=Depends(current_identity)):
    return invoke(service(request).reveal, identity, follow_up_id, attempt_id)


@router.post('/delayed-follow-ups/{follow_up_id}/views/{view_id}/display')
def display(follow_up_id: str, view_id: str, request: Request, identity=Depends(current_identity)):
    return invoke(service(request).display, identity, follow_up_id, view_id)


@router.post('/delayed-follow-ups/{follow_up_id}/schedule')
def schedule(follow_up_id: str, payload: ScheduleFollowUp, request: Request, identity=Depends(current_identity)):
    return invoke(service(request).schedule, identity, follow_up_id, payload)


@router.post('/delayed-follow-ups/{follow_up_id}/choice')
def choose(follow_up_id: str, payload: ChooseFollowUp, request: Request, identity=Depends(current_identity)):
    return invoke(service(request).choose, identity, follow_up_id, payload)


@router.post('/delayed-follow-ups/{follow_up_id}/purge')
def purge(follow_up_id: str, request: Request, identity=Depends(current_identity)):
    current = service(request)
    return invoke(ManagedPurge(current.learning).run, identity, 'delayed', follow_up_id,
                  lambda: current.purge(identity, follow_up_id))
