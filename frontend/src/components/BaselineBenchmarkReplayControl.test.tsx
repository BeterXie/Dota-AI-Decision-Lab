import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AiBenchmarkPayload } from "../benchmarkApi";
import { BaselineBenchmarkPanel } from "./BaselineBenchmarkPanel";

const identity = {
  provider: "openai",
  model: "gpt-5.6-terra",
  prompt_version: "decision-analyst-v5.1-output",
  decision_policy_version: "shadow-tournament-portfolio-v3",
  ai_view_version: "ctx-replay-production-v1"
};

const payload: AiBenchmarkPayload = {
  benchmark_report_version: "ai-benchmark-v1",
  baseline_contract: {
    id: "production-baseline-v1",
    frozen_at_commit: "81698ca175a75dfb08285c3725c98835f616a843",
    prompt_version: identity.prompt_version,
    decision_policy_version: identity.decision_policy_version,
    ai_view_version: "ai-view-v6",
    models_by_provider: { openai: identity.model },
    immutable: true
  },
  methodology: {
    forecast_sample: "FIRST_EVALUABLE_FORECAST_PER_MAP",
    forecast_accuracy: "PREDICT_A_WHEN_FAIR_PROBABILITY_A_GTE_0_5",
    clv_sample: "FIRST_NON_NULL_CLV_PER_MAP",
    abstention_actions: ["NO_BUY", "INSUFFICIENT_DATA"],
    calibration: {
      version: "ece-equal-width-10-v1",
      metric: "EXPECTED_CALIBRATION_ERROR",
      bins: 10,
      binning: "EQUAL_WIDTH_0_TO_1"
    },
    latency: "AI_PROVIDER_HTTP_LATENCY_SECONDS_ALL_ATTEMPTS",
    market_comparison: "VIG_REMOVED_TWO_WAY_PROBABILITY_AT_DECISION_SNAPSHOT",
    significance: "DESCRIPTIVE_ONLY_NO_STATISTICAL_SIGNIFICANCE_CLAIM"
  },
  experiments: [
    {
      experiment: identity,
      observed_model_versions: [identity.model],
      baseline_role: "CHALLENGER",
      samples: {
        attempts: 8,
        successful_decisions: 8,
        parse_success_rate: 1,
        forecast_maps: 8,
        clv_maps: 0,
        market_comparison_maps: 8
      },
      quality: {
        forecast_accuracy: 0.625,
        average_brier_score: 0.21,
        average_log_loss: 0.61,
        calibration_error: 0.1,
        average_clv: null,
        market_brier_improvement: 0.01,
        abstention_rate: 0.5,
        action_counts: { NO_BUY: 4, BUY_A: 4 },
        parse_status_counts: { SUCCESS: 8 }
      },
      latency: { sample_count: 8, average_seconds: 4, p95_seconds: 6 },
      portfolio: {
        event_count: 0,
        realized_roi: null,
        realized_pnl: null,
        worst_event_drawdown_pct: null,
        bet_count: 0
      },
      baseline_reference: null,
      delta_vs_baseline: null,
      context_experiment: {
        ai_view_version: identity.ai_view_version,
        label: "Matched replay production-view control",
        reference_ai_view_version: "ai-view-v6",
        removed_evidence: [],
        schema_aligned_history: false
      },
      context_reference: null,
      delta_vs_context_reference: null
    }
  ]
};

describe("BaselineBenchmarkPanel matched replay control", () => {
  it("labels the pointwise replay control without calling it a schema repair", () => {
    render(
      <BaselineBenchmarkPanel
        data={payload}
        loading={false}
        error={false}
        onRetry={() => undefined}
        locale="zh-CN"
      />
    );

    expect(screen.getByText(/Matched replay production-view control/)).toBeTruthy();
    expect(screen.getByText(/匹配回放生产视图控制/)).toBeTruthy();
    expect(screen.queryByText(/修正历史字段投影/)).toBeNull();
  });
});
