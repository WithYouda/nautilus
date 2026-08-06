import { expect, test } from "@playwright/test";

test("production delivery excludes development clients", async ({ request }) => {
  const response = await request.get("/");
  expect(response.ok()).toBeTruthy();

  const html = await response.text();
  expect(html).not.toContain("/@vite/client");
  expect(html).not.toContain("@react-refresh");
  expect(html).not.toContain("react-refresh");
  expect(html).toMatch(/\/assets\/index-[^\"']+\.js/);
});

test("authorized delivery page does not open HMR sockets or navigate unexpectedly", async ({
  page,
}) => {
  const mainFrameNavigations: string[] = [];
  const unexpectedWebSockets: string[] = [];

  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame()) mainFrameNavigations.push(frame.url());
  });
  page.on("websocket", (socket) => {
    const pathname = new URL(socket.url()).pathname;
    if (!pathname.startsWith("/api/ws/")) unexpectedWebSockets.push(socket.url());
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "授权此设备，继续学习。" })).toBeVisible();
  mainFrameNavigations.length = 0;

  await page.getByRole("button", { name: "填入当前授权码" }).click();
  await page.getByRole("button", { name: "进入工作区" }).click();
  await expect(page.getByRole("navigation", { name: "工作区视图" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "当前视角" })).toBeVisible();

  const memoryMarker = await page.evaluate(() => {
    const marker = crypto.randomUUID();
    Object.assign(window, { __nautilusPlaywrightMarker: marker });
    return marker;
  });

  await page.waitForTimeout(5_000);

  expect(mainFrameNavigations).toEqual([]);
  expect(unexpectedWebSockets).toEqual([]);
  expect(await page.evaluate(() => window.__nautilusPlaywrightMarker)).toBe(memoryMarker);
});

test("task list filters, reschedules, and exposes the task in calendar", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "填入当前授权码" }).click();
  await page.getByRole("button", { name: "进入工作区" }).click();
  await expect(page.getByRole("navigation", { name: "工作区视图" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "当前视角" })).toBeVisible();

  const today = new Date();
  const tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
  const planEnd = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 30);
  const title = "Playwright 延期任务";
  const created = await page.context().request.post("/api/plans/manual", {
    data: {
      goal_title: "Playwright 计划阶段验证",
      description: "隔离数据库中的端到端测试数据",
      start_date: localDateKey(today),
      end_date: localDateKey(planEnd),
      subject_title: "自动化测试",
      topic_title: "任务列表与日历",
      task_title: title,
      task_type: "practice",
      schedule_mode: "flexible",
      task_start_date: localDateKey(today),
      task_due_date: localDateKey(today),
      estimate_minutes: 30,
      timer_mode: "pomodoro_25_5",
      work_minutes: 25,
      break_minutes: 5,
    },
  });
  expect(created.ok()).toBeTruthy();
  await page.reload();

  await page.getByRole("button", { name: "任务", exact: true }).click();
  await expect(page.getByRole("heading", { name: "独立任务列表" })).toBeVisible();
  await page.getByPlaceholder("搜索任务、目标、科目或主题").fill("延期任务");
  const row = page.locator(".task-table-row").filter({ hasText: title });
  await expect(row).toBeVisible();

  const rescheduleResponse = page.waitForResponse((response) =>
    response.url().includes("/reschedule") && response.request().method() === "POST",
  );
  await row.getByRole("button", { name: "重排" }).click();
  expect((await rescheduleResponse).ok()).toBeTruthy();
  const taskResponse = await page.context().request.get("/api/tasks", { params: { query: title } });
  expect(taskResponse.ok()).toBeTruthy();
  expect((await taskResponse.json())[0].start_date).toBe(localDateKey(tomorrow));

  await page.getByRole("button", { name: "日历", exact: true }).click();
  await expect(page.getByRole("heading", { name: "月历视图" })).toBeVisible();
  if (tomorrow.getMonth() !== today.getMonth()) {
    await page.getByRole("button", { name: "下个月" }).click();
  }
  await expect(page.getByRole("button", { name: title })).toBeVisible();
  await page.getByRole("button", { name: title }).click();
  await expect(page.getByText(title, { exact: true }).first()).toBeVisible();
});

test("task and calendar views keep the mobile page within the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "填入当前授权码" }).click();
  await page.getByRole("button", { name: "进入工作区" }).click();

  await page.getByRole("button", { name: "任务", exact: true }).click();
  await expect(page.getByRole("heading", { name: "独立任务列表" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();

  await page.getByRole("button", { name: "日历", exact: true }).click();
  await expect(page.getByRole("heading", { name: "月历视图" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

function localDateKey(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

declare global {
  interface Window {
    __nautilusPlaywrightMarker?: string;
  }
}
