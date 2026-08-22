import { expect, test } from "playwright/test";

const anonymousSession = {
  enabled: true,
  authenticated: false,
  user: null,
  entitlements: [],
  grants: [],
  providers: { email: true, google: false, steam: false }
};

const matches = [
  {
    id: "ti-live-map-1",
    series_id: "ti-series-a",
    canonical_map_id: "ti-live-map-1",
    entity_type: "MAP",
    identity_status: "RESOLVED",
    phase: "LIVE_DATA_DELAYED",
    map_number: 1,
    canonical_event_id: "event-ti",
    scheduled_at: "2026-08-18T09:00:00Z",
    tournament_name: "TI15 国际邀请赛",
    round: "小组赛",
    team_a: { id: "liquid", name: "Team Liquid" },
    team_b: { id: "yandex", name: "Team Yandex" },
    best_of: 3,
    series_score: { team_a: 1, team_b: 1 },
    provider_observed_at: "2026-08-18T09:19:00Z",
    live: {
      game_time_seconds: 1112,
      last_message_received_at: "2026-08-18T09:18:32Z",
      effective_state_age_seconds: 88
    }
  },
  {
    id: "ti-live-map-2",
    series_id: "ti-series-a",
    canonical_map_id: "ti-live-map-2",
    entity_type: "MAP",
    identity_status: "RESOLVED",
    phase: "PREMATCH",
    map_number: 2,
    scheduled_at: "2026-08-18T10:00:00Z",
    tournament_name: "TI15 国际邀请赛",
    round: "小组赛",
    team_a: { id: "liquid", name: "Team Liquid" },
    team_b: { id: "yandex", name: "Team Yandex" },
    best_of: 3,
    series_score: { team_a: 1, team_b: 1 }
  },
  {
    id: "ti-upcoming",
    series_id: "ti-series-b",
    canonical_map_id: "ti-upcoming",
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
  },
  {
    id: "dreamleague-final",
    series_id: "dreamleague-series",
    canonical_map_id: "dreamleague-final",
    entity_type: "MAP",
    identity_status: "RESOLVED",
    phase: "POSTMATCH",
    map_number: 2,
    scheduled_at: "2026-08-17T18:00:00Z",
    tournament_name: "DreamLeague S24",
    round: "淘汰赛",
    team_a: { id: "tundra", name: "Tundra Esports" },
    team_b: { id: "betboom", name: "BetBoom Team" },
    best_of: 3,
    series_score: { team_a: 2, team_b: 0 }
  }
];

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN");
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const payload = path === "/api/auth/session" ? anonymousSession : path === "/api/matches" ? matches : null;
    await route.fulfill({
      status: payload === null ? 404 : 200,
      contentType: "application/json",
      body: JSON.stringify(payload)
    });
  });
});

test("event directory is public, searchable and drills into the event with the canonical official slug", async ({ page }) => {
  await page.goto("/events");

  await expect(page.getByRole("heading", { name: "全球 Dota 赛事，一处追踪" })).toBeVisible();
  if ((page.viewportSize()?.width ?? 1440) >= 700) {
    await expect(page.getByRole("link", { name: "赛事", exact: true })).toHaveAttribute("aria-current", "page");
  }

  const tiCard = page.locator(".event-directory-card").filter({ hasText: "The International 2026" });
  const dreamleagueCard = page.locator(".event-directory-card").filter({ hasText: "DreamLeague S24" });
  await expect(tiCard).toBeVisible();
  await expect(dreamleagueCard).toBeVisible();
  await expect(tiCard).toContainText("2");
  await expect(tiCard.getByRole("link", { name: "查看赛事" })).toHaveAttribute(
    "href",
    "/events/the-international-2026"
  );
  await expect(tiCard.locator(".event-mark")).toBeAttached();
  await expect(dreamleagueCard.locator(".event-mark")).toHaveAttribute("data-event-art-source", "fallback");

  await page.getByLabel("搜索赛事").fill("DreamLeague");
  await expect(dreamleagueCard).toBeVisible();
  await expect(tiCard).toHaveCount(0);

  await page.getByLabel("搜索赛事").fill("");
  await tiCard.getByRole("link", { name: "查看赛事" }).click();
  await expect(page).toHaveURL(/\/events\/the-international-2026$/);
  await expect(page.getByRole("heading", { name: "The International 2026" })).toBeVisible();
});

test("event detail deduplicates series, shows team crests and keeps free versus pass boundaries clear", async ({ page }) => {
  await page.goto("/events/the-international-2026");

  await expect(page.getByRole("heading", { name: "The International 2026" })).toBeVisible();
  await expect(page.getByText("当前与近期比赛", { exact: true })).toBeVisible();
  await expect(page.locator(".event-series-row")).toHaveCount(1);
  await expect(page.getByText("Team Spirit").first()).toBeVisible();
  await expect(page.locator(".event-featured-timing > span").nth(0)).toContainText("第 1 局仍在进行");
  await expect(page.locator(".event-featured-timing > span").nth(1)).toContainText("18:32");
  await expect(page.locator(".event-series-row")).not.toContainText("局记录");
  await expect(page.locator(".team-crest").first()).toBeAttached();
  await expect(page.getByRole("heading", { name: "比赛公开，AI 按权限解锁" })).toBeVisible();
  const publicAccessDetail = page.getByText("赛程、对阵、比分、赛果与基础比赛情报无需登录。", { exact: true });
  if ((page.viewportSize()?.width ?? 1440) <= 760) await expect(publicAccessDetail).toBeHidden();
  else await expect(publicAccessDetail).toBeVisible();
  await expect(page.getByRole("link", { name: /查看赛事 Pass/ })).toHaveAttribute("href", "/billing?event=event-ti");
  await expect(page.getByRole("link", { name: /本赛事 AI 复盘/ })).toHaveAttribute("href", /event=event-ti/);

  await page.getByRole("button", { name: "已结束" }).click();
  await expect(page).toHaveURL(/\?tab=completed$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/events\/the-international-2026$/);
  await expect(page.getByRole("button", { name: "总览" })).toHaveAttribute("aria-pressed", "true");

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noOverflow).toBe(true);
});

test("source TI15 names resolve to the canonical official event route", async ({ page }) => {
  await page.goto("/events/the-international-2026");
  await expect(page.getByRole("heading", { name: "The International 2026" })).toBeVisible();
});
