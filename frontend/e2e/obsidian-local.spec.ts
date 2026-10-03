import { openAnswerSources } from './answer-source-helpers';
import { expect, test } from '@playwright/test';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { authorize } from './fact-helpers';

const NOTE = '# 矩阵笔记\nMATRIX 是合成笔记内容。\n';
const NESTED = '# Deep Note\n嵌套目录占位内容。\n';
const THIRD = '# 第三笔记\nTHIRD_MARKER_7955\n';
const backendUrl = `http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT ?? '8012'}`;

function buildVault() {
  const root = mkdtempSync(join(tmpdir(), 'nautilus-obsidian-vault.'));
  mkdirSync(join(root, '.obsidian'));
  mkdirSync(join(root, '子目录 空格'));
  writeFileSync(join(root, '矩阵 笔记.md'), NOTE);
  writeFileSync(join(root, '第三 笔记.md'), THIRD);
  writeFileSync(join(root, '子目录 空格', 'Deep Note.MD'), NESTED);
  writeFileSync(join(root, '.obsidian', '隐藏.md'), 'SECRET_VAULT_INTERNAL_MARKER');
  return root;
}

function tree(root: string): string[] {
  const entries: string[] = [];
  const walk = (dir: string, prefix: string) => {
    for (const name of readdirSync(dir).sort()) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) { entries.push(`${prefix}${name}/`); walk(path, `${prefix}${name}/`); }
      else entries.push(`${prefix}${name}:${readFileSync(path).toString('base64')}`);
    }
  };
  walk(root, '');
  return entries;
}

async function connectVault(page: import('@playwright/test').Page, vault: string) {
  await page.getByRole('button', { name: '设置', exact: true }).click();
  const settings = page.getByRole('dialog', { name: '设置', exact: true });
  const section = settings.getByRole('region', { name: '本地 Obsidian Vault' });
  await expect(section.getByRole('heading', { name: '知识库：本地 Obsidian Vault' })).toBeVisible();
  await expect(section.getByText('正在读取连接设置…')).toHaveCount(0);
  // A previous connection may still be stored for this isolated run; switch it to this vault.
  const change = section.getByRole('button', { name: '更改 Vault 路径' });
  if (await change.count()) await change.click();
  await section.getByLabel('Vault 路径（后端主机上的绝对路径）').fill(vault);
  const first = section.getByRole('button', { name: '连接本地 Vault' });
  if (await first.count()) await first.click();
  else await section.getByRole('button', { name: '保存新路径' }).click();
  await expect(settings.getByText(/状态已连接/)).toBeVisible();
  await settings.getByRole('button', { name: '关闭', exact: true }).click();
  await expect(settings).toHaveCount(0);
}

async function openRoom(page: import('@playwright/test').Page) {
  // A reload can restore the room directly, in which case there is no entry button.
  const entry = page.getByRole('button', { name: '学习室', exact: true });
  if (await entry.count()) await entry.click();
  await expect(page.locator('.ai-composer').getByRole('button', { name: /联网搜索/ })).toBeEnabled();
}

test('本地 Obsidian：连接、检索、显式保存快照并用于回答', async ({ page }) => {
  test.setTimeout(120_000);
  const vault = buildVault();
  const before = tree(vault);
  try {
    await authorize(page);
    const routes = await (await page.request.get(`${backendUrl}/openapi.json`)).json();
    expect(routes.paths['/api/obsidian/connection']).toBeTruthy();
    expect(routes.paths['/api/obsidian/{kind}/{scope_id}/search']).toBeTruthy();
    expect(routes.paths['/api/obsidian/{kind}/{scope_id}/capture']).toBeTruthy();
    expect((await page.request.put('/api/ai/provider', { data: {
      display_name: 'Obsidian mock provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1',
      model: 'mock-success', api_key: 'synthetic-obsidian-key', enabled: true, request_timeout_seconds: 15, api_protocol: 'openai_compatible',
    } })).ok()).toBeTruthy();
    await page.reload();
    await connectVault(page, vault);

    await openRoom(page);
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    const materialsButton = page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ });
    const panel = page.locator('.task-materials-panel');
    await materialsButton.click();
    const obsidian = panel.getByRole('region', { name: '从 Obsidian 选用' });
    await obsidian.getByRole('button', { name: '从 Obsidian 选用' }).click();
    await expect(obsidian.getByText(/当前 Vault：/)).toBeVisible();
    await expect(obsidian.getByText('检索只读取 .md 文件，不会修改 Obsidian 原文。')).toBeVisible();

    // Opening the panel and searching by hand are the only triggers; nothing scans the vault on its own.
    await expect(obsidian.getByText(/没有匹配的笔记/)).toHaveCount(0);
    await obsidian.getByLabel('检索笔记').fill('matrix');
    await obsidian.getByRole('button', { name: '检索', exact: true }).click();
    await expect(obsidian.getByText(/矩阵 笔记 · 矩阵 笔记\.md · 第 2–2 行/)).toBeVisible();
    await expect(obsidian.getByText('摘要只帮助选择文档，不代表模型实际引用过这一句。')).toBeVisible();
    await expect(obsidian.getByText(/Deep Note · 子目录 空格\/Deep Note\.MD/)).toHaveCount(0);
    await obsidian.getByLabel('检索笔记').fill('');
    await obsidian.getByRole('button', { name: '检索', exact: true }).click();
    await expect(obsidian.getByText(/Deep Note · 子目录 空格\/Deep Note\.MD/)).toBeVisible();
    await expect(obsidian.getByText(/隐藏\.md/)).toHaveCount(0);

    await obsidian.getByLabel('检索笔记').fill('matrix');
    await obsidian.getByRole('button', { name: '检索', exact: true }).click();
    const capture = page.waitForResponse(response => response.url().endsWith('/capture') && response.request().method() === 'POST');
    await obsidian.getByRole('button', { name: '保存快照并选用' }).first().click();
    const saved = await (await capture).json();
    expect(saved.provenance_json).toContain('obsidian_local');
    expect(saved.original.media_type).toBe('text/markdown');
    expect(saved.url).toBeNull();
    await expect(obsidian.getByRole('status').first()).toContainText('已保存');
    await expect(panel.getByRole('checkbox', { name: '矩阵 笔记 · 文本资料' })).toBeChecked();

    await materialsButton.click();
    const question = page.getByLabel('输入学习问题');
    await question.fill('请依据这份笔记解释 MATRIX');
    const sent = page.waitForRequest(request => request.url().endsWith('/messages') && request.method() === 'POST');
    await question.press('Enter');
    const request = await sent;
    expect(request.postDataJSON().source_scope.version_ids).toEqual([saved.id]);
    const { run } = await (await request.response())!.json();
    await expect.poll(async () => (await (await page.request.get(`/api/ai/conversations/${run.conversation_id}`)).json()).active_run).toBeNull();

    await page.reload();
    await openRoom(page);
    await materialsButton.click();
    await expect(panel.getByRole('checkbox', { name: '矩阵 笔记 · 文本资料' })).toBeChecked();
    await panel.getByText('查看当前版本和历史').click();
    const sourceReview = panel.locator('.task-material-obsidian-source');
    await expect(sourceReview).toContainText('Obsidian 保存快照');
    await expect(sourceReview).toContainText('矩阵 笔记.md');
    await expect(sourceReview).toContainText('Nautilus 第 1 版');
    await expect(sourceReview).toContainText('内容指纹');
    await expect(sourceReview).toContainText('全文（第 1–2 行）');
    expect(await sourceReview.getByRole('link', { name: '在 Obsidian 打开' }).getAttribute('href'))
      .toBe(`obsidian://open?vault=${encodeURIComponent(vault.split('/').pop()!)}&file=${encodeURIComponent('矩阵 笔记')}`);
    await sourceReview.getByRole('button', { name: '检查原文变化' }).click();
    await expect(sourceReview.getByRole('status')).toContainText('相同');
    const download = page.waitForEvent('download');
    await panel.getByRole('link', { name: '下载原件：矩阵 笔记.md' }).click();
    expect((await download).suggestedFilename()).toBe('矩阵 笔记.md');
    const answerSource = await openAnswerSources(page, page.locator('.task-material-use').first());
    await expect(answerSource).not.toContainText('Obsidian 保存快照');
    await expect(answerSource).toContainText('矩阵 笔记');
    expect(tree(vault)).toEqual(before);
  } finally {
    rmSync(vault, { recursive: true, force: true });
  }
});

test('Obsidian：跨场景复用、变化追加版本、断开后不再新读取', async ({ page }) => {
  test.setTimeout(150_000);
  const vault = buildVault();
  const note = join(vault, '矩阵 笔记.md');
  try {
    await authorize(page);
    await page.request.put('/api/ai/provider', { data: {
      display_name: 'Obsidian mock provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1',
      model: 'mock-success', api_key: 'synthetic-obsidian-key', enabled: true, request_timeout_seconds: 15, api_protocol: 'openai_compatible',
    } });
    await page.reload();
    await connectVault(page, vault);
    await openRoom(page);
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    const materialsButton = page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ });
    const panel = page.locator('.task-materials-panel');

    async function saveNote() {
      await materialsButton.click();
      const obsidian = panel.getByRole('region', { name: '从 Obsidian 选用' });
      if (await obsidian.getByRole('button', { name: '从 Obsidian 选用' }).getAttribute('aria-expanded') === 'false') {
        await obsidian.getByRole('button', { name: '从 Obsidian 选用' }).click();
      }
      await obsidian.getByLabel('检索笔记').fill('matrix');
      await obsidian.getByRole('button', { name: '检索', exact: true }).click();
      const capture = page.waitForResponse(response => response.url().endsWith('/capture') && response.request().method() === 'POST');
      await obsidian.getByRole('button', { name: '保存快照并选用' }).first().click();
      const saved = await (await capture).json();
      await materialsButton.click();
      return saved;
    }

    const first = await saveNote();
    const connectionId = (await (await page.request.get('/api/obsidian/connection')).json()).connection.connection_id;
    const question = page.getByLabel('输入学习问题');
    await question.fill('请依据这份笔记解释 MATRIX');
    const sent = page.waitForRequest(request => request.url().endsWith('/messages') && request.method() === 'POST');
    await question.press('Enter');
    const request = await sent;
    const { run } = await (await request.response())!.json();
    await expect.poll(async () => (await (await page.request.get(`/api/ai/conversations/${run.conversation_id}`)).json()).active_run).toBeNull();

    // The second learning scope reuses the identical source version; no duplicate material is created.
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    const second = await saveNote();
    expect(second.id).toBe(first.id);
    expect(second.material_id).toBe(first.material_id);
    const library = await (await page.request.get('/api/materials/library')).json();
    expect(library.versions.filter((item: { material_id: string }) => item.material_id === first.material_id).length).toBe(1);

    // Changing the note appends version 2 without rewriting the earlier answer's basis.
    writeFileSync(note, '# 矩阵笔记\nMATRIX 已改写为合成第二版。\n');
    const third = await saveNote();
    expect(third.material_id).toBe(first.material_id);
    expect(third.version).toBe(2);
    const history = await (await page.request.get(`/api/ai/conversations/${run.conversation_id}`)).json();
    const earlier = history.messages.find((item: { ai_run_id: string; role: string }) => item.ai_run_id === run.id && item.role === 'assistant');
    expect(earlier.source_scope.version_ids).toEqual([first.id]);
    expect((await page.request.get(`/api/materials/conversation/${run.conversation_id}/versions/${first.id}/original`)).ok()).toBeTruthy();

    await materialsButton.click();
    await panel.getByText('查看当前版本和历史').click();
    await expect(panel.getByText('第 2 版 · 矩阵 笔记')).toBeVisible();
    const versionNote = (number: number) => panel.locator('.task-material-list details > div').filter({ hasText: `第 ${number} 版 · 矩阵 笔记` });
    await versionNote(2).locator('.task-material-obsidian-source').getByRole('button', { name: '检查原文变化' }).click();
    await expect(versionNote(2).locator('.task-material-obsidian-source').getByRole('status')).toContainText('相同');
    await versionNote(1).locator('.task-material-obsidian-source').getByRole('button', { name: '检查原文变化' }).click();
    await expect(versionNote(1).locator('.task-material-obsidian-source').getByRole('status')).toContainText('已变化');
    await materialsButton.click();

    // Disconnecting stops new reads but keeps the saved snapshot readable.
    await page.getByRole('button', { name: '设置', exact: true }).click();
    const settings = page.getByRole('dialog', { name: '设置', exact: true });
    await settings.getByRole('button', { name: '断开连接' }).click();
    await expect(settings.getByText(/状态已断开/)).toBeVisible();
    await settings.getByRole('button', { name: '关闭', exact: true }).click();
    await materialsButton.click();
    const afterDisconnect = panel.getByRole('region', { name: '从 Obsidian 选用' });
    const entry = afterDisconnect.getByRole('button', { name: '从 Obsidian 选用' });
    if (await entry.getAttribute('aria-expanded') === 'false') await entry.click();
    await expect(panel.getByText(/Obsidian 连接已断开/)).toBeVisible();
    await expect(panel.getByRole('button', { name: '保存快照并选用' })).toHaveCount(0);
    await panel.getByText('查看当前版本和历史').click();
    await expect(panel.locator('.task-material-obsidian-source').first()).toContainText('矩阵 笔记.md');
    await panel.locator('.task-material-obsidian-source').first().getByRole('button', { name: '检查原文变化' }).click();
    await expect(panel.locator('.task-material-obsidian-source').first().getByRole('status')).toContainText('连接已断开');
    await materialsButton.click();

    // Reconnecting the same path keeps the connection id, so earlier snapshots stay attached.
    await page.getByRole('button', { name: '设置', exact: true }).click();
    await settings.getByRole('button', { name: '重新连接' }).click();
    await expect(settings.getByText(/状态已连接/)).toBeVisible();
    await settings.getByRole('button', { name: '关闭', exact: true }).click();
    const reconnected = await (await page.request.get('/api/obsidian/connection')).json();
    expect(reconnected.connection.connection_id).toBe(connectionId);
    expect(reconnected.connection.enabled).toBe(true);

    // Switching conversations drops in-flight search results instead of showing them in another scope.
    await materialsButton.click();
    const obsidian = panel.getByRole('region', { name: '从 Obsidian 选用' });
    await page.route('**/api/obsidian/conversation/*/search', async route => {
      await new Promise(resolve => setTimeout(resolve, 1200));
      await route.continue();
    });
    await obsidian.getByRole('button', { name: '从 Obsidian 选用' }).click();
    await obsidian.getByLabel('检索笔记').fill('matrix');
    await obsidian.getByRole('button', { name: '检索', exact: true }).click();
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    await page.waitForTimeout(1600);
    await materialsButton.click();
    const reopened = panel.getByRole('region', { name: '从 Obsidian 选用' });
    await reopened.getByRole('button', { name: '从 Obsidian 选用' }).click();
    await expect(reopened.getByRole('button', { name: '保存快照并选用' })).toHaveCount(0);
    await page.unroute('**/api/obsidian/conversation/*/search');
  } finally {
    rmSync(vault, { recursive: true, force: true });
  }
});

test('Obsidian：题目讨论同一入口选用，清除不动外部 Vault', async ({ page }) => {
  test.setTimeout(180_000);
  const vault = buildVault();
  const before = tree(vault);
  try {
    await authorize(page);
    await page.request.put('/api/ai/provider', { data: {
      display_name: 'Obsidian discussion provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1',
      model: 'mock-review', api_key: 'synthetic-obsidian-key', enabled: true, request_timeout_seconds: 15,
    } });
    await page.reload();
    await connectVault(page, vault);
    const start = page.getByRole('button', { name: '学习首页', exact: true }).first();
    await expect(start).toBeVisible();
    await start.click();
    if (await (await page.request.get('/api/learning/return-review')).json()) await page.getByRole('button', { name: '创建', exact: true }).click();
    await page.getByLabel('学习目标', { exact: true }).fill('合成目标：Obsidian 讨论选用');
    await page.getByRole('button', { name: '我想自己安排' }).click();
    await page.getByLabel('现在先做什么', { exact: true }).fill('合成 Obsidian 讨论旅程');
    await page.getByRole('button', { name: '确认这份学习安排' }).click();
    await page.getByRole('button', { name: '进入学习室并开始这项任务' }).click();
    await expect(page.locator('.ai-message--assistant').first()).toBeVisible();
    await page.getByRole('button', { name: '进入验证', exact: true }).click();
    await page.getByRole('button', { name: '开始验证', exact: true }).click();
    await page.getByPlaceholder('写出你的判断、过程或结果').first().fill('合成原作答：先定位，再检查边界。');
    await page.getByPlaceholder('写出你的判断、过程或结果').nth(1).fill('合成第二题作答：检查空输入。');
    await page.getByRole('button', { name: '保存作答并验证' }).click();
    const review = page.getByRole('region', { name: '验证回看' });
    const firstQuestion = review.getByRole('article', { name: '第 1 题回看' });
    await expect(firstQuestion.getByText('合成原作答：先定位，再检查边界。', { exact: true })).toBeVisible();
    await firstQuestion.getByRole('button', { name: '讨论这道题' }).click();
    const discussion = page.getByRole('region', { name: '题目学习室' });
    await expect(discussion).toBeVisible();
    const materialsButton = discussion.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ });
    await materialsButton.click();
    const panel = discussion.locator('.task-materials-panel');
    const obsidian = panel.getByRole('region', { name: '从 Obsidian 选用' });
    await obsidian.getByRole('button', { name: '从 Obsidian 选用' }).click();
    await obsidian.getByLabel('检索笔记').fill('matrix');
    await obsidian.getByRole('button', { name: '检索', exact: true }).click();
    await expect(obsidian.getByText(/矩阵 笔记 · 矩阵 笔记\.md/)).toBeVisible();
    const capture = page.waitForResponse(response => response.url().includes('/api/obsidian/discussion/') && response.url().endsWith('/capture'));
    await obsidian.getByRole('button', { name: '保存快照并选用' }).first().click();
    const saved = await (await capture).json();
    await expect(panel.getByRole('checkbox', { name: '矩阵 笔记 · 文本资料' })).toBeChecked();

    let purgeRequests = 0;
    page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith(`/${saved.material_id}/purge`)) purgeRequests++; });
    await panel.getByRole('button', { name: '清除', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '清除这份资料？' });
    await expect(dialog).toContainText('不会删除 Obsidian 原文或其云端备份');
    await dialog.getByRole('button', { name: '取消' }).click();
    await expect(dialog).toHaveCount(0);
    expect(purgeRequests).toBe(0);
    await expect(panel.getByRole('checkbox', { name: '矩阵 笔记 · 文本资料' })).toBeChecked();
    await panel.getByRole('button', { name: '清除', exact: true }).click();
    await dialog.getByRole('button', { name: '确认清除' }).click();
    await expect(panel.locator('.task-material-purge-notice')).toContainText('资料及关联内容已清除');
    expect(purgeRequests).toBe(1);
    const listed = await (await page.request.get(`/api/materials/discussion/${new URL(page.url()).searchParams.get('discussion')}`)).json();
    expect(listed.versions.every((item: { purged_at: string | null }) => !!item.purged_at)).toBeTruthy();
    expect(tree(vault)).toEqual(before);
  } finally {
    rmSync(vault, { recursive: true, force: true });
  }
});


function buildBrokenVault() {
  const root = mkdtempSync(join(tmpdir(), 'nautilus-obsidian-broken.'));
  for (let index = 0; index < 50; index += 1) {
    writeFileSync(join(root, `broken-${String(index).padStart(2, '0')}.md`), Buffer.from([0xff, 0xfe, 0x00, 0x62]));
  }
  writeFileSync(join(root, 'zz-good.md'), '# 正常笔记\nGOOD_NOTE_4113\n');
  return root;
}

test('Obsidian：选用结果只在当前态确认后显示', async ({ page }) => {
  test.setTimeout(180_000);
  const vault = buildVault();
  try {
    await authorize(page);
    await page.request.put('/api/ai/provider', { data: {
      display_name: 'Obsidian mock provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1',
      model: 'mock-success', api_key: 'synthetic-obsidian-key', enabled: true, request_timeout_seconds: 15, api_protocol: 'openai_compatible',
    } });
    await page.reload();
    await connectVault(page, vault);
    await openRoom(page);
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    const materialsButton = page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ });
    const panel = page.locator('.task-materials-panel');

    async function openPanel() {
      if (await panel.count() === 0) await materialsButton.click();
      await expect(panel).toBeVisible();
    }
    async function capture(query: string, outcome: 'applied' | 'conflict' | 'busy' = 'applied') {
      await openPanel();
      const obsidian = panel.getByRole('region', { name: '从 Obsidian 选用' });
      if (await obsidian.getByRole('button', { name: '从 Obsidian 选用' }).getAttribute('aria-expanded') === 'false') {
        await obsidian.getByRole('button', { name: '从 Obsidian 选用' }).click();
      }
      await obsidian.getByLabel('检索笔记').fill(query);
      await obsidian.getByRole('button', { name: '检索', exact: true }).click();
      const statePut = outcome === 'busy' ? null
        : page.waitForResponse(response => response.url().includes('/api/conversation-state/')
          && response.request().method() === 'PUT');
      const captured = page.waitForResponse(response => response.url().endsWith('/capture') && response.request().method() === 'POST');
      await obsidian.getByRole('button', { name: '保存快照并选用' }).first().click();
      const response = await captured;
      const version = await response.json();
      const conversationId = new URL(response.url()).pathname.split('/')[4];
      if (statePut) {
        // The success notice may only follow a confirmed write; the conflict case is a 409.
        expect((await statePut).status()).toBe(outcome === 'conflict' ? 409 : 200);
      }
      return { version, conversationId };
    }

    const first = await capture('matrix');
    await expect(panel.getByRole('status').first()).toContainText('已保存');
    await expect(panel.getByRole('checkbox', { name: '矩阵 笔记 · 文本资料' })).toBeChecked();
    await page.reload();
    await openRoom(page);
    await materialsButton.click();
    await expect(panel.getByRole('checkbox', { name: '矩阵 笔记 · 文本资料' })).toBeChecked();

    // Another page moves the current state on; this page's stale revision must lose.
    const stateUrl = `/api/conversation-state/conversation/${first.conversationId}`;
    const current = await (await page.request.get(stateUrl)).json();
    expect(current.source_scope.version_ids).toEqual([first.version.id]);
    const moved = await page.request.put(stateUrl, { data: { ...current, expected_revision: current.revision,
      source_scope: { ...current.source_scope, conflict_policy: 'balanced' } } });
    expect(moved.ok()).toBeTruthy();
    const second = await capture('Deep', 'conflict');
    await expect(panel.getByRole('alert')).toContainText('快照已保存，但当前选择未确认');
    await expect(panel.getByText(/已保存「/)).toHaveCount(0);
    const stored = await (await page.request.get(stateUrl)).json();
    expect(stored.source_scope.conflict_policy).toBe('balanced');
    expect(stored.source_scope.version_ids).toEqual([first.version.id]);
    const listed = await (await page.request.get('/api/materials/library')).json();
    expect(listed.versions.some((item: { id: string }) => item.id === second.version.id)).toBeTruthy();

    // A current-state save that is already in flight when the capture lands keeps the
    // apply unconfirmed (save() reports false without sending anything) instead of
    // silently pretending the selection was applied.
    let putCount = 0;
    page.on('request', request => { if (request.method() === 'PUT' && request.url().includes('/api/conversation-state/')) putCount++; });
    await page.route('**/capture', async route => { await new Promise(resolve => setTimeout(resolve, 600)); await route.continue(); });
    await page.route('**/api/conversation-state/**', async route => {
      if (route.request().method() === 'PUT') await new Promise(resolve => setTimeout(resolve, 5000));
      await route.continue();
    });
    await openPanel();
    const thirdObsidian = panel.getByRole('region', { name: '从 Obsidian 选用' });
    if (await thirdObsidian.getByRole('button', { name: '从 Obsidian 选用' }).getAttribute('aria-expanded') === 'false') {
      await thirdObsidian.getByRole('button', { name: '从 Obsidian 选用' }).click();
    }
    await thirdObsidian.getByLabel('检索笔记').fill('第三');
    await thirdObsidian.getByRole('button', { name: '检索', exact: true }).click();
    const thirdCapture = page.waitForResponse(response => response.url().endsWith('/capture') && response.request().method() === 'POST');
    await thirdObsidian.getByRole('button', { name: '保存快照并选用' }).first().click();
    await panel.getByLabel('资料冲突时').selectOption('ask');   // occupies the save slot while capture is in flight
    const thirdVersion = await (await thirdCapture).json();
    await expect(panel.getByRole('alert')).toContainText('快照已保存，但当前选择未确认');
    await expect(panel.getByText(new RegExp(`并选用第 ${thirdVersion.version} 版`))).toHaveCount(0);
    expect(putCount).toBe(1);                                   // the apply never sent its own write
    await page.unroute('**/capture');
    await page.unroute('**/api/conversation-state/**');
  } finally {
    rmSync(vault, { recursive: true, force: true });
  }
});

test('Obsidian：切换对话后迟到的捕获不发起新的选用', async ({ page }) => {
  test.setTimeout(120_000);
  const vault = buildVault();
  try {
    await authorize(page);
    await page.request.put('/api/ai/provider', { data: {
      display_name: 'Obsidian mock provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1',
      model: 'mock-success', api_key: 'synthetic-obsidian-key', enabled: true, request_timeout_seconds: 15, api_protocol: 'openai_compatible',
    } });
    await page.reload();
    await connectVault(page, vault);
    await openRoom(page);
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    const materialsButton = page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ });
    const panel = page.locator('.task-materials-panel');
    await materialsButton.click();
    const obsidian = panel.getByRole('region', { name: '从 Obsidian 选用' });
    await obsidian.getByRole('button', { name: '从 Obsidian 选用' }).click();
    await obsidian.getByLabel('检索笔记').fill('matrix');
    await obsidian.getByRole('button', { name: '检索', exact: true }).click();
    await expect(obsidian.getByText(/矩阵 笔记 · 矩阵 笔记\.md/)).toBeVisible();
    const statePuts: string[] = [];
    page.on('request', request => { if (request.method() === 'PUT' && request.url().includes('/api/conversation-state/')) statePuts.push(request.url()); });
    await page.route('**/capture', async route => { await new Promise(resolve => setTimeout(resolve, 1200)); await route.continue(); });
    const captured = page.waitForResponse(response => response.url().endsWith('/capture') && response.request().method() === 'POST');
    await obsidian.getByRole('button', { name: '保存快照并选用' }).first().click();
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    const snapshot = await (await captured).json();
    await page.waitForTimeout(1600);
    expect(statePuts).toEqual([]);        // the late capture must not write any current state
    await expect(page.getByText(/已保存「/)).toHaveCount(0);
    await expect(page.getByText('快照已保存，但当前选择未确认')).toHaveCount(0);
    const listed = await (await page.request.get('/api/materials/library')).json();
    expect(listed.versions.some((item: { id: string }) => item.id === snapshot.id)).toBeTruthy();
    await page.unroute('**/capture');
  } finally {
    rmSync(vault, { recursive: true, force: true });
  }
});

test('Obsidian：全部不可读的第一页仍能翻到正常笔记', async ({ page }) => {
  test.setTimeout(120_000);
  const vault = buildBrokenVault();
  try {
    await authorize(page);
    await page.reload();
    await connectVault(page, vault);
    await openRoom(page);
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    const materialsButton = page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ });
    const panel = page.locator('.task-materials-panel');
    await materialsButton.click();
    const obsidian = panel.getByRole('region', { name: '从 Obsidian 选用' });
    await obsidian.getByRole('button', { name: '从 Obsidian 选用' }).click();
    await obsidian.getByRole('button', { name: '检索', exact: true }).click();
    await expect(obsidian.getByText(/有 50 个文件或目录未能读取/)).toBeVisible();
    await expect(obsidian.getByRole('button', { name: '下一页' })).toBeVisible();
    await obsidian.getByRole('button', { name: '下一页' }).click();
    await expect(obsidian.getByText(/zz-good · zz-good\.md/)).toBeVisible();
    await expect(obsidian.getByRole('button', { name: '下一页' })).toHaveCount(0);
  } finally {
    rmSync(vault, { recursive: true, force: true });
  }
});


test('Obsidian：关闭内层入口后迟到的捕获不再发起选用', async ({ page }) => {
  test.setTimeout(180_000);
  const vault = buildVault();
  try {
    await authorize(page);
    await page.request.put('/api/ai/provider', { data: {
      display_name: 'Obsidian mock provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1',
      model: 'mock-success', api_key: 'synthetic-obsidian-key', enabled: true, request_timeout_seconds: 15, api_protocol: 'openai_compatible',
    } });
    await page.reload();
    await connectVault(page, vault);
    await openRoom(page);
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    const materialsButton = page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ });
    const panel = page.locator('.task-materials-panel');
    await materialsButton.click();
    const obsidian = panel.getByRole('region', { name: '从 Obsidian 选用' });
    await obsidian.getByRole('button', { name: '从 Obsidian 选用' }).click();
    await obsidian.getByLabel('检索笔记').fill('matrix');
    await obsidian.getByRole('button', { name: '检索', exact: true }).click();

    const statePuts: string[] = [];
    page.on('request', request => { if (request.method() === 'PUT' && request.url().includes('/api/conversation-state/')) statePuts.push(request.url()); });
    let releaseCapture!: () => void;
    const captureGate = new Promise<void>(resolve => { releaseCapture = resolve; });
    let captureEntered!: () => void;
    const captureStarted = new Promise<void>(resolve => { captureEntered = resolve; });
    await page.route('**/capture', async route => { captureEntered(); await captureGate; await route.continue(); });

    const captured = page.waitForResponse(response => response.url().endsWith('/capture') && response.request().method() === 'POST');
    await obsidian.getByRole('button', { name: '保存快照并选用' }).first().click();
    await captureStarted;                                   // the capture is still unanswered
    await obsidian.getByRole('button', { name: '从 Obsidian 选用' }).click();  // collapse the inner entry
    releaseCapture();
    const snapshot = await (await captured).json();
    // Drain deterministically: a new search response can only arrive after any
    // continuation of the released capture has already run.
    const drain = page.waitForResponse(response => /\/search$/.test(response.url()) && response.request().method() === 'POST');
    await obsidian.getByRole('button', { name: '从 Obsidian 选用' }).click();
    await obsidian.getByLabel('检索笔记').fill('matrix');
    await obsidian.getByRole('button', { name: '检索', exact: true }).click();
    await drain;
    expect(statePuts).toEqual([]);
    await expect(panel.getByText(/已保存「/)).toHaveCount(0);
    await expect(panel.getByText(/当前选择未确认/)).toHaveCount(0);
    const listed = await (await page.request.get('/api/materials/library')).json();
    expect(listed.versions.some((item: { id: string }) => item.id === snapshot.id)).toBeTruthy();

    // Reopening must not revive the closed operation, and an explicit new capture still applies.
    await page.unroute('**/capture');
    const statePut = page.waitForResponse(response => response.url().includes('/api/conversation-state/')
      && response.request().method() === 'PUT' && response.status() === 200);
    const again = page.waitForResponse(response => response.url().endsWith('/capture') && response.request().method() === 'POST');
    await obsidian.getByRole('button', { name: '保存快照并选用' }).first().click();
    const reused = await (await again).json();
    await statePut;
    await expect(panel.getByRole('status').first()).toContainText('已保存');
    expect(reused.id).toBe(snapshot.id);
    expect(statePuts.length).toBe(1);
  } finally {
    rmSync(vault, { recursive: true, force: true });
  }
});

test('Obsidian：外层面板关闭后等待中的刷新不再发起选用', async ({ page }) => {
  test.setTimeout(180_000);
  const vault = buildVault();
  try {
    await authorize(page);
    await page.request.put('/api/ai/provider', { data: {
      display_name: 'Obsidian mock provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1',
      model: 'mock-success', api_key: 'synthetic-obsidian-key', enabled: true, request_timeout_seconds: 15, api_protocol: 'openai_compatible',
    } });
    await page.reload();
    await connectVault(page, vault);
    await openRoom(page);
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    const materialsButton = page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ });
    const panel = page.locator('.task-materials-panel');
    await materialsButton.click();
    const obsidian = panel.getByRole('region', { name: '从 Obsidian 选用' });
    await obsidian.getByRole('button', { name: '从 Obsidian 选用' }).click();
    await obsidian.getByLabel('检索笔记').fill('matrix');
    await obsidian.getByRole('button', { name: '检索', exact: true }).click();

    const statePuts: string[] = [];
    page.on('request', request => { if (request.method() === 'PUT' && request.url().includes('/api/conversation-state/')) statePuts.push(request.url()); });
    let holdNextList = false;
    let releaseRefresh!: () => void;
    const refreshGate = new Promise<void>(resolve => { releaseRefresh = resolve; });
    let refreshEntered!: () => void;
    const refreshStarted = new Promise<void>(resolve => { refreshEntered = resolve; });
    await page.route('**/api/materials/conversation/**', async route => {
      if (!holdNextList || route.request().method() !== 'GET') return route.continue();
      holdNextList = false;
      refreshEntered();
      await refreshGate;
      return route.continue();
    });

    const captured = page.waitForResponse(response => response.url().endsWith('/capture') && response.request().method() === 'POST');
    holdNextList = true;
    await obsidian.getByRole('button', { name: '保存快照并选用' }).first().click();
    const snapshot = await (await captured).json();
    await refreshStarted;                                  // the parent is inside useCaptured, awaiting the list
    await materialsButton.click();                         // close the outer materials panel
    releaseRefresh();
    // Drain deterministically: reopening the panel issues the next list request, which
    // cannot be observed before the released continuation has run.
    const drain = page.waitForResponse(response => /\/api\/materials\/conversation\//.test(response.url())
      && response.request().method() === 'GET');
    await materialsButton.click();
    await drain;
    expect(statePuts).toEqual([]);
    await expect(page.getByText(/已保存「/)).toHaveCount(0);
    await expect(page.getByText(/当前选择未确认/)).toHaveCount(0);
    const listed = await (await page.request.get('/api/materials/library')).json();
    expect(listed.versions.some((item: { id: string }) => item.id === snapshot.id)).toBeTruthy();
    expect(await (await page.request.get('/api/conversation-state/conversation/'
      + new URL((await captured).url()).pathname.split('/')[4])).json()).toMatchObject({ initialized: true });
  } finally {
    rmSync(vault, { recursive: true, force: true });
  }
});

test('Obsidian：编辑查询后重新检索不沿用旧分页游标', async ({ page }) => {
  test.setTimeout(120_000);
  const vault = mkdtempSync(join(tmpdir(), 'nautilus-obsidian-query.'));
  writeFileSync(join(vault, '00-target.md'), '# 查询起点\nQUERY_BEFORE_OLD_CURSOR_3117\n');
  for (let index = 1; index <= 50; index += 1) {
    writeFileSync(join(vault, `${String(index).padStart(2, '0')}-filler.md`), '# 合成占位笔记\n');
  }
  try {
    await authorize(page);
    await page.request.put('/api/ai/provider', { data: {
      display_name: 'Obsidian mock provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1',
      model: 'mock-success', api_key: 'synthetic-obsidian-key', enabled: true, request_timeout_seconds: 15, api_protocol: 'openai_compatible',
    } });
    await page.reload();
    await connectVault(page, vault);
    await openRoom(page);
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    await page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ }).click();
    const obsidian = page.locator('.task-materials-panel').getByRole('region', { name: '从 Obsidian 选用' });
    await obsidian.getByRole('button', { name: '从 Obsidian 选用' }).click();
    const requests: { query: string; after?: string | null }[] = [];
    page.on('request', request => {
      if (request.method() === 'POST' && /\/api\/obsidian\/conversation\/[^/]+\/search$/.test(request.url())) {
        requests.push(request.postDataJSON());
      }
    });
    await obsidian.getByRole('button', { name: '检索', exact: true }).click();
    await expect(obsidian.getByRole('button', { name: '下一页' })).toBeVisible();
    await expect(obsidian.getByRole('button', { name: '保存快照并选用' })).toHaveCount(50);

    // This match sorts before the old cursor and would be skipped by a mixed request.
    await obsidian.getByLabel('检索笔记').fill('QUERY_BEFORE_OLD_CURSOR_3117');
    await expect(obsidian.getByRole('button', { name: '下一页' })).toHaveCount(0);
    await expect(obsidian.getByRole('button', { name: '保存快照并选用' })).toHaveCount(0);
    await obsidian.getByLabel('检索笔记').press('Enter');
    await expect(obsidian.getByText(/00-target · 00-target\.md/)).toBeVisible();
    await expect(obsidian.getByRole('button', { name: '保存快照并选用' })).toHaveCount(1);
    expect(requests).toHaveLength(2);
    expect(requests[1].query).toBe('QUERY_BEFORE_OLD_CURSOR_3117');
    expect(requests[1].after ?? null).toBeNull();
  } finally {
    rmSync(vault, { recursive: true, force: true });
  }
});

test('Obsidian：连接读取与检索互斥，关闭前的连接响应不能覆盖重开状态', async ({ page }) => {
  test.setTimeout(120_000);
  const vault = buildVault();
  let releaseSearch = () => {};
  let releaseConnection = () => {};
  try {
    await authorize(page);
    await page.request.put('/api/ai/provider', { data: {
      display_name: 'Obsidian mock provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1',
      model: 'mock-success', api_key: 'synthetic-obsidian-key', enabled: true, request_timeout_seconds: 15, api_protocol: 'openai_compatible',
    } });
    await page.reload();
    await connectVault(page, vault);
    const { connection } = await (await page.request.get('/api/obsidian/connection')).json();
    await openRoom(page);
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    await page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ }).click();
    const obsidian = page.locator('.task-materials-panel').getByRole('region', { name: '从 Obsidian 选用' });
    const entry = obsidian.getByRole('button', { name: '从 Obsidian 选用' });
    await entry.click();
    await expect(obsidian.getByRole('button', { name: '检索', exact: true })).toBeEnabled();

    let searchEntered!: () => void;
    const searchStarted = new Promise<void>(resolve => { searchEntered = resolve; });
    const searchGate = new Promise<void>(resolve => { releaseSearch = resolve; });
    await page.route('**/api/obsidian/conversation/*/search', async route => {
      searchEntered(); await searchGate; await route.continue();
    });
    let connectionRequests = 0;
    let searchRequests = 0;
    page.on('request', request => {
      if (request.method() === 'GET' && request.url().endsWith('/api/obsidian/connection')) connectionRequests++;
      if (request.method() === 'POST' && /\/api\/obsidian\/conversation\/[^/]+\/search$/.test(request.url())) searchRequests++;
    });
    await obsidian.getByLabel('检索笔记').fill('matrix');
    await obsidian.getByRole('button', { name: '检索', exact: true }).click();
    await searchStarted;
    const reload = obsidian.getByRole('button', { name: '重新读取连接状态' });
    await expect(reload).toBeDisabled();
    await reload.evaluate(button => (button as HTMLButtonElement).click());
    expect(connectionRequests).toBe(0);
    releaseSearch();
    await expect(obsidian.getByText(/矩阵 笔记 · 矩阵 笔记\.md/)).toBeVisible();
    await expect(obsidian.getByRole('button', { name: '检索', exact: true })).toBeEnabled();
    await expect(obsidian.getByLabel('检索笔记')).toBeEnabled();
    await expect(reload).toBeEnabled();
    await page.unroute('**/api/obsidian/conversation/*/search');

    let connectionEntered!: () => void;
    const connectionStarted = new Promise<void>(resolve => { connectionEntered = resolve; });
    const connectionGate = new Promise<void>(resolve => { releaseConnection = resolve; });
    let holdFirstConnection = true;
    await page.route('**/api/obsidian/connection', async route => {
      if (!holdFirstConnection) return route.continue();
      holdFirstConnection = false;
      connectionEntered(); await connectionGate;
      // An older disconnected view must not replace the next open's connected view.
      await route.fulfill({ json: { connection: { ...connection, enabled: false } } });
    });
    await reload.click();
    await connectionStarted;
    await expect(obsidian.getByRole('button', { name: '检索', exact: true })).toBeDisabled();
    await expect(obsidian.getByLabel('检索笔记')).toBeDisabled();
    await expect(obsidian.getByRole('button', { name: '保存快照并选用' })).toHaveCount(0);
    await obsidian.getByRole('button', { name: '检索', exact: true }).evaluate(button => (button as HTMLButtonElement).click());
    expect(searchRequests).toBe(1);
    await entry.click();
    await entry.click();
    await expect(reload).toBeEnabled();
    const oldResponse = page.waitForResponse(response => response.url().endsWith('/api/obsidian/connection'));
    releaseConnection();
    await (await oldResponse).finished();
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
    await expect(obsidian.getByText(/Obsidian 连接已断开/)).toHaveCount(0);
    await expect(obsidian.getByRole('button', { name: '检索', exact: true })).toBeEnabled();
    await obsidian.getByRole('button', { name: '检索', exact: true }).click();
    await expect(obsidian.getByText(/矩阵 笔记 · 矩阵 笔记\.md/)).toBeVisible();
    expect(searchRequests).toBe(2);
    await page.unroute('**/api/obsidian/connection');
  } finally {
    releaseSearch(); releaseConnection();
    rmSync(vault, { recursive: true, force: true });
  }
});

test('Obsidian：另一对话仅从资料库清除时仍说明原文边界，包括手工新版', async ({ page }) => {
  test.setTimeout(120_000);
  const vault = buildVault();
  writeFileSync(join(vault, '独立快照清除说明.md'), '# 独立清除说明\nLIBRARY_PURGE_WARNING_3187\n');
  const before = tree(vault);
  try {
    await authorize(page);
    await page.request.put('/api/ai/provider', { data: {
      display_name: 'Obsidian mock provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1',
      model: 'mock-success', api_key: 'synthetic-obsidian-key', enabled: true, request_timeout_seconds: 15, api_protocol: 'openai_compatible',
    } });
    await page.reload();
    await connectVault(page, vault);
    await openRoom(page);
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    const materialsButton = page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ });
    const panel = page.locator('.task-materials-panel');
    await materialsButton.click();
    const obsidian = panel.getByRole('region', { name: '从 Obsidian 选用' });
    await obsidian.getByRole('button', { name: '从 Obsidian 选用' }).click();
    await obsidian.getByLabel('检索笔记').fill('LIBRARY_PURGE_WARNING_3187');
    await obsidian.getByRole('button', { name: '检索', exact: true }).click();
    const captured = page.waitForResponse(response => response.url().endsWith('/capture') && response.request().method() === 'POST');
    await obsidian.getByRole('button', { name: '保存快照并选用' }).click();
    const response = await captured;
    const saved = await response.json();
    const sourceId = new URL(response.url()).pathname.split('/')[4];
    await expect(obsidian.getByRole('status')).toContainText('已保存');
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
    await materialsButton.click();
    await expect(panel.locator('.task-material-list > li')).toHaveCount(0);
    const libraryButton = panel.getByRole('button', { name: '从资料库选用' });
    await libraryButton.click();
    const dialog = page.getByRole('dialog', { name: '清除这份资料？' });
    let purgeRequests = 0;
    page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith(`/${saved.material_id}/purge`)) purgeRequests++; });

    async function checkLibraryWarning(title: string, versionCount: number) {
      const row = panel.locator('.task-material-library-list > li').filter({ has: page.getByText(title, { exact: true }) });
      await expect(row).toContainText(`${versionCount} 个版本`);
      await row.getByText('更多操作', { exact: true }).click();
      await row.getByRole('button', { name: '彻底清除资料' }).click();
      await expect(dialog).toContainText('不会删除 Obsidian 原文或其云端备份');
      await dialog.getByRole('button', { name: '取消' }).click();
      await expect(dialog).toHaveCount(0);
      await expect(panel.locator('.task-material-list > li')).toHaveCount(0);
    }
    await checkLibraryWarning('独立快照清除说明', 1);
    const editedResponse = await page.request.post(`/api/materials/conversation/${sourceId}`, { data: {
      material_id: saved.material_id, title: '手工编辑后的独立快照', content: '合成手工新版，保留原快照历史。',
    } });
    expect(editedResponse.ok()).toBeTruthy();
    const edited = await editedResponse.json();
    expect(edited.version).toBe(2);
    expect(edited.provenance_json ?? '').not.toContain('obsidian_local');
    await libraryButton.click();
    await libraryButton.click();
    await checkLibraryWarning('手工编辑后的独立快照', 2);
    expect(purgeRequests).toBe(0);
    expect(tree(vault)).toEqual(before);
  } finally {
    rmSync(vault, { recursive: true, force: true });
  }
});
