"""Small registration constants/hooks shared by online purge and backup scrub."""
from .core.commitments import erase_private,erase_sources

PURGE_TABLES={'commitment_content':('learning_commitment_draft','id'),
              'commitment_run':('learning_commitment_run','id'),
              'session_feedback':('learning_session_feedback','id')}
PURGE_BARRIERS=(('learning_commitment_private',('owner_id','kind','object_id','revision')),
                ('learning_commitment_private_tombstone',('owner_id','kind','object_id')),
                ('learning_commitment_draft',('owner_id','id')),
                ('learning_commitment_version',('owner_id','id')),
                ('learning_commitment_run',('owner_id','id')),
                ('learning_session_feedback',('owner_id','id')))
PRIVATE_COLUMNS={'learning_commitment_private':['content_json','content_hash']}


def _ids(connection,table,where,params):
    if not connection.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():return []
    return [row[0] for row in connection.execute(f'SELECT id FROM {table} WHERE {where}',params)]


def erase_managed(connection,owner,kind,object_id,now,*,submission_ids=(),artifact_ids=()):
    """Return true only when this hook fully handles a new private-content kind."""
    if kind in PURGE_TABLES:
        target={'commitment_content':'draft','commitment_run':'run','session_feedback':'feedback'}[kind]
        erase_private(connection,owner,target,object_id,now)
        return True
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='learning_commitment_source'").fetchone():
        return False
    if kind=='artifact':
        artifacts=[object_id,*artifact_ids]
        for identifier in artifacts:
            erase_sources(connection,owner,'artifact',[identifier],now)
            submission_ids=[*submission_ids,*_ids(connection,'learning_verification_submission','owner_id=? AND artifact_id=?',(owner,identifier))]
            follows=_ids(connection,'learning_delayed_follow_up','owner_id=? AND source_artifact_id=?',(owner,identifier))
            for follow in follows:
                erase_sources(connection,owner,'delayed_attempt',_ids(connection,'learning_delayed_attempt','owner_id=? AND follow_up_id=?',(owner,follow)),now)
        erase_sources(connection,owner,'submission',submission_ids,now)
    elif kind=='verification':
        submissions=_ids(connection,'learning_verification_submission','owner_id=? AND verification_id=?',(owner,object_id))
        erase_sources(connection,owner,'submission',[*submissions,*submission_ids],now)
        for identifier in artifact_ids:erase_sources(connection,owner,'artifact',[identifier],now)
    elif kind=='completion':erase_sources(connection,owner,'completion',[object_id],now)
    elif kind=='delayed':erase_sources(connection,owner,'delayed_attempt',_ids(connection,'learning_delayed_attempt','owner_id=? AND follow_up_id=?',(owner,object_id)),now)
    elif kind in {'plan_content','module_content'}:erase_sources(connection,owner,kind,[object_id],now)
    elif kind=='path_content':
        erase_sources(connection,owner,'path_version',[object_id],now)
        row=connection.execute('SELECT private_object_id FROM learning_path_version WHERE owner_id=? AND id=?',(owner,object_id)).fetchone()
        if row:erase_sources(connection,owner,'path_version',_ids(connection,'learning_path_version','owner_id=? AND private_object_id=?',(owner,row[0])),now)
    # No material/conversation body or C2 observation enters the permitted input.
    # Such references must be added explicitly before introducing any new reads.
    return False
