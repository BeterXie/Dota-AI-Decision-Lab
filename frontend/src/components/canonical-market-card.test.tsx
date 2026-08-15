import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import type { MapSummary } from "../api";
import { I18nProvider } from "../i18n";
import { CanonicalMarketCard } from "./CanonicalMarketCard";

afterEach(() => {
  cleanup();
});

function marketFixture(phase: MapSummary["phase"]): MapSummary {
  return {
    entity_type: "MAP",
    identity_status: "RESOLVED",
    phase,
    id: "map-1",
    series_id: "series-1",
    canonical_map_id: "map-1",
    map_number: 1,
    valve_match_id: 101,
    scheduled_at: "2026-08-15T10:42:00Z",
    provider_match_id: 38426143,
    tournament_name: null,
    round: "bo3",
    raw_status: 1,
    provider_observed_at: "2026-08-15T10:42:00Z",
    team_a: { id: "team-a", name: "BoomBoys" },
    team_b: { id: "team-b", name: "Team Falcons" },
    market: [
      {
        odds_id: 75345547,
        selection_team_id: "team-a",
        price: "1.22",
        fair_probability: null,
        raw_status: 1,
        normalized_status: "UNKNOWN",
        metadata_version: "v1",
        market_type: "Winner",
        match_stage: "r1",
        received_at: "2026-08-15T11:34:13Z",
        age_seconds: 900
      },
      {
        odds_id: 75345548,
        selection_team_id: "team-b",
        price: "3.99",
        fair_probability: null,
        raw_status: 1,
        normalized_status: "UNKNOWN",
        metadata_version: "v1",
        market_type: "Winner",
        match_stage: "r1",
        received_at: "2026-08-15T11:34:13Z",
        age_seconds: 900
      }
    ],
    market_quality: {
      eligible: false,
      blockers: ["MARKET_PAIR_STALE_LEG"],
      warnings: ["MARKET_STATUS_UNKNOWN"],
      metadata_version: "v1",
      paired_at: "2026-08-15T11:34:13Z",
      pair_skew_seconds: 0
    },
    draft: null,
    live: null,
    sync: null,
    latest_snapshot: null,
    decisions: []
  } as unknown as MapSummary;
}

test("labels a POSTMATCH winner market as closed with closing odds", () => {
  window.localStorage.clear();
  window.localStorage.setItem("dota-ai-decision-lab-locale", "en");

  render(
    <I18nProvider>
      <CanonicalMarketCard match={marketFixture("POSTMATCH")} />
    </I18nProvider>
  );

  expect(screen.getByText("CLOSED")).toBeInTheDocument();
  expect(screen.getByText("Map finished · closing odds shown.")).toBeInTheDocument();
  expect(screen.getByText("1.22")).toBeInTheDocument();
  expect(screen.getByText("3.99")).toBeInTheDocument();
});

test("labels an AWAITING_RESULT winner market as closed in Chinese", () => {
  window.localStorage.clear();
  window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN");

  render(
    <I18nProvider>
      <CanonicalMarketCard match={marketFixture("AWAITING_RESULT")} />
    </I18nProvider>
  );

  expect(screen.getByText("已停盘")).toBeInTheDocument();
  expect(screen.getByText("盘口已停盘 · 等待赛果确认。")).toBeInTheDocument();
});
