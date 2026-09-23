import { expect, test, type Page } from '@playwright/test';
import { authorize } from './fact-helpers';

async function openLearning(page: Page) {
  await expect(page.getByRole('button', {name:'退出会话'})).toBeVisible();
  const button = page.getByRole('button', { name: '学习首页', exact: true }).first();
  if (!(await button.isVisible())) await page.getByRole('button', { name: '打开导航' }).click();
  await button.click();
  const close = page.getByRole('button', { name: '关闭导航' });
  if (await close.isVisible()) await close.click();
}
async function provider(page: Page) {
  const response = await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic continuity provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model: 'mock-success', api_key: 'synthetic-test-only', enabled: true, request_timeout_seconds: 15,
  }});
  expect(response.ok()).toBeTruthy();
}
async function setup(page: Page, title: string) {
  const existing = await (await page.request.get('/api/learning/return-review')).json();
  await openLearning(page);
  const card = page.getByRole('region', { name: '当前学习' });
  if (existing) {
    await expect(card).toBeVisible();
    await page.getByRole('button', { name: '创建', exact: true }).click();
  }
  await page.getByLabel('学习目标', { exact: true }).fill('合成目标：解释编号匹配及未知情况');
  await page.getByRole('button', { name: '让 AI 帮我整理第一步' }).click();
  await page.getByLabel('现在先做什么', { exact: true }).fill(title);
  await page.getByRole('button', { name: '确认这份学习安排' }).click();
  await page.getByRole('button', { name: '进入学习室并开始这项任务' }).click();
  await expect(page.getByRole('region', { name: '本次学习安排' })).toContainText(title);
}

test('new learning → saved verification → confirmed completion → return card → continue', async ({ page }) => {
  await authorize(page);
  await provider(page);
  await setup(page, '合成完成旅程');
  await page.getByRole('button', { name: '进入验证', exact: true }).click();
  await page.getByRole('button', { name: '开始验证', exact: true }).click();
  await page.getByPlaceholder('写出你的判断、过程或结果').fill('我先定位编号，再检查字符类型。目前不知道空输入时的情况。');
  await page.getByRole('button', { name: '保存作答并验证' }).click();
  await expect(page.getByText('作答已保存。', { exact: false })).toBeVisible();
  await page.getByRole('checkbox', { name: /我已核对结果/ }).check();
  await page.getByRole('button', { name: '确认完成本次委托' }).click();
  const card = page.getByRole('region', { name: '当前学习' });
  await expect(card).toBeVisible();
  await expect(card).toContainText('本次学习已完成');
  const firstState = await (await page.request.get('/api/learning/state')).json();
  const firstPlan = firstState.plans[0].id;
  await expect(card.getByText('已完成', {exact:true})).toBeVisible();
  await expect(card.getByRole('heading', {name:'已有依据'})).toHaveCount(0);
  await page.reload();
  await openLearning(page);
  await expect(card).toContainText('合成完成旅程');
  await card.getByRole('button', { name: '添加下一步', exact: true }).click();
  await expect(page.getByRole('heading', { name: '接下来学什么？' })).toBeVisible();
  await page.getByLabel('下一步想做什么', {exact:true}).fill('合成目标：观察另一个输入');
  await page.getByRole('button', {name:'我想自己安排',exact:true}).click();
  await page.getByLabel('现在先做什么', {exact:true}).fill('复核后确认的下一步');
  await page.getByRole('button', {name:'确认这份学习安排'}).click();
  const secondState = await (await page.request.get('/api/learning/state')).json();
  expect(secondState.plans).toHaveLength(firstState.plans.length);
  expect(secondState.goals).toHaveLength(firstState.goals.length);
  const step = secondState.actions.find(item => item.title === '复核后确认的下一步');
  expect(secondState.action_links.find(item => item.action_id === step.id).plan_id).toBe(firstPlan);
  await page.getByRole('button', {name:'进入学习室并开始这项任务'}).click();
  await page.getByRole('button', {name:'进入验证',exact:true}).click();
  await page.getByRole('button', {name:'开始验证',exact:true}).click();
  await page.getByPlaceholder('写出你的判断、过程或结果').fill('合成作答：比较了新输入并记录未检查的边界。');
  await page.getByRole('button', {name:'保存作答并验证'}).click();
  await page.getByRole('checkbox', {name:/我已核对结果/}).check();
  await page.getByRole('button', {name:'确认完成本次委托'}).click();
  await expect(card).toContainText('复核后确认的下一步');
  const metrics = await (await page.request.get('/api/learning/metrics')).json();
  expect(metrics.product_metrics.review_to_next_action).toMatchObject({status:'observed',numerator:1,denominator:1});
});

test('interruption → reopened return card → same delegation and conversation on 390px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await authorize(page);
  await provider(page);
  await setup(page, '合成恢复旅程');
  await page.getByPlaceholder(/输入关于/).fill('合成消息：请保留这次编号练习的上下文');
  await page.getByRole('button', { name: '发送问题', exact: true }).click();
  await expect(page.getByText('合成消息：请保留这次编号练习的上下文', {exact:true})).toBeVisible();
  const before = await (await page.request.get('/api/learning/return-review')).json();
  const oldRoom = await (await page.request.get(`/api/learning/sessions/${before.position.last_session}/room`)).json();
  expect(oldRoom.conversation_id).toBeTruthy();
  await page.getByRole('button', { name: '今天先停', exact: true }).click();
  await expect(page.getByRole('region', { name: '当前学习' })).toContainText('学习位置已保存');
  await page.reload();
  await openLearning(page);
  const card = page.getByRole('region', { name: '当前学习' });
  await expect(card.getByText('正在学习', {exact:true})).toBeVisible();
  for (const viewport of [{width:390,height:844},{width:1024,height:640},{width:1440,height:1000}]) {
    await page.setViewportSize(viewport);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    const button = await card.getByRole('button', { name: '继续学习', exact: true }).boundingBox();
    expect(button!.y).toBeLessThan(viewport.height);
    await page.screenshot({path: `/tmp/nautilus-return-${viewport.width}.png`, fullPage: true});
  }
  await page.setViewportSize({ width:390,height:844 });
  await page.evaluate(() => { document.documentElement.style.zoom='1.25'; });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.evaluate(() => { document.documentElement.style.zoom='1'; });
  await card.getByRole('button', { name: '继续学习', exact: true }).click();
  await expect(page.getByRole('region', { name: '本次学习安排' })).toContainText('合成恢复旅程');
  await expect(page.getByText('合成消息：请保留这次编号练习的上下文', {exact:true})).toBeVisible();
  const after = await (await page.request.get('/api/learning/return-review')).json();
  expect(after.position.delegation_id).toBe(before.position.delegation_id);
  expect(after.position.last_session).not.toBe(before.position.last_session);
  const room = await (await page.request.get(`/api/learning/sessions/${after.position.last_session}/room`)).json();
  expect(room.conversation_id).toBe(oldRoom.conversation_id);
  const metrics = await (await page.request.get('/api/learning/metrics')).json();
  expect(metrics.product_metrics.interrupted_delegation_recovery).toMatchObject({status:'observed', numerator:1,denominator:1});
});
