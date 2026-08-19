import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import type { MapDetail } from "../api";
import { MatchLivePulse } from "./MatchLivePulse";

afterEach(cleanup);

function liveMatch(overrides: Partial<MapDetail> = {}): MapDetail {
  return {
    entity_type: "MAP",
    identity_status: "RESOLVED",
    phase: "LIVE",
    id: "map-1",
    series_id: "series-1",
    canonical_map_id: "map-1",
    map_number: 2,
    valve_match_id: 123,
    scheduled_at: "2026-08-19T12:00:00Z",
    tournament_name: "Test event",
    round: "Group stage",
    raw_status: 1,
    provider_observed_at: "2026-08-19T12:20:00Z",
    team_a: { id: "team-a", name: "Alpha" },
    team_b: { id: "team-b", name: "Bravo" },
    market: [],
    market_quality: null,
    draft: null,
    side_identity: {
      status: "RESOLVED",
      radiant_team_id: "team-b",
      dire_team_id: "team-a",
      source: null,
      confidence: 1,
      observed_at: "2026-08-19T12:00:00Z",
      raw_event_id: null,
      blocker: null
    },
    live: {
      game_time_seconds: 900,
      radiant_kills: 9,
      dire_kills: 7,
      radiant_nw_lead: 4200,
      first_blood: "dire",
      received_at: "2026-08-19T12:15:00Z",
      last_message_received_at: "2026-08-19T12:15:00Z",
      last_state_change_received_at: "2026-08-19T12:14:56Z",
      message_age_seconds: 2,
      effective_state_age_seconds: 6,
      connection_id: null,
      reconnect_generation: 0
    },
    sync: {
      status: "SAFE",
      p50_seconds: 3,
      p90_seconds: 5,
      jitter_seconds: 1,
      sample_size: 10,
      accepted_pair_ratio: 1,
      ambiguous_ratio: 0,
      outlier_ratio: 0,
      confidence: "HIGH",
      calculated_at: "2026-08-19T12:15:00Z"
    },
    latest_snapshot: null,
    decisions: [],
    market_timeline: [],
    live_timeline: [
      { game_time_seconds: 600, radiant_kills: 5, dire_kills: 5, radiant_nw_lead: 1200, first_blood: "dire", received_at: "2026-08-19T12:10:00Z", last_message_received_at: "2026-08-19T12:10:00Z", last_state_change_received_at: "2026-08-19T12:10:00Z", connection_id: null, reconnect_generation: 0 },
      { game_time_seconds: 720, radiant_kills: 6, dire_kills: 6, radiant_nw_lead: 2100, first_blood: "dire", received_at: "2026-08-19T12:12:00Z", last_message_received_at: "2026-08-19T12:12:00Z", last_state_change_received_at: "2026-08-19T12:12:00Z", connection_id: null, reconnect_generation: 0 },
      { game_time_seconds: 900, radiant_kills: 9, dire_kills: 7, radiant_nw_lead: 4200, first_blood: "dire", received_at: "2026-08-19T12:15:00Z", last_message_received_at: "2026-08-19T12:15:00Z", last_state_change_received_at: "2026-08-19T12:15:00Z", connection_id: null, reconnect_generation: 0 }
    ],
    future_odds: [],
    result: null,
    result_evidence: [],
    ...overrides
  } as MapDetail;
}

test("attributes the lead and recent changes through verified map sides", () => {
  render(<MatchLivePulse match={liveMatch()} locale="zh-CN" />);

  expect(screen.getByText("Bravo 领先")).toBeInTheDocument();
  expect(screen.getByText("Bravo +3k")).toBeInTheDocument();
  expect(screen.getByText("新增击杀 2 : 4")).toBeInTheDocument();
  expect(screen.getAllByText("Alpha")).toHaveLength(2);
  expect(screen.getByText("数据正常")).toBeInTheDocument();
});

test("separates connection freshness from stale effective state", () => {
  const match = liveMatch();
  match.live = { ...match.live!, message_age_seconds: 3, effective_state_age_seconds: 134 };
  render(<MatchLivePulse match={match} locale="zh-CN" liveMaxAgeSeconds={120} />);

  expect(screen.getByText("显示最后确认值")).toBeInTheDocument();
  expect(screen.getByText("3 秒前")).toBeInTheDocument();
  expect(screen.getByText("2 分 14 秒前")).toBeInTheDocument();
});

test("uses provider-neutral user-facing copy", () => {
  const { container } = render(<MatchLivePulse match={liveMatch()} locale="zh-CN" />);
  expect(container.textContent?.toLowerCase()).not.toMatch(/dltv|raybet/);
});
