import { expect, test, type Page } from '@playwright/test';
import { authorize } from './fact-helpers';

async function searchSettings(page: Page) {
  await page.getByRole('button', { name: '设置', exact: true }).click();
  await page.getByRole('dialog', { name: '设置', exact: true }).getByRole('button', { name: '管理搜索服务与高级设置' }).click();
  const dialog = page.getByRole('dialog', { name: '联网搜索设置', exact: true });
  await expect(dialog.getByRole('button', { name: '新增', exact: true })).toBeEnabled();
  return dialog;
}

test('external and knowledge budgets exceed former caps and persist on mobile', async ({ page }) => {
  await authorize(page);
  const dialog = await searchSettings(page);
  await dialog.getByLabel('每轮外部检索次数', { exact: true }).fill('12');
  await dialog.getByLabel('每轮知识库读取次数', { exact: true }).fill('9');
  await expect(dialog.getByLabel('每轮外部检索次数', { exact: true })).not.toHaveAttribute('max');
  await dialog.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(dialog).toBeHidden();
  await page.reload();
  const reopened = await searchSettings(page);
  await expect(reopened.getByLabel('每轮外部检索次数', { exact: true })).toHaveValue('12');
  await expect(reopened.getByLabel('每轮知识库读取次数', { exact: true })).toHaveValue('9');
  await page.setViewportSize({ width: 390, height: 900 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: '/tmp/nautilus-limits-settings-390.png', fullPage: true });
});
