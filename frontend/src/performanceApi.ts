export interface AiExperimentIdentity {
  provider: string;
  model: string;
  prompt_version: string;
  decision_policy_version: string;
  ai_view_version: string;
}

export interface AiEventBreakdown {
  canonical_event_id: string;
  event_name: string;
  started_at: string | null;
  ended_at: string | null;
  initial_bankroll: number;
  equity: number;
  realized_pnl: number;
  realized_roi: number | null;
  max_drawdown_pct: number;
  status: string;
}

export interface AiLeaderboardExperiment {
  rank: number;
  experiment: AiExperimentIdentity;
  event_count: number;
  total_initial_bankroll: number;
  cash_balance: number;
  locked_balance: number;
  equity: number;
  realized_pnl: number;
  realized_roi: number;
  profitable_events: number;
  losing_events: number;
  flat_events: number;
  profitable_event_rate: number;
  bankrupt_events: number;
  worst_event_drawdown_pct: number;
  bet_count: number;
  open_bet_count: number;
  rejected_bet_count: number;
  wins: number;
  losses: number;
  hit_rate: number | null;
  turnover: number;
  profit_factor: number | null;
  events: AiEventBreakdown[];
}

export interface AiLeaderboardPayload {
  scope: string;
  ranking: string;
  experiments: AiLeaderboardExperiment[];
}

export interface AiReadinessStage {
  key: string;
  label: string;
  count: number;
  rate: number | null;
  drop_count: number;
}

export interface AiReadinessFailureReason {
  stage: string;
  reason: string;
  count: number;
  rate: number;
}

export interface AiReadinessSeries {
  canonical_series_id: string;
  canonical_event_id: string | null;
  event_name: string | null;
  scheduled_at: string;
  team_a: { id: string; name: string };
  team_b: { id: string; name: string };
  best_of: number | null;
  current_stage: string;
  blocker: { stage: string; reason: string } | null;
  facts: Record<string, boolean>;
  counts: {
    maps: number;
    live_maps: number;
    snapshots: number;
    successful_decision_snapshots: number;
    result_maps: number;
    evaluated_snapshots: number;
  };
  ai_status_counts: Record<string, number>;
}

export interface AiReadinessPayload {
  report_version: string;
  generated_at: string;
  window: {
    from: string;
    to: string;
    lookback_hours: number;
    future_series_included: boolean;
  };
  scope: {
    source: string;
    series_count: number;
    series_limit: number;
  };
  stages: AiReadinessStage[];
  failure_reasons: AiReadinessFailureReason[];
  series: AiReadinessSeries[];
}

export interface AiQualityGate {
  mode: "SHADOW_ONLY" | string;
  status: "PASS" | "FAIL" | "INSUFFICIENT_SAMPLE" | string;
  failures: string[];
}

export interface AiQualityPolicy {
  min_settled_maps: number;
  min_settled_bets: number;
  min_prediction_samples: number;
  min_clv_samples: number;
  min_market_comparison_samples: number;
  min_roi: number;
  min_average_clv: number;
  min_brier_improvement_vs_market: number;
  max_drawdown_pct: number;
}

export interface AiQualityMetrics {
  sample_policy: {
    prediction: string;
    clv: string;
    portfolio: string;
  };
  settled_maps: number;
  successful_decisions: number;
  action_counts: Record<string, number>;
  prediction_sample_count: number;
  average_brier_score: number | null;
  average_log_loss: number | null;
  average_clv: number | null;
  clv_sample_count: number;
  market_comparison: {
    sample_count: number;
    market_average_brier_score: number | null;
    ai_average_brier_score: number | null;
    brier_improvement_vs_market: number | null;
    market_average_log_loss: number | null;
    ai_average_log_loss: number | null;
    log_loss_improvement_vs_market: number | null;
  };
  decision_level: {
    prediction_sample_count: number;
    average_brier_score: number | null;
    average_log_loss: number | null;
    average_clv: number | null;
    clv_sample_count: number;
  };
  average_stake_pct_of_available_cash: number | null;
  largest_stake_pct_of_available_cash: number | null;
  longest_losing_streak: number;
  risk_adjusted_return_over_max_drawdown: number | null;
}

export interface AiPortfolioMetrics {
  account_id: string;
  canonical_event_id: string;
  experiment: AiExperimentIdentity;
  initial_bankroll: number;
  cash_balance: number;
  locked_balance: number;
  equity: number;
  realized_pnl: number;
  roi: number | null;
  peak_equity: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  bet_count: number;
  open_bet_count: number;
  rejected_bet_count: number;
  wins: number;
  losses: number;
  hit_rate: number | null;
  turnover: number;
  profit_factor: number | null;
  status: string;
}

export interface AiEquityPoint {
  occurred_at: string;
  entry_type: string;
  equity: number;
  cash: number;
  locked: number;
  realized_pnl_delta: number;
}

export interface AiLatencyHorizon {
  sample_count: number;
  actionable_count: number;
  actionable_rate: number | null;
  average_model_edge_vs_break_even: number | null;
  average_odds_slippage_pct: number | null;
  average_observed_after_ai_seconds: number | null;
}

export interface AiExecutionLatency {
  source: string;
  position_policy: string;
  interpretation: string;
  pre_response_capture_count: number;
  invalid_pair_capture_count: number;
  horizons: Record<string, AiLatencyHorizon>;
}

export interface AiEventQualityExperiment {
  experiment: AiExperimentIdentity;
  portfolio: AiPortfolioMetrics;
  quality: AiQualityMetrics;
  execution_latency: AiExecutionLatency;
  gate: AiQualityGate;
  equity_curve: AiEquityPoint[];
}

export interface AiEventQualityPayload {
  quality_report_version: string;
  gate_mode: string;
  canonical_event_id: string;
  policy: AiQualityPolicy;
  experiments: AiEventQualityExperiment[];
}

export interface AiPositionAudit {
  id: string;
  ai_decision_id: string;
  canonical_series_id: string;
  canonical_map_id: string;
  map_number: number | null;
  action: string;
  team_a: { id: string; name: string };
  team_b: { id: string; name: string };
  selected_team: { id: string; name: string } | null;
  cash_before: number;
  stake: number;
  odds: number | null;
  status: string;
  rejection_reason: string | null;
  payout: number | null;
  realized_pnl: number | null;
  opened_at: string;
  settled_at: string | null;
}

export interface AiPositionAuditPayload {
  canonical_event_id: string;
  account_id: string;
  experiment: AiExperimentIdentity;
  positions: AiPositionAudit[];
}

export async function fetchAiLeaderboard(): Promise<AiLeaderboardPayload> {
  return fetchJson("/api/review/ai-quality/leaderboard");
}

export async function fetchAiReadiness(lookbackHours = 168): Promise<AiReadinessPayload> {
  const query = new URLSearchParams({ lookback_hours: String(lookbackHours) });
  return fetchJson(`/api/review/ai-quality/readiness?${query.toString()}`);
}

export async function fetchAiEventQuality(eventId: string): Promise<AiEventQualityPayload> {
  return fetchJson(`/api/review/events/${encodeURIComponent(eventId)}/ai-quality`);
}

export async function fetchAiPositionAudit(
  eventId: string,
  accountId: string
): Promise<AiPositionAuditPayload> {
  const query = new URLSearchParams({ account_id: accountId });
  return fetchJson(
    `/api/review/events/${encodeURIComponent(eventId)}/ai-quality/positions?${query.toString()}`
  );
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    cache: "no-store",
    credentials: "same-origin",
    headers: { Accept: "application/json" }
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}
