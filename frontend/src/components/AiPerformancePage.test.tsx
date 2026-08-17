import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { AiPerformancePage } from "./AiPerformancePage";

const experiment = {
  id: "openai::gpt-test::2026-08::prompt-v2::policy-v3::ai-view-v2",
  provider: "openai",
  model: "gpt-test",
  model_version: "2026-08",
  prompt_version: "prompt-v2",
  decision_policy_version: "policy-v3",
  ai_view_version: "ai-view-v2",
  attempts: 12,
  successful: 11,
  failed: 1,
  success_rate: 11 / 12,
  evaluated: 9,
  buy_decisions: 8,
  settled_buy_decisions: 7,
  correct_buy_decisions: 5,
  buy_accuracy: 5 / 7,
  average_brier: 0.162,
  average_log_loss: 0.49,
  unit_pnl: 2.4,
  unit_bets: 7,
  unit_roi: 2.4 / 7,
  average_latency_seconds: 1.8,
  p95_latency_seconds: 2.9,
  average_end_to_end_seconds: 3.2,
  average_total_tokens: 2100,
  cached_input_ratio: 0.66,
  last_decision_at: "2026-08-17T12:00:00Z"
};

const decision = {
  id: "decision-1",
  experiment_id: experiment.id,
  snapshot_id: "snapshot-1",
  canonical_map_id: "map-1",
  match: {
    map_number: 2,
    valve_match_id: 123456,
    tournament_name: "EPL Masters",
    team_a: { id: "team-a", name: "Team Spirit" },
    team_b: { id: "team-b", name: "Aurora" }
  },
  decision_at: "2026-08-17T12:00:00Z",
  mode: "LIVE",
  snapshot_hash: "snapshot-hash-abcdef123456",
  ai_input_hash: "input-hash-abcdef654321",
  provider: "openai",
  model: "gpt-test",
  model_version: "2026-08",
  prompt_version: "prompt-v2",
  decision_policy_version: "policy-v3",
  ai_view_version: "ai-view-v2",
  parse_status: "SUCCESS",
  error: null,
  action: "BUY_A",
  fair_probability_a: 0.61,
  confidence: 0.72,
  market_assessment: "VALUE_A",
  primary_reasons: ["draft edge", "market gap"],
  blockers: [],
  bankroll_before: 100,
  stake: 2,
  trace: {
    job_enqueued_at: "2026-08-17T11:59:56Z",
    job_claimed_at: "2026-08-17T11:59:57Z",
    input_prepare_started_at: "2026-08-17T11:59:57Z",
    input_prepare_completed_at: "2026-08-17T11:59:58Z",
    request_started_at: "2026-08-17T11:59:58Z",
    response_received_at: "2026-08-17T12:00:00Z",
    decision_persisted_at: "2026-08-17T12:00:00Z",
    provider_latency_seconds: 2,
    queue_seconds: 1,
    input_prepare_seconds: 1,
    end_to_end_seconds: 4
  },
  tokens: { input: 1500, cached_input: 900, reasoning: 300, output: 200, total: 2000 },
  evaluation: {
    result_correct: true,
    brier_score: 0.12,
    log_loss: 0.41,
    clv: 0.03,
    future_odds_direction: "FAVORABLE",
    virtual_pnl: 2.4,
    virtual_odds: 2.2,
    unit_pnl: 1.2,
    evaluated_at: "2026-08-17T13:00:00Z",
    metrics_version: "evaluation-v3"
  }
};

const payload = {
  summary: {
    attempts: 12,
    successful: 11,
    success_rate: 11 / 12,
    evaluated: 9,
    settled_buy_decisions: 7,
    correct_buy_decisions: 5,
    buy_accuracy: 5 / 7,
    average_brier: 0.162,
    average_log_loss: 0.49,
    unit_pnl: 2.4,
    unit_bets: 7,
    unit_roi: 2.4 / 7,
    experiment_count: 1
  },
  experiments: [experiment],
  decisions: [decision],
  methodology: {
    query_limit: 1000,
    experiment_identity: [
      "provider",
      "model",
      "model_version",
      "prompt_version",
      "decision_policy_version",
      "ai_view_version"
    ],
    comparison_rule: "KEEP_EACH_EXPERIMENT_VERSION_SEPARATE",
    buy_accuracy: "SETTLED_BUY_DECISIONS_ONLY",
    probability_quality: "BRIER_AND_LOG_LOSS_FROM_DECISION_EVALUATIONS",
    unit_roi: "SUM_1_UNIT_PNL_DIVIDED_BY_SETTLED_1_UNIT_BETS",
    audit_identity: "SNAPSHOT_HASH_PLUS_AI_INPUT_HASH_PLUS_EXPERIMENT_VERSIONS",
    source: "IMMUTABLE_DECISION_SNAPSHOT_AND_FROZEN_AI_DECISION",
    no_future_leakage: true
  }
};

beforeEach(() => {
  window.localStorage.setItem("dota-ai-decision-lab-locale", "en");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    )
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider>
        <AiPerformancePage />
      </I18nProvider>
    </QueryClientProvider>
  );
}

test("pins an experiment for comparison and opens a reproducible decision trace", async () => {
  renderPage();

  expect(await screen.findByText("Version scoreboard")).toBeInTheDocument();
  expect(screen.getByText("Team Spirit vs Aurora")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Compare" }));
  expect(screen.getAllByRole("button", { name: "Unpin" }).length).toBeGreaterThan(0);
  expect(screen.getAllByText("prompt-v2").length).toBeGreaterThan(1);

  fireEvent.click(screen.getByText("Team Spirit vs Aurora"));
  expect(await screen.findByRole("dialog", { name: "Decision audit trail" })).toBeInTheDocument();
  expect(screen.getByText("snapshot-hash-abcdef123456")).toBeInTheDocument();
  expect(screen.getByText("input-hash-abcdef654321")).toBeInTheDocument();
  expect(screen.getByText("draft edge")).toBeInTheDocument();
  expect(screen.getByText("market gap")).toBeInTheDocument();
  expect(screen.getByText("evaluation-v3")).toBeInTheDocument();
});
