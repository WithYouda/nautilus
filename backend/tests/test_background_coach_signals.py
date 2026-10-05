"""The optional sidechannel follows real successful answers and current sessions."""
import json
from app.core.commands import StartSession,EndSession
from app.learning_domain import Principal
from test_ai_conversations import make_client,configure_provider
from test_evidence_claims import authorize
from test_teaching_output_runtime import StructuredTeachingProvider,checked,proposal
from test_teaching_runtime import new_chat,chat_turn
from test_plan_organization import plan,task

BASE='/api/learning/coach'

def bound_room(client):
    identity=authorize(client);organization=plan(client);item=task(client,organization)
    db=client.app.state.learning.database;core=client.app.state.learning.core
    version=db.fetchone('SELECT version FROM learning_action WHERE id=?',(item['action_id'],))[0]
    session=core.execute(Principal.user(identity['id']),StartSession(delegation_id=item['delegation_id'],expected_version=version),'signal-session')['id']
    cid=new_chat(client)
    response=client.put('/api/learning/sessions/'+session+'/room',json={'conversation_id':cid})
    assert response.status_code==200,response.text
    return identity,item,session,cid

def test_actual_json_answer_signal_source_correction_and_new_session_binding(tmp_path):
    provider=StructuredTeachingProvider()
    with make_client(tmp_path,provider) as client:
        identity,item,session,cid=bound_room(client)
        checked(client,configure_provider(client))
        provider.next={'body':'可以单独安排这项工作。','proposal':proposal(assignment_signal={'kind':'separate_work_requested','quote':'单独安排一个任务'})}
        answer=chat_turn(client,cid,'请单独安排一个任务')
        assert answer['teaching']['assignment_signal']['immediate'] is True
        first=client.get(BASE+'/signals').json()['items'][0]
        assert first['session_id']==session and first['action_id']==item['action_id']
        assert len(provider.calls)==1
        excluded=client.post(BASE+'/signals/'+first['id']+'/corrections',json={'operation':'exclude','expected_revision':1,'request_key':'exclude'})
        assert excluded.status_code==200 and excluded.json()['status']=='excluded'
        restored=client.post(BASE+'/signals/'+first['id']+'/corrections',json={'operation':'restore','expected_revision':2,'request_key':'restore'})
        assert restored.status_code==200 and restored.json()['status']=='active'
        db=client.app.state.learning.database;core=client.app.state.learning.core;p=Principal.user(identity['id'])
        version=lambda:db.fetchone('SELECT version FROM learning_action WHERE id=?',(item['action_id'],))[0]
        core.execute(p,EndSession(session_id=session,disposition='interrupted',expected_version=version()),'signal-pause')
        second=core.execute(p,StartSession(delegation_id=item['delegation_id'],expected_version=version()),'signal-second')['id']
        # The existing room relation remains historical; a new request must
        # capture the actual running session rather than reuse that relation.
        answer=chat_turn(client,cid,'再次单独安排一个任务')
        signals=client.get(BASE+'/signals').json()['items']
        assert len(signals)==2 and signals[0]['session_id']==second
        assert len(provider.calls)==2

def test_unchecked_plain_answer_keeps_body_and_never_adds_signal_call(tmp_path):
    provider=StructuredTeachingProvider()
    with make_client(tmp_path,provider) as client:
        _,_,_,cid=bound_room(client);configure_provider(client)
        provider.next={'body':'普通回答仍可继续。','proposal':proposal(assignment_signal={'kind':'separate_work_requested','quote':'单独安排一个任务'})}
        answer=chat_turn(client,cid,'单独安排一个任务')
        assert answer['content']=='普通回答仍可继续。'
        assert answer['teaching'].get('assignment_signal') is None
        assert client.get(BASE+'/signals').json()['items']==[] and len(provider.calls)==1

def test_discussion_real_same_response_signal_uses_owned_sources(tmp_path):
    import asyncio
    from test_project_runtime import ready_discussion
    from test_learning_verifications import IDENTITY
    provider=StructuredTeachingProvider()
    with make_client(tmp_path,provider) as client:
        async def journey():
            service,did,_,_=await ready_discussion(client,provider)
            provider.next={'body':'在当前作品任务中核对，原任务保持。','proposal':proposal(assignment_signal={'kind':'cannot_continue','quote':'暂时无法继续'})}
            result=await service.send(IDENTITY,did,'暂时无法继续','discussion-signal')
            turn=result['turns'][-1]
            assert turn['status']=='succeeded' and turn['teaching']['assignment_signal']['immediate'] is True
            signals=client.app.state.background_coach.signals(IDENTITY)['items']
            assert signals and signals[0]['source']['id']==turn['id'] and signals[0]['source_available'], [dict(r) for r in service.db.fetchall("SELECT operation,reason_code FROM learning_audit WHERE operation='RecordCoachSignal'")]
            assert len(provider.calls)==1
        asyncio.run(journey())
