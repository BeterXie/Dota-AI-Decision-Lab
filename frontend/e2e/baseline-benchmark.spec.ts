import { expect, test } from "playwright/test";

test("keeps the performance route focused on the current leaderboard without duplicating benchmark reports", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN"));
  let benchmarkRequests = 0;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/session") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ enabled: true, authenticated: false, user: null, entitlements: [], grants: [] })
      });
      return;
    }
    if (path === "/api/review/ai-quality/leaderboard") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ scope: "ALL_CANONICAL_EVENTS", ranking: "REALIZED_ROI_THEN_PNL", experiments: [] })
      });
      return;
    }
    if (path === "/api/review/ai-quality/benchmark") benchmarkRequests += 1;
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });

  await page.goto("/performance");

  await expect(page.getByRole("heading", { name: "AI 表现榜" })).toBeVisible();
  await expect(page.getByText("还没有可比较的 AI 配置。", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "AI 基线 Benchmark" })).toHaveCount(0);
  expect(benchmarkRequests).toBe(0);
});
