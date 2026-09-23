import { expect, test } from '@playwright/test';
import { authorize } from './fact-helpers';

test('one start flow, streamed math, actionable verification retry and math questions on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await authorize(page);
  const provider = await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic math provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model: 'mock-math', api_key: 'synthetic-only', enabled: true, request_timeout_seconds: 15,
  }});
  expect(provider.ok()).toBeTruthy();
  await page.reload();
  const existing = await (await page.request.get('/api/learning/return-review')).json();
  const open = page.getByRole('button', { name: '学习首页', exact: true }).first();
  if (!(await open.isVisible())) await page.getByRole('button', { name: '打开导航' }).click();
  await open.click();
  const closeNav = page.getByRole('button', { name: '关闭导航' });
  if (await closeNav.isVisible()) await closeNav.click();
  if (existing) {
    const card = page.getByRole('region', { name: '当前学习' });
    await expect(card).toBeVisible();
    await page.getByRole('button', { name: '创建', exact: true }).click();
  }
  await expect(page.getByRole('heading', { name: '你想学会什么？' })).toBeVisible();
  await expect(page.getByText('旧计划管理入口', { exact: true })).toHaveCount(0);
  await expect(page.getByText('我想从学习目标开始', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '按计划开始' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '查看历史计划' })).toHaveCount(0);
  await page.screenshot({ path: '/tmp/nautilus-feedback-start-390.png', fullPage: true });
  await page.getByLabel('学习目标', { exact: true }).fill('合成目标：解释简单代数式');
  await page.getByRole('button', { name: '我想自己安排' }).click();
  await page.getByRole('button', { name: '确认这份学习安排' }).click();
  await page.getByRole('button', { name: '进入学习室并开始这项任务' }).click();
  const reply = page.locator('.ai-message--assistant .ai-markdown').first();
  await expect(reply.locator('.katex')).toHaveCount(5);
  await expect(reply.locator('code').filter({ hasText: '\\(literal_code\\)' })).toHaveCount(1);
  await expect(reply.locator('pre code')).toHaveText('\\[literal_block\\]\n');
  await expect(reply.locator('.katex-error')).toHaveCount(0);
  await page.screenshot({ path: '/tmp/nautilus-feedback-math-390.png', fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();

  await page.getByRole('button', { name: '进入验证', exact: true }).click();
  const modes = page.getByRole('group', { name: '验证方式' });
  await modes.getByRole('button', { name: /提交我的材料/ }).click();
  await page.getByRole('button', { name: '开始验证', exact: true }).click();
  const work = page.getByPlaceholder('说明你自己做了什么、如何判断，以及实际结果');
  await work.fill('合成材料草稿：切换方式不丢失这段未提交内容。');
  await modes.getByRole('button', { name: /AI 出题验证/ }).click();
  await page.route('**/api/learning/verifications', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    return route.fulfill({ status: 502, contentType: 'application/json', body: JSON.stringify({ detail: {
      kind: 'verification_output_truncated', message: 'AI 输出达到长度上限，题目不完整；请缩小学习范围后重试。',
    } }) });
  });
  await page.getByRole('button', { name: '开始验证', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('输出达到长度上限');
  await expect(page.getByRole('button', { name: '开始验证', exact: true })).toBeEnabled();
  await page.unroute('**/api/learning/verifications');
  await modes.getByRole('button', { name: /提交我的材料/ }).click();
  await expect(work).toHaveValue('合成材料草稿：切换方式不丢失这段未提交内容。');
  // This is the reported failure: reopen a saved material-mode attempt before
  // any answer was submitted, then choose AI questions instead.
  await page.reload();
  await page.getByRole('button', { name: '进入验证', exact: true }).click();
  await expect(work).toBeVisible();
  await expect(modes.getByRole('button', { name: /AI 出题验证/ })).toBeVisible();
  await work.fill('合成材料作答：保留这次已保存的结果。');
  await page.getByRole('button', { name: '保存作答并验证' }).click();
  await expect(page.getByText('作答已保存。', { exact: false })).toBeVisible();
  const before = await (await page.request.get('/api/learning/verifications')).json();
  const materialAttempt = before.find((item: { mode: string }) => item.mode === 'user_material');
  expect(materialAttempt.latest_submission_id).toBeTruthy();
  await modes.getByRole('button', { name: /AI 出题验证/ }).click();
  await page.getByRole('button', { name: '开始验证', exact: true }).click();
  await expect(page.locator('.verification-question .katex')).toHaveCount(5);
  // Real wheel input must reach both ends without Playwright auto-scrolling a
  // clicked field into view (which can mask overflow:hidden ancestors).
  const verificationScroll = page.locator('.verification-page').locator('..');
  for (const viewport of [{ width: 390, height: 844 }, { width: 1024, height: 640 }, { width: 1440, height: 1000 }]) {
    await page.setViewportSize(viewport);
    await page.mouse.move(viewport.width / 2, 180);
    await page.mouse.wheel(0, 5000);
    await expect.poll(() => verificationScroll.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
    await expect(page.getByRole('button', { name: '保存作答并验证' })).toBeInViewport();
    await page.mouse.wheel(0, -5000);
    await expect.poll(() => verificationScroll.evaluate(element => element.scrollTop)).toBe(0);
    await expect(page.getByRole('heading', { name: '验证本次学习' })).toBeInViewport();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  const touch = await page.context().newCDPSession(page);
  await touch.send('Emulation.setTouchEmulationEnabled', { enabled: true });
  await touch.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: 25, y: 700 }] });
  for (let y = 650; y >= 200; y -= 50) {
    await touch.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: 25, y }] });
  }
  await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await expect.poll(() => verificationScroll.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
  await touch.send('Emulation.setTouchEmulationEnabled', { enabled: false });
  await touch.detach();
  await page.getByPlaceholder('写出你的判断、过程或结果').fill('合成 AI 作答草稿');
  await modes.getByRole('button', { name: /提交我的材料/ }).click();
  await expect(page.getByText('作答已保存。', { exact: false })).toBeVisible();
  await modes.getByRole('button', { name: /AI 出题验证/ }).click();
  await expect(page.getByPlaceholder('写出你的判断、过程或结果')).toHaveValue('合成 AI 作答草稿');
  const after = await (await page.request.get('/api/learning/verifications')).json();
  expect(after.filter((item: { delegation_id: string; session_id: string }) => item.delegation_id === materialAttempt.delegation_id && item.session_id === materialAttempt.session_id)).toHaveLength(2);
  expect(after.find((item: { id: string }) => item.id === materialAttempt.id).latest_submission_id).toBe(materialAttempt.latest_submission_id);
  await expect(page.getByText('通过说明边界判断本次表现', { exact: false })).toHaveCount(0);
  for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 1000 }]) {
    await page.setViewportSize(viewport);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.screenshot({ path: `/tmp/nautilus-feedback-verification-${viewport.width}.png`, fullPage: true });
  }
  await page.getByPlaceholder('写出你的判断、过程或结果').fill('合成作答：表达式与求和具有不同范围。');
  await page.getByRole('button', { name: '保存作答并验证' }).click();
  await expect(page.getByText('作答已保存。', { exact: false })).toBeVisible();
  await expect(page.locator('.verification-result .katex')).toHaveCount(2);
  await expect(page.locator('.verification-result .mord.mathnormal').first()).toHaveCSS('display', 'inline');
  await page.getByRole('checkbox', { name: /我已核对结果/ }).check();
  await page.getByRole('button', { name: '确认完成本次委托' }).click();
  await expect(page.getByRole('region', { name: '当前学习' })).toBeVisible();
});
