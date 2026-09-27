import { expect, test } from '@playwright/test';
import { authorize } from './fact-helpers';

test('branches an earlier learning answer into an independent conversation with inherited material', async ({ page }) => {
  test.setTimeout(60_000);
  // The trial is opened over HTTP on a WSL IP, where randomUUID is unavailable.
  await page.addInitScript(() => Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true }));
  const pageErrors: string[] = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  const routes = await (await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT ?? '8012'}/openapi.json`)).json();
  expect(routes.paths['/api/ai/conversations/{conversation_id}/branches']).toBeTruthy();
  expect(routes.paths['/api/ai/conversations/{conversation_id}/branch-map']).toBeTruthy();

  await authorize(page);
  const provider = await page.request.put('/api/ai/provider', { data: {
    display_name: 'Branch mock provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? 'http://127.0.0.1:8013/v1',
    model: 'mock-success', api_key: 'synthetic-branch-key', enabled: true, request_timeout_seconds: 15,
    api_protocol: 'openai_compatible',
  } });
  expect(provider.ok()).toBeTruthy();
  await page.reload();
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  const composer = page.getByLabel('输入学习问题');
  const materialsButton = page.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ });
  await materialsButton.click();
  const panel = page.locator('.task-materials-panel');
  await expect(panel.getByLabel(/上传资料/)).toBeEnabled();
  await panel.getByLabel(/上传资料/).setInputFiles({ name: '分支合成教材.txt', mimeType: 'text/plain', buffer: Buffer.from('合成教材只包含概念甲。') });
  await expect(panel.getByRole('checkbox', { name: '分支合成教材.txt · 文本资料' })).toBeChecked();
  await materialsButton.click();

  async function send(text: string) {
    await composer.fill(text);
    const request = page.waitForRequest(value => value.url().endsWith('/messages') && value.method() === 'POST');
    await composer.press('Enter');
    const result = await request;
    const { run } = await (await result.response())!.json();
    await expect.poll(async () => (await (await page.request.get(`/api/ai/conversations/${run.conversation_id}`)).json()).active_run).toBeNull();
    return run.conversation_id as string;
  }
  const sourceId = await send('请用资料解释合成概念甲');
  const first = await (await page.request.get(`/api/ai/conversations/${sourceId}`)).json();
  const sourceAnswer = first.messages.find((message: { role: string }) => message.role === 'assistant');
  expect(sourceAnswer?.status).toBe('complete');
  await send('继续说明合成概念甲的例子');
  const sourceBefore = await (await page.request.get(`/api/ai/conversations/${sourceId}`)).json();
  expect(sourceBefore.messages).toHaveLength(4);
  const laterMessageId = sourceBefore.messages[3].id;

  await composer.fill('这段未发送草稿要保留');
  const branchResponse = page.waitForResponse(response => response.url().endsWith(`/api/ai/conversations/${sourceId}/branches`) && response.request().method() === 'POST');
  await page.locator('.ai-message--assistant').first().getByRole('button', { name: '从这里创建独立对话' }).click();
  const created = await branchResponse;
  expect(created.status()).toBe(201);
  const branchId = (await created.json()).conversation.id as string;
  await expect(page.getByText('从另一对话分出')).toBeVisible();
  await expect(composer).toHaveValue('这段未发送草稿要保留');
  let branch = await (await page.request.get(`/api/ai/conversations/${branchId}`)).json();
  expect(branch.branch_origin).toEqual({ conversation_id: sourceId, message_id: sourceAnswer.id });
  expect(branch.messages).toHaveLength(2);
  expect(branch.messages.some((message: { id: string }) => message.id === laterMessageId)).toBe(false);
  expect(branch.messages[1].inherited_from).toEqual({ conversation_id: sourceId, message_id: sourceAnswer.id });
  expect((await (await page.request.get(`/api/ai/conversations/${sourceId}`)).json()).messages).toEqual(sourceBefore.messages);

  await materialsButton.click();
  await expect(panel.getByRole('checkbox', { name: /分支合成教材.txt/ })).toBeChecked();
  await panel.getByText('查看当前版本和历史', { exact: true }).click();
  await expect(panel.getByText(/继承（只读）/).first()).toBeVisible();
  await expect(panel.getByRole('button', { name: '编辑为新版本' })).toHaveCount(0);
  await materialsButton.click();

  const map = await (await page.request.get(`/api/ai/conversations/${branchId}/branch-map`)).json();
  expect(map.current_id).toBe(branchId);
  expect(map.nodes).toHaveLength(2);
  expect(map.nodes.find((node: { id: string }) => node.id === branchId)).toMatchObject({ parent_id: sourceId, source_id: sourceAnswer.id, available: true });
  expect(map.nodes.find((node: { id: string }) => node.id === sourceId)).toMatchObject({ parent_id: null, available: true });
  await expect(page.getByRole('dialog', { name: '分支图' })).toHaveCount(0);
  await page.getByRole('button', { name: '分支图', exact: true }).click();
  const branchMap = page.getByRole('dialog', { name: '分支图' });
  await expect(branchMap.locator('.branch-map-node')).toHaveCount(2);
  await branchMap.screenshot({ path: '/tmp/nautilus-conversation-branch-map-desktop.png' });
  const canvas = branchMap.locator('.branch-map-canvas');
  const initialView = await canvas.getAttribute('style');
  await branchMap.getByRole('button', { name: '放大', exact: true }).click();
  expect(await canvas.getAttribute('style')).not.toBe(initialView);
  await branchMap.getByRole('button', { name: '缩小' }).click();
  await branchMap.getByRole('button', { name: '适应画布' }).click();
  await branchMap.getByRole('button', { name: '编辑标题' }).click();
  await branchMap.getByLabel('修改标题').fill('合成概念甲的独立分支');
  await branchMap.getByRole('button', { name: '保存', exact: true }).click();
  await expect(branchMap.locator('.branch-map-detail-title')).toHaveText('合成概念甲的独立分支');
  expect((await (await page.request.get(`/api/ai/conversations/${branchId}/branch-map`)).json()).nodes.find((node: { id: string }) => node.id === branchId).title).toBe('合成概念甲的独立分支');
  await branchMap.getByRole('button', { name: '查看分出位置' }).click();
  await expect(branchMap).toBeHidden();
  await expect(page.locator(`#answer-${sourceAnswer.id}`)).toBeInViewport();
  await expect(page.locator(`#answer-${laterMessageId}`)).toHaveCount(0);
  await expect(composer).toHaveValue('这段未发送草稿要保留');
  await page.getByRole('button', { name: '对话历史' }).click();
  await page.getByLabel('对话列表').locator(`[data-conversation-id="${branchId}"]`).click();
  await expect(page.getByText('从另一对话分出')).toBeVisible();
  await page.reload();
  await expect(page.getByText('从另一对话分出')).toBeVisible();
  await expect(page.locator('.ai-message--assistant')).toHaveCount(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('button', { name: '返回原对话' })).toBeInViewport();
  await page.getByRole('button', { name: '分支图', exact: true }).click();
  const mobileMap = page.getByRole('dialog', { name: '分支图' });
  await expect(mobileMap.locator('.branch-map-node')).toHaveCount(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await mobileMap.screenshot({ path: '/tmp/nautilus-conversation-branch-map-390.png' });
  await page.getByRole('button', { name: '关闭分支图' }).click();
  await page.screenshot({ path: '/tmp/nautilus-branch-mobile.png' });
  await page.setViewportSize({ width: 1280, height: 800 });
  await send('在独立分支继续合成问题');
  branch = await (await page.request.get(`/api/ai/conversations/${branchId}`)).json();
  expect(branch.messages).toHaveLength(4);
  expect((await (await page.request.get(`/api/ai/conversations/${sourceId}`)).json()).messages).toHaveLength(4);
  await materialsButton.click();
  await panel.getByRole('button', { name: '清除', exact: true }).click();
  await expect(panel.getByRole('alert')).toContainText('原对话和其他分支');
  await panel.getByRole('button', { name: '确认清除' }).click();
  await expect(panel.getByRole('status')).toContainText('清除状态');
  const erasedBranch = await (await page.request.get(`/api/ai/conversations/${branchId}`)).json();
  const erasedSource = await (await page.request.get(`/api/ai/conversations/${sourceId}`)).json();
  expect(erasedBranch.messages.filter((message: { role: string }) => message.role === 'assistant').every((message: { content: string }) => !message.content)).toBe(true);
  expect(erasedSource.messages.filter((message: { role: string }) => message.role === 'assistant').every((message: { content: string }) => !message.content)).toBe(true);
  expect(pageErrors).toEqual([]);
});
