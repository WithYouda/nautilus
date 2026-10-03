import { expect, test, type Locator, type Page } from '@playwright/test';
import { authorize } from './fact-helpers';
import type { AiConversationDetail, AiProvider, AiRun } from '../src/api';

async function setup(page: Page, model = 'mock-success') {
  await authorize(page);
  const response = await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic record provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model, api_key: 'synthetic-record-key', enabled: true, request_timeout_seconds: 15,
  } });
  expect(response.ok()).toBeTruthy();
  const { provider } = await response.json() as { provider: AiProvider };
  const preferences = await (await page.request.get('/api/preferences')).json();
  expect((await page.request.put('/api/preferences', { data: { ...preferences, teaching_mode: 'stepwise', search: { mode: 'off' } } })).ok()).toBeTruthy();
  await page.reload();
  return provider;
}

async function expand(locator: Locator) {
  if (!(await locator.evaluate(element => (element as HTMLDetailsElement).open))) await locator.locator('summary').first().click();
}

async function settings(page: Page) {
  await page.getByRole('button', { name: '设置', exact: true }).click();
  const dialog = page.locator('.unified-settings-dialog');
  const record = dialog.locator('.teaching-record-settings');
  await expect(record).toBeVisible();
  await expand(record);
  await expect(record.getByLabel('检查模型', { exact: true })).toBeVisible();
  return { dialog, record };
}

async function check(page: Page, record: Locator) {
  const completed = page.waitForResponse(response => response.url().endsWith('/teaching-support/check') && response.request().method() === 'POST');
  await record.getByRole('button', { name: '检查支持', exact: true }).click();
  const response = await completed;
  expect(response.ok()).toBeTruthy();
  await expect(record.getByRole('button', { name: '检查支持', exact: true })).toBeEnabled();
  return response.json();
}

async function read(page: Page, id: string): Promise<AiConversationDetail> {
  return (await page.request.get(`/api/ai/conversations/${id}`)).json();
}

async function send(page: Page, content: string): Promise<AiRun> {
  const accepted = page.waitForResponse(response => /\/api\/ai\/conversations\/[^/]+\/messages$/.test(response.url()) && response.request().method() === 'POST');
  const input = page.getByLabel('输入学习问题', { exact: true });
  await input.fill(content); await input.press('Enter');
  const response = await accepted;
  expect(response.ok()).toBeTruthy();
  const { run } = await response.json();
  await expect.poll(async () => (await read(page, run.conversation_id)).active_run, { timeout: 15_000 }).toBeNull();
  await expect(page.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  return run;
}

async function newRoom(page: Page) {
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
}

test('unchecked chat, explicit support checks, decoded streaming and configuration invalidation on 390px', async ({ page }) => {
  test.setTimeout(90_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const provider = await setup(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await newRoom(page);
  const run = await send(page, '[C2学习] 先讨论输入边界。');
  const id = run.conversation_id;
  expect((await read(page, id)).messages.at(-1)!.teaching).toMatchObject({ status: 'unavailable', recording: { available: false, reason: 'not_checked' } });
  const arrangement = page.locator('.teaching-arrangement');
  await expand(arrangement.locator('details').first());
  await expect(arrangement).toContainText('当前模型尚未检查教学记录支持');
  await expect(page.getByLabel('输入学习问题', { exact: true })).toBeEnabled();

  const { dialog, record } = await settings(page);
  await expect(record).toContainText('普通对话：未检查');
  await expect(record).toContainText('外部搜索和知识库：未检查');
  expect((await check(page, record)).support).toMatchObject({ plain: 'supported', tools: 'supported' });
  await expect(record).toContainText('普通对话：可记录');
  await expect(record).toContainText('外部搜索和知识库：可记录');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/nautilus-teaching-record-settings-390.png', fullPage: true });

  expect((await page.request.post(`http://127.0.0.1:${process.env.NAUTILUS_E2E_MOCK_PROVIDER_PORT ?? '8013'}/__mock__/teaching-check/fail-next`)).ok()).toBeTruthy();
  const failed = await check(page, record);
  expect(failed).toMatchObject({ updated: false, support: { plain: 'supported', tools: 'supported' }, failures: { plain: 'auth_error', tools: 'auth_error' } });
  await expect(record).toContainText('已保留此前结果');
  await expect(record).toContainText('普通对话：可记录');
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();

  const streamed = page.waitForResponse(response => /\/api\/ai\/runs\/[^/]+\/stream$/.test(response.url()));
  await send(page, '[C2慢流] 请解释当前输入边界。');
  const wire = await (await streamed).text();
  const chunks = wire.split('\n').filter(line => line.startsWith('data: ')).map(line => JSON.parse(line.slice(6)))
    .filter(event => event.kind === 'content' || event.type === 'content');
  expect(chunks.length).toBeGreaterThan(0);
  const saved = (await read(page, id)).messages.at(-1)!;
  expect(saved.teaching).toMatchObject({ status: 'applied', recording: { available: true, reason: null } });
  expect(saved.teaching!.current.step?.text).toBeTruthy();
  expect(saved.content).not.toMatch(/nautilus_teaching_|"reply"|"teaching"|"token"|output_format/);
  expect(chunks.map(chunk => chunk.text).join('')).not.toMatch(/nautilus_teaching_|"reply"|"teaching"|"token"|output_format/);
  await expect(page.locator('.ai-message--assistant').last()).toContainText(saved.teaching!.current.step!.text);
  await expect(arrangement.getByRole('button', { name: '用自己的话说说', exact: true })).toBeEnabled();
  await page.reload();
  expect((await read(page, id)).messages.at(-1)!.content).toBe(saved.content);

  // A changed provider config requires a fresh check; the saved small point is
  // preserved while record-dependent actions become unavailable.
  expect((await page.request.patch(`/api/ai/providers/${provider.id}`, { data: { request_timeout_seconds: 16 } })).ok()).toBeTruthy();
  await send(page, '[C2学习] 继续普通对话。');
  expect((await read(page, id)).messages.at(-1)!.teaching).toMatchObject({ status: 'unavailable', current: saved.teaching!.current, recording: { reason: 'not_checked' } });
  await expand(arrangement.locator('details').first());
  await expect(arrangement.getByRole('button', { name: '换一道试试', exact: true })).toBeDisabled();
  await expect(arrangement.getByRole('button', { name: '用自己的话说说', exact: true })).toBeDisabled();
  await expect(page.getByLabel('输入学习问题', { exact: true })).toBeEnabled();
  await page.screenshot({ path: '/tmp/nautilus-teaching-record-unavailable-390.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('unsupported model reports unavailable and retains ordinary chat', async ({ page }) => {
  test.setTimeout(60_000);
  await setup(page, 'mock-unsupported');
  const { dialog, record } = await settings(page);
  expect((await check(page, record)).support).toMatchObject({ plain: 'unavailable', tools: 'unavailable' });
  await expect(record).toContainText('普通对话：暂不可记录');
  await expect(record).toContainText('外部搜索和知识库：暂不可记录');
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  await newRoom(page);
  const run = await send(page, '[C2学习] 请继续解释输入边界。');
  const message = (await read(page, run.conversation_id)).messages.at(-1)!;
  expect(message.content).toContain('学习步骤');
  expect(message.teaching).toMatchObject({ status: 'unavailable', recording: { available: false, reason: 'not_supported' }, attempt: null });
  await expand(page.locator('.teaching-arrangement details').first());
  await expect(page.locator('.teaching-arrangement')).toContainText('当前模型暂不能记录教学状态');
  await expect(page.getByLabel('输入学习问题', { exact: true })).toBeEnabled();
});

test('late support check cannot overwrite another selected model', async ({ page }) => {
  test.setTimeout(60_000);
  const provider = await setup(page);
  const model = await page.request.post(`/api/ai/providers/${provider.id}/models/manual`, { data: { model_id: 'mock-unsupported', display_name: 'Synthetic second model' } });
  expect(model.ok()).toBeTruthy();
  const second = (await model.json()).model;
  let release!: () => void;
  let reached!: () => void;
  const ready = new Promise<void>(resolve => { reached = resolve; });
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/teaching-support/check', async route => {
    const response = await route.fetch();
    reached(); await held;
    await route.fulfill({ response }).catch(() => {});
  });
  const { dialog, record } = await settings(page);
  await expect(record).toContainText('普通对话：未检查');
  await record.getByRole('button', { name: '检查支持', exact: true }).click();
  await ready;
  await record.getByLabel('检查模型', { exact: true }).selectOption(`${provider.id}::${second.id}`);
  await expect(record).toContainText('普通对话：未检查');
  release();
  await expect(record.getByRole('button', { name: '检查支持', exact: true })).toBeEnabled();
  await expect(record).not.toContainText('检查已完成');
  await expect(record).not.toContainText('普通对话：可记录');
  await record.locator('summary').click();
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
});
