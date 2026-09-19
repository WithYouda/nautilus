import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const mockProviderBaseUrl =
  process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? "http://127.0.0.1:8013/v1";
const fakeApiKey = "sk-playwright-fake-key-only";

test.beforeEach(async ({ page }) => {
  await authorize(page);
  await resetMockProvider(page.context().request);
});

test("provider connection distinguishes an unreachable local API from an upstream error", async ({ page }) => {
  await page.getByRole("button", { name: "提供方设置" }).click();
  await page.route("**/api/ai/provider/models", (route) => route.abort("failed"));
  await page.route("**/api/ai/provider/test", (route) => route.abort("failed"));
  await page.getByLabel("Base URL").fill("https://api.deepseek.com/v1");
  await page.getByRole("combobox", { name: "模型" }).fill("deepseek-chat");
  await page.getByLabel("API Key").fill(fakeApiKey);

  await page.getByRole("button", { name: "连接测试" }).click();
  await expect(page.getByRole("dialog", { name: "选择要测试的模型" })).toBeVisible();
  await page.getByRole("button", { name: "测试所选模型" }).click();

  await expect(page.getByRole("alert")).toContainText("无法连接 Nautilus 本地服务");
  await expect(page.getByRole("alert")).not.toContainText("Failed to fetch");
});

test("model discovery keeps structured upstream errors actionable and allows manual models", async ({ page }) => {
  await page.getByRole("button", { name: "提供方设置" }).click();
  await page.route("**/api/ai/provider/models", (route) => route.fulfill({
    status: 404,
    contentType: "application/json",
    body: JSON.stringify({ detail: { kind: "endpoint_not_found", message: "模型发现端点不可用，可手动填写模型名称" } }),
  }));
  await page.getByLabel("Base URL").fill("https://api.deepseek.com/v1");
  await page.getByRole("combobox", { name: "模型" }).fill("deepseek-chat");
  await page.getByLabel("API Key").fill(fakeApiKey);

  await page.getByRole("button", { name: "连接测试" }).click();
  await expect(page.getByRole("dialog", { name: "选择要测试的模型" })).toBeVisible();
  await expect(page.getByText("模型发现端点不可用", { exact: false })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "选择要测试的模型" }).getByText("仍可手动填写", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "取消" }).last().click();
  await expect(page.getByRole("combobox", { name: "模型" })).toHaveValue("deepseek-chat");
});

test("AI learning streams a normal reply and persists one message pair", async ({ page }) => {
  const task = await createTask(page.context().request, "正常流");
  await configureProvider(page.context().request, "mock-success");
  await page.reload();
  await openLearningRoom(page, task.title);

  await expect(page.getByRole("heading", { name: "AI 学习室" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "新的学习对话" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "工作区视图" })).toHaveCount(0);
  await expect(page.getByRole("complementary", { name: "AI 学习伙伴" })).toHaveCount(0);
  const contextButton = page.getByRole("button", { name: "当前对话信息", exact: true });
  await expect(contextButton).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(".ai-room-header").getByRole("button", { name: "当前对话信息" })).toBeVisible();
  await expect(page.locator(".ai-room-chat").getByRole("button", { name: "当前对话信息" })).toHaveCount(0);
  await expect(page.locator(".ai-status")).toHaveCount(0);
  const configButton = page.getByRole("button", { name: "对话配置" });
  await expect(page.locator(".ai-room-chat").getByRole("button", { name: "对话配置" })).toHaveCount(0);
  await expect(page.locator(".ai-room-header").getByRole("button", { name: "对话配置" })).toBeVisible();
  await expect(configButton).toHaveCSS("background-color", "rgb(221, 213, 199)");
  await configButton.click();
  await expect(page.getByText("本次对话配置", { exact: true })).toBeVisible();
  await page.locator(".ai-message-list").click({ position: { x: 20, y: 20 } });
  await expect(page.getByText("本次对话配置", { exact: true })).toBeHidden();
  await configButton.click();
  await page.keyboard.press("Escape");
  await expect(page.getByText("本次对话配置", { exact: true })).toBeHidden();
  await configButton.click();
  await page.getByRole("button", { name: "新建对话" }).focus();
  await expect(page.getByText("本次对话配置", { exact: true })).toBeHidden();
  const roomMetrics = await page.evaluate(() => {
    const room = document.querySelector(".ai-room")!.getBoundingClientRect();
    const chat = document.querySelector(".ai-room-chat")!.getBoundingClientRect();
    const composer = document.querySelector(".ai-composer")!.getBoundingClientRect();
    const header = document.querySelector(".ai-room-header")!.getBoundingClientRect();
    const titlebar = document.querySelector(".ai-chat-titlebar")!.getBoundingClientRect();
    const messageList = document.querySelector(".ai-message-list")!;
    const messageListRect = messageList.getBoundingClientRect();
    return {
      roomWidth: room.width,
      roomBottom: room.bottom,
      chatWidth: chat.width,
      composerBottom: composer.bottom,
      composerHeight: composer.height,
      headerHeight: header.height,
      titlebarHeight: titlebar.height,
      titleCenterOffset: Math.abs(
        document.querySelector(".ai-chat-title-copy h2")!.getBoundingClientRect().x
          + document.querySelector(".ai-chat-title-copy h2")!.getBoundingClientRect().width / 2
          - (titlebar.x + titlebar.width / 2),
      ),
      messageListHeight: messageListRect.height,
      timerTop: document.querySelector(".v6-floating-timer")?.getBoundingClientRect().top ?? null,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      documentHeight: document.documentElement.scrollHeight,
      messageOverflowY: getComputedStyle(messageList).overflowY,
    };
  });
  expect(roomMetrics.roomWidth).toBeGreaterThan(roomMetrics.viewportWidth * 0.95);
  expect(roomMetrics.chatWidth).toBeGreaterThan(roomMetrics.roomWidth * 0.9);
  expect(roomMetrics.roomBottom).toBeLessThanOrEqual(roomMetrics.viewportHeight);
  expect(roomMetrics.composerBottom).toBeLessThanOrEqual(roomMetrics.viewportHeight);
  expect(roomMetrics.documentHeight).toBeLessThanOrEqual(roomMetrics.viewportHeight);
  expect(roomMetrics.messageOverflowY).toBe("auto");
  expect(roomMetrics.headerHeight).toBeLessThan(70);
  expect(roomMetrics.titlebarHeight).toBeLessThanOrEqual(52);
  expect(roomMetrics.titleCenterOffset).toBeLessThanOrEqual(2);
  expect(roomMetrics.composerHeight).toBeLessThan(100);
  expect(roomMetrics.messageListHeight).toBeGreaterThan(roomMetrics.viewportHeight * 0.45);
  if (roomMetrics.timerTop !== null) {
    expect(roomMetrics.composerBottom).toBeLessThanOrEqual(roomMetrics.timerTop - 8);
  }
  await contextButton.click();
  await expect(contextButton).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".ai-context-panel").getByText(task.title, { exact: true })).toBeVisible();
  await expect(page.getByText("进度", { exact: true })).toBeVisible();
  await page.locator(".ai-message-list").click({ position: { x: 20, y: 20 } });
  await expect(contextButton).toHaveAttribute("aria-expanded", "false");

  const sent = waitForSentRun(page);
  const composer = page.getByLabel("输入学习问题");
  await composer.fill("第一行");
  await composer.press("Shift+Enter");
  await composer.type("第二行");
  await expect(composer).toHaveValue("第一行\n第二行");
  await composer.press("Enter");
  const { conversationId, runId } = await sent;

  await expect(page.getByRole("heading", { name: "学习步骤" })).toBeVisible();
  await expect(page.locator(".ai-markdown ol li")).toHaveCount(2);
  await expect(page.locator(".ai-markdown table")).toBeVisible();
  await expect(page.locator(".ai-markdown code").filter({ hasText: "完成" })).toBeVisible();
  await expect(page.getByRole("button", { name: "取消生成" })).toBeHidden();
  await expect(page.getByRole("heading", { name: "学习步骤与目标拆解" })).toBeVisible({ timeout: 10_000 });

  const detail = await getConversation(page.context().request, conversationId);
  expect(detail.active_run).toBeNull();
  expect(detail.messages).toHaveLength(2);
  expect(detail.messages.map((message: Message) => message.role)).toEqual(["user", "assistant"]);
  expect(detail.messages[1].status).toBe("complete");
  expect(detail.messages[0].content).toBe("第一行\n第二行");
  expect(detail.messages[1].content).toContain("用例题检查");
  expect(detail.conversation.title_source).toBe("ai");

  const stats = await mockStats(page.context().request);
  expect(stats.requests["mock-success"]).toBe(1);
  expect(stats.requests["title:mock-success"]).toBe(1);
  expect(runId).toBeTruthy();
});

test("task conversations persist across new conversation, workspace return, refresh, and history switching", async ({ page }) => {
  const task = await createTask(page.context().request, "任务关联恢复");
  const configuredProvider = await configureProvider(page.context().request, "mock-success");
  const independentResponse = await page.context().request.post("/api/ai/conversations", { data: {} });
  expect(independentResponse.status()).toBe(201);
  const independentId = (await independentResponse.json()).conversation.id as string;
  await page.reload();
  await openLearningRoom(page, task.title);

  const firstSent = waitForSentRun(page);
  await page.getByLabel("输入学习问题").fill("第一段任务对话");
  await page.getByRole("button", { name: "发送问题" }).click();
  const first = await firstSent;
  await expect.poll(async () => (await getConversation(page.request, first.conversationId)).active_run).toBeNull();
  const configured = await page.request.put(`/api/ai/conversations/${first.conversationId}/config`, {
    data: {
      provider_profile_id: configuredProvider.id,
      provider_model_id: configuredProvider.default_model.id,
    },
  });
  expect(configured.ok()).toBeTruthy();

  await page.getByRole("button", { name: "新建对话" }).click();
  const secondSent = waitForSentRun(page);
  await page.getByLabel("输入学习问题").fill("第二段任务对话");
  await page.getByRole("button", { name: "发送问题" }).click();
  const second = await secondSent;
  await expect.poll(async () => (await getConversation(page.request, second.conversationId)).active_run).toBeNull();

  expect((await getConversation(page.request, first.conversationId)).context.task_id).toBe(task.id);
  expect((await getConversation(page.request, second.conversationId)).context.task_id).toBe(task.id);
  expect((await getConversation(page.request, independentId)).context).toBeNull();

  await page.getByRole("button", { name: "返回工作区" }).click();
  await openLearningRoom(page, task.title);
  await expect(page.getByText("第二段任务对话", { exact: true })).toBeVisible();
  await expect(page.locator(".ai-context-trigger")).toContainText(task.title);

  await page.reload();
  await expect(page.getByText("第二段任务对话", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "对话历史" }).click();
  const history = page.getByLabel("对话列表");
  expect(await history.locator(".ai-history-item").count()).toBeGreaterThanOrEqual(3);
  await expect(history.getByText("当前任务", { exact: true })).toHaveCount(2);
  await expect(history.getByText("独立对话", { exact: true })).toHaveCount(1);
  await history.locator(`[data-conversation-id="${first.conversationId}"]`).click();
  await expect(page.getByText("第一段任务对话", { exact: true })).toBeVisible();
  await expect(page.locator(".ai-context-trigger")).toContainText(task.title);
  await page.getByRole("button", { name: "对话配置" }).click();
  await expect(page.getByLabel("对话引擎选择")).toHaveValue(`${configuredProvider.id}::${configuredProvider.default_model.id}`);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "对话历史" }).click();
  await page.getByLabel("对话列表").locator(`[data-conversation-id="${independentId}"]`).click();
  await expect(page.locator(".ai-context-trigger")).toContainText("独立对话");
  await page.reload();
  await expect(page.locator(".ai-context-trigger")).toContainText("独立对话");
  expect(await page.evaluate(() => JSON.parse(sessionStorage.getItem("nautilus.ai.learning-room") ?? "{}").conversationId)).toBe(independentId);
});

test("global plan and task entries persist distinct AI context scopes", async ({ page }) => {
  const task = await createTask(page.request, "分级上下文");
  await configureProvider(page.request, "mock-success");
  await page.reload();

  const companion = page.getByRole("complementary", { name: "AI 学习伙伴" });
  await expect(companion.getByText("全局上下文", { exact: true })).toBeVisible();
  await companion.getByRole("button", { name: "进入学习室" }).click();
  await expect(page.getByRole("button", { name: "当前对话信息" })).toContainText("全局学习工作区");
  let sent = waitForSentRun(page);
  await page.getByLabel("输入学习问题").fill("请从全局安排学习顺序");
  await page.getByRole("button", { name: "发送问题" }).click();
  const globalRun = await sent;
  await expect.poll(async () => (await getConversation(page.request, globalRun.conversationId)).active_run).toBeNull();
  const globalConversation = await getConversation(page.request, globalRun.conversationId);
  expect(globalConversation.conversation.context_scope).toBe("global");
  expect(globalConversation.context.scope_kind).toBe("global");

  await page.getByRole("button", { name: "返回工作区" }).click();
  await page.getByRole("button", { name: "计划", exact: true }).click();
  await page.getByRole("heading", { name: task.goalTitle }).click();
  await expect(page.getByRole("complementary", { name: "AI 学习伙伴" }).getByText("计划级上下文", { exact: true })).toBeVisible();
  await page.getByRole("complementary", { name: "AI 学习伙伴" }).getByRole("button", { name: "进入学习室" }).click();
  await expect(page.getByRole("button", { name: "当前对话信息" })).toContainText(task.goalTitle);
  sent = waitForSentRun(page);
  await page.getByLabel("输入学习问题").fill("检查这个计划的进度");
  await page.getByRole("button", { name: "发送问题" }).click();
  const planRun = await sent;
  await expect.poll(async () => (await getConversation(page.request, planRun.conversationId)).active_run).toBeNull();
  const planConversation = await getConversation(page.request, planRun.conversationId);
  expect(planConversation.conversation.context_scope).toBe("plan");
  expect(planConversation.context.goal_id).toBe(task.goalId);

  await page.getByRole("button", { name: "返回工作区" }).click();
  await page.getByRole("button", { name: "今日", exact: true }).click();
  await openLearningRoom(page, task.title);
  sent = waitForSentRun(page);
  await page.getByLabel("输入学习问题").fill("只讲解当前任务");
  await page.getByRole("button", { name: "发送问题" }).click();
  const taskRun = await sent;
  const taskConversation = await getConversation(page.request, taskRun.conversationId);
  expect(taskConversation.conversation.context_scope).toBe("task");
  expect(taskConversation.context.task_id).toBe(task.id);
});

test("conversation history supports inline rename and confirmed soft delete", async ({ page }) => {
  const task = await createTask(page.context().request, "历史管理");
  const firstResponse = await page.request.post("/api/ai/conversations", {
    data: { task_id: task.id, title: "待修改标题" },
  });
  const secondResponse = await page.request.post("/api/ai/conversations", {
    data: { task_id: task.id, title: "准备删除的对话" },
  });
  expect(firstResponse.status()).toBe(201);
  expect(secondResponse.status()).toBe(201);
  const firstId = (await firstResponse.json()).conversation.id as string;
  const secondId = (await secondResponse.json()).conversation.id as string;

  await page.reload();
  await openLearningRoom(page, task.title);
  await expect(page.getByRole("heading", { name: "准备删除的对话" })).toBeVisible();
  await page.getByRole("button", { name: "对话历史" }).click();

  const history = page.getByLabel("对话列表");
  const firstRow = history.locator(`[data-conversation-id="${firstId}"]`);
  await firstRow.getByRole("button", { name: "编辑对话标题：待修改标题" }).click();
  const titleInput = firstRow.getByRole("textbox", { name: "编辑对话标题" });
  await titleInput.fill("手动整理后的标题");
  await titleInput.press("Enter");
  await expect(firstRow.getByText("手动整理后的标题", { exact: true })).toBeVisible();
  const renamed = await getConversation(page.request, firstId);
  expect(renamed.conversation.title).toBe("手动整理后的标题");
  expect(renamed.conversation.title_source).toBe("manual");

  const secondRow = history.locator(`[data-conversation-id="${secondId}"]`);
  await secondRow.getByRole("button", { name: "删除对话：准备删除的对话" }).click();
  const confirmDialog = page.getByRole("dialog", { name: "删除“准备删除的对话”？" });
  await expect(confirmDialog).toBeVisible();
  expect((await page.request.get(`/api/ai/conversations/${secondId}`)).status()).toBe(200);
  await confirmDialog.getByRole("button", { name: "取消" }).click();
  await expect(confirmDialog).toBeHidden();
  expect((await page.request.get(`/api/ai/conversations/${secondId}`)).status()).toBe(200);

  await secondRow.getByRole("button", { name: "删除对话：准备删除的对话" }).click();
  const deleteRequest = page.waitForResponse((response) =>
    response.url().includes(`/api/ai/conversations/${secondId}`) && response.request().method() === "DELETE",
  );
  await page.getByRole("dialog", { name: "删除“准备删除的对话”？" }).getByRole("button", { name: "确认删除" }).click();
  expect((await deleteRequest).status()).toBe(204);
  await expect(page.locator(`[data-conversation-id="${secondId}"]`)).toHaveCount(0);
  expect((await page.request.get(`/api/ai/conversations/${secondId}`)).status()).toBe(404);
  await expect(page.getByRole("heading", { name: "手动整理后的标题" })).toBeVisible();
});

test("explicit task entry ignores a stale independent conversation id", async ({ page }) => {
  const task = await createTask(page.context().request, "隔离独立会话");
  const independentResponse = await page.context().request.post("/api/ai/conversations", { data: {} });
  expect(independentResponse.status()).toBe(201);
  const independentId = (await independentResponse.json()).conversation.id as string;
  await page.evaluate(({ taskId, conversationId }) => {
    sessionStorage.setItem("nautilus.ai.learning-room", JSON.stringify({
      taskId,
      conversationId,
      runId: null,
      open: false,
    }));
  }, { taskId: task.id, conversationId: independentId });

  await page.reload();
  await openLearningRoom(page, task.title);
  await expect(page.getByRole("heading", { name: "新的学习对话" })).toBeVisible();
  await expect(page.locator(".ai-context-trigger")).toContainText(task.title);
  expect(await page.evaluate(() => JSON.parse(sessionStorage.getItem("nautilus.ai.learning-room") ?? "{}").conversationId)).toBeNull();
});

test("AI learning room stays within the viewport at desktop, compact, and mobile sizes", async ({ page }) => {
  const task = await createTask(page.context().request, "三档视口稳定");
  await configureProvider(page.context().request, "mock-success");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.reload();
  await openLearningRoom(page, task.title);

  for (const viewport of [{ width: 1440, height: 1000 }, { width: 1024, height: 640 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.reload();
    await expect(page.getByRole("heading", { name: "AI 学习室" })).toBeVisible();
    const metrics = await page.evaluate(() => {
      const messageList = document.querySelector(".ai-message-list")!.getBoundingClientRect();
      const room = document.querySelector(".ai-room")!.getBoundingClientRect();
      return {
        scrollWidth: document.documentElement.scrollWidth,
        scrollHeight: document.documentElement.scrollHeight,
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight,
        roomBottom: room.bottom,
        messageHeight: messageList.height,
      };
    });
    expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.viewportWidth);
    expect(metrics.scrollHeight).toBeLessThanOrEqual(metrics.viewportHeight);
    expect(metrics.roomBottom).toBeLessThanOrEqual(metrics.viewportHeight);
    expect(metrics.messageHeight).toBeGreaterThan(metrics.viewportHeight * 0.35);
  }
});

test("provider settings discover and cache models, then choose a model for connection test", async ({ page }) => {
  const task = await createTask(page.context().request, "模型发现");
  await configureProvider(page.context().request, "mock-success");
  await page.reload();
  await openLearningRoom(page, task.title);
  await page.getByRole("button", { name: "AI 提供方设置" }).click();

  const modelInput = page.getByRole("combobox", { name: "模型" });
  await modelInput.click();
  await expect(page.getByRole("option", { name: "mock-reasoning" })).toBeVisible();
  await page.getByRole("heading", { name: "AI 提供方设置" }).click();
  await expect(page.getByRole("option", { name: "mock-reasoning" })).toBeHidden();
  await modelInput.click();
  await page.getByRole("option", { name: "mock-reasoning" }).click();
  await modelInput.click();
  await expect(page.getByText(/缓存.*6 个模型|已读取缓存 6 个模型/)).toBeVisible();
  await page.getByRole("heading", { name: "AI 提供方设置" }).click();
  await expect(page.getByRole("option", { name: "mock-reasoning" })).toBeHidden();

  await page.getByRole("button", { name: "连接测试" }).click();
  const testDialog = page.getByRole("dialog", { name: "选择要测试的模型" });
  await expect(testDialog).toBeVisible();
  await testDialog.getByRole("button", { name: /mock-reasoning/ }).click();
  await testDialog.getByRole("button", { name: "测试所选模型" }).click();
  await expect(page.locator(".ai-provider-success")).toContainText("连接成功 · mock-reasoning");
  await expect(page.getByLabel("该模型连接测试成功")).toBeVisible();

  const stats = await mockStats(page.context().request);
  expect(stats.requests.models).toBe(1);
  expect(stats.requests["mock-reasoning"]).toBe(1);
});

test("reasoning returned by provider is visible while streaming and folded after completion", async ({ page }) => {
  const task = await createTask(page.context().request, "推理展示");
  await configureProvider(page.context().request, "mock-reasoning");
  await page.reload();
  await openLearningRoom(page, task.title);

  const sent = waitForSentRun(page);
  await page.getByLabel("输入学习问题").fill("请展示推理与答案。");
  await page.getByLabel("输入学习问题").press("Enter");
  const { conversationId } = await sent;
  const reasoning = page.locator(".ai-reasoning");
  await expect(reasoning).toHaveAttribute("open", "");
  await expect(reasoning).toContainText("先识别题目条件");
  await expect(reasoning).not.toHaveAttribute("open", "", { timeout: 10_000 });
  await expect(reasoning.getByText("已思考 · 点击展开")).toBeVisible();

  await page.reload();
  await expect(page.locator(".ai-reasoning")).toContainText("先识别题目条件");
  await expect(page.locator(".ai-reasoning")).not.toHaveAttribute("open", "");
  const detail = await getConversation(page.context().request, conversationId);
  expect(detail.messages[1].reasoning_content).toContain("再核对推导路径");
});

test("AI learning cancel stops a slow stream and keeps partial text", async ({ page }) => {
  const task = await createTask(page.context().request, "取消流");
  await configureProvider(page.context().request, "mock-slow");
  await page.reload();
  await openLearningRoom(page, task.title);

  const sent = waitForSentRun(page);
  await page.getByLabel("输入学习问题").fill("请持续讲解，稍后我会取消。");
  await page.getByRole("button", { name: "发送问题" }).click();
  const { conversationId } = await sent;

  await expect(page.getByText("慢速块 1。", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "取消生成" }).click();
  await expect.poll(async () => (await getConversation(page.request, conversationId)).active_run).toBeNull();

  const detail = await getConversation(page.context().request, conversationId);
  expect(detail.messages).toHaveLength(2);
  expect(detail.messages[1].status).toBe("canceled");
  expect(detail.messages[1].content).toContain("慢速块 1");

  const stats = await mockStats(page.context().request);
  expect(stats.delivered["mock-slow"]).toBeLessThan(60);
});

test("AI learning reports provider errors without duplicating messages", async ({ page }) => {
  const task = await createTask(page.context().request, "错误流");
  await configureProvider(page.context().request, "mock-error");
  await page.reload();
  await openLearningRoom(page, task.title);

  const sent = waitForSentRun(page);
  await page.getByLabel("输入学习问题").fill("触发测试提供方错误。");
  await page.getByRole("button", { name: "发送问题" }).click();
  const { conversationId } = await sent;

  await expect(page.getByRole("alert")).toContainText(/API 密钥|提供方|失败/);
  const detail = await getConversation(page.context().request, conversationId);
  expect(detail.active_run).toBeNull();
  expect(detail.messages).toHaveLength(2);
  expect(detail.messages[1].status).toBe("failed");
  expect(JSON.stringify(detail)).not.toContain(fakeApiKey);

  const stats = await mockStats(page.context().request);
  expect(stats.requests["mock-error"]).toBe(1);
});

test("refresh and repeated submission reuse the same run without appending messages", async ({ page }) => {
  const task = await createTask(page.context().request, "刷新流");
  await configureProvider(page.context().request, "mock-refresh");
  await page.reload();
  await openLearningRoom(page, task.title);

  const sentRequest = page.waitForRequest((request) =>
    request.url().includes("/api/ai/conversations/") &&
    request.url().endsWith("/messages") &&
    request.method() === "POST",
  );
  const sentResponse = waitForSentRun(page);
  await page.getByLabel("输入学习问题").fill("刷新后继续同一次回答。");
  await page.getByRole("button", { name: "发送问题" }).click();
  const request = await sentRequest;
  const originalPayload = request.postDataJSON() as { content: string; client_message_id: string };
  const { conversationId, runId } = await sentResponse;

  await expect(page.getByText("刷新块 1。", { exact: false })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "AI 学习室" })).toBeVisible();

  const repeated = await page.context().request.post(
    `/api/ai/conversations/${conversationId}/messages`,
    { data: originalPayload },
  );
  expect(repeated.status()).toBe(202);
  const repeatedBody = await repeated.json();
  expect(repeatedBody.created).toBe(false);
  expect(repeatedBody.run.id).toBe(runId);

  await expect(page.getByText("刷新块 12。", { exact: false })).toBeVisible({ timeout: 10_000 });
  await expect.poll(async () => {
    const current = await getConversation(page.context().request, conversationId);
    return current.active_run;
  }).toBeNull();
  const detail = await getConversation(page.context().request, conversationId);
  expect(detail.active_run).toBeNull();
  expect(detail.messages).toHaveLength(2);
  expect(detail.messages.map((message: Message) => message.sequence)).toEqual([0, 1]);

  const stats = await mockStats(page.context().request);
  expect(stats.requests["mock-refresh"]).toBe(1);
});

async function authorize(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "授权此设备，继续学习。" })).toBeVisible();
  await page.getByRole("button", { name: "填入当前授权码" }).click();
  await page.getByRole("button", { name: "进入工作区" }).click();
  await expect(page.getByRole("navigation", { name: "当前视角" })).toBeVisible();
}

async function openLearningRoom(page: Page, taskTitle: string) {
  await page.getByRole("button", { name: `选择任务：${taskTitle}` }).click();
  await page.getByRole("button", { name: new RegExp(`与 AI 学习.*${escapeRegex(taskTitle)}`) }).click();
}

async function waitForSentRun(page: Page) {
  const response = await page.waitForResponse((candidate) =>
    candidate.url().includes("/api/ai/conversations/") &&
    candidate.url().endsWith("/messages") &&
    candidate.request().method() === "POST",
  );
  expect(response.status()).toBe(202);
  const body = await response.json();
  return {
    conversationId: body.run.conversation_id as string,
    runId: body.run.id as string,
  };
}

async function configureProvider(request: APIRequestContext, model: string) {
  const response = await request.put("/api/ai/provider", {
    data: {
      display_name: "Playwright Mock provider",
      base_url: mockProviderBaseUrl,
      model,
      api_key: fakeApiKey,
      enabled: true,
      request_timeout_seconds: 15,
    },
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).provider;
}

async function createTask(request: APIRequestContext, suffix: string) {
  const now = new Date();
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 30);
  const title = `Playwright AI ${suffix}`;
  const response = await request.post("/api/plans/manual", {
    data: {
      goal_title: `Playwright AI 计划 ${suffix}`,
      description: "仅存放在隔离临时数据库中的自动化测试数据",
      start_date: localDateKey(now),
      end_date: localDateKey(end),
      subject_title: "自动化测试",
      topic_title: "AI 学习纵切片",
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
  return {
    goalId: plan.id as string,
    goalTitle: plan.title as string,
    id: plan.subjects[0].topics[0].tasks[0].id as string,
    title,
  };
}

async function getConversation(request: APIRequestContext, conversationId: string) {
  const response = await request.get(`/api/ai/conversations/${conversationId}`);
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function resetMockProvider(request: APIRequestContext) {
  const response = await request.post(`${mockProviderBaseUrl.replace(/\/v1$/, "")}/__mock__/reset`);
  expect(response.ok()).toBeTruthy();
}

async function mockStats(request: APIRequestContext): Promise<MockStats> {
  const response = await request.get(`${mockProviderBaseUrl.replace(/\/v1$/, "")}/__mock__/stats`);
  expect(response.ok()).toBeTruthy();
  return response.json();
}

function localDateKey(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function escapeRegex(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

type Message = {
  role: "user" | "assistant" | "system";
  content: string;
  reasoning_content: string;
  sequence: number;
  status: "complete" | "streaming" | "failed" | "canceled";
};

type MockStats = {
  requests: Record<string, number | undefined>;
  delivered: Record<string, number | undefined>;
  disconnects: Record<string, number | undefined>;
};
