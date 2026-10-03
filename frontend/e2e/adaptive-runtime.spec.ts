import { expect, test, type Locator, type Page } from '@playwright/test';
import { authorize, checkDefaultTeachingSupport } from './fact-helpers';
import type { AdaptiveLearningProfile, AiConversationDetail, AiRun, QuestionDiscussion } from '../src/api';

test.beforeEach(async ({ page }) => {
  // Route and schema readiness precede either browser journey.
  const response = await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT ?? '8012'}/openapi.json`);
  expect(response.ok()).toBeTruthy();
  const schema = await response.json();
  expect(schema.paths['/api/adaptive-learning']).toBeTruthy();
  expect(schema.paths['/api/adaptive-learning/changes']).toBeTruthy();
  for (const name of ['MessageSendRequest', 'QuestionDiscussionMessageRequest']) {
    expect(schema.components.schemas[name].properties.teaching_mode.anyOf.find((value: { enum?: string[] }) => value.enum)?.enum).toContain('adaptive');
  }
});

async function profile(page: Page): Promise<AdaptiveLearningProfile> {
  const response = await page.request.get('/api/adaptive-learning'); expect(response.ok()).toBeTruthy(); return response.json();
}

async function setup(page: Page) {
  await authorize(page);
  expect((await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic adaptive provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model: 'mock-success', api_key: 'synthetic-adaptive-key', enabled: true, request_timeout_seconds: 15,
  } })).ok()).toBeTruthy();
  await checkDefaultTeachingSupport(page);
  let state = await profile(page);
  expect(Array.isArray(state.ignored)).toBe(true);
  for (const draft of state.drafts) {
    const response = await page.request.post('/api/adaptive-learning/changes', { data: {
      expected_revision: state.revision, request_key: `synthetic-dismiss-${Date.now()}-${draft.id}`, action: 'dismiss', candidate_id: draft.id,
    } }); expect(response.ok()).toBeTruthy(); state = await response.json();
  }
  for (const rule of state.rules) {
    const response = await page.request.post('/api/adaptive-learning/changes', { data: {
      expected_revision: state.revision, request_key: `synthetic-remove-${Date.now()}-${rule.id}`, action: 'remove', rule_id: rule.id,
    } }); expect(response.ok()).toBeTruthy(); state = await response.json();
  }
  const preferences = await (await page.request.get('/api/preferences')).json();
  expect((await page.request.put('/api/preferences', { data: { ...preferences, teaching_mode: 'stepwise', search: { mode: 'off' } } })).ok()).toBeTruthy();
  await page.reload();
}

async function expand(locator: Locator) {
  await expect(locator).toBeVisible();
  if (!(await locator.evaluate(element => (element as HTMLDetailsElement).open))) await locator.locator('summary').first().click();
}

async function settings(page: Page) {
  await page.getByRole('button', { name: '设置', exact: true }).click();
  const dialog = page.locator('.unified-settings-dialog');
  await expect(dialog.getByRole('combobox', { name: '默认学习方式', exact: true })).toBeVisible();
  const preferences = dialog.locator('.adaptive-learning-settings');
  return { dialog, preferences };
}

async function adaptiveDefault(page: Page) {
  const { dialog } = await settings(page);
  await dialog.getByRole('combobox', { name: '默认学习方式', exact: true }).selectOption('adaptive');
  await expect(dialog).toContainText('新的偏好建议会在这里等待确认');
  await dialog.getByRole('button', { name: '保存默认设置', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '保存默认设置', exact: true })).toBeDisabled();
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
}

async function arrangement(page: Page) {
  const view = page.locator('.teaching-arrangement'); await expand(view.locator('details').first()); return view;
}

async function conversation(page: Page, id: string): Promise<AiConversationDetail> {
  return (await page.request.get(`/api/ai/conversations/${id}`)).json();
}

async function finished(page: Page, id: string) {
  await expect.poll(async () => (await conversation(page, id)).active_run, { timeout: 15_000 }).toBeNull();
  await expect(page.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
}

async function send(page: Page, content: string, complete = true): Promise<AiRun> {
  const accepted = page.waitForResponse(response => /\/api\/ai\/conversations\/[^/]+\/messages$/.test(response.url()) && response.request().method() === 'POST');
  const input = page.getByLabel('输入学习问题', { exact: true }); await input.fill(content); await input.press('Enter');
  const response = await accepted; expect(response.ok()).toBeTruthy(); const { run } = await response.json();
  if (complete) await finished(page, run.conversation_id); return run;
}

async function action(page: Page, id: string, label: string) {
  await arrangement(page);
  const accepted = page.waitForResponse(response => /\/api\/ai\/conversations\/[^/]+\/messages$/.test(response.url()) && response.request().method() === 'POST');
  await page.getByRole('button', { name: label, exact: true }).click();
  expect((await accepted).ok()).toBeTruthy(); await finished(page, id);
}

async function changed(page: Page, button: Locator) {
  const response = page.waitForResponse(value => value.url().endsWith('/api/adaptive-learning/changes') && value.request().method() === 'POST');
  await button.click(); const saved = await response; expect(saved.ok()).toBeTruthy(); return saved.json() as Promise<AdaptiveLearningProfile>;
}

test('adaptive settings preserve exact source, require confirmation, freeze retry and keep practice manual on 390px', async ({ page }) => {
  test.setTimeout(180_000);
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await setup(page);
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  const view = await arrangement(page);
  await expect(view.getByLabel('讲解方式', { exact: true }).locator('option[value="adaptive"]')).toHaveCount(0);
  await adaptiveDefault(page);
  await expect(view.getByLabel('讲解方式', { exact: true })).toContainText('沿用设置（个人自适应）');
  const { conversation_id: id } = await send(page, '[C2学习] [ADAPT概念] 理解输入边界。');
  expect((await conversation(page, id)).messages.at(-1)!.teaching).toMatchObject({ current: { mode: 'stepwise', policy: 'adaptive' }, adaptation: { method: 'stepwise', rule_id: null } });
  await expect(view).toContainText('当前方式 · 分步讲解');
  const quote = '[C2学习] [ADAPT偏好] 以后理解概念时，先让我自己试，卡住时再讲解。';
  await send(page, quote);
  const proposed = await profile(page);
  expect(proposed.rules).toHaveLength(0); expect(proposed.drafts).toHaveLength(1);
  expect(proposed.drafts[0]).toMatchObject({ original_text: quote, source: { kind: 'conversation', scope_id: id }, configuration: { scenario: 'concepts', method: 'socratic', start: 'try_first', help: 'explain_when_stuck' } });
  let { dialog, preferences } = await settings(page);
  await expect(preferences.locator('summary').first()).toContainText('1 条待确认');
  expect(await preferences.evaluate(element => (element as HTMLDetailsElement).open)).toBe(false);
  await expand(preferences);
  const pending = preferences.getByRole('article', { name: '待确认偏好', exact: true });
  await expand(pending.locator('.adaptive-learning__source'));
  await expect(pending.locator('blockquote')).toHaveText(quote);
  await expect(pending).toContainText('来源：学习对话中的反馈');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/nautilus-adaptive-settings-390.png', fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  // Adoption while a request is streaming must not rewrite its frozen profile.
  await send(page, '[C2慢流] [ADAPT概念] 继续理解输入边界。', false);
  ({ dialog, preferences } = await settings(page)); await expand(preferences);
  const accepted = await changed(page, preferences.getByRole('button', { name: '采纳', exact: true }));
  expect(accepted.rules).toHaveLength(1); expect(accepted.drafts).toHaveLength(0);
  expect((await (await page.request.get('/api/preferences')).json()).teaching_mode).toBe('adaptive');
  await dialog.getByRole('button', { name: '关闭', exact: true }).click(); await finished(page, id);
  expect((await conversation(page, id)).messages.at(-1)!.teaching!.adaptation).toMatchObject({ method: 'stepwise', profile_revision: proposed.revision });
  await send(page, '[C2学习] [ADAPT概念] 再解释输入边界。');
  expect((await conversation(page, id)).messages.at(-1)!.teaching).toMatchObject({ current: { mode: 'socratic', policy: 'adaptive' }, adaptation: { method: 'socratic', rule_id: accepted.rules[0].id, profile_revision: accepted.revision } });
  await expect(view).toContainText('当前方式 · 提问引导');
  await send(page, '[C2学习] [ADAPT概念] 请直接给答案。');
  expect((await conversation(page, id)).messages.at(-1)!.teaching).toMatchObject({ effective_mode: 'direct_answer', current: { mode: 'socratic', policy: 'adaptive' }, adaptation: { method: 'direct_answer' } });

  ({ dialog, preferences } = await settings(page)); await expand(preferences);
  let rule = preferences.getByRole('article', { name: '已确认偏好', exact: true }); await expand(rule.locator('.adaptive-learning__editor'));
  await rule.getByRole('combobox', { name: '如何开始', exact: true }).selectOption('example_first');
  const edited = await changed(page, rule.getByRole('button', { name: '保存偏好', exact: true }));
  expect(edited.rules[0].configuration.start).toBe('example_first');
  // A concurrent change refreshes the UI and never silently applies stale edits.
  await expand(rule.locator('.adaptive-learning__editor'));
  await rule.getByRole('combobox', { name: '学习方式', exact: true }).selectOption('stepwise');
  const concurrent = await page.request.post('/api/adaptive-learning/changes', { data: {
    expected_revision: edited.revision, request_key: `synthetic-concurrent-${Date.now()}`, action: 'edit', rule_id: edited.rules[0].id,
    configuration: { ...edited.rules[0].configuration, start: 'try_first' }, enabled: true,
  } }); expect(concurrent.ok()).toBeTruthy();
  await rule.getByRole('button', { name: '保存偏好', exact: true }).click();
  await expect(preferences.getByRole('alert')).toContainText('已读取最新内容');
  expect((await profile(page)).rules[0].configuration).toMatchObject({ method: 'socratic', start: 'try_first' });
  // Lost acknowledgements retry the identical command and key.
  rule = preferences.getByRole('article', { name: '已确认偏好', exact: true }); await expand(rule.locator('.adaptive-learning__editor'));
  await rule.getByLabel('启用这条偏好', { exact: true }).uncheck();
  let lose = true; const requests: Array<Record<string, unknown>> = [];
  await page.route('**/api/adaptive-learning/changes', async route => {
    requests.push(route.request().postDataJSON());
    if (!lose) { await route.continue(); return; }
    lose = false; expect((await route.fetch()).ok()).toBeTruthy(); await route.abort('failed');
  });
  await rule.getByRole('button', { name: '保存偏好', exact: true }).click();
  await expect(preferences.getByRole('button', { name: '重试保存', exact: true })).toBeVisible();
  await changed(page, preferences.getByRole('button', { name: '重试保存', exact: true }));
  expect(requests[0]).toEqual(requests[1]); expect((await profile(page)).rules[0].enabled).toBe(false);
  await page.unroute('**/api/adaptive-learning/changes');
  await expand(preferences.locator('.adaptive-learning__history'));
  const versions = (await profile(page)).history;
  const versionIndex = versions.findIndex(version => version.revision === accepted.revision); expect(versionIndex).toBeGreaterThanOrEqual(0);
  const restored = await changed(page, preferences.locator('.adaptive-learning__history article').nth(versionIndex).getByRole('button', { name: '恢复这份偏好', exact: true }));
  expect(restored.rules[0]).toMatchObject({ enabled: true, configuration: { method: 'socratic', start: 'try_first' } });
  const removed = await changed(page, preferences.getByRole('article', { name: '已确认偏好', exact: true }).getByRole('button', { name: '删除偏好', exact: true }));
  expect(removed.rules).toHaveLength(0);
  await changed(page, preferences.locator('.adaptive-learning__history article').nth(removed.history.findIndex(version => version.revision === accepted.revision)).getByRole('button', { name: '恢复这份偏好', exact: true }));
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  await send(page, '[C2学习] [ADAPT忽略] 以后写代码时，先看例子，一次给一个提示。');
  ({ dialog, preferences } = await settings(page)); await expand(preferences);
  const ignored = await changed(page, preferences.getByRole('button', { name: '忽略', exact: true }));
  expect(ignored.drafts).toHaveLength(0); expect(ignored.rules).toHaveLength(1);
  expect(ignored.ignored.some(draft => draft.configuration.scenario === 'coding')).toBe(true);
  const ignoredView = preferences.locator('.adaptive-learning__ignored');
  expect(await ignoredView.evaluate(element => (element as HTMLDetailsElement).open)).toBe(false);
  await expand(ignoredView);
  const ignoredDraft = ignoredView.getByRole('article', { name: '已忽略偏好', exact: true }).filter({ hasText: '写代码' });
  const reconsidered = await changed(page, ignoredDraft.getByRole('button', { name: '重新考虑', exact: true }));
  expect(reconsidered.drafts).toHaveLength(1); expect(reconsidered.rules).toHaveLength(1);
  await changed(page, preferences.getByRole('article', { name: '待确认偏好', exact: true }).getByRole('button', { name: '忽略', exact: true }));
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  await send(page, '[C2学习] [ADAPT忽略] 以后写代码时，先看例子，一次给一个提示。');
  expect((await profile(page)).drafts).toHaveLength(0);

  await send(page, '[C2练习] [ADAPT练习] 练习检查输入边界。');
  const exercise = (await conversation(page, id)).messages.at(-1)!.teaching!.current.exercise!; expect(exercise).toBeTruthy();
  await send(page, '[C2练习作答] [ADAPT概念] 我先检查缺失编号，再返回提示。');
  expect((await conversation(page, id)).messages.at(-1)!.teaching).toMatchObject({ current: { mode: 'practice_first', policy: 'adaptive', exercise: { id: exercise.id, phase: 'feedback_available' } }, exercise_question: null });
  await arrangement(page);
  await expect(view.getByRole('button', { name: '下一题', exact: true })).toBeVisible();
  await action(page, id, '用自己的话说说');
  expect((await conversation(page, id)).messages.at(-1)!.teaching!.current).toMatchObject({ exercise: { id: exercise.id }, practice: { kind: 'retelling' } });
  await expect(view.getByRole('button', { name: '下一题', exact: true })).toHaveCount(0);
  await action(page, id, '继续学习');
  expect((await conversation(page, id)).messages.at(-1)!.teaching!.current).toMatchObject({ practice: null, exercise: { id: exercise.id } });
  await page.setViewportSize({ width: 390, height: 844 }); await expect(view.getByRole('button', { name: '下一题', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/nautilus-adaptive-practice-390.png', fullPage: true });
  await action(page, id, '下一题');
  expect((await conversation(page, id)).messages.at(-1)!.teaching!.current.exercise!.id).not.toBe(exercise.id);
  expect(errors).toEqual([]);
});

test('adaptive question discussion preserves the current project step and traced pending suggestion', async ({ page }) => {
  test.setTimeout(180_000);
  await setup(page);
  await page.getByRole('button', { name: '学习首页', exact: true }).first().click();
  if (await (await page.request.get('/api/learning/return-review')).json()) await page.getByRole('button', { name: '创建', exact: true }).click();
  await page.getByLabel('学习目标', { exact: true }).fill('合成自适应目标：输入边界');
  await page.getByRole('button', { name: '我想自己安排', exact: true }).click();
  await page.getByLabel('现在先做什么', { exact: true }).fill('合成自适应题目讨论');
  await page.getByRole('button', { name: '确认这份学习安排', exact: true }).click();
  await page.getByRole('button', { name: '进入学习室并开始这项任务', exact: true }).click();
  await expect(page.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '进入验证', exact: true }).click();
  await page.getByRole('button', { name: '开始验证', exact: true }).click();
  await page.getByPlaceholder('写出你的判断、过程或结果').fill('合成原作答：先定位，再检查边界。');
  await page.getByRole('button', { name: '保存作答并验证', exact: true }).click();
  await page.getByRole('region', { name: '验证回看' }).getByRole('article', { name: '第 1 题回看' }).getByRole('button', { name: '讨论这道题', exact: true }).click();
  const room = page.getByRole('region', { name: '题目学习室' }); await expect(room).toBeVisible();
  await expect.poll(() => new URL(page.url()).searchParams.get('discussion')).not.toBeNull();
  const id = new URL(page.url()).searchParams.get('discussion')!;
  async function read(): Promise<QuestionDiscussion> { return (await page.request.get(`/api/learning/discussions/${id}`)).json(); }
  const source = await read();
  const reviewPath = `/api/learning/verifications/${source.verification_id}?submission_id=${source.submission_id}&evaluation_id=${source.evaluation_id}`;
  const review = await (await page.request.get(reviewPath)).json();
  async function round(content: string | null, label?: string) {
    const accepted = page.waitForResponse(response => response.url().endsWith(`/api/learning/discussions/${id}/messages`) && response.request().method() === 'POST');
    if (label) { await arrangement(page); await room.getByRole('button', { name: label, exact: true }).click(); }
    else { const input = room.getByLabel('继续提问或回答拓展问题'); await input.fill(content!); await input.press('Enter'); }
    expect((await accepted).ok()).toBeTruthy();
    await expect.poll(async () => (await read()).turns.at(-1)?.status, { timeout: 15_000 }).not.toBe('running');
    await expect(room.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  }
  await adaptiveDefault(page);
  await round('[C2项目] [ADAPT项目] 做一个检查输入边界的小程序。');
  const first = (await read()).turns.at(-1)!; const project = first.teaching!.current.project!; expect(project).toBeTruthy();
  expect(first.teaching).toMatchObject({ current: { mode: 'project', policy: 'adaptive' }, adaptation: { method: 'project' } });
  const view = room.locator('.teaching-state');
  await arrangement(page);
  await expect(view).toContainText('当前方式 · 项目实践');
  await expect(view.getByRole('button', { name: '下一步', exact: true })).toBeVisible();
  await round('[C2项目作品] [ADAPT概念] 代码：if not item: return "缺失"；运行结果：返回缺失。');
  expect((await read()).turns.at(-1)!.teaching).toMatchObject({ current: { mode: 'project', project: { id: project.id, step: { id: project.step.id, phase: 'feedback_available' } } }, project_step: null });
  const quote = '[C2学习] [ADAPT偏好] 以后理解概念时，先让我自己试，一次给一个提示。';
  await round(quote);
  const proposed = (await profile(page)).drafts.find(draft => draft.source.kind === 'discussion' && draft.source.scope_id === id)!; expect(proposed).toBeTruthy();
  expect(proposed.original_text).toBe(quote);
  expect((await read()).turns.at(-1)!.teaching!.current.project!.step.id).toBe(project.step.id);
  const { dialog, preferences } = await settings(page); await expand(preferences);
  const pending = preferences.getByRole('article', { name: '待确认偏好', exact: true }); await expand(pending.locator('.adaptive-learning__source'));
  await expect(pending).toContainText('来源：题目讨论中的反馈'); await expect(pending.locator('blockquote')).toHaveText(quote);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/nautilus-adaptive-discussion-settings-390.png', fullPage: true });
  await changed(page, pending.getByRole('button', { name: '采纳', exact: true }));
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  await round('[C2学习] [ADAPT概念] 我已做好，接下来呢？');
  expect((await read()).turns.at(-1)!.teaching).toMatchObject({ current: { mode: 'project', project: { step: { id: project.step.id } } }, project_step: null });
  await round(null, '下一步');
  expect((await read()).turns.at(-1)!.teaching!.current.project!.step.id).not.toBe(project.step.id);
  const finalReview = await (await page.request.get(reviewPath)).json();
  expect(finalReview.content).toEqual(review.content);
  expect(finalReview.evaluations).toEqual(review.evaluations);
  expect(finalReview.result).toEqual(review.result);
});
