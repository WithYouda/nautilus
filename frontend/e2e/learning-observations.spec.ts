import { expect, test, type Locator, type Page } from '@playwright/test';
import { authorize, checkDefaultTeachingSupport } from './fact-helpers';
import type { AiConversationDetail, QuestionDiscussion, TeachingRecord, VerificationReview } from '../src/api';

type Entry = { id: string; teaching: TeachingRecord | null; userContent: string | null; answerContent: string | null };
const attemptText = '[LEARN尝试] 🧩我先检查空输入。\n缺失编号时我还不知道返回什么。';
const correctedTopic = '空输入边界（已纠正）';
const correctedNote = '仍需检查返回值。';
const excerpt = (content: string, start: number, end: number) => Array.from(content).slice(start, end).join('');

async function expand(details: Locator) {
  await expect(details).toBeVisible();
  if (!(await details.evaluate(element => (element as HTMLDetailsElement).open))) await details.locator('summary').first().click();
}
async function arrangement(page: Page) {
  const view = page.locator('.teaching-arrangement');
  await expect(view).toBeVisible();
  await expand(view.locator('details').first());
  return view;
}
async function observations(page: Page) {
  const view = await arrangement(page);
  const panel = view.locator('.learning-observations');
  await expand(panel);
  return panel;
}
async function setup(page: Page) {
  const schema = await (await page.request.get(`http://127.0.0.1:${process.env.NAUTILUS_E2E_BACKEND_PORT ?? '8012'}/openapi.json`)).json();
  for (const path of ['/api/ai/conversations/{conversation_id}/messages/{message_id}/learning-observation', '/api/learning/discussions/{discussion_id}/turns/{turn_id}/learning-observation'])
    expect(schema.paths[path]).toBeTruthy();
  await authorize(page);
  expect((await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic learning observations provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model: 'mock-success', api_key: 'synthetic-learning-observation-key', enabled: true, request_timeout_seconds: 15,
  } })).ok()).toBeTruthy();
  const preferences = await (await page.request.get('/api/preferences')).json();
  expect((await page.request.put('/api/preferences', { data: { ...preferences, teaching_mode: 'stepwise', search: { mode: 'off' } } })).ok()).toBeTruthy();
  await checkDefaultTeachingSupport(page);
  await page.reload();
}

async function correctRecord(record: Locator, topic: string, state: 'progress' | 'difficulty' | 'uncertain', note: string) {
  await record.getByRole('button', { name: '纠正', exact: true }).click();
  await record.getByLabel('知识点', { exact: true }).fill(topic);
  await record.getByLabel('学习情况', { exact: true }).selectOption(state);
  await record.getByLabel('补充说明（可选）', { exact: true }).fill(note);
  await record.getByRole('button', { name: '保存纠正', exact: true }).click();
  await expect(record.locator('form')).toHaveCount(0);
  await expect(record).toContainText(topic);
}

async function journey(page: Page, read: () => Promise<Entry[]>, send: (text: string, help?: boolean) => Promise<void>, screenshot: string) {
  await send('[LEARN开始] 请讲输入边界。');
  await send('给个提示。', true);
  await send(attemptText);
  let entries = await read();
  const attempt = entries.at(-1)!;
  const [first, second] = attempt.teaching!.learning_observations!;
  expect([first.topic, second.topic]).toEqual(['空输入检查', '缺失编号返回值']);
  expect([first.state, second.state]).toEqual(['progress', 'difficulty']);
  expect(first.point_id).toBe(first.id);
  expect(second.point_id).toBe(second.id);
  expect(first.eligible && second.eligible).toBe(true);
  expect(excerpt(attempt.userContent!, first.source.start, first.source.end)).toBe('🧩我先检查空输入。');
  expect(excerpt(attempt.userContent!, second.source.start, second.source.end)).toBe('缺失编号时我还不知道返回什么。');
  expect(excerpt(attempt.answerContent!, first.feedback.start, first.feedback.end)).toBe('💬你说明了先检查空输入，这次有进展。');
  expect(first.help_context.some(help => help.request?.kind === 'hint' && help.provided)).toBe(true);
  let view = await arrangement(page);
  expect(await view.locator('.learning-observations').evaluate(element => (element as HTMLDetailsElement).open)).toBe(false);
  let panel = await observations(page);
  await expect(panel.locator('.learning-observations__point > .learning-observation')).toHaveCount(2);
  let record = panel.locator(`[data-observation-id="${first.id}"]`);
  await expect(record).toContainText('有进展');
  expect(await record.locator('.learning-observation__evidence').evaluate(element => (element as HTMLDetailsElement).open)).toBe(false);
  await expand(record.locator('.learning-observation__evidence'));
  await expect(record).toContainText('🧩我先检查空输入。');
  await expect(record).toContainText('💬你说明了先检查空输入，这次有进展。');
  await expect(record).toContainText('给个提示');
  await correctRecord(record, correctedTopic, 'uncertain', correctedNote);
  await expect(record).toContainText('你的纠正');
  await expand(record.locator('.learning-observation__evidence'));
  await expect(record).toContainText('AI原始观察 · 空输入检查 · 有进展');
  await page.reload();
  panel = await observations(page);
  record = panel.locator(`[data-observation-id="${first.id}"]`);
  await expect(record).toContainText(correctedNote);
  await send('[LEARN参考] 请按目前记录继续。');
  let latest = (await read()).at(-1)!;
  expect(latest.teaching!.learning_used).toEqual([first.id]);
  expect(latest.answerContent).toContain(`${correctedTopic}：尚不明确。按你的说明：${correctedNote}`);
  panel = await observations(page);
  await expand(panel.locator('.learning-observations__used'));
  await expect(panel.locator('.learning-observations__used')).toContainText('本轮回答当时参考');
  await record.getByRole('button', { name: '排除此观察', exact: true }).click();
  await expect(record).toContainText('已排除');
  await expect(panel.locator('.learning-observations__used')).toContainText('现已不再使用');
  await send('[LEARN参考] 排除后继续。');
  expect((await read()).at(-1)!.teaching!.learning_used).toEqual([second.id]);
  panel = await observations(page);
  await record.getByRole('button', { name: '恢复使用', exact: true }).click();
  await expect(record.locator(':scope > .learning-observation__label')).not.toContainText('已排除');
  view = await arrangement(page);
  await expand(view.locator('.teaching-state__attempts'));
  const attemptRecord = view.getByRole('article', { name: 'AI识别的尝试', exact: true }).first();
  await attemptRecord.getByRole('button', { name: '这不是一次尝试', exact: true }).click();
  await expect(record).toContainText('对应内容已改为非尝试');
  expect((await read()).find(entry => entry.id === attempt.id)!.teaching!.learning_observations!.every(item => !item.eligible)).toBe(true);
  await send('[LEARN参考] 核对已改为非尝试的记录。');
  expect((await read()).at(-1)!.teaching!.learning_used).toEqual([]);
  panel = await observations(page);
  await expand(view.locator('.teaching-state__attempts'));
  await attemptRecord.getByRole('button', { name: '恢复为尝试', exact: true }).click();
  await expect(record).not.toContainText('对应内容已改为非尝试');
  await send('[LEARN再试] 🧩我仍不知道空输入应返回什么。');
  entries = await read();
  latest = entries.at(-1)!;
  const repeated = latest.teaching!.learning_observations![0];
  expect(repeated.point_id).toBe(first.point_id);
  expect(repeated.state).toBe('difficulty');
  panel = await observations(page);
  await expect(panel.locator('.learning-observations__point > .learning-observation')).toHaveCount(2);
  const point = panel.locator('.learning-observations__point').first();
  await expect(point.locator(':scope > .learning-observation')).toContainText('仍有困难');
  await expand(point.locator('.learning-observations__history'));
  const old = point.getByRole('article', { name: '此前观察', exact: true });
  await expect(old).toContainText('尚不明确');
  await expand(old.locator('.learning-observation__corrections'));
  await expect(old.locator('.learning-observation__corrections')).toContainText('已排除');
  await expand(old.locator('.learning-observation__evidence'));
  await expect(old).toContainText('AI原始观察 · 空输入检查 · 有进展');
  await view.locator('.teaching-state__attempts > summary').click();
  await point.locator('.learning-observations__history > summary').click();
  await expand(point.locator(':scope > .learning-observation > .learning-observation__evidence'));
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(panel).toBeVisible();
  await point.locator(':scope > .learning-observation').scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: screenshot, fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  return { first, second, repeated, attemptId: attempt.id };
}

test('ordinary current path keeps corrigible sourced knowledge points, frozen usage and isolated branch copies', async ({ page }) => {
  test.setTimeout(180_000);
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await setup(page);
  await page.getByRole('button', { name: '学习室', exact: true }).click();
  await expect(page.getByLabel('输入学习问题', { exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '新建对话', exact: true }).click();
  let id = '';
  async function detail(): Promise<AiConversationDetail> { return (await page.request.get(`/api/ai/conversations/${id}`)).json(); }
  async function read(): Promise<Entry[]> {
    const saved = await detail();
    return saved.messages.filter(message => message.role === 'assistant').map(message => ({ id: message.id, teaching: message.teaching ?? null,
      answerContent: message.content, userContent: saved.messages.find(source => source.id === message.teaching?.attempt?.message_id)?.content ?? null }));
  }
  async function send(text: string, help = false) {
    const accepted = page.waitForResponse(response => /\/api\/ai\/conversations\/[^/]+\/messages$/.test(response.url()) && response.request().method() === 'POST');
    if (help) await page.locator('.ai-composer').getByRole('button', { name: '给个提示', exact: true }).click();
    else { const input = page.getByLabel('输入学习问题', { exact: true }); await input.fill(text); await input.press('Enter'); }
    const response = await accepted; expect(response.ok()).toBeTruthy(); id = (await response.json()).run.conversation_id;
    await expect.poll(async () => (await detail()).active_run, { timeout: 15_000 }).toBeNull();
    await expect(page.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  }
  const { first, repeated } = await journey(page, read, send, '/tmp/nautilus-learning-observations-ordinary-390.png');
  const sourceId = id; const original = await detail();
  const branched = page.waitForResponse(response => response.url().endsWith(`/api/ai/conversations/${id}/branches`) && response.request().method() === 'POST');
  await page.locator('.ai-message--assistant').last().getByRole('button', { name: '从这里创建独立对话', exact: true }).click();
  const branch = await branched; expect(branch.ok()).toBeTruthy(); id = (await branch.json()).conversation.id;
  await expect(page.getByRole('button', { name: '返回原对话', exact: true })).toBeVisible();
  const copied = (await read()).at(-1)!.teaching!.learning_observations![0];
  expect(copied.id).not.toBe(repeated.id);
  expect(copied.point_id).not.toBe(first.point_id);
  expect(copied.source.message_id).not.toBe(repeated.source.message_id);
  let panel = await observations(page);
  await correctRecord(panel.locator(`[data-observation-id="${copied.id}"]`), '仅分支空输入', 'progress', '这条纠正只留在分支。');
  expect((await (await page.request.get(`/api/ai/conversations/${sourceId}`)).json()).messages).toEqual(original.messages);
  await send('[LEARN参考] 分支继续。');
  expect((await read()).at(-1)!.teaching!.learning_used).toEqual([copied.id]);
  await page.getByRole('button', { name: '返回原对话', exact: true }).click();
  panel = await observations(page);
  await expect(panel).not.toContainText('仅分支空输入');
  await expect(panel.locator(`[data-observation-id="${repeated.id}"]`)).toContainText(correctedTopic);
  expect(errors).toEqual([]);
});

test('discussion observations preserve Unicode sources, corrections and conflicting history without changing formal verification', async ({ page }) => {
  test.setTimeout(180_000);
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await setup(page);
  await page.getByRole('button', { name: '学习首页', exact: true }).first().click();
  if (await (await page.request.get('/api/learning/return-review')).json()) await page.getByRole('button', { name: '创建', exact: true }).click();
  await page.getByLabel('学习目标', { exact: true }).fill('合成目标：逐点核对学习情况');
  await page.getByRole('button', { name: '我想自己安排', exact: true }).click();
  await page.getByLabel('现在先做什么', { exact: true }).fill('合成学习观察讨论旅程');
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
  async function detail(): Promise<QuestionDiscussion> { return (await page.request.get(`/api/learning/discussions/${id}`)).json(); }
  async function read(): Promise<Entry[]> { return (await detail()).turns.map(turn => ({ id: turn.id, teaching: turn.teaching ?? null, userContent: turn.user_content, answerContent: turn.assistant_content })); }
  async function send(text: string, help = false) {
    const accepted = page.waitForResponse(response => response.url().endsWith(`/api/learning/discussions/${id}/messages`) && response.request().method() === 'POST');
    if (help) await room.locator('.ai-composer').getByRole('button', { name: '给个提示', exact: true }).click();
    else { const input = room.getByLabel('继续提问或回答拓展问题'); await input.fill(text); await input.press('Enter'); }
    expect((await accepted).ok()).toBeTruthy();
    await expect.poll(async () => (await detail()).turns.at(-1)?.status, { timeout: 15_000 }).toBe('succeeded');
    await expect(room.getByRole('button', { name: '取消生成', exact: true })).toHaveCount(0);
  }
  const source = await detail();
  const reviewPath = `/api/learning/verifications/${source.verification_id}?submission_id=${source.submission_id}&evaluation_id=${source.evaluation_id}`;
  const originalReview: VerificationReview = await (await page.request.get(reviewPath)).json();
  await journey(page, read, send, '/tmp/nautilus-learning-observations-discussion-390.png');
  expect((await detail()).source).toEqual(source.source);
  const finalReview: VerificationReview = await (await page.request.get(reviewPath)).json();
  expect(finalReview.content).toEqual(originalReview.content);
  expect(finalReview.evaluations).toEqual(originalReview.evaluations);
  expect(finalReview.result).toEqual(originalReview.result);
  expect(errors).toEqual([]);
});
