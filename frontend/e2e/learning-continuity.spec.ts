import { expect, test, type Page } from '@playwright/test';
import { authorize } from './fact-helpers';

async function openLearning(page: Page) {
  await expect(page.getByRole('button', {name:'退出会话'})).toBeVisible();
  const button = page.getByRole('button', { name: '学习首页', exact: true }).first();
  if (!(await button.isVisible())) await page.getByRole('button', { name: '打开导航' }).click();
  await button.click();
  const close = page.getByRole('button', { name: '关闭导航' });
  if (await close.isVisible()) await close.click();
}
async function provider(page: Page) {
  const response = await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic continuity provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model: 'mock-success', api_key: 'synthetic-test-only', enabled: true, request_timeout_seconds: 15,
  }});
  expect(response.ok()).toBeTruthy();
}
async function setup(page: Page, title: string) {
  const existing = await (await page.request.get('/api/learning/return-review')).json();
  await openLearning(page);
  const card = page.getByRole('region', { name: '当前学习' });
  if (existing) {
    await expect(card).toBeVisible();
    await page.getByRole('button', { name: '创建', exact: true }).click();
  }
  await page.getByLabel('学习目标', { exact: true }).fill('合成目标：解释编号匹配及未知情况');
  await page.getByRole('button', { name: '让 AI 帮我整理第一步' }).click();
  await page.getByLabel('现在先做什么', { exact: true }).fill(title);
  await page.getByRole('button', { name: '确认这份学习安排' }).click();
  await page.getByRole('button', { name: '进入学习室并开始这项任务' }).click();
  await expect(page.getByRole('region', { name: '本次学习安排' })).toContainText(title);
}

test('learning position: AI summary, correction, refresh and answer version isolation', async ({ page }) => {
  await authorize(page);
  await provider(page);
  await page.reload(); // Provider setup used the API; refresh the workspace's cached selection.
  await setup(page, '合成位置记录');
  await expect(page.getByRole('button', { name: '重新生成', exact: true }).first()).toBeEnabled();
  const arrangement = page.getByRole('region', { name: '本次学习安排' });
  await arrangement.locator('summary').first().click();
  const position = page.locator('.learning-position');
  await position.getByRole('button', { name: 'AI整理', exact: true }).click();
  await expect(position).toContainText('正在讨论如何定位日志编号，尚未验证理解。');
  await expect(position.getByText('AI概括', { exact: true })).toBeVisible();
  await position.getByText('查看依据对话', { exact: true }).click();
  await expect(position.locator('.learning-position__excerpt')).toHaveCount(2);
  await position.getByRole('button', { name: '修改记录', exact: true }).click();
  await position.getByRole('textbox', { name: '当前讨论', exact: true }).fill('我还在确认数字范围');
  await position.getByRole('textbox', { name: '建议下一步', exact: true }).fill('比较空输入与正常输入');
  await position.getByRole('button', { name: '保存记录', exact: true }).click();
  await expect(position.getByText('我的记录', { exact: true })).toBeVisible();
  await page.reload();
  await arrangement.locator('summary').first().click();
  await expect(position).toContainText('我还在确认数字范围');
  await expect(position).toContainText('比较空输入与正常输入');
  await page.getByRole('button', { name: '重新生成', exact: true }).first().click();
  await expect(page.getByRole('button', { name: '上一个回答', exact: true })).toBeEnabled();
  await expect(position).toContainText('未记录，请整理或自己填写。');
  await page.getByRole('button', { name: '上一个回答', exact: true }).click();
  await expect(position).toContainText('我还在确认数字范围');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(position.getByRole('button', { name: '修改记录', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: '/tmp/nautilus-position-preview.png', fullPage: true });
});

test('new learning → saved verification → confirmed completion → return card → continue', async ({ page }) => {
  await authorize(page);
  await provider(page);
  await setup(page, '合成完成旅程');
  await page.getByRole('button', { name: '进入验证', exact: true }).click();
  await page.getByRole('button', { name: '开始验证', exact: true }).click();
  await page.getByPlaceholder('写出你的判断、过程或结果').fill('我先定位编号，再检查字符类型。目前不知道空输入时的情况。');
  await page.getByRole('button', { name: '保存作答并验证' }).click();
  await expect(page.getByText('作答已保存。', { exact: false })).toBeVisible();
  await page.route('**/api/learning/metrics', route => route.fulfill({ status: 500, json: { detail: 'Synthetic metrics outage' } }));
  await page.getByRole('button', { name: '返回学习室', exact: true }).click();
  await page.getByRole('button', { name: '返回工作区', exact: true }).click();
  const savedCard = await (await page.request.get('/api/learning/return-review')).json();
  const savedReview = page.getByRole('region', { name: '当前学习' });
  await expect(savedReview).toContainText(savedCard.recommendation.explanation);
  await savedReview.getByRole('button', { name: '继续验证', exact: true }).click();
  await expect(page.getByText('作答已保存。', { exact: false })).toBeVisible();
  expect(await (await page.request.get('/api/learning/return-review')).json()).toMatchObject({
    position: { delegation_id: savedCard.position.delegation_id },
    what_happened: { verification_id: savedCard.what_happened.verification_id },
  });
  await page.getByRole('checkbox', { name: /我已核对结果/ }).check();
  await page.getByRole('button', { name: '确认完成本次委托' }).click();
  const card = page.getByRole('region', { name: '当前学习' });
  await expect(card).toBeVisible();
  await expect(card).toContainText('本次学习已完成');
  const firstState = await (await page.request.get('/api/learning/state')).json();
  const firstPlan = firstState.plans[0].id;
  await expect(card.getByText('已完成', {exact:true})).toBeVisible();
  await expect(card.getByRole('heading', {name:'已有依据'})).toHaveCount(0);
  await page.reload();
  await openLearning(page);
  await expect(card).toContainText('合成完成旅程');
  await card.getByRole('button', { name: '添加下一步', exact: true }).click();
  await expect(page.getByRole('heading', { name: '接下来学什么？' })).toBeVisible();
  await page.getByLabel('下一步想做什么', {exact:true}).fill('合成目标：观察另一个输入');
  await page.getByRole('button', {name:'让 AI 帮我整理下一步',exact:true}).click();
  await page.getByLabel('现在先做什么', {exact:true}).fill('复核后确认的下一步');
  await page.getByRole('button', {name:'确认这份学习安排'}).click();
  const secondState = await (await page.request.get('/api/learning/state')).json();
  expect(secondState.plans).toHaveLength(firstState.plans.length);
  expect(secondState.goals).toHaveLength(firstState.goals.length);
  const step = secondState.actions.find(item => item.title === '复核后确认的下一步');
  expect(secondState.action_links.find(item => item.action_id === step.id).plan_id).toBe(firstPlan);
  await page.getByRole('button', {name:'进入学习室并开始这项任务'}).click();
  await page.getByRole('button', {name:'进入验证',exact:true}).click();
  await page.getByRole('button', {name:'开始验证',exact:true}).click();
  await page.getByPlaceholder('写出你的判断、过程或结果').fill('合成作答：比较了新输入并记录未检查的边界。');
  await page.getByRole('button', {name:'保存作答并验证'}).click();
  await page.getByRole('checkbox', {name:/我已核对结果/}).check();
  await page.getByRole('button', {name:'确认完成本次委托'}).click();
  await expect(card).toContainText('复核后确认的下一步');
  const metrics = await (await page.request.get('/api/learning/metrics')).json();
  // Resuming the saved verification and adding the next step each produced a
  // confirmed recommendation choice followed by its action completion.
  expect(metrics.product_metrics.review_to_next_action).toMatchObject({status:'observed',numerator:2,denominator:2});
});

test('interruption → reopened return card → same delegation and conversation on 390px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await authorize(page);
  await provider(page);
  await setup(page, '合成恢复旅程');
  await page.getByPlaceholder(/输入关于/).fill('合成消息：请保留这次编号练习的上下文');
  await page.getByRole('button', { name: '发送问题', exact: true }).click();
  await expect(page.getByText('合成消息：请保留这次编号练习的上下文', {exact:true})).toBeVisible();
  const before = await (await page.request.get('/api/learning/return-review')).json();
  const oldRoom = await (await page.request.get(`/api/learning/sessions/${before.position.last_session}/room`)).json();
  expect(oldRoom.conversation_id).toBeTruthy();
  await page.route('**/api/learning/metrics', route => route.fulfill({ status: 500, json: { detail: 'Synthetic metrics outage' } }));
  await page.getByRole('button', { name: '今天先停', exact: true }).click();
  await expect(page.getByRole('region', { name: '当前学习' })).toContainText('学习位置已保存');
  await page.reload();
  await openLearning(page);
  const card = page.getByRole('region', { name: '当前学习' });
  await expect(card.getByText('正在学习', {exact:true})).toBeVisible();
  const interrupted = await (await page.request.get('/api/learning/return-review')).json();
  await expect(card).toContainText(interrupted.recommendation.explanation);
  for (const viewport of [{width:390,height:844},{width:1024,height:640},{width:1440,height:1000}]) {
    await page.setViewportSize(viewport);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    const button = await card.getByRole('button', { name: '继续学习', exact: true }).boundingBox();
    expect(button!.y).toBeLessThan(viewport.height);
    await page.screenshot({path: `/tmp/nautilus-return-${viewport.width}.png`, fullPage: true});
  }
  await page.setViewportSize({ width:390,height:844 });
  await page.evaluate(() => { document.documentElement.style.zoom='1.25'; });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.evaluate(() => { document.documentElement.style.zoom='1'; });
  await card.getByRole('button', { name: '继续学习', exact: true }).click();
  await expect(page.getByRole('region', { name: '本次学习安排' })).toContainText('合成恢复旅程');
  await expect(page.getByText('合成消息：请保留这次编号练习的上下文', {exact:true})).toBeVisible();
  const after = await (await page.request.get('/api/learning/return-review')).json();
  expect(after.position.delegation_id).toBe(before.position.delegation_id);
  expect(after.position.last_session).not.toBe(before.position.last_session);
  const room = await (await page.request.get(`/api/learning/sessions/${after.position.last_session}/room`)).json();
  expect(room.conversation_id).toBe(oldRoom.conversation_id);
  const metrics = await (await page.request.get('/api/learning/metrics')).json();
  expect(metrics.product_metrics.interrupted_delegation_recovery).toMatchObject({status:'observed', numerator:1,denominator:1});
});

test('creating a goal after continuing an active goal opens an isolated teaching conversation', async ({ page }) => {
  await authorize(page);
  await provider(page);
  await setup(page, '隔离旅程：旧目标任务');
  await expect(page.locator('.ai-message--assistant')).toContainText('完成');
  await expect(page.getByRole('button', {name:'取消生成',exact:true})).toHaveCount(0);
  await page.getByRole('button', {name:'返回工作区'}).click();
  await page.getByRole('region', {name:'当前学习'}).getByRole('button', {name:'继续学习',exact:true}).click();
  const firstCard = await (await page.request.get('/api/learning/return-review')).json();
  const firstRoom = await (await page.request.get(`/api/learning/sessions/${firstCard.position.last_session}/room`)).json();
  const original = await (await page.request.get(`/api/ai/conversations/${firstRoom.conversation_id}`)).json();
  expect(original.messages).toHaveLength(2);
  await page.getByRole('button', {name:'返回工作区'}).click();
  await setup(page, '隔离旅程：全新目标任务');
  await expect(page.locator('.ai-learning-prompt')).toHaveCount(1);
  await expect(page.locator('.ai-learning-prompt')).toContainText('隔离旅程：全新目标任务');
  await expect(page.locator('.ai-learning-prompt')).not.toContainText('隔离旅程：旧目标任务');
  await expect(page.locator('.ai-message--assistant')).toContainText('完成');
  const nextCard = await (await page.request.get('/api/learning/return-review')).json();
  const nextRoom = await (await page.request.get(`/api/learning/sessions/${nextCard.position.last_session}/room`)).json();
  expect(nextRoom.brief.delegation_id).not.toBe(firstRoom.brief.delegation_id);
  expect(nextRoom.brief.action_id).not.toBe(firstRoom.brief.action_id);
  expect(nextRoom.conversation_id).not.toBe(firstRoom.conversation_id);
  expect(nextRoom.conversation_ids).not.toContain(firstRoom.conversation_id);
  const state = await (await page.request.get('/api/learning/state')).json();
  expect(state.sessions.find(item => item.id === firstCard.position.last_session).status).toBe('interrupted');
  expect(state.sessions.filter(item => item.status === 'running')).toEqual([expect.objectContaining({delegation_id:nextRoom.brief.delegation_id})]);
  await page.reload();
  await expect(page.getByRole('region', {name:'本次学习安排'})).toContainText('隔离旅程：全新目标任务');
  await expect(page.locator('.ai-learning-prompt')).not.toContainText('隔离旅程：旧目标任务');
  const originalAfter = await (await page.request.get(`/api/ai/conversations/${firstRoom.conversation_id}`)).json();
  expect(originalAfter.messages).toEqual(original.messages);
  const roomUrl = `**/api/learning/sessions/${nextCard.position.last_session}/room`;
  await page.route(roomUrl, route => route.fulfill({json:firstRoom}));
  await page.reload();
  await expect(page.getByRole('alert')).toContainText('学习室与当前任务不一致');
  await expect(page.getByLabel('输入学习问题', {exact:true})).toBeDisabled();
  await expect(page.locator('.ai-message--assistant')).toHaveCount(0);
  await page.unroute(roomUrl);
  await page.reload();
  await expect(page.locator('.ai-learning-prompt')).toContainText('隔离旅程：全新目标任务');
  await page.getByRole('button', {name:'返回工作区'}).click();
  await page.getByRole('button', {name:'学习计划',exact:true}).click();
  const firstPlan = state.action_links.find(item => item.action_id === firstRoom.brief.action_id).plan_id;
  // Navigate by the actual plan id because both synthetic AI drafts share a title.
  await page.goto(`/?view=plans&plan=${firstPlan}`);
  const task = page.getByRole('region', {name:'计划详情'}).locator('.learning-plan-task').filter({hasText:'隔离旅程：旧目标任务'});
  await task.getByRole('button', {name:'继续学习',exact:true}).click();
  await expect(page.locator('.ai-learning-prompt')).toContainText('隔离旅程：旧目标任务');
  await expect(page.locator('.ai-learning-prompt')).not.toContainText('隔离旅程：全新目标任务');
});


test('outcome review: history versions, raw artifact and deletion stay connected', async ({ page }) => {
  await authorize(page);
  await provider(page);
  await page.reload();
  await setup(page, '合成成果依据旅程');
  const card = await (await page.request.get('/api/learning/return-review')).json();
  const state = await (await page.request.get('/api/learning/state')).json();
  const action = state.actions.find(item => item.id === card.position.action_id);
  const savedArtifact = await page.request.post('/api/learning/artifacts', { data: {
    session_id: card.position.last_session, content: '合成原始产出：第一次边界分析',
    expected_version: action.version, idempotency_key: 'outcome-artifact',
  }});
  expect(savedArtifact.ok()).toBeTruthy();
  await page.getByRole('button', { name: '进入验证', exact: true }).click();
  await page.getByRole('button', { name: '开始验证', exact: true }).click();
  await page.getByPlaceholder('写出你的判断、过程或结果').fill('合成第一版作答：空输入仍待检查');
  await page.getByRole('button', { name: '保存作答并验证' }).click();
  await expect(page.getByText('作答已保存。', { exact: false })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: /我已核对结果/ })).toBeVisible();
  const record = await (await page.request.get(`/api/learning/records/${card.position.delegation_id}`)).json();
  const vid = record.verifications[0].id;
  const firstResponse = await page.request.get(`/api/learning/verifications/${vid}`);
  expect(firstResponse.ok()).toBeTruthy();
  const first = await firstResponse.json();
  const submitted = await page.request.post(`/api/learning/verifications/${vid}/submit`, { data: {
    responses: { q1: '合成第二版作答：已对照参考解法' }, evidence_condition: 'with_materials', request_key: 'outcome-second',
  }});
  expect(submitted.ok()).toBeTruthy();
  const second = await submitted.json();
  expect((await page.request.post(`/api/learning/verifications/${vid}/evaluate`, { data: {
    submission_id: second.latest_submission_id, request_key: 'outcome-evaluate-second',
  }})).ok()).toBeTruthy();
  await page.getByRole('button', { name: '返回学习室', exact: true }).click();
  await page.getByRole('button', { name: '返回工作区', exact: true }).click();
  await page.getByRole('button', { name: '学习记录', exact: true }).click();
  await page.getByRole('button', { name: /合成成果依据旅程.*次 AI 验证/ }).click();
  await page.getByRole('button', { name: '查看这个成果的依据' }).click();
  const outcome = page.getByRole('region', { name: '单成果依据回看' });
  await expect(outcome).toContainText('目前没有可用的已批准标准');
  await expect(outcome.getByRole('button', { name: '查看当时作答与评估版本' })).toHaveCount(2);
  await outcome.getByRole('button', { name: '查看这个版本的原始产出' }).click();
  await expect(outcome.locator('.outcome-review__raw')).toContainText('合成原始产出：第一次边界分析');
  await outcome.getByRole('button', { name: '查看当时作答与评估版本' }).last().click();
  const review = page.getByRole('region', { name: '验证回看' });
  await expect(review.getByLabel('查看哪次作答')).toHaveValue(first.selected_submission_id);
  await expect(review).toContainText('合成第一版作答：空输入仍待检查');
  expect(new URL(page.url()).searchParams.get('evaluation')).toBe(first.selected_evaluation_id);
  await page.reload();
  await expect(review.getByLabel('查看哪次作答')).toHaveValue(first.selected_submission_id);
  await expect(review).toContainText('合成第一版作答：空输入仍待检查');
  await review.getByLabel('查看哪次作答').selectOption(second.latest_submission_id);
  await expect(review).toContainText('合成第二版作答：已对照参考解法');
  await page.getByRole('button', { name: '返回成果依据' }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(outcome).toContainText('有资料');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: '/tmp/nautilus-outcome-preview.png', fullPage: true });
  await outcome.getByRole('button', { name: '查看当时作答与评估版本' }).first().click();
  await review.getByText('更多操作', { exact: true }).click();
  page.once('dialog', dialog => dialog.accept());
  await review.getByRole('button', { name: '彻底删除本次验证内容' }).click();
  await expect(review).toContainText('本次作答内容已彻底删除');
  await page.getByRole('button', { name: '返回成果依据' }).click();
  await expect(outcome.getByRole('button', { name: '查看当时作答与评估版本' })).toHaveCount(0);
  await expect(outcome.getByText('查看 AI 反馈', { exact: true })).toHaveCount(0);
  await expect(outcome).toContainText('内容已删除');
});
