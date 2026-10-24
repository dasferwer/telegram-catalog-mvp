import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests", fullyParallel: false, workers: 1,
  use: { baseURL: process.env.BASE_URL || "http://localhost:8088", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  reporter: "list",
});
