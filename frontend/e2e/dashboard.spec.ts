import { expect, test, type Page } from "playwright/test";

const observedAt = "2026-08-12T12:00:00Z";
const mapId = "11111111-1111-1111-1111-111111111111";

const runtime = {
  overall: "DEGRADED",
  workers: {
    SnapshotCoordinator: {
      name: "SnapshotCoordinator",
      state: "RUNNING",
      last_attempt_at: observedAt,
      last_success_at: observedAt,
      last_message_at: observedAt,
      consecutive_failures: 0,
      last_error: null,
      messages_received: 12,
      restart_count: 1,
      metadata: {}
    }
  },
  dependencies: Object.fromEntries(
    [
      "RAYBET_HTTP",
      "RAYBET_SOCKET",
      "DLTV_SOCKET",
      "DLTV_DRAFT",
      "LIVE_SYNC",
      "STRATZ",
      "DRAFT_ENGINE",
      "HISTORY",
      "GPT",
      "CLAUDE",
      "GEMINI",
      "DEEPSEEK",
      "KIMI",
      "EMAIL"
    ].map((name) => [
      name,
      { name, status: name === "LIVE_SYNC" ? "CAUTION" : "READY", message: null, updated_at: observedAt, metadata: {} }
    ])
  ),
  observed_at: observedAt
};

const market = [
  { odds_id: 101, selection_team_id: "team-a", price: "1.86", fair_probability: 0.537, raw_status: 1, received_at: observedAt },
  { odds_id: 102, selection_team_id: "team-b", price: "2.04", fair_probability: 0.49, raw_status: 1, received_at: observedAt }
];

const summary = {
  entity_type: "MAP",
  identity_status: "RESOLVED",
  id: mapId,
  series_id: "22222222-2222-2222-2222-222222222222",
  canonical_map_id: mapId,
  map_number: 2,
  valve_match_id: 8940730389,
  scheduled_at: observedAt,
  provider_match_id: 38423260,
  tournament_name: "TI15 International",
  round: "bo3",
  raw_status: 1,
  provider_observed_at: observedAt,
  team_a: { id: "team-a", name: "Team Spirit" },
  team_b: { id: "team-b", name: "Tundra" },
  market,
  draft: {
    complete: true,
    blockers: [],
    warnings: [],
    roster_ready_count: 10,
    hero_ready_count: 10,
    slots: Array.from({ length: 10 }, (_, index) => ({
      side: index < 5 ? "radiant" : "dire",
      position: (index % 5) + 1,
      account_id: 1000 + index,
      canonical_player_id: `player-${index}`,
      player_name: index === 0 ? "Collapse" : null,
      hero_id: index + 1,
      hero_name: index === 0 ? "Magnus" : null
    })),
    observed_at: observedAt,
    features: { current_edge: 3.2, next_5m_edge: 2.6, peak_minute: 35, peak_edge: 5.1 },
    curve: [
      { minute: 20, pure_radiant_edge: 1.2, adjusted_radiant_edge: 2.0, support: 950, confidence: 0.72 },
      { minute: 40, pure_radiant_edge: 3.8, adjusted_radiant_edge: 4.6, support: 810, confidence: 0.68 },
      { minute: 60, pure_radiant_edge: -0.8, adjusted_radiant_edge: -0.2, support: 420, confidence: 0.55 }
    ],
    model_version: "rosh-v1",
    data_version: "stratz-2026-08-12"
  },
  live: {
    game_time_seconds: 1540,
    radiant_kills: 18,
    dire_kills: 14,
    radiant_nw_lead: 3200,
    first_blood: "radiant",
    received_at: observedAt,
    last_message_received_at: observedAt,
    last_state_change_received_at: observedAt,
    message_age_seconds: 2.4,
    effective_state_age_seconds: 4.1,
    connection_id: "connection-1",
    reconnect_generation: 1
  },
  sync: { status: "CAUTION", p50_seconds: 2.1, p90_seconds: 4.7, jitter_seconds: 1.4, sample_size: 8 },
  latest_snapshot: {
    id: "33333333-3333-3333-3333-333333333333",
    decision_at: observedAt,
    mode: "POST_DRAFT",
    snapshot_hash: "fixture-snapshot-hash",
    quality: { eligible: true, blockers: [], warnings: ["LIVE_DATA_DESYNC"] }
  },
  decisions: ["openai", "anthropic", "gemini"].map((provider, index) => ({
    id: `decision-${index}`,
    provider,
    model: ["gpt-5.6-terra", "claude-sonnet-4-6", "gemini-3.6-flash"][index],
    model_version: ["gpt-5.6-terra", "claude-sonnet-4-6", "gemini-3.6-flash"][index],
    parse_status: "SUCCESS",
    latency_seconds: 0.8 + index,
    decision: {
      action: index === 0 ? "BUY_A" : "NO_BUY",
      confidence: 0.66 - index * 0.08,
      fair_probability_a: 0.57,
      primary_reasons: ["Draft curve supports Team Spirit"],
      counter_arguments: ["Live synchronization is not safe"],
      data_quality_concerns: ["LIVE_DATA_DESYNC"],
      blockers: []
    },
    error: null
  }))
};

const detail = {
  ...summary,
  market_timeline: [
    { ...market[0], price: "1.94", received_at: "2026-08-12T11:55:00Z" },
    market[0],
    { ...market[1], price: "1.96", received_at: "2026-08-12T11:55:00Z" },
    market[1]
  ],
  live_timeline: [
    {
      game_time_seconds: 1480,
      radiant_kills: 16,
      dire_kills: 13,
      radiant_nw_lead: 2400,
      first_blood: "radiant",
      received_at: "2026-08-12T11:59:00Z",
      last_message_received_at: "2026-08-12T11:59:00Z",
      last_state_change_received_at: "2026-08-12T11:59:00Z",
      connection_id: "connection-1",
      reconnect_generation: 1
    },
    summary.live
  ],
  snapshot_payload: {
    history: {
      team_a: { base_rating: 1684, recent_form: 0.12, current_roster_strength: 0.18, roster_stability: 0.88 },
      team_b: { base_rating: 1642, recent_form: 0.05, current_roster_strength: 0.11, roster_stability: 0.79 },
      players_a: [{ canonical_player_id: "p1", position: 1, base_strength: 0.22, recent_form: 0.16, player_hero_strength: 0.19, player_hero_confidence: 0.74 }],
      players_b: [{ canonical_player_id: "p2", position: 1, base_strength: 0.18, recent_form: 0.09, player_hero_strength: 0.11, player_hero_confidence: 0.63 }]
    }
  },
  future_odds: [{
    id: "44444444-4444-4444-4444-444444444444",
    capture_type: "CLOSING",
    horizon_seconds: null,
    triggered_at: observedAt,
    due_at: observedAt,
    observed_at: observedAt,
    odds_a: "1.80",
    odds_b: "2.20",
    market_type: "Winner",
    match_stage: "Map 2",
    market_status: "UNKNOWN",
    capture_policy_version: "closing-policy-v1",
    pair_quality: { eligible: true },
    pair_skew_seconds: 0,
    status: "CAPTURED"
  }],
  result: {
    winner_team_id: "team-a",
    basic_first_usable_at: observedAt,
    advanced_first_usable_at: null,
    settled_at: observedAt,
    provider_conflict: false
  },
  result_evidence: [{
    id: "55555555-5555-5555-5555-555555555555",
    provider: "opendota",
    provider_match_id: "8940730389",
    winner_team_id: "team-a",
    result_observed_at: observedAt,
    first_usable_at: observedAt,
    raw_event_id: "66666666-6666-6666-6666-666666666666",
    normalizer_version: "opendota-v1",
    identity_confidence: 1,
    conflict_status: "CONSISTENT"
  }]
};

async function mockApi(page: Page): Promise<void> {
  await page.addInitScript(() => {
    Object.defineProperty(window, "WebSocket", { value: undefined, configurable: true });
    if (window.localStorage.getItem("dota-ai-decision-lab-locale") === null) {
      window.localStorage.setItem("dota-ai-decision-lab-locale", "en");
    }
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const payload = path === "/api/runtime"
      ? runtime
      : path === "/api/matches"
        ? [summary]
        : path === `/api/maps/${mapId}`
          ? detail
          : path === "/api/jobs/summary"
            ? { by_status: { PENDING: 2, COMPLETED: 18 }, by_type: [], oldest_pending_at: observedAt, recent_failures: [] }
            : null;
    await route.fulfill({
      status: payload === null ? 404 : 200,
      contentType: "application/json",
      body: JSON.stringify(payload)
    });
  });
}

test("renders the operational decision lifecycle without page overflow", async ({ page }) => {
  await mockApi(page);
  await page.goto("/?e2e=bilingual");

  await expect(page.getByRole("heading", { name: "Team Spirit vs Tundra" })).toBeVisible();
  const matchOverview = page.getByLabel("Match overview");
  await expect(matchOverview.getByRole("heading", { name: "Current lineup" })).toBeVisible();
  await expect(matchOverview.getByRole("heading", { name: "Live match state" })).toBeVisible();
  await expect(matchOverview.getByText("Collapse", { exact: true })).toBeVisible();
  await expect(matchOverview.getByText("Magnus", { exact: true })).toBeVisible();
  await expect(matchOverview.getByText("18 - 14", { exact: true })).toBeVisible();
  await expect(matchOverview.locator(".live-facts").getByText("Radiant", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Draft Intelligence" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Independent AI decisions" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Market odds timeline" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Draft minute curve" })).toBeVisible();
  await expect(page.getByText("LIVE_DATA_DESYNC").first()).toBeVisible();

  const noPageOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth === document.documentElement.clientWidth
  );
  expect(noPageOverflow).toBe(true);

  await expect(page.getByRole("tab", { name: "Historical" })).toBeVisible();
  await expect(page.getByText("Base Elo", { exact: true })).toHaveCount(2);
  await expect(page.getByRole("tab", { name: "Runtime" })).toBeVisible();
  await expect(page.getByText("SnapshotCoordinator", { exact: true })).toBeAttached();
  await expect(page.getByText("Durable jobs", { exact: true })).toBeAttached();
  await expect(page.getByRole("tab", { name: "Evaluation" })).toBeVisible();
  await expect(page.getByText("Closing odds", { exact: true })).toBeAttached();
  await expect(page.getByText("Result evidence", { exact: true })).toBeAttached();

  const chineseButton = page.getByRole("button", { name: "中文" });
  await chineseButton.click({ force: true });
  await expect(page.getByRole("heading", { name: "Team Spirit 对阵 Tundra", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "当前阵容", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "实时赛况", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "选人情报", exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "历史", exact: true })).toBeVisible();
  await page.locator("details.readiness-summary > summary").click();
  await expect(
    page.getByRole("region", { name: "业务就绪状态" }).getByText("DLTV 实时", { exact: true })
  ).toBeAttached();
  await expect(page.getByText("赛果证据", { exact: true })).toBeAttached();
  await expect(chineseButton).toHaveAttribute("aria-pressed", "true");

  await page.reload();
  await expect(page.getByRole("heading", { name: "选人情报", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "中文" })).toHaveAttribute("aria-pressed", "true");
});
