import { expect, test, type Page } from '@playwright/test';
import { authorize } from './fact-helpers';
import type { AiConversationDetail, AiProvider, ModelConfig, ModelOverride, QuestionDiscussion, ReasoningSupport } from '../src/api';

test.beforeEach(async ({ page }) => {
  const schema = await (await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT ?? '8012'}/openapi.json`)).json();
  expect(schema.paths['/api/ai/providers/{provider_id}/models/{model_id}/reasoning-support']).toBeTruthy();
  expect(schema.paths['/api/model-config/global/default/reasoning']).toBeTruthy();
});
async function declare(page: Page, provider: AiProvider, modelId: string, profile = 'openai_gpt6') {
  const path = `/api/ai/providers/${provider.id}/models/${modelId}/reasoning-support`;
  const before = await (await page.request.get(path)).json() as ReasoningSupport;
  const response = await page.request.put(path, { data: { expected_revision: before.revision, profile_id: profile } });
  expect(response.ok()).toBeTruthy();
}
async function configure(page: Page, model = 'mock-success') {
  await authorize(page);
  const response = await page.request.put('/api/ai/provider', { data: {
    display_name: '合成思考控制', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL, model,
    api_key: 'synthetic-reasoning-control-key', enabled: true, request_timeout_seconds: 15,
  } });
  expect(response.ok()).toBeTruthy(); const { provider } = await response.json() as { provider: AiProvider };
  await declare(page, provider, provider.default_model_id!); await page.reload();
  return provider;
}
async function addModel(page: Page, provider: AiProvider, modelId: string, displayName: string, profile?: string) {
  const response = await page.request.post(`/api/ai/providers/${provider.id}/models/manual`, { data: { model_id: modelId, display_name: displayName } });
  expect(response.ok()).toBeTruthy(); const { model } = await response.json();
  if (profile) await declare(page, provider, model.id, profile);
  return model.id as string;
}
async function config(page: Page, kind: string, id: string): Promise<ModelConfig> {
  const response = await page.request.get(`/api/model-config/${kind}/${id}`); expect(response.ok()).toBeTruthy(); return response.json();
}
async function save(page: Page, kind: string, id: string, override: ModelOverride) {
  const before = await config(page, kind, id);
  const response = await page.request.put(`/api/model-config/${kind}/${id}`, { data: { expected_revision: before.revision, override } });
  expect(response.ok()).toBeTruthy(); return response.json() as Promise<ModelConfig>;
}
async function currentId(page: Page) { return JSON.parse(await page.evaluate(() => sessionStorage.getItem('nautilus.ai.learning-room')) ?? '{}').conversationId as string; }
async function room(page: Page) { await page.getByRole('button', { name: '学习室', exact: true }).click(); await page.getByRole('button', { name: '新建对话', exact: true }).click(); }
const quick = (page: Page) => page.getByRole('button', { name: '思考设置', exact: true });
const popup = (page: Page) => page.getByRole('dialog', { name: '思考设置', exact: true });
async function open(page: Page) { await expect(quick(page)).toBeEnabled(); await quick(page).click(); await expect(popup(page).getByRole('button', { name: '当前对话', exact: true })).toBeEnabled(); }
async function pick(page: Page, label: string, once = false) {
  await open(page); if (once) await popup(page).getByRole('button', { name: '仅本次', exact: true }).click();
  await popup(page).getByRole('button', { name: label, exact: true }).click(); await expect(popup(page)).toHaveCount(0);
}
async function send(page: Page, text: string) {
  const accepted = page.waitForResponse(response => /\/api\/ai\/conversations\/[^/]+\/messages$/.test(response.url()) && response.request().method() === 'POST');
  const input = page.getByLabel('输入学习问题', { exact: true }); await input.fill(text); await input.press('Enter');
  const response = await accepted; expect(response.ok()).toBeTruthy(); return response;
}
async function finished(page: Page, id: string): Promise<AiConversationDetail> {
  await expect.poll(async () => (await (await page.request.get(`/api/ai/conversations/${id}`)).json()).active_run, { timeout: 20_000 }).toBeNull();
  await expect(page.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  return (await page.request.get(`/api/ai/conversations/${id}`)).json();
}

test('quick reasoning prepares a conversation, persists separately, changes next send during generation, and keeps history', async ({ page }) => {
  test.setTimeout(90_000); await configure(page, 'mock-slow'); await room(page);
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  const input = page.getByLabel('输入学习问题', { exact: true }); await input.fill('合成思考控制原草稿');
  await open(page); const first = await currentId(page); expect(first).toBeTruthy();
  await page.keyboard.press('Escape'); await expect(quick(page)).toBeFocused(); await expect(input).toHaveValue('合成思考控制原草稿');
  await pick(page, '高'); expect((await config(page, 'conversation', first)).override.reasoning).toEqual({ mode: 'effort', effort: 'high' });
  const accepted = await send(page, '合成运行冻结检查');
  await expect(page.getByRole('button', { name: '取消生成', exact: true })).toBeVisible();
  await expect(quick(page)).toBeEnabled(); await pick(page, '低');
  const saved = await finished(page, first); const answer = saved.messages.at(-1)!;
  expect(accepted.request().postDataJSON().model_override).toBeNull();
  expect(answer.model_config).toMatchObject({ reasoning: { mode: 'effort', effort: 'high' }, reasoning_parameters: { reasoning_effort: 'high' }, sources: { reasoning: { kind: 'conversation' } } });
  expect((await config(page, 'conversation', first)).override.reasoning).toEqual({ mode: 'effort', effort: 'low' });
  const history = page.locator(`#answer-${answer.id} .model-config-history`); await history.locator(':scope > summary').click();
  await expect(history).toContainText('思考 高'); const parameters = history.locator('.reasoning-parameters'); await expect(parameters).not.toHaveAttribute('open');
  await parameters.locator('summary').click(); await expect(parameters).toContainText('reasoning_effort');
  await page.getByRole('button', { name: '新建对话', exact: true }).click(); await pick(page, '中'); const second = await currentId(page); expect(second).not.toBe(first);
  await page.getByRole('button', { name: '对话历史', exact: true }).click(); await page.locator(`[data-conversation-id="${first}"] .ai-history-select`).click();
  await expect(quick(page)).toContainText('低'); expect((await config(page, 'conversation', second)).override.reasoning).toEqual({ mode: 'effort', effort: 'medium' });
  await pick(page, '恢复继承'); expect((await config(page, 'conversation', first)).override.reasoning).toBeNull(); await expect(quick(page)).toContainText('模型默认');
  await open(page); await page.screenshot({ path: '/tmp/nautilus-reasoning-quick-desktop.png', fullPage: true }); await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 390, height: 844 }); await open(page);
  const bounds = await popup(page).boundingBox(); expect(bounds).not.toBeNull(); expect(bounds!.x).toBeGreaterThanOrEqual(0); expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390); expect(bounds!.y).toBeGreaterThanOrEqual(0); expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(844);
  await page.keyboard.press('ArrowDown'); expect(await popup(page).evaluate(node => node.contains(document.activeElement))).toBeTruthy();
  await page.screenshot({ path: '/tmp/nautilus-reasoning-quick-mobile.png', fullPage: true }); await page.keyboard.press('Escape'); await expect(quick(page)).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy(); expect(errors).toEqual([]);
});

test('one-run reasoning preserves model and timeout, clears only reasoning, and is consumed after failed generation', async ({ page }) => {
  test.setTimeout(60_000); const provider = await configure(page); const failure = await addModel(page, provider, 'mock-error', '合成失败模型', 'qwen38');
  await page.reload(); await room(page); await pick(page, '高'); const id = await currentId(page);
  await page.getByRole('button', { name: '对话配置', exact: true }).click(); const panel = page.locator('#ai-conversation-config-panel');
  await panel.getByRole('button', { name: '仅本次', exact: true }).click(); await panel.getByLabel('模型配置选择').selectOption(`${provider.id}::${failure}`); await panel.getByLabel('模型配置超时').fill('42');
  await panel.getByLabel('思考设置', { exact: true }).selectOption('default');
  await panel.getByRole('button', { name: '用于本次', exact: true }).click(); await expect(panel).toContainText('仅本次覆盖已准备'); await page.getByRole('button', { name: '对话配置', exact: true }).click();
  await open(page); await expect(popup(page).getByRole('button', { name: '最高', exact: true })).toBeVisible(); await popup(page).getByRole('button', { name: '中', exact: true }).click();
  await open(page); await popup(page).getByRole('button', { name: '仅本次', exact: true }).click(); await expect(popup(page).getByRole('button', { name: '最高', exact: true })).toHaveCount(0); await page.keyboard.press('Escape');
  await pick(page, '低', true); await expect(quick(page)).toContainText('低 · 本次');
  await pick(page, '恢复继承', true); await expect(quick(page)).toContainText('中');
  await pick(page, '超高', true);
  const accepted = await send(page, '合成失败运行仍消耗一次覆盖');
  expect(accepted.request().postDataJSON().model_override).toMatchObject({ model: { provider_model_id: failure }, timeout_seconds: 42, reasoning: { mode: 'effort', effort: 'xhigh' } });
  const saved = await finished(page, id); expect(saved.messages.at(-1)!.status).toBe('failed'); expect(saved.messages.at(-1)!.model_config).toMatchObject({ reasoning: { mode: 'effort', effort: 'xhigh' }, timeout_seconds: 42 });
  await expect(quick(page)).toContainText('中'); expect((await config(page, 'conversation', id)).override.reasoning).toEqual({ mode: 'effort', effort: 'medium' });
  await page.getByRole('button', { name: '对话配置', exact: true }).click(); await expect(panel).not.toContainText('仅本次覆盖已准备');
  await page.getByRole('button', { name: '对话配置', exact: true }).click(); await pick(page, '最高');
  const input = page.getByLabel('输入学习问题', { exact: true }); await input.fill('合成兼容性原草稿');
  await page.getByRole('button', { name: '对话配置', exact: true }).click(); await panel.getByRole('button', { name: '当前对话', exact: true }).click(); await panel.getByLabel('模型配置选择').selectOption(`${provider.id}::${failure}`);
  await expect(panel.getByLabel('思考设置', { exact: true })).toHaveValue('effort:max'); await panel.getByRole('button', { name: '保存配置', exact: true }).click(); await expect(panel).toContainText('当前模型不支持这个思考设置');
  await expect(input).toHaveValue('合成兼容性原草稿'); expect((await config(page, 'conversation', id)).override.model).toBeNull();
});

test('unknown acceptance retries the original reasoning payload after another setting changes', async ({ page }) => {
  test.setTimeout(60_000); await configure(page); await room(page); await pick(page, '高'); await pick(page, '低', true); const id = await currentId(page);
  const requests: Record<string, unknown>[] = []; let drop = true;
  await page.route('**/api/ai/conversations/*/messages', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    requests.push(route.request().postDataJSON()); const response = await route.fetch();
    if (drop) { drop = false; await route.abort('failed'); } else await route.fulfill({ response });
  });
  const input = page.getByLabel('输入学习问题', { exact: true }); await input.fill('合成思考未知接受'); await input.press('Enter');
  await expect(input).toHaveValue('合成思考未知接受'); await expect(quick(page)).toBeDisabled();
  await save(page, 'conversation', id, { reasoning: { mode: 'effort', effort: 'max' } });
  await input.press('Enter'); await expect.poll(() => requests.length).toBe(2);
  expect(requests[1].client_message_id).toBe(requests[0].client_message_id); expect(requests[1].model_override).toEqual(requests[0].model_override); expect(requests[1].model_config_token).toBe(requests[0].model_config_token);
  const saved = await finished(page, id); expect(saved.messages).toHaveLength(2); expect(saved.messages.at(-1)!.model_config).toMatchObject({ reasoning: { mode: 'effort', effort: 'low' } });
});

test('unknown aliases use explicit model specs and literal budgets; global reasoning saves preserve Provider defaults', async ({ page }) => {
  test.setTimeout(60_000); const provider = await configure(page); const alias = await addModel(page, provider, 'synthetic-reasoning-alias', '合成未知别名'); await room(page); await open(page); const id = await currentId(page); await page.keyboard.press('Escape');
  await save(page, 'conversation', id, { model: { provider_profile_id: provider.id, provider_model_id: alias }, reasoning: { mode: 'default' } });
  await page.evaluate(() => window.dispatchEvent(new Event('nautilus:model-settings-changed'))); await open(page);
  await expect(popup(page)).toContainText('思考规格尚未确认'); await expect(popup(page).getByRole('button', { name: '高', exact: true })).toHaveCount(0);
  const statsUrl = `${process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL!.replace(/\/v1$/, '')}/__mock__/stats`; const beforeStats = await (await page.request.get(statsUrl)).json();
  await popup(page).getByRole('button', { name: '配置模型思考规格', exact: true }).click(); const declaration = page.getByRole('dialog', { name: '模型思考规格', exact: true });
  await declaration.getByLabel('模型思考规格', { exact: true }).selectOption('qwen_budget'); await declaration.getByRole('button', { name: '保存思考规格', exact: true }).click(); await expect(declaration).toContainText('思考规格已保存');
  expect(await (await page.request.get(statsUrl)).json()).toEqual(beforeStats);
  await declaration.getByRole('button', { name: '关闭模型思考规格', exact: true }).click(); await expect(popup(page).getByRole('button', { name: '自定义思考预算', exact: true })).toBeEnabled();
  await popup(page).getByRole('button', { name: '自定义思考预算', exact: true }).click(); await popup(page).getByLabel('思考预算（Token）').fill('256'); await expect(popup(page).getByLabel('预算模式响应投入')).toHaveCount(0); await popup(page).getByRole('button', { name: '使用这个预算', exact: true }).click();
  await expect(quick(page)).toContainText('256 Token'); await send(page, '合成预算思考问题'); const saved = await finished(page, id);
  expect(saved.messages.at(-1)!.model_config).toMatchObject({ reasoning: { mode: 'budget', budget_tokens: 256 }, reasoning_parameters: { enable_thinking: true, thinking_budget: 256 } });
  const providerBefore = (await (await page.request.get('/api/ai/provider')).json()).provider as AiProvider;
  await page.getByRole('button', { name: '设置', exact: true }).click(); const settings = page.getByRole('dialog', { name: '设置', exact: true }); const section = settings.locator('.reasoning-settings'); await expect(section).not.toHaveAttribute('open'); await section.locator(':scope > summary').click();
  await section.getByLabel('思考设置', { exact: true }).selectOption('effort:low'); await section.getByRole('button', { name: '保存全局思考默认', exact: true }).click(); await expect(section).toContainText('全局思考默认已保存');
  const providerAfter = (await (await page.request.get('/api/ai/provider')).json()).provider as AiProvider;
  expect(providerAfter.default_model_id).toBe(providerBefore.default_model_id); expect(providerAfter.config_version).toBe(providerBefore.config_version); expect(providerAfter.request_timeout_seconds).toBe(providerBefore.request_timeout_seconds);
  expect((await config(page, 'global', 'default')).effective.reasoning).toEqual({ mode: 'effort', effort: 'low' });
});

test('discussion quick reasoning persists, one-run overrides are consumed, and history survives refresh', async ({ page }) => {
  test.setTimeout(90_000); await configure(page);
  await page.getByRole('button', { name: '学习首页', exact: true }).click(); if (await (await page.request.get('/api/learning/return-review')).json()) await page.getByRole('button', { name: '创建', exact: true }).click();
  await page.getByLabel('学习目标', { exact: true }).fill('合成目标：讨论思考控制'); await page.getByRole('button', { name: '我想自己安排', exact: true }).click(); await page.getByLabel('现在先做什么', { exact: true }).fill('合成讨论思考任务'); await page.getByRole('button', { name: '确认这份学习安排', exact: true }).click(); await page.getByRole('button', { name: '进入学习室并开始这项任务', exact: true }).click();
  await expect(page.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0); await page.getByRole('button', { name: '进入验证', exact: true }).click(); await page.getByRole('button', { name: '开始验证', exact: true }).click(); await page.getByPlaceholder('写出你的判断、过程或结果').fill('合成作答：核对边界。'); await page.getByRole('button', { name: '保存作答并验证', exact: true }).click(); await page.getByRole('region', { name: '验证回看' }).getByRole('article', { name: '第 1 题回看' }).getByRole('button', { name: '讨论这道题', exact: true }).click();
  await pick(page, '高'); const id = new URL(page.url()).searchParams.get('discussion')!; await pick(page, '低', true);
  const accepted = page.waitForResponse(response => response.url().endsWith(`/api/learning/discussions/${id}/messages`) && response.request().method() === 'POST'); const room = page.getByRole('region', { name: '题目学习室' }); const input = room.getByLabel('继续提问或回答拓展问题'); await input.fill('合成讨论思考问题'); await input.press('Enter'); const response = await accepted; expect(response.ok()).toBeTruthy(); expect(response.request().postDataJSON().model_override.reasoning).toEqual({ mode: 'effort', effort: 'low' });
  await expect.poll(async () => (await (await page.request.get(`/api/learning/discussions/${id}`)).json() as QuestionDiscussion).turns.at(-1)?.status, { timeout: 15_000 }).toBe('succeeded');
  await expect(quick(page)).toContainText('高'); expect((await config(page, 'discussion', id)).override.reasoning).toEqual({ mode: 'effort', effort: 'high' });
  await page.reload(); await expect(input).toBeEnabled(); const history = room.locator('.model-config-history'); await history.locator(':scope > summary').click(); await expect(history).toContainText('思考 低');
  await page.setViewportSize({ width: 390, height: 844 }); await open(page); const bounds = await popup(page).boundingBox(); expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390); await page.screenshot({ path: '/tmp/nautilus-reasoning-discussion-mobile.png', fullPage: true }); await page.keyboard.press('Escape');
});
