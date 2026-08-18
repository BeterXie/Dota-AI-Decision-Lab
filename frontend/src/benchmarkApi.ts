import type { AiExperimentIdentity } from "./performanceApi";

export interface AiBaselineContract {
  id: string;
  frozen_at_commit: string;
  prompt_version: string;
  decision_policy_version: string;
  ai_view_version: string;
  models_by_provider: Record<string, string>;
  immutable: boolean;
}

export interface AiBenchmarkSamples {
  attempts: number;
  successful_decisions: number;
  parse_success_rate: number | null;
  forecast_maps: number;
  clv_maps: number;
  market_comparison_maps: number;
}

export interface AiBenchmarkQuality {
  forecast_accuracy: number | null;
  average_brier_score: number | null;
  average_log_loss: number | null;
  calibration_error: number | null;
  average_clv: number | null;
  market_brier_improvement: number | null;
  abstention_rate: number | null;
  action_counts: Record<string, number>;
  parse_status_counts: Record<string, number>;
}

export interface AiBenchmarkLatency {
  sample_count: number;
  average_seconds: number | null;
  p95_seconds: number | null;
}

export interface AiBenchmarkPortfolio {
  event_count: number;
  realized_roi: number | null;
  realized_pnl: number | null;
  worst_event_drawdown_pct: number | null;
  bet_count: number;
}

export interface AiBenchmarkDelta {
  forecast_maps: number;
  forecast_accuracy: number | null;
  brier_improvement: number | null;
  log_loss_improvement: number | null;
  calibration_improvement: number | null;
  clv_improvement: number | null;
  market_brier_improvement_delta: number | null;
  abstention_rate_delta: number | null;
  average_latency_improvement_seconds: number | null;
  p95_latency_improvement_seconds: number | null;
  shadow_roi_delta: number | null;
  drawdown_improvement: number | null;
}

export interface AiContextExperimentMetadata {
  ai_view_version: string;
  label: string;
  reference_ai_view_version: string;
  removed_evidence: string[];
  schema_aligned_history: boolean;
}

export interface AiBenchmarkExperiment {
  experiment: AiExperimentIdentity;
  observed_model_versions: string[];
  baseline_role: "BASELINE" | "CHALLENGER";
  samples: AiBenchmarkSamples;
  quality: AiBenchmarkQuality;
  latency: AiBenchmarkLatency;
  portfolio: AiBenchmarkPortfolio;
  baseline_reference: AiExperimentIdentity | null;
  delta_vs_baseline: AiBenchmarkDelta | null;
  context_experiment?: AiContextExperimentMetadata | null;
  context_reference?: AiExperimentIdentity | null;
  delta_vs_context_reference?: AiBenchmarkDelta | null;
}

export interface AiBenchmarkPayload {
  benchmark_report_version: string;
  baseline_contract: AiBaselineContract;
  methodology: {
    forecast_sample: string;
    forecast_accuracy: string;
    clv_sample: string;
    abstention_actions: string[];
    calibration: {
      version: string;
      metric: string;
      bins: number;
      binning: string;
    };
    latency: string;
    market_comparison: string;
    significance: string;
  };
  experiments: AiBenchmarkExperiment[];
}

export async function fetchAiBenchmark(): Promise<AiBenchmarkPayload> {
  const response = await fetch("/api/review/ai-quality/benchmark", {
    cache: "no-store",
    credentials: "same-origin",
    headers: { Accept: "application/json" }
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<AiBenchmarkPayload>;
}
