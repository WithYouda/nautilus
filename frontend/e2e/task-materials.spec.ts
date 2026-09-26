import { expect, test } from '@playwright/test';
import { authorize } from './fact-helpers';

test('conversation materials keep versioned scope through regeneration, refresh, and purge', async ({ page }) => {
  test.setTimeout(60_000);
  await authorize(page);
  const provider = await page.request.put('/api/ai/provider', { data: {
    display_name: 'Materials mock provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1',
    model: 'mock-success', api_key: 'synthetic-materials-key', enabled: true, request_timeout_seconds: 15,
    api_protocol: 'openai_compatible',
  } });
  expect(provider.ok()).toBeTruthy();
  await page.reload();
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await page.locator('.ai-composer').getByRole('button', { name: '资料', exact: true }).click();
  const panel = page.locator('.task-materials-panel');
  await expect(panel).toBeVisible();
  await panel.getByLabel('标题').fill('合成教材');
  await panel.getByLabel('正文').fill('第一版只解释合成概念A。');
  await panel.getByRole('button', { name: '保存版本' }).click();
  await expect(panel.getByText('第 1 版 · 合成教材')).toBeVisible();
  await panel.getByLabel('使用方式').selectOption('only');
  await panel.getByRole('checkbox', { name: '第 1 版 · 合成教材' }).check();
  await page.locator('.ai-composer').getByRole('button', { name: /资料/ }).click();
  const question = page.getByLabel('输入学习问题');
  await question.fill('请依据选定资料解释合成概念A');
  const firstRequest = page.waitForRequest(request => request.url().endsWith('/messages') && request.method() === 'POST');
  await question.press('Enter');
  const first = await firstRequest;
  expect(first.postDataJSON().source_scope).toEqual({ mode: 'only', version_ids: [expect.any(String)] });
  const firstResponse = await first.response();
  const { run } = await firstResponse!.json();
  await expect.poll(async () => (await (await page.request.get(`/api/ai/conversations/${run.conversation_id}`)).json()).active_run).toBeNull();
  await expect(page.locator('.task-material-use').first()).toContainText('只依据所选资料');

  await page.locator('.ai-composer').getByRole('button', { name: /资料/ }).click();
  await panel.getByRole('button', { name: '编辑为新版本' }).click();
  await panel.getByLabel('正文').fill('第二版补充合成概念B。');
  await panel.getByRole('button', { name: '保存版本' }).click();
  await expect(panel.getByText('第 2 版 · 合成教材')).toBeVisible();
  await panel.getByRole('checkbox', { name: '第 2 版 · 合成教材' }).check();
  await expect(panel.getByRole('checkbox', { name: '第 1 版 · 合成教材' })).not.toBeChecked();
  await page.locator('.ai-composer').getByRole('button', { name: /资料/ }).click();
  const secondRequest = page.waitForRequest(request => request.url().endsWith('/messages') && request.method() === 'POST');
  await page.locator('.ai-message--assistant').last().getByRole('button', { name: '重新生成', exact: true }).click();
  const second = await secondRequest;
  expect(second.postDataJSON().source_scope.mode).toBe('only');
  expect(second.postDataJSON().source_scope.version_ids).not.toEqual(first.postDataJSON().source_scope.version_ids);
  await expect.poll(async () => (await (await page.request.get(`/api/ai/conversations/${run.conversation_id}`)).json()).active_run).toBeNull();
  await page.reload();
  await expect(page.locator('.task-material-use').last()).toContainText('第 2 版');
  await page.locator('.ai-composer').getByRole('button', { name: /资料/ }).click();
  await expect(panel.getByText('第 1 版 · 合成教材')).toBeVisible();
  await panel.getByRole('button', { name: '清除', exact: true }).click();
  await expect(panel).toContainText('原检索回答');
  await panel.getByRole('button', { name: '确认清除' }).click();
  await expect(panel.getByRole('status')).toContainText('清除状态');
  await expect(panel.getByLabel('使用方式')).toHaveValue('unspecified');
  const erased = await (await page.request.get(`/api/ai/conversations/${run.conversation_id}`)).json();
  expect(erased.messages.filter((message: { role: string; ai_run_id: string; content: string }) => message.role === 'assistant' && message.ai_run_id === run.id).every((message: { content: string }) => !message.content)).toBeTruthy();
  await page.reload();
  await page.locator('.ai-composer').getByRole('button', { name: /资料/ }).click();
  await panel.getByRole('button', { name: '查看清除状态' }).click();
  await expect(panel.getByRole('status')).toContainText('清除状态');
});
