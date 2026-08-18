import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AiBenchmarkPayload } from "../benchmarkApi";
import { BaselineBenchmarkPanel } from "./BaselineBenchmarkPanel";

const identity = {
  provider: "openai",
  model: "gpt-5.6-terra",
  prompt_version: "decision-analyst-v5.1-output",
  decision_policy_version: "shadow-tournament-portfolio-v3",
  ai_view_version: "ai-view-v6"
};

const payload: AiBenchmarkPayload = {
  benchmark_report_version: "ai-benchmark-v1",
  baseline_contract: {
    id: "production-baseline-v1",
    frozen_at_commit: "81698ca175a75dfb08285c3725c98835f616a843",
    prompt_version: identity.prompt_version,
    decision_policy_version: identity.decision_policy_version,
    ai_view_version: identity.ai_view_version,
    models_by_provider: { openai: identity.model, gemini: "gemini-3.6-flash" },
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
      baseline_role: "BASELINE",
      samples: { attempts: 30, successful_decisions: 29, parse_success_rate: 29 / 30, forecast_maps: 20, clv_maps: 10, market_comparison_maps: 18 },
      quality: {
        forecast_accuracy: 0.6,
        average_brier_score: 0.21,
        average_log_loss: 0.59,
        calibration_error: 0.12,
        average_clv: 0.01,
        market_brier_improvement: 0.015,
        abstention_rate: 0.45,
        action_counts: { BUY_A: 8, BUY_B: 8, NO_BUY: 13 },
        parse_status_counts: { SUCCESS: 29, PARSE_FAILED: 1 }
      },
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
      quality: {
        forecast_accuracy: 0.7,
        average_brier_score: 0.18,
        average_log_loss: 0.52,
        calibration_error: 0.08,
        average_clv: 0.025,
        market_brier_improvement: 0.03,
        abstention_rate: 0.35,
        action_counts: { BUY_A: 9, BUY_B: 9, NO_BUY: 10 },
        parse_status_counts: { SUCCESS: 28 }
      },
      latency: { sample_count: 28, average_seconds: 3.5, p95_seconds: 6.2 },
      portfolio: { event_count: 2, realized_roi: 0.08, realized_pnl: 1600, worst_event_drawdown_pct: 0.1, bet_count: 18 },
      baseline_reference: identity,
      delta_vs_baseline: {
        forecast_maps: 0,
        forecast_accuracy: 0.1,
        brier_improvement: 0.03,
        log_loss_improvement: 0.07,
        calibration_improvement: 0.04,
        clv_improvement: 0.015,
        market_brier_improvement_delta: 0.015,
        abstention_rate_delta: -0.1,
        average_latency_improvement_seconds: 0.7,
        p95_latency_improvement_seconds: 1.6,
        shadow_roi_delta: 0.04,
        drawdown_improvement: 0.02
      }
    },
    {
      experiment: { ...identity, provider: "gemini", model: "gemini-3.6-flash" },
      observed_model_versions: ["gemini-3.6-flash"],
      baseline_role: "BASELINE",
      samples: { attempts: 10, successful_decisions: 10, parse_success_rate: 1, forecast_maps: 8, clv_maps: 3, market_comparison_maps: 8 },
      quality: { forecast_accuracy: 0.5, average_brier_score: 0.24, average_log_loss: 0.68, calibration_error: 0.14, average_clv: 0, market_brier_improvement: -0.01, abstention_rate: 0.5, action_counts: {}, parse_status_counts: { SUCCESS: 10 } },
      latency: { sample_count: 10, average_seconds: 2, p95_seconds: 3 },
      portfolio: { event_count: 1, realized_roi: 0, realized_pnl: 0, worst_event_drawdown_pct: 0.05, bet_count: 3 },
      baseline_reference: null,
      delta_vs_baseline: null
    }
  ]
};

describe("BaselineBenchmarkPanel", () => {
  it("shows the frozen contract, challenger deltas and provider filtering", () => {
    render(<BaselineBenchmarkPanel data={payload} loading={false} error={false} onRetry={() => undefined} locale="zh-CN" />);

    expect(screen.getByText("AI 基线 Benchmark")).toBeTruthy();
    expect(screen.getByText("production-baseline-v1")).toBeTruthy();
    expect(screen.getAllByText("BASELINE").length).toBeGreaterThan(0);
    expect(screen.getByText("CHALLENGER")).toBeTruthy();
    expect(screen.getByText("相对基线改善")).toBeTruthy();
    expect(screen.getByText("+10%")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "gemini" }));

    expect(screen.getByText("gemini · gemini-3.6-flash")).toBeTruthy();
    expect(screen.queryByText("CHALLENGER")).toBeNull();
  });
});
