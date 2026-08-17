import { expect, test, type Page } from "playwright/test";

const publicMatch = {
  id: "map-live",
  series_id: "series-live",
  canonical_map_id: "map-live",
  entity_type: "MAP",
  identity_status: "RESOLVED",
  phase: "LIVE",
  map_number: 2,
  valve_match_id: 123456,
  scheduled_at: "2026-08-18T09:00:00Z",
  provider_match_id: 99,
  tournament_name: "TI15 国际邀请赛",
  round: "小组赛",
  raw_status: 1,
  provider_observed_at: "2026-08-18T09:20:00Z",
  team_a: { id: "liquid", name: "Team Liquid" },
  team_b: { id: "spirit", name: "Team Spirit" },
  best_of: 3,
  series_score: { team_a: 1, team_b: 1 },
  market: [],
  market_quality: null,
  current_market_view: {
    team_a: { odds_id: 1, selection_team_id: "liquid", price: 1.72, implied_probability: 0.581, fair_probability: 0.55 },
    team_b: { odds_id: 2, selection_team_id: "spirit", price: 2.1, implied_probability: 0.476, fair_probability: 0.45 },
    overround: 0.057,
    quality: { eligible: true, blockers: [], warnings: [], metadata_version: "v1", paired_at: "2026-08-18T09:20:00Z", pair_skew_seconds: 0 }
  },
  draft: {
    complete: true,
    blockers: [],
    warnings: [],
    observed_at: "2026-08-18T09:05:00Z",
    statistics_cutoff: "2026-08-18T08:55:00Z",
    features: null,
    roster_ready_count: 10,
    hero_ready_count: 10,
    slots: [
      { side: "radiant", position: 1, account_id: 1, canonical_player_id: "p1", player_name: "miCKe", hero_id: 1, hero_name: "Juggernaut" },
      { side: "radiant", position: 2, account_id: 2, canonical_player_id: "p2", player_name: "Nisha", hero_id: 2, hero_name: "Puck" },
      { side: "dire", position: 1, account_id: 3, canonical_player_id: "p3", player_name: "Yatoro", hero_id: 3, hero_name: "Morphling" },
      { side: "dire", position: 2, account_id: 4, canonical_player_id: "p4", player_name: "Larl", hero_id: 4, hero_name: "Invoker" }
    ]
  },
  live: {
    game_time_seconds: 1275,
    radiant_kills: 14,
    dire_kills: 11,
    radiant_nw_lead: 3400,
    first_blood: "radiant",
    received_at: "2026-08-18T09:20:00Z",
    last_message_received_at: "2026-08-18T09:20:00Z",
    last_state_change_received_at: "2026-08-18T09:19:58Z",
    connection_id: "live-1",
    reconnect_generation: 0
  },
  sync: null,
  latest_snapshot: null,
  decisions: []
};

const detail = {
  ...publicMatch,
  market_timeline: [],
  live_timeline: [publicMatch.live],
  checkpoint_decisions: [],
  future_odds: [],
  result: null,
  result_evidence: []
};

const anonymousSession = {
  enabled: true,
  authenticated: false,
  user: null,
  entitlements: [],
  grants: [],
  providers: { email: true, google: false, steam: false }
};

const scopedSession = {
  enabled: true,
  authenticated: true,
  user: { id: "user-1", email: null, email_verified_at: null, display_name: "Steam Player", avatar_url: null, created_at: "2026-08-18T00:00:00Z" },
  entitlements: [],
  grants: [
    { entitlement: "ai_decisions", scope_type: "MAP", scope_ref: "map-live", campaign_key: null, starts_at: null, expires_at: null }
  ],
  providers: { email: true, google: false, steam: true }
};

const aiPayload = {
  canonical_map_id: "map-live",
  canonical_series_id: "series-live",
  latest_snapshot: null,
  checkpoint_decisions: [],
  decisions: [
    {
      id: "decision-1",
      provider: "openai",
      model: "gpt-match",
      model_version: "v1",
      prompt_version: "v1",
      decision_policy_version: "v1",
      snapshot_hash: "hash",
      request_started_at: "2026-08-18T09:20:01Z",
      response_received_at: "2026-08-18T09:20:03Z",
      parse_status: "SUCCESS",
      latency_seconds: 2,
      decision: {
        action: "BUY_A",
        confidence: 0.72,
        primary_reasons: ["Team Liquid 的当前局面和市场价格形成了正向优势。"]
      },
      error: null
    }
  ]
};

async function installRoutes(page: Page, session: typeof anonymousSession | typeof scopedSession) {
  let aiRequests = 0;
  await page.addInitScript(() => {
    window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN");
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let payload: unknown = null;
    let status = 200;
    if (path === "/api/auth/session") payload = session;
    else if (path === "/api/matches") payload = [publicMatch];
    else if (path === "/api/maps/map-live") payload = detail;
    else if (path === "/api/maps/map-live/ai-decisions") {
      aiRequests += 1;
      if (session.authenticated) payload = aiPayload;
      else {
        status = 401;
        payload = { detail: "authentication required" };
      }
    } else status = 404;
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(payload) });
  });
  return () => aiRequests;
}

test("public match page exposes match intelligence without requesting premium AI", async ({ page }) => {
  const aiRequestCount = await installRoutes(page, anonymousSession);
  await page.goto("/matches/map-live");

  await expect(page.getByRole("heading", { name: "Team Liquid" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Team Spirit" })).toBeVisible();
  await expect(page.getByText("21:15", { exact: true })).toBeVisible();
  await expect(page.getByText("14", { exact: true })).toBeVisible();
  await expect(page.getByText("Juggernaut", { exact: true })).toBeVisible();
  await expect(page.getByText("1.72", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "登录后查看 AI 判断" })).toBeVisible();
  await expect(page.getByRole("button", { name: "登录", exact: true })).toBeVisible();
  expect(aiRequestCount()).toBe(0);

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noOverflow).toBe(true);
});

test("map-scoped access requests and renders AI without requiring global Pro", async ({ page }) => {
  const aiRequestCount = await installRoutes(page, scopedSession);
  await page.goto("/matches/map-live");

  await expect(page.getByText("本局权限", { exact: true })).toBeVisible();
  await expect(page.getByText("openai", { exact: true })).toBeVisible();
  await expect(page.locator(".match-ai-decision").getByText("Team Liquid", { exact: true })).toBeVisible();
  await expect(page.getByText("72%", { exact: true })).toBeVisible();
  await expect(page.getByText(/当前局面和市场价格/)).toBeVisible();
  expect(aiRequestCount()).toBeGreaterThan(0);

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noOverflow).toBe(true);
});
