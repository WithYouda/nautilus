import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, type Page } from "@playwright/test";
import type { AiProvider } from '../src/api';

export function localAuthorizationCode(): string {
  const dataDir = process.env.NAUTILUS_E2E_DATA_DIR;
  if (!dataDir) throw new Error("E2E 隔离数据目录未配置");
  return readFileSync(join(dataDir, "runtime", "access-token"), "utf8");
}

export async function authorize(page: Page) {
  await page.goto("/");
  await page.getByLabel("授权码", { exact: true }).fill(localAuthorizationCode());
  await page.getByRole("button", { name: "进入工作区" }).click();
  await expect(page.getByRole("button", { name: "退出会话" })).toBeVisible();
}

export async function checkDefaultTeachingSupport(page: Page) {
  const response = await page.request.get('/api/ai/provider');
  expect(response.ok()).toBeTruthy();
  const { provider } = await response.json() as { provider: AiProvider };
  const modelId = provider.default_model_id ?? provider.default_model?.id;
  expect(modelId).toBeTruthy();
  const check = await page.request.post(`/api/ai/providers/${provider.id}/models/${modelId}/teaching-support/check`);
  expect(check.ok()).toBeTruthy();
  expect((await check.json()).support).toMatchObject({ plain: 'supported', tools: 'supported' });
}

export async function openFactWorkspace(page: Page) {
  const factButton = page.getByRole("button", { name: "学习首页" }).first();
  if (!(await factButton.isVisible())) {
    await page.getByRole("button", { name: "打开导航" }).click();
  }
  await factButton.click();
  await expect(page.getByRole("heading", { name: "学习首页" })).toBeVisible();
  const closeNavigation = page.getByRole("button", { name: "关闭导航" });
  if (await closeNavigation.isVisible()) await closeNavigation.click();
  const advancedTools = page.locator("details.advanced-facts > summary");
  await expect(advancedTools).toHaveCount(1);
  await advancedTools.click();
}
