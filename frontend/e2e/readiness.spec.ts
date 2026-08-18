import { expect, test, type Page } from "playwright/test";

const readiness = {
  report_version: "decision-readiness-v1",
  generated_at: "2026-08-18T12:00:00Z",
  window: {
    from: "2026-08-11T12:00:00Z",
    to: "2026-08-18T12:00:00Z",
    lookback_hours: 168,
    future_series_included: false
  },
  scope: {
    source: "LIQUIPEDIA_BACKED_CANONICAL_SERIES",
    series_count: 3,
    series_limit: 250
  },
  stages: [
    { key: "scheduled", label: "SCHEDULED", count: 3, rate: 1, drop_count: 0 },
    { key: "raybet_linked", label: "RAYBET_LINKED", count: 2, rate: 2 / 3, drop_count: 1 },
    { key: "market_ready", label: "MARKET_READY", count: 2, rate: 2 / 3, drop_count: 0 },
    { key: "map_identity", label: "MAP_IDENTITY", count: 2, rate: 2 / 3, drop_count: 0 },
    { key: "live_ready", label: "LIVE_READY", count: 2, rate: 2 / 3, drop_count: 0 },
    { key: "snapshot_ready", label: "SNAPSHOT_READY", count: 1, rate: 1 / 3, drop_count: 1 },
    { key: "ai_decision", label: "AI_DECISION", count: 1, rate: 1 / 3, drop_count: 0 },
    { key: "result_ready", label: "RESULT_READY", count: 1, rate: 1 / 3, drop_count: 0 },
    { key: "evaluated", label: "EVALUATED", count: 1, rate: 1 / 3, drop_count: 0 }
  ],
  failure_reasons: [
    { stage: "raybet_linked", reason: "RAYBET_IDENTITY_MISSING", count: 1, rate: 1 / 3 },
    { stage: "snapshot_ready", reason: "DRAFT_INCOMPLETE", count: 1, rate: 1 / 3 }
  ],
  series: [
    {
      canonical_series_id: "series-evaluated",
      canonical_event_id: "event-ti",
      event_name: "The International 2026",
      scheduled_at: "2026-08-18T09:00:00Z",
      team_a: { id: "liquid", name: "Team Liquid" },
      team_b: { id: "spirit", name: "Team Spirit" },
      best_of: 3,
      current_stage: "EVALUATED",
      blocker: null,
      facts: {},
      counts: { maps: 2, live_maps: 2, snapshots: 2, successful_decision_snapshots: 2, result_maps: 2, evaluated_snapshots: 2 },
      ai_status_counts: { SUCCESS: 2 }
    },
    {
      canonical_series_id: "series-raybet",
      canonical_event_id: "event-ti",
      event_name: "The International 2026",
      scheduled_at: "2026-08-18T10:00:00Z",
      team_a: { id: "aurora", name: "Aurora" },
      team_b: { id: "xg", name: "Xtreme Gaming" },
      best_of: 3,
      current_stage: "SCHEDULED",
      blocker: { stage: "raybet_linked", reason: "RAYBET_IDENTITY_MISSING" },
      facts: {},
      counts: { maps: 0, live_maps: 0, snapshots: 0, successful_decision_snapshots: 0, result_maps: 0, evaluated_snapshots: 0 },
      ai_status_counts: {}
    },
    {
      canonical_series_id: "series-draft",
      canonical_event_id: "event-ti",
      event_name: "The International 2026",
      scheduled_at: "2026-08-18T11:00:00Z",
      team_a: { id: "falcons", name: "Team Falcons" },
      team_b: { id: "tundra", name: "Tundra Esports" },
      best_of: 3,
      current_stage: "LIVE_READY",
      blocker: { stage: "snapshot_ready", reason: "DRAFT_INCOMPLETE" },
      facts: {},
      counts: { maps: 1, live_maps: 1, snapshots: 0, successful_decision_snapshots: 0, result_maps: 0, evaluated_snapshots: 0 },
      ai_status_counts: {}
    }
  ]
};

async function mockApis(page: Page) {
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
          email: "pro@example.com",
          email_verified_at: "2026-08-15T10:00:00Z",
          created_at: "2026-08-15T10:00:00Z"
        },
        entitlements: ["ai_decisions", "realtime_notifications"],
        grants: []
      })
    });
  });
  await page.route("**/api/review/ai-quality/readiness**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(readiness) });
  });
  await page.route("**/api/review/ai-quality/leaderboard", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ scope: "ALL_CANONICAL_EVENTS", ranking: "REALIZED_ROI_THEN_PNL", experiments: [] })
    });
  });
}

test("shows the production readiness funnel and traces blockers to real series", async ({ page }) => {
  await mockApis(page);
  await page.goto("/performance");

  await expect(page.getByRole("heading", { name: "真实比赛决策就绪度" })).toBeVisible();
  await expect(page.getByText("端到端闭环率")).toBeVisible();
  await expect(page.getByRole("button", { name: /RayBet 绑定.*67%.*掉点/ })).toBeVisible();
  const teamRows = page.locator(".readiness-series-main strong");
  await expect(teamRows.filter({ hasText: "Aurora" })).toBeVisible();
  await expect(teamRows.filter({ hasText: "Team Falcons" })).toBeVisible();

  await page.getByRole("button", { name: /RayBet 身份未匹配/ }).click();

  await expect(teamRows.filter({ hasText: "Aurora" })).toBeVisible();
  await expect(teamRows.filter({ hasText: "Team Falcons" })).toHaveCount(0);
});
