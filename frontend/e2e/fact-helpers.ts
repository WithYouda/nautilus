import { expect, type Page } from "@playwright/test";

export async function authorize(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "填入当前授权码" }).click();
  await page.getByRole("button", { name: "进入工作区" }).click();
  await expect(page.getByRole("button", { name: "退出会话" })).toBeVisible();
}

export async function openFactWorkspace(page: Page) {
  const factButton = page.getByRole("button", { name: "开始学习" }).first();
  if (!(await factButton.isVisible())) {
    await page.getByRole("button", { name: "打开导航" }).click();
  }
  await factButton.click();
  await expect(page.getByRole("heading", { name: "开始学习" })).toBeVisible();
  const closeNavigation = page.getByRole("button", { name: "关闭导航" });
  if (await closeNavigation.isVisible()) await closeNavigation.click();
  const advancedTools = page.locator("details.advanced-facts > summary");
  await expect(advancedTools).toHaveCount(1);
  await advancedTools.click();
}
