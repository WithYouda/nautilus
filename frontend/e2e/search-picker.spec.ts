import { expect, test } from '@playwright/test';
import { authorize } from './fact-helpers';

async function setProvider(page: import('@playwright/test').Page) {
  const response = await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic mock provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1',
    model: 'mock-success', api_key: 'synthetic-test-key', enabled: true, request_timeout_seconds: 15, api_protocol: 'openai_compatible',
  } });
  expect(response.ok()).toBeTruthy();
}

test('search picker lives in the composer and dismisses through every exit', async ({ page }) => {
  await authorize(page);
  await setProvider(page);
  await page.reload();
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  const composer = page.locator('.ai-composer');
  const trigger = composer.getByRole('button', { name: '联网搜索：关闭' });
  await expect(trigger).toBeVisible();
  await expect(page.locator('.ai-room-chat > .search-controls')).toHaveCount(0);
  await expect(page.getByRole('dialog', { name: '联网搜索选择' })).toHaveCount(0);

  await trigger.click();
  const picker = page.getByRole('dialog', { name: '联网搜索选择' });
  await expect(picker).toBeVisible();
  await page.screenshot({ path: '/tmp/nautilus-search-picker-desktop-open.png' });
  await trigger.click();
  await expect(picker).toHaveCount(0);
  await trigger.click();
  await picker.getByRole('button', { name: '关闭搜索选择' }).click();
  await expect(trigger).toBeFocused();
  await trigger.click();
  await page.keyboard.press('Escape');
  await expect(picker).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await trigger.click();
  await page.getByLabel('输入学习问题').click();
  await expect(picker).toHaveCount(0);

  await trigger.click();
  await picker.getByRole('button', { name: /外部服务/ }).click();
  await expect(picker).toHaveCount(0);
  await expect(composer.getByRole('button', { name: /联网搜索：/ })).toHaveAttribute('aria-label', /联网搜索：/);
  await expect(composer.getByLabel('搜索查询')).toHaveCount(0);
  await page.screenshot({ path: '/tmp/nautilus-search-picker-desktop.png' });
});

test('picker selects a service, keeps advanced filters, and fits a phone', async ({ page }) => {
  await authorize(page);
  await setProvider(page);
  const before = await (await page.request.get('/api/search/settings')).json();
  const exaId = crypto.randomUUID();
  const saved = await page.request.put('/api/search/settings', { data: {
    revision: before.revision,
    services: [{ id: exaId, kind: 'exa', name: 'Exa synthetic', options: {}, secret_updates: { api_key: 'synthetic-test-key' } }, ...before.services],
    selected_service_id: exaId,
    result_size: before.result_size, timeout_seconds: before.timeout_seconds, max_requests: before.max_requests,
  } });
  expect(saved.ok()).toBeTruthy();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  const composer = page.locator('.ai-composer');
  const trigger = composer.getByRole('button', { name: '联网搜索：关闭' });
  await trigger.click();
  const picker = page.getByRole('dialog', { name: '联网搜索选择' });
  await picker.getByRole('button', { name: /外部服务/ }).click();
  await expect(picker).toHaveCount(0);
  const active = composer.getByRole('button', { name: '联网搜索：Exa synthetic' });
  await active.click();
  await expect(picker.getByText('当前：Exa synthetic')).toBeVisible();
  await picker.getByRole('button', { name: '展开高级参数' }).click();
  await picker.getByRole('combobox', { name: /搜索类型/ }).selectOption('deep');
  await picker.getByRole('button', { name: '收起高级参数' }).click();
  await expect(picker.getByRole('combobox', { name: /搜索类型/ })).toHaveCount(0);
  await picker.getByRole('button', { name: 'Exa synthetic', exact: true }).click();
  await expect(picker).toHaveCount(0);
  await expect(active).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await active.click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: '/tmp/nautilus-search-picker-mobile.png' });
});
