import { defineConfig } from "playwright/test";

const externalBaseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL;
const localEdge = process.platform === "win32" ? { channel: "msedge" } : {};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: "line",
  expect: { timeout: 10_000 },
  use: {
    baseURL: externalBaseUrl ?? "http://127.0.0.1:4173",
    ...localEdge,
    screenshot: "only-on-failure",
    trace: "retain-on-failure"
  },
  webServer: externalBaseUrl
    ? undefined
    : {
        command: "npx vite --host 127.0.0.1 --port 4173",
        url: "http://127.0.0.1:4173",
        reuseExistingServer: !process.env.CI
      },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 1000 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 } } }
  ]
});
