import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

const frontendPort = Number(process.env.NAUTILUS_E2E_FRONTEND_PORT ?? 5186);
const mockProviderPort = Number(process.env.NAUTILUS_E2E_MOCK_PROVIDER_PORT ?? 8013);
const e2eDataDir =
  process.env.NAUTILUS_E2E_DATA_DIR ?? join(tmpdir(), `nautilus-playwright.${process.pid}-${Date.now()}`);
process.env.NAUTILUS_E2E_DATA_DIR = e2eDataDir;
process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL = `http://127.0.0.1:${mockProviderPort}/v1`;
const systemChromiumCandidates = [
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
  "/home/kingdom/.local/bin/chromium",
  "/usr/bin/chromium",
  "/usr/bin/google-chrome",
].filter((candidate): candidate is string => Boolean(candidate));
const executablePath = systemChromiumCandidates.find((candidate) => existsSync(candidate));

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  reporter: [["list"]],
  globalTeardown: "./e2e/global-teardown.ts",
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    browserName: "chromium",
    headless: true,
    launchOptions: executablePath ? { executablePath } : undefined,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "bash ../scripts/start-e2e.sh",
    env: {
      NAUTILUS_E2E_DATA_DIR: e2eDataDir,
      NAUTILUS_E2E_MOCK_PROVIDER_PORT: String(mockProviderPort),
    },
    url: `http://127.0.0.1:${frontendPort}`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
