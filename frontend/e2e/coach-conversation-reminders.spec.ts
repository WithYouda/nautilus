import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { authorize } from './fact-helpers';
import type { CoachReminderSettings, CoachReminderView } from '../src/coach-conversation-api';

test.setTimeout(90_000);
test.use({ timezoneId: 'Asia/Shanghai' });
const key = (kind: string) => `coach-complete:${kind}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
async function get(request: APIRequestContext, url: string): Promise<any> { const response = await request.get(url); expect(response.ok(), await response.text()).toBeTruthy(); return response.json(); }
async function post(request: APIRequestContext, url: string, data: object): Promise<any> { const response = await request.post(url, { data }); expect(response.ok(), await response.text()).toBeTruthy(); return response.json(); }
async function configure(page: Page, model = 'mock-success') { const response = await page.request.put('/api/ai/provider', { data: { display_name: 'Synthetic coach conversation', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL, model, api_key: 'synthetic-coach-only', enabled: true, request_timeout_seconds: 15 } }); expect(response.ok(), await response.text()).toBeTruthy(); }
async function seed(request: APIRequestContext, due?: string) {
  const plan = await post(request, '/api/learning/plans', { title: `合成学习计划 ${Math.random().toString(36).slice(2, 5)}`, description: '', goal_id: null, request_key: key('plan') });
  const organization = await get(request, `/api/learning/plans/${plan.plan_id}/organization`);
  const task = await post(request, `/api/learning/plans/${plan.plan_id}/tasks`, { action_title: '合成教练任务', context_key: key('context'), object_description: '合成输入', behavior: '解释合成输入', outcome_context_key: key('outcome'), outcome_id: null, criterion_id: null, boundaries: '仅合成数据', stop_conditions: '解释后停下', time_budget_minutes: null, expected_revision: organization.revision, request_key: key('task') });
  const pathUrl = `/api/learning/plans/${plan.plan_id}/path`, path = await get(request, pathUrl);
  const draft = await post(request, `${pathUrl}/drafts`, { title: '合成教练路线', nodes: [{ id: 'coach-node', title: '合成阶段', action_ids: [task.action_id], outcome_ids: [] }], edges: [], entry_node_id: 'coach-node', current_node_id: 'coach-node', reason: '', intent: 'create', expected_revision: path.revision, expected_organization_revision: path.organization_revision, request_key: key('path') });
  const preview = await post(request, `${pathUrl}/previews`, { draft_id: draft.draft_id });
  const adopted = await post(request, `${pathUrl}/decisions`, { draft_id: draft.draft_id, expected_draft_revision: preview.draft_revision, expected_revision: preview.revision, review_key: preview.review_key, request_key: key('adopt') });
  let item: any = null;
  if (due) {
    const base = `/api/learning/plans/${plan.plan_id}/commitments`, current = await get(request, base);
    const proposed = await post(request, `${base}/drafts`, { route_version_id: adopted.adopted_version_id, items: [{ id: null, node_id: 'coach-node', action_id: task.action_id, delegation_id: task.delegation_id, estimate_min_minutes: null, estimate_max_minutes: null, due_at: due, timezone: 'UTC', reason: '合成到期时点', source_refs: [] }], reason: '', draft_id: null, expected_revision: current.revision, request_key: key('commitment') });
    const review = await post(request, `${base}/previews`, { draft_id: proposed.draft_id });
    const confirmed = await post(request, `${base}/confirm`, { draft_id: proposed.draft_id, expected_draft_revision: review.draft_revision, expected_revision: review.revision, review_key: review.review_key, request_key: key('confirm') });
    item = confirmed.current_version.items[0];
  }
  return { id: plan.plan_id as string, task, item };
}
const facts = (state: any) => ({ actions: state.actions.map((item: any) => [item.id, item.status, item.version]), sessions: state.sessions.map((item: any) => [item.id, item.status, item.version]), artifacts: state.artifacts.map((item: any) => [item.id, item.content_version]), claims: state.evidence_claims.map((item: any) => [item.id, item.status]) });
async function screenshots(page: Page, name: string) { for (const width of [1280, 390, 320]) { await page.setViewportSize({ width, height: 900 }); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy(); await page.screenshot({ path: `/tmp/nautilus-coach-${name}-${width}.png`, fullPage: true }); } await page.setViewportSize({ width: 1280, height: 900 }); }
async function openCoach(page: Page, text?: string, fresh = false) { if (fresh) await post(page.request, '/api/learning/coach/conversations', { request_key: key('fresh'), new_conversation: true }); await page.goto('/?view=home'); const entry = page.getByRole('region', { name: '学习教练', exact: true }); if (text) { await entry.getByLabel('和教练说说今天').fill(text); await entry.getByRole('button', { name: '和教练聊聊', exact: true }).click(); } else await entry.getByRole('button', { name: '继续对话', exact: true }).click(); await expect(page.getByRole('heading', { name: '学习教练', exact: true, level: 1 })).toBeVisible(); }
const currentId = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem('nautilus.ai.coach-room')!).conversationId as string);

test('today conversation is continuous, resumes on refresh and navigates without starting a teaching session', async ({ page }) => {
  await authorize(page); await configure(page); await seed(page.request);
  await post(page.request, '/api/ai/conversations', { context_scope: 'global', title: '旧全局会话不混入' });
  const before = facts(await get(page.request, '/api/learning/state'));
  const homeLoads = ['/api/learning/state', '/api/learning/return-review'].map(path => page.waitForResponse(response => new URL(response.url()).pathname === path)); await page.goto('/?view=home'); for (const response of await Promise.all(homeLoads)) expect(response.ok(), `${new URL(response.url()).pathname}: ${response.status()}`).toBeTruthy(); await expect(page.getByRole('region', { name: '学习首页', exact: true })).toBeVisible(); await expect(page.locator('.fact-workspace .workspace-loading')).toHaveCount(0); await expect(page.locator('.fact-workspace .workspace-alert')).toHaveCount(0); await expect(page.getByRole('region', { name: '当前学习', exact: true })).toBeVisible(); await screenshots(page, 'home');
  await openCoach(page, '今天只有20分钟，有点累，想恢复学习。');
  const id = await currentId(page);
  await expect(page.locator('.ai-message--assistant:not(.ai-message--streaming)')).toHaveCount(1);
  await expect(page.getByRole('button', { name: '从这里创建独立对话', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '分支（尚未实现）', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '当前对话帮助记录' })).toHaveCount(0);
  await page.getByLabel('和教练说说今天', { exact: true }).fill('如果今天没开始，明天怎样接着做？'); await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.locator('.ai-message--assistant:not(.ai-message--streaming)')).toHaveCount(2);
  await page.reload(); await expect(page.getByRole('heading', { name: '学习教练', exact: true, level: 1 })).toBeVisible(); await expect(page.locator('.ai-message--assistant')).toHaveCount(2); expect(await currentId(page)).toBe(id);
  await page.getByRole('button', { name: '对话历史', exact: true }).click(); await expect(page.locator('.ai-history-list')).not.toContainText('旧全局会话不混入'); await page.getByRole('button', { name: '关闭对话历史', exact: true }).click();
  await screenshots(page, 'conversation');
  expect(facts(await get(page.request, '/api/learning/state'))).toEqual(before);
  const target = (await get(page.request, `/api/learning/coach/conversations/${id}`)).messages.find((item: any) => item.coach?.actions.some((action: any) => action.target.kind === 'task')).coach.actions.find((action: any) => action.target.kind === 'task');
  await page.getByRole('button', { name: target.label, exact: true }).first().click(); await expect(page).toHaveURL(new RegExp(`view=plans.*plan=${target.target.plan_id}`));
  expect(facts(await get(page.request, '/api/learning/state'))).toEqual(before);
  await expect(page.getByRole('button', { name: '开始学习', exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: '学习室', exact: true }).click(); await expect(page.getByRole('heading', { name: 'AI 学习室', exact: true, level: 1 })).toBeVisible(); await page.getByRole('button', { name: '对话历史', exact: true }).click(); await expect(page.locator('.ai-history-list')).toContainText('旧全局会话不混入'); await expect(page.locator(`[data-conversation-id="${id}"]`)).toHaveCount(0);
  let mappingUnavailable = true; await page.route('**/api/learning/coach/conversations', route => route.request().method() === 'GET' && mappingUnavailable ? route.fulfill({ status: 503, json: { detail: '合成教练身份列表暂时不可读' } }) : route.continue()); await page.reload(); await page.getByRole('button', { name: '对话历史', exact: true }).click(); await expect(page.getByRole('button', { name: '重读对话历史', exact: true })).toBeVisible(); await expect(page.locator(`[data-conversation-id="${id}"]`)).toHaveCount(0); mappingUnavailable = false; await page.getByRole('button', { name: '重读对话历史', exact: true }).click(); await expect(page.locator('.ai-history-list')).toContainText('旧全局会话不混入'); await expect(page.locator(`[data-conversation-id="${id}"]`)).toHaveCount(0);
  await page.getByRole('button', { name: '关闭对话历史', exact: true }).click(); await page.getByRole('button', { name: '返回工作区', exact: true }).click(); await page.setViewportSize({ width: 390, height: 900 }); await page.getByRole('button', { name: '打开学习教练', exact: true }).click(); const drawer = page.getByRole('dialog', { name: '学习教练抽屉', exact: true }); await drawer.getByLabel('和学习教练交流', { exact: true }).fill('现在多了十分钟，可以怎样继续？'); await drawer.getByRole('button', { name: '和教练聊聊', exact: true }).click(); await expect(page.getByRole('heading', { name: '学习教练', exact: true, level: 1 })).toBeVisible(); expect(await currentId(page)).toBe(id); await expect(page.locator('.ai-message--assistant:not(.ai-message--streaming)')).toHaveCount(3); expect(facts(await get(page.request, '/api/learning/state'))).toEqual(before);
});

test('refresh reconnects a coach answer, cancellation and retry reuse the same conversation', async ({ page }) => {
  await authorize(page); await configure(page, 'mock-slow'); await openCoach(page, undefined, true);
  const id = await currentId(page), before = facts(await get(page.request, '/api/learning/state'));
  await page.getByLabel('和教练说说今天', { exact: true }).fill('先看看怎样重新开始'); await page.getByRole('button', { name: '发送', exact: true }).click(); await expect(page.getByRole('button', { name: '取消生成', exact: true })).toBeVisible();
  await page.reload(); await expect(page.getByRole('button', { name: '取消生成', exact: true })).toBeVisible(); expect(await currentId(page)).toBe(id); await page.getByRole('button', { name: '取消生成', exact: true }).click(); await expect(page.locator('.ai-message--canceled')).not.toHaveCount(0);
  await configure(page); await page.reload(); await expect(page.getByRole('button', { name: '重新生成', exact: true }).first()).toBeEnabled(); await page.getByRole('button', { name: '重新生成', exact: true }).first().click(); await expect(page.locator('.ai-message--assistant:not(.ai-message--streaming):not(.ai-message--canceled):not(.ai-message--failed)')).not.toHaveCount(0);
  expect(await currentId(page)).toBe(id); expect(facts(await get(page.request, '/api/learning/state'))).toEqual(before);
});

test('an action resolved after history switching cannot navigate the new conversation', async ({ page }) => {
  await authorize(page); await configure(page); await seed(page.request); await openCoach(page, '今天从哪里开始？', true); await expect(page.locator('.ai-message--assistant:not(.ai-message--streaming)')).not.toHaveCount(0);
  const other = await post(page.request, '/api/learning/coach/conversations', { request_key: key('other'), new_conversation: true }); await page.reload();
  let release!: () => void; const waiting = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/learning/coach/conversations/*/actions/*/resolve', async route => { const response = await route.fetch(); await waiting; await route.fulfill({ response }); });
  await page.getByRole('button', { name: '继续：合成教练任务', exact: true }).first().click(); await page.getByRole('button', { name: '对话历史', exact: true }).click(); await page.locator(`[data-conversation-id="${other.conversation.id}"] .ai-history-select`).click(); await expect.poll(() => currentId(page)).toBe(other.conversation.id); release();
  await page.waitForTimeout(150); await expect(page.getByRole('heading', { name: '学习教练', exact: true, level: 1 })).toBeVisible(); expect(await currentId(page)).toBe(other.conversation.id); await expect(page).not.toHaveURL(/view=plans/);
});

test('many current tasks stay behind three compact entries until the learner expands them', async ({ page }) => {
  await authorize(page); await configure(page); for (let index = 0; index < 5; index++) await seed(page.request); await openCoach(page, undefined, true);
  const id = await currentId(page), detail = await get(page.request, `/api/learning/coach/conversations/${id}`); expect(detail.coach_context.actions.length).toBeGreaterThan(3);
  const entrances = page.getByLabel('当前可用入口', { exact: true }); await expect(entrances.locator('div > button')).toHaveCount(3); await expect(entrances.getByRole('button', { name: /^更多入口/ })).toBeVisible();
  await screenshots(page, 'current-entries'); await entrances.getByRole('button', { name: /^更多入口/ }).click(); await expect(entrances.locator('div > button')).toHaveCount(detail.coach_context.actions.length); await entrances.getByRole('button', { name: '收起入口', exact: true }).click(); await expect(entrances.locator('div > button')).toHaveCount(3);
});

test('all reminder times are editable and browser permission is requested only by its button', async ({ page }) => {
  await page.addInitScript(() => { let permission: NotificationPermission = 'default'; (window as any).__notificationRequests = 0; class SyntheticNotification { static get permission() { return permission; } static async requestPermission() { (window as any).__notificationRequests++; permission = 'granted'; return permission; } constructor() {} close() {} } Object.defineProperty(window, 'Notification', { configurable: true, value: SyntheticNotification }); });
  await authorize(page); await page.getByRole('button', { name: '设置', exact: true }).click(); const settings = page.getByRole('region', { name: '学习提醒设置', exact: true }); await expect(settings.getByRole('checkbox', { name: '开启学习提醒', exact: true })).toBeVisible(); expect(await page.evaluate(() => (window as any).__notificationRequests)).toBe(0);
  await settings.getByRole('button', { name: '添加学习时间', exact: true }).click(); await settings.getByLabel('学习时间 1', { exact: true }).fill('18:45'); await settings.getByRole('checkbox', { name: '开启学习提醒', exact: true }).check(); await settings.getByText('提醒频率与免打扰', { exact: true }).click(); await settings.getByLabel('追加间隔（分钟）', { exact: true }).fill('47'); await settings.getByLabel('每天最多提醒（次）', { exact: true }).fill('4'); await settings.getByLabel('免打扰开始', { exact: true }).fill('23:15'); await settings.getByLabel('免打扰结束', { exact: true }).fill('07:30'); await settings.getByLabel('提醒时区', { exact: true }).fill('Asia/Shanghai');
  await settings.getByRole('checkbox', { name: '同时使用浏览器通知', exact: true }).check(); expect(await page.evaluate(() => (window as any).__notificationRequests)).toBe(0); await settings.getByRole('button', { name: '授权浏览器通知', exact: true }).click(); expect(await page.evaluate(() => (window as any).__notificationRequests)).toBe(1); await settings.getByRole('button', { name: '保存提醒设置', exact: true }).click(); await expect(settings).toContainText('学习提醒已保存。');
  const saved = await get(page.request, '/api/learning/coach/reminders/settings'); expect(saved).toMatchObject({ enabled: true, browser_enabled: true, timezone: 'Asia/Shanghai', followup_delay_minutes: 47, max_per_day: 4, quiet_start: '23:15', quiet_end: '07:30', study_times: [{ time: '18:45', weekdays: [1, 2, 3, 4, 5, 6, 7] }] });
  await settings.getByRole('checkbox', { name: '未开始时追加一次', exact: true }).uncheck(); await settings.getByRole('checkbox', { name: '免打扰', exact: true }).uncheck(); await settings.getByRole('checkbox', { name: '开启学习提醒', exact: true }).uncheck(); await settings.getByRole('button', { name: '保存提醒设置', exact: true }).click(); expect(await get(page.request, '/api/learning/coach/reminders/settings')).toMatchObject({ enabled: false, followup_enabled: false, quiet_enabled: false });
});

test('LAN capability fallback keeps app reminders available and never asks browser permission', async ({ page }) => {
  await page.addInitScript(() => { Object.defineProperty(window, 'isSecureContext', { configurable: true, value: false }); (window as any).__notificationRequests = 0; Object.defineProperty(window, 'Notification', { value: class { static permission = 'default'; static async requestPermission() { (window as any).__notificationRequests++; return 'granted'; } } }); });
  await authorize(page); await page.getByRole('button', { name: '设置', exact: true }).click(); const settings = page.getByRole('region', { name: '学习提醒设置', exact: true }); await expect(settings).toContainText('当前地址或浏览器不支持系统通知'); await expect(settings.getByRole('button', { name: '授权浏览器通知', exact: true })).toHaveCount(0); await expect(settings.getByRole('checkbox', { name: '同时使用浏览器通知', exact: true })).toBeDisabled(); expect(await page.evaluate(() => (window as any).__notificationRequests)).toBe(0);
});

test('only a newly claimed reminder creates a browser notification, and invalidated prompts are removed', async ({ page }) => {
  await page.addInitScript(() => { (window as any).__notifications = []; (window as any).__closedNotifications = 0; class SyntheticNotification { static permission = 'granted'; onclick: (() => void) | null = null; onclose: (() => void) | null = null; constructor(title: string) { if ((window as any).__rejectNotification) throw new Error('Synthetic unsupported Notification constructor'); (window as any).__notifications.push(title); } close() { (window as any).__closedNotifications++; this.onclose?.(); } } Object.defineProperty(window, 'Notification', { configurable: true, value: SyntheticNotification }); });
  let claimed = false, invalid = false;
  const settings: CoachReminderSettings = { revision: 1, enabled: true, timezone: 'UTC', browser_enabled: true, study_times: [], followup_enabled: true, followup_delay_minutes: 30, max_per_day: 2, quiet_enabled: false, quiet_start: '22:00', quiet_end: '08:00' };
  const item = { id: 'synthetic-browser-reminder', revision: 1, occurrence_key: 'synthetic-occurrence', stage: 'initial' as const, status: 'pending' as const, title: '合成浏览器提醒', body: '当前安排还未开始。', target: { kind: 'commitment_review' as const, plan_id: null, action_id: null, delegation_id: null, item_id: null, href: '?view=plans', label: '查看安排' }, scheduled_at: new Date().toISOString(), dispatched_at: null, source_revision: 'synthetic-revision', reason: null };
  const view = (): CoachReminderView => ({ settings, due: claimed || invalid ? [] : [item], recent: claimed ? [{ ...item, status: invalid ? 'unavailable' : 'dispatched', dispatched_at: new Date().toISOString() }] : [], learning_active: false, quiet_now: false, budget: { used_today: claimed ? 1 : 0, remaining_today: claimed ? 1 : 2, local_date: '2026-10-07' }, next_due_at: null, revision: String(claimed) + String(invalid) });
  await page.route('**/api/learning/coach/reminders', route => route.fulfill({ json: view() }));
  await page.route('**/api/learning/coach/reminders/*/dispatch', route => { const fresh = !claimed; claimed = true; return route.fulfill({ json: { reminder: { ...item, status: 'dispatched', dispatched_at: new Date().toISOString() }, claimed: fresh, reason: null, view: view() } }); });
  await authorize(page); const reminder = page.getByRole('complementary', { name: '学习提醒', exact: true }); await expect(reminder).toContainText('合成浏览器提醒'); expect(await page.evaluate(() => (window as any).__notifications)).toEqual(['合成浏览器提醒']);
  await page.getByRole('button', { name: '学习计划', exact: true }).first().click(); await expect(reminder).toContainText('合成浏览器提醒'); await page.evaluate(() => window.dispatchEvent(new Event('nautilus:learning-state-changed'))); expect(await page.evaluate(() => (window as any).__notifications.length)).toBe(1);
  invalid = true; await page.evaluate(() => window.dispatchEvent(new Event('nautilus:learning-state-changed'))); await expect(reminder).toHaveCount(0); expect(await page.evaluate(() => (window as any).__closedNotifications)).toBeGreaterThan(0);
  invalid = false; await page.reload(); await expect(page.getByRole('button', { name: '退出会话' })).toBeVisible(); await expect(reminder).toHaveCount(0); expect(await page.evaluate(() => (window as any).__notifications.length)).toBe(0);
  item.id = 'synthetic-browser-reminder-throw'; item.occurrence_key = 'synthetic-occurrence-throw'; claimed = false; await page.evaluate(() => { (window as any).__rejectNotification = true; window.dispatchEvent(new Event('nautilus:learning-state-changed')); }); await expect(reminder).toContainText('浏览器通知未能显示，应用内提醒仍可用。'); await expect(reminder).toContainText('合成浏览器提醒');
});

test('coach content purge shows its real impact and preserves learning facts', async ({ page }) => {
  await authorize(page); await configure(page); await openCoach(page, '清除检查：只在这个合成教练对话里说明今天精力。', true);
  await expect(page.locator('.ai-message--assistant:not(.ai-message--streaming)')).not.toHaveCount(0); const id = await currentId(page), before = facts(await get(page.request, '/api/learning/state'));
  await page.getByRole('button', { name: '对话历史', exact: true }).click(); await page.locator('.ai-history-item.is-current').getByRole('button', { name: /^清除教练内容：/ }).click();
  const dialog = page.getByRole('dialog', { name: /^清除.*的内容/ }); await expect(dialog).toContainText('条消息'); await expect(dialog.getByRole('button', { name: '确认清除内容', exact: true })).toBeEnabled(); await dialog.getByRole('button', { name: '确认清除内容', exact: true }).click(); await expect(dialog).toContainText('教练内容已清除。');
  await dialog.getByRole('button', { name: '关闭', exact: true }).click(); await expect(page.locator('.ai-message')).toHaveCount(0); expect(facts(await get(page.request, '/api/learning/state'))).toEqual(before); expect((await get(page.request, `/api/learning/coach/conversations/${id}/purge`)).purge_report.status).toBe('complete');
});

test('real schedule dispatch survives navigation and retracts after the learner starts, without claiming completion', async ({ page }) => {
  await authorize(page); const due = new Date(Date.now() - 60_000).toISOString(), plan = await seed(page.request, due);
  const settings = await get(page.request, '/api/learning/coach/reminders/settings') as CoachReminderSettings; const { revision, ...fields } = settings;
  const saved = await page.request.put('/api/learning/coach/reminders/settings', { data: { ...fields, enabled: true, browser_enabled: false, study_times: [], timezone: 'UTC', quiet_enabled: false, followup_enabled: false, max_per_day: 100, expected_revision: revision, request_key: key('reminders') } }); expect(saved.ok(), await saved.text()).toBeTruthy();
  const before = facts(await get(page.request, '/api/learning/state')); await page.goto('/?view=home'); const reminder = page.getByRole('complementary', { name: '学习提醒', exact: true }); await expect(reminder).toContainText('合成教练任务'); expect(facts(await get(page.request, '/api/learning/state'))).toEqual(before);
  const current = await get(page.request, '/api/learning/coach/reminders') as CoachReminderView; expect(current.recent.some(item => item.status === 'dispatched')).toBeTruthy(); const claimed = current.recent.find(item => item.status === 'dispatched')!;
  const replay = await post(page.request, `/api/learning/coach/reminders/${claimed.id}/dispatch`, { expected_revision: claimed.revision, request_key: key('replay') }); expect(replay.claimed).toBe(false);
  await page.getByRole('button', { name: '学习计划', exact: true }).first().click(); await expect(reminder).toContainText('合成教练任务'); await reminder.getByRole('button', { name: claimed.target.label, exact: true }).click();
  const state = await get(page.request, '/api/learning/state'), view = await get(page.request, `/api/learning/plans/${plan.id}/commitments`);
  await post(page.request, `/api/learning/plans/${plan.id}/commitments/items/${plan.item.id}/start`, { expected_action_version: state.actions.find((item: any) => item.id === plan.task.action_id).version, expected_revision: view.revision, use_checkpoint: false, request_key: key('start') });
  await page.evaluate(() => window.dispatchEvent(new Event('nautilus:learning-state-changed'))); await expect(reminder).toHaveCount(0); const after = await get(page.request, '/api/learning/state'); expect(after.sessions.some((item: any) => item.action_id === plan.task.action_id && item.status === 'running')).toBeTruthy(); expect(after.actions.find((item: any) => item.id === plan.task.action_id).status).toBe('open');
  await page.reload(); await expect(reminder).toHaveCount(0);
  await page.getByRole('button', { name: '设置', exact: true }).click(); const history = page.getByRole('region', { name: '学习提醒设置', exact: true }); await history.getByText('提醒记录', { exact: true }).click(); await expect(history.locator('.coach-reminder-settings__history')).not.toHaveCount(0); expect(await history.locator('.coach-reminder-settings__history').count()).toBeLessThanOrEqual(5); await expect(history.locator('.coach-reminder-settings__history').getByRole('button').first()).toBeDisabled();
  const running = after.sessions.find((item: any) => item.action_id === plan.task.action_id && item.status === 'running'); await post(page.request, `/api/learning/sessions/${running.id}/end`, { disposition: 'interrupted', expected_version: after.actions.find((item: any) => item.id === plan.task.action_id).version, idempotency_key: key('fixture-stop') });
});
