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
      const payload = url.endsWith("/api/maps")
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

  expect((await screen.findAllByText("ACTION REQUIRED")).length).toBeGreaterThan(0);
  expect(await screen.findByText("No canonical maps")).toBeInTheDocument();
  expect(screen.getByText("Waiting for canonical map discovery")).toBeInTheDocument();
});

test("switches to Chinese and restores the choice after remount", async () => {
  const firstClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const firstView = render(
    <QueryClientProvider client={firstClient}>
      <App />
    </QueryClientProvider>
  );

  fireEvent.click(await screen.findByRole("button", { name: "中文" }));
  expect(await screen.findByText("暂无规范化地图")).toBeInTheDocument();
  expect(screen.getByText("等待规范化地图发现")).toBeInTheDocument();
  expect(window.localStorage.getItem("dota-ai-decision-lab-locale")).toBe("zh-CN");
  expect(document.documentElement.lang).toBe("zh-CN");

  firstView.unmount();
  const secondClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={secondClient}>
      <App />
    </QueryClientProvider>
  );

  expect(await screen.findByText("暂无规范化地图")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "中文" })).toHaveAttribute("aria-pressed", "true");
});

test("shows bilingual audit evidence for a decision lifecycle", async () => {
  const map = {
    id: "11111111-1111-1111-1111-111111111111",
    series_id: "22222222-2222-2222-2222-222222222222",
    map_number: 1,
    valve_match_id: 8940730389,
    scheduled_at: "2026-08-12T12:00:00Z",
    team_a: { id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", name: "Radiant" },
    team_b: { id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", name: "Dire" },
    market: [
      { odds_id: 10, selection_team_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", price: "1.90", fair_probability: 0.52, raw_status: 1, normalized_status: "UNKNOWN", metadata_version: "registry-v1", market_type: "match_winner", match_stage: "Map 1", received_at: "2026-08-12T12:00:01Z", age_seconds: 1 },
      { odds_id: 20, selection_team_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", price: "2.10", fair_probability: 0.48, raw_status: 1, normalized_status: "UNKNOWN", metadata_version: "registry-v1", market_type: "match_winner", match_stage: "Map 1", received_at: "2026-08-12T12:00:01Z", age_seconds: 1 }
    ],
    market_quality: { eligible: true, blockers: [], warnings: ["MARKET_STATUS_UNKNOWN"], metadata_version: "registry-v1", paired_at: "2026-08-12T12:00:02Z", pair_skew_seconds: 0 },
    draft: null,
    live: null,
    sync: null,
    latest_snapshot: { id: "33333333-3333-3333-3333-333333333333", decision_at: "2026-08-12T12:00:02Z", created_at: "2026-08-12T12:00:03Z", mode: "PREMATCH", snapshot_hash: "abcdef1234567890", quality: { eligible: true, blockers: [], warnings: [] }, market_quality: null, history_coverage: null },
    decisions: [],
    market_timeline: [],
    live_timeline: [],
    snapshot_payload: { history: {}, quality: {} },
    future_odds: [{ id: "44444444-4444-4444-4444-444444444444", capture_type: "CLOSING", horizon_seconds: null, triggered_at: "2026-08-12T12:05:00Z", due_at: "2026-08-12T12:05:00Z", observed_at: "2026-08-12T12:04:59Z", odds_a: "1.80", odds_b: "2.20", market_type: "match_winner", match_stage: "Map 1", market_status: "UNKNOWN", capture_policy_version: "closing-policy-v1", pair_quality: { eligible: true }, pair_skew_seconds: 0, status: "CAPTURED" }],
    result: { winner_team_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", basic_first_usable_at: "2026-08-12T13:00:00Z", advanced_first_usable_at: null, settled_at: "2026-08-12T13:00:01Z", provider_conflict: false },
    result_evidence: [{ id: "55555555-5555-5555-5555-555555555555", provider: "opendota", provider_match_id: "8940730389", winner_team_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", result_observed_at: "2026-08-12T13:00:00Z", first_usable_at: "2026-08-12T13:00:00Z", raw_event_id: "66666666-6666-6666-6666-666666666666", normalizer_version: "opendota-v1", identity_confidence: 1, conflict_status: "CONSISTENT" }]
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.endsWith(`/api/maps/${map.id}`)
        ? map
        : url.endsWith("/api/maps")
          ? [map]
          : url.endsWith("/api/jobs/summary")
            ? { by_status: {}, by_type: [], oldest_pending_at: null, recent_failures: [] }
            : runtime;
      return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
    })
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><App /></QueryClientProvider>);

  expect(await screen.findByText(/Snapshot hash abcdef123456/)).toBeInTheDocument();
  expect(await screen.findByText("Pair quality")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "Evaluation" }));
  expect(await screen.findByText("Closing odds")).toBeInTheDocument();
  expect(screen.getByText("Result evidence")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "中文" }));
  expect(await screen.findByText("赛果证据")).toBeInTheDocument();
});
