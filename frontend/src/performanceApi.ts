export interface PerformanceSummary {
  attempts: number;
  successful: number;
  success_rate: number | null;
  evaluated: number;
  settled_buy_decisions: number;
  correct_buy_decisions: number;
  buy_accuracy: number | null;
  average_brier: number | null;
  average_log_loss: number | null;
  unit_pnl: number | null;
  unit_bets: number;
  unit_roi: number | null;
  experiment_count: number;
}

export interface PerformanceExperiment {
  id: string;
  provider: string;
  model: string;
  model_version: string;
  prompt_version: string;
  decision_policy_version: string;
  ai_view_version: string;
  attempts: number;
  successful: number;
  failed: number;
  success_rate: number | null;
  evaluated: number;
  buy_decisions: number;
  settled_buy_decisions: number;
  correct_buy_decisions: number;
  buy_accuracy: number | null;
  average_brier: number | null;
  average_log_loss: number | null;
  unit_pnl: number | null;
  unit_bets: number;
  unit_roi: number | null;
  average_latency_seconds: number | null;
  p95_latency_seconds: number | null;
  average_end_to_end_seconds: number | null;
  average_total_tokens: number | null;
  cached_input_ratio: number | null;
  last_decision_at: string;
}

export interface PerformanceTeam {
  id: string;
  name: string;
}

export interface PerformanceMatchContext {
  map_number: number | null;
  valve_match_id: number | null;
  tournament_name: string | null;
  team_a: PerformanceTeam | null;
  team_b: PerformanceTeam | null;
}

export interface PerformanceLatencyTrace {
  job_enqueued_at: string | null;
  job_claimed_at: string | null;
  input_prepare_started_at: string | null;
  input_prepare_completed_at: string | null;
  request_started_at: string;
  response_received_at: string | null;
  decision_persisted_at: string | null;
  provider_latency_seconds: number | null;
  queue_seconds: number | null;
  input_prepare_seconds: number | null;
  end_to_end_seconds: number | null;
}

export interface PerformanceTokens {
  input: number | null;
  cached_input: number | null;
  reasoning: number | null;
  output: number | null;
  total: number | null;
}

export interface PerformanceEvaluation {
  result_correct: boolean | null;
  brier_score: number | null;
  log_loss: number | null;
  clv: number | null;
  future_odds_direction: string | null;
  virtual_pnl: number | null;
  virtual_odds: number | null;
  unit_pnl: number | null;
  evaluated_at: string;
  metrics_version: string;
}

export interface PerformanceDecision {
  id: string;
  experiment_id: string;
  snapshot_id: string;
  canonical_map_id: string | null;
  match: PerformanceMatchContext | null;
  decision_at: string;
  mode: string | null;
  snapshot_hash: string;
  ai_input_hash: string | null;
  provider: string;
  model: string;
  model_version: string;
  prompt_version: string;
  decision_policy_version: string;
  ai_view_version: string;
  parse_status: string;
  error: string | null;
  action: string | null;
  fair_probability_a: number | null;
  confidence: number | null;
  market_assessment: string | null;
  primary_reasons: string[];
  blockers: string[];
  bankroll_before: number | null;
  stake: number | null;
  trace: PerformanceLatencyTrace;
  tokens: PerformanceTokens;
  evaluation: PerformanceEvaluation | null;
}

export interface PerformanceMethodology {
  query_limit: number;
  experiment_identity: string[];
  comparison_rule: string;
  buy_accuracy: string;
  probability_quality: string;
  unit_roi: string;
  audit_identity: string;
  source: string;
  no_future_leakage: boolean;
}

export interface PerformancePayload {
  summary: PerformanceSummary;
  experiments: PerformanceExperiment[];
  decisions: PerformanceDecision[];
  methodology: PerformanceMethodology;
}

export async function fetchAiPerformance(limit = 1000): Promise<PerformancePayload> {
  const response = await fetch(`/api/ai-performance?limit=${limit}`, {
    cache: "no-store",
    credentials: "same-origin",
    headers: { Accept: "application/json" }
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<PerformancePayload>;
}
