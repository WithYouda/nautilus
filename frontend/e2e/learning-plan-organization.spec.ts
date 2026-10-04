import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { authorize } from './fact-helpers';
import type { PlanOrganization } from '../src/learning-organization-api';

const unique = (label: string) => `${label}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
async function organization(request: APIRequestContext, planId: string): Promise<PlanOrganization> {
  const response = await request.get(`/api/learning/plans/${planId}/organization`);
  expect(response.ok()).toBeTruthy(); return response.json();
}
async function createPlan(request: APIRequestContext, title: string) {
  const response = await request.post('/api/learning/plans', { data: { title, description: '', goal_id: null, request_key: unique('test-plan') } });
  expect(response.status()).toBe(201); return response.json() as Promise<{ plan_id: string; organization: PlanOrganization }>;
}
async function createTask(request: APIRequestContext, planId: string, title: string) {
  const data = await organization(request, planId);
  const response = await request.post(`/api/learning/plans/${planId}/tasks`, { data: {
    action_title: title, context_key: '合成组织检查', object_description: '测试文本', behavior: '拆分文本', outcome_context_key: '合成组织检查',
    outcome_id: null, criterion_id: null, boundaries: '', stop_conditions: '核对样例后停止', time_budget_minutes: null,
    expected_revision: data.revision, request_key: unique('test-task'),
  } });
  expect(response.status()).toBe(201); return response.json() as Promise<{ action_id: string; delegation_id: string; outcome_id: string }>;
}
async function openPlan(page: Page, title: string) {
  await page.getByRole('button', { name: '学习计划', exact: true }).click();
  await page.locator('.learning-plans__list').getByRole('button').filter({ has: page.getByText(title, { exact: true }) }).click();
  await expect(page.getByRole('button', { name: '组织任务', exact: true })).toBeVisible();
}
async function saveModule(dialog: Locator, title: string, parent = '') {
  await dialog.getByRole('button', { name: '新建模块', exact: true }).click();
  await dialog.getByLabel('模块名称', { exact: true }).fill(title);
  await dialog.getByLabel('父模块', { exact: true }).selectOption(parent);
  await dialog.getByRole('button', { name: '创建模块', exact: true }).click();
  await expect(dialog.getByRole('status')).toContainText('已保存组织');
}

test('a plan can have no goal and explicitly saves tasks without starting a session', async ({ page }) => {
  await authorize(page);
  await page.getByRole('button', { name: '学习计划', exact: true }).click();
  await page.getByRole('button', { name: '创建', exact: true }).click();
  const create = page.getByRole('dialog', { name: '创建学习计划', exact: true });
  const title = unique('合成无目标计划');
  await create.getByLabel('计划名称', { exact: true }).fill(title);
  await expect(create.getByLabel('关联目标（可选）', { exact: true })).toHaveValue('');
  await create.getByRole('button', { name: '创建计划', exact: true }).click();
  await expect(create).toHaveCount(0);
  await expect(page.locator('.learning-plan-detail')).toContainText(title);
  const before = await (await page.request.get('/api/learning/state')).json();
  const plan = before.plans.find((item: { title: string }) => item.title === title);
  expect(plan.goal_id).toBeNull();
  await page.getByRole('button', { name: '添加下一步', exact: true }).click();
  const task = page.getByRole('dialog', { name: '添加下一步', exact: true });
  await task.getByLabel('任务名称', { exact: true }).fill('合成检查：清理一段文本');
  await task.getByLabel('学习对象', { exact: true }).fill('含空行的测试文本');
  await task.getByLabel('希望具备的能力', { exact: true }).fill('独立拆分并清理文本');
  await task.getByLabel('做到哪里可以停', { exact: true }).fill('核对三个输入样例后停下');
  const taskRequest = page.waitForRequest(request => request.method() === 'POST' && new URL(request.url()).pathname === `/api/learning/plans/${plan.id}/tasks`);
  await task.getByRole('button', { name: '确认任务', exact: true }).click();
  expect((await taskRequest).postDataJSON()).toMatchObject({ outcome_id: null, criterion_id: null, time_budget_minutes: null, context_key: '本次学习', outcome_context_key: '本次学习' });
  await expect(task).toHaveCount(0);
  const after = await (await page.request.get('/api/learning/state')).json();
  const actionId = after.action_links.find((item: { plan_id: string }) => item.plan_id === plan.id).action_id;
  const delegation = after.delegations.find((item: { action_id: string }) => item.action_id === actionId);
  const outcome = after.outcomes.find((item: { id: string }) => item.id === delegation.outcome_id);
  expect(outcome.object_description).toBe('含空行的测试文本');
  expect(outcome.behavior).toBe('独立拆分并清理文本');
  expect(after.sessions).toHaveLength(before.sessions.length);
  expect(delegation.status).toBe('ready');
  expect((await organization(page.request, plan.id)).children).toEqual([expect.objectContaining({ kind: 'task', id: actionId, parent_module_id: null })]);
  await expect(page.locator(`[data-task-id="${actionId}"]`).getByRole('button', { name: '开始学习', exact: true })).toBeVisible();
  // Explicitly reuse the same atomic outcome for a separate task, without copying its identity.
  await page.getByRole('button', { name: '添加下一步', exact: true }).click();
  await task.getByLabel('任务名称', { exact: true }).fill('合成检查：再做一个不同输入');
  await task.getByLabel('做到哪里可以停', { exact: true }).fill('核对新的输入后停下');
  await task.getByText('情境、时间与已有成果', { exact: true }).click();
  await expect(task.getByLabel('成果来源', { exact: true }).locator(`option[value="${outcome.id}"]`)).toHaveCount(1);
  await task.getByLabel('成果来源', { exact: true }).selectOption(outcome.id);
  await expect(task.getByRole('textbox', { name: '希望具备的能力', exact: true })).toHaveValue('独立拆分并清理文本');
  await task.getByRole('button', { name: '确认任务', exact: true }).click();
  await expect(task).toHaveCount(0);
  const reused = await (await page.request.get('/api/learning/state')).json();
  expect(reused.outcomes).toHaveLength(after.outcomes.length);
  expect(reused.delegations.filter((item: { outcome_id: string }) => item.outcome_id === outcome.id)).toHaveLength(2);
  expect(reused.sessions).toHaveLength(before.sessions.length);
});

test('nested modules, direct tasks, mixed order, conflict drafts and mobile confirmations preserve identity', async ({ page }) => {
  await authorize(page);
  const title = unique('合成任务组织计划');
  const plan = await createPlan(page.request, title);
  const first = await createTask(page.request, plan.plan_id, '直接任务');
  const second = await createTask(page.request, plan.plan_id, '嵌套任务');
  await openPlan(page, title);
  await expect(page.locator('.learning-organization-tree [data-task-id]')).toHaveCount(2);
  await page.getByRole('button', { name: '组织任务', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '组织任务', exact: true });
  await saveModule(dialog, '文本处理');
  let data = await organization(page.request, plan.plan_id);
  const parentId = data.modules.find(item => item.title === '文本处理')!.id;
  await saveModule(dialog, '边界情况', parentId);
  data = await organization(page.request, plan.plan_id);
  const childId = data.modules.find(item => item.title === '边界情况')!.id;
  await dialog.getByRole('button', { name: '编辑模块：边界情况', exact: true }).click();
  await dialog.getByLabel('父模块', { exact: true }).selectOption('');
  await dialog.getByRole('button', { name: '保存组织', exact: true }).click();
  await expect.poll(async () => (await organization(page.request, plan.plan_id)).modules.find(item => item.id === childId)?.parent_module_id).toBeNull();
  await dialog.getByLabel('父模块', { exact: true }).selectOption(parentId);
  await dialog.getByRole('button', { name: '保存组织', exact: true }).click();
  await expect.poll(async () => (await organization(page.request, plan.plan_id)).modules.find(item => item.id === childId)?.parent_module_id).toBe(parentId);
  await dialog.getByRole('button', { name: '移动任务：嵌套任务', exact: true }).click();
  await dialog.getByLabel('放入', { exact: true }).selectOption(childId);
  await dialog.getByRole('button', { name: '保存组织', exact: true }).click();
  await expect(dialog.getByRole('status')).toContainText('已保存组织');
  await dialog.getByLabel('放入', { exact: true }).selectOption('');
  await dialog.getByRole('button', { name: '保存组织', exact: true }).click();
  await expect.poll(async () => (await organization(page.request, plan.plan_id)).children.find(item => item.id === second.action_id)?.parent_module_id).toBeNull();
  await dialog.getByLabel('放入', { exact: true }).selectOption(childId);
  await dialog.getByRole('button', { name: '保存组织', exact: true }).click();
  await expect.poll(async () => (await organization(page.request, plan.plan_id)).children.find(item => item.id === second.action_id)?.parent_module_id).toBe(childId);
  await dialog.getByRole('button', { name: '编辑模块：文本处理', exact: true }).click();
  await expect(dialog.getByLabel('父模块', { exact: true }).locator(`option[value="${childId}"]`)).toHaveCount(0);
  await dialog.getByRole('button', { name: '向上移', exact: true }).click();
  await expect.poll(async () => (await organization(page.request, plan.plan_id)).children.filter(item => item.parent_module_id === null).sort((a, b) => a.position - b.position).map(item => item.id)).toEqual([parentId, first.action_id]);
  await dialog.getByLabel('模块名称', { exact: true }).fill('文本处理（已核对）');
  // A concurrent addition invalidates the revision while preserving the entered name.
  data = await organization(page.request, plan.plan_id);
  const external = await page.request.post(`/api/learning/plans/${plan.plan_id}/modules`, { data: {
    title: '另一处新增', description: '', parent_module_id: null, expected_revision: data.revision, request_key: unique('test-concurrent'),
  } });
  expect(external.status()).toBe(201);
  await dialog.getByRole('button', { name: '保存组织', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('输入已保留');
  await expect(dialog.getByLabel('模块名称', { exact: true })).toHaveValue('文本处理（已核对）');
  await expect(dialog.getByRole('button', { name: '保存组织', exact: true })).toBeDisabled();
  await dialog.getByRole('button', { name: '读取最新状态', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '编辑模块：另一处新增', exact: true })).toBeVisible();
  await expect(dialog.getByLabel('模块名称', { exact: true })).toHaveValue('文本处理（已核对）');
  await dialog.getByRole('button', { name: '已核对，继续编辑', exact: true }).click();
  await dialog.getByRole('button', { name: '保存组织', exact: true }).click();
  await expect(dialog.getByRole('status')).toContainText('已保存组织');
  await dialog.getByRole('button', { name: '完成', exact: true }).click();
  await page.reload();
  await expect(page.locator(`[data-module-id="${parentId}"] [data-module-id="${childId}"] [data-task-id="${second.action_id}"]`)).toBeVisible();
  await page.screenshot({ path: '/tmp/nautilus-d2-path-review-organization-nested.png', fullPage: true });
  await expect(page.locator(`[data-task-id="${first.action_id}"]`).getByRole('button', { name: '查看记录', exact: true })).toBeVisible();
  const state = await (await page.request.get('/api/learning/state')).json();
  expect(state.delegations.find((item: { id: string }) => item.id === second.delegation_id)).toMatchObject({ action_id: second.action_id, outcome_id: second.outcome_id, status: 'ready' });
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await page.getByRole('button', { name: '组织任务', exact: true }).click();
    await dialog.getByRole('button', { name: '编辑模块：边界情况', exact: true }).click();
    await dialog.getByText('更多操作', { exact: true }).click();
    const purgeTrigger = dialog.getByRole('button', { name: '彻底清除模块名称与说明', exact: true });
    await purgeTrigger.click();
    const confirmation = page.getByRole('dialog', { name: '彻底清除模块名称与说明？', exact: true });
    await expect(confirmation).toBeVisible();
    const rect = await confirmation.boundingBox();
    expect(Math.abs(rect!.y + rect!.height / 2 - 422)).toBeLessThan(2);
    expect(rect!.width).toBeLessThanOrEqual(width);
    await page.keyboard.press('Escape');
    await expect(confirmation).toHaveCount(0);
    await expect(purgeTrigger).toBeFocused();
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('button', { name: '完成', exact: true })).toBeInViewport({ ratio: 1 });
    expect(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth)).toBeTruthy();
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole('button', { name: '组织任务', exact: true })).toBeFocused();
  }
});

test('closed goals retain task records and disable organization and execution', async ({ page }) => {
  await authorize(page);
  const title = unique('合成关闭目标计划');
  const setup = await page.request.post('/api/learning/setup/confirm', { data: {
    original_intent: '合成关闭目标检查', goal_title: unique('合成目标'), goal_description: '', plan_title: title, plan_description: '',
    action_title: '保留记录的任务', context_key: '合成关闭目标检查', object_description: '测试文本', behavior: '说明文本', outcome_context_key: '合成关闭目标检查',
    boundaries: '', stop_conditions: '核对后停止', time_budget_minutes: null, idempotency_key: unique('test-closed'),
  } });
  expect(setup.status()).toBe(201);
  const created = await setup.json();
  const initialOrganization = await organization(page.request, created.plan_id);
  const privateModule = await page.request.post(`/api/learning/plans/${created.plan_id}/modules`, { data: { title: '关闭目标后仍可清除的模块', description: '合成说明', parent_module_id: null, expected_revision: initialOrganization.revision, request_key: unique('closed-module') } });
  expect(privateModule.status()).toBe(201);
  const privateModuleId = (await privateModule.json()).object_id;
  const review = await (await page.request.get(`/api/learning/goals/${created.goal_id}/review`)).json();
  const closed = await page.request.post(`/api/learning/goals/${created.goal_id}/status`, { data: {
    status: 'paused', expected_version: review.goal.version, review_key: review.review_key, idempotency_key: unique('test-close'),
  } });
  expect(closed.ok()).toBeTruthy();
  await openPlan(page, title);
  await expect(page.getByRole('button', { name: '组织任务', exact: true })).toBeDisabled();
  await expect(page.locator('.learning-plan-detail').getByRole('button', { name: '添加下一步', exact: true })).toHaveCount(0);
  const task = page.locator(`[data-task-id="${created.action_id}"]`);
  await expect(task.getByRole('button', { name: /开始学习|继续学习/ })).toHaveCount(0);
  await expect(task.getByRole('button', { name: '查看记录', exact: true })).toBeVisible();
  const module = page.locator(`[data-module-id="${privateModuleId}"]`);
  await module.getByText('更多操作', { exact: true }).click();
  await module.getByRole('button', { name: '彻底清除模块名称与说明', exact: true }).click();
  const confirmation = page.getByRole('dialog', { name: '彻底清除模块名称与说明？', exact: true });
  await expect(confirmation.getByRole('button', { name: '确认清除', exact: true })).toBeEnabled();
  await confirmation.getByRole('button', { name: '确认清除', exact: true }).click();
  await expect(confirmation).toHaveCount(0);
  expect((await organization(page.request, created.plan_id)).modules.find(item => item.id === privateModuleId)?.content_available).toBe(false);
  await expect(page.getByRole('button', { name: '组织任务', exact: true })).toBeDisabled();
});

test('cleared module text stays erased while its container and purge result remain usable after reload', async ({ page }) => {
  await authorize(page);
  const title = unique('合成模块清除计划');
  const plan = await createPlan(page.request, title);
  const task = await createTask(page.request, plan.plan_id, '清除后保留的任务');
  await openPlan(page, title);
  await page.getByRole('button', { name: '组织任务', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '组织任务', exact: true });
  await saveModule(dialog, '可移动的父模块');
  const data = await organization(page.request, plan.plan_id);
  const parent = data.modules.find(item => item.title === '可移动的父模块')!;
  await saveModule(dialog, '要清除的模块');
  const module = (await organization(page.request, plan.plan_id)).modules.find(item => item.title === '要清除的模块')!;
  await dialog.getByRole('button', { name: '移动任务：清除后保留的任务', exact: true }).click();
  await dialog.getByLabel('放入', { exact: true }).selectOption(module.id);
  await dialog.getByRole('button', { name: '保存组织', exact: true }).click();
  await expect(dialog.getByRole('status')).toContainText('已保存组织');
  await dialog.getByRole('button', { name: '编辑模块：要清除的模块', exact: true }).click();
  await dialog.getByText('更多操作', { exact: true }).click();
  await dialog.getByRole('button', { name: '彻底清除模块名称与说明', exact: true }).click();
  const confirmation = page.getByRole('dialog', { name: '彻底清除模块名称与说明？', exact: true });
  await confirmation.getByRole('button', { name: '确认清除', exact: true }).click();
  await expect(confirmation).toHaveCount(0);
  await expect(dialog.getByRole('textbox', { name: '模块名称', exact: true })).toHaveValue('内容已清除');
  await expect(dialog.getByRole('textbox', { name: '模块名称', exact: true })).toBeDisabled();
  await dialog.getByLabel('父模块', { exact: true }).selectOption(parent.id);
  await dialog.getByRole('button', { name: '保存组织', exact: true }).click();
  await expect.poll(async () => (await organization(page.request, plan.plan_id)).modules.find(item => item.id === module.id)?.parent_module_id).toBe(parent.id);
  await page.reload();
  await expect(page.locator(`[data-module-id="${parent.id}"] [data-module-id="${module.id}"] [data-task-id="${task.action_id}"]`)).toBeVisible();
  await page.getByRole('button', { name: '组织任务', exact: true }).click();
  await dialog.getByRole('button', { name: '编辑模块：内容已清除', exact: true }).click();
  await dialog.getByText('更多操作', { exact: true }).click();
  await expect(dialog.getByText('名称、说明及受管理副本已清除。', { exact: true })).toBeVisible();
  await expect(dialog.getByRole('button', { name: '重试清除剩余副本', exact: true })).toHaveCount(0);
  expect((await organization(page.request, plan.plan_id)).modules.find(item => item.id === module.id)).toMatchObject({ content_available: false, can_purge_content: true });
});
