"""One explicitly requested, candidate-bound use of the existing task read grant."""
import json
from datetime import datetime,timezone
from .core.background_coach import original
from .agent_runtime import GLOBAL_AGENT_ID

def request_fields(c,owner,candidate_id):
    candidate=c.execute('SELECT * FROM learning_coach_candidate WHERE owner_id=? AND id=?',(owner,candidate_id)).fetchone()
    if candidate is None: return None
    body=original(c,owner,candidate['run_id'])
    item=next((x for x in (body or {}).get('candidates',[]) if x.get('id')==candidate_id),None)
    if not item or item['target']['kind']!='permission_review' or not item.get('access_request'): return None
    request=item['access_request']
    action=next((a for a in body['inputs']['actions'] if a['id']==item['target']['action_id']),None)
    purpose=('核对“'+action['title']+'”：' if action else '')+request['purpose']
    prefix='coach-permission:'+candidate_id+':'
    rows=c.execute('''SELECT r.*,g.status AS grant_status FROM learning_agent_permission_request r
        LEFT JOIN learning_agent_permission_grant g ON g.owner_id=r.owner_id AND g.request_id=r.id
        WHERE r.owner_id=? AND r.request_key LIKE ? ORDER BY r.created_at DESC,r.rowid DESC''',(owner,prefix+'%')).fetchall()
    current=None;maximum=0;now=datetime.now(timezone.utc)
    for row in rows:
        suffix=row['request_key'][len(prefix):]
        if suffix.isdigit(): maximum=max(maximum,int(suffix))
        try: valid_time=datetime.fromisoformat(row['expires_at'].replace('Z','+00:00'))>now
        except ValueError: valid_time=False
        pending=row['status']=='pending' and row['grant_status'] is None
        if valid_time and (row['grant_status']=='active' or pending):
            current=row['request_key']
            if row['grant_status']=='active': break
    return dict(purpose=purpose[:1000],scope='learning_action',target_id=item['target']['action_id'],
        content_granularity='full_text',ttl_seconds=300,alternative=request['alternative'],request_key=current or prefix+str(maximum+1))

def approved(c,owner,ref,chats=None):
    expected=request_fields(c,owner,ref.get('candidate_id'))
    if expected is None: return None
    candidate=c.execute('SELECT run_id,status FROM learning_coach_candidate WHERE owner_id=? AND id=?',(owner,ref['candidate_id'])).fetchone()
    if candidate['status'] not in {'pending','accepted'}: return None
    prior=original(c,owner,candidate['run_id'])
    prior_run=c.execute('SELECT scope,plan_id FROM learning_coach_run WHERE owner_id=? AND id=?',(owner,candidate['run_id'])).fetchone()
    from .coach_sources import source_available,input_state
    if prior is None or prior['inputs'].get('authorization') or any(not source_available(c,owner,r,chats) for r in prior['inputs']['refs']): return None
    if input_state(c,owner,prior_run['scope'],prior_run['plan_id'],prior['inputs']['refs'],chats)!=prior['inputs']: return None
    request=c.execute('SELECT * FROM learning_agent_permission_request WHERE owner_id=? AND id=?',(owner,ref['id'])).fetchone()
    grant=c.execute('SELECT * FROM learning_agent_permission_grant WHERE owner_id=? AND request_id=?',(owner,ref['id'])).fetchone()
    if not request or not grant or grant['status']!='active' or grant['agent_id']!=GLOBAL_AGENT_ID: return None
    if any(request[key]!=expected[key] for key in ('purpose','scope','target_id','content_granularity','ttl_seconds')): return None
    prefix='coach-permission:'+ref['candidate_id']+':'
    suffix=request['request_key'][len(prefix):] if request['request_key'].startswith(prefix) else ''
    if not suffix.isdigit() or int(suffix)<1 or request['request_key']!=prefix+str(int(suffix)): return None
    if grant['target_id']!=expected['target_id'] or grant['content_granularity']!='full_text' or grant['scope']!='learning_action': return None
    try:
        if datetime.fromisoformat(grant['expires_at'].replace('Z','+00:00'))<=datetime.now(timezone.utc): return None
    except ValueError: return None
    return dict(request_id=request['id'],grant_id=grant['id'],candidate_id=ref['candidate_id'],action_id=grant['target_id'],
        purpose=expected['purpose'],content_granularity='full_text',expires_at=grant['expires_at'])

def context(c,owner,ref,chats=None):
    authorization=approved(c,owner,ref,chats)
    if authorization is None: return None
    rows=c.execute('''SELECT r.artifact_id,r.content_version,r.content,r.content_hash,r.session_id FROM learning_raw_artifact r
        JOIN learning_artifact a ON a.owner_id=r.owner_id AND a.id=r.artifact_id AND a.content_version=r.content_version
        JOIN learning_session s ON s.owner_id=r.owner_id AND s.id=r.session_id
        JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
        WHERE r.owner_id=? AND d.action_id=? AND a.visibility='visible' AND a.evidence_status='eligible'
          AND r.purged_at IS NULL AND r.content IS NOT NULL ORDER BY r.created_at DESC,r.artifact_id''',(owner,authorization['action_id'])).fetchall()
    remaining=12000;artifacts=[]
    for row in rows[:3]:
        content=row['content'][:4000].encode()[:remaining].decode('utf-8','ignore')
        if not content: break
        remaining-=len(content.encode())
        artifacts.append(dict(id=row['artifact_id'],version=row['content_version'],session_id=row['session_id'],
            start=0,end=len(content),content=content,content_hash=row['content_hash'],partial=len(content)<len(row['content'])))
    return {**authorization,'artifacts':artifacts,'available_artifact_count':len(rows),
        'limited':len(artifacts)<len(rows) or any(x['partial'] for x in artifacts)}
