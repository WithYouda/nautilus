import {expect,test} from '@playwright/test';
import {writeFileSync} from 'node:fs';
import {authorize} from './fact-helpers';

test('SSE and visible output do not wait for a delayed shared-state refresh',async({page})=>{
 test.setTimeout(45000);
 await authorize(page);
 expect((await page.request.put('/api/ai/provider',{data:{display_name:'Synthetic first response',base_url:process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,model:'mock-first-response',api_key:'synthetic',enabled:true}})).ok()).toBeTruthy();
 let acceptedAt=0,subscribedAt=0,metadataRequests=0,readsBeforeSubscribe=0,conversationId='';
 let release=()=>{};const metadataGate=new Promise<void>(resolve=>{release=resolve;});
 const samples:any[]=[];
 page.on('request',request=>{
   if(request.url().endsWith('/display-timing')) samples.push(request.postDataJSON());
   if(acceptedAt&&conversationId&&request.method()==='GET'&&new URL(request.url()).pathname==='/api/ai/conversations/'+conversationId&&!subscribedAt)readsBeforeSubscribe++;
 });
 await page.route('**/api/ai/conversations/*/messages',async route=>{
  if(route.request().method()!=='POST'){await route.continue();return;}
  const response=await route.fetch();conversationId=(await response.json()).run.conversation_id;acceptedAt=performance.now();await route.fulfill({response});
 });
 await page.route('**/api/conversation-state/conversation/*',async route=>{
  if(!acceptedAt||route.request().method()!=='GET'){await route.continue();return;}
  metadataRequests++;const response=await route.fetch();await metadataGate;await route.fulfill({response});
 });
 await page.route('**/api/ai/runs/*/stream',async route=>{subscribedAt=performance.now();await route.continue();});
 try {
  await page.reload();await page.getByRole('button',{name:'学习室',exact:true}).click();await page.getByRole('button',{name:'新建对话',exact:true}).click();
  const input=page.getByLabel('输入学习问题',{exact:true});await input.fill('合成首响应测试');await input.press('Enter');
  await expect(page.getByText('等待模型响应',{exact:true})).toBeVisible();
  expect(subscribedAt-acceptedAt).toBeLessThan(1000);expect(metadataRequests).toBeGreaterThan(0);
  await page.screenshot({path:'/tmp/nautilus-first-response-waiting.png'});
  await expect(page.locator('.ai-message--assistant')).toContainText('完成',{timeout:10000});
  const completed=await page.locator('.ai-message--assistant').innerText();
  expect(readsBeforeSubscribe).toBe(0);
  release();
  await expect(page.locator('.ai-message--assistant')).toContainText('完成');
  expect(await page.locator('.ai-message--assistant').innerText()).toBe(completed);
  await expect.poll(()=>samples.some(s=>s.phase==='waiting')).toBeTruthy();
  expect(samples.every(s=>s.subscription_delay_ms>=0&&s.subscription_delay_ms<1000)).toBeTruthy();
  writeFileSync('/tmp/nautilus-first-response-browser-timings.json',JSON.stringify({subscribe_after_accept_ms:subscribedAt-acceptedAt,readsBeforeSubscribe,samples},null,2));
 }finally{release();}
});


test('immediate subscription preserves regenerated ancestry and an unsent draft',async({page})=>{
 await authorize(page);
 expect((await page.request.put('/api/ai/provider',{data:{display_name:'Synthetic ancestry',base_url:process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,model:'mock-success',api_key:'synthetic',enabled:true}})).ok()).toBeTruthy();
 await page.reload();await page.getByRole('button',{name:'学习室',exact:true}).click();await page.getByRole('button',{name:'新建对话',exact:true}).click();
 const input=page.getByLabel('输入学习问题',{exact:true}),answers=page.locator('.ai-message--assistant');
 for(const text of ['合成首问','合成后续问题']){
  await input.fill(text);await input.press('Enter');
  await expect(answers.last()).toContainText('完成');
  await expect(page.getByRole('button',{name:'取消生成',exact:true})).toHaveCount(0);
 }
 await expect(answers).toHaveCount(2);await input.fill('保留这份未发送草稿');
 await answers.first().getByRole('button',{name:'重新生成',exact:true}).click();
 await expect(answers).toHaveCount(1);await expect(answers.first()).toContainText('完成');
 await expect(page.getByRole('button',{name:'取消生成',exact:true})).toHaveCount(0);
 await expect(input).toHaveValue('保留这份未发送草稿');
 await expect(page.getByLabel('回答 2/2',{exact:true})).toBeVisible();
 await answers.first().getByRole('button',{name:'上一个回答',exact:true}).click();
 await expect(answers).toHaveCount(2);await expect(page.getByText('合成后续问题',{exact:true})).toBeVisible();
 await page.reload();await expect(answers).toHaveCount(2);await expect(page.getByLabel('回答 1/2',{exact:true})).toBeVisible();
});
