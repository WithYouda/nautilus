"""Manually authorized Python plugin; histories belong to existing reply snapshots."""
from __future__ import annotations
import asyncio
import hashlib
import json
import base64
from io import BytesIO
from tempfile import SpooledTemporaryFile
import warnings
from PIL import Image
from uuid import uuid4
from .agent_runtime import utc_timestamp
from .learning_domain import DomainError
from .conversations import ConversationError
from .content_resources import ensure_capacity

IMAGE = 'nautilus-python:1'
ACTIVE = {'queued', 'running'}


async def docker(*args, data=None, timeout=10):
    process = await asyncio.create_subprocess_exec('docker', *args, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(process.communicate(data), timeout)
        return process.returncode, out
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def exchange(process, payload):
    async def write():
        try:
            process.stdin.write(payload)
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process.stdin.close()
    writer=asyncio.create_task(write())
    try:
        with SpooledTemporaryFile(max_size=1024*1024) as buffer:
            size=0
            while chunk:=await process.stdout.read(65536):
                size+=len(chunk);ensure_capacity(size);buffer.write(chunk)
            await writer
            await process.wait()
            buffer.seek(0)
            return buffer.read(),None
    finally:
        if not writer.done():writer.cancel()
        await asyncio.gather(writer,return_exceptions=True)


def validate_figures(figures):
    for encoded in figures:
        raw=base64.b64decode(encoded,validate=True)
        ensure_capacity(len(raw))
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as figure:
                if figure.format!='PNG':raise ValueError('invalid figure')
                ensure_capacity(figure.width*figure.height*4)
                figure.verify()


class PythonExecution:
    def __init__(self, agent, materials, credentials):
        self.agent, self.materials, self.credentials = agent, materials, credentials
        self.chats = materials.conversations
        self.jobs = {}
        self.lock = asyncio.Lock()
        self.image = None
        self.instance = hashlib.sha256(str(agent.database.database_path).encode()).hexdigest()[:24]

    def settings(self, owner):
        raw = self.credentials.get('python-plugin:' + owner)
        return json.loads(raw) if raw else dict(enabled=False, timeout_seconds=30, memory_mb=512, revision=0)

    async def info(self, owner):
        try:
            code, out = await docker('image','inspect',IMAGE,'--format','{{.Id}}',timeout=5)
            self.image = out.decode().strip() if code == 0 else None
        except (OSError, asyncio.TimeoutError):
            self.image = None
        return {**self.settings(owner), 'id':'python', 'name':'Python 代码', 'available':bool(self.image),
            'libraries':['Python 3.12', 'NumPy 2.2.6', 'pandas 2.2.3', 'Matplotlib 3.10.1']}

    def audit(self, owner, operation, result, identifier=None):
        with self.agent.database.transaction() as c:
            self.agent._audit(c,owner,operation,result,identifier,actor_id=owner)

    async def configure(self, owner, payload):
        async with self.lock:
            current = self.settings(owner)
            if current['revision'] != payload['revision']:
                raise DomainError('version_conflict')
            current = {**payload, 'revision':current['revision']+1}
            self.credentials.set('python-plugin:'+owner,json.dumps(current))
            if not current['enabled']:
                for job in list(self.jobs.values()):
                    if job['owner'] == owner: await self.stop(job,'disabled')
            self.audit(owner,'PythonPluginSettings','enabled' if current['enabled'] else 'disabled')
            return {**await self.info(owner)}

    def source(self, owner, origin):
        kind, scope, answer = origin['kind'],origin['id'],origin['answer_id']
        self.materials._owned_scope(owner,kind,scope)
        if kind == 'conversation':
            db, table, field = self.chats.database, 'ai_run','config_snapshot_json'
            row = db.fetchone('''SELECT r.id,r.config_snapshot_json AS snapshot,m.content,m.status
                FROM ai_run r JOIN message m ON m.id=r.response_message_id
                WHERE r.identity_id=? AND r.conversation_id=? AND m.id=?''',(owner,scope,answer))
            terminal = 'complete'
        else:
            db, table, field = self.agent.database,'learning_discussion_turn','provider_snapshot_json'
            row = db.fetchone('''SELECT id,provider_snapshot_json AS snapshot,assistant_content AS content,status
                FROM learning_discussion_turn WHERE discussion_id=? AND id=?''',(scope,answer))
            terminal = 'succeeded'
        if row is None or row['status'] != terminal or not row['content']:
            raise DomainError('python_source_unavailable',409)
        snapshot = json.loads(row['snapshot'] or '{}')
        if (snapshot.get('source_scope') or {}).get('purged'):
            raise DomainError('python_source_unavailable',409)
        return db,table,field,row['id'],snapshot

    def history(self, owner, origin):
        *_, snapshot = self.source(owner,origin)
        return [run for run in snapshot.get('python_runs',[]) if run['origin']==origin]

    def write(self, owner, origin, transform):
        # Match the shared material-clear lock order across the two databases.
        with self.materials.lock, self.agent.database._lock, self.chats.database._lock:
            db,table,field,identifier,_ = self.source(owner,origin)
            with db.transaction(immediate=True) as c:
                *_, snapshot = self.source(owner,origin)
                snapshot['python_runs'] = transform(snapshot.get('python_runs',[]))
                c.execute(f'UPDATE {table} SET {field}=? WHERE id=?',
                          (json.dumps(snapshot,ensure_ascii=False),identifier))

    async def start(self, owner, origin, payload):
        async with self.lock:
            history = self.history(owner,origin)
            old = next((x for x in history if x['request_key']==payload['request_key']),None)
            if old:
                if old['code']!=payload['code'] or old['stdin']!=payload['stdin']:
                    raise DomainError('idempotency_conflict')
                return old
            settings = self.settings(owner)
            if not settings['enabled']: raise DomainError('python_disabled',409)
            if any(j['owner']==owner for j in self.jobs.values()): raise DomainError('python_busy',409)
            info = await self.info(owner)
            if not info['available']: raise DomainError('python_unavailable',503)
            ensure_capacity(len(payload['code'].encode())+len(payload['stdin'].encode()))
            run = dict(id=str(uuid4()),origin=origin,request_key=payload['request_key'],
                code=payload['code'],stdin=payload['stdin'],status='queued',created_at=utc_timestamp(),
                finished_at=None,result=None,reason=None,
                environment=dict(image=self.image,libraries=info['libraries'],timeout_seconds=settings['timeout_seconds'],memory_mb=settings['memory_mb']))
            self.write(owner,origin,lambda runs:[*runs,run])
            self.audit(owner,'PythonExecution','accepted',run['id'])
            job=dict(owner=owner,origin=origin,run=run,reason='canceled')
            job['task']=asyncio.create_task(self.execute(job))
            self.jobs[run['id']]=job
            return run

    def update(self, job, **changes):
        identifier=job['run']['id']
        def change(runs):
            found=False
            result=[]
            for run in runs:
                if run['id']==identifier:
                    found=True;run={**run,**changes}
                result.append(run)
            if not found: raise DomainError('python_source_unavailable')
            return result
        self.write(job['owner'],job['origin'],change)

    async def execute(self,job):
        run=job['run'];name='nautilus-python-'+run['id'];env=run['environment']
        process=None;reader=None;status='failed';result=None;reason='execution_failed'
        try:
            self.update(job,status='running')
            process=await asyncio.create_subprocess_exec('docker','run','--rm','--pull=never','--name',name,
                '--label','nautilus.python='+self.instance,'--network','none','--read-only','--cap-drop','ALL',
                '--security-opt','no-new-privileges','--pids-limit','64','--memory',str(env['memory_mb'])+'m',
                '--memory-swap',str(env['memory_mb'])+'m','--cpus','1','--ulimit','core=0',
                '--tmpfs','/work:rw,nosuid,nodev,noexec,size=64m,uid=65534,gid=65534',
                '--user','65534:65534','-i',env['image'],
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
            reader=asyncio.create_task(exchange(process,json.dumps({'code':run['code'],'stdin':run['stdin']}).encode()))
            deadline=asyncio.get_running_loop().time()+env['timeout_seconds']
            while not reader.done():
                if asyncio.get_running_loop().time()>=deadline:
                    status,reason='timed_out','timeout';break
                # Source deletion/clearing is a revocation, including during execution.
                if not any(x['id']==run['id'] for x in self.history(job['owner'],job['origin'])):
                    raise DomainError('python_source_unavailable')
                await asyncio.wait({reader},timeout=.2)
            else:
                raw,_=reader.result()
                ensure_capacity(len(raw))
                if process.returncode == 0:
                    value=json.loads(raw)
                    if (not isinstance(value,dict) or type(value.get('exit_code')) is not int
                        or not isinstance(value.get('stdout'),str) or not isinstance(value.get('stderr'),str)
                        or not isinstance(value.get('figures'),list) or any(not isinstance(x,str) for x in value['figures'])):
                        raise ValueError('invalid output')
                    validate_figures(value['figures'])
                    result=value
                    status='succeeded' if value['exit_code']==0 else 'failed'
                    reason=None if status=='succeeded' else 'python_error'
                elif process.returncode==137:
                    reason='resource_limit'
        except asyncio.CancelledError:
            status,reason='canceled',job['reason']
        except (DomainError,ConversationError):
            status,reason='canceled','source_unavailable'
        except Exception:
            status,reason='failed','execution_failed'
        finally:
            try: await docker('rm','-f',name,timeout=10)
            except (OSError,asyncio.TimeoutError): pass
            if process is not None and process.returncode is None:
                process.kill();await process.wait()
            if reader is not None:
                if not reader.done():reader.cancel()
                await asyncio.gather(reader,return_exceptions=True)
            try:self.update(job,status=status,reason=reason,result=result,finished_at=utc_timestamp())
            except (DomainError,ConversationError):pass
            self.audit(job['owner'],'PythonExecution',status,run['id'])
            self.jobs.pop(run['id'],None)

    async def stop(self, job, reason):
        job['reason']=reason
        job['task'].cancel()
        await asyncio.gather(job['task'],return_exceptions=True)
        # A task canceled before its first instruction never enters finally.
        if self.jobs.pop(job['run']['id'],None) is not None:
            try:self.update(job,status='canceled',reason=reason,finished_at=utc_timestamp())
            except (DomainError,ConversationError):pass
            self.audit(job['owner'],'PythonExecution','canceled',job['run']['id'])

    async def cancel(self, owner, origin, identifier):
        run=next((x for x in self.history(owner,origin) if x['id']==identifier),None)
        if not run:raise DomainError('not_found',404)
        job=self.jobs.get(identifier)
        if job:
            await self.stop(job,'canceled')
        return next(x for x in self.history(owner,origin) if x['id']==identifier)

    async def recover(self):
        # Only this database's containers belong to this runtime. Never touch
        # other Docker workloads or another trial's executions.
        try:
            code,raw=await docker('ps','-aq','--filter','label=nautilus.python='+self.instance,timeout=5)
            if code==0:
                for identifier in raw.decode().split():await docker('rm','-f',identifier)
        except (OSError,asyncio.TimeoutError):pass
        for db,table,field in ((self.chats.database,'ai_run','config_snapshot_json'),(self.agent.database,'learning_discussion_turn','provider_snapshot_json')):
            with db.transaction() as c:
                for row in c.execute(f"SELECT id,{field} FROM {table} WHERE json_type({field}, '$.python_runs')='array'").fetchall():
                    snapshot=json.loads(row[field]);changed=False
                    for run in snapshot['python_runs']:
                        if run['status'] in ACTIVE:
                            run.update(status='interrupted',reason='restarted',finished_at=utc_timestamp());changed=True
                    if changed:c.execute(f'UPDATE {table} SET {field}=? WHERE id=?',(json.dumps(snapshot,ensure_ascii=False),row['id']))

    async def shutdown(self):
        await asyncio.gather(*(self.stop(job,'service_stopped') for job in list(self.jobs.values())))
