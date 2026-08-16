import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App, isReviewRoute } from "./App";

const runtime = {
  overall: "ACTION_REQUIRED",
  workers: {},
  dependencies: {},
  observed_at: "2026-08-12T12:00:00Z",
  live_state_max_age_seconds: 120
};

const jobs = { by_status: {}, by_type: [], oldest_pending_at: null, recent_failures: [] };
const anonymousSession = {
  enabled: true,
  authenticated: false,
  user: null,
  entitlements: []
};
const proSession = {
  enabled: true,
  authenticated: true,
  user: {
    id: "99999999-9999-9999-9999-999999999999",
    email: "pro@example.com",
    email_verified_at: "2026-08-12T10:00:00Z",
    created_at: "2026-08-12T10:00:00Z"
  },
  entitlements: ["ai_decisions"]
};

beforeEach(() => {
  window.localStorage.clear();
  Object.defineProperty(window, "WebSocket", { value: undefined, configurable: true });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><App /></QueryClientProvider>);
}

function response(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

function liveMatchFixture() {
  return {
    entity_type: "MAP",
    identity_status: "RESOLVED",
    phase: "LIVE",
    id: "11111111-1111-1111-1111-111111111111",
    series_id: "22222222-2222-2222-2222-222222222222",
    canonical_map_id: "11111111-1111-1111-1111-111111111111",
    map_number: 2,
    valve_match_id: 8940730389,
    scheduled_at: "2026-08-12T12:00:00Z",
    provider_match_id: 38423260,
    tournament_name: "EPL Masters",
    round: "bo3",
    raw_status: 1,
    provider_observed_at: "2026-08-12T11:59:00Z",
    team_a: { id: "team-a", name: "Team Spirit" },
    team_b: { id: "team-b", name: "Aurora" },
    market: [
      { odds_id: 10, selection_team_id: "team-a", price: "1.72", fair_probability: 0.56, raw_status: 1, normalized_status: "UNKNOWN", metadata_version: "v1.4.2", market_type: "match_winner", match_stage: "Map 2", received_at: "2026-08-12T12:18:40Z", age_seconds: 2 },
      { odds_id: 20, selection_team_id: "team-b", price: "2.18", fair_probability: 0.44, raw_status: 1, normalized_status: "UNKNOWN", metadata_version: "v1.4.2", market_type: "match_winner", match_stage: "Map 2", received_at: "2026-08-12T12:18:40Z", age_seconds: 2 }
    ],
    market_quality: { eligible: true, blockers: [], warnings: [], metadata_version: "v1.4.2", paired_at: "2026-08-12T12:18:40Z", pair_skew_seconds: 0 },
    snapshot_market_quality: null,
    draft: {
      complete: true,
      blockers: [], warnings: [], observed_at: "2026-08-12T12:00:00Z", statistics_cutoff: "2026-08-01T00:00:00Z",
      features: { current_edge: 5.2, next_5m_edge: 6.1, peak_edge: 8.4, peak_minute: 31, cross_over_minute: 46 },
      curve: [
        { minute: 20, pure_radiant_edge: 2.2, adjusted_radiant_edge: 3.0, support: 100, confidence: 0.8 },
        { minute: 31, pure_radiant_edge: 6.8, adjusted_radiant_edge: 8.4, support: 100, confidence: 0.8 },
        { minute: 46, pure_radiant_edge: -0.5, adjusted_radiant_edge: -0.8, support: 80, confidence: 0.7 },
        { minute: 47, pure_radiant_edge: -1.0, adjusted_radiant_edge: -1.2, support: 80, confidence: 0.7 }
      ],
      model_version: "rosh-v1", data_version: "stratz-v1", roster_ready_count: 10, hero_ready_count: 10,
      slots: [
        { side: "radiant", position: 1, account_id: 101, canonical_player_id: "p1", player_name: "Yatoro", hero_id: 10, hero_name: "Morphling" },
        { side: "dire", position: 1, account_id: 201, canonical_player_id: "p6", player_name: "23savage", hero_id: 1, hero_name: "Anti-Mage" }
      ]
    },
    live: {
      game_time_seconds: 1320, radiant_kills: 12, dire_kills: 8, radiant_nw_lead: 3400, first_blood: "Dire",
      received_at: "2026-08-12T12:22:00Z", last_message_received_at: "2026-08-12T12:21:59Z", last_state_change_received_at: "2026-08-12T12:21:58Z",
      message_age_seconds: 1, effective_state_age_seconds: 2, connection_id: "conn-1", reconnect_generation: 0
    },
    sync: { status: "SAFE", p50_seconds: 1.2, p90_seconds: 2.1, jitter_seconds: 0.3, sample_size: 100, accepted_pair_ratio: 0.98, ambiguous_ratio: 0.01, outlier_ratio: 0.01, confidence: "HIGH", calculated_at: "2026-08-12T12:21:59Z" },
    latest_snapshot: { id: "snap-1", decision_at: "2026-08-12T12:21:59Z", created_at: "2026-08-12T12:22:00Z", mode: "LIVE_BASIC", market_quality: null, history_coverage: null, quality: { eligible: true, blockers: [], warnings: [] } },
    ai_access: { required_entitlement: "ai_decisions", analysis_available: true, updated_at: "2026-08-12T12:21:59Z", completed_models: 1 },
    decisions: [],
    market_timeline: [], live_timeline: [], result: null, result_evidence: []
  };
}

function premiumFixture(match = liveMatchFixture()) {
  return {
    canonical_map_id: match.canonical_map_id,
    latest_snapshot: match.latest_snapshot,
    decisions: [
      { id: "dec-gpt", snapshot_id: "snap-1", provider: "openai", model: "gpt-5", model_version: "2026-08", prompt_version: "v2.1", decision_policy_version: "v1.0", snapshot_hash: "3a7f89b1c4e20d", request_started_at: "2026-08-12T12:21:59Z", response_received_at: "2026-08-12T12:22:00Z", parse_status: "PARSED", latency_seconds: 0.8, decision: { action: "BUY_A", confidence: 0.76, fair_probability_a: 0.61, primary_reasons: ["Draft and price align"], counter_arguments: ["Late crossover risk"], data_quality_concerns: [] }, error: null }
    ],
    checkpoint_decisions: [],
    snapshot_payload: { history: {}, quality: {} },
    future_odds: []
  };
}

function summaryFromDetail(detail: ReturnType<typeof liveMatchFixture>) {
  const summary: Record<string, unknown> = { ...detail };
  for (const key of ["market_timeline", "live_timeline", "result", "result_evidence"]) delete summary[key];
  return summary;
}

test("renders public empty state without requiring login and persists locale", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/auth/session")) return response(anonymousSession);
    if (url.endsWith("/api/matches")) return response([]);
    return response(runtime);
  }));

  const first = renderApp();
  expect((await screen.findAllByText("No discovered matches")).length).toBeGreaterThan(0);
  expect(screen.getByText("Dota AI Decision Lab")).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "中文" }));
  expect(window.localStorage.getItem("dota-ai-decision-lab-locale")).toBe("zh-CN");
  first.unmount();

  renderApp();
  expect(await screen.findByRole("button", { name: "中文" })).toHaveAttribute("aria-pressed", "true");
});

test("anonymous users see match intelligence but not the AI decision", async () => {
  const match = liveMatchFixture();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/auth/session")) return response(anonymousSession);
    if (url.endsWith("/api/matches")) return response([summaryFromDetail(match)]);
    if (url.includes(`/api/maps/${match.canonical_map_id}`)) return response(match);
    return response(runtime);
  }));

  renderApp();
  expect((await screen.findAllByText("Team Spirit")).length).toBeGreaterThan(0);
  expect(screen.getByText("Live AI decisions")).toBeInTheDocument();
  expect(screen.getByText(/AI analysis is ready/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Sign in for AI access" })).toBeInTheDocument();
  expect(screen.queryByText("BUY A")).not.toBeInTheDocument();
  expect(screen.getByText("R.O.S.H. Draft Advantage")).toBeInTheDocument();
  expect(screen.getByText("Radiant +5.2pp")).toBeInTheDocument();
});

test("entitled users receive premium AI decisions without losing public match data", async () => {
  const match = liveMatchFixture();
  const premium = premiumFixture(match);
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/auth/session")) return response(proSession);
    if (url.endsWith("/api/matches")) return response([summaryFromDetail(match)]);
    if (url.endsWith("/ai-decisions")) return response(premium);
    if (url.includes("/api/snapshots/")) return response({ decisions: premium.decisions });
    if (url.includes(`/api/maps/${match.canonical_map_id}`)) return response(match);
    if (url.endsWith("/api/jobs/summary")) return response({ ...jobs, by_status: { COMPLETED: 15 } });
    return response(runtime);
  }));

  renderApp();
  expect((await screen.findAllByText("Team Spirit")).length).toBeGreaterThan(0);
  expect(screen.getByText("Decision data ready")).toBeInTheDocument();
  expect(await screen.findByText("Independent AI decisions")).toBeInTheDocument();
  expect(screen.getAllByText("BUY A").length).toBeGreaterThan(0);
  expect(screen.getByText("R.O.S.H. Draft Advantage")).toBeInTheDocument();
  expect(screen.getByText("Radiant advantage")).toBeInTheDocument();
  expect(screen.getByText("46m → Dire")).toBeInTheDocument();
  expect(screen.getAllByText("Yatoro").length).toBeGreaterThan(0);

  fireEvent.click(screen.getByTitle("Open Engineering Diagnostics"));
  expect(await screen.findByText("System Diagnostics & Engineering Audit")).toBeInTheDocument();
});

test("default-selects the LIVE match instead of the first list row", async () => {
  const prematch = {
    ...liveMatchFixture(),
    id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    canonical_map_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    phase: "PREMATCH",
    scheduled_at: "2026-08-13T12:00:00Z",
    team_a: { id: "team-a2", name: "Prematch Team" },
    team_b: { id: "team-b2", name: "Prematch Foe" }
  };
  const live = {
    ...liveMatchFixture(),
    id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    canonical_map_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
  };
  const requestedDetails: string[] = [];

  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/auth/session")) return response(anonymousSession);
    if (url.endsWith("/api/matches")) return response([prematch, live]);
    if (url.includes("/api/maps/")) {
      requestedDetails.push(url);
      return response(url.includes(live.canonical_map_id) ? live : prematch);
    }
    return response(runtime);
  }));

  renderApp();
  expect(await screen.findByText("Decision data ready")).toBeInTheDocument();
  expect(requestedDetails.some((url) => url.includes(`/api/maps/${live.canonical_map_id}`))).toBe(true);
  expect(requestedDetails.some((url) => url.includes(`/api/maps/${prematch.canonical_map_id}`))).toBe(false);
});

test("entitled AI view shows probability for the selected BUY side", async () => {
  const detail = liveMatchFixture();
  const premium = premiumFixture(detail);
  premium.decisions[0].decision.action = "BUY_B";
  premium.decisions[0].decision.fair_probability_a = 0.25;

  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/auth/session")) return response(proSession);
    if (url.endsWith("/api/matches")) return response([summaryFromDetail(detail)]);
    if (url.endsWith("/ai-decisions")) return response(premium);
    if (url.includes("/api/snapshots/")) return response({ decisions: premium.decisions });
    if (url.includes("/api/maps/")) return response(detail);
    if (url.endsWith("/api/jobs/summary")) return response(jobs);
    return response(runtime);
  }));

  renderApp();
  expect(await screen.findByText("BUY B 75%")).toBeInTheDocument();
});

test("renders a public detail error instead of leaving a failed request in loading state", async () => {
  const summary = summaryFromDetail(liveMatchFixture());
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/auth/session")) return response(anonymousSession);
    if (url.endsWith("/api/matches")) return response([summary]);
    if (url.includes("/api/maps/")) {
      return response({ detail: "fixture failure" }, 500);
    }
    return response(runtime);
  }));

  renderApp();
  expect(await screen.findByText("Failed to load match intelligence")).toBeInTheDocument();
  expect(screen.queryByText("Loading match intelligence")).not.toBeInTheDocument();
});

test("review route predicate does not capture unrelated prefixes", () => {
  expect(isReviewRoute("/review")).toBe(true);
  expect(isReviewRoute("/review/map-1")).toBe(true);
  expect(isReviewRoute("/reviewfoo")).toBe(false);
  expect(isReviewRoute("/review-anything")).toBe(false);
});
