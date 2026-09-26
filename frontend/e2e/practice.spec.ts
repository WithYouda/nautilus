import { expect, test, type Page } from '@playwright/test';
import { authorize } from './fact-helpers';

async function provider(page: Page, model = 'mock-success') {
  expect((await page.request.put('/api/ai/provider', { data: {
    display_name: 'Synthetic practice provider', base_url: process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,
    model, api_key: 'synthetic-only', enabled: true, request_timeout_seconds: 15,
  } })).ok()).toBeTruthy();
}

test('practice: disputed feedback, replace, save, failed evaluation retry, help snapshots and deletion', async ({ page }) => {
  await authorize(page); await provider(page);
  const context = await (await page.request.post('/api/learning/setup/confirm', { data: {
    original_intent: '合成补练旅程', goal_title: '合成补练旅程', plan_title: '合成补练旅程', action_title: '合成补练旅程',
    context_key: 'practice', object_description: '合成编号判断', behavior: '解释边界', outcome_context_key: 'practice',
    stop_conditions: '说明自己的判断', idempotency_key: 'practice-browser',
  } })).json();
  const started = await page.request.post('/api/learning/verifications', { data: {
    action_id: context.action_id, delegation_id: context.delegation_id, mode: 'ai_challenge', request_key: 'source',
  } });
  expect(started.ok()).toBeTruthy(); const verification = await started.json();
  const saved = await (await page.request.post(`/api/learning/verifications/${verification.id}/submit`, { data: {
    responses: { q1: '合成原作答：先识别编号，再说明字符边界。' }, evidence_condition: 'independent', request_key: 'source-answer',
  } })).json();
  const evaluated = await page.request.post(`/api/learning/verifications/${verification.id}/evaluate`, { data: { submission_id: saved.latest_submission_id, request_key: 'source-eval' } });
  expect(evaluated.ok()).toBeTruthy();
  const original = await (await page.request.get(`/api/learning/verifications/${verification.id}`)).json();
  await page.goto(`/?view=records&record=${context.delegation_id}&verification=${verification.id}`);
  const question = page.getByRole('article', { name: '第 1 题回看' });
  await question.locator('summary').filter({ hasText: /^针对性补练$/ }).click();
  const panel = question.getByLabel('针对性补练', { exact: true });
  await panel.getByLabel('对原反馈有疑问？先说出要复核的具体判断').fill('合成质疑：请核对原题是否要求额外内容');
  await expect(panel.getByRole('button', { name: '建议一个练习' })).toBeDisabled();
  await panel.getByRole('button', { name: '先复核反馈' }).click();
  await expect(panel.getByLabel('原反馈复核')).toContainText('原反馈需要修正');
  await expect(panel.getByLabel('补练题目')).toHaveCount(0);
  await panel.getByRole('button', { name: '按复核结果出练习' }).click();
  await expect(panel.getByLabel('补练题目')).toContainText('输入只包含一个编号');
  await expect(panel).not.toContainText('SYNTHETIC_PRIVATE_PRACTICE_GUIDANCE');
  await panel.getByRole('button', { name: '换一个', exact: true }).click();
  await expect(panel.getByLabel('补练题目')).toContainText('换为两个编号');
  await panel.getByRole('button', { name: '暂不练', exact: true }).click();
  await panel.getByRole('button', { name: '现在开始', exact: true }).click();
  await panel.getByLabel('我的作答', { exact: true }).fill('合成补练答案一：我先检查边界');
  await panel.getByRole('checkbox').check();
  await panel.getByRole('button', { name: '保存作答', exact: true }).click();
  await provider(page, 'mock-error');
  await panel.getByRole('button', { name: '评估这次作答', exact: true }).click();
  await expect(panel.getByLabel('补练作答版本')).toContainText('合成补练答案一');
  await expect(panel.getByLabel('补练 AI 结果')).toContainText('失败');
  await provider(page);
  await panel.getByRole('button', { name: '评估这次作答（重试）', exact: true }).click();
  await expect(panel.getByLabel('补练 AI 结果')).toContainText('已完成');
  await panel.getByRole('button', { name: '给个提示', exact: true }).click();
  await panel.getByLabel('补练 AI 结果').locator('summary').filter({ hasText: /^提示 · 已完成/ }).click();
  await expect(panel).toContainText('合成补练提示：先单独检查输入边界。');
  await panel.getByLabel('我的作答', { exact: true }).fill('合成补练答案二：分别检查两个编号边界');
  await panel.getByRole('checkbox').check();
  await panel.getByRole('button', { name: '保存作答', exact: true }).click();
  await expect(panel.getByLabel('补练作答版本')).toContainText('同题再试');
  await page.reload();
  await question.locator('summary').filter({ hasText: /^针对性补练$/ }).click();
  await expect(panel.getByLabel('补练作答版本')).toContainText('合成补练答案二');
  const endpoint = `/api/learning/verifications/${verification.id}/practices?submission_id=${saved.latest_submission_id}&evaluation_id=${original.selected_evaluation_id}&question_id=q1`;
  const practices = await (await page.request.get(endpoint)).json();
  expect(practices[0].attempts[0].condition).toMatchObject({ user_report: 'independent', evidence_condition: 'with_materials' });
  expect(practices[0].attempts[1].condition.records).toEqual([]);
  expect(practices[0].attempts[0].condition.records.some((r: { kind: string; displayed_at: string }) => r.kind === 'hint' && r.displayed_at)).toBeTruthy();
  await page.setViewportSize({ width: 390, height: 844 });
  await panel.getByLabel('补练题目').scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: '/tmp/nautilus-practice-preview.png' });
  await page.getByRole('button', { name: '查看这个成果的依据' }).click();
  const outcome = page.getByLabel('单成果依据回看');
  await expect(outcome.getByLabel('针对性补练记录')).toContainText('合成补练反馈');
  await outcome.getByRole('button', { name: '查看这项补练' }).first().click();
  await expect(outcome.getByLabel('补练详情')).toContainText('合成补练答案二');
  await outcome.getByRole('button', { name: '查看原验证版本' }).click();
  await question.locator('summary').filter({ hasText: /^针对性补练$/ }).click();
  await panel.locator('summary').filter({ hasText: /^删除补练内容$/ }).click();
  page.once('dialog', dialog => dialog.accept());
  await panel.getByRole('button', { name: '彻底删除这项补练' }).click();
  await expect(panel.getByLabel('副本清除结果')).toContainText('Nautilus 管理的副本已处理完成');
  const after = await (await page.request.get(`/api/learning/verifications/${verification.id}`)).json();
  expect(after.content).toEqual(original.content); expect(after.result).toEqual(original.result);
});
