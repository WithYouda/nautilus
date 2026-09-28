// Exercise the actual Windows WebView/Rust IPC with synthetic, isolated local data.
// node smoke-windows.cjs <exe> <frontend-directory-containing-node_modules>
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const net = require('node:net');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {setTimeout: delay} = require('node:timers/promises');
const [exe, frontend] = process.argv.slice(2);
if (!exe || !frontend) throw Error('Provide the EXE and frontend directory');
const {chromium} = require(path.join(frontend, 'node_modules/playwright'));
const dataDir = fs.mkdtempSync(path.join(process.env.TEMP, 'nautilus-windows-smoke-'));
let child, browser, page, requests = 0, lastResponse, debugPort;
const server = http.createServer(async (req, res) => {
  if (req.method !== 'POST' || req.url !== '/v1/chat/completions') { res.writeHead(404).end(); return; }
  let body = ''; for await (const part of req) body += part;
  const payload = JSON.parse(body);
  assert.equal(req.headers.authorization, 'Bearer synthetic-key');
  assert.equal(payload.tools, undefined);
  assert(payload.messages.some(m => m.content.includes('Windows synthetic material')));
  requests++;
  res.writeHead(200, {'Content-Type':'text/event-stream'});
  res.write(`data: ${JSON.stringify({choices:[{delta:{content:'Synthetic answer'}}]})}\n\n`);
  if (requests !== 2) {
    res.end(`data: ${JSON.stringify({choices:[{delta:{},finish_reason:'stop'}]})}\n\ndata: [DONE]\n\n`);
  } else lastResponse = res;
});
async function freePort() {
  const listener = net.createServer(); listener.listen(0, '127.0.0.1'); await once(listener, 'listening');
  const port = listener.address().port; await new Promise(resolve => listener.close(resolve)); return port;
}
async function launch() {
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
  await page.getByLabel('继续提问').waitFor();
}
async function close() {
  if (browser) { await browser.close().catch(()=>{}); browser=undefined; }
  if (child && child.exitCode===null) { const exited=once(child,'exit'); child.kill(); await exited; }
  await delay(500);
}
(async()=>{
  server.listen(0,'127.0.0.1'); await once(server,'listening');
  try {
    await launch();
    const pageErrors=[]; page.on('pageerror',e=>pageErrors.push(e.message));
    await page.getByLabel('兼容 OpenAI 的 HTTPS 地址（以 /v1 结尾）').fill(`http://127.0.0.1:${server.address().port}/v1`);
    await page.getByLabel('模型名称').fill('synthetic');
    await page.getByRole('button',{name:'保存模型设置'}).click();
    await page.getByText('模型设置已保存在这台设备。').waitFor();
    await page.getByLabel('API Key（只保留在当前应用内存，重启后需重新输入）').fill('synthetic-key');
    await page.getByLabel('标题',{exact:true}).fill('Windows test');
    await page.getByLabel('内容',{exact:true}).fill('Windows synthetic material');
    await page.getByRole('button',{name:'保存并选用'}).click();
    await page.getByText('已选 1',{exact:true}).waitFor();
    await page.getByLabel('继续提问').fill('First synthetic question');
    await page.getByRole('button',{name:'发送',exact:true}).click();
    await page.getByText('回答已保存。',{exact:true}).waitFor();
    await page.getByLabel('继续提问').fill('Second synthetic question');
    await page.getByRole('button',{name:'发送',exact:true}).click();
    await page.locator('.turn').nth(1).getByText('Synthetic answer',{exact:true}).waitFor();
    // A second launch must focus the existing window, not recover its live turn as interrupted.
    const second = spawn(exe, [], {cwd:path.dirname(exe),env:{...process.env,NAUTILUS_VALIDATION_DATA_DIR:dataDir},stdio:'ignore'});
    let timeout;
    try { await Promise.race([once(second,'exit'),new Promise((_,reject)=>{timeout=setTimeout(()=>{second.kill();reject(Error('Second instance did not exit'));},10000);})]); }
    finally { clearTimeout(timeout); }
    assert.equal(second.exitCode,0);
    const live = await page.evaluate(()=>window.__TAURI__.core.invoke('snapshot'));
    assert.equal(live.turns.at(-1).status,'pending');
    await page.getByRole('button',{name:'停止回答'}).click();
    await page.getByText('已取消',{exact:true}).waitFor();
    assert.equal(requests,2);
    await page.getByLabel('继续提问').fill('Continue after cancellation');
    await page.getByRole('button',{name:'发送',exact:true}).click();
    await page.getByText('回答已保存。',{exact:true}).waitFor();
    assert.equal(requests,3);
    await close();
    await launch();
    const restored = await page.evaluate(()=>window.__TAURI__.core.invoke('snapshot'));
    assert.equal(restored.materials[0].content,'Windows synthetic material');
    assert.equal(restored.turns.length,3);
    assert.equal(restored.turns[0].status,'complete');
    assert.equal(restored.turns[0].answer,'Synthetic answer');
    assert.equal(restored.turns[1].status,'canceled');
    assert.equal(restored.turns[1].answer,'Synthetic answer');
    assert.equal(restored.turns[2].status,'complete');
    assert.equal(restored.turns[2].parent_id,restored.turns[1].id);
    assert.equal(await page.getByLabel('API Key（只保留在当前应用内存，重启后需重新输入）').inputValue(),'');
    assert.equal(requests,3);
    assert.deepEqual(pageErrors,[]);
    await page.screenshot({path:path.join(dataDir,'windows-smoke.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth <= document.documentElement.clientWidth));
    await page.screenshot({path:path.join(dataDir,'windows-smoke-390.png'),fullPage:true});
    console.log(`PASS native Windows: real IPC, local model stream, single instance, cancel, reopen, memory-only key; data=${dataDir}`);
  } finally { await close(); lastResponse?.destroy(); server.closeAllConnections(); server.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
