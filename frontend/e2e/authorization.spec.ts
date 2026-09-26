import { expect, test } from "@playwright/test";
import { localAuthorizationCode } from "./fact-helpers";

test("first authorization requires a code read on the service host", async ({ page, request }) => {
  const missingChallenge = await request.get("/api/auth/challenge");
  expect(missingChallenge.status()).toBe(404);

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "授权此设备，继续学习。" })).toBeVisible();
  await expect(page.getByRole("button", { name: "填入当前授权码" })).toHaveCount(0);
  await expect(page.getByLabel("授权二维码")).toHaveCount(0);
  await page.getByLabel("授权码", { exact: true }).fill("incorrect-code");
  await page.getByRole("button", { name: "进入工作区" }).click();
  await expect(page.getByRole("alert")).toContainText("访问令牌无效或已过期");

  await page.getByLabel("授权码", { exact: true }).fill(localAuthorizationCode());
  await page.getByRole("button", { name: "进入工作区" }).click();
  await expect(page.getByRole("button", { name: "退出会话" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "退出会话" })).toBeVisible();
  await page.getByRole("button", { name: "退出会话" }).click();
  await expect(page.getByRole("heading", { name: "授权此设备，继续学习。" })).toBeVisible();
});
