import { expect, test } from '@playwright/test';
import { authorize } from './fact-helpers';

for (const kind of ['conversation', 'discussion']) test(`${kind}: compare, edit, save, source graph and continue`, async ({ page }) => {
  test.setTimeout(90_000);
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  const routes = await (await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT}/openapi.json`)).json();
  expect(routes.paths['/api/branch-comparisons/{kind}/{identifier}/previews']).toBeTruthy();
  await authorize(page);
  expect((await page.request.put('/api/ai/provider', { data: { display_name: 'Synthetic comparison', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL, model: 'mock-review', api_key: 'synthetic-comparison', enabled: true, request_timeout_seconds: 15 } })).ok()).toBeTruthy();
  await page.reload();
  if (kind === 'conversation') {
    await page.getByRole('button', { name: '学习室', exact: true }).click();
    await page.getByRole('button', { name: '新建对话', exact: true }).click();
  } else {
    await page.getByRole('button', { name: '学习首页', exact: true }).first().click();
    if (await (await page.request.get('/api/learning/return-review')).json()) await page.getByRole('button', { name: '创建', exact: true }).click();
    await page.getByLabel('学习目标', { exact: true }).fill('合成目标：分支比较');
    await page.getByRole('button', { name: '我想自己安排' }).click();
    await page.getByLabel('现在先做什么', { exact: true }).fill('合成分支结论任务');
    await page.getByRole('button', { name: '确认这份学习安排' }).click();
    await page.getByRole('button', { name: '进入学习室并开始这项任务' }).click();
    await expect(page.locator('.ai-message--assistant').first()).toBeVisible();
    await page.getByRole('button', { name: '进入验证', exact: true }).click();
    await page.getByRole('button', { name: '开始验证', exact: true }).click();
    await page.getByPlaceholder('写出你的判断、过程或结果').first().fill('合成作答：先定位问题。');
    await page.getByPlaceholder('写出你的判断、过程或结果').nth(1).fill('合成作答：检查边界。');
    await page.getByRole('button', { name: '保存作答并验证' }).click();
    await page.getByRole('region', { name: '验证回看' }).getByRole('article', { name: '第 1 题回看' }).getByRole('button', { name: '讨论这道题' }).click();
  }
  const input = page.getByLabel(kind === 'conversation' ? '输入学习问题' : '继续提问或回答拓展问题', { exact: true });
  async function send(text: string) {
    const posted = page.waitForResponse(response => /\/messages$/.test(response.url()) && response.request().method() === 'POST');
    await input.fill(text); await input.press('Enter');
    const response = await posted; expect(response.ok()).toBeTruthy(); const data = await response.json();
    const id = kind === 'conversation' ? data.run.conversation_id : data.id;
    const path = kind === 'conversation' ? '/api/ai/conversations' : '/api/learning/discussions';
    await expect.poll(async () => { const result = await (await page.request.get(`${path}/${id}`)).json(); return kind === 'conversation' ? result.active_run === null : result.turns.at(-1)?.status === 'succeeded'; }, { timeout: 15_000 }).toBeTruthy();
    await expect(page.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
    return id as string;
  }
  await send('合成原思路：先理解问题。');
  const branchResponse = page.waitForResponse(response => response.url().endsWith('/branches') && response.request().method() === 'POST');
  await page.getByRole('button', { name: '从这里创建独立对话' }).first().click();
  expect((await branchResponse).ok()).toBeTruthy();
  await send('合成另一条思路：先检查边界。');
  await page.getByRole('button', { name: '分支图', exact: true }).click();
  const graph = page.getByRole('dialog', { name: '分支图', exact: true });
  await graph.getByRole('button', { name: '比较分支', exact: true }).click();
  const compare = graph.getByRole('region', { name: '分支比较' });
  await compare.getByRole('button', { name: '生成观点对比' }).click();
  await compare.getByLabel('采用：方法的互补', { exact: true }).check();
  await compare.getByLabel('结论：方法的互补', { exact: true }).fill('本人整理：理解问题后，补充边界例子。');
  await compare.getByText('查看原文依据', { exact: true }).click();
  await expect(compare.locator('blockquote')).toHaveCount(2);
  await compare.getByLabel('结论标题', { exact: true }).fill('合成两路结论');
  await compare.getByText('查看原文依据', { exact: true }).click();
  await compare.evaluate(element => { element.scrollTop = 0; });
  await graph.screenshot({ path: `/tmp/nautilus-e1-${kind}-desktop.png` });
  await page.setViewportSize({ width: 390, height: 900 });
  await compare.getByRole('button', { name: '保存结论并继续' }).scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: `/tmp/nautilus-e1-${kind}-390.png` });
  const accepted = page.waitForResponse(response => response.url().endsWith('/api/branch-comparisons/confirm'));
  await compare.getByRole('button', { name: '保存结论并继续' }).click();
  const response = await accepted; expect(response.ok()).toBeTruthy(); const merged = (await response.json()).id;
  await expect(graph).toBeHidden();
  await expect(page.getByText('已整理确认的分支结论 · 来源见分支图', { exact: true })).toBeVisible();
  await expect(page.getByText('本人整理：理解问题后，补充边界例子。', { exact: true })).toBeVisible();
  expect(await send('从结论继续举一个例子。')).toBe(merged);
  await page.getByRole('button', { name: '分支图', exact: true }).click();
  await expect(graph.locator('.branch-map-node')).toHaveCount(3);
  await expect(graph.locator('.branch-map-lines path')).toHaveCount(3);
  await expect(graph.locator('.branch-map-merge-sources button')).toHaveCount(2);
  await graph.screenshot({ path: `/tmp/nautilus-e1-${kind}-graph-390.png` });
  await graph.locator('.branch-map-merge-sources button').last().click();
  await expect(graph).toBeHidden(); await expect(input).toBeEnabled();
  expect(errors).toEqual([]);
});
