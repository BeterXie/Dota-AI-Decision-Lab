import { expect, test, type Page } from "playwright/test";

const mapId = "11111111-1111-1111-1111-111111111111";
const now = "2026-08-12T12:00:00Z";

const runtime = {
  overall: "DEGRADED",
  workers: { SnapshotCoordinator: { name: "SnapshotCoordinator", state: "RUNNING", messages_received: 12 } },
  dependencies: {},
  observed_at: now
};

const decision = { id: "d1", snapshot_id: "snapshot-1", provider: "openai", model: "gpt-5.6", model_version: "gpt-5.6", prompt_version: "v2", decision_policy_version: "shadow-v1", snapshot_hash: "fixture-hash", request_started_at: now, response_received_at: now, parse_status: "PARSED", latency_seconds: 0.8, decision: { action: "BUY_A", confidence: 0.66, fair_probability_a: 0.59, primary_reasons: ["Draft edge"], counter_arguments: ["Late crossover"], data_quality_concerns: [] }, error: null };

const match = {
  entity_type: "MAP",
  identity_status: "RESOLVED",
  phase: "LIVE",
  id: mapId,
  series_id: "series-1",
  canonical_map_id: mapId,
  map_number: 2,
  valve_match_id: 8940730389,
  scheduled_at: now,
  provider_match_id: 38423260,
  tournament_name: "TI15 International",
  round: "bo3",
  raw_status: 1,
  provider_observed_at: now,
  team_a: { id: "team-a", name: "Team Spirit" },
  team_b: { id: "team-b", name: "Tundra" },
  market: [
    { odds_id: 101, selection_team_id: "team-a", price: "1.86", fair_probability: 0.537, raw_status: 1, normalized_status: "UNKNOWN", metadata_version: "v1", market_type: "Winner", match_stage: "Map 2", received_at: now, age_seconds: 2 },
    { odds_id: 102, selection_team_id: "team-b", price: "2.04", fair_probability: 0.463, raw_status: 1, normalized_status: "UNKNOWN", metadata_version: "v1", market_type: "Winner", match_stage: "Map 2", received_at: now, age_seconds: 2 }
  ],
  market_quality: { eligible: true, blockers: [], warnings: [], metadata_version: "v1", paired_at: now, pair_skew_seconds: 0 },
  draft: {
    complete: true,
    blockers: [],
    warnings: [],
    observed_at: now,
    statistics_cutoff: now,
    roster_ready_count: 10,
    hero_ready_count: 10,
    features: { current_edge: 3.2, next_5m_edge: 2.6, peak_edge: 5.1, peak_minute: 35, cross_over_minute: 54 },
    curve: [
      { minute: 20, pure_radiant_edge: 1.2, adjusted_radiant_edge: 2.0, support: 950, confidence: 0.72 },
      { minute: 40, pure_radiant_edge: 3.8, adjusted_radiant_edge: 4.6, support: 810, confidence: 0.68 },
      { minute: 54, pure_radiant_edge: -0.3, adjusted_radiant_edge: -0.5, support: 510, confidence: 0.58 },
      { minute: 55, pure_radiant_edge: -0.6, adjusted_radiant_edge: -0.9, support: 500, confidence: 0.56 }
    ],
    model_version: "rosh-v1",
    data_version: "stratz-v1",
    slots: [
      { side: "radiant", position: 1, account_id: 1001, canonical_player_id: "p1", player_name: "Collapse", hero_id: 97, hero_name: "Magnus" },
      { side: "dire", position: 1, account_id: 2001, canonical_player_id: "p6", player_name: "Pure", hero_id: 1, hero_name: "Anti-Mage" }
    ]
  },
  live: { game_time_seconds: 1540, radiant_kills: 18, dire_kills: 14, radiant_nw_lead: 3200, first_blood: "radiant", received_at: now, last_message_received_at: now, last_state_change_received_at: now, message_age_seconds: 2, effective_state_age_seconds: 4, connection_id: "c1", reconnect_generation: 0 },
  sync: { status: "CAUTION", p50_seconds: 2.1, p90_seconds: 4.7, jitter_seconds: 1.4, sample_size: 8, accepted_pair_ratio: 0.88, ambiguous_ratio: 0.08, outlier_ratio: 0.04, confidence: "MEDIUM", calculated_at: now },
  latest_snapshot: { id: "snapshot-1", decision_at: now, created_at: now, mode: "POST_DRAFT", market_quality: null, history_coverage: null, quality: { eligible: true, blockers: [], warnings: ["LIVE_DATA_DESYNC"] } },
  ai_access: { required_entitlement: "ai_decisions", analysis_available: true, updated_at: now, completed_models: 1 },
  decisions: []
};

const detail = { ...match, market_timeline: [], live_timeline: [], result: null, result_evidence: [] };
const premium = { canonical_map_id: mapId, latest_snapshot: match.latest_snapshot, decisions: [decision], checkpoint_decisions: [], snapshot_payload: { history: {}, quality: {} }, future_odds: [] };
const jobs = { by_status: { COMPLETED: 18 }, by_type: [], oldest_pending_at: null, recent_failures: [] };
const anonymousSession = { enabled: true, authenticated: false, user: null, entitlements: [] };
const proSession = {
  enabled: true,
  authenticated: true,
  user: { id: "99999999-9999-9999-9999-999999999999", email: "pro@example.com", email_verified_at: now, created_at: now },
  entitlements: ["ai_decisions"]
};

async function mockApi(page: Page, { entitled }: { entitled: boolean }) {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const payload =
      path === "/api/auth/session" ? (entitled ? proSession : anonymousSession) :
      path === "/api/runtime" ? runtime :
      path === "/api/matches" ? [match] :
      path === `/api/maps/${mapId}` ? detail :
      path === `/api/maps/${mapId}/ai-decisions` && entitled ? premium :
      path === "/api/snapshots/snapshot-1" && entitled ? { decisions: [decision] } :
      path === "/api/jobs/summary" && entitled ? jobs : null;
    await route.fulfill({ status: payload === null ? 404 : 200, contentType: "application/json", body: JSON.stringify(payload) });
  });
}

test("keeps ordinary match data public while premium AI remains locked", async ({ page }) => {
  await mockApi(page, { entitled: false });
  await page.goto("/match-console?e2e=public-match");

  await expect(page.getByText("Team Spirit", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Tundra", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Live AI decisions" })).toBeVisible();
  await expect(page.getByText(/AI analysis is ready/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in for AI access" })).toBeVisible();
  await expect(page.getByText("BUY A", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "R.O.S.H. Draft Advantage" })).toBeVisible();
  await expect(page.getByText("Collapse", { exact: true })).toBeVisible();
});

test("renders player-first premium AI decision workspace for entitled users", async ({ page }) => {
  await mockApi(page, { entitled: true });
  await page.goto("/match-console?e2e=player-first");

  await expect(page.getByText("Team Spirit", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Tundra", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Decision available with limitations", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Independent AI decisions" })).toBeVisible();
  await expect(page.getByText("BUY A", { exact: true }).last()).toBeVisible();
  await expect(page.getByRole("heading", { name: "R.O.S.H. Draft Advantage" })).toBeVisible();
  await expect(page.getByText("Radiant advantage", { exact: true })).toBeVisible();
  await expect(page.getByText("Radiant +3.2pp", { exact: true })).toBeVisible();
  await expect(page.getByText("54m → Dire", { exact: true })).toBeVisible();
  await expect(page.getByText("Team Spirit advantage", { exact: true })).toHaveCount(0);
  await expect(page.getByText("DRAFT LINEUP", { exact: true })).toBeVisible();
  await expect(page.getByText("Collapse", { exact: true })).toBeVisible();

  const noOverflow = await page.evaluate(() => document.documentElement.scrollWidth === document.documentElement.clientWidth);
  expect(noOverflow).toBe(true);

  await page.getByTitle("Open Engineering Diagnostics").click();
  await expect(page.getByText("System Diagnostics & Engineering Audit", { exact: true })).toBeVisible();
  await expect(page.getByText("SnapshotCoordinator", { exact: true })).toBeVisible();
});
