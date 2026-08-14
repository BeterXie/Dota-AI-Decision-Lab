import { describe, expect, test } from "vitest";

import type { MapDetail } from "../api";
import { resolveDecisionLiveFreshness } from "./liveFreshness";

function detailWithFreshness(
  freshness: Record<string, unknown>,
  overrides: Partial<MapDetail["live"]> = {}
): MapDetail {
  return {
    entity_type: "MAP",
    identity_status: "RESOLVED",
    phase: "LIVE",
    id: "map-1",
    series_id: "series-1",
    canonical_map_id: "map-1",
    map_number: 1,
    valve_match_id: 123,
    scheduled_at: null,
    provider_match_id: 456,
    tournament_name: "Fixture",
    round: "bo3",
    raw_status: 1,
    provider_observed_at: "2026-08-14T00:00:00Z",
    team_a: { id: "team-a", name: "Alpha" },
    team_b: { id: "team-b", name: "Bravo" },
    market: [],
    market_quality: null,
    draft: null,
    live: {
      game_time_seconds: 600,
      radiant_kills: 10,
      dire_kills: 8,
      radiant_nw_lead: 2400,
      first_blood: "radiant",
      received_at: "2026-08-14T00:10:00Z",
      last_message_received_at: "2026-08-14T00:10:00Z",
      last_state_change_received_at: "2026-08-14T00:10:00Z",
      message_age_seconds: 5,
      effective_state_age_seconds: 1,
      connection_id: "connection-1",
      reconnect_generation: 1,
      ...overrides
    },
    sync: null,
    latest_snapshot: null,
    decisions: [],
    market_timeline: [],
    live_timeline: [],
    snapshot_payload: {
      quality: {
        live_field_freshness: freshness
      }
    },
    future_odds: [],
    result: null,
    result_evidence: []
  };
}

describe("resolveDecisionLiveFreshness", () => {
  test("prefers immutable field evidence over the legacy shared state age", () => {
    const detail = detailWithFreshness({
      complete: true,
      observed_at: {
        game_time_seconds: "2026-08-14T00:10:00Z",
        radiant_kills: "2026-08-14T00:09:30Z",
        dire_kills: "2026-08-14T00:09:40Z",
        radiant_nw_lead: "2026-08-14T00:09:20Z"
      },
      ages_seconds: {
        game_time_seconds: 0,
        radiant_kills: 30,
        dire_kills: 20,
        radiant_nw_lead: 40
      }
    });

    const resolved = resolveDecisionLiveFreshness(detail, Date.parse("2030-01-01T00:00:00Z"));

    expect(resolved.source).toBe("SNAPSHOT_FIELD_EVIDENCE");
    expect(resolved.complete).toBe(true);
    expect(resolved.effectiveAgeSeconds).toBe(45);
    expect(resolved.effectiveAgeSeconds).not.toBe(detail.live?.effective_state_age_seconds);
  });

  test("uses the API server reference time instead of the browser clock", () => {
    const detail = detailWithFreshness({
      complete: true,
      observed_at: {
        game_time_seconds: "2026-08-14T00:09:58Z",
        radiant_kills: "2026-08-14T00:09:55Z",
        dire_kills: "2026-08-14T00:09:57Z",
        radiant_nw_lead: "2026-08-14T00:09:50Z"
      }
    });

    const resolved = resolveDecisionLiveFreshness(detail, Date.parse("2030-01-01T00:00:00Z"));

    expect(resolved.agesSeconds.game_time_seconds).toBe(7);
    expect(resolved.agesSeconds.radiant_kills).toBe(10);
    expect(resolved.agesSeconds.dire_kills).toBe(8);
    expect(resolved.agesSeconds.radiant_nw_lead).toBe(15);
    expect(resolved.effectiveAgeSeconds).toBe(15);
  });

  test("does not produce an effective age when required field evidence is incomplete", () => {
    const detail = detailWithFreshness({
      complete: false,
      observed_at: {
        game_time_seconds: "2026-08-14T00:10:00Z",
        radiant_kills: "2026-08-14T00:09:59Z",
        dire_kills: "2026-08-14T00:09:59Z"
      },
      ages_seconds: {
        game_time_seconds: 0,
        radiant_kills: 1,
        dire_kills: 1
      }
    });

    const resolved = resolveDecisionLiveFreshness(detail);

    expect(resolved.complete).toBe(false);
    expect(resolved.effectiveAgeSeconds).toBeNull();
    expect(resolved.agesSeconds.radiant_nw_lead).toBeUndefined();
  });
});
