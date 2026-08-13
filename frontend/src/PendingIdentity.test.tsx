import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "./App";

const runtime = { overall: "DEGRADED", workers: {}, dependencies: {}, observed_at: "2026-08-13T12:00:00Z" };
const jobs = { by_status: {}, by_type: [], oldest_pending_at: null, recent_failures: [] };
const pending = {
  entity_type: "SERIES",
  identity_status: "PENDING_MAP_IDENTITY",
  phase: "PREMATCH",
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
  team_a: { id: "team-a", name: "Team Spirit" },
  team_b: { id: "team-b", name: "Xtreme Gaming" },
  market: [
    { odds_id: 10, selection_team_id: "team-a", price: "1.90", fair_probability: null, raw_status: 1, normalized_status: "UNKNOWN", metadata_version: "registry-v1", market_type: "Winner", match_stage: "Full Time", received_at: "2026-08-13T12:00:01Z", age_seconds: 1 },
    { odds_id: 20, selection_team_id: "team-b", price: "2.10", fair_probability: null, raw_status: 1, normalized_status: "UNKNOWN", metadata_version: "registry-v1", market_type: "Winner", match_stage: "Full Time", received_at: "2026-08-13T12:00:01Z", age_seconds: 1 }
  ],
  market_quality: null,
  draft: null,
  live: null,
  sync: null,
  latest_snapshot: null,
  decisions: [],
  historical_prewarm: {
    team_strength_ready_count: 2,
    player_form_ready_count: 0,
    player_hero_ready_count: 0,
    latest_knowledge_cutoff: "2026-08-13T11:55:00Z"
  }
};

beforeEach(() => {
  window.localStorage.clear();
  Object.defineProperty(window, "WebSocket", { value: undefined, configurable: true });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function response(payload: unknown) {
  return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
}

test("pending series shows only truthful market and historical prewarm", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/matches")) return response([pending]);
    if (url.endsWith("/api/jobs/summary")) return response(jobs);
    return response(runtime);
  });
  vi.stubGlobal("fetch", fetchMock);

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><App /></QueryClientProvider>);

  expect(await screen.findByText("Waiting for map identity")).toBeInTheDocument();
  expect(screen.getByText("Primary winner market")).toBeInTheDocument();
  expect(screen.getByText("2/2")).toBeInTheDocument();
  expect(screen.queryByText("Independent AI decisions")).not.toBeInTheDocument();
  expect(screen.queryByText("R.O.S.H. Draft Advantage")).not.toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/api/maps/"))).toBe(false);
});
