"""Coach private-copy registrations shared by live purge and offline backup scrub."""
import json
from .core.background_coach import erase_private

PURGE_TABLES={'coach_run':('learning_coach_run','id')}
PURGE_BARRIERS=(('learning_coach_private',('owner_id','run_id','revision')),
                ('learning_coach_tombstone',('owner_id','run_id')),
                ('learning_coach_run',('owner_id','id')))
PRIVATE_COLUMNS={'learning_coach_private':['content_json','content_hash'],'learning_agent_permission_request':['purpose']}

def erase_managed(c,owner,kind,identifier,now,*,submission_ids=(),artifact_ids=()):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='learning_coach_private'").fetchone(): return False
    if kind=='coach_run': erase_private(c,owner,identifier,now);return True
    artifacts={identifier,*artifact_ids} if kind=='artifact' else set(artifact_ids)
    runs=set()
    for value in c.execute('SELECT owner_id,run_id,revision,content_json FROM learning_coach_private WHERE owner_id=? AND purged_at IS NULL',(owner,)).fetchall():
        body=json.loads(value['content_json']);inputs=body.get('inputs',{})
        for ref in inputs.get('refs',[]):
            match=False
            if ref['kind']=='event':
                event=c.execute('SELECT payload_json FROM learning_event WHERE owner_id=? AND event_id=?',(owner,ref['id'])).fetchone()
                p=json.loads(event[0]) if event else {}
                match=bool(artifacts.intersection({p.get('artifact_id'),p.get('id')}))
            elif ref['kind']=='claim':
                claim=c.execute('SELECT artifact_id FROM learning_evidence_claim WHERE owner_id=? AND id=?',(owner,ref['id'])).fetchone()
                match=bool(claim and claim[0] in artifacts)
            elif ref['kind']=='artifact': match=ref['id'] in artifacts
            elif ref['kind']=='answer':
                signal=c.execute('SELECT * FROM learning_coach_signal WHERE owner_id=? AND id=?',(owner,ref['id'])).fetchone()
                if signal and kind=='verification' and signal['answer_kind']=='discussion':
                    match=bool(c.execute('SELECT 1 FROM learning_discussion_turn t JOIN learning_question_discussion d ON d.id=t.discussion_id WHERE d.owner_id=? AND t.id=? AND d.verification_id=?',(owner,signal['answer_id'],identifier)).fetchone())
            elif kind=='delayed' and ref['kind']=='delayed_follow_up': match=ref['id']==identifier
            if match: runs.add(value['run_id'])
        if kind=='session_feedback' and any(f['id']==identifier for f in inputs.get('feedback',[])): runs.add(value['run_id'])
        if kind=='path_content' and any(r.get('adopted_version_id')==identifier for r in inputs.get('routes',[])): runs.add(value['run_id'])
        if kind=='plan_content' and (inputs.get('plan_id')==identifier or any(a['plan_id']==identifier for a in inputs.get('actions',[]))): runs.add(value['run_id'])
    for run in runs: erase_private(c,owner,run,now)
    return False
