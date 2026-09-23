import { expect, test } from '@playwright/test';
import { authorize } from './fact-helpers';

test('one navigation, real learning plans, same-plan next step and linked records', async ({ page }) => {
  await authorize(page);
  const legacyReads: string[] = [];
  page.on('request', request => { if (/\/api\/(plans|tasks|dashboard|layouts)(\/|\?|$)/.test(request.url())) legacyReads.push(request.url()); });
  await page.reload();
  const nav = page.getByRole('navigation', {name:'工作区视图'});
  await expect(nav.getByRole('button')).toHaveText(['学习首页01', '学习计划02', '学习记录03']);
  for (const label of ['今日', '任务', '历史计划', '日历', '甘特图']) await expect(page.getByRole('button', {name:label, exact:true})).toHaveCount(0);
  const created = await page.request.post('/api/learning/setup/confirm', {data:{
    original_intent:'合成目标：学习路线归属', goal_title:'合成路线目标', plan_title:'合成连续计划', action_title:'路线第一步', context_key:'navigation',
    object_description:'合成对象', behavior:'解释一个例子', outcome_context_key:'navigation', stop_conditions:'解释完一个例子', idempotency_key:crypto.randomUUID(),
  }});
  expect(created.ok()).toBeTruthy();
  const first = await created.json();
  await nav.getByRole('button', {name:'学习计划'}).click();
  await page.getByRole('navigation', {name:'计划列表'}).getByRole('button', {name:/合成连续计划/}).click();
  const detail = page.getByRole('region', {name:'计划详情'});
  await expect(detail).toContainText('合成路线目标');
  await expect(detail).toContainText('路线第一步');
  await detail.getByRole('button', {name:'添加下一步'}).click();
  await expect(page.getByRole('heading', {name:'接下来学什么？'})).toBeVisible();
  await page.getByLabel('下一步想做什么').fill('在原计划内比较两个例子');
  await page.getByRole('button', {name:'我想自己安排'}).click();
  await expect(page.getByLabel('你的目标', {exact:true})).toBeDisabled();
  await page.getByLabel('现在先做什么', {exact:true}).fill('路线第二步');
  await page.getByRole('button', {name:'确认这份学习安排'}).click();
  await expect(page.getByText('学习安排已确认，下一步是开始这项任务')).toBeVisible();
  const state = await (await page.request.get('/api/learning/state')).json();
  const next = state.setups.find(item => item.action_id === state.actions.find(action => action.title === '路线第二步').id);
  expect(next).toMatchObject({goal_id:first.goal_id, plan_id:first.plan_id});
  await nav.getByRole('button', {name:'学习计划'}).click();
  await page.getByRole('navigation', {name:'计划列表'}).getByRole('button', {name:/合成连续计划/}).click();
  await expect(detail.locator('.learning-plan-task')).toHaveCount(2);
  await page.reload();
  await expect(detail.locator('.learning-plan-task')).toHaveCount(2);
  await detail.locator('.learning-plan-task').filter({hasText:'路线第二步'}).getByRole('button', {name:'查看记录'}).click();
  await expect(page.getByRole('region', {name:'委托历史'})).toContainText('路线第二步');
  await page.reload();
  await expect(page.getByRole('region', {name:'委托历史'})).toContainText('路线第二步');
  await page.goBack();
  await expect(page.getByRole('region', {name:'计划详情'})).toContainText('路线第二步');
  // Switching tasks uses their own sessions, including while another task is running.
  await detail.locator('.learning-plan-task').filter({hasText:'路线第二步'}).getByRole('button', {name:'开始学习',exact:true}).click();
  await expect(page.getByRole('region', {name:'本次学习安排'})).toContainText('路线第二步');
  await page.getByRole('button', {name:'返回工作区'}).click();
  await expect(detail).toContainText('路线第一步');
  await detail.locator('.learning-plan-task').filter({hasText:'路线第一步'}).getByRole('button', {name:'开始学习',exact:true}).click();
  await expect(page.getByRole('region', {name:'本次学习安排'})).toContainText('路线第一步');
  const switched = await (await page.request.get('/api/learning/state')).json();
  expect(switched.sessions.filter(item => item.status === 'running')).toEqual([expect.objectContaining({delegation_id:first.delegation_id})]);
  expect(switched.sessions.some(item => item.delegation_id === next.delegation_id && item.status === 'interrupted')).toBeTruthy();
  await page.getByRole('button', {name:'返回工作区'}).click();
  expect(legacyReads).toEqual([]);
  for (const viewport of [{width:1440,height:1000}, {width:1024,height:640}, {width:390,height:844}]) {
    await page.setViewportSize(viewport);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.screenshot({path:`/tmp/nautilus-plans-${viewport.width}.png`,fullPage:true});
  }
});
