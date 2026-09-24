import { expect, test } from '@playwright/test';
import { authorize } from './fact-helpers';

test('saved answers → per-question discussion with local sources → completed history → refresh → permanent deletion on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await authorize(page);
  expect((await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic review provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model: 'mock-review', api_key: 'synthetic-test-only', enabled: true, request_timeout_seconds: 15,
  }})).ok()).toBeTruthy();
  await page.reload();
  const existing = await (await page.request.get('/api/learning/return-review')).json();
  const start = page.getByRole('button', { name: '学习首页', exact: true }).first();
  if (!(await start.isVisible())) await page.getByRole('button', { name: '打开导航' }).click();
  await start.click();
  if (await page.getByRole('button', { name: '关闭导航' }).isVisible()) await page.getByRole('button', { name: '关闭导航' }).click();
  const card = page.getByRole('region', { name: '当前学习' });
  if (existing) {
    await expect(card).toBeVisible();
    await page.getByRole('button', { name: '创建', exact: true }).click();
  }
  await page.getByLabel('学习目标', { exact: true }).fill('合成目标：验证回看与追问');
  await page.getByRole('button', { name: '我想自己安排' }).click();
  await page.getByLabel('现在先做什么', { exact: true }).fill('合成验证回看旅程');
  await page.getByRole('button', { name: '确认这份学习安排' }).click();
  await page.getByRole('button', { name: '进入学习室并开始这项任务' }).click();
  await expect(page.locator('.ai-message--assistant').first()).toBeVisible();
  const historyText = '合成历史：我想比较编号的边界情况\n\n' + '合成长段记录：比较空输入、不同前缀、字符边界以及多个编号的情况。'.repeat(16);
  await page.getByPlaceholder(/输入关于/).fill(historyText);
  await page.getByRole('button', { name: '发送问题', exact: true }).click();
  await expect(page.getByRole('button', { name: '停止生成', exact: true })).toBeHidden();
  await page.getByRole('button', { name: '进入验证', exact: true }).click();
  await page.getByRole('button', { name: '开始验证', exact: true }).click();
  await page.getByPlaceholder('写出你的判断、过程或结果').first().fill('合成原始答案：先找编号，再检查字符边界。空输入仍未知。');
  await page.getByPlaceholder('写出你的判断、过程或结果').nth(1).fill('合成第二题答案：检查空字符串。');
  await page.getByRole('button', { name: '保存作答并验证' }).click();
  const review = page.getByRole('region', { name: '验证回看' });
  await expect(review.getByText('合成原始答案：先找编号，再检查字符边界。空输入仍未知。', { exact: true })).toBeVisible();
  await expect(review.getByText('合成逐题反馈：已说明过程和未知。')).toBeVisible();
  const firstQuestion = review.getByRole('article', { name: '第 1 题回看' });
  const secondQuestion = review.getByRole('article', { name: '第 2 题回看' });
  await expect(firstQuestion.getByText('换一个输入时，你会怎样检查？')).toBeVisible();
  await expect(secondQuestion.getByText('第二题反馈：应单独检查空输入，不能据此泛化。')).toBeVisible();
  await expect(secondQuestion).not.toContainText('合成逐题反馈：已说明过程和未知。');
  expect(await review.evaluate(element => {
    const questions = element.querySelectorAll('.verification-question');
    const summary = element.querySelector('.verification-result')!;
    return [...questions].every(question => Boolean(question.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING));
  })).toBeTruthy();
  await expect(page.getByRole('button', { name: '彻底删除本次验证内容' })).toBeHidden();
  await firstQuestion.getByText('AI 参考解法（可继续质疑）', { exact: true }).click();
  await expect(firstQuestion.getByText('合成参考解法：先定位，再检查边界。')).toBeVisible();
  await firstQuestion.getByRole('button', { name: '讨论这道题' }).click();
  const discussion = page.getByRole('region', { name: '题目学习室' });
  await expect(discussion.getByRole('region', { name: '本题 AI 反馈' })).toContainText('合成逐题反馈：已说明过程和未知。');
  await discussion.getByText('AI 参考解法（可继续质疑）', { exact: true }).click();
  await expect(discussion.getByText('合成参考解法：先定位，再检查边界。')).toBeVisible();
  for (const viewport of [{ width: 390, height: 844 }, { width: 1024, height: 640 }, { width: 1440, height: 1000 }]) {
    await page.setViewportSize(viewport);
    const composer = await discussion.locator('.ai-composer').boundingBox();
    expect(composer!.y + composer!.height).toBeLessThanOrEqual(viewport.height);
    const messages = discussion.locator('.ai-message-list');
    await messages.evaluate(element => { element.scrollTop = element.scrollHeight; });
    if (viewport.width === 390) expect(await messages.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.screenshot({ path: `/tmp/nautilus-discussion-${viewport.width}.png`, fullPage: true });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  let releaseSend!: () => void;
  const sendGate = new Promise<void>(resolve => { releaseSend = resolve; });
  await page.route('**/api/learning/discussions/*/messages', async route => { await sendGate; await route.continue(); });
  const input = discussion.getByLabel('继续提问或回答拓展问题');
  await input.fill('合成追问：我这样补充边界说明可以吗？');
  await input.press('Enter');
  await expect(discussion.locator('.ai-message--user')).toContainText('合成追问：我这样补充边界说明可以吗？');
  await expect(input).toHaveValue('');
  await expect(discussion.getByText('发送中', { exact: true })).toBeVisible();
  const userBubble = await discussion.locator('.ai-message--user').boundingBox();
  const messagePane = await discussion.locator('.ai-message-list').boundingBox();
  expect(userBubble!.x).toBeGreaterThan(messagePane!.x);
  releaseSend();
  const answer = discussion.locator('.ai-message--assistant .ai-message-content');
  const thinking = discussion.locator('.ai-reasoning');
  await expect(thinking).toHaveAttribute('open', '');
  await expect(thinking.locator('pre')).toHaveText('先识别题目条件。');
  await expect(answer).toHaveText('…');
  await page.reload(); // Recover reasoning before any answer has arrived.
  await expect(thinking).toHaveAttribute('open', '');
  await expect(thinking.locator('pre')).toContainText('先识别题目条件。');
  await expect(answer).toHaveText('合成续学讲解：');
  await expect(discussion.getByRole('button', { name: '取消生成' })).toBeVisible();
  await page.reload(); // Resume while still generating, without duplicating the question.
  await expect(discussion.locator('.ai-message--user')).toHaveCount(1);
  await expect(answer).toHaveText('合成续学讲解：可以继续分析不同输入；此前的记录见[记录1]。');
  await expect(discussion.getByRole('button', { name: '取消生成' })).toBeHidden();
  await expect(thinking).not.toHaveAttribute('open', '');
  await thinking.locator('summary').click();
  await expect(thinking.locator('pre')).toHaveText('先识别题目条件。再核对推导路径。');
  await thinking.locator('summary').click();
  await discussion.getByText(/实际查阅的 \d+ 段记录/).click();
  const excerpts = discussion.locator('.discussion-source__excerpt');
  expect(await excerpts.count()).toBeGreaterThanOrEqual(2);
  await expect(discussion.locator('.discussion-source__excerpt.is-expanded')).toHaveCount(0);
  const longSource = discussion.locator('.discussion-source').filter({ hasText: '合成长段记录' });
  await expect(longSource.locator('.is-truncated')).toHaveCount(1);
  expect(await longSource.locator('.discussion-source__excerpt').evaluate(node => getComputedStyle(node).maskImage)).toContain('linear-gradient');
  for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 1000 }]) {
    await page.setViewportSize(viewport);
    await page.screenshot({ path: `/tmp/nautilus-stream-sources-${viewport.width}.png`, fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  }
  await longSource.getByRole('button', { name: /展开记录/ }).click();
  await expect(longSource.locator('.is-expanded')).toBeVisible();
  await expect(discussion.locator('.discussion-source__excerpt.is-expanded')).toHaveCount(1);
  await longSource.getByRole('button', { name: /收起记录/ }).click();
  await expect(longSource.locator('.is-truncated')).toHaveCount(1);
  await page.unroute('**/api/learning/discussions/*/messages');
  await input.fill('合成追问：验证取消后重试。');
  await input.press('Enter');
  await expect(answer.last()).toHaveText('合成续学讲解：');
  await discussion.getByRole('button', { name: '取消生成' }).click();
  await expect(discussion.getByText('已取消生成，已收到的内容保留。')).toBeVisible();
  await expect(thinking.last()).not.toHaveAttribute('open', '');
  await expect(answer.last()).toHaveText('合成续学讲解：');
  await discussion.getByRole('button', { name: '重试', exact: true }).last().click();
  await expect(answer.last()).toHaveText('合成续学讲解：可以继续分析不同输入；此前的记录见[记录1]。');
  await expect(discussion.getByRole('button', { name: '取消生成' })).toBeHidden();
  await expect(discussion.locator('.ai-message--user')).toHaveCount(3);
  await expect(answer.nth(1)).toHaveText('合成续学讲解：');
  await page.reload();
  await expect(discussion.getByText('合成追问：我这样补充边界说明可以吗？', { exact: true })).toBeVisible();
  await expect(thinking).toHaveCount(3);
  await expect(thinking.first()).not.toHaveAttribute('open', '');
  await thinking.first().locator('summary').click();
  await expect(thinking.first().locator('pre')).toHaveText('先识别题目条件。再核对推导路径。');
  await discussion.getByRole('button', { name: '返回验证记录' }).click();
  await page.getByRole('checkbox', { name: /我已核对结果/ }).check();
  await page.getByRole('button', { name: '确认完成本次委托' }).click();
  await expect(card).toBeVisible();
  await card.getByRole('button', { name: '查看验证记录' }).click();
  await page.getByRole('button', { name: /合成验证回看旅程.*已完成/ }).click();
  await page.getByRole('button', { name: /验证 1 · AI 出题/ }).click();
  await expect(review.getByText('合成原始答案：先找编号，再检查字符边界。空输入仍未知。', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('region', { name: '学习记录' })).toBeVisible();
  await expect(review.getByText('合成原始答案：先找编号，再检查字符边界。空输入仍未知。', { exact: true })).toBeVisible();
  for (const viewport of [{ width: 390, height: 844 }, { width: 1024, height: 640 }, { width: 1440, height: 1000 }]) {
    await page.setViewportSize(viewport);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.screenshot({ path: `/tmp/nautilus-review-${viewport.width}.png`, fullPage: true });
  }
  await review.getByRole('button', { name: '打开题目讨论 1' }).click();
  await expect(discussion.getByText('合成追问：我这样补充边界说明可以吗？', { exact: true })).toBeVisible();
  const composer = await discussion.locator('.ai-composer').boundingBox();
  expect(composer!.y + composer!.height).toBeLessThanOrEqual(1000);
  await page.screenshot({ path: '/tmp/nautilus-discussion-from-records.png', fullPage: true });
  await discussion.getByRole('button', { name: '返回验证记录' }).click();
  // An existing summary-only record stays readable without inventing historical feedback.
  await page.route(/\/api\/learning\/verifications\/[^/?]+\?/, async route => {
    const response = await route.fetch();
    const record = await response.json();
    if (record.result) delete record.result.question_feedback;
    await route.fulfill({ response, json: record });
  });
  await page.reload();
  await expect(firstQuestion.getByText('这次记录未保存逐题反馈，可在讨论中请 AI 重新讲解。')).toBeVisible();
  await expect(review.getByRole('status', { name: '整体验证总结' })).toContainText('合成评估：本次说明符合当前任务要求。');
  await expect(firstQuestion.getByRole('region', { name: '本题 AI 反馈' })).toHaveCount(0);
  await review.getByText('更多操作', { exact: true }).click();
  page.once('dialog', dialog => dialog.accept());
  await review.getByRole('button', { name: '彻底删除本次验证内容' }).click();
  await expect(review.getByText('本次作答内容已彻底删除。完成事实仍保留。')).toBeVisible();
  await expect(page.getByRole('region', { name: '委托历史' })).toContainText('任务状态：已完成');
});
