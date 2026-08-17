import { expect, test } from "playwright/test";

test("keeps the cross-event AI performance dashboard global-Pro only", async ({ page }) => {
  let leaderboardRequests = 0;
  await page.addInitScript(() => window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN"));
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        enabled: true,
        authenticated: true,
        user: {
          id: "99999999-9999-9999-9999-999999999999",
          email: "series@example.com",
          email_verified_at: "2026-08-15T10:00:00Z",
          created_at: "2026-08-15T10:00:00Z"
        },
        entitlements: [],
        grants: [
          {
            entitlement: "ai_decisions",
            scope_type: "SERIES",
            scope_ref: "22222222-2222-2222-2222-222222222222",
            source: "PADDLE",
            starts_at: "2026-08-17T10:00:00Z",
            expires_at: "2026-08-20T10:00:00Z"
          }
        ]
      })
    });
  });
  await page.route("**/api/review/ai-quality/leaderboard", async (route) => {
    leaderboardRequests += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ scope: "ALL_CANONICAL_EVENTS", ranking: "REALIZED_ROI_THEN_PNL", experiments: [] })
    });
  });

  await page.goto("/performance");

  await expect(page.getByRole("heading", { name: "AI 表现榜属于 Pro 功能" })).toBeVisible();
  await expect(
    page.getByText(
      "这里会比较不同模型跨赛事的长期模拟表现和预测质量，因此需要全局 Pro。赛事 Pass 仍然只覆盖购买的赛事。",
      { exact: true }
    )
  ).toBeVisible();
  await expect(page.getByText("当前账号还不是全局 Pro。", { exact: true })).toBeVisible();
  expect(leaderboardRequests).toBe(0);
});
