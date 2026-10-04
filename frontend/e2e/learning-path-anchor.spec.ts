import { expect,test } from '@playwright/test';
import { authorize,checkDefaultTeachingSupport } from './fact-helpers';

test('a restored path opens its exact answer and allows explicit retry after a state conflict',async({page})=>{
  test.setTimeout(60_000);
  await authorize(page);
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
  const key=(label:string)=>`d2-anchor-test:${label}:${Date.now()}`;
  async function post(url:string,data:unknown){const response=await page.request.post(url,{data});expect(response.ok(),await response.text()).toBeTruthy();return response.json();}
  async function get(url:string){const response=await page.request.get(url);expect(response.ok()).toBeTruthy();return response.json();}
  const created=await post('/api/learning/plans',{title:'合成回答位置检查',goal_id:null,request_key:key('plan')});
  const pid=created.plan_id,base=`/api/learning/plans/${pid}/path`;
  const tasks=[];
  for(const label of ['原学习任务','另一阶段任务']){
    const org=await get(`/api/learning/plans/${pid}/organization`);
    tasks.push(await post(`/api/learning/plans/${pid}/tasks`,{action_title:label,context_key:'test:anchor',object_description:label,
      behavior:'比较输入',outcome_context_key:'test:anchor',boundaries:'',stop_conditions:'核对后暂停',expected_revision:org.revision,request_key:key(label)}));
  }
  const fields={title:'合成两阶段路线',nodes:tasks.map((task,index)=>({id:`n${index}`,title:`阶段${index+1}`,action_ids:[task.action_id],outcome_ids:[task.outcome_id]})),
    edges:[{source:'n0',target:'n1'}],entry_node_id:'n0',current_node_id:'n0',reason:''};
  async function adopt(fields:object,intent:string){const view=await get(base);
    const draft=await post(base+'/drafts',{...fields,intent,expected_revision:view.revision,expected_organization_revision:view.organization_revision,request_key:key('draft')});
    const preview=await post(base+'/previews',{draft_id:draft.draft_id});
    return post(base+'/decisions',{draft_id:draft.draft_id,expected_draft_revision:preview.draft_revision,expected_revision:preview.revision,review_key:preview.review_key,request_key:key('adopt')});}
  const first=await adopt(fields,'create');
  const state=await get('/api/learning/state');
  const started=await post(base+'/start',{version_id:first.adopted_version_id,node_id:'n0',delegation_id:tasks[0].delegation_id,
    expected_revision:first.revision,expected_action_version:state.actions.find((a:{id:string})=>a.id===tasks[0].action_id).version,request_key:key('start')});
  const configured=await page.request.put('/api/ai/provider',{data:{display_name:'Synthetic path provider',base_url:process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model:'mock-success',api_key:'synthetic-path-only',enabled:true,request_timeout_seconds:15}});expect(configured.ok()).toBeTruthy();
  await checkDefaultTeachingSupport(page);
  const chat=await post('/api/ai/conversations',{context_scope:'independent'});const cid=chat.conversation.id;
  expect((await page.request.put(`/api/learning/sessions/${started.session_id}/room`,{data:{conversation_id:cid}})).ok()).toBeTruthy();
  const messageUrl=`/api/ai/conversations/${cid}/messages`,chatUrl=`/api/ai/conversations/${cid}`;
  const answer=await post(messageUrl,{content:'合成问题',client_message_id:key('message'),source_scope:{mode:'unspecified',version_ids:[]}});
  await expect.poll(async()=>(await get(chatUrl)).active_run).toBeNull();
  const oldAnswer=answer.run.response_message_id;
  const later=await post(messageUrl,{content:'合成问题',regenerate_message_id:oldAnswer,client_message_id:key('regenerate'),source_scope:{mode:'unspecified',version_ids:[]}});
  await expect.poll(async()=>(await get(chatUrl)).active_run).toBeNull();
  const currentUrl=`/api/conversation-state/conversation/${cid}`;
  async function select(leaf:string){const current=await get(currentUrl);const saved=await page.request.put(currentUrl,{data:{expected_revision:current.revision,
    leaf_id:leaf,paths:{[leaf]:leaf},source_scope:{mode:'unspecified',version_ids:[]},search_override:null}});expect(saved.ok(),await saved.text()).toBeTruthy();}
  await select(oldAnswer);
  const changed=await adopt({...fields,current_node_id:'n1'},'change_scope');
  await select(later.run.response_message_id);
  const restoredDraft=await post(base+'/restore-draft',{version_id:first.adopted_version_id,intent:'restore',expected_revision:changed.revision,
    expected_organization_revision:changed.organization_revision,request_key:key('restore')});
  const preview=await post(base+'/previews',{draft_id:restoredDraft.draft_id});
  const restored=await post(base+'/decisions',{draft_id:restoredDraft.draft_id,expected_revision:preview.revision,
    expected_draft_revision:preview.draft_revision,review_key:preview.review_key,request_key:key('restore-confirm')});
  let conflict=false;
  await page.route(`**${currentUrl}`,async route=>{if(route.request().method()==='PUT'&&!conflict){conflict=true;await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'conversation_state_conflict'})});}else await route.continue();});
  await page.goto(`/?view=plans&plan=${pid}&plan_view=path&path_version=${restored.adopted_version_id}&path_node=n0`);
  await page.getByRole('button',{name:'继续学习',exact:true}).click();
  await expect(page.getByRole('button',{name:'重试恢复原位置',exact:true})).toBeVisible();
  await expect(page.getByLabel('输入学习问题')).toBeDisabled();
  expect((await get(currentUrl)).leaf_id).toBe(later.run.response_message_id);
  await page.getByRole('button',{name:'重试恢复原位置',exact:true}).click();
  await expect(page.getByLabel('输入学习问题')).toBeEnabled();
  await expect(page.locator(`#answer-${oldAnswer}`)).toBeVisible();
  await expect(page.locator(`#answer-${later.run.response_message_id}`)).toHaveCount(0);
  expect((await get(currentUrl)).leaf_id).toBe(oldAnswer);
  const before=await get(chatUrl);await page.reload();
  await expect(page.getByLabel('输入学习问题')).toBeEnabled();
  await expect(page.locator(`#answer-${oldAnswer}`)).toBeVisible();
  expect((await get(chatUrl)).messages).toEqual(before.messages);
  expect((await get('/api/learning/state')).sessions.filter((s:{action_id:string})=>s.action_id===tasks[0].action_id)).toHaveLength(2);
  expect(errors).toEqual([]);
});
