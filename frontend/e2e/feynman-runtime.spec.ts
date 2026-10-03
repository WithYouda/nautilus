import { expect, test, type Locator, type Page, type Response } from '@playwright/test';
import { authorize, checkDefaultTeachingSupport } from './fact-helpers';
import type { AiConversationDetail, AiRun, QuestionDiscussion, TeachingMethod, VerificationReview } from '../src/api';

test.beforeEach(async ({ page }) => {
  const response = await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT ?? '8012'}/openapi.json`);
  expect(response.ok()).toBeTruthy();
  const schema = await response.json();
  for (const name of ['MessageSendRequest', 'QuestionDiscussionMessageRequest']) {
    expect(schema.components.schemas[name].properties.teaching_mode).toBeTruthy();
    expect(schema.components.schemas[name].properties.teaching_action).toBeTruthy();
  }
});

async function setup(page: Page) {
  await authorize(page);
  expect((await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic Feynman provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model: 'mock-success', api_key: 'synthetic-feynman-key', enabled: true, request_timeout_seconds: 15,
  } })).ok()).toBeTruthy();
  await checkDefaultTeachingSupport(page);
  const preferences = await (await page.request.get('/api/preferences')).json();
  expect((await page.request.put('/api/preferences', { data: { ...preferences, teaching_mode: 'stepwise' } })).ok()).toBeTruthy();
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

async function defaultMode(page: Page, mode: TeachingMethod, screenshot?: string) {
  await page.getByRole('button', { name: '设置', exact: true }).click();
  const settings = page.locator('.unified-settings-dialog');
  await expect(settings).toBeVisible();
  const choice = settings.getByRole('combobox', { name: '默认学习方式', exact: true });
  await expect(choice).toBeVisible();
  await choice.selectOption(mode);
  await settings.getByRole('button', { name: '保存默认设置', exact: true }).click();
  await expect(settings.getByRole('button', { name: '保存默认设置', exact: true })).toBeDisabled();
  if (screenshot) {
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: screenshot, fullPage: true });
    await page.setViewportSize({ width: 1280, height: 900 });
  }
  await settings.getByRole('button', { name: '关闭', exact: true }).click();
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

async function sendOrdinary(page: Page, text: string, complete = true): Promise<AiRun> {
  const accepted = ordinaryResponse(page);
  const input = page.getByLabel('输入学习问题', { exact: true });
  await input.fill(text); await input.press('Enter');
  const response = await accepted;
  expect(response.ok()).toBeTruthy();
  const { run } = await response.json();
  if (complete) await ordinaryFinished(page, run.conversation_id);
  return run;
}

async function ordinaryAction(page: Page, id: string, label: string): Promise<Response> {
  const accepted = ordinaryResponse(page);
  await page.getByRole('button', { name: label, exact: true }).click();
  const response = await accepted;
  expect(response.ok()).toBeTruthy();
  await ordinaryFinished(page, id);
  return response;
}

async function retellings(view: Locator) {
  await expand(view.locator('details').first());
  await expand(view.locator('.teaching-state__retellings'));
  return view.getByRole('article', { name: '复述作答', exact: true });
}

async function mobileScreenshot(page: Page, view: Locator, path: string) {
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(view.getByRole('button', { name: '用自己的话说说', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await view.getByRole('article', { name: '复述作答', exact: true }).last().scrollIntoViewIfNeeded();
  await page.screenshot({ path, fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
}

test('settings default, persistent and single retelling retain original feedback through retry, correction, history, branches and cancellation', async ({ page }) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await setup(page);
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await expect(page.getByLabel('输入学习问题', { exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  let view = await arrangement(page);
  await expect(view.getByLabel('讲解方式', { exact: true })).toHaveValue('default');
  await expect(view.getByLabel('讲解方式', { exact: true }).locator('option[value="feynman"]')).toHaveCount(0);
  await defaultMode(page, 'feynman', '/tmp/nautilus-feynman-settings-390.png');
  await expect(view.getByLabel('讲解方式', { exact: true })).toContainText('沿用设置（费曼复述）');
  let loseResponse = true;
  let lostRun: AiRun | null = null;
  const posted: Array<Record<string, unknown>> = [];
  await page.route(/\/api\/ai\/conversations\/[^/]+\/messages$/, async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    posted.push(route.request().postDataJSON());
    if (!loseResponse) { await route.continue(); return; }
    loseResponse = false;
    const response = await route.fetch();
    expect(response.ok()).toBeTruthy(); lostRun = (await response.json()).run;
    await route.abort('failed');
  });
  const input = page.getByLabel('输入学习问题', { exact: true });
  const firstText = '[C2复述] 先讨论输入边界。';
  await input.fill(firstText); await input.press('Enter');
  await expect(page.locator('.ai-room-error')).toBeVisible();
  expect(lostRun).not.toBeNull();
  await defaultMode(page, 'stepwise');
  await sendOrdinary(page, firstText);
  const id = lostRun!.conversation_id;
  expect(posted.slice(0, 2).map(request => request.teaching_mode)).toEqual([null, null]);
  expect(posted[0].client_message_id).toBe(posted[1].client_message_id);
  let saved = await readConversation(page, id);
  expect(saved.messages).toHaveLength(2);
  const first = saved.messages.at(-1)!;
  expect(first.teaching).toMatchObject({ default_mode: 'feynman', requested_mode: null, current: { mode: 'feynman', mode_source: 'default', retelling: { phase: 'awaiting_retelling' } }, retelling_observation: null });
  await expect(page.locator('.ai-message--assistant').last()).toContainText('请用自己的话说说');
  await expect(view.locator('.teaching-state__retellings')).toHaveCount(0);
  await expect(view).toContainText('下次使用分步讲解');
  await defaultMode(page, 'feynman');
  const words = '[C2复述作答] 🧩我先检查输入边界，因为空输入没有可读取的内容。';
  await sendOrdinary(page, words);
  const feedback = (await readConversation(page, id)).messages.at(-1)!;
  expect(feedback.teaching!.retelling_observation).toMatchObject({ question_id: first.teaching!.current.step!.id, eligible: true });
  expect(feedback.teaching!.practice_observation).toBeNull();
  expect(await view.locator('.teaching-state__retellings').evaluate(element => (element as HTMLDetailsElement).open)).toBe(false);
  let observations = await retellings(view);
  await expect(observations).toHaveCount(1);
  await expect(observations).toContainText(words);
  await expect(observations).toContainText(feedback.content.trim());
  await expect(view.getByRole('article', { name: '持续复述', exact: true })).toContainText(first.teaching!.current.step!.text);
  await observations.getByLabel('尝试进展', { exact: true }).selectOption('stuck');
  await expect(observations.getByLabel('尝试进展', { exact: true })).toHaveValue('stuck');
  await observations.getByRole('button', { name: '这不是一次尝试', exact: true }).click();
  await expect(observations).toContainText('已改为非尝试');
  await expect(view.getByRole('article', { name: 'AI识别的尝试', exact: true })).toHaveCount(0);
  await page.reload(); view = await arrangement(page); observations = await retellings(view);
  await expect(observations).toContainText(words);
  await expect(observations).toContainText(feedback.content.trim());
  await expect(observations).toContainText('已改为非尝试');
  await mobileScreenshot(page, view, '/tmp/nautilus-feynman-ordinary-390.png');
  await observations.getByRole('button', { name: '恢复为尝试', exact: true }).click();
  await expect(observations.getByLabel('尝试进展', { exact: true })).toHaveValue('stuck');
  await view.getByLabel('讲解方式', { exact: true }).selectOption('stepwise');
  const regenerated = ordinaryResponse(page);
  await page.locator('.ai-message--assistant').last().getByRole('button', { name: '重新生成', exact: true }).click();
  expect((await regenerated).request().postDataJSON()).toMatchObject({ regenerate_message_id: feedback.id, teaching_mode: null });
  await ordinaryFinished(page, id);
  await expect(view.getByLabel('讲解方式', { exact: true })).toHaveValue('default');
  await page.locator('.ai-message--assistant').last().getByRole('button', { name: '上一个回答', exact: true }).click();
  observations = await retellings(view);
  await expect(observations).toContainText(feedback.content.trim());
  const branched = page.waitForResponse(response => response.url().endsWith(`/api/ai/conversations/${id}/branches`) && response.request().method() === 'POST');
  await page.locator('.ai-message--assistant').last().getByRole('button', { name: '从这里创建独立对话', exact: true }).click();
  const branch = await branched; expect(branch.ok()).toBeTruthy();
  const branchId = (await branch.json()).conversation.id;
  await expect(page.getByRole('button', { name: '返回原对话', exact: true })).toBeVisible();
  view = await arrangement(page); observations = await retellings(view);
  await expect(observations).toContainText(words);
  const before = (await readConversation(page, branchId)).messages.at(-1)!.teaching!.current;
  await sendOrdinary(page, '[C2慢流] [C2复述作答] 我补充空输入的处理。', false);
  await expect(page.locator('.ai-message--assistant').last().locator('.ai-message-content')).not.toBeEmpty();
  await page.getByRole('button', { name: '取消生成', exact: true }).click();
  await ordinaryFinished(page, branchId);
  expect((await readConversation(page, branchId)).messages.at(-1)!.teaching).toMatchObject({ status: 'not_updated', current: before, retelling_observation: null });
  const next = await ordinaryAction(page, branchId, '继续学习');
  expect(next.request().postDataJSON()).toMatchObject({ teaching_action: 'continue', content: '继续学习。' });
  expect((await readConversation(page, branchId)).messages.at(-1)!.teaching!.current.retelling?.phase).toBe('awaiting_retelling');
  await defaultMode(page, 'stepwise');
  await sendOrdinary(page, '[C2复述] 继续讨论输入。');
  expect((await readConversation(page, branchId)).messages.at(-1)!.teaching!.current).toMatchObject({ mode: 'stepwise', mode_source: 'default' });
  view = await arrangement(page);
  await view.getByLabel('讲解方式', { exact: true }).selectOption('socratic');
  await sendOrdinary(page, '[C2复述] 沿当前对话提问。');
  await defaultMode(page, 'feynman');
  await sendOrdinary(page, '[C2复述] 继续当前对话。');
  expect((await readConversation(page, branchId)).messages.at(-1)!.teaching!.current).toMatchObject({ mode: 'socratic', mode_source: 'conversation' });
  await view.getByLabel('讲解方式', { exact: true }).selectOption('default');
  const reset = ordinaryResponse(page);
  await sendOrdinary(page, '[C2复述] 重新沿用设置。');
  expect((await reset).request().postDataJSON().teaching_mode).toBe('default');
  expect((await readConversation(page, branchId)).messages.at(-1)!.teaching!.current).toMatchObject({ mode: 'feynman', mode_source: 'default' });
  await defaultMode(page, 'stepwise');
  await sendOrdinary(page, '[C2复述] 回到分步讲解。');
  const base = (await readConversation(page, branchId)).messages.at(-1)!.teaching!.current;
  const draft = '这是一份还未发送的草稿。';
  await input.fill(draft);
  expect((await ordinaryAction(page, branchId, '用自己的话说说')).request().postDataJSON()).toMatchObject({ teaching_action: 'retell', content: '用自己的话说说。', teaching_mode: null });
  await expect(input).toHaveValue(draft);
  expect((await readConversation(page, branchId)).messages.at(-1)!.teaching!.current).toMatchObject({ mode: 'stepwise', practice: { kind: 'retelling', basis_step: base.step } });
  await sendOrdinary(page, '[C2复述作答] 我先看输入是否为空。');
  observations = await retellings(view);
  await expect(view.getByRole('article', { name: '单次复述', exact: true })).toHaveCount(1);
  await expect(view.locator('.teaching-state__practices')).toHaveCount(0);
  expect((await ordinaryAction(page, branchId, '继续学习')).request().postDataJSON()).toMatchObject({ teaching_action: 'continue', content: '继续学习。' });
  expect((await readConversation(page, branchId)).messages.at(-1)!.teaching!.current).toMatchObject({ mode: 'stepwise', practice: null });
  expect((await readConversation(page, id)).messages.find(message => message.id === feedback.id)!.teaching!.current.mode).toBe('feynman');
  expect(errors).toEqual([]);
});

test('question discussion preserves separate retelling sources and formal verification through feedback, corrections and branch cancellation', async ({ page }) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await setup(page);
  await page.getByRole('button', { name: '学习首页', exact: true }).first().click();
  if (await (await page.request.get('/api/learning/return-review')).json()) await page.getByRole('button', { name: '创建', exact: true }).click();
  await page.getByLabel('学习目标', { exact: true }).fill('合成目标：复述当前小点');
  await page.getByRole('button', { name: '我想自己安排', exact: true }).click();
  await page.getByLabel('现在先做什么', { exact: true }).fill('合成复述题目讨论旅程');
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
  const sourceId = new URL(page.url()).searchParams.get('discussion')!;
  let id = sourceId;
  async function read(): Promise<QuestionDiscussion> { return (await page.request.get(`/api/learning/discussions/${id}`)).json(); }
  function accepted() { return page.waitForResponse(response => response.url().endsWith(`/api/learning/discussions/${id}/messages`) && response.request().method() === 'POST'); }
  async function finished() {
    await expect.poll(async () => (await read()).turns.at(-1)?.status, { timeout: 15_000 }).not.toBe('running');
    await expect(room.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  }
  const input = room.getByLabel('继续提问或回答拓展问题');
  async function send(text: string, complete = true) {
    const response = accepted(); await input.fill(text); await input.press('Enter');
    const value = await response; expect(value.ok()).toBeTruthy();
    if (complete) await finished(); return value;
  }
  async function action(label: string) {
    const response = accepted(); await room.getByRole('button', { name: label, exact: true }).click();
    const value = await response; expect(value.ok()).toBeTruthy(); await finished(); return value;
  }
  const source = await read();
  const reviewPath = `/api/learning/verifications/${source.verification_id}?submission_id=${source.submission_id}&evaluation_id=${source.evaluation_id}`;
  const originalReview: VerificationReview = await (await page.request.get(reviewPath)).json();
  await defaultMode(page, 'feynman');
  let view = await arrangement(page);
  expect((await send('[C2复述] 先讨论当前题目的边界。')).request().postDataJSON().teaching_mode).toBeNull();
  const first = (await read()).turns.at(-1)!;
  expect(first.teaching!.current).toMatchObject({ mode: 'feynman', mode_source: 'default', retelling: { phase: 'awaiting_retelling' } });
  const words = '[C2复述作答] 🧩空输入没有编号，所以我先检查是否为空。';
  await send(words);
  const feedback = (await read()).turns.at(-1)!;
  expect(feedback.teaching!.retelling_observation).toMatchObject({ question_id: first.teaching!.current.step!.id, message_id: feedback.id, answer_id: feedback.id, eligible: true });
  let observations = await retellings(view);
  await expect(observations).toContainText(words);
  await expect(observations).toContainText(feedback.assistant_content!.trim());
  await observations.getByRole('button', { name: '这不是一次尝试', exact: true }).click();
  await expect(observations).toContainText('已改为非尝试');
  await page.reload(); view = await arrangement(page); observations = await retellings(view);
  await expect(observations).toContainText(words);
  await expect(observations).toContainText(feedback.assistant_content!.trim());
  await expect(observations).toContainText('已改为非尝试');
  await mobileScreenshot(page, view, '/tmp/nautilus-feynman-discussion-390.png');
  await observations.getByRole('button', { name: '恢复为尝试', exact: true }).click();
  await expect(observations.getByLabel('尝试进展', { exact: true })).toBeEnabled();
  await view.getByLabel('讲解方式', { exact: true }).selectOption('stepwise');
  const regenerated = accepted();
  await room.locator('.ai-message--assistant').last().getByRole('button', { name: '重新生成', exact: true }).click();
  expect((await regenerated).request().postDataJSON()).toMatchObject({ regenerate_turn_id: feedback.id, teaching_mode: null });
  await finished();
  await expect(view.getByLabel('讲解方式', { exact: true })).toHaveValue('default');
  await room.locator('.ai-message--assistant').last().getByRole('button', { name: '上一个回答', exact: true }).click();
  const branched = page.waitForResponse(response => response.url().endsWith(`/api/learning/discussions/${id}/branches`) && response.request().method() === 'POST');
  await room.locator('.ai-message--assistant').last().getByRole('button', { name: '从这里创建独立对话', exact: true }).click();
  const branch = await branched; expect(branch.ok()).toBeTruthy(); id = (await branch.json()).id;
  await expect(room.getByRole('button', { name: '返回原讨论', exact: true })).toBeVisible();
  view = await arrangement(page); observations = await retellings(view);
  await expect(observations).toContainText(words);
  const before = (await read()).turns.at(-1)!.teaching!.current;
  await send('[C2慢流] [C2复述作答] 我补充返回值。', false);
  await expect(room.locator('.ai-message--assistant').last().locator('.ai-message-content')).not.toBeEmpty();
  await room.getByRole('button', { name: '取消生成', exact: true }).click(); await finished();
  expect((await read()).turns.at(-1)!.teaching).toMatchObject({ status: 'not_updated', current: before, retelling_observation: null });
  await defaultMode(page, 'stepwise');
  await send('[C2复述] 继续当前小点。');
  const base = (await read()).turns.at(-1)!.teaching!.current;
  const draft = '尚未发送的讨论草稿。'; await input.fill(draft);
  expect((await action('用自己的话说说')).request().postDataJSON().teaching_action).toBe('retell');
  await expect(input).toHaveValue(draft);
  const invitation = (await read()).turns.at(-1)!;
  expect(invitation.teaching!.current).toMatchObject({ mode: 'stepwise', practice: { kind: 'retelling', basis_step: base.step } });
  await retellings(view);
  const single = view.getByRole('article', { name: '单次复述', exact: true });
  await expect(single).toContainText(invitation.assistant_content!.trim());
  await expect(single).not.toContainText(invitation.user_content!);
  await send('[C2复述作答] 我先检查输入边界，再检查正常输入。');
  const singleFeedback = (await read()).turns.at(-1)!;
  expect(singleFeedback.teaching!.practice_observation).toMatchObject({ question_id: invitation.id, message_id: singleFeedback.id, answer_id: singleFeedback.id });
  await expect(single.getByRole('article', { name: '复述作答', exact: true })).toContainText(singleFeedback.user_content!);
  await expect(single.getByRole('article', { name: '复述作答', exact: true })).toContainText(singleFeedback.assistant_content!.trim());
  expect((await action('继续学习')).request().postDataJSON()).toMatchObject({ teaching_action: 'continue', content: '继续学习。' });
  expect((await read()).turns.at(-1)!.teaching!.current).toMatchObject({ mode: 'stepwise', practice: null });
  expect((await read()).source).toEqual(source.source);
  const finalReview: VerificationReview = await (await page.request.get(reviewPath)).json();
  expect(finalReview.content).toEqual(originalReview.content);
  expect(finalReview.evaluations).toEqual(originalReview.evaluations);
  expect(finalReview.result).toEqual(originalReview.result);
  expect(errors).toEqual([]);
});
