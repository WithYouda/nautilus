"""New coach scope on the real chat runtime; only synthetic Provider requests."""
import json
import sqlite3
import shutil
from contextlib import closing
import httpx
import pytest
from app.conversation_branches import create_branch
from app.conversations import ConversationConflict
from app.learning_production import create_learning_backup,restore_learning_backup,ProductionLearningDatabaseError
from app.purge_storage import register_backup
from fastapi.testclient import TestClient
from app.main import create_app
from conftest import build_settings
from test_ai_conversations import streaming_handler
from test_evidence_claims import authorize
from test_plan_organization import plan,task,rows
from test_managed_purge import absent,snapshot
from app.learning_domain import DomainError

BASE='/api/learning/coach/conversations'

@pytest.fixture
def coach_chat(client):
    identity=authorize(client);organization=plan(client,title='COACH_PLAN_PRIVATE_TITLE');created=task(client,organization)
    response=client.put('/api/ai/provider',json={'display_name':'synthetic coach','base_url':'https://synthetic.example/v1','model':'mock-coach','api_key':'sk-synthetic-only'})
    assert response.status_code==200,response.text
    state={'client':client,'identity':identity,'db':client.app.state.learning.database,'chats':client.app.state.conversations,
        'calls':[],'plan':organization['plan']['id'],'task':created}
    def handler(request):
        data=json.loads(request.content);state['calls'].append(data)
        if not data.get('stream'): return httpx.Response(200,json={'choices':[{'message':{'content':'合成教练标题'}}]})
        answer='可以先用今天20分钟继续合成任务，精力不足时先做一个小步骤。COACH_REPLY_PRIVATE'
        return httpx.Response(200,text='data: '+json.dumps({'choices':[{'delta':{'content':answer}}]},ensure_ascii=False)+'\n\ndata: [DONE]\n\n')
    client.app.state.ai_runs.transport=httpx.MockTransport(handler)
    return state

def open_chat(ctx,key='open',new=False):
    response=ctx['client'].post(BASE,json={'request_key':key,'new_conversation':new})
    assert response.status_code==200,response.text
    return response.json()

def send(ctx,identifier,key='message',**changes):
    response=ctx['client'].post('/api/ai/conversations/'+identifier+'/messages',json={'content':'我今天有20分钟，没精力，有些拖延。COACH_USER_PRIVATE','client_message_id':key,**changes})
    assert response.status_code==202,response.text
    value=response.json();stream=ctx['client'].get('/api/ai/runs/'+value['run']['id']+'/stream')
    assert stream.status_code==200,stream.text
    return value,stream.text

def test_new_domain_role_reuses_chat_and_isolates_teaching_and_formal_facts(coach_chat):
    ctx=coach_chat;client=ctx['client'];detail=open_chat(ctx);identifier=detail['conversation']['id']
    assert detail['coach']['role']=='coach'
    assert open_chat(ctx)['conversation']['id']==identifier
    assert open_chat(ctx,'other-open')['conversation']['id']==identifier
    assert 'COACH_PLAN_PRIVATE_TITLE' in json.dumps(detail['context'],ensure_ascii=False)
    before=rows(ctx['db'],('learning_session','learning_action','learning_delegation','learning_completion','learning_evidence_claim','learning_event'))
    response,stream=send(ctx,identifier)
    assert 'COACH_REPLY_PRIVATE' in stream and '"coach"' in stream
    detail=client.get(BASE+'/'+identifier).json();message=detail['messages'][-1]
    assert message['coach']['actions'] and message['teaching'] is None
    assert before==rows(ctx['db'],before)
    snapshot=json.loads(ctx['chats'].owned_run(ctx['identity']['id'],response['run']['id'])['config_snapshot_json'])
    assert 'teaching' not in snapshot and snapshot['coach']['inputs']['plans'][0]['id']==ctx['plan']
    repeated=client.post('/api/ai/conversations/'+identifier+'/messages',json={'content':'我今天有20分钟，没精力，有些拖延。COACH_USER_PRIVATE','client_message_id':'message'})
    assert repeated.json()['run']['id']==response['run']['id'] and not repeated.json()['created']
    assert len([call for call in ctx['calls'] if call.get('stream')])==1
    assert client.get(BASE).json()['items'][0]['conversation_id']==identifier
    assert next(v for v in client.get('/api/ai/conversations').json() if v['id']==identifier)['conversation_role']=='coach'
    for changes in ({'search':{'mode':'native'}},{'teaching_mode':'stepwise'},{'source_scope':{'mode':'reference','version_ids':['invented']}},{'help_request':'hint'}):
        assert client.post('/api/ai/conversations/'+identifier+'/messages',json={'content':'bypass','client_message_id':'bypass',**changes}).status_code in {400,409,422}
    assert client.post('/api/ai/conversations/'+identifier+'/branches',json={'message_id':message['id'],'request_key':'branch'}).status_code==409
    with pytest.raises(ConversationConflict): create_branch(ctx['chats'],ctx['identity']['id'],identifier,message['id'],'direct-branch')
    action=message['coach']['actions'][0]
    result=client.post(BASE+'/'+identifier+'/actions/'+action['id']+'/resolve',json={'source_revision':action['source_revision']})
    assert result.status_code==200,result.text
    assert before==rows(ctx['db'],before)

def test_complete_cross_database_erasure_registered_backups_and_restore_barrier(coach_chat,tmp_path):
    ctx=coach_chat;client=ctx['client'];identifier=open_chat(ctx)['conversation']['id'];send(ctx,identifier)
    learning_backup,_,_=create_learning_backup(ctx['db'].database_path,tmp_path/'backups',label='synthetic')
    ordinary_backup=snapshot(ctx['chats'].database,tmp_path/'ordinary-backup.sqlite3');register_backup(ctx['chats'].database.database_path,ordinary_backup)
    unmanaged=snapshot(ctx['db'],tmp_path/'unmanaged.sqlite3')
    preview=client.get(BASE+'/'+identifier+'/purge').json();assert preview['impact']['messages']==2
    result=client.post(BASE+'/'+identifier+'/purge',json={'confirm':True,'request_key':'purge'})
    assert result.status_code==200,result.text
    assert result.json()['purge_report']['status']=='complete',result.text
    for path in (ctx['chats'].database.database_path,ordinary_backup): absent(path,'COACH_USER_PRIVATE','COACH_REPLY_PRIVATE','COACH_PLAN_PRIVATE_TITLE')
    assert client.get('/api/ai/conversations/'+identifier).status_code==400
    assert client.get(BASE+'/'+identifier).status_code==404
    assert client.post(BASE+'/'+identifier+'/purge',json={'confirm':True,'request_key':'purge'}).json()['purge_report']['status']=='complete'
    with pytest.raises(ProductionLearningDatabaseError,match='purged|barrier'): restore_learning_backup(unmanaged,ctx['db'].database_path)
    restore_learning_backup(learning_backup,ctx['db'].database_path)

def test_plan_purge_clears_only_dependent_assistants_and_restored_ordinary_copies(coach_chat,tmp_path):
    ctx=coach_chat;client=ctx['client'];identifier=open_chat(ctx)['conversation']['id'];send(ctx,identifier)
    backup=snapshot(ctx['chats'].database,tmp_path/'ordinary-backup.sqlite3');register_backup(ctx['chats'].database.database_path,backup)
    organization=client.get('/api/learning/plans/'+ctx['plan']+'/organization').json()
    response=client.post('/api/learning/plans/'+ctx['plan']+'/organization-content/purge',json={'expected_revision':organization['revision'],'request_key':'plan-purge','confirmation':'PURGE'})
    assert response.status_code==200,response.text
    assert response.json()['purge_report']['status']=='complete',response.text
    for path in (ctx['chats'].database.database_path,backup): absent(path,'COACH_PLAN_PRIVATE_TITLE','COACH_REPLY_PRIVATE')
    messages=client.get(BASE+'/'+identifier).json()['messages']
    assert 'COACH_USER_PRIVATE' in messages[0]['content'] and messages[1]['content']==''

def test_json_same_run_reply_stream_and_actions_validate_target_ids(coach_chat,monkeypatch):
    import re
    ctx=coach_chat;identifier=open_chat(ctx)['conversation']['id']
    monkeypatch.setattr(ctx['chats'],'teaching_output',lambda *args,**kwargs:{'format':'json'})
    def handler(request):
        data=json.loads(request.content)
        if not data.get('stream'): return httpx.Response(200,json={'choices':[{'message':{'content':'合成标题'}}]})
        assert data['response_format']=={'type':'json_object'}
        system=data['messages'][0]['content'];raw=system.split('当前最小摘要：',1)[1]
        inputs=json.JSONDecoder().raw_decode(raw)[0];token=re.search(r'token必须为([^。]+)',system)[1]
        envelope={'reply':'可以先做5分钟🙂。','coach':{'actions':[inputs['actions'][0]['id']],'unknowns':[]},'token':token}
        encoded=json.dumps(envelope,ensure_ascii=False)
        return httpx.Response(200,text=''.join('data: '+json.dumps({'choices':[{'delta':{'content':encoded[i:i+7]}}]},ensure_ascii=False)+'\n\n' for i in range(0,len(encoded),7))+'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    ctx['client'].app.state.ai_runs.transport=httpx.MockTransport(handler)
    result,stream=send(ctx,identifier)
    message=ctx['client'].get(BASE+'/'+identifier).json()['messages'][-1]
    assert message['content']=='可以先做5分钟🙂。' and message['coach']['actions']
    assert message['teaching'] is None and 'token' not in stream
    ctx['client'].app.state.ai_runs._runs.clear()
    replay=ctx['client'].get('/api/ai/runs/'+result['run']['id']+'/stream').text
    assert '"coach"' in replay

def test_mapping_insert_failure_leaves_no_old_global_orphan(coach_chat):
    ctx=coach_chat;before=ctx['chats'].database.fetchone('SELECT COUNT(*) FROM conversation')[0]
    with ctx['db'].transaction() as c: c.execute("CREATE TEMP TRIGGER reject_mapping BEFORE INSERT ON learning_coach_conversation BEGIN SELECT RAISE(ABORT,'synthetic mapping failure'); END")
    with pytest.raises(sqlite3.IntegrityError): open_chat(ctx)
    assert ctx['chats'].database.fetchone('SELECT COUNT(*) FROM conversation')[0]==before
    assert ctx['db'].fetchone('SELECT COUNT(*) FROM learning_coach_request')[0]==0

def test_coach_purge_checks_both_database_owners(coach_chat):
    ctx=coach_chat;owner=ctx['identity']['id'];ordinary=ctx['chats'].database
    with ordinary.transaction() as c:
        identity=dict(c.execute('SELECT * FROM local_identity WHERE id=?',(owner,)).fetchone());identity['id']='other-owner';identity['device_id']='other-device'
        c.execute('INSERT INTO local_identity ('+','.join(identity)+') VALUES ('+','.join('?' for _ in identity)+')',tuple(identity.values()))
    foreign=ctx['chats'].create_conversation('other-owner')['conversation']['id']
    with ctx['db'].transaction() as c: c.execute("INSERT INTO learning_coach_conversation VALUES (?,?,1,'now','now',NULL)",(owner,foreign))
    before=[tuple(r) for r in ordinary.fetchall('SELECT * FROM conversation WHERE id=?',(foreign,))]
    assert ctx['client'].post(BASE+'/'+foreign+'/purge',json={'confirm':True,'request_key':'invalid-owner'}).status_code==404
    assert before==[tuple(r) for r in ordinary.fetchall('SELECT * FROM conversation WHERE id=?',(foreign,))]

@pytest.mark.parametrize('source_purge',[False,True])
def test_actual_startup_scrubs_independently_rolled_back_ordinary_database(tmp_path,source_purge):
    settings=build_settings(tmp_path)
    with TestClient(create_app(settings,provider_transport=httpx.MockTransport(streaming_handler))) as client:
        identity=authorize(client);organization=plan(client,title='COACH_STARTUP_PRIVATE_TITLE');task(client,organization)
        result=client.put('/api/ai/provider',json={'display_name':'synthetic','base_url':'https://synthetic.example/v1','model':'mock-coach','api_key':'sk-synthetic-only'})
        assert result.status_code==200,result.text
        ctx={'client':client};identifier=open_chat(ctx)['conversation']['id'];send(ctx,identifier)
        original=snapshot(client.app.state.database,tmp_path/'unmanaged-ordinary.sqlite3')
        if source_purge:
            current=client.get('/api/learning/plans/'+organization['plan']['id']+'/organization').json()
            response=client.post('/api/learning/plans/'+organization['plan']['id']+'/organization-content/purge',json={'expected_revision':current['revision'],'request_key':'source','confirmation':'PURGE'})
        else: response=client.post(BASE+'/'+identifier+'/purge',json={'confirm':True,'request_key':'self'})
        assert response.status_code==200,response.text
    shutil.copyfile(original,settings.database_path)
    with TestClient(create_app(settings,provider_transport=httpx.MockTransport(streaming_handler))) as client:
        authorize(client)
        response=client.get('/api/ai/conversations/'+identifier)
        if source_purge:
            assert response.status_code==200,response.text
            assert 'COACH_USER_PRIVATE' in response.json()['messages'][0]['content']
            assert response.json()['messages'][1]['content']==''
            absent(settings.database_path,'COACH_STARTUP_PRIVATE_TITLE')
        else:
            assert response.status_code==400
            absent(settings.database_path,'COACH_USER_PRIVATE','COACH_STARTUP_PRIVATE_TITLE')
