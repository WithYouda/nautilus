import { expect, test } from "@playwright/test";
import { authorize, openFactWorkspace } from "./fact-helpers";

const mockProviderBaseUrl =
  process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL ?? "http://127.0.0.1:8013/v1";

test("artifact lifecycle and evidence replay stay separate and recoverable", async ({ page }) => {
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
      const withdrawn = await page.request.post(
        `/api/learning/evidence-claims/${claim.id}/review`,
        {
          data: {
            action: "withdraw",
            reason: "测试隔离：清理旧候选主张",
            request_key: `lifecycle-setup-withdraw-${claim.id}`,
          },
        },
      );
      expect(withdrawn.ok()).toBeTruthy();
    }
  }

  const provider = await page.request.put("/api/ai/provider", {
    data: {
      display_name: "Playwright Evidence Lifecycle Mock",
      base_url: mockProviderBaseUrl,
      model: "mock-evidence",
      api_key: "sk-playwright-evidence-lifecycle",
      enabled: true,
      request_timeout_seconds: 15,
    },
  });
  expect(provider.ok()).toBeTruthy();

  const state = await (await page.request.get("/api/learning/state")).json();
  const standard = state.standards[0];
  const action = await (
    await page.request.post("/api/learning/actions", {
      data: {
        title: "Playwright 证据生命周期行动",
        context_key: "python-regex-basics",
        idempotency_key: "lifecycle-e2e-action",
      },
    })
  ).json();
  const delegation = await (
    await page.request.post("/api/learning/delegations", {
      data: {
        action_id: action.id,
        outcome_id: standard.outcome_id,
        criterion_id: standard.id,
        boundaries: "验证生命周期",
        stop_conditions: "完成生命周期验证",
        time_budget_minutes: 30,
        expected_version: 1,
        idempotency_key: "lifecycle-e2e-delegation",
      },
    })
  ).json();
  const session = await (
    await page.request.post("/api/learning/sessions", {
      data: {
        delegation_id: delegation.id,
        expected_version: 2,
        idempotency_key: "lifecycle-e2e-session",
      },
    })
  ).json();
  const artifact = await (
    await page.request.post("/api/learning/artifacts", {
      data: {
        session_id: session.id,
        content: "regex: ^Lifecycle\\d+$\nsample: Lifecycle42",
        expected_version: 3,
        idempotency_key: "lifecycle-e2e-artifact",
      },
    })
  ).json();
  const analysis = await (
    await page.request.post(`/api/learning/artifacts/${artifact.id}/analysis`, {
      data: { request_key: "lifecycle-e2e-analysis" },
    })
  ).json();
  expect(analysis.claims).toHaveLength(2);

  await page.reload();
  await openFactWorkspace(page);
  await page.getByRole("button", { name: "批量采纳候选主张" }).click();
  await expect(page.getByText("批量采纳完成：2 条主张")).toBeVisible();
  const applicationState = page.locator(".fact-state-list li").filter({ hasText: "application" });
  await expect(applicationState).toContainText("supported");

  await page.getByRole("button", { name: "普通删除" }).click();
  await expect(page.getByText("产出已普通删除，可恢复")).toBeVisible();
  await expect(applicationState).toContainText("awaiting_evidence");

  await page.getByRole("button", { name: "恢复" }).click();
  await expect(page.getByText("产出已恢复")).toBeVisible();
  await expect(applicationState).toContainText("supported");

  await page.getByRole("button", { name: "撤回证据" }).click();
  await expect(page.getByText("产出已撤出当前证据计算")).toBeVisible();
  await expect(applicationState).toContainText("awaiting_evidence");

  await page.getByLabel("彻底删除确认").fill("PURGE");
  await page.getByRole("button", { name: "彻底删除" }).click();
  await expect(page.getByText("产出已彻底删除，依赖主张已失效")).toBeVisible();
  await expect(page.locator(".fact-claim").filter({ hasText: "invalidated" })).toHaveCount(2);

  await page.getByRole("button", { name: "回放证据" }).click();
  await expect(page.getByText(/证据回放完成：\d+ 个事件，\d+ 个聚合/)).toBeVisible();
  await expect(page.locator(".fact-claim").filter({ hasText: "invalidated" })).toHaveCount(2);
  await expect(applicationState).toContainText("awaiting_evidence");
});
