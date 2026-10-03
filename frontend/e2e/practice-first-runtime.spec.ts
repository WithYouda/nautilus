import { expect, test, type Locator, type Page, type Response } from '@playwright/test';
import { authorize, checkDefaultTeachingSupport } from './fact-helpers';
import type { AiConversationDetail, AiRun, QuestionDiscussion, TeachingMethod, VerificationReview } from '../src/api';

test.beforeEach(async ({ page }) => {
  const response = await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT ?? '8012'}/openapi.json`);
  expect(response.ok()).toBeTruthy();
  const schema = await response.json();
  for (const name of ['MessageSendRequest', 'QuestionDiscussionMessageRequest']) {
    const properties = schema.components.schemas[name].properties;
    expect(properties.teaching_mode.anyOf.find((value: { enum?: string[] }) => value.enum)?.enum).toContain('practice_first');
    expect(properties.teaching_action.anyOf.find((value: { enum?: string[] }) => value.enum)?.enum).toContain('next_question');
  }
});

async function setup(page: Page) {
  await authorize(page);
  expect((await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic practice-first provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model: 'mock-success', api_key: 'synthetic-practice-first-key', enabled: true, request_timeout_seconds: 15,
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
  await expand(view.locator('.teaching-state__practices'));
  return view.getByRole('article', { name: '持续练习', exact: true });
}

async function defaultMode(page: Page, mode: TeachingMethod, screenshot?: string) {
  await page.getByRole('button', { name: '设置', exact: true }).click();
  const dialog = page.locator('.unified-settings-dialog');
  const choice = dialog.getByRole('combobox', { name: '默认学习方式', exact: true });
  await expect(choice).toBeVisible();
  await choice.selectOption(mode);
  if (mode === 'practice_first') await expect(dialog).toContainText('点“下一题”才继续');
  await dialog.getByRole('button', { name: '保存默认设置', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '保存默认设置', exact: true })).toBeDisabled();
  if (screenshot) {
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: screenshot, fullPage: true });
    await page.setViewportSize({ width: 1280, height: 900 });
  }
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  expect((await (await page.request.get('/api/preferences')).json()).teaching_mode).toBe(mode);
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

async function mobileScreenshot(page: Page, view: Locator, path: string) {
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(view.getByRole('button', { name: '下一题', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path, fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
}

test('ordinary practice-first waits for explicit next, preserves drafts and sources through correction, retry and retelling', async ({ page }) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await setup(page);
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  let view = await arrangement(page);
  await expect(view.getByLabel('讲解方式', { exact: true }).locator('option[value="practice_first"]')).toHaveCount(0);
  await defaultMode(page, 'practice_first', '/tmp/nautilus-practice-first-settings-390.png');
  await expect(view.getByLabel('讲解方式', { exact: true })).toContainText('沿用设置（练习优先）');
  const run = await sendOrdinary(page, '[C2澄清] 我想做些练习。');
  const id = run.conversation_id;
  const clarification = (await readConversation(page, id)).messages.at(-1)!;
  expect(clarification.teaching).toMatchObject({ current: { mode: 'practice_first' }, attempt: null, exercise_question: null, exercise_observation: null });
  expect(clarification.teaching!.current.exercise).toBeFalsy();
  await sendOrdinary(page, '[C2练习] 练习检查输入边界。');
  const first = (await readConversation(page, id)).messages.at(-1)!;
  const exercise = first.teaching!.exercise_question!;
  expect(exercise).toMatchObject({ id: first.id, phase: 'awaiting_attempt' });
  expect(first.teaching).toMatchObject({ default_mode: 'practice_first', current: { mode_source: 'default', exercise }, attempt: null, exercise_observation: null });
  expect(first.content.trim()).toMatch(/^🧩合成练习\d+：/);
  expect(first.content).not.toContain('合成完整讲解');
  await expect(view.locator('.teaching-state__step')).toContainText('当前题目');
  await expect(view.getByRole('button', { name: '换一道试试', exact: true })).toHaveCount(0);
  expect(await view.locator('.teaching-state__practices').evaluate(element => (element as HTMLDetailsElement).open)).toBe(false);
  let questions = await records(view);
  await expect(questions).toHaveCount(1);
  await expect(questions).toContainText(first.content.trim());
  const words = '[C2练习作答] 🧩我先检查缺失编号，缺失时返回明确提示。';
  await sendOrdinary(page, words);
  const feedback = (await readConversation(page, id)).messages.at(-1)!;
  expect(feedback.teaching).toMatchObject({ current: { exercise: { id: exercise.id, phase: 'feedback_available' } }, exercise_question: null, exercise_observation: { question_id: exercise.id, eligible: true, needs_help: false } });
  expect(feedback.content).not.toContain('🧩合成练习');
  let observation = questions.first().getByRole('article', { name: '练习作答', exact: true });
  await expect(observation).toContainText(words);
  await expect(observation).toContainText(feedback.content.trim());
  const input = page.getByLabel('输入学习问题', { exact: true });
  const draft = '尚未发送的练习草稿。';
  await input.fill(draft);
  await ordinaryAction(page, id, '给个提示');
  await expect(input).toHaveValue(draft);
  expect((await readConversation(page, id)).messages.at(-1)!.teaching).toMatchObject({ current: { exercise: { id: exercise.id } }, exercise_question: null, exercise_observation: null });
  await sendOrdinary(page, '[C2练习] 请直接给答案。');
  expect((await readConversation(page, id)).messages.at(-1)!.teaching).toMatchObject({ effective_mode: 'direct_answer', current: { mode: 'practice_first', exercise: { id: exercise.id } }, exercise_question: null, exercise_observation: null });
  await expect(questions).toHaveCount(1);
  await observation.getByRole('button', { name: '这不是一次尝试', exact: true }).click();
  await expect(observation).toContainText('已改为非尝试');
  await expect(view.getByRole('article', { name: 'AI识别的尝试', exact: true })).toHaveCount(0);
  await page.reload(); view = await arrangement(page); questions = await records(view);
  observation = questions.first().getByRole('article', { name: '练习作答', exact: true });
  await expect(observation).toContainText(words);
  await expect(observation).toContainText(feedback.content.trim());
  await expect(observation).toContainText('已改为非尝试');
  await mobileScreenshot(page, view, '/tmp/nautilus-practice-first-ordinary-390.png');
  await input.fill(draft);
  expect((await ordinaryAction(page, id, '用自己的话说说')).request().postDataJSON().teaching_action).toBe('retell');
  await expect(input).toHaveValue(draft);
  expect((await readConversation(page, id)).messages.at(-1)!.teaching!.current).toMatchObject({ exercise: { id: exercise.id }, practice: { kind: 'retelling' } });
  await expect(view.getByRole('button', { name: '下一题', exact: true })).toHaveCount(0);
  await sendOrdinary(page, '[C2复述作答] 我先检查是否缺失，因为不能直接读取缺失的编号。');
  expect((await readConversation(page, id)).messages.at(-1)!.teaching!.practice_observation).toBeTruthy();
  await ordinaryAction(page, id, '继续学习');
  expect((await readConversation(page, id)).messages.at(-1)!.teaching!.current).toMatchObject({ practice: null, exercise: { id: exercise.id } });
  await expect(view.locator('.teaching-state__step')).toContainText(first.content.trim());
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
  await view.getByRole('button', { name: '下一题', exact: true }).click();
  await expect(page.locator('.ai-room-error')).toBeVisible();
  await expect(input).toHaveValue(draft);
  await expect(view.getByRole('button', { name: '下一题', exact: true })).toBeDisabled();
  await ordinaryAction(page, id, '重试发送');
  expect(posted.slice(0, 2).map(request => request.teaching_action)).toEqual(['next_question', 'next_question']);
  expect(posted[0].client_message_id).toBe(posted[1].client_message_id);
  await expect(input).toHaveValue(draft);
  await expect(questions).toHaveCount(2);
  const next = (await readConversation(page, id)).messages.at(-1)!;
  expect(next.teaching).toMatchObject({ requested_action: 'next_question', attempt: null, exercise_observation: null, current: { exercise: { id: next.id, phase: 'awaiting_attempt' } } });
  expect((await ordinaryAction(page, id, '下一题')).request().postDataJSON()).toMatchObject({ teaching_action: 'next_question', content: '下一题。' });
  const skippedTo = (await readConversation(page, id)).messages.at(-1)!;
  expect(skippedTo.teaching!.current.exercise!.id).not.toBe(next.id);
  expect(skippedTo.teaching!.attempt).toBeNull();
  await expect(questions).toHaveCount(3);
  const before = skippedTo.teaching!.current;
  await sendOrdinary(page, '[C2慢流] [C2练习作答] 我检查新的缺失输入。', false);
  await expect(page.locator('.ai-message--assistant').last().locator('.ai-message-content')).not.toBeEmpty();
  await expect(view.getByRole('button', { name: '下一题', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '取消生成', exact: true }).click(); await ordinaryFinished(page, id);
  expect((await readConversation(page, id)).messages.at(-1)!.teaching).toMatchObject({ status: 'not_updated', current: before, exercise_question: null, exercise_observation: null });
  await view.getByLabel('讲解方式', { exact: true }).selectOption('stepwise');
  await sendOrdinary(page, '[C2学习] 继续检查输入。');
  const switched = (await readConversation(page, id)).messages.at(-1)!.teaching!.current;
  expect(switched).toMatchObject({ mode: 'stepwise', mode_source: 'conversation' });
  expect(switched.exercise).toBeFalsy();
  await view.getByLabel('讲解方式', { exact: true }).selectOption('default');
  await sendOrdinary(page, '[C2练习] 继续练习输入边界。');
  expect((await readConversation(page, id)).messages.at(-1)!.teaching!.current).toMatchObject({ mode: 'practice_first', mode_source: 'default', exercise: { phase: 'awaiting_attempt' } });
  expect(errors).toEqual([]);
});

test('question discussion retains full exercise sources, waits and skips without changing formal verification', async ({ page }) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await setup(page);
  await page.getByRole('button', { name: '学习首页', exact: true }).first().click();
  if (await (await page.request.get('/api/learning/return-review')).json()) await page.getByRole('button', { name: '创建', exact: true }).click();
  await page.getByLabel('学习目标', { exact: true }).fill('合成目标：练习输入边界');
  await page.getByRole('button', { name: '我想自己安排', exact: true }).click();
  await page.getByLabel('现在先做什么', { exact: true }).fill('合成练习优先题目讨论旅程');
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
  async function send(content: string, complete = true) {
    const response = accepted(); await input.fill(content); await input.press('Enter');
    const value = await response; expect(value.ok()).toBeTruthy(); if (complete) await finished(); return value;
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
  await defaultMode(page, 'practice_first');
  let view = await arrangement(page);
  await send('[C2练习] 练习当前题目的输入边界。');
  const first = (await read()).turns.at(-1)!;
  expect(first.teaching).toMatchObject({ current: { mode: 'practice_first', exercise: { id: first.id, phase: 'awaiting_attempt' } }, attempt: null, exercise_observation: null });
  let questions = await records(view);
  await expect(questions).toContainText(first.assistant_content!.trim());
  await expect(questions).not.toContainText(first.user_content!);
  const words = '[C2练习作答] 🧩我检查缺失编号，并返回缺失提示。';
  await send(words);
  const feedback = (await read()).turns.at(-1)!;
  expect(feedback.teaching).toMatchObject({ current: { exercise: { id: first.id, phase: 'feedback_available' } }, exercise_question: null, exercise_observation: { question_id: first.id, message_id: feedback.id, answer_id: feedback.id, eligible: true } });
  let observation = questions.first().getByRole('article', { name: '练习作答', exact: true });
  await expect(observation).toContainText(words);
  await expect(observation).toContainText(feedback.assistant_content!.trim());
  await observation.getByLabel('尝试进展', { exact: true }).selectOption('stuck');
  await expect(observation.getByLabel('尝试进展', { exact: true })).toHaveValue('stuck');
  const draft = '还没发送的题目讨论草稿。'; await input.fill(draft);
  await action('给个提示'); await expect(input).toHaveValue(draft);
  await send('[C2练习] 请完整讲解。');
  expect((await read()).turns.at(-1)!.teaching).toMatchObject({ effective_mode: 'full_explanation', current: { mode: 'practice_first', exercise: { id: first.id } }, exercise_question: null, exercise_observation: null });
  await page.reload(); view = await arrangement(page); questions = await records(view);
  observation = questions.first().getByRole('article', { name: '练习作答', exact: true });
  await expect(observation).toContainText(words);
  await expect(observation).toContainText(feedback.assistant_content!.trim());
  await expect(observation.getByLabel('尝试进展', { exact: true })).toHaveValue('stuck');
  await mobileScreenshot(page, view, '/tmp/nautilus-practice-first-discussion-390.png');
  await input.fill(draft); await action('用自己的话说说'); await expect(input).toHaveValue(draft);
  expect((await read()).turns.at(-1)!.teaching!.current).toMatchObject({ practice: { kind: 'retelling' }, exercise: { id: first.id } });
  await expect(view.getByRole('button', { name: '下一题', exact: true })).toHaveCount(0);
  await action('继续学习');
  expect((await read()).turns.at(-1)!.teaching!.current).toMatchObject({ practice: null, exercise: { id: first.id } });
  await expect(view.locator('.teaching-state__step')).toContainText(first.assistant_content!.trim());
  const nextResponse = await action('下一题');
  expect(nextResponse.request().postDataJSON()).toMatchObject({ teaching_action: 'next_question', content: '下一题。' });
  const next = (await read()).turns.at(-1)!;
  expect(next.teaching).toMatchObject({ attempt: null, exercise_observation: null, current: { exercise: { id: next.id, phase: 'awaiting_attempt' } } });
  await expect(input).toHaveValue(draft);
  await action('下一题');
  const skippedTo = (await read()).turns.at(-1)!;
  expect(skippedTo.teaching!.exercise_question!.id).not.toBe(next.id);
  await expect(questions).toHaveCount(3);
  const before = skippedTo.teaching!.current;
  await send('[C2慢流] [C2练习作答] 我检查新的输入。', false);
  await expect(room.locator('.ai-message--assistant').last().locator('.ai-message-content')).not.toBeEmpty();
  await expect(view.getByRole('button', { name: '下一题', exact: true })).toBeDisabled();
  await room.getByRole('button', { name: '取消生成', exact: true }).click(); await finished();
  expect((await read()).turns.at(-1)!.teaching).toMatchObject({ status: 'not_updated', current: before, exercise_question: null, exercise_observation: null });
  expect((await read()).source).toEqual(source.source);
  const finalReview: VerificationReview = await (await page.request.get(reviewPath)).json();
  expect(finalReview.content).toEqual(originalReview.content);
  expect(finalReview.evaluations).toEqual(originalReview.evaluations);
  expect(finalReview.result).toEqual(originalReview.result);
  expect(await (await page.request.get(practicesPath)).json()).toEqual(originalPractices);
  expect(errors).toEqual([]);
});
