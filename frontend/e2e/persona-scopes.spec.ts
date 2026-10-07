import { expect, test, type Locator } from '@playwright/test';
import { authorize } from './fact-helpers';

test('persona inherits plan/task, overrides conversation and restores on mobile', async ({ page }) => {
  test.setTimeout(60_000);
  const schema = await (await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT}/openapi.json`)).json();
  expect(schema.paths['/api/personas/scopes/{kind}/{scope_id}']).toBeTruthy();
  await authorize(page);
  expect((await page.request.put('/api/ai/provider', { data: { display_name: 'Synthetic', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL, model: 'mock-success', api_key: 'synthetic', enabled: true, request_timeout_seconds: 15 } })).ok()).toBeTruthy();
  const ids: string[] = [];
  for (const name of ['合成全局导师', '合成计划导师']) {
    const preview = await page.request.post('/api/personas/previews', { data: { package: { format: 'nautilus.persona', schema_version: 1, name, description: '合成测试人格', style: { address: '同学', tone: 'warm', phrasing: 'plain', detail: 'concise', reminders: 'gentle', traits: [] } }, request_key: crypto.randomUUID() } });
    expect(preview.ok()).toBeTruthy();
    const state = await (await page.request.get('/api/personas')).json();
    const confirmed = await page.request.post('/api/personas/changes', { data: { action: 'confirm', preview_id: (await preview.json()).preview_id, expected_revision: state.revision, request_key: crypto.randomUUID() } });
    expect(confirmed.ok()).toBeTruthy(); ids.push((await confirmed.json()).active_id);
  }
  const state = await (await page.request.get('/api/personas')).json();
  expect((await page.request.put('/api/personas/scopes/global/default', { data: { selection: ids[0], expected_revision: state.revision } })).ok()).toBeTruthy();
  const setup = await page.request.post('/api/learning/setup/confirm', { data: {
    original_intent: '合成人格目标', goal_title: '合成人格目标', plan_title: '合成人格计划', action_title: '合成人格任务', context_key: 'persona-scope', object_description: '合成对象', behavior: '解释例子', outcome_context_key: 'persona-scope', stop_conditions: '解释例子', idempotency_key: crypto.randomUUID(),
  } });
  expect(setup.ok()).toBeTruthy();
  await page.getByRole('button', { name: '学习计划', exact: true }).click();
  await page.getByRole('navigation', { name: '计划列表' }).getByRole('button', { name: /合成人格计划/ }).click();
  const detail = page.getByRole('region', { name: '计划详情' });
  const plan = detail.locator(':scope > .model-control-entry');
  await plan.locator(':scope > summary').click();
  async function choose(area: Locator, value: string, text: string) {
    await area.getByLabel('人格选择', { exact: true }).selectOption(value);
    await area.getByRole('button', { name: '保存人格', exact: true }).click();
    await expect(area.getByRole('region', { name: '当前范围人格' })).toContainText(text);
  }
  await expect(plan.getByRole('region', { name: '当前范围人格' })).toContainText('合成全局导师 · 来自全局');
  await choose(plan, ids[1], '合成计划导师 · 来自计划');
  const task = detail.locator('.learning-plan-task .model-control-entry');
  await task.locator(':scope > summary').click();
  await expect(task.getByRole('region', { name: '当前范围人格' })).toContainText('合成计划导师 · 来自计划');
  await choose(task, 'none', '不用人格 · 来自任务');
  await detail.getByRole('button', { name: '开始学习', exact: true }).click();
  await expect(page.getByLabel('输入学习问题', { exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '对话配置', exact: true }).click();
  const panel = page.locator('#ai-conversation-config-panel');
  await expect(panel.getByRole('region', { name: '当前范围人格' })).toContainText('不用人格 · 来自任务');
  await choose(panel, ids[0], '合成全局导师 · 来自当前对话');
  await page.setViewportSize({ width: 390, height: 900 });
  await panel.getByRole('region', { name: '当前范围人格' }).scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: '/tmp/nautilus-persona-scopes-390.png' });
  await choose(panel, 'inherit', '不用人格 · 来自任务');
  await page.reload();
  await page.getByRole('button', { name: '对话配置', exact: true }).click();
  await expect(page.getByRole('region', { name: '当前范围人格' })).toContainText('不用人格 · 来自任务');
});
