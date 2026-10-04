"""D1 graph commands and replay projections; no evidence ownership changes."""
import hashlib
import json
from uuid import uuid4

from ..learning_domain import DomainError
from .events import append_event, canonical, digest
from .graph_commands import (CreateRelation, ReviseRelation, RevokeRelation, PurgeRelation,
    StartGraphRun, FinishGraphRun, CancelGraphRun, PurgeGraphRun, ReviewGraphCandidate, RelationFields)


def owned(connection, owner, table, object_id):
    row = connection.execute(f'SELECT * FROM {table} WHERE owner_id=? AND id=?', (owner, object_id)).fetchone()
    if row is None:
        raise DomainError('not_found', 404)
    return dict(row)


def outcome_input(connection, owner, outcome_id):
    item = owned(connection, owner, 'learning_outcome', outcome_id)
    return {key: item[key] for key in ('id', 'object_description', 'behavior', 'context_key')} | {
        'kind': 'composite' if connection.execute('SELECT 1 FROM learning_outcome_kind WHERE owner_id=? AND outcome_id=?',
                                                 (owner, outcome_id)).fetchone() else 'atomic', 'version': 1}


def source_available(connection, owner, source):
    kind, source_id, version = source['kind'], source.get('id'), source.get('version')
    if kind == 'external':
        return True, None
    if kind == 'outcome':
        row = connection.execute('SELECT 1 FROM learning_outcome WHERE owner_id=? AND id=?', (owner, source_id)).fetchone()
        return bool(row and version in (None, 1)), None if row and version in (None, 1) else 'missing'
    if kind == 'criterion':
        row = connection.execute('''SELECT c.version,c.review_status,a.reason FROM learning_criterion_version c
            LEFT JOIN learning_criterion_availability a ON a.owner_id=c.owner_id AND a.criterion_id=c.id
            WHERE c.owner_id=? AND c.id=?''', (owner, source_id)).fetchone()
        ok = bool(row and version in (None, row['version']) and not row['reason'])
        return ok, None if ok else 'unavailable'
    row = connection.execute('''SELECT ar.visibility,raw.purged_at,raw.content FROM learning_raw_artifact raw
        JOIN learning_artifact ar ON ar.owner_id=raw.owner_id AND ar.id=raw.artifact_id
        WHERE raw.owner_id=? AND raw.artifact_id=? AND raw.content_version=?''', (owner, source_id, version or 1)).fetchone()
    ok = bool(row and row['visibility'] == 'visible' and not row['purged_at'] and row['content'] is not None)
    return ok, None if ok else 'unavailable'


def read_private(connection, owner, kind, object_id, revision=1):
    row = connection.execute('SELECT * FROM learning_graph_private WHERE owner_id=? AND kind=? AND object_id=? AND revision=?',
                             (owner, kind, object_id, revision)).fetchone()
    if row is None:
        raise DomainError('graph_source_missing', 409)
    if row['purged_at'] or row['content_json'] is None:
        return None
    if hashlib.sha256(row['content_json'].encode()).hexdigest() != row['content_hash']:
        raise DomainError('event_integrity_failed')
    return json.loads(row['content_json'])


def public_private(connection, owner, kind, object_id, revision=1):
    content = read_private(connection, owner, kind, object_id, revision)
    if content is None:
        return dict(context_key='', rationale=None, uncertainty=None, source_refs=[], available=False)
    refs = []
    available = True
    for source in content.get('source_refs', []):
        ok, reason = source_available(connection, owner, source)
        refs.append({**source, 'available': ok, 'unavailable_reason': reason})
        available &= ok
    if not available:
        for ref in refs:
            # A private external URL can itself contain copied source wording.
            ref.pop('url',None)
    return {key: content.get(key, '') if available else None for key in ('context_key','rationale','uncertainty')} | {
        'source_refs': refs, 'available': bool(available)}


def validate_relation(connection, owner, fields, exclude=None, *, check_sources=True):
    value = RelationFields.model_validate(fields).model_dump(mode='json')
    left, right, kind, context = (value[key] for key in ('source_outcome_id','target_outcome_id','relation_type','context_key'))
    if left == right:
        raise DomainError('graph_self_relation', 422)
    source = outcome_input(connection, owner, left)
    outcome_input(connection, owner, right)
    if kind == 'contains' and source['kind'] != 'composite':
        raise DomainError('graph_contains_requires_composite', 422)
    if kind in {'equivalent', 'overlap'}:
        left, right = sorted((left, right))
        value.update(source_outcome_id=left, target_outcome_id=right)
    normalized = []
    for source in value['source_refs']:
        source = {key: val for key, val in source.items() if val is not None}
        if source['kind'] != 'external':
            if source['kind'] == 'artifact' and 'version' not in source:
                raise DomainError('graph_source_version_required', 422)
            if source['kind'] in {'outcome','criterion'} and 'version' not in source:
                source['version'] = (1 if source['kind'] == 'outcome' else
                    owned(connection, owner, 'learning_criterion_version', source['id'])['version'])
            ok, _ = source_available(connection, owner, source)
            if not ok and check_sources:
                # Hide cross-owner existence and reject inaccessible source versions.
                raise DomainError('not_found', 404)
        if source not in normalized:
            normalized.append(source)
    value['source_refs'] = normalized
    edges = []
    for row in connection.execute('SELECT * FROM learning_outcome_relation WHERE owner_id=? AND status=\'active\'', (owner,)):
        if row['id'] == exclude:
            continue
        body = read_private(connection, owner, 'relation', row['id'], row['revision'])
        if body is None or body['context_key'] != context:
            continue
        a, b, existing = row['source_outcome_id'], row['target_outcome_id'], row['relation_type']
        if existing == kind and (a,b) == (left,right):
            raise DomainError('graph_duplicate_relation', 409)
        if {a,b} == {left,right} and ((kind == 'equivalent' and existing in {'contains','prerequisite'}) or
                                      (existing == 'equivalent' and kind in {'contains','prerequisite'})):
            raise DomainError('graph_relation_conflict', 409)
        if existing == kind:
            edges.append((a,b))
    if kind in {'contains','prerequisite'}:
        # Containment is structural across contexts; scope labels cannot bypass cycles.
        if kind == 'contains':
            edges = [(r[0],r[1]) for r in connection.execute('''SELECT source_outcome_id,target_outcome_id
                FROM learning_outcome_relation WHERE owner_id=? AND status='active' AND relation_type='contains' AND id<>?''',
                (owner, exclude or ''))]
        queue, visited = [right], set()
        while queue:
            node = queue.pop()
            if node == left:
                raise DomainError('graph_relation_cycle', 409)
            if node in visited:
                continue
            visited.add(node)
            queue.extend(b for a,b in edges if a == node)
    return value


def _private_payload(fields):
    return {key: fields[key] for key in ('context_key','rationale','uncertainty','source_refs')}


def _relation_event(connection, principal, command_id, key, now, fields, *, relation_id=None,
                    expected=0, source_kind='manual', candidate_id=None):
    relation_id = relation_id or str(uuid4())
    value = validate_relation(connection, principal.owner_id, fields, relation_id if expected else None)
    event = append_event(connection, principal, command_id=command_id, key=key, aggregate_type='outcome_relation',
        aggregate_id=relation_id, expected_version=expected,
        event_type='graph.relation_revised' if expected else 'graph.relation_created', now=now,
        payload={'id':relation_id, **{name:value[name] for name in ('source_outcome_id','target_outcome_id','relation_type')},
                 'source_kind':source_kind,'candidate_id':candidate_id,'content':canonical(_private_payload(value))})
    return dict(id=relation_id,event_id=event['event_id'],aggregate_version=event['aggregate_version'])


def dispatch_graph(connection, principal, command, command_id, key, now):
    owner = principal.owner_id
    if isinstance(command, CreateRelation):
        fields = command.model_dump(exclude={'relation_id','expected_revision'}, mode='json')
        if isinstance(command, ReviseRelation):
            row = owned(connection, owner, 'learning_outcome_relation', command.relation_id)
            if row['status'] != 'active':
                raise DomainError('graph_relation_inactive')
            if row['revision'] != command.expected_revision:
                raise DomainError('version_conflict')
            return _relation_event(connection,principal,command_id,key,now,fields,relation_id=row['id'],
                expected=command.expected_revision,source_kind=row['source_kind'],candidate_id=row['candidate_id'])
        return _relation_event(connection,principal,command_id,key,now,fields)
    if isinstance(command, RevokeRelation):
        row = owned(connection, owner, 'learning_outcome_relation', command.relation_id)
        if row['revision'] != command.expected_revision:
            raise DomainError('version_conflict')
        if isinstance(command, PurgeRelation):
            event_type = 'graph.relation_purged'
        else:
            if row['status'] != 'active':
                raise DomainError('graph_relation_inactive')
            event_type = 'graph.relation_revoked'
        event = append_event(connection,principal,command_id=command_id,key=key,aggregate_type='outcome_relation',
            aggregate_id=row['id'],expected_version=command.expected_revision,event_type=event_type,
            payload={'id':row['id']},now=now)
        return dict(id=row['id'],event_id=event['event_id'],aggregate_version=event['aggregate_version'])
    if isinstance(command, StartGraphRun):
        if len(set(command.outcome_ids)) != len(command.outcome_ids):
            raise DomainError('graph_duplicate_selection', 422)
        inputs = [outcome_input(connection,owner,item) for item in command.outcome_ids]
        if inputs != command.inputs:
            raise DomainError('graph_input_changed')
        run_id = str(uuid4())
        event = append_event(connection,principal,command_id=command_id,key=key,aggregate_type='graph_run',aggregate_id=run_id,
            expected_version=0,event_type='graph.run_started',now=now,payload={'id':run_id,'outcome_ids':command.outcome_ids,
                'provider_snapshot':command.provider_snapshot,'content':canonical({'inputs':inputs})})
        return dict(id=run_id,event_id=event['event_id'],aggregate_version=event['aggregate_version'])
    if isinstance(command, (FinishGraphRun, CancelGraphRun)):
        row = owned(connection,owner,'learning_graph_run',command.run_id)
        if row['revision'] != command.expected_revision:
            raise DomainError('version_conflict')
        if isinstance(command,PurgeGraphRun):
            event_type, payload = 'graph.run_purged', {'id':row['id']}
        elif isinstance(command,CancelGraphRun):
            if row['status'] != 'running':
                raise DomainError('graph_run_inactive')
            event_type, payload = 'graph.run_canceled', {'id':row['id']}
        else:
            if row['status'] != 'running':
                raise DomainError('graph_run_inactive')
            content = read_private(connection,owner,'run',row['id'])
            if command.status == 'succeeded' and (content is None or content['inputs'] != [outcome_input(connection,owner,item) for item in json.loads(row['outcome_ids_json'])]):
                raise DomainError('graph_input_changed')
            candidates, bodies = [], {}
            selected = set(json.loads(row['outcome_ids_json']))
            if command.status == 'failed' and command.candidates:
                raise DomainError('event_scope_invalid')
            seen = set()
            for proposal in command.candidates:
                # A candidate is a hypothesis, but endpoints and declared direction must be valid.
                value = proposal.model_dump(mode='json')
                if not {value['source_outcome_id'],value['target_outcome_id']}.issubset(selected):
                    raise DomainError('graph_candidate_out_of_scope',422)
                if any(ref.kind != 'outcome' or ref.id not in selected for ref in proposal.source_refs):
                    raise DomainError('graph_candidate_out_of_scope',422)
                if not value['source_refs']:
                    # These exact declarations were actually supplied to this call.
                    value['source_refs']=[{'kind':'outcome','id':item,'version':1} for item in
                        (value['source_outcome_id'],value['target_outcome_id'])]
                try:
                    value = validate_relation(connection,owner,value)
                except DomainError as error:
                    if error.code == 'graph_duplicate_relation':
                        # A fresh user analysis may repeat an already adopted decision.
                        # It is redundant, not a provider or permission failure.
                        continue
                    raise
                signature=(value['source_outcome_id'],value['target_outcome_id'],value['relation_type'],value['context_key'])
                if signature in seen:
                    continue
                seen.add(signature)
                candidate_id=str(uuid4())
                body=_private_payload(value)
                bodies[candidate_id]=body
                candidates.append({'id':candidate_id, **{name:value[name] for name in
                    ('source_outcome_id','target_outcome_id','relation_type')},'private_hash':digest(body)})
            event_type='graph.run_finished'
            payload={'id':row['id'],'status':command.status,'reason':command.reason,'candidates':candidates,
                     'content':canonical(bodies)}
        event=append_event(connection,principal,command_id=command_id,key=key,aggregate_type='graph_run',aggregate_id=row['id'],
            expected_version=command.expected_revision,event_type=event_type,payload=payload,now=now)
        return dict(id=row['id'],event_id=event['event_id'],aggregate_version=event['aggregate_version'])
    if isinstance(command,ReviewGraphCandidate):
        run=owned(connection,owner,'learning_graph_run',command.run_id)
        row=owned(connection,owner,'learning_graph_candidate',command.candidate_id)
        if row['run_id']!=run['id']:
            raise DomainError('not_found',404)
        if row['revision'] != command.expected_revision:
            raise DomainError('version_conflict')
        if row['status']!='pending' or run['status']!='succeeded':
            raise DomainError('graph_candidate_inactive')
        relation_id=None
        if command.decision=='accept':
            raw=read_private(connection,owner,'candidate',row['id'])
            frozen=read_private(connection,owner,'run',run['id'])
            if raw is None or frozen is None or frozen['inputs'] != [outcome_input(connection,owner,item) for item in json.loads(run['outcome_ids_json'])]:
                raise DomainError('graph_input_changed')
            original={**{name:row[name] for name in ('source_outcome_id','target_outcome_id','relation_type')},**raw}
            fields=command.relation.model_dump(mode='json') if command.relation else original
            if not {fields['source_outcome_id'],fields['target_outcome_id']}.issubset(set(json.loads(run['outcome_ids_json']))):
                raise DomainError('graph_candidate_out_of_scope',422)
            # Edited decisions may add verified references, while the frozen proposal remains preserved.
            relation_id=_relation_event(connection,principal,command_id,key,now,fields,
                source_kind='ai_accepted',candidate_id=row['id'])['id']
        elif command.relation is not None:
            raise DomainError('graph_reject_has_relation',422)
        event=append_event(connection,principal,command_id=command_id,key=key,aggregate_type='graph_candidate',
            aggregate_id=row['id'],expected_version=command.expected_revision-1,event_type='graph.candidate_reviewed',now=now,
            payload={'id':row['id'],'status':'accepted' if command.decision=='accept' else 'rejected',
                     'relation_id':relation_id,'run_id':run['id']})
        return dict(candidate_id=row['id'],revision=command.expected_revision+1,
                    status='accepted' if command.decision=='accept' else 'rejected',relation_id=relation_id)
    raise DomainError('command_unsupported',422)


def _store_private(connection,event,kind,object_id,revision,body=None,expected_hash=None):
    owner=event['owner_id']
    row=connection.execute('SELECT * FROM learning_graph_private WHERE owner_id=? AND kind=? AND object_id=? AND revision=?',
        (owner,kind,object_id,revision)).fetchone()
    if row:
        if row['purged_at'] is None:
            actual=read_private(connection,owner,kind,object_id,revision)
            if digest(actual)!=expected_hash:
                raise DomainError('event_integrity_failed')
        return
    if body is None:
        private=event.get('_private_content')
        if private is None:
            raise DomainError('graph_source_missing')
        body=json.loads(private)
    if digest(body)!=expected_hash:
        raise DomainError('event_integrity_failed')
    text=canonical(body)
    connection.execute('INSERT INTO learning_graph_private VALUES (?,?,?,?,?,?,NULL)',
        (owner,kind,object_id,revision,text,expected_hash))
    refs=body.get('source_refs',[])
    if kind=='run':
        refs=[{'kind':'outcome','id':item['id'],'version':1} for item in body['inputs']]
    for ref in refs:
        if ref['kind']!='external':
            connection.execute('INSERT OR IGNORE INTO learning_graph_source VALUES (?,?,?,?,?,?,?)',
                (owner,kind,object_id,revision,ref['kind'],ref['id'],ref.get('version',1)))


def apply_graph_event(connection,event,payload):
    owner,object_id,version,now,kind=event['owner_id'],payload['id'],event['aggregate_version'],event['occurred_at'],event['event_type']
    if object_id != event['aggregate_id']:
        raise DomainError('event_scope_invalid')
    aggregate=('outcome_relation' if kind.startswith('graph.relation_') else
               'graph_candidate' if kind=='graph.candidate_reviewed' else 'graph_run')
    if event['aggregate_type']!=aggregate:
        raise DomainError('event_scope_invalid')
    if kind in {'graph.relation_created','graph.relation_revised'}:
        _store_private(connection,event,'relation',object_id,version,expected_hash=payload['content_hash'])
        fields={name:payload[name] for name in ('source_outcome_id','target_outcome_id','relation_type','source_kind','candidate_id')}
        private=read_private(connection,owner,'relation',object_id,version)
        if private is not None:
            validate_relation(connection,owner,{**{name:fields[name] for name in
                ('source_outcome_id','target_outcome_id','relation_type')},**private},object_id,check_sources=False)
        previous=connection.execute('SELECT created_at FROM learning_outcome_relation WHERE owner_id=? AND id=?',(owner,object_id)).fetchone()
        if (kind=='graph.relation_created') != (previous is None):
            raise DomainError('event_scope_invalid')
        # Purged sources keep structural history until an explicit revoke/purge event.
        connection.execute('''INSERT INTO learning_outcome_relation VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)
            ON CONFLICT(id) DO UPDATE SET source_outcome_id=excluded.source_outcome_id,target_outcome_id=excluded.target_outcome_id,
            relation_type=excluded.relation_type,revision=excluded.revision,status=excluded.status,updated_at=excluded.updated_at''',
            (object_id,owner,fields['source_outcome_id'],fields['target_outcome_id'],fields['relation_type'],fields['source_kind'],
             fields['candidate_id'],version,'active',previous['created_at'] if previous else now,now))
        history={**fields,'status':'active'}
    elif kind in {'graph.relation_revoked','graph.relation_purged'}:
        row=owned(connection,owner,'learning_outcome_relation',object_id)
        status='purged' if kind.endswith('purged') else 'revoked'
        connection.execute('UPDATE learning_outcome_relation SET status=?,revision=?,updated_at=?,purged_at=? WHERE owner_id=? AND id=?',
            (status,version,now,now if status=='purged' else row['purged_at'],owner,object_id))
        if status=='purged':
            erase_graph(connection,owner,'relation',object_id,now)
        history={**row,'status':status}
    elif kind=='graph.run_started':
        _store_private(connection,event,'run',object_id,1,expected_hash=payload['content_hash'])
        connection.execute('INSERT INTO learning_graph_run VALUES (?,?,1,\'running\',NULL,?,?,?,NULL,NULL)',
            (object_id,owner,canonical(payload['outcome_ids']),canonical(payload['provider_snapshot']),now))
    elif kind=='graph.run_finished':
        bodies=json.loads(event['_private_content']) if '_private_content' in event else {}
        for proposal in payload['candidates']:
            candidate_id=proposal['id']
            _store_private(connection,event,'candidate',candidate_id,1,body=bodies.get(candidate_id),expected_hash=proposal['private_hash'])
            connection.execute('INSERT INTO learning_graph_candidate VALUES (?,?,?,1,\'pending\',?,?,?,NULL,?,?,NULL)',
                (candidate_id,owner,object_id,proposal['source_outcome_id'],proposal['target_outcome_id'],proposal['relation_type'],now,now))
        connection.execute('UPDATE learning_graph_run SET status=?,reason=?,revision=?,finished_at=? WHERE owner_id=? AND id=?',
            (payload['status'],payload['reason'],version,now,owner,object_id))
    elif kind in {'graph.run_canceled','graph.run_purged'}:
        status='purged' if kind.endswith('purged') else 'canceled'
        connection.execute('UPDATE learning_graph_run SET status=?,revision=?,reason=?,finished_at=?,purged_at=? WHERE owner_id=? AND id=?',
            (status,version,'content_purged' if status=='purged' else 'canceled',now,now if status=='purged' else None,owner,object_id))
        if status=='purged':
            erase_graph(connection,owner,'run',object_id,now)
    elif kind=='graph.candidate_reviewed':
        row=owned(connection,owner,'learning_graph_candidate',object_id)
        if row['run_id']!=payload['run_id'] or row['status']!='pending':
            raise DomainError('event_scope_invalid')
        connection.execute('UPDATE learning_graph_candidate SET status=?,revision=?,relation_id=?,updated_at=? WHERE owner_id=? AND id=?',
            (payload['status'],version+1,payload['relation_id'],now,owner,object_id))
    else:
        raise DomainError('event_type_unsupported')
    if kind.startswith('graph.relation_'):
        connection.execute('INSERT INTO learning_outcome_relation_history VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (owner,object_id,version,history['source_outcome_id'],history['target_outcome_id'],history['relation_type'],
             history['source_kind'],history['candidate_id'],history['status'],now,event['event_id']))


def erase_graph(connection,owner,kind,object_id,now):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='learning_graph_private'").fetchone():
        return
    private_ids={(kind,object_id)}
    if kind=='run':
        private_ids.update(('candidate',row[0]) for row in connection.execute('SELECT id FROM learning_graph_candidate WHERE owner_id=? AND run_id=?',(owner,object_id)))
        private_ids.update(('relation',row[0]) for row in connection.execute('''SELECT r.id FROM learning_outcome_relation r
            JOIN learning_graph_candidate c ON c.owner_id=r.owner_id AND c.id=r.candidate_id
            WHERE c.owner_id=? AND c.run_id=?''',(owner,object_id)))
        connection.execute("UPDATE learning_graph_run SET status='purged',reason='content_purged',purged_at=COALESCE(purged_at,?) WHERE owner_id=? AND id=?",(now,owner,object_id))
        connection.execute("UPDATE learning_graph_candidate SET status='purged',purged_at=COALESCE(purged_at,?) WHERE owner_id=? AND run_id=?",(now,owner,object_id))
    if kind=='relation':
        connection.execute("UPDATE learning_outcome_relation SET status='purged',purged_at=COALESCE(purged_at,?) WHERE owner_id=? AND id=?",(now,owner,object_id))
        # The original AI rationale is another managed copy, even after adoption.
        for row in connection.execute('SELECT candidate_id FROM learning_outcome_relation WHERE owner_id=? AND id=?',(owner,object_id)):
            if row[0]:
                private_ids.add(('candidate',row[0]))
    for private_kind,private_id in private_ids:
        connection.execute('UPDATE learning_graph_private SET content_json=NULL,content_hash=NULL,purged_at=COALESCE(purged_at,?) WHERE owner_id=? AND kind=? AND object_id=?',
            (now,owner,private_kind,private_id))


def erase_graph_sources(connection,owner,artifact_ids,now):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='learning_graph_source'").fetchone():
        return
    for artifact_id in artifact_ids:
        for row in connection.execute("SELECT DISTINCT kind,object_id FROM learning_graph_source WHERE owner_id=? AND source_kind='artifact' AND source_id=?",(owner,artifact_id)).fetchall():
            # Derived private wording is erased; the formal structural decision remains auditable.
            connection.execute('UPDATE learning_graph_private SET content_json=NULL,content_hash=NULL,purged_at=COALESCE(purged_at,?) WHERE owner_id=? AND kind=? AND object_id=?',
                (now,owner,row['kind'],row['object_id']))
