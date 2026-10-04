"""Owner-scoped plan organization application boundary."""
from .core.organization_commands import (CreatePlan, CreateModule, ReviseModule, PlaceTask,
    OrderChildren, CreatePlanTask, PurgePlanContent, PurgeModuleContent)
from .core.plan_organization import require_plan, children, revision, removed_task_ids
from .managed_purge import ManagedPurge


class PlanOrganization:
    def __init__(self, learning):
        self.learning, self.db = learning, learning.database

    def organization(self, identity, plan_id):
        owner = self.learning.principal(identity).owner_id
        with self.db.transaction() as connection:
            plan = require_plan(connection,owner,plan_id,writable=False)
            def content_state(kind, object_id):
                original = connection.execute('SELECT 1 FROM learning_plan_private WHERE owner_id=? AND kind=? AND object_id=?',
                                              (owner,kind,object_id)).fetchone()
                purged = connection.execute('SELECT 1 FROM learning_plan_private_tombstone WHERE owner_id=? AND kind=? AND object_id=?',
                                            (owner,kind,object_id)).fetchone()
                return {'can_purge_content':bool(original),'content_available':not bool(purged)}
            modules = [dict(row) | content_state('module',row['id']) for row in connection.execute('''SELECT id,title,description,
                parent_module_id,position,status FROM learning_module WHERE owner_id=? AND plan_id=? ORDER BY created_at,id''', (owner,plan_id))]
            state = children(connection,owner,plan_id)
            positions = {row['id']:row['position'] for row in state if row['kind']=='module'}
            for module in modules:
                module['position'] = positions[module['id']]
            removed = removed_task_ids(connection,owner,plan_id)
            tasks = [dict(row) for row in connection.execute('''SELECT a.id,a.title,a.status FROM learning_action a
                JOIN learning_action_link l ON l.owner_id=a.owner_id AND l.action_id=a.id
                WHERE l.owner_id=? AND l.plan_id=? ORDER BY l.created_at,a.id''', (owner,plan_id)) if row['id'] not in removed]
            return {'plan':{key:plan[key] for key in ('id','title','description','goal_id','status')} | content_state('plan',plan_id),
                    'revision':revision(connection,owner,plan_id),'modules':modules,'children':state,'tasks':tasks}

    def create(self, identity, payload, key):
        result = self.learning.core.execute(self.learning.principal(identity),CreatePlan(**payload),key)
        return {'organization':self.organization(identity,result['plan_id']), 'plan_id':result['plan_id'], 'object_id':result['object_id']}

    def _write(self, identity, command, key):
        result = self.learning.core.execute(self.learning.principal(identity),command,key)
        return {'organization':self.organization(identity,result['plan_id']), 'object_id':result['object_id']}

    def create_module(self,identity,plan_id,payload,key):
        return self._write(identity,CreateModule(plan_id=plan_id,**payload),key)

    def revise_module(self,identity,plan_id,module_id,payload,key):
        return self._write(identity,ReviseModule(plan_id=plan_id,module_id=module_id,**payload),key)

    def place_task(self,identity,plan_id,action_id,payload,key):
        return self._write(identity,PlaceTask(plan_id=plan_id,action_id=action_id,**payload),key)

    def order_children(self,identity,plan_id,payload,key):
        return self._write(identity,OrderChildren(plan_id=plan_id,**payload),key)

    def create_task(self,identity,plan_id,payload,key):
        return self.learning.core.execute(self.learning.principal(identity),CreatePlanTask(plan_id=plan_id,**payload),key)

    def purge_content(self,identity,plan_id,payload,key,module_id=None):
        object_id, kind = (module_id,'module_content') if module_id else (plan_id,'plan_content')
        command = (PurgeModuleContent(plan_id=plan_id,module_id=module_id,**payload) if module_id else
                   PurgePlanContent(plan_id=plan_id,**payload))
        result = ManagedPurge(self.learning).run(identity,kind,object_id,
            lambda:self.learning.core.execute(self.learning.principal(identity),command,key))
        return {'organization':self.organization(identity,plan_id),'object_id':object_id,'purge_report':result['purge']}
