"""Owner-facing route views. Cross-database anchors remain checked references."""
from __future__ import annotations

import json

from .conversations import ConversationError
from .core.path_commands import (SavePathDraft, ConfirmPathDecision, StartPathTask,
                                SetPathPosition, PurgePathContent, TransferFields, TransferPathToPlan)
from .core.learning_paths import (owned, plan_state, organization_revision, read_private,
                                 reference_hash, version_fields, review, transfer_review)
from .learning_domain import DomainError
from .managed_purge import ManagedPurge
from .purge_storage import receipts


class LearningPaths:
    def __init__(self, learning, conversations):
        self.learning, self.db, self.chats = learning, learning.database, conversations

    def _owner(self, identity):
        return self.learning.principal(identity).owner_id

    def _anchor_available(self, owner, checkpoint):
        if not checkpoint:
            return True
        session_id, delegation_id = checkpoint.get('session_id'), checkpoint.get('delegation_id')
        if session_id:
            session = self.db.fetchone('SELECT delegation_id FROM learning_session WHERE owner_id=? AND id=?', (owner,session_id))
            if not session or session['delegation_id'] != delegation_id:
                return False
        anchor = checkpoint.get('anchor') or json.loads(checkpoint.get('anchor_json') or '{}')
        conversation_id = anchor.get('conversation_id')
        if not conversation_id:
            return True
        try:
            self.chats.owned_conversation(owner,conversation_id)
        except ConversationError:
            return False
        link = self.db.fetchone('''SELECT d.id FROM learning_room_conversation r
            JOIN learning_session s ON s.owner_id=r.owner_id AND s.id=r.session_id
            JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
            WHERE r.owner_id=? AND r.conversation_id=?''', (owner,conversation_id))
        if not link or link['id'] != delegation_id:
            return False
        nodes={row['id']:row for row in self.chats.list_messages(owner,conversation_id)
               if row['role'] in {'user','assistant'} and not (row.get('source_scope') or {}).get('purged')}
        leaf = anchor.get('leaf_id')
        if leaf and leaf not in nodes:
            return False
        for ancestor,descendant in (anchor.get('paths') or {}).items():
            if ancestor not in nodes or descendant not in nodes:
                return False
            current,seen=descendant,set()
            while current and current!=ancestor and current not in seen:
                seen.add(current)
                current=nodes.get(current,{}).get('parent_message_id')
            if current!=ancestor:
                return False
        return True

    def _checkpoint(self, connection, owner, plan_id, version_id):
        row = connection.execute('SELECT * FROM learning_path_checkpoint WHERE owner_id=? AND plan_id=? AND version_id=?',
                                 (owner,plan_id,version_id)).fetchone()
        if row is None:
            return None
        value = {key:row[key] for key in ('node_id','action_id','delegation_id','session_id')}
        value['anchor'] = json.loads(row['anchor_json'])
        value['available'] = self._anchor_available(owner,value)
        value['precision'] = ('answer' if value['anchor'].get('leaf_id') else
                              'conversation' if value['anchor'].get('conversation_id') else 'task')
        return value

    def _display(self, connection, owner, row, *, draft=False):
        data = json.loads(row['data_json'])
        private = read_private(connection,owner,row['id'] if draft else row['private_object_id'],
                               row['revision'] if draft else row['private_revision'])
        visible = private is not None and row['purged_at'] is None
        value = {key:row[key] for key in (('id','revision','intent','source_version_id','restore_version_id') if draft else
                 ('id','route_id','previous_version_id','parent_version_id','branch_node_id','created_at'))}
        value.update(title=private['title'] if visible else '', reason=private.get('reason','') if visible else '',
            content_available=visible, nodes=[{**node,'title':private['node_titles'].get(node['id'],'') if visible else ''}
                for node in data['nodes']], edges=data['edges'], entry_node_id=data['entry_node_id'],
            current_node_id=data['current_node_id'])
        if draft:
            state = plan_state(connection,owner,row['plan_id'])
            value.update(parent_version_id=row['base_version_id'],branch_node_id=row['base_node_id'])
            try:
                value['stale'] = (not visible or row['base_version_id'] != state['adopted_version_id']
                    or row['base_node_id'] != state['current_node_id']
                    or row['organization_revision'] != organization_revision(connection,owner,row['plan_id'])
                    or row['reference_hash'] != reference_hash(connection,owner,row['plan_id'],data))
            except DomainError:
                value['stale'] = True
        else:
            value['checkpoint'] = self._checkpoint(connection,owner,row['plan_id'],row['id'])
        return value

    def data(self, identity, plan_id):
        owner = self._owner(identity)
        with self.db.transaction() as connection:
            state = plan_state(connection,owner,plan_id)
            versions = [self._display(connection,owner,row) for row in connection.execute(
                'SELECT * FROM learning_path_version WHERE owner_id=? AND plan_id=? ORDER BY rowid', (owner,plan_id))]
            drafts = [self._display(connection,owner,row,draft=True) for row in connection.execute(
                "SELECT * FROM learning_path_draft WHERE owner_id=? AND plan_id=? AND status='draft' ORDER BY rowid", (owner,plan_id))]
            decisions = []
            for row in connection.execute('SELECT * FROM learning_path_decision WHERE owner_id=? AND plan_id=? ORDER BY rowid DESC', (owner,plan_id)):
                value = dict(row)
                version = owned(connection,owner,'learning_path_version',row['version_id'])
                private = read_private(connection,owner,version['private_object_id'],version['private_revision'])
                value['reason'] = private.get('reason','') if private else ''
                decisions.append(value)
            version_ids={version['id'] for version in versions}
            retry_ids=[receipt['object_id'] for receipt in receipts(self.db.database_path)
                if receipt.get('owner')==owner and receipt.get('kind')=='path_content'
                and receipt.get('status') in {'pending','partial'} and receipt.get('object_id') in version_ids]
            transfers=[]
            for row in connection.execute("SELECT aggregate_id,payload_json,occurred_at FROM learning_event WHERE owner_id=? AND event_type='path.transfer_departed' AND (aggregate_id=? OR json_extract(payload_json,'$.destination_plan_id')=?) ORDER BY position",(owner,plan_id,plan_id)):
                transfers.append(dict(source_plan_id=row['aggregate_id'],created_at=row['occurred_at'],**json.loads(row['payload_json'])))
            return {**{key:state[key] for key in ('plan_id','revision','adopted_version_id','current_node_id','status')},
                    'organization_revision':organization_revision(connection,owner,plan_id),
                    'versions':versions,'drafts':drafts,'decisions':decisions,'purge_retry_ids':retry_ids,'transfers':transfers}

    def save(self, identity, plan_id, payload, key):
        result = self.learning.core.execute(self.learning.principal(identity), SavePathDraft(plan_id=plan_id,**payload), key)
        return {**self.data(identity,plan_id),'draft_id':result['draft_id']}

    def restore_draft(self, identity, plan_id, payload, key):
        owner = self._owner(identity)
        with self.db.transaction() as connection:
            version, fields = version_fields(connection,owner,payload['version_id'])
            if version['plan_id'] != plan_id:
                raise DomainError('path_reference_scope')
            point = self._checkpoint(connection,owner,plan_id,version['id'])
            fields['current_node_id'] = payload.get('node_id') or (point['node_id'] if point else fields['current_node_id'])
        fields.update(intent=payload['intent'],source_version_id=version['id'],restore_version_id=version['id'],
                      expected_revision=payload['expected_revision'],
                      expected_organization_revision=payload['expected_organization_revision'],reason=payload.get('reason',''))
        return self.save(identity,plan_id,fields,key)

    def _require_not_generating(self, owner, action_ids):
        if not action_ids:
            return
        marks = ','.join('?' for _ in action_ids)
        conversations = [row[0] for row in self.db.fetchall(f'''SELECT r.conversation_id FROM learning_room_conversation r
            JOIN learning_session s ON s.owner_id=r.owner_id AND s.id=r.session_id
            JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
            WHERE r.owner_id=? AND d.action_id IN ({marks})''', (owner,*action_ids))]
        if conversations:
            chat_marks=','.join('?' for _ in conversations)
            if self.chats.database.fetchone(f"SELECT 1 FROM ai_run WHERE identity_id=? AND conversation_id IN ({chat_marks}) AND status IN ('queued','running')", (owner,*conversations)):
                raise DomainError('path_generation_running')
        if self.db.fetchone(f'''SELECT 1 FROM learning_discussion_turn t JOIN learning_question_discussion d ON d.id=t.discussion_id
            JOIN learning_verification v ON v.owner_id=d.owner_id AND v.id=d.verification_id
            WHERE d.owner_id=? AND v.action_id IN ({marks}) AND t.status='running' ''', (owner,*action_ids)):
            raise DomainError('path_generation_running')

    def preview(self, identity, plan_id, draft_id):
        owner = self._owner(identity)
        with self.db.transaction() as connection:
            result = review(connection,owner,plan_id,draft_id)
            self._require_not_generating(owner,[s['action_id'] for s in result['affected_sessions']])
            point = result['checkpoint']
            if point:
                point={**point,'anchor':json.loads(point['anchor_json']),'available':self._anchor_available(owner,point)}
                point.pop('anchor_json')
            return {key:result[key] for key in ('review_key','revision','draft_revision','intent')} | dict(
                affected_sessions=[{key:s[key] for key in ('id','action_id','action_title')} for s in result['affected_sessions']],
                checkpoint=point,draft=self._display(connection,owner,result['draft'],draft=True),commitment_changes=result['commitments']['changes'])

    def confirm(self, identity, plan_id, payload, key):
        # The ordinary chat DB is read-only here. No distributed transaction is claimed.
        owner = self._owner(identity)
        previous=self.db.fetchone('SELECT 1 FROM learning_command WHERE owner_id=? AND actor_id=? AND idempotency_key=?',(owner,owner,key))
        if previous is None:
            with self.db.transaction() as connection:
                result = review(connection,owner,plan_id,payload['draft_id'])
                self._require_not_generating(owner,[s['action_id'] for s in result['affected_sessions']])
        self.learning.core.execute(self.learning.principal(identity), ConfirmPathDecision(plan_id=plan_id,**payload), key)
        return self.data(identity,plan_id)

    def position(self, identity, plan_id, payload, key):
        self.learning.core.execute(self.learning.principal(identity), SetPathPosition(plan_id=plan_id,**payload), key)
        return self.data(identity,plan_id)

    def transfer_preview(self,identity,plan_id,payload):
        owner=self._owner(identity)
        with self.db.transaction() as connection:
            result=transfer_review(connection,owner,plan_id,TransferFields(**payload))
            self._require_not_generating(owner,[s['action_id'] for s in result['affected_sessions']])
            result['affected_sessions']=[{key:s[key] for key in ('id','action_id','action_title')} for s in result['affected_sessions']]
            result['commitment_changes']=result.pop('commitments')['changes']
            if result['checkpoint']:
                result['checkpoint']={**result['checkpoint'],'anchor':json.loads(result['checkpoint']['anchor_json'])}
                result['checkpoint'].pop('anchor_json')
                result['checkpoint']['available']=self._anchor_available(owner,result['checkpoint'])
                anchor=result['checkpoint']['anchor']
                result['checkpoint']['precision']='answer' if anchor.get('leaf_id') else 'conversation' if anchor.get('conversation_id') else 'task'
            return result

    def transfer(self,identity,plan_id,payload,key):
        owner=self._owner(identity)
        previous=self.db.fetchone('SELECT 1 FROM learning_command WHERE owner_id=? AND actor_id=? AND idempotency_key=?',(owner,owner,key))
        if previous is None:
            self.transfer_preview(identity,plan_id,{key:value for key,value in payload.items() if key!='review_key'})
        result=self.learning.core.execute(self.learning.principal(identity),TransferPathToPlan(plan_id=plan_id,**payload),key)
        return dict(plan_id=result['plan_id'],source_path=self.data(identity,plan_id),path=self.data(identity,result['plan_id']))

    def start(self, identity, plan_id, payload, key):
        payload = dict(payload)
        use_checkpoint = payload.get('use_checkpoint',True)
        owner = self._owner(identity)
        with self.db.transaction() as connection:
            point = self._checkpoint(connection,owner,plan_id,payload['version_id'])
            delegation=owned(connection,owner,'learning_delegation',payload['delegation_id'])
            applies = bool(point and point['node_id']==payload['node_id'] and point['delegation_id']==delegation['id'])
            running=self.db.fetchone("SELECT 1 FROM learning_session WHERE owner_id=? AND delegation_id=? AND status='running'",(owner,delegation['id']))
            if use_checkpoint and applies and not running and not point['available']:
                raise DomainError('path_anchor_unavailable')
            previous=connection.execute('SELECT 1 FROM learning_command WHERE owner_id=? AND actor_id=? AND idempotency_key=?',(owner,owner,key)).fetchone()
            if previous is None and not running:
                active=[row[0] for row in connection.execute('''SELECT d.action_id FROM learning_session s
                    JOIN learning_delegation d ON d.owner_id=s.owner_id AND d.id=s.delegation_id
                    WHERE s.owner_id=? AND s.status='running' ''',(owner,))]
                self._require_not_generating(owner,[delegation['action_id'],*active])
        result=self.learning.core.execute(self.learning.principal(identity),StartPathTask(plan_id=plan_id,**payload),key)
        if result.get('path_anchor') and not self._anchor_available(owner,dict(
                session_id=result['session_id'],delegation_id=payload['delegation_id'],anchor=result['path_anchor'])):
            raise DomainError('path_anchor_unavailable')
        return result

    def purge(self, identity, plan_id, version_id, payload, key):
        report=ManagedPurge(self.learning).run(identity,'path_content',version_id,
            lambda:self.learning.core.execute(self.learning.principal(identity),PurgePathContent(plan_id=plan_id,version_id=version_id,**payload),key))
        return dict(path=self.data(identity,plan_id),purge_report=report['purge'])
