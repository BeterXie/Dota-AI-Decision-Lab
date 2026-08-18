import { expect, test, type Page } from "playwright/test";

const teamDirectory = [
  {
    id: "spirit",
    name: "Team Spirit",
    slug: "team-spirit",
    short_name: "Spirit",
    valve_team_id: 7119388,
    identity_source: "registry",
    country_code: "RS",
    logo_url: null,
    logo_source: "valve-steam",
    website_url: null,
    source_url: "https://www.opendota.com/teams/7119388",
    observed_at: "2026-08-18T02:00:00Z"
  },
  {
    id: "liquid",
    name: "Team Liquid",
    slug: "team-liquid",
    short_name: "Liquid",
    valve_team_id: null,
    identity_source: "registry",
    country_code: "NL",
    logo_url: null,
    logo_source: null,
    website_url: null,
    source_url: null,
    observed_at: "2026-08-18T02:00:00Z"
  }
];

const teamDetail = {
  ...teamDirectory[0],
  current_roster: [
    roster("r1", "Yatoro", 1, "PLAYER"),
    roster("r2", "Larl", 2, "PLAYER"),
    roster("r3", "Collapse", 3, "PLAYER"),
    {
      ...roster("r-coach", "Silent", null, "COACH", "STAFF"),
      source_name: "official-team-site"
    }
  ],
  roster_history: [
    roster("r1", "Yatoro", 1, "PLAYER"),
    roster("r2", "Larl", 2, "PLAYER"),
    roster("r3", "Collapse", 3, "PLAYER"),
    {
      ...roster("r-coach", "Silent", null, "COACH", "STAFF"),
      source_name: "official-team-site"
    },
    {
      ...roster("old-1", "Former Support", 5, "PLAYER"),
      valid_from: "2025-01-01T00:00:00Z",
      valid_to: "2026-05-01T00:00:00Z",
      source_name: "official-announcement"
    }
  ]
};

const liveMatch = match({
  id: "live-map",
  phase: "LIVE",
  scheduled_at: "2026-08-18T10:00:00Z",
  series_score: { team_a: 1, team_b: 0 }
});
const recentMatch = match({
  id: "recent-map",
  phase: "POSTMATCH",
  scheduled_at: "2026-08-17T10:00:00Z",
  series_score: { team_a: 2, team_b: 1 }
});

const anonymousSession = {
  enabled: true,
  authenticated: false,
  user: null,
  entitlements: [],
  grants: [],
  providers: { email: true, google: false, steam: false }
};

function roster(
  id: string,
  name: string,
  position: number | null,
  role: string,
  type: "PLAYER" | "STAFF" = "PLAYER"
) {
  return {
    id,
    subject: {
      type,
      id: `${type.toLowerCase()}-${id}`,
      name,
      account_id: type === "PLAYER" ? 1000 + Number.parseInt(id.replace(/\D/g, "") || "1", 10) : null,
      real_name: null,
      country_code: "RS",
      avatar_url: null
    },
    role,
    position,
    is_standin: false,
    valid_from: "2026-01-01T00:00:00Z",
    valid_to: null,
    source_name: "opendota",
    source_url: "https://www.opendota.com/teams/7119388",
    observed_at: "2026-08-18T02:00:00Z",
    confidence: 0.9
  };
}

function match(overrides: Record<string, unknown>) {
  return {
    id: "map",
    series_id: "series",
    canonical_map_id: "map",
    entity_type: "MAP",
    identity_status: "RESOLVED",
    phase: "PREMATCH",
    map_number: 1,
    valve_match_id: 123456,
    scheduled_at: "2026-08-18T10:00:00Z",
    provider_match_id: 99,
    tournament_name: "TI15 国际邀请赛",
    round: "小组赛",
    raw_status: 1,
    provider_observed_at: "2026-08-18T02:00:00Z",
    team_a: { id: "spirit", name: "Team Spirit" },
    team_b: { id: "liquid", name: "Team Liquid" },
    best_of: 3,
    series_score: null,
    market: [],
    market_quality: null,
    current_market_view: null,
    draft: null,
    live: null,
    sync: null,
    latest_snapshot: null,
    decisions: [],
    ...overrides
  };
}

async function installRoutes(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN");
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let payload: unknown = null;
    let status = 200;
    if (path === "/api/auth/session") payload = anonymousSession;
    else if (path === "/api/matches") payload = [liveMatch, recentMatch];
    else if (path === "/api/teams") payload = teamDirectory;
    else if (path === "/api/teams/by-slug/team-spirit") payload = teamDetail;
    else if (path === "/api/maps/live-map") {
      payload = {
        ...liveMatch,
        market_timeline: [],
        live_timeline: [],
        checkpoint_decisions: [],
        future_odds: [],
        result: null,
        result_evidence: []
      };
    } else status = 404;
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(payload) });
  });
  await page.route("**/apps/dota2/images/team_logos/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" fill="currentColor"/></svg>'
    });
  });
}

test("public team page renders maintained roster, staff, matches and history", async ({ page }) => {
  await installRoutes(page);
  await page.goto("/teams/team-spirit");

  await expect(page.getByRole("heading", { name: "Team Spirit", level: 1 })).toBeVisible();
  await expect(page.getByText("3 名当前选手", { exact: true })).toBeVisible();
  await expect(page.getByText("Yatoro", { exact: true })).toBeVisible();
  await expect(page.getByText("Larl", { exact: true })).toBeVisible();
  await expect(page.getByText("Collapse", { exact: true })).toBeVisible();
  await expect(page.getByText("Silent", { exact: true })).toBeVisible();
  await expect(page.getByText("Former Support", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "正在参加 / 即将比赛" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "最近比赛" })).toBeVisible();
  await expect(page.getByRole("link", { name: "比赛详情" })).toHaveCount(2);

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noOverflow).toBe(true);
});

test("team pages remain usable on a narrow mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installRoutes(page);
  await page.goto("/teams/team-spirit");

  await expect(page.getByRole("heading", { name: "Team Spirit", level: 1 })).toBeVisible();
  await expect(page.locator(".team-player-card")).toHaveCount(3);
  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noOverflow).toBe(true);
});

test("match team crests link into the maintained team profile", async ({ page }) => {
  await installRoutes(page);
  await page.goto("/matches/live-map");

  await expect(page.locator('a.team-crest[href="/teams/team-spirit"]')).toBeVisible();
  await expect(page.locator('a.team-crest[href="/teams/team-liquid"]')).toBeVisible();
});
