import { expect, type Locator, type Page } from '@playwright/test';

export async function openAnswerSources(page: Page, entry: Locator) {
  await entry.getByRole('button', { name: '更多回答操作', exact: true }).click();
  await page.getByRole('menuitem', { name: '回答资料范围', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '回答资料范围', exact: true });
  await expect(dialog).toBeVisible();
  return dialog;
}
