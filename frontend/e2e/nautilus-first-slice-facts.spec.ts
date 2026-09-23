import { expect, test } from "@playwright/test";
import { authorize, openFactWorkspace } from "./fact-helpers";

const mockProviderBaseUrl =
  process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? "http://127.0.0.1:8013/v1";

test("fact gate saves, corrects, replays, and survives refresh without a standard", async ({ page }) => {
  await authorize(page);
  await openFactWorkspace(page);

  // Suites share only the newly created /tmp test database. Preserve earlier
  // synthetic artifacts and pause any previous journey before starting ours.
  const existing = await (await page.request.get("/api/learning/state")).json();
  const running = existing.sessions.find((item: { status: string }) => item.status === "running");
  if (running) {
    const delegation = existing.delegations.find((item: { id: string }) => item.id === running.delegation_id);
    const action = existing.actions.find((item: { id: string }) => item.id === delegation.action_id);
    const paused = await page.request.post(`/api/learning/sessions/${running.id}/end`, { data: {
      disposition: "interrupted", expected_version: action.aggregate_version,
      idempotency_key: `synthetic-fact-isolation:${running.id}`,
    }});
    expect(paused.ok()).toBeTruthy();
    await page.getByRole("button", {name:"刷新状态"}).click();
  }

  await page.getByLabel("任务标题").fill("Playwright 事实门任务");
  await page.getByLabel("上下文").first().fill("playwright-context");
  await page.getByRole("button", { name: "创建任务" }).click();
  await expect(page.getByText("任务已保存")).toBeVisible();

  await page.getByLabel("对象", {exact:true}).fill("Playwright 可验证成果");
  await page.getByLabel("行为").fill("能独立完成事实链说明");
  await page.getByLabel("上下文").nth(1).fill("playwright-context");
  await page.getByRole("button", { name: "创建可验证成果" }).click();
  await expect(page.getByText("可验证成果已保存")).toBeVisible();

  await page.getByLabel("停止条件").fill("保存一份文本产出");
  await page.getByRole("button", { name: "创建学习委托" }).click();
  await expect(page.getByText("学习委托已保存")).toBeVisible();
  await page.getByRole("button", {name:"学习判断详情",exact:true}).click();
  await page.getByText("判断范围与待观察内容", {exact:true}).click();
  await expect(page.getByText("尚无已审核标准，本次反馈不派生成果状态。")).toBeVisible();

  await page.getByRole("button", { name: "开始学习会话" }).click();
  await expect(page.getByText("学习会话已开始")).toBeVisible();
  await expect(page.getByText("running", { exact: true }).last()).toBeVisible();

  const output = page.getByLabel("原始文本产出");
  await output.fill("这是第一版 Playwright 学习产出。");
  const saveButton = page.getByRole("button", { name: "保存原始产出" });
  await saveButton.click();
  await expect(page.getByText("学习产出已保存")).toBeVisible();
  await expect(page.locator(".fact-list li").filter({hasText:"Playwright 事实门任务"})).toHaveCount(1);
  await expect(page.getByText("这是第一版 Playwright 学习产出。")).toBeVisible();
  await expect(page.getByText("blocked_no_criterion")).toBeVisible();
  await expect(page.getByText("no approved criterion")).toBeVisible();

  await page.getByRole("button", { name: "结束会话" }).click();
  await expect(page.getByText("学习会话已结束")).toBeVisible();

  await page.getByLabel("追加更正版本").fill("这是更正后的 Playwright 学习产出。");
  await page.getByRole("button", { name: "追加更正" }).click();
  await expect(page.getByText("学习产出已追加更正版本")).toBeVisible();
  await expect(page.getByText("这是更正后的 Playwright 学习产出。")).toBeVisible();

  await page.getByLabel("读取粒度").selectOption("full_text");
  await page.getByRole("button", { name: "发起 Agent 权限申请" }).click();
  await expect(page.getByText("Agent 已发起最小范围读取申请")).toBeVisible();
  await expect(page.getByText(/等待处理 · 任务范围 · 原文 · 5 分钟/)).toBeVisible();
  await page.getByRole("button", { name: "批准", exact: true }).click();
  await expect(page.getByText("已批准本次最小范围读取，未扩大写入权限")).toBeVisible();
  await expect(page.getByText("当前行动上下文 · 已授权")).toBeVisible();
  await expect(page.getByText("0 条证据引用 · 1 个授权产出 · 授权范围内可读")).toBeVisible();
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(page.getByText("已撤销 Agent 读取授权")).toBeVisible();
  await expect(page.getByText("当前行动上下文 · 最小范围")).toBeVisible();
  await expect(page.getByText("0 条证据引用 · 0 个授权产出 · 不可用：原文、授权产出元数据")).toBeVisible();
  await page.getByRole("button", { name: "再次申请" }).click();
  await expect(page.getByText("Agent 已发起最小范围读取申请")).toBeVisible();
  await page.getByRole("button", { name: "拒绝", exact: true }).click();
  await expect(page.getByText("已拒绝 Agent 读取申请，学习产出保存不受影响")).toBeVisible();

  await page.getByRole("button", { name: "回放事实" }).first().click();
  await expect(page.getByText(/事实回放完成：\d+ 个事件，\d+ 个聚合/)).toBeVisible();

  await page.reload();
  await openFactWorkspace(page);
  await expect(page.locator(".fact-list").getByText("Playwright 事实门任务")).toBeVisible();
  await expect(page.getByText("这是更正后的 Playwright 学习产出。")).toBeVisible();
  await expect(page.locator(".fact-meta").getByText("ended")).toBeVisible();
  await expect(page.getByText("artifact.corrected")).toBeVisible();
});

test("fact workspace keeps the mobile page within the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await authorize(page);
  await openFactWorkspace(page);

  await expect(page.getByRole("heading", { name: "任务", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test("fact workspace saves an explicit evidence analysis provider", async ({ page }) => {
  await authorize(page);
  const providerResponse = await page.request.put("/api/ai/provider", {
    data: {
      display_name: "Playwright Evidence Mock",
      base_url: mockProviderBaseUrl,
      model: "mock-evidence",
      api_key: "sk-playwright-evidence-mock",
      enabled: true,
      request_timeout_seconds: 15,
    },
  });
  expect(providerResponse.ok()).toBeTruthy();
  const { provider } = await providerResponse.json();

  await openFactWorkspace(page);
  const providerCard = page.getByRole("region", { name: "证据分析 Provider 设置" });
  await expect(providerCard.getByText("跟随默认 Provider")).toBeVisible();
  await providerCard.getByLabel("Provider").selectOption(provider.id);
  await providerCard.getByLabel("分析模型").selectOption(provider.default_model.id);
  await providerCard.getByRole("button", { name: "保存证据分析 Provider" }).click();
  await expect(page.getByText("证据分析 Provider 已保存")).toBeVisible();
  await expect(providerCard.getByText("独立配置")).toBeVisible();

  const selectionResponse = await page.request.get("/api/learning/evidence-provider");
  expect(selectionResponse.ok()).toBeTruthy();
  expect(await selectionResponse.json()).toMatchObject({
    provider_profile_id: provider.id,
    provider_model_id: provider.default_model.id,
  });

  await page.reload();
  await openFactWorkspace(page);
  await expect(page.getByRole("region", { name: "证据分析 Provider 设置" }).getByText("独立配置")).toBeVisible();

  await page.getByRole("button", { name: "恢复默认 Provider" }).click();
  await expect(page.getByText("证据分析 Provider 已恢复默认")).toBeVisible();
  await expect(page.getByRole("region", { name: "证据分析 Provider 设置" }).getByText("跟随默认 Provider")).toBeVisible();
  const clearedSelection = await page.request.get("/api/learning/evidence-provider");
  expect(clearedSelection.ok()).toBeTruthy();
  expect(await clearedSelection.json()).toBeNull();
});

test("approved regex standard creates semantic and deterministic candidate claims", async ({ page }) => {
  await authorize(page);
  const provider = await page.request.put("/api/ai/provider", {
    data: {
      display_name: "Playwright Evidence Mock",
      base_url: mockProviderBaseUrl,
      model: "mock-evidence",
      api_key: "sk-playwright-evidence-mock",
      enabled: true,
      request_timeout_seconds: 15,
    },
  });
  expect(provider.ok()).toBeTruthy();
  await openFactWorkspace(page);

  await page.getByLabel("任务标题").fill("Playwright 正则标准任务");
  await page.getByLabel("上下文").first().fill("python-regex-basics");
  await page.getByRole("button", { name: "创建任务" }).click();
  await expect(page.getByText("任务已保存")).toBeVisible();

  const delegationCard = page.getByRole("region", { name: "创建学习委托" });
  await delegationCard.getByLabel("可验证成果").selectOption({
    label:
      "Python re 模块中的基础正则表达式语法 / 能在不查阅资料的情况下解释并编写基础 Python 正则表达式，用于匹配文本中的字面量、字符类、边界、量词和分组",
  });
  await delegationCard.getByLabel("达成标准").selectOption({
    label: "Python 正则表达式基础 v1 · v1",
  });
  await delegationCard.getByLabel("停止条件").fill("完成一次正则表达式确定性检查");
  await page.getByRole("button", { name: "创建学习委托" }).click();
  await expect(page.getByText("学习委托已保存")).toBeVisible();

  await page.getByRole("button", { name: "开始学习会话" }).click();
  await expect(page.getByText("学习会话已开始")).toBeVisible();

  await page.getByLabel("原始文本产出").fill("regex: ^Playwright\\d+$\nsample: Playwright42");
  await page.getByRole("button", { name: "保存原始产出" }).click();
  await expect(page.getByText("学习产出已保存")).toBeVisible();
  await expect(page.locator(".fact-list li").filter({ hasText: "Playwright 正则标准任务" })).toHaveCount(1);

  await page.getByRole("button", { name: "分析产出" }).click();
  await expect(page.getByText("证据分析完成：生成 2 条候选主张")).toBeVisible();
  await expect(page.getByText("尝试 1 · succeeded")).toBeVisible();
  await expect(page.locator(".fact-claim")).toHaveCount(2);
  await expect(page.getByText("syntax_semantics · supports")).toBeVisible();
  await expect(page.getByText("candidate · ai_analysis")).toBeVisible();
  await expect(page.getByText("application · supports")).toBeVisible();
  await expect(page.getByText("candidate · deterministic_check")).toBeVisible();
  await expect(page.getByText("语义分析确认产出说明了正则表达式的匹配语义。")).toBeVisible();
  await expect(page.getByText("确定性检查通过：该正则表达式在示例文本中匹配成功。")).toBeVisible();
  await expect(page.getByText("复核依据可见范围")).toBeVisible();
  await expect(page.getByText("Agent：仅有摘要、状态和证据引用，无原文授权")).toBeVisible();
  await expect(page.getByText("用户无需授权即可暂不处理、请求人工复核或安排补充验证。")).toBeVisible();

  const semanticClaim = page.locator(".fact-claim").filter({
    hasText: "syntax_semantics · supports",
  });
  await semanticClaim.getByRole("button", { name: "暂不处理" }).click();
  await expect(page.getByText("主张保持候选，暂不处理")).toBeVisible();

  const applicationClaim = page.locator(".fact-claim").filter({
    hasText: "application · supports",
  });
  await applicationClaim.getByRole("button", { name: "请求人工复核" }).click();
  await expect(page.getByText("已请求人工复核")).toBeVisible();
  await applicationClaim.getByRole("button", { name: "安排补充验证" }).click();
  await expect(page.getByText("已安排补充验证")).toBeVisible();
  await expect(page.locator(".fact-follow-up")).toHaveCount(2);
  await expect(page.locator(".fact-follow-up").getByText("人工复核", { exact: true })).toBeVisible();
  await expect(page.locator(".fact-follow-up").getByText("补充验证", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "分析产出" }).click();
  await expect(page.getByText("证据分析完成：生成 2 条候选主张")).toBeVisible();
  await expect(page.locator(".fact-claim")).toHaveCount(2);

  await page.reload();
  await expect(page.getByRole("heading", { name: "学习首页" })).toBeVisible();
  await expect(page.locator(".fact-claim")).toHaveCount(2);
  await expect(page.locator(".fact-follow-up")).toHaveCount(2);
});

test("derived state recalculates after review and artifact correction", async ({ page }) => {
  await authorize(page);
  await openFactWorkspace(page);

  const existingEndSession = page.getByRole("button", { name: "结束会话" });
  if (await existingEndSession.isEnabled()) {
    await existingEndSession.click();
    await expect(page.getByText("学习会话已结束")).toBeVisible();
  }

  const existingClaimsResponse = await page.request.get("/api/learning/evidence-claims");
  expect(existingClaimsResponse.ok()).toBeTruthy();
  const existingClaims = await existingClaimsResponse.json();
  for (const claim of existingClaims) {
    if (claim.status === "candidate") {
      const superseded = await page.request.post(
        `/api/learning/evidence-claims/${claim.id}/review`,
        {
          data: {
            action: "withdraw",
            reason: "测试隔离：清理旧候选主张",
            request_key: `setup-supersede-${claim.id}`,
          },
        },
      );
      expect(superseded.ok()).toBeTruthy();
    }
  }

  await page.getByLabel("任务标题").fill("Playwright 状态派生任务");
  await page.getByLabel("上下文").first().fill("python-regex-basics");
  await page.getByRole("button", { name: "创建任务" }).click();
  await expect(page.getByText("任务已保存")).toBeVisible();

  const delegationCard = page.getByRole("region", { name: "创建学习委托" });
  await delegationCard.getByLabel("可验证成果").selectOption({
    label:
      "Python re 模块中的基础正则表达式语法 / 能在不查阅资料的情况下解释并编写基础 Python 正则表达式，用于匹配文本中的字面量、字符类、边界、量词和分组",
  });
  await delegationCard.getByLabel("达成标准").selectOption({
    label: "Python 正则表达式基础 v1 · v1",
  });
  await delegationCard.getByLabel("停止条件").fill("验证状态派生和重算");
  await page.getByRole("button", { name: "创建学习委托" }).click();
  await expect(page.getByText("学习委托已保存")).toBeVisible();

  await page.getByRole("button", { name: "开始学习会话" }).click();
  await expect(page.getByText("学习会话已开始")).toBeVisible();
  await page.getByLabel("原始文本产出").fill("regex: ^State\\d+$\nsample: State42");
  await page.getByRole("button", { name: "保存原始产出" }).click();
  await expect(page.getByText("学习产出已保存")).toBeVisible();

  await page.getByRole("button", { name: "分析产出" }).click();
  await expect(page.getByText("证据分析完成：生成 2 条候选主张")).toBeVisible();

  await page.getByRole("button", { name: "批量采纳候选主张" }).click();
  await expect(page.getByText("批量采纳完成：2 条主张")).toBeVisible();

  const applicationClaim = page.locator(".fact-claim").filter({
    hasText: "application · supports",
  });
  const applicationState = page.locator(".fact-state-list li").filter({ hasText: "application" });
  const syntaxState = page.locator(".fact-state-list li").filter({ hasText: "syntax_semantics" });
  await expect(applicationState).toContainText("partially_supported");
  await expect(syntaxState).toContainText("partially_supported");
  await expect(applicationState).toContainText("independence_unverified");
  await expect(applicationState).toContainText("v1");
  await expect(applicationState).toContainText("v1");

  await applicationClaim.getByRole("button", { name: "质疑" }).click();
  await expect(page.getByText("主张已质疑，状态已重新计算")).toBeVisible();
  await expect(applicationState).toContainText("awaiting_evidence");
  await expect(applicationState).toContainText("no_current_evidence");
  await expect(page.locator(".fact-revisit-list li").filter({ hasText: "questioned_claim" })).toBeVisible();

  const beforeRecalcResponse = await page.request.get("/api/learning/derived-states");
  expect(beforeRecalcResponse.ok()).toBeTruthy();
  const beforeRecalcStates = await beforeRecalcResponse.json();
  const beforeApplicationState = beforeRecalcStates.find(
    (item) => item.dimension_id === "application",
  );

  await page.getByRole("button", { name: "重算状态" }).click();
  await expect(page.getByText("状态重算完成：3 个维度")).toBeVisible();
  await expect(applicationState).toContainText("awaiting_evidence");

  const afterRecalcResponse = await page.request.get("/api/learning/derived-states");
  expect(afterRecalcResponse.ok()).toBeTruthy();
  const afterRecalcStates = await afterRecalcResponse.json();
  const afterApplicationState = afterRecalcStates.find(
    (item) => item.dimension_id === "application",
  );
  expect(afterApplicationState.calculation_version).toBe(
    beforeApplicationState.calculation_version + 1,
  );

  await page.getByLabel("追加更正版本").fill("regex: ^Recalculated\\d+$\nsample: Recalculated42");
  await page.getByRole("button", { name: "追加更正" }).click();
  await expect(page.getByText("学习产出已追加更正版本")).toBeVisible();
  await expect(applicationState).toContainText("awaiting_evidence");
  await expect(applicationClaim).toContainText("superseded");

  await page.getByRole("button", { name: "分析产出" }).click();
  await expect(page.getByText("证据分析完成：生成 2 条候选主张")).toBeVisible();
  await expect(page.locator(".fact-replacement")).toHaveCount(4);
  await expect(page.getByText("替代关系")).toHaveCount(4);
});
