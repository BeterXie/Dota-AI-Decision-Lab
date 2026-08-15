export interface ReviewTeam {
  id: string;
  name: string;
}

export interface ReviewRoshEdge {
  edge_pp: number | null;
  favored_team_id: string | null;
  correct: boolean | null;
}

export interface ReviewRoshPoint {
  minute: number;
  pure: ReviewRoshEdge;
  adjusted: ReviewRoshEdge;
}

export interface ReviewRosh {
  snapshot_id: string;
  decision_at: string;
  reference_minute: number;
  model_version: string | null;
  data_version: string | null;
  radiant_team_id: string;
  dire_team_id: string;
  points: ReviewRoshPoint[];
  reference: ReviewRoshPoint | null;
}

export interface ReviewAiLatest {
  snapshot_id: string;
  decision_at: string;
  action: string | null;
  fair_probability_a: number | null;
  confidence: number | null;
  market_assessment: string | null;
}

export interface ReviewAiGroup {
  provider: string;
  model: string;
  rounds: number;
  buy_decisions: number;
  settled_buy_decisions: number;
  correct_buy_decisions: number;
  buy_accuracy: number | null;
  average_brier: number | null;
  average_log_loss: number | null;
  unit_pnl: number | null;
  unit_bets: number;
  unit_roi: number | null;
  latest: ReviewAiLatest | null;
}

export interface ReviewOddsPair {
  odds_a: number;
  odds_b: number;
  fair_probability_a: number | null;
  fair_probability_b: number | null;
  observed_at: string;
}

export interface ReviewOdds {
  start: ReviewOddsPair;
  end: ReviewOddsPair;
  end_kind: "CLOSING" | "LATEST_DECISION";
  team_a_fair_probability_change_pp: number | null;
}

export interface ReviewMatch {
  canonical_map_id: string;
  series_id: string;
  map_number: number | null;
  valve_match_id: number | null;
  scheduled_at: string | null;
  settled_at: string;
  tournament_name: string | null;
  team_a: ReviewTeam;
  team_b: ReviewTeam;
  winner_team_id: string;
  rosh: ReviewRosh | null;
  ai: ReviewAiGroup[];
  odds: ReviewOdds | null;
}

export interface ReviewRateSummary {
  evaluated: number;
  correct: number;
  accuracy: number | null;
}

export interface ReviewPayload {
  summary: {
    settled_maps: number;
    rosh: {
      reference_minute: number;
      pure: ReviewRateSummary;
      adjusted: ReviewRateSummary;
    };
    ai: ReviewAiGroup[];
    odds: {
      eligible_maps: number;
      closing_captured: number;
      closing_coverage: number | null;
    };
  };
  matches: ReviewMatch[];
  methodology: {
    rosh_reference_minute: number;
    rosh_review_minutes: number[];
    rosh_source: string;
    ai_round_rule: string;
    odds_start: string;
    odds_end: string;
  };
}

export async function fetchReviewMatches(limit = 100): Promise<ReviewPayload> {
  const response = await fetch(`/api/review/matches?limit=${limit}`, {
    cache: "no-store",
    headers: { Accept: "application/json" }
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<ReviewPayload>;
}
