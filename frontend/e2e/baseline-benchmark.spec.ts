import { expect, test, type Page } from "playwright/test";

const identity = {
  provider: "openai",
  model: "gpt-5.6-terra",
  prompt_version: "decision-analyst-v5.1-output",
  decision_policy_version: "shadow-tournament-portfolio-v3",
  ai_view_version: "ai-view-v6"
};

const baseline = {
  experiment: identity,
  observed_model_versions: [identity.model],
  baseline_role: "BASELINE",
  samples: { attempts: 30, successful_decisions: 29, parse_success_rate: 29 / 30, forecast_maps: 20, clv_maps: 10, market_comparison_maps: 18 },
  quality: { forecast_accuracy: 0.6, average_brier_score: 0.21, average_log_loss: 0.59, calibration_error: 0.12, average_clv: 0.01, market_brier_improvement: 0.015, abstention_rate: 0.45, action_counts: {}, parse_status_counts: { SUCCESS: 29, PARSE_FAILED: 1 } },
  latency: { sample_count: 30, average_seconds: 4.2, p95_seconds: 7.8 },
  portfolio: { event_count: 2, realized_roi: 0.04, realized_pnl: 800, worst_event_drawdown_pct: 0.12, bet_count: 16 },
  baseline_reference: null,
  delta_vs_baseline: null,
  context_experiment: null,
  context_reference: null,
  delta_vs_context_reference: null
};

const alignedIdentity = { ...identity, ai_view_version: "ctx-history-schema-aligned-v1" };
const aligned = {
  ...baseline,
  experiment: alignedIdentity,
  baseline_role: "CHALLENGER",
  context_experiment: {
    ai_view_version: alignedIdentity.ai_view_version,
    label: "History schema aligned full context",
    reference_ai_view_version: "ai-view-v6",
    removed_evidence: [],
    schema_aligned_history: true
  },
  context_reference: identity,
  delta_vs_context_reference: { forecast_maps: 0, forecast_accuracy: 0.06, brier_improvement: 0.03, log_loss_improvement: 0.05, calibration_improvement: 0.03, clv_improvement: 0.008, market_brier_improvement_delta: 0.011, abstention_rate_delta: -0.05, average_latency_improvement_seconds: 0.1, p95_latency_improvement_seconds: 0.3, shadow_roi_delta: 0.02, drawdown_improvement: 0.01 }
};

const noFormIdentity = { ...identity, ai_view_version: "ctx-ablation-no-player-form-v1" };
const noForm = {
  ...baseline,
  experiment: noFormIdentity,
  baseline_role: "CHALLENGER",
  quality: { ...baseline.quality, forecast_accuracy: 0.55, average_brier_score: 0.24 },
  context_experiment: {
    ai_view_version: noFormIdentity.ai_view_version,
    label: "No player form context",
    reference_ai_view_version: alignedIdentity.ai_view_version,
    removed_evidence: ["player_form"],
    schema_aligned_history: true
  },
  context_reference: alignedIdentity,
  delta_vs_context_reference: { forecast_maps: 0, forecast_accuracy: -0.11, brier_improvement: -0.06, log_loss_improvement: -0.04, calibration_improvement: -0.02, clv_improvement: -0.01, market_brier_improvement_delta: -0.02, abstention_rate_delta: 0.05, average_latency_improvement_seconds: 0.2, p95_latency_improvement_seconds: 0.2, shadow_roi_delta: -0.02, drawdown_improvement: -0.01 }
};

const benchmark = {
  benchmark_report_version: "ai-benchmark-v1",
  baseline_contract: {
    id: "production-baseline-v1",
    frozen_at_commit: "81698ca175a75dfb08285c3725c98835f616a843",
    prompt_version: identity.prompt_version,
    decision_policy_version: identity.decision_policy_version,
    ai_view_version: identity.ai_view_version,
    models_by_provider: { openai: identity.model },
    immutable: true
  },
  methodology: {
    forecast_sample: "FIRST_EVALUABLE_FORECAST_PER_MAP",
    forecast_accuracy: "PREDICT_A_WHEN_FAIR_PROBABILITY_A_GTE_0_5",
    clv_sample: "FIRST_NON_NULL_CLV_PER_MAP",
    abstention_actions: ["NO_BUY", "INSUFFICIENT_DATA"],
    calibration: { version: "ece-equal-width-10-v1", metric: "EXPECTED_CALIBRATION_ERROR", bins: 10, binning: "EQUAL_WIDTH_0_TO_1" },
    latency: "AI_PROVIDER_HTTP_LATENCY_SECONDS_ALL_ATTEMPTS",
    market_comparison: "VIG_REMOVED_TWO_WAY_PROBABILITY_AT_DECISION_SNAPSHOT",
    significance: "DESCRIPTIVE_ONLY_NO_STATISTICAL_SIGNIFICANCE_CLAIM"
  },
  experiments: [baseline, aligned, noForm]
};

async function mockApis(page: Page) {
  await page.addInitScript(() => window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN"));
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ enabled: true, authenticated: true, user: { id: "99999999-9999-9999-9999-999999999999", email: "pro@example.com", email_verified_at: "2026-08-18T08:00:00Z", created_at: "2026-08-18T08:00:00Z" }, entitlements: ["ai_decisions"], grants: [] }) });
  });
  await page.route("**/api/review/ai-quality/readiness**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ report_version: "decision-readiness-v1", generated_at: "2026-08-18T08:00:00Z", window: { from: "2026-08-11T08:00:00Z", to: "2026-08-18T08:00:00Z", lookback_hours: 168, future_series_included: false }, scope: { source: "LIQUIPEDIA_BACKED_CANONICAL_SERIES", series_count: 0, series_limit: 250 }, stages: [], failure_reasons: [], series: [] }) });
  });
  await page.route("**/api/review/ai-quality/benchmark", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(benchmark) });
  });
  await page.route("**/api/review/ai-quality/leaderboard", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ scope: "ALL_CANONICAL_EVENTS", ranking: "REALIZED_ROI_THEN_PNL", experiments: [] }) });
  });
}

test("shows frozen baseline, aligned context challenger and ablation reference", async ({ page }) => {
  await mockApis(page);
  await page.goto("/performance");

  await expect(page.getByRole("heading", { name: "AI 基线 Benchmark" })).toBeVisible();
  await expect(page.getByText("production-baseline-v1")).toBeVisible();
  await expect(page.getByText("81698ca175a7")).toBeVisible();
  await expect(page.getByText("CONTEXT TEST").first()).toBeVisible();
  await expect(page.getByText(/History schema aligned full context/)).toBeVisible();
  await expect(page.getByText(/相对实验参照 · ai-view-v6/)).toBeVisible();
  await expect(page.getByText(/No player form context/)).toBeVisible();
  await expect(page.getByText(/移除: player_form/)).toBeVisible();
  await expect(page.getByText(/相对实验参照 · ctx-history-schema-aligned-v1/)).toBeVisible();
});
