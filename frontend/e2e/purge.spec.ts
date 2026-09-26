import { expect, test } from '@playwright/test';
import { chmodSync, mkdirSync, readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { join, resolve } from 'node:path';
import { authorize } from './fact-helpers';

test('purge: real backup failure, retry, reload and preserved completion fact', async ({ page }) => {
  await authorize(page);
  const setup = await page.request.post('/api/learning/setup/confirm', { data: {
    original_intent: '合成清除旅程', goal_title: '合成清除旅程', plan_title: '合成清除旅程', action_title: '合成清除旅程',
    context_key: 'purge', object_description: '合成作品', behavior: '解释一个例子',
    outcome_context_key: 'purge', stop_conditions: '保存合成作品', idempotency_key: 'purge-browser',
  }});
  expect(setup.ok()).toBeTruthy();
  const context = await setup.json();
  await page.goto(`/?view=records&record=${context.delegation_id}`);
  const completion = page.getByRole('region', { name: '本次执行完成记录' });
  await completion.getByLabel('补充说明（可选）').fill('BROWSER_PRIVATE_PURGE_MARKER');
  await completion.getByRole('button', { name: '记录本次完成', exact: true }).click();
  await expect(completion).toContainText('BROWSER_PRIVATE_PURGE_MARKER');
  const root = process.env.NAUTILUS_E2E_DATA_DIR!;
  const backup = join(root, 'backups', 'synthetic-readonly.sqlite3');
  mkdirSync(join(root, 'backups'), { recursive: true });
  execFileSync(resolve('../.venv/bin/python'), ['-c',
    'import sqlite3,sys; source=sqlite3.connect(sys.argv[1]); target=sqlite3.connect(sys.argv[2]); source.backup(target); target.close(); source.close()',
    join(root, 'learning.sqlite3'), backup]);
  chmodSync(backup, 0o400);
  page.once('dialog', async dialog => {
    expect(dialog.message()).toContain('普通备份');
    await dialog.accept();
  });
  await completion.getByRole('button', { name: '删除完成记录内容' }).click();
  const report = completion.getByLabel('副本清除结果');
  await expect(report).toContainText('仅部分清除');
  await expect(report).toContainText('synthetic-readonly.sqlite3：失败');
  await expect(completion).not.toContainText('BROWSER_PRIVATE_PURGE_MARKER');
  await page.reload();
  await expect(report).toContainText('仅部分清除');
  chmodSync(backup, 0o600);
  await report.getByRole('button', { name: '重试清除剩余副本' }).click();
  await expect(report).toContainText('Nautilus 管理的副本已处理完成。');
  expect(readFileSync(backup).includes(Buffer.from('BROWSER_PRIVATE_PURGE_MARKER'))).toBeFalsy();
  await page.reload();
  await expect(completion).toContainText('已记录完成');
  await expect(report).toContainText('Nautilus 管理的副本已处理完成。');
  await expect(report).toContainText('未确认清除');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: '/tmp/nautilus-purge-preview.png' });
});
