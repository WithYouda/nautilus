import { expect, test } from "@playwright/test";
import { authorize } from "./fact-helpers";

test("existing plan can enter the learning room with or without focus timing", async ({ page }) => {
  await authorize(page);

  const now = new Date();
  const startDate = localDateKey(now);
  const endDate = localDateKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 30));
  const response = await page.request.post("/api/plans/manual", {
    data: {
      goal_title: "已有计划直达验证",
      description: "隔离数据库中的直接学习入口验证",
      start_date: startDate,
      end_date: endDate,
      subject_title: "直接学习",
      topic_title: "学习室入口",
      task_title: "无计时答疑任务",
      task_type: "study",
      schedule_mode: "flexible",
      task_start_date: startDate,
      task_due_date: startDate,
      estimate_minutes: 30,
      timer_mode: "pomodoro_25_5",
      work_minutes: 25,
      break_minutes: 5,
    },
  });
  expect(response.ok()).toBeTruthy();
  const plan = await response.json();
  const task = plan.subjects[0].topics[0].tasks[0];

  const secondResponse = await page.request.post("/api/plans/manual", {
    data: {
      goal_title: "已有计划直达计时验证",
      description: "隔离数据库中的直接学习计时验证",
      start_date: startDate,
      end_date: endDate,
      subject_title: "直接学习",
      topic_title: "专注计时",
      task_title: "带计时答疑任务",
      task_type: "practice",
      schedule_mode: "flexible",
      task_start_date: startDate,
      task_due_date: startDate,
      estimate_minutes: 30,
      timer_mode: "pomodoro_25_5",
      work_minutes: 25,
      break_minutes: 5,
    },
  });
  expect(secondResponse.ok()).toBeTruthy();
  const secondPlan = await secondResponse.json();
  const timedTask = secondPlan.subjects[0].topics[0].tasks[0];

  await page.reload();
  await page.getByRole("button", { name: "开始学习" }).first().click();
  await expect(page.getByRole("heading", { name: "开始学习" })).toBeVisible();
  await page.getByRole("button", { name: "我已有学习计划" }).click();

  const direct = page.getByRole("region", { name: "按计划进入学习室" });
  await direct.getByLabel("选择计划任务").selectOption(task.id);
  await direct.getByRole("button", { name: "进入学习室" }).click();
  await expect(page.getByRole("heading", { name: "AI 学习室" })).toBeVisible();
  await page.getByRole("button", { name: "当前对话信息" }).click();
  await expect(page.getByText("无计时答疑任务", { exact: true }).last()).toBeVisible();
  await page.getByRole("button", { name: "返回工作区" }).click();

  await page.getByRole("button", { name: "我已有学习计划" }).click();
  await page.getByRole("region", { name: "按计划进入学习室" }).getByLabel("选择计划任务").selectOption(timedTask.id);
  await page.getByRole("region", { name: "按计划进入学习室" }).getByRole("button", { name: "开始专注并进入" }).click();
  await expect(page.getByRole("heading", { name: "AI 学习室" })).toBeVisible();
  await expect(page.getByRole("region", { name: "活动学习计时" })).toBeVisible();

  await page.getByRole("button", { name: "返回工作区" }).click();
  await expect(page.getByRole("region", { name: "活动学习计时" })).toBeVisible();
  await page.getByRole("button", { name: "结束计时" }).click();
  await expect(page.getByRole("region", { name: "活动学习计时" })).toBeHidden();
});

function localDateKey(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}
