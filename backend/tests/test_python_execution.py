"""Real isolated container journeys; no user database or external AI requests."""
import json
import time
import subprocess
import shutil
import pytest
from test_model_control import RecordingProvider,make_client,authorize,configure_provider,make_scope,send

BASE='/api/plugins/python'

@pytest.fixture
def execution(tmp_path):
    if not shutil.which('docker') or subprocess.run(['docker','image','inspect','nautilus-python:1'],capture_output=True).returncode:
        pytest.skip('Optional real-container checks require scripts/build-python-sandbox.py')
    provider=RecordingProvider()
    with make_client(tmp_path,provider) as client:
        authorize(client);configure_provider(client)
        yield client,provider


def origin_for(client,provider,kind='conversation'):
    identifier,_,_=make_scope(client,provider,kind)
    answer=send(client,kind,identifier)
    return dict(kind=kind,id=identifier,answer_id=answer['id'])


def enable(client,**values):
    config=client.get(BASE).json()
    assert config['available'], 'Build backend/sandbox with docker build -t nautilus-python:1 first'
    result=client.put(BASE,json={k:values.get(k,True if k=='enabled' else config[k]) for k in ('enabled','timeout_seconds','memory_mb','revision')})
    assert result.status_code==200,result.text
    return result.json()


def start(client,origin,code,key='run',stdin=''):
    response=client.post(BASE+'/runs',json=dict(origin=origin,code=code,stdin=stdin,request_key=key))
    assert response.status_code==201,response.text
    return response.json()


def finish(client,origin,identifier):
    for _ in range(240):
        response=client.get(BASE+'/runs',params=origin)
        assert response.status_code==200,response.text
        run=next(r for r in response.json() if r['id']==identifier)
        if run['status'] not in {'queued','running'}:return run
        time.sleep(.05)
    raise AssertionError('code did not finish')


@pytest.mark.parametrize('kind',['conversation','discussion'])
def test_manual_scientific_code_figures_history_and_duplicate(execution,kind):
    client,provider=execution;origin=origin_for(client,provider,kind)
    before=len(provider.calls)
    assert client.post(BASE+'/runs',json=dict(origin=origin,code='print(1)',request_key='disabled')).status_code==409
    enable(client)
    code="import numpy as np\nimport pandas as pd\nimport matplotlib.pyplot as plt\nprint(pd.Series(np.arange(4)).sum())\nprint(input())\nplt.plot([1,4,2]);plt.show()"
    run=start(client,origin,code,stdin='合成输入\n');result=finish(client,origin,run['id'])
    assert result['status']=='succeeded',result
    assert result['result']['stdout']=='6\n合成输入\n'
    assert result['result']['figures'][0].startswith('iVBOR')
    assert result['code']==code and len(provider.calls)==before
    assert start(client,origin,code,stdin='合成输入\n')['id']==run['id']
    assert client.post(BASE+'/runs',json=dict(origin=origin,code='print(2)',stdin='',request_key='run')).status_code==409
    assert client.get(BASE+'/runs',params={**origin,'id':'other'}).status_code==404
    db=client.app.state.learning.database
    assert db.fetchone("SELECT COUNT(*) FROM learning_audit WHERE operation='PythonExecution' AND result='succeeded'")[0]==1


def test_container_cannot_read_host_or_network_and_errors_are_retained(execution,tmp_path):
    client,provider=execution;origin=origin_for(client,provider);enable(client)
    sentinel=tmp_path/'private.txt';sentinel.write_text('PRIVATE-HOST-SENTINEL')
    code=f"from pathlib import Path\nimport socket, os\nassert not Path({str(sentinel)!r}).exists()\nassert not Path('/var/run/docker.sock').exists()\nassert 'NAUTILUS_RUNTIME_TOKEN_FILE' not in os.environ\ns=socket.socket();s.settimeout(.2)\nassert s.connect_ex(('1.1.1.1',443)) != 0\nprint('isolation verified')\nassert False, 'synthetic failure'"
    result=finish(client,origin,start(client,origin,code)['id'])
    assert result['status']=='failed' and result['reason']=='python_error',result
    assert result['result']['stdout']=='isolation verified\n'
    assert 'synthetic failure' in result['result']['stderr']
    assert sentinel.read_text()=='PRIVATE-HOST-SENTINEL'


def test_timeout_cancel_disable_and_source_purge_do_not_publish_late_output(execution):
    client,provider=execution;origin=origin_for(client,provider);enable(client,timeout_seconds=1)
    run=start(client,origin,'while True: pass');assert finish(client,origin,run['id'])['status']=='timed_out'
    enable(client,timeout_seconds=30)
    run=start(client,origin,'import time;time.sleep(20)','cancel')
    response=client.post(BASE+'/runs/'+run['id']+'/cancel',json={'origin':origin})
    assert response.status_code==200 and response.json()['status']=='canceled',response.text
    run=start(client,origin,'import time;time.sleep(20)','disable')
    enable(client,enabled=False)
    assert finish(client,origin,run['id'])['reason']=='disabled'
    enable(client)
    run=start(client,origin,"import time;time.sleep(2);print('PRIVATE_LATE_OUTPUT')",'purge')
    db=client.app.state.conversations.database
    # The established material erasure replaces this snapshot, including its
    # adjunct history. A late container response must not restore any content.
    with db.transaction() as c:
        c.execute("UPDATE ai_run SET config_snapshot_json=? WHERE response_message_id=?",(json.dumps({'source_scope':{'purged':True}}),origin['answer_id']))
    for _ in range(100):
        if not client.app.state.python_execution.jobs:break
        time.sleep(.05)
    assert not client.app.state.python_execution.jobs
    assert client.get(BASE+'/runs',params=origin).status_code==409
    raw=db.fetchone('SELECT config_snapshot_json FROM ai_run WHERE response_message_id=?',(origin['answer_id'],))[0]
    assert 'python_runs' not in raw and 'PRIVATE_LATE_OUTPUT' not in raw


def test_material_clear_erases_execution_copy_from_live_and_managed_backup(execution,tmp_path):
    import sqlite3
    from app.purge_storage import register_backup
    client,provider=execution
    scope,_,_=make_scope(client,provider,'conversation')
    base='/api/materials/conversation/'+scope
    material=client.post(base,json={'title':'合成资料','content':'PRIVATE-PYTHON-SOURCE'}).json()
    answer=send(client,'conversation',scope,source_scope={'mode':'only','version_ids':[material['id']]})
    origin=dict(kind='conversation',id=scope,answer_id=answer['id'])
    enable(client)
    run=start(client,origin,"print('PRIVATE-PYTHON-RESULT')")
    assert finish(client,origin,run['id'])['status']=='succeeded'
    db=client.app.state.conversations.database
    path=tmp_path/'ordinary-managed.sqlite3'
    with sqlite3.connect(path) as backup:db.connection.backup(backup)
    register_backup(client.app.state.learning.database.database_path,path)
    response=client.post(base+'/'+material['material_id']+'/purge')
    assert response.status_code==200 and response.json()['purge']['status']=='complete',response.text
    for connection in (db.connection,sqlite3.connect(path)):
        raw=connection.execute('SELECT config_snapshot_json FROM ai_run WHERE response_message_id=?',(answer['id'],)).fetchone()[0]
        assert 'PRIVATE-PYTHON-RESULT' not in raw and 'python_runs' not in raw
        if connection is not db.connection:connection.close()


def test_recovery_preserves_completed_history_and_marks_stale_run_interrupted(execution):
    client,provider=execution;origin=origin_for(client,provider);enable(client)
    run=start(client,origin,'print(42)');finish(client,origin,run['id'])
    runtime=client.app.state.python_execution
    runtime.write(client.app.state.auth.identity_for_session(client.cookies.get(client.app.state.settings.cookie_name))['id'],origin,
        lambda runs:[*runs,{**runs[0],'id':'synthetic-stale','status':'running','result':None,'request_key':'stale'}])
    client.portal.call(runtime.recover)
    rows=client.get(BASE+'/runs',params=origin).json()
    assert rows[0]['status']=='succeeded' and rows[0]['result']['stdout']=='42\n'
    assert rows[1]['status']=='interrupted' and rows[1]['result'] is None
