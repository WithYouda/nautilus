import { expect, test } from '@playwright/test';
import { authorize } from './fact-helpers';

test('goal closure checks current tasks, preserves work, and can be reopened', async ({ page }) => {
  await authorize(page);
  const routes = await (await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT ?? '8012'}/openapi.json`)).json();
  expect(routes.paths['/api/learning/goals/{goal_id}/review']).toBeTruthy();
  expect(routes.paths['/api/learning/goals/{goal_id}/status']).toBeTruthy();
  const setup = { original_intent: '合成目标收尾检查', goal_title: '合成目标收尾', goal_description: '',
    plan_title: '合成收尾计划', plan_description: '', action_title: '第一项合成任务', context_key: 'goal-test',
    object_description: '合成练习', behavior: '说明结果', outcome_context_key: 'goal-test',
    boundaries: '', stop_conditions: '用户确认执行情况', idempotency_key: 'goal-setup' };
  const response = await page.request.post('/api/learning/setup/confirm', { data: setup });
  expect(response.status()).toBe(201);
  const created = await response.json();
  let state = await (await page.request.get('/api/learning/state')).json();
  const started = await page.request.post('/api/learning/sessions', { data: {
    delegation_id: created.delegation_id, expected_version: state.actions.find((item: {id:string}) => item.id === created.action_id).version,
    idempotency_key: 'goal-start',
  } });
  expect(started.status()).toBe(201);
  await page.getByRole('button', { name: '学习计划', exact: true }).click();
  await page.getByRole('button', { name: '收尾目标', exact: true }).click();
  let dialog = page.getByRole('dialog', { name: '正式收尾目标' });
  await expect(dialog).toContainText('1 项任务');
  await expect(dialog).toContainText('1 个学习会话正在运行');
  // Another tab adds a task after the review was opened. Confirmation must refresh.
  expect((await page.request.post('/api/learning/setup/confirm', { data: {
    ...setup, plan_id: created.plan_id, action_title: '另一处新增的任务', idempotency_key: 'goal-step',
  } })).status()).toBe(201);
  await dialog.getByRole('radio', { name: /由我确认目标已达成/ }).check();
  await dialog.getByRole('button', { name: '确认收尾', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('已变化');
  await dialog.getByRole('button', { name: '刷新收尾检查' }).click();
  await expect(dialog).toContainText('2 项任务');
  await dialog.getByRole('radio', { name: /由我确认目标已达成/ }).check();
  await dialog.getByRole('button', { name: '确认收尾', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('.learning-plan-detail')).toContainText('已达成');
  await expect(page.getByRole('button', { name: '添加下一步', exact: true })).toHaveCount(0);
  state = await (await page.request.get('/api/learning/state')).json();
  expect(state.actions.every((item: {status:string}) => item.status === 'open')).toBeTruthy();
  expect(state.sessions[0].status).toBe('interrupted');
  await page.reload();
  await page.getByRole('button', { name: '学习首页', exact: true }).click();
  const card = page.getByRole('region', { name: '当前学习' });
  await expect(card).toContainText('目标已达成');
  await expect(card.getByRole('button', { name: /开始学习|继续学习|添加下一步/ })).toHaveCount(0);
  await card.getByRole('button', { name: '查看目标' }).click();

  async function reopen() {
    await page.getByRole('button', { name: '查看收尾 / 重新开启' }).click();
    const review = page.getByRole('dialog', { name: '查看收尾与重新开启' });
    await review.getByRole('radio', { name: /重新开启/ }).check();
    await review.getByRole('button', { name: '确认重新开启' }).click();
    await expect(review).toHaveCount(0);
    await expect(page.getByRole('button', { name: '添加下一步', exact: true })).toBeVisible();
  }
  await reopen();
  state = await (await page.request.get('/api/learning/state')).json();
  expect(state.sessions.every((item: {status:string}) => item.status !== 'running')).toBeTruthy();
  for (const label of ['暂时停止', '放弃跟踪']) {
    await page.getByRole('button', { name: '收尾目标', exact: true }).click();
    dialog = page.getByRole('dialog', { name: '正式收尾目标' });
    await dialog.getByRole('radio', { name: new RegExp(label) }).check();
    await dialog.getByRole('button', { name: '确认收尾', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    if (label === '暂时停止') await reopen();
  }
  await page.getByRole('button', { name: '查看收尾 / 重新开启' }).click();
  const history = page.getByRole('dialog', { name: '查看收尾与重新开启' });
  await history.getByText('查看状态历史', { exact: true }).click();
  await expect(history.locator('ol li')).toHaveCount(5);
  await expect(history).toContainText('已停止跟踪');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(history.getByRole('heading', { name: '查看收尾与重新开启' })).toBeInViewport({ ratio: 1 });
  const cancel = history.getByRole('button', { name: '取消' });
  await expect(cancel).toBeVisible();
  const rect = await cancel.boundingBox();
  expect(rect!.y + rect!.height).toBeLessThanOrEqual(844);
  await page.screenshot({ path: '/tmp/nautilus-goal-closure-mobile.png' });
});
