import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests drive a real browser against the whole stack. Start it first:
 *
 *   docker compose up --build --wait
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
    baseURL: process.env.HARTRIAGE_WEB_URL ?? "http://localhost:8280",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], permissions: ["clipboard-read", "clipboard-write"] } }],
});
