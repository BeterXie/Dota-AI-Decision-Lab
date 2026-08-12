import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

export interface WorkerHealth {
  name: string;
  state: string;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_message_at: string | null;
  consecutive_failures: number;
  last_error: string | null;
  messages_received: number;
  restart_count: number;
  metadata: Record<string, unknown>;
}

export interface DependencyHealth {
  name: string;
  status: string;
  message: string | null;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_message_at: string | null;
  age_seconds: number | null;
  consecutive_failures: number;
  last_error: string | null;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface RuntimeSnapshot {
  overall: "READY" | "DEGRADED" | "ACTION_REQUIRED";
  workers: Record<string, WorkerHealth>;
  dependencies: Record<string, DependencyHealth>;
  observed_at: string;
}

export interface MarketObservation {
  odds_id: number;
  selection_team_id: string | null;
  price: number | string;
  fair_probability: number | null;
  raw_status: number | null;
  normalized_status: string | null;
  metadata_version: string | null;
  market_type: string | null;
  match_stage: string | null;
  provider_updated_at?: string | null;
  received_at: string;
  age_seconds: number;
}

export interface MarketQuality {
  eligible: boolean;
  blockers: string[];
  warnings: string[];
  metadata_version: string | null;
  paired_at: string;
  pair_skew_seconds: number | null;
}

export interface DraftPoint {
  minute: number;
  pure_radiant_edge: number | null;
  adjusted_radiant_edge: number | null;
  support: number | null;
  confidence: number | null;
}

export interface LiveObservation {
  game_time_seconds: number | null;
  radiant_kills: number | null;
  dire_kills: number | null;
  radiant_nw_lead: number | null;
  received_at: string;
  last_message_received_at: string;
  last_state_change_received_at: string;
  message_age_seconds?: number;
  effective_state_age_seconds?: number;
  connection_id: string | null;
  reconnect_generation: number;
}

export interface AiDecision {
  id: string;
  provider: string;
  model: string;
  model_version: string;
  prompt_version: string;
  decision_policy_version: string;
  snapshot_hash: string;
  request_started_at: string;
  response_received_at: string | null;
  parse_status: string;
  latency_seconds: number | null;
  decision: {
    action?: string;
    confidence?: number;
    fair_probability_a?: number | null;
    primary_reasons?: string[];
    counter_arguments?: string[];
    data_quality_concerns?: string[];
    blockers?: string[];
  } | null;
  error: string | null;
}

export interface MapSummary {
  entity_type: "MAP" | "SERIES";
  identity_status: "RESOLVED" | "PENDING_MAP_IDENTITY";
  id: string;
  series_id: string;
  canonical_map_id: string | null;
  map_number: number | null;
  valve_match_id: number | null;
  scheduled_at: string | null;
  provider_match_id: number | null;
  tournament_name: string | null;
  round: string | null;
  raw_status: number | null;
  provider_observed_at: string | null;
  team_a: { id: string; name: string } | null;
  team_b: { id: string; name: string } | null;
  market: MarketObservation[];
  market_quality: MarketQuality | null;
  draft: {
    complete: boolean;
    blockers: string[];
    warnings: string[];
    observed_at: string;
    statistics_cutoff: string;
    features: Record<string, unknown> | null;
    curve?: DraftPoint[];
    model_version?: string;
    data_version?: string;
  } | null;
  live: LiveObservation | null;
  sync: {
    status: string;
    p50_seconds: number | null;
    p90_seconds: number | null;
    jitter_seconds: number | null;
    sample_size: number;
    accepted_pair_ratio: number;
    ambiguous_ratio: number;
    outlier_ratio: number;
    confidence: string;
    calculated_at: string;
  } | null;
  latest_snapshot: {
    id: string;
    decision_at: string;
    created_at: string;
    mode: string;
    snapshot_hash: string;
    market_quality: MarketQuality | null;
    history_coverage: Record<string, unknown> | null;
    quality: {
      eligible?: boolean;
      blockers?: string[];
      warnings?: string[];
    } | null;
  } | null;
  decisions: AiDecision[];
  historical_prewarm?: {
    team_strength_ready_count: number;
    player_form_ready_count: number;
    player_hero_ready_count: number;
    latest_knowledge_cutoff: string | null;
  };
}

export interface MapDetail extends MapSummary {
  market_timeline: MarketObservation[];
  live_timeline: LiveObservation[];
  snapshot_payload?: {
    history?: Record<string, unknown>;
    quality?: Record<string, unknown>;
  };
  future_odds: FutureOddsCapture[];
  result: {
    winner_team_id: string | null;
    basic_first_usable_at: string;
    advanced_first_usable_at: string | null;
    settled_at: string;
    provider_conflict: boolean;
  } | null;
  result_evidence: ResultEvidence[];
}

export interface FutureOddsCapture {
  id: string;
  capture_type: "TIME_HORIZON" | "CLOSING";
  horizon_seconds: number | null;
  triggered_at: string;
  due_at: string;
  observed_at: string | null;
  odds_a: number | string | null;
  odds_b: number | string | null;
  market_type: string | null;
  match_stage: string | null;
  market_status: string | null;
  capture_policy_version: string;
  pair_quality: Partial<MarketQuality>;
  pair_skew_seconds: number | null;
  status: string;
}

export interface ResultEvidence {
  id: string;
  provider: string;
  provider_match_id: string;
  winner_team_id: string | null;
  result_observed_at: string;
  first_usable_at: string;
  raw_event_id: string;
  normalizer_version: string;
  identity_confidence: number;
  conflict_status: string;
}

export interface JobSummary {
  by_status: Record<string, number>;
  by_type: Array<{ job_type: string; status: string; count: number }>;
  oldest_pending_at: string | null;
  recent_failures: Array<{
    id: string;
    job_type: string;
    dedupe_key: string;
    attempt_count: number;
    last_error: string | null;
    completed_at: string | null;
  }>;
}

export const queryKeys = {
  runtime: ["runtime"] as const,
  maps: ["maps"] as const,
  map: (id: string) => ["map", id] as const,
  jobs: ["jobs"] as const
};

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    cache: "no-store",
    headers: { Accept: "application/json" }
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const fetchRuntime = () => getJson<RuntimeSnapshot>("/api/runtime");
export const fetchMaps = () => getJson<MapSummary[]>("/api/matches");
export const fetchMap = (id: string) => getJson<MapDetail>(`/api/maps/${id}`);
export const fetchJobs = () => getJson<JobSummary>("/api/jobs/summary");

export function useRuntimeSocket(): void {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (typeof window.WebSocket !== "function") return;
    let socket: WebSocket | null = null;
    let retry: number | null = null;
    let closed = false;
    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(`${protocol}//${window.location.host}/ws/status`);
      socket.onmessage = (event) => {
        queryClient.setQueryData(queryKeys.runtime, JSON.parse(event.data));
      };
      socket.onclose = () => {
        if (!closed) retry = window.setTimeout(connect, 2000);
      };
    };
    connect();
    return () => {
      closed = true;
      if (retry !== null) window.clearTimeout(retry);
      socket?.close();
    };
  }, [queryClient]);
}
