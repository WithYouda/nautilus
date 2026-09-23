import { expect, test, type Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "填入当前授权码" }).click();
  await page.getByRole("button", { name: "进入工作区" }).click();
});

test("V6 desktop shell supports collapse, bounded resize, and real navigation", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect(page.getByRole("navigation", { name: "工作区视图" })).toBeVisible();
  const companion = page.getByRole("complementary", { name: "AI 学习伙伴" });
  await expect(companion).toBeHidden();
  const collapsed = await layoutMetrics(page);
  expect(collapsed.companion).toBe(0);
  await page.getByRole("button", { name: "打开 AI 学习伙伴" }).click();
  await expect(companion).toBeVisible();
  expect((await layoutMetrics(page)).main).toBeLessThan(collapsed.main);
  await page.getByRole("button", { name: "收起 AI 学习伙伴" }).click();
  await expect(companion).toBeHidden();
  await page.getByRole("button", { name: "打开 AI 学习伙伴" }).click();
  await expect(page.getByRole("navigation", { name: "当前视角" })).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "工作区视图" }).getByRole("button")).toHaveCount(3);
  await expect(page.getByRole("button", { name: "知识库（开发中）" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /新建计划/ })).toHaveCount(0);
  const initial = await layoutMetrics(page);
  expect(initial.rail).toBeGreaterThanOrEqual(144);
  expect(initial.companion).toBeGreaterThanOrEqual(260);

  await page.getByRole("button", { name: "收起导航" }).click();
  await expect(page.getByRole("button", { name: "展开导航" })).toBeVisible();
  expect((await layoutMetrics(page)).rail).toBeLessThanOrEqual(60);

  await page.getByRole("button", { name: "展开导航" }).click();
  const separator = page.getByRole("separator", { name: "调整 AI 伙伴栏宽度" });
  const box = await separator.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + 120);
  await page.mouse.down();
  await page.mouse.move(box!.x - 300, box!.y + 120);
  await page.mouse.up();
  const resized = await layoutMetrics(page);
  expect(resized.companion).toBeLessThanOrEqual(421);
  expect(resized.main).toBeGreaterThan(500);

  await page.getByRole("button", { name: "学习计划", exact: true }).click();
  await expect(page.getByRole("heading", { name: "学习计划" })).toBeVisible();
  await page.getByRole("button", { name: "学习记录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "学习记录" })).toBeVisible();
});

test("desktop rails stay fixed while only the main column scrolls", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 760 });
  await page.getByRole("button", { name: "打开 AI 学习伙伴" }).click();
  await page.locator(".learning-page").evaluate((element) => {
    (element as HTMLElement).style.minHeight = "1800px";
  });

  const before = await fixedShellMetrics(page);
  await page.locator(".v6-main-column").evaluate((element) => element.scrollTo({ top: 900 }));
  await expect.poll(async () => page.locator(".v6-main-column").evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  const after = await fixedShellMetrics(page);

  expect(before.workspaceHeight).toBe(760);
  expect(before.railTop).toBe(after.railTop);
  expect(before.railBottom).toBe(after.railBottom);
  expect(before.companionTop).toBe(after.companionTop);
  expect(before.companionBottom).toBe(after.companionBottom);
  expect(after.windowScrollY).toBe(0);
  expect(after.documentHeight).toBeLessThanOrEqual(after.viewportHeight);
});

test("V6 mobile shell has no page overflow and exposes the navigation drawer", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight)).toBeTruthy();
  const mobileShell = await page.evaluate(() => {
    const workspace = document.querySelector(".v6-workspace")!.getBoundingClientRect();
    const main = document.querySelector(".v6-main-column")!.getBoundingClientRect();
    return {
      workspaceHeight: workspace.height,
      mainHeight: main.height,
      viewportHeight: window.innerHeight,
      mainOverflowY: getComputedStyle(document.querySelector(".v6-main-column")!).overflowY,
    };
  });
  expect(mobileShell.workspaceHeight).toBe(mobileShell.viewportHeight);
  expect(mobileShell.mainHeight).toBe(mobileShell.viewportHeight);
  expect(mobileShell.mainOverflowY).toBe("auto");

  const toggle = page.getByRole("button", { name: "打开导航" });
  await expect(toggle).toBeVisible();
  await toggle.click();
  await expect(page.getByRole("navigation", { name: "工作区视图" }).getByRole("button", { name: "学习首页" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

async function fixedShellMetrics(page: Page) {
  return page.evaluate(() => {
    const workspace = document.querySelector(".v6-workspace")!.getBoundingClientRect();
    const rail = document.querySelector(".v6-rail")!.getBoundingClientRect();
    const companion = document.querySelector(".v6-companion")!.getBoundingClientRect();
    return {
      workspaceHeight: workspace.height,
      railTop: rail.top,
      railBottom: rail.bottom,
      companionTop: companion.top,
      companionBottom: companion.bottom,
      windowScrollY: window.scrollY,
      documentHeight: document.documentElement.scrollHeight,
      viewportHeight: window.innerHeight,
    };
  });
}

async function layoutMetrics(page: Page) {
  return page.evaluate(() => {
    const rail = document.querySelector(".v6-rail")!.getBoundingClientRect();
    const main = document.querySelector(".v6-main-column")!.getBoundingClientRect();
    const companion = document.querySelector(".v6-companion")!.getBoundingClientRect();
    return { rail: rail.width, main: main.width, companion: companion.width };
  });
}
