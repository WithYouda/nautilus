// Real Windows WebView/Rust IPC + isolated Linux Rust peer over the LAN transport.
// node smoke-windows-sync.cjs <exe> <frontend-dir> <peer-host> <peer-port> <peer-control-token> [synthetic-v1-sqlite]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const http = require('node:http');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {setTimeout: delay} = require('node:timers/promises');
const [exe, frontend, peerHost, peerPortText, peerControlToken, v1Fixture] = process.argv.slice(2);
if (!exe || !frontend || !peerHost || !peerPortText || !peerControlToken) {
  throw Error('Provide EXE, frontend dir, peer host, peer control port, peer control token, and optional synthetic v1 SQLite file');
}
const peerPort = Number(peerPortText);
assert(Number.isInteger(peerPort) && peerPort > 0 && peerPort <= 65535);
const {chromium} = require(path.join(frontend, 'node_modules/playwright'));
let dataDir = fs.mkdtempSync(path.join(process.env.TEMP || os.tmpdir(), 'nautilus-windows-sync-'));
let child, browser, page, debugPort, modelRequests = 0;
const pageErrors = [];
const modelServer = http.createServer(async (request, response) => {
  if (request.method !== 'POST' || request.url !== '/v1/chat/completions') { response.writeHead(404).end(); return; }
  let body = '';
  for await (const part of request) body += part;
  const payload = JSON.parse(body);
  assert.equal(request.headers.authorization, 'Bearer synthetic-key');
  assert(payload.messages.some(item => item.content.includes('Windows branch question')));
  modelRequests++;
  response.writeHead(200, {'Content-Type': 'text/event-stream'});
  response.end(`data: ${JSON.stringify({choices:[{delta:{content:'Windows synthetic answer'}}]})}\n\ndata: ${JSON.stringify({choices:[{delta:{},finish_reason:'stop'}]})}\n\ndata: [DONE]\n\n`);
});
function control(command, values={}) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection({host:peerHost, port:peerPort});
    socket.setTimeout(10000);
    let data = '';
    socket.on('connect', () => socket.write(JSON.stringify({token:peerControlToken, command, ...values}) + '\n'));
    socket.on('data', chunk => { data += chunk; if (data.includes('\n')) socket.end(); });
    socket.on('timeout', () => socket.destroy(Error(`peer control timed out: ${command}`)));
    socket.on('error', reject);
    socket.on('end', () => {
      try {
        const reply = JSON.parse(data.trim());
        if (!reply.ok) reject(Error(`peer ${command}: ${reply.error}`));
        else resolve(reply.value);
      } catch (error) { reject(error); }
    });
  });
}
async function until(label, check, timeout=20000) {
  const end = Date.now() + timeout;
  let last;
  while (Date.now() < end) {
    try { const value = await check(); if (value) return value; }
    catch (error) { last = error; }
    await delay(200);
  }
  throw Error(`Timed out waiting for ${label}${last ? `: ${last.message}` : ''}`);
}
async function freePort() {
  const listener = net.createServer(); listener.listen(0, '127.0.0.1'); await once(listener, 'listening');
  const port = listener.address().port; await new Promise(resolve => listener.close(resolve)); return port;
}
async function snapshot() { return page.evaluate(() => window.__TAURI__.core.invoke('snapshot')); }
async function launch(expectUpgrade=false) {
  debugPort = await freePort();
  child = spawn(exe, [], {cwd:path.dirname(exe),env:{...process.env,
    NAUTILUS_VALIDATION_DATA_DIR:dataDir,
    WEBVIEW2_USER_DATA_FOLDER:path.join(dataDir,'webview'),
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${debugPort} --remote-debugging-address=127.0.0.1`,
  },stdio:'ignore'});
  child.on('error', error => { console.error(error.message); });
  browser = await until('WebView2 debugging endpoint', async () => chromium.connectOverCDP(`http://127.0.0.1:${debugPort}`), 30000);
  page = await until('native WebView', () => browser.contexts().flatMap(context => context.pages()).find(candidate => candidate.url().includes('tauri.localhost')));
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.getByRole('heading',{name:'在这台设备上继续学习'}).waitFor();
  if (expectUpgrade) await page.getByRole('button',{name:'备份并升级本机数据'}).waitFor();
  else await page.getByLabel('继续提问').waitFor();
}
async function close() {
  if (browser) { await browser.close().catch(()=>{}); browser=undefined; }
  if (child && child.exitCode === null) {
    const exited = once(child, 'exit'); child.kill(); await Promise.race([exited, delay(10000)]);
  }
  child=undefined; page=undefined;
}
(async () => {
  modelServer.listen(0,'127.0.0.1'); await once(modelServer,'listening');
  try {
    if (v1Fixture) {
      assert(fs.statSync(v1Fixture).isFile(), 'upgrade fixture must be a file');
      fs.copyFileSync(v1Fixture,path.join(dataDir,'native-validation.sqlite3'));
      await launch(true);
      await page.getByRole('button',{name:'备份并升级本机数据'}).click();
      await page.getByLabel('继续提问').waitFor();
      const upgraded = await snapshot();
      assert.equal(upgraded.schema_version,2);
      assert(upgraded.materials.length + upgraded.turns.length > 0, 'synthetic v1 fixture should contain saved records');
      assert(fs.readdirSync(dataDir).some(name => name.startsWith('native-before-sync-') && name.endsWith('.sqlite3')), 'upgrade backup missing');
      await close();
      dataDir = fs.mkdtempSync(path.join(process.env.TEMP || os.tmpdir(), 'nautilus-windows-sync-'));
    }
    const peerMaterial = await control('add_material',{title:'Peer note',content:'Peer synthetic material'});
    const rootId = await control('create_completed_turn',{question:'Shared root question',answer:'Shared root answer',materialIds:[],parentId:null});
    const code = await control('invite');
    await launch();
    await until('Windows sync service', async () => page.evaluate(() => window.__TAURI__.core.invoke('sync_invite').then(() => true).catch(() => false)));
    await page.getByLabel('继续提问').fill('Draft survives incoming sync');
    await page.getByLabel('这台设备的名称').fill('Windows synthetic device');
    await page.getByRole('button',{name:'保存设备名称'}).click();
    await until('Windows name saved', async () => (await page.evaluate(() => window.__TAURI__.core.invoke('sync_status'))).device_name === 'Windows synthetic device');
    await page.getByPlaceholder('输入 10 分钟内生成的配对码').fill(code);
    await page.getByRole('button',{name:'发送配对请求'}).click();
    await page.getByText('合成设备',{exact:true}).waitFor();
    assert.equal((await snapshot()).materials.length,0, 'private content arrived before confirmation');
    assert.equal((await snapshot()).turns.length,0, 'saved turns arrived before confirmation');
    const pending = await until('peer pairing request', async () => (await control('status')).pending[0]);
    assert.equal(pending.name,'Windows synthetic device');
    await page.getByRole('button',{name:'确认配对'}).click();
    assert.equal((await snapshot()).materials.length,0, 'private content arrived after only one confirmation');
    await control('confirm',{peerId:pending.id});
    await until('both devices paired', async () => {
      const remote = await control('status');
      const local = await page.evaluate(() => window.__TAURI__.core.invoke('sync_status'));
      return remote.peers.length === 1 && local.peers.length === 1;
    },30000);
    await until('peer material and turn auto-arrive', async () => {
      const now = await snapshot();
      return now.materials.some(material => material.id === peerMaterial.id) && now.turns.some(turn => turn.id === rootId);
    },30000);
    assert.equal(await page.getByLabel('继续提问').inputValue(),'Draft survives incoming sync');
    await page.getByLabel('标题',{exact:true}).fill('Windows note');
    await page.getByPlaceholder('粘贴需要参考的文字').fill('Windows synthetic material');
    await page.getByRole('button',{name:'保存并选用'}).click();
    const windowsMaterial = await until('Windows material saved', async () => (await snapshot()).materials.find(material => material.title === 'Windows note'));
    await until('Windows material auto-arrives at peer', async () => (await control('snapshot')).materials.some(material => material.id === windowsMaterial.id),30000);
    await page.locator('.material').filter({hasText:'Windows note'}).getByRole('checkbox').uncheck();
    await until('empty selection saved', async () => (await snapshot()).selection_heads[0]?.material_ids.length === 0);
    await page.getByRole('button',{name:'Shared root question'}).click();
    await page.getByLabel('兼容 OpenAI 的 HTTPS 地址（以 /v1 结尾）').fill(`http://127.0.0.1:${modelServer.address().port}/v1`);
    await page.getByLabel('模型名称').fill('synthetic');
    await page.getByRole('button',{name:'保存模型设置'}).click();
    await page.getByLabel('API Key（只保留在当前应用内存，重启后需重新输入）').fill('synthetic-key');
    await page.getByLabel('继续提问').fill('Windows branch question');
    await page.getByRole('button',{name:'发送',exact:true}).click();
    const windowsTurn = await until('Windows turn complete', async () => (await snapshot()).turns.find(turn => turn.question === 'Windows branch question' && turn.status === 'complete'),30000);
    assert.equal(windowsTurn.parent_id,rootId);
    await until('Windows turn auto-arrives at peer', async () => (await control('snapshot')).turns.some(turn => turn.id === windowsTurn.id),30000);
    await page.getByLabel('继续提问').fill('Unsent draft after branch sync');
    const peerBranchId = await control('create_completed_turn',{question:'Peer sibling question',answer:'Peer sibling answer',materialIds:[],parentId:rootId});
    await until('peer sibling auto-arrives', async () => (await snapshot()).turns.some(turn => turn.id === peerBranchId),30000);
    assert.equal(await page.getByLabel('继续提问').inputValue(),'Unsent draft after branch sync');
    assert.equal(await page.locator('.turn').count(),2);
    assert(await page.locator('.turn').last().getByText('Windows branch question').isVisible());
    await page.getByRole('button',{name:'Peer sibling question'}).click();
    assert.equal(await page.locator('.turn').count(),2);
    assert(await page.locator('.turn').last().getByText('Peer sibling question').isVisible());
    await page.getByRole('button',{name:'Windows branch question'}).click();
    assert(await page.locator('.turn').last().getByText('Windows branch question').isVisible());
    console.log('pairing and branch steps passed; checking conflicts');
    // Both stores edit the same retained material head while transport is offline.
    await control('pause');
    await page.locator('.material').filter({hasText:'Peer note'}).getByRole('button',{name:'编辑'}).click();
    await page.getByLabel('标题',{exact:true}).fill('Windows changed peer note');
    await page.getByPlaceholder('粘贴需要参考的文字').fill('Windows conflict content');
    await page.getByRole('button',{name:'保存新版本'}).click();
    await until('Windows offline material edit', async () => (await snapshot()).materials.find(material => material.id === peerMaterial.id)?.content === 'Windows conflict content');
    await control('edit_material',{materialId:peerMaterial.id,title:'Peer changed peer note',content:'Peer conflict content'});
    await control('resume');
    const conflict = await until('material conflict imported over LAN', async () =>
      (await snapshot()).material_conflicts.find(item => item.material_id === peerMaterial.id),30000);
    assert.equal(conflict.versions.length,2);
    assert.deepEqual(new Set(conflict.versions.map(version => version.content)),new Set(['Windows conflict content','Peer conflict content']));
    assert.equal(await page.getByLabel('继续提问').inputValue(),'Unsent draft after branch sync');
    const windowsVersion = page.locator('.conflict-version').filter({hasText:'Windows changed peer note'});
    await windowsVersion.getByText('查看完整内容').click();
    assert.equal(await windowsVersion.locator('pre').innerText(),'Windows conflict content');
    const peerVersion = page.locator('.conflict-version').filter({hasText:'Peer changed peer note'});
    await peerVersion.getByText('查看完整内容').click();
    assert.equal(await peerVersion.locator('pre').innerText(),'Peer conflict content');
    assert(await page.getByRole('button',{name:'发送',exact:true}).isEnabled(), 'unselected material conflict blocked an unrelated question');
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth <= document.documentElement.clientWidth));
    await page.screenshot({path:path.join(dataDir,'material-conflict-390.png'),fullPage:true});
    await page.setViewportSize({width:900,height:780});
    await windowsVersion.getByRole('button',{name:'采用此版本'}).click();
    await until('material resolution converges', async () => {
      const local = await snapshot();
      const remote = await control('snapshot');
      return local.material_conflicts.length === 0 && remote.material_conflicts.length === 0 &&
        local.materials.find(material => material.id === peerMaterial.id)?.content === 'Windows conflict content' &&
        remote.materials.find(material => material.id === peerMaterial.id)?.content === 'Windows conflict content';
    },30000);
    console.log('material conflict resolved; checking selection conflict');
    // Selection is independently changed on both sides from the same head.
    await control('pause');
    await page.locator('.material').filter({hasText:'Windows note'}).getByRole('checkbox').check();
    await until('Windows offline selection', async () => (await snapshot()).selection_heads[0]?.material_ids.includes(windowsMaterial.id));
    await control('save_selection',{materialIds:[peerMaterial.id]});
    await control('resume');
    const selectionConflict = await until('selection conflict imported over LAN', async () => {
      const heads = (await snapshot()).selection_heads;
      return heads.length === 2 ? heads : null;
    },30000);
    assert(selectionConflict.some(head => head.material_ids.length === 1 && head.material_ids[0] === windowsMaterial.id));
    assert(selectionConflict.some(head => head.material_ids.length === 1 && head.material_ids[0] === peerMaterial.id));
    assert.equal(await page.getByLabel('继续提问').inputValue(),'Unsent draft after branch sync');
    await page.locator('.choice-row').filter({hasText:'Windows note'}).getByRole('button',{name:'采用这份选择'}).click();
    await until('selection resolution converges', async () => {
      const local = (await snapshot()).selection_heads;
      const remote = (await control('snapshot')).selection_heads;
      return local.length === 1 && remote.length === 1 &&
        local[0].material_ids.length === 1 && local[0].material_ids[0] === windowsMaterial.id &&
        remote[0].material_ids.length === 1 && remote[0].material_ids[0] === windowsMaterial.id;
    },30000);
    console.log('selection conflict resolved; checking stale edit');
    // A draft opened on an old material revision must survive a rejected stale save.
    await page.locator('.material').filter({hasText:'Windows changed peer note'}).getByRole('button',{name:'编辑'}).click();
    await page.getByPlaceholder('粘贴需要参考的文字').fill('Unsent stale editor draft');
    const editedRevision = (await snapshot()).materials.find(material => material.id === peerMaterial.id).revision_id;
    await control('edit_material',{materialId:peerMaterial.id,title:'Peer newer note',content:'Peer newer content'});
    await until('new peer revision auto-arrives', async () => {
      const material = (await snapshot()).materials.find(item => item.id === peerMaterial.id);
      return material?.revision_id !== editedRevision && material?.content === 'Peer newer content';
    },30000);
    await page.getByRole('button',{name:'保存新版本'}).click();
    await page.getByText('另一台设备已更新相关内容',{exact:false}).waitFor();
    assert.equal(await page.getByPlaceholder('粘贴需要参考的文字').inputValue(),'Unsent stale editor draft');
    assert.equal((await snapshot()).materials.find(material => material.id === peerMaterial.id)?.content,'Peer newer content');
    await page.getByRole('button',{name:'取消编辑'}).click();
    console.log('conflict checks passed; checking app reopen and automatic reconnect');
    await close();
    await launch();
    const afterRestart = await control('add_material',{title:'After Windows restart',content:'Reconnect should retain authorization'});
    await until('automatic reconnect after Windows restart',async()=> (await snapshot()).materials.some(material=>material.id===afterRestart.id),30000);
    assert.equal((await page.evaluate(()=>window.__TAURI__.core.invoke('sync_status'))).peers.length,1);
    page.once('dialog', dialog => void dialog.accept());
    await page.getByRole('button',{name:'解除配对'}).click();
    await until('both devices unpaired', async () => (await control('status')).peers.length === 0 && (await page.evaluate(() => window.__TAURI__.core.invoke('sync_status'))).peers.length === 0,30000);
    assert((await snapshot()).turns.some(turn => turn.id === peerBranchId), 'unpair removed saved Windows copy');
    assert((await control('snapshot')).turns.some(turn => turn.id === windowsTurn.id), 'unpair removed saved peer copy');
    const afterUnpair = await control('add_material',{title:'After unpair',content:'Must stay on peer'});
    await delay(4500);
    assert(!(await snapshot()).materials.some(material => material.id === afterUnpair.id), 'content synced after unpair');
    assert.equal(modelRequests,1);
    assert.deepEqual(pageErrors,[]);
    console.log('Journey data:',dataDir);
    console.log('PASS native Windows LAN sync: bilateral pairing, bidirectional material/turn sync, branch and draft preservation, material/selection conflict resolution, stale edit rejection, unpair cutoff');
  } catch (error) {
    if(page) await page.screenshot({path:path.join(dataDir,'failure.png'),fullPage:true}).catch(()=>{});
    console.error('Failed journey data directory:',dataDir);
    throw error;
  } finally {
    await close(); modelServer.closeAllConnections(); modelServer.close();
  }
})().catch(error => { console.error(error); process.exitCode=1; });
