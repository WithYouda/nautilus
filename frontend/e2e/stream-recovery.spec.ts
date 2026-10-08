import {expect,test} from '@playwright/test';
import {authorize} from './fact-helpers';

test('subscriber lag reconnects to the same run without resending the question',async({page})=>{
 await authorize(page);
 expect((await page.request.put('/api/ai/provider',{data:{display_name:'Synthetic stream',base_url:process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,model:'mock-slow',api_key:'synthetic',enabled:true}})).ok()).toBeTruthy();
 let posts=0,streams=0;
 let release:(run:any)=>void=()=>{};
 const accepted=new Promise<any>(resolve=>{release=resolve;});
 await page.route('**/api/ai/conversations/*/messages',async route=>{if(route.request().method()!=='POST'){await route.continue();return;}posts++;const response=await route.fetch();release((await response.json()).run);await route.fulfill({response});});
 await page.route('**/api/ai/runs/*/stream',async route=>{
  streams++;
  if(streams>1){await route.continue();return;}
  const run=await accepted;
  await route.fulfill({status:200,contentType:'text/event-stream',body:'event: error\ndata: '+JSON.stringify({run_id:run.id,message_id:run.response_message_id,status:'running',kind:'subscriber_lag',message:'流式连接处理过慢，请重新连接以继续接收',content:'',reasoning_content:''})+'\n\n'});
 });
 await page.reload();await page.getByRole('button',{name:'学习室',exact:true}).click();await page.getByRole('button',{name:'新建对话',exact:true}).click();
 const input=page.getByLabel('输入学习问题',{exact:true});await input.fill('合成流式恢复案例');await input.press('Enter');
 const run=await accepted;
 await expect.poll(()=>streams).toBeGreaterThan(1);
 await expect.poll(async()=>{const data=await(await page.request.get('/api/ai/conversations/'+run.conversation_id)).json();return data.active_run;},{timeout:15000}).toBeNull();
 await expect(page.getByRole('button',{name:'取消生成',exact:true})).toHaveCount(0);
 await expect(page.locator('.ai-message--assistant')).toHaveCount(1);
 await expect(page.locator('.ai-message--user')).toHaveCount(1);
 await expect(page.getByText('流式连接处理过慢，请重新连接以继续接收',{exact:true})).toHaveCount(0);
 expect(posts).toBe(1);
 const detail=await(await page.request.get('/api/ai/conversations/'+run.conversation_id)).json();
 expect(detail.messages.at(-1).status).toBe('complete');
 await expect(page.locator('.ai-message--assistant')).toContainText(detail.messages.at(-1).content);
});
