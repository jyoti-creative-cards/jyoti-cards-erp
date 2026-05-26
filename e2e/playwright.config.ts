import { defineConfig, devices } from "@playwright/test";

const adminBase = process.env.E2E_ADMIN_BASE_URL || "http://127.0.0.1:3010";
const customerBase = process.env.E2E_CUSTOMER_BASE_URL || "http://127.0.0.1:3000";

export default defineConfig({
  testDir: "./tests",
  globalSetup: require.resolve("./global-setup"),
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["list"]],
  timeout: 60_000,
  use: {
    trace: "on-first-retry",
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: "admin",
      testMatch: /admin.*\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], baseURL: adminBase },
    },
    {
      name: "customer",
      testMatch: /customer.*\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], baseURL: customerBase },
    },
    {
      name: "api",
      testMatch: /api.*\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
