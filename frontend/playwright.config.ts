import { defineConfig } from "@playwright/test";

/**
 * Browser tests against a RUNNING stack (see e2e/README.md):
 *   E2E_WEB  the frontend   (default http://localhost:3000)
 *   E2E_API  the backend    (default http://localhost:8000), started with AUTH_REQUIRED=true
 * Locally E2E_CHANNEL=msedge (or chrome) uses the installed browser instead of a download.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_WEB ?? "http://localhost:3000",
    channel: process.env.E2E_CHANNEL || undefined,
    viewport: { width: 1366, height: 860 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
