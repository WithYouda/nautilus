import { expect, test, type Page } from '@playwright/test';
import { authorize } from './fact-helpers';

async function setup(page: Page, title: string) {
  const response = await page.request.post('/api/learning/setup/confirm', { data: {
    original_intent: '合成完成流程', goal_title: title, plan_title: title, action_title: title,
    context_key: 'completion', object_description: '合成作品', behavior: '解释一个例子',
    outcome_context_key: 'completion', stop_conditions: '写下本次学习结果', idempotency_key: title,
  }});
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function provider(page: Page, model: string) {
  const response = await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic completion provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model, api_key: 'synthetic-test-only', enabled: true, request_timeout_seconds: 15,
  }});
  expect(response.ok()).toBeTruthy();
}

test('completion: no Provider, three report kinds, optional review and original records', async ({ page }) => {
  await authorize(page);
  const first = await setup(page, '合成未验证完成');
  await page.goto(`/?view=plans&plan=${first.plan_id}`);
  await page.getByRole('region', { name: '计划详情' }).getByRole('button', { name: '开始学习', exact: true }).click();
  await expect(page.getByRole('region', { name: '本次学习安排' })).toContainText('合成未验证完成');
  await page.getByRole('button', { name: '记录本次完成', exact: true }).click();
  const completion = page.getByRole('region', { name: '本次执行完成记录' });
  await completion.getByLabel('补充说明（可选）').fill('合成说明：今天的任务做完了，尚未验证');
  await completion.getByRole('button', { name: '记录本次完成', exact: true }).click();
  await page.getByRole('button', { name: '学习首页', exact: true }).click();
  await expect(page.getByRole('region', { name: '当前学习' })).toContainText('未经过验证');
  await page.getByRole('region', { name: '当前学习' }).getByRole('button', { name: '查看记录', exact: true }).click();
  await expect(completion).toContainText('合成说明：今天的任务做完了，尚未验证');
  await page.reload();
  await expect(completion).toContainText('未经过验证');

  const external = await setup(page, '合成无材料考试');
  await page.goto(`/?view=records&record=${external.delegation_id}`);
  await completion.getByLabel('实际验证情况').selectOption('external_report');
  await completion.getByLabel('原验证方式').fill('合成线下考试');
  await completion.getByLabel('用户报告的验证结果').fill('未通过，分数待通知');
  await completion.getByRole('button', { name: '记录本次完成', exact: true }).click();
  await expect(completion).toContainText('未附材料');
  await expect(completion).toContainText('未通过，分数待通知');
  await expect(completion).toContainText('平台未核验');
  await expect(completion.getByRole('button', { name: /请 AI 审查/ })).toHaveCount(0);

  const material = await setup(page, '合成附材料完成');
  await page.goto(`/?view=records&record=${material.delegation_id}`);
  await completion.getByLabel('实际验证情况').selectOption('external_material');
  await completion.getByLabel('原验证方式').fill('合成教师批改');
  await completion.getByLabel('用户报告的验证结果').fill('部分通过，仍有错误');
  await completion.getByLabel('材料名称').fill('合成批改文字');
  await completion.getByLabel('材料文字').fill('合成评分：60分。缺少原题和评分表。');
  await completion.getByRole('button', { name: '记录本次完成', exact: true }).click();
  await expect(completion).toContainText('部分通过，仍有错误');
  await expect(completion.getByText(/AI 材料审查 ·/)).toHaveCount(0);
  await provider(page, 'mock-error');
  await completion.getByRole('button', { name: /请 AI 审查/ }).click();
  await expect(completion).toContainText('AI 材料审查 · 失败');
  await expect(completion).toContainText('已记录完成');
  await provider(page, 'mock-success');
  await completion.getByRole('button', { name: /请 AI 审查/ }).click();
  await expect(completion).toContainText('AI 材料审查 · 已完成');
  await expect(completion).toContainText('没有题目和评分依据，无法判断具体能力。');
  await completion.getByLabel('回应这次审查').fill('合成回应：保留原评分，稍后再补题目');
  await completion.getByRole('button', { name: '保存回应' }).click();
  await page.reload();
  await expect(completion).toContainText('合成回应：保留原评分，稍后再补题目');
  await expect(completion).toContainText('部分通过，仍有错误');
  await page.getByRole('button', { name: '查看这个成果的依据' }).click();
  const outcome = page.getByRole('region', { name: '单成果依据回看' });
  await expect(outcome).toContainText('用户报告非 AI 验证');
  await outcome.getByRole('button', { name: '查看原委托记录' }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await completion.getByRole('heading', { name: '本次执行完成', exact: true }).scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: '/tmp/nautilus-completion-preview.png' });
  page.once('dialog', dialog => dialog.accept());
  await completion.getByRole('button', { name: '删除完成记录内容' }).click();
  await expect(completion).toContainText('曾附材料，内容已删除');
  await expect(completion).not.toContainText('部分通过，仍有错误');
  await page.reload();
  await expect(completion).not.toContainText('合成回应');
  await expect(completion).toContainText('已记录完成');
});
