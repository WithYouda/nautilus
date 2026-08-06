import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "填入当前授权码" }).click();
  await page.getByRole("button", { name: "进入工作区" }).click();
});

test("plan view starts with the portfolio and opens stacked overview sections", async ({ page }) => {
  const first = await createPlan(page.request, "考研数学强化计划", "高等数学", "极限与导数", "极限综合练习");
  await createPlan(page.request, "英语阅读提升计划", "英语", "阅读理解", "完成一篇真题阅读");
  await page.reload();

  await page.getByRole("button", { name: "计划", exact: true }).click();
  await expect(page.getByRole("heading", { name: "学习计划" })).toBeVisible();
  await expect.poll(() => page.getByLabel("全部计划").locator(".plan-summary-row").count()).toBeGreaterThanOrEqual(2);
  await expect(page.getByRole("heading", { name: first.title })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "计划详情视图" })).toHaveCount(0);

  await page.getByRole("heading", { name: first.title }).click();
  await expect(page.getByRole("navigation", { name: "计划详情视图" })).toBeVisible();
  await expect(page.getByRole("button", { name: "概览" })).toHaveClass(/is-active/);
  await expect(page.getByRole("button", { name: "科目" })).toBeVisible();
  const stacking = await page.evaluate(() => {
    const subjects = document.querySelector(".subject-progress-list")!.getBoundingClientRect();
    const recent = document.querySelector(".plan-recent-section")!.getBoundingClientRect();
    return { subjectBottom: subjects.bottom, recentTop: recent.top };
  });
  expect(stacking.recentTop).toBeGreaterThanOrEqual(stacking.subjectBottom);
  await page.getByRole("button", { name: "科目", exact: true }).click();
  await expect(page.getByRole("button", { name: "结构" })).toHaveClass(/is-active/);
  await expect(page.getByRole("heading", { name: "新建科目" })).toBeVisible();
});

test("document outline keeps one task editor and isolates row controls", async ({ page }) => {
  const plan = await createPlan(page.request, "结构交互计划", "数学", "函数", "极限综合练习");
  const second = await createTask(page.request, plan.topicId, "导数错题复盘");
  await page.goto(`/?view=plans&plan=${plan.id}&tab=structure`);

  await expect(page.getByRole("button", { name: "结构" })).toHaveClass(/is-active/);
  await expect(page.locator(".editor-form--inline")).toHaveCount(0);
  const firstMain = page.locator(".outline-node-main--task").filter({ hasText: plan.taskTitle });
  const secondMain = page.locator(".outline-node-main--task").filter({ hasText: second.title });
  await expect(firstMain).toBeVisible();
  await expect(secondMain).toBeVisible();

  await firstMain.click();
  await expect(page.getByRole("heading", { name: `编辑任务：${plan.taskTitle}` })).toBeVisible();
  await expect(page.locator(".editor-form--inline")).toHaveCount(1);
  await firstMain.click();
  await expect(page.locator(".editor-form--inline")).toHaveCount(0);

  await firstMain.click();
  await secondMain.click();
  await expect(page.getByRole("heading", { name: `编辑任务：${second.title}` })).toBeVisible();
  await expect(page.locator(".editor-form--inline")).toHaveCount(1);
  await secondMain.click();
  await expect(page.locator(".editor-form--inline")).toHaveCount(0);

  await page.getByRole("button", { name: `完成任务：${plan.taskTitle}` }).click();
  await expect(page.getByRole("button", { name: `撤销完成：${plan.taskTitle}` })).toBeVisible();
  await expect(page.locator(".editor-form--inline")).toHaveCount(0);
  await page.getByRole("button", { name: `更多操作：${plan.taskTitle}` }).click();
  await expect(page.getByRole("menuitem", { name: "删除" })).toBeVisible();
  await expect(page.locator(".editor-form--inline")).toHaveCount(0);
});

test("dirty task editor guards tab changes and supports discard", async ({ page }) => {
  const plan = await createPlan(page.request, "未保存保护计划", "数学", "函数", "任务草稿");
  await page.goto(`/?view=plans&plan=${plan.id}&tab=structure`);
  const taskMain = page.locator(".outline-node-main--task").filter({ hasText: plan.taskTitle });
  await taskMain.click();
  await page.getByLabel("任务名称").fill("尚未保存的任务名称");
  await page.getByRole("button", { name: "概览" }).click();
  const dialog = page.getByRole("dialog", { name: "当前修改还没有保存" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "继续编辑" }).click();
  await expect(page.getByRole("button", { name: "结构" })).toHaveClass(/is-active/);

  await page.getByRole("button", { name: "概览" }).click();
  await dialog.getByRole("button", { name: "放弃修改" }).click();
  await expect(page.getByRole("button", { name: "概览" })).toHaveClass(/is-active/);
});

test("failed node creation keeps the editor input and error visible", async ({ page }) => {
  const plan = await createPlan(page.request, "节点失败恢复计划", "数学", "函数", "任务草稿");
  await page.goto(`/?view=plans&plan=${plan.id}&tab=structure`);
  await page.route("**/api/plans/*/subjects", async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "模拟创建失败" }) });
  });

  await page.getByRole("button", { name: "科目", exact: true }).click();
  const input = page.getByLabel("科目名称");
  await input.fill("不能丢失的科目名称");
  await page.getByRole("button", { name: "创建" }).click();

  await expect(page.getByRole("alert")).toContainText("模拟创建失败");
  await expect(page.getByRole("heading", { name: "新建科目" })).toBeVisible();
  await expect(input).toHaveValue("不能丢失的科目名称");
});

test("plan settings protect unsaved changes when closing", async ({ page }) => {
  const plan = await createPlan(page.request, "设置保护计划", "数学", "函数", "任务草稿");
  await page.goto(`/?view=plans&plan=${plan.id}&tab=overview`);
  await page.getByRole("button", { name: "计划设置" }).click();
  await page.getByLabel("计划名称").fill("尚未保存的计划名称");
  await page.getByRole("button", { name: "关闭计划设置" }).click();

  const warning = page.getByRole("dialog", { name: "当前修改还没有保存" });
  await expect(warning).toBeVisible();
  await warning.getByRole("button", { name: "继续编辑" }).click();
  await expect(page.getByRole("dialog", { name: "计划设置" })).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(warning).toBeVisible();
  await warning.getByRole("button", { name: "放弃修改" }).click();
  await expect(page.getByRole("dialog", { name: "计划设置" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: plan.title })).toBeVisible();
});

test("plan schedule opens calendar with a persistent clearable plan filter", async ({ page }) => {
  const first = await createPlan(page.request, "日历筛选计划甲", "数学", "函数", "甲计划唯一任务");
  const second = await createPlan(page.request, "日历筛选计划乙", "英语", "阅读", "乙计划唯一任务");
  await page.goto(`/?view=plans&plan=${first.id}&tab=schedule`);
  await page.getByRole("button", { name: "在学习日历中查看" }).click();

  await expect(page).toHaveURL(new RegExp(`view=calendar.*plan_filter=${first.id}`));
  await expect(page.getByText(`计划：${first.title}`)).toBeVisible();
  await expect(page.getByRole("button", { name: first.taskTitle })).toBeVisible();
  await expect(page.getByRole("button", { name: second.taskTitle })).toHaveCount(0);

  await page.goBack();
  await expect(page.getByRole("heading", { name: first.title })).toBeVisible();
  await expect(page.getByRole("button", { name: "排期" })).toHaveClass(/is-active/);
  await page.goForward();
  await expect(page.getByText(`计划：${first.title}`)).toBeVisible();

  await page.reload();
  await expect(page.getByText(`计划：${first.title}`)).toBeVisible();
  await expect(page.getByRole("button", { name: second.taskTitle })).toHaveCount(0);
  await expect(page.locator(".calendar-cell.is-today .calendar-date small")).toHaveText("1");
  await page.getByRole("button", { name: "清除计划筛选" }).click();
  await expect(page).not.toHaveURL(/plan_filter=/);
  await expect(page.getByText(`计划：${first.title}`)).toHaveCount(0);
  await expect.poll(async () => Number(await page.locator(".calendar-cell.is-today .calendar-date small").textContent())).toBeGreaterThan(1);
});

test("compact AI companion drawer closes with Escape and backdrop", async ({ page }) => {
  for (const viewport of [{ width: 1024, height: 640 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.goto("/?view=today");
    await page.getByRole("button", { name: "打开 AI 学习伙伴" }).click();
    await expect(page.getByRole("dialog", { name: "AI 学习伙伴抽屉" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "AI 学习伙伴抽屉" })).toHaveCount(0);

    await page.getByRole("button", { name: "打开 AI 学习伙伴" }).click();
    await page.locator(".v6-companion-drawer-backdrop").click({ position: { x: 4, y: 4 } });
    await expect(page.getByRole("dialog", { name: "AI 学习伙伴抽屉" })).toHaveCount(0);
  }
});

test("plan workspace remains inside desktop compact and mobile viewports", async ({ page }) => {
  const plan = await createPlan(page.request, "响应式计划", "计算机", "数据结构", "完成树结构练习");
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 1024, height: 640 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.goto(`/?view=plans&plan=${plan.id}&tab=structure`);
    await expect(page.getByRole("heading", { name: plan.title })).toBeVisible();
    const metrics = await page.evaluate(() => ({
      width: document.documentElement.scrollWidth,
      height: document.documentElement.scrollHeight,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      mainWidth: document.querySelector(".v6-main-column")!.getBoundingClientRect().width,
    }));
    expect(metrics.width).toBeLessThanOrEqual(metrics.viewportWidth);
    expect(metrics.height).toBeLessThanOrEqual(metrics.viewportHeight);
    expect(metrics.mainWidth).toBeGreaterThan(300);
  }
});

async function createPlan(request: APIRequestContext, title: string, subject: string, topic: string, taskTitle: string) {
  const today = new Date();
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 45);
  const response = await request.post("/api/plans/manual", { data: {
    goal_title: title,
    description: `${title}的可执行学习路线`,
    start_date: dateKey(today),
    end_date: dateKey(end),
    subject_title: subject,
    topic_title: topic,
    task_title: taskTitle,
    task_type: "study",
    schedule_mode: "flexible",
    task_start_date: dateKey(today),
    task_due_date: dateKey(today),
    estimate_minutes: 50,
    timer_mode: "pomodoro_50_10",
    work_minutes: 50,
    break_minutes: 10,
  }});
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  return {
    id: body.id as string,
    title,
    topicId: body.subjects[0].topics[0].id as string,
    taskId: body.subjects[0].topics[0].tasks[0].id as string,
    taskTitle,
  };
}

async function createTask(request: APIRequestContext, topicId: string, title: string) {
  const today = new Date();
  const response = await request.post(`/api/topics/${topicId}/tasks`, { data: {
    title,
    task_type: "review",
    schedule_mode: "flexible",
    start_date: dateKey(today),
    due_date: dateKey(today),
    estimate_minutes: 35,
    timer_mode: "pomodoro_25_5",
    work_minutes: 25,
    break_minutes: 5,
  }});
  expect(response.ok()).toBeTruthy();
  return response.json() as Promise<{ id: string; title: string }>;
}

function dateKey(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}
