import { expect, test } from '@playwright/test';
import { authorize } from './fact-helpers';

test('collapsed graph hides deleted nodes and zooms around the pointer', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await authorize(page);
  expect((await page.request.put('/api/ai/provider', { data: {
    display_name: 'Graph display mock', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model: 'mock-success', api_key: 'synthetic-map-key', enabled: true, request_timeout_seconds: 15,
    api_protocol: 'openai_compatible',
  } })).ok()).toBeTruthy();
  await page.reload();
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  await page.getByLabel('输入学习问题').fill('用于关系图的合成根问题');
  const posted = page.waitForResponse(response => response.url().endsWith('/messages') && response.request().method() === 'POST');
  await page.getByLabel('输入学习问题').press('Enter');
  const { run } = await (await posted).json();
  const root = run.conversation_id;
  await expect.poll(async () => (await (await page.request.get(`/api/ai/conversations/${root}`)).json()).active_run).toBeNull();
  async function branch(cid: string, answer: string, key: string) {
    const response = await page.request.post(`/api/ai/conversations/${cid}/branches`, { data: { message_id: answer, request_key: key } });
    expect(response.status()).toBe(201);
    return response.json();
  }
  const middle = await branch(root, run.response_message_id, 'middle');
  const leaf = await branch(root, run.response_message_id, 'deleted-leaf');
  const child = await branch(middle.conversation.id, middle.messages.find((message: { role: string }) => message.role === 'assistant').id, 'surviving-child');
  expect((await page.request.patch(`/api/ai/conversations/${child.conversation.id}`, { data: { title: '保留的后续讨论' } })).ok()).toBeTruthy();
  for (const id of [middle.conversation.id, leaf.conversation.id]) expect((await page.request.delete(`/api/ai/conversations/${id}`)).status()).toBe(204);
  const dialog = page.getByRole('dialog', { name: '分支图' });
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('.branch-map-tree')).toHaveCount(0);
  const chat = await page.locator('.ai-room-chat').boundingBox();
  const container = await page.locator('.ai-chat-with-map').boundingBox();
  expect(chat!.width).toBeGreaterThan(container!.width - 5);
  await page.getByRole('button', { name: '分支图', exact: true }).click();
  await expect(dialog.locator('.branch-map-node')).toHaveCount(2);
  await expect(dialog.locator('path[stroke-dasharray]')).toHaveCount(1);
  await dialog.locator('.branch-map-node').filter({ hasText: '保留的后续讨论' }).click();
  await expect(dialog.locator('.branch-map-detail')).toContainText('中间对话已删除');
  await expect(dialog.getByRole('button', { name: '查看分出位置' })).toHaveCount(0);
  const viewport = dialog.locator('.branch-map-viewport');
  const canvas = dialog.locator('.branch-map-canvas');
  const box = (await viewport.boundingBox())!;
  const point = { x: box.width * .65, y: box.height * .4 };
  const transform = () => canvas.evaluate(node => { const m = new DOMMatrix(getComputedStyle(node).transform); return { scale: m.a, x: m.e, y: m.f }; });
  // Wait until the initial fit has settled before testing the pointer anchor.
  await dialog.getByRole('button', { name: '适应画布' }).click();
  const before = await transform();
  await page.mouse.move(box.x + point.x, box.y + point.y);
  await page.mouse.wheel(0, -180);
  await expect.poll(async () => (await transform()).scale).toBeGreaterThan(before.scale);
  const after = await transform();
  expect(Math.abs((point.x - before.x) / before.scale - (point.x - after.x) / after.scale)).toBeLessThan(1);
  expect(Math.abs((point.y - before.y) / before.scale - (point.y - after.y) / after.scale)).toBeLessThan(1);
  await page.mouse.wheel(0, 180);
  await expect.poll(async () => (await transform()).scale).toBeLessThan(after.scale);
  await dialog.screenshot({ path: '/tmp/nautilus-map-deleted-middle.png' });
  await dialog.getByRole('button', { name: '打开对话', exact: true }).click();
  await expect(dialog).toBeHidden();
  expect((await page.request.delete(`/api/ai/conversations/${root}`)).status()).toBe(204);
  await page.getByRole('button', { name: '分支图', exact: true }).click();
  await expect(dialog.locator('.branch-map-node')).toHaveCount(1);
  await expect(dialog.locator('.branch-map-detail')).toContainText('来源对话已删除');
  await expect(dialog.locator('.branch-map-lines path')).toHaveCount(0);
  await page.getByRole('button', { name: '关闭分支图' }).click();
  await expect(dialog).toHaveCount(0);
  expect(errors).toEqual([]);
});
