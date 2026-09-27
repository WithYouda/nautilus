import { expect, test } from '@playwright/test';
import { authorize } from './fact-helpers';

test('branches an earlier question answer while preserving the verification and both discussions', async ({ page }) => {
  test.setTimeout(90_000);
  const pageErrors: string[] = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  const routes = await (await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT ?? '8012'}/openapi.json`)).json();
  expect(routes.paths['/api/learning/discussions/{discussion_id}/branches']).toBeTruthy();
  expect(routes.paths['/api/learning/discussions/{discussion_id}/branch-map']).toBeTruthy();

  await authorize(page);
  expect((await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic discussion branch provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model: 'mock-review', api_key: 'synthetic-discussion-branch-key', enabled: true, request_timeout_seconds: 15,
  }})).ok()).toBeTruthy();
  await page.reload();
  const start = page.getByRole('button', { name: '学习首页', exact: true }).first();
  await expect(start).toBeVisible();
  await start.click();
  if (await (await page.request.get('/api/learning/return-review')).json()) await page.getByRole('button', { name: '创建', exact: true }).click();
  await page.getByLabel('学习目标', { exact: true }).fill('合成目标：题目讨论独立分支');
  await page.getByRole('button', { name: '我想自己安排' }).click();
  await page.getByLabel('现在先做什么', { exact: true }).fill('合成题目讨论分支旅程');
  await page.getByRole('button', { name: '确认这份学习安排' }).click();
  await page.getByRole('button', { name: '进入学习室并开始这项任务' }).click();
  await expect(page.locator('.ai-message--assistant').first()).toBeVisible();
  await page.getByRole('button', { name: '进入验证', exact: true }).click();
  await page.getByRole('button', { name: '开始验证', exact: true }).click();
  await page.getByPlaceholder('写出你的判断、过程或结果').first().fill('合成原作答：先定位，再检查边界。');
  await page.getByPlaceholder('写出你的判断、过程或结果').nth(1).fill('合成第二题作答：检查空输入。');
  await page.getByRole('button', { name: '保存作答并验证' }).click();
  const review = page.getByRole('region', { name: '验证回看' });
  const firstQuestion = review.getByRole('article', { name: '第 1 题回看' });
  await expect(firstQuestion.getByText('合成原作答：先定位，再检查边界。', { exact: true })).toBeVisible();
  await expect(firstQuestion.getByText('合成逐题反馈：已说明过程和未知。')).toBeVisible();
  const verificationId = (await (await page.request.get('/api/learning/verifications')).json())[0].id as string;
  await firstQuestion.getByRole('button', { name: '讨论这道题' }).click();
  const discussion = page.getByRole('region', { name: '题目学习室' });
  await expect(discussion).toBeVisible();
  const sourceId = new URL(page.url()).searchParams.get('discussion');
  expect(sourceId).toBeTruthy();

  const materialsButton = discussion.locator('.ai-composer').getByRole('button', { name: /^资料(?: · \d+)?$/ });
  await materialsButton.click();
  const materials = discussion.locator('.task-materials-panel');
  await materials.getByLabel(/上传资料/).setInputFiles({ name: '讨论分支教材.txt', mimeType: 'text/plain', buffer: Buffer.from('合成资料：先检查边界。') });
  await expect(materials.getByRole('checkbox', { name: '讨论分支教材.txt · 文本资料' })).toBeChecked();
  await materialsButton.click();

  const input = discussion.getByLabel('继续提问或回答拓展问题');
  async function send(text: string, discussionId: string) {
    await input.fill(text);
    const response = page.waitForResponse(value => value.url().endsWith(`/api/learning/discussions/${discussionId}/messages`) && value.request().method() === 'POST');
    await input.press('Enter');
    expect((await response).ok()).toBeTruthy();
    await expect.poll(async () => (await (await page.request.get(`/api/learning/discussions/${discussionId}`)).json()).turns.at(-1)?.status, { timeout: 15_000 }).toBe('succeeded');
    await expect(discussion.getByRole('button', { name: '取消生成' })).toBeHidden();
  }
  await send('合成第一轮追问：为什么检查边界？', sourceId!);
  await send('合成第二轮追问：再给一个例子。', sourceId!);
  const sourceBefore = await (await page.request.get(`/api/learning/discussions/${sourceId}`)).json();
  expect(sourceBefore.turns).toHaveLength(2);
  const firstTurnId = sourceBefore.turns[0].id as string;
  const secondTurnId = sourceBefore.turns[1].id as string;

  await input.fill('合成未发送草稿');
  const branchResponse = page.waitForResponse(value => value.url().endsWith(`/api/learning/discussions/${sourceId}/branches`) && value.request().method() === 'POST');
  await discussion.locator('.discussion-turn').first().getByRole('button', { name: '从这里创建独立对话' }).click();
  const response = await branchResponse;
  expect(response.status()).toBe(201);
  const branch = await response.json();
  const branchId = branch.id as string;
  await expect(discussion.getByText('从另一段题目讨论分出')).toBeVisible();
  await expect(input).toHaveValue('合成未发送草稿');
  expect(new URL(page.url()).searchParams.get('discussion')).toBe(branchId);
  expect(branch.branch_origin).toEqual({ discussion_id: sourceId, turn_id: firstTurnId });
  expect(branch.turns).toHaveLength(1);
  expect(branch.turns[0].inherited_from).toEqual({ discussion_id: sourceId, turn_id: firstTurnId });
  expect(branch.turns[0].user_content).toBe(sourceBefore.turns[0].user_content);
  expect(branch.turns[0].assistant_content).toBe(sourceBefore.turns[0].assistant_content);
  expect(branch.turns.some((turn: { id: string }) => turn.id === secondTurnId)).toBe(false);
  expect(branch.source).toEqual(sourceBefore.source);
  expect(branch.verification_id).toBe(sourceBefore.verification_id);
  expect(branch.submission_id).toBe(sourceBefore.submission_id);
  expect(branch.evaluation_id).toBe(sourceBefore.evaluation_id);
  expect((await (await page.request.get(`/api/learning/discussions/${sourceId}`)).json()).turns).toEqual(sourceBefore.turns);

  await materialsButton.click();
  await expect(materials.getByRole('checkbox', { name: /讨论分支教材.txt/ })).toBeChecked();
  await materials.getByText('查看当前版本和历史', { exact: true }).click();
  await expect(materials.getByText(/继承（只读）/).first()).toBeVisible();
  await expect(materials.getByRole('button', { name: '编辑为新版本' })).toHaveCount(0);
  await materialsButton.click();

  const map = await (await page.request.get(`/api/learning/discussions/${branchId}/branch-map`)).json();
  expect(map.current_id).toBe(branchId);
  expect(map.nodes).toHaveLength(2);
  expect(map.nodes.find((node: { id: string }) => node.id === branchId)).toMatchObject({ parent_id: sourceId, source_id: firstTurnId, available: true });
  expect(map.nodes.find((node: { id: string }) => node.id === sourceId)).toMatchObject({ parent_id: null, available: true });
  await expect(page.getByRole('dialog', { name: '分支图' })).toHaveCount(0);
  await discussion.getByRole('button', { name: '分支图', exact: true }).click();
  const branchMap = page.getByRole('dialog', { name: '分支图' });
  await expect(branchMap.locator('.branch-map-node')).toHaveCount(2);
  await branchMap.screenshot({ path: '/tmp/nautilus-discussion-branch-map-desktop.png' });
  await branchMap.getByRole('button', { name: '编辑标题' }).click();
  const branchTitle = '合成边界问题的独立讨论';
  await branchMap.getByLabel('修改标题').fill(branchTitle);
  await branchMap.getByRole('button', { name: '保存', exact: true }).click();
  await expect(branchMap.locator('.branch-map-detail-title')).toHaveText(branchTitle);
  expect((await (await page.request.get(`/api/learning/discussions/${branchId}/branch-map`)).json()).nodes.find((node: { id: string }) => node.id === branchId).title).toBe(branchTitle);
  await branchMap.getByRole('button', { name: '查看分出位置' }).click();
  await expect(branchMap).toBeHidden();
  expect(new URL(page.url()).searchParams.get('discussion')).toBe(sourceId);
  await expect(input).toHaveValue('合成未发送草稿');
  await expect(discussion.locator(`#turn-${firstTurnId}`)).toBeInViewport();
  await expect(discussion.locator(`#turn-${secondTurnId}`)).toHaveCount(0);

  await page.reload();
  await expect(discussion.locator('.discussion-turn')).toHaveCount(1);
  expect(new URL(page.url()).searchParams.get('discussion')).toBe(sourceId);
  await discussion.getByRole('button', { name: '返回验证记录' }).click();
  await expect(review.getByRole('button', { name: `打开讨论：${sourceBefore.title}` })).toBeVisible();
  await expect(review.getByRole('button', { name: `打开讨论：${branchTitle}` })).toBeVisible();
  await review.getByRole('button', { name: `打开讨论：${branchTitle}` }).click();
  expect(new URL(page.url()).searchParams.get('discussion')).toBe(branchId);
  await expect(discussion.getByText('从另一段题目讨论分出')).toBeVisible();
  await expect(discussion.locator('.discussion-turn')).toHaveCount(1);
  await send('合成分支独立追问：只在新讨论继续。', branchId);
  expect((await (await page.request.get(`/api/learning/discussions/${branchId}`)).json()).turns).toHaveLength(2);
  expect((await (await page.request.get(`/api/learning/discussions/${sourceId}`)).json()).turns).toHaveLength(2);
  expect((await (await page.request.get(`/api/learning/verifications/${verificationId}`)).json()).discussions.map((item: { id: string }) => item.id)).toContain(branchId);
  await page.setViewportSize({ width: 390, height: 844 });
  await discussion.getByRole('button', { name: '分支图', exact: true }).click();
  const mobileMap = page.getByRole('dialog', { name: '分支图' });
  await expect(mobileMap.locator('.branch-map-node')).toHaveCount(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await mobileMap.screenshot({ path: '/tmp/nautilus-discussion-branch-map-390.png' });
  await page.getByRole('button', { name: '关闭分支图' }).click();
  await discussion.locator('.ai-message-list').evaluate(element => { element.scrollTop = 0; });
  await page.screenshot({ path: '/tmp/nautilus-discussion-branch-mobile.png' });
  await discussion.getByRole('button', { name: '返回验证记录' }).click();
  await review.getByText('更多操作', { exact: true }).click();
  page.once('dialog', dialog => dialog.accept());
  await review.getByRole('button', { name: '彻底删除本次验证内容' }).click();
  await expect(page.getByText('验证在线内容已清除，相关证据已失效。已有行动完成记录保留。')).toBeVisible();
  for (const did of [sourceId, branchId]) {
    const erased = await (await page.request.get(`/api/learning/discussions/${did}`)).json();
    expect(erased.purged).toBe(true);
    expect(erased.source).toBeNull();
    expect(erased.turns.every((turn: {user_content:string|null;assistant_content:string|null}) => !turn.user_content && !turn.assistant_content)).toBe(true);
  }
  expect(pageErrors).toEqual([]);

});
