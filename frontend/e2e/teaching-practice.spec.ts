import { expect, test, type Locator, type Page, type Response } from '@playwright/test';
import { authorize } from './fact-helpers';
import type { AiConversationDetail, AiRun, QuestionDiscussion, TeachingPractice, VerificationReview } from '../src/api';

test.beforeEach(async ({ page }) => {
  const response = await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT ?? '8012'}/openapi.json`);
  expect(response.ok()).toBeTruthy();
  const schema = await response.json();
  for (const name of ['MessageSendRequest', 'QuestionDiscussionMessageRequest'])
    expect(schema.components.schemas[name].properties.teaching_action).toBeTruthy();
});

async function setup(page: Page) {
  await authorize(page);
  expect((await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic teaching practice provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model: 'mock-success', api_key: 'synthetic-teaching-practice-key', enabled: true, request_timeout_seconds: 15,
  } })).ok()).toBeTruthy();
  await page.reload();
}

async function expand(locator: Locator) {
  await expect(locator).toBeVisible();
  if (!(await locator.evaluate(element => (element as HTMLDetailsElement).open))) await locator.locator('summary').first().click();
}

async function arrangement(page: Page) {
  const view = page.locator('.teaching-arrangement');
  await expect(view).toBeVisible();
  await expand(view.locator('details').first());
  return view;
}

async function records(view: Locator) {
  await expand(view.locator('.teaching-state__practices'));
  return view.getByRole('article', { name: '变式练习', exact: true });
}

const excerpt = (content: string, start: number, end: number) => Array.from(content).slice(start, end).join('');

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

async function mobileScreenshot(page: Page, view: Locator, path: string) {
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(view.getByRole('button', { name: '换一道试试', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path, fullPage: true });
}

test('ordinary optional practice preserves drafts, referenced feedback and correction across retry, versions, branch and cancellation', async ({ page }) => {
  test.setTimeout(150_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await setup(page);
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await expect(page.getByLabel('输入学习问题', { exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  let view = await arrangement(page);
  await expect(view.getByRole('button', { name: '换一道试试', exact: true })).toHaveCount(0);
  await view.getByLabel('讲解方式', { exact: true }).selectOption('socratic');
  // A C1 turn in the same path must not supersede the explicit practice action.
  const firstRun = await sendOrdinary(page, '[C1学习] [C2变式] 请先讲一个输入边界的小点。');
  const id = firstRun.conversation_id;
  const initial = (await readConversation(page, id)).messages.at(-1)!.teaching!.current;
  view = await arrangement(page);
  await expect(view.getByRole('button', { name: '继续学习', exact: true })).toHaveCount(0);
  const input = page.getByLabel('输入学习问题', { exact: true });
  const draft = '🧩这是还没有发出的学习草稿。';
  await input.fill(draft);
  let loseResponse = true;
  const posted: Array<Record<string, unknown>> = [];
  await page.route(/\/api\/ai\/conversations\/[^/]+\/messages$/, async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    posted.push(route.request().postDataJSON());
    if (!loseResponse) { await route.continue(); return; }
    loseResponse = false;
    const accepted = await route.fetch();
    expect(accepted.ok()).toBeTruthy();
    await route.abort('failed');
  });
  await view.getByRole('button', { name: '换一道试试', exact: true }).click();
  await expect(page.locator('.ai-room-error')).toBeVisible();
  await expect(input).toHaveValue(draft);
  await expect(view.getByRole('button', { name: '换一道试试', exact: true })).toBeDisabled();
  await ordinaryAction(page, id, '重试发送');
  expect(posted.slice(0, 2).map(value => value.teaching_action)).toEqual(['practice', 'practice']);
  expect(posted[0].client_message_id).toBe(posted[1].client_message_id);
  await expect(input).toHaveValue(draft);
  let saved = await readConversation(page, id);
  expect(saved.messages).toHaveLength(4);
  const questionAnswer = saved.messages.at(-1)!;
  const practice = questionAnswer.teaching!.practice_question!;
  expect(practice).toMatchObject({ id: questionAnswer.id, phase: 'awaiting_attempt', basis_step: initial.step });
  const questionText = excerpt(questionAnswer.content, practice.question.start, practice.question.end);
  await expect(view).toContainText('等待作答');
  expect(await view.locator('.teaching-state__practices').evaluate(element => (element as HTMLDetailsElement).open)).toBe(false);
  let groups = await records(view);
  await expect(groups).toHaveCount(1);
  await expect(groups.first()).toContainText(questionText);
  await expect(groups.first()).toContainText(initial.step!.text);

  const original = '[C2作答] 🧩我先检查缺失编号，再检查两个编号都存在的情况。';
  await sendOrdinary(page, original);
  const firstFeedback = (await readConversation(page, id)).messages.at(-1)!;
  expect(firstFeedback.teaching!.practice_observation).toMatchObject({ question_id: practice.id, eligible: true, needs_help: false });
  await expect(view).toContainText('已有反馈');
  await sendOrdinary(page, '[C2作答] [C2卡住] 我试过缺失编号，仍不知道怎样返回。');
  let observations = view.getByRole('article', { name: '练习作答', exact: true });
  await expect(observations).toHaveCount(2);
  await observations.last().getByLabel('尝试进展', { exact: true }).selectOption('progressed');
  await expect(observations.last().getByLabel('尝试进展', { exact: true })).toHaveValue('progressed');
  await observations.first().getByRole('button', { name: '这不是一次尝试', exact: true }).click();
  await expect(observations.first()).toContainText('已改为非尝试');
  await expect(observations.first()).toContainText(firstFeedback.content.trim());
  await expect(view.getByRole('article', { name: 'AI识别的尝试', exact: true })).toHaveCount(0);
  await page.reload(); view = await arrangement(page); groups = await records(view);
  observations = view.getByRole('article', { name: '练习作答', exact: true });
  await expect(observations.first()).toContainText(original);
  await expect(observations.first()).toContainText('已改为非尝试');
  await expect(observations.first()).toContainText(firstFeedback.content.trim());
  await expect(observations.last().getByLabel('尝试进展', { exact: true })).toHaveValue('progressed');
  await mobileScreenshot(page, view, '/tmp/nautilus-teaching-practice-ordinary-390.png');
  await page.setViewportSize({ width: 1280, height: 900 });

  await input.fill(draft);
  const again = await ordinaryAction(page, id, '换一道试试');
  expect(again.request().postDataJSON()).toMatchObject({ content: '换一道试试。', teaching_action: 'practice' });
  await expect(input).toHaveValue(draft);
  const secondQuestion = (await readConversation(page, id)).messages.at(-1)!;
  await expect(groups).toHaveCount(2);
  await view.getByLabel('讲解方式', { exact: true }).selectOption('stepwise');
  const regenerate = ordinaryResponse(page);
  await page.locator('.ai-message--assistant').last().getByRole('button', { name: '重新生成', exact: true }).click();
  expect((await regenerate).request().postDataJSON()).toMatchObject({ regenerate_message_id: secondQuestion.id, teaching_action: 'practice' });
  await ordinaryFinished(page, id);
  const replacement = (await readConversation(page, id)).messages.at(-1)!;
  await expect(groups).toHaveCount(2);
  await expect(groups.last()).toContainText(replacement.content.trim());
  await page.locator('.ai-message--assistant').last().getByRole('button', { name: '上一个回答', exact: true }).click();
  await expect(groups.last()).toContainText(secondQuestion.content.trim());
  await expect(groups.last()).not.toContainText(replacement.content.trim());
  const branched = page.waitForResponse(response => response.url().endsWith(`/api/ai/conversations/${id}/branches`) && response.request().method() === 'POST');
  await page.locator('.ai-message--assistant').last().getByRole('button', { name: '从这里创建独立对话', exact: true }).click();
  const branch = await branched; expect(branch.ok()).toBeTruthy();
  const branchId = (await branch.json()).conversation.id;
  await expect(page.getByRole('button', { name: '返回原对话', exact: true })).toBeVisible();
  view = await arrangement(page); groups = await records(view);
  await expect(groups).toHaveCount(2);
  const before = (await readConversation(page, branchId)).messages.at(-1)!.teaching!.current;
  expect(before.practice!.id).not.toBe(secondQuestion.id);
  await sendOrdinary(page, '[C2慢流] [C2作答] 我先检查新的输入。', false);
  await expect(page.locator('.ai-message--assistant').last().locator('.ai-message-content')).not.toBeEmpty();
  await expect(view.getByRole('button', { name: '继续学习', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '取消生成', exact: true }).click();
  await ordinaryFinished(page, branchId);
  saved = await readConversation(page, branchId);
  expect(saved.messages.at(-1)!.teaching).toMatchObject({ status: 'not_updated', current: before, practice_observation: null });
  await page.reload(); view = await arrangement(page); groups = await records(view);
  await expect(groups).toHaveCount(2);
  const skip = await ordinaryAction(page, branchId, '继续学习');
  expect(skip.request().postDataJSON()).toMatchObject({ content: '这道先不练了，继续学习。', teaching_action: 'continue' });
  expect((await readConversation(page, branchId)).messages.at(-1)!.teaching!.current.practice).toBeNull();
  await expect(groups).toHaveCount(2);
  await expect(view.getByRole('button', { name: '继续学习', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '返回原对话', exact: true }).click();
  view = await arrangement(page);
  await expect(view.getByRole('button', { name: '继续学习', exact: true })).toBeEnabled();
  expect((await readConversation(page, id)).messages.find(message => message.id === secondQuestion.id)!.teaching!.current.practice!.id).toBe(secondQuestion.id);
  expect(errors).toEqual([]);
});

test('question discussion keeps separate turn sources and original verification through optional practice, correction, versions and branch cancellation', async ({ page }) => {
  test.setTimeout(150_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await setup(page);
  await page.getByRole('button', { name: '学习首页', exact: true }).first().click();
  if (await (await page.request.get('/api/learning/return-review')).json()) await page.getByRole('button', { name: '创建', exact: true }).click();
  await page.getByLabel('学习目标', { exact: true }).fill('合成目标：可选变式练习');
  await page.getByRole('button', { name: '我想自己安排', exact: true }).click();
  await page.getByLabel('现在先做什么', { exact: true }).fill('合成可选练习讨论旅程');
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
  async function accepted() { return page.waitForResponse(response => response.url().endsWith(`/api/learning/discussions/${id}/messages`) && response.request().method() === 'POST'); }
  async function finished() {
    await expect.poll(async () => (await read()).turns.at(-1)?.status, { timeout: 15_000 }).not.toBe('running');
    await expect(room.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  }
  const input = room.getByLabel('继续提问或回答拓展问题');
  async function send(text: string, complete = true) {
    const response = accepted();
    await input.fill(text); await input.press('Enter');
    const value = await response; expect(value.ok()).toBeTruthy();
    if (complete) await finished();
    return value;
  }
  async function action(label: string) {
    const response = accepted();
    await room.getByRole('button', { name: label, exact: true }).click();
    const value = await response; expect(value.ok()).toBeTruthy();
    await finished(); return value;
  }
  const source = await read();
  const reviewPath = `/api/learning/verifications/${source.verification_id}?submission_id=${source.submission_id}&evaluation_id=${source.evaluation_id}`;
  const originalReview: VerificationReview = await (await page.request.get(reviewPath)).json();
  const practicesPath = `/api/learning/verifications/${source.verification_id}/practices?submission_id=${source.submission_id}&evaluation_id=${source.evaluation_id}&question_id=${source.question_id}`;
  const originalPractices = await (await page.request.get(practicesPath)).json();
  let view = await arrangement(page);
  await expect(view.getByRole('button', { name: '换一道试试', exact: true })).toHaveCount(0);
  await view.getByLabel('讲解方式', { exact: true }).selectOption('socratic');
  await send('[C2变式] 请完整讲解当前输入的小点。');
  const basis = (await read()).turns.at(-1)!.teaching!.current.step!;
  const draft = '还没发出的题目讨论草稿。';
  await input.fill(draft);
  expect((await action('换一道试试')).request().postDataJSON().teaching_action).toBe('practice');
  await expect(input).toHaveValue(draft);
  const question = (await read()).turns.at(-1)!;
  const practice: TeachingPractice = question.teaching!.practice_question!;
  expect(practice.id).toBe(question.id);
  let groups = await records(view);
  await expect(groups.first()).toContainText(basis.text);
  await expect(groups.first()).toContainText(question.assistant_content!.trim());
  await expect(groups.first()).not.toContainText(question.user_content!);
  const answer = '[C2作答] 🧩我先检查缺失编号，并说明缺失时的返回值。';
  await send(answer);
  const feedback = (await read()).turns.at(-1)!;
  expect(feedback.teaching!.practice_observation).toMatchObject({ question_id: practice.id, message_id: feedback.id, answer_id: feedback.id, eligible: true });
  let observation = view.getByRole('article', { name: '练习作答', exact: true });
  await expect(observation).toContainText(answer);
  await expect(observation).toContainText(feedback.assistant_content!.trim());
  await observation.getByLabel('尝试进展', { exact: true }).selectOption('stuck');
  await expect(observation.getByLabel('尝试进展', { exact: true })).toHaveValue('stuck');
  await observation.getByRole('button', { name: '这不是一次尝试', exact: true }).click();
  await expect(observation).toContainText('已改为非尝试');
  await page.reload(); view = await arrangement(page); groups = await records(view);
  observation = view.getByRole('article', { name: '练习作答', exact: true });
  await expect(observation).toContainText(answer);
  await expect(observation).toContainText(feedback.assistant_content!.trim());
  await expect(observation).toContainText('已改为非尝试');
  await observation.getByRole('button', { name: '恢复为尝试', exact: true }).click();
  await expect(observation.getByLabel('尝试进展', { exact: true })).toHaveValue('stuck');
  await mobileScreenshot(page, view, '/tmp/nautilus-teaching-practice-discussion-390.png');
  await page.setViewportSize({ width: 1280, height: 900 });

  await input.fill(draft);
  await action('换一道试试');
  await expect(input).toHaveValue(draft);
  const secondQuestion = (await read()).turns.at(-1)!;
  const regeneration = accepted();
  await room.locator('.ai-message--assistant').last().getByRole('button', { name: '重新生成', exact: true }).click();
  expect((await regeneration).request().postDataJSON()).toMatchObject({ regenerate_turn_id: secondQuestion.id, teaching_action: 'practice' });
  await finished();
  const replacement = (await read()).turns.at(-1)!;
  await expect(groups).toHaveCount(2);
  await expect(groups.last()).toContainText(replacement.assistant_content!.trim());
  await room.locator('.ai-message--assistant').last().getByRole('button', { name: '上一个回答', exact: true }).click();
  await expect(groups.last()).toContainText(secondQuestion.assistant_content!.trim());
  const branched = page.waitForResponse(response => response.url().endsWith(`/api/learning/discussions/${id}/branches`) && response.request().method() === 'POST');
  await room.locator('.ai-message--assistant').last().getByRole('button', { name: '从这里创建独立对话', exact: true }).click();
  const branch = await branched; expect(branch.ok()).toBeTruthy();
  id = (await branch.json()).id;
  await expect(room.getByRole('button', { name: '返回原讨论', exact: true })).toBeVisible();
  view = await arrangement(page); groups = await records(view);
  await expect(groups).toHaveCount(2);
  const before = (await read()).turns.at(-1)!.teaching!.current;
  expect(before.practice!.id).not.toBe(secondQuestion.id);
  await send('[C2慢流] [C2作答] 我再检查两个编号。', false);
  await expect(room.locator('.ai-message--assistant').last().locator('.ai-message-content')).not.toBeEmpty();
  await expect(view.getByRole('button', { name: '继续学习', exact: true })).toBeDisabled();
  await room.getByRole('button', { name: '取消生成', exact: true }).click();
  await finished();
  expect((await read()).turns.at(-1)!.teaching).toMatchObject({ status: 'not_updated', current: before, practice_observation: null });
  await page.reload(); view = await arrangement(page); groups = await records(view);
  await expect(groups).toHaveCount(2);
  expect((await action('继续学习')).request().postDataJSON().teaching_action).toBe('continue');
  expect((await read()).turns.at(-1)!.teaching!.current.practice).toBeNull();
  await expect(groups).toHaveCount(2);
  await expect(view.getByRole('button', { name: '继续学习', exact: true })).toHaveCount(0);
  expect((await read()).source).toEqual(source.source);
  const finalReview: VerificationReview = await (await page.request.get(reviewPath)).json();
  expect(finalReview.content).toEqual(originalReview.content);
  expect(finalReview.evaluations).toEqual(originalReview.evaluations);
  expect(finalReview.result).toEqual(originalReview.result);
  expect(await (await page.request.get(practicesPath)).json()).toEqual(originalPractices);
  await room.getByRole('button', { name: '返回原讨论', exact: true }).click();
  view = await arrangement(page);
  await expect(view.getByRole('button', { name: '继续学习', exact: true })).toBeEnabled();
  expect(errors).toEqual([]);
});
