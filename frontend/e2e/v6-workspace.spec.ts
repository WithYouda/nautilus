import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "填入当前授权码" }).click();
  await page.getByRole("button", { name: "进入工作区" }).click();
});

test("V6 desktop shell supports collapse, bounded resize, and real navigation", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect(page.getByRole("navigation", { name: "工作区视图" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "AI 学习伙伴" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "当前视角" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "工作区视图" }).getByRole("button")).toHaveCount(2);
  await expect(page.getByRole("button", { name: "知识库（开发中）" })).toBeDisabled();
  const hierarchy = await page.evaluate(() => {
    const header = document.querySelector(".app-header")!.getBoundingClientRect();
    const perspective = document.querySelector(".workspace-perspective-bar")!.getBoundingClientRect();
    return { headerBottom: header.bottom, perspectiveTop: perspective.top };
  });
  expect(hierarchy.perspectiveTop).toBeGreaterThanOrEqual(hierarchy.headerBottom);

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

  await page.getByRole("button", { name: "任务", exact: true }).click();
  await expect(page.getByRole("heading", { name: "独立任务列表" })).toBeVisible();
  await page.getByRole("button", { name: "日历", exact: true }).click();
  await expect(page.getByRole("heading", { name: "月历视图" })).toBeVisible();
});

test("new plan dialog is mounted to the viewport on desktop and mobile", async ({ page }) => {
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.reload();
    await page.getByRole("button", { name: /新建计划/ }).click();

    const dialog = page.getByRole("dialog", { name: "建立一条可执行学习路线" });
    await expect(dialog).toBeVisible();
    const metrics = await page.evaluate(() => {
      const backdrop = document.querySelector(".dialog-backdrop")!;
      const dialogElement = document.querySelector(".plan-dialog")!;
      const backdropRect = backdrop.getBoundingClientRect();
      const dialogRect = dialogElement.getBoundingClientRect();
      return {
        backdropPosition: getComputedStyle(backdrop).position,
        backdropParent: backdrop.parentElement?.tagName,
        backdropRect: { top: backdropRect.top, left: backdropRect.left, right: backdropRect.right, bottom: backdropRect.bottom },
        dialogRect: { top: dialogRect.top, left: dialogRect.left, right: dialogRect.right, bottom: dialogRect.bottom },
        viewport: { width: window.innerWidth, height: window.innerHeight },
      };
    });
    expect(metrics.backdropPosition).toBe("fixed");
    expect(metrics.backdropParent).toBe("BODY");
    expect(metrics.backdropRect).toEqual({ top: 0, left: 0, right: viewport.width, bottom: viewport.height });
    expect(metrics.dialogRect.top).toBeGreaterThanOrEqual(0);
    expect(metrics.dialogRect.top).toBeLessThan(viewport.height);
    expect(metrics.dialogRect.left).toBeGreaterThanOrEqual(0);
    expect(metrics.dialogRect.right).toBeLessThanOrEqual(viewport.width);

    await page.getByRole("button", { name: "关闭" }).click();
  }
});

test("V6 active timer stays inside the main column", async ({ page }) => {
  const task = await createTask(page.request, "V6 悬浮计时");
  await page.reload();
  await page.getByRole("button", { name: `选择任务：${task.title}` }).click();

  const started = await page.request.post(`/api/tasks/${task.id}/timer`, {
    data: { action: "start", timer_mode: "pomodoro_25_5", work_minutes: 25, break_minutes: 5 },
  });
  expect(started.ok()).toBeTruthy();
  await page.evaluate(() => {
    localStorage.setItem("nautilus.v6.timer-position", JSON.stringify({ x: 2400, y: 3600 }));
  });
  await page.reload();

  const timer = page.getByRole("region", { name: "活动学习计时" });
  await expect(timer).toBeVisible();
  await expectTimerInsideMain(page);
  const initialMetrics = await page.evaluate(() => {
    const timerElement = document.querySelector(".v6-floating-timer")!;
    const stored = JSON.parse(localStorage.getItem("nautilus.v6.timer-position") ?? "null");
    return {
      position: getComputedStyle(timerElement).position,
      parent: timerElement.parentElement?.tagName,
      documentWidth: document.documentElement.scrollWidth,
      documentHeight: document.documentElement.scrollHeight,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      stored,
    };
  });
  expect(initialMetrics.position).toBe("fixed");
  expect(initialMetrics.parent).toBe("BODY");
  expect(initialMetrics.documentWidth).toBeLessThanOrEqual(initialMetrics.viewportWidth);
  expect(initialMetrics.documentHeight).toBeLessThanOrEqual(initialMetrics.viewportHeight);
  expect(initialMetrics.stored).toMatchObject({ version: 2 });
  expect(initialMetrics.stored.x).toBeUndefined();
  expect(initialMetrics.stored.y).toBeUndefined();

  const timerBox = await timer.boundingBox();
  const mainBox = await page.locator(".v6-main-column").boundingBox();
  const dragHandle = timer.getByRole("button", { name: "拖动计时器" });
  const dragBox = await dragHandle.boundingBox();
  expect(timerBox).not.toBeNull();
  expect(mainBox).not.toBeNull();
  expect(dragBox).not.toBeNull();
  await page.mouse.move(dragBox!.x + dragBox!.width / 2, dragBox!.y + dragBox!.height / 2);
  await page.mouse.down();
  await page.mouse.move(mainBox!.x + mainBox!.width - 20, mainBox!.y + mainBox!.height - 20);
  await page.mouse.up();
  await expectTimerInsideMain(page);

  const companionSeparator = page.getByRole("separator", { name: "调整 AI 伙伴栏宽度" });
  const separatorBox = await companionSeparator.boundingBox();
  expect(separatorBox).not.toBeNull();
  await page.mouse.move(separatorBox!.x + separatorBox!.width / 2, separatorBox!.y + 100);
  await page.mouse.down();
  await page.mouse.move(separatorBox!.x - 120, separatorBox!.y + 100);
  await page.mouse.up();
  await expectTimerInsideMain(page);

  await page.setViewportSize({ width: 1024, height: 900 });
  await expectTimerInsideMain(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight)).toBeTruthy();

  await page.getByRole("button", { name: "暂停计时" }).click();
  await expect(page.getByRole("button", { name: "继续计时" })).toBeVisible();
  await timer.getByRole("button", { name: "结束计时" }).click();
  await expect(timer).toBeHidden();
});

test("desktop rails stay fixed while only the main column scrolls", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 760 });
  await page.locator(".workspace-content").evaluate((element) => {
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
  await expect(page.getByRole("navigation", { name: "工作区视图" }).getByRole("button", { name: /学习室/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test("mobile active timer remains visible without covering the AI composer", async ({ page }) => {
  const task = await createTask(page.request, "V6 移动计时条");
  const started = await page.request.post(`/api/tasks/${task.id}/timer`, {
    data: { action: "start", timer_mode: "pomodoro_25_5", work_minutes: 25, break_minutes: 5 },
  });
  expect(started.ok()).toBeTruthy();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  const timer = page.getByRole("region", { name: "活动学习计时" });
  await expect(timer).toBeVisible();
  await page.getByRole("button", { name: `选择任务：${task.title}` }).click();
  await page.getByRole("button", { name: new RegExp(`与 AI 学习.*${task.title}`) }).first().click();
  await expect(page.getByRole("heading", { name: "AI 学习室" })).toBeVisible();

  const metrics = await page.evaluate(() => {
    const timerRect = document.querySelector(".v6-floating-timer")!.getBoundingClientRect();
    const composerRect = document.querySelector(".ai-composer")!.getBoundingClientRect();
    return {
      timerTop: timerRect.top,
      timerBottom: timerRect.bottom,
      composerBottom: composerRect.bottom,
      viewportHeight: window.innerHeight,
      documentHeight: document.documentElement.scrollHeight,
    };
  });
  expect(metrics.timerTop).toBeGreaterThan(metrics.composerBottom + 8);
  expect(metrics.timerBottom).toBeLessThanOrEqual(metrics.viewportHeight);
  expect(metrics.documentHeight).toBeLessThanOrEqual(metrics.viewportHeight);

  await timer.getByRole("button", { name: "结束计时" }).click();
  await expect(timer).toBeHidden();
});

async function expectTimerInsideMain(page: Page) {
  await expect.poll(async () => {
    const timerBox = await page.getByRole("region", { name: "活动学习计时" }).boundingBox();
    const mainBox = await page.locator(".v6-main-column").boundingBox();
    if (!timerBox || !mainBox) return false;
    return timerBox.x >= mainBox.x + 11 &&
      timerBox.x + timerBox.width <= mainBox.x + mainBox.width - 11 &&
      timerBox.y >= mainBox.y + 73 &&
      timerBox.y + timerBox.height <= mainBox.y + mainBox.height - 11;
  }).toBeTruthy();
}

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

async function createTask(request: APIRequestContext, title: string) {
  const now = new Date();
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 30);
  const response = await request.post("/api/plans/manual", {
    data: {
      goal_title: "Playwright V6 验证",
      description: "隔离数据库中的 V6 计时验证",
      start_date: localDateKey(now),
      end_date: localDateKey(end),
      subject_title: "界面验证",
      topic_title: "悬浮计时",
      task_title: title,
      task_type: "study",
      schedule_mode: "flexible",
      task_start_date: localDateKey(now),
      task_due_date: localDateKey(now),
      estimate_minutes: 30,
      timer_mode: "pomodoro_25_5",
      work_minutes: 25,
      break_minutes: 5,
    },
  });
  expect(response.ok()).toBeTruthy();
  const plan = await response.json();
  return { id: plan.subjects[0].topics[0].tasks[0].id as string, title };
}

function localDateKey(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}
