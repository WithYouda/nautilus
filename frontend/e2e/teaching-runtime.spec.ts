import { expect, test, type Page, type Locator } from '@playwright/test';
import { authorize, checkDefaultTeachingSupport } from './fact-helpers';
import type { AiConversationDetail, QuestionDiscussion } from '../src/api';

test.beforeEach(async ({ page }) => {
  const response = await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT ?? '8012'}/openapi.json`);
  expect(response.ok()).toBeTruthy();
  const schema = await response.json();
  expect(Object.keys(schema.paths).some(path => path.startsWith('/api/ai/conversations/') && path.endsWith('/teaching-attempt'))).toBe(true);
  expect(Object.keys(schema.paths).some(path => path.startsWith('/api/learning/discussions/') && path.endsWith('/teaching-attempt'))).toBe(true);
});

async function provider(page: Page) {
  expect((await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic teaching provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model: 'mock-success', api_key: 'synthetic-teaching-key', enabled: true, request_timeout_seconds: 15,
  } })).ok()).toBeTruthy();
  await checkDefaultTeachingSupport(page);
}

async function conversation(page: Page, id: string): Promise<AiConversationDetail> {
  const response = await page.request.get(`/api/ai/conversations/${id}`);
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function sendOrdinary(page: Page, content: string, complete = true) {
  const accepted = page.waitForResponse(response => /\/api\/ai\/conversations\/[^/]+\/messages$/.test(response.url()) && response.request().method() === 'POST');
  await page.getByLabel('输入学习问题', { exact: true }).fill(content);
  await page.getByLabel('输入学习问题', { exact: true }).press('Enter');
  const response = await accepted;
  expect(response.ok()).toBeTruthy();
  const { run } = await response.json();
  if (complete) {
    await expect.poll(async () => (await conversation(page, run.conversation_id)).active_run, { timeout: 15_000 }).toBeNull();
    await expect(page.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  }
  return run;
}

async function expand(locator: Locator) {
  if (!(await locator.evaluate(element => (element as HTMLDetailsElement).open))) await locator.locator('summary').first().click();
}

async function openAttempts(arrangement: Locator) {
  await expand(arrangement.locator('details').first());
  await expand(arrangement.locator('.teaching-state__attempts'));
  return arrangement.getByRole('article', { name: 'AI识别的尝试' });
}

test('ordinary teaching follows selected versions, preserves cancelled checkpoints and rejects stale corrections on 390px', async ({ page }) => {
  test.setTimeout(90_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await authorize(page);
  await provider(page);
  await page.reload();
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  const firstRun = await sendOrdinary(page, '[C1学习] 请先讲一个小点。');
  const id = firstRun.conversation_id;
  const first = (await conversation(page, id)).messages.at(-1)!;
  expect(first.teaching?.status).toBe('applied');
  expect(first.teaching?.current.step?.text).toBeTruthy();
  const arrangement = page.locator('.teaching-arrangement');
  await expect(arrangement).toBeVisible();
  await expect(arrangement.locator('.teaching-state')).toBeHidden();
  await expand(arrangement.locator('details').first());
  await expect(arrangement.locator('.teaching-state__step')).toContainText(first.teaching!.current.step!.text);
  await expect(arrangement).toContainText('分步讲解');

  const original = '[C1尝试] 我先检查空输入，再检查正常输入。';
  await sendOrdinary(page, original);
  const old = (await conversation(page, id)).messages.at(-1)!;
  expect(old.teaching?.attempt?.is_attempt).toBe(true);
  expect(old.teaching?.before.step?.id).toBe(first.teaching!.current.step!.id);
  let attempt = await openAttempts(arrangement);
  await expect(attempt).toHaveCount(1);
  await expect(attempt).toContainText('AI识别');
  await expect(attempt).toContainText(first.teaching!.current.step!.text);
  await expect(attempt.locator('blockquote').first()).toContainText('我先检查空输入');
  await attempt.getByRole('button', { name: '这不是一次尝试', exact: true }).click();
  await expect(attempt.getByRole('button', { name: '恢复为尝试', exact: true })).toBeEnabled();
  const corrected = (await conversation(page, id)).messages.find(message => message.id === old.id)!;
  expect(corrected.teaching?.attempt).toMatchObject({ is_attempt: false, revision: old.teaching!.attempt!.revision + 1 });
  expect((await conversation(page, id)).messages.find(message => message.id === corrected.teaching!.attempt!.message_id)?.content).toBe(original);

  // The new answer version starts from the original question's checkpoint, and
  // its new AI observation must not inherit the old answer's user correction.
  await page.locator('.ai-message--assistant').last().getByRole('button', { name: '重新生成', exact: true }).click();
  await expect.poll(async () => (await conversation(page, id)).messages.filter(message => message.role === 'assistant').length).toBe(3);
  await expect.poll(async () => (await conversation(page, id)).active_run, { timeout: 15_000 }).toBeNull();
  attempt = await openAttempts(arrangement);
  await expect(attempt).toHaveCount(1);
  await expect(attempt.getByRole('button', { name: '这不是一次尝试', exact: true })).toBeEnabled();
  await page.locator('.ai-message--assistant').last().getByRole('button', { name: '上一个回答', exact: true }).click();
  await expect(attempt.getByRole('button', { name: '恢复为尝试', exact: true })).toBeEnabled();
  await page.reload();
  attempt = await openAttempts(arrangement);
  await expect(attempt).toHaveCount(1);
  await expect(attempt.getByRole('button', { name: '恢复为尝试', exact: true })).toBeEnabled();

  // Update in another client first. This page sends once, reads the new revision,
  // and leaves the user to choose again instead of resending the correction.
  const correctionPath = `/api/ai/conversations/${id}/messages/${old.id}/teaching-attempt`;
  expect((await page.request.post(correctionPath, { data: {
    expected_revision: corrected.teaching!.attempt!.revision, is_attempt: true, request_key: 'c1-other-page-restore',
  } })).ok()).toBeTruthy();
  let posts = 0;
  page.on('request', request => { if (request.url().endsWith(correctionPath) && request.method() === 'POST') posts += 1; });
  const conflict = page.waitForResponse(response => response.url().endsWith(correctionPath) && response.request().method() === 'POST');
  await attempt.getByRole('button', { name: '恢复为尝试', exact: true }).click();
  expect((await conflict).status()).toBe(409);
  await expect(attempt.getByRole('alert')).toContainText('已读取最新记录');
  await expect(attempt.getByRole('button', { name: '这不是一次尝试', exact: true })).toBeEnabled();
  expect(posts).toBe(1);
  await attempt.getByRole('button', { name: '这不是一次尝试', exact: true }).click();
  await expect(attempt.getByRole('button', { name: '恢复为尝试', exact: true })).toBeEnabled();
  await expand(attempt.locator('.teaching-attempt__history'));
  await expect(attempt.locator('.teaching-attempt__history')).toContainText('改为非尝试');

  const beforeSlow = (await conversation(page, id)).messages.find(message => message.id === old.id)!.teaching!.current;
  await sendOrdinary(page, '[C1慢流] 请继续这个小点。', false);
  await expect(page.locator('.ai-message--assistant').last().locator('.ai-message-content')).toContainText('正在分析输入边界。');
  await expect(arrangement.locator('.teaching-state__step')).toContainText(beforeSlow.step!.text);
  await expect(attempt.getByRole('button', { name: '恢复为尝试', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '取消生成', exact: true }).click();
  await expect.poll(async () => (await conversation(page, id)).active_run).toBeNull();
  const cancelled = (await conversation(page, id)).messages.at(-1)!;
  expect(cancelled.content).toBeTruthy();
  expect(cancelled.teaching).toMatchObject({ status: 'not_updated', current: beforeSlow, after: null });
  await page.reload();
  await page.setViewportSize({ width: 390, height: 844 });
  await expand(arrangement.locator('details').first());
  await expect(arrangement.locator('.teaching-state__step')).toContainText(beforeSlow.step!.text);
  await expect(arrangement).toContainText('本轮未更新教学位置');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/nautilus-teaching-ordinary-390.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('question discussion shares teaching state, correctable original references and refresh on 390px', async ({ page }) => {
  test.setTimeout(90_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await authorize(page);
  await provider(page);
  await page.reload();
  await page.getByRole('button', { name: '学习首页', exact: true }).first().click();
  if (await (await page.request.get('/api/learning/return-review')).json()) await page.getByRole('button', { name: '创建', exact: true }).click();
  await page.getByLabel('学习目标', { exact: true }).fill('合成目标：教学状态讨论');
  await page.getByRole('button', { name: '我想自己安排', exact: true }).click();
  await page.getByLabel('现在先做什么', { exact: true }).fill('合成教学状态讨论旅程');
  await page.getByRole('button', { name: '确认这份学习安排', exact: true }).click();
  await page.getByRole('button', { name: '进入学习室并开始这项任务', exact: true }).click();
  await expect(page.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  const taskArrangement = page.getByRole('region', { name: '本次学习安排' });
  await expect(taskArrangement).toHaveCount(1);
  await page.getByRole('button', { name: '进入验证', exact: true }).click();
  await page.getByRole('button', { name: '开始验证', exact: true }).click();
  await page.getByPlaceholder('写出你的判断、过程或结果').fill('合成原作答：先定位再检查边界。');
  await page.getByRole('button', { name: '保存作答并验证', exact: true }).click();
  const review = page.getByRole('region', { name: '验证回看' });
  await review.getByRole('article', { name: '第 1 题回看' }).getByRole('button', { name: '讨论这道题', exact: true }).click();
  const room = page.getByRole('region', { name: '题目学习室' });
  await expect(room).toBeVisible();
  await expect.poll(() => new URL(page.url()).searchParams.get('discussion')).not.toBeNull();
  const id = new URL(page.url()).searchParams.get('discussion')!;
  expect(id).toBeTruthy();
  const input = room.getByLabel('继续提问或回答拓展问题');
  async function read(): Promise<QuestionDiscussion> { return (await page.request.get(`/api/learning/discussions/${id}`)).json(); }
  async function send(text: string) {
    const accepted = page.waitForResponse(response => response.url().endsWith(`/api/learning/discussions/${id}/messages`) && response.request().method() === 'POST');
    await input.fill(text); await input.press('Enter');
    expect((await accepted).ok()).toBeTruthy();
    await expect.poll(async () => (await read()).turns.at(-1)?.status, { timeout: 15_000 }).toBe('succeeded');
    await expect(room.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  }
  await send('[C1学习] 请讲清楚这个小点。');
  const first = (await read()).turns[0];
  expect(first.teaching?.status).toBe('applied');
  const arrangement = room.locator('.teaching-arrangement');
  await expect(arrangement.locator('.teaching-state')).toBeHidden();
  await expand(arrangement.locator('details').first());
  await expect(arrangement.locator('.teaching-state__step')).toContainText(first.teaching!.current.step!.text);
  const original = '[C1尝试] 我先检查空输入，再检查正常输入。';
  await send(original);
  const second = (await read()).turns.at(-1)!;
  expect(second.teaching?.attempt?.message_id).toBe(second.id);
  let attempt = await openAttempts(arrangement);
  await expect(attempt).toHaveCount(1);
  await expect(attempt).toContainText(first.teaching!.current.step!.text);
  await expect(attempt.locator('blockquote').first()).toContainText('我先检查空输入');
  await attempt.getByRole('button', { name: '这不是一次尝试', exact: true }).click();
  await expect(attempt.getByRole('button', { name: '恢复为尝试', exact: true })).toBeEnabled();
  expect((await read()).turns.at(-1)?.user_content).toBe(original);
  await page.reload();
  attempt = await openAttempts(arrangement);
  await expect(attempt.getByRole('button', { name: '恢复为尝试', exact: true })).toBeEnabled();
  await attempt.getByRole('button', { name: '恢复为尝试', exact: true }).click();
  await expect(attempt.getByRole('button', { name: '这不是一次尝试', exact: true })).toBeEnabled();
  await expand(attempt.locator('.teaching-attempt__history'));
  await expect(attempt.locator('.teaching-attempt__history')).toContainText('恢复为尝试');
  expect((await read()).turns.at(-1)?.teaching?.attempt?.corrections).toHaveLength(2);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(attempt.getByRole('button', { name: '这不是一次尝试', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/nautilus-teaching-discussion-390.png', fullPage: true });
  expect(errors).toEqual([]);
});
