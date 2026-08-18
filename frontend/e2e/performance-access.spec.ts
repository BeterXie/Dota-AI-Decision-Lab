import { expect, test } from "playwright/test";

test("keeps the cross-event AI performance dashboard free for series-pass and free users", async ({ page }) => {
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
            expires_at: null
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

  await expect(page.getByRole("heading", { name: "AI 表现榜" })).toBeVisible();
  await expect(page.getByText("没有匹配的 AI experiment。", { exact: true })).toBeVisible();
  expect(leaderboardRequests).toBeGreaterThan(0);
});
