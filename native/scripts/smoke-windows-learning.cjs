// Exercise the actual Windows WebView/Rust IPC with synthetic, isolated local data.
// node smoke-windows-learning.cjs <exe> <frontend-directory-containing-node_modules> [synthetic-schema2-sqlite]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const net = require('node:net');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {setTimeout: delay} = require('node:timers/promises');
const [exe, frontend, fixture] = process.argv.slice(2);
if (!exe || !frontend) throw Error('Provide the EXE and frontend directory');
const {chromium} = require(path.join(frontend, 'node_modules/playwright'));
const dataDir = fs.mkdtempSync(path.join(process.env.TEMP, 'nautilus-windows-smoke-'));
let child, browser, page, requests = 0, lastResponse, debugPort;
const seen=[];
const learningDraft={original_intent:'Learn synthetic fractions',goal_title:'Understand fractions',goal_description:'Compare simple fractions',plan_title:'Fraction practice',plan_description:'One small step',action_title:'Explain one half',context_key:'basic fractions',object_description:'Fractions',behavior:'Explain one half with an example',outcome_context_key:'basic fractions',boundaries:'Only one half',stop_conditions:'Explain it in my own words',time_budget_minutes:15};
const server=http.createServer(async(req,res)=>{
 if(req.method!=='POST'||req.url!=='/v1/chat/completions'){res.writeHead(404).end();return;}
 let body='';for await(const part of req)body+=part;
 const payload=JSON.parse(body);seen.push(payload);requests++;
 assert.equal(req.headers.authorization,'Bearer synthetic-key');
 const setup=payload.messages.some(m=>m.role==='system'&&m.content.includes('学习安排助手'));
 const answer=setup?JSON.stringify(learningDraft):`Learning answer ${requests}`;
 res.writeHead(200,{'Content-Type':'text/event-stream'});
 res.end(`data: ${JSON.stringify({choices:[{delta:{content:answer}}]})}\n\ndata: ${JSON.stringify({choices:[{delta:{},finish_reason:'stop'}]})}\n\ndata: [DONE]\n\n`);
});
async function freePort() {
  const listener = net.createServer(); listener.listen(0, '127.0.0.1'); await once(listener, 'listening');
  const port = listener.address().port; await new Promise(resolve => listener.close(resolve)); return port;
}
async function launch(upgrade=false) {
  const port = debugPort ??= await freePort();
  child = spawn(exe, [], {cwd:path.dirname(exe), env:{...process.env,
    NAUTILUS_VALIDATION_DATA_DIR:dataDir,
    WEBVIEW2_USER_DATA_FOLDER:path.join(dataDir,'webview'),
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port} --remote-debugging-address=127.0.0.1`,
  }, stdio:'ignore'});
  child.on('error', error => { console.error(error.message); });
  for (let attempt=0;attempt<120;attempt++) {
    if (child.exitCode !== null) throw Error(`App exited during startup: ${child.exitCode}`);
    try { browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`); break; }
    catch { await delay(250); }
  }
  if (!browser) throw Error('WebView2 debugging endpoint unavailable');
  for (let attempt=0;attempt<80;attempt++) {
    page = browser.contexts().flatMap(c=>c.pages()).find(p=>p.url().includes('tauri.localhost'));
    if (page) break; await delay(250);
  }
  if (!page) throw Error('Native application page unavailable');
  await page.getByRole('heading',{name:'在这台设备上继续学习'}).waitFor();
  if(upgrade) { await page.getByRole('button',{name:'备份并升级本机数据'}).click(); }
  await page.getByLabel('继续提问').waitFor();
}
async function close() {
  if (browser) { await browser.close().catch(()=>{}); browser=undefined; }
  if (child && child.exitCode===null) { const exited=once(child,'exit'); child.kill(); await exited; }
  await delay(500);
}
async function until(label,check,timeout=20000){const end=Date.now()+timeout;while(Date.now()<end){if(await check())return;await delay(150);}throw Error('Timed out: '+label);}
async function snapshot(){return page.evaluate(()=>window.__TAURI__.core.invoke('snapshot'));}
async function send(question){await page.getByLabel('继续提问',{exact:true}).fill(question);await page.getByRole('button',{name:'发送',exact:true}).click();await page.getByText('回答已保存。',{exact:true}).waitFor();}
(async()=>{
 server.listen(0,'127.0.0.1');await once(server,'listening');
 const errors=[];
 try{
  let copiedKeys;
  if(fixture){fs.copyFileSync(fixture,path.join(dataDir,'native-validation.sqlite3'));const oldKeys=path.join(path.dirname(fixture),'credentials');if(fs.existsSync(oldKeys)){fs.cpSync(oldKeys,path.join(dataDir,'credentials'),{recursive:true});copiedKeys=fs.readdirSync(oldKeys).map(name=>[name,fs.readFileSync(path.join(oldKeys,name))]);}}
  await launch(Boolean(fixture));page.on('pageerror',e=>errors.push(e.message));
  const initial=await snapshot();assert.equal(initial.schema_version,3);
  if(copiedKeys)for(const [name,bytes]of copiedKeys)assert.deepEqual(fs.readFileSync(path.join(dataDir,'credentials',name)),bytes,'upgrade changed encrypted key');
  if(fixture){assert(initial.turns.length>0);assert(initial.turns.every(t=>t.session_id===null));assert.equal(initial.learning_tasks.length,0);assert(fs.readdirSync(dataDir).some(n=>n.startsWith('native-before-sync-')));}
  await page.getByLabel('兼容 OpenAI 的 HTTPS 地址（以 /v1 结尾）').fill(`http://127.0.0.1:${server.address().port}/v1`);
  await page.getByLabel('模型名称',{exact:true}).fill('synthetic');
  await page.getByRole('button',{name:'保存模型设置',exact:true}).click();
  await page.getByText('模型设置已保存在这台设备。',{exact:true}).waitFor();
  await page.getByLabel('API Key',{exact:true}).fill('synthetic-key');
  await page.getByRole('button',{name:'保存 Key',exact:true}).click();
  await page.getByText('Key 已保存在本机，重开应用后会自动使用。',{exact:true}).waitFor();
  await page.getByLabel('标题',{exact:true}).fill('Shared learning material');
  await page.getByLabel('内容',{exact:true}).fill('Private fraction reference');
  await page.getByRole('button',{name:'保存并选用',exact:true}).click();
  await until('legacy selected material',async()=>(await snapshot()).materials.some(m=>m.title==='Shared learning material'));
  await page.getByRole('button',{name:'学习首页',exact:true}).click();
  await page.getByRole('button',{name:'创建学习任务',exact:true}).click();
  await page.getByLabel('你想学习什么',{exact:true}).fill('Learn synthetic fractions');
  await page.getByRole('button',{name:'AI 草案',exact:true}).click();
  await page.getByText('草案可以修改；确认后才会保存目标、计划与任务。',{exact:true}).waitFor();
  assert.equal((await snapshot()).learning_tasks.length,0,'AI draft created learning facts');
  await page.getByLabel('第一步任务',{exact:true}).fill('Task Alpha');
  await page.getByRole('button',{name:'确认并保存安排',exact:true}).click();
  await page.getByText('学习安排已保存。点击“开始学习”才会建立学习会话。',{exact:true}).waitFor();
  let now=await snapshot();assert.equal(now.learning_tasks.length,1);assert.equal(now.learning_sessions.length,0);
  const alpha=now.learning_tasks[0];assert.equal(alpha.draft.action_title,'Task Alpha');
  await page.getByRole('button',{name:'学习首页',exact:true}).click();
  await page.locator('.learning-list-row').filter({hasText:'Task Alpha'}).getByRole('button',{name:'开始学习',exact:true}).click();
  await page.getByText('已开始学习。可以提问，也可以保存学习记录。',{exact:true}).waitFor();
  assert.equal((await snapshot()).selection_heads.filter(h=>h.task_id===alpha.id).length,0,'new task inherited legacy material choices');
  await page.locator('.material').filter({hasText:'Shared learning material'}).getByRole('checkbox').check();
  await send('Alpha question');
  const alphaCall=seen.at(-1);assert(JSON.stringify(alphaCall).includes('Task Alpha'));assert(JSON.stringify(alphaCall).includes('Private fraction reference'));
  await page.getByLabel('继续提问',{exact:true}).fill('Draft to preserve');
  await page.getByRole('button',{name:'给个提示',exact:true}).click();
  await until('help finished',async()=>(await snapshot()).turns.some(t=>t.help_request==='hint'&&t.status==='complete'));
  assert.equal(await page.getByLabel('继续提问',{exact:true}).inputValue(),'Draft to preserve');
  await page.locator('.turn').last().locator('.answer').scrollIntoViewIfNeeded();
  await until('help display recorded',async()=>(await snapshot()).help_displays.length>0);
  await page.getByLabel('学习记录内容',{exact:true}).fill('I can describe a half');
  await page.getByRole('button',{name:'保存记录',exact:true}).click();
  await page.getByText('学习记录已保存。',{exact:true}).waitFor();
  assert.equal((await snapshot()).learning_notes.length,1);
  await page.getByRole('button',{name:'学习首页',exact:true}).click();
  await page.getByRole('button',{name:'创建学习任务',exact:true}).click();
  await page.getByLabel('你想学习什么',{exact:true}).fill('Learn another topic');
  await page.getByRole('button',{name:'自己安排',exact:true}).click();
  for(const [label,value] of Object.entries({'目标':'Another goal','计划':'Another plan','第一步任务':'Task Beta','学习情境':'Second context','学习对象':'Other topic','要做的事':'Explain another thing','成果情境':'Second context','停止条件':'Give one explanation'}))await page.getByLabel(label,{exact:true}).fill(value);
  await page.getByRole('button',{name:'确认并保存安排',exact:true}).click();
  await page.getByText('学习安排已保存。点击“开始学习”才会建立学习会话。',{exact:true}).waitFor();
  await page.getByRole('button',{name:'学习首页',exact:true}).click();
  await page.locator('.learning-list-row').filter({hasText:'Task Beta'}).getByRole('button',{name:'开始学习',exact:true}).click();
  await page.getByText('已开始学习。可以提问，也可以保存学习记录。',{exact:true}).waitFor();
  assert.equal(await page.locator('.turn').count(),0);
  await send('Beta question');
  const betaCall=JSON.stringify(seen.at(-1));assert(betaCall.includes('Task Beta'));assert(!betaCall.includes('Alpha question'));assert(!betaCall.includes('Private fraction reference'));
  await page.getByRole('button',{name:'学习首页',exact:true}).click();
  await page.locator('.learning-list-row').filter({hasText:'Task Alpha'}).getByRole('button',{name:'继续学习',exact:true}).click();
  assert.equal(await page.getByLabel('继续提问',{exact:true}).inputValue(),'Draft to preserve');
  assert.equal(await page.locator('.turn').count(),2);
  await until('position persisted',async()=>{const n=await snapshot();return n.position.session_id===n.learning_sessions.find(s=>s.task_id===alpha.id).id&&Boolean(n.position.turn_id);});
  await close();await launch();
  await until('restored task and path',async()=>await page.locator('.turn').count()===2);
  assert(await page.locator('.turn').first().getByText('Alpha question',{exact:true}).isVisible());
  await page.getByRole('button',{name:'学习记录',exact:true}).click();
  await page.getByText('I can describe a half',{exact:true}).waitFor();
  const final=await snapshot();assert.equal(final.learning_tasks.length,2);assert.equal(final.learning_sessions.length,2);assert.equal(final.learning_notes.length,1);
  assert.equal(requests,4);assert.deepEqual(errors,[]);
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth));
  await page.screenshot({path:path.join(dataDir,'learning-390.png'),fullPage:true});
  console.log('PASS native learning: explicit upgrade, AI draft/manual setup, separate start, task/context/material isolation, help/draft/display facts, records and reopen; data='+dataDir);
 }catch(error){if(page)await page.screenshot({path:path.join(dataDir,'learning-failure.png'),fullPage:true}).catch(()=>{});console.error('Data:',dataDir);throw error;}
 finally{await close();server.closeAllConnections();server.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
