import { expect, test, type Locator, type Page } from '@playwright/test';
import { authorize } from './fact-helpers';
import type { AiConversationDetail, AiProvider, ModelConfig, ModelOverride, QuestionDiscussion } from '../src/api';

test.beforeEach(async ({ page }) => {
  const schema = await (await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT ?? '8012'}/openapi.json`)).json();
  expect(schema.paths['/api/model-config/{kind}/{scope_id}']).toBeTruthy();
});

async function configure(page: Page) {
  await authorize(page);
  const response = await page.request.put('/api/ai/provider', { data: {
    display_name: '合成模型控制', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model: 'mock-success', api_key: 'synthetic-model-control-key', enabled: true, request_timeout_seconds: 15,
  } });
  expect(response.ok()).toBeTruthy();
  const { provider } = await response.json() as { provider: AiProvider };
  const added = await page.request.post(`/api/ai/providers/${provider.id}/models/manual`, { data: { model_id: 'mock-model-control-alternate', display_name: '合成备选模型' } });
  expect(added.ok()).toBeTruthy();
  const { model } = await added.json();
  await page.reload();
  return { provider, alternate: model.id as string };
}
async function getConfig(page: Page, kind: string, id: string): Promise<ModelConfig> {
  const response = await page.request.get(`/api/model-config/${kind}/${id}`);
  expect(response.ok()).toBeTruthy(); return response.json();
}
async function putConfig(page: Page, kind: string, id: string, override: ModelOverride) {
  const previous = await getConfig(page, kind, id);
  const response = await page.request.put(`/api/model-config/${kind}/${id}`, { data: { expected_revision: previous.revision, override } });
  expect(response.ok()).toBeTruthy(); return response.json() as Promise<ModelConfig>;
}
async function openEntry(locator: Locator) { await locator.locator(':scope > summary').click(); await expect(locator.getByLabel('模型配置选择')).toBeEnabled(); }
async function ordinary(page: Page, text: string) {
  const accepted = page.waitForResponse(response => /\/api\/ai\/conversations\/[^/]+\/messages$/.test(response.url()) && response.request().method() === 'POST');
  const input = page.getByLabel('输入学习问题', { exact: true });
  await input.fill(text); await input.press('Enter');
  const response = await accepted;
  return { response, payload: response.request().postDataJSON() };
}
async function waitOrdinary(page: Page, id: string): Promise<AiConversationDetail> {
  await expect.poll(async () => (await (await page.request.get(`/api/ai/conversations/${id}`)).json()).active_run, { timeout: 15_000 }).toBeNull();
  await expect(page.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  return (await page.request.get(`/api/ai/conversations/${id}`)).json();
}

test('model inheritance uses Provider timeout; ordinary only-once, history, conflict and restore on mobile', async ({ page }) => {
  test.setTimeout(90_000);
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  const { provider, alternate } = await configure(page);
  const setup = await page.request.post('/api/learning/setup/confirm', { data: {
    original_intent: '合成目标：模型控制', goal_title: '合成模型目标', plan_title: '合成模型计划', action_title: '合成模型任务', context_key: 'model-control',
    object_description: '合成对象', behavior: '解释一个例子', outcome_context_key: 'model-control', stop_conditions: '解释完一个例子', idempotency_key: crypto.randomUUID(),
  } });
  expect(setup.ok()).toBeTruthy(); const linked = await setup.json();
  await page.getByRole('button', { name: '学习计划', exact: true }).click();
  await page.getByRole('navigation', { name: '计划列表' }).getByRole('button', { name: /合成模型计划/ }).click();
  const detail = page.getByRole('region', { name: '计划详情' });
  const plan = detail.locator(':scope > .model-control-entry'); await openEntry(plan);
  await expect(plan.getByLabel('模型配置超时')).toHaveCount(0);
  await plan.getByLabel('模型配置选择').selectOption(`${provider.id}::${alternate}`);
  await plan.getByRole('button', { name: '保存配置', exact: true }).click();
  await expect.poll(async () => (await getConfig(page, 'plan', linked.plan_id)).sources.model?.kind).toBe('plan');
  const task = detail.locator('.learning-plan-task .model-control-entry'); await openEntry(task);
  await expect(task.getByLabel('模型配置超时')).toHaveCount(0);
  await task.getByRole('button', { name: '保存配置', exact: true }).click();
  await expect.poll(async () => (await getConfig(page, 'task', linked.action_id)).effective.timeout_seconds).toBe(15);
  expect((await getConfig(page, 'task', linked.action_id)).sources).toMatchObject({ model: { kind: 'plan' }, timeout: { kind: 'global' } });
  await detail.getByRole('button', { name: '开始学习', exact: true }).click();
  await expect(page.getByLabel('输入学习问题', { exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '对话配置', exact: true }).click();
  const panel = page.locator('#ai-conversation-config-panel');
  await expect(panel).toContainText('来自计划'); await expect(panel).toContainText('来自提供方默认');
  await expect(panel.getByLabel('模型配置超时')).toHaveCount(0);
  await expect(panel.getByLabel('模型配置选择')).toBeEnabled();
  const session = JSON.parse(await page.evaluate(() => sessionStorage.getItem('nautilus.ai.learning-room')) ?? '{}'); const id = session.conversationId;
  expect(id).toBeTruthy();
  await panel.getByRole('button', { name: '仅本次', exact: true }).click();
  await panel.getByLabel('模型配置选择').selectOption(`${provider.id}::${provider.default_model_id}`);
  await panel.getByLabel('模型配置超时').fill('42');
  await panel.getByRole('button', { name: '用于本次', exact: true }).click();
  await expect(panel).toContainText('仅本次覆盖已准备');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.getByRole('button', { name: '对话配置', exact: true }).click();
  const first = await ordinary(page, '合成模型控制第一次提问'); expect(first.response.ok()).toBeTruthy();
  expect(first.payload.model_override).toMatchObject({ model: { provider_model_id: provider.default_model_id }, timeout_seconds: 42 });
  const saved = await waitOrdinary(page, id); const answer = saved.messages.at(-1)!;
  expect(answer.model_config).toMatchObject({ model_id: 'mock-success', timeout_seconds: 42, sources: { model: { kind: 'run' }, timeout: { kind: 'run' } } });
  const history = page.locator(`#answer-${answer.id} .model-config-history`);
  await expect(history).not.toHaveAttribute('open'); await history.locator('summary').click(); await expect(history).toContainText('42 秒');
  expect((await getConfig(page, 'conversation', id)).override).toMatchObject({ model: null, timeout_seconds: null });
  await page.getByRole('button', { name: '对话配置', exact: true }).click(); await expect(panel).not.toContainText('仅本次覆盖已准备');
  await panel.getByRole('button', { name: '当前对话', exact: true }).click();
  await expect(panel.getByLabel('模型配置超时')).toHaveCount(0);
  await panel.getByLabel('模型配置选择').selectOption(`${provider.id}::${provider.default_model_id}`);
  await panel.getByRole('button', { name: '保存配置', exact: true }).click();
  await expect.poll(async () => (await getConfig(page, 'conversation', id)).sources.model?.kind).toBe('conversation');
  await page.reload(); await expect(page.getByLabel('输入学习问题', { exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '对话配置', exact: true }).click(); await expect(panel).toContainText('15 秒');
  await panel.getByRole('button', { name: '恢复继承', exact: true }).click(); await expect(panel).toContainText('来自计划');
  await page.getByRole('button', { name: '对话配置', exact: true }).click();
  await putConfig(page, 'task', linked.action_id, { model: { provider_profile_id: provider.id, provider_model_id: provider.default_model_id! } });
  const stale = await ordinary(page, '合成旧配置拒绝'); expect(stale.response.status()).toBe(409);
  await expect(page.getByRole('alert').filter({ hasText: /配置/ }).first()).toBeVisible();
  const after = await waitOrdinary(page, id); expect(after.messages).toHaveLength(saved.messages.length);
  await expect(page.getByLabel('输入学习问题', { exact: true })).toHaveValue('合成旧配置拒绝');
  expect(errors).toEqual([]);
});

test('unknown acceptance replays the same ordinary override and request number after provider settings change', async ({ page }) => {
  test.setTimeout(60_000);
  const { provider, alternate } = await configure(page);
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  await page.getByRole('button', { name: '对话配置', exact: true }).click();
  const panel = page.locator('#ai-conversation-config-panel'); await expect(panel.getByLabel('模型配置选择')).toBeEnabled();
  await panel.getByRole('button', { name: '仅本次', exact: true }).click();
  await panel.getByLabel('模型配置选择').selectOption(`${provider.id}::${alternate}`);
  await panel.getByLabel('模型配置超时').fill('27'); await panel.getByRole('button', { name: '用于本次', exact: true }).click();
  await expect(panel).toContainText('仅本次覆盖已准备');
  await page.getByRole('button', { name: '对话配置', exact: true }).click();
  const requests: Record<string, unknown>[] = []; let drop = true;
  await page.route('**/api/ai/conversations/*/messages', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    requests.push(route.request().postDataJSON());
    const response = await route.fetch();
    if (drop) { drop = false; await route.abort('failed'); } else await route.fulfill({ response });
  });
  const input = page.getByLabel('输入学习问题', { exact: true });
  await input.fill('合成未知发送结果'); await input.press('Enter');
  await expect.poll(() => requests.length).toBe(1);
  await expect(input).toHaveValue('合成未知发送结果');
  await expect(input).toBeEnabled();
  const stored = JSON.parse(await page.evaluate(() => sessionStorage.getItem('nautilus.ai.learning-room')) ?? '{}');
  await putConfig(page, 'conversation', stored.conversationId, { model: { provider_profile_id: provider.id, provider_model_id: provider.default_model_id! } });
  expect((await page.request.patch(`/api/ai/providers/${provider.id}`, { data: { request_timeout_seconds: 44 } })).ok()).toBeTruthy();
  await input.press('Enter'); await expect.poll(() => requests.length).toBe(2);
  expect(requests[1].client_message_id).toBe(requests[0].client_message_id);
  expect(requests[1].model_override).toEqual(requests[0].model_override);
  expect(requests[1].model_config_token).toBe(requests[0].model_config_token);
  const saved = await waitOrdinary(page, stored.conversationId); expect(saved.messages).toHaveLength(2);
  expect(saved.messages.at(-1)!.model_config).toMatchObject({ model_id: 'mock-model-control-alternate', timeout_seconds: 27 });
});

test('an unconfirmed request keeps its model override and number across refresh before retry', async ({ page }) => {
  test.setTimeout(60_000);
  const { provider, alternate } = await configure(page);
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  await page.getByRole('button', { name: '对话配置', exact: true }).click();
  const panel = page.locator('#ai-conversation-config-panel'); await expect(panel.getByLabel('模型配置选择')).toBeEnabled();
  await panel.getByRole('button', { name: '仅本次', exact: true }).click();
  await panel.getByLabel('模型配置选择').selectOption(`${provider.id}::${alternate}`);
  await panel.getByLabel('模型配置超时').fill('29'); await panel.getByRole('button', { name: '用于本次', exact: true }).click();
  await expect(panel).toContainText('仅本次覆盖已准备');
  await page.getByRole('button', { name: '对话配置', exact: true }).click();
  let unsent: Record<string, unknown> | null = null;
  await page.route('**/api/ai/conversations/*/messages', async route => {
    if (route.request().method() === 'POST') { unsent = route.request().postDataJSON(); await route.abort('failed'); }
    else await route.continue();
  });
  const input = page.getByLabel('输入学习问题', { exact: true });
  await input.fill('合成刷新后的原问题'); await input.press('Enter');
  await expect(input).toHaveValue('合成刷新后的原问题');
  await expect.poll(() => unsent).not.toBeNull();
  const stored = JSON.parse(await page.evaluate(() => sessionStorage.getItem('nautilus.ai.learning-room')) ?? '{}');
  await page.unroute('**/api/ai/conversations/*/messages'); await page.reload();
  await expect(input).toBeEnabled();
  await expect(page.getByRole('alert').filter({ hasText: '上次发送结果尚未确认' })).toBeVisible();
  const retried = await ordinary(page, '合成刷新后的原问题'); expect(retried.response.ok()).toBeTruthy();
  expect(retried.payload.client_message_id).toBe((unsent as unknown as Record<string, unknown>).client_message_id);
  expect(retried.payload.model_override).toEqual((unsent as unknown as Record<string, unknown>).model_override);
  const saved = await waitOrdinary(page, stored.conversationId); expect(saved.messages).toHaveLength(2);
  expect(saved.messages.at(-1)!.model_config).toMatchObject({ model_id: 'mock-model-control-alternate', timeout_seconds: 29 });
});

test('provider and image settings refresh effective configuration without a failed send, with an actionable unavailable notice', async ({ page }) => {
  test.setTimeout(60_000);
  const { provider, alternate } = await configure(page);
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  await page.getByRole('button', { name: '对话配置', exact: true }).click();
  const panel = page.locator('#ai-conversation-config-panel'); await expect(panel.getByLabel('模型配置选择')).toBeEnabled();
  await expect(panel).toContainText('15 秒');
  await panel.getByRole('button', { name: '仅本次', exact: true }).click();
  await panel.getByLabel('模型配置选择').selectOption(`${provider.id}::${alternate}`);
  await panel.getByRole('button', { name: '用于本次', exact: true }).click();
  await expect(panel).toContainText('仅本次覆盖已准备');
  await page.getByRole('button', { name: '对话配置', exact: true }).click();
  await page.getByRole('button', { name: '设置', exact: true }).click();
  await page.getByRole('button', { name: '打开提供方设置', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'AI 提供方设置' });
  await dialog.getByLabel('超时（秒）', { exact: true }).fill('24');
  await dialog.getByRole('button', { name: '保存配置', exact: true }).click();
  await expect(dialog.getByText('配置已保存。建议连接测试通过后再开始对话。', { exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: '关闭 AI 提供方设置', exact: true }).click();
  const settings = page.getByRole('dialog', { name: '设置' });
  if (await settings.isVisible()) await settings.getByRole('button', { name: '关闭设置', exact: true }).click();
  await page.getByRole('button', { name: '对话配置', exact: true }).click();
  await expect(panel).toContainText('24 秒'); await expect(panel).toContainText('仅本次覆盖已准备');
  await expect(panel).toContainText('合成备选模型');
  const changed = await page.request.put(`/api/ai/providers/${provider.id}/models/${alternate}/image-capability`, { data: { supports_image_input: true } });
  expect(changed.ok()).toBeTruthy();
  const previewResponses = page.waitForResponse(response => response.url().endsWith('/preview') && response.request().method() === 'POST');
  await page.evaluate(() => window.dispatchEvent(new Event('nautilus:image-settings-changed')));
  expect((await previewResponses).ok()).toBeTruthy();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: '/tmp/nautilus-model-control-mobile.png', fullPage: true });
  await page.getByRole('button', { name: '对话配置', exact: true }).click();
  expect((await page.request.patch(`/api/ai/providers/${provider.id}`, { data: { enabled: false } })).ok()).toBeTruthy();
  await page.evaluate(() => window.dispatchEvent(new Event('nautilus:model-settings-changed')));
  const notice = page.getByRole('alert').filter({ hasText: /已停用/ });
  await expect(notice).toBeVisible(); await notice.getByRole('button', { name: '模型配置', exact: true }).click();
  await expect(panel).toBeVisible(); await expect(page.getByLabel('输入学习问题', { exact: true })).toBeDisabled();
});

test('discussion controls its own model and exposes saved per-answer history after refresh', async ({ page }) => {
  test.setTimeout(90_000);
  const { provider, alternate } = await configure(page);
  await page.getByRole('button', { name: '学习首页', exact: true }).click();
  if (await (await page.request.get('/api/learning/return-review')).json()) await page.getByRole('button', { name: '创建', exact: true }).click();
  await page.getByLabel('学习目标', { exact: true }).fill('合成目标：讨论模型控制');
  await page.getByRole('button', { name: '我想自己安排', exact: true }).click();
  await page.getByLabel('现在先做什么', { exact: true }).fill('合成讨论模型任务');
  await page.getByRole('button', { name: '确认这份学习安排', exact: true }).click();
  await page.getByRole('button', { name: '进入学习室并开始这项任务', exact: true }).click();
  await expect(page.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '进入验证', exact: true }).click();
  await page.getByRole('button', { name: '开始验证', exact: true }).click();
  await page.getByPlaceholder('写出你的判断、过程或结果').fill('合成作答：定位并检查边界。');
  await page.getByRole('button', { name: '保存作答并验证', exact: true }).click();
  await page.getByRole('region', { name: '验证回看' }).getByRole('article', { name: '第 1 题回看' }).getByRole('button', { name: '讨论这道题', exact: true }).click();
  const room = page.getByRole('region', { name: '题目学习室' });
  const entry = room.locator('.model-control-entry'); await openEntry(entry);
  await expect(entry.getByLabel('模型配置超时')).toHaveCount(0);
  await entry.getByLabel('模型配置选择').selectOption(`${provider.id}::${alternate}`);
  await entry.getByRole('button', { name: '保存配置', exact: true }).click();
  const id = new URL(page.url()).searchParams.get('discussion')!;
  await expect.poll(async () => (await getConfig(page, 'discussion', id)).sources.model?.kind).toBe('discussion');
  await entry.getByRole('button', { name: '仅本次', exact: true }).click();
  await entry.getByLabel('模型配置超时').fill('38'); await entry.getByRole('button', { name: '用于本次', exact: true }).click();
  await expect(entry).toContainText('仅本次覆盖已准备');
  const input = room.getByLabel('继续提问或回答拓展问题');
  const accepted = page.waitForResponse(response => response.url().endsWith(`/api/learning/discussions/${id}/messages`) && response.request().method() === 'POST');
  await input.fill('合成讨论模型提问'); await input.press('Enter');
  const response = await accepted; expect(response.ok()).toBeTruthy();
  expect(response.request().postDataJSON().model_override).toEqual({ model: null, timeout_seconds: 38 });
  await expect.poll(async () => {
    const data: QuestionDiscussion = await (await page.request.get(`/api/learning/discussions/${id}`)).json();
    return data.turns.at(-1)?.status;
  }, { timeout: 15_000 }).toBe('succeeded');
  await expect(entry).not.toContainText('仅本次覆盖已准备');
  await page.reload(); await expect(room.getByLabel('继续提问或回答拓展问题')).toBeEnabled();
  const history = room.locator('.model-config-history'); await history.locator('summary').click();
  await expect(history).toContainText('合成备选模型'); await expect(history).toContainText('38 秒');
  await openEntry(room.locator('.model-control-entry')); await expect(room.locator('.model-control-entry')).toContainText('15 秒');
  await expect(room.locator('.model-control-entry')).toContainText('来自提供方默认');
  await room.locator('.model-control-entry').getByRole('button', { name: '恢复继承', exact: true }).click();
  await expect.poll(async () => (await getConfig(page, 'discussion', id)).sources.model?.kind).not.toBe('discussion');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
