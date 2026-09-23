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
  await expect(page.getByRole("navigation", { name: "当前视角" })).toHaveCount(0);

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
