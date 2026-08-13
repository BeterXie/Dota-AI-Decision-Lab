import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { App } from "./App";

const runtime = {
  overall: "ACTION_REQUIRED",
  workers: {},
  dependencies: {
    DATABASE: {
      name: "DATABASE",
      status: "READY",
      message: null,
      updated_at: "2026-08-12T12:00:00Z",
      metadata: {}
    }
  },
  observed_at: "2026-08-12T12:00:00Z"
};

beforeEach(() => {
  window.localStorage.clear();
  Object.defineProperty(window, "WebSocket", { value: undefined, configurable: true });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.endsWith("/api/matches")
        ? []
        : url.endsWith("/api/jobs/summary")
          ? { by_status: {}, by_type: [], oldest_pending_at: null, recent_failures: [] }
          : runtime;
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    })
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("renders operational empty and readiness states", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  );

  expect((await screen.findAllByText(/System/i)).length).toBeGreaterThan(0);
  expect((await screen.findAllByText("No discovered matches")).length).toBeGreaterThan(0);
  expect(screen.queryByText("BUY A")).not.toBeInTheDocument();
  expect(screen.getByText("Dota AI Decision Lab")).toBeInTheDocument();
});

test("switches to Chinese and restores the choice after remount", async () => {
  const firstClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const firstView = render(
    <QueryClientProvider client={firstClient}>
      <App />
    </QueryClientProvider>
  );

  fireEvent.click(await screen.findByRole("button", { name: "中文" }));
  expect(window.localStorage.getItem("dota-ai-decision-lab-locale")).toBe("zh-CN");
  expect(document.documentElement.lang).toBe("zh-CN");

  firstView.unmount();
  const secondClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={secondClient}>
      <App />
    </QueryClientProvider>
  );

  expect(await screen.findByRole("button", { name: "中文" })).toBeInTheDocument();
});

test("renders match header, AI decision strip, draft lineup and diagnostics drawer", async () => {
  const mockMatch = {
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
      { odds_id: 10, selection_team_id: "team-a", price: "1.72", fair_probability: 0.58, raw_status: 1, normalized_status: "UNKNOWN", metadata_version: "v1.4.2", market_type: "match_winner", match_stage: "Map 2", received_at: "2026-08-12T12:00:01Z", age_seconds: 2 },
      { odds_id: 20, selection_team_id: "team-b", price: "2.18", fair_probability: 0.42, raw_status: 1, normalized_status: "UNKNOWN", metadata_version: "v1.4.2", market_type: "match_winner", match_stage: "Map 2", received_at: "2026-08-12T12:00:01Z", age_seconds: 2 }
    ],
    market_quality: { eligible: true, blockers: [], warnings: [], metadata_version: "v1.4.2", paired_at: "2026-08-12T12:00:02Z", pair_skew_seconds: 0 },
    draft: {
      complete: true,
      blockers: [],
      warnings: [],
      observed_at: "2026-08-12T12:00:00Z",
      statistics_cutoff: "2026-08-01",
      features: null,
      roster_ready_count: 10,
      hero_ready_count: 10,
      slots: [
        { side: "radiant", position: 1, account_id: 101, canonical_player_id: "p1", player_name: "Yatoro", hero_id: 10, hero_name: "Morphling" },
        { side: "dire", position: 1, account_id: 201, canonical_player_id: "p6", player_name: "23savage", hero_id: 1, hero_name: "Anti-Mage" }
      ]
    },
    live: {
      game_time_seconds: 1122,
      radiant_kills: 12,
      dire_kills: 8,
      radiant_nw_lead: 3400,
      first_blood: "Dire",
      received_at: "2026-08-12T12:18:42Z",
      last_message_received_at: "2026-08-12T12:18:41Z",
      last_state_change_received_at: "2026-08-12T12:18:39Z",
      message_age_seconds: 1,
      effective_state_age_seconds: 3,
      connection_id: "conn-1",
      reconnect_generation: 0
    },
    sync: { status: "SAFE", p50_seconds: 1.2, p90_seconds: 2.1, jitter_seconds: 0.3, sample_size: 100, accepted_pair_ratio: 0.98, ambiguous_ratio: 0.01, outlier_ratio: 0.01, confidence: "HIGH", calculated_at: "2026-08-12T12:18:00Z" },
    latest_snapshot: { id: "snap-1", decision_at: "2026-08-12T12:18:00Z", created_at: "2026-08-12T12:18:01Z", mode: "LIVE_BASIC", snapshot_hash: "3a7f89b1c4e20d", quality: { eligible: true, blockers: [], warnings: [] }, market_quality: null, history_coverage: null },
    decisions: [
      {
        id: "dec-gpt",
        provider: "OpenAI",
        model: "gpt-4o",
        model_version: "2026-05",
        prompt_version: "v2.1",
        decision_policy_version: "v1.0",
        snapshot_hash: "3a7f89b1c4e20d",
        request_started_at: "2026-08-12T12:18:00Z",
        response_received_at: "2026-08-12T12:18:01Z",
        parse_status: "PARSED",
        latency_seconds: 0.8,
        decision: { action: "BUY A", confidence: 0.61, fair_probability_a: 0.61, primary_reasons: ["Strong late-game draft synergy"], counter_arguments: [], data_quality_concerns: [] },
        error: null
      }
    ]
  };

  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const payload = url.endsWith("/api/matches")
      ? [mockMatch]
      : url.endsWith(`/api/maps/${mockMatch.id}`)
        ? mockMatch
        : url.endsWith("/api/jobs/summary")
          ? { by_status: { COMPLETED: 15 }, by_type: [], oldest_pending_at: null, recent_failures: [] }
          : runtime;
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" }
    });
  });
  vi.stubGlobal("fetch", fetchMock);

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  );

  // Check Match Header & Score
  expect((await screen.findAllByText("Team Spirit")).length).toBeGreaterThan(0);
  expect((await screen.findAllByText("Aurora")).length).toBeGreaterThan(0);
  expect((await screen.findAllByText("12")).length).toBeGreaterThan(0);
  expect((await screen.findAllByText("8")).length).toBeGreaterThan(0);

  // Check Decision Trust Banner
  expect(screen.getByText("Ready for analysis")).toBeInTheDocument();

  // Check AI Decision Strip
  expect(screen.getByText("AI DECISION")).toBeInTheDocument();
  expect(screen.getByText("gpt-4o")).toBeInTheDocument();
  expect(screen.queryByText("Claude 3.5")).not.toBeInTheDocument();
  expect(screen.queryByText("Gemini 1.5 Pro")).not.toBeInTheDocument();

  // Check Hero Lineup
  expect(screen.getByText("DRAFT LINEUP")).toBeInTheDocument();
  expect(screen.getAllByText("Yatoro").length).toBeGreaterThan(0);

  // Test Diagnostics Drawer toggle
  const sysBtn = screen.getByTitle("Open Engineering Diagnostics");
  fireEvent.click(sysBtn);
  expect(await screen.findByText("System Diagnostics & Engineering Audit")).toBeInTheDocument();
  expect(screen.getByText("Snapshot Hash:")).toBeInTheDocument();
});
