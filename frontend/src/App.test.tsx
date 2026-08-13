import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { App } from "./App";

const runtime = {
  overall: "ACTION_REQUIRED",
  workers: {},
  dependencies: {},
  observed_at: "2026-08-13T12:00:00Z"
};

const jobs = {
  by_status: {},
  by_type: [],
  oldest_pending_at: null,
  recent_failures: []
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
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  );
}

test("renders player-first empty state and persists locale", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const payload = url.endsWith("/api/matches") ? [] : url.endsWith("/api/jobs/summary") ? jobs : runtime;
    return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
  }));

  const first = renderApp();
  expect(await screen.findByText("No discovered matches")).toBeInTheDocument();
  expect(screen.getByText("Waiting for canonical map discovery")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "中文" }));
  expect(await screen.findByText("暂无已发现比赛")).toBeInTheDocument();
  expect(window.localStorage.getItem("dota-ai-decision-lab-locale")).toBe("zh-CN");

  first.unmount();
  renderApp();
  expect(await screen.findByText("暂无已发现比赛")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "中文" })).toHaveAttribute("aria-pressed", "true");
});

test("keeps RayBet series usable while map identity is pending", async () => {
  const pending = {
    entity_type: "SERIES",
    identity_status: "PENDING_MAP_IDENTITY",
    id: "series-1",
    series_id: "series-1",
    canonical_map_id: null,
    map_number: null,
    valve_match_id: null,
    scheduled_at: "2026-08-14T05:00:00Z",
    provider_match_id: 38423260,
    tournament_name: "TI15 International",
    round: "bo3",
    raw_status: 1,
    provider_observed_at: "2026-08-13T12:00:00Z",
    team_a: { id: "team-a", name: "Spirit" },
    team_b: { id: "team-b", name: "Xtreme Gaming" },
    market: [
      {
        odds_id: 10, selection_team_id: "team-a", price: "1.90", fair_probability: null,
        raw_status: 1, normalized_status: "UNKNOWN", metadata_version: "registry-v1",
        market_type: "Winner", match_stage: "Full Time",
        received_at: "2026-08-13T12:00:01Z", age_seconds: 1
      },
      {
        odds_id: 20, selection_team_id: "team-b", price: "2.10", fair_probability: null,
        raw_status: 1, normalized_status: "UNKNOWN", metadata_version: "registry-v1",
        market_type: "Winner", match_stage: "Full Time",
        received_at: "2026-08-13T12:00:01Z", age_seconds: 1
      }
    ],
    market_quality: null,
    draft: null,
    live: null,
    sync: null,
    latest_snapshot: null,
    decisions: [],
    historical_prewarm: {
      team_strength_ready_count: 0,
      player_form_ready_count: 0,
      player_hero_ready_count: 0,
      latest_knowledge_cutoff: null
    }
  };

  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const payload = url.endsWith("/api/matches") ? [pending] : url.endsWith("/api/jobs/summary") ? jobs : runtime;
    return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp();

  expect(await screen.findByRole("heading", { name: "Spirit vs Xtreme Gaming" })).toBeInTheDocument();
  expect(screen.getByLabelText("Headline odds")).toHaveTextContent("1.90");
  expect(screen.getByLabelText("Headline odds")).toHaveTextContent("2.10");
  expect(screen.getByText("Historical prewarm")).toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/api/maps/"))).toBe(false);
});

test("renders player-first match, AI strip, overview and diagnostics", async () => {
  const map = {
    entity_type: "MAP",
    identity_status: "RESOLVED",
    id: "map-1",
    series_id: "series-1",
    canonical_map_id: "map-1",
    map_number: 2,
    valve_match_id: 8940730389,
    scheduled_at: "2026-08-13T12:00:00Z",
    provider_match_id: 38423260,
    tournament_name: "EPL Masters",
    round: "bo3",
    raw_status: 1,
    provider_observed_at: "2026-08-13T11:59:00Z",
    team_a: { id: "team-a", name: "Team Spirit" },
    team_b: { id: "team-b", name: "Aurora" },
    market: [
      {
        odds_id: 10, selection_team_id: "team-a", price: "1.72", fair_probability: 0.56,
        raw_status: 1, normalized_status: "UNKNOWN", metadata_version: "registry-v1",
        market_type: "match_winner", match_stage: "Map 2",
        received_at: "2026-08-13T12:18:40Z", age_seconds: 2
      },
      {
        odds_id: 20, selection_team_id: "team-b", price: "2.18", fair_probability: 0.44,
        raw_status: 1, normalized_status: "UNKNOWN", metadata_version: "registry-v1",
        market_type: "match_winner", match_stage: "Map 2",
        received_at: "2026-08-13T12:18:40Z", age_seconds: 2
      }
    ],
    market_quality: {
      eligible: true, blockers: [], warnings: [], metadata_version: "registry-v1",
      paired_at: "2026-08-13T12:18:40Z", pair_skew_seconds: 0
    },
    draft: {
      complete: true,
      blockers: [],
      warnings: [],
      observed_at: "2026-08-13T12:00:00Z",
      statistics_cutoff: "2026-08-13T11:59:00Z",
      features: { current_edge: 5.2, next_5m_edge: 6.1, peak_edge: 8.4, peak_minute: 31 },
      curve: [
        { minute: 20, pure_radiant_edge: 2, adjusted_radiant_edge: 3, support: 100, confidence: .8 },
        { minute: 30, pure_radiant_edge: 5, adjusted_radiant_edge: 8, support: 100, confidence: .8 }
      ],
      model_version: "rosh-v1",
      data_version: "stratz-v1",
      roster_ready_count: 2,
      hero_ready_count: 2,
      slots: [
        { side: "radiant", position: 1, account_id: 1, canonical_player_id: "p1", player_name: "Yatoro", hero_id: 1, hero_name: "Anti-Mage" },
        { side: "dire", position: 1, account_id: 2, canonical_player_id: "p2", player_name: "23savage", hero_id: 2, hero_name: "Axe" }
      ]
    },
    live: {
      game_time_seconds: 1122,
      radiant_kills: 12,
      dire_kills: 8,
      radiant_nw_lead: 3400,
      first_blood: "dire",
      received_at: "2026-08-13T12:18:42Z",
      last_message_received_at: "2026-08-13T12:18:42Z",
      last_state_change_received_at: "2026-08-13T12:18:41Z",
      message_age_seconds: 1,
      effective_state_age_seconds: 2,
      connection_id: "c1",
      reconnect_generation: 0
    },
    sync: {
      status: "SAFE", p50_seconds: 1.2, p90_seconds: 2.1, jitter_seconds: .4,
      sample_size: 10, accepted_pair_ratio: .9, ambiguous_ratio: 0, outlier_ratio: .1,
      confidence: "HIGH", calculated_at: "2026-08-13T12:18:40Z"
    },
    latest_snapshot: {
      id: "snapshot-1",
      decision_at: "2026-08-13T12:18:40Z",
      created_at: "2026-08-13T12:18:41Z",
      mode: "LIVE_BASIC",
      snapshot_hash: "abcdef1234567890",
      market_quality: null,
      history_coverage: {
        team_strength_ready_count: 2,
        player_form_ready_count: 10,
        player_hero_ready_count: 8
      },
      quality: { eligible: true, blockers: [], warnings: [] }
    },
    decisions: [
      {
        id: "ai-1", provider: "openai", model: "gpt-5", model_version: "gpt-5",
        prompt_version: "v1", decision_policy_version: "v1", snapshot_hash: "abcdef1234567890",
        request_started_at: "2026-08-13T12:18:41Z", response_received_at: "2026-08-13T12:18:42Z",
        parse_status: "PARSED", latency_seconds: 1.1,
        decision: {
          action: "BUY_A", confidence: .76, fair_probability_a: .61,
          primary_reasons: ["Draft and market edge align."],
          counter_arguments: ["Late game may favor Aurora."],
          data_quality_concerns: []
        },
        error: null
      }
    ],
    market_timeline: [],
    live_timeline: [],
    snapshot_payload: { history: {}, quality: {} },
    historical_prewarm: {
      team_strength_ready_count: 2,
      player_form_ready_count: 10,
      player_hero_ready_count: 8,
      latest_knowledge_cutoff: "2026-08-13T11:59:00Z"
    },
    future_odds: [
      {
        id: "close-1", capture_type: "CLOSING", horizon_seconds: null,
        triggered_at: "2026-08-13T13:00:00Z", due_at: "2026-08-13T13:00:00Z",
        observed_at: "2026-08-13T12:59:59Z", odds_a: "1.65", odds_b: "2.30",
        market_type: "match_winner", match_stage: "Map 2", market_status: "UNKNOWN",
        capture_policy_version: "closing-v1", pair_quality: { eligible: true },
        pair_skew_seconds: 0, status: "CAPTURED"
      }
    ],
    result: null,
    result_evidence: []
  };

  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const payload = url.endsWith("/api/matches")
      ? [map]
      : url.endsWith("/api/jobs/summary")
        ? jobs
        : url.includes("/api/maps/")
          ? map
          : runtime;
    return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
  }));

  renderApp();

  expect(await screen.findByRole("heading", { name: "Team Spirit" })).toBeInTheDocument();
  expect(screen.getByText("Independent AI decisions")).toBeInTheDocument();
  expect(screen.getByText("BUY A")).toBeInTheDocument();
  expect(screen.getByText("Hero lineup")).toBeInTheDocument();
  expect(screen.getByText("Yatoro")).toBeInTheDocument();
  expect(screen.getByText("23savage")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /System readiness/i }));
  expect(await screen.findByRole("heading", { name: "Diagnostics" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Close diagnostics" }));
  fireEvent.click(screen.getByRole("button", { name: "Evaluation" }));
  expect(await screen.findByText("Future & closing odds")).toBeInTheDocument();
});
