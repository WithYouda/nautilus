import { expect, test, type Page } from '@playwright/test';
import { authorize } from './fact-helpers';

const mockBase = process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1';
const mockOrigin = mockBase.replace(/\/v1$/, '');

async function provider(page: Page, model: string) {
  expect((await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic outbound provider', base_url: mockBase, model,
    api_key: 'synthetic-outbound-key', enabled: true, request_timeout_seconds: 15,
    api_protocol: 'openai_compatible',
  } })).ok()).toBeTruthy();
}

async function searchService(page: Page) {
  const before = await (await page.request.get('/api/search/settings')).json();
  const id = crypto.randomUUID();
  expect((await page.request.put('/api/search/settings', { data: {
    revision: before.revision,
    services: [{ id, kind: 'searxng', name: '合成外部搜索', options: { url: mockOrigin, engines: '', language: '' }, secret_updates: {} }],
    selected_service_id: id, result_size: 5, timeout_seconds: 15, max_requests: 1,
  } })).ok()).toBeTruthy();
}

async function chooseExternal(page: Page, room = page.locator('.ai-room').first()) {
  await room.locator('.ai-composer').getByRole('button', { name: /联网搜索：/ }).click();
  await page.getByRole('dialog', { name: '联网搜索选择' }).getByRole('button', { name: /外部服务/ }).click();
  await expect(room.locator('.ai-composer').getByRole('button', { name: '联网搜索：合成外部搜索' })).toBeVisible();
}

async function outboundCount(page: Page) {
  const stats = await (await page.request.get(`${mockOrigin}/__mock__/stats`)).json();
  return stats.requests['outbound-search'] ?? 0;
}

test.beforeEach(async ({ page }) => {
  await authorize(page);
  expect((await page.request.post(`${mockOrigin}/__mock__/reset`)).ok()).toBeTruthy();
  const conversations = await (await page.request.get('/api/ai/conversations')).json();
  for (const item of conversations) expect((await page.request.delete(`/api/ai/conversations/${item.id}`)).ok()).toBeTruthy();
});

test('ordinary learning room blocks unknown egress, restores approval, and honors each decision', async ({ page }) => {
  test.setTimeout(90_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await provider(page, 'mock-search-tools');
  await searchService(page);
  await page.reload();
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await chooseExternal(page);
  const input = page.getByLabel('输入学习问题');
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: '确认这次外发' }) });

  await input.fill('第一轮：检索合成资料');
  await input.press('Enter');
  await expect(card).toBeVisible();
  await expect(card).toContainText('合成外部搜索');
  await expect(card).toContainText('Nautilus search reference');
  expect(await outboundCount(page)).toBe(0);
  await page.reload();
  await expect(card).toBeVisible();
  await card.getByRole('button', { name: '拒绝这次发送' }).click();
  await expect(card).toHaveCount(0);
  await expect(page.getByRole('button', { name: '取消生成' })).toBeHidden();
  expect(await outboundCount(page)).toBe(0);

  await input.fill('第二轮：允许合成检索');
  await input.press('Enter');
  await expect(card).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(card).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const approvalBox = await page.getByRole('region', { name: '外发确认' }).boundingBox();
  expect(approvalBox!.y + approvalBox!.height).toBeLessThan(844);
  await card.getByRole('button', { name: '取消本轮回答' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: '/tmp/nautilus-outbound-390.png' });
  await card.getByRole('button', { name: '允许这次发送' }).click();
  await expect.poll(() => outboundCount(page)).toBe(1);
  await expect(page.getByRole('button', { name: '取消生成' })).toBeHidden();

  await input.fill('第三轮：停止本轮');
  await input.press('Enter');
  await expect(card).toBeVisible();
  await card.getByRole('button', { name: '取消本轮回答' }).click();
  await expect(card).toHaveCount(0);
  await expect(page.getByRole('button', { name: '取消生成' })).toBeHidden();
  expect(await outboundCount(page)).toBe(1);

  const pickerButton = page.locator('.ai-composer').getByRole('button', { name: /联网搜索：/ });
  await pickerButton.click();
  await page.getByRole('dialog', { name: '联网搜索选择' }).getByRole('textbox', { name: /公开检索词/ }).fill('Nautilus search reference');
  await page.getByRole('dialog', { name: '联网搜索选择' }).getByRole('button', { name: '关闭搜索选择' }).click();
  await input.fill('第四轮：明确公开检索词');
  const request = page.waitForRequest(value => value.url().endsWith('/messages') && value.method() === 'POST');
  await input.press('Enter');
  expect((await request).postDataJSON().public_search_query).toBe('Nautilus search reference');
  await expect.poll(() => outboundCount(page)).toBe(2);
  await expect(card).toHaveCount(0);
  await expect(page.getByRole('button', { name: '取消生成' })).toBeHidden();
  await pickerButton.click();
  await expect(page.getByRole('dialog', { name: '联网搜索选择' }).getByRole('textbox', { name: /公开检索词/ })).toHaveValue('');
  expect(errors).toEqual([]);
});

test('question discussion displays the same real outbound decision before search', async ({ page }) => {
  test.setTimeout(120_000);
  await provider(page, 'mock-review');
  await searchService(page);
  await page.reload();
  await page.getByRole('button', { name: '学习首页', exact: true }).first().click();
  if (await (await page.request.get('/api/learning/return-review')).json()) await page.getByRole('button', { name: '创建', exact: true }).click();
  await page.getByLabel('学习目标', { exact: true }).fill('合成目标：外发审批');
  await page.getByRole('button', { name: '我想自己安排' }).click();
  await page.getByLabel('现在先做什么', { exact: true }).fill('合成题目讨论审批');
  await page.getByRole('button', { name: '确认这份学习安排' }).click();
  await page.getByRole('button', { name: '进入学习室并开始这项任务' }).click();
  await expect(page.locator('.ai-message--assistant').first()).toBeVisible();
  await page.getByRole('button', { name: '进入验证', exact: true }).click();
  await page.getByRole('button', { name: '开始验证', exact: true }).click();
  await page.getByPlaceholder('写出你的判断、过程或结果').first().fill('合成作答');
  await page.getByPlaceholder('写出你的判断、过程或结果').nth(1).fill('合成第二题作答');
  await page.getByRole('button', { name: '保存作答并验证' }).click();
  await page.getByRole('region', { name: '验证回看' }).getByRole('article', { name: '第 1 题回看' }).getByRole('button', { name: '讨论这道题' }).click();
  await provider(page, 'mock-search-tools');
  await page.reload();
  const room = page.getByRole('region', { name: '题目学习室' });
  await expect(room).toBeVisible();
  await chooseExternal(page, room);
  await room.getByLabel('继续提问或回答拓展问题').fill('请检索合成资料');
  await room.getByLabel('继续提问或回答拓展问题').press('Enter');
  const card = room.locator('.outbound-approval__card');
  await expect(card).toContainText('Nautilus search reference');
  expect(await outboundCount(page)).toBe(0);
  await card.getByRole('button', { name: '允许这次发送' }).click();
  await expect.poll(() => outboundCount(page)).toBe(1);
  await expect(card).toHaveCount(0);
});
