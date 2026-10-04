import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { authorize } from './fact-helpers';
import type { LearningPathView } from '../src/learning-path-api';

const key = (label: string) => `d2-path-test:${label}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
async function pathView(request: APIRequestContext, planId: string): Promise<LearningPathView> {
  const response = await request.get(`/api/learning/plans/${planId}/path`);
  expect(response.ok()).toBeTruthy(); return response.json();
}
async function seed(request: APIRequestContext) {
  const title = key('合成路径计划');
  const response = await request.post('/api/learning/plans', { data: { title, description: '', goal_id: null, request_key: key('plan') } });
  expect(response.status()).toBe(201);
  const { plan_id } = await response.json();
  const tasks: Array<{ action_id: string; delegation_id: string; outcome_id: string; title: string }> = [];
  for (const title of ['合成样例任务', '合成边界任务', '合成未关联任务']) {
    const organization = await (await request.get(`/api/learning/plans/${plan_id}/organization`)).json();
    const result = await request.post(`/api/learning/plans/${plan_id}/tasks`, { data: {
      action_title: title, context_key: 'D2合成路径检查', object_description: title, behavior: '比较两个测试输入', outcome_context_key: 'D2合成路径检查',
      outcome_id: null, criterion_id: null, boundaries: '', stop_conditions: '核对输入后停止', time_budget_minutes: null,
      expected_revision: organization.revision, request_key: key('task'),
    } });
    expect(result.status()).toBe(201); tasks.push({ ...await result.json(), title });
  }
  return { planId: plan_id as string, title, tasks };
}
async function openPath(page: Page, plan: { planId: string; title: string }) {
  await page.goto(`/?view=plans&plan=${plan.planId}`);
  await page.getByText('路径图', { exact: true }).click();
  await expect(page.getByRole('region', { name: '计划路径', exact: true })).toBeVisible();
}
async function manualDraft(page: Page, title: string, firstTask: string, secondTask?: string) {
  await page.getByRole('button', { name: '建立路径', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '建立路径', exact: true });
  await editor.getByRole('textbox', { name: '路线名称', exact: true }).fill(title);
  let stage = editor.getByRole('group', { name: '阶段 1', exact: true });
  await stage.getByRole('textbox', { name: '阶段名称', exact: true }).fill('比较输入');
  await stage.getByText('关联任务与成果', { exact: true }).click();
  await stage.getByRole('group', { name: '计划任务', exact: true }).getByRole('checkbox', { name: firstTask, exact: true }).check();
  if (secondTask) {
    await editor.getByRole('button', { name: '添加阶段', exact: true }).click();
    stage = editor.getByRole('group', { name: '阶段 2', exact: true });
    // Equal titles remain separate logical nodes, with different task identities.
    await stage.getByRole('textbox', { name: '阶段名称', exact: true }).fill('比较输入');
    await stage.getByText('关联任务与成果', { exact: true }).click();
    await stage.getByRole('group', { name: '计划任务', exact: true }).getByRole('checkbox', { name: secondTask, exact: true }).check();
  }
  await editor.getByRole('button', { name: '保存草案', exact: true }).click();
  await expect(editor).toHaveCount(0);
  await expect(page.getByRole('button', { name: '查看采用方案', exact: true })).toBeVisible();
}
async function confirmCandidate(page: Page, label = '确认采用') {
  await page.getByRole('button', { name: '查看采用方案', exact: true }).click();
  const preview = page.locator('.learning-path-preview');
  await expect(preview).toBeVisible();
  await preview.getByRole('button', { name: label, exact: true }).click();
  await expect(preview).toHaveCount(0);
}

test('manual drafts, real node start, direction adoption, restore and undo retain original work', async ({ page }) => {
  await authorize(page);
  const plan = await seed(page.request);
  const initialSessionCount = (await (await page.request.get('/api/learning/state')).json()).sessions.length;
  await openPath(page, plan);
  await manualDraft(page, '合成比较路线', plan.tasks[0].title, plan.tasks[1].title);
  let view = await pathView(page.request, plan.planId);
  const initialDraft = view.drafts[0];
  await page.getByRole('button', { name: '编辑草案', exact: true }).click();
  const rename = page.getByRole('dialog', { name: '建立路径', exact: true });
  for (const position of [1, 2]) await rename.getByRole('group', { name: `阶段 ${position}`, exact: true }).getByRole('textbox', { name: '阶段名称', exact: true }).fill('比较输入（已核对）');
  await rename.getByRole('button', { name: '保存草案', exact: true }).click();
  await expect(rename).toHaveCount(0);
  view = await pathView(page.request, plan.planId);
  expect(view.drafts[0].id).toBe(initialDraft.id);
  for (const node of initialDraft.nodes) await expect(page.locator(`[data-path-node="draft:${initialDraft.id}:${node.id}"]`)).toContainText('比较输入（已核对）');
  expect(view.adopted_version_id).toBeNull();
  expect(view.drafts[0].nodes).toHaveLength(2);
  expect(view.drafts[0].edges).toEqual([{ source: view.drafts[0].nodes[0].id, target: view.drafts[0].nodes[1].id }]);
  await confirmCandidate(page);
  view = await pathView(page.request, plan.planId);
  const original = view.versions.find(version => version.id === view.adopted_version_id)!;
  const firstNode = original.nodes[0], secondNode = original.nodes[1];
  let state = await (await page.request.get('/api/learning/state')).json();
  expect(state.sessions).toHaveLength(initialSessionCount);
  await expect(page.locator('[data-path-node]')).toHaveCount(2);
  await page.locator(`[data-path-node="version:${original.id}:${firstNode.id}"]`).click();
  await expect(page.locator('.learning-path-detail')).toContainText(plan.tasks[0].title);
  await expect(page.locator('.learning-path-detail')).not.toContainText(plan.tasks[1].title);
  await page.locator(`[data-path-node="version:${original.id}:${secondNode.id}"]`).click();
  await expect(page.locator('.learning-path-detail')).toContainText(plan.tasks[1].title);
  await page.locator('.learning-path-detail').getByRole('button', { name: '开始学习', exact: true }).click();
  await expect(page.getByRole('region', { name: '本次学习安排' })).toContainText(plan.tasks[1].title);
  state = await (await page.request.get('/api/learning/state')).json();
  const session = state.sessions.find((item: { delegation_id: string; status: string }) => item.delegation_id === plan.tasks[1].delegation_id && item.status === 'running');
  expect(session).toBeTruthy();
  expect((await pathView(page.request, plan.planId)).current_node_id).toBe(secondNode.id);
  const saved = await page.request.post('/api/learning/artifacts', { data: { session_id: session.id, content: '合成作答：已比较普通输入，边界输入尚未继续。', expected_version: state.actions.find((item: { id: string }) => item.id === plan.tasks[1].action_id).version, idempotency_key: key('artifact') } });
  expect(saved.status()).toBe(201);
  const artifactId = (await saved.json()).id;
  await page.getByRole('button', { name: '返回工作区', exact: true }).click();
  await openPath(page, plan);
  await page.getByRole('button', { name: '调整方向', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '调整方向', exact: true });
  await editor.getByLabel('这次想调整什么', { exact: true }).selectOption('change_direction');
  await editor.getByLabel('这还是同一个学习目标吗？', { exact: true }).selectOption('current');
  await expect(editor.getByRole('textbox', { name: '路线名称', exact: true })).toHaveValue('');
  await editor.getByRole('textbox', { name: '路线名称', exact: true }).fill('合成新方向');
  await editor.getByRole('textbox', { name: '阶段名称', exact: true }).fill('换一类输入');
  await editor.getByText('关联任务与成果', { exact: true }).click();
  await editor.getByRole('group', { name: '计划任务', exact: true }).getByRole('checkbox', { name: plan.tasks[0].title, exact: true }).check();
  await editor.getByRole('button', { name: '添加阶段', exact: true }).click();
  const futureStage = editor.getByRole('group', { name: '阶段 2', exact: true });
  await futureStage.getByRole('textbox', { name: '阶段名称', exact: true }).fill('独立检查');
  await futureStage.getByText('关联任务与成果', { exact: true }).click();
  await futureStage.getByRole('group', { name: '计划任务', exact: true }).getByRole('checkbox', { name: plan.tasks[2].title, exact: true }).check();
  await editor.getByRole('button', { name: '保存草案', exact: true }).click();
  await expect(editor).toHaveCount(0);
  await page.getByRole('button', { name: '查看采用方案', exact: true }).click();
  const preview = page.locator('.learning-path-preview');
  await expect(preview).toContainText('确认后暂停当前学习');
  await expect(preview).toContainText(plan.tasks[1].title);
  await preview.getByRole('button', { name: '取消', exact: true }).click();
  state = await (await page.request.get('/api/learning/state')).json();
  expect(state.sessions.find((item: { id: string }) => item.id === session.id).status).toBe('running');
  await confirmCandidate(page, '确认调整');
  view = await pathView(page.request, plan.planId);
  expect(view.versions).toHaveLength(2);
  expect(view.adopted_version_id).not.toBe(original.id);
  state = await (await page.request.get('/api/learning/state')).json();
  expect(state.sessions).toHaveLength(initialSessionCount + 1);
  expect(state.sessions.find((item: { id: string }) => item.id === session.id).status).toBe('interrupted');
  expect(state.artifacts.find((item: { id: string }) => item.id === artifactId).content).toBe('合成作答：已比较普通输入，边界输入尚未继续。');
  await expect(page.locator(`[data-path-node="version:${original.id}:${secondNode.id}"]`)).toContainText('上次位置');
  await page.locator('.learning-paths').screenshot({ path: '/tmp/nautilus-d2-path-desktop.png' });
  await page.locator(`[data-path-node="version:${original.id}:${firstNode.id}"]`).click();
  await page.getByRole('button', { name: '全图', exact: true }).click();
  await page.screenshot({ path: '/tmp/nautilus-d2-path-review-desktop-branch.png', fullPage: true });
  await page.getByRole('button', { name: '从这里继续', exact: true }).click();
  await expect(preview).toContainText('没有精确的旧对话位置');
  await preview.getByRole('button', { name: '确认恢复', exact: true }).click();
  await expect(preview).toHaveCount(0);
  view = await pathView(page.request, plan.planId);
  expect(view.current_node_id).toBe(firstNode.id);
  expect((await (await page.request.get('/api/learning/state')).json()).sessions).toHaveLength(initialSessionCount + 1);
  await page.getByRole('button', { name: '撤销上次调整', exact: true }).click();
  await preview.getByRole('button', { name: '确认撤销', exact: true }).click();
  await expect(preview).toHaveCount(0);
  state = await (await page.request.get('/api/learning/state')).json();
  expect(state.artifacts.find((item: { id: string }) => item.id === artifactId).content).toBeTruthy();
  expect(state.delegations.find((item: { id: string }) => item.id === plan.tasks[1].delegation_id).outcome_id).toBe(plan.tasks[1].outcome_id);
});

test('conflicts preserve draft input and busy previews require an explicit new review', async ({ page }) => {
  await authorize(page);
  const plan = await seed(page.request);
  await openPath(page, plan);
  await manualDraft(page, '合成冲突路线', plan.tasks[0].title);
  await confirmCandidate(page);
  await page.getByRole('button', { name: '调整方向', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '调整方向', exact: true });
  await editor.getByRole('textbox', { name: '路线名称', exact: true }).fill('本人正在核对的路线');
  const organization = await (await page.request.get(`/api/learning/plans/${plan.planId}/organization`)).json();
  expect((await page.request.post(`/api/learning/plans/${plan.planId}/modules`, { data: { title: '合成并发模块', description: '', parent_module_id: null, expected_revision: organization.revision, request_key: key('concurrent') } })).status()).toBe(201);
  await editor.getByRole('button', { name: '保存草案', exact: true }).click();
  await expect(editor.getByRole('alert')).toContainText('输入已保留');
  await expect(editor.getByRole('textbox', { name: '路线名称', exact: true })).toHaveValue('本人正在核对的路线');
  await editor.getByRole('button', { name: '读取最新状态', exact: true }).click();
  await editor.getByRole('button', { name: '已核对，继续编辑', exact: true }).click();
  await editor.getByRole('button', { name: '保存草案', exact: true }).click();
  await expect(editor).toHaveCount(0);
  // This isolated response checks the client boundary without starting an AI run.
  await page.route(`**/api/learning/plans/${plan.planId}/path/previews`, route => route.fulfill({ status: 409, json: { detail: { kind: 'path_generation_running', message: '相关对话仍在生成。' } } }));
  await page.getByRole('button', { name: '查看采用方案', exact: true }).click();
  const preview = page.locator('.learning-path-preview');
  await expect(preview.getByRole('alert')).toContainText('先完成或取消当前回答');
  await expect(preview.getByRole('button', { name: '确认调整', exact: true })).toBeDisabled();
  await page.unroute(`**/api/learning/plans/${plan.planId}/path/previews`);
  await preview.getByRole('button', { name: '重新读取并核对', exact: true }).click();
  await expect(preview.getByRole('button', { name: '确认调整', exact: true })).toBeEnabled();
  await preview.getByRole('button', { name: '取消', exact: true }).click();
  const view = await pathView(page.request, plan.planId);
  expect(view.versions).toHaveLength(1);
  expect(view.drafts.some(draft => draft.title === '本人正在核对的路线')).toBeTruthy();
});

test('390 and 320px path controls, drawer, nested preview, identity and completed record entries work', async ({ page }) => {
  await authorize(page);
  const plan = await seed(page.request);
  await openPath(page, plan);
  await manualDraft(page, '合成手机路线', plan.tasks[0].title, plan.tasks[1].title);
  await confirmCandidate(page);
  const completed = await page.request.post(`/api/learning/delegations/${plan.tasks[0].delegation_id}/completion`, { data: { request_key: key('completed'), verification_kind: 'unverified', note: '合成任务已执行，能力尚未验证。', report: null, material: null } });
  expect(completed.status()).toBe(200);
  await page.reload();
  await page.getByText('路径图', { exact: true }).click();
  let view = await pathView(page.request, plan.planId);
  const original = view.versions.find(version => version.id === view.adopted_version_id)!;
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    const canvas = page.locator('.learning-path-canvas');
    await canvas.scrollIntoViewIfNeeded();
    await expect(canvas.getByRole('button', { name: '全图', exact: true })).toBeInViewport({ ratio: 1 });
    const transform = await page.locator('.learning-path-canvas__space').getAttribute('data-path-transform');
    await canvas.getByRole('button', { name: '放大路径图', exact: true }).click();
    await expect(page.locator('.learning-path-canvas__space')).not.toHaveAttribute('data-path-transform', transform!);
    const beforePan = await page.locator('.learning-path-canvas__space').getAttribute('data-path-transform');
    const viewport = await page.locator('.learning-path-canvas__viewport').boundingBox();
    await page.mouse.move(viewport!.x + 8, viewport!.y + 8);
    await page.mouse.down();
    await page.mouse.move(viewport!.x + 54, viewport!.y + 35, { steps: 5 });
    await page.mouse.up();
    await expect(page.locator('.learning-path-canvas__space')).not.toHaveAttribute('data-path-transform', beforePan!);
    await canvas.getByRole('button', { name: '当前位置', exact: true }).click();
    const drawer = page.getByRole('dialog', { name: '比较输入', exact: true });
    await expect(drawer.getByRole('button', { name: '回看记录', exact: true })).toBeVisible();
    await expect(drawer.getByRole('button', { name: /开始学习|继续学习/ })).toHaveCount(0);
    await page.keyboard.press('Escape');
    await expect(drawer).toHaveCount(0);
    await expect(page.locator(`[data-path-node="version:${original.id}:${original.nodes[0].id}"]`)).toBeFocused();
    await canvas.screenshot({ path: `/tmp/nautilus-d2-path-canvas-${width}.png` });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '调整方向', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '调整方向', exact: true });
  await editor.getByRole('textbox', { name: '路线名称', exact: true }).fill('合成待核对手机方向');
  await editor.getByRole('button', { name: '保存草案', exact: true }).click();
  await expect(editor).toHaveCount(0);
  const candidateDrawer = page.getByRole('dialog', { name: '比较输入', exact: true });
  const trigger = candidateDrawer.getByRole('button', { name: '查看采用方案', exact: true });
  await trigger.click();
  const preview = page.locator('.learning-path-preview');
  await expect(preview).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(preview).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await expect(candidateDrawer).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(candidateDrawer).toHaveCount(0);
  view = await pathView(page.request, plan.planId);
  expect(view.adopted_version_id).toBe(original.id);
  expect(view.drafts).toHaveLength(1);
});

test('cross-plan preview cancels safely and confirmation pauses the source without moving tasks or making a goal', async ({ page }) => {
  await authorize(page);
  const plan = await seed(page.request);
  await openPath(page, plan);
  await manualDraft(page, '合成原路线', plan.tasks[0].title, plan.tasks[1].title);
  await confirmCandidate(page);
  let view = await pathView(page.request, plan.planId);
  const originalVersion = view.adopted_version_id!;
  const before = await (await page.request.get('/api/learning/state')).json();
  const start = await page.request.post('/api/learning/sessions', { data: { delegation_id: plan.tasks[0].delegation_id, expected_version: before.actions.find((item: { id: string }) => item.id === plan.tasks[0].action_id).version, idempotency_key: key('cross-start') } });
  expect(start.status()).toBe(201);
  const sessionId = (await start.json()).id;
  await page.reload();
  await page.getByRole('button', { name: '调整方向', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '调整方向', exact: true });
  await editor.getByLabel('这次想调整什么', { exact: true }).selectOption('change_direction');
  await expect(editor.getByLabel('这还是同一个学习目标吗？', { exact: true })).toHaveValue('new');
  const destination = key('合成独立计划');
  await editor.getByRole('textbox', { name: '新计划名称', exact: true }).fill(destination);
  await editor.getByRole('textbox', { name: '路线名称', exact: true }).fill('合成独立实践路线');
  await editor.getByRole('textbox', { name: '阶段名称', exact: true }).fill('处理不同输入');
  await editor.getByText('关联任务与成果', { exact: true }).click();
  const taskChoices = editor.getByRole('group', { name: '计划任务', exact: true });
  await expect(taskChoices.getByRole('checkbox', { name: plan.tasks[0].title, exact: true })).toBeDisabled();
  await expect(taskChoices.getByRole('checkbox', { name: plan.tasks[0].title, exact: true })).not.toBeChecked();
  const outcomes = editor.getByRole('group', { name: '已有成果（可选）', exact: true });
  await outcomes.locator(`input[data-path-outcome="${plan.tasks[0].outcome_id}"]`).check();
  await editor.getByRole('button', { name: '查看转向方案', exact: true }).click();
  const preview = page.locator('.learning-path-transfer-preview');
  await expect(preview).toContainText(destination);
  await expect(preview).toContainText('确认后暂停原计划当前学习');
  await preview.getByRole('button', { name: '取消', exact: true }).click();
  let state = await (await page.request.get('/api/learning/state')).json();
  expect(state.plans).toHaveLength(before.plans.length);
  expect(state.sessions.find((item: { id: string }) => item.id === sessionId).status).toBe('running');
  await expect(editor.getByRole('textbox', { name: '新计划名称', exact: true })).toHaveValue(destination);
  await editor.getByRole('button', { name: '查看转向方案', exact: true }).click();
  await preview.getByRole('button', { name: '确认新建并转向', exact: true }).click();
  await expect(preview).toHaveCount(0);
  await expect(page.locator('.learning-plan-detail')).toContainText(destination);
  state = await (await page.request.get('/api/learning/state')).json();
  const created = state.plans.find((item: { title: string }) => item.title === destination);
  expect(created.goal_id).toBeNull();
  expect(state.goals).toHaveLength(before.goals.length);
  expect(state.action_links.filter((item: { plan_id: string }) => item.plan_id === created.id)).toHaveLength(0);
  for (const task of plan.tasks) expect(state.action_links.find((item: { action_id: string }) => item.action_id === task.action_id).plan_id).toBe(plan.planId);
  expect(state.sessions).toHaveLength(before.sessions.length + 1);
  expect(state.sessions.find((item: { id: string }) => item.id === sessionId).status).toBe('interrupted');
  const destinationPath = await pathView(page.request, created.id);
  expect(destinationPath.versions.find(version => version.id === destinationPath.adopted_version_id)!.nodes[0]).toMatchObject({ action_ids: [], outcome_ids: [plan.tasks[0].outcome_id] });
  await page.locator('.learning-paths').screenshot({ path: '/tmp/nautilus-d2-path-review-desktop.png' });
  await page.getByText('转向来源与新计划', { exact: true }).click();
  await page.getByRole('link', { name: `查看原路线：${plan.title}`, exact: true }).click();
  await expect(page.getByRole('button', { name: '预览恢复原方向', exact: true })).toBeVisible();
  await expect(page.locator('.learning-path-detail').getByRole('button', { name: /开始学习|继续学习/ })).toHaveCount(0);
  view = await pathView(page.request, plan.planId);
  expect(view.status).toBe('paused');
  expect(view.adopted_version_id).toBe(originalVersion);
  await page.getByRole('button', { name: '任务', exact: true }).click();
  await page.locator('.learning-plan-organization').screenshot({ path: '/tmp/nautilus-d2-path-review-organization.png' });
  await page.getByRole('button', { name: '路径图', exact: true }).click();
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    const source = await pathView(page.request, plan.planId);
    const version = source.versions.find(item => item.id === source.adopted_version_id)!;
    const drawer = page.getByRole('dialog', { name: '比较输入', exact: true });
    if (!await drawer.isVisible()) await page.locator(`[data-path-node="version:${version.id}:${version.checkpoint?.node_id ?? version.current_node_id}"]`).click();
    await expect(drawer).toContainText('暂停方向');
    await page.screenshot({ path: `/tmp/nautilus-d2-path-review-drawer-${width}.png` });
    await page.keyboard.press('Escape');
    await expect(drawer).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  }
  await page.getByRole('button', { name: '预览恢复原方向', exact: true }).click();
  const restore = page.locator('.learning-path-preview');
  await restore.getByRole('button', { name: '确认恢复', exact: true }).click();
  await expect(restore).toHaveCount(0);
  expect((await pathView(page.request, plan.planId)).status).toBe('active');
  expect((await (await page.request.get('/api/learning/state')).json()).sessions.find((item: { id: string }) => item.id === sessionId).status).toBe('interrupted');
});

test('ordinary task entry explains a different linked stage without moving the route marker', async ({ page }) => {
  await authorize(page);
  const plan = await seed(page.request);
  await openPath(page, plan);
  await manualDraft(page, '合成独立定位路线', plan.tasks[0].title, plan.tasks[1].title);
  await confirmCandidate(page);
  const initial = await pathView(page.request, plan.planId);
  const state = await (await page.request.get('/api/learning/state')).json();
  const response = await page.request.post('/api/learning/sessions', { data: { delegation_id: plan.tasks[1].delegation_id, expected_version: state.actions.find((item: { id: string }) => item.id === plan.tasks[1].action_id).version, idempotency_key: key('ordinary') } });
  expect(response.status()).toBe(201);
  await page.reload();
  await expect(page.locator('.learning-path-outside')).toContainText(`当前正在学习：${plan.tasks[1].title}`);
  await page.getByRole('button', { name: '查看关联阶段', exact: true }).click();
  await expect(page.locator('.learning-path-detail')).toContainText(plan.tasks[1].title);
  expect((await pathView(page.request, plan.planId)).current_node_id).toBe(initial.current_node_id);
  expect((await pathView(page.request, plan.planId)).revision).toBe(initial.revision);
});
