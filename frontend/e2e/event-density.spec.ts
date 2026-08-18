import { expect, test } from "playwright/test";

const session = {
  enabled: true,
  authenticated: false,
  user: null,
  entitlements: [],
  grants: [],
  providers: { email: true, google: false, steam: false }
};

const matches = [
  {
    id: "ti-live-map",
    series_id: "ti-series-a",
    canonical_map_id: "ti-live-map",
    entity_type: "MAP",
    identity_status: "RESOLVED",
    phase: "LIVE",
    map_number: 1,
    scheduled_at: "2026-08-18T09:00:00Z",
    tournament_name: "TI15 国际邀请赛",
    round: "小组赛",
    team_a: { id: "liquid", name: "Team Liquid" },
    team_b: { id: "yandex", name: "Team Yandex" },
    best_of: 3,
    series_score: { team_a: 1, team_b: 1 }
  },
  {
    id: "ti-next-series",
    series_id: "ti-series-b",
    canonical_map_id: "ti-next-series",
    entity_type: "MAP",
    identity_status: "RESOLVED",
    phase: "PREMATCH",
    map_number: 1,
    scheduled_at: "2026-08-18T12:00:00Z",
    tournament_name: "TI15 国际邀请赛",
    round: "小组赛",
    team_a: { id: "spirit", name: "Team Spirit" },
    team_b: { id: "falcons", name: "Team Falcons" },
    best_of: 3,
    series_score: { team_a: 0, team_b: 0 }
  }
];

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN"));
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const payload = path === "/api/auth/session" ? session : path === "/api/matches" ? matches : null;
    await route.fulfill({
      status: payload === null ? 404 : 200,
      contentType: "application/json",
      body: JSON.stringify(payload)
    });
  });
});

test("keeps matches dominant and access guidance secondary on event detail", async ({ page }) => {
  await page.goto(`/events/${encodeURIComponent("TI15 国际邀请赛")}`);

  const schedule = page.locator(".event-schedule-panel");
  const aside = page.locator(".event-detail-aside");
  await expect(schedule).toBeVisible();
  await expect(aside).toBeVisible();
  await expect(page.getByText("对阵与赛果", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "比赛公开，AI 按权限解锁" })).toBeVisible();

  const viewport = page.viewportSize();
  if (viewport && viewport.width >= 1101) {
    const scheduleBox = await schedule.boundingBox();
    const asideBox = await aside.boundingBox();
    expect(scheduleBox).not.toBeNull();
    expect(asideBox).not.toBeNull();
    expect(scheduleBox!.width).toBeGreaterThan(800);
    expect(asideBox!.x).toBeGreaterThan(scheduleBox!.x + scheduleBox!.width - 1);
    expect(Math.abs(asideBox!.y - scheduleBox!.y)).toBeLessThan(2);
  }

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noOverflow).toBe(true);
});
