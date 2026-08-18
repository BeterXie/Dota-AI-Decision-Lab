import { expect, test, type Page } from "playwright/test";

const identity = {
  provider: "openai",
  model: "gpt-5.6-terra",
  prompt_version: "decision-analyst-v5.1-output",
  decision_policy_version: "shadow-tournament-portfolio-v3",
  ai_view_version: "ai-view-v6"
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
  experiments: [
    {
      experiment: identity,
      observed_model_versions: [identity.model],
      baseline_role: "BASELINE",
      samples: { attempts: 30, successful_decisions: 29, parse_success_rate: 29 / 30, forecast_maps: 20, clv_maps: 10, market_comparison_maps: 18 },
      quality: { forecast_accuracy: 0.6, average_brier_score: 0.21, average_log_loss: 0.59, calibration_error: 0.12, average_clv: 0.01, market_brier_improvement: 0.015, abstention_rate: 0.45, action_counts: {}, parse_status_counts: { SUCCESS: 29, PARSE_FAILED: 1 } },
      latency: { sample_count: 30, average_seconds: 4.2, p95_seconds: 7.8 },
      portfolio: { event_count: 2, realized_roi: 0.04, realized_pnl: 800, worst_event_drawdown_pct: 0.12, bet_count: 16 },
      baseline_reference: null,
      delta_vs_baseline: null
    },
    {
      experiment: { ...identity, prompt_version: "decision-analyst-vNext" },
      observed_model_versions: [identity.model],
      baseline_role: "CHALLENGER",
      samples: { attempts: 28, successful_decisions: 28, parse_success_rate: 1, forecast_maps: 20, clv_maps: 11, market_comparison_maps: 18 },
      quality: { forecast_accuracy: 0.7, average_brier_score: 0.18, average_log_loss: 0.52, calibration_error: 0.08, average_clv: 0.025, market_brier_improvement: 0.03, abstention_rate: 0.35, action_counts: {}, parse_status_counts: { SUCCESS: 28 } },
      latency: { sample_count: 28, average_seconds: 3.5, p95_seconds: 6.2 },
      portfolio: { event_count: 2, realized_roi: 0.08, realized_pnl: 1600, worst_event_drawdown_pct: 0.1, bet_count: 18 },
      baseline_reference: identity,
      delta_vs_baseline: { forecast_maps: 0, forecast_accuracy: 0.1, brier_improvement: 0.03, log_loss_improvement: 0.07, calibration_improvement: 0.04, clv_improvement: 0.015, market_brier_improvement_delta: 0.015, abstention_rate_delta: -0.1, average_latency_improvement_seconds: 0.7, p95_latency_improvement_seconds: 1.6, shadow_roi_delta: 0.04, drawdown_improvement: 0.02 }
    }
  ]
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

test("shows frozen baseline contract and challenger deltas", async ({ page }) => {
  await mockApis(page);
  await page.goto("/performance");

  await expect(page.getByRole("heading", { name: "AI 基线 Benchmark" })).toBeVisible();
  await expect(page.getByText("production-baseline-v1")).toBeVisible();
  await expect(page.getByText("81698ca175a")).toBeVisible();
  await expect(page.getByText("CHALLENGER")).toBeVisible();
  await expect(page.getByText("相对基线改善")).toBeVisible();
  await expect(page.getByText("+3.0%")).toBeVisible();
});
