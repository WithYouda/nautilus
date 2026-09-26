import { expect, test } from '@playwright/test';
import { authorize, openFactWorkspace } from './fact-helpers';

test('metrics failure leaves creation available and retry requests only metrics', async ({ page }) => {
  await authorize(page);
  const report = await (await page.request.get('/api/learning/metrics')).json();
  let metricsRequests = 0;
  let stateRequests = 0;
  let reviewRequests = 0;
  await page.route('**/api/learning/return-review', async route => {
    reviewRequests += 1;
    await route.fulfill({ json: null });
  });
  await page.route('**/api/learning/state', async route => {
    stateRequests += 1;
    await route.continue();
  });
  await page.route('**/api/learning/metrics', async route => {
    metricsRequests += 1;
    if (metricsRequests === 1) await route.fulfill({ status: 500, json: { detail: '指标暂不可用' } });
    else await route.fulfill({ json: report });
  });

  await openFactWorkspace(page);
  await expect(page.getByRole('heading', { name: '你想学会什么？' })).toBeVisible();
  await expect(page.getByRole('region', { name: '首片指标' }).getByRole('alert')).toContainText('指标暂时不可用');
  const beforeRetry = { stateRequests, reviewRequests };
  await page.getByRole('button', { name: '重试指标' }).click();
  await expect(page.getByRole('region', { name: '首片指标' }).getByText(report.window)).toBeVisible();
  expect(metricsRequests).toBe(2);
  expect({ stateRequests, reviewRequests }).toEqual(beforeRetry);
});

test('pending and stale metrics responses do not hold or overwrite the learning home', async ({ page }) => {
  await authorize(page);
  const report = await (await page.request.get('/api/learning/metrics')).json();
  let releaseMetrics: (() => void) | undefined;
  const metricsGate = new Promise<void>(resolve => { releaseMetrics = resolve; });
  let metricsRequests = 0;
  await page.route('**/api/learning/metrics', async route => {
    metricsRequests += 1;
    if (metricsRequests === 1) {
      await metricsGate;
      await route.fulfill({ status: 500, json: { detail: '过期的指标响应' } });
    } else {
      await route.fulfill({ json: report });
    }
  });
  await page.route('**/api/learning/return-review', async route => {
    await route.fulfill({ json: null });
  });
  try {
    await openFactWorkspace(page);
    await expect(page.getByRole('heading', { name: '你想学会什么？' })).toBeVisible();
    await expect(page.getByRole('region', { name: '首片指标' }).getByRole('status')).toContainText('正在加载指标');
    await page.getByLabel('学习目标', { exact: true }).fill('合成目标：指标请求仍在等待');
    await expect(page.getByRole('button', { name: '我想自己安排' })).toBeEnabled();
    await page.getByRole('button', { name: '刷新状态' }).click();
    await expect(page.getByRole('region', { name: '首片指标' }).getByText(report.window)).toBeVisible();
    const staleResponse = page.waitForResponse(response => response.url().endsWith('/api/learning/metrics') && response.status() === 500);
    releaseMetrics?.();
    await staleResponse;
    await expect(page.getByRole('region', { name: '首片指标' }).getByRole('alert')).toHaveCount(0);
    expect(metricsRequests).toBe(2);
  } finally {
    releaseMetrics?.();
  }
});

test('return card shows the rule reason beside the action it offers', async ({ page }) => {
  await authorize(page);
  const cases = [
    { status: 'completed', saved: true, session: 'ended', reason: '本次学习已完成，可以在原计划中添加下一步。', action: '添加下一步' },
    { status: 'active', saved: true, session: 'interrupted', reason: '作答已保存，继续查看或重试本次验证。', action: '继续验证' },
    { status: 'active', saved: false, session: 'interrupted', reason: '你上次在这里中断，继续原来的任务可以保留学习上下文。', action: '继续学习' },
  ];
  let current = cases[0];
  await page.route('**/api/learning/return-review', async route => {
    await route.fulfill({ json: {
      id: `synthetic-${current.status}-${current.saved}-${current.session}`,
      position: { goal: '合成目标', plan: '合成计划', plan_id: 'synthetic-plan', action: '合成任务', action_id: 'synthetic-action', delegation_id: 'synthetic-delegation', last_session: null, last_activity_at: null },
      what_happened: { summary: '', action_status: 'open', delegation_status: current.status, verification_status: null, verification_id: null, has_saved_answer: current.saved, session_status: current.session },
      supported: [], unknowns: [], evidence_details: [], alternatives: [], choices: [],
      recommendation: { kind: current.status === 'completed' ? 'choose_next' : current.saved ? 'supplemental_verification' : 'resume', action_id: null, delegation_id: null, label: '', reason_code: '', explanation: current.reason, verification_id: null },
    } });
  });
  for (const item of cases) {
    current = item;
    await page.goto('/?view=facts');
    const card = page.getByRole('region', { name: '当前学习' });
    await expect(card.getByText(item.reason)).toBeVisible();
    await expect(card.getByRole('button', { name: item.action, exact: true })).toBeVisible();
  }
});
