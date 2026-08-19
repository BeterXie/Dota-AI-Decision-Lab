import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test } from "vitest";
import type { MapDetail } from "../api";
import { I18nProvider } from "../i18n";
import { LineupCard } from "./LineupCard";
import { PlayerDraftAdvantageCard } from "./PlayerDraftAdvantageCard";

const match = {
  phase: "LIVE",
  tournament_name: "Side Identity Fixture",
  round: "bo3",
  map_number: 2,
  team_a: { id: "team-a", name: "Alpha" },
  team_b: { id: "team-b", name: "Bravo" },
  market: [],
  market_quality: null,
  decisions: [],
  latest_snapshot: {
    mode: "LIVE_BASIC"
  },
  draft: {
    complete: true,
    features: {
      current_edge: 3.2,
      next_5m_edge: 2.4,
      peak_edge: 4.5,
      peak_minute: 35,
      cross_over_minute: null
    },
    curve: [
      { minute: 20, pure_radiant_edge: 2.8, adjusted_radiant_edge: 3.2, support: 100, confidence: 0.8 },
      { minute: 35, pure_radiant_edge: 4.0, adjusted_radiant_edge: 4.5, support: 90, confidence: 0.75 }
    ],
    slots: [
      { side: "radiant", position: 1, player_name: "Bravo Carry", hero_name: "Morphling" },
      { side: "dire", position: 1, player_name: "Alpha Carry", hero_name: "Anti-Mage" }
    ]
  },
  live: {
    game_time_seconds: 1320,
    radiant_kills: 10,
    dire_kills: 8,
    radiant_nw_lead: 2000,
    first_blood: "radiant",
    effective_state_age_seconds: 2,
    message_age_seconds: 1
  },
  sync: { status: "SAFE" },
  snapshot_payload: {
    identity: {
      side_identity: {
        status: "RESOLVED",
        radiant_team_id: "team-b",
        dire_team_id: "team-a",
        source: "DLTV_DB_IS_RADIANT",
        confidence: 1,
        observed_at: "2026-08-13T12:00:00Z",
        raw_event_id: "raw-side-fixture",
        blocker: null
      }
    }
  }
} as MapDetail;

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
});

function withI18n(node: React.ReactNode) {
  return render(<I18nProvider>{node}</I18nProvider>);
}

test("R.O.S.H. attributes positive radiant edge to the verified radiant team", () => {
  withI18n(<PlayerDraftAdvantageCard match={match} />);

  expect(screen.getByText("Bravo · Radiant advantage")).toBeInTheDocument();
  expect(screen.getByText("Bravo · Radiant +3.2pp")).toBeInTheDocument();
  expect(screen.queryByText("Alpha advantage")).not.toBeInTheDocument();
});

test("lineup uses the verified side mapping", () => {
  withI18n(<LineupCard match={match} />);

  expect(screen.getByText("Bravo · RADIANT")).toBeInTheDocument();
  expect(screen.getByText("Alpha · DIRE")).toBeInTheDocument();
});
