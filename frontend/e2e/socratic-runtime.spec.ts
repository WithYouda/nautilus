import { expect, test, type Locator, type Page } from '@playwright/test';
import { authorize, checkDefaultTeachingSupport } from './fact-helpers';
import type { AiConversationDetail, AiRun, QuestionDiscussion } from '../src/api';

test.beforeEach(async ({ page }) => {
  const response = await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT ?? '8012'}/openapi.json`);
  expect(response.ok()).toBeTruthy();
  const schema = await response.json();
  for (const name of ['MessageSendRequest', 'QuestionDiscussionMessageRequest'])
    expect(schema.components.schemas[name].properties.teaching_mode).toBeTruthy();
});

async function setup(page: Page) {
  await authorize(page);
  expect((await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic socratic provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model: 'mock-success', api_key: 'synthetic-socratic-key', enabled: true, request_timeout_seconds: 15,
  } })).ok()).toBeTruthy();
  await checkDefaultTeachingSupport(page);
  await page.reload();
}

async function conversation(page: Page, id: string): Promise<AiConversationDetail> {
  const response = await page.request.get(`/api/ai/conversations/${id}`);
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function newRoom(page: Page) {
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await expect(page.getByLabel('输入学习问题', { exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  await expect(page.getByLabel('输入学习问题', { exact: true })).toBeEnabled();
  await expect(page.locator('.ai-message--user')).toHaveCount(0);
}

async function finished(page: Page, id: string) {
  await expect.poll(async () => (await conversation(page, id)).active_run, { timeout: 15_000 }).toBeNull();
  await expect(page.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
}

function messageResponse(page: Page) {
  return page.waitForResponse(response => /\/api\/ai\/conversations\/[^/]+\/messages$/.test(response.url()) && response.request().method() === 'POST');
}

async function send(page: Page, content: string, complete = true): Promise<AiRun> {
  const accepted = messageResponse(page);
  const input = page.getByLabel('输入学习问题', { exact: true });
  await input.fill(content); await input.press('Enter');
  const response = await accepted;
  expect(response.ok()).toBeTruthy();
  const { run } = await response.json();
  if (complete) await finished(page, run.conversation_id);
  return run;
}

async function expand(locator: Locator) {
  if (!(await locator.evaluate(element => (element as HTMLDetailsElement).open))) await locator.locator('summary').first().click();
}

async function arrangement(page: Page) {
  const value = page.locator('.teaching-arrangement');
  await expect(value).toBeVisible();
  await expand(value.locator('details').first());
  return value;
}

async function help(page: Page, id: string, label: string) {
  const accepted = messageResponse(page);
  await page.getByRole('button', { name: label, exact: true }).click();
  expect((await accepted).ok()).toBeTruthy();
  await finished(page, id);
}

test('ordinary guidance persists, advances on actual stuck attempts and uses corrected progress on 390px', async ({ page }) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await setup(page);
  await newRoom(page);
  const view = await arrangement(page);
  let posts = 0;
  page.on('request', request => { if (/\/api\/ai\/conversations\/[^/]+\/messages$/.test(request.url()) && request.method() === 'POST') posts += 1; });
  await view.getByLabel('讲解方式', { exact: true }).selectOption('socratic');
  await expect(view).toContainText('下次发送时使用提问引导');
  expect(posts).toBe(0);
  const firstAccepted = messageResponse(page);
  const run = await send(page, '[C2学习] 先检查一种输入。');
  expect((await firstAccepted).request().postDataJSON().teaching_mode).toBe('socratic');
  const id = run.conversation_id;
  const first = (await conversation(page, id)).messages.at(-1)!.teaching!;
  expect(first).toMatchObject({ requested_mode: 'socratic', current: { mode: 'socratic', guidance: { level: 0, stuck_count: 0 } } });
  await page.reload();
  const refreshed = await arrangement(page);
  await expect(refreshed.getByLabel('讲解方式', { exact: true })).toHaveValue('socratic');
  await expect(refreshed).toContainText('提示安排 · 开放提问');

  await send(page, '[C2卡住] 我检查了空输入，仍不知道该返回什么。');
  expect((await conversation(page, id)).messages.at(-1)!.teaching!.current.guidance).toMatchObject({ level: 0, stuck_count: 1 });
  await send(page, '[C2卡住] 我再检查空输入，还是不知道返回值。');
  expect((await conversation(page, id)).messages.at(-1)!.teaching!.current.guidance).toMatchObject({ level: 1, stuck_count: 0 });
  expect((await conversation(page, id)).messages.at(-1)!.teaching!.current.step?.id).toBe(first.current.step!.id);
  await expect(refreshed).toContainText('提示安排 · 相关概念');
  const input = page.getByLabel('输入学习问题', { exact: true });
  await input.fill('这是一份尚未发送的草稿。');
  await help(page, id, '换个例子');
  await expect(input).toHaveValue('这是一份尚未发送的草稿。');
  expect((await conversation(page, id)).messages.at(-1)!.teaching!.current.guidance?.level).toBe(1);

  const correctedText = '[C2卡住] 我试了空数组，仍没有找到边界判断。';
  await send(page, correctedText);
  await expand(refreshed.locator('.teaching-state__attempts'));
  const corrected = refreshed.getByRole('article', { name: 'AI识别的尝试' }).filter({ hasText: correctedText });
  await corrected.getByLabel('尝试进展', { exact: true }).selectOption('progressed');
  await expect(corrected.getByLabel('尝试进展', { exact: true })).toHaveValue('progressed');
  await send(page, '[C2卡住] 我试了另一份空数组，仍没找到判断。');
  expect((await conversation(page, id)).messages.at(-1)!.teaching!.current.guidance).toMatchObject({ level: 1, stuck_count: 1 });
  await corrected.getByLabel('尝试进展', { exact: true }).selectOption('stuck');
  await expect(corrected.getByLabel('尝试进展', { exact: true })).toHaveValue('stuck');
  await send(page, '[C2学习] 继续讨论当前小点。');
  expect((await conversation(page, id)).messages.at(-1)!.teaching!.current.guidance).toMatchObject({ level: 2, stuck_count: 0 });
  await help(page, id, '给个提示');
  expect((await conversation(page, id)).messages.at(-1)!.teaching!.current.guidance?.level).toBe(3);
  await send(page, '[C2学习] 给我提示。');
  expect((await conversation(page, id)).messages.at(-1)!.teaching!.current.guidance?.level).toBe(4);
  await send(page, '[C2学习] 请完整讲解。');
  expect((await conversation(page, id)).messages.at(-1)!.teaching).toMatchObject({ effective_mode: 'full_explanation', current: { mode: 'socratic' } });
  await expect(refreshed).toContainText('本轮：完整讲解 · 下轮：提问引导');
  await send(page, '[C2学习] 继续这个小点。');
  expect((await conversation(page, id)).messages.at(-1)!.teaching!.effective_mode).toBe('socratic');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(refreshed.getByLabel('讲解方式', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/nautilus-socratic-ordinary-390.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('first selection survives unknown acceptance, regeneration uses its original choice and branches keep cancelled checkpoints', async ({ page }) => {
  test.setTimeout(120_000);
  await setup(page);
  await newRoom(page);
  let view = await arrangement(page);
  await view.getByLabel('讲解方式', { exact: true }).selectOption('socratic');
  let lostRun: AiRun | null = null;
  let loseResponse = true;
  const posted: Array<Record<string, unknown>> = [];
  await page.route(/\/api\/ai\/conversations\/[^/]+\/messages$/, async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    posted.push(route.request().postDataJSON());
    if (!loseResponse) { await route.continue(); return; }
    loseResponse = false;
    const response = await route.fetch();
    expect(response.ok()).toBeTruthy();
    lostRun = (await response.json()).run;
    await route.abort('failed');
  });
  const question = '[C2学习] 首次选择提问方式后先检查输入。';
  const input = page.getByLabel('输入学习问题', { exact: true });
  await input.fill(question); await input.press('Enter');
  await expect(page.locator('.ai-room-error')).toBeVisible();
  expect(lostRun).not.toBeNull();
  await expect(input).toHaveValue(question);
  view = await arrangement(page);
  await expect(view.getByLabel('讲解方式', { exact: true })).toHaveValue('socratic');
  await expect(view.getByLabel('讲解方式', { exact: true })).toBeDisabled();
  await send(page, question);
  const id = lostRun!.conversation_id;
  expect(posted.slice(0, 2).map(request => request.teaching_mode)).toEqual(['socratic', 'socratic']);
  expect(posted[0].client_message_id).toBe(posted[1].client_message_id);
  expect((await conversation(page, id)).messages).toHaveLength(2);
  const firstAnswer = (await conversation(page, id)).messages.at(-1)!;
  view = await arrangement(page);
  await view.getByLabel('讲解方式', { exact: true }).selectOption('stepwise');
  const regenerate = messageResponse(page);
  await page.locator('.ai-message--assistant').last().getByRole('button', { name: '重新生成', exact: true }).click();
  const response = await regenerate;
  expect(response.request().postDataJSON()).toMatchObject({ regenerate_message_id: firstAnswer.id, teaching_mode: 'socratic' });
  await finished(page, id);
  await expect(view.getByLabel('讲解方式', { exact: true })).toHaveValue('socratic');
  await view.getByLabel('讲解方式', { exact: true }).selectOption('stepwise');
  await page.locator('.ai-message--assistant').last().getByRole('button', { name: '上一个回答', exact: true }).click();
  await expect(view.getByLabel('讲解方式', { exact: true })).toHaveValue('socratic');
  await expect(view).not.toContainText('下次发送时使用');
  await page.reload();
  view = await arrangement(page);
  await expect(view.getByLabel('讲解方式', { exact: true })).toHaveValue('socratic');

  const branchAccepted = page.waitForResponse(response => response.url().endsWith(`/api/ai/conversations/${id}/branches`) && response.request().method() === 'POST');
  await page.locator('.ai-message--assistant').last().getByRole('button', { name: '从这里创建独立对话', exact: true }).click();
  const branchResponse = await branchAccepted;
  expect(branchResponse.ok()).toBeTruthy();
  const branchId = (await branchResponse.json()).conversation.id;
  await expect(page.getByRole('button', { name: '返回原对话', exact: true })).toBeVisible();
  view = await arrangement(page);
  await expect(view.getByLabel('讲解方式', { exact: true })).toHaveValue('socratic');
  const before = (await conversation(page, branchId)).messages.at(-1)!.teaching!.current;
  await send(page, '[C2慢流] 继续检查输入边界。', false);
  await expect(page.locator('.ai-message--assistant').last().locator('.ai-message-content')).not.toBeEmpty();
  await expect(view.getByLabel('讲解方式', { exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '取消生成', exact: true }).click();
  await finished(page, branchId);
  expect((await conversation(page, branchId)).messages.at(-1)!.teaching).toMatchObject({ status: 'not_updated', before, current: before, after: null });
  await page.reload();
  view = await arrangement(page);
  await expect(view.getByLabel('讲解方式', { exact: true })).toHaveValue('socratic');
  await expect(view.locator('.teaching-state__step')).toContainText(before.step!.text);
});

test('question discussion chooses from an empty path and corrects progress while preserving original answers on 390px', async ({ page }) => {
  test.setTimeout(120_000);
  await setup(page);
  await page.getByRole('button', { name: '学习首页', exact: true }).first().click();
  if (await (await page.request.get('/api/learning/return-review')).json()) await page.getByRole('button', { name: '创建', exact: true }).click();
  await page.getByLabel('学习目标', { exact: true }).fill('合成目标：提问引导讨论');
  await page.getByRole('button', { name: '我想自己安排', exact: true }).click();
  await page.getByLabel('现在先做什么', { exact: true }).fill('合成提问引导讨论旅程');
  await page.getByRole('button', { name: '确认这份学习安排', exact: true }).click();
  await page.getByRole('button', { name: '进入学习室并开始这项任务', exact: true }).click();
  await expect(page.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '进入验证', exact: true }).click();
  await page.getByRole('button', { name: '开始验证', exact: true }).click();
  await page.getByPlaceholder('写出你的判断、过程或结果').fill('合成原作答：先定位，再检查边界。');
  await page.getByRole('button', { name: '保存作答并验证', exact: true }).click();
  await page.getByRole('region', { name: '验证回看' }).getByRole('article', { name: '第 1 题回看' }).getByRole('button', { name: '讨论这道题', exact: true }).click();
  const room = page.getByRole('region', { name: '题目学习室' });
  await expect(room).toBeVisible();
  await expect.poll(() => new URL(page.url()).searchParams.get('discussion')).not.toBeNull();
  const id = new URL(page.url()).searchParams.get('discussion')!;
  async function read(): Promise<QuestionDiscussion> { return (await page.request.get(`/api/learning/discussions/${id}`)).json(); }
  const input = room.getByLabel('继续提问或回答拓展问题');
  async function discussionSend(text: string) {
    const accepted = page.waitForResponse(response => response.url().endsWith(`/api/learning/discussions/${id}/messages`) && response.request().method() === 'POST');
    await input.fill(text); await input.press('Enter');
    const response = await accepted;
    expect(response.ok()).toBeTruthy();
    await expect.poll(async () => (await read()).turns.at(-1)?.status, { timeout: 15_000 }).toBe('succeeded');
    await expect(room.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
    return response;
  }
  const view = room.locator('.teaching-arrangement');
  await expand(view.locator('details').first());
  await view.getByLabel('讲解方式', { exact: true }).selectOption('socratic');
  expect((await read()).turns).toHaveLength(0);
  expect((await discussionSend('[C2学习] 先检查当前题目的输入。')).request().postDataJSON().teaching_mode).toBe('socratic');
  await discussionSend('[C2卡住] 我尝试检查空输入，仍不知道如何返回。');
  await expand(view.locator('.teaching-state__attempts'));
  const attempt = view.getByRole('article', { name: 'AI识别的尝试' }).last();
  await attempt.getByLabel('尝试进展', { exact: true }).selectOption('progressed');
  await expect(attempt.getByLabel('尝试进展', { exact: true })).toHaveValue('progressed');
  await discussionSend('[C2卡住] 我检查另一份空输入，仍找不到返回值。');
  expect((await read()).turns.at(-1)!.teaching!.current.guidance).toMatchObject({ level: 0, stuck_count: 1 });
  await discussionSend('[C2学习] 请完整讲解。');
  await expect(view).toContainText('本轮：完整讲解 · 下轮：提问引导');
  await page.reload();
  await expand(view.locator('details').first());
  await expect(view.getByLabel('讲解方式', { exact: true })).toHaveValue('socratic');
  await discussionSend('[C2学习] 继续当前小点。');
  expect((await read()).turns.at(-1)!.teaching!.effective_mode).toBe('socratic');
  expect((await read()).source?.answer).toBe('合成原作答：先定位，再检查边界。');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(view.getByLabel('讲解方式', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/nautilus-socratic-discussion-390.png', fullPage: true });
});
