import { expect, test } from '@playwright/test';
import { authorize } from './fact-helpers';

test.beforeEach(async ({ page }) => {
  await authorize(page);
  const conversations = await (await page.request.get('/api/ai/conversations')).json();
  for (const conversation of conversations) expect((await page.request.delete(`/api/ai/conversations/${conversation.id}`)).ok()).toBeTruthy();
});

test('saved process trace keeps reasoning, tools, and answer in order', async ({ page }) => {
  const mockBase = process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1';
  const provider = await page.request.put('/api/ai/provider', { data: {
    display_name: 'Process trace test provider', base_url: mockBase, model: 'mock-success',
    api_key: 'synthetic-process-test-key', enabled: true, request_timeout_seconds: 15,
    api_protocol: 'openai_compatible',
  } });
  expect(provider.ok()).toBeTruthy();
  await page.reload();
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  const input = page.getByLabel('输入学习问题');
  await input.fill('Synthetic process question');
  const sent = page.waitForRequest(request => request.url().endsWith('/messages') && request.method() === 'POST');
  await input.press('Enter');
  const response = await (await sent).response();
  const { run } = await response!.json();
  await expect(page.locator('.ai-message--assistant').first()).toContainText('完成');
  const now = '2026-09-26T12:00:00Z';
  const part = (id: string, type: 'reasoning' | 'text' | 'tool', extra: Record<string, unknown> = {}) => ({ id, type, status: 'succeeded', started_at: now, finished_at: now, duration_ms: 1250, ...extra });
  let routeHits = 0;
  await page.route(`**/api/ai/conversations/${run.conversation_id}`, async route => {
    routeHits += 1;
    const original = await route.fetch();
    const data = await original.json();
    const assistant = data.messages.find((message: { id: string }) => message.id === run.response_message_id);
    assistant.generation_trace = { version: 1, status: 'succeeded', started_at: now, finished_at: now, elapsed_ms: 6000, parts: [
      part('r1', 'reasoning', { text: '先辨认问题' }),
      part('t1', 'tool', { name: 'search_web', query: 'synthetic evidence', service_name: 'Synthetic JS', result: { mode: 'external', status: 'succeeded', service_name: 'Synthetic JS', query: 'synthetic evidence', items: [{ title: 'Synthetic source', url: 'https://example.com/process-proof', text: 'Evidence' }] } }),
      part('r2', 'reasoning', { text: '对比来源' }),
      part('t2', 'tool', { name: 'scrape_web', url: 'https://example.com/process-proof', result: { mode: 'external', status: 'succeeded', content: 'Source content', url: 'https://example.com/process-proof', items: [] } }),
      part('mid', 'text', { text: '中途说明。' }),
      part('r3', 'reasoning', { text: '完成核对' }),
      part('answer', 'text', { text: '最终回答。' }),
    ] };
    await route.fulfill({ response: original, contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.reload();
  await expect.poll(() => routeHits).toBeGreaterThan(0);
  const answer = page.locator('.ai-message--assistant').first();
  const responseView = answer.locator('.ai-assistant-response');
  await expect(responseView.getByRole('button', { name: /展开较早的 2 个步骤/ })).toBeVisible();
  await expect(responseView.getByText('中途说明。')).toBeVisible();
  await expect(responseView.getByText('最终回答。')).toBeVisible();
  await expect(responseView.getByText('先辨认问题')).toHaveCount(0);
  await responseView.getByRole('button', { name: /展开较早的 2 个步骤/ }).click();
  await responseView.getByRole('button', { name: /已思考.*1.3 秒/ }).first().click();
  await expect(responseView.getByText('先辨认问题')).toBeVisible();
  await responseView.getByRole('button', { name: '查看来源与检索过程' }).first().click();
  const detail = page.getByRole('dialog', { name: '联网搜索详情' });
  await expect(detail.getByRole('link', { name: 'Synthetic source' })).toHaveAttribute('href', 'https://example.com/process-proof');
  await detail.getByRole('button', { name: '关闭搜索详情' }).click();
  await expect(answer.locator(':scope > .search-result-block')).toHaveCount(0);
});

test('live tool run preserves process and sources after reload', async ({ page }) => {
  test.setTimeout(60_000);
  const mockBase = process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1';
  const provider = await page.request.put('/api/ai/provider', { data: {
    display_name: 'Process trace live provider', base_url: mockBase, model: 'mock-process-tools',
    api_key: 'synthetic-process-test-key', enabled: true, request_timeout_seconds: 15,
    api_protocol: 'openai_compatible',
  } });
  expect(provider.ok()).toBeTruthy();
  const settings = await (await page.request.get('/api/search/settings')).json();
  const service = { id: crypto.randomUUID(), kind: 'custom_js', name: 'Synthetic JS', options: {
    name: '', search_script: `function search(query,maxResults){ return {items:[{title:'Source for '+query,url:'https://example.com/process-proof',text:'Synthetic evidence for '+query,publishedDate:'2026-01-01'}]}; }`, scrape_script: '',
  }, secret_updates: {} };
  expect((await page.request.put('/api/search/settings', { data: {
    revision: settings.revision, services: [service], selected_service_id: service.id,
    result_size: 5, timeout_seconds: 15, max_requests: 3,
  } })).ok()).toBeTruthy();
  await page.reload();
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await page.locator('.ai-composer').getByRole('button', { name: /联网搜索：/ }).click();
  await page.getByRole('dialog', { name: '联网搜索选择' }).getByRole('button', { name: /外部服务/ }).click();
  const input = page.getByLabel('输入学习问题');
  await input.fill('Synthetic live process question');
  const sent = page.waitForRequest(request => request.url().endsWith('/messages') && request.method() === 'POST');
  await input.press('Enter');
  const answer = page.locator('.ai-message--assistant').last();
  await expect(answer.getByRole('button', { name: /思考中/ })).toBeVisible();
  const response = await (await sent).response();
  const { run } = await response!.json();
  await expect(answer).toContainText('思考与工具步骤已按发生顺序保留。', { timeout: 30000 });
  const saved = await (await page.request.get(`/api/ai/conversations/${run.conversation_id}`)).json();
  const assistant = saved.messages.find((message: { id: string }) => message.id === run.response_message_id);
  expect(assistant.generation_trace?.parts.map((part: {type:string}) => part.type)).toEqual(['reasoning', 'text', 'tool', 'reasoning', 'tool', 'reasoning', 'text']);
  await answer.getByRole('button', { name: /展开较早的 2 个步骤/ }).click();
  await expect(answer.locator('.ai-process-tool')).toHaveCount(2);
  await expect(answer.locator('.ai-process-reasoning')).toHaveCount(3);
  await expect(answer.getByText('已思考', { exact: false }).first()).toBeVisible();
  await page.reload();
  const restored = page.locator('.ai-message--assistant').first();
  await restored.getByRole('button', { name: '查看来源与检索过程' }).click();
  await expect(page.getByRole('dialog', { name: '联网搜索详情' })).toBeVisible();
  await expect(restored.locator('.ai-process-tool')).toHaveCount(2); // Opening detail keeps its step mounted as the group expands.
  await page.getByRole('dialog', { name: '联网搜索详情' }).getByRole('button', { name: '关闭搜索详情' }).click();
  await expect(restored.locator('.ai-process-tool')).toHaveCount(2);
  await page.screenshot({ path: '/tmp/nautilus-process-trace.png' });
  await restored.getByRole('button', { name: '查看来源与检索过程' }).first().click();
  await expect(page.getByRole('dialog', { name: '联网搜索详情' }).getByRole('link', { name: /Source for Nautilus process reference/ })).toHaveAttribute('href', 'https://example.com/process-proof');
  await page.screenshot({ path: '/tmp/nautilus-process-source-detail.png' });
  await page.getByRole('dialog', { name: '联网搜索详情' }).getByRole('button', { name: '关闭搜索详情' }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: '/tmp/nautilus-process-trace-mobile.png' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await restored.getByRole('button', { name: '查看来源与检索过程' }).first().click();
  await expect(page.getByRole('dialog', { name: '联网搜索详情' })).toBeVisible();
  await page.screenshot({ path: '/tmp/nautilus-process-source-detail-mobile.png' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
