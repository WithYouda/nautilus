import { expect, test } from "@playwright/test";
import { authorize } from "./fact-helpers";

test("manual guided setup turns a natural-language goal into a learning session", async ({ page }) => {
  await authorize(page);
  const factButton = page.getByRole("button", { name: "开始学习" }).first();
  if (!(await factButton.isVisible())) {
    await page.getByRole("button", { name: "打开导航" }).click();
  }
  await factButton.click();
  await expect(page.getByRole("heading", { name: "开始一次学习" })).toBeVisible();

  const setup = page.getByRole("region", { name: "从学习意图开始" });
  const intent = "我想学会用 Python 正则处理日志，并能独立写出一个小脚本。";
  const actionTitle = "手动编写日志匹配练习";
  const stopConditions = "完成一个日志匹配脚本，并记录仍然不确定的正则语法。";

  await setup.getByLabel("学习目标").fill(intent);
  await expect(setup.getByRole("button", { name: "我想自己安排" })).toBeEnabled();
  await setup.getByRole("button", { name: "我想自己安排" }).click();

  await expect(setup.getByText("等待确认")).toBeVisible();
  await expect(setup.getByLabel("目标", { exact: true })).toHaveValue(intent);
  await expect(setup.getByLabel("这次任务")).toHaveValue("完成一次最小练习并说明自己的理解");

  await setup.getByLabel("这次任务").fill(actionTitle);
  await setup.getByLabel("完成后停止").fill(stopConditions);
  await setup.getByRole("button", { name: "确认这份学习安排" }).click();

  await expect(page.getByText("学习安排已确认，下一步是开始这项任务")).toBeVisible();
  await expect(setup.getByText("已确认")).toBeVisible();
  await expect(setup.getByLabel("这次任务")).toBeDisabled();
  await expect(setup.getByLabel("完成后停止")).toBeDisabled();

  const confirmedStateResponse = await page.request.get("/api/learning/state");
  expect(confirmedStateResponse.ok()).toBeTruthy();
  const confirmedState = await confirmedStateResponse.json();
  const confirmedSetup = confirmedState.setups.find((item) => item.original_intent === intent);
  expect(confirmedSetup).toBeDefined();

  const confirmedGoal = confirmedState.goals.find((item) => item.id === confirmedSetup.goal_id);
  const confirmedPlan = confirmedState.plans.find((item) => item.id === confirmedSetup.plan_id);
  const confirmedAction = confirmedState.actions.find((item) => item.id === confirmedSetup.action_id);
  const confirmedDelegation = confirmedState.delegations.find(
    (item) => item.id === confirmedSetup.delegation_id,
  );
  expect(confirmedGoal).toMatchObject({ original_intent: intent });
  expect(confirmedPlan).toMatchObject({ goal_id: confirmedSetup.goal_id });
  expect(confirmedAction).toMatchObject({ title: actionTitle });
  expect(confirmedDelegation).toMatchObject({ action_id: confirmedSetup.action_id });

  const eventsResponse = await page.request.get(`/api/learning/actions/${confirmedSetup.action_id}/events`);
  expect(eventsResponse.ok()).toBeTruthy();
  const events = await eventsResponse.json();
  expect(events.map((event) => event.event_type)).toEqual([
    "action.created",
    "delegation.created",
  ]);
  const delegationEvent = events.find((event) => event.event_type === "delegation.created");
  expect(JSON.parse(delegationEvent.payload_json)).toMatchObject({
    action_id: confirmedSetup.action_id,
    stop_conditions: stopConditions,
  });

  await setup.getByRole("button", { name: "开始这项任务" }).click();

  await expect(page.getByRole("heading", { name: "AI 学习室" })).toBeVisible();
  await expect(page.getByRole("region", { name: "本次学习安排" })).toContainText(actionTitle);
  await expect(page.getByRole("button", { name: "当前对话信息" })).toContainText("独立对话");
  await page.getByRole("button", { name: "当前对话信息" }).click();
  await expect(page.getByRole("region", { name: "本次学习安排" })).toContainText(stopConditions);
  await page.getByRole("button", { name: "关闭当前对话信息" }).click();
  await page.reload();
  await expect(page.getByRole("heading", { name: "AI 学习室" })).toBeVisible();
  await expect(page.getByRole("region", { name: "本次学习安排" })).toContainText(actionTitle);
  await page.getByRole("button", { name: "返回工作区" }).click();
  await expect(page.getByRole("heading", { name: "开始学习" })).toBeVisible();
  const session = page.getByRole("region", { name: "当前学习会话" });
  await expect(session.getByText("状态：running", { exact: true })).toBeVisible();

  const runningStateResponse = await page.request.get("/api/learning/state");
  expect(runningStateResponse.ok()).toBeTruthy();
  const runningState = await runningStateResponse.json();
  expect(runningState.sessions).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        delegation_id: confirmedSetup.delegation_id,
        status: "running",
      }),
    ]),
  );

  await session.getByRole("button", { name: "结束学习记录" }).click();
  await expect(page.getByText("学习会话已结束")).toBeVisible();
});
