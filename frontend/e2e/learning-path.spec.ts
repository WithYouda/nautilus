import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { authorize } from './fact-helpers';
import type { LearningPathEdge, LearningPathNode, LearningPathView } from '../src/learning-path-api';
import type { CommitmentView } from '../src/learning-commitment-api';
import type { LearningState } from '../src/api';

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
async function checkedPost(request: APIRequestContext, url: string, data: object) {
  const response = await request.post(url, { data });
  expect(response.ok(), await response.text()).toBeTruthy(); return response.json();
}
async function stopOtherSyntheticSessions(request: APIRequestContext) {
  let state = await (await request.get('/api/learning/state')).json() as LearningState;
  for (const session of state.sessions.filter(item => item.status === 'running')) {
    await checkedPost(request, `/api/learning/sessions/${session.id}/end`, { disposition: 'interrupted', expected_version: state.actions.find(item => item.id === session.action_id)!.version, idempotency_key: key('isolate-running') });
    state = await (await request.get('/api/learning/state')).json() as LearningState;
  }
}
async function adoptRoute(request: APIRequestContext, planId: string, nodes: LearningPathNode[], edges: LearningPathEdge[], current = nodes[0].id) {
  const before = await pathView(request, planId), url = `/api/learning/plans/${planId}/path`;
  const draft = await checkedPost(request, `${url}/drafts`, { title: '任务画布检查路线', nodes, edges, entry_node_id: nodes[0].id, current_node_id: current,
    reason: '', intent: 'create', expected_revision: before.revision, expected_organization_revision: before.organization_revision, request_key: key('route') });
  const review = await checkedPost(request, `${url}/previews`, { draft_id: draft.draft_id });
  return checkedPost(request, `${url}/decisions`, { draft_id: draft.draft_id, expected_revision: review.revision, expected_draft_revision: review.draft_revision, review_key: review.review_key, request_key: key('adopt') }) as Promise<LearningPathView>;
}
async function inspectCanvasLayout(page: Page) {
  const result = await page.locator('.learning-path-canvas__space').evaluate(root => {
    const boxes = [...root.querySelectorAll<HTMLElement>('[data-path-stage]')].map(node => ({ id: node.dataset.pathStage, box: node.getBoundingClientRect() }));
    const overlaps = boxes.flatMap((first, index) => boxes.slice(index + 1).filter(second => first.box.left < second.box.right - 1 && first.box.right > second.box.left + 1 && first.box.top < second.box.bottom - 1 && first.box.bottom > second.box.top + 1).map(second => `${first.id}/${second.id}`));
    const outsideTasks = [...root.querySelectorAll<HTMLElement>('[data-path-canvas-task]')].filter(task => {
      const box = task.getBoundingClientRect(), parent = task.closest('[data-path-stage]')!.getBoundingClientRect();
      return box.left < parent.left || box.right > parent.right || box.top < parent.top || box.bottom > parent.bottom;
    }).map(task => task.dataset.pathCanvasTask);
    const edgesThroughStages = [...root.querySelectorAll<SVGPathElement>('[data-path-edge]')].filter(edge => {
      const matrix = edge.getScreenCTM()!, length = edge.getTotalLength();
      for (let step = 1; step < 40; step++) {
        const point = edge.getPointAtLength(length * step / 40), screen = new DOMPoint(point.x, point.y).matrixTransform(matrix);
        if (boxes.some(({ box }) => screen.x > box.left + 2 && screen.x < box.right - 2 && screen.y > box.top + 2 && screen.y < box.bottom - 2)) return true;
      }
      return false;
    }).map(edge => edge.dataset.pathEdge);
    return { overlaps, outsideTasks, edgesThroughStages };
  });
  expect(result).toEqual({ overlaps: [], outsideTasks: [], edgesThroughStages: [] });
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
  await page.getByRole('button', { name: '全图', exact: true }).click();
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

for (const width of [1280, 390, 320]) {
  test(`adding from an empty path stage displays the task and retains its association after reload at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await authorize(page);
    const plan = await seed(page.request);
    const before = await pathView(page.request, plan.planId);
    const saved = await page.request.post(`/api/learning/plans/${plan.planId}/path/drafts`, { data: {
      title: '添加任务检查路线', nodes: [
        { id: 'entry', title: '已有阶段', action_ids: [plan.tasks[0].action_id], outcome_ids: [] },
        { id: 'empty', title: '待添加任务阶段', action_ids: [], outcome_ids: [] },
      ], edges: [{ source: 'entry', target: 'empty' }], entry_node_id: 'entry', current_node_id: 'entry',
      reason: '', intent: 'create', expected_revision: before.revision, expected_organization_revision: before.organization_revision,
      request_key: key('empty-stage'),
    } });
    expect(saved.ok()).toBeTruthy();
    const draft = await saved.json();
    const review = await (await page.request.post(`/api/learning/plans/${plan.planId}/path/previews`, { data: { draft_id: draft.draft_id } })).json();
    const adopted = await page.request.post(`/api/learning/plans/${plan.planId}/path/decisions`, { data: {
      draft_id: draft.draft_id, expected_revision: review.revision, expected_draft_revision: review.draft_revision,
      review_key: review.review_key, request_key: key('adopt-empty'),
    } });
    expect(adopted.ok()).toBeTruthy();
    const initial = await adopted.json() as LearningPathView;
    const stateBefore = await (await page.request.get('/api/learning/state')).json();
    await openPath(page, plan);
    await page.getByRole('button', { name: '全图', exact: true }).click();
    await page.locator(`[data-path-node="version:${initial.adopted_version_id}:empty"]`).click();
    await page.locator('.learning-path-detail').getByRole('button', { name: '添加任务', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '添加任务', exact: true });
    await expect(dialog).toContainText('添加到阶段：待添加任务阶段');
    if (width <= 390) {
      await dialog.getByRole('button', { name: '取消', exact: true }).click();
      await expect(page.getByRole('dialog', { name: '待添加任务阶段', exact: true })).toBeVisible();
      await page.locator('.learning-path-detail').getByRole('button', { name: '添加任务', exact: true }).click();
    }
    const title = key(`阶段任务-${width}`);
    await dialog.getByRole('textbox', { name: '任务名称', exact: true }).fill(title);
    await dialog.getByRole('textbox', { name: '学习对象', exact: true }).fill('合成文本');
    await dialog.getByRole('textbox', { name: '希望具备的能力', exact: true }).fill('独立拆分文本');
    await dialog.getByRole('textbox', { name: '做到哪里可以停', exact: true }).fill('完成合成检查后停止');
    if (width === 1280) {
      const organization = await (await page.request.get(`/api/learning/plans/${plan.planId}/organization`)).json();
      const concurrent = await page.request.post(`/api/learning/plans/${plan.planId}/modules`, { data: {
        title: '并发模块', description: '', parent_module_id: null, expected_revision: organization.revision, request_key: key('concurrent-module'),
      } });
      expect(concurrent.ok()).toBeTruthy();
      await dialog.getByRole('button', { name: '确认任务', exact: true }).click();
      await expect(dialog.getByRole('button', { name: '读取最新状态', exact: true })).toBeVisible();
      await expect(dialog.getByRole('textbox', { name: '任务名称', exact: true })).toHaveValue(title);
      await dialog.getByRole('button', { name: '读取最新状态', exact: true }).click();
      await dialog.getByRole('button', { name: '已核对，继续编辑', exact: true }).click();
    }
    await dialog.getByRole('button', { name: '确认任务', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.locator('.learning-path-detail')).toContainText(title);
    await expect(page.locator('.learning-path-detail').getByRole('button', { name: '开始学习', exact: true })).toBeVisible();
    const view = await pathView(page.request, plan.planId);
    const current = view.versions.find(item => item.id === view.adopted_version_id)!;
    const node = page.locator(`[data-path-node="version:${current.id}:empty"]`);
    await expect(node).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator(`[data-path-stage="version:${current.id}:empty"]`).getByRole('button', { name: title, exact: true })).toHaveAttribute('aria-pressed', 'true');
    expect(view.current_node_id).toBe('entry');
    const state = await (await page.request.get('/api/learning/state')).json();
    const added = state.actions.find((item: { title: string }) => item.title === title);
    expect(current.nodes[1].action_ids).toEqual([added.id]);
    expect(state.sessions).toEqual(stateBefore.sessions);
    if (width <= 390) await page.getByRole('button', { name: '关闭阶段详情', exact: true }).click();
    await expect(page.locator(`[data-path-stage="version:${current.id}:empty"]`).getByRole('button', { name: title, exact: true })).toBeInViewport({ ratio: 1 });
    await page.screenshot({ path: `/tmp/nautilus-path-add-task-${width}.png`, fullPage: true });
    await page.reload();
    await page.getByRole('button', { name: '全图', exact: true }).click();
    await page.locator(`[data-path-stage="version:${current.id}:empty"]`).getByRole('button', { name: title, exact: true }).click();
    await expect(page.locator(`[data-path-stage="version:${current.id}:empty"]`).getByRole('button', { name: title, exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('.learning-path-detail')).toContainText(title);
    if (width <= 390) await page.getByRole('button', { name: '关闭阶段详情', exact: true }).click();
    await page.getByRole('button', { name: '全图', exact: true }).click();
    await page.locator(`[data-path-node="version:${initial.adopted_version_id}:empty"]`).click();
    await expect(page.locator('.learning-path-detail').getByRole('button', { name: '添加任务', exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  });
}

test('adding a task to a candidate stage updates the candidate without adopting or starting it', async ({ page }) => {
  await authorize(page);
  const plan = await seed(page.request), before = await pathView(page.request, plan.planId);
  const saved = await page.request.post(`/api/learning/plans/${plan.planId}/path/drafts`, { data: {
    title: '待核对路线', nodes: [{ id: 'candidate', title: '待核对阶段', action_ids: [], outcome_ids: [] }], edges: [],
    entry_node_id: 'candidate', current_node_id: 'candidate', reason: '', intent: 'create',
    expected_revision: before.revision, expected_organization_revision: before.organization_revision, request_key: key('candidate'),
  } });
  expect(saved.ok()).toBeTruthy();
  const draft = await saved.json();
  await openPath(page, plan);
  await page.locator(`[data-path-node="draft:${draft.draft_id}:candidate"]`).click();
  await page.locator('.learning-path-detail').getByRole('button', { name: '添加任务', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '添加任务', exact: true });
  await dialog.getByRole('textbox', { name: '任务名称', exact: true }).fill('草案阶段任务');
  await dialog.getByRole('textbox', { name: '学习对象', exact: true }).fill('合成文本');
  await dialog.getByRole('textbox', { name: '希望具备的能力', exact: true }).fill('独立处理');
  await dialog.getByRole('textbox', { name: '做到哪里可以停', exact: true }).fill('完成即停止');
  await dialog.getByRole('button', { name: '确认任务', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('.learning-path-detail')).toContainText('草案阶段任务');
  await expect(page.locator(`[data-path-stage="draft:${draft.draft_id}:candidate"]`).getByRole('button', { name: '草案阶段任务', exact: true })).toHaveAttribute('aria-pressed', 'true');
  const view = await pathView(page.request, plan.planId);
  expect(view.adopted_version_id).toBeNull();
  expect(view.drafts[0].stale).toBeFalsy();
  await expect(page.locator('.learning-path-detail').getByRole('button', { name: '开始学习', exact: true })).toHaveCount(0);
  await confirmCandidate(page);
  await expect(page.locator('.learning-path-canvas').getByRole('button', { name: '草案阶段任务', exact: true })).toBeVisible();
});

for (const width of [1280, 390, 320]) {
  test(`canvas tasks select their stage and next-stage drafts preserve both successors at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); await authorize(page);
    const plan = await seed(page.request);
    const nodes = plan.tasks.map((task, index) => ({ id: `stage-${index}`, title: ['准备输入', '处理正文', '检查边界'][index], action_ids: [task.action_id], outcome_ids: [] }));
    nodes[2].action_ids.push(plan.tasks[1].action_id);
    const original = await adoptRoute(page.request, plan.planId, nodes, [{ source: nodes[0].id, target: nodes[1].id }, { source: nodes[0].id, target: nodes[2].id }], nodes[1].id);
    await openPath(page, plan); await page.getByRole('button', { name: '全图', exact: true }).click();
    const sourceKey = `version:${original.adopted_version_id}:${nodes[0].id}`;
    await page.locator(`[data-path-stage="${sourceKey}"]`).getByRole('button', { name: plan.tasks[0].title, exact: true }).click();
    await expect(page.locator(`[data-path-node="${sourceKey}"]`)).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator(`[data-path-stage="${sourceKey}"]`).getByRole('button', { name: plan.tasks[0].title, exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator(`[data-path-stage="${sourceKey}"]`).getByRole('button', { name: plan.tasks[0].title, exact: true })).toBeInViewport({ ratio: 1 });
    const detail = page.locator('.learning-path-detail');
    await expect(detail.getByRole('button', { name: '移出阶段', exact: true })).toBeVisible();
    await expect(detail.getByRole('button', { name: '删除任务', exact: true })).toBeVisible();
    const before = await pathView(page.request, plan.planId);
    expect(before.current_node_id).toBe(nodes[1].id);
    await detail.getByRole('button', { name: '添加下一阶段', exact: true }).click();
    const editor = page.getByRole('dialog', { name: '添加下一阶段', exact: true });
    await expect(editor.getByRole('group', { name: '阶段 2', exact: true }).getByRole('textbox', { name: '阶段名称', exact: true })).toHaveValue('');
    await editor.getByRole('group', { name: '阶段 2', exact: true }).getByRole('textbox', { name: '阶段名称', exact: true }).fill('明确下一阶段');
    await expect(editor.getByLabel('起点', { exact: true })).toHaveValue(nodes[0].id);
    await expect(editor.getByLabel('当前位置', { exact: true })).toHaveValue(nodes[1].id);
    await editor.getByRole('button', { name: '保存草案', exact: true }).click();
    await expect(editor).toHaveCount(0);
    const view = await pathView(page.request, plan.planId), draft = view.drafts.find(item => item.intent === 'change_scope')!;
    expect(view.adopted_version_id).toBe(before.adopted_version_id); expect(view.current_node_id).toBe(nodes[1].id);
    const inserted = draft.nodes.find(node => node.title === '明确下一阶段')!;
    expect(draft.nodes.filter(node => node.id !== inserted.id)).toEqual(nodes);
    expect(draft.edges).toEqual(expect.arrayContaining([{ source: nodes[0].id, target: inserted.id }, { source: inserted.id, target: nodes[1].id }, { source: inserted.id, target: nodes[2].id }]));
    expect(draft.edges).toHaveLength(3);
    await expect(page.locator(`[data-path-node="draft:${draft.id}:${inserted.id}"]`)).toHaveAttribute('aria-pressed', 'true');
    if (width <= 390) await page.getByRole('button', { name: '关闭阶段详情', exact: true }).click();
    await page.getByRole('button', { name: '全图', exact: true }).click();
    await inspectCanvasLayout(page);
    await page.locator('.learning-path-canvas').screenshot({ path: `/tmp/nautilus-path-task-branches-${width}.png` });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  });
}

for (const width of [1280, 390, 320]) {
  test(`detach preserves the plan task; deletion reviews running work and retains history at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); await authorize(page);
    await stopOtherSyntheticSessions(page.request);
    const plan = await seed(page.request), task = plan.tasks[0];
    const original = await adoptRoute(page.request, plan.planId, [
      { id: 'first', title: '准备输入', action_ids: [task.action_id, plan.tasks[1].action_id], outcome_ids: [] },
      { id: 'second', title: '继续处理', action_ids: [task.action_id], outcome_ids: [] },
    ], [{ source: 'first', target: 'second' }], 'second');
    const stateBefore = await (await page.request.get('/api/learning/state')).json() as LearningState;
    const started = await checkedPost(page.request, '/api/learning/sessions', { delegation_id: task.delegation_id, expected_version: stateBefore.actions.find(item => item.id === task.action_id)!.version, idempotency_key: key('removal-start') });
    let facts = await (await page.request.get('/api/learning/state')).json() as LearningState;
    const artifact = await checkedPost(page.request, '/api/learning/artifacts', { session_id: started.id, content: '删除任务也保留的合成原始产出', expected_version: facts.actions.find(item => item.id === task.action_id)!.version, idempotency_key: key('retained-artifact') });
    const commitmentUrl = `/api/learning/plans/${plan.planId}/commitments`;
    const commitments = await (await page.request.get(commitmentUrl)).json() as CommitmentView;
    const arrangement = await checkedPost(page.request, `${commitmentUrl}/drafts`, { route_version_id: original.adopted_version_id,
      items: [{ id: null, node_id: 'second', action_id: task.action_id, delegation_id: task.delegation_id, estimate_min_minutes: null, estimate_max_minutes: null, due_at: null, timezone: null, reason: '', source_refs: [] }],
      reason: '', draft_id: null, expected_revision: commitments.revision, request_key: key('arrangement') });
    const commitmentReview = await checkedPost(page.request, `${commitmentUrl}/previews`, { draft_id: arrangement.draft_id });
    await checkedPost(page.request, `${commitmentUrl}/confirm`, { draft_id: arrangement.draft_id, expected_revision: commitmentReview.revision, expected_draft_revision: commitmentReview.draft_revision, review_key: commitmentReview.review_key, request_key: key('confirm-arrangement') });
    await openPath(page, plan); await page.getByRole('button', { name: '全图', exact: true }).click();
    await page.locator(`[data-path-stage="version:${original.adopted_version_id}:first"]`).getByRole('button', { name: task.title, exact: true }).click();
    await page.locator('.learning-path-detail').getByRole('button', { name: '移出阶段', exact: true }).click();
    let preview = page.getByRole('dialog', { name: '移出阶段', exact: true });
    await expect(preview).toContainText('任务仍保留在计划中');
    await preview.getByRole('button', { name: '确认移出阶段', exact: true }).click(); await expect(preview).toHaveCount(0);
    let view = await pathView(page.request, plan.planId), main = view.versions.find(item => item.id === view.adopted_version_id)!;
    expect(main.nodes.find(node => node.id === 'first')!.action_ids).not.toContain(task.action_id);
    expect(main.nodes.find(node => node.id === 'second')!.action_ids).toContain(task.action_id);
    facts = await (await page.request.get('/api/learning/state')).json() as LearningState;
    expect(facts.action_links.some(item => item.action_id === task.action_id && item.plan_id === plan.planId)).toBeTruthy();
    expect(facts.sessions.find(item => item.id === started.id)!.status).toBe('running');
    if (width <= 390) await page.getByRole('button', { name: '关闭阶段详情', exact: true }).click();
    await page.getByRole('button', { name: '全图', exact: true }).click();
    await page.locator(`[data-path-stage="version:${main.id}:second"]`).getByRole('button', { name: task.title, exact: true }).click();
    const trigger = page.locator('.learning-path-detail').getByRole('button', { name: '删除任务', exact: true });
    await trigger.click(); preview = page.getByRole('dialog', { name: '删除任务', exact: true });
    await expect(preview).toContainText('确认后暂停当前学习'); await expect(preview).toContainText('延期未执行部分');
    await page.keyboard.press('Escape'); await expect(preview).toHaveCount(0); await expect(trigger).toBeFocused();
    facts = await (await page.request.get('/api/learning/state')).json() as LearningState;
    expect(facts.sessions.find(item => item.id === started.id)!.status).toBe('running'); expect(facts.actions.find(item => item.id === task.action_id)!.deleted).toBeFalsy();
    await trigger.click(); await expect(preview.getByRole('button', { name: '确认删除任务', exact: true })).toBeEnabled();
    if (width === 1280) {
      const organization = await (await page.request.get(`/api/learning/plans/${plan.planId}/organization`)).json();
      await checkedPost(page.request, `/api/learning/plans/${plan.planId}/modules`, { title: '并发组织变化', description: '', parent_module_id: null, expected_revision: organization.revision, request_key: key('removal-cas') });
      await preview.getByRole('button', { name: '确认删除任务', exact: true }).click();
      await expect(preview.getByRole('button', { name: '重新读取并核对', exact: true })).toBeVisible();
      await preview.getByRole('button', { name: '重新读取并核对', exact: true }).click();
      await expect(preview.getByRole('button', { name: '确认删除任务', exact: true })).toBeEnabled();
    }
    await preview.screenshot({ path: `/tmp/nautilus-path-task-delete-preview-${width}.png` });
    await preview.getByRole('button', { name: '确认删除任务', exact: true }).click(); await expect(preview).toHaveCount(0);
    facts = await (await page.request.get('/api/learning/state')).json() as LearningState;
    expect(facts.actions.find(item => item.id === task.action_id)).toMatchObject({ status: 'cancelled', deleted: true });
    expect(facts.sessions.find(item => item.id === started.id)!.status).toBe('interrupted');
    expect(facts.artifacts.find(item => item.id === artifact.id)!.content).toBe('删除任务也保留的合成原始产出');
    view = await pathView(page.request, plan.planId); main = view.versions.find(item => item.id === view.adopted_version_id)!;
    expect(main.nodes.every(node => !node.action_ids.includes(task.action_id))).toBeTruthy();
    expect(view.versions.find(item => item.id === original.adopted_version_id)!.nodes[0].action_ids).toContain(task.action_id);
    const currentCommitments = await (await page.request.get(commitmentUrl)).json() as CommitmentView;
    expect(currentCommitments.current_version!.items.find(item => item.action_id === task.action_id)!.status).toBe('deferred');
    if (width <= 390) await page.getByRole('button', { name: '关闭阶段详情', exact: true }).click();
    await page.getByRole('button', { name: '全图', exact: true }).click();
    const historyKey = `version:${original.adopted_version_id}:first`;
    const expansion = page.locator(`[data-path-stage="${historyKey}"]`).getByRole('button', { name: /阶段任务：准备输入$/ });
    if (await expansion.getAttribute('aria-expanded') === 'false') await expansion.click();
    await page.getByRole('button', { name: '全图', exact: true }).click();
    const oldTask = page.locator(`[data-path-stage="${historyKey}"]`).getByRole('button', { name: task.title, exact: true });
    await expect(oldTask).toContainText('已删除'); await oldTask.click();
    await expect(page.locator('.learning-path-detail')).toContainText('已删除');
    await expect(page.locator('.learning-path-detail').getByRole('button', { name: '查看记录', exact: true })).toBeVisible();
    await expect(page.locator('.learning-path-detail').getByRole('button', { name: /^(删除任务|移出阶段|开始学习|继续学习)$/ })).toHaveCount(0);
    if (width <= 390) await page.getByRole('button', { name: '关闭阶段详情', exact: true }).click();
    await inspectCanvasLayout(page);
    await page.getByRole('button', { name: '任务', exact: true }).click();
    await expect(page.locator('.learning-plan-task').filter({ hasText: task.title })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  });
}

test('candidate deletion retains its draft and adopted historical references without reopening completed work', async ({ page }) => {
  await authorize(page); const plan = await seed(page.request), task = plan.tasks[0];
  const original = await adoptRoute(page.request, plan.planId, [{ id: 'shared', title: '已走阶段', action_ids: [task.action_id], outcome_ids: [] }], []);
  const completion = await checkedPost(page.request, `/api/learning/delegations/${task.delegation_id}/completion`, { request_key: key('completed-delete'), verification_kind: 'unverified', note: '合成已完成事实', report: null, material: null });
  const current = await pathView(page.request, plan.planId);
  const draft = await checkedPost(page.request, `/api/learning/plans/${plan.planId}/path/drafts`, { title: '候选保留检查', nodes: [{ id: 'candidate', title: '候选阶段', action_ids: [task.action_id], outcome_ids: [] }], edges: [], entry_node_id: 'candidate', current_node_id: 'candidate', reason: '', intent: 'change_scope', source_version_id: current.adopted_version_id,
    expected_revision: current.revision, expected_organization_revision: current.organization_revision, request_key: key('candidate-delete') });
  await openPath(page, plan); await page.getByRole('button', { name: '全图', exact: true }).click();
  await page.locator(`[data-path-stage="draft:${draft.draft_id}:candidate"]`).getByRole('button', { name: task.title, exact: true }).click();
  await page.locator('.learning-path-detail').getByRole('button', { name: '删除任务', exact: true }).click();
  await page.getByRole('dialog', { name: '删除任务', exact: true }).getByRole('button', { name: '确认删除任务', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '删除任务', exact: true })).toHaveCount(0);
  const result = await pathView(page.request, plan.planId), selected = result.drafts.find(item => item.id === draft.draft_id)!;
  expect(selected.stale).toBeFalsy(); expect(selected.nodes[0].action_ids).toEqual([]);
  expect(result.versions.find(item => item.id === result.adopted_version_id)!.nodes[0].action_ids).toEqual([]);
  expect(result.versions.find(item => item.id === original.adopted_version_id)!.nodes[0].action_ids).toEqual([task.action_id]);
  const facts = await (await page.request.get('/api/learning/state')).json() as LearningState;
  expect(facts.actions.find(item => item.id === task.action_id)).toMatchObject({ status: 'completed', deleted: true });
  const preservedCompletion = await (await page.request.get(`/api/learning/delegations/${task.delegation_id}/completion`)).json();
  expect(preservedCompletion.id).toBe(completion.id);
  await expect(page.locator(`[data-path-node="draft:${draft.draft_id}:candidate"]`)).toHaveAttribute('aria-pressed', 'true');
});
