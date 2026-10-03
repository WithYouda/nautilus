import { expect, test } from '@playwright/test';
import { authorize } from './fact-helpers';

test('settings, automatic upload references, independent network, versions and purge', async ({ page }) => {
  test.setTimeout(60_000);
  await authorize(page);
  const routes = await (await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT ?? '8012'}/openapi.json`)).json();
  expect(routes.paths['/api/preferences']).toBeTruthy();
  expect(routes.paths['/api/materials/{scope_kind}/{scope_id}/upload']).toBeTruthy();
  const provider = await page.request.put('/api/ai/provider', { data: {
    display_name: 'Materials mock provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1',
    model: 'mock-success', api_key: 'synthetic-materials-key', enabled: true, request_timeout_seconds: 15,
    api_protocol: 'openai_compatible',
  } });
  expect(provider.ok()).toBeTruthy();
  await page.reload();
  await page.getByRole('button', { name: '设置', exact: true }).click();
  const settings = page.getByRole('dialog', { name: '设置', exact: true });
  await settings.getByLabel('资料冲突默认方式').selectOption('balanced');
  await settings.getByRole('button', { name: '联网搜索：关闭' }).click();
  await page.getByRole('button', { name: /外部服务/ }).click();
  await settings.getByRole('button', { name: '保存默认设置' }).click();
  await expect(settings.getByRole('button', { name: '保存默认设置' })).toBeDisabled();
  await settings.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await expect(page.locator('.ai-composer').getByRole('button', { name: /联网搜索：Bing/ })).toBeEnabled();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  await page.locator('.ai-composer').getByRole('button', { name: '资料', exact: true }).click();
  const panel = page.locator('.task-materials-panel');
  await expect(panel.getByLabel(/上传资料/)).toBeEnabled();
  await panel.getByLabel(/上传资料/).setInputFiles({ name: '合成教材.txt', mimeType: 'text/plain', buffer: Buffer.from('第一版只解释合成概念A。') });
  await expect(panel.getByRole('checkbox', { name: '合成教材.txt · 文本资料' })).toBeChecked();
  await expect(panel.getByLabel('资料冲突时')).toHaveValue('');
  await expect(panel.getByLabel('资料冲突时')).toContainText('沿用默认（由 AI 综合判断）');
  // Unsupported files remain visible failures, without replacing the successful upload.
  await panel.getByLabel(/上传资料/).setInputFiles({ name: 'image.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('synthetic') });
  await expect(panel.getByRole('alert')).toContainText('暂不支持此文件格式');
  await page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ }).click();
  const question = page.getByLabel('输入学习问题');
  await question.fill('请参考上传资料解释合成概念A');
  const firstRequest = page.waitForRequest(request => request.url().endsWith('/messages') && request.method() === 'POST');
  await question.press('Enter');
  const first = await firstRequest;
  expect(first.postDataJSON().source_scope).toEqual({ mode: 'reference', version_ids: [expect.any(String)] });
  expect(first.postDataJSON().search.mode).toBe('external');
  const { run } = await (await first.response())!.json();
  await expect.poll(async () => (await (await page.request.get(`/api/ai/conversations/${run.conversation_id}`)).json()).active_run).toBeNull();
  await expect(page.locator('.task-material-use').first()).toContainText('由 AI 综合判断');

  await page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ }).click();
  await panel.getByText('查看当前版本和历史', { exact: true }).click();
  await panel.getByRole('button', { name: '编辑为新版本' }).click();
  await panel.getByLabel('正文').fill('第二版补充合成概念B。');
  await panel.getByRole('button', { name: '保存版本' }).click();
  await expect(panel.getByText('第 2 版 · 合成教材.txt · 当前使用')).toBeVisible();
  // Editing extracted text creates a new version; it must not acquire the old file.
  await expect(panel.getByText('此版本未保存原件', { exact: true })).toBeVisible();
  const originalDownload = page.waitForEvent('download');
  await panel.getByRole('link', { name: '下载原件：合成教材.txt' }).click();
  const downloaded = await originalDownload;
  expect(downloaded.suggestedFilename()).toBe('合成教材.txt');
  const stream = await downloaded.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
  expect(Buffer.concat(chunks).toString('utf8')).toBe('第一版只解释合成概念A。');
  await panel.getByLabel('只依据所选资料（严格范围）').click();
  await expect(panel.getByLabel('只依据所选资料（严格范围）')).toBeChecked();
  await panel.getByLabel('资料冲突时').selectOption('materials');
  await page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ }).click();
  await expect(page.locator('.ai-composer').getByRole('button', { name: /联网搜索：Bing/ })).toBeEnabled();
  const secondRequest = page.waitForRequest(request => request.url().endsWith('/messages') && request.method() === 'POST');
  await page.locator('.ai-message--assistant').last().getByRole('button', { name: '重新生成', exact: true }).click();
  const second = await secondRequest;
  expect(second.postDataJSON().source_scope.mode).toBe('only');
  expect(second.postDataJSON().source_scope.conflict_policy).toBe('materials');
  expect(second.postDataJSON().search.mode).toBe('external');
  expect(second.postDataJSON().source_scope.version_ids).not.toEqual(first.postDataJSON().source_scope.version_ids);
  await expect.poll(async () => (await (await page.request.get(`/api/ai/conversations/${run.conversation_id}`)).json()).active_run).toBeNull();
  await page.reload();
  await expect(page.locator('.task-material-use').last()).toContainText('以所选资料为准');
  await expect(page.locator('.ai-composer').getByRole('button', { name: /联网搜索：Bing/ })).toBeEnabled();
  await page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ }).click();
  await expect(panel.getByLabel('资料冲突时')).toHaveValue('materials');
  await panel.getByLabel('资料冲突时').selectOption('');
  await expect(panel.getByLabel('资料冲突时')).toContainText('沿用默认（由 AI 综合判断）');
  let purgeRequests = 0;
  page.on('request', request => { if (request.method() === 'POST' && /\/purge$/.test(request.url())) purgeRequests++; });
  await panel.evaluate(element => { element.scrollTop = element.scrollHeight; });
  await panel.getByRole('button', { name: '清除', exact: true }).click();
  const purgeDialog = page.getByRole('dialog', { name: '清除这份资料？' });
  await expect(purgeDialog).toBeVisible();
  expect(Math.abs((await purgeDialog.boundingBox())!.y + (await purgeDialog.boundingBox())!.height / 2 - (await page.evaluate(() => innerHeight)) / 2)).toBeLessThan(30);
  await purgeDialog.getByRole('button', { name: '取消' }).click();
  await expect(purgeDialog).toHaveCount(0);
  expect(purgeRequests).toBe(0);
  await expect(panel.getByRole('checkbox', { name: '合成教材.txt · 文本资料' })).toBeVisible();
  await panel.getByRole('button', { name: '清除', exact: true }).click();
  await purgeDialog.getByRole('button', { name: '取消' }).focus();
  await page.keyboard.press('Shift+Tab');
  await expect(purgeDialog.getByRole('button', { name: '确认清除' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(purgeDialog).toHaveCount(0);
  expect(purgeRequests).toBe(0);
  await page.setViewportSize({ width: 390, height: 720 });
  await panel.getByRole('button', { name: '清除', exact: true }).click();
  await expect(purgeDialog).toBeVisible();
  const mobileBox = (await purgeDialog.boundingBox())!;
  expect(mobileBox.x).toBeGreaterThanOrEqual(0);
  expect(mobileBox.x + mobileBox.width).toBeLessThanOrEqual(390);
  await expect(purgeDialog.getByRole('button', { name: '确认清除' })).toBeInViewport();
  await purgeDialog.getByRole('button', { name: '确认清除' }).click();
  await expect(panel.getByRole('status')).toContainText('资料及关联内容已清除');
  await expect(panel.getByRole('checkbox', { name: '合成教材.txt · 文本资料' })).toHaveCount(0);
  await expect(panel.getByRole('button', { name: '查看清除状态' })).toHaveCount(0);
  await expect(panel).not.toContainText('清除状态：');
  // A1 keeps invalid references until the user explicitly repairs the scope.
  await expect(panel.getByLabel('只依据所选资料（严格范围）')).toBeChecked();
  await expect(panel.getByRole('link', { name: '下载原件：合成教材.txt' })).toHaveCount(0);
  expect((await page.request.get(`/api/materials/conversation/${run.conversation_id}/versions/${first.postDataJSON().source_scope.version_ids[0]}/original`)).status()).toBe(404);
  await panel.getByRole('button', { name: '取消全部资料参考，重新选择' }).click();
  await expect(panel.getByLabel('只依据所选资料（严格范围）')).not.toBeChecked();
  const erased = await (await page.request.get(`/api/ai/conversations/${run.conversation_id}`)).json();
  expect(erased.messages.filter((message: { role: string; ai_run_id: string; content: string }) => message.role === 'assistant' && message.ai_run_id === run.id).every((message: { content: string }) => !message.content)).toBeTruthy();
  await page.reload();
  await expect(page.locator('.ai-composer').getByRole('button', { name: /联网搜索/ })).toBeEnabled();
  await page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ }).click();
  await expect(panel.getByRole('checkbox', { name: '合成教材.txt · 文本资料' })).toHaveCount(0);
  await expect(panel.getByRole('button', { name: '查看清除状态' })).toHaveCount(0);
  await expect(panel).not.toContainText('清除状态：');
});

test('partial purge stays actionable and retry completes', async ({ page }) => {
  await authorize(page);
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await expect(page.locator('.ai-composer').getByRole('button', { name: /联网搜索/ })).toBeEnabled();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  await page.locator('.ai-composer').getByRole('button', { name: '资料', exact: true }).click();
  const panel = page.locator('.task-materials-panel');
  await expect(panel.getByLabel(/上传资料/)).toBeEnabled();
  await panel.getByLabel(/上传资料/).setInputFiles({ name: '待清除.txt', mimeType: 'text/plain', buffer: Buffer.from('用于测试部分清除') });
  await expect(panel.getByRole('checkbox', { name: '待清除.txt · 文本资料' })).toBeVisible();
  await page.route('**/api/materials/**/purge', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ purge: { status: 'partial', files: [{ name: 'private-file-name.txt', status: 'failed' }], external_limits: [] } }) });
    await page.unroute('**/api/materials/**/purge');
  });
  await panel.getByRole('button', { name: '清除', exact: true }).click();
  await page.getByRole('dialog', { name: '清除这份资料？' }).getByRole('button', { name: '确认清除' }).click();
  await expect(panel.getByText('部分内容未能清除，请重试。')).toBeVisible();
  await expect(panel.getByRole('button', { name: '重试清除' })).toBeVisible();
  await expect(panel).not.toContainText('private-file-name.txt');
  await panel.getByRole('button', { name: '重试清除' }).click();
  await page.getByRole('dialog', { name: '清除这份资料？' }).getByRole('button', { name: '确认清除' }).click();
  await expect(panel.getByRole('status')).toContainText('资料及关联内容已清除');
  await expect(panel.getByRole('checkbox', { name: '待清除.txt · 文本资料' })).toHaveCount(0);
});

test('long uploaded materials and selections beyond eight survive refresh', async ({ page }) => {
  await authorize(page);
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await expect(page.locator('.ai-composer').getByRole('button', { name: /联网搜索/ })).toBeEnabled();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  await page.locator('.ai-composer').getByRole('button', { name: '资料', exact: true }).click();
  const panel = page.locator('.task-materials-panel');
  const file = panel.getByLabel(/上传资料/);
  await expect(file).toBeEnabled();
  for (let index = 0; index < 9; index++) {
    await file.setInputFiles({ name: `教材${index}.txt`, mimeType: 'text/plain', buffer: Buffer.from(index < 2 ? '完整正文'.repeat(20000) : '第九份资料也可参考') });
    await expect(panel.getByRole('checkbox', { name: `教材${index}.txt · 文本资料` })).toBeChecked();
  }
  await expect(panel.getByText(/^当前参考 9 份资料/)).toBeVisible();
  await expect(panel.getByLabel('正文')).not.toHaveAttribute('maxlength', /.+/);
  await page.reload();
  await expect(page.locator('.ai-composer').getByRole('button', { name: /联网搜索/ })).toBeEnabled();
  await page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ }).click();
  await expect(panel.getByText(/^当前参考 9 份资料/)).toBeVisible();
  for (let index = 0; index < 9; index++) await expect(panel.getByRole('checkbox', { name: `教材${index}.txt · 文本资料` })).toBeChecked();
});
