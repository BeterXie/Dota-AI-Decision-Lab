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

  await expect(page.getByRole("heading", { name: "AI 表现榜属于全局 Pro" })).toBeVisible();
  await expect(
    page.getByText(
      "这里比较不同 AI 配置跨赛事的 Shadow 表现、预测质量和逐笔审计，因此只开放给全局 Pro；单个系列赛通行证不会解锁全局历史。",
      { exact: true }
    )
  ).toBeVisible();
  await expect(page.getByText("当前账号尚未拥有全局 Pro 权限。", { exact: true })).toBeVisible();
  expect(leaderboardRequests).toBe(0);
});
