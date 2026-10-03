import { expect, test, type Locator, type Page, type Response } from '@playwright/test';
import { authorize, checkDefaultTeachingSupport } from './fact-helpers';
import type { AiConversationDetail, AiRun, QuestionDiscussion, TeachingTextRef, VerificationReview } from '../src/api';

test.beforeEach(async ({ page }) => {
  // Confirm the isolated runtime is ready before starting either browser journey.
  const response = await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT ?? '8012'}/openapi.json`);
  expect(response.ok()).toBeTruthy();
  const schema = await response.json();
  for (const name of ['MessageSendRequest', 'QuestionDiscussionMessageRequest']) {
    const properties = schema.components.schemas[name].properties;
    expect(properties.teaching_mode.anyOf.find((value: { enum?: string[] }) => value.enum)?.enum).toContain('project');
    expect(properties.teaching_action.anyOf.find((value: { enum?: string[] }) => value.enum)?.enum).toContain('next_step');
  }
});

async function setup(page: Page) {
  await authorize(page);
  expect((await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic project practice provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model: 'mock-success', api_key: 'synthetic-project-key', enabled: true, request_timeout_seconds: 15,
  } })).ok()).toBeTruthy();
  await checkDefaultTeachingSupport(page);
  const preferences = await (await page.request.get('/api/preferences')).json();
  expect((await page.request.put('/api/preferences', { data: { ...preferences, teaching_mode: 'stepwise', search: { mode: 'off' } } })).ok()).toBeTruthy();
  await page.reload();
}

async function expand(locator: Locator) {
  await expect(locator).toBeVisible();
  if (!(await locator.evaluate(element => (element as HTMLDetailsElement).open))) await locator.locator('summary').first().click();
}

async function arrangement(page: Page) {
  const view = page.locator('.teaching-arrangement');
  await expand(view.locator('details').first());
  return view;
}

async function records(view: Locator) {
  await expand(view.locator('details').first());
  await expand(view.locator('.teaching-state__projects'));
  return view.getByRole('article', { name: '实践步骤', exact: true });
}

async function projectDefault(page: Page, screenshot?: string) {
  await page.getByRole('button', { name: '设置', exact: true }).click();
  const dialog = page.locator('.unified-settings-dialog');
  await dialog.getByRole('combobox', { name: '默认学习方式', exact: true }).selectOption('project');
  await expect(dialog).toContainText('点“下一步”才继续');
  await dialog.getByRole('button', { name: '保存默认设置', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '保存默认设置', exact: true })).toBeDisabled();
  if (screenshot) {
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: screenshot, fullPage: true });
    await page.setViewportSize({ width: 1280, height: 900 });
  }
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  expect((await (await page.request.get('/api/preferences')).json()).teaching_mode).toBe('project');
}

async function readConversation(page: Page, id: string): Promise<AiConversationDetail> {
  const response = await page.request.get(`/api/ai/conversations/${id}`);
  expect(response.ok()).toBeTruthy();
  return response.json();
}

function ordinaryResponse(page: Page) {
  return page.waitForResponse(response => /\/api\/ai\/conversations\/[^/]+\/messages$/.test(response.url()) && response.request().method() === 'POST');
}

async function ordinaryFinished(page: Page, id: string) {
  await expect.poll(async () => (await readConversation(page, id)).active_run, { timeout: 15_000 }).toBeNull();
  await expect(page.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
}

async function sendOrdinary(page: Page, content: string, complete = true): Promise<AiRun> {
  const accepted = ordinaryResponse(page);
  const input = page.getByLabel('输入学习问题', { exact: true });
  await input.fill(content); await input.press('Enter');
  const response = await accepted; expect(response.ok()).toBeTruthy();
  const { run } = await response.json();
  if (complete) await ordinaryFinished(page, run.conversation_id);
  return run;
}

async function ordinaryAction(page: Page, id: string, label: string): Promise<Response> {
  const accepted = ordinaryResponse(page);
  await page.getByRole('button', { name: label, exact: true }).click();
  const response = await accepted; expect(response.ok()).toBeTruthy();
  await ordinaryFinished(page, id);
  return response;
}

function excerpt(content: string, ref: TeachingTextRef) {
  return Array.from(content).slice(ref.start, ref.end).join('');
}

async function mobileScreenshot(page: Page, view: Locator, path: string) {
  await page.setViewportSize({ width: 390, height: 844 });
  await view.locator('.teaching-state__project').scrollIntoViewIfNeeded();
  await expect(view.locator('.teaching-state__project')).toContainText('当前目标');
  await expect(view.getByRole('button', { name: '下一步', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path, fullPage: true });
  await view.getByRole('article', { name: '实践内容', exact: true }).first().scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.replace('.png', '-history.png'), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
}

test('ordinary project practice preserves actual work, feedback, changed requirements and explicit next steps', async ({ page }) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await setup(page);
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  let view = await arrangement(page);
  await expect(view.getByLabel('讲解方式', { exact: true }).locator('option[value="project"]')).toHaveCount(0);
  await projectDefault(page, '/tmp/nautilus-project-settings-390.png');
  await expect(view.getByLabel('讲解方式', { exact: true })).toContainText('沿用设置（项目实践）');
  const run = await sendOrdinary(page, '[C2澄清] 我想做个小作品。');
  const id = run.conversation_id;
  const clarification = (await readConversation(page, id)).messages.at(-1)!;
  expect(clarification.teaching).toMatchObject({ current: { mode: 'project' }, attempt: null, project_step: null, project_observation: null });
  expect(clarification.teaching!.current.project).toBeFalsy();
  await expect(view.getByRole('button', { name: '下一步', exact: true })).toHaveCount(0);
  await sendOrdinary(page, '[C2项目] 做一个检查输入边界的小程序。');
  const first = (await readConversation(page, id)).messages.at(-1)!;
  const project = first.teaching!.project_step!;
  expect(project).toMatchObject({ id: first.id, step: { id: first.id, change: 'start', phase: 'awaiting_work', previous_step_id: null, change_request: null } });
  expect(first.teaching).toMatchObject({ default_mode: 'project', current: { mode_source: 'default', project }, attempt: null, project_observation: null });
  const originalGoal = excerpt(first.content, project.goal);
  const originalInstruction = excerpt(first.content, project.step.instruction);
  await expect(view.locator('.teaching-state__project')).toContainText(originalGoal);
  await expect(view.locator('.teaching-state__project')).toContainText(originalInstruction);
  expect(await view.locator('.teaching-state__projects').evaluate(element => (element as HTMLDetailsElement).open)).toBe(false);
  let steps = await records(view);
  await expect(steps).toHaveCount(1);
  await expect(steps.first()).toContainText(originalInstruction);
  const words = '[C2项目作品] 🧩代码：if not item: return "缺失"；操作结果：输入缺失编号，返回“缺失”。';
  await sendOrdinary(page, words);
  const feedback = (await readConversation(page, id)).messages.at(-1)!;
  expect(feedback.teaching).toMatchObject({ current: { project: { id: project.id, step: { id: project.step.id, phase: 'feedback_available' } } }, project_step: null, project_observation: { project_id: project.id, question_id: project.step.id, eligible: true, needs_help: false } });
  let work = steps.first().getByRole('article', { name: '实践内容', exact: true });
  await expect(work).toContainText(words);
  await expect(work).toContainText(feedback.content.trim());
  await expect(steps).toHaveCount(1);
  const input = page.getByLabel('输入学习问题', { exact: true });
  const draft = '还没发送的下一版代码。'; await input.fill(draft);
  await ordinaryAction(page, id, '给个提示');
  await expect(input).toHaveValue(draft);
  await expect(steps.first().getByRole('article', { name: '实践帮助', exact: true })).toContainText('想想缺失编号时');
  await sendOrdinary(page, '[C2项目作品] 🧩补充操作结果：编号2缺失时，返回“缺失”。');
  const secondFeedback = (await readConversation(page, id)).messages.at(-1)!;
  expect(secondFeedback.teaching!.project_observation!.help_context).not.toHaveLength(0);
  await expect(steps.first().getByRole('article', { name: '实践内容', exact: true })).toHaveCount(2);
  await sendOrdinary(page, '[C2项目] 请直接给答案。');
  expect((await readConversation(page, id)).messages.at(-1)!.teaching).toMatchObject({ effective_mode: 'direct_answer', current: { mode: 'project', project: { id: project.id, step: { id: project.step.id } } }, project_step: null, project_observation: null });
  await sendOrdinary(page, '[C2项目] 我已经做好了，下一步呢？');
  expect((await readConversation(page, id)).messages.at(-1)!.teaching).toMatchObject({ project_step: null, project_observation: null });
  await expect(steps).toHaveCount(1);
  await expect(steps.first().getByRole('article', { name: '实践帮助', exact: true })).toHaveCount(2);
  work = steps.first().getByRole('article', { name: '实践内容', exact: true }).first();
  await work.getByRole('button', { name: '这不是一次尝试', exact: true }).click();
  await expect(work).toContainText('已改为非尝试');
  await expect(view.getByRole('article', { name: 'AI识别的尝试', exact: true })).toHaveCount(0);
  const revisionWords = '[C2项目调整] 修改要求：缺失编号时改为返回空列表。';
  await sendOrdinary(page, revisionWords);
  const revised = (await readConversation(page, id)).messages.at(-1)!;
  const revisedProject = revised.teaching!.project_step!;
  expect(revisedProject).toMatchObject({ id: project.id, step: { id: revised.id, change: 'revision', previous_step_id: project.step.id, phase: 'awaiting_work' } });
  expect(revisedProject.step.change_request).toBeTruthy();
  const revisedInstruction = excerpt(revised.content, revisedProject.step.instruction);
  await expect(steps).toHaveCount(2);
  await expect(steps.last()).toContainText('调整要求后');
  await expect(steps.last()).toContainText(revisionWords);
  await expect(steps.first().getByRole('article', { name: '实践帮助', exact: true })).toHaveCount(2);
  await expect(view.locator('.teaching-state__project')).toContainText(revisedInstruction);
  await expect(steps.first()).toContainText(originalGoal);
  await expect(steps.first()).toContainText(originalInstruction);
  await page.reload(); view = await arrangement(page); steps = await records(view);
  work = steps.first().getByRole('article', { name: '实践内容', exact: true }).first();
  await expect(work).toContainText(words);
  await expect(work).toContainText(feedback.content.trim());
  await expect(work).toContainText('已改为非尝试');
  await expect(steps.last()).toContainText(revisionWords);
  await mobileScreenshot(page, view, '/tmp/nautilus-project-ordinary-390.png');
  await input.fill(draft);
  await ordinaryAction(page, id, '用自己的话说说');
  await expect(input).toHaveValue(draft);
  expect((await readConversation(page, id)).messages.at(-1)!.teaching!.current).toMatchObject({ project: { id: project.id, step: { id: revised.id } }, practice: { kind: 'retelling' } });
  await expect(view.getByRole('button', { name: '下一步', exact: true })).toHaveCount(0);
  await sendOrdinary(page, '[C2复述作答] 因为先检查缺失编号，才能决定返回空列表。');
  await ordinaryAction(page, id, '继续学习');
  expect((await readConversation(page, id)).messages.at(-1)!.teaching!.current).toMatchObject({ practice: null, project: { id: project.id, step: { id: revised.id } } });
  await input.fill(draft);
  let loseResponse = true;
  const posted: Array<Record<string, unknown>> = [];
  await page.route(/\/api\/ai\/conversations\/[^/]+\/messages$/, async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    posted.push(route.request().postDataJSON());
    if (!loseResponse) { await route.continue(); return; }
    loseResponse = false;
    const accepted = await route.fetch(); expect(accepted.ok()).toBeTruthy();
    await route.abort('failed');
  });
  await view.getByRole('button', { name: '下一步', exact: true }).click();
  await expect(page.locator('.ai-room-error')).toBeVisible();
  await expect(input).toHaveValue(draft);
  await expect(view.getByRole('button', { name: '下一步', exact: true })).toBeDisabled();
  await ordinaryAction(page, id, '重试发送');
  expect(posted.slice(0, 2).map(request => request.teaching_action)).toEqual(['next_step', 'next_step']);
  expect(posted[0].client_message_id).toBe(posted[1].client_message_id);
  const next = (await readConversation(page, id)).messages.at(-1)!;
  expect(next.teaching).toMatchObject({ requested_action: 'next_step', attempt: null, project_observation: null, current: { project: { id: project.id, step: { id: next.id, change: 'next', previous_step_id: revised.id, phase: 'awaiting_work' } } } });
  await expect(steps).toHaveCount(3);
  expect((await ordinaryAction(page, id, '下一步')).request().postDataJSON()).toMatchObject({ teaching_action: 'next_step', content: '下一步。' });
  const skippedTo = (await readConversation(page, id)).messages.at(-1)!;
  expect(skippedTo.teaching!.current.project!.step.id).not.toBe(next.id);
  expect(skippedTo.teaching!.attempt).toBeNull();
  await expect(input).toHaveValue(draft);
  await expect(steps).toHaveCount(4);
  const before = skippedTo.teaching!.current;
  await sendOrdinary(page, '[C2慢流] [C2项目作品] 新输入运行结果返回空列表。', false);
  await expect(page.locator('.ai-message--assistant').last().locator('.ai-message-content')).not.toBeEmpty();
  await expect(view.getByRole('button', { name: '下一步', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '取消生成', exact: true }).click(); await ordinaryFinished(page, id);
  expect((await readConversation(page, id)).messages.at(-1)!.teaching).toMatchObject({ status: 'not_updated', current: before, project_step: null, project_observation: null });
  expect(errors).toEqual([]);
});

test('question discussion keeps practice sources and revisions independent of formal verification', async ({ page }) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await setup(page);
  await page.getByRole('button', { name: '学习首页', exact: true }).first().click();
  if (await (await page.request.get('/api/learning/return-review')).json()) await page.getByRole('button', { name: '创建', exact: true }).click();
  await page.getByLabel('学习目标', { exact: true }).fill('合成目标：项目输入边界实践');
  await page.getByRole('button', { name: '我想自己安排', exact: true }).click();
  await page.getByLabel('现在先做什么', { exact: true }).fill('合成项目实践题目讨论旅程');
  await page.getByRole('button', { name: '确认这份学习安排', exact: true }).click();
  await page.getByRole('button', { name: '进入学习室并开始这项任务', exact: true }).click();
  await expect(page.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '进入验证', exact: true }).click();
  await page.getByRole('button', { name: '开始验证', exact: true }).click();
  await page.getByPlaceholder('写出你的判断、过程或结果').fill('合成原作答：先定位，再检查边界。');
  await page.getByRole('button', { name: '保存作答并验证', exact: true }).click();
  await page.getByRole('region', { name: '验证回看' }).getByRole('article', { name: '第 1 题回看' }).getByRole('button', { name: '讨论这道题', exact: true }).click();
  const room = page.getByRole('region', { name: '题目学习室' });
  await expect(room).toBeVisible();
  await expect.poll(() => new URL(page.url()).searchParams.get('discussion')).not.toBeNull();
  const id = new URL(page.url()).searchParams.get('discussion')!;
  async function read(): Promise<QuestionDiscussion> { return (await page.request.get(`/api/learning/discussions/${id}`)).json(); }
  function accepted() { return page.waitForResponse(response => response.url().endsWith(`/api/learning/discussions/${id}/messages`) && response.request().method() === 'POST'); }
  async function finished() {
    await expect.poll(async () => (await read()).turns.at(-1)?.status, { timeout: 15_000 }).not.toBe('running');
    await expect(room.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  }
  const input = room.getByLabel('继续提问或回答拓展问题');
  async function send(content: string) {
    const response = accepted(); await input.fill(content); await input.press('Enter');
    expect((await response).ok()).toBeTruthy(); await finished();
  }
  async function action(label: string) {
    const response = accepted(); await room.getByRole('button', { name: label, exact: true }).click();
    const value = await response; expect(value.ok()).toBeTruthy(); await finished(); return value;
  }
  const source = await read();
  const reviewPath = `/api/learning/verifications/${source.verification_id}?submission_id=${source.submission_id}&evaluation_id=${source.evaluation_id}`;
  const originalReview: VerificationReview = await (await page.request.get(reviewPath)).json();
  const practicesPath = `/api/learning/verifications/${source.verification_id}/practices?submission_id=${source.submission_id}&evaluation_id=${source.evaluation_id}&question_id=${source.question_id}`;
  const originalPractices = await (await page.request.get(practicesPath)).json();
  await projectDefault(page);
  let view = await arrangement(page);
  await send('[C2项目] 做一个检查当前题目输入边界的小程序。');
  const first = (await read()).turns.at(-1)!;
  const project = first.teaching!.project_step!;
  expect(project).toMatchObject({ id: first.id, step: { id: first.id, change: 'start', phase: 'awaiting_work' } });
  let steps = await records(view);
  await expect(steps).toContainText(excerpt(first.assistant_content!, project.step.instruction));
  await expect(steps).not.toContainText(first.user_content!);
  const words = '[C2项目作品] 🧩我的代码先检查缺失编号，运行结果返回“缺失”。';
  await send(words);
  const feedback = (await read()).turns.at(-1)!;
  expect(feedback.teaching).toMatchObject({ current: { project: { id: project.id, step: { id: first.id, phase: 'feedback_available' } } }, project_step: null, project_observation: { project_id: project.id, question_id: first.id, message_id: feedback.id, answer_id: feedback.id, eligible: true } });
  let work = steps.first().getByRole('article', { name: '实践内容', exact: true });
  await expect(work).toContainText(words);
  await expect(work).toContainText(feedback.assistant_content!.trim());
  await work.getByLabel('尝试进展', { exact: true }).selectOption('stuck');
  await expect(work.getByLabel('尝试进展', { exact: true })).toHaveValue('stuck');
  const draft = '未发送的题目实践草稿。'; await input.fill(draft);
  await action('给个提示'); await expect(input).toHaveValue(draft);
  await expect(steps.first().getByRole('article', { name: '实践帮助', exact: true })).toContainText('想想缺失编号时');
  const revisionWords = '[C2项目调整] 修改要求：缺失编号时改为返回空列表。';
  await send(revisionWords);
  const revised = (await read()).turns.at(-1)!;
  expect(revised.teaching!.project_step).toMatchObject({ id: project.id, step: { id: revised.id, change: 'revision', previous_step_id: first.id } });
  await expect(steps).toHaveCount(2);
  await expect(steps.last()).toContainText(revisionWords);
  await page.reload(); view = await arrangement(page); steps = await records(view);
  work = steps.first().getByRole('article', { name: '实践内容', exact: true });
  await expect(work).toContainText(words);
  await expect(work).toContainText(feedback.assistant_content!.trim());
  await expect(work.getByLabel('尝试进展', { exact: true })).toHaveValue('stuck');
  await mobileScreenshot(page, view, '/tmp/nautilus-project-discussion-390.png');
  await input.fill(draft);
  const nextResponse = await action('下一步');
  expect(nextResponse.request().postDataJSON()).toMatchObject({ teaching_action: 'next_step', content: '下一步。' });
  const next = (await read()).turns.at(-1)!;
  expect(next.teaching).toMatchObject({ attempt: null, project_observation: null, current: { project: { id: project.id, step: { id: next.id, change: 'next', phase: 'awaiting_work' } } } });
  await expect(input).toHaveValue(draft);
  await action('下一步');
  await expect(steps).toHaveCount(4);
  await action('用自己的话说说');
  await expect(view.getByRole('button', { name: '下一步', exact: true })).toHaveCount(0);
  await action('继续学习');
  await expect(view.getByRole('button', { name: '下一步', exact: true })).toBeVisible();
  expect((await read()).source).toEqual(source.source);
  const finalReview: VerificationReview = await (await page.request.get(reviewPath)).json();
  expect(finalReview.content).toEqual(originalReview.content);
  expect(finalReview.evaluations).toEqual(originalReview.evaluations);
  expect(finalReview.result).toEqual(originalReview.result);
  expect(await (await page.request.get(practicesPath)).json()).toEqual(originalPractices);
  expect(errors).toEqual([]);
});
